<template>
  <div style="height: 100vh; display: flex; flex-direction: column; background: #fff">
    <!-- 顶部三步引导 -->
    <div style="padding: 16px 40px; border-bottom: 1px solid #e4e7ed; background: #fff">
      <el-steps :active="2" finish-status="success" align-center>
        <el-step title="项目信息填报" />
        <el-step title="报告辅助生成" />
        <el-step title="报告预览导出" />
      </el-steps>
    </div>

    <!-- 主内容区: 左侧章节树 + 右侧内容预览 -->
    <div style="flex: 1; display: flex; overflow: hidden">

      <!-- 左侧: 章节大纲 -->
      <div style="width: 260px; border-right: 1px solid #e4e7ed; overflow-y: auto; background: #fafbfc; padding: 12px 0">
        <div style="padding: 8px 16px; font-size: 14px; font-weight: bold; color: #303133">
          页面大纲
        </div>
        <el-tree
          :data="treeData"
          :props="{ label: 'label', children: 'children' }"
          :default-expand-all="true"
          :highlight-current="true"
          node-key="id"
          :current-node-key="selectedSection"
          @node-click="onTreeClick"
          style="background: transparent"
        />

        <!-- 审计信息 -->
        <div v-if="audit" style="padding: 16px; border-top: 1px solid #e4e7ed; margin-top: 12px">
          <div style="font-size: 13px; color: #909399; margin-bottom: 8px">审计总分</div>
          <div style="font-size: 28px; font-weight: bold; text-align: center"
            :style="{ color: (audit.final_score || 0) >= 80 ? '#67c23a' : '#e6a23c' }">
            {{ audit.final_score || 0 }}
          </div>
          <div v-if="audit.needs_human_review"
            style="text-align: center; margin-top: 4px; color: #e6a23c; font-size: 12px">
            需人工复核
          </div>
        </div>
      </div>

      <!-- 右侧: 内容预览 -->
      <div ref="contentArea" style="flex: 1; overflow-y: auto; padding: 32px 48px"
        v-loading="loading">

        <div v-if="!loading && chapters.length > 0">
          <div v-for="chapter in chapters" :key="chapter.id">
            <h2 :id="`ch-${chapter.id}`" style="margin-top: 32px; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid #409eff; color: #303133">
              {{ chapterTitle(chapter) }}
            </h2>
            <div v-for="section in chapter.sections" :key="section.tag">
              <h3 :id="`sec-${section.tag}`" style="margin-top: 20px; margin-bottom: 8px; color: #606266">
                {{ section.label }}
              </h3>
              <div style="line-height: 1.8; color: #303133; text-indent: 2em; text-align: justify; white-space: pre-wrap; font-size: 14px">{{ section.text || '(暂无内容)' }}</div>
            </div>
          </div>
        </div>

        <el-empty v-if="!loading && chapters.length === 0" description="暂无章节内容" />
      </div>
    </div>

    <!-- 底部操作栏 -->
    <div style="padding: 12px 40px; border-top: 1px solid #e4e7ed; background: #fff; display: flex; justify-content: space-between; align-items: center">
      <div style="color: #909399; font-size: 13px">
        共 {{ totalChars }} 个字
      </div>
      <div>
        <el-button @click="$router.push('/new')">重新生成</el-button>
        <el-button @click="download('draft')">下载初稿</el-button>
        <el-button type="primary" @click="download('result')">报告导出</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getRun, getAudit, getChapters, downloadResult, downloadDraft } from '../api/index.js'
import { ElMessage } from 'element-plus'

const props = defineProps({ id: String })

const loading = ref(true)
const run = ref(null)
const audit = ref(null)
const chapters = ref([])
const selectedSection = ref(null)

const CHAPTER_NUMBERS = { chapter1: '一', chapter2: '二', chapter3: '三', chapter4: '四', chapter5: '五', chapter6: '六', chapter7: '七', chapter8: '八' }

function chapterTitle(ch) {
  const n = CHAPTER_NUMBERS[ch.id] || ''
  return n ? `（${n}）${ch.name}` : ch.name
}

// 树形数据
const treeData = computed(() => {
  return chapters.value.map(ch => ({
    id: ch.id,
    label: chapterTitle(ch),
    children: ch.sections.map((s, i) => ({
      id: s.tag,
      label: `(${i + 1}) ${s.label}`,
    })),
  }))
})

const totalChars = computed(() => {
  let n = 0
  for (const ch of chapters.value) {
    for (const s of ch.sections) {
      n += (s.text || '').length
    }
  }
  return n
})

function onTreeClick(node) {
  selectedSection.value = node.id
  const isChapter = node.id.startsWith('chapter') && !node.id.includes('_')
  const elId = isChapter ? `ch-${node.id}` : `sec-${node.id}`
  const el = document.getElementById(elId)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function download(type) {
  const url = type === 'result' ? downloadResult(props.id) : downloadDraft(props.id)
  window.open(url, '_blank')
}

onMounted(async () => {
  try {
    const [runRes, chaptersRes] = await Promise.all([
      getRun(props.id),
      getChapters(props.id),
    ])
    run.value = runRes.data
    chapters.value = chaptersRes.data
    // 尝试加载审计
    try {
      const auditRes = await getAudit(props.id)
      audit.value = auditRes.data
    } catch { /* audit optional */ }
  } catch (e) {
    ElMessage.error('加载报告内容失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
})
</script>
