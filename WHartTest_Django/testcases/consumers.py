"""
自动化脚本执行实时预览 WebSocket Consumer

使用独立子进程执行 Playwright，完全避免 Windows 事件循环问题。
执行完成后自动清理资源，不占用服务器存储。
"""

import asyncio
import json
import logging
import subprocess
import sys
import tempfile
import os
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)

# Playwright 执行器脚本路径
EXECUTOR_SCRIPT = Path(__file__).parent / 'playwright_executor.py'


class ExecutionPreviewConsumer(AsyncWebsocketConsumer):
    """
    脚本执行实时预览 WebSocket Consumer
    
    连接地址: ws://server/ws/execution-preview/<script_id>/
    
    消息格式:
    - 发送 {"action": "start", "headless": true} 开始执行
    - 发送 {"action": "stop"} 停止执行
    - 接收 {"type": "frame", "data": "<base64>"} 截图帧
    - 接收 {"type": "status", "status": "running|completed|error", "message": "..."} 状态
    - 接收 {"type": "log", "message": "..."} 执行日志
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.script_id: Optional[int] = None
        self.user = None
        self.is_executing = False
        self.process: Optional[subprocess.Popen] = None
        self.reader_task = None
        self.fps = 10
        self.temp_file_path = None  # 临时参数文件路径
    
    async def connect(self):
        """WebSocket 连接建立"""
        self.script_id = self.scope['url_route']['kwargs'].get('script_id')
        
        # 从 query string 获取 token
        query_string = self.scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]
        
        # 验证用户权限
        user = await self._authenticate(token)
        if not user:
            await self.close(code=4001)
            return
        
        self.user = user
        
        # 验证脚本访问权限
        if not await self._check_script_access():
            await self.close(code=4003)
            return
        
        await self.accept()
        await self.send_status('connected', '已连接，等待开始执行')
    
    async def disconnect(self, close_code):
        """WebSocket 断开连接，清理资源"""
        await self._cleanup()
    
    async def receive(self, text_data=None, bytes_data=None):
        """接收客户端消息"""
        if not text_data:
            return
        
        try:
            data = json.loads(text_data)
            action = data.get('action')
            
            if action == 'start':
                headless = data.get('headless', False)
                fps = data.get('fps', 10)
                await self._start_execution(headless, fps)
            elif action == 'stop':
                await self._stop_execution()
            else:
                await self.send_status('error', f'未知操作: {action}')
        except json.JSONDecodeError:
            await self.send_status('error', '无效的 JSON 格式')
        except Exception as e:
            logger.exception(f'处理消息时出错: {e}')
            await self.send_status('error', str(e))
    
    async def _start_execution(self, headless: bool, fps: int):
        """开始执行脚本"""
        if self.is_executing:
            await self.send_status('error', '脚本正在执行中')
            return
        
        self.is_executing = True
        self.fps = min(max(fps, 1), 30)
        
        try:
            await self.send_status('starting', '正在准备执行...')
            
            # 获取脚本内容
            script = await self._get_script()
            if not script:
                await self.send_status('error', '脚本不存在')
                self.is_executing = False
                return
            
            # 准备执行参数
            exec_params = {
                'script_content': script['script_content'],
                'target_url': script.get('target_url', ''),
                'headless': headless,
                'fps': self.fps,
                'timeout_seconds': script.get('timeout_seconds', 60),
            }
            
            # 使用临时文件传递参数（避免命令行参数长度限制和转义问题）
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', delete=False, encoding='utf-8'
            ) as f:
                json.dump(exec_params, f)
                self.temp_file_path = f.name
            
            logger.info(f'启动执行器，参数文件: {self.temp_file_path}')
            
            # 启动独立进程执行 Playwright
            # 合并 stderr 到 stdout，避免管道写满阻塞
            self.process = subprocess.Popen(
                [sys.executable, str(EXECUTOR_SCRIPT), self.temp_file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # 合并 stderr 到 stdout
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
            
            # 启动输出读取任务
            self.reader_task = asyncio.create_task(self._read_process_output())
            
            # 等待进程结束
            await self.reader_task
            
        except asyncio.CancelledError:
            await self.send_status('cancelled', '执行已取消')
        except Exception as e:
            logger.exception(f'执行脚本时出错: {e}')
            await self.send_status('error', f'执行出错: {str(e)}')
        finally:
            await self._cleanup()
    
    async def _read_process_output(self):
        """异步读取进程输出并转发到 WebSocket"""
        if not self.process or not self.process.stdout:
            return
        
        loop = asyncio.get_event_loop()
        frame_count = 0
        
        try:
            while self.process.poll() is None:
                # 非阻塞读取一行
                line = await loop.run_in_executor(
                    None,
                    self.process.stdout.readline
                )
                
                if not line:
                    await asyncio.sleep(0.01)
                    continue
                
                line = line.strip()
                if not line:
                    continue
                
                # 解析 JSON 消息
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f'JSON解析失败: {e}')
                    # 非 JSON 输出作为日志转发
                    message = {'type': 'log', 'message': line}
                
                msg_type = message.get('type', 'unknown')
                
                # 处理 frame_file 类型：从文件读取数据并转换为 frame 消息
                if msg_type == 'frame_file':
                    frame_path = message.get('path', '')
                    try:
                        with open(frame_path, 'r', encoding='utf-8') as f:
                            frame_data = f.read()
                        os.remove(frame_path)
                        message = {'type': 'frame', 'data': frame_data}
                        msg_type = 'frame'
                    except Exception as e:
                        logger.warning(f'读取 frame 文件失败: {e}')
                        continue
                
                if msg_type == 'frame':
                    frame_count += 1
                
                await self.send(text_data=json.dumps(message))
            
            # 读取剩余输出
            remaining = self.process.stdout.read()
            if remaining:
                for line in remaining.strip().split('\n'):
                    if not line:
                        continue
                    
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        message = {'type': 'log', 'message': line}
                    
                    msg_type = message.get('type', 'unknown')
                    
                    # 处理 frame_file 类型
                    if msg_type == 'frame_file':
                        frame_path = message.get('path', '')
                        try:
                            with open(frame_path, 'r', encoding='utf-8') as f:
                                frame_data = f.read()
                            os.remove(frame_path)
                            message = {'type': 'frame', 'data': frame_data}
                            msg_type = 'frame'
                        except Exception as e:
                            logger.warning(f'读取 frame 文件失败: {e}')
                            continue
                    
                    if msg_type == 'frame':
                        frame_count += 1
                    
                    await self.send(text_data=json.dumps(message))
            
            logger.info(f'共转发 {frame_count} 帧')
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f'读取进程输出出错: {e}')
    
    async def _stop_execution(self):
        """停止执行"""
        if not self.is_executing:
            return
        
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        
        await self.send_status('stopping', '正在停止执行...')
    
    async def _cleanup(self):
        """清理所有资源"""
        # 取消读取任务
        if self.reader_task and not self.reader_task.done():
            self.reader_task.cancel()
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass
        
        # 终止进程
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        
        # 清理临时文件
        if self.temp_file_path and os.path.exists(self.temp_file_path):
            try:
                os.unlink(self.temp_file_path)
            except Exception:
                pass
            self.temp_file_path = None
        
        self.process = None
        self.is_executing = False
        logger.info(f'已清理脚本 {self.script_id} 的执行资源')
    
    async def send_status(self, status: str, message: str):
        """发送状态消息"""
        await self.send(text_data=json.dumps({
            'type': 'status',
            'status': status,
            'message': message
        }))
    
    async def send_log(self, message: str):
        """发送日志消息"""
        await self.send(text_data=json.dumps({
            'type': 'log',
            'message': message
        }))
    
    @database_sync_to_async
    def _authenticate(self, token: str):
        """验证用户身份（支持 JWT）"""
        if not token:
            return None
        
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            from django.contrib.auth import get_user_model
            
            User = get_user_model()
            # 验证 JWT token
            access_token = AccessToken(token)
            user_id = access_token['user_id']
            return User.objects.get(id=user_id)
        except Exception as e:
            logger.debug(f'JWT 认证失败: {e}')
            return None
    
    @database_sync_to_async
    def _check_script_access(self) -> bool:
        """检查用户是否有权限访问脚本"""
        if not self.script_id or not self.user:
            return False
        
        try:
            from testcases.models import AutomationScript
            script = AutomationScript.objects.select_related(
                'test_case__project'
            ).get(id=self.script_id)
            
            # 超级管理员可以访问所有
            if self.user.is_superuser:
                return True
            
            # 检查项目成员权限
            project_id = script.test_case.project_id
            return self.user.project_memberships.filter(project_id=project_id).exists()
        except Exception:
            return False
    
    @database_sync_to_async
    def _get_script(self) -> Optional[dict]:
        """获取脚本信息"""
        try:
            from testcases.models import AutomationScript
            script = AutomationScript.objects.get(id=self.script_id)
            return {
                'id': script.id,
                'name': script.name,
                'script_content': script.script_content,
                'script_type': script.script_type,
                'target_url': script.target_url,
                'timeout_seconds': script.timeout_seconds,
            }
        except Exception:
            return None
