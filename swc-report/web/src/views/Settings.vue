<template>
  <div style="padding: 24px; max-width: 700px; margin: 0 auto">
    <h2 style="margin-bottom: 24px">系统设置</h2>

    <!-- 健康检查 -->
    <el-card style="margin-bottom: 20px">
      <template #header><span>LLM 连接状态</span></template>
      <el-result
        :icon="health?.llm_reachable ? 'success' : 'error'"
        :title="health?.llm_reachable ? 'LLM 文本模型在线' : 'LLM 文本模型不可达'"
        :sub-title="health?.message || ''"
        style="padding: 16px 0"
      >
        <template #extra>
          <el-button @click="checkHealth" :loading="checking">刷新检测</el-button>
        </template>
      </el-result>
      <div v-if="health?.llm_models?.length > 0" style="margin-top: 4px; text-align: center">
        <span style="color:#909399; font-size:13px; margin-right: 8px">可用模型:</span>
        <el-tag v-for="m in health.llm_models" :key="m" style="margin-right: 6px" size="small">{{ m }}</el-tag>
      </div>
    </el-card>

    <!-- VL 模型状态 -->
    <el-card style="margin-bottom: 20px">
      <template #header><span>VL 视觉模型状态</span></template>
      <el-result
        :icon="vlHealth?.vl_reachable ? 'success' : 'warning'"
        :title="vlHealth?.vl_reachable ? 'VL 视觉模型在线' : 'VL 视觉模型未连接'"
        :sub-title="vlHealth?.vl_reachable ? `端口: ${vlHealth.vl_url}` : '视觉模型用于文档智能识别 (可选功能)'"
        style="padding: 16px 0"
      >
        <template #extra>
          <el-button @click="checkVlHealth" :loading="checkingVl">刷新检测</el-button>
        </template>
      </el-result>
      <div v-if="vlHealth?.vl_models?.length > 0" style="margin-top: 4px; text-align: center">
        <span style="color:#909399; font-size:13px; margin-right: 8px">VL 模型:</span>
        <el-tag v-for="m in vlHealth.vl_models" :key="m" style="margin-right: 6px" size="small" type="success">{{ m }}</el-tag>
      </div>
      <div style="margin-top: 8px; text-align: center; font-size: 12px; color: #909399">
        AutoDL 部署: GPU 0,1 → 文本模型 (端口 8000) | GPU 2,3 → VL 模型 (端口 8001)
      </div>
    </el-card>

    <!-- 快捷预设 -->
    <el-card style="margin-bottom: 20px">
      <template #header><span>快捷预设</span></template>
      <el-space wrap>
        <el-button v-for="p in presets" :key="p.name" @click="applyPreset(p)"
          :type="form.vllm_url === p.vllm_url && form.model_name === p.model_name ? 'primary' : ''">
          {{ p.name }}
        </el-button>
      </el-space>
    </el-card>

    <!-- 设置表单 -->
    <el-card>
      <template #header><span>LLM 参数配置</span></template>
      <el-form label-width="140px" v-loading="loadingSettings">
        <el-form-item label="API 地址">
          <el-input v-model="form.vllm_url" placeholder="http://localhost:11434/v1" />
          <div style="font-size: 12px; color: #909399; margin-top: 4px">
            Ollama: http://localhost:11434/v1 | vLLM: http://localhost:8000/v1
          </div>
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="form.model_name" placeholder="qwen2.5:7b" />
          <div style="font-size: 12px; color: #909399; margin-top: 4px">
            Ollama: qwen2.5:7b / qwen2.5:14b | vLLM: Qwen2.5-72B-Instruct
          </div>
        </el-form-item>
        <el-form-item label="最大输出 Token">
          <el-input-number v-model="form.max_tokens" :min="512" :max="16384" :step="512" />
        </el-form-item>
        <el-form-item label="生成温度">
          <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.05" show-input />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="saveSettings" :loading="saving">保存设置</el-button>
          <el-button @click="loadSettings">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { healthCheck, getSettings, updateSettings, vlHealthCheck } from '../api/index.js'
import { ElMessage } from 'element-plus'
import api from '../api/index.js'

const health = ref(null)
const vlHealth = ref(null)
const checking = ref(false)
const checkingVl = ref(false)
const loadingSettings = ref(false)
const saving = ref(false)
const presets = ref([])
const form = reactive({
  vllm_url: '',
  model_name: '',
  max_tokens: 4096,
  temperature: 0.3,
})

async function checkHealth() {
  checking.value = true
  try {
    const { data } = await healthCheck()
    health.value = data
  } catch (e) {
    health.value = { status: 'error', llm_reachable: false, message: e.message }
  } finally {
    checking.value = false
  }
}

async function checkVlHealth() {
  checkingVl.value = true
  try {
    const { data } = await vlHealthCheck()
    vlHealth.value = data
  } catch (e) {
    vlHealth.value = { status: 'error', vl_reachable: false, message: e.message }
  } finally {
    checkingVl.value = false
  }
}

async function loadSettings() {
  loadingSettings.value = true
  try {
    const { data } = await getSettings()
    Object.assign(form, data)
  } catch (e) {
    ElMessage.error('加载设置失败')
  } finally {
    loadingSettings.value = false
  }
}

async function loadPresets() {
  try {
    const { data } = await api.get('/system/presets')
    presets.value = data
  } catch { /* ignore */ }
}

function applyPreset(p) {
  form.vllm_url = p.vllm_url
  form.model_name = p.model_name
  ElMessage.info(`已切换到: ${p.name}，点击"保存设置"生效`)
}

async function saveSettings() {
  saving.value = true
  try {
    await updateSettings(form)
    ElMessage.success('设置已保存')
    checkHealth()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadSettings()
  checkHealth()
  checkVlHealth()
  loadPresets()
})
</script>
