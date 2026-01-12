from rest_framework import status, permissions, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from django.db.models import Q
from django.utils import timezone
from .models import LLMConfig, ChatSession, ChatMessage
from .serializers import LLMConfigSerializer
import logging
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

# 项目相关导入
from projects.models import Project, ProjectMember
from projects.permissions import IsProjectMember

# 导入统一的权限系统
from wharttest_django.viewsets import BaseModelViewSet
from wharttest_django.permissions import HasModelPermission

# 导入提示词管理
from prompts.models import UserPrompt

# 导入上下文压缩模块
from orchestrator_integration.context_compression import ConversationCompressor, CompressionSettings

# --- New Imports ---
from typing import TypedDict, Annotated, List, Optional
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages # Correct import for add_messages
from langgraph.prebuilt import create_react_agent # For agent with tools
import os
import uuid # Import uuid module
import copy  # For deep copying checkpoint data
import re
import base64  # For requirement doc images (multimodal)
# Knowledge base integration
from knowledge.langgraph_integration import KnowledgeRAGService, ConversationalRAGService, LangGraphKnowledgeIntegration
from knowledge.models import KnowledgeBase
from django.conf import settings
import logging # Import logging
from asgiref.sync import sync_to_async # For async operations in sync context
# 统一的 Checkpointer 工厂
from wharttest_django.checkpointer import get_async_checkpointer, get_sync_checkpointer, delete_checkpoints_by_thread_id, delete_checkpoints_batch, check_history_exists, get_thread_ids_by_prefix, rollback_checkpoints_to_count
import json # For JSON serialization in streaming
import asyncio # For async operations

# Django streaming response
from django.http import StreamingHttpResponse

from mcp_tools.models import RemoteMCPConfig # To load remote MCP server configs
from langchain_mcp_adapters.client import MultiServerMCPClient # To connect to remote MCPs
from mcp_tools.persistent_client import mcp_session_manager # 持久化MCP会话管理器
# Requirement documents (docimg:// placeholders)
from requirements.models import RequirementDocument
# --- End New Imports ---

logger = logging.getLogger(__name__) # Initialize logger

# --- Helper Functions ---
def create_llm_instance(active_config, temperature=0.7):
    """
    根据配置创建LLM实例
    统一使用OpenAI兼容格式，支持所有兼容的服务商
    """
    model_identifier = active_config.name or "gpt-3.5-turbo"
    
    llm_kwargs = {
        "model": model_identifier,
        "temperature": temperature,
        "api_key": active_config.api_key,
        "base_url": active_config.api_url
    }
    llm = ChatOpenAI(**llm_kwargs)
    logger.info(f"Initialized OpenAI-compatible LLM with model: {model_identifier}, base_url: {active_config.api_url}")
    
    return llm

def create_sse_data(data_dict):
    """
    创建SSE格式的数据，确保中文字符正确编码
    """
    json_str = json.dumps(data_dict, ensure_ascii=False)
    return f"data: {json_str}\n\n"

_REQ_DOC_ID_RE = re.compile(r'需求文档ID[:：]\s*([0-9a-fA-F-]{36})')
_REQ_DOC_IMAGE_URL_RE = re.compile(
    r'/api/requirements/documents/(?P<doc_id>[0-9a-fA-F-]{36})/images/(?P<image_id>[^/]+)/'
)
_REQ_DOCIMG_MD_RE = re.compile(r'!\[[^\]]*?\]\(docimg://(?P<image_id>[^)]+)\)')
_REQ_DOCIMG_API_MD_RE = re.compile(
    r'!\[[^\]]*?\]\(/api/requirements/documents/(?P<doc_id>[0-9a-fA-F-]{36})/images/(?P<image_id>[^)/]+)/*\)'
)


def _detect_requirement_document_id(message: str) -> Optional[str]:
    if not message:
        return None
    url_match = _REQ_DOC_IMAGE_URL_RE.search(message)
    if url_match:
        return url_match.group("doc_id")
    text_match = _REQ_DOC_ID_RE.search(message)
    if text_match:
        return text_match.group(1)
    return None


def _replace_docimg_markdown_with_api_urls(message: str, document_id: str) -> str:
    if not message or not document_id or "docimg://" not in message:
        return message

    def _repl(match: re.Match) -> str:
        alt = match.group(1)
        image_id = match.group(2)
        return f"![{alt}](/api/requirements/documents/{document_id}/images/{image_id}/)"

    return re.sub(r'!\[(.*?)\]\(docimg://([^)]+)\)', _repl, message)


def _extract_requirement_image_ids_in_order(message: str) -> list[str]:
    if not message:
        return []

    ordered: list[str] = []
    seen: set[str] = set()

    # docimg://img_001 in Markdown
    for m in _REQ_DOCIMG_MD_RE.finditer(message):
        image_id = m.group("image_id")
        if image_id and image_id not in seen:
            seen.add(image_id)
            ordered.append(image_id)

    # /api/requirements/documents/{doc}/images/{img}/ in Markdown
    for m in _REQ_DOCIMG_API_MD_RE.finditer(message):
        image_id = m.group("image_id")
        if image_id and image_id not in seen:
            seen.add(image_id)
            ordered.append(image_id)

    return ordered


def _file_to_data_url(path: str, content_type: str) -> str:
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{content_type};base64,{encoded}"


async def _extract_requirement_doc_images_for_message(
    message: str,
    project: Project,
) -> tuple[str, list[str], Optional[str]]:
    """
    从消息中识别需求文档图片引用（docimg:// 或 /api/requirements/documents/.../images/...），
    并返回：
    - message_text: 将 docimg:// 占位符替换为可访问的 /api URL 后的文本（用于展示/存档）
    - image_data_urls: 需要送入多模态模型的 data:... URL 列表（按出现顺序、去重）
    - document_id: 解析到的需求文档ID（UUID字符串）
    """
    if not message:
        return message, [], None

    document_id = _detect_requirement_document_id(message)
    if not document_id:
        return message, [], None

    message_text = _replace_docimg_markdown_with_api_urls(message, document_id)
    image_ids = _extract_requirement_image_ids_in_order(message_text)
    if not image_ids:
        return message_text, [], document_id

    # 只允许读取当前项目下的文档图片，避免跨项目泄露
    document = await sync_to_async(
        lambda: RequirementDocument.objects.filter(id=document_id, project=project).first()
    )()
    if not document:
        logger.warning(
            "Chat: RequirementDocument %s not found in project %s, skip image attachment",
            document_id,
            getattr(project, "id", None),
        )
        return message_text, [], document_id

    images = await sync_to_async(lambda: list(document.images.filter(image_id__in=image_ids)))()
    image_map = {img.image_id: img for img in images}

    data_urls: list[str] = []
    for image_id in image_ids:
        img = image_map.get(image_id)
        if not img:
            logger.warning("Chat: Document image %s not found in document %s", image_id, document_id)
            continue
        try:
            path = img.image_file.path
            data_url = await sync_to_async(_file_to_data_url)(path, img.content_type)
            data_urls.append(data_url)
        except Exception as e:
            logger.error("Chat: Failed to load document image %s (%s): %s", image_id, document_id, e)
            continue

    return message_text, data_urls, document_id

# --- AgentState Definition ---
class AgentState(TypedDict):
    messages: Annotated[List[AnyMessage], add_messages]
# --- End AgentState Definition ---

# --- Global Checkpointer ---
# This creates/uses a SQLite file in the project's BASE_DIR
# Ensure BASE_DIR is correctly defined in your settings.py
# settings.BASE_DIR should be a Path object or string.
# --- End Global Checkpointer ---
# Global checkpointer 'memory' is removed. It will be instantiated within the post method.

class LLMConfigViewSet(BaseModelViewSet):
    """
    LLM配置管理接口
    提供完整的CRUD操作
    """
    queryset = LLMConfig.objects.all().order_by('-created_at')
    serializer_class = LLMConfigSerializer
    def perform_create(self, serializer):
        """执行创建操作"""
        if serializer.validated_data.get('is_active', False):
            LLMConfig.objects.filter(is_active=True).update(is_active=False)
        serializer.save()

    def perform_update(self, serializer):
        """执行更新操作"""
        if serializer.validated_data.get('is_active', False):
            LLMConfig.objects.filter(is_active=True).exclude(pk=serializer.instance.pk).update(is_active=False)
        serializer.save()

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """测试LLM配置连接"""
        import requests as http_requests
        config = self.get_object()
        api_url = config.api_url.rstrip('/')
        headers = {'Content-Type': 'application/json'}
        if config.api_key:
            headers['Authorization'] = f'Bearer {config.api_key}'
        try:
            resp = http_requests.post(
                f'{api_url}/chat/completions',
                json={'model': config.name, 'messages': [{'role': 'user', 'content': 'Hi'}], 'max_tokens': 5},
                headers=headers,
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get('choices') and len(data['choices']) > 0:
                return Response({'status': 'success', 'message': '连接测试成功'})
            return Response({'status': 'warning', 'message': '响应格式异常'}, status=status.HTTP_200_OK)
        except http_requests.Timeout:
            return Response({'status': 'error', 'message': '请求超时'}, status=status.HTTP_408_REQUEST_TIMEOUT)
        except http_requests.RequestException as e:
            msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    msg = e.response.json().get('error', {}).get('message', str(e))
                except Exception:
                    msg = e.response.text[:200] if e.response.text else str(e)
            return Response({'status': 'error', 'message': f'连接失败: {msg}'}, status=status.HTTP_400_BAD_REQUEST)


def get_effective_system_prompt(user, prompt_id=None):
    """
    获取有效的系统提示词（同步版本）
    优先级：用户指定的提示词 > 用户默认提示词 > 全局LLM配置的system_prompt

    Args:
        user: 当前用户
        prompt_id: 指定的提示词ID（可选）

    Returns:
        tuple: (prompt_content, prompt_source)
        prompt_content: 提示词内容
        prompt_source: 提示词来源 ('user_specified', 'user_default', 'global', 'none')
    """
    try:
        # 1. 如果指定了提示词ID，优先使用
        if prompt_id:
            try:
                user_prompt = UserPrompt.objects.get(
                    id=prompt_id,
                    user=user,
                    is_active=True
                )
                return user_prompt.content, 'user_specified'
            except UserPrompt.DoesNotExist:
                logger.warning(f"Specified prompt {prompt_id} not found for user {user.id}")

        # 2. 尝试获取用户的默认提示词
        default_prompt = UserPrompt.get_user_default_prompt(user)
        if default_prompt:
            return default_prompt.content, 'user_default'

        # 3. 使用全局LLM配置的system_prompt
        try:
            active_config = LLMConfig.objects.get(is_active=True)
            if active_config.system_prompt and active_config.system_prompt.strip():
                return active_config.system_prompt.strip(), 'global'
        except LLMConfig.DoesNotExist:
            logger.warning("No active LLM configuration found")

        # 4. 没有任何提示词
        return None, 'none'

    except Exception as e:
        logger.error(f"Error getting effective system prompt: {e}")
        # 降级到全局配置
        try:
            active_config = LLMConfig.objects.get(is_active=True)
            if active_config.system_prompt and active_config.system_prompt.strip():
                return active_config.system_prompt.strip(), 'global'
        except:
            pass
        return None, 'none'


async def _format_project_credentials(project):
    """
    格式化项目凭据信息为文本
    
    Args:
        project: 项目对象
    
    Returns:
        str: 格式化后的凭据信息文本
    """
    try:
        from projects.models import ProjectCredential
        
        # 获取项目的所有凭据
        credentials = await sync_to_async(list)(
            ProjectCredential.objects.filter(project=project).all()
        )
        
        if not credentials:
            return "当前项目未配置登录信息。\n"
        
        # 格式化凭据信息
        credentials_text = "**当前项目已配置以下登录信息**：\n"
        for cred in credentials:
            role = cred.user_role or "未指定角色"
            url = cred.system_url or "未指定URL"
            username = cred.username or "未指定用户名"
            password = cred.password or "未指定密码"
            credentials_text += f"- **{role}**：系统地址: {url} / 用户名: {username} / 密码: {password}\n"
        
        credentials_text += "\n"
        return credentials_text
    
    except Exception as e:
        logger.error(f"Format project credentials error: {e}")
        return ""


async def _format_project_skills(project):
    """
    格式化全局 Skills 信息为文本（渐进式加载）

    只注入 Skill 的名称和描述（元数据），完整的 SKILL.md 内容需要通过
    read_skill_content 工具按需获取。Skills 全局共享，不限制项目。

    Args:
        project: 项目对象（保留参数兼容性，但不用于过滤）

    Returns:
        str: 格式化后的 Skills 元数据文本
    """
    try:
        from skills.models import Skill

        # Skills 全局共享，不限制项目
        skills = await sync_to_async(list)(
            Skill.objects.filter(is_active=True).all()
        )

        if not skills:
            return ""

        skills_text = "\n\n# Available Skills\n\n"
        skills_text += "以下是可用的 Skills 列表。需要使用某个 Skill 时，先调用 `read_skill_content` 工具获取完整的使用说明，再调用 `execute_skill_script` 执行命令。\n\n"
        for skill in skills:
            skills_text += f"- **{skill.name}**: {skill.description}\n"

        return skills_text

    except Exception as e:
        logger.error(f"Format project skills error: {e}")
        return ""


async def _inject_project_context(prompt_content: str, project) -> str:
    """
    注入项目上下文（凭据和 Skills）到提示词中

    Args:
        prompt_content: 原始提示词内容
        project: 项目对象

    Returns:
        str: 注入上下文后的提示词
    """
    if not project:
        return prompt_content

    # 注入凭据信息
    if '{credentials_info}' in prompt_content:
        credentials_text = await _format_project_credentials(project)
        prompt_content = prompt_content.replace('{credentials_info}', credentials_text)

    # 注入 Skills 信息
    if '{skills_info}' in prompt_content:
        skills_text = await _format_project_skills(project)
        prompt_content = prompt_content.replace('{skills_info}', skills_text)
    else:
        # 即使没有占位符，也自动追加 Skills 到提示词末尾
        skills_text = await _format_project_skills(project)
        if skills_text:
            prompt_content = prompt_content + skills_text

    return prompt_content


async def get_effective_system_prompt_async(user, prompt_id=None, project=None):
    """
    获取有效的系统提示词（异步版本）
    优先级：用户指定的提示词 > 用户默认提示词 > 全局LLM配置的system_prompt
    支持占位符: {credentials_info} 注入项目凭据, {skills_info} 注入项目 Skills 元数据
    如果未使用 {skills_info} 占位符，活跃的 Skills 元数据将自动追加到提示词末尾
    （完整的 SKILL.md 内容通过 read_skill_content 工具按需获取）

    Args:
        user: 当前用户
        prompt_id: 指定的提示词ID（可选）
        project: 项目对象（可选），用于注入凭据和 Skills 信息

    Returns:
        tuple: (prompt_content, prompt_source)
        prompt_content: 提示词内容（已注入项目上下文）
        prompt_source: 提示词来源 ('user_specified', 'user_default', 'global', 'none')
    """
    try:
        # 1. 如果指定了提示词ID，优先使用
        if prompt_id:
            try:
                user_prompt = await sync_to_async(UserPrompt.objects.get)(
                    id=prompt_id,
                    user=user,
                    is_active=True
                )
                prompt_content = await _inject_project_context(user_prompt.content, project)
                return prompt_content, 'user_specified'
            except UserPrompt.DoesNotExist:
                logger.warning(f"Specified prompt {prompt_id} not found for user {user.id}")

        # 2. 尝试获取用户的默认提示词
        try:
            default_prompt = await sync_to_async(UserPrompt.objects.get)(
                user=user,
                is_default=True,
                is_active=True
            )
            if default_prompt:
                prompt_content = await _inject_project_context(default_prompt.content, project)
                return prompt_content, 'user_default'
        except UserPrompt.DoesNotExist:
            pass

        # 3. 使用全局LLM配置的system_prompt
        try:
            active_config = await sync_to_async(LLMConfig.objects.get)(is_active=True)
            if active_config.system_prompt and active_config.system_prompt.strip():
                prompt_content = await _inject_project_context(active_config.system_prompt.strip(), project)
                return prompt_content, 'global'
        except LLMConfig.DoesNotExist:
            logger.warning("No active LLM configuration found")

        # 4. 没有任何提示词
        return None, 'none'

    except Exception as e:
        logger.error(f"Error getting effective system prompt: {e}")
        # 降级到全局配置
        try:
            active_config = await sync_to_async(LLMConfig.objects.get)(is_active=True)
            if active_config.system_prompt and active_config.system_prompt.strip():
                return active_config.system_prompt.strip(), 'global'
        except:
            pass
        return None, 'none'


class ChatAPIView(APIView):
    """
    API endpoint for handling chat with the currently active LLM using LangGraph,
    with potential integration of remote MCP tools.
    支持项目隔离，聊天记录按项目分组。
    """
    permission_classes = [HasModelPermission]

    def _check_project_permission(self, user, project_id):
        """检查用户是否有访问指定项目的权限"""
        try:
            project = Project.objects.get(id=project_id)
            # 超级用户可以访问所有项目
            if user.is_superuser:
                return project
            # 检查用户是否是项目成员
            if ProjectMember.objects.filter(project=project, user=user).exists():
                return project
            return None
        except Project.DoesNotExist:
            return None

    async def dispatch(self, request, *args, **kwargs):
        """
        Handles incoming requests and ensures that the view is treated as async.
        """
        self.request = request
        self.args = args
        self.kwargs = kwargs
        # Ensure request object is initialized for DRF's typical expectations
        # This might involve more complex handling if request.user is accessed early by sync code
        # For now, we assume standard DRF request processing can be wrapped.
        request = await sync_to_async(self.initialize_request)(request, *args, **kwargs)
        self.request = request
        self.headers = await sync_to_async(lambda: self.default_response_headers)()

        try:
            await sync_to_async(self.initial)(request, *args, **kwargs)

            if request.method.lower() in self.http_method_names:
                handler = getattr(self, request.method.lower(), self.http_method_not_allowed)
            else:
                handler = self.http_method_not_allowed

            response = await handler(request, *args, **kwargs)

        except Exception as exc:
            response = await sync_to_async(self.handle_exception)(exc)

        self.response = await sync_to_async(self.finalize_response)(request, response, *args, **kwargs)
        return self.response

    async def post(self, request, *args, **kwargs):
        logger.info(f"ChatAPIView: Received POST request from user {request.user.id}")
        user_message_content = request.data.get('message')
        session_id = request.data.get('session_id')
        project_id = request.data.get('project_id')
        image_base64 = request.data.get('image')  # 图片base64编码（不含前缀）

        # 知识库相关参数
        knowledge_base_id = request.data.get('knowledge_base_id')
        use_knowledge_base = request.data.get('use_knowledge_base', True)  # 默认启用知识库
        similarity_threshold = request.data.get('similarity_threshold', 0.5)
        top_k = request.data.get('top_k', 5)

        # 提示词相关参数
        prompt_id = request.data.get('prompt_id')  # 用户指定的提示词ID

        # 验证项目ID是否提供
        if not project_id:
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "project_id is required.", "data": {},
                "errors": {"project_id": ["This field is required."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        # 检查项目权限
        project = await sync_to_async(self._check_project_permission)(request.user, project_id)
        if not project:
            return Response({
                "status": "error", "code": status.HTTP_403_FORBIDDEN,
                "message": "You don't have permission to access this project or project doesn't exist.", "data": {},
                "errors": {"project_id": ["Permission denied or project not found."]}
            }, status=status.HTTP_403_FORBIDDEN)

        is_new_session = False
        if not session_id:
            session_id = uuid.uuid4().hex
            is_new_session = True
            logger.info(f"ChatAPIView: Generated new session_id: {session_id}")

        if not user_message_content:
            logger.warning("ChatAPIView: Message content is required but not provided.")
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "Message content is required.", "data": {},
                "errors": {"message": ["This field may not be blank."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 如果是新会话，立即创建ChatSession对象
            if is_new_session:
                try:
                    # 获取关联的提示词对象
                    prompt_obj = None
                    if prompt_id:
                        try:
                            prompt_obj = await sync_to_async(UserPrompt.objects.get)(
                                id=prompt_id,
                                user=request.user,
                                is_active=True
                            )
                        except UserPrompt.DoesNotExist:
                            logger.warning(f"ChatAPIView: Prompt {prompt_id} not found or inactive")
                    
                    await sync_to_async(ChatSession.objects.create)(
                        user=request.user,
                        session_id=session_id,
                        project=project,
                        prompt=prompt_obj,
                        title=f"新对话 - {user_message_content[:30]}"
                    )
                    logger.info(f"ChatAPIView: Created new ChatSession entry for session_id: {session_id}, prompt_id: {prompt_id}")
                except Exception as e:
                    logger.error(f"ChatAPIView: Failed to create ChatSession entry: {e}", exc_info=True)

            active_config = await sync_to_async(LLMConfig.objects.get)(is_active=True)
            logger.info(f"ChatAPIView: Using active LLMConfig: {active_config.name}")
        except LLMConfig.DoesNotExist:
            logger.error("ChatAPIView: No active LLM configuration found.")
            return Response({
                "status": "error", "code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "message": "No active LLM configuration found. Please configure and activate an LLM.", "data": {},
                "errors": {"llm_config": ["No active LLM configuration available."]}
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except LLMConfig.MultipleObjectsReturned:
            logger.error("ChatAPIView: Multiple active LLM configurations found.")
            return Response({
                "status": "error", "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "message": "Multiple active LLM configurations found. Ensure only one is active.", "data": {},
                "errors": {"llm_config": ["Multiple active LLM configurations found."]}
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # 验证图片输入是否支持
        if image_base64 and not active_config.supports_vision:
            logger.warning(f"ChatAPIView: Image input rejected - model {active_config.name} does not support vision")
            return Response({
                "status": "error",
                "code": status.HTTP_400_BAD_REQUEST,
                "message": f"当前模型 {active_config.name} 不支持图片输入，请切换到支持多模态的模型（如 GPT-4V、Claude 3、Gemini Vision 或 Qwen-VL）",
                "data": {},
                "errors": {"image": ["Current model does not support image input. Please switch to a vision-capable model."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 使用新的LLM工厂函数，支持多供应商
            llm = create_llm_instance(active_config, temperature=0.7)
            logger.info(f"ChatAPIView: Initialized LLM with provider auto-detection")

            async with get_async_checkpointer() as actual_memory_checkpointer:
                # Load remote MCP tools
                logger.info("ChatAPIView: Attempting to load remote MCP tools.")
                mcp_tools_list = []
                try:
                    active_remote_mcp_configs_qs = RemoteMCPConfig.objects.filter(is_active=True)
                    active_remote_mcp_configs = await sync_to_async(list)(active_remote_mcp_configs_qs)

                    if active_remote_mcp_configs:
                        client_mcp_config = {}
                        for r_config in active_remote_mcp_configs:
                            config_key = r_config.name or f"remote_config_{r_config.id}"
                            client_mcp_config[config_key] = {
                                "url": r_config.url,
                                "transport": (r_config.transport or "streamable_http").replace('-', '_'),
                            }
                            if r_config.headers and isinstance(r_config.headers, dict) and r_config.headers:
                                client_mcp_config[config_key]["headers"] = r_config.headers

                        if client_mcp_config:
                            logger.info(f"ChatAPIView: Initializing persistent MCP client with config: {client_mcp_config}")
                            # 使用持久化MCP会话管理器，传递用户、项目和会话信息以支持跨对话轮次的状态保持
                            mcp_tools_list = await mcp_session_manager.get_tools_for_config(
                                client_mcp_config,
                                user_id=str(request.user.id),
                                project_id=str(project_id),
                                session_id=session_id  # 传递session_id以启用会话级别的工具缓存
                            )
                            logger.info(f"ChatAPIView: Successfully loaded {len(mcp_tools_list)} persistent tools from remote MCP servers: {[tool.name for tool in mcp_tools_list if hasattr(tool, 'name')]}")
                        else:
                            logger.info("ChatAPIView: No active remote MCP configurations to build client config.")
                    else:
                        logger.info("ChatAPIView: No active RemoteMCPConfig found.")
                except Exception as e: # Catches errors from mcp_client.get_tools() like HTTP 429
                    logger.error(f"ChatAPIView: Error loading remote MCP tools: {e}", exc_info=True)
                    # mcp_tools_list remains empty, will fallback to basic chatbot

                # Prepare LangGraph runnable
                runnable_to_invoke = None
                is_agent_with_tools = False

                # 检查是否需要创建Agent（有MCP工具）
                if mcp_tools_list:
                    logger.info(f"ChatAPIView: Attempting to create agent with {len(mcp_tools_list)} remote tools.")
                    try:
                        # 如果同时有知识库和MCP工具，创建知识库增强的Agent
                        if knowledge_base_id and use_knowledge_base:
                            logger.info(f"ChatAPIView: Creating knowledge-enhanced agent with {len(mcp_tools_list)} tools and knowledge base {knowledge_base_id}")

                            # 创建知识库工具
                            from knowledge.langgraph_integration import create_knowledge_tool
                            knowledge_tool = create_knowledge_tool(
                                knowledge_base_id=knowledge_base_id,
                                user=request.user,
                                similarity_threshold=similarity_threshold,
                                top_k=top_k
                            )

                            # 将知识库工具添加到MCP工具列表
                            enhanced_tools = mcp_tools_list + [knowledge_tool]
                            agent_executor = create_react_agent(llm, enhanced_tools, checkpointer=actual_memory_checkpointer)
                            runnable_to_invoke = agent_executor
                            is_agent_with_tools = True
                            logger.info(f"ChatAPIView: Knowledge-enhanced agent created with {len(enhanced_tools)} tools (including knowledge base)")
                        else:
                            # 只有MCP工具，创建普通Agent
                            agent_executor = create_react_agent(llm, mcp_tools_list, checkpointer=actual_memory_checkpointer)
                            runnable_to_invoke = agent_executor
                            is_agent_with_tools = True
                            logger.info("ChatAPIView: Agent with remote tools created with checkpointer.")
                    except Exception as e:
                        logger.error(f"ChatAPIView: Failed to create agent with remote tools: {e}. Falling back to knowledge-enhanced chatbot.", exc_info=True)

                if not runnable_to_invoke:
                    logger.info("ChatAPIView: No remote tools or agent creation failed. Using knowledge-enhanced chatbot.")
                    is_agent_with_tools = False # Ensure flag is false for basic chatbot

                    def knowledge_enhanced_chatbot_node(state: AgentState):
                        """知识库增强的聊天机器人节点"""
                        try:
                            # 获取最新的用户消息
                            user_messages = [msg for msg in state['messages']
                                           if isinstance(msg, HumanMessage)]

                            if not user_messages:
                                # 如果没有用户消息，直接调用LLM
                                invoked_response = llm.invoke(state['messages'])
                                return {"messages": [invoked_response]}

                            latest_user_message = user_messages[-1].content

                            # 检查是否需要使用知识库
                            should_use_kb = use_knowledge_base and knowledge_base_id

                            if should_use_kb:
                                logger.info(f"ChatAPIView: Using knowledge base {knowledge_base_id} for query")

                                # 使用知识库RAG服务
                                from knowledge.langgraph_integration import ConversationalRAGService
                                rag_service = ConversationalRAGService(llm)

                                # 执行RAG查询
                                rag_result = rag_service.query(
                                    question=latest_user_message,
                                    knowledge_base_id=knowledge_base_id,
                                    user=request.user,
                                    project_id=project_id,
                                    thread_id=thread_id,
                                    use_knowledge_base=True,
                                    similarity_threshold=similarity_threshold,
                                    top_k=top_k
                                )

                                # 返回RAG结果中的消息
                                rag_messages = rag_result.get("messages", [])
                                if rag_messages:
                                    logger.info(f"ChatAPIView: RAG returned {len(rag_messages)} messages")
                                    return {"messages": rag_messages}
                                else:
                                    logger.warning("ChatAPIView: RAG returned no messages, falling back to basic chat")

                            # 降级到基础对话
                            logger.info("ChatAPIView: Using basic chat without knowledge base")
                            invoked_response = llm.invoke(state['messages'])
                            return {"messages": [invoked_response]}

                        except Exception as e:
                            logger.error(f"ChatAPIView: Error in knowledge-enhanced chatbot: {e}")
                            # 降级到基础对话
                            invoked_response = llm.invoke(state['messages'])
                            return {"messages": [invoked_response]}

                    graph_builder = StateGraph(AgentState)
                    graph_builder.add_node("chatbot", knowledge_enhanced_chatbot_node)
                    graph_builder.set_entry_point("chatbot")
                    graph_builder.add_edge("chatbot", END)
                    runnable_to_invoke = graph_builder.compile(checkpointer=actual_memory_checkpointer) # Use actual checkpointer instance
                    logger.info("ChatAPIView: Knowledge-enhanced chatbot graph compiled.")

                # Determine thread_id - 包含项目ID以实现项目隔离
                thread_id_parts = [str(request.user.id), str(project_id)]
                if session_id:
                    thread_id_parts.append(str(session_id))
                thread_id = "_".join(thread_id_parts)
                logger.info(f"ChatAPIView: Using thread_id: {thread_id} for project: {project.name}")

                # 构建消息列表，检查是否需要添加系统提示词
                messages_list = []

                # 获取有效的系统提示词（用户提示词优先，并注入项目凭据信息）
                effective_prompt, prompt_source = await get_effective_system_prompt_async(request.user, prompt_id, project)

                # 检查当前会话是否已经有系统提示词
                should_add_system_prompt = False
                if effective_prompt:
                    try:
                        # 尝试获取当前会话的历史消息
                        with get_sync_checkpointer() as memory:
                            checkpoint_generator = memory.list(config={"configurable": {"thread_id": thread_id}})
                            checkpoint_tuples_list = list(checkpoint_generator)

                            if checkpoint_tuples_list:
                                # 检查最新checkpoint中是否已有系统提示词
                                latest_checkpoint = checkpoint_tuples_list[0].checkpoint
                                if (latest_checkpoint and 'channel_values' in latest_checkpoint
                                    and 'messages' in latest_checkpoint['channel_values']):
                                    existing_messages = latest_checkpoint['channel_values']['messages']
                                    # 检查第一条消息是否是系统消息
                                    if not existing_messages or not isinstance(existing_messages[0], SystemMessage):
                                        should_add_system_prompt = True
                                else:
                                    should_add_system_prompt = True
                            else:
                                # 新会话，需要添加系统提示词
                                should_add_system_prompt = True
                    except Exception as e:
                        logger.warning(f"ChatAPIView: Error checking existing messages: {e}")
                        should_add_system_prompt = True

                if should_add_system_prompt and effective_prompt:
                    messages_list.append(SystemMessage(content=effective_prompt))
                    logger.info(f"ChatAPIView: Added {prompt_source} system prompt: {effective_prompt[:100]}...")

                clean_user_message = user_message_content.strip()
                clean_user_message, req_image_data_urls, req_doc_id = await _extract_requirement_doc_images_for_message(
                    clean_user_message,
                    project,
                )

                if req_image_data_urls and not active_config.supports_vision:
                    logger.warning(
                        "ChatAPIView: Requirement document images detected but model %s does not support vision; sending text only",
                        active_config.name,
                    )

                # 构建用户消息（支持多模态：上传图片 + 需求文档图片）
                multimodal_parts = []
                if active_config.supports_vision and (image_base64 or req_image_data_urls):
                    multimodal_parts.append({"type": "text", "text": clean_user_message})

                    # 需求文档图片（按占位符出现顺序）
                    for data_url in req_image_data_urls:
                        multimodal_parts.append({"type": "image_url", "image_url": {"url": data_url}})

                    # 用户上传图片（最后追加）
                    if image_base64:
                        multimodal_parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                        })

                    additional_kwargs = {}
                    if req_doc_id:
                        additional_kwargs["requirement_document_id"] = req_doc_id
                        additional_kwargs["image_source"] = "requirement_document"

                    messages_list.append(HumanMessage(content=multimodal_parts, additional_kwargs=additional_kwargs))
                    logger.info("ChatAPIView: Added multimodal message with %s doc images", len(req_image_data_urls))
                else:
                    # 纯文本消息
                    messages_list.append(HumanMessage(content=clean_user_message))
                input_messages = {"messages": messages_list}

                invoke_config = {
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": 1000  # 支持约500次工具调用
                }
                logger.info(f"ChatAPIView: Set recursion_limit to 1000 for thread_id: {thread_id}")
                # Checkpointer is already configured in both agent and basic chatbot

                final_state = await runnable_to_invoke.ainvoke(
                    input_messages,
                    config=invoke_config
                )

                ai_response_content = "No valid AI response found."
                conversation_flow = []  # 存储完整的对话流程

                if final_state and final_state.get('messages'):
                    # 处理所有消息，提取对话流程
                    messages = final_state['messages']
                    logger.info(f"ChatAPIView: Processing {len(messages)} messages in final state")

                    # 找到本次对话的起始位置（用户刚发送的消息）
                    user_message_index = -1
                    def _human_message_text(content):
                        if isinstance(content, list):
                            text_parts = []
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    text_parts.append(item.get("text", ""))
                            return "".join(text_parts)
                        return content

                    for i, msg in enumerate(messages):
                        if isinstance(msg, HumanMessage):
                            msg_text = _human_message_text(getattr(msg, "content", ""))
                            if msg_text == clean_user_message:
                                user_message_index = i
                                break

                    # 如果找到了用户消息，提取从该消息开始的所有后续消息
                    if user_message_index >= 0:
                        current_conversation = messages[user_message_index:]

                        for i, msg in enumerate(current_conversation):
                            msg_type = "unknown"
                            content = ""

                            if isinstance(msg, SystemMessage):
                                msg_type = "system"
                                content = msg.content if hasattr(msg, 'content') else str(msg)
                            elif isinstance(msg, HumanMessage):
                                msg_type = "human"
                                raw_content = msg.content if hasattr(msg, 'content') else str(msg)
                                content = _human_message_text(raw_content)
                            elif isinstance(msg, AIMessage):
                                msg_type = "ai"
                                content = msg.content if hasattr(msg, 'content') else str(msg)

                                # 跳过空的AI消息（工具调用前的中间状态）
                                if not content or content.strip() == "":
                                    logger.debug(f"ChatAPIView: Skipping empty AI message at index {i}")
                                    continue

                            elif isinstance(msg, ToolMessage):
                                msg_type = "tool"
                                content = msg.content if hasattr(msg, 'content') else str(msg)
                            else:
                                # 处理其他类型的消息，可能是工具调用结果
                                content = msg.content if hasattr(msg, 'content') else str(msg)
                                # 如果内容看起来像JSON，可能是工具返回
                                if content.strip().startswith('[') or content.strip().startswith('{'):
                                    msg_type = "tool"
                                else:
                                    msg_type = "unknown"

                            # 只添加有内容的消息
                            if content and content.strip():
                                conversation_flow.append({
                                    "type": msg_type,
                                    "content": content
                                })

                                # 记录最后一条AI消息作为主要回复
                                if msg_type == "ai":
                                    ai_response_content = content

                    # 如果没有找到用户消息，使用最后一条消息作为回复
                    if user_message_index == -1 and messages:
                        last_message = messages[-1]
                        if hasattr(last_message, 'content'):
                            ai_response_content = last_message.content

                logger.info(f"ChatAPIView: Successfully processed message for thread_id: {thread_id}. AI response: {ai_response_content[:100]}...")
                logger.info(f"ChatAPIView: Conversation flow contains {len(conversation_flow)} messages")

                return Response({
                    "status": "success", "code": status.HTTP_200_OK,
                    "message": "Message processed successfully.",
                    "data": {
                        "user_message": user_message_content,
                        "llm_response": ai_response_content,
                        "conversation_flow": conversation_flow,  # 新增：完整的对话流程
                        "active_llm": active_config.name,
                        "thread_id": thread_id,
                        "session_id": session_id,
                        "project_id": project_id,
                        "project_name": project.name,
                        # 知识库相关信息
                        "knowledge_base_id": knowledge_base_id,
                        "use_knowledge_base": use_knowledge_base,
                        "knowledge_base_used": bool(knowledge_base_id and use_knowledge_base)
                    }
                }, status=status.HTTP_200_OK)

        except Exception as e: # This outer try-except catches errors from the 'with SqliteSaver' block or LLM init
            logger.error(f"ChatAPIView: Error interacting with LLM or LangGraph: {e}", exc_info=True)
            return Response({
                "status": "error", "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "message": f"Error interacting with LLM or LangGraph: {str(e)}", "data": {},
                "errors": {"llm_interaction": [str(e)]}
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ChatHistoryAPIView(APIView):
    """
    API endpoint for retrieving chat history for a given session_id.
    支持项目隔离，只能获取指定项目的聊天记录。
    """
    permission_classes = [permissions.IsAuthenticated]

    def _check_project_permission(self, user, project_id):
        """检查用户是否有访问指定项目的权限"""
        try:
            project = Project.objects.get(id=project_id)
            # 超级用户可以访问所有项目
            if user.is_superuser:
                return project
            # 检查用户是否是项目成员
            if ProjectMember.objects.filter(project=project, user=user).exists():
                return project
            return None
        except Project.DoesNotExist:
            return None

    def get(self, request, *args, **kwargs):
        session_id = request.query_params.get('session_id')
        project_id = request.query_params.get('project_id')

        if not session_id:
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "session_id query parameter is required.", "data": {},
                "errors": {"session_id": ["This field is required."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        if not project_id:
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "project_id query parameter is required.", "data": {},
                "errors": {"project_id": ["This field is required."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        # 检查项目权限
        project = self._check_project_permission(request.user, project_id)
        if not project:
            return Response({
                "status": "error", "code": status.HTTP_403_FORBIDDEN,
                "message": "You don't have permission to access this project or project doesn't exist.", "data": {},
                "errors": {"project_id": ["Permission denied or project not found."]}
            }, status=status.HTTP_403_FORBIDDEN)

        # 获取会话信息（包括关联的提示词）
        prompt_id = None
        prompt_name = None
        try:
            chat_session = ChatSession.objects.select_related('prompt').get(
                session_id=session_id,
                user=request.user,
                project_id=project_id
            )
            if chat_session.prompt:
                prompt_id = chat_session.prompt.id
                prompt_name = chat_session.prompt.name
        except ChatSession.DoesNotExist:
            pass  # 会话可能还没创建到数据库

        thread_id_parts = [str(request.user.id), str(project_id), str(session_id)]
        thread_id = "_".join(thread_id_parts)

        history_messages = []

        try:
            # 使用统一的 Checkpointer 读取数据
            from wharttest_django.checkpointer import get_database_type, get_db_connection_string
            db_type = get_database_type()
            conn_str = get_db_connection_string()
            logger.warning(f"ChatHistoryAPIView: DEBUG - database_type={db_type}, connection={conn_str}")
            
            with get_sync_checkpointer() as memory:
                logger.warning(f"ChatHistoryAPIView: DEBUG - Checkpointer type={type(memory).__name__}")
                checkpoint_generator = memory.list(config={"configurable": {"thread_id": thread_id}})
                checkpoint_tuples_list = list(checkpoint_generator)

                logger.info(f"ChatHistoryAPIView: Found {len(checkpoint_tuples_list)} checkpoints for thread_id: {thread_id}")

                if checkpoint_tuples_list: # Check if the list is not empty
                    # 构建消息到时间戳的映射
                    # 遍历所有checkpoints，为每条新消息分配对应checkpoint的时间戳
                    message_timestamps = {}
                    processed_message_count = 0

                    # 按时间顺序处理checkpoints（从旧到新）
                    for checkpoint_tuple in reversed(checkpoint_tuples_list):
                        if checkpoint_tuple and hasattr(checkpoint_tuple, 'checkpoint'):
                            checkpoint_data = checkpoint_tuple.checkpoint
                            if checkpoint_data and 'channel_values' in checkpoint_data and 'messages' in checkpoint_data['channel_values']:
                                messages = checkpoint_data['channel_values']['messages']
                                current_message_count = len(messages)

                                # 如果这个checkpoint有新消息，为新消息分配时间戳
                                if current_message_count > processed_message_count:
                                    checkpoint_timestamp = checkpoint_data.get('ts')
                                    if checkpoint_timestamp:
                                        # 为新增的消息分配时间戳
                                        for i in range(processed_message_count, current_message_count):
                                            message_timestamps[i] = checkpoint_timestamp
                                    processed_message_count = current_message_count

                    # 获取最新checkpoint的消息列表
                    latest_checkpoint_tuple = checkpoint_tuples_list[0]
                    logger.info(f"ChatHistoryAPIView: latest_checkpoint_tuple type={type(latest_checkpoint_tuple).__name__}")
                    if latest_checkpoint_tuple and hasattr(latest_checkpoint_tuple, 'checkpoint'):
                        checkpoint_data = latest_checkpoint_tuple.checkpoint
                        logger.info(f"ChatHistoryAPIView: checkpoint_data type={type(checkpoint_data).__name__}, keys={list(checkpoint_data.keys()) if isinstance(checkpoint_data, dict) else 'N/A'}")
                        if isinstance(checkpoint_data, dict) and 'channel_values' in checkpoint_data:
                            channel_values = checkpoint_data['channel_values']
                            logger.info(f"ChatHistoryAPIView: channel_values keys={list(channel_values.keys()) if isinstance(channel_values, dict) else 'N/A'}")

                        if checkpoint_data and 'channel_values' in checkpoint_data and 'messages' in checkpoint_data['channel_values']:
                            messages = checkpoint_data['channel_values']['messages']
                            logger.info(f"ChatHistoryAPIView: Found {len(messages)} messages in latest checkpoint")

                            for i, msg in enumerate(messages):
                                msg_type = "unknown"
                                content = ""

                                if isinstance(msg, SystemMessage):
                                    msg_type = "system"
                                    content = msg.content if hasattr(msg, 'content') else str(msg)
                                elif isinstance(msg, HumanMessage):
                                    msg_type = "human"
                                    raw_content = msg.content if hasattr(msg, 'content') else str(msg)
                                    # 处理多模态消息（包含图片的列表格式）
                                    image_data = None  # 用于存储图片数据（仅用于“上传图片”这类单图消息）
                                    if isinstance(raw_content, list):
                                        # 提取文本部分 + 图片部分
                                        text_parts = []
                                        image_urls = []
                                        for item in raw_content:
                                            if isinstance(item, dict):
                                                if item.get("type") == "text":
                                                    text_parts.append(item.get("text", ""))
                                                elif item.get("type") == "image_url":
                                                    # 提取图片URL中的Base64数据
                                                    image_url = item.get("image_url", {})
                                                    if isinstance(image_url, dict):
                                                        url = image_url.get("url", "")
                                                        # url格式: data:image/jpeg;base64,xxx
                                                        if url and url.startswith("data:image/"):
                                                            image_urls.append(url)

                                        # 保留原文本格式（拼接而不是用空格连接），避免破坏Markdown/换行
                                        content = "".join(text_parts) if text_parts else "[包含图片的消息]"

                                        # 如果文本中已经包含需求文档图片占位符/URL，则不再通过 image 字段额外展示图片，避免重复
                                        has_requirement_doc_images = (
                                            isinstance(content, str)
                                            and ("docimg://" in content or "/api/requirements/documents/" in content)
                                        )

                                        # 仅对“单图上传”这类消息保留 image 字段
                                        if image_urls and (len(image_urls) == 1) and not has_requirement_doc_images:
                                            image_data = image_urls[0]
                                    else:
                                        content = raw_content
                                elif isinstance(msg, AIMessage):
                                    msg_type = "ai"
                                    raw_content = msg.content if hasattr(msg, 'content') else str(msg)
                                    # AI消息通常不是多模态，但为了安全也检查一下
                                    if isinstance(raw_content, list):
                                        text_parts = [item.get("text", "") for item in raw_content if isinstance(item, dict) and item.get("type") == "text"]
                                        content = " ".join(text_parts) if text_parts else ""
                                    else:
                                        content = raw_content

                                    # 跳过空的AI消息（工具调用前的中间状态）
                                    if not content or (isinstance(content, str) and content.strip() == ""):
                                        logger.debug(f"ChatHistoryAPIView: Skipping empty AI message at index {i}")
                                        continue
                                    
                                    # ⭐ 提取 additional_kwargs 中的 metadata（包含 Agent Loop 元数据）
                                    agent_info = None
                                    agent_type = None
                                    step = None
                                    max_steps = None
                                    sse_event_type = None
                                    
                                    if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs:
                                        # 兼容旧格式（直接存在 additional_kwargs）
                                        agent_info = msg.additional_kwargs.get('agent')
                                        agent_type = msg.additional_kwargs.get('agent_type')
                                        
                                        # ⭐ 从 metadata 子字段提取（新格式）
                                        metadata = msg.additional_kwargs.get('metadata', {})
                                        if metadata:
                                            agent_info = agent_info or metadata.get('agent')
                                            agent_type = agent_type or metadata.get('agent_type')
                                            step = metadata.get('step')
                                            max_steps = metadata.get('max_steps')
                                            sse_event_type = metadata.get('sse_event_type')
                                        
                                        logger.debug(f"ChatHistoryAPIView: AI message metadata - agent: {agent_info}, type: {agent_type}, step: {step}, sse_type: {sse_event_type}")

                                elif isinstance(msg, ToolMessage):
                                    msg_type = "tool"
                                    content = msg.content if hasattr(msg, 'content') else str(msg)
                                    
                                    # ⭐ 提取工具消息的元数据
                                    step = None
                                    sse_event_type = None
                                    if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs:
                                        metadata = msg.additional_kwargs.get('metadata', {})
                                        if metadata:
                                            step = metadata.get('step')
                                            sse_event_type = metadata.get('sse_event_type')
                                        logger.debug(f"ChatHistoryAPIView: Tool message metadata - step: {step}, sse_type: {sse_event_type}")
                                else:
                                    # 处理其他类型的消息，可能是工具调用结果
                                    content = msg.content if hasattr(msg, 'content') else str(msg)
                                    # 如果内容看起来像JSON，可能是工具返回
                                    if content.strip().startswith('[') or content.strip().startswith('{'):
                                        msg_type = "tool"
                                    else:
                                        msg_type = "unknown"

                                logger.debug(f"ChatHistoryAPIView: Message {i}: type={msg_type}, content={str(content)[:50]}...")

                                # 只添加有内容的消息
                                if content and (not isinstance(content, str) or content.strip()):
                                    message_data = {
                                        "type": msg_type,
                                        "content": content,
                                    }
                                    # 如果消息包含图片，添加图片数据
                                    if msg_type == "human" and image_data:
                                        message_data["image"] = image_data
                                    
                                    # ⭐ 如果 AI 消息包含 agent 信息（Agent Loop），添加完整元数据
                                    if msg_type == "ai":
                                        if 'agent_info' in locals() and agent_info:
                                            message_data["agent"] = agent_info
                                        if 'agent_type' in locals() and agent_type:
                                            message_data["agent_type"] = agent_type
                                        if 'step' in locals() and step is not None:
                                            message_data["step"] = step  # ⭐ 步骤号
                                        if 'max_steps' in locals() and max_steps is not None:
                                            message_data["max_steps"] = max_steps
                                        if 'sse_event_type' in locals() and sse_event_type:
                                            message_data["sse_event_type"] = sse_event_type  # ⭐ SSE 事件类型
                                        
                                        # 检查是否是思考过程消息
                                        if hasattr(msg, 'additional_kwargs') and msg.additional_kwargs:
                                            metadata = msg.additional_kwargs.get('metadata', {})
                                            if metadata.get('is_thinking_process'):
                                                message_data["is_thinking_process"] = True
                                    
                                    # ⭐ 如果是工具消息，添加步骤号和事件类型
                                    elif msg_type == "tool":
                                        if 'step' in locals() and step is not None:
                                            message_data["step"] = step
                                        if 'sse_event_type' in locals() and sse_event_type:
                                            message_data["sse_event_type"] = sse_event_type
                                    
                                    # 添加对应的时间戳
                                    if i in message_timestamps:
                                        timestamp_str = message_timestamps[i]
                                        try:
                                            # 解析ISO时间戳并转换为本地时间
                                            from datetime import datetime
                                            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                                            # 转换为本地时间
                                            local_dt = dt.astimezone()
                                            # 格式化为本地时间字符串
                                            message_data["timestamp"] = local_dt.strftime("%Y-%m-%d %H:%M:%S")
                                        except Exception as e:
                                            # 如果解析失败，只返回原始字符串
                                            logger.warning(f"ChatHistoryAPIView: Failed to parse timestamp {timestamp_str}: {e}")
                                            message_data["timestamp"] = timestamp_str

                                    history_messages.append(message_data)
                        else:
                            logger.warning(f"ChatHistoryAPIView: No messages found in checkpoint data structure")
                    else:
                        logger.warning(f"ChatHistoryAPIView: Invalid checkpoint tuple structure")
                else:
                    logger.info(f"ChatHistoryAPIView: No checkpoints found for thread_id: {thread_id}")
            # By processing only the latest checkpoint, we get the final state of messages, avoiding duplicates.

            # 计算上下文Token使用信息
            context_token_count = 0
            context_limit = 128000
            try:
                from requirements.context_limits import context_checker
                active_config = LLMConfig.objects.get(is_active=True)
                context_limit = active_config.context_limit or 128000
                
                for msg_data in history_messages:
                    content = msg_data.get('content', '')
                    if content:
                        content_str = content if isinstance(content, str) else str(content)
                        context_token_count += context_checker.count_tokens(content_str, active_config.name or "gpt-4o")
            except Exception as e:
                logger.warning(f"ChatHistoryAPIView: Failed to calculate token count: {e}")

            return Response({
                "status": "success", "code": status.HTTP_200_OK,
                "message": "Chat history retrieved successfully.",
                "data": {
                    "thread_id": thread_id,
                    "session_id": session_id,
                    "project_id": project_id,
                    "project_name": project.name,
                    "prompt_id": prompt_id,
                    "prompt_name": prompt_name,
                    "history": history_messages,
                    "context_token_count": context_token_count,
                    "context_limit": context_limit
                }
            }, status=status.HTTP_200_OK)

        except FileNotFoundError:
             return Response({
                "status": "success", "code": status.HTTP_200_OK, # Or 404 if preferred for no history file
                "message": "No chat history found for this session (history file does not exist).",
                "data": {
                    "thread_id": thread_id,
                    "session_id": session_id,
                    "history": []
                }
            }, status=status.HTTP_200_OK)
        except Exception as e:
            # import logging
            # logging.exception(f"Error retrieving chat history for thread_id {thread_id}")
            return Response({
                "status": "error", "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "message": f"Error retrieving chat history: {str(e)}", "data": {},
                "errors": {"history_retrieval": [str(e)]}
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, *args, **kwargs):
        session_id = request.query_params.get('session_id')
        project_id = request.query_params.get('project_id')

        if not session_id:
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "session_id query parameter is required.", "data": {},
                "errors": {"session_id": ["This field is required."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        if not project_id:
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "project_id query parameter is required.", "data": {},
                "errors": {"project_id": ["This field is required."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        # 检查项目权限
        project = self._check_project_permission(request.user, project_id)
        if not project:
            return Response({
                "status": "error", "code": status.HTTP_403_FORBIDDEN,
                "message": "You don't have permission to access this project or project doesn't exist.", "data": {},
                "errors": {"project_id": ["Permission denied or project not found."]}
            }, status=status.HTTP_403_FORBIDDEN)

        thread_id_parts = [str(request.user.id), str(project_id), str(session_id)]
        thread_id = "_".join(thread_id_parts)

        if not check_history_exists():
            return Response({
                "status": "success",
                "code": status.HTTP_200_OK,
                "message": "No chat history found to delete (history storage does not exist).",
                "data": {"thread_id": thread_id, "session_id": session_id, "deleted_count": 0}
            }, status=status.HTTP_200_OK)

        try:
            deleted_count = delete_checkpoints_by_thread_id(thread_id)

            # 同时删除 Django ChatSession 记录
            django_deleted_count = 0
            try:
                deleted_result = ChatSession.objects.filter(
                    session_id=session_id,
                    user=request.user,
                    project=project
                ).delete()
                django_deleted_count = deleted_result[0]
                logger.info(f"ChatHistoryAPIView: Deleted {django_deleted_count} ChatSession records for session_id: {session_id}")
            except Exception as e:
                logger.warning(f"ChatHistoryAPIView: Failed to delete ChatSession for {session_id}: {e}")

            if deleted_count > 0 or django_deleted_count > 0:
                message = f"Successfully deleted chat history for session_id: {session_id} (Thread ID: {thread_id}). {deleted_count} checkpoint records and {django_deleted_count} session records removed."
            else:
                message = f"No chat history found for session_id: {session_id} (Thread ID: {thread_id}) to delete."

            return Response({
                "status": "success", "code": status.HTTP_200_OK,
                "message": message,
                "data": {"thread_id": thread_id, "session_id": session_id, "deleted_count": deleted_count, "session_deleted_count": django_deleted_count}
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({
                "status": "error", "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "message": f"Database error while deleting chat history: {str(e)}", "data": {},
                "errors": {"database_error": [str(e)]}
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def patch(self, request, *args, **kwargs):
        """
        回滚聊天历史到指定消息数量
        保留前 keep_count 条消息，删除之后的所有消息
        """
        session_id = request.query_params.get('session_id')
        project_id = request.query_params.get('project_id')
        keep_count = request.data.get('keep_count')

        if not session_id:
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "session_id query parameter is required.", "data": {},
                "errors": {"session_id": ["This field is required."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        if not project_id:
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "project_id query parameter is required.", "data": {},
                "errors": {"project_id": ["This field is required."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        if keep_count is None or not isinstance(keep_count, int) or keep_count < 0:
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "keep_count must be a non-negative integer.", "data": {},
                "errors": {"keep_count": ["This field must be a non-negative integer."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        # 检查项目权限
        project = self._check_project_permission(request.user, project_id)
        if not project:
            return Response({
                "status": "error", "code": status.HTTP_403_FORBIDDEN,
                "message": "You don't have permission to access this project or project doesn't exist.", "data": {},
                "errors": {"project_id": ["Permission denied or project not found."]}
            }, status=status.HTTP_403_FORBIDDEN)

        thread_id_parts = [str(request.user.id), str(project_id), str(session_id)]
        thread_id = "_".join(thread_id_parts)

        if not check_history_exists():
            return Response({
                "status": "success",
                "code": status.HTTP_200_OK,
                "message": "No chat history found to rollback (history storage does not exist).",
                "data": {"thread_id": thread_id, "session_id": session_id, "deleted_count": 0}
            }, status=status.HTTP_200_OK)

        try:
            deleted_count = rollback_checkpoints_to_count(thread_id, keep_count)

            if deleted_count > 0:
                message = f"Successfully rolled back chat history for session_id: {session_id}. Kept {keep_count} checkpoints, removed {deleted_count} checkpoints."
            else:
                message = f"No checkpoints to remove for session_id: {session_id}. Current count is already at or below {keep_count}."

            logger.info(f"ChatHistoryAPIView PATCH: {message}")

            return Response({
                "status": "success", "code": status.HTTP_200_OK,
                "message": message,
                "data": {"thread_id": thread_id, "session_id": session_id, "deleted_count": deleted_count, "kept_count": keep_count}
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"ChatHistoryAPIView PATCH error: {str(e)}")
            return Response({
                "status": "error", "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "message": f"Database error while rolling back chat history: {str(e)}", "data": {},
                "errors": {"database_error": [str(e)]}
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ChatBatchDeleteAPIView(APIView):
    """
    API endpoint for batch deleting chat sessions.
    批量删除聊天会话的API端点。
    """
    permission_classes = [permissions.IsAuthenticated]

    def _check_project_permission(self, user, project_id):
        """检查用户是否有访问指定项目的权限"""
        try:
            project = Project.objects.get(id=project_id)
            # 超级用户可以访问所有项目
            if user.is_superuser:
                return project
            # 检查用户是否是项目成员
            if ProjectMember.objects.filter(project=project, user=user).exists():
                return project
            return None
        except Project.DoesNotExist:
            return None

    def post(self, request, *args, **kwargs):
        """批量删除聊天会话"""
        session_ids = request.data.get('session_ids', [])
        project_id = request.data.get('project_id')

        if not session_ids or not isinstance(session_ids, list):
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "session_ids must be a non-empty list.", "data": {},
                "errors": {"session_ids": ["This field is required and must be a list."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        if not project_id:
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "project_id is required.", "data": {},
                "errors": {"project_id": ["This field is required."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        # 检查项目权限
        project = self._check_project_permission(request.user, project_id)
        if not project:
            return Response({
                "status": "error", "code": status.HTTP_403_FORBIDDEN,
                "message": "You don't have permission to access this project or project doesn't exist.", "data": {},
                "errors": {"project_id": ["Permission denied or project not found."]}
            }, status=status.HTTP_403_FORBIDDEN)

        if not check_history_exists():
            return Response({
                "status": "success",
                "code": status.HTTP_200_OK,
                "message": "No chat history found to delete (history storage does not exist).",
                "data": {"deleted_count": 0, "failed_sessions": []}
            }, status=status.HTTP_200_OK)

        total_deleted = 0
        failed_sessions = []
        
        try:
            # 构建所有 thread_ids
            thread_ids = []
            for session_id in session_ids:
                thread_id_parts = [str(request.user.id), str(project_id), str(session_id)]
                thread_ids.append("_".join(thread_id_parts))
            
            # 批量删除 checkpoints
            total_deleted = delete_checkpoints_batch(thread_ids)
            
            # 删除 Django 中的 ChatSession 记录
            for session_id in session_ids:
                try:
                    ChatSession.objects.filter(
                        session_id=session_id,
                        user=request.user,
                        project=project
                    ).delete()
                except Exception as e:
                    logger.warning(f"Failed to delete ChatSession for {session_id}: {e}")
                    failed_sessions.append({
                        "session_id": session_id,
                        "reason": str(e)
                    })

            message = f"Successfully deleted {total_deleted} checkpoint records from {len(session_ids)} sessions."
            if failed_sessions:
                message += f" {len(failed_sessions)} sessions had issues with Django model deletion."

            return Response({
                "status": "success", "code": status.HTTP_200_OK,
                "message": message,
                "data": {
                    "deleted_count": total_deleted,
                    "processed_sessions": len(session_ids),
                    "failed_sessions": failed_sessions
                }
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error during batch delete: {e}", exc_info=True)
            return Response({
                "status": "error", "code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "message": f"Database error while batch deleting chat history: {str(e)}", "data": {},
                "errors": {"database_error": [str(e)]}
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UserChatSessionsAPIView(APIView):
    """
    API endpoint for listing all chat sessions for the authenticated user in a specific project.
    支持项目隔离，只返回指定项目的聊天会话。
    优先从Django ChatSession模型读取（带标题和时间），回退到sqlite查询session_id。
    """
    permission_classes = [permissions.IsAuthenticated]

    def _check_project_permission(self, user, project_id):
        """检查用户是否有访问指定项目的权限"""
        try:
            project = Project.objects.get(id=project_id)
            # 超级用户可以访问所有项目
            if user.is_superuser:
                return project
            # 检查用户是否是项目成员
            if ProjectMember.objects.filter(project=project, user=user).exists():
                return project
            return None
        except Project.DoesNotExist:
            return None

    def get(self, request, *args, **kwargs):
        user_id = str(request.user.id)
        project_id = request.query_params.get('project_id')

        if not project_id:
            return Response({
                "status": "error", "code": status.HTTP_400_BAD_REQUEST,
                "message": "project_id query parameter is required.", "data": {},
                "errors": {"project_id": ["This field is required."]}
            }, status=status.HTTP_400_BAD_REQUEST)

        # 检查项目权限
        project = self._check_project_permission(request.user, project_id)
        if not project:
            return Response({
                "status": "error", "code": status.HTTP_403_FORBIDDEN,
                "message": "You don't have permission to access this project or project doesn't exist.", "data": {},
                "errors": {"project_id": ["Permission denied or project not found."]}
            }, status=status.HTTP_403_FORBIDDEN)

        # 优先从Django ChatSession模型读取会话列表（带标题和时间，无需查sqlite）
        django_sessions = ChatSession.objects.filter(
            user=request.user,
            project_id=project_id
        ).order_by('-updated_at').values('session_id', 'title', 'updated_at', 'created_at')
        
        sessions_list = []
        django_session_ids = set()
        
        for s in django_sessions:
            django_session_ids.add(s['session_id'])
            sessions_list.append({
                'id': s['session_id'],
                'title': s['title'] or '新对话',
                'updated_at': s['updated_at'].isoformat() if s['updated_at'] else None,
                'created_at': s['created_at'].isoformat() if s['created_at'] else None,
            })
        
        # 回退：检查checkpoints中是否有Django模型没记录的会话
        if check_history_exists():
            try:
                thread_id_prefix = f"{user_id}_{project_id}_"
                thread_ids = get_thread_ids_by_prefix(thread_id_prefix)
                
                for full_thread_id in thread_ids:
                    if full_thread_id.startswith(thread_id_prefix):
                        session_id_part = full_thread_id[len(thread_id_prefix):]
                        if session_id_part and session_id_part not in django_session_ids:
                            # checkpoints有但Django没有的会话，添加到列表
                            sessions_list.append({
                                'id': session_id_part,
                                'title': f'会话 {session_id_part[:8]}...',
                                'updated_at': None,
                                'created_at': None,
                            })
            except Exception as e:
                logger.warning(f"UserChatSessionsAPIView: Failed to check checkpoints for additional sessions: {e}")

        return Response({
            "status": "success", "code": status.HTTP_200_OK,
            "message": "User chat sessions retrieved successfully.",
            "data": {
                "user_id": user_id,
                "project_id": project_id,
                "project_name": project.name,
                "sessions": [s['id'] for s in sessions_list],  # 保持向后兼容
                "sessions_detail": sessions_list  # 新增：带详情的会话列表
            }
        }, status=status.HTTP_200_OK)


from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed

@method_decorator(csrf_exempt, name='dispatch')
class ChatStreamAPIView(View):
    """
    API endpoint for streaming chat with the currently active LLM using LangGraph,
    with potential integration of remote MCP tools.
    支持项目隔离，聊天记录按项目分组。
    使用Server-Sent Events (SSE)实现流式响应。
    使用Django原生View绕过DRF的渲染器系统。
    """

    async def authenticate_request(self, request):
        """手动进行JWT认证（异步版本）"""
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if not auth_header or not auth_header.startswith('Bearer '):
            raise AuthenticationFailed('Authentication credentials were not provided.')

        token = auth_header.split(' ')[1]
        jwt_auth = JWTAuthentication()

        try:
            # 在异步上下文中使用sync_to_async包装同步方法
            validated_token = await sync_to_async(jwt_auth.get_validated_token)(token)
            user = await sync_to_async(jwt_auth.get_user)(validated_token)
            return user
        except Exception as e:
            raise AuthenticationFailed(f'Invalid token: {str(e)}')

    def _check_project_permission(self, user, project_id):
        """检查用户是否有访问指定项目的权限"""
        try:
            project = Project.objects.get(id=project_id)
            # 超级用户可以访问所有项目
            if user.is_superuser:
                return project
            # 检查用户是否是项目成员
            if ProjectMember.objects.filter(project=project, user=user).exists():
                return project
            return None
        except Project.DoesNotExist:
            return None

    async def _create_sse_generator(self, request, user_message_content, session_id, project_id, project,
                                   knowledge_base_id=None, use_knowledge_base=True, similarity_threshold=0.7, top_k=5, prompt_id=None, image_base64=None):
        """创建SSE数据生成器"""
        try:
            # 获取活跃的LLM配置
            active_config = await sync_to_async(LLMConfig.objects.get)(is_active=True)
            logger.info(f"ChatStreamAPIView: Using active LLMConfig: {active_config.name}")
        except LLMConfig.DoesNotExist:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No active LLM configuration found'})}\n\n"
            return
        except LLMConfig.MultipleObjectsReturned:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Multiple active LLM configurations found'})}\n\n"
            return

        # 验证图片输入是否支持
        if image_base64 and not active_config.supports_vision:
            logger.warning(f"ChatStreamAPIView: Image input rejected - model {active_config.name} does not support vision")
            yield f"data: {json.dumps({'type': 'error', 'message': f'当前模型 {active_config.name} 不支持图片输入，请切换到支持多模态的模型（如 GPT-4V、Claude 3、Gemini Vision 或 Qwen-VL）'})}\n\n"
            return

        try:
            # 使用新的LLM工厂函数，支持多供应商
            llm = create_llm_instance(active_config, temperature=0.7)
            logger.info(f"ChatStreamAPIView: Initialized LLM with provider auto-detection")

            async with get_async_checkpointer() as actual_memory_checkpointer:
                # 加载远程MCP工具
                logger.info("ChatStreamAPIView: Attempting to load remote MCP tools.")
                mcp_tools_list = []
                try:
                    active_remote_mcp_configs_qs = RemoteMCPConfig.objects.filter(is_active=True)
                    active_remote_mcp_configs = await sync_to_async(list)(active_remote_mcp_configs_qs)

                    if active_remote_mcp_configs:
                        client_mcp_config = {}
                        for r_config in active_remote_mcp_configs:
                            config_key = r_config.name or f"remote_config_{r_config.id}"
                            client_mcp_config[config_key] = {
                                "url": r_config.url,
                                "transport": (r_config.transport or "streamable_http").replace('-', '_'),
                            }
                            if r_config.headers and isinstance(r_config.headers, dict) and r_config.headers:
                                client_mcp_config[config_key]["headers"] = r_config.headers

                        if client_mcp_config:
                            logger.info(f"ChatStreamAPIView: Initializing persistent MCP client with config: {client_mcp_config}")
                            # 使用持久化MCP会话管理器，传递用户、项目和会话信息以支持跨对话轮次的状态保持
                            mcp_tools_list = await mcp_session_manager.get_tools_for_config(
                                client_mcp_config,
                                user_id=str(request.user.id),
                                project_id=str(project_id),
                                session_id=session_id  # 传递session_id以启用会话级别的工具缓存
                            )
                            logger.info(f"ChatStreamAPIView: Successfully loaded {len(mcp_tools_list)} persistent tools from remote MCP servers")
                        else:
                            logger.info("ChatStreamAPIView: No active remote MCP configurations to build client config.")
                    else:
                        logger.info("ChatStreamAPIView: No active RemoteMCPConfig found.")
                except Exception as e:
                    logger.error(f"ChatStreamAPIView: Error loading remote MCP tools: {e}", exc_info=True)
                    yield f"data: {json.dumps({'type': 'warning', 'message': f'Failed to load MCP tools: {str(e)}'})}\n\n"

                # 准备LangGraph runnable
                runnable_to_invoke = None

                # 检查是否需要创建Agent（有MCP工具）
                if mcp_tools_list:
                    logger.info(f"ChatStreamAPIView: Attempting to create agent with {len(mcp_tools_list)} remote tools.")
                    try:
                        # 如果同时有知识库和MCP工具，创建知识库增强的Agent
                        if knowledge_base_id and use_knowledge_base:
                            logger.info(f"ChatStreamAPIView: Creating knowledge-enhanced agent with {len(mcp_tools_list)} tools and knowledge base {knowledge_base_id}")

                            # 创建知识库工具
                            from knowledge.langgraph_integration import create_knowledge_tool
                            knowledge_tool = create_knowledge_tool(
                                knowledge_base_id=knowledge_base_id,
                                user=request.user,
                                similarity_threshold=similarity_threshold,
                                top_k=top_k
                            )

                            # 将知识库工具添加到MCP工具列表
                            enhanced_tools = mcp_tools_list + [knowledge_tool]
                            agent_executor = create_react_agent(llm, enhanced_tools, checkpointer=actual_memory_checkpointer)
                            runnable_to_invoke = agent_executor
                            logger.info(f"ChatStreamAPIView: Knowledge-enhanced agent created with {len(enhanced_tools)} tools (including knowledge base)")
                            yield create_sse_data({'type': 'info', 'message': f'Knowledge-enhanced agent initialized with {len(enhanced_tools)} tools'})
                        else:
                            # 只有MCP工具，创建普通Agent
                            agent_executor = create_react_agent(llm, mcp_tools_list, checkpointer=actual_memory_checkpointer)
                            runnable_to_invoke = agent_executor
                            logger.info("ChatStreamAPIView: Agent with remote tools created with checkpointer.")
                            yield create_sse_data({'type': 'info', 'message': f'Agent initialized with {len(mcp_tools_list)} tools'})
                    except Exception as e:
                        logger.error(f"ChatStreamAPIView: Failed to create agent with remote tools: {e}. Falling back to knowledge-enhanced chatbot.", exc_info=True)
                        yield create_sse_data({'type': 'warning', 'message': 'Failed to create agent with tools, using knowledge-enhanced chatbot'})

                if not runnable_to_invoke:
                    logger.info("ChatStreamAPIView: No remote tools or agent creation failed. Using knowledge-enhanced chatbot.")

                    def knowledge_enhanced_chatbot_node(state: AgentState):
                        """知识库增强的聊天机器人节点"""
                        messages = state['messages']
                        if not messages:
                            return {"messages": []}

                        # 获取最后一条用户消息
                        last_message = messages[-1]
                        if hasattr(last_message, 'content'):
                            user_query = last_message.content
                        else:
                            user_query = str(last_message)

                        # 检查是否需要使用知识库
                        if knowledge_base_id and use_knowledge_base:
                            try:
                                # 使用知识库增强回答
                                from knowledge.langgraph_integration import KnowledgeRAGService
                                rag_service = KnowledgeRAGService(llm)
                                rag_result = rag_service.query(
                                    question=user_query,
                                    knowledge_base_id=knowledge_base_id,
                                    user=request.user,
                                    similarity_threshold=similarity_threshold,
                                    top_k=top_k
                                )

                                # 使用RAG结果作为上下文
                                context_prompt = f"基于以下相关信息回答用户问题：\n\n{rag_result['context']}\n\n用户问题：{user_query}"
                                enhanced_messages = messages[:-1] + [HumanMessage(content=context_prompt)]
                                invoked_response = llm.invoke(enhanced_messages)
                                logger.info(f"ChatStreamAPIView: Used knowledge base {knowledge_base_id} for enhanced response")

                            except Exception as e:
                                logger.warning(f"ChatStreamAPIView: Knowledge base query failed: {e}, falling back to normal response")
                                invoked_response = llm.invoke(messages)
                        else:
                            # 普通聊天回复
                            invoked_response = llm.invoke(messages)

                        return {"messages": [invoked_response]}

                    graph_builder = StateGraph(AgentState)
                    graph_builder.add_node("chatbot", knowledge_enhanced_chatbot_node)
                    graph_builder.set_entry_point("chatbot")
                    graph_builder.add_edge("chatbot", END)
                    runnable_to_invoke = graph_builder.compile(checkpointer=actual_memory_checkpointer)

                    if knowledge_base_id and use_knowledge_base:
                        logger.info(f"ChatStreamAPIView: Knowledge-enhanced chatbot initialized with KB: {knowledge_base_id}")
                        yield create_sse_data({'type': 'info', 'message': f'Knowledge-enhanced chatbot initialized with knowledge base'})
                    else:
                        logger.info("ChatStreamAPIView: Basic chatbot initialized")
                        yield create_sse_data({'type': 'info', 'message': 'Basic chatbot initialized'})

                # 确定thread_id - 包含项目ID以实现项目隔离
                thread_id_parts = [str(request.user.id), str(project_id)]
                if session_id:
                    thread_id_parts.append(str(session_id))
                thread_id = "_".join(thread_id_parts)
                logger.info(f"ChatStreamAPIView: Using thread_id: {thread_id} for project: {project.name}")

                # 预加载 checkpoint 数据（供系统提示词检查和上下文压缩共用）
                checkpoint_tuples_list = []
                try:
                    async for checkpoint_tuple in actual_memory_checkpointer.alist(config={"configurable": {"thread_id": thread_id}}):
                        checkpoint_tuples_list.append(checkpoint_tuple)
                except Exception as e:
                    logger.warning(f"ChatStreamAPIView: Failed to load checkpoint history: {e}")
                
                # 构建消息列表，检查是否需要添加系统提示词
                messages_list = []

                # 获取有效的系统提示词（用户提示词优先，并注入项目凭据信息）
                effective_prompt, prompt_source = await get_effective_system_prompt_async(request.user, prompt_id, project)
                logger.info(f"ChatStreamAPIView: Using {prompt_source} prompt: {repr(effective_prompt[:100] if effective_prompt else None)}")

                # 检查当前会话是否已经有系统提示词
                should_add_system_prompt = False
                if effective_prompt:
                    try:
                        # 使用预加载的 checkpoint 数据检查
                        if checkpoint_tuples_list:
                            # 检查最新checkpoint中是否已有系统提示词
                            latest_checkpoint = checkpoint_tuples_list[0].checkpoint
                            if (latest_checkpoint and 'channel_values' in latest_checkpoint
                                and 'messages' in latest_checkpoint['channel_values']):
                                existing_messages = latest_checkpoint['channel_values']['messages']
                                # 检查第一条消息是否是系统消息
                                if not existing_messages or not isinstance(existing_messages[0], SystemMessage):
                                    should_add_system_prompt = True
                            else:
                                should_add_system_prompt = True
                        else:
                            # 新会话，需要添加系统提示词
                            should_add_system_prompt = True
                    except Exception as e:
                        logger.warning(f"ChatStreamAPIView: Error checking existing messages: {e}")
                        should_add_system_prompt = True

                    if should_add_system_prompt:
                        messages_list.append(SystemMessage(content=effective_prompt))
                        logger.info(f"ChatStreamAPIView: Added {prompt_source} system prompt: {effective_prompt[:100]}...")
                else:
                    logger.info("ChatStreamAPIView: No system prompt available")

                # 验证用户消息内容不为空
                if not user_message_content or not user_message_content.strip():
                    logger.error("ChatStreamAPIView: User message content is empty or whitespace only")
                    yield create_sse_data({'type': 'error', 'message': 'User message content cannot be empty'})
                    return

                # 确保用户消息内容格式正确
                clean_user_message = user_message_content.strip()
                clean_user_message, req_image_data_urls, req_doc_id = await _extract_requirement_doc_images_for_message(
                    clean_user_message,
                    project,
                )
                if not clean_user_message and not image_base64:
                    logger.error("ChatStreamAPIView: User message is empty after stripping")
                    yield create_sse_data({'type': 'error', 'message': 'User message cannot be empty'})
                    return

                # 构建用户消息（支持多模态）
                if req_image_data_urls and not active_config.supports_vision:
                    logger.warning(
                        "ChatStreamAPIView: Requirement document images detected but model %s does not support vision; sending text only",
                        active_config.name,
                    )

                if active_config.supports_vision and (image_base64 or req_image_data_urls):
                    multimodal_parts = [{"type": "text", "text": clean_user_message}]

                    # 需求文档图片（按占位符出现顺序）
                    for data_url in req_image_data_urls:
                        multimodal_parts.append({"type": "image_url", "image_url": {"url": data_url}})

                    # 用户上传图片（最后追加）
                    if image_base64:
                        multimodal_parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                        })

                    additional_kwargs = {}
                    if req_doc_id:
                        additional_kwargs["requirement_document_id"] = req_doc_id
                        additional_kwargs["image_source"] = "requirement_document"

                    messages_list.append(HumanMessage(content=multimodal_parts, additional_kwargs=additional_kwargs))
                    logger.info(
                        "ChatStreamAPIView: Added multimodal message (doc_images=%s, uploaded_image=%s)",
                        len(req_image_data_urls),
                        bool(image_base64),
                    )
                else:
                    # 纯文本消息
                    messages_list.append(HumanMessage(content=clean_user_message))
                logger.info(f"ChatStreamAPIView: Final messages list length: {len(messages_list)}")

                # 验证消息列表不为空且所有消息都有有效内容
                if not messages_list:
                    logger.error("ChatStreamAPIView: Messages list is empty")
                    yield create_sse_data({'type': 'error', 'message': 'No valid messages to process'})
                    return

                for i, msg in enumerate(messages_list):
                    if not hasattr(msg, 'content') or not msg.content or not str(msg.content).strip():
                        logger.error(f"ChatStreamAPIView: Message at index {i} has empty content: {msg}")
                        yield create_sse_data({'type': 'error', 'message': f'Message at index {i} has invalid content'})
                        return
                    logger.info(f"ChatStreamAPIView: Message {i}: {type(msg).__name__} with content length {len(str(msg.content))}")

                # 上下文检查与压缩
                context_limit = active_config.context_limit or 128000
                try:
                    from requirements.context_limits import context_checker
                    
                    # 初始化压缩器
                    compression_settings = CompressionSettings(
                        max_context_tokens=context_limit,
                        trigger_ratio=0.75
                    )
                    conversation_compressor = ConversationCompressor(
                        llm=llm,
                        model_name=active_config.name or getattr(llm, "model_name", "gpt-4o"),
                        settings=compression_settings
                    )
                    
                    # 从预加载的 checkpoint 获取历史消息和压缩状态
                    latest_checkpoint_tuple = checkpoint_tuples_list[0] if checkpoint_tuples_list else None
                    history_messages = []
                    existing_metadata = {}
                    summary_text = None
                    summarized_count = 0
                    
                    if latest_checkpoint_tuple:
                        latest_checkpoint = latest_checkpoint_tuple.checkpoint or {}
                        history_messages = latest_checkpoint.get('channel_values', {}).get('messages', []) or []
                        existing_metadata = latest_checkpoint_tuple.metadata or {}
                        compression_state = dict(existing_metadata.get("context_compression") or {})
                        summary_text = compression_state.get("context_summary")
                        summarized_count = compression_state.get("summarized_message_count", 0)
                    
                    # 执行压缩检查
                    compression_result = await conversation_compressor.prepare(
                        messages=history_messages,
                        summary_text=summary_text,
                        summarized_count=summarized_count,
                    )
                    history_token_count = compression_result.token_count
                    
                    # 如果压缩被触发，更新 checkpoint
                    if latest_checkpoint_tuple and (
                        compression_result.triggered
                        or "context_summary" in compression_result.state_updates
                        or "summarized_message_count" in compression_result.state_updates
                    ):
                        updated_checkpoint = copy.deepcopy(latest_checkpoint_tuple.checkpoint)
                        updated_channel_values = updated_checkpoint.setdefault("channel_values", {})
                        if compression_result.triggered:
                            updated_channel_values["messages"] = compression_result.messages
                            logger.info(f"ChatStreamAPIView: Context compression triggered, messages reduced from {len(history_messages)} to {len(compression_result.messages)}")
                        
                        updated_metadata = copy.deepcopy(existing_metadata)
                        compression_meta = dict(updated_metadata.get("context_compression") or {})
                        if "context_summary" in compression_result.state_updates:
                            compression_meta["context_summary"] = compression_result.state_updates["context_summary"]
                        if "summarized_message_count" in compression_result.state_updates:
                            compression_meta["summarized_message_count"] = compression_result.state_updates["summarized_message_count"]
                        compression_meta["context_token_count"] = compression_result.state_updates.get("context_token_count", history_token_count)
                        updated_metadata["context_compression"] = compression_meta
                        
                        # 写入更新后的 checkpoint
                        checkpoint_config = latest_checkpoint_tuple.config.get("configurable", {})
                        update_config = {
                            "configurable": {
                                "thread_id": checkpoint_config.get("thread_id"),
                                "checkpoint_ns": checkpoint_config.get("checkpoint_ns", ""),
                            }
                        }
                        parent_config = latest_checkpoint_tuple.parent_config
                        if parent_config:
                            parent_checkpoint_id = parent_config.get("configurable", {}).get("checkpoint_id")
                            if parent_checkpoint_id:
                                update_config["configurable"]["checkpoint_id"] = parent_checkpoint_id
                        
                        await actual_memory_checkpointer.aput(
                            update_config,
                            updated_checkpoint,
                            updated_metadata,
                            updated_checkpoint.get("channel_versions", {}),
                        )
                        logger.info(f"ChatStreamAPIView: Applied context compression for thread {thread_id}")
                    
                    # 计算总 token 数（历史 + 当前消息）
                    total_tokens = history_token_count
                    for msg in messages_list:
                        if hasattr(msg, 'content') and msg.content:
                            content = msg.content if isinstance(msg.content, str) else str(msg.content)
                            total_tokens += context_checker.count_tokens(content, active_config.name or "gpt-4o")
                    
                    usage_ratio = total_tokens / context_limit
                    logger.info(f"ChatStreamAPIView: Context usage: {total_tokens}/{context_limit} ({usage_ratio*100:.1f}%)")
                    
                    # 压缩后仍超过95%时拒绝新消息
                    if usage_ratio > 0.95:
                        logger.warning(f"ChatStreamAPIView: Context limit exceeded after compression ({usage_ratio*100:.1f}%)")
                        yield create_sse_data({
                            'type': 'error', 
                            'message': f'对话上下文已达上限（{total_tokens}/{context_limit} tokens），压缩后仍无法继续，请新建对话。'
                        })
                        return
                    # 压缩后仍超过85%时发送警告
                    elif usage_ratio > 0.85:
                        yield create_sse_data({
                            'type': 'warning', 
                            'message': f'对话上下文即将达到上限（{int(usage_ratio*100)}%），建议尽快新建对话。'
                        })
                except Exception as e:
                    logger.warning(f"ChatStreamAPIView: Context check/compression failed: {e}", exc_info=True)

                input_messages = {"messages": messages_list}
                invoke_config = {
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": 1000  # 支持约500次工具调用
                }
                logger.info(f"ChatStreamAPIView: Set recursion_limit to 1000 for thread_id: {thread_id}")
                logger.info(f"ChatStreamAPIView: Input messages structure: {input_messages}")

                # 详细记录每个消息的内容
                for i, msg in enumerate(messages_list):
                    logger.info(f"ChatStreamAPIView: Message {i}: type={type(msg).__name__}, content={repr(msg.content)}")

                # 发送开始信号
                yield create_sse_data({
                    'type': 'start', 
                    'thread_id': thread_id, 
                    'session_id': session_id, 
                    'project_id': project_id,
                    'context_limit': context_limit
                })

                # 使用astream进行流式处理，支持多种模式
                stream_modes = ["updates", "messages"]

                try:
                    async for stream_mode, chunk in runnable_to_invoke.astream(
                        input_messages,
                        config=invoke_config,
                        stream_mode=stream_modes
                    ):
                        if stream_mode == "updates":
                            # 代理进度更新 - 安全地序列化复杂对象
                            try:
                                # 尝试将chunk转换为可序列化的格式
                                if hasattr(chunk, '__dict__'):
                                    serializable_chunk = str(chunk)
                                else:
                                    serializable_chunk = chunk
                                yield create_sse_data({'type': 'update', 'data': serializable_chunk})
                            except (TypeError, ValueError) as e:
                                yield create_sse_data({'type': 'update', 'data': f'Update: {str(chunk)}'})
                        elif stream_mode == "messages":
                            # LLM令牌流式传输
                            if hasattr(chunk, 'content') and chunk.content:
                                yield create_sse_data({'type': 'message', 'data': chunk.content})
                            else:
                                yield create_sse_data({'type': 'message', 'data': str(chunk)})

                        # 添加小延迟以确保流式传输效果
                        await asyncio.sleep(0.01)

                except Exception as e:
                    logger.error(f"ChatStreamAPIView: Error during streaming: {e}", exc_info=True)
                    yield create_sse_data({'type': 'error', 'message': f'Streaming error: {str(e)}'})

                # 计算并发送上下文Token使用信息
                try:
                    from requirements.context_limits import context_checker
                    context_limit = active_config.context_limit or 128000
                    
                    # 获取当前会话的所有消息来计算token
                    current_state = await runnable_to_invoke.aget_state(invoke_config)
                    all_messages = current_state.values.get("messages", []) if current_state.values else []
                    
                    # 计算所有消息的token总数
                    total_tokens = 0
                    for msg in all_messages:
                        if hasattr(msg, 'content') and msg.content:
                            content = msg.content if isinstance(msg.content, str) else str(msg.content)
                            total_tokens += context_checker.count_tokens(content, active_config.name or "gpt-4o")
                    
                    logger.info(f"[Context Update] Chat mode: {total_tokens}/{context_limit} tokens")
                    yield create_sse_data({
                        'type': 'context_update',
                        'context_token_count': total_tokens,
                        'context_limit': context_limit
                    })
                except Exception as e:
                    logger.warning(f"ChatStreamAPIView: Failed to calculate token count: {e}")

                # 发送完成信号
                yield create_sse_data({'type': 'complete'})

                # 发送流结束标记
                yield "data: [DONE]\n\n"

        except Exception as e:
            logger.error(f"ChatStreamAPIView: Error in stream generator: {e}", exc_info=True)
            yield create_sse_data({'type': 'error', 'message': f'Generator error: {str(e)}'})

    async def post(self, request, *args, **kwargs):
        """处理流式聊天请求"""
        try:
            # 手动认证（异步）
            user = await self.authenticate_request(request)
            request.user = user
            logger.info(f"ChatStreamAPIView: Received POST request from user {user.id}")
        except AuthenticationFailed as e:
            error_data = create_sse_data({
                'type': 'error',
                'message': str(e),
                'code': 401
            })
            return StreamingHttpResponse(
                iter([error_data]),
                content_type='text/event-stream; charset=utf-8',
                status=401
            )

        # 解析JSON数据
        try:
            import json as json_module
            body_data = json_module.loads(request.body.decode('utf-8'))
        except (json_module.JSONDecodeError, UnicodeDecodeError) as e:
            error_data = create_sse_data({
                'type': 'error',
                'message': f'Invalid JSON data: {str(e)}',
                'code': 400
            })
            return StreamingHttpResponse(
                iter([error_data]),
                content_type='text/event-stream; charset=utf-8',
                status=400
            )

        user_message_content = body_data.get('message')
        session_id = body_data.get('session_id')
        project_id = body_data.get('project_id')
        image_base64 = body_data.get('image')  # 图片base64编码（不含前缀）

        # 知识库相关参数
        knowledge_base_id = body_data.get('knowledge_base_id')
        use_knowledge_base = body_data.get('use_knowledge_base', True)
        similarity_threshold = body_data.get('similarity_threshold', 0.5)
        top_k = body_data.get('top_k', 5)

        # 提示词相关参数
        prompt_id = body_data.get('prompt_id')  # 用户指定的提示词ID

        # 验证项目ID是否提供
        if not project_id:
            error_data = create_sse_data({
                'type': 'error',
                'message': 'project_id is required',
                'code': status.HTTP_400_BAD_REQUEST
            })
            return StreamingHttpResponse(
                iter([error_data]),
                content_type='text/event-stream; charset=utf-8',
                status=status.HTTP_400_BAD_REQUEST
            )

        # 检查项目权限
        project = await sync_to_async(self._check_project_permission)(request.user, project_id)
        if not project:
            error_data = create_sse_data({
                'type': 'error',
                'message': "You don't have permission to access this project or project doesn't exist",
                'code': status.HTTP_403_FORBIDDEN
            })
            return StreamingHttpResponse(
                iter([error_data]),
                content_type='text/event-stream; charset=utf-8',
                status=status.HTTP_403_FORBIDDEN
            )

        is_new_session = False
        if not session_id:
            session_id = uuid.uuid4().hex
            is_new_session = True
            logger.info(f"ChatStreamAPIView: Generated new session_id: {session_id}")

        # 如果是新会话，立即创建ChatSession对象
        if is_new_session:
            try:
                # 获取关联的提示词对象
                prompt_obj = None
                if prompt_id:
                    try:
                        prompt_obj = await sync_to_async(UserPrompt.objects.get)(
                            id=prompt_id,
                            user=request.user,
                            is_active=True
                        )
                    except UserPrompt.DoesNotExist:
                        logger.warning(f"ChatStreamAPIView: Prompt {prompt_id} not found or inactive")
                
                await sync_to_async(ChatSession.objects.create)(
                    user=request.user,
                    session_id=session_id,
                    project=project,
                    prompt=prompt_obj,
                    title=f"新对话 - {user_message_content[:30]}"
                )
                logger.info(f"ChatStreamAPIView: Created new ChatSession entry for session_id: {session_id}, prompt_id: {prompt_id}")
            except Exception as e:
                logger.error(f"ChatStreamAPIView: Failed to create ChatSession entry: {e}", exc_info=True)


        if not user_message_content:
            logger.warning("ChatStreamAPIView: Message content is required but not provided.")
            error_data = create_sse_data({
                'type': 'error',
                'message': 'Message content is required',
                'code': status.HTTP_400_BAD_REQUEST
            })
            return StreamingHttpResponse(
                iter([error_data]),
                content_type='text/event-stream; charset=utf-8',
                status=status.HTTP_400_BAD_REQUEST
            )

        # 创建异步生成器
        async def async_generator():
            async for chunk in self._create_sse_generator(
                request, user_message_content, session_id, project_id, project,
                knowledge_base_id, use_knowledge_base, similarity_threshold, top_k, prompt_id, image_base64
            ):
                yield chunk

        response = StreamingHttpResponse(
            async_generator(),
            content_type='text/event-stream; charset=utf-8'
        )
        response['Cache-Control'] = 'no-cache'
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Headers'] = 'Cache-Control'

        return response


class ProviderChoicesAPIView(APIView):
    """获取可用的LLM供应商选项"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request, *args, **kwargs):
        """返回所有可用的供应商选项"""
        choices = [{'value': choice[0], 'label': choice[1]} for choice in LLMConfig.PROVIDER_CHOICES]
        return Response({
            'status': 'success',
            'code': status.HTTP_200_OK,
            'message': 'Provider choices retrieved successfully.',
            'data': {'choices': choices}
        })


class KnowledgeRAGAPIView(APIView):
    """知识库RAG查询API视图"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        """执行知识库RAG查询"""
        try:
            # 获取请求参数
            query = request.data.get('query')
            knowledge_base_id = request.data.get('knowledge_base_id')
            project_id = request.data.get('project_id')

            if not query:
                return Response(
                    {'error': '查询内容不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not knowledge_base_id:
                return Response(
                    {'error': '知识库ID不能为空'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 验证项目权限
            if project_id:
                try:
                    project = Project.objects.get(id=project_id)
                    if not project.members.filter(user=request.user).exists() and not request.user.is_superuser:
                        return Response(
                            {'error': '您没有权限访问此项目'},
                            status=status.HTTP_403_FORBIDDEN
                        )
                except Project.DoesNotExist:
                    return Response(
                        {'error': '项目不存在'},
                        status=status.HTTP_404_NOT_FOUND
                    )

            # 验证知识库权限
            try:
                knowledge_base = KnowledgeBase.objects.get(id=knowledge_base_id)
                if not knowledge_base.project.members.filter(user=request.user).exists() and not request.user.is_superuser:
                    return Response(
                        {'error': '您没有权限访问此知识库'},
                        status=status.HTTP_403_FORBIDDEN
                    )
            except KnowledgeBase.DoesNotExist:
                return Response(
                    {'error': '知识库不存在'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # 获取LLM配置
            try:
                active_config = LLMConfig.objects.filter(is_active=True).first()
                if not active_config:
                    return Response(
                        {'error': '没有可用的LLM配置'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

                # 使用新的LLM工厂函数，支持多供应商
                llm = create_llm_instance(active_config, temperature=0.7)
            except Exception as e:
                logger.error(f"LLM配置错误: {e}")
                return Response(
                    {'error': 'LLM配置错误'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # 执行RAG查询
            rag_service = KnowledgeRAGService(llm)
            result = rag_service.query(
                question=query,
                knowledge_base_id=knowledge_base_id,
                user=request.user
            )

            return Response({
                'query': result['question'],
                'answer': result['answer'],
                'sources': result['context'],
                'retrieval_time': result['retrieval_time'],
                'generation_time': result['generation_time'],
                'total_time': result['total_time']
            })

        except Exception as e:
            logger.error(f"知识库RAG查询失败: {e}")
            return Response(
                {'error': f'查询失败: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
