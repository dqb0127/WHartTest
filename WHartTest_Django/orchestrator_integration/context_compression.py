"""
对话上下文压缩模块

功能：
- 在对话历史Token超过阈值时自动压缩
- 保留最近N条消息完整，对更早的消息生成摘要
- 摘要作为SystemMessage前缀传入LLM
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage

from requirements.context_limits import RESERVED_TOKENS, context_checker

logger = logging.getLogger(__name__)


@dataclass
class CompressionSettings:
    """压缩配置参数"""
    max_context_tokens: int = 128000
    trigger_ratio: float = 0.75  # 达到75%时触发压缩
    preserve_recent_messages: int = 4  # 保留最近4条消息（约2轮对话）
    min_messages_to_compress: int = 2  # 至少有2条消息才能压缩
    summary_prefix: str = "对话历史摘要"
    reserved_tokens: int = RESERVED_TOKENS


@dataclass
class CompressionResult:
    """压缩结果"""
    messages: List[BaseMessage]  # 压缩后的消息列表
    summary_message: Optional[SystemMessage]  # 摘要消息（如有）
    state_updates: Dict[str, object]  # 需要更新的状态字段
    triggered: bool  # 是否触发了压缩
    token_count: int  # 当前Token数


class ConversationCompressor:
    """对话上下文压缩器"""

    def __init__(self, llm, model_name: str, settings: Optional[CompressionSettings] = None):
        self.llm = llm
        self.model_name = model_name or getattr(llm, "model_name", "gpt-4o")
        self.settings = settings or CompressionSettings()

    async def prepare(
        self,
        messages: Sequence[BaseMessage],
        summary_text: Optional[str] = None,
        summarized_count: int = 0,
    ) -> CompressionResult:
        """
        准备上下文：检查是否需要压缩，如需则执行压缩
        
        Args:
            messages: 当前完整消息历史
            summary_text: 已有的摘要文本
            summarized_count: 已被摘要覆盖的消息数量
        
        Returns:
            CompressionResult: 压缩结果
        """
        normalized_messages = list(messages or [])
        incoming_summary = summary_text or None
        incoming_count = summarized_count or 0

        # 计算可用Token空间
        available_tokens = max(
            self.settings.max_context_tokens - self.settings.reserved_tokens, 1000
        )
        
        # 计算现有摘要的Token数
        summary_tokens = (
            context_checker.count_tokens(incoming_summary, self.model_name)
            if incoming_summary else 0
        )
        
        # 计算总Token数
        raw_token_count = self._estimate_token_count(normalized_messages) + summary_tokens
        trigger_tokens = int(available_tokens * self.settings.trigger_ratio)

        summary_value = incoming_summary
        new_summarized_count = incoming_count
        summary_updated = False
        
        # 计算当前使用率
        usage_ratio = raw_token_count / available_tokens if available_tokens > 0 else 0

        # 判断是否需要压缩
        if raw_token_count > trigger_tokens and len(normalized_messages) >= self.settings.min_messages_to_compress:
            # 计算需要保留的消息数量
            # 如果使用率 > 90%，更激进地压缩，只保留更少的消息
            if usage_ratio > 0.9:
                preserve_count = max(2, self.settings.preserve_recent_messages // 2)
                logger.info(f"高使用率({usage_ratio*100:.1f}%)，激进压缩模式，保留{preserve_count}条消息")
            else:
                preserve_count = self.settings.preserve_recent_messages
            
            cutoff = max(len(normalized_messages) - preserve_count, 0)
            
            # 检查是否有新的消息需要摘要
            if cutoff > new_summarized_count:
                block = normalized_messages[new_summarized_count:cutoff]
                block_summary = await self._summarize_block(block)
                
                if block_summary:
                    summary_value = self._merge_summary(summary_value, block_summary)
                    new_summarized_count = cutoff
                    summary_updated = True
                    logger.info(
                        "对话上下文已压缩：覆盖消息#0-#%s，保留最近%s条",
                        cutoff, preserve_count
                    )
                    
                    # 检查摘要是否过长（超过可用空间的30%），如果是则重新压缩摘要
                    summary_tokens = context_checker.count_tokens(summary_value, self.model_name)
                    max_summary_tokens = int(available_tokens * 0.3)
                    if summary_tokens > max_summary_tokens:
                        logger.info(f"摘要过长({summary_tokens} tokens)，重新压缩...")
                        summary_value = await self._recompress_summary(summary_value)
                        logger.info(f"摘要重压缩完成")
            else:
                logger.debug("触发压缩但无新消息块可处理（cutoff=%s, summarized_count=%s）", cutoff, new_summarized_count)

        # 构建最终消息列表
        if summary_value:
            summary_message = SystemMessage(
                content=f"【{self.settings.summary_prefix}】\n\n{summary_value}",
                additional_kwargs={"agent": "context_summary", "is_summary": True},
            )
            preserved_messages = normalized_messages[new_summarized_count:]
            context_messages: List[BaseMessage] = [summary_message] + list(preserved_messages)
        else:
            summary_message = None
            context_messages = normalized_messages

        # 计算最终Token数
        final_token_count = self._estimate_token_count(context_messages)
        
        # 构建状态更新
        state_updates: Dict[str, object] = {"context_token_count": final_token_count}
        if summary_value != incoming_summary:
            state_updates["context_summary"] = summary_value
        if new_summarized_count != incoming_count:
            state_updates["summarized_message_count"] = new_summarized_count

        return CompressionResult(
            messages=context_messages,
            summary_message=summary_message,
            state_updates=state_updates,
            triggered=summary_updated,
            token_count=final_token_count,
        )

    def _message_to_text(self, message: BaseMessage) -> str:
        """将消息转换为文本"""
        role = getattr(message, "type", message.__class__.__name__)
        agent = getattr(message, "additional_kwargs", {}).get("agent")
        label = agent or role
        body = self._normalize_content(getattr(message, "content", ""))
        return f"[{label}] {body}".strip()

    def _normalize_content(self, content) -> str:
        """标准化消息内容"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [self._normalize_content(item) for item in content if item]
            return "\n".join([part for part in parts if part])
        if isinstance(content, dict):
            try:
                return json.dumps(content, ensure_ascii=False)
            except TypeError:
                return str(content)
        return str(content or "")

    def _estimate_token_count(self, messages: Sequence[BaseMessage]) -> int:
        """估算消息列表的Token总数"""
        total = 0
        for msg in messages:
            text = self._message_to_text(msg)
            if text:
                total += context_checker.count_tokens(text, self.model_name)
        return total

    def _merge_summary(self, existing: Optional[str], new_block: str) -> str:
        """合并摘要 - 当有旧摘要时，让AI生成综合摘要"""
        if existing:
            # 简单合并，后续如果摘要过长会在下次压缩时被重新压缩
            # 因为摘要本身也会计入token，当摘要+保留消息超过阈值时会再次触发压缩
            return f"{existing}\n\n---\n\n{new_block}"
        return new_block

    async def _recompress_summary(self, long_summary: str) -> str:
        """当摘要本身过长时，重新生成更简洁的摘要"""
        try:
            prompt = f"""以下是一段对话历史的摘要，请将其压缩为更简洁的版本，只保留最关键的信息：

{long_summary}

请生成一个更简洁的摘要，保留核心上下文信息。"""

            response = await self.llm.ainvoke([
                SystemMessage(content="你是一个专业的摘要压缩助手，擅长提炼关键信息。"),
                HumanMessage(content=prompt)
            ])
            
            return response.content.strip() if hasattr(response, 'content') else str(response).strip()
        except Exception as e:
            # 某些 OpenAI 兼容服务会返回非标准响应，导致 langchain_openai 在解析 choices 时抛 TypeError
            if isinstance(e, TypeError) and "NoneType" in str(e) and "iterable" in str(e):
                logger.warning("摘要重压缩失败（服务端响应异常，已降级处理）: %s", e)
            else:
                logger.error("摘要重压缩失败: %s", e)
            # 回退：截取前半部分
            return long_summary[:len(long_summary)//2] + "\n[历史摘要已截断]"

    async def _summarize_block(self, block: Sequence[BaseMessage]) -> str:
        """对消息块生成结构化摘要"""
        docs = []
        for msg in block:
            text = self._message_to_text(msg)
            if text:
                docs.append(Document(page_content=text))
        
        if not docs:
            return ""

        try:
            # 合并文档内容
            combined_content = "\n\n".join([doc.page_content for doc in docs])
            
            # 使用结构化提示词生成摘要
            summary_prompt = f"""请将以下对话内容压缩成简洁的摘要，保留关键信息。

对话内容：
{combined_content}

请按以下格式生成摘要：
1. 已完成事项：（列出已讨论或完成的要点）
2. 当前状态：（当前讨论到的位置或状态）
3. 待处理事项：（如有提到需要后续处理的事项）

请用简洁的语言概括，保持专业性。"""

            # 直接调用 LLM 生成摘要
            response = await self.llm.ainvoke([
                SystemMessage(content="你是一个专业的对话摘要助手，擅长提取对话中的关键信息。"),
                HumanMessage(content=summary_prompt)
            ])
            
            return response.content.strip() if hasattr(response, 'content') else str(response).strip()
            
        except Exception as e:
            # 某些 OpenAI 兼容服务会返回非标准响应，导致 langchain_openai 在解析 choices 时抛 TypeError
            if isinstance(e, TypeError) and "NoneType" in str(e) and "iterable" in str(e):
                logger.warning("摘要生成失败（服务端响应异常，已降级处理）: %s", e)
            else:
                logger.error("摘要生成失败: %s", e, exc_info=True)
            # 回退：简单截断
            combined = "\n".join([self._message_to_text(msg) for msg in block[:3]])
            return f"[摘要生成失败，保留前3条消息概要]\n{combined[:500]}..."
