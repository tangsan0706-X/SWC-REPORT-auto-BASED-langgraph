<template>
  <div>
    <h3 style="text-align: center; margin-bottom: 24px">报告生成中</h3>
    <el-card>
      <el-steps :active="activeStep" direction="vertical" finish-status="success">
        <el-step v-for="(step, i) in STEPS" :key="i"
          :title="step"
          :status="stepStatus(i)"
          :description="stepDesc(i)"
        />
      </el-steps>
    </el-card>

    <el-card v-if="logs.length > 0" style="margin-top: 16px">
      <template #header><span>执行日志</span></template>
      <div ref="logBox" style="max-height: 200px; overflow-y: auto; font-family: monospace; font-size: 13px; line-height: 1.6">
        <div v-for="(log, i) in logs" :key="i" :style="{ color: log.status === 'error' ? '#f56c6c' : '#303133' }">
          <span style="color: #909399">{{ formatTime(log.timestamp) }}</span>
          [{{ log.step }}] {{ log.status }}
          <span v-if="log.error" style="color: #f56c6c"> - {{ log.error }}</span>
        </div>
      </div>
    </el-card>

    <!-- 错误状态 -->
    <el-result v-if="errorMsg" icon="error" title="生成失败" :sub-title="errorMsg" style="margin-top: 24px" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted, nextTick } from 'vue'
import { getRun, streamProgress } from '../api/index.js'

const props = defineProps({ runId: String })
const emit = defineEmits(['done', 'error'])

const STEPS = [
  '1/15 加载配置', '2/15 预处理', '3/15 土方平衡计算', '4/15 侵蚀预测计算',
  '5/15 措施规划', '6/15 造价估算', '7/15 效益分析', '8/15 状态装配(229标签)',
  '9/15 报告撰写', '10/15 图表生成', '11/15 初次渲染', '12/15 质量审计',
  '13/15 审计回弹重写', '14/15 最终渲染', '15/15 打包输出',
]

const logs = ref([])
const errorMsg = ref(null)
const logBox = ref(null)
const stepStates = ref({})
let evtSource = null

const activeStep = computed(() => {
  for (let i = STEPS.length - 1; i >= 0; i--) {
    if (stepStates.value[STEPS[i]] === 'done') return i + 1
    if (stepStates.value[STEPS[i]] === 'running') return i
  }
  return 0
})

function stepStatus(i) {
  const s = stepStates.value[STEPS[i]]
  if (s === 'done') return 'success'
  if (s === 'running') return 'process'
  if (s === 'error') return 'error'
  return 'wait'
}

function stepDesc(i) {
  const s = stepStates.value[STEPS[i]]
  if (s === 'running') return '执行中...'
  if (s === 'error') return '失败'
  if (s === 'done') return '完成'
  return ''
}

function formatTime(t) {
  return t ? t.substring(11, 19) : ''
}

function startListening() {
  if (!props.runId) return
  evtSource = streamProgress(props.runId, (evt) => {
    logs.value.push(evt)
    if (evt.step && evt.step !== 'pipeline') {
      stepStates.value[evt.step] = evt.status
    }
    if (evt.step === 'pipeline' && evt.status === 'error') {
      errorMsg.value = evt.error || '未知错误'
    }
    nextTick(() => { if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight })
  }, async () => {
    const { data } = await getRun(props.runId)
    if (data.status === 'done') {
      emit('done')
    } else {
      errorMsg.value = data.error_message || '运行异常'
      emit('error')
    }
  })
}

watch(() => props.runId, (newId) => {
  if (evtSource) evtSource.close()
  if (newId) startListening()
}, { immediate: true })

onUnmounted(() => { if (evtSource) evtSource.close() })
</script>
