"""
testcases WebSocket 路由配置
"""

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(
        r'ws/execution-preview/(?P<script_id>\d+)/$',
        consumers.ExecutionPreviewConsumer.as_asgi()
    ),
]
