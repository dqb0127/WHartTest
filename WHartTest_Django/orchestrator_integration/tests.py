"""orchestrator_integration单元测试"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from unittest.mock import Mock, patch
from langchain_core.messages import AIMessage

from .models import OrchestratorTask
from .graph import create_orchestrator_graph, AgentNodes, OrchestratorState
from projects.models import Project

User = get_user_model()


class OrchestratorTaskModelTest(TestCase):
    """测试OrchestratorTask模型"""
    
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.project = Project.objects.create(
            name='TestProject',
            description='测试项目',
            creator=self.user
        )
    
    def test_create_task(self):
        """测试创建编排任务"""
        task = OrchestratorTask.objects.create(
            user=self.user,
            project=self.project,
            requirement="创建登录功能测试用例",
            knowledge_base_ids=[1, 2]
        )
        
        self.assertEqual(task.status, 'pending')
        self.assertEqual(task.requirement, "创建登录功能测试用例")
        self.assertEqual(task.knowledge_base_ids, [1, 2])
        self.assertIsNone(task.requirement_analysis)
        self.assertEqual(task.knowledge_docs, [])
        self.assertEqual(task.testcases, [])
    
    def test_task_status_flow(self):
        """测试任务状态流转"""
        task = OrchestratorTask.objects.create(
            user=self.user,
            project=self.project,
            requirement="测试需求",
            status='pending'
        )
        
        # pending -> running
        task.status = 'running'
        task.save()
        self.assertEqual(task.status, 'running')
        
        # running -> completed
        task.status = 'completed'
        task.requirement_analysis = {"title": "需求分析", "description": "详细分析"}
        task.testcases = [{"name": "test_login"}]
        task.save()
        
        self.assertEqual(task.status, 'completed')
        self.assertIsNotNone(task.requirement_analysis)
        self.assertTrue(len(task.testcases) > 0)


class OrchestratorGraphTest(TestCase):
    """测试LangGraph StateGraph编排逻辑"""
    
    def setUp(self):
        self.mock_llm = Mock()
    
    def test_brain_node_routing(self):
        """测试Brain节点路由决策"""
        # 模拟LLM返回下一个Agent决策
        self.mock_llm.invoke.return_value = AIMessage(
            content='{"next_agent": "requirement", "instruction": "分析需求", "reason": "首先需要理解需求"}'
        )
        
        nodes = AgentNodes(self.mock_llm)
        state = OrchestratorState(
            requirement="创建用户登录测试",
            knowledge_base_ids=[],
            messages=[],
            requirement_analysis=None,
            knowledge_docs=[],
            testcases=[],
            next_agent="",
            instruction="",
            reason="",
            current_step=0,
            max_steps=20
        )
        
        result = nodes.brain_node(state)
        
        self.assertEqual(result["next_agent"], "requirement")
        self.assertEqual(result["instruction"], "分析需求")
        self.assertTrue(len(result["messages"]) > 0)
    
    def test_requirement_node(self):
        """测试Requirement节点需求分析"""
        self.mock_llm.invoke.return_value = AIMessage(
            content='{"title": "用户登录测试", "description": "验证登录功能", "scope": "UI+API"}'
        )
        
        nodes = AgentNodes(self.mock_llm)
        state = OrchestratorState(
            requirement="创建登录测试",
            knowledge_base_ids=[],
            messages=[],
            requirement_analysis=None,
            knowledge_docs=[],
            testcases=[],
            next_agent="requirement",
            instruction="分析需求详情",
            reason="",
            current_step=1,
            max_steps=20
        )
        
        result = nodes.requirement_node(state)
        
        self.assertIsNotNone(result["requirement_analysis"])
        self.assertIn("title", result["requirement_analysis"])
    
    def test_graph_creation(self):
        """测试StateGraph创建"""
        graph = create_orchestrator_graph(self.mock_llm)
        
        self.assertIsNotNone(graph)
        # 验证图可以被编译（不会抛出异常）
        self.assertTrue(hasattr(graph, 'invoke'))
