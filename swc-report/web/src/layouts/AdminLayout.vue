<template>
  <el-container style="min-height: 100vh">
    <!-- 左侧导航 — 深紫色调区分前台 -->
    <el-aside :width="collapsed ? '64px' : '220px'" class="admin-aside">
      <div class="admin-logo">
        <h1 v-if="!collapsed">后台管理</h1>
        <span v-else style="color: #fff; font-size: 16px; font-weight: bold">Admin</span>
      </div>

      <el-menu
        :router="true"
        :default-active="activeMenu"
        :collapse="collapsed"
        background-color="#2b1e3d"
        text-color="#b8a9cc"
        active-text-color="#fff"
        style="border: none"
      >
        <el-menu-item index="/admin/knowledge">
          <el-icon><Collection /></el-icon>
          <template #title>知识库管理</template>
        </el-menu-item>

        <el-divider style="border-color: #3d2e55; margin: 12px 0" />

        <el-menu-item index="/" class="back-link">
          <el-icon><Back /></el-icon>
          <template #title>返回前台</template>
        </el-menu-item>
      </el-menu>

      <div class="collapse-btn">
        <el-button link style="color: #b8a9cc" @click="collapsed = !collapsed">
          <el-icon :size="18"><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
        </el-button>
      </div>
    </el-aside>

    <!-- 右侧主内容 -->
    <el-container>
      <el-header class="admin-header">
        <span style="font-size: 14px; color: #666">后台管理系统</span>
      </el-header>
      <el-main style="background: #f5f5f5; padding: 0; overflow: hidden">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { Collection, Back, Fold, Expand } from '@element-plus/icons-vue'

const route = useRoute()
const collapsed = ref(false)
const activeMenu = computed(() => route.path)
</script>

<style scoped>
.admin-aside {
  background: #2b1e3d;
  position: relative;
  overflow: hidden;
  transition: width 0.3s;
}
.admin-logo {
  padding: 16px 12px;
  text-align: center;
  border-bottom: 1px solid #3d2e55;
}
.admin-logo h1 {
  color: #e0d4f0;
  font-size: 16px;
  margin: 0;
  line-height: 1.4;
  letter-spacing: 2px;
}
.collapse-btn {
  position: absolute;
  bottom: 12px;
  width: 100%;
  text-align: center;
}
.admin-header {
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  height: 48px;
  padding: 0 20px;
}
.back-link {
  opacity: 0.7;
}
.back-link:hover {
  opacity: 1;
}
</style>
