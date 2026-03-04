<template>
  <div style="padding: 24px; height: 100vh; overflow-y: auto">
    <h2 style="margin: 0 0 20px">知识库管理</h2>

    <el-tabs v-model="activeTab" type="border-card">
      <!-- ═══ Tab 1: 配置文件 ═══ -->
      <el-tab-pane label="配置文件" name="config">
        <el-table :data="configFiles" stripe style="width: 100%" v-loading="configLoading">
          <el-table-column prop="name" label="文件名" min-width="200" />
          <el-table-column prop="size_kb" label="大小 (KB)" width="120" />
          <el-table-column prop="modified" label="修改时间" width="200">
            <template #default="{ row }">{{ formatTime(row.modified) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="editConfigFile(row)">编辑</el-button>
              <el-button size="small" type="info" link @click="backupConfigFile(row)">备份</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div style="margin-top: 20px">
          <el-button
            type="warning"
            :loading="generateLoading"
            @click="handleGenerate"
          >
            LLM 重新生成措施库
          </el-button>
          <span v-if="generateStatus.status !== 'idle'" style="margin-left: 12px; color: #666">
            {{ generateStatusText }}
          </span>
        </div>
      </el-tab-pane>

      <!-- ═══ Tab 2: 知识文档 (atlas/) ═══ -->
      <el-tab-pane label="知识文档" name="atlas">
        <el-upload
          drag
          :auto-upload="false"
          :on-change="handleAtlasFileChange"
          :show-file-list="false"
          accept=".md,.docx,.pdf,.dwg,.dxf,.png,.jpg,.jpeg,.txt"
          style="margin-bottom: 16px"
        >
          <el-icon style="font-size: 40px; color: #c0c4cc"><UploadFilled /></el-icon>
          <div>将文件拖到此处，或<em>点击上传</em></div>
          <template #tip>
            <div style="color: #909399; font-size: 12px">
              支持 md / docx / pdf / dwg / dxf / png / jpg / txt，最大 50MB
            </div>
          </template>
        </el-upload>

        <el-table :data="atlasFiles" stripe style="width: 100%" v-loading="atlasLoading">
          <el-table-column prop="name" label="文件名" min-width="250" />
          <el-table-column prop="file_type" label="类型" width="100" />
          <el-table-column prop="size_kb" label="大小 (KB)" width="120" />
          <el-table-column prop="modified" label="修改时间" width="200">
            <template #default="{ row }">{{ formatTime(row.modified) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-popconfirm
                title="确认删除？文件将移到回收站。"
                @confirm="handleDeleteAtlas(row.name)"
              >
                <template #reference>
                  <el-button size="small" type="danger" link>删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>

        <div style="margin-top: 20px">
          <el-button
            type="primary"
            :loading="atlasReindexLoading"
            @click="handleAtlasReindex"
          >
            重建索引
          </el-button>
          <span v-if="atlasReindexStatus.status !== 'idle'" style="margin-left: 12px; color: #666">
            {{ atlasReindexStatusText }}
          </span>
        </div>
      </el-tab-pane>

      <!-- ═══ Tab 3: 范文语料 (corpus/) ═══ -->
      <el-tab-pane label="范文语料" name="corpus">
        <el-upload
          drag
          :auto-upload="false"
          :on-change="handleCorpusFileChange"
          :show-file-list="false"
          accept=".pdf"
          style="margin-bottom: 16px"
        >
          <el-icon style="font-size: 40px; color: #c0c4cc"><UploadFilled /></el-icon>
          <div>将 PDF 文件拖到此处，或<em>点击上传</em></div>
          <template #tip>
            <div style="color: #909399; font-size: 12px">仅支持 PDF，最大 50MB</div>
          </template>
        </el-upload>

        <el-table :data="corpusFiles" stripe style="width: 100%" v-loading="corpusLoading">
          <el-table-column prop="name" label="文件名" min-width="300" />
          <el-table-column prop="size_kb" label="大小 (KB)" width="120" />
          <el-table-column prop="modified" label="修改时间" width="200">
            <template #default="{ row }">{{ formatTime(row.modified) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-popconfirm
                title="确认删除？文件将移到回收站。"
                @confirm="handleDeleteCorpus(row.name)"
              >
                <template #reference>
                  <el-button size="small" type="danger" link>删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>

        <div style="margin-top: 20px">
          <el-button
            type="primary"
            :loading="corpusReindexLoading"
            @click="handleCorpusReindex"
          >
            重建索引
          </el-button>
          <span v-if="corpusReindexStatus.status !== 'idle'" style="margin-left: 12px; color: #666">
            {{ corpusReindexStatusText }}
          </span>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ═══ 编辑配置文件弹窗 ═══ -->
    <el-dialog
      v-model="editDialogVisible"
      :title="`编辑: ${editingFile?.name || ''}`"
      width="70%"
      top="5vh"
      destroy-on-close
    >
      <el-input
        v-model="editContent"
        type="textarea"
        :autosize="{ minRows: 15, maxRows: 30 }"
        style="font-family: monospace; font-size: 13px"
      />
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saveLoading" @click="handleSaveConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import {
  listConfigFiles, getConfigFile, updateConfigFile,
  listAtlasFiles, uploadAtlasFile, deleteAtlasFile, reindexAtlas, getAtlasReindexStatus,
  listCorpusFiles, uploadCorpusFile, deleteCorpusFile, reindexCorpus, getCorpusReindexStatus,
  generateMeasureLibrary, getGenerateStatus,
} from '../api'

// ── State ───────────────────────────────────────────
const activeTab = ref('config')

// Config
const configFiles = ref([])
const configLoading = ref(false)
const editDialogVisible = ref(false)
const editingFile = ref(null)
const editingKey = ref('')
const editContent = ref('')
const saveLoading = ref(false)

// Atlas
const atlasFiles = ref([])
const atlasLoading = ref(false)
const atlasReindexLoading = ref(false)
const atlasReindexStatus = ref({ status: 'idle', message: '' })

// Corpus
const corpusFiles = ref([])
const corpusLoading = ref(false)
const corpusReindexLoading = ref(false)
const corpusReindexStatus = ref({ status: 'idle', message: '' })

// Generate
const generateLoading = ref(false)
const generateStatus = ref({ status: 'idle', message: '', updated_at: '' })

// ── Computed ────────────────────────────────────────
const generateStatusText = computed(() => {
  const s = generateStatus.value
  if (s.status === 'running') return '正在生成中...'
  if (s.status === 'done') return `完成: ${s.message}`
  if (s.status === 'error') return `错误: ${s.message}`
  return ''
})
const atlasReindexStatusText = computed(() => {
  const s = atlasReindexStatus.value
  if (s.status === 'running') return '正在重建索引...'
  if (s.status === 'done') return `完成: ${s.message}`
  if (s.status === 'error') return `错误: ${s.message}`
  return ''
})
const corpusReindexStatusText = computed(() => {
  const s = corpusReindexStatus.value
  if (s.status === 'running') return '正在重建索引...'
  if (s.status === 'done') return `完成: ${s.message}`
  if (s.status === 'error') return `错误: ${s.message}`
  return ''
})

// ── Helpers ─────────────────────────────────────────
function formatTime(iso) {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN')
  } catch {
    return iso
  }
}

// file_key from filename
const FILE_KEY_MAP = {
  'measure_library.json': 'measure_library',
  'legal_refs.json': 'legal_refs',
  'fee_rate_config.json': 'fee_rate_config',
  'soil_map.json': 'soil_map',
  'price_v2.csv': 'price_v2',
}

// ── Config Files ────────────────────────────────────
async function loadConfigFiles() {
  configLoading.value = true
  try {
    const { data } = await listConfigFiles()
    configFiles.value = data
  } catch (e) {
    ElMessage.error('加载配置文件列表失败')
  } finally {
    configLoading.value = false
  }
}

async function editConfigFile(row) {
  const key = FILE_KEY_MAP[row.name]
  if (!key) {
    ElMessage.warning('未知配置文件')
    return
  }
  try {
    const { data } = await getConfigFile(key)
    editingFile.value = row
    editingKey.value = key
    editContent.value = typeof data.content === 'string'
      ? data.content
      : JSON.stringify(data.content, null, 2)
    editDialogVisible.value = true
  } catch (e) {
    ElMessage.error('读取文件内容失败')
  }
}

async function backupConfigFile(row) {
  const key = FILE_KEY_MAP[row.name]
  if (!key) return
  try {
    // 读取并立即写回（触发自动备份）
    const { data } = await getConfigFile(key)
    await updateConfigFile(key, { content: data.content })
    ElMessage.success(`已备份 ${row.name} → ${row.name}.bak`)
  } catch (e) {
    ElMessage.error('备份失败')
  }
}

async function handleSaveConfig() {
  saveLoading.value = true
  try {
    let content
    const filename = editingFile.value?.name || ''
    if (filename.endsWith('.json')) {
      content = JSON.parse(editContent.value)
    } else if (filename.endsWith('.csv')) {
      // CSV: 解析为对象数组
      const lines = editContent.value.trim().split('\n')
      if (lines.length < 2) throw new Error('CSV 至少需要表头和一行数据')
      const headers = lines[0].split(',').map(h => h.trim())
      content = lines.slice(1).map(line => {
        const vals = line.split(',').map(v => v.trim())
        const obj = {}
        headers.forEach((h, i) => { obj[h] = vals[i] || '' })
        return obj
      })
    } else {
      content = editContent.value
    }
    await updateConfigFile(editingKey.value, { content })
    ElMessage.success('保存成功（已自动备份）')
    editDialogVisible.value = false
    loadConfigFiles()
  } catch (e) {
    ElMessage.error(`保存失败: ${e.message || e}`)
  } finally {
    saveLoading.value = false
  }
}

// ── LLM Generate ────────────────────────────────────
let generatePollTimer = null

async function handleGenerate() {
  try {
    await ElMessageBox.confirm(
      '将使用 LLM 重新生成 measure_library.json，当前文件会自动备份。确认继续？',
      '确认生成',
      { type: 'warning' }
    )
  } catch {
    return
  }

  generateLoading.value = true
  try {
    await generateMeasureLibrary()
    // 开始轮询
    pollGenerateStatus()
  } catch (e) {
    ElMessage.error('启动生成任务失败')
    generateLoading.value = false
  }
}

function pollGenerateStatus() {
  if (generatePollTimer) clearInterval(generatePollTimer)
  generatePollTimer = setInterval(async () => {
    try {
      const { data } = await getGenerateStatus()
      generateStatus.value = data
      if (data.status === 'done') {
        clearInterval(generatePollTimer)
        generatePollTimer = null
        generateLoading.value = false
        ElMessage.success('措施库已生成并覆盖写入')
        loadConfigFiles()
      } else if (data.status === 'error') {
        clearInterval(generatePollTimer)
        generatePollTimer = null
        generateLoading.value = false
        ElMessage.error(`生成失败: ${data.message}`)
      }
    } catch {
      clearInterval(generatePollTimer)
      generatePollTimer = null
      generateLoading.value = false
    }
  }, 2000)
}

// ── Atlas Files ─────────────────────────────────────
async function loadAtlasFiles() {
  atlasLoading.value = true
  try {
    const { data } = await listAtlasFiles()
    atlasFiles.value = data
  } catch (e) {
    ElMessage.error('加载知识文档列表失败')
  } finally {
    atlasLoading.value = false
  }
}

async function handleAtlasFileChange(uploadFile) {
  if (!uploadFile?.raw) return
  try {
    await uploadAtlasFile(uploadFile.raw)
    ElMessage.success(`上传成功: ${uploadFile.name}`)
    loadAtlasFiles()
  } catch (e) {
    const msg = e.response?.data?.detail || '上传失败'
    ElMessage.error(msg)
  }
}

async function handleDeleteAtlas(name) {
  try {
    await deleteAtlasFile(name)
    ElMessage.success('已删除')
    loadAtlasFiles()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

let atlasReindexTimer = null

async function handleAtlasReindex() {
  atlasReindexLoading.value = true
  try {
    await reindexAtlas()
    pollAtlasReindex()
  } catch (e) {
    const msg = e.response?.data?.detail || '启动重建失败'
    ElMessage.error(msg)
    atlasReindexLoading.value = false
  }
}

function pollAtlasReindex() {
  if (atlasReindexTimer) clearInterval(atlasReindexTimer)
  atlasReindexTimer = setInterval(async () => {
    try {
      const { data } = await getAtlasReindexStatus()
      atlasReindexStatus.value = data
      if (data.status === 'done') {
        clearInterval(atlasReindexTimer)
        atlasReindexTimer = null
        atlasReindexLoading.value = false
        ElMessage.success('图集索引重建完成')
      } else if (data.status === 'error') {
        clearInterval(atlasReindexTimer)
        atlasReindexTimer = null
        atlasReindexLoading.value = false
        ElMessage.error(`索引重建失败: ${data.message}`)
      }
    } catch {
      clearInterval(atlasReindexTimer)
      atlasReindexTimer = null
      atlasReindexLoading.value = false
    }
  }, 2000)
}

// ── Corpus Files ────────────────────────────────────
async function loadCorpusFiles() {
  corpusLoading.value = true
  try {
    const { data } = await listCorpusFiles()
    corpusFiles.value = data
  } catch (e) {
    ElMessage.error('加载范文语料列表失败')
  } finally {
    corpusLoading.value = false
  }
}

async function handleCorpusFileChange(uploadFile) {
  if (!uploadFile?.raw) return
  try {
    await uploadCorpusFile(uploadFile.raw)
    ElMessage.success(`上传成功: ${uploadFile.name}`)
    loadCorpusFiles()
  } catch (e) {
    const msg = e.response?.data?.detail || '上传失败'
    ElMessage.error(msg)
  }
}

async function handleDeleteCorpus(name) {
  try {
    await deleteCorpusFile(name)
    ElMessage.success('已删除')
    loadCorpusFiles()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

let corpusReindexTimer = null

async function handleCorpusReindex() {
  corpusReindexLoading.value = true
  try {
    await reindexCorpus()
    pollCorpusReindex()
  } catch (e) {
    const msg = e.response?.data?.detail || '启动重建失败'
    ElMessage.error(msg)
    corpusReindexLoading.value = false
  }
}

function pollCorpusReindex() {
  if (corpusReindexTimer) clearInterval(corpusReindexTimer)
  corpusReindexTimer = setInterval(async () => {
    try {
      const { data } = await getCorpusReindexStatus()
      corpusReindexStatus.value = data
      if (data.status === 'done') {
        clearInterval(corpusReindexTimer)
        corpusReindexTimer = null
        corpusReindexLoading.value = false
        ElMessage.success('范文语料索引重建完成')
      } else if (data.status === 'error') {
        clearInterval(corpusReindexTimer)
        corpusReindexTimer = null
        corpusReindexLoading.value = false
        ElMessage.error(`索引重建失败: ${data.message}`)
      }
    } catch {
      clearInterval(corpusReindexTimer)
      corpusReindexTimer = null
      corpusReindexLoading.value = false
    }
  }, 2000)
}

// ── Lifecycle ───────────────────────────────────────
onMounted(() => {
  loadConfigFiles()
  loadAtlasFiles()
  loadCorpusFiles()
})
</script>
