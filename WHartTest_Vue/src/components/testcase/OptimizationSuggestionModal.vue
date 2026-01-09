<template>
  <a-modal
    v-model:visible="visible"
    title="用例优化"
    :width="960"
    @ok="handleSubmit"
    @cancel="handleCancel"
    ok-text="确认优化"
    cancel-text="取消"
    :body-style="{ padding: '16px 20px' }"
  >
    <div class="optimization-modal">
      <!-- 顶部：基本信息（横向排列） -->
      <div class="basic-info">
        <div class="info-item">
          <span class="info-label">ID</span>
          <span class="info-value">{{ testCase?.id }}</span>
        </div>
        <div class="info-item name-item">
          <span class="info-label">名称</span>
          <span class="info-value">{{ testCase?.name }}</span>
        </div>
        <div class="info-item">
          <span class="info-label">优先级</span>
          <a-tag :color="getLevelColor(testCase?.level)" size="small">{{ testCase?.level }}</a-tag>
        </div>
        <div class="info-item" v-if="testCase?.module_detail">
          <span class="info-label">模块</span>
          <span class="info-value">{{ testCase?.module_detail }}</span>
        </div>
      </div>

      <!-- 前置条件（如果有） -->
      <div class="precondition-section" v-if="testCase?.precondition">
        <span class="section-label">前置条件：</span>
        <span class="section-text">{{ testCase.precondition }}</span>
      </div>

      <!-- 中间：步骤表格 -->
      <div class="steps-section" v-if="testCase?.steps && testCase.steps.length > 0">
        <div class="section-header">测试步骤</div>
        <div class="steps-table">
          <div class="table-header">
            <div class="col-step">步骤</div>
            <div class="col-action">操作描述</div>
            <div class="col-expected">预期结果</div>
          </div>
          <div class="table-body">
            <div class="table-row" v-for="step in testCase.steps" :key="step.step_number">
              <div class="col-step">{{ step.step_number }}</div>
              <div class="col-action">{{ step.description }}</div>
              <div class="col-expected">{{ step.expected_result }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 备注（如果有） -->
      <div class="notes-section" v-if="testCase?.notes">
        <span class="section-label">备注：</span>
        <span class="section-text">{{ testCase.notes }}</span>
      </div>

      <!-- 分隔线 -->
      <a-divider :margin="12" />

      <!-- 底部：优化建议输入 -->
      <div class="suggestion-section">
        <div class="suggestion-header">
          <span class="suggestion-title">优化建议</span>
          <span class="suggestion-optional">（可选）</span>
        </div>
        <a-textarea
          v-model="suggestion"
          placeholder="请输入您对该用例的优化建议。如不填写，AI将根据测试最佳实践进行全面优化。"
          :max-length="1000"
          show-word-limit
          :auto-size="{ minRows: 2, maxRows: 4 }"
        />
      </div>

      <!-- 提示信息 -->
      <div class="optimization-hint">
        <icon-info-circle />
        <span>确认后将在后台开始优化任务，您可以在通知中查看进度。</span>
      </div>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { IconInfoCircle } from '@arco-design/web-vue/es/icon';
import type { TestCase } from '@/services/testcaseService';
import { getLevelColor } from '@/utils/formatters';

const props = defineProps<{
  modelValue: boolean;
  testCase: TestCase | null;
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'submit', data: { testCase: TestCase; suggestion: string }): void;
}>();

const visible = ref(props.modelValue);
const suggestion = ref('');

watch(() => props.modelValue, (newVal) => {
  visible.value = newVal;
  if (newVal) {
    suggestion.value = '';
  }
});

watch(visible, (newVal) => {
  emit('update:modelValue', newVal);
});

const handleSubmit = () => {
  if (props.testCase) {
    emit('submit', {
      testCase: props.testCase,
      suggestion: suggestion.value.trim(),
    });
  }
  visible.value = false;
};

const handleCancel = () => {
  visible.value = false;
};
</script>

<style scoped>
.optimization-modal {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 基本信息区域 - 横向排列 */
.basic-info {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 10px 14px;
  background: linear-gradient(135deg, #f8f9fa 0%, #f2f3f5 100%);
  border-radius: 6px;
  flex-wrap: wrap;
}

.info-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.info-item.name-item {
  flex: 1;
  min-width: 200px;
}

.info-label {
  font-size: 12px;
  color: #86909c;
  flex-shrink: 0;
}

.info-value {
  font-size: 13px;
  color: #1d2129;
  font-weight: 500;
}

/* 前置条件 */
.precondition-section {
  display: flex;
  font-size: 13px;
  padding: 8px 12px;
  background-color: #fffbe6;
  border-radius: 4px;
  border-left: 3px solid #faad14;
}

.section-label {
  color: #86909c;
  flex-shrink: 0;
  margin-right: 8px;
}

.section-text {
  color: #4e5969;
  word-break: break-word;
}

/* 步骤表格 */
.steps-section {
  display: flex;
  flex-direction: column;
}

.section-header {
  font-size: 13px;
  font-weight: 500;
  color: #1d2129;
  margin-bottom: 8px;
}

.steps-table {
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  overflow: hidden;
  max-height: 240px;
  overflow-y: auto;
}

.table-header {
  display: flex;
  background-color: #f7f8fa;
  font-size: 12px;
  font-weight: 500;
  color: #4e5969;
  border-bottom: 1px solid #e5e6eb;
}

.table-body {
  font-size: 12px;
}

.table-row {
  display: flex;
  border-bottom: 1px solid #f2f3f5;
}

.table-row:last-child {
  border-bottom: none;
}

.table-row:hover {
  background-color: #f7f8fa;
}

.col-step {
  width: 50px;
  flex-shrink: 0;
  padding: 8px 10px;
  text-align: center;
  color: #165dff;
  font-weight: 500;
  border-right: 1px solid #f2f3f5;
}

.table-header .col-step {
  color: #4e5969;
  border-right: 1px solid #e5e6eb;
}

.col-action {
  flex: 1;
  padding: 8px 12px;
  color: #1d2129;
  border-right: 1px solid #f2f3f5;
  word-break: break-word;
}

.table-header .col-action {
  border-right: 1px solid #e5e6eb;
}

.col-expected {
  flex: 1;
  padding: 8px 12px;
  color: #00b42a;
  word-break: break-word;
}

.table-header .col-expected {
  color: #4e5969;
}

/* 备注区域 */
.notes-section {
  display: flex;
  font-size: 12px;
  padding: 8px 12px;
  background-color: #f7f8fa;
  border-radius: 4px;
}

.notes-section .section-text {
  white-space: pre-wrap;
}

/* 优化建议输入 */
.suggestion-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.suggestion-header {
  display: flex;
  align-items: center;
}

.suggestion-title {
  font-size: 13px;
  font-weight: 500;
  color: #1d2129;
}

.suggestion-optional {
  font-size: 12px;
  color: #86909c;
  margin-left: 4px;
}

/* 提示信息 */
.optimization-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background-color: #e8f3ff;
  border-radius: 4px;
  color: #165dff;
  font-size: 12px;
}
</style>
