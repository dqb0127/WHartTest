"""智能编排任务数据模型"""
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class OrchestratorTask(models.Model):
    """智能编排任务"""
    
    STATUS_CHOICES = [
        ('pending', '待处理'),
        ('planning', '规划中'),
        ('waiting_confirmation', '等待确认'),
        ('executing', '执行中'),
        ('completed', '已完成'),
        ('failed', '失败'),
        ('cancelled', '已取消'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orchestrator_tasks')
    project = models.ForeignKey(
        'projects.Project',
        on_delete=models.CASCADE,
        verbose_name='所属项目',
        help_text='任务必须关联到项目,用于数据隔离'
    )
    chat_session = models.ForeignKey('langgraph_integration.ChatSession', on_delete=models.SET_NULL,
                                     null=True, blank=True, verbose_name='关联对话会话',
                                     help_text='任务源自的对话会话')
    
    # 输入
    requirement = models.TextField(verbose_name='需求描述')
    # ❌ 移除 knowledge_base_ids,Brain自动访问项目下所有知识库
    
    # 状态
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending')
    
    # 交互式执行相关
    execution_plan = models.JSONField(null=True, blank=True, verbose_name='执行计划')
    execution_history = models.JSONField(default=list, blank=True, verbose_name='执行历史')
    current_step = models.IntegerField(default=0, verbose_name='当前步骤')
    waiting_for = models.CharField(max_length=50, blank=True, verbose_name='等待对象')
    user_notes = models.TextField(blank=True, verbose_name='用户备注')
    
    # 输出
    requirement_analysis = models.JSONField(null=True, blank=True, verbose_name='需求分析结果')
    knowledge_docs = models.JSONField(default=list, blank=True, verbose_name='检索的知识文档')
    testcases = models.JSONField(default=list, blank=True, verbose_name='生成的测试用例')
    
    # 执行记录(保留兼容性)
    execution_log = models.JSONField(default=list, blank=True, verbose_name='执行日志(旧)')
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    
    # 时间
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'orchestrator_task'
        ordering = ['-created_at']
        verbose_name = '智能编排任务'
        verbose_name_plural = verbose_name
    
    def __str__(self):
        return f"Task {self.id}: {self.requirement[:50]}"

