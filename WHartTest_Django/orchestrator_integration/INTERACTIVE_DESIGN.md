# 交互式智能编排系统设计

## 核心理念

Brain Agent 作为**思考和决策层**,与用户协作并动态调度子 Agent:

```
用户 ⇄ Brain Agent ⇄ 子 Agents
     (交互)      (决策)    (执行)
```

## 工作流程

### 阶段 1: 计划生成与确认

```
1. 用户提交需求
   ↓
2. Brain 分析需求,生成执行计划
   ↓
3. 用户查看计划,确认或调整
   ↓
4. 用户确认 → 进入执行阶段
```

### 阶段 2: 动态执行与决策

```
Brain 发出指令 → 子 Agent 执行
         ↓
    获取反馈结果
         ↓
   Brain 分析结果
         ↓
  ┌──────┴──────┐
  │             │
成功            遇到问题
  │             │
下一步          重新决策
```

## 状态机设计

```
pending → planning → waiting_confirmation → executing → completed
                                ↓                ↓
                            cancelled        failed
```

- **pending**: 任务已创建
- **planning**: Brain 正在生成计划
- **waiting_confirmation**: 等待用户确认计划
- **executing**: 执行中(Brain 持续决策)
- **completed**: 完成
- **failed**: 失败
- **cancelled**: 用户取消

## 数据模型扩展

### OrchestratorTask 新增字段:

```python
execution_plan = JSONField(null=True)  # Brain 生成的执行计划
{
    "steps": [
        {"agent": "requirement", "action": "分析需求", "reason": "..."},
        {"agent": "knowledge", "action": "检索文档", "reason": "..."},
        {"agent": "testcase", "action": "生成用例", "reason": "..."}
    ],
    "estimated_time": "5 minutes",
    "risks": ["可能需要更多知识库信息"]
}

execution_history = JSONField(default=list)  # 执行历史
[
    {
        "step": 1,
        "agent": "requirement",
        "action": "分析需求",
        "status": "completed",
        "result": {...},
        "brain_decision": "继续下一步",
        "timestamp": "..."
    },
    ...
]

current_step = IntegerField(default=0)  # 当前执行到第几步
waiting_for = CharField(max_length=50, blank=True)  # 等待什么 (user_confirmation, agent_result)
```

## API 接口设计

### 1. 创建任务并生成计划

```
POST /api/orchestrator/tasks/
{
    "requirement": "创建用户登录功能的测试用例",
    "knowledge_base_ids": [1, 2]
}

Response:
{
    "id": 1,
    "status": "planning",
    "requirement": "...",
    ...
}
```

后台 Celery 任务:
- Brain Agent 分析需求
- 生成执行计划
- 状态变为 `waiting_confirmation`

### 2. 获取执行计划

```
GET /api/orchestrator/tasks/{id}/plan/

Response:
{
    "status": "waiting_confirmation",
    "execution_plan": {
        "steps": [...],
        "estimated_time": "5 minutes",
        "risks": [...]
    }
}
```

### 3. 确认计划并开始执行

```
POST /api/orchestrator/tasks/{id}/confirm/
{
    "approved": true,
    "user_notes": "同意执行"
}

Response:
{
    "status": "executing",
    "message": "任务已开始执行"
}
```

后台 Celery 任务:
- Brain 开始调度子 Agent
- 每个子 Agent 执行后,Brain 分析结果
- Brain 决定下一步行动

### 4. 查看执行进度

```
GET /api/orchestrator/tasks/{id}/progress/

Response:
{
    "status": "executing",
    "current_step": 2,
    "total_steps": 3,
    "execution_history": [
        {
            "step": 1,
            "agent": "requirement",
            "status": "completed",
            "result": "需求分析完成",
            "brain_decision": "继续知识检索"
        },
        {
            "step": 2,
            "agent": "knowledge",
            "status": "executing",
            "progress": "正在检索知识库..."
        }
    ]
}
```

### 5. 获取最终结果

```
GET /api/orchestrator/tasks/{id}/

Response:
{
    "status": "completed",
    "requirement_analysis": {...},
    "knowledge_docs": [...],
    "testcases": [...],
    "execution_history": [...]
}
```

## Brain Agent 的决策逻辑

### 初始规划阶段

```python
def generate_execution_plan(requirement, knowledge_base_ids):
    """Brain 分析需求,生成执行计划"""
    prompt = f"""
    分析以下测试需求,制定执行计划:
    
    需求: {requirement}
    可用知识库: {knowledge_base_ids}
    
    请生成详细的执行计划,包括:
    1. 需要调用哪些子 Agent
    2. 每个 Agent 的具体任务
    3. 预计执行时间
    4. 可能的风险点
    
    输出 JSON 格式的计划。
    """
    
    plan = llm.invoke(prompt)
    return plan
```

### 执行阶段的动态决策

```python
def brain_execute_step(current_state, agent_result):
    """Brain 根据子 Agent 的执行结果,决定下一步"""
    prompt = f"""
    当前状态: {current_state}
    刚完成的任务: {agent_result}
    
    分析:
    1. 这一步执行得如何?
    2. 是否需要重试或调整?
    3. 下一步应该做什么?
    
    输出决策 JSON:
    {{
        "analysis": "结果分析",
        "next_action": "continue|retry|skip|end",
        "next_agent": "requirement|knowledge|testcase|END",
        "instruction": "给下一个 Agent 的指令",
        "reason": "决策理由"
    }}
    """
    
    decision = llm.invoke(prompt)
    return decision
```

## 实现要点

### 1. 两阶段的 Celery 任务

```python
@shared_task
def generate_plan_task(task_id):
    """阶段1: 生成执行计划"""
    task = OrchestratorTask.objects.get(id=task_id)
    task.status = 'planning'
    task.save()
    
    # Brain 生成计划
    plan = brain_agent.generate_execution_plan(
        task.requirement,
        task.knowledge_base_ids
    )
    
    task.execution_plan = plan
    task.status = 'waiting_confirmation'
    task.save()

@shared_task
def execute_plan_task(task_id):
    """阶段2: 执行计划"""
    task = OrchestratorTask.objects.get(id=task_id)
    task.status = 'executing'
    task.save()
    
    plan = task.execution_plan
    
    # 按计划逐步执行
    for step_idx, step in enumerate(plan['steps']):
        # 执行子 Agent
        result = execute_agent(step['agent'], step['action'])
        
        # Brain 分析结果并决策
        decision = brain_agent.analyze_and_decide(step, result)
        
        # 记录执行历史
        task.execution_history.append({
            "step": step_idx + 1,
            "agent": step['agent'],
            "result": result,
            "brain_decision": decision,
            "timestamp": now()
        })
        task.current_step = step_idx + 1
        task.save()
        
        # 根据 Brain 的决策继续或调整
        if decision['next_action'] == 'end':
            break
        elif decision['next_action'] == 'retry':
            # 重试逻辑
            pass
    
    task.status = 'completed'
    task.save()
```

### 2. LangGraph 的交互式集成

不使用自动循环的 `invoke()`,而是手动控制每一步:

```python
def execute_interactive_step(graph, current_state, next_agent):
    """执行单步,返回结果"""
    # 只执行一个节点
    result = graph.invoke_node(next_agent, current_state)
    return result
```

## 优势

1. **用户可控**: 用户在执行前可以审查计划
2. **动态调整**: Brain 可以根据执行情况实时调整策略
3. **透明度高**: 每一步的决策和结果都可见
4. **容错性强**: 遇到问题时 Brain 可以重试或跳过
5. **人机协作**: 充分发挥 AI 的智能和人的判断力

## 下一步实现顺序

1. ✅ 完成架构设计文档
2. 修改数据模型
3. 实现计划生成逻辑
4. 添加 API 接口
5. 实现交互式执行逻辑
6. 编写测试脚本