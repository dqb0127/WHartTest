"""
Agent Loop 流式 API 视图

基于 Agent Loop 架构实现流式聊天，解决 Token 累积问题。
"""
import asyncio
import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from langchain_core.messages import SystemMessage
from asgiref.sync import sync_to_async

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage, AnyMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from .context_compression import ConversationCompressor, CompressionSettings
from requirements.context_limits import context_checker, RESERVED_TOKENS

from .agent_loop import AgentOrchestrator
from .models import AgentTask, AgentBlackboard
from langgraph_integration.models import ChatSession, LLMConfig
from langgraph_integration.views import (
    create_llm_instance,
    create_sse_data,
    get_effective_system_prompt_async,
)
from projects.models import Project, ProjectMember
from prompts.models import UserPrompt
from mcp_tools.models import RemoteMCPConfig
from mcp_tools.persistent_client import mcp_session_manager

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class AgentLoopStreamAPIView(View):
    """
    Agent Loop 流式聊天 API
    
    核心特性：
    - 每步独立 AI 调用，不累积 Token
    - Blackboard 状态管理
    - 工具结果自动摘要
    - 支持 SSE 流式输出
    """

    async def authenticate_request(self, request):
        """JWT 认证"""
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise AuthenticationFailed('Authentication credentials were not provided.')

        token = auth_header.split(' ')[1]
        jwt_auth = JWTAuthentication()

        try:
            validated_token = await sync_to_async(jwt_auth.get_validated_token)(token)
            user = await sync_to_async(jwt_auth.get_user)(validated_token)
            return user
        except Exception as e:
            raise AuthenticationFailed(f'Invalid token: {str(e)}')

    def _check_project_permission(self, user, project_id):
        """检查项目权限"""
        try:
            project = Project.objects.get(id=project_id)
            if user.is_superuser:
                return project
            if ProjectMember.objects.filter(project=project, user=user).exists():
                return project
            return None
        except Project.DoesNotExist:
            return None

    async def _save_chat_history(
        self,
        user_id: int,
        project_id: str,
        session_id: str,
        messages: List[AnyMessage]
    ):
        """
        保存对话历史到 chat_history.sqlite
        
        messages 参数应包含本轮的用户消息、每个 Agent Loop 步骤的
        推理与工具摘要，与 ChatStreamAPIView 使用相同的 checkpointer
        格式，确保 ChatHistoryAPIView 能正确读取历史记录。
        """
        if not messages:
            logger.warning("AgentLoopStreamAPI: No new messages to persist")
            return
        
        # 构建与 ChatStreamAPIView 相同的 thread_id 格式
        thread_id = f"{user_id}_{project_id}_{session_id}"
        
        db_path = os.path.join(str(settings.BASE_DIR), "chat_history.sqlite")
        
        async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
            # 配置必须包含 thread_id 和 checkpoint_ns
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ""  # 空字符串表示根命名空间
                }
            }
            
            # 获取现有的 checkpoint（如果有）
            existing_messages = []
            try:
                checkpoint_tuple = await checkpointer.aget(config)
                if checkpoint_tuple:
                    checkpoint_dict = checkpoint_tuple.checkpoint if hasattr(checkpoint_tuple, 'checkpoint') else checkpoint_tuple
                    if checkpoint_dict and isinstance(checkpoint_dict, dict):
                        channel_values = checkpoint_dict.get("channel_values", {})
                        existing_messages = channel_values.get("messages", [])
                        logger.info(f"AgentLoopStreamAPI: Found {len(existing_messages)} existing messages")
            except Exception as e:
                logger.warning(f"AgentLoopStreamAPI: Could not load existing checkpoint: {e}")
            
            # 添加新消息
            all_messages = list(existing_messages) + list(messages)
            
            # 创建新的 checkpoint
            import time
            from datetime import datetime
            checkpoint_id = f"checkpoint_{int(time.time() * 1000)}"
            # 使用 ISO 格式的时间戳字符串，与 LangGraph 原生格式兼容
            ts_str = datetime.utcnow().isoformat() + "Z"
            new_checkpoint = {
                "v": 1,
                "id": checkpoint_id,
                "ts": ts_str,
                "channel_values": {
                    "messages": all_messages
                },
                "channel_versions": {},
                "versions_seen": {},
                "pending_sends": []
            }
            
            metadata = {
                "source": "agent_loop",
                "step": -1,
                "writes": {}
            }
            
            # 保存 checkpoint - 使用正确的配置格式
            save_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint_id
                }
            }
            
            await checkpointer.aput(
                save_config,
                new_checkpoint,
                metadata,
                new_checkpoint.get("channel_versions", {})
            )
            
            logger.info(f"AgentLoopStreamAPI: Saved {len(messages)} new messages to checkpoint, total: {len(all_messages)}")

    async def _load_conversation_summary(
        self,
        user_id: int,
        project_id: str,
        session_id: str,
        llm=None,
        context_limit: int = 128000,
        model_name: str = "gpt-4o"
    ) -> str:
        """
        从聊天历史中提取对话摘要，用于初始化新任务的上下文。
        
        如果历史消息 Token 数超过 context_limit 的 70%，会使用 AI 生成结构化摘要；
        否则直接返回完整的消息列表。
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            session_id: 会话ID
            llm: LLM 实例（用于 AI 摘要）
            context_limit: 模型的上下文限制（从 LLMConfig 获取）
            model_name: 模型名称（用于 Token 计算）
        """
        thread_id = f"{user_id}_{project_id}_{session_id}"
        db_path = os.path.join(str(settings.BASE_DIR), "chat_history.sqlite")
        
        # 计算触发压缩的阈值（上下文限制的 70%，减去预留空间）
        trigger_threshold = int((context_limit - RESERVED_TOKENS) * 0.7)

        try:
            async with AsyncSqliteSaver.from_conn_string(db_path) as checkpointer:
                config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": ""
                    }
                }
                checkpoint_tuple = await checkpointer.aget(config)
                if not checkpoint_tuple:
                    return ""

                checkpoint_dict = checkpoint_tuple.checkpoint if hasattr(checkpoint_tuple, "checkpoint") else checkpoint_tuple
                if not checkpoint_dict:
                    return ""

                channel_values = checkpoint_dict.get("channel_values", {})
                existing_messages = channel_values.get("messages", [])
                if not existing_messages:
                    return ""

                # 过滤掉 SystemMessage
                filtered_messages = [
                    msg for msg in existing_messages 
                    if not isinstance(msg, SystemMessage)
                ]
                
                if not filtered_messages:
                    return ""

                # 估算现有消息的 Token 数
                total_tokens = 0
                for msg in filtered_messages:
                    content = getattr(msg, 'content', '')
                    if isinstance(content, list):
                        # 多模态消息
                        text_parts = [item.get('text', '') for item in content if isinstance(item, dict) and item.get('type') == 'text']
                        content = ' '.join(text_parts)
                    if content:
                        total_tokens += context_checker.count_tokens(str(content), model_name)
                
                logger.info(f"AgentLoopStreamAPI: Found {len(filtered_messages)} messages, ~{total_tokens} tokens (limit: {context_limit}, trigger: {trigger_threshold})")

                # 如果 Token 数在触发阈值内，直接返回完整消息
                if total_tokens <= trigger_threshold:
                    logger.info(f"AgentLoopStreamAPI: Token count within limit, returning full messages")
                    if llm:
                        filtered_messages = await self._summarize_tool_outputs_for_history(
                            filtered_messages,
                            llm=llm,
                            model_name=model_name
                        )
                    return self._format_messages_as_summary(
                        filtered_messages,
                        truncate_tool_output=not bool(llm)
                    )
                
                # Token 超过阈值且有 LLM，使用 AI 生成摘要
                if llm:
                    logger.info(f"AgentLoopStreamAPI: Token count ({total_tokens}) exceeds trigger threshold ({trigger_threshold}), using AI summary")
                    try:
                        compressor = ConversationCompressor(
                            llm=llm,
                            model_name=model_name,
                            settings=CompressionSettings(
                                max_context_tokens=context_limit,
                                preserve_recent_messages=4,  # 保留最近 4 条完整
                                trigger_ratio=0.7
                            )
                        )
                        # 调用压缩器的摘要方法
                        summary = await compressor._summarize_block(filtered_messages)
                        if summary:
                            return summary
                    except Exception as e:
                        logger.warning(f"AgentLoopStreamAPI: AI summary failed: {e}, falling back to simple format")
                
                # 回退：截取最近的消息
                recent_messages = filtered_messages[-8:]  # 保留最近 8 条
                if llm:
                    recent_messages = await self._summarize_tool_outputs_for_history(
                        recent_messages,
                        llm=llm,
                        model_name=model_name
                    )
                return self._format_messages_as_summary(
                    recent_messages,
                    truncate_tool_output=not bool(llm)
                )
                
        except FileNotFoundError:
            return ""
        except Exception as exc:
            logger.warning(f"AgentLoopStreamAPI: Failed to load conversation summary: {exc}")
            return ""

    def _normalize_message_content(self, content: Any) -> str:
        """规范化消息内容为字符串"""
        if content is None:
            return ""
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        parts.append("[图片]")
                else:
                    parts.append(str(item))
            return " ".join([p for p in parts if p.strip()])
        if isinstance(content, dict):
            try:
                return json.dumps(content, ensure_ascii=False)
            except Exception:
                return str(content)
        return str(content)

    async def _summarize_tool_outputs_for_history(
        self,
        messages: List[AnyMessage],
        llm,
        model_name: str,
        summary_limit: int = 600
    ) -> List[AnyMessage]:
        """对历史消息中的工具输出进行摘要"""
        summarized: List[AnyMessage] = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                raw_content = self._normalize_message_content(getattr(msg, "content", ""))
                if len(raw_content) > summary_limit and llm:
                    try:
                        prompt = (
                            "以下是工具输出，请用简洁中文概括关键结论、数据和建议，控制在150字内：\n"
                            f"{raw_content}\n\n"
                            "要求：保留结论和数值，忽略日志、重复细节。"
                        )
                        response = await llm.ainvoke([
                            SystemMessage(content="你擅长压缩冗长的工具返回，只保留要点。"),
                            HumanMessage(content=prompt)
                        ])
                        summary_text = response.content if hasattr(response, "content") else str(response)
                        if summary_text:
                            msg = ToolMessage(
                                content=f"[工具摘要] {summary_text.strip()}",
                                name=getattr(msg, "name", None),
                                tool_call_id=getattr(msg, "tool_call_id", None),
                                additional_kwargs=getattr(msg, "additional_kwargs", None)
                            )
                    except Exception as tool_err:
                        logger.warning(f"AgentLoopStreamAPI: tool summary failed: {tool_err}")
            summarized.append(msg)
        return summarized

    def _format_messages_as_summary(
        self,
        messages: List[AnyMessage],
        max_messages: Optional[int] = 20,
        *,
        truncate_tool_output: bool = False,
        tool_content_limit: int = 600
    ) -> str:
        """
        将消息列表转换为模型可读的文本摘要。
        保留用户/AI/工具的顺序，并可限制最近若干条。
        """
        trimmed_messages = list(messages or [])
        if max_messages and len(trimmed_messages) > max_messages:
            trimmed_messages = trimmed_messages[-max_messages:]

        lines: List[str] = []
        for msg in trimmed_messages:
            if isinstance(msg, SystemMessage):
                continue

            content = self._normalize_message_content(getattr(msg, "content", "")).strip()
            if not content:
                continue

            metadata = {}
            if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
                metadata = msg.additional_kwargs.get("metadata", {})

            if isinstance(msg, HumanMessage):
                prefix = "用户"
            elif isinstance(msg, AIMessage):
                prefix = "AI"
            elif isinstance(msg, ToolMessage):
                prefix = "工具"
            else:
                prefix = msg.__class__.__name__

            step = metadata.get("step")
            max_steps = metadata.get("max_steps")
            if step:
                if prefix == "AI":
                    prefix = f"AI(Step {step}/{max_steps or '?'})"
                elif prefix == "工具":
                    prefix = f"工具(Step {step}/{max_steps or '?'})"

            if isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", "agent_tool")
                prefix = f"{prefix}-{tool_name}"
                if truncate_tool_output and len(content) > tool_content_limit:
                    content = content[:tool_content_limit].rstrip() + "... [工具输出已截断]"

            lines.append(f"{prefix}: {content}")

        return "\n".join(lines).strip()

    async def _create_stream_generator(
        self,
        request,
        user_message: str,
        session_id: str,
        project_id: str,
        project: Project,
        knowledge_base_id: Optional[int] = None,
        use_knowledge_base: bool = True,
        prompt_id: Optional[int] = None,
        image_base64: Optional[str] = None,
    ):
        """创建 SSE 流式生成器"""
        # 用于收集所有消息的列表
        conversation_messages: List[AnyMessage] = []
        session_created = False
        
        try:
            # 1. 获取 LLM 配置
            active_config = await sync_to_async(LLMConfig.objects.get)(is_active=True)
            logger.info(f"AgentLoopStreamAPI: Using LLM config: {active_config.name}")
            context_limit = active_config.context_limit or 128000
            model_name = active_config.name or "gpt-4o"
        except LLMConfig.DoesNotExist:
            yield create_sse_data({'type': 'error', 'message': 'No active LLM configuration found'})
            return

        # 2. 验证多模态支持
        if image_base64 and not active_config.supports_vision:
            yield create_sse_data({
                'type': 'error',
                'message': f'模型 {active_config.name} 不支持图片输入'
            })
            return

        try:
            # 3. 初始化 LLM（避免阻塞事件循环）
            llm = await sync_to_async(create_llm_instance)(active_config, temperature=0.7)

            # 4. 加载 MCP 工具
            mcp_tools_list = []
            try:
                active_mcp_configs = await sync_to_async(list)(
                    RemoteMCPConfig.objects.filter(is_active=True)
                )
                if active_mcp_configs:
                    client_config = {}
                    for cfg in active_mcp_configs:
                        key = cfg.name or f"remote_{cfg.id}"
                        client_config[key] = {
                            "url": cfg.url,
                            "transport": (cfg.transport or "streamable_http").replace('-', '_'),
                        }
                        if cfg.headers:
                            client_config[key]["headers"] = cfg.headers

                    if client_config:
                        mcp_tools_list = await mcp_session_manager.get_tools_for_config(
                            client_config,
                            user_id=str(request.user.id),
                            project_id=str(project_id),
                            session_id=session_id
                        )
                        logger.info(f"AgentLoopStreamAPI: Loaded {len(mcp_tools_list)} MCP tools")
                        yield create_sse_data({
                            'type': 'info',
                            'message': f'已加载 {len(mcp_tools_list)} 个工具'
                        })
            except Exception as e:
                logger.error(f"AgentLoopStreamAPI: MCP tools loading failed: {e}", exc_info=True)
                yield create_sse_data({
                    'type': 'warning',
                    'message': f'MCP 工具加载失败: {str(e)}'
                })

            # 5. 添加知识库工具
            if knowledge_base_id and use_knowledge_base:
                try:
                    from knowledge.langgraph_integration import create_knowledge_tool
                    kb_tool = await sync_to_async(create_knowledge_tool)(
                        knowledge_base_id=knowledge_base_id,
                        user=request.user
                    )
                    mcp_tools_list.append(kb_tool)
                    logger.info(f"AgentLoopStreamAPI: Added knowledge base tool")
                except Exception as e:
                    logger.warning(f"AgentLoopStreamAPI: Knowledge tool creation failed: {e}")

            # 6. 获取或创建 ChatSession
            chat_session = await sync_to_async(
                lambda: ChatSession.objects.filter(
                    session_id=session_id,
                    user=request.user,
                    project_id=project_id
                ).first()
            )()
            
            if not chat_session:
                prompt_obj = None
                if prompt_id:
                    try:
                        prompt_obj = await sync_to_async(UserPrompt.objects.get)(
                            id=prompt_id, user=request.user, is_active=True
                        )
                    except UserPrompt.DoesNotExist:
                        pass
                
                chat_session = await sync_to_async(ChatSession.objects.create)(
                    user=request.user,
                    session_id=session_id,
                    project=project,
                    prompt=prompt_obj,
                    title=f"新对话 - {user_message[:30]}"
                )
                session_created = True
                logger.info(f"AgentLoopStreamAPI: Created new ChatSession: {session_id}")

            # 7. 获取系统提示词
            effective_prompt, prompt_source = await get_effective_system_prompt_async(
                request.user, prompt_id, project
            )

            # 7.5 加载历史对话摘要（跨对话上下文，根据模型context_limit判断是否需要AI摘要）
            conversation_summary = await self._load_conversation_summary(
                request.user.id,
                project_id,
                session_id,
                llm=llm,
                context_limit=active_config.context_limit or 128000,
                model_name=active_config.name or "gpt-4o"
            )
            if conversation_summary:
                logger.info(
                    f"AgentLoopStreamAPI: Loaded conversation summary with {len(conversation_summary.splitlines())} lines"
                )

            # 8. 构建初始上下文
            initial_context = {
                'system_prompt': effective_prompt,
                'project_name': project.name,
                'project_id': project_id,
                'conversation_history': conversation_summary or ''
            }

            # 9. 如果是新会话且有系统提示词，添加到消息列表
            if session_created and effective_prompt:
                conversation_messages.append(SystemMessage(content=effective_prompt))

            # 10. 构建目标（含图片时特殊处理）并添加用户消息
            if image_base64:
                goal = f"[包含图片] {user_message}"
                # 多模态消息格式
                human_message_content = [
                    {"type": "text", "text": user_message},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            else:
                goal = user_message
                human_message_content = user_message
            
            conversation_messages.append(HumanMessage(content=human_message_content))

            # 11. 发送开始信号
            yield create_sse_data({
                'type': 'start',
                'session_id': session_id,
                'project_id': project_id,
                'mode': 'agent_loop'
            })

            # 12. 创建 AgentOrchestrator 并执行
            orchestrator = AgentOrchestrator(
                llm=llm,
                tools=mcp_tools_list,
                max_steps=500
            )

            # 13. 执行 Agent Loop（流式输出每个步骤）
            task = await orchestrator._create_task(goal, chat_session)
            blackboard = await orchestrator._create_blackboard(task, initial_context)
            
            logger.info(f"AgentLoopStreamAPI: Starting task {task.id}, goal: {goal[:100]}")

            conversation_window = 20
            last_conversation_snapshot = (blackboard.current_state or {}).get('conversation_history', '')
            conversation_summary_text = conversation_summary or ''
            summarized_message_count = 0
            conversation_compressor = None
            summary_token_limit = max(2000, int(context_limit * 0.2))

            try:
                conversation_compressor = ConversationCompressor(
                    llm=llm,
                    model_name=model_name,
                    settings=CompressionSettings(
                        max_context_tokens=context_limit,
                        preserve_recent_messages=max(4, conversation_window // 2)
                    )
                )
            except Exception as compressor_error:
                logger.warning(f"AgentLoopStreamAPI: ConversationCompressor init failed: {compressor_error}")

            async def refresh_conversation_history_snapshot(force: bool = False) -> bool:
                nonlocal last_conversation_snapshot, conversation_summary_text, summarized_message_count

                total_messages = len(conversation_messages)
                if conversation_compressor:
                    cutoff = max(total_messages - conversation_window, 0)
                    if cutoff > summarized_message_count:
                        block = conversation_messages[summarized_message_count:cutoff]
                        if block:
                            try:
                                block_summary = await conversation_compressor._summarize_block(block)
                            except Exception as summary_error:
                                logger.warning(f"AgentLoopStreamAPI: conversation summary failed: {summary_error}")
                                block_summary = None
                            if block_summary:
                                block_summary = block_summary.strip()
                                if conversation_summary_text:
                                    conversation_summary_text = f"{conversation_summary_text}\n{block_summary}"
                                else:
                                    conversation_summary_text = block_summary
                                summarized_message_count = cutoff

                                if conversation_summary_text and conversation_compressor:
                                    try:
                                        summary_tokens = context_checker.count_tokens(conversation_summary_text, model_name)
                                        if summary_tokens > summary_token_limit:
                                            compressed = await conversation_compressor._recompress_summary(conversation_summary_text)
                                            if compressed:
                                                conversation_summary_text = compressed.strip()
                                                logger.info(f"AgentLoopStreamAPI: conversation summary recompressed to {context_checker.count_tokens(conversation_summary_text, model_name)} tokens")
                                    except Exception as recompress_error:
                                        logger.warning(f"AgentLoopStreamAPI: conversation summary recompress failed: {recompress_error}")

                recent_start = max(total_messages - conversation_window, 0)
                recent_messages = conversation_messages[recent_start:]
                recent_text = self._format_messages_as_summary(recent_messages, max_messages=None)

                sections: List[str] = []
                if conversation_summary_text:
                    sections.append(f"[过往对话摘要]\n{conversation_summary_text}".strip())
                if recent_text:
                    sections.append(f"[最近对话]\n{recent_text}".strip())

                combined_text = "\n\n".join([section for section in sections if section]).strip()

                if combined_text == last_conversation_snapshot and not force:
                    return False

                blackboard.current_state = dict(blackboard.current_state or {})
                blackboard.current_state['conversation_history'] = combined_text
                await sync_to_async(blackboard.save)(update_fields=['current_state', 'updated_at'])
                last_conversation_snapshot = combined_text
                return True

            await refresh_conversation_history_snapshot(force=True)

            step_count = 0
            while step_count < orchestrator.max_steps:
                step_count += 1
                task.current_step = step_count
                task.status = 'running'
                await orchestrator._save_task(task)

                # 发送步骤开始信号
                yield create_sse_data({
                    'type': 'step_start',
                    'step': step_count,
                    'max_steps': orchestrator.max_steps
                })

                # 构建上下文
                step_context = orchestrator._build_step_context(blackboard, goal)

                # 执行单步
                step_result = await orchestrator._execute_step(task, step_context)

                # 记录并流式输出 AI 响应
                ai_response = step_result.get('response')
                if ai_response:
                    is_final = step_result.get('is_final', False)
                    
                    # ⭐ 构建包含 SSE 事件类型的完整元数据
                    ai_metadata = {
                        "agent": "agent_loop",
                        "agent_type": "final" if is_final else "intermediate",
                        "step": step_count,
                        "max_steps": orchestrator.max_steps,
                        "sse_event_type": "message"  # ⭐ 标记为 message 事件
                    }
                    # ✅ Agent Loop 的 intermediate 消息不再标记为"思考过程"
                    # 这些是正常的分步执行结果,应该完整显示,而非折叠
                    
                    conversation_messages.append(
                        AIMessage(content=ai_response, additional_kwargs={"metadata": ai_metadata})
                    )
                    await refresh_conversation_history_snapshot()
                    yield create_sse_data({
                        'type': 'message',
                        'data': ai_response
                    })

                # 工具调用信息
                tool_summary = step_result.get('tool_summary')
                if tool_summary:
                    # ⭐ 工具消息也保存元数据
                    tool_metadata = {
                        "step": step_count,
                        "max_steps": orchestrator.max_steps,  # ⭐ 添加max_steps字段
                        "agent": "agent_loop",
                        "sse_event_type": "tool_result"  # ⭐ 标记为 tool_result 事件
                    }
                    conversation_messages.append(
                        ToolMessage(
                            content=f"Step {step_count} 工具结果:\n{tool_summary}",
                            tool_call_id=f"agent-loop-step-{step_count}",
                            name="agent_loop_tools",
                            additional_kwargs={"metadata": tool_metadata}
                        )
                    )
                    await refresh_conversation_history_snapshot()
                    yield create_sse_data({
                        'type': 'tool_result',
                        'summary': tool_summary
                    })

                # 更新 Blackboard
                await orchestrator._update_blackboard(blackboard, step_result)

                # 发送步骤完成信号
                yield create_sse_data({
                    'type': 'step_complete',
                    'step': step_count,
                    'summary': step_result.get('tool_summary', '')[:200]
                })

                # ⭐ 每步完成后立即保存对话历史（增量保存，防止中断丢失）
                try:
                    await self._save_chat_history(
                        request.user.id,
                        project_id,
                        session_id,
                        conversation_messages
                    )
                    logger.debug(f"AgentLoopStreamAPI: Step {step_count} history saved ({len(conversation_messages)} messages)")
                except Exception as save_err:
                    logger.warning(f"AgentLoopStreamAPI: Step {step_count} history save failed: {save_err}")

                # ⭐ 每步完成后计算Token使用情况（实时监控）
                # ✅ 修复：计算实际传递给LLM的内容，而不是存储用的conversation_messages
                try:
                    # 调试:检查实际配置值
                    logger.info(f"[Token] 读取配置: context_limit={context_limit}, name={active_config.name}, config_name={active_config.config_name}")
                    logger.info(f"[Token] 使用: context_limit={context_limit}, model={model_name}")
                    
                    # ⭐⭐ 构建实际的LLM输入内容（与_build_step_context一致）
                    # 这才是LLM真正看到的内容
                    history = blackboard.get_recent_history(orchestrator.DEFAULT_HISTORY_WINDOW)
                    history_text = '\n'.join([f"- {h}" for h in history]) if history else '（无历史）'
                    
                    conversation_history = blackboard.current_state.get('conversation_history', '') if blackboard.current_state else ''
                    conversation_history_text = conversation_history if conversation_history else '（无对话历史）'
                    
                    state_text = json.dumps(blackboard.current_state, ensure_ascii=False, indent=2) if blackboard.current_state else '（无）'
                    context_variables = blackboard.context_variables
                    
                    # 格式化为实际的SystemMessage内容（与STEP_SYSTEM_PROMPT一致）
                    step_context = {
                        'goal': goal,
                        'conversation_history': conversation_history_text,
                        'history': history_text,
                        'current_state': state_text,
                        'context_variables': context_variables
                    }
                    
                    # 使用实际的STEP_SYSTEM_PROMPT模板格式化
                    # 注：无需导入STEP_SYSTEM_PROMPT，直接计算各组件的token
                    token_counts = {}
                    token_counts['goal'] = context_checker.count_tokens(goal, model_name)
                    token_counts['conversation_history'] = context_checker.count_tokens(conversation_history_text, model_name)
                    token_counts['blackboard_history'] = context_checker.count_tokens(history_text, model_name)
                    
                    # ⚠️ 修复：current_state 已包含 conversation_history，不要重复计算
                    # 从 current_state 中排除 conversation_history 再计算
                    state_for_token = {k: v for k, v in (blackboard.current_state or {}).items() if k != 'conversation_history'}
                    state_text_for_token = json.dumps(state_for_token, ensure_ascii=False, indent=2) if state_for_token else '（无）'
                    token_counts['current_state'] = context_checker.count_tokens(state_text_for_token, model_name)
                    
                    token_counts['context_variables'] = context_checker.count_tokens(str(context_variables), model_name)
                    
                    # 加上固定的prompt模板开销（粗略估算）
                    token_counts['prompt_template'] = 200  # 估算STEP_SYSTEM_PROMPT模板本身的token
                    
                    total_tokens = sum(token_counts.values())
                    
                    # 打印各部分token分布（调试用）
                    logger.info(f"[Token分布] goal:{token_counts['goal']}, conv_history:{token_counts['conversation_history']}, bb_history:{token_counts['blackboard_history']}, state:{token_counts['current_state']}, vars:{token_counts['context_variables']}, template:{token_counts['prompt_template']}")
                    logger.info(f"[Context Update] Agent Loop Step {step_count}: {total_tokens}/{context_limit} tokens")
                    
                    # ⭐ 每步都发送Token更新事件
                    yield create_sse_data({
                        'type': 'context_update',
                        'context_token_count': total_tokens,
                        'context_limit': context_limit,
                        'step': step_count  # ⭐ 标记是哪一步的Token统计
                    })
                    
                    # ⭐⭐ 达到90%触发AI驱动的历史压缩
                    if total_tokens >= context_limit * 0.9:
                        logger.warning(f"[Compression Trigger] Step {step_count}: Token达到{total_tokens}/{context_limit}(90%),触发压缩")
                        
                        yield create_sse_data({
                            'type': 'compressing',
                            'message': '⚙️ Token达到90%,正在压缩记忆...',
                            'step': step_count,
                            'current_tokens': total_tokens,
                            'context_limit': context_limit
                        })
                        
                        compression_actions: List[str] = []
                        try:
                            history_compressed = await sync_to_async(blackboard.compress_old_history)(context_limit, model_name)
                            if history_compressed:
                                compression_actions.append('执行记录')
                        except Exception as compress_err:
                            logger.error(f"[Compression] 调用Blackboard压缩失败: {compress_err}", exc_info=True)
                        
                        try:
                            updated_conv = await refresh_conversation_history_snapshot()
                            if updated_conv:
                                compression_actions.append('对话历史')
                        except Exception as conv_err:
                            logger.error(f"[Compression] 更新对话历史失败: {conv_err}", exc_info=True)
                        
                        if compression_actions:
                            history = blackboard.get_recent_history(orchestrator.DEFAULT_HISTORY_WINDOW)
                            new_history_text = '\n'.join([f"- {h}" for h in history]) if history else '（无历史）'
                            
                            new_conversation_history = blackboard.current_state.get('conversation_history', '') if blackboard.current_state else ''
                            new_conversation_history_text = new_conversation_history if new_conversation_history else '（无对话历史）'
                            
                            state_for_token_after = {k: v for k, v in (blackboard.current_state or {}).items() if k != 'conversation_history'}
                            state_text_after = json.dumps(state_for_token_after, ensure_ascii=False, indent=2) if state_for_token_after else '（无）'
                            
                            new_token_counts = {
                                'goal': token_counts['goal'],
                                'conversation_history': context_checker.count_tokens(new_conversation_history_text, model_name),
                                'blackboard_history': context_checker.count_tokens(new_history_text, model_name),
                                'current_state': context_checker.count_tokens(state_text_after, model_name),
                                'context_variables': token_counts['context_variables'],
                                'prompt_template': token_counts['prompt_template']
                            }
                            
                            new_total_tokens = sum(new_token_counts.values())
                            reduction = max(total_tokens - new_total_tokens, 0)
                            actions_text = '、'.join(compression_actions)
                            
                            yield create_sse_data({
                                'type': 'compression_done',
                                'message': f'{actions_text}已压缩: {total_tokens}→{new_total_tokens} tokens',
                                'step': step_count,
                                'token_reduction': reduction
                            })
                            
                            yield create_sse_data({
                                'type': 'context_update',
                                'context_token_count': new_total_tokens,
                                'context_limit': context_limit,
                                'step': step_count
                            })
                            
                            logger.info(f"[Compression Done] Step {step_count}: Token {total_tokens}→{new_total_tokens} (动作: {actions_text})")
                            total_tokens = new_total_tokens
                        else:
                            logger.warning(f"[Compression] Step {step_count}: 没有可压缩的内容")
                
                except Exception as e:
                    logger.warning(f"AgentLoopStreamAPI Step {step_count}: Failed to calculate token count: {e}")

                # 检查是否完成
                if step_result.get('is_final'):
                    logger.info(f"AgentLoopStreamAPI: Task is_final=True, saving task...")
                    task.status = 'completed'
                    task.final_response = step_result.get('response', '')
                    task.completed_at = timezone.now()
                    await orchestrator._save_task(task)
                    
                    # 对话历史已在每步保存，此处无需重复保存
                    logger.info(f"AgentLoopStreamAPI: Task completed, history already saved ({len(conversation_messages)} messages)")
                    
                    # ✅ Token统计已移至每步完成后实时计算,此处不再重复
                    
                    yield create_sse_data({
                        'type': 'complete',
                        'total_steps': step_count,
                        'task_id': task.id
                    })
                    break

                # 检查错误
                if step_result.get('error'):
                    task.status = 'failed'
                    task.error_message = step_result['error']
                    task.completed_at = timezone.now()
                    await orchestrator._save_task(task)
                    
                    # 错误时确保已有对话历史已保存（通常每步已保存，这里是兜底）
                    logger.info(f"AgentLoopStreamAPI: Task failed at step {step_count}, history already saved")
                    
                    yield create_sse_data({
                        'type': 'error',
                        'message': step_result['error']
                    })
                    break

                # 小延迟确保流式效果
                await asyncio.sleep(0.05)

            # 超过最大步骤
            if step_count >= orchestrator.max_steps:
                task.status = 'failed'
                task.error_message = f'超过最大步骤数 {orchestrator.max_steps}'
                task.completed_at = timezone.now()
                await orchestrator._save_task(task)
                
                yield create_sse_data({
                    'type': 'error',
                    'message': task.error_message
                })

            # 发送流结束标记
            yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"AgentLoopStreamAPI: Error: {e}", exc_info=True)
            yield create_sse_data({
                'type': 'error',
                'message': f'执行错误: {str(e)}'
            })

    async def post(self, request, *args, **kwargs):
        """处理流式聊天请求"""
        # 1. 认证
        try:
            user = await self.authenticate_request(request)
            request.user = user
        except AuthenticationFailed as e:
            return StreamingHttpResponse(
                iter([create_sse_data({'type': 'error', 'message': str(e), 'code': 401})]),
                content_type='text/event-stream; charset=utf-8',
                status=401
            )

        # 2. 解析请求
        try:
            body_data = json.loads(request.body.decode('utf-8'))
        except json.JSONDecodeError as e:
            return StreamingHttpResponse(
                iter([create_sse_data({'type': 'error', 'message': f'Invalid JSON: {e}', 'code': 400})]),
                content_type='text/event-stream; charset=utf-8',
                status=400
            )

        user_message = body_data.get('message')
        session_id = body_data.get('session_id')
        project_id = body_data.get('project_id')
        knowledge_base_id = body_data.get('knowledge_base_id')
        use_knowledge_base = body_data.get('use_knowledge_base', True)
        prompt_id = body_data.get('prompt_id')
        image_base64 = body_data.get('image')

        # 3. 参数验证
        if not project_id:
            return StreamingHttpResponse(
                iter([create_sse_data({'type': 'error', 'message': 'project_id is required', 'code': 400})]),
                content_type='text/event-stream; charset=utf-8',
                status=400
            )

        if not user_message:
            return StreamingHttpResponse(
                iter([create_sse_data({'type': 'error', 'message': 'message is required', 'code': 400})]),
                content_type='text/event-stream; charset=utf-8',
                status=400
            )

        # 4. 项目权限检查
        project = await sync_to_async(self._check_project_permission)(request.user, project_id)
        if not project:
            return StreamingHttpResponse(
                iter([create_sse_data({'type': 'error', 'message': 'Project access denied', 'code': 403})]),
                content_type='text/event-stream; charset=utf-8',
                status=403
            )

        # 5. 生成 session_id
        if not session_id:
            session_id = uuid.uuid4().hex
            logger.info(f"AgentLoopStreamAPI: Generated new session_id: {session_id}")

        # 6. 返回流式响应
        async def async_generator():
            async for chunk in self._create_stream_generator(
                request, user_message, session_id, project_id, project,
                knowledge_base_id, use_knowledge_base, prompt_id, image_base64
            ):
                yield chunk

        response = StreamingHttpResponse(
            async_generator(),
            content_type='text/event-stream; charset=utf-8'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response
