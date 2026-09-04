<template>
  <div class="dashboard-layout">
    <el-container>
      <el-aside width="200px" class="sidebar">
        <div class="logo"><h2>📊 META_ADS</h2></div>
        <el-menu :default-active="activeMenu" @select="handleMenuSelect" router>
          <el-menu-item index="overview"><el-icon><DocumentCopy /></el-icon><span>仪表板</span></el-menu-item>
          <el-menu-item index="campaigns"><el-icon><Promotion /></el-icon><span>广告系列</span></el-menu-item>
          <el-menu-item index="templates"><el-icon><Collection /></el-icon><span>投放模板</span></el-menu-item>
          <el-menu-item index="batch-publish"><el-icon><Upload /></el-icon><span>批量投放</span></el-menu-item>
          <el-menu-item index="jobs"><el-icon><List /></el-icon><span>任务中心</span></el-menu-item>
          <el-menu-item index="material"><el-icon><Picture /></el-icon><span>素材库</span></el-menu-item>
          <el-menu-item index="scheduled-tasks"><el-icon><Timer /></el-icon><span>定时任务</span></el-menu-item>
          <el-menu-item index="reports"><el-icon><PieChart /></el-icon><span>报表分析</span></el-menu-item>
          <el-menu-item index="risk-control"><el-icon><Warning /></el-icon><span>风险控制</span></el-menu-item>
          <el-divider />
          <el-menu-item index="accounts"><el-icon><OfficeBuilding /></el-icon><span>BM / 广告账户</span></el-menu-item>
          <el-menu-item index="settings"><el-icon><Setting /></el-icon><span>设置</span></el-menu-item>
        </el-menu>
      </el-aside>

      <el-container>
        <el-header class="header">
          <div class="header-left">
            <el-select v-model="accountStore.selectedAccountId" placeholder="选择广告账户" @change="handleAccountChange" class="account-selector" clearable>
              <el-option v-for="account in accountStore.accounts" :key="account.id" :label="account.account_name" :value="account.id" />
            </el-select>
            <el-breadcrumb v-if="route.path === '/dashboard/accounts'" separator="/" class="breadcrumb">
              <el-breadcrumb-item>账号中心</el-breadcrumb-item>
              <el-breadcrumb-item>Meta</el-breadcrumb-item>
              <el-breadcrumb-item>BM / 广告账户</el-breadcrumb-item>
            </el-breadcrumb>
          </div>

          <div class="header-right">
            <el-badge :value="notificationCount" class="notification-badge">
              <el-button text @click="showNotifications"><el-icon><Bell /></el-icon></el-button>
            </el-badge>
            <el-popover placement="bottom" trigger="click" width="250">
              <template #reference>
                <div class="user-info">
                  <el-avatar :size="32" :src="userStore.user?.settings?.avatar" />
                  <span>{{ userStore.user?.username }}</span>
                  <el-icon><ArrowDown /></el-icon>
                </div>
              </template>
              <div class="dropdown-menu">
                <div class="menu-item" @click="goToSettings"><el-icon><Setting /></el-icon><span>用户设置</span></div>
                <el-divider style="margin: 10px 0" />
                <div class="menu-item" @click="handleLogout"><el-icon><Switch /></el-icon><span>登出</span></div>
              </div>
            </el-popover>
          </div>
        </el-header>

        <el-main class="main-content">
          <router-view v-slot="{ Component }"><keep-alive><component :is="Component" /></keep-alive></router-view>
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/userStore'
import { useAccountStore } from '@/stores/accountStore'
import {
  DocumentCopy, Promotion, Collection, Upload, List, Picture, Timer,
  PieChart, Warning, OfficeBuilding, Setting, Switch, ArrowDown, Bell,
} from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const accountStore = useAccountStore()
const notificationCount = ref(0)

const activeMenu = computed(() => {
  const path = route.path.split('/').pop()
  return path || 'overview'
})

const handleMenuSelect = (key: string) => router.push(`/dashboard/${key}`)
const handleAccountChange = (accountId: string) => {
  if (accountId) {
    accountStore.selectAccount(accountId)
    ElMessage.success('广告账户已切换')
  }
}
const showNotifications = () => ElMessage.info('您没有新通知')
const goToSettings = () => router.push('/dashboard/settings')
const handleLogout = async () => {
  await userStore.logout()
  await router.push('/login')
  ElMessage.success('已登出')
}

onMounted(async () => {
  if (userStore.user && !accountStore.accounts.length) await accountStore.fetchAccounts(userStore.user.id)
})
</script>

<style scoped lang="scss">
.dashboard-layout { height: 100vh; display: flex; :deep(.el-container) { height: 100%; } }
.sidebar { background: #fff; border-right: 1px solid #e4e7eb; overflow-y: auto;
  .logo { padding: 16px 18px; border-bottom: 1px solid #e4e7eb; text-align: center; background: var(--primary-gradient); h2 { margin: 0; font-size: 15px; font-weight: 600; line-height: 1.2; color: #fff; letter-spacing: .5px; } }
  :deep(.el-menu) { border: none; padding: 8px; .el-menu-item { border-radius: 8px; margin-bottom: 4px; transition: all .2s; &:hover { background: #f5f7fa; } &.is-active { background: var(--primary-gradient) !important; color: #fff; box-shadow: 0 4px 12px rgba(59,130,246,.35); .el-icon { color: #fff; } } } }
}
.header { background: #fff; border-bottom: 1px solid #e4e7eb; box-shadow: 0 2px 8px rgba(0,0,0,.04); display: flex; justify-content: space-between; align-items: center; padding: 0 20px;
  .header-left { display: flex; align-items: center; gap: 20px; min-width: 0; .account-selector { width: 200px; } .breadcrumb { white-space: nowrap; } }
  .header-right { display: flex; align-items: center; gap: 18px; .notification-badge { cursor: pointer; } .user-info { display: flex; align-items: center; gap: 8px; cursor: pointer; padding: 5px 10px; border-radius: 6px; &:hover { background: #f5f7fa; } } }
}
.main-content { background: #f5f7fa; padding: 20px; overflow-y: auto; }
.dropdown-menu .menu-item { display: flex; align-items: center; gap: 10px; padding: 10px 15px; cursor: pointer; border-radius: 4px; &:hover { background: #f5f7fa; } }
@media (max-width: 900px) { .breadcrumb { display: none; } .header-left .account-selector { width: 160px !important; } }
</style>
