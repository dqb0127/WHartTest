<template>
  <a-modal
    v-model:visible="modalVisible"
    :title="isEditing ? '编辑测试套件' : '创建测试套件'"
    :width="900"
    :mask-closable="false"
    @before-ok="handleSubmit"
    @cancel="handleCancel"
  >
    <a-form :model="formData" :rules="rules" ref="formRef" layout="vertical">
      <a-form-item label="套件名称" field="name" required>
        <a-input
          v-model="formData.name"
          placeholder="请输入测试套件名称"
          :max-length="100"
          show-word-limit
        />
      </a-form-item>

      <a-form-item label="套件描述" field="description">
        <a-textarea
          v-model="formData.description"
          placeholder="请输入套件描述(可选)"
          :max-length="500"
          :auto-size="{ minRows: 3, maxRows: 6 }"
          show-word-limit
        />
      </a-form-item>

      <a-form-item label="并发执行数" field="max_concurrent_tasks" required>
        <a-input-number
          v-model="formData.max_concurrent_tasks"
          :min="1"
          :max="10"
          :default-value="1"
          :style="{ width: '200px' }"
        />
        <div class="field-hint">
          <icon-info-circle style="margin-right: 4px;" />
          设置同时执行的测试用例/脚本数量。1表示串行执行，2-10表示并发执行。
        </div>
      </a-form-item>

      <!-- 标签页切换用例和脚本选择 -->
      <a-form-item required>
        <template #label>
          <div class="label-with-hint">
            <span>选择测试内容</span>
            <a-tag v-if="selectedTestCaseIds.length === 0 && selectedScriptIds.length === 0" color="orangered" size="small">
              请至少选择一个
            </a-tag>
            <a-tag v-else color="green" size="small">
              已选 {{ selectedTestCaseIds.length }} 用例 + {{ selectedScriptIds.length }} 脚本
            </a-tag>
          </div>
        </template>

        <a-tabs default-active-key="testcase">
          <a-tab-pane key="testcase" title="功能用例">
            <div class="content-selection">
              <a-alert v-if="selectedTestCaseIds.length > 0" type="info" style="margin-bottom: 12px;">
                已选择 <strong>{{ selectedTestCaseIds.length }}</strong> 个功能用例
              </a-alert>
              <a-button
                type="outline"
                @click="showTestCaseSelector = true"
                style="width: 100%; margin-bottom: 12px;"
              >
                <template #icon><icon-plus /></template>
                {{ selectedTestCaseIds.length > 0 ? '重新选择功能用例' : '选择功能用例' }}
              </a-button>

              <div v-if="selectedTestCases.length > 0" class="selected-items">
                <div class="item-list-header">
                  <span>已选择的功能用例:</span>
                  <a-button type="text" size="small" status="danger" @click="handleClearTestCases">清空</a-button>
                </div>
                <a-list :max-height="200" :scrollbar="true">
                  <a-list-item v-for="tc in selectedTestCases" :key="tc.id" class="item-row">
                    <a-list-item-meta :title="tc.name" :description="`优先级: ${tc.level}`" />
                    <template #actions>
                      <a-button type="text" size="small" status="danger" @click="handleRemoveTestCase(tc.id)">
                        <icon-close />
                      </a-button>
                    </template>
                  </a-list-item>
                </a-list>
              </div>
            </div>
          </a-tab-pane>

          <a-tab-pane key="script" title="自动化脚本">
            <div class="content-selection">
              <a-alert v-if="selectedScriptIds.length > 0" type="info" style="margin-bottom: 12px;">
                已选择 <strong>{{ selectedScriptIds.length }}</strong> 个自动化脚本
              </a-alert>
              <a-button
                type="outline"
                @click="showScriptSelector = true"
                style="width: 100%; margin-bottom: 12px;"
              >
                <template #icon><icon-plus /></template>
                {{ selectedScriptIds.length > 0 ? '重新选择自动化脚本' : '选择自动化脚本' }}
              </a-button>

              <div v-if="selectedScripts.length > 0" class="selected-items">
                <div class="item-list-header">
                  <span>已选择的自动化脚本:</span>
                  <a-button type="text" size="small" status="danger" @click="handleClearScripts">清空</a-button>
                </div>
                <a-list :max-height="200" :scrollbar="true">
                  <a-list-item v-for="sc in selectedScripts" :key="sc.id" class="item-row">
                    <a-list-item-meta :title="sc.name" :description="`关联用例: ${sc.test_case_name || '-'}`" />
                    <template #actions>
                      <a-button type="text" size="small" status="danger" @click="handleRemoveScript(sc.id)">
                        <icon-close />
                      </a-button>
                    </template>
                  </a-list-item>
                </a-list>
              </div>
            </div>
          </a-tab-pane>
        </a-tabs>
      </a-form-item>
    </a-form>

    <!-- 测试用例选择器模态框 -->
    <a-modal
      v-model:visible="showTestCaseSelector"
      title="选择功能用例"
      :width="1000"
      :footer="false"
      :mask-closable="false"
    >
      <TestCaseSelectorTable
        :current-project-id="currentProjectId"
        :initial-selected-ids="selectedTestCaseIds"
        @confirm="handleTestCaseSelect"
        @cancel="showTestCaseSelector = false"
      />
    </a-modal>

    <!-- 脚本选择器模态框 -->
    <a-modal
      v-model:visible="showScriptSelector"
      title="选择自动化脚本"
      :width="1000"
      :footer="false"
      :mask-closable="false"
    >
      <ScriptSelectorTable
        :current-project-id="currentProjectId"
        :initial-selected-ids="selectedScriptIds"
        @confirm="handleScriptSelect"
        @cancel="showScriptSelector = false"
      />
    </a-modal>
  </a-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import { Message } from '@arco-design/web-vue';
import { IconPlus, IconClose, IconInfoCircle } from '@arco-design/web-vue/es/icon';
import {
  createTestSuite,
  updateTestSuite,
  getTestSuiteDetail,
  type CreateTestSuiteRequest,
  type AutomationScriptBrief,
	} from '@/services/testSuiteService';
	import { getTestCaseDetail, type TestCase } from '@/services/testcaseService';
	import { getAutomationScript } from '@/services/automationScriptService';
	import TestCaseSelectorTable from './TestCaseSelectorTable.vue';
	import ScriptSelectorTable from './ScriptSelectorTable.vue';

interface Props {
  visible: boolean;
  currentProjectId: number | null;
  suiteId?: number | null;
  initialTestCaseIds?: number[];
  initialScriptIds?: number[];
}

const props = withDefaults(defineProps<Props>(), {
  suiteId: null,
  initialTestCaseIds: () => [],
  initialScriptIds: () => [],
});

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void;
  (e: 'success'): void;
}>();

const modalVisible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value),
});

const isEditing = computed(() => !!props.suiteId);

const formRef = ref();
const showTestCaseSelector = ref(false);
const showScriptSelector = ref(false);
const selectedTestCaseIds = ref<number[]>([]);
const selectedTestCases = ref<TestCase[]>([]);
const selectedScriptIds = ref<number[]>([]);
const selectedScripts = ref<AutomationScriptBrief[]>([]);
const loading = ref(false);

const formData = ref<CreateTestSuiteRequest>({
  name: '',
  description: '',
  testcase_ids: [],
  script_ids: [],
  max_concurrent_tasks: 1,
});

const rules = {
  name: [
    { required: true, message: '请输入套件名称' },
    { minLength: 2, message: '套件名称至少2个字符' },
  ],
  max_concurrent_tasks: [
    { required: true, message: '请设置并发执行数' },
    { type: 'number', min: 1, max: 10, message: '并发数必须在1-10之间' },
  ],
};

// 加载已选择的测试用例详情
const loadSelectedTestCases = async () => {
  if (!props.currentProjectId || selectedTestCaseIds.value.length === 0) {
    selectedTestCases.value = [];
    return;
  }
  try {
    const promises = selectedTestCaseIds.value.map((id) =>
      getTestCaseDetail(props.currentProjectId!, id)
    );
    const responses = await Promise.all(promises);
    selectedTestCases.value = responses.filter((r) => r.success && r.data).map((r) => r.data!);
  } catch (error) {
    console.error('加载测试用例详情失败:', error);
  }
};

// 加载已选择的脚本详情
	const loadSelectedScripts = async () => {
	  if (!props.currentProjectId || selectedScriptIds.value.length === 0) {
	    selectedScripts.value = [];
	    return;
	  }
	  try {
	    const promises = selectedScriptIds.value.map((id) =>
	      getAutomationScript(props.currentProjectId!, id)
	    );
	    const responses = await Promise.all(promises);
	    selectedScripts.value = responses
	      .filter((r) => r.data?.success && r.data?.data)
	      .map((r) => r.data.data);
  } catch (error) {
    console.error('加载脚本详情失败:', error);
  }
};

// 处理测试用例选择
const handleTestCaseSelect = (testcaseIds: number[]) => {
  selectedTestCaseIds.value = testcaseIds;
  loadSelectedTestCases();
  showTestCaseSelector.value = false;
};

// 处理脚本选择
const handleScriptSelect = (scriptIds: number[]) => {
  selectedScriptIds.value = scriptIds;
  loadSelectedScripts();
  showScriptSelector.value = false;
};

// 移除单个测试用例
const handleRemoveTestCase = (id: number) => {
  selectedTestCaseIds.value = selectedTestCaseIds.value.filter((tcId) => tcId !== id);
  selectedTestCases.value = selectedTestCases.value.filter((tc) => tc.id !== id);
};

// 移除单个脚本
const handleRemoveScript = (id: number) => {
  selectedScriptIds.value = selectedScriptIds.value.filter((scId) => scId !== id);
  selectedScripts.value = selectedScripts.value.filter((sc) => sc.id !== id);
};

// 清空用例选择
const handleClearTestCases = () => {
  selectedTestCaseIds.value = [];
  selectedTestCases.value = [];
};

// 清空脚本选择
const handleClearScripts = () => {
  selectedScriptIds.value = [];
  selectedScripts.value = [];
};

// 提交表单
const handleSubmit = async () => {
  if (!props.currentProjectId) {
    Message.error('缺少项目ID');
    return false;
  }

  // 自定义验证：至少选择一个用例或脚本
  if (selectedTestCaseIds.value.length === 0 && selectedScriptIds.value.length === 0) {
    Message.error('请至少选择一个功能用例或自动化脚本');
    return false;
  }

  try {
    await formRef.value?.validate();

    loading.value = true;
    formData.value.testcase_ids = selectedTestCaseIds.value;
    formData.value.script_ids = selectedScriptIds.value;

    const response = isEditing.value
      ? await updateTestSuite(props.currentProjectId, props.suiteId!, formData.value)
      : await createTestSuite(props.currentProjectId, formData.value);

    if (response.success) {
      Message.success(response.message || (isEditing.value ? '更新成功' : '创建成功'));
      emit('success');
      handleCancel();
      return true;
    } else {
      Message.error(response.error || '操作失败');
      return false;
    }
  } catch (error) {
    console.error('提交表单失败:', error);
    return false;
  } finally {
    loading.value = false;
  }
};

// 取消
const handleCancel = () => {
  formRef.value?.resetFields();
  selectedTestCaseIds.value = [];
  selectedTestCases.value = [];
  selectedScriptIds.value = [];
  selectedScripts.value = [];
  emit('update:visible', false);
};

// 加载套件详情
const loadSuiteDetail = async () => {
  if (!props.currentProjectId || !props.suiteId) {
    return;
  }

  loading.value = true;
  try {
    const response = await getTestSuiteDetail(props.currentProjectId, props.suiteId);

    if (response.success && response.data) {
      const suite = response.data;

      formData.value.name = suite.name;
      formData.value.description = suite.description || '';
      formData.value.max_concurrent_tasks = suite.max_concurrent_tasks || 1;

      // 获取用例ID列表
      if (suite.testcases_detail && suite.testcases_detail.length > 0) {
        selectedTestCaseIds.value = suite.testcases_detail.map((tc) => tc.id);
        selectedTestCases.value = [...suite.testcases_detail];
      }

      // 获取脚本ID列表
      if (suite.scripts_detail && suite.scripts_detail.length > 0) {
        selectedScriptIds.value = suite.scripts_detail.map((sc) => sc.id);
        selectedScripts.value = [...suite.scripts_detail];
      }
    } else {
      Message.error(response.error || '加载套件详情失败');
    }
  } catch (error) {
    console.error('加载套件详情失败:', error);
    Message.error('加载套件详情时发生错误');
  } finally {
    loading.value = false;
  }
};

// 监听visible变化，初始化数据
watch(
  () => props.visible,
  async (newVal) => {
    if (newVal) {
      if (isEditing.value && props.suiteId) {
        await loadSuiteDetail();
      } else {
        selectedTestCaseIds.value = [...props.initialTestCaseIds];
        selectedScriptIds.value = [...props.initialScriptIds];
        loadSelectedTestCases();
        loadSelectedScripts();
      }
    }
  }
);
</script>

<style scoped>
:deep(.arco-tabs) {
  width: 100%;
}

:deep(.arco-tabs-content) {
  width: 100%;
}

:deep(.arco-tabs-pane) {
  width: 100%;
}

.content-selection {
  width: 100%;
}

.selected-items {
  border: 1px solid var(--color-border);
  border-radius: 4px;
  padding: 12px;
}

.item-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-weight: 500;
}

.item-row {
  padding: 8px 0;
}

.item-row:not(:last-child) {
  border-bottom: 1px solid var(--color-border-1);
}

.field-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-3);
  display: flex;
  align-items: flex-start;
  line-height: 1.5;
}

.label-with-hint {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
