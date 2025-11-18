<template>
  <div class="chat-layout">
    <!-- 左侧历史对话列表 -->
    <ChatSidebar
      :sessions="chatSessions"
      :current-session-id="sessionId"
      :is-loading="isLoading"
      @create-new-chat="createNewChat"
      @switch-session="switchSession"
      @delete-session="deleteSession"
      @batch-delete-sessions="batchDeleteSessions"
    />

    <!-- 右侧聊天区域 -->
    <div class="chat-container">
      <ChatHeader
        ref="chatHeaderRef"
        :session-id="sessionId"
        :is-stream-mode="isStreamMode"
        :has-messages="messages.length > 0"
        :project-id="projectStore.currentProjectId"
        :use-knowledge-base="useKnowledgeBase"
        :selected-knowledge-base-id="selectedKnowledgeBaseId"
        :similarity-threshold="similarityThreshold"
        :top-k="topK"
        :selected-prompt-id="selectedPromptId"
        :brain-mode="isBrainMode"
        @update:is-stream-mode="isStreamMode = $event"
        @clear-chat="clearChat"
        @show-system-prompt="showSystemPromptModal"
        @update:use-knowledge-base="useKnowledgeBase = $event"
        @update:selected-knowledge-base-id="selectedKnowledgeBaseId = $event"
        @update:similarity-threshold="similarityThreshold = $event"
        @update:top-k="topK = $event"
        @update:selected-prompt-id="selectedPromptId = $event"
      />

      <ChatMessages
        :messages="displayedMessages"
        :is-loading="isLoading && messages.length === 0"
        @toggle-expand="toggleExpand"
      />

      <ChatInput
        :is-loading="isLoading"
        :has-prompts="hasPrompts"
        :supports-vision="currentLlmConfig?.supports_vision || false"
        v-model:brain-mode="isBrainMode"
        @send-message="handleSendMessage"
      />
    </div>

    <!-- 系统提示词管理弹窗 -->
    <SystemPromptModal
      :visible="isSystemPromptModalVisible"
      :current-llm-config="currentLlmConfig"
      :loading="isSystemPromptLoading"
      @update-system-prompt="handleUpdateSystemPrompt"
      @cancel="closeSystemPromptModal"
      @prompts-updated="handlePromptsUpdated"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onActivated, watch, onUnmounted, computed } from 'vue';
import { Message, Modal } from '@arco-design/web-vue';
import {
  sendChatMessage,
  sendChatMessageStream,
  getChatHistory,
  deleteChatHistory,
  batchDeleteChatHistory,
  getChatSessions,
  activeStreams,
  clearStreamState
} from '@/features/langgraph/services/chatService';
import { listLlmConfigs, partialUpdateLlmConfig } from '@/features/langgraph/services/llmConfigService';
import { getUserPrompts } from '@/features/prompts/services/promptService';
import { 
  sendOrchestratorStreamMessage, 
  activeOrchestratorStreams,
  clearOrchestratorStreamState
} from '@/features/langgraph/services/orchestratorService';
import type { ChatRequest } from '@/features/langgraph/types/chat';
import type { LlmConfig } from '@/features/langgraph/types/llmConfig';
import { useProjectStore } from '@/store/projectStore';
import { useLlmConfigRefresh } from '@/composables/useLlmConfigRefresh';
import { marked } from 'marked';

// 导入子组件
import ChatSidebar from '../components/ChatSidebar.vue';
import ChatHeader from '../components/ChatHeader.vue';
import ChatMessages from '../components/ChatMessages.vue';
import ChatInput from '../components/ChatInput.vue';
import SystemPromptModal from '../components/SystemPromptModal.vue';

// 配置marked
marked.setOptions({
  breaks: true,
  gfm: true
});

interface ChatMessage {
  content: string;
  isUser: boolean;
  time: string;
  isLoading?: boolean;
  messageType?: 'human' | 'ai' | 'tool' | 'system';
  toolName?: string;
  isExpanded?: boolean;
  isStreaming?: boolean;
  imageBase64?: string;
  imageDataUrl?: string;
  isThinkingProcess?: boolean;
  isThinkingExpanded?: boolean;
}

interface ChatSession {
  id: string;
  title: string;
  lastTime: Date;
  messageCount: number;
}

const messages = ref<ChatMessage[]>([]);
const isLoading = ref(false);
const sessionId = ref<string>('');
const chatSessions = ref<ChatSession[]>([]);
const isStreamMode = ref(true); // 流式模式开关，默认开启

// ⭐大脑模式开关 - 从localStorage加载
const loadBrainModeState = (): boolean => {
  const saved = localStorage.getItem('langgraph_brain_mode');
  return saved === 'true';
};
const isBrainMode = ref(loadBrainModeState());

// 知识库相关
const useKnowledgeBase = ref(false); // 是否启用知识库功能
const selectedKnowledgeBaseId = ref<string | null>(null); // 选中的知识库ID
const similarityThreshold = ref(0.3); // 相似度阈值
const topK = ref(5); // 检索结果数量

// 提示词相关
const selectedPromptId = ref<number | null>(null); // 用户选择的提示词ID
const hasPrompts = ref(false); // 是否有可用的提示词

// ⭐从localStorage恢复选中的提示词
const PROMPT_STORAGE_KEY = 'wharttest_selected_prompt_id';
const loadSavedPromptId = () => {
  try {
    const saved = localStorage.getItem(PROMPT_STORAGE_KEY);
    if (saved) {
      selectedPromptId.value = parseInt(saved, 10);
    }
  } catch (error) {
    console.error('加载保存的提示词ID失败:', error);
  }
};

// ⭐监听selectedPromptId变化,保存到localStorage
watch(selectedPromptId, (newValue) => {
  try {
    if (newValue !== null) {
      localStorage.setItem(PROMPT_STORAGE_KEY, String(newValue));
    } else {
      localStorage.removeItem(PROMPT_STORAGE_KEY);
    }
  } catch (error) {
    console.error('保存提示词ID失败:', error);
  }
});


// 系统提示词相关
const isSystemPromptModalVisible = ref(false);
const isSystemPromptLoading = ref(false);
const currentLlmConfig = ref<LlmConfig | null>(null);

// 项目store
const projectStore = useProjectStore();
const { getRefreshTrigger } = useLlmConfigRefresh();

// 组件引用
const chatHeaderRef = ref<{ refreshPrompts: () => Promise<void> } | null>(null);

// 终止控制器
let abortController = new AbortController();

// 定时刷新控制
let historyRefreshTimer: number | null = null;
const isAutoRefreshing = ref(false); // 是否正在自动刷新
let isMountedLoadComplete = false; // 标记onMounted是否完成了首次加载

// 静默加载历史记录(不显示loading状态)
const loadChatHistorySilently = async () => {
  const storedSessionId = getSessionIdFromStorage();
  if (!storedSessionId || !projectStore.currentProjectId) return;

  try {
    const response = await getChatHistory(storedSessionId, projectStore.currentProjectId);

    if (response.status === 'success') {
      const currentMessageCount = messages.value.length;
      const historyMessageCount = response.data.history.filter(h => h.type !== 'system').length;
      
      // 只有当历史记录数量增加时才更新(说明有新消息)
      if (historyMessageCount > currentMessageCount) {
        console.log(`📥 检测到新消息: ${historyMessageCount - currentMessageCount}条`);
        
        // 🎨 保存当前的展开状态
        const expandedStates = new Map<string, boolean>();
        messages.value.forEach(msg => {
          if (msg.isThinkingProcess && msg.isThinkingExpanded) {
            const key = msg.content.substring(0, 100);
            expandedStates.set(key, true);
          }
        });
        
        // 清空当前消息列表
        messages.value = [];

        // 重新加载所有消息
        const tempMessages: ChatMessage[] = [];
        response.data.history.forEach(historyItem => {
          if (historyItem.type === 'system') {
            return;
          }

          const message: ChatMessage = {
            content: historyItem.content,
            isUser: historyItem.type === 'human',
            time: formatHistoryTime(historyItem.timestamp),
            messageType: historyItem.type
          };

          if (historyItem.type === 'tool') {
            message.isExpanded = false;
          }

          // 🎨 如果是思考过程消息，设置折叠状态
          if (historyItem.is_thinking_process) {
            message.isThinkingProcess = true;
            message.isThinkingExpanded = false;
          }

          // 如果消息包含图片，添加图片数据
          if (historyItem.image) {
            message.imageDataUrl = historyItem.image;
          }

          tempMessages.push(message);
        });

        // 🎨 合并连续的思考过程消息
        messages.value = mergeThinkingProcessMessages(tempMessages);
        
        // 🎨 恢复展开状态
        messages.value.forEach(msg => {
          if (msg.isThinkingProcess) {
            const key = msg.content.substring(0, 100);
            if (expandedStates.has(key)) {
              msg.isThinkingExpanded = true;
            }
          }
        });
      }
    }
  } catch (error) {
    console.error('静默刷新历史记录失败:', error);
    // 静默失败,不显示错误提示
  }
};

// 停止自动刷新
const stopAutoRefresh = () => {
  if (historyRefreshTimer) {
    clearInterval(historyRefreshTimer);
    historyRefreshTimer = null;
  }
  isAutoRefreshing.value = false;
};

// 智能定时刷新历史记录(仅在非流式状态下)
const startAutoRefresh = () => {
  // 如果已经在刷新,先停止
  stopAutoRefresh();
  
  historyRefreshTimer = window.setInterval(async () => {
    // 只在以下条件下刷新:
    // 1. 有会话ID
    // 2. 不在流式输出中(没有活跃流或流已完成)
    // 3. 不在加载状态
    if (sessionId.value && !isLoading.value) {
      const stream = activeStreams.value[sessionId.value];
      const isStreaming = stream && !stream.isComplete;
      
      if (!isStreaming) {
        console.log('🔄 自动刷新历史记录...');
        isAutoRefreshing.value = true;
        await loadChatHistorySilently();
        isAutoRefreshing.value = false;
      } else {
        console.log('⏸️ 跳过刷新(流式输出进行中)');
      }
    }
  }, 3000); // 每3秒检查一次
};

// 在本地存储中保存会话ID
const saveSessionId = (id: string) => {
  localStorage.setItem('langgraph_session_id', id);
  sessionId.value = id;
};

// 从本地存储中获取会话ID
const getSessionIdFromStorage = (): string | null => {
  return localStorage.getItem('langgraph_session_id');
};

// 保存知识库设置到本地存储
const saveKnowledgeBaseSettings = () => {
  const settings = {
    useKnowledgeBase: useKnowledgeBase.value,
    selectedKnowledgeBaseId: selectedKnowledgeBaseId.value,
    similarityThreshold: similarityThreshold.value,
    topK: topK.value
  };
  localStorage.setItem('langgraph_knowledge_settings', JSON.stringify(settings));
};

// 从本地存储加载知识库设置
const loadKnowledgeBaseSettings = () => {
  const settingsJson = localStorage.getItem('langgraph_knowledge_settings');
  if (settingsJson) {
    try {
      const settings = JSON.parse(settingsJson);
      useKnowledgeBase.value = settings.useKnowledgeBase ?? false;
      selectedKnowledgeBaseId.value = settings.selectedKnowledgeBaseId ?? null;
      similarityThreshold.value = settings.similarityThreshold ?? 0.3;
      topK.value = settings.topK ?? 5;
      console.log('✅ 知识库设置加载完成:', settings);
    } catch (error) {
      console.error('❌ 加载知识库设置失败:', error);
    }
  }
};

// 从本地存储加载会话列表


// 保存会话列表到本地存储
const saveSessionsToStorage = () => {
  localStorage.setItem('langgraph_sessions', JSON.stringify(chatSessions.value));
};

// 从服务器加载会话列表
const loadSessionsFromServer = async () => {
  // 🔧 修复：静默处理没有项目ID的情况
  if (!projectStore.currentProjectId) {
    console.log('⏳ 等待项目加载完成，暂不加载会话列表');
    return;
  }

  try {
    isLoading.value = true;
    const response = await getChatSessions(projectStore.currentProjectId);

    if (response.status === 'success') {
      // 获取到会话ID列表后，需要为每个会话获取历史记录以显示标题
      const sessionsData = response.data.sessions;

      // 🔧 修复：使用临时数组收集会话，避免直接操作 chatSessions.value 导致的重复问题
      const tempSessions: ChatSession[] = [];

      // 如果没有会话，清空列表并返回
      if (sessionsData.length === 0) {
        chatSessions.value = [];
        saveSessionsToStorage();
        isLoading.value = false;
        return;
      }

      // 为了避免一次发送太多请求，限制并发数量
      const BATCH_SIZE = 3; // 一次处理3个会话

      // 分批处理会话
      for (let i = 0; i < sessionsData.length; i += BATCH_SIZE) {
        const batch = sessionsData.slice(i, i + BATCH_SIZE);
        await Promise.all(batch.map(async (sessionId) => {
          try {
            // 为每个会话获取历史记录
            const historyResponse = await getChatHistory(sessionId, projectStore.currentProjectId!);
            if (historyResponse.status === 'success') {
              const history = historyResponse.data.history;
              // 使用第一条人类消息作为标题
              const firstHumanMessage = history.find(msg => msg.type === 'human')?.content || '';
              const title = firstHumanMessage
                ? (firstHumanMessage.length > 20 ? `${firstHumanMessage.substring(0, 20)}...` : firstHumanMessage)
                : '未命名对话';

              // 获取最后一条消息的时间戳作为会话时间
              const lastMessage = history[history.length - 1];
              let lastTime = new Date();
              if (lastMessage?.timestamp) {
                try {
                  // 处理时间戳格式，确保正确解析
                  const timestamp = lastMessage.timestamp;
                  // 如果时间戳格式是 "YYYY-MM-DD HH:MM:SS"，需要确保正确解析
                  lastTime = new Date(timestamp.replace(' ', 'T'));
                  // 检查日期是否有效
                  if (isNaN(lastTime.getTime())) {
                    lastTime = new Date();
                  }
                } catch (error) {
                  console.error('解析会话时间戳失败:', error);
                  lastTime = new Date();
                }
              }

              // 🔧 修复：添加到临时数组，避免重复
              tempSessions.push({
                id: sessionId,
                title,
                lastTime,
                messageCount: history.length
              });
            } else {
              // 🔧 修复：如果获取历史失败（会话可能已损坏），仍然显示在列表中但标记为异常
              console.warn(`⚠️ 会话 ${sessionId} 历史记录获取失败，状态: ${historyResponse.status}`);
              tempSessions.push({
                id: sessionId,
                title: `会话 ${sessionId.substring(0, 8)}... (历史记录异常)`,
                lastTime: new Date(),
                messageCount: 0
              });
            }
          } catch (error) {
            // 🔧 修复：网络错误或其他异常，仍然显示会话但标记为异常
            console.error(`❌ 获取会话 ${sessionId} 历史记录异常:`, error);
            tempSessions.push({
              id: sessionId,
              title: `会话 ${sessionId.substring(0, 8)}... (加载失败)`,
              lastTime: new Date(),
              messageCount: 0
            });
          }
        }));
      }

      // 🔧 修复：按时间倒序排序后，一次性替换整个列表
      tempSessions.sort((a, b) => b.lastTime.getTime() - a.lastTime.getTime());
      chatSessions.value = tempSessions;

      console.log(`✅ 从服务器加载了 ${tempSessions.length} 个会话`);

      // 保存到本地存储作为备份
      saveSessionsToStorage();
    } else {
      Message.error('获取会话列表失败');
      // 🔧 修复：如果服务器获取失败，不从本地存储加载，避免加载旧的重复数据
      // loadSessionsFromStorage();
    }
  } catch (error) {
    console.error('获取会话列表失败:', error);
    Message.error('获取会话列表失败，请稍后重试');
    // 🔧 修复：如果服务器请求出错，不从本地存储加载，避免加载旧的重复数据
    // loadSessionsFromStorage();
  } finally {
    isLoading.value = false;
  }
};

// 加载聊天历史记录
const loadChatHistory = async () => {
  const storedSessionId = getSessionIdFromStorage();
  
  // 🔧 修复：静默处理无会话ID的情况，不显示任何提示
  if (!storedSessionId) {
    console.log('💭 没有保存的会话ID，显示空白对话界面');
    return;
  }
  
  // 如果没有项目ID，也静默返回（watch会在项目加载完成后重新调用）
  if (!projectStore.currentProjectId) {
    console.log('⏳ 等待项目加载完成...');
    return;
  }

  try {
    isLoading.value = true;
    const response = await getChatHistory(storedSessionId, projectStore.currentProjectId);

    if (response.status === 'success') {
      sessionId.value = response.data.session_id;

      // 清空当前消息列表
      messages.value = [];

      // 将历史记录转换为消息格式
      const tempMessages: ChatMessage[] = [];
      response.data.history.forEach(historyItem => {
        // 🆕 跳过系统消息，不在消息列表中显示
        if (historyItem.type === 'system') {
          return;
        }

        const message: ChatMessage = {
          content: historyItem.content,
          isUser: historyItem.type === 'human',
          time: formatHistoryTime(historyItem.timestamp),
          messageType: historyItem.type
        };

        // 如果是工具消息，设置默认折叠状态
        if (historyItem.type === 'tool') {
          message.isExpanded = false;
        }

        // 🎨 如果是思考过程消息，设置折叠状态
        if (historyItem.is_thinking_process) {
          message.isThinkingProcess = true;
          message.isThinkingExpanded = false;
        }

        // 如果消息包含图片，添加图片数据
        if (historyItem.image) {
          message.imageDataUrl = historyItem.image;
        }

        tempMessages.push(message);
      });

      // 🎨 合并连续的思考过程消息
      messages.value = mergeThinkingProcessMessages(tempMessages);

      // 只有在会话列表中不存在该会话时才添加（避免重复）
      const existingSession = chatSessions.value.find(s => s.id === response.data.session_id);
      if (!existingSession) {
        const firstHumanMessage = response.data.history.find(msg => msg.type === 'human')?.content;
        updateSessionInList(response.data.session_id, firstHumanMessage, false);
      }
      
      console.log(`✅ 成功加载会话历史: ${sessionId.value}, ${messages.value.length} 条消息`);
    } else {
      // 🔧 修复：获取历史失败时静默处理，不显示错误提示
      // 可能是会话已被删除或过期，清除存储的会话ID即可
      console.warn('⚠️ 会话历史获取失败，可能已被删除');
      localStorage.removeItem('langgraph_session_id');
      sessionId.value = '';
    }
  } catch (error) {
    // 🔧 修复：网络错误等异常情况才显示错误提示
    console.error('❌ 加载聊天历史异常:', error);
    // 只在真正的错误情况下提示用户
    Message.error('加载聊天历史失败，将开始新的对话');
    localStorage.removeItem('langgraph_session_id');
    sessionId.value = '';
  } finally {
    isLoading.value = false;
  }
};

// 获取当前时间
const getCurrentTime = () => {
  const now = new Date();
  return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
};

// 获取Agent的emoji标识


// 🎨 合并连续的思考过程消息（保持对象引用，避免丢失状态）
const mergeThinkingProcessMessages = (messages: ChatMessage[]): ChatMessage[] => {
  const result: ChatMessage[] = [];
  let thinkingBuffer: ChatMessage[] = [];

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    
    if (msg.isThinkingProcess) {
      thinkingBuffer.push(msg);
    } else {
      // 遇到非思考过程消息，先处理缓冲区
      if (thinkingBuffer.length > 0) {
        if (thinkingBuffer.length === 1) {
          // 只有一个思考过程，直接添加
          result.push(thinkingBuffer[0]);
        } else {
          // 多个思考过程，合并内容到第一个对象（保持响应性）
          const merged = thinkingBuffer[0];
          merged.content = thinkingBuffer.map(m => m.content).join('\n\n---\n\n');
          result.push(merged);
        }
        thinkingBuffer = [];
      }
      // 添加当前非思考过程消息
      result.push(msg);
    }
  }

  // 处理末尾剩余的思考过程消息
  if (thinkingBuffer.length > 0) {
    if (thinkingBuffer.length === 1) {
      result.push(thinkingBuffer[0]);
    } else {
      const merged = thinkingBuffer[0];
      merged.content = thinkingBuffer.map(m => m.content).join('\n\n---\n\n');
      result.push(merged);
    }
  }

  return result;
};

// 获取Agent的中文名称


// 格式化历史消息时间
const formatHistoryTime = (timestamp: string) => {
  if (!timestamp) return getCurrentTime();

  try {
    // 处理时间戳格式，确保正确解析
    // 如果时间戳格式是 "YYYY-MM-DD HH:MM:SS"，转换为 ISO 格式
    const isoTimestamp = timestamp.includes('T') ? timestamp : timestamp.replace(' ', 'T');
    const date = new Date(isoTimestamp);

    // 检查日期是否有效
    if (isNaN(date.getTime())) {
      return getCurrentTime();
    }

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const messageDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());

    // 如果是今天的消息，只显示时间
    if (messageDate.getTime() === today.getTime()) {
      return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
    }

    // 如果是昨天的消息
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);
    if (messageDate.getTime() === yesterday.getTime()) {
      return `昨天 ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
    }

    // 如果是更早的消息，显示月日和时间
    return `${date.getMonth() + 1}月${date.getDate()}日 ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
  } catch (error) {
    console.error('格式化时间失败:', error);
    return getCurrentTime();
  }
};

// 切换工具消息或思考过程的展开/收起状态
const toggleExpand = (message: ChatMessage) => {
  // 首先尝试在历史消息中查找并更新
  const index = messages.value.findIndex(m => 
    m.content === message.content && 
    m.time === message.time && 
    m.messageType === message.messageType
  );
  
  if (index !== -1) {
    // 使用响应式方式更新消息
    if (message.isThinkingProcess) {
      messages.value[index] = {
        ...messages.value[index],
        isThinkingExpanded: !messages.value[index].isThinkingExpanded
      };
    } else {
      messages.value[index] = {
        ...messages.value[index],
        isExpanded: !messages.value[index].isExpanded
      };
    }
    return;
  }

  // 如果在历史消息中找不到，检查当前活动流中的消息
  const stream = sessionId.value ? activeStreams.value[sessionId.value] : null;
  if (stream?.messages && stream.messages.length > 0) {
    const streamMsgIndex = stream.messages.findIndex(
      m => m.content === message.content && 
           m.time === message.time && 
           m.type === message.messageType
    );
    
    if (streamMsgIndex !== -1) {
      // 直接修改 activeStreams 中的消息对象
      if (message.isThinkingProcess) {
        stream.messages[streamMsgIndex].isThinkingExpanded = !stream.messages[streamMsgIndex].isThinkingExpanded;
      } else {
        stream.messages[streamMsgIndex].isExpanded = !stream.messages[streamMsgIndex].isExpanded;
      }
    }
  }
};

// ⭐大脑模式消息处理
const handleBrainModeMessage = async (message: string) => {
  // 添加用户消息
  messages.value.push({
    content: message,
    isUser: true,
    time: getCurrentTime(),
    messageType: 'human'
  });

  isLoading.value = true;
  let brainSessionId: string | null = null;

  // onStart 回调
  const handleStart = (newSessionId: string) => {
    brainSessionId = newSessionId;
    // 保存sessionId到全局状态和localStorage以保持上下文连续性
    saveSessionId(newSessionId);
    console.log(`Brain mode session started: ${brainSessionId}`);
    
    // 🔧 修复：不在这里停止loading，保持转圈直到流完成
    // isLoading.value = false;
    
    // 不再创建占位符，由watch在检测到第一个流式内容时创建
  };

  try {
    await sendOrchestratorStreamMessage(
      message,
      projectStore.currentProjectId!,
      handleStart,
      undefined,  // signal参数
      sessionId.value || undefined  // 传递session_id以保持上下文
    );

    // sendOrchestratorStreamMessage 现在使用全局状态管理
    // 需要监听 activeOrchestratorStreams 的变化来实时更新界面
  } catch (error) {
    console.error('Brain mode error:', error);
    Message.error('消息发送失败');
    isLoading.value = false;
  }
};

// 添加或更新会话到列表
const updateSessionInList = (id: string, firstMessage?: string, updateTime: boolean = true) => {
  if (!id) {
    console.warn('updateSessionInList: session_id is empty, skipping');
    return;
  }

  const existingIndex = chatSessions.value.findIndex(s => s.id === id);
  const title = firstMessage ? (firstMessage.length > 20 ? `${firstMessage.substring(0, 20)}...` : firstMessage) : '新对话';

  if (existingIndex >= 0) {
    // 更新现有会话
    if (updateTime) {
      chatSessions.value[existingIndex].lastTime = new Date();
    }
    if (firstMessage && !chatSessions.value[existingIndex].title) {
      chatSessions.value[existingIndex].title = title;
    }
    if (chatSessions.value[existingIndex].messageCount !== undefined && updateTime) {
      chatSessions.value[existingIndex].messageCount += 1;
    }
    
    // 🆕 更新时间后，重新按时间倒序排序会话列表
    if (updateTime) {
      chatSessions.value.sort((a, b) => b.lastTime.getTime() - a.lastTime.getTime());
    }
    console.log(`updateSessionInList: Updated existing session ${id}`);
  } else {
    // 添加新会话前，再次检查是否已存在（防止并发问题）
    const doubleCheckIndex = chatSessions.value.findIndex(s => s.id === id);
    if (doubleCheckIndex >= 0) {
      console.warn(`updateSessionInList: Session ${id} already exists, skipping duplicate addition`);
      return;
    }
    
    // 添加新会话
    chatSessions.value.unshift({
      id,
      title,
      lastTime: new Date(),
      messageCount: messages.value.length || 1
    });
    console.log(`updateSessionInList: Added new session ${id}`);
  }

  // 保存到本地存储
  saveSessionsToStorage();
};

// 切换到指定会话
const switchSession = async (id: string) => {
  if (id === sessionId.value) return;

  // 终止正在进行的流式请求
  // abortController.abort(); // 🔴 不再需要终止请求

  sessionId.value = id;
  saveSessionId(id);
  messages.value = [];

  // 加载选定会话的历史记录
  if (!projectStore.currentProjectId) {
    Message.error('没有选择项目，无法加载会话历史');
    return;
  }

  try {
    isLoading.value = true;
    const response = await getChatHistory(id, projectStore.currentProjectId);

    if (response.status === 'success') {
      const tempMessages: ChatMessage[] = [];
      response.data.history.forEach(historyItem => {
        // 🆕 跳过系统消息，不在消息列表中显示
        if (historyItem.type === 'system') {
          return;
        }

        const message: ChatMessage = {
          content: historyItem.content,
          isUser: historyItem.type === 'human',
          time: formatHistoryTime(historyItem.timestamp),
          messageType: historyItem.type
        };

        // 如果是工具消息，设置默认折叠状态
        if (historyItem.type === 'tool') {
          message.isExpanded = false;
        }

        // 🎨 如果是思考过程消息，设置折叠状态
        if (historyItem.is_thinking_process) {
          message.isThinkingProcess = true;
          message.isThinkingExpanded = false;
        }

        // 如果消息包含图片，添加图片数据
        if (historyItem.image) {
          message.imageDataUrl = historyItem.image;
        }

        tempMessages.push(message);
      });

      // 🎨 合并连续的思考过程消息
      messages.value = mergeThinkingProcessMessages(tempMessages);

      // 更新会话信息（不更新时间，因为这是加载历史记录）
      updateSessionInList(id, undefined, false);
    } else {
      Message.error('加载会话历史失败');
    }
  } catch (error) {
    console.error('加载会话历史失败:', error);
    Message.error('加载会话历史失败');
  } finally {
    isLoading.value = false;
  }
};

// 创建新对话
const createNewChat = () => {
  // 终止正在进行的流式请求
  // abortController.abort(); // 🔴 不再需要终止请求

  // 清除当前会话ID和消息
  sessionId.value = '';
  localStorage.removeItem('langgraph_session_id');
  messages.value = [];
};

// 删除指定会话
const deleteSession = async (id: string) => {
  Modal.confirm({
    title: '确认删除',
    content: '确定要删除此对话吗？此操作不可恢复。',
    okText: '确认删除',
    cancelText: '取消',
    okButtonProps: {
      status: 'danger',
    },
    async onOk() {
      try {
        if (!projectStore.currentProjectId) {
          Message.error('没有选择项目，无法删除会话');
          return;
        }

        isLoading.value = true;
        const response = await deleteChatHistory(id, projectStore.currentProjectId);

        if (response.status === 'success') {
          // 从列表中移除
          chatSessions.value = chatSessions.value.filter(s => s.id !== id);
          saveSessionsToStorage();

          // 如果删除的是当前会话，清除当前状态
          if (id === sessionId.value) {
            sessionId.value = '';
            localStorage.removeItem('langgraph_session_id');
            messages.value = [];
          }

          // 重新加载会话列表
          await loadSessionsFromServer();

          Message.success('对话已删除');
        } else {
          Message.error('删除对话失败');
        }
      } catch (error) {
        console.error('删除对话失败:', error);
        Message.error('删除对话失败，请稍后重试');
      } finally {
        isLoading.value = false;
      }
    },
  });
};

// 批量删除会话
const batchDeleteSessions = async (sessionIds: string[]) => {
  try {
    if (!projectStore.currentProjectId) {
      Message.error('没有选择项目，无法删除会话');
      return;
    }

    isLoading.value = true;
    const response = await batchDeleteChatHistory(sessionIds, projectStore.currentProjectId);

    if (response.status === 'success') {
      const { processed_sessions, failed_sessions } = response.data;
      
      // 从列表中移除已删除的会话
      chatSessions.value = chatSessions.value.filter(s => !sessionIds.includes(s.id));
      saveSessionsToStorage();

      // 如果删除的包含当前会话，清除当前状态
      if (sessionIds.includes(sessionId.value)) {
        sessionId.value = '';
        localStorage.removeItem('langgraph_session_id');
        messages.value = [];
      }

      // 重新加载会话列表
      await loadSessionsFromServer();

      // 显示结果消息
      if (failed_sessions.length === 0) {
        Message.success(`成功删除 ${processed_sessions} 个对话`);
      } else {
        Message.warning(`删除完成：成功 ${processed_sessions - failed_sessions.length} 个，失败 ${failed_sessions.length} 个`);
      }
    } else {
      Message.error('批量删除对话失败');
    }
  } catch (error) {
    console.error('批量删除对话失败:', error);
    Message.error('批量删除对话失败，请稍后重试');
  } finally {
    isLoading.value = false;
  }
};

// 清除聊天历史
const clearChat = async () => {
  if (messages.value.length === 0) return;

  // 显示确认对话框
  Modal.confirm({
    title: '确认删除',
    content: '确定要删除此对话的所有历史记录吗？此操作不可恢复。',
    okText: '确认删除',
    cancelText: '取消',
    okButtonProps: {
      status: 'danger',
    },
    async onOk() {
      try {
        // 如果有会话ID，调用API删除服务器端历史记录
        if (sessionId.value && projectStore.currentProjectId) {
          isLoading.value = true;
          const response = await deleteChatHistory(sessionId.value, projectStore.currentProjectId);

          if (response.status === 'success') {
            // 从会话列表中移除
            chatSessions.value = chatSessions.value.filter(s => s.id !== sessionId.value);
            saveSessionsToStorage();

            Message.success('对话历史已从服务器删除');
          } else {
            // 即使服务器删除失败，我们仍然会清除本地状态
            Message.warning('服务器删除可能未完成，但本地对话已清除');
          }
        }

        // 无论服务器操作结果如何，都清除本地状态
        messages.value = [];
        localStorage.removeItem('langgraph_session_id');
        sessionId.value = '';
      } catch (error) {
        console.error('删除聊天历史失败:', error);
        Message.error('删除聊天历史失败，请稍后重试');
      } finally {
        isLoading.value = false;
      }
    },
  });
};

// 发送消息
const handleSendMessage = async (data: { message: string; image?: string; imageDataUrl?: string }) => {
  const { message, image, imageDataUrl } = data;
  
  if (!message.trim() && !image) {
    Message.warning('消息内容不能为空！');
    return;
  }

  if (!projectStore.currentProjectId) {
    Message.error('请先选择一个项目');
    return;
  }

  // ⭐大脑模式使用orchestrator流式接口
  if (isBrainMode.value) {
    await handleBrainModeMessage(message);
    return;
  }

  // 添加用户消息（保存图片数据以便显示）
  messages.value.push({
    content: message,
    isUser: true,
    time: getCurrentTime(),
    messageType: 'human',
    imageBase64: image, // 保存图片Base64数据（用于发送到后端）
    imageDataUrl: imageDataUrl // 保存完整Data URL（用于前端显示）
  });

  isLoading.value = true;

  const requestData: ChatRequest = {
    message: message,
    session_id: sessionId.value || undefined,
    project_id: String(projectStore.currentProjectId), // 转换为string类型
  };
  
  // 如果有图片，添加到请求中
  if (image) {
    (requestData as any).image = image; // 临时使用any，稍后更新ChatRequest类型
  }

  // 添加提示词参数
  if (selectedPromptId.value) {
    requestData.prompt_id = selectedPromptId.value;
  }

  // 添加知识库参数
  if (useKnowledgeBase.value && selectedKnowledgeBaseId.value) {
    requestData.knowledge_base_id = selectedKnowledgeBaseId.value;
    requestData.use_knowledge_base = true;
    requestData.similarity_threshold = similarityThreshold.value;
    requestData.top_k = topK.value;
  } else if (useKnowledgeBase.value && !selectedKnowledgeBaseId.value) {
    // 如果开启了知识库但没有选择知识库，提示用户
    Message.warning('请先选择一个知识库');
    isLoading.value = false;
    return;
  }

  if (isStreamMode.value) {
    // 流式模式
    await handleStreamMessage(requestData);
  } else {
    // 非流式模式
    await handleNormalMessage(requestData, message);
  }
};

// 计算用于显示的最终消息列表
const displayedMessages = computed(() => {
  const combined = [...messages.value];
  // 从共享状态中获取当前会话的流
  const stream = sessionId.value ? activeStreams.value[sessionId.value] : null;

  // 如果当前会话有正在进行的流，则添加流式消息
  if (stream && !stream.isComplete) {
    // 首先添加工具消息(如果有)
    if (stream.messages && stream.messages.length > 0) {
      stream.messages.forEach(msg => {
        combined.push({
          content: msg.content,
          isUser: false,
          time: msg.time,
          messageType: msg.type,
          isExpanded: msg.isExpanded
        });
      });
    }
    
    // 然后处理AI消息
    if (stream.error) {
      // 如果有错误，显示错误消息
      combined.push({
        content: stream.error,
        isUser: false,
        time: getCurrentTime(),
        messageType: 'ai',
        isStreaming: false,
      });
    }
    else if (!stream.content || stream.content.trim() === '') {
      // 如果流式内容为空或只有空白字符，显示加载中状态
      combined.push({
        content: '',
        isUser: false,
        time: getCurrentTime(),
        messageType: 'ai',
        isLoading: true,
      });
    }
    else {
      // 有实际内容时，显示流式内容
      combined.push({
        content: stream.content,
        isUser: false,
        time: getCurrentTime(),
        messageType: 'ai',
        isStreaming: true,
      });
    }
  }
  return combined;
});

// 处理流式消息
const handleStreamMessage = async (requestData: ChatRequest) => {
  abortController = new AbortController();
  const isNewSession = !sessionId.value;

  isLoading.value = true;

  // onStart 回调，在收到 session_id 后立即处理
  const handleStart = async (newSessionId: string) => {
    if (isNewSession) {
      sessionId.value = newSessionId;
      saveSessionId(newSessionId);
      console.log(`handleStart: New session created with id ${newSessionId}`);
      // 🔧 修复：不在这里刷新会话列表，避免与后续的 updateSessionInList 冲突
      // 会话信息会在流完成后通过 loadChatHistory -> updateSessionInList 来更新
    }
  };

  await sendChatMessageStream(
    requestData,
    handleStart,
    abortController.signal
  );

  // sendChatMessageStream 现在是异步的，但我们不在这里等待它完成
  // 使用 watch 监视 isComplete 状态
};

// 处理非流式消息
const handleNormalMessage = async (requestData: ChatRequest, originalMessage: string) => {
  // 添加loading占位消息
  const loadingMessageIndex = messages.value.length;
  messages.value.push({
    content: '',
    isUser: false,
    time: getCurrentTime(),
    messageType: 'ai',
    isLoading: true
  });

  try {
    const response = await sendChatMessage(requestData);

    // 移除loading消息
    messages.value.splice(loadingMessageIndex, 1);

    if (response.status === 'success') {
      // 保存会话ID
      if (response.data.session_id) {
        saveSessionId(response.data.session_id);
        // 🔧 修复：统一使用 updateSessionInList 更新会话信息，避免重复
        // 获取用户的第一条消息作为标题
        const firstUserMessage = originalMessage;
        updateSessionInList(response.data.session_id, firstUserMessage, true);
      }

      // 处理conversation_flow中的新消息
      if (response.data.conversation_flow && response.data.conversation_flow.length > 0) {
        handleConversationFlow(response.data.conversation_flow, originalMessage);
      } else {
        // 如果没有conversation_flow，使用原来的方式添加AI回复
        messages.value.push({
          content: response.data.llm_response,
          isUser: false,
          time: getCurrentTime(),
          messageType: 'ai'
        });
      }
    } else {
      const errorMessages = response.errors ? Object.values(response.errors).flat().join('; ') : '';
      const errorMessage = `${response.message}${errorMessages ? ` (${errorMessages})` : ''}` || '发送消息失败';
      Message.error(errorMessage);
      messages.value.push({
        content: `错误: ${response.message || '发送失败'}`,
        isUser: false,
        time: getCurrentTime(),
        messageType: 'ai'
      });
    }
  } catch (error: any) {
    // 移除loading消息
    messages.value.splice(loadingMessageIndex, 1);

    console.error('Error sending chat message:', error);
    const errorDetail = error.response?.data?.message || error.message || '发送消息失败';
    Message.error(errorDetail);
    messages.value.push({
      content: `错误: ${errorDetail}`,
      isUser: false,
      time: getCurrentTime(),
      messageType: 'ai'
    });
  } finally {
    isLoading.value = false;
  }
};

// 处理conversation_flow
const handleConversationFlow = (conversationFlow: any[], originalMessage: string, skipAiIndex?: number) => {
  // 找到当前用户消息在conversation_flow中的位置
  let userMessageIndex = -1;

  // 从后往前找，找到最后一个匹配的用户消息
  for (let i = conversationFlow.length - 1; i >= 0; i--) {
    if (conversationFlow[i].type === 'human' &&
        conversationFlow[i].content === originalMessage) {
      userMessageIndex = i;
      break;
    }
  }

  // 如果找到了用户消息，添加该消息之后的所有新消息
  if (userMessageIndex >= 0) {
    const newMessages = conversationFlow.slice(userMessageIndex + 1);

    // 添加新消息到界面
    newMessages.forEach((flowItem, index) => {
      // 如果是流式模式，跳过已经在流式处理中添加的消息
      if (skipAiIndex !== undefined) {
        // 跳过最后一个AI消息（已经在流式处理中添加了）
        if (flowItem.type === 'ai' && index === newMessages.length - 1) {
          return;
        }
        // 跳过工具消息（已经在流式处理中添加了）
        if (flowItem.type === 'tool') {
          return;
        }
      }

      const message: ChatMessage = {
        content: flowItem.content,
        isUser: flowItem.type === 'human',
        time: getCurrentTime(),
        messageType: flowItem.type
      };

      // 如果是工具消息，设置默认折叠状态
      if (flowItem.type === 'tool') {
        message.isExpanded = false;
      }

      messages.value.push(message);
    });
  }
};

// 监听项目变化，重新加载数据
watch(() => projectStore.currentProjectId, async (newProjectId, oldProjectId) => {
  if (newProjectId && newProjectId !== oldProjectId) {
    // 项目切换时清空当前状态
    messages.value = [];
    chatSessions.value = [];
    sessionId.value = '';
    localStorage.removeItem('langgraph_session_id');

    // 重新加载会话列表
    await loadSessionsFromServer();
  }
}, { immediate: false });

// 获取当前激活的LLM配置
const loadCurrentLlmConfig = async () => {
  try {
    const response = await listLlmConfigs();
    if (response.status === 'success') {
      // 找到激活的配置
      const activeConfig = response.data.find(config => config.is_active);
      if (activeConfig) {
        currentLlmConfig.value = activeConfig;
      } else {
        Message.warning('未找到激活的LLM配置');
      }
    }
  } catch (error) {
    console.error('获取LLM配置失败:', error);
    Message.error('获取LLM配置失败');
  }
};

// 显示系统提示词弹窗
const showSystemPromptModal = async () => {
  await loadCurrentLlmConfig();
  isSystemPromptModalVisible.value = true;
};

// 关闭系统提示词弹窗
const closeSystemPromptModal = async () => {
  isSystemPromptModalVisible.value = false;
  
  // 检查关闭弹窗后是否还没有提示词
  await checkPromptStatusAfterClose();
};

// 关闭弹窗后检查提示词状态
const checkPromptStatusAfterClose = async () => {
  try {
    const response = await getUserPrompts({
      is_active: true,
      page_size: 1
    });

    if (response.status === 'success') {
      const prompts = Array.isArray(response.data) ? response.data : response.data.results || [];
      hasPrompts.value = prompts.length > 0;
      
      // 如果还是没有提示词，提示用户
      if (!hasPrompts.value) {
        Message.warning('请添加或初始化提示词后才能开始对话');
      }
    }
  } catch (error) {
    console.error('❌ 关闭弹窗后检查提示词状态失败:', error);
  }
};

// 更新系统提示词
const handleUpdateSystemPrompt = async (configId: number, systemPrompt: string) => {
  isSystemPromptLoading.value = true;
  try {
    const response = await partialUpdateLlmConfig(configId, {
      system_prompt: systemPrompt
    });

    if (response.status === 'success') {
      Message.success('系统提示词更新成功');
      // 更新本地配置
      if (currentLlmConfig.value) {
        currentLlmConfig.value.system_prompt = systemPrompt;
      }
      closeSystemPromptModal();
    } else {
      Message.error(response.message || '更新系统提示词失败');
    }
  } catch (error) {
    console.error('更新系统提示词失败:', error);
    Message.error('更新系统提示词失败');
  } finally {
    isSystemPromptLoading.value = false;
  }
};

// 检查提示词状态
const checkPromptStatus = async () => {
  try {
    const response = await getUserPrompts({
      is_active: true,
      page_size: 1 // 只需要知道是否有提示词，不需要全部数据
    });

    if (response.status === 'success') {
      const prompts = Array.isArray(response.data) ? response.data : response.data.results || [];
      hasPrompts.value = prompts.length > 0;
      console.log('📝 提示词状态检查完成:', { hasPrompts: hasPrompts.value, count: prompts.length });
      
      // 如果没有提示词，自动弹出管理弹窗
      if (!hasPrompts.value) {
        console.log('⚠️ 没有提示词，自动弹出管理弹窗');
        isSystemPromptModalVisible.value = true;
      }
    } else {
      hasPrompts.value = false;
      console.warn('⚠️ 获取提示词状态失败:', response.message);
    }
  } catch (error) {
    hasPrompts.value = false;
    console.error('❌ 检查提示词状态失败:', error);
  }
};

// 处理提示词数据更新
const handlePromptsUpdated = async () => {
  console.log('🔄 收到提示词更新事件，开始刷新ChatHeader数据...');

  // 重新检查提示词状态（不会自动弹窗，因为用户刚刚在管理页面操作过）
  try {
    const response = await getUserPrompts({
      is_active: true,
      page_size: 1
    });

    if (response.status === 'success') {
      const prompts = Array.isArray(response.data) ? response.data : response.data.results || [];
      hasPrompts.value = prompts.length > 0;
      console.log('📝 提示词状态更新完成:', { hasPrompts: hasPrompts.value, count: prompts.length });
    }
  } catch (error) {
    console.error('❌ 更新提示词状态失败:', error);
  }

  // 先检查当前选中的提示词是否还存在
  if (selectedPromptId.value !== null) {
    try {
      const response = await getUserPrompts({
        is_active: true,
        page_size: 100
      });

      if (response.status === 'success') {
        const allPrompts = Array.isArray(response.data) ? response.data : response.data.results || [];
        const currentPromptExists = allPrompts.some(prompt => prompt.id === selectedPromptId.value);

        if (!currentPromptExists) {
          console.log('⚠️ 当前选中的提示词已被删除，重置为默认选择');
          selectedPromptId.value = null;
        }
      }
    } catch (error) {
      console.error('检查提示词存在性失败:', error);
    }
  }

  // 刷新ChatHeader中的提示词列表
  if (chatHeaderRef.value) {
    await chatHeaderRef.value.refreshPrompts();
    console.log('✅ ChatHeader提示词数据刷新完成');
  } else {
    console.warn('⚠️ chatHeaderRef为空，无法刷新提示词数据');
  }
};

// 监听知识库设置变化，自动保存到本地存储
// 监视当前会话的流是否完成
watch(
  () => (sessionId.value ? activeStreams.value[sessionId.value] : null),
  async (stream) => {
    if (stream && stream.isComplete) {
      console.log(`会话 ${sessionId.value} 的流已完成。`);
      
      // 🔧 修复：流完成后重新加载完整的对话历史，包括工具消息
      if (sessionId.value && projectStore.currentProjectId) {
        try {
          const response = await getChatHistory(sessionId.value, projectStore.currentProjectId);
          if (response.status === 'success') {
            // 清空当前消息列表
            messages.value = [];
            
            // 重新加载所有消息（包括工具消息）
            response.data.history.forEach(historyItem => {
              // 跳过系统消息
              if (historyItem.type === 'system') {
                return;
              }
              
              const message: ChatMessage = {
                content: historyItem.content,
                isUser: historyItem.type === 'human',
                time: formatHistoryTime(historyItem.timestamp),
                messageType: historyItem.type
              };
              
              // 如果是工具消息，设置默认折叠状态
              if (historyItem.type === 'tool') {
                message.isExpanded = false;
              }
              
              // 如果消息包含图片，添加图片数据
              if (historyItem.image) {
                message.imageDataUrl = historyItem.image;
              }
              
              messages.value.push(message);
            });
            
            // 更新会话信息（只在新会话时添加到列表）
            const existingSession = chatSessions.value.find(s => s.id === sessionId.value);
            if (!existingSession) {
              const firstHumanMessage = response.data.history.find(msg => msg.type === 'human')?.content;
              if (firstHumanMessage) {
                updateSessionInList(sessionId.value, firstHumanMessage, true);
              }
            }
          }
        } catch (error) {
          console.error('重新加载对话历史失败:', error);
        }
      }
      
      // 清理已完成的流状态，避免不必要的内存占用
      clearStreamState(sessionId.value!);

      // 如果是通过本页面发送的消息，则需要在这里设置 isLoading = false
      if (isLoading.value) {
        isLoading.value = false;
      }
    }
  },
  { deep: true }
);

// 监听会话ID变化,控制自动刷新
watch(() => sessionId.value, (newSessionId) => {
  if (newSessionId) {
    // 有会话时启动自动刷新
    startAutoRefresh();
  } else {
    // 无会话时停止自动刷新
    stopAutoRefresh();
  }
});

// 🔧 修复：监听项目ID变化，当项目加载完成后自动加载会话数据
watch(() => projectStore.currentProjectId, async (newProjectId, oldProjectId) => {
  console.log(`📊 项目ID变化: ${oldProjectId} -> ${newProjectId}`);
  
  if (newProjectId && newProjectId !== oldProjectId) {
    // 项目切换或首次加载完成
    console.log('🔄 项目已切换，重新加载会话数据...');
    
    // 只有在onMounted完成后才通过watch加载（避免重复）
    // 或者如果onMounted时没有项目，现在项目加载完成了，也需要加载
    if (isMountedLoadComplete || !oldProjectId) {
      await loadSessionsFromServer();
      await loadChatHistory();
      
      // 启动自动刷新(如果有会话)
      if (sessionId.value) {
        startAutoRefresh();
      }
    }
  } else if (!newProjectId && oldProjectId) {
    // 项目被清除
    console.log('⚠️ 项目已清除');
    messages.value = [];
    chatSessions.value = [];
    sessionId.value = '';
    stopAutoRefresh();
  }
});

// 监听 Brain 模式的流式输出,实时更新消息
watch(
  () => {
    const streams = activeOrchestratorStreams.value;
    return Object.keys(streams).length > 0 ? streams : null;
  },
  async (streams) => {
    if (!streams) return;
    
    const sessionIds = Object.keys(streams);
    if (sessionIds.length === 0) return;
    
    const latestSessionId = sessionIds[sessionIds.length - 1];
    const stream = streams[latestSessionId];
    
    if (!stream) return;
    
    // 1. 追加 stream.messages（Brain决策、工具消息等）
    if (stream.messages && stream.messages.length > 0) {
      if (!stream.processedMessageCount) {
        stream.processedMessageCount = 0;
      }
      
      const newMessages = stream.messages.slice(stream.processedMessageCount);
      if (newMessages.length > 0) {
        // 🎨 直接追加消息，不立即合并（保持对象引用稳定）
        newMessages.forEach(msg => {
          messages.value.push({
            content: msg.content,
            isUser: false,
            time: msg.time,
            messageType: msg.type,
            toolName: msg.toolName,
            isExpanded: msg.isExpanded,
            isThinkingProcess: msg.isThinkingProcess,
            isThinkingExpanded: msg.isThinkingExpanded
          });
        });
        
        stream.processedMessageCount = stream.messages.length;
        console.log('[Brain Watch] Appended', newMessages.length, 'structured messages');
      }
    }
    
    // 2. 管理流式内容占位符
    // 查找当前的流式内容占位符（标记为 isStreaming=true）
    let streamingMessageIndex = -1;
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].isStreaming === true) {
        streamingMessageIndex = i;
        break;
      }
    }
    
    if (stream.content && stream.content.trim()) {
      // 有流式内容
      if (streamingMessageIndex === -1) {
        // 没有占位符，创建一个新的
        messages.value.push({
          content: stream.content,
          isUser: false,
          time: getCurrentTime(),
          messageType: 'ai',
          isStreaming: true // 使用isStreaming标记来识别流式内容占位符
        });
        console.log('[Brain Watch] Created streaming placeholder');
      } else {
        // 更新现有占位符
        messages.value[streamingMessageIndex].content = stream.content;
      }
    }
    
    // 3. 流完成时的处理
    if (stream.isComplete) {
      console.log('[Brain Watch] Stream complete, reloading history');
      
      // 关闭流式状态
      if (streamingMessageIndex !== -1) {
        messages.value[streamingMessageIndex].isStreaming = false;
      }
      
      // 重新加载完整历史，确保包含所有后端保存的消息
      if (latestSessionId && projectStore.currentProjectId) {
        try {
          // 🎨 保存当前的展开状态（根据内容匹配）
          const expandedStates = new Map<string, boolean>();
          messages.value.forEach(msg => {
            if (msg.isThinkingProcess && msg.isThinkingExpanded) {
              // 使用内容的前100个字符作为key
              const key = msg.content.substring(0, 100);
              expandedStates.set(key, true);
            }
          });
          
          const response = await getChatHistory(latestSessionId, projectStore.currentProjectId);
          if (response.status === 'success') {
            // 清空当前消息并重新加载
            messages.value = [];
            
            const tempMessages: ChatMessage[] = [];
            response.data.history.forEach(historyItem => {
              if (historyItem.type === 'system') return;
              
              const message: ChatMessage = {
                content: historyItem.content,
                isUser: historyItem.type === 'human',
                time: formatHistoryTime(historyItem.timestamp),
                messageType: historyItem.type
              };
              
              if (historyItem.type === 'tool') {
                message.isExpanded = false;
              }
              
              // 🎨 如果是思考过程消息，设置折叠状态
              if (historyItem.is_thinking_process) {
                message.isThinkingProcess = true;
                message.isThinkingExpanded = false;
              }
              
              if (historyItem.image) {
                message.imageDataUrl = historyItem.image;
              }
              
              tempMessages.push(message);
            });
            
            // 🎨 合并连续的思考过程消息
            messages.value = mergeThinkingProcessMessages(tempMessages);
            
            // 🎨 恢复展开状态
            messages.value.forEach(msg => {
              if (msg.isThinkingProcess) {
                const key = msg.content.substring(0, 100);
                if (expandedStates.has(key)) {
                  msg.isThinkingExpanded = true;
                }
              }
            });
            
            // 更新会话列表
            const firstUserMessage = messages.value.find(m => m.isUser);
            if (firstUserMessage) {
              updateSessionInList(latestSessionId, firstUserMessage.content, true);
            }
            
            console.log('[Brain Watch] History reloaded:', messages.value.length, 'messages');
          }
        } catch (error) {
          console.error('[Brain Watch] Failed to reload history:', error);
        }
      }
      
      // 清理流状态
      clearOrchestratorStreamState(latestSessionId);
      isLoading.value = false;
    }
  },
  { deep: true }
);

watch([useKnowledgeBase, selectedKnowledgeBaseId, similarityThreshold, topK], () => {
  saveKnowledgeBaseSettings();
}, { deep: true });

// 监听Brain模式状态，保存到localStorage
watch(isBrainMode, (newValue) => {
  localStorage.setItem('langgraph_brain_mode', newValue.toString());
  console.log('💾 Brain mode state saved:', newValue);
});

onMounted(async () => {
  // ⭐加载保存的提示词ID
  loadSavedPromptId();
  
  // 加载知识库设置
  loadKnowledgeBaseSettings();
  
  // 🔧 修复：确保项目已选择
  // 如果没有当前项目，等待项目store加载完成
  if (!projectStore.currentProjectId) {
    console.log('⏳ 等待项目初始化...');
    // 尝试从projectStore加载项目列表
    if (projectStore.projectList.length === 0) {
      try {
        await projectStore.fetchProjects();
      } catch (error) {
        console.error('❌ 加载项目列表失败:', error);
      }
    }
    
    // 如果还是没有项目，提示用户
    // 注意：不直接return，因为watch会在项目加载后自动加载会话数据
    if (!projectStore.currentProjectId) {
      console.warn('⚠️ 没有选择项目，等待项目选择...');
      // 不显示提示，因为MainLayout会处理项目选择
    }
  }
  
  // 只有在有项目时才加载会话数据（避免watch中重复加载）
  if (projectStore.currentProjectId) {
    // 🔧 修复：先加载会话列表，再加载当前会话历史
    // 这样可以避免 loadChatHistory 中的 updateSessionInList 导致重复
    await loadSessionsFromServer();

    // 尝试加载当前会话的历史记录（只加载消息，不更新会话列表）
    await loadChatHistory();
    
    // 启动自动刷新(如果有会话)
    if (sessionId.value) {
      startAutoRefresh();
    }
  }

  // 加载当前LLM配置（不依赖项目）
  await loadCurrentLlmConfig();
  
  // 检查提示词状态（如果没有会自动弹出管理弹窗）
  await checkPromptStatus();
  
  // 标记onMounted完成
  isMountedLoadComplete = true;
});

// 监听 LLM 配置变化
watch(getRefreshTrigger(), async () => {
  console.log('🔄 检测到 LLM 配置变化,重新加载配置...');
  await loadCurrentLlmConfig();
}, { immediate: false });

onActivated(async () => {
  // 每次组件被激活时（从其他页面切回来）
  console.log('✅ Chat component activated.');

  // 1. 刷新左侧的会话列表
  await loadSessionsFromServer();

  // 2. 检查localStorage，看是否有指定的会话需要加载
  const storedSessionId = getSessionIdFromStorage();

  // 3. 如果存储的ID和当前组件活跃的ID不一致，则强制切换到新会话
  if (storedSessionId && storedSessionId !== sessionId.value) {
    console.log(`Detected session change from localStorage: ${storedSessionId}. Switching...`);
    await switchSession(storedSessionId);
  }
  // 4. 如果是同一个会话，检查是否有正在进行的流需要恢复显示
  else if (storedSessionId && activeStreams.value[storedSessionId]) {
    console.log(`Resuming stream display for current session ${storedSessionId}.`);
    // 如果流在后台已经完成，但UI没有及时更新，这里重新加载历史记录
    if (activeStreams.value[storedSessionId].isComplete) {
      await loadChatHistory();
      clearStreamState(storedSessionId);
    }
  }
});

onUnmounted(() => {
  // 组件卸载时，终止任何正在进行的流式请求
  abortController.abort();
  // 停止自动刷新
  stopAutoRefresh();
});
</script>

<script lang="ts">
export default {
  name: 'LangGraphChat'
}
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100%;
  background-color: #f7f8fa;
  border-radius: 8px;
  overflow: hidden;
}

.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  background-color: #f7f8fa;
  overflow: hidden;
}
</style>