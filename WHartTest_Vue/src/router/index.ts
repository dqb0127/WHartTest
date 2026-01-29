import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';
import { useAuthStore } from '../store/authStore.ts'; // 导入 authStore
import MainLayout from '../layouts/MainLayout.vue'; // 导入主布局组件
import LoginView from '../views/LoginView.vue'; // 显式导入 LoginView
import RegisterView from '../views/RegisterView.vue'; // 导入 RegisterView
import DashboardView from '../views/DashboardView.vue'; // 显式导入 DashboardView
import UserManagementView from '../views/UserManagementView.vue'; // 导入用户管理页面
import OrganizationManagementView from '../views/OrganizationManagementView.vue'; // 导入组织管理页面
import PermissionManagementView from '../views/PermissionManagementView.vue'; // 导入权限管理页面
import ProjectManagementView from '../views/ProjectManagementView.vue'; // 导入项目管理页面
import TestCaseManagementView from '../views/TestCaseManagementView.vue'; // 导入用例管理页面
import TestSuiteManagementView from '../views/TestSuiteManagementView.vue'; // 导入测试套件管理页面
import TestExecutionHistoryView from '../views/TestExecutionHistoryView.vue'; // 导入执行历史页面
import LlmConfigManagementView from '@/features/langgraph/views/LlmConfigManagementView.vue'; // 导入 LLM 配置管理视图
import LangGraphChatView from '@/features/langgraph/views/LangGraphChatView.vue'; // 导入 LLM 聊天视图
import KnowledgeManagementView from '@/features/knowledge/views/KnowledgeManagementView.vue'; // 导入知识库管理视图
import ApiKeyManagementView from '@/views/ApiKeyManagementView.vue'; // 导入 API Key 管理视图
import RemoteMcpConfigManagementView from '@/views/RemoteMcpConfigManagementView.vue'; // 导入远程 MCP配置管理视图
import RequirementManagementView from '@/features/requirements/views/RequirementManagementView.vue'; // 导入需求管理视图
import DocumentDetailView from '@/features/requirements/views/DocumentDetailView.vue'; // 导入文档详情视图
import SpecializedReportView from '@/features/requirements/views/SpecializedReportView.vue'; // 导入专项分析报告视图
import AiDiagramView from '@/features/diagrams/views/AiDiagramView.vue'; // 导入 AI 图表视图
import SkillsManagementView from '@/features/skills/views/SkillsManagementView.vue'; // 导入 Skills 管理视图
import TemplateManagementView from '@/features/testcase-templates/views/TemplateManagementView.vue'; // 导入用例导入导出模版管理视图
import UiAutomationView from '@/features/ui-automation/views/UiAutomationView.vue'; // 导入 UI 自动化视图
import TraceDetailView from '@/features/ui-automation/views/TraceDetail.vue'; // 导入 Trace 详情视图

const routes: Array<RouteRecordRaw> = [
  {
    path: '/login',
    name: 'Login',
    component: LoginView
  },
  {
    path: '/register',
    name: 'Register',
    component: RegisterView
  },
  {
    path: '/', // 主应用布局的根路径
    component: MainLayout,
    meta: { requiresAuth: true },
    redirect: '/dashboard', // 默认重定向到首页
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: DashboardView,
      },
      {
        path: 'projects',
        name: 'ProjectManagement',
        component: ProjectManagementView,
      },
      {
        path: 'users',
        name: 'UserManagement',
        component: UserManagementView,
      },
      {
        path: 'organizations',
        name: 'OrganizationManagement',
        component: OrganizationManagementView,
      },
      {
        path: 'permissions',
        name: 'PermissionManagement',
        component: PermissionManagementView,
      },
      {
        path: 'testcases',
        name: 'TestCaseManagement',
        component: TestCaseManagementView,
      },
      {
        path: 'testsuites',
        name: 'TestSuiteManagement',
        component: TestSuiteManagementView,
      },
      {
        path: 'test-executions',
        name: 'TestExecutionHistory',
        component: TestExecutionHistoryView,
      },
      {
        path: 'llm-configs', // LLM 配置管理
        name: 'LlmConfigManagement',
        component: LlmConfigManagementView,
      },
      {
        path: 'langgraph-chat', // LLM 对话
        name: 'LangGraphChat',
        component: LangGraphChatView,
      },
      {
        path: 'knowledge-management', // 知识库管理
        name: 'KnowledgeManagement',
        component: KnowledgeManagementView,
      },
      {
        path: 'api-keys', // API Key 管理
        name: 'ApiKeyManagement',
        component: ApiKeyManagementView,
      },
      {
        path: 'remote-mcp-configs', // 远程MCP配置管理
        name: 'RemoteMcpConfigManagement',
        component: RemoteMcpConfigManagementView,
      },
      {
        path: 'requirements', // 需求管理
        name: 'RequirementManagement',
        component: RequirementManagementView,
      },
      {
        path: 'requirements/:id', // 文档详情
        name: 'DocumentDetail',
        component: DocumentDetailView,
      },
      {
        path: 'requirements/:id/report', // 评审报告（支持历史版本切换）
        name: 'ReportDetail',
        component: SpecializedReportView,
      },
      {
        path: 'ai-diagram', // AI 图表生成
        name: 'AiDiagram',
        component: AiDiagramView,
      },
      {
        path: 'skills', // Skills 管理
        name: 'SkillsManagement',
        component: SkillsManagementView,
      },
      {
        path: 'testcase-templates', // 用例导入导出模版管理
        name: 'TemplateManagement',
        component: TemplateManagementView,
      },
      {
        path: 'ui-automation', // UI 自动化
        name: 'UiAutomation',
        component: UiAutomationView,
      },
      {
        path: 'ui-automation/trace/:id', // Trace 详情页
        name: 'TraceDetail',
        component: TraceDetailView,
        props: true,
      },
      // 其他受保护的子路由可以加在这里
    ]
  },
  // Catch-all 路由：捕获所有未匹配的路径，重定向到首页
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    redirect: '/dashboard'
  }
];

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
});

router.beforeEach((to, _from, next) => {
  console.log('[Router Guard] 路由守卫触发:', { path: to.path, name: to.name, matched: to.matched.length });

  const authStore = useAuthStore();

  // 确保在每次导航前检查认证状态，特别是对于首次加载或刷新
  if (!authStore.isAuthenticated && typeof localStorage !== 'undefined') {
    authStore.checkAuthStatus();
  }

  const isLoggedIn = authStore.isAuthenticated;
  console.log('[Router Guard] 认证状态:', { isLoggedIn, toName: to.name });

  // 不需要认证的白名单路由
  const publicRoutes = ['Login', 'Register'];
  const isPublicRoute = publicRoutes.includes(to.name as string);

  if (!isLoggedIn && !isPublicRoute) {
    // 未登录且不是公开路由，重定向到登录页
    console.log('[Router Guard] 未登录，重定向到登录页');
    next({ name: 'Login', query: { redirect: to.fullPath } });
  } else if (isLoggedIn && isPublicRoute) {
    // 已登录但访问登录/注册页，重定向到首页
    console.log('[Router Guard] 已登录，重定向到首页');
    next({ name: 'Dashboard' });
  } else {
    console.log('[Router Guard] 放行');
    next();
  }
});

export default router;