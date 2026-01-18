from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LLMConfigViewSet, ChatAPIView, ChatHistoryAPIView, UserChatSessionsAPIView,
    ChatResumeAPIView, KnowledgeRAGAPIView, ProviderChoicesAPIView, ChatBatchDeleteAPIView,
    UserToolApprovalViewSet
)

# Create a router and register our viewsets with it.
router = DefaultRouter()
router.register(r'llm-configs', LLMConfigViewSet, basename='llmconfig')
router.register(r'tool-approvals', UserToolApprovalViewSet, basename='tool-approval')

# The API URLs are now determined automatically by the router.
# Additionally, we include login URLs for the browsable API.
urlpatterns = [
    path('', include(router.urls)),
    path('providers/', ProviderChoicesAPIView.as_view(), name='provider_choices_api'),
    path('chat/', ChatAPIView.as_view(), name='chat_api'),
    path('chat/resume/', ChatResumeAPIView.as_view(), name='chat_resume_api'),
    path('chat/history/', ChatHistoryAPIView.as_view(), name='chat_history_api'),
    path('chat/sessions/', UserChatSessionsAPIView.as_view(), name='user_chat_sessions_api'),
    path('chat/batch-delete/', ChatBatchDeleteAPIView.as_view(), name='chat_batch_delete_api'),
    path('knowledge/rag/', KnowledgeRAGAPIView.as_view(), name='knowledge_rag_api'),
]