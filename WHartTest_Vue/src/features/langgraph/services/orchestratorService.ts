import { ref } from 'vue';
import request from '@/utils/request';

// --- 全局流式状态管理 (与chatService保持一致) ---
interface OrchestratorStreamMessage {
  content: string;
  type: 'human' | 'ai' | 'tool' | 'system';
  time: string;
  toolName?: string; // 工具名称(仅 tool 类型消息)
  isExpanded?: boolean;
  isThinkingProcess?: boolean; // 🎨 是否是思考过程
  isThinkingExpanded?: boolean; // 🎨 思考过程是否展开
}

interface OrchestratorStreamState {
  content: string; // 当前AI消息内容(流式累积)
  error?: string;
  isComplete: boolean;
  messages: OrchestratorStreamMessage[]; // 所有消息(包括工具消息)
  needsNewMessage?: boolean; // 标记需要创建新消息
  waitingForNextAgent?: boolean; // 等待下一个Agent的第一个消息
  nextAgent?: string; // 下一个Agent名称
  agentIdentityAdded?: boolean; // 标记是否已添加agent身份标识
  processedMessageCount?: number; // 已处理的消息数量（用于前端跟踪）
}

export const activeOrchestratorStreams = ref<Record<string, OrchestratorStreamState>>({});

export const clearOrchestratorStreamState = (sessionId: string) => {
  if (activeOrchestratorStreams.value[sessionId]) {
    delete activeOrchestratorStreams.value[sessionId];
  }
};

// --- 全局流式状态管理结束 ---

/**
 * Orchestrator任务状态
 */
export interface OrchestratorTask {
  id: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  requirement: string;
  requirement_analysis?: any;
  knowledge_docs?: any[];
  testcases?: any[];
  error_message?: string;
  created_at?: string;
  updated_at?: string;
}

interface ApiResponse<T> {
  status: 'success' | 'error';
  data: T;
  message: string;
}

/**
 * 创建Orchestrator任务
 */
export async function createOrchestratorTask(params: {
  requirement: string;
  project: number;
}): Promise<ApiResponse<OrchestratorTask>> {
  return await request({
    url: '/orchestrator/tasks/',
    method: 'POST',
    data: params
  });
}

/**
 * 获取Orchestrator任务状态
 */
export async function getOrchestratorTask(taskId: number): Promise<ApiResponse<OrchestratorTask>> {
  return await request({
    url: `/orchestrator/tasks/${taskId}/`,
    method: 'GET'
  });
}

/**
 * 轮询Orchestrator任务状态
 */
export async function pollOrchestratorTask(
  taskId: number,
  onUpdate?: (task: OrchestratorTask) => void,
  maxAttempts: number = 60,
  interval: number = 2000
): Promise<OrchestratorTask> {
  let attempts = 0;
  
  while (attempts < maxAttempts) {
    const response = await getOrchestratorTask(taskId);
    
    if (response.status === 'error') {
      throw new Error(response.message);
    }
    
    const task = response.data;
    
    if (onUpdate) {
      onUpdate(task);
    }
    
    if (task.status === 'completed' || task.status === 'failed') {
      return task;
    }
    
    await new Promise(resolve => setTimeout(resolve, interval));
    attempts++;
  }
  
  throw new Error('任务执行超时');
}

/**
 * 流式发送消息到Orchestrator Brain Agent (与chatService保持一致的结构)
 */
export async function sendOrchestratorStreamMessage(
  message: string,
  projectId: number,
  onStart: (sessionId: string) => void,
  signal?: AbortSignal,
  sessionId?: string  // 新增：可选的session_id参数
): Promise<void> {
  // 获取token
  const token = localStorage.getItem('auth-accessToken');
  let streamSessionId: string | null = sessionId || null;  // 使用传入的session_id

  // 错误处理函数
  const handleError = (error: any, sessionId: string | null) => {
    console.error('Orchestrator stream error:', error);
    if (sessionId && activeOrchestratorStreams.value[sessionId]) {
      activeOrchestratorStreams.value[sessionId].error = error.message || 'Orchestrator流式请求失败';
      activeOrchestratorStreams.value[sessionId].isComplete = true;
    }
  };

  if (!token) {
    handleError(new Error('未登录或登录已过期'), streamSessionId);
    return;
  }

  try {
    const response = await fetch('/api/orchestrator/stream/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        message,
        project_id: projectId,
        session_id: sessionId  // 传递session_id到后端
      }),
      signal
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();

    if (!reader) {
      throw new Error('Failed to get response reader');
    }

    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        // 流结束
        if (streamSessionId && activeOrchestratorStreams.value[streamSessionId] && !activeOrchestratorStreams.value[streamSessionId].isComplete) {
          activeOrchestratorStreams.value[streamSessionId].isComplete = true;
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.trim() === '' || !line.startsWith('data: ')) continue;

        const jsonData = line.slice(6);
        if (jsonData === '[DONE]') {
          if (streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            activeOrchestratorStreams.value[streamSessionId].isComplete = true;
          }
          continue;
        }

        try {
          const parsed = JSON.parse(jsonData);

          if (parsed.type === 'error') {
            handleError(new Error(parsed.message || 'Orchestrator流式请求失败'), streamSessionId);
            return;
          }

          // 处理start事件
          if (parsed.type === 'start' && parsed.session_id) {
            streamSessionId = parsed.session_id;
            if (streamSessionId) {
              // 初始化流状态
              activeOrchestratorStreams.value[streamSessionId] = {
                content: '',
                isComplete: false,
                messages: []
              };
              onStart(streamSessionId);
            }
          }

          // 处理工具调用开始事件(tool_start)
          if (parsed.type === 'tool_start' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            const toolName = parsed.tool_name || 'unknown_tool';
            const toolInputDetail = parsed.tool_input_detail || '';
            const toolInput = parsed.tool_input;
            
            const now = new Date();
            const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
            
            // 🔧 关键修复：先固化当前AI流式内容为独立消息，确保顺序正确
            if (activeOrchestratorStreams.value[streamSessionId].content && activeOrchestratorStreams.value[streamSessionId].content.trim()) {
              activeOrchestratorStreams.value[streamSessionId].messages.push({
                content: activeOrchestratorStreams.value[streamSessionId].content,
                type: 'ai',
                time: time,
                isExpanded: false
              });
              activeOrchestratorStreams.value[streamSessionId].content = '';
            }
            
            // 构建参数信息内容(工具名由标题显示)
            let toolContent = '';
            if (toolInputDetail) {
              toolContent = `**参数说明**: ${toolInputDetail}`;
            } else if (typeof toolInput === 'string' && toolInput === '无需参数') {
              toolContent = '该工具无需输入参数';
            } else if (toolInput && Object.keys(toolInput).length > 0) {
              toolContent = `**输入参数**:\n\`\`\`json\n${JSON.stringify(toolInput, null, 2)}\n\`\`\``;
            } else {
              toolContent = '该工具无需输入参数';
            }
            
            // 添加工具调用开始消息
            activeOrchestratorStreams.value[streamSessionId].messages.push({
              content: toolContent,
              type: 'tool',
              time: time,
              isExpanded: false
            });
            
            console.log('[Orchestrator] Tool start:', toolName, '参数:', toolInputDetail);
          }

          // 处理工具调用结束事件(tool_end)
          if (parsed.type === 'tool_end' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            const toolName = parsed.tool_name || 'unknown_tool';
            const toolOutput = parsed.tool_output || '';
            
            const now = new Date();
            const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
            
            // 🔧 关键修复：先固化当前AI流式内容，确保顺序正确
            if (activeOrchestratorStreams.value[streamSessionId].content && activeOrchestratorStreams.value[streamSessionId].content.trim()) {
              activeOrchestratorStreams.value[streamSessionId].messages.push({
                content: activeOrchestratorStreams.value[streamSessionId].content,
                type: 'ai',
                time: time,
                isExpanded: false
              });
              activeOrchestratorStreams.value[streamSessionId].content = '';
            }
            
            // 直接使用工具输出内容,前端 formatToolMessage 会自动美化
            activeOrchestratorStreams.value[streamSessionId].messages.push({
              content: toolOutput,
              type: 'tool',
              time: time,
              isExpanded: false
            });
            
            console.log('[Orchestrator] Tool end:', toolName, '输出长度:', toolOutput.length);
          }

          // 处理工具调用错误事件(tool_error)
          if (parsed.type === 'tool_error' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            const toolName = parsed.tool_name || 'unknown_tool';
            const errorInfo = parsed.error || 'Unknown error';
            
            const now = new Date();
            const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
            
            // 🔧 关键修复：先固化当前AI流式内容，确保顺序正确
            if (activeOrchestratorStreams.value[streamSessionId].content && activeOrchestratorStreams.value[streamSessionId].content.trim()) {
              activeOrchestratorStreams.value[streamSessionId].messages.push({
                content: activeOrchestratorStreams.value[streamSessionId].content,
                type: 'ai',
                time: time,
                isExpanded: false
              });
              activeOrchestratorStreams.value[streamSessionId].content = '';
            }
            
            // 添加工具调用错误消息
            activeOrchestratorStreams.value[streamSessionId].messages.push({
              content: `❌ 工具调用失败 (${toolName}):\n${errorInfo}`,
              type: 'tool',
              time: time,
              isExpanded: false
            });
            
            console.error('[Orchestrator] Tool error:', toolName, errorInfo);
          }

          // 处理工具消息(update事件 - 兼容旧版本,使用astream_events后这部分逻辑已不再需要)
          if (parsed.type === 'update' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            const updateData = parsed.data;
            if (typeof updateData === 'string') {
              // 解析工具消息: ToolMessage(content='...', name='tool_name', ...)
              if (updateData.includes('ToolMessage')) {
                try {
                  const contentMatch = updateData.match(/content='([^']*(?:\\'[^']*)*)'/);

                  if (contentMatch) {
                    const toolContent = contentMatch[1].replace(/\\'/g, "'").replace(/\\n/g, '\n');

                    const now = new Date();
                    const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;

                    // 如果当前有AI流式内容,先固化为独立消息
                    if (activeOrchestratorStreams.value[streamSessionId].content && activeOrchestratorStreams.value[streamSessionId].content.trim()) {
                      activeOrchestratorStreams.value[streamSessionId].messages.push({
                        content: activeOrchestratorStreams.value[streamSessionId].content,
                        type: 'ai',
                        time: time,
                        isExpanded: false
                      });
                      activeOrchestratorStreams.value[streamSessionId].content = '';
                    }

                    // 添加工具消息
                    activeOrchestratorStreams.value[streamSessionId].messages.push({
                      content: toolContent,
                      type: 'tool',
                      time: time,
                      isExpanded: false
                    });
                  }
                } catch (e) {
                  console.warn('Failed to parse tool message:', updateData);
                }
              }
            }
          }

          // 处理 brain_decision 事件 - Agent 切换信号
          if (parsed.type === 'brain_decision' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            // Brain决策完成,即将切换到下一个Agent
            // 标记需要创建新的消息占位符
            activeOrchestratorStreams.value[streamSessionId].needsNewMessage = true;
            activeOrchestratorStreams.value[streamSessionId].nextAgent = parsed.next_agent || 'unknown';
            activeOrchestratorStreams.value[streamSessionId].agentIdentityAdded = false; // 重置标志
            
            console.log('[Orchestrator] brain_decision: Agent switching from Brain to', parsed.next_agent);
          }

          // 处理AI消息(message事件) - 与ChatStreamAPIView保持一致的格式
          if (parsed.type === 'message' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            // 使用data字段，与chatService保持一致
            const messageData = parsed.data || parsed.content; // 兼容旧格式
            
            // 🔧 修复：处理新的JSON格式 {content: "xxx", additional_kwargs: {}, ...}
            if (typeof messageData === 'object' && messageData.content) {
              // 🎨 检查是否是思考过程（默认折叠）
              const isThinkingProcess = messageData.additional_kwargs?.is_thinking_process === true;
              
              // 🎨 所有思考过程消息（Brain决策 + 子Agent内部报告）都作为独立消息处理
              if (isThinkingProcess) {
                // 🔧 关键修复：思考过程消息先固化当前流式内容，确保顺序正确
                const now = new Date();
                const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
                
                // 先固化当前流式内容
                if (activeOrchestratorStreams.value[streamSessionId].content && 
                    activeOrchestratorStreams.value[streamSessionId].content.trim()) {
                  activeOrchestratorStreams.value[streamSessionId].messages.push({
                    content: activeOrchestratorStreams.value[streamSessionId].content,
                    type: 'ai',
                    time: time,
                    isExpanded: false
                  });
                  activeOrchestratorStreams.value[streamSessionId].content = '';
                }
                
                // 直接添加思考过程消息到messages数组，按接收顺序
                activeOrchestratorStreams.value[streamSessionId].messages.push({
                  content: messageData.content,
                  type: 'ai' as const,
                  time: time,
                  isExpanded: false,
                  isThinkingProcess: true,  // 🎨 标记为思考过程
                  isThinkingExpanded: false  // 🎨 默认折叠
                });
              } else {
                // 普通 AI 消息：累积到流式内容（不添加emoji身份标识，与历史记录格式一致）
                const contentToAdd = messageData.content;
                activeOrchestratorStreams.value[streamSessionId].content += contentToAdd;
              }
            } else if (typeof messageData === 'string') {
              // 旧格式（向后兼容）
              let content = '';
              if (messageData.includes('AIMessageChunk')) {
                const match = messageData.match(/content=(?:'([^']*)'|"([^"]*)")/);
                if (match) {
                  content = (match[1] || match[2] || '').replace(/\\'/g, "'").replace(/\\"/g, '"');
                }
              } else if (messageData.trim()) {
                content = messageData;
              }
              
              if (content) {
                activeOrchestratorStreams.value[streamSessionId].content += content;
              }
            }
          }

          // 处理agent_start事件 - Agent节点开始执行
          if (parsed.type === 'agent_start' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            const agentName = parsed.agent || 'Unknown';
            const now = new Date();
            const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
            
            // 🔧 如果当前有AI流式内容，先固化
            if (activeOrchestratorStreams.value[streamSessionId].content && 
                activeOrchestratorStreams.value[streamSessionId].content.trim()) {
              activeOrchestratorStreams.value[streamSessionId].messages.push({
                content: activeOrchestratorStreams.value[streamSessionId].content,
                type: 'ai',
                time: time,
                isExpanded: false
              });
              activeOrchestratorStreams.value[streamSessionId].content = '';
            }
            
            // 标记新agent开始（不再添加emoji身份标识）
            activeOrchestratorStreams.value[streamSessionId].nextAgent = agentName.toLowerCase();
            activeOrchestratorStreams.value[streamSessionId].agentIdentityAdded = false;
            
            console.log('[Orchestrator] Agent start:', agentName);
          }

          // 处理chat_response事件 - Chat Agent完成
          if (parsed.type === 'chat_response' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            console.log('[Orchestrator] Chat Agent completed');
            // Chat响应已通过message事件流式传输，此处仅日志
          }

          // 处理requirement_analysis事件 - Requirement Agent完成
          if (parsed.type === 'requirement_analysis' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            const analysis = parsed.analysis;
            const now = new Date();
            const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
            
            // 添加需求分析结果消息
            const analysisContent = `**需求分析完成**\n\n${JSON.stringify(analysis, null, 2)}`;
            activeOrchestratorStreams.value[streamSessionId].messages.push({
              content: analysisContent,
              type: 'system',
              time: time,
              isExpanded: false
            });
            
            console.log('[Orchestrator] Requirement analysis completed:', analysis);
          }

          // 处理testcase_generation事件 - TestCase Agent完成
          if (parsed.type === 'testcase_generation' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            const testcaseCount = parsed.testcase_count || 0;
            const now = new Date();
            const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
            
            // 添加测试用例生成结果消息
            const testcaseContent = `**测试用例生成完成**\n\n共生成 ${testcaseCount} 个测试用例`;
            activeOrchestratorStreams.value[streamSessionId].messages.push({
              content: testcaseContent,
              type: 'system',
              time: time,
              isExpanded: false
            });
            
            console.log('[Orchestrator] Testcase generation completed:', testcaseCount, 'cases');
          }

          // 处理final_summary事件 - 最终摘要
          if (parsed.type === 'final_summary' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            const summary = {
              requirement_analysis: parsed.requirement_analysis,
              knowledge_doc_count: parsed.knowledge_doc_count || 0,
              testcase_count: parsed.testcase_count || 0,
              total_steps: parsed.total_steps || 0
            };
            const now = new Date();
            const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
            
            // 🔧 如果有流式内容,先保存
            if (activeOrchestratorStreams.value[streamSessionId].content && 
                activeOrchestratorStreams.value[streamSessionId].content.trim()) {
              activeOrchestratorStreams.value[streamSessionId].messages.push({
                content: activeOrchestratorStreams.value[streamSessionId].content,
                type: 'ai',
                time: time,
                isExpanded: false
              });
              activeOrchestratorStreams.value[streamSessionId].content = '';
            }
            
            // 添加最终摘要消息
            const summaryContent = `**✅ 任务完成**\n\n` +
              `- 总步骤: ${summary.total_steps}\n` +
              `- 文档检索: ${summary.knowledge_doc_count} 个\n` +
              `- 测试用例: ${summary.testcase_count} 个`;
            
            activeOrchestratorStreams.value[streamSessionId].messages.push({
              content: summaryContent,
              type: 'system',
              time: time,
              isExpanded: false
            });
            
            console.log('[Orchestrator] Final summary:', summary);
          }

          // 处理complete事件
          if (parsed.type === 'complete' && streamSessionId && activeOrchestratorStreams.value[streamSessionId]) {
            activeOrchestratorStreams.value[streamSessionId].isComplete = true;
          }
        } catch (e) {
          console.warn('Failed to parse Orchestrator SSE data:', jsonData);
        }
      }
    }
  } catch (error) {
    handleError(error, streamSessionId);
  }
}

/**
 * Orchestrator流式事件类型 (支持astream_events的工具调用事件)
 */
export interface OrchestratorStreamEvent {
  type: 'start' | 'update' | 'message' | 'brain_decision' | 'agent_start' | 'chat_response' | 'requirement_analysis' | 'testcase_generation' | 'final_summary' | 'complete' | 'error' | 'tool_start' | 'tool_end' | 'tool_error';
  session_id?: string; // start事件的会话ID
  content?: string; // message事件的数据(向后兼容)
  data?: string; // message和update事件的数据(与ChatStreamAPIView统一格式)
  // brain_decision事件字段
  agent?: string;
  next_agent?: string;
  instruction?: string;
  reason?: string;
  step?: number;
  // agent_start事件字段 (agent名称在agent字段中)
  // requirement_analysis事件字段
  analysis?: any;
  // testcase_generation事件字段
  testcase_count?: number;
  testcases?: any[];
  // tool_start事件字段
  tool_name?: string;
  tool_input?: any;
  tool_input_detail?: string;
  // tool_end事件字段
  tool_output?: string;
  output_preview?: string;
  output_length?: number;
  // tool_error事件字段
  error?: string;
  // final_summary事件字段
  requirement_analysis?: any;
  knowledge_doc_count?: number;
  total_steps?: number;
  // error事件的错误信息
  message?: string;
}
