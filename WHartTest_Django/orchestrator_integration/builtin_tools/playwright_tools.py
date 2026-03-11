"""
Playwright 脚本管理工具集

提供以下工具：
- save_playwright_script: 保存脚本
- list_playwright_scripts: 列出脚本
- get_playwright_script: 获取脚本详情
- update_playwright_script: 更新脚本
- execute_playwright_script: 执行脚本
- get_script_execution_result: 获取执行结果
"""

import logging
from typing import Optional

from langchain_core.tools import tool as langchain_tool

logger = logging.getLogger('orchestrator_integration')


def get_playwright_tools(
    user_id: int,
    project_id: int,
    test_case_id: Optional[int] = None,
) -> list:
    """
    获取 Playwright 脚本管理工具列表
    
    Args:
        user_id: 当前用户 ID
        project_id: 当前项目 ID
        test_case_id: 关联的测试用例 ID（可选，用于 save 时的默认值）
    
    Returns:
        LangChain 工具列表
    """
    # 捕获上下文变量
    current_user_id = user_id
    current_project_id = project_id
    current_test_case_id = test_case_id
    
    # ==================== 保存脚本 ====================
    @langchain_tool
    def save_playwright_script(
        script_content: str,
        test_case_id: int = 0,
        description: str = ''
    ) -> str:
        """
        保存完整的 Playwright Python 测试脚本到数据库。
        
        调用此工具后，脚本将被保存并可在"自动化脚本管理"页面查看和执行。
        
        Args:
            script_content: 完整的 Playwright Python 脚本代码，必须包含 playwright 导入和完整的测试逻辑
            test_case_id: 关联的测试用例 ID（可选，不填则使用当前执行的测试用例）
            description: 脚本描述（可选）
        
        Returns:
            保存结果信息，包含脚本 ID 和名称
        """
        from testcases.models import TestCase, AutomationScript
        from django.db.models import Max
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        script_content = script_content.strip()
        
        if not script_content:
            return "错误：脚本内容为空"
        
        if 'playwright' not in script_content.lower():
            return "错误：脚本内容似乎不是 Playwright 脚本，请确保包含 playwright 导入"
        
        effective_test_case_id = test_case_id if test_case_id > 0 else current_test_case_id
        if not effective_test_case_id:
            return "错误：未指定测试用例 ID，请提供 test_case_id 参数"
        
        try:
            test_case = TestCase.objects.get(id=effective_test_case_id)
            
            if test_case.project_id != current_project_id:
                return f"错误：测试用例 {effective_test_case_id} 不属于当前项目"
            
            max_version = AutomationScript.objects.filter(
                test_case=test_case
            ).aggregate(Max('version'))['version__max'] or 0
            new_version = max_version + 1
            
            creator = User.objects.filter(id=current_user_id).first()
            
            script_name = f'{test_case.name}_v{new_version}'
            script = AutomationScript.objects.create(
                test_case=test_case,
                name=script_name,
                description=description or '由 AI 生成的自动化脚本',
                script_type='playwright_python',
                source='ai_generated',
                status='active',
                script_content=script_content,
                recorded_steps=[],
                target_url='',
                timeout_seconds=30,
                headless=True,
                version=new_version,
                creator=creator,
            )
            
            logger.info(f"[save_playwright_script] 脚本已保存: {script_name} (ID: {script.id})")
            return f"脚本已成功保存！\n- 脚本名称: {script_name}\n- 脚本 ID: {script.id}\n- 字符数: {len(script_content)}\n- 可在'自动化脚本管理'页面查看"
            
        except TestCase.DoesNotExist:
            return f"错误：测试用例 {effective_test_case_id} 不存在"
        except Exception as e:
            logger.error(f"[save_playwright_script] 保存失败: {e}", exc_info=True)
            return f"保存失败: {str(e)}"
    
    # ==================== 列出脚本 ====================
    @langchain_tool
    def list_playwright_scripts(
        test_case_id: int = 0,
        keyword: str = '',
        limit: int = 20
    ) -> str:
        """
        列出自动化脚本列表。
        
        可以按测试用例过滤，或按关键词搜索脚本名称。
        
        Args:
            test_case_id: 按测试用例 ID 过滤（可选）
            keyword: 按脚本名称搜索的关键词（可选）
            limit: 返回的最大数量，默认 20，最大 50
        
        Returns:
            脚本列表信息
        """
        from testcases.models import AutomationScript
        
        # 限制最大查询数量
        limit = min(max(1, limit), 50)
        
        try:
            queryset = AutomationScript.objects.filter(
                test_case__project_id=current_project_id
            ).select_related('test_case').order_by('-created_at')
            
            if test_case_id > 0:
                queryset = queryset.filter(test_case_id=test_case_id)
            
            if keyword:
                queryset = queryset.filter(name__icontains=keyword)
            
            scripts = list(queryset[:limit])
            
            if not scripts:
                return "未找到符合条件的脚本"
            
            result = f"找到 {len(scripts)} 个脚本：\n"
            for s in scripts:
                status_icon = "🟢" if s.status == 'active' else "⚪"
                result += f"\n{status_icon} [{s.id}] {s.name}\n"
                result += f"   关联用例: {s.test_case.name}\n"
                result += f"   版本: v{s.version}, 状态: {s.status}\n"
            
            return result
            
        except Exception as e:
            logger.error(f"[list_playwright_scripts] 查询失败: {e}", exc_info=True)
            return f"查询失败: {str(e)}"
    
    # ==================== 获取脚本详情 ====================
    @langchain_tool
    def get_playwright_script(script_id: int) -> str:
        """
        获取指定脚本的详细信息和代码内容。
        
        Args:
            script_id: 脚本 ID
        
        Returns:
            脚本详情，包含完整代码
        """
        from testcases.models import AutomationScript
        
        try:
            script = AutomationScript.objects.select_related(
                'test_case', 'creator'
            ).get(id=script_id)
            
            if script.test_case.project_id != current_project_id:
                return f"错误：脚本 {script_id} 不属于当前项目"
            
            # 获取最近执行记录
            latest_exec = script.executions.order_by('-created_at').first()
            exec_info = ""
            if latest_exec:
                exec_info = f"\n\n最近执行：\n- 状态: {latest_exec.status}\n- 时间: {latest_exec.created_at}\n- 耗时: {latest_exec.execution_time or 0:.2f}s"
                if latest_exec.error_message:
                    exec_info += f"\n- 错误: {latest_exec.error_message[:200]}"
            
            result = f"""脚本详情：
- ID: {script.id}
- 名称: {script.name}
- 关联用例: {script.test_case.name} (ID: {script.test_case.id})
- 版本: v{script.version}
- 状态: {script.status}
- 描述: {script.description or '无'}
- 创建者: {script.creator.username if script.creator else '未知'}
- 创建时间: {script.created_at}
{exec_info}

脚本代码：
```python
{script.script_content}
```"""
            return result
            
        except AutomationScript.DoesNotExist:
            return f"错误：脚本 {script_id} 不存在"
        except Exception as e:
            logger.error(f"[get_playwright_script] 查询失败: {e}", exc_info=True)
            return f"查询失败: {str(e)}"
    
    # ==================== 更新脚本 ====================
    @langchain_tool
    def update_playwright_script(
        script_id: int,
        script_content: str,
        description: str = ''
    ) -> str:
        """
        更新已有脚本的内容。
        
        注意：这会直接修改脚本内容，建议先查看当前内容再修改。
        
        Args:
            script_id: 脚本 ID
            script_content: 新的脚本代码
            description: 新的描述（可选，不填则保持原描述）
        
        Returns:
            更新结果
        """
        from testcases.models import AutomationScript
        
        script_content = script_content.strip()
        
        if not script_content:
            return "错误：脚本内容为空"
        
        if 'playwright' not in script_content.lower():
            return "错误：脚本内容似乎不是 Playwright 脚本"
        
        try:
            script = AutomationScript.objects.select_related('test_case').get(id=script_id)
            
            if script.test_case.project_id != current_project_id:
                return f"错误：脚本 {script_id} 不属于当前项目"
            
            old_length = len(script.script_content or '')
            script.script_content = script_content
            if description:
                script.description = description
            script.save()
            
            logger.info(f"[update_playwright_script] 脚本已更新: {script.name} (ID: {script.id})")
            return f"脚本已更新！\n- 脚本 ID: {script.id}\n- 脚本名称: {script.name}\n- 原长度: {old_length} 字符\n- 新长度: {len(script_content)} 字符"
            
        except AutomationScript.DoesNotExist:
            return f"错误：脚本 {script_id} 不存在"
        except Exception as e:
            logger.error(f"[update_playwright_script] 更新失败: {e}", exc_info=True)
            return f"更新失败: {str(e)}"
    
    # ==================== 执行脚本 ====================
    @langchain_tool
    def execute_playwright_script(
        script_id: int,
        headless: bool = True,
        record_video: bool = False
    ) -> str:
        """
        执行自动化脚本，与用户在界面点击"执行"按钮的效果完全一致。
        
        执行完成后会保存执行记录，包括输出日志、截图、错误信息等。
        
        Args:
            script_id: 脚本 ID
            headless: 是否无头模式执行，默认 True
            record_video: 是否录制视频，默认 False
        
        Returns:
            执行结果摘要
        """
        from testcases.models import AutomationScript
        from testcases.script_executor import execute_automation_script
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        try:
            script = AutomationScript.objects.select_related('test_case').get(id=script_id)
            
            if script.test_case.project_id != current_project_id:
                return f"错误：脚本 {script_id} 不属于当前项目"
            
            executor = User.objects.filter(id=current_user_id).first()
            
            logger.info(f"[execute_playwright_script] 开始执行脚本: {script.name} (ID: {script.id})")
            
            execution = execute_automation_script(
                script=script,
                executor=executor,
                headless=headless,
                record_video=record_video
            )
            
            result = f"""执行完成！

- 执行 ID: {execution.id}
- 状态: {execution.status}
- 耗时: {execution.execution_time or 0:.2f}s
- 截图数: {len(execution.screenshots or [])}
"""
            
            if execution.status == 'pass':
                result += f"\n输出日志:\n{execution.output or '(无输出)'}"
            else:
                result += f"\n错误信息:\n{execution.error_message or '(无错误信息)'}"
                if execution.stack_trace:
                    result += f"\n\n堆栈跟踪:\n{execution.stack_trace[:500]}"
            
            return result
            
        except AutomationScript.DoesNotExist:
            return f"错误：脚本 {script_id} 不存在"
        except Exception as e:
            logger.error(f"[execute_playwright_script] 执行失败: {e}", exc_info=True)
            return f"执行失败: {str(e)}"
    
    # ==================== 获取执行结果 ====================
    @langchain_tool
    def get_script_execution_result(
        execution_id: int = 0,
        script_id: int = 0
    ) -> str:
        """
        获取脚本执行结果详情。
        
        可以通过 execution_id 获取特定执行记录，或通过 script_id 获取该脚本的最新执行结果。
        
        Args:
            execution_id: 执行记录 ID（优先使用）
            script_id: 脚本 ID（获取最新执行结果）
        
        Returns:
            执行结果详情
        """
        from testcases.models import ScriptExecution, AutomationScript
        
        try:
            execution = None
            
            if execution_id > 0:
                # 直接在查询中过滤项目，避免 ID 枚举风险
                execution = ScriptExecution.objects.select_related(
                    'script', 'script__test_case', 'executor'
                ).filter(
                    id=execution_id,
                    script__test_case__project_id=current_project_id
                ).first()
                if not execution:
                    return f"错误：执行记录 {execution_id} 不存在或无权访问"
            elif script_id > 0:
                script = AutomationScript.objects.filter(
                    id=script_id,
                    test_case__project_id=current_project_id
                ).first()
                if not script:
                    return f"错误：脚本 {script_id} 不存在或不属于当前项目"
                execution = script.executions.order_by('-created_at').first()
                if not execution:
                    return f"脚本 {script_id} 尚未执行过"
            else:
                return "错误：请提供 execution_id 或 script_id"
            
            result = f"""执行结果详情：

- 执行 ID: {execution.id}
- 脚本: {execution.script.name} (ID: {execution.script.id})
- 状态: {execution.status}
- 执行时间: {execution.created_at}
- 耗时: {execution.execution_time or 0:.2f}s
- 执行人: {execution.executor.username if execution.executor else '未知'}
"""
            
            if execution.output:
                result += f"\n输出日志:\n{execution.output}\n"
            
            if execution.error_message:
                result += f"\n错误信息:\n{execution.error_message}\n"
            
            if execution.stack_trace:
                result += f"\n堆栈跟踪:\n{execution.stack_trace}\n"
            
            if execution.screenshots:
                result += f"\n截图 ({len(execution.screenshots)} 张):\n"
                for ss in execution.screenshots:
                    result += f"- /media/{ss}\n"
            
            return result
            
        except Exception as e:
            logger.error(f"[get_script_execution_result] 查询失败: {e}", exc_info=True)
            return f"查询失败: {str(e)}"
    
    # 返回所有工具
    return [
        save_playwright_script,
        list_playwright_scripts,
        get_playwright_script,
        update_playwright_script,
        execute_playwright_script,
        get_script_execution_result,
    ]
