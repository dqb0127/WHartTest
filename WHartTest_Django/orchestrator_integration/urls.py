"""URL路由配置"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrchestratorTaskViewSet, OrchestratorStreamAPIView

router = DefaultRouter()
router.register(r'tasks', OrchestratorTaskViewSet, basename='orchestrator-task')

urlpatterns = [
    path('', include(router.urls)),
    # 流式对话接口 - Brain调用Agent的主要接口
    path('stream/', OrchestratorStreamAPIView.as_view(), name='orchestrator-stream'),
]
