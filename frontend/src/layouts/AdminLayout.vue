<template>
  <div class="admin-layout">
    <el-container>
      <el-aside width="200px" class="sidebar">
        <div class="logo">
          <h2>🛡️ 管理后台</h2>
        </div>
        <el-menu :default-active="activeMenu" router>
          <el-menu-item index="dashboard">
            <el-icon><DataLine /></el-icon>
            <span>仪表板</span>
          </el-menu-item>
          <el-menu-item index="users">
            <el-icon><User /></el-icon>
            <span>用户管理</span>
          </el-menu-item>
          <el-divider />
          <el-menu-item index="meta-accounts">
            <el-icon><OfficeBuilding /></el-icon>
            <span>主账号管理</span>
          </el-menu-item>
          <el-menu-item index="credentials">
            <el-icon><Key /></el-icon>
            <span>凭据管理</span>
          </el-menu-item>
          <el-menu-item index="accounts">
            <el-icon><Postcard /></el-icon>
            <span>广告账户</span>
          </el-menu-item>
          <el-divider />
          <el-menu-item index="overview" @click="goDashboard">
            <el-icon><Back /></el-icon>
            <span>返回用户端</span>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <el-container>
        <el-header class="header">
          <span class="title">管理员控制台</span>
          <el-dropdown>
            <div class="user-info">
              <el-avatar :size="32">{{ userStore.user?.username?.[0] || 'A' }}</el-avatar>
              <span>{{ userStore.user?.username }}</span>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="handleLogout">登出</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </el-header>

        <el-main class="main-content">
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
// 图标不走 unplugin-vue-components 的自动注册（components.d.ts 只含 El* 组件），
// 必须显式导入，否则运行时会渲染成空标签
import { DataLine, User, Postcard, OfficeBuilding, Key, Back } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/userStore'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const activeMenu = computed(() => route.path.split('/').pop() || 'dashboard')

// 侧边栏由 el-menu 的 router 模式按 index 自动跳转；
// 「返回用户端」对应 /admin/overview 路由，已配置重定向到用户端首页
const handleLogout = async () => {
  await userStore.logout()
  await router.push('/login')
  ElMessage.success('已登出')
}
</script>

<style scoped lang="scss">
.admin-layout {
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
      padding: 22px 20px;
      border-bottom: 1px solid #e4e7eb;
      text-align: center;
      background: var(--primary-gradient);

      h2 {
        margin: 0;
        font-size: 18px;
        color: #fff;
        letter-spacing: 1px;
      }
    }

    :deep(.el-menu) {
      border: none;
      padding: 8px;

      .el-menu-item {
        border-radius: 8px;
        margin-bottom: 4px;
        transition: all 0.2s;

        &:hover {
          background-color: #f5f7fa;
        }

        &.is-active {
          background: var(--primary-gradient) !important;
          color: white;
          box-shadow: 0 4px 12px rgba(90, 169, 230, 0.35);

          .el-icon {
            color: white;
          }
        }
      }
    }
  }

  .header {
    background: #fff;
    border-bottom: 1px solid #e4e7eb;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 20px;

    .title {
      font-weight: 600;
    }

    .user-info {
      display: flex;
      align-items: center;
      gap: 10px;
      cursor: pointer;
      padding: 5px 10px;
      border-radius: 8px;
      transition: background-color 0.2s;

      &:hover {
        background-color: #f5f7fa;
      }
    }
  }

  .main-content {
    background: #f5f7fa;
    padding: 20px;
    overflow-y: auto;
  }
}
</style>
