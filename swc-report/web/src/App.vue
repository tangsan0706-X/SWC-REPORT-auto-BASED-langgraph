<template>
  <el-container style="min-height: 100vh">
    <!-- 左侧导航 -->
    <el-aside :width="sidebarCollapsed ? '64px' : '200px'" style="background: #1a3353; transition: width 0.3s">
      <div style="padding: 16px 12px; text-align: center; border-bottom: 1px solid #2a4a6b">
        <h1 v-if="!sidebarCollapsed" style="color: #fff; font-size: 15px; margin: 0; line-height: 1.4">
          AI水保助手
        </h1>
        <span v-else style="color: #fff; font-size: 18px; font-weight: bold">AI</span>
      </div>
      <el-menu
        :router="true"
        :default-active="activeMenu"
        :collapse="sidebarCollapsed"
        background-color="#1a3353"
        text-color="#8ba3c7"
        active-text-color="#fff"
        style="border: none"
      >
        <el-menu-item index="/new">
          <el-icon><EditPen /></el-icon>
          <template #title>报告表编写</template>
        </el-menu-item>
        <el-menu-item index="/">
          <el-icon><FolderOpened /></el-icon>
          <template #title>我的报告</template>
        </el-menu-item>
        <el-menu-item index="/knowledge">
          <el-icon><Collection /></el-icon>
          <template #title>知识库管理</template>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <template #title>系统设置</template>
        </el-menu-item>
      </el-menu>
      <div style="position: absolute; bottom: 12px; width: 100%; text-align: center">
        <el-button link style="color: #8ba3c7" @click="sidebarCollapsed = !sidebarCollapsed">
          <el-icon :size="18"><Fold v-if="!sidebarCollapsed" /><Expand v-else /></el-icon>
        </el-button>
      </div>
    </el-aside>

    <!-- 右侧主内容 -->
    <el-container>
      <el-main style="background: #f0f2f5; padding: 0; overflow: hidden">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { EditPen, FolderOpened, Setting, Fold, Expand, Collection } from '@element-plus/icons-vue'

const route = useRoute()
const sidebarCollapsed = ref(false)
const activeMenu = computed(() => {
  const p = route.path
  if (p.startsWith('/run/') || p.startsWith('/result/') || p === '/new') return '/new'
  return p
})
</script>

<style>
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Microsoft YaHei', sans-serif; }
.el-aside { position: relative; overflow: hidden; }
.el-menu--collapse .el-menu-item { padding: 0 20px !important; }
.el-main { height: 100vh; }
</style>
