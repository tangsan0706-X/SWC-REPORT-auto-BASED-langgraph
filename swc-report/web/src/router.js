import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  // ── 前台 (用户界面) ──────────────────────────────
  { path: '/', name: 'Dashboard', component: () => import('./views/Dashboard.vue') },
  { path: '/new', name: 'NewRun', component: () => import('./views/NewRun.vue') },
  { path: '/run/:id', name: 'RunProgress', component: () => import('./views/RunProgress.vue'), props: true },
  { path: '/result/:id', name: 'Result', component: () => import('./views/Result.vue'), props: true },
  { path: '/settings', name: 'Settings', component: () => import('./views/Settings.vue') },

  // ── 后台 (管理界面) ──────────────────────────────
  {
    path: '/admin',
    component: () => import('./layouts/AdminLayout.vue'),
    children: [
      { path: '', redirect: '/admin/knowledge' },
      { path: 'knowledge', name: 'KnowledgeBase', component: () => import('./views/KnowledgeBase.vue') },
    ],
  },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
