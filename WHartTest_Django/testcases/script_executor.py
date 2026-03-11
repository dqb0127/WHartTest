"""
Playwright 脚本执行器

执行生成的自动化测试脚本并记录结果
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import os
import re
import shutil
import logging
import uuid
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from datetime import datetime

from django.utils import timezone
from django.conf import settings

if TYPE_CHECKING:
    from .models import ScriptExecution

logger = logging.getLogger(__name__)


# 录屏注入代码模板
VIDEO_INJECTION_IMPORTS = '''import os
'''

VIDEO_INJECTION_CODE = '''
        # 动态录屏配置（由执行器注入）
        video_dir = os.environ.get('PLAYWRIGHT_VIDEO_DIR', '')
        _context_options = {"ignore_https_errors": True}
        if video_dir:
            _context_options["record_video_dir"] = video_dir
            _context_options["record_video_size"] = {"width": 1280, "height": 720}
'''


class ScriptExecutor:
    """
    执行 Playwright Python 脚本
    """
    
    def __init__(
        self,
        work_dir: Optional[str] = None,
        timeout_seconds: int = 300,
        browser_type: str = 'chromium'
    ):
        self.work_dir = work_dir or tempfile.mkdtemp(prefix='playwright_')
        self.timeout_seconds = timeout_seconds
        self.browser_type = browser_type
    
    def _inject_headless_setting(self, script_content: str, headless: bool) -> str:
        """
        动态替换脚本中的 headless 参数
        """
        headless_str = 'True' if headless else 'False'
        # 匹配 headless=True 或 headless=False
        modified = re.sub(
            r'(\.launch\([^)]*headless=)(True|False)',
            rf'\g<1>{headless_str}',
            script_content
        )
        if modified != script_content:
            logger.info(f"[ScriptExecutor] 已设置 headless={headless_str}")
        return modified
    
    def _inject_video_recording(self, script_content: str) -> str:
        """
        在脚本中注入录屏配置代码
        
        匹配 browser.new_context(...) 调用并替换为使用录屏配置
        """
        # 确保导入 os 模块
        if 'import os' not in script_content:
            # 在 from playwright 导入之前插入 os 导入
            script_content = re.sub(
                r'(from playwright\.sync_api import)',
                VIDEO_INJECTION_IMPORTS + r'\1',
                script_content
            )
        
        # 匹配 browser.new_context(...) 调用并替换
        # 模式：browser.new_context(任意参数)
        pattern = r'(\s+)(context\s*=\s*browser\.new_context\([^)]*\))'
        
        def replace_context(match):
            indent = match.group(1)
            # 替换为使用动态配置的版本
            return f'''{indent}# 动态录屏配置（由执行器注入）
{indent}video_dir = os.environ.get('PLAYWRIGHT_VIDEO_DIR', '')
{indent}_context_options = {{"ignore_https_errors": True}}
{indent}if video_dir:
{indent}    _context_options["record_video_dir"] = video_dir
{indent}    _context_options["record_video_size"] = {{"width": 1280, "height": 720}}
{indent}context = browser.new_context(**_context_options)'''
        
        modified = re.sub(pattern, replace_context, script_content)
        
        # 如果没有匹配到，记录警告
        if modified == script_content:
            logger.warning("[ScriptExecutor] 未找到 browser.new_context() 调用，无法注入录屏配置")
        else:
            logger.info("[ScriptExecutor] 已注入录屏配置代码")
        
        return modified
    
    def execute_script(
        self,
        script_content: str,
        use_pytest: bool = True,
        headless: bool = True,
        record_video: bool = False
    ) -> dict:
        """
        执行脚本并返回结果
        
        Args:
            script_content: 脚本内容
            use_pytest: 是否使用 pytest 执行
            headless: 是否无头模式
            record_video: 是否录制视频
        
        Returns:
            执行结果字典
        """
        result = {
            'success': False,
            'output': '',
            'error_message': '',
            'stack_trace': '',
            'screenshots': [],
            'videos': [],  # 新增：视频列表
            'execution_time': 0,
            'started_at': timezone.now(),
            'completed_at': None
        }
        
        logger.info(f"[ScriptExecutor] 开始执行脚本, use_pytest={use_pytest}, headless={headless}, record_video={record_video}")
        logger.info(f"[ScriptExecutor] 工作目录: {self.work_dir}")
        
        # 动态替换 headless 设置
        script_content = self._inject_headless_setting(script_content, headless)
        
        # 如果需要录屏，动态注入录屏配置代码
        if record_video:
            script_content = self._inject_video_recording(script_content)
        
        logger.debug(f"[ScriptExecutor] 脚本内容预览:\n{script_content[:500]}...")
        
        try:
            # 创建临时脚本文件
            script_path = Path(self.work_dir) / 'test_script.py'
            script_path.write_text(script_content, encoding='utf-8')
            logger.info(f"[ScriptExecutor] 脚本文件已写入: {script_path}")
            
            # 确定执行命令 - 不使用可能不存在的插件参数
            if use_pytest:
                cmd = [
                    sys.executable, '-m', 'pytest',
                    str(script_path),
                    '-v',
                    '--tb=short',
                ]
            else:
                cmd = [sys.executable, str(script_path)]
            
            logger.info(f"[ScriptExecutor] 执行命令: {' '.join(cmd)}")
            
            # 设置环境变量
            env = os.environ.copy()
            env['PLAYWRIGHT_HEADLESS'] = '1' if headless else '0'
            env['PWDEBUG'] = '0'  # 禁用调试模式
            env['PYTHONIOENCODING'] = 'utf-8'  # 解决 Windows GBK 编码问题
            
            # 录屏目录（通过环境变量传递给脚本）
            video_dir = ''
            if record_video:
                video_dir = str(Path(self.work_dir) / 'videos')
                Path(video_dir).mkdir(parents=True, exist_ok=True)
                env['PLAYWRIGHT_VIDEO_DIR'] = video_dir
                logger.info(f"[ScriptExecutor] 录屏目录: {video_dir}")
            
            # 执行脚本
            start_time = datetime.now()
            logger.info(f"[ScriptExecutor] 开始执行, 超时时间: {self.timeout_seconds}秒")
            
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=self.timeout_seconds,
                cwd=self.work_dir,
                env=env
            )
            
            end_time = datetime.now()
            
            result['output'] = process.stdout or ''
            result['execution_time'] = (end_time - start_time).total_seconds()
            result['completed_at'] = timezone.now()
            
            logger.info(f"[ScriptExecutor] 执行完成, 返回码: {process.returncode}, 耗时: {result['execution_time']:.2f}秒")
            logger.info(f"[ScriptExecutor] 标准输出({len(result['output'])}字符):\n{result['output']}")
            if process.stderr:
                logger.info(f"[ScriptExecutor] 标准错误({len(process.stderr)}字符):\n{process.stderr}")
            
            if process.returncode == 0:
                result['success'] = True
                logger.info("[ScriptExecutor] ✅ 执行成功")
            else:
                result['error_message'] = process.stderr or '执行失败'
                result['stack_trace'] = process.stderr
                logger.error(f"[ScriptExecutor] ❌ 执行失败, stderr:\n{process.stderr}")
            
            # 收集截图并移动到持久化目录
            result['screenshots'] = self._persist_screenshots()
            logger.info(f"[ScriptExecutor] 截图数量: {len(result['screenshots'])}")
            
            # 收集视频并移动到持久化目录
            if record_video:
                result['videos'] = self._persist_videos()
                logger.info(f"[ScriptExecutor] 视频数量: {len(result['videos'])}")
            
        except subprocess.TimeoutExpired:
            result['error_message'] = f'执行超时: {self.timeout_seconds}秒'
            result['stack_trace'] = f'TimeoutExpired after {self.timeout_seconds}s'
            result['completed_at'] = timezone.now()
            logger.error(f"[ScriptExecutor] ❌ 执行超时: {self.timeout_seconds}秒")
            
        except Exception as e:
            result['error_message'] = str(e)
            result['stack_trace'] = f'{type(e).__name__}: {e}'
            result['completed_at'] = timezone.now()
            logger.exception("[ScriptExecutor] ❌ 脚本执行异常")
        
        return result
    
    def _persist_screenshots(self) -> list:
        """
        将截图从临时目录移动到持久化的 media 目录
        返回相对于 MEDIA_ROOT 的路径列表
        """
        screenshots = []
        temp_screenshots = list(Path(self.work_dir).glob('*.png'))
        
        if not temp_screenshots:
            return screenshots
        
        # 创建持久化目录
        persist_dir = Path(settings.MEDIA_ROOT) / 'script_screenshots' / datetime.now().strftime('%Y%m%d')
        persist_dir.mkdir(parents=True, exist_ok=True)
        
        for temp_path in temp_screenshots:
            # 生成唯一文件名避免冲突
            unique_name = f"{uuid.uuid4().hex[:8]}_{temp_path.name}"
            persist_path = persist_dir / unique_name
            
            try:
                shutil.copy2(temp_path, persist_path)
                # 存储相对于 MEDIA_ROOT 的路径
                relative_path = persist_path.relative_to(settings.MEDIA_ROOT)
                screenshots.append(str(relative_path))
            except Exception as e:
                logger.warning(f"保存截图失败: {e}")
        
        return screenshots
    
    def _persist_videos(self) -> list:
        """
        将视频从临时目录移动到持久化的 media 目录
        返回相对于 MEDIA_ROOT 的路径列表
        """
        videos = []
        video_dir = Path(self.work_dir) / 'videos'
        
        if not video_dir.exists():
            return videos
        
        # Playwright 生成的视频是 .webm 格式
        temp_videos = list(video_dir.glob('*.webm'))
        
        if not temp_videos:
            return videos
        
        # 创建持久化目录
        persist_dir = Path(settings.MEDIA_ROOT) / 'script_videos' / datetime.now().strftime('%Y%m%d')
        persist_dir.mkdir(parents=True, exist_ok=True)
        
        for temp_path in temp_videos:
            # 生成唯一文件名避免冲突
            unique_name = f"{uuid.uuid4().hex[:8]}_{temp_path.name}"
            persist_path = persist_dir / unique_name
            
            try:
                shutil.copy2(temp_path, persist_path)
                # 存储相对于 MEDIA_ROOT 的路径
                relative_path = persist_path.relative_to(settings.MEDIA_ROOT)
                videos.append(str(relative_path))
                logger.info(f"[ScriptExecutor] 视频已保存: {relative_path}")
            except Exception as e:
                logger.warning(f"保存视频失败: {e}")
        
        return videos
    
    def cleanup(self):
        """清理临时文件"""
        if self.work_dir and Path(self.work_dir).exists():
            shutil.rmtree(self.work_dir, ignore_errors=True)


def _cleanup_old_executions(script, max_executions: int = 15):
    """
    清理旧的执行记录，只保留最新的 max_executions 条
    同时删除关联的截图和视频文件
    
    Args:
        script: AutomationScript 实例
        max_executions: 最多保留的执行记录数
    """
    from .models import ScriptExecution
    
    # 获取该脚本所有执行记录，按创建时间降序排列
    all_executions = ScriptExecution.objects.filter(
        script=script
    ).order_by('-created_at')
    
    total_count = all_executions.count()
    if total_count <= max_executions:
        return
    
    # 获取需要删除的旧记录
    executions_to_delete = all_executions[max_executions:]
    
    for execution in executions_to_delete:
        execution_id = execution.id  # 在删除前保存 ID
        try:
            # 删除关联的截图文件（screenshots 是 JSONField，存储路径列表）
            if execution.screenshots:
                for screenshot_path in execution.screenshots:
                    image_path = Path(settings.MEDIA_ROOT) / screenshot_path
                    if image_path.exists():
                        image_path.unlink()
                        logger.debug(f"已删除截图文件: {image_path}")
            
            # 删除关联的视频文件（videos 是 JSONField，存储路径列表）
            if execution.videos:
                for video_path in execution.videos:
                    full_video_path = Path(settings.MEDIA_ROOT) / video_path
                    if full_video_path.exists():
                        full_video_path.unlink()
                        logger.debug(f"已删除视频文件: {full_video_path}")
            
            # 删除执行记录
            execution.delete()
            logger.info(f"已清理旧执行记录: ID={execution_id}")
        except Exception as e:
            logger.warning(f"清理执行记录 ID={execution_id} 时出错: {e}")
    
    logger.info(f"脚本 ID={script.id} 清理了 {total_count - max_executions} 条旧执行记录")


def execute_automation_script(
    script,
    executor=None,
    headless: bool = None,
    record_video: bool = False,
    max_executions: int = 15
) -> 'ScriptExecution':
    """
    执行 AutomationScript 并创建 ScriptExecution 记录
    
    Args:
        script: AutomationScript 实例
        executor: 执行人（User 实例）
        headless: 是否无头模式，默认使用脚本配置
        record_video: 是否录制视频
        max_executions: 每个脚本最多保留的执行记录数，默认 15
    
    Returns:
        创建的 ScriptExecution 实例
    """
    from .models import ScriptExecution
    
    # 安全检查：只允许执行 AI 生成或录制的脚本
    if script.source not in ('ai_generated', 'recorded'):
        raise ValueError("只能执行 AI 生成或录制的脚本，手动编写的脚本需要先审核")
    
    # 创建执行记录
    execution = ScriptExecution.objects.create(
        script=script,
        status='running',
        started_at=timezone.now(),
        executor=executor,
        browser_type='chromium'
    )
    
    # 清理旧的执行记录，只保留最新的 max_executions 条
    _cleanup_old_executions(script, max_executions)
    
    logger.info(f"[execute_automation_script] 开始执行脚本 ID={script.id}, 名称={script.name}")

    logger.info(f"[execute_automation_script] 脚本类型={script.script_type}, 来源={script.source}, record_video={record_video}")
    logger.info(f"[execute_automation_script] 创建执行记录 ID={execution.id}")
    
    try:
        # 创建执行器
        script_executor = ScriptExecutor(
            timeout_seconds=script.timeout_seconds,
            browser_type='chromium'
        )
        
        # 判断是否使用 pytest - 使用更可靠的方式
        use_pytest = (
            script.script_type == 'playwright_python' 
            and 'import pytest' in script.script_content 
            and 'def test_' in script.script_content
        )
        
        logger.info(f"[execute_automation_script] use_pytest={use_pytest}, headless={headless}, record_video={record_video}")
        logger.info(f"[execute_automation_script] 脚本内容长度: {len(script.script_content)} 字符")
        
        # 执行脚本
        result = script_executor.execute_script(
            script_content=script.script_content,
            use_pytest=use_pytest,
            headless=headless if headless is not None else script.headless,
            record_video=record_video
        )
        
        # 更新执行记录
        execution.completed_at = result['completed_at']
        execution.execution_time = result['execution_time']
        execution.output = result['output']
        
        if result['success']:
            execution.status = 'pass'
            logger.info(f"[execute_automation_script] ✅ 执行成功, 耗时: {result['execution_time']:.2f}秒")
        else:
            execution.status = 'fail'
            execution.error_message = result['error_message']
            execution.stack_trace = result['stack_trace']
            logger.error(f"[execute_automation_script] ❌ 执行失败: {result['error_message']}")
        
        execution.screenshots = result['screenshots']
        execution.videos = result.get('videos', [])  # 保存视频
        execution.save()
        
        # 清理临时目录（截图已持久化）
        script_executor.cleanup()
        
    except Exception as e:
        execution.status = 'error'
        execution.error_message = str(e)
        execution.completed_at = timezone.now()
        execution.save()
        logger.exception("[execute_automation_script] ❌ 执行脚本时发生错误")
    
    return execution
