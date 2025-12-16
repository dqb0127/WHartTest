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
from .context_compression import ConversationCompressor, CompressionSettings
from requirements.context_limits import context_checker, RESERVED_TOKENS
from wharttest_django.checkpointer import get_async_checkpointer

from .agent_loop import AgentOrchestrator
from .models import AgentTask, AgentBlackboard, AgentStep
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
        
        messages 参数是本轮完整的消息列表（包含之前步骤的消息），
        直接覆盖保存，避免重复追加。
        """
        if not messages:
            logger.warning("AgentLoopStreamAPI: No new messages to persist")
            return
        
        # 构建与 ChatStreamAPIView 相同的 thread_id 格式
        thread_id = f"{user_id}_{project_id}_{session_id}"
        
        async with get_async_checkpointer() as checkpointer:
            # 配置必须包含 thread_id 和 checkpoint_ns
            config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ""  # 空字符串表示根命名空间
                }
            }
            
            # 获取现有 checkpoint 的 channel_versions（用于计算下一个版本）
            current_channel_versions = {}
            try:
                checkpoint_tuple = await checkpointer.aget(config)
                if checkpoint_tuple:
                    checkpoint_dict = checkpoint_tuple.checkpoint if hasattr(checkpoint_tuple, 'checkpoint') else checkpoint_tuple
                    if checkpoint_dict and isinstance(checkpoint_dict, dict):
                        current_channel_versions = checkpoint_dict.get("channel_versions", {})
            except Exception as e:
                logger.warning(f"AgentLoopStreamAPI: Could not load existing checkpoint: {e}")
            
            # 直接使用传入的 messages 作为完整消息列表（不再追加）
            all_messages = list(messages)
            
            # 计算新的 channel 版本
            current_messages_version = current_channel_versions.get("messages")
            next_messages_version = checkpointer.get_next_version(current_messages_version, None)
            
            # 创建新的 checkpoint
            import time
            from datetime import datetime
            checkpoint_id = f"checkpoint_{int(time.time() * 1000)}"
            ts_str = datetime.utcnow().isoformat() + "Z"
            
            new_channel_versions = {"messages": next_messages_version}
            new_checkpoint = {
                "v": 1,
                "id": checkpoint_id,
                "ts": ts_str,
                "channel_values": {
                    "messages": all_messages
                },
                "channel_versions": new_channel_versions,
                "versions_seen": {"": {"messages": next_messages_version}},
                "pending_sends": []
            }
            
            metadata = {
                "source": "agent_loop",
                "step": -1,
                "writes": {}
            }
            
            # 保存 checkpoint
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
                new_channel_versions
            )
            
            logger.info(f"AgentLoopStreamAPI: Saved checkpoint with {len(all_messages)} messages")

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
        
        # 计算触发压缩的阈值（上下文限制的 70%，减去预留空间）
        trigger_threshold = int((context_limit - RESERVED_TOKENS) * 0.7)

        try:
            async with get_async_checkpointer() as checkpointer:
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
        generate_playwright_script: bool = False,
        test_case_id: Optional[int] = None,
        use_pytest: bool = True,
    ):
        """创建 SSE 流式生成器"""
        # 用于收集所有消息的列表（会先加载历史消息）
        conversation_messages: List[AnyMessage] = []
        session_created = False
        
        # 先加载历史消息（用于续接会话时避免重复）
        thread_id = f"{request.user.id}_{project_id}_{session_id}"
        try:
            async with get_async_checkpointer() as checkpointer:
                config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
                checkpoint_tuple = await checkpointer.aget(config)
                if checkpoint_tuple:
                    checkpoint_dict = checkpoint_tuple.checkpoint if hasattr(checkpoint_tuple, 'checkpoint') else checkpoint_tuple
                    if checkpoint_dict and isinstance(checkpoint_dict, dict):
                        existing_messages = checkpoint_dict.get("channel_values", {}).get("messages", [])
                        if existing_messages:
                            conversation_messages = list(existing_messages)
                            logger.info(f"AgentLoopStreamAPI: Loaded {len(existing_messages)} existing messages for continuation")
        except Exception as e:
            logger.warning(f"AgentLoopStreamAPI: Could not load existing messages: {e}")
        
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

            # 5.5. 添加内置工具（Playwright 脚本管理等）
            from orchestrator_integration.builtin_tools import get_builtin_tools
            
            builtin_tools = get_builtin_tools(
                user_id=request.user.id,
                project_id=int(project_id),
                test_case_id=test_case_id,
            )
            mcp_tools_list.extend(builtin_tools)
            logger.info(f"AgentLoopStreamAPI: Added {len(builtin_tools)} builtin tools")

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
            
            # 7.1 如果需要生成脚本，追加脚本生成指令
            if generate_playwright_script:
                script_instruction = """

## 【强制要求】自动化脚本生成

**重要：本次任务必须在执行完所有测试步骤后，生成并保存 Playwright 脚本！这是强制要求，不可跳过！**

### 任务流程（必须按顺序完成）
1. ✅ 执行所有测试步骤（使用 Playwright MCP 工具）
2. ✅ 为每个步骤截图并上传
3. ⚠️ **【必须】生成 Playwright Python 脚本**（根据执行过程）
4. ⚠️ **【必须】调用 `save_playwright_script` 保存脚本**
5. ✅ 返回测试结果 JSON

**如果没有调用 `save_playwright_script` 保存脚本，本次任务视为未完成！**

## 自动化脚本管理工具

你可以使用以下工具管理自动化脚本：

### 可用工具列表
- `save_playwright_script(script_content, test_case_id, description)` - 保存新的 Playwright 脚本
- `list_playwright_scripts(test_case_id, keyword, limit)` - 列出脚本列表
- `get_playwright_script(script_id)` - 获取脚本详情和代码
- `update_playwright_script(script_id, script_content, description)` - 更新已有脚本
- `execute_playwright_script(script_id, headless, record_video)` - 执行脚本
- `get_script_execution_result(execution_id, script_id)` - 获取执行结果

### 执行流程
1. **执行测试步骤**：使用 Playwright MCP 工具执行测试用例中的所有步骤
2. **生成脚本**：所有步骤执行完成后，根据执行过程生成完整的 Playwright Python 脚本
3. **保存脚本**：调用 `save_playwright_script` 工具保存脚本

### 脚本要求
生成的脚本必须是**标准的自动化测试脚本**，包含：
- `from playwright.sync_api import sync_playwright, expect` 导入
- `run()` 函数定义
- 所有测试步骤对应的 Playwright Python 代码
- 使用准确的选择器（根据实际执行时使用的选择器）
- 适当的错误处理（try/finally 确保浏览器关闭）
- **每个关键步骤后添加截图**（用于执行报告）
- **适当的 print 输出**（记录执行进度）
- **断言验证**（验证每个操作的预期结果）
- 脚本必须是 **Python** 语法，不是 JavaScript
- 使用 `page.get_by_role()`, `page.locator()` 等方法
- 在所有测试步骤执行完成后再生成脚本
- **禁止在脚本中使用 emoji 字符**（如 ✅ ❌ 等），使用纯文本描述
- **每个步骤后必须截图**，截图文件名格式: `step{N}_{action}.png`
- **每个步骤后必须 print**，输出格式: `步骤{N}: {描述}成功`
- **关键操作必须有断言**，验证操作的预期结果
- **生成后必须执行脚本，验证脚本的可执行性

### 断言示例
使用 Playwright 的 `expect` API 进行断言：
- `expect(page).to_have_url("...")` - 验证 URL
- `expect(page).to_have_title("...")` - 验证标题
- `expect(page.locator("...")).to_be_visible()` - 验证元素可见
- `expect(page.locator("...")).to_have_text("...")` - 验证文本内容
- `expect(page.locator("...")).to_have_count(n)` - 验证元素数量
- `expect(page.locator("...")).to_be_enabled()` - 验证元素可用

### 断言规则（非常重要）
1. **禁止猜测 URL**：断言中的 URL 必须使用执行步骤时**实际观察到的 URL**，不要自己编造或猜测
2. **禁止使用通配符模式**：不要使用 `**/dashboard` 这样的模式，必须使用完整的实际 URL
3. **断言必须来源于实际结果**：所有断言值（URL、标题、文本等）必须是执行过程中**实际看到的值**
4. **如果不确定实际值，使用 to_be_visible() 代替**：当无法确定元素的具体文本时，优先使用可见性断言

### 正确示例
```python
# 正确：使用实际执行时看到的完整 URL
expect(page).to_have_url("http://localhost:5173/project-management")

# 正确：使用实际看到的标题
expect(page).to_have_title("项目管理 - WHartTest")
```

### 错误示例（禁止这样做）
```python
# 错误：自己猜测的 URL
expect(page).to_have_url("https://example.com/dashboard")

# 错误：使用通配符模式
expect(page).to_have_url("**/dashboard")

# 错误：编造的标题
expect(page).to_have_title("Dashboard Page")
```

### 脚本模板（仅供参考结构，所有值必须替换为实际执行时观察到的值）
**重要：以下模板中的所有 URL、选择器、文本都是占位符示例，你必须替换为执行测试步骤时实际看到的值！**

```python
from playwright.sync_api import sync_playwright, expect


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.set_default_timeout(30000)
        
        step = 0
        
        try:
            # 步骤1: 打开页面
            step += 1
            # 【替换为实际URL】下面的URL必须是你执行goto时使用的真实URL
            page.goto("【替换为实际目标URL】")
            # 【替换为实际标题】下面的标题必须是页面打开后你实际看到的标题
            expect(page).to_have_title("【替换为实际页面标题】")
            print(f"步骤{step}: 打开页面成功")
            page.screenshot(path=f"step{step}_open_page.png")
            
            # 步骤2: 输入内容（示例）
            step += 1
            # 【替换为实际选择器】使用你执行fill操作时实际使用的选择器
            page.get_by_role("textbox", name="【替换为实际placeholder或label】").fill("【替换为实际输入值】")
            print(f"步骤{step}: 输入内容成功")
            page.screenshot(path=f"step{step}_input.png")
            
            # 步骤3: 点击按钮（示例）
            step += 1
            # 【替换为实际选择器】使用你执行click操作时实际使用的选择器
            page.get_by_role("button", name="【替换为实际按钮文本】").click()
            # 【替换为实际URL】如果点击后会跳转，使用实际跳转后的完整URL
            expect(page).to_have_url("【替换为跳转后的实际完整URL】")
            print(f"步骤{step}: 点击按钮成功")
            page.screenshot(path=f"step{step}_click.png")
            
            print(f"测试执行成功, 共执行 {step} 个步骤, 所有断言通过")
        except Exception as e:
            print(f"步骤{step}执行失败: {e}")
            page.screenshot(path="error_screenshot.png")
            raise
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    run()
```

### 重要提示
- 脚本必须是 **Python** 语法，不是 JavaScript
- 使用 `page.get_by_role()`, `page.locator()` 等方法
- 在所有测试步骤执行完成后再生成脚本
- **禁止在脚本中使用 emoji 字符**（如 ✅ ❌ 等），使用纯文本描述
- **每个步骤后必须截图**，截图文件名格式: `step{N}_{action}.png`
- **每个步骤后必须 print**，输出格式: `步骤{N}: {描述}成功`
- **关键操作必须有断言**，验证操作的预期结果
- **生成后必须执行脚本**，验证脚本的可执行性
- **禁止使用虚构的选择器**：如 `.welcome-message`、`#main-content` 等，必须使用执行时实际使用的选择器
- **禁止照抄模板占位符**：模板中的 `【替换为...】` 只是提示，必须替换为实际值


### Python Playwright 语法规范（非常重要）
**注意：Python 版本的 Playwright 与 JavaScript 版本语法不同！**

#### 定位器方法语法
Python 使用**关键字参数**，不是 JavaScript 的对象语法：

```python
# ✅ 正确的 Python 语法：使用关键字参数 name=
page.get_by_role("textbox", name="请输入用户名")
page.get_by_role("button", name="登录")
page.get_by_role("link", name="首页")

# ❌ 错误的 JavaScript 语法：不要使用 { } 对象
page.get_by_role('textbox', { 'name': '请输入用户名' })  # 错误！
page.get_by_role("button", { name: "登录" })  # 错误！
```

#### 其他定位器示例
```python
# 正确的 Python 语法
page.get_by_label("用户名")
page.get_by_placeholder("请输入密码")
page.get_by_text("欢迎")
page.get_by_test_id("submit-button")
page.locator("css=.button-class")
page.locator("xpath=//button[@id='submit']")
```

#### 错误处理
如果遇到定位器参数问题，请使用以下方式：
```python
# 方式1：使用 get_by_role + name 关键字参数
page.get_by_role("textbox", name="用户名").fill("admin")

# 方式2：使用 locator + CSS 选择器
page.locator("input[placeholder='用户名']").fill("admin")

# 方式3：使用 get_by_placeholder
page.get_by_placeholder("用户名").fill("admin")
```
"""
                effective_prompt = (effective_prompt or '') + script_instruction
                logger.info(f"AgentLoopStreamAPI: 已追加脚本生成指令，系统提示词长度: {len(effective_prompt)} 字符")

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
                'mode': 'agent_loop',
                'created_at': chat_session.created_at.isoformat() if chat_session and chat_session.created_at else None
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

            # 连续工具失败计数器（防止无效重试浪费步数）
            consecutive_tool_failures = 0
            max_consecutive_tool_failures = 3
            
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

                # ⭐ 使用队列实现真正的流式输出
                stream_queue = asyncio.Queue()
                streaming_content = []  # 收集流式内容用于保存
                
                async def stream_callback(chunk: str):
                    """流式回调：将 chunk 放入队列并收集"""
                    streaming_content.append(chunk)
                    await stream_queue.put(('chunk', chunk))
                
                # 启动后台任务执行 LLM 调用
                step_task = asyncio.create_task(
                    orchestrator._execute_step(task, step_context, stream_callback=stream_callback)
                )
                
                # ⭐ 设置步骤整体超时（5分钟）
                step_timeout = 300  # 秒
                step_start_time = asyncio.get_event_loop().time()
                step_timed_out = False
                
                # 实时输出流式内容
                while not step_task.done():
                    try:
                        # 检查整体超时
                        elapsed = asyncio.get_event_loop().time() - step_start_time
                        if elapsed > step_timeout:
                            step_timed_out = True
                            step_task.cancel()
                            logger.error(f"步骤 {step_count} 执行超时 ({step_timeout}秒)")
                            yield create_sse_data({
                                'type': 'error',
                                'message': f'步骤执行超时（{step_timeout}秒）'
                            })
                            break
                        
                        # 等待队列数据，设置超时避免阻塞
                        msg_type, content = await asyncio.wait_for(
                            stream_queue.get(), 
                            timeout=0.1
                        )
                        if msg_type == 'chunk':
                            yield create_sse_data({
                                'type': 'stream',
                                'data': content
                            })
                    except asyncio.TimeoutError:
                        # 超时后继续检查任务是否完成
                        continue
                    except asyncio.CancelledError:
                        break
                
                # 如果超时，更新任务状态并退出
                if step_timed_out:
                    # ⭐ 等待任务取消完成
                    try:
                        await step_task
                    except asyncio.CancelledError:
                        pass
                    
                    # 更新任务状态
                    task.status = 'failed'
                    task.error_message = f'步骤 {step_count} 执行超时'
                    task.completed_at = timezone.now()
                    await orchestrator._save_task(task)
                    
                    # ⭐ 保存已收集的流式内容到对话历史
                    if streaming_content:
                        partial_response = ''.join(streaming_content)
                        timeout_metadata = {
                            "agent": "agent_loop",
                            "agent_type": "timeout",
                            "step": step_count,
                            "max_steps": orchestrator.max_steps,
                            "sse_event_type": "error"
                        }
                        conversation_messages.append(
                            AIMessage(
                                content=f"[超时中断] {partial_response}" if partial_response else "[步骤执行超时]",
                                additional_kwargs={"metadata": timeout_metadata}
                            )
                        )
                        # 保存对话历史
                        try:
                            await self._save_chat_history(
                                request.user.id,
                                project_id,
                                session_id,
                                conversation_messages
                            )
                        except Exception as save_err:
                            logger.warning(f"AgentLoopStreamAPI: Timeout history save failed: {save_err}")
                    
                    # 发送错误结束事件
                    yield create_sse_data({
                        'type': 'error',
                        'message': f'步骤执行超时（{step_timeout}秒）',
                        'step': step_count
                    })
                    yield create_sse_data({
                        'type': 'complete',
                        'status': 'timeout',
                        'steps': step_count
                    })
                    return
                
                # 处理队列中剩余的数据
                while not stream_queue.empty():
                    msg_type, content = await stream_queue.get()
                    if msg_type == 'chunk':
                        yield create_sse_data({
                            'type': 'stream',
                            'data': content
                        })
                
                # 获取执行结果
                try:
                    step_result = await step_task
                except asyncio.CancelledError:
                    step_result = {'error': '步骤被取消'}

                # 记录并流式输出 AI 响应（完整响应，用于保存历史）
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
                    
                    # ⭐ 发送流式结束信号（内容已通过 stream 事件发送）
                    yield create_sse_data({
                        'type': 'stream_end',
                        'step': step_count,
                        'is_final': is_final
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
                    
                    complete_data = {
                        'type': 'complete',
                        'total_steps': step_count,
                        'task_id': task.id
                    }
                    
                    # Playwright 脚本管理工具已通过 builtin_tools 加载
                    if generate_playwright_script:
                        complete_data['script_generation'] = {
                            'enabled': True,
                            'message': '脚本管理工具已启用（保存/查询/执行等）'
                        }
                    
                    yield create_sse_data(complete_data)
                    break

                # 检查错误：工具调用失败时继续循环让 LLM 重试
                if step_result.get('error') and not step_result.get('tool_results'):
                    # 非工具调用错误，直接失败
                    task.status = 'failed'
                    task.error_message = step_result['error']
                    task.completed_at = timezone.now()
                    await orchestrator._save_task(task)
                    
                    logger.info(f"AgentLoopStreamAPI: Task failed at step {step_count}, history already saved")
                    
                    yield create_sse_data({
                        'type': 'error',
                        'message': step_result['error']
                    })
                    break
                
                # 检查工具调用失败计数
                if step_result.get('error') and step_result.get('tool_results'):
                    consecutive_tool_failures += 1
                    logger.warning(f"工具调用失败 ({consecutive_tool_failures}/{max_consecutive_tool_failures}): {step_result['error'][:100]}")
                    
                    if consecutive_tool_failures >= max_consecutive_tool_failures:
                        task.status = 'failed'
                        task.error_message = f'工具调用连续失败 {consecutive_tool_failures} 次: {step_result["error"]}'
                        task.completed_at = timezone.now()
                        await orchestrator._save_task(task)
                        
                        yield create_sse_data({
                            'type': 'error',
                            'message': task.error_message
                        })
                        break
                else:
                    # 成功时重置计数器
                    consecutive_tool_failures = 0

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
        
        # Playwright 脚本生成参数
        generate_playwright_script = body_data.get('generate_playwright_script', False)
        test_case_id = body_data.get('test_case_id')  # 用于关联生成的脚本
        use_pytest = body_data.get('use_pytest', True)  # 生成 pytest 格式还是简单格式

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
                knowledge_base_id, use_knowledge_base, prompt_id, image_base64,
                generate_playwright_script, test_case_id, use_pytest
            ):
                yield chunk

        response = StreamingHttpResponse(
            async_generator(),
            content_type='text/event-stream; charset=utf-8'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response
