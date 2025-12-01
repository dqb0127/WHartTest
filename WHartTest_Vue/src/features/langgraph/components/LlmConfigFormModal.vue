<template>
  <a-modal
    :visible="props.visible"
    :title="isEditing ? '编辑 LLM 配置' : '新增 LLM 配置'"
    @ok="handleSubmit"
    @cancel="handleCancel"
    :confirm-loading="formLoading"
    :mask-closable="false"
    width="700px"
  >
    <a-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      layout="vertical"
      @submit="handleSubmit"
    >
      <a-row :gutter="24">
        <!-- 第一行：配置名称 + 供应商 -->
        <a-col :span="12">
          <a-form-item field="config_name" label="配置名称" required>
            <a-input v-model="formData.config_name" placeholder="例如: GPT-4 生产环境" />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item field="provider" label="供应商" required>
            <a-select 
              v-model="formData.provider" 
              placeholder="请选择供应商"
              :loading="loadingProviders"
            >
              <a-option 
                v-for="option in providerOptions" 
                :key="option.value" 
                :value="option.value"
              >
                {{ option.label }}
              </a-option>
            </a-select>
          </a-form-item>
        </a-col>

        <!-- 第二行：模型名称 (全宽 + 刷新按钮内联) -->
        <a-col :span="24">
          <a-form-item field="name" label="模型名称" required>
            <div class="model-input-wrapper">
              <a-auto-complete
                v-model="formData.name"
                :data="modelOptions"
                :loading="loadingModels"
                placeholder="输入或选择模型名称 (如: gpt-4-turbo)"
                allow-clear
                @focus="handleModelInputFocus"
                class="model-input"
              />
              <a-tooltip content="从 API 刷新模型列表">
                <a-button
                  type="secondary"
                  :loading="loadingModels"
                  @click="fetchAvailableModels"
                >
                  <template #icon><icon-refresh /></template>
                </a-button>
              </a-tooltip>
            </div>
          </a-form-item>
        </a-col>

        <!-- 第三行：API URL + API Key -->
        <a-col :span="12">
          <a-form-item field="api_url" label="API URL" required>
            <a-input v-model="formData.api_url" placeholder="https://api.openai.com/v1" />
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item field="api_key" label="API Key" :required="!isEditing">
            <a-input-password
              v-model="formData.api_key"
              :placeholder="isEditing ? '留空不修改' : '请输入 API Key'"
            />
          </a-form-item>
        </a-col>

        <!-- 测试按钮：右对齐，紧凑 -->
        <a-col :span="24" class="test-button-row">
          <a-button 
            type="outline"
            status="success"
            size="small"
            :loading="testingModel"
            @click="testLlmModel"
          >
            <template #icon><icon-thunderbolt /></template>
            测试连接
          </a-button>
        </a-col>

        <!-- 第四行：系统提示词 (全宽) -->
        <a-col :span="24">
          <a-form-item field="system_prompt" label="系统提示词">
            <a-textarea
              v-model="formData.system_prompt"
              placeholder="设置模型的默认 System Prompt（可选）"
              :auto-size="{ minRows: 3, maxRows: 6 }"
              :max-length="2000"
              show-word-limit
            />
          </a-form-item>
        </a-col>

        <!-- 第五行：开关区域 (并排) -->
        <a-col :span="12">
          <a-form-item field="supports_vision" label="能力支持">
            <a-space>
              <a-switch v-model="formData.supports_vision" />
              <span class="switch-desc">支持图片输入 (Vision)</span>
            </a-space>
          </a-form-item>
        </a-col>
        <a-col :span="12">
          <a-form-item field="is_active" label="配置状态">
            <a-space>
              <a-switch v-model="formData.is_active" checked-color="#00b42a" />
              <span class="switch-desc">已激活</span>
            </a-space>
          </a-form-item>
        </a-col>
      </a-row>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, watch, computed, nextTick, onMounted } from 'vue';
import {
  Modal as AModal,
  Form as AForm,
  FormItem as AFormItem,
  Input as AInput,
  InputPassword as AInputPassword,
  Textarea as ATextarea,
  Switch as ASwitch,
  Select as ASelect,
  Option as AOption,
  AutoComplete as AAutoComplete,
  Button as AButton,
  Row as ARow,
  Col as ACol,
  Space as ASpace,
  Tooltip as ATooltip,
  Message,
  type FormInstance,
  type FieldRule,
} from '@arco-design/web-vue';
import { IconRefresh, IconThunderbolt } from '@arco-design/web-vue/es/icon';
import axios from 'axios';
import type { LlmConfig, CreateLlmConfigRequest, PartialUpdateLlmConfigRequest } from '@/features/langgraph/types/llmConfig';
import { getProviders, type ProviderOption } from '@/features/langgraph/services/llmConfigService';

interface Props {
  visible: boolean;
  configData?: LlmConfig | null; // 用于编辑时预填数据
  formLoading?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  visible: false,
  configData: null,
  formLoading: false,
});

const emit = defineEmits<{
  (e: 'submit', data: CreateLlmConfigRequest | PartialUpdateLlmConfigRequest, id?: number): void;
  (e: 'cancel'): void;
}>();

const formRef = ref<FormInstance | null>(null);
const providerOptions = ref<ProviderOption[]>([]);
const loadingProviders = ref(false);
const modelOptions = ref<string[]>([]);
const loadingModels = ref(false);
const testingModel = ref(false);
const defaultFormData: CreateLlmConfigRequest = {
  config_name: '',
  provider: '',
  name: '',
  api_url: '',
  api_key: '',
  system_prompt: '',
  supports_vision: false,
  is_active: false,
};
const formData = ref<CreateLlmConfigRequest>({ ...defaultFormData });

const isEditing = computed(() => !!props.configData?.id);

const formRules: Record<string, FieldRule[]> = {
  config_name: [{ required: true, message: '配置名称不能为空' }],
  provider: [{ required: true, message: '供应商不能为空' }],
  name: [{ required: true, message: '模型名称不能为空' }],
  api_url: [
    { required: true, message: 'API URL 不能为空' },
    { type: 'url', message: '请输入有效的 URL' },
  ],
  api_key: [
    // API Key 在创建时必填，编辑时可选
    {
      required: !isEditing.value,
      message: 'API Key 不能为空',
      validator: (value, cb) => {
        if (!isEditing.value && !value) {
          return cb('API Key 不能为空');
        }
        if (value && value.length < 10 && !isEditing.value) {
            // 仅在创建时或编辑时输入了新值才校验长度
            return cb('API key 必须至少 10 个字符长。');
        }
        if (isEditing.value && value && value.length > 0 && value.length < 10) {
             return cb('API key 必须至少 10 个字符长。');
        }
        return cb();
      }
    },
  ],
};


watch(
  () => props.visible,
  (newVal) => {
    if (newVal) {
      if (props.configData && props.configData.id) {
        // 编辑模式：填充表单，但不包括 API Key（除非用户想修改）
        formData.value = {
          config_name: props.configData.config_name,
          provider: props.configData.provider,
          name: props.configData.name,
          api_url: props.configData.api_url,
          api_key: '', // 编辑时不显示旧 Key，留空表示不修改
          system_prompt: props.configData.system_prompt || '', // 填充系统提示词
          supports_vision: props.configData.supports_vision || false, // 填充多模态支持
          is_active: props.configData.is_active,
        };
      } else {
        // 新增模式：重置表单
        formData.value = { ...defaultFormData };
      }
      // 清除之前的校验状态
      nextTick(() => {
        formRef.value?.clearValidate();
      });
    }
  }
);

const handleSubmit = async () => {
  if (!formRef.value) return;
  const validation = await formRef.value.validate();
  if (validation) {
    // 校验失败
    Message.error('请检查表单输入！');
    return;
  }

  let submitData: CreateLlmConfigRequest | PartialUpdateLlmConfigRequest;

  if (isEditing.value && props.configData?.id) {
    // 编辑模式
    const partialData: PartialUpdateLlmConfigRequest = {
      config_name: formData.value.config_name,
      provider: formData.value.provider,
      name: formData.value.name,
      api_url: formData.value.api_url,
      is_active: formData.value.is_active,
    };
    if (formData.value.api_key) { // 只有当用户输入了新的 API Key 时才包含它
      partialData.api_key = formData.value.api_key;
    }
    if (formData.value.system_prompt !== undefined) { // 包含系统提示词（可以为空字符串）
      partialData.system_prompt = formData.value.system_prompt;
    }
    if (formData.value.supports_vision !== undefined) { // 包含多模态支持
      partialData.supports_vision = formData.value.supports_vision;
    }
    submitData = partialData;
    emit('submit', submitData, props.configData.id);
  } else {
    // 新增模式
    submitData = { ...formData.value };
     if (!submitData.api_key) { // 防御性检查，理论上表单校验会阻止
        Message.error('API Key 不能为空');
        return;
    }
    emit('submit', submitData);
  }
};

const handleCancel = () => {
  emit('cancel');
};

const loadProviders = async () => {
  loadingProviders.value = true;
  try {
    const response = await getProviders();
    if (response.status === 'success' && response.data) {
      providerOptions.value = response.data.choices;
    }
  } catch (error) {
    console.error('Failed to load providers:', error);
  } finally {
    loadingProviders.value = false;
  }
};

// 从 API 获取可用模型列表
const fetchAvailableModels = async () => {
  if (!formData.value.api_url) {
    Message.warning('请先填写 API URL');
    return;
  }

  if (!formData.value.api_key) {
    Message.warning('请先填写 API Key');
    return;
  }

  loadingModels.value = true;
  try {
    // 构造 models API 端点
    const apiUrl = formData.value.api_url.replace(/\/$/, ''); // 移除末尾斜杠
    const modelsEndpoint = `${apiUrl}/models`;

    const response = await axios.get(modelsEndpoint, {
      headers: {
        'Authorization': `Bearer ${formData.value.api_key}`,
        'Content-Type': 'application/json',
      },
      timeout: 10000, // 10秒超时
    });

    // OpenAI API 格式: { data: [{ id: 'model-name' }] }
    if (response.data && response.data.data) {
      const models = response.data.data.map((model: any) => model.id);
      modelOptions.value = models;
      if (models.length > 0) {
        Message.success(`成功获取 ${models.length} 个模型`);
      } else {
        Message.warning('未找到可用模型');
      }
    } else {
      Message.warning('API 返回格式不符合预期');
      modelOptions.value = [];
    }
  } catch (error: any) {
    console.error('获取模型列表失败:', error);
    const errorMsg = error.response?.data?.error?.message 
      || error.response?.statusText 
      || error.message 
      || '获取模型列表失败';
    Message.error(`获取模型列表失败: ${errorMsg}`);
    modelOptions.value = [];
  } finally {
    loadingModels.value = false;
  }
};

// 测试 LLM 模型真实可用性
const testLlmModel = async () => {
  // 验证必要字段
  if (!formData.value.api_url) {
    Message.warning('请先填写 API URL');
    return;
  }
  if (!formData.value.api_key) {
    Message.warning('请先填写 API Key');
    return;
  }
  if (!formData.value.name) {
    Message.warning('请先填写模型名称');
    return;
  }

  testingModel.value = true;
  try {
    // 构造 chat completions API 端点
    const apiUrl = formData.value.api_url.replace(/\/$/, '');
    const chatEndpoint = `${apiUrl}/chat/completions`;

    // 发送测试请求
    const response = await axios.post(chatEndpoint, {
      model: formData.value.name,
      messages: [
        { role: 'user', content: 'Hi, this is a test message.' }
      ],
      max_tokens: 10
    }, {
      headers: {
        'Authorization': `Bearer ${formData.value.api_key}`,
        'Content-Type': 'application/json',
      },
      timeout: 30000, // 30秒超时
    });

    // 验证返回数据包含有效响应
    if (response.data && response.data.choices && response.data.choices.length > 0) {
      const content = response.data.choices[0].message?.content;
      if (content !== undefined) {
        Message.success('模型测试成功！服务运行正常');
      } else {
        Message.warning('模型响应成功但数据格式异常');
      }
    } else {
      Message.warning('模型响应成功但未返回有效数据');
    }
  } catch (error: any) {
    console.error('模型测试失败:', error);
    const errorMsg = error.response?.data?.error?.message 
      || error.response?.statusText 
      || error.message 
      || '模型测试失败';
    Message.error(`模型测试失败: ${errorMsg}`);
  } finally {
    testingModel.value = false;
  }
};

// 处理模型输入框聚焦
const handleModelInputFocus = () => {
  // 如果有 API URL 和 API Key,且模型列表为空,自动获取
  if (formData.value.api_url && formData.value.api_key && modelOptions.value.length === 0) {
    fetchAvailableModels();
  }
};

onMounted(() => {
  loadProviders();
});
</script>

<style scoped>
.model-input-wrapper {
  display: flex;
  width: 100%;
  gap: 8px;
  align-items: center;
}

.model-input {
  flex: 1;
}

.test-button-row {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
  margin-top: -8px;
}

.switch-desc {
  font-size: 13px;
  color: var(--color-text-3);
  cursor: pointer;
}
</style>