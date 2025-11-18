<template>
  <div class="chat-messages" ref="messagesContainer">
    <div v-if="messages.length === 0" class="empty-chat">
      <div class="empty-icon">
        <icon-message />
      </div>
      <p>开始与 WHartTest 的对话吧</p>
    </div>

    <MessageItem
      v-for="(message, index) in messages"
      :key="index"
      :message="message"
      @toggle-expand="$emit('toggle-expand', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue';
import { IconMessage } from '@arco-design/web-vue/es/icon';
import MessageItem from './MessageItem.vue';

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

interface Props {
  messages: ChatMessage[];
  isLoading: boolean;
}

const props = defineProps<Props>();

defineEmits<{
  'toggle-expand': [message: ChatMessage];
}>();

const messagesContainer = ref<HTMLElement | null>(null);
const userIsScrolling = ref(false); // 用户是否正在查看历史消息
let scrollTimeout: number | null = null;

// 检测用户是否在底部附近
const isNearBottom = (): boolean => {
  if (!messagesContainer.value) return true;
  const { scrollTop, scrollHeight, clientHeight } = messagesContainer.value;
  // 如果距离底部小于100px，认为用户在底部
  return scrollHeight - scrollTop - clientHeight < 100;
};

// 滚动到最新消息
const scrollToBottom = async () => {
  await nextTick();
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
  }
};

// 处理滚动事件
const handleScroll = () => {
  // 检测用户是否在底部
  const nearBottom = isNearBottom();
  userIsScrolling.value = !nearBottom;
  
  // 清除之前的定时器
  if (scrollTimeout !== null) {
    clearTimeout(scrollTimeout);
  }
  
  // 如果用户滚动到底部附近，恢复自动滚动
  if (nearBottom) {
    scrollTimeout = window.setTimeout(() => {
      userIsScrolling.value = false;
    }, 150);
  }
};

// 监听消息数量变化，只在用户未主动滚动时自动滚动
watch(() => props.messages.length, () => {
  if (!userIsScrolling.value) {
    scrollToBottom();
  }
});

// 监听流式消息内容变化，只在用户未主动滚动时自动滚动
watch(() => {
  // 找到最后一条正在流式输出的消息
  const lastMessage = props.messages[props.messages.length - 1];
  if (lastMessage && lastMessage.isStreaming && lastMessage.messageType === 'ai') {
    return lastMessage.content;
  }
  return null;
}, (newContent) => {
  // 只有当内容确实发生变化且用户未主动滚动时才滚动
  if (newContent !== null && !userIsScrolling.value) {
    scrollToBottom();
  }
});

// 组件挂载时添加滚动监听
onMounted(() => {
  if (messagesContainer.value) {
    messagesContainer.value.addEventListener('scroll', handleScroll);
  }
});

// 组件卸载时移除滚动监听
onUnmounted(() => {
  if (messagesContainer.value) {
    messagesContainer.value.removeEventListener('scroll', handleScroll);
  }
  if (scrollTimeout !== null) {
    clearTimeout(scrollTimeout);
  }
});

// 暴露滚动方法给父组件
defineExpose({
  scrollToBottom
});
</script>

<style scoped>
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.empty-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #86909c;
}

.empty-icon {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background-color: #f2f3f5;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}

.empty-icon .arco-icon {
  font-size: 32px;
  color: #c9cdd4;
}
</style>
