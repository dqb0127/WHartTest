<template>
  <div class="chat-header-container">
    <div class="chat-header">
      <h1 class="chat-title">LLM对话</h1>
      <div class="chat-actions">
        <!-- ⭐大脑模式下隐藏流式开关 -->
        <div v-if="!brainMode" class="stream-toggle">
          <span class="toggle-label">流式输出</span>
          <a-switch
            :model-value="isStreamMode"
            @update:model-value="(value: string | number | boolean) => $emit('update:is-stream-mode', Boolean(value))"
            size="small"
          />
        </div>

        <!-- ⭐大脑模式下隐藏知识库开关 -->
        <div v-if="!brainMode" class="kb-toggle">
          <span class="kb-icon">📚</span>
          <span class="toggle-label">知识库</span>
          <a-switch
            :model-value="useKnowledgeBase"
            @update:model-value="handleKnowledgeBaseToggle"
            size="small"
          />
        </div>

        <!-- ⭐大脑模式下隐藏提示词选择器 -->
        <div v-if="!brainMode" class="prompt-selector">
          <span class="prompt-label">提示词：</span>
          <a-select
            v-model="selectedPromptId"
            :placeholder="defaultPrompt ? defaultPrompt.name : '选择提示词'"
            style="width: 200px"
            allow-clear
            @change="handlePromptChange"
            :loading="promptsLoading"
            :fallback-option="false"
          >
            <a-option
              v-for="prompt in userPrompts"
              :key="prompt.id"
              :value="prompt.id"
              :label="prompt.name"
            >
              <span>{{ prompt.name }}</span>
              <a-tag v-if="prompt.is_default" color="blue" size="small" style="margin-left: 8px;">默认</a-tag>
            </a-option>
          </a-select>
        </div>

        <!-- ⭐大脑模式下隐藏管理提示词按钮 -->
        <a-button v-if="!brainMode" type="text" @click="$emit('show-system-prompt')">
          <template #icon>
            <i class="icon-settings"></i>
          </template>
          管理提示词
        </a-button>
        
        <!-- LLM配置按钮 -->
        <a-button v-if="!brainMode" type="text" @click="goToLlmConfigs">
          <template #icon>
            <icon-settings />
          </template>
          LLM配置
        </a-button>
        
        <a-tag v-if="sessionId" color="green">会话ID: {{ sessionIdShort }}</a-tag>
        <a-button v-if="hasMessages" type="text" status="danger" @click="$emit('clear-chat')">
          <template #icon>
            <icon-delete style="color: #f53f3f;" />
          </template>
          清除对话
        </a-button>
      </div>
    </div>

    <!-- ⭐大脑模式下隐藏知识库设置面板 -->
    <div v-if="useKnowledgeBase && !brainMode" class="kb-settings-panel">
      <KnowledgeBaseSelector
        :project-id="projectId"
        :use-knowledge-base="useKnowledgeBase"
        :selected-knowledge-base-id="selectedKnowledgeBaseId"
        :similarity-threshold="similarityThreshold"
        :top-k="topK"
        @update:use-knowledge-base="$emit('update:use-knowledge-base', $event)"
        @update:selected-knowledge-base-id="$emit('update:selected-knowledge-base-id', $event)"
        @update:similarity-threshold="$emit('update:similarity-threshold', $event)"
        @update:top-k="$emit('update:top-k', $event)"
      />
    </div>


  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue';
import { useRouter } from 'vue-router';
import { Button as AButton, Tag as ATag, Switch as ASwitch, Select as ASelect, Option as AOption } from '@arco-design/web-vue';
import { IconDelete, IconSettings } from '@arco-design/web-vue/es/icon';
import KnowledgeBaseSelector from './KnowledgeBaseSelector.vue';
import { getUserPrompts, getDefaultPrompt } from '@/features/prompts/services/promptService';
import type { UserPrompt } from '@/features/prompts/types/prompt';

const router = useRouter();

interface Props {
  sessionId: string;
  isStreamMode: boolean;
  hasMessages: boolean;
  projectId: number | null;
  useKnowledgeBase: boolean;
  selectedKnowledgeBaseId: string | null;
  similarityThreshold: number;
  topK: number;
  selectedPromptId: number | null;
  brainMode?: boolean; // ⭐大脑模式
}

const props = withDefaults(defineProps<Props>(), {
  brainMode: false
});

const emit = defineEmits<{
  (e: 'update:is-stream-mode', value: boolean): void;
  (e: 'clear-chat'): void;
  (e: 'show-system-prompt'): void;
  (e: 'update:use-knowledge-base', value: boolean): void;
  (e: 'update:selected-knowledge-base-id', value: string | null): void;
  (e: 'update:similarity-threshold', value: number): void;
  (e: 'update:top-k', value: number): void;
  (e: 'update:selected-prompt-id', value: number | null): void;
}>();

// 截断会话ID以便展示
const sessionIdShort = computed(() => {
  if (!props.sessionId) return '';
  return props.sessionId.length > 8 ? `${props.sessionId.substring(0, 8)}...` : props.sessionId;
});

// 跳转到LLM配置页面
const goToLlmConfigs = () => {
  router.push('/llm-configs');
};

// 提示词相关数据
const selectedPromptId = ref<number | null>(props.selectedPromptId);
const userPrompts = ref<UserPrompt[]>([]);
const defaultPrompt = ref<UserPrompt | null>(null);
const promptsLoading = ref(false);

// 加载用户提示词
const loadUserPrompts = async () => {
  console.log('🔄 ChatHeader开始加载提示词数据...');
  promptsLoading.value = true;
  try {
    const [promptsResponse, defaultResponse] = await Promise.all([
      getUserPrompts({
        is_active: true,
        ordering: 'name', // 先按名称排序
        page_size: 100
      }),
      getDefaultPrompt()
    ]);

    if (promptsResponse.status === 'success') {
      let allPrompts: UserPrompt[] = [];
      if (Array.isArray(promptsResponse.data)) {
        allPrompts = promptsResponse.data;
      } else if (promptsResponse.data.results) {
        allPrompts = promptsResponse.data.results;
      }
      
      // 🆕 过滤：只显示 general 和 brain_orchestrator 类型的提示词
      const allowedTypes = ['general', 'brain_orchestrator'];
      allPrompts = allPrompts.filter(prompt => 
        allowedTypes.includes(prompt.prompt_type || 'general')
      );
      
      // 🆕 在前端手动排序：默认提示词在前，然后按类型和名称排序
      userPrompts.value = allPrompts.sort((a, b) => {
        // 第一级：按 is_default 排序，默认的在前
        if (a.is_default && !b.is_default) return -1;
        if (!a.is_default && b.is_default) return 1;
        
        // 第二级：按提示词类型排序，通用对话类型在前，智能规划在后
        const getTypeSort = (type: string) => {
          if (type === 'general') return 1; // 通用对话类型
          if (type === 'brain_orchestrator') return 2; // 智能规划类型
          return 3; // 其他类型(理论上不会出现)
        };
        
        const aTypeSort = getTypeSort(a.prompt_type || 'general');
        const bTypeSort = getTypeSort(b.prompt_type || 'general');
        if (aTypeSort !== bTypeSort) return aTypeSort - bTypeSort;
        
        // 第三级：按名称排序
        return a.name.localeCompare(b.name);
      });
      console.log('📋 ChatHeader加载到的提示词列表:', userPrompts.value.map(p => ({ id: p.id, name: p.name, isDefault: p.is_default, type: p.prompt_type })));

      // 🆕 检查当前选中的提示词是否在允许的列表中
      if (selectedPromptId.value !== null) {
        const selectedExists = userPrompts.value.some(p => p.id === selectedPromptId.value);
        if (!selectedExists) {
          console.log(`⚠️ 当前选中的提示词(ID:${selectedPromptId.value})不在允许列表中，重置选择`);
          selectedPromptId.value = null;
          emit('update:selected-prompt-id', null);
        }
      }
    }

    if (defaultResponse.status === 'success' && defaultResponse.data) {
      defaultPrompt.value = defaultResponse.data;
      console.log('🌟 ChatHeader加载到的默认提示词:', defaultPrompt.value.name);

      // 如果当前没有选择提示词且有默认提示词，则自动选中默认提示词
      if (selectedPromptId.value === null && !props.selectedPromptId) {
        selectedPromptId.value = defaultPrompt.value.id;
        emit('update:selected-prompt-id', defaultPrompt.value.id);
      }
    } else {
      console.log('❌ ChatHeader未找到默认提示词');
    }
  } catch (error) {
    console.error('加载用户提示词失败:', error);
    userPrompts.value = [];
    defaultPrompt.value = null;
  } finally {
    promptsLoading.value = false;
    console.log('✅ ChatHeader提示词数据加载完成');
  }
};

// 处理提示词变化
const handlePromptChange = (promptId: number | null) => {
  selectedPromptId.value = promptId;
  emit('update:selected-prompt-id', promptId);
};

// 处理知识库开关变化
const handleKnowledgeBaseToggle = (value: string | number | boolean) => {
  emit('update:use-knowledge-base', Boolean(value));
};

// 监听props变化
watch(
  () => props.selectedPromptId,
  (newValue) => {
    selectedPromptId.value = newValue;
  }
);

// 组件挂载时加载数据
onMounted(() => {
  loadUserPrompts();
});

// 暴露刷新方法给父组件
defineExpose({
  refreshPrompts: loadUserPrompts
});
</script>

<style scoped>
.chat-header-container {
  background-color: #ffffff;
  border-bottom: 1px solid #e5e6eb;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
  z-index: 1;
}

.chat-header {
  padding: 16px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.chat-title {
  font-size: 18px;
  font-weight: 600;
  color: #1d2129;
  margin: 0;
}

.chat-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.stream-toggle,
.kb-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  background-color: rgba(0, 0, 0, 0.04);
  border-radius: 16px;
  font-size: 12px;
}

.kb-icon {
  font-size: 14px;
}

.toggle-label {
  color: #4e5969;
  font-weight: 500;
}

.icon-settings::before {
  content: '⚙️';
  margin-right: 4px;
}

.kb-settings-panel {
  border-top: 1px solid #e5e6eb;
  background-color: #f7f8fa;
}

.prompt-selector {
  display: flex;
  align-items: center;
  gap: 8px;
}

.prompt-label {
  font-size: 13px;
  color: #4e5969;
  white-space: nowrap;
}


</style>
