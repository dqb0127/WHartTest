"""
Skill 工具

提供渐进式加载的 Skill 系统：
- read_skill_content: 读取 Skill 的 SKILL.md 内容（按需加载）
- execute_skill_script: 执行 Skill 的 shell 命令（支持持久化浏览器会话）
"""

import logging
import subprocess
import os
import threading
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool as langchain_tool
from django.conf import settings

from .persistent_playwright import PlaywrightSessionManager, extract_runjs_args

logger = logging.getLogger('orchestrator_integration')

_playwright_session_manager: Optional[PlaywrightSessionManager] = None
_playwright_session_manager_lock = threading.Lock()


def _get_playwright_session_manager() -> PlaywrightSessionManager:
    """延迟初始化，避免在 import 时启动后台清理线程（线程安全）"""
    global _playwright_session_manager
    if _playwright_session_manager is None:
        with _playwright_session_manager_lock:
            if _playwright_session_manager is None:
                idle_timeout = getattr(settings, "PLAYWRIGHT_BROWSER_SESSION_IDLE_TIMEOUT_SECONDS", 15 * 60)
                max_sessions = getattr(settings, "PLAYWRIGHT_BROWSER_MAX_SESSIONS", 20)
                _playwright_session_manager = PlaywrightSessionManager(
                    idle_timeout_seconds=int(idle_timeout),
                    max_sessions=int(max_sessions),
                )
    return _playwright_session_manager


def get_skill_tools(user_id: int, project_id: int = None, test_case_id: int = None, chat_session_id: str = None) -> list:
    """获取 Skill 工具列表（Skills 全局共享，不限制项目）"""
    current_user_id = user_id
    current_project_id = project_id if project_id is not None else 0
    current_test_case_id = test_case_id
    current_chat_session_id = chat_session_id

    @langchain_tool
    def read_skill_content(skill_name: str) -> str:
        """
        读取指定 Skill 的完整 SKILL.md 内容。

        当你需要使用某个 Skill 时，先调用此工具获取详细的使用说明。
        系统提示词中只包含 Skill 的名称和简短描述，完整的指令和示例需要通过此工具获取。

        Args:
            skill_name: Skill 名称

        Returns:
            SKILL.md 的完整内容，包含详细的使用说明和示例
        """
        from skills.models import Skill

        logger.info(f"[read_skill_content] skill_name={skill_name}")

        try:
            skill = Skill.objects.filter(
                name=skill_name,
                is_active=True
            ).first()

            if not skill:
                available = Skill.objects.filter(
                    is_active=True
                ).values_list('name', flat=True)
                available_list = list(available)
                return f"错误: 未找到名为 '{skill_name}' 的 Skill。可用的 Skills: {available_list}"

            if not skill.skill_content:
                return f"错误: Skill '{skill_name}' 没有 SKILL.md 内容"

            return skill.skill_content

        except Exception as e:
            logger.error(f"[read_skill_content] 读取失败: {e}", exc_info=True)
            return f"错误: {str(e)}"

    @langchain_tool
    def execute_skill_script(skill_name: str, command: str, session_id: str = None) -> str:
        """
        执行指定 Skill 的命令。

        在调用此工具前，应先使用 read_skill_content 获取 Skill 的使用说明。
        命令会在 Skill 目录下执行，支持任意语言的脚本。

        Args:
            skill_name: Skill 名称
            command: 完整的 shell 命令，例如 "python whart_tools.py --action get_projects"
            session_id: 可选的会话ID。对于 playwright-skill 的 `node run.js ...` 命令，
                       传入 session_id 可保持浏览器会话跨多次调用持久化。
                       同一 session_id 的调用会复用同一个浏览器实例。

        Returns:
            命令执行的输出结果
        """
        from skills.models import Skill

        logger.info(f"[execute_skill_script] skill_name={skill_name}, command={command}")

        try:
            skill = Skill.objects.filter(
                name=skill_name,
                is_active=True
            ).first()

            if not skill:
                available = Skill.objects.filter(
                    is_active=True
                ).values_list('name', flat=True)
                available_list = list(available)
                return f"错误: 未找到名为 '{skill_name}' 的 Skill。可用的 Skills: {available_list}"

            skill_dir = skill.get_full_path()
            if not skill_dir or not os.path.isdir(skill_dir):
                return f"错误: Skill '{skill_name}' 目录不存在"

            logger.info(f"[execute_skill_script] 在目录 {skill_dir} 执行: {command}")

            env = os.environ.copy()
            env['WHARTTEST_BACKEND_URL'] = getattr(settings, 'WHARTTEST_BACKEND_URL', 'http://localhost:8000')
            env['WHARTTEST_API_KEY'] = getattr(settings, 'WHARTTEST_API_KEY', '')

            # 截图目录：使用 playwright-skill 目录下的 media/screenshots（跨 skill 共享）
            # 优先使用 test_case_id（最稳定），其次 session_id，最后 _default
            playwright_skill = Skill.objects.filter(name='playwright-skill', is_active=True).first()
            if playwright_skill and playwright_skill.skill_path:
                playwright_skill_dir = os.path.join(settings.MEDIA_ROOT, playwright_skill.skill_path)
            else:
                playwright_skill_dir = skill_dir

            # 确定截图子目录 key
            case_dir_key = None
            if current_test_case_id:
                case_dir_key = str(current_test_case_id)
            elif session_id:
                case_dir_key = session_id

            if case_dir_key:
                screenshots_dir = os.path.abspath(os.path.join(playwright_skill_dir, 'media', 'screenshots', case_dir_key))
                # 使用标记文件记录当前 chat_session_id，不同对话时清空目录
                session_marker = os.path.join(screenshots_dir, '.chat_session')
                current_chat_id = current_chat_session_id or 'default'
                should_clear = False
                if os.path.exists(screenshots_dir):
                    if os.path.exists(session_marker):
                        with open(session_marker, 'r') as f:
                            stored_chat_id = f.read().strip()
                        if stored_chat_id != current_chat_id:
                            should_clear = True
                    else:
                        should_clear = True
                if should_clear:
                    import shutil
                    shutil.rmtree(screenshots_dir, ignore_errors=True)
                    logger.info(f"[execute_skill_script] 清空旧截图目录: {screenshots_dir}")
                os.makedirs(screenshots_dir, exist_ok=True)
                with open(session_marker, 'w') as f:
                    f.write(current_chat_id)
            else:
                screenshots_dir = os.path.abspath(os.path.join(playwright_skill_dir, 'media', 'screenshots', '_default'))
                os.makedirs(screenshots_dir, exist_ok=True)
            env['SCREENSHOT_DIR'] = screenshots_dir

            # Windows 兼容：将单引号包裹的参数转换为双引号（用于 cmd.exe）
            # 同时处理多行字符串，将换行符转换为单行
            import platform
            import re

            exec_command = command
            if platform.system() == 'Windows':
                # 处理多行字符串：将双引号内的换行符替换为空格或分号
                def collapse_multiline(m):
                    content = m.group(1)
                    # 将换行替换为空格，保持代码可执行
                    collapsed = ' '.join(line.strip() for line in content.split('\n') if line.strip())
                    return f'"{collapsed}"'
                # 匹配 "..." 形式的多行字符串
                exec_command = re.sub(r'"([^"]*\n[^"]*)"', collapse_multiline, command)

                # 单引号转双引号
                def convert_quotes(m):
                    param = m.group(1)
                    value = m.group(2)
                    escaped = value.replace('"', '\\"')
                    return f'{param}"{escaped}"'
                exec_command = re.sub(r"(--\w+\s+)'([^']*)'", convert_quotes, exec_command)

                if exec_command != command:
                    logger.info(f"[execute_skill_script] Windows 命令转换完成")

            # 持久化 Playwright 会话路径
            # 仅当 session_id 存在 + skill_name == 'playwright-skill' + 命令是 run.js 调用时启用
            if session_id and skill_name == 'playwright-skill':
                run_js_args = extract_runjs_args(exec_command)
                if run_js_args is not None:
                    # 调试日志
                    logger.debug(f"[execute_skill_script] run_js_args: {run_js_args}")
                    # session_key 包含 chat_session_id 以隔离不同对话的浏览器会话
                    chat_id_part = current_chat_session_id or "default"
                    session_key = f"{current_user_id}_{current_project_id}_{chat_id_part}_{session_id}"
                    try:
                        manager = _get_playwright_session_manager()
                        output = manager.execute_run_js(
                            session_key=session_key,
                            skill_dir=skill_dir,
                            run_js_args=run_js_args,
                            env=env,
                            timeout_seconds=120,
                        )
                        logger.info(f"[execute_skill_script] 持久化会话执行完成, session_key={session_key}")
                        result_output = output.strip() if output.strip() else "(无输出)"
                        return f"[PERSISTENT_SESSION] session_id={session_id}\n[SCREENSHOT_DIR] {screenshots_dir}\n{result_output}\n[提示] 后续步骤请继续使用 session_id=\"{session_id}\"；截图已保存在 {screenshots_dir}"
                    except TimeoutError:
                        logger.error("[execute_skill_script] 持久化 Playwright 执行超时")
                        return "错误: 命令执行超时（120秒）"
                    except Exception as e:
                        logger.error(f"[execute_skill_script] 持久化 Playwright 执行失败: {e}", exc_info=True)
                        return f"错误: {str(e)}"

            # Windows 编码处理：cmd.exe 默认使用 GBK (cp936)，需要使用系统默认编码
            import locale
            if platform.system() == 'Windows':
                # Windows cmd 默认使用 GBK 编码，使用 None 让 subprocess 自动检测
                result = subprocess.run(
                    exec_command,
                    shell=True,
                    cwd=skill_dir,
                    capture_output=True,
                    timeout=120,
                    env=env,
                )
                # 智能解码：先尝试 UTF-8（现代工具通常输出 UTF-8），失败再用 GBK（Windows cmd 默认）
                def smart_decode(data: bytes) -> str:
                    if not data:
                        return ''
                    try:
                        return data.decode('utf-8')
                    except UnicodeDecodeError:
                        return data.decode('gbk', errors='replace')
                
                stdout = smart_decode(result.stdout)
                stderr = smart_decode(result.stderr)
            else:
                result = subprocess.run(
                    exec_command,
                    shell=True,
                    cwd=skill_dir,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env=env,
                    encoding='utf-8',
                    errors='replace'
                )
                stdout = result.stdout or ''
                stderr = result.stderr or ''

            output = ''
            if stdout:
                output += stdout
            if stderr:
                if output:
                    output += '\n--- stderr ---\n'
                output += stderr

            if result.returncode != 0:
                output = f"命令执行失败 (退出码: {result.returncode})\n{output}"

            logger.info(f"[execute_skill_script] 执行完成, returncode={result.returncode}, output_len={len(output)}")
            if output:
                logger.debug(f"[execute_skill_script] output: {output[:500]}")
            result_output = output.strip() if output.strip() else "(无输出)"

            # 如果是 playwright-skill 的 run.js 调用但没有使用 session_id，提醒 LLM
            if skill_name == 'playwright-skill' and 'run.js' in command and not session_id:
                result_output = f"[SCREENSHOT_DIR] {screenshots_dir}\n{result_output}\n\n[注意] 此次执行未使用 session_id，浏览器已关闭。如果这是多步骤测试的一部分，请在后续调用中使用 session_id 参数保持浏览器会话。"
            elif skill_name == 'playwright-skill':
                result_output = f"[SCREENSHOT_DIR] {screenshots_dir}\n{result_output}"

            return result_output

        except subprocess.TimeoutExpired:
            logger.error("[execute_skill_script] 执行超时")
            return "错误: 命令执行超时（120秒）"
        except Exception as e:
            logger.error(f"[execute_skill_script] 执行失败: {e}", exc_info=True)
            return f"错误: {str(e)}"

    return [read_skill_content, execute_skill_script]
