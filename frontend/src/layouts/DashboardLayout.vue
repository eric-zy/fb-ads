<template>
  <div class="dashboard-layout">
    <el-container>
      <!-- 侧边栏 -->
      <el-aside width="200px" class="sidebar">
        <div class="logo">
          <h2>📊 FBA</h2>
        </div>
        <el-menu
          :default-active="activeMenu"
          @select="handleMenuSelect"
          router
        >
          <el-menu-item index="overview">
            <el-icon><DocumentCopy /></el-icon>
            <span>仪表板</span>
          </el-menu-item>
          <el-menu-item index="campaigns">
            <el-icon><Promotion /></el-icon>
            <span>广告系列</span>
          </el-menu-item>
          <el-menu-item index="batch-publish">
            <el-icon><Rocket /></el-icon>
            <span>批量投放</span>
          </el-menu-item>
          <el-menu-item index="scheduled-tasks">
            <el-icon><Timer /></el-icon>
            <span>定时任务</span>
          </el-menu-item>
          <el-menu-item index="reports">
            <el-icon><PieChart /></el-icon>
            <span>报表分析</span>
          </el-menu-item>
          <el-menu-item index="risk-control">
            <el-icon><Warning /></el-icon>
            <span>风险控制</span>
          </el-menu-item>
          <el-divider />
          <el-menu-item index="accounts">
            <el-icon><User /></el-icon>
            <span>账户管理</span>
          </el-menu-item>
          <el-menu-item index="settings">
            <el-icon><Setting /></el-icon>
            <span>设置</span>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <el-container>
        <!-- 顶部栏 -->
        <el-header class="header">
          <div class="header-left">
            <!-- 账户选择器 -->
            <el-select
              v-model="accountStore.selectedAccountId"
              placeholder="选择账户"
              @change="handleAccountChange"
              class="account-selector"
            >
              <el-option
                v-for="account in accountStore.accounts"
                :key="account.id"
                :label="account.account_name"
                :value="account.id"
              />
            </el-select>
          </div>

          <div class="header-right">
            <el-badge
              :value="notificationCount"
              class="notification-badge"
            >
              <el-button
                type="text"
                @click="showNotifications"
                icon="Bell"
              />
            </el-badge>

            <el-popover
              placement="bottom"
              trigger="click"
              width="250"
            >
              <template #reference>
                <el-dropdown>
                  <div class="user-info">
                    <el-avatar
                      :size="32"
                      :src="userStore.user?.settings?.avatar"
                    />
                    <span>{{ userStore.user?.username }}</span>
                    <el-icon class="is-icon"><ArrowDown /></el-icon>
                  </div>
                </el-dropdown>
              </template>

              <div class="dropdown-menu">
                <div class="menu-item" @click="goToSettings">
                  <el-icon><Setting /></el-icon>
                  <span>用户设置</span>
                </div>
                <el-divider style="margin: 10px 0" />
                <div class="menu-item" @click="handleLogout">
                  <el-icon><Switch /></el-icon>
                  <span>登出</span>
                </div>
              </div>
            </el-popover>
          </div>
        </el-header>

        <!-- 主内容区域 -->
        <el-main class="main-content">
          <router-view v-slot="{ Component }">
            <keep-alive>
              <component :is="Component" />
            </keep-alive>
          </router-view>
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

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const accountStore = useAccountStore()

const notificationCount = ref(0)

const activeMenu = computed(() => {
  const path = route.path.split('/').pop()
  return path || 'overview'
})

const handleMenuSelect = (key: string) => {
  router.push(`/dashboard/${key}`)
}

const handleAccountChange = (accountId: string) => {
  accountStore.selectAccount(accountId)
  ElMessage.success('账户已切换')
}

const showNotifications = () => {
  ElMessage.info('您没有新通知')
}

const goToSettings = () => {
  router.push('/dashboard/settings')
}

const handleLogout = async () => {
  await userStore.logout()
  await router.push('/login')
  ElMessage.success('已登出')
}

onMounted(async () => {
  if (userStore.user && !accountStore.accounts.length) {
    await accountStore.fetchAccounts(userStore.user.id)
  }
})
</script>

<style scoped lang="scss">
.dashboard-layout {
  height: 100vh;
  display: flex;

  :deep(.el-container) {
    height: 100%;
  }

  .sidebar {
    background: #fff;
    border-right: 1px solid #e4e7eb;
    overflow-y: auto;

    .logo {
      padding: 20px;
      border-bottom: 1px solid #e4e7eb;
      text-align: center;

      h2 {
        margin: 0;
        font-size: 20px;
      }
    }

    :deep(.el-menu) {
      border: none;

      .el-menu-item {
        &:hover {
          background-color: #f5f7fa;
        }

        &.is-active {
          background-color: #667eea !important;
          color: white;

          .el-icon {
            color: white;
          }
        }
      }
    }
  }

  .header {
    background: white;
    border-bottom: 1px solid #e4e7eb;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 20px;

    .header-left {
      display: flex;
      align-items: center;
      gap: 20px;

      .account-selector {
        width: 200px;
      }
    }

    .header-right {
      display: flex;
      align-items: center;
      gap: 20px;

      .notification-badge {
        cursor: pointer;
      }

      .user-info {
        display: flex;
        align-items: center;
        gap: 10px;
        cursor: pointer;
        padding: 5px 10px;
        border-radius: 4px;
        transition: background-color 0.2s;

        &:hover {
          background-color: #f5f7fa;
        }
      }
    }
  }

  .main-content {
    background: #f5f7fa;
    padding: 20px;
    overflow-y: auto;
  }

  .dropdown-menu {
    .menu-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 15px;
      cursor: pointer;
      border-radius: 4px;
      transition: background-color 0.2s;

      &:hover {
        background-color: #f5f7fa;
      }
    }
  }
}
</style>
