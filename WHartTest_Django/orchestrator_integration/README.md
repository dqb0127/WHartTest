# 智能编排系统 (Orchestrator Integration)

## 概述

这是一个**实时流式**的智能编排系统,通过 Brain Agent 作为决策层,调度多个子 Agent 完成测试用例生成任务。所有交互过程通过 SSE 流式传输,用户可以实时看到 Brain 的决策和各个 Agent 的执行过程。

## ✨ 新特性：流式对话接口

**推荐使用流式接口** - 提供更好的用户体验和实时反馈！

详细文档请参阅：[**流式API使用指南**](STREAM_API_GUIDE.md)

### 快速开始

```bash
# 流式接口端点
POST /api/orchestrator/stream/

# 请求示例
{
  "message": "实现用户登录功能",
  "project_id": 1
}

# 返回SSE流式事件
data: {"type": "brain_decision", "next_agent": "requirement", ...}
data: {"type": "requirement_analysis", "analysis": {...}}
data: {"type": "testcase_generation", "testcases": [...]}
data: [DONE]
```

### 优势

- ✅ **实时反馈**: 用户可以看到Brain的每一步决策
- ✅ **流畅体验**: 无需等待,边执行边显示
- ✅ **透明过程**: 完整展示需求分析、知识检索、用例生成
- ✅ **易于集成**: 复用现有对话框,只需添加"智能规划"按钮

## 核心特性

### 🧠 Brain Agent 决策层
- 分析需求并生成执行计划
- 持续监控子 Agent 执行
- 根据执行结果动态调整策略

### 👥 人机协作
- 用户提交需求
- Brain 生成执行计划,**等待用户确认**
- 用户审查并确认后,才开始执行
- 执行过程透明可见

### 🤖 多 Agent 协同
- **Requirement Agent**: 需求分析专家
  
- **TestCase Agent**: 测试用例生成专家

## 工作流程

```
┌─────────────────────────────────────────────────────────┐
│ 1. 用户提交需求                                          │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Brain Agent 分析需求并生成执行计划                    │
│    - 理解需求                                            │
│    - 规划步骤                                            │
│    - 评估风险                                            │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│ 3. 展示计划,等待用户确认                                 │
│    ✓ 用户审查执行计划                                    │
│    ✓ 用户确认或取消                                      │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│ 4. Brain 调度子 Agent 执行                               │
│    → Requirement Agent 分析需求                          │
│    （Agent可自行调用search_knowledge_base工具）      │
│    → TestCase Agent 生成用例                             │
│    每步执行后,Brain 分析结果并决定下一步                  │
└────────────────┬────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────┐
│ 5. 返回最终结果                                          │
│    - 需求分析                                            │
│    - 知识文档                                            │
│    - 测试用例                                            │
└─────────────────────────────────────────────────────────┘
```

## API 接口

### 推荐：流式接口 ⭐

详细文档：[**流式API使用指南**](STREAM_API_GUIDE.md)

```bash
POST /api/orchestrator/stream/
{
    "message": "实现用户登录功能",
    "project_id": 1,
    "session_id": "可选",
    "prompt_id": 可选的Brain提示词ID
}

# SSE流式响应
data: {"type": "start", "session_id": "...", ...}
data: {"type": "brain_decision", "next_agent": "requirement", ...}
data: {"type": "requirement_analysis", "analysis": {...}}
data: {"type": "knowledge_retrieval", "doc_count": 5, ...}
data: {"type": "testcase_generation", "testcases": [...]}
data: {"type": "complete"}
data: [DONE]
```

### 传统REST接口（已过时）

**注意**: 以下接口已废弃,建议使用上面的流式接口。

### 1. 创建任务
```bash
POST /api/orchestrator/tasks/
{
    "requirement": "为用户登录功能创建测试用例",
    "project_id": 1
}

Response:
{
    "status": "success",
    "data": {
        "id": 1,
        "status": "pending",
        ...
    }
}
```

### 2. 查看执行计划
```bash
GET /api/orchestrator/tasks/{id}/plan/

Response (status=waiting_confirmation):
{
    "status": "success",
    "data": {
        "status": "waiting_confirmation",
        "execution_plan": {
            "需求理解": "...",
            "执行步骤": [
                {
                    "步骤": 1,
                    "agent": "requirement",
                    "任务": "分析需求",
                    "原因": "理解测试目标"
                },
                ...
            ],
            "预计时间": "5-10分钟",
            "风险点": [...]
        }
    }
}
```

### 3. 确认执行计划
```bash
POST /api/orchestrator/tasks/{id}/confirm/
{
    "approved": true,
    "user_notes": "同意执行"
}

Response:
{
    "status": "success",
    "data": {
        "message": "任务已开始执行"
    }
}
```

### 4. 查看执行进度
```bash
GET /api/orchestrator/tasks/{id}/progress/

Response:
{
    "status": "success",
    "data": {
        "status": "executing",
        "current_step": 2,
        "total_steps": 3,
        "progress_percent": 66,
        "execution_history": [
            {
                "步骤": 1,
                "agent": "requirement",
                "任务": "分析需求",
                "状态": "completed",
                "结果": {...}
            },
            ...
        ]
    }
}
```

### 5. 获取最终结果
```bash
GET /api/orchestrator/tasks/{id}/

Response:
{
    "status": "success",
    "data": {
        "status": "completed",
        "requirement_analysis": {...},
        "knowledge_docs": [...],
        "testcases": [...],
        "execution_history": [...]
    }
}
```

## 状态机

```
pending → planning → waiting_confirmation → executing → completed
                            ↓                   ↓
                        cancelled            failed
```

- **pending**: 任务已创建,排队中
- **planning**: Brain 正在生成计划
- **waiting_confirmation**: 等待用户确认
- **executing**: 执行中
- **completed**: 已完成
- **failed**: 失败
- **cancelled**: 用户取消

## 使用示例

### 流式接口测试（推荐）

1. **启动服务**
```bash
# 启动 Django
uv run python manage.py runserver
```

2. **运行流式测试**
```bash
# 设置环境变量
export JWT_TOKEN="your_token"
export PROJECT_ID=1

# 运行测试
python orchestrator_integration/test_stream.py
```

### 传统接口测试（已过时）

1. **启动服务**
```bash
# 启动 Django
uv run python manage.py runserver

# 启动 Celery (新终端) - 仅传统接口需要
celery -A wharttest_django worker -l info
```

2. **运行交互式测试**
```bash
cd orchestrator_integration/test_api
uv run python test_interactive_orchestrator.py
```

### Python 代码示例

#### 流式接口（推荐）

```python
import requests
import json

BASE_URL = "http://localhost:8000"
token = "your_jwt_token"
headers = {"Authorization": f"Bearer {token}"}

# 发送流式请求
response = requests.post(
    f"{BASE_URL}/api/orchestrator/stream/",
    json={
        "message": "实现用户登录功能",
        "project_id": 1,
    },
    headers=headers,
    stream=True  # 启用流式接收
)

# 处理SSE流
for line in response.iter_lines(decode_unicode=True):
    if line.startswith("data: "):
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        
        data = json.loads(data_str)
        event_type = data['type']
        
        if event_type == 'brain_decision':
            print(f"🧠 Brain决策: {data['next_agent']}")
        elif event_type == 'requirement_analysis':
            print(f"📝 需求分析: {data['analysis']}")
        elif event_type == 'testcase_generation':
            print(f"✅ 生成用例: {len(data['testcases'])} 个")
```

#### 传统接口（已过时）

```python
import requests
import time

BASE_URL = "http://localhost:8000"
token = "your_jwt_token"
headers = {"Authorization": f"Bearer {token}"}

# 1. 创建任务
response = requests.post(
    f"{BASE_URL}/api/orchestrator/tasks/",
    json={
        "requirement": "为用户登录功能创建测试用例",
        "project_id": 1
    },
    headers=headers
)
task_id = response.json()["data"]["id"]

# 2-5. 轮询进度...（省略,参见完整示例）
```

## 数据模型

### OrchestratorTask

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 任务ID |
| user | ForeignKey | 创建用户 |
| project | ForeignKey | 所属项目(自动使用项目下所有知识库) |
| requirement | TextField | 需求描述 |
| status | CharField | 任务状态 |
| execution_plan | JSONField | 执行计划 |
| execution_history | JSONField | 执行历史 |
| current_step | Integer | 当前步骤 |
| waiting_for | CharField | 等待对象 |
| user_notes | TextField | 用户备注 |
| requirement_analysis | JSONField | 需求分析结果 |
| knowledge_docs | JSONField | 知识文档 |
| testcases | JSONField | 测试用例 |

## 配置

### Celery 任务

- `generate_execution_plan`: 生成执行计划
- `execute_interactive_plan`: 执行交互式计划

### Agent 提示词

在 [`prompts.py`](prompts.py:1) 中可以自定义各个 Agent 的系统提示词:
- `BRAIN_AGENT_PROMPT`: Brain 决策提示词
- `REQUIREMENT_AGENT_PROMPT`: 需求分析提示词

- `TESTCASE_AGENT_PROMPT`: 测试用例生成提示词

## 故障排除

### 1. 任务一直处于 planning 状态
- 检查 Celery worker 是否启动
- 检查 LLM 配置是否正确
- 查看 Celery 日志

### 2. 执行计划格式错误
- LLM 返回的 JSON 格式不正确
- 查看 `tasks.py` 中的日志输出
- 调整 Brain Agent 的 prompt

### 3. 子 Agent 执行失败
- 检查知识库是否存在
- 检查 LLM API 是否正常
- 查看 execution_history 中的错误信息

## 开发

### 添加新的 Agent

1. 在 [`prompts.py`](prompts.py:1) 中添加提示词
2. 在 [`tasks.py`](tasks.py:1) 的 `_execute_agent_step` 中添加处理逻辑
3. 更新 Brain Agent 的决策逻辑

### 扩展执行计划格式

修改 [`tasks.py`](tasks.py:1) 中的 `generate_execution_plan` 函数的 prompt。

## 许可证

与项目主许可证相同