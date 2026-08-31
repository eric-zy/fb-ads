import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/userStore'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/pages/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/pages/Register.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/dashboard',
    component: () => import('@/layouts/DashboardLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: 'overview',
        name: 'Overview',
        component: () => import('@/pages/dashboard/Overview.vue'),
        meta: { title: '仪表板' },
      },
      {
        path: 'campaigns',
        name: 'Campaigns',
        component: () => import('@/pages/dashboard/Campaigns.vue'),
        meta: { title: '广告系列' },
      },
      {
        path: 'templates',
        name: 'Templates',
        component: () => import('@/pages/dashboard/Templates.vue'),
        meta: { title: '投放模板' },
      },
      {
        path: 'batch-publish',
        name: 'BatchPublish',
        component: () => import('@/pages/dashboard/BatchPublish.vue'),
        meta: { title: '批量投放' },
      },
      {
        path: 'jobs',
        name: 'Jobs',
        component: () => import('@/pages/dashboard/Jobs.vue'),
        meta: { title: '任务中心' },
      },
      {
        path: 'material',
        name: 'Material',
        component: () => import('@/pages/dashboard/Material.vue'),
        meta: { title: '素材库' },
      },
      {
        path: 'scheduled-tasks',
        name: 'ScheduledTasks',
        component: () => import('@/pages/dashboard/ScheduledTasks.vue'),
        meta: { title: '定时任务' },
      },
      {
        path: 'reports',
        name: 'Reports',
        component: () => import('@/pages/dashboard/Reports.vue'),
        meta: { title: '报表' },
      },
      {
        path: 'risk-control',
        name: 'RiskControl',
        component: () => import('@/pages/dashboard/RiskControl.vue'),
        meta: { title: '风险控制' },
      },
      {
        path: 'accounts',
        name: 'Accounts',
        component: () => import('@/pages/dashboard/Accounts.vue'),
        meta: { title: '账户管理' },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/pages/dashboard/Settings.vue'),
        meta: { title: '设置' },
      },
    ],
  },
  {
    path: '/admin',
    component: () => import('@/layouts/AdminLayout.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      {
        path: 'dashboard',
        name: 'AdminDashboard',
        component: () => import('@/pages/admin/Dashboard.vue'),
        meta: { title: '管理员仪表板' },
      },
      {
        path: 'users',
        name: 'AdminUsers',
        component: () => import('@/pages/admin/Users.vue'),
        meta: { title: '用户管理' },
      },
      {
        path: 'accounts',
        name: 'AdminAccounts',
        component: () => import('@/pages/admin/Accounts.vue'),
        meta: { title: '账户管理' },
      },
      {
        path: 'meta-accounts',
        name: 'AdminMetaAccounts',
        component: () => import('@/pages/admin/MetaAccounts.vue'),
        meta: { title: '主账号管理' },
      },
      {
        path: 'businesses/:id',
        name: 'AdminBusinessDetail',
        component: () => import('@/pages/admin/BusinessDetail.vue'),
        meta: { title: 'BM 详情' },
      },
      {
        path: 'credentials',
        name: 'AdminCredentials',
        component: () => import('@/pages/admin/Credentials.vue'),
        meta: { title: '凭据管理' },
      },
      // 侧边栏「返回用户端」的落点（el-menu 的 router 模式按 index 跳转）
      {
        path: 'overview',
        redirect: '/dashboard/overview',
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard/overview',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 导航守卫
router.beforeEach(async (to, from, next) => {
  const userStore = useUserStore()

  // 初始化认证状态
  if (!userStore.isAuthenticated && !userStore.user) {
    userStore.initAuth()
  }

  const requiresAuth = to.matched.some(record => record.meta.requiresAuth)
  const requiresAdmin = to.matched.some(record => record.meta.requiresAdmin)

  if (requiresAuth && !userStore.isAuthenticated) {
    next('/login')
  } else if (requiresAdmin && !userStore.isAdmin) {
    next('/dashboard/overview')
  } else {
    next()
  }
})

export default router
