<template>
  <div style="height: 100vh; display: flex; flex-direction: column; background: #fff">
    <!-- 顶部三步引导 -->
    <div style="padding: 16px 40px; border-bottom: 1px solid #e4e7ed; background: #fff">
      <el-steps :active="1" finish-status="success" align-center>
        <el-step title="项目信息填报" />
        <el-step title="报告辅助生成" />
        <el-step title="报告预览导出" />
      </el-steps>
    </div>

    <div style="flex: 1; overflow-y: auto; padding: 24px 40px">
      <div style="max-width: 900px; margin: 0 auto">
        <run-progress-inner :run-id="id" @done="onDone" @error="onError" />
      </div>

      <div v-if="finished" style="text-align: center; margin-top: 24px">
        <el-result v-if="finishStatus === 'done'" icon="success" title="报告生成完成">
          <template #extra>
            <el-button type="primary" @click="$router.push(`/result/${id}`)">查看报告预览</el-button>
          </template>
        </el-result>
        <el-result v-else icon="error" title="生成失败">
          <template #extra>
            <el-button @click="$router.push('/new')">重新生成</el-button>
            <el-button @click="$router.push('/')">返回列表</el-button>
          </template>
        </el-result>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import RunProgressInner from '../components/RunProgressInner.vue'

const props = defineProps({ id: String })
const finished = ref(false)
const finishStatus = ref('')

function onDone() { finished.value = true; finishStatus.value = 'done' }
function onError() { finished.value = true; finishStatus.value = 'error' }
</script>
