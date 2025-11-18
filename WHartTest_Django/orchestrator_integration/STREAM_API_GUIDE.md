# Orchestrator流式对话接口使用指南

## 概述

Orchestrator流式接口允许Brain通过StateGraph调用各个Agent（Requirement、Knowledge、TestCase），所有交互过程以SSE（Server-Sent Events）流式返回，实现实时可见的智能编排过程。

## 接口信息

**端点**: `/api/orchestrator/stream/`  
**方法**: `POST`  
**认证**: JWT Bearer Token  
**响应类型**: `text/event-stream` (SSE)

## 请求格式

```json
{
  "message": "需求描述文本",
  "project_id": 1,
  "session_id": "可选的会话ID",
  "prompt_id": 可选的Brain提示词ID
}
```

### 参数说明

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `message` | string | 是 | 用户的需求描述 |
| `project_id` | integer | 是 | 项目ID，用于数据隔离和权限控制 |
| `session_id` | string | 否 | 会话ID，不提供则自动生成 |
| `prompt_id` | integer | 否 | 指定Brain使用的提示词ID（PromptType.BRAIN_ORCHESTRATOR） |

## 响应格式

SSE格式的事件流，每个事件包含JSON数据：

```
data: {"type": "event_type", ...}
```

### 事件类型

#### 1. `start` - 开始执行
```json
{
  "type": "start",
  "session_id": "abc123",
  "project_id": 1,
  "project_name": "项目名称",
  "requirement": "需求描述"
}
```

#### 2. `brain_decision` - Brain决策
```json
{
  "type": "brain_decision",
  "agent": "Brain",
  "next_agent": "requirement|knowledge|testcase|END",
  "instruction": "给子Agent的指令",
  "reason": "决策理由",
  "step": 1
}
```

#### 3. `requirement_analysis` - 需求分析完成
```json
{
  "type": "requirement_analysis",
  "agent": "Requirement",
  "analysis": {
    "功能描述": "...",
    "测试点": ["...", "..."],
    "业务规则": ["...", "..."],
    "边界条件": ["...", "..."]
  }
}
```

#### 4. `knowledge_retrieval` - 知识检索完成
```json
{
  "type": "knowledge_retrieval",
  "agent": "Knowledge",
  "doc_count": 5,
  "docs": [
    {
      "content": "文档内容摘要...",
      "metadata": {...}
    }
  ]
}
```

#### 5. `testcase_generation` - 测试用例生成完成
```json
{
  "type": "testcase_generation",
  "agent": "TestCase",
  "testcase_count": 3,
  "testcases": [
    {
      "用例ID": "TC001",
      "用例名称": "...",
      "测试步骤": ["...", "..."],
      "断言": ["...", "..."]
    }
  ]
}
```

#### 6. `agent_message` - Agent消息
```json
{
  "type": "agent_message",
  "agent": "Brain|Requirement|Knowledge|TestCase",
  "content": "消息内容"
}
```

#### 7. `final_summary` - 最终结果摘要
```json
{
  "type": "final_summary",
  "requirement_analysis": {...},
  "knowledge_doc_count": 5,
  "testcase_count": 3,
  "total_steps": 4
}
```

#### 8. `complete` - 任务完成
```json
{
  "type": "complete"
}
```

#### 9. `error` - 错误
```json
{
  "type": "error",
  "message": "错误信息"
}
```

#### 10. 流结束标记
```
data: [DONE]
```

## 工作流程

标准的执行流程：

```
1. Brain → 决策调用 Requirement Agent
2. Requirement Agent → 分析需求
3. （Agent可通过search_knowledge_base工具检索知识库）
5. Brain → 决策调用 TestCase Agent
6. TestCase Agent → 生成测试用例
7. Brain → 决策结束 (END)
8. 保存任务记录
```

## 使用示例

### Python (requests)

```python
import requests
import json

headers = {
    "Authorization": "Bearer YOUR_JWT_TOKEN",
    "Content-Type": "application/json",
}

payload = {
    "message": "实现用户登录功能",
    "project_id": 1,
}

response = requests.post(
    "http://localhost:8000/api/orchestrator/stream/",
    headers=headers,
    json=payload,
    stream=True
)

for line in response.iter_lines(decode_unicode=True):
    if line.startswith("data: "):
        data_str = line[6:]
        if data_str == "[DONE]":
            break
        data = json.loads(data_str)
        print(f"Event: {data['type']}")
```

### JavaScript (Fetch API)

```javascript
const response = await fetch('/api/orchestrator/stream/', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    message: '实现用户登录功能',
    project_id: 1,
  }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const text = decoder.decode(value);
  const lines = text.split('\n');
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const dataStr = line.substring(6);
      if (dataStr === '[DONE]') break;
      
      const data = JSON.parse(dataStr);
      console.log('Event:', data.type);
      
      // 根据事件类型处理
      switch (data.type) {
        case 'brain_decision':
          console.log('Brain决策:', data.next_agent);
          break;
        case 'testcase_generation':
          console.log('生成用例:', data.testcase_count);
          break;
        // ... 其他事件类型
      }
    }
  }
}
```

## 前端集成建议

### Vue.js示例

可以复用现有的`LangGraphChatView.vue`组件，添加"智能规划"按钮：

```vue
<template>
  <div class="chat-view">
    <!-- 现有的对话框 -->
    <chat-messages :messages="messages" />
    
    <!-- 添加智能规划按钮 -->
    <div class="action-buttons">
      <button @click="startOrchestrator" class="orchestrator-btn">
        🧠 智能规划
      </button>
    </div>
  </div>
</template>

<script>
export default {
  methods: {
    async startOrchestrator() {
      const requirement = this.inputMessage;
      
      // 切换到流式接口
      const response = await fetch('/api/orchestrator/stream/', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: requirement,
          project_id: this.currentProjectId,
        }),
      });
      
      // 处理SSE流
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const text = decoder.decode(value);
        this.processSSEChunk(text);
      }
    },
    
    processSSEChunk(text) {
      const lines = text.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = JSON.parse(line.substring(6));
          this.handleOrchestratorEvent(data);
        }
      }
    },
    
    handleOrchestratorEvent(data) {
      // 根据事件类型更新UI
      switch (data.type) {
        case 'brain_decision':
          this.addMessage({
            role: 'assistant',
            content: `🧠 Brain决策: ${data.next_agent}`,
            metadata: data,
          });
          break;
        case 'testcase_generation':
          this.addMessage({
            role: 'assistant',
            content: `✅ 生成了 ${data.testcase_count} 个测试用例`,
            testcases: data.testcases,
          });
          break;
        // ... 其他事件类型
      }
    },
  },
}
</script>
```

## 权限与隔离

- **项目隔离**: 任务自动关联到指定项目，只能访问该项目的知识库
- **权限验证**: 自动验证用户是否有项目访问权限
- **知识库访问**: 自动访问项目下所有激活的知识库，无需手动指定

## 提示词配置

Brain可以使用自定义提示词：

1. 在`prompts`模块创建`PromptType.BRAIN_ORCHESTRATOR`类型的提示词
2. 请求时通过`prompt_id`参数指定
3. 如果未指定，使用默认的Brain提示词

## 测试

使用提供的测试脚本：

```bash
# 设置环境变量
export JWT_TOKEN="your_token"
export PROJECT_ID=1

# 运行测试
python orchestrator_integration/test_stream.py
```

## 故障排查

### 1. 连接超时
- 检查Django服务器是否运行
- 确认防火墙允许SSE连接

### 2. 认证失败
- 验证JWT Token是否有效
- 检查Token是否包含正确的用户信息

### 3. 项目权限错误
- 确认用户是项目成员
- 检查项目ID是否正确

### 4. 知识库检索失败
- 确认项目下有激活的知识库
- 检查知识库向量数据是否正常

## 与非流式接口的对比

| 特性 | 流式接口 | 非流式接口 |
|------|---------|-----------|
| 实时反馈 | ✅ 是 | ❌ 否 |
| 用户体验 | ✅ 流畅 | ⚠️ 等待 |
| 错误处理 | ✅ 即时 | ⚠️ 延迟 |
| 前端复杂度 | ⚠️ 较高 | ✅ 较低 |
| 网络效率 | ✅ 高 | ⚠️ 一般 |

## 性能优化建议

1. **连接池管理**: 限制同时的SSE连接数
2. **超时设置**: 合理设置客户端超时时间（建议5分钟）
3. **缓冲控制**: 在Nginx中禁用缓冲 (`X-Accel-Buffering: no`)
4. **错误重试**: 客户端实现自动重连机制

## 下一步

- [ ] 前端集成到对话框
- [ ] 添加进度条显示
- [ ] 支持中断任务
- [ ] 增加任务历史查看