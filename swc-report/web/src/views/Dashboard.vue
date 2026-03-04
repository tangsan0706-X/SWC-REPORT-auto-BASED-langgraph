<template>
  <div style="padding: 24px">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px">
      <h2 style="margin: 0">我的报告</h2>
      <el-button type="primary" @click="$router.push('/new')">新建报告</el-button>
    </div>

    <el-table :data="runs" v-loading="loading" stripe style="width: 100%">
      <el-table-column prop="id" label="ID" width="130" />
      <el-table-column prop="project_name" label="项目名称" min-width="200">
        <template #default="{ row }">
          {{ row.project_name || '(未命名)' }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="total_score" label="审计分数" width="100" align="center">
        <template #default="{ row }">
          <span v-if="row.status === 'done'" :style="{ fontWeight: 'bold', color: row.total_score >= 80 ? '#67c23a' : '#e6a23c' }">
            {{ row.total_score }}
          </span>
          <span v-else style="color: #c0c4cc">-</span>
        </template>
      </el-table-column>
      <el-table-column label="LLM" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.use_llm ? '' : 'info'" size="small">{{ row.use_llm ? 'LLM' : '无' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="180">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="260" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status === 'running' || row.status === 'pending'"
            size="small" type="warning" @click="$router.push(`/run/${row.id}`)">
            查看进度
          </el-button>
          <el-button v-if="row.status === 'done'"
            size="small" type="primary" @click="$router.push(`/result/${row.id}`)">
            查看报告
          </el-button>
          <el-button v-if="row.status === 'done'"
            size="small" @click="downloadReport(row.id)">
            导出
          </el-button>
          <el-button size="small" type="danger" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && runs.length === 0" description="暂无报告记录，点击上方按钮新建">
      <el-button type="primary" @click="$router.push('/new')">新建报告</el-button>
    </el-empty>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { listRuns, deleteRun, downloadResult } from '../api/index.js'
import { ElMessageBox, ElMessage } from 'element-plus'

const runs = ref([])
const loading = ref(false)

const statusType = (s) => ({ pending: 'info', running: 'warning', done: 'success', error: 'danger' }[s] || 'info')
const statusLabel = (s) => ({ pending: '等待', running: '生成中', done: '完成', error: '失败' }[s] || s)
const formatTime = (t) => t ? t.replace('T', ' ').substring(0, 19) : ''

function downloadReport(id) {
  window.open(downloadResult(id), '_blank')
}

async function loadRuns() {
  loading.value = true
  try {
    const { data } = await listRuns()
    runs.value = data
  } catch (e) {
    ElMessage.error('加载失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function handleDelete(id) {
  try {
    await ElMessageBox.confirm('确定删除此报告及输出文件?', '确认删除', { type: 'warning' })
    await deleteRun(id)
    ElMessage.success('已删除')
    loadRuns()
  } catch { /* cancelled */ }
}

onMounted(loadRuns)
</script>
