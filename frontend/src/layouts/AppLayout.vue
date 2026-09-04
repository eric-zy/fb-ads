<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">FA</div>
        <div>
          <h1>Flow Ads</h1>
          <p>Multi-tenant growth ops</p>
        </div>
      </div>

      <el-scrollbar class="nav-scroll">
        <div class="nav-groups">
          <section v-for="section in navigationSections" :key="section.key" class="nav-section">
            <div class="section-title">
              <el-icon><component :is="section.icon" /></el-icon>
              <span>{{ section.label }}</span>
            </div>

            <router-link
              v-for="item in section.items"
              :key="item.key"
              :to="item.route"
              class="nav-item"
              :class="{ active: isRouteActive(item.route) }"
            >
              <span>{{ item.label }}</span>
              <el-tag v-if="item.badge" size="small" effect="plain">{{ item.badge }}</el-tag>
            </router-link>
          </section>
        </div>
      </el-scrollbar>

      <div class="sidebar-footer">
        <div class="footer-label">平台扩展位</div>
        <div class="platform-pills">
          <button
            v-for="platform in PLATFORMS"
            :key="platform.key"
            type="button"
            class="platform-pill"
            :class="{ active: activePlatform === platform.key, disabled: !platform.enabled }"
            @click="onPlatformClick(platform)"
          >
            <span>{{ platform.emoji }}</span>
            <span>{{ platform.short }}</span>
          </button>
        </div>
      </div>
    </aside>

    <div class="workspace-shell">
      <header class="topbar">
        <div class="topbar-left">
          <el-select
            v-model="workspaceStore.activeWorkspaceId"
            class="workspace-switcher"
            placeholder="选择工作空间"
            @change="workspaceStore.setWorkspace"
          >
            <el-option
              v-for="space in workspaceStore.workspaceOptions"
              :key="space.id"
              :label="space.name"
              :value="space.id"
            >
              <div class="workspace-option">
                <span>{{ space.name }}</span>
                <small>{{ space.roleLabel }}</small>
              </div>
            </el-option>
          </el-select>

          <div class="context-chip">
            <span class="label">当前平台</span>
            <strong>{{ currentPlatform?.name || 'META_ADS' }}</strong>
          </div>

          <div class="context-chip account-chip">
            <span class="label">投放账户</span>
            <el-select
              v-model="accountStore.selectedAccountId"
              placeholder="选择广告账户"
              filterable
              clearable
              @change="handleAccountChange"
            >
              <el-option
                v-for="account in accountStore.accounts"
                :key="account.id"
                :label="account.account_name || account.account_id"
                :value="account.id"
              />
            </el-select>
          </div>
        </div>

        <div class="topbar-right">
          <el-button text @click="showHelp">帮助</el-button>
          <el-badge :value="notificationCount" :hidden="notificationCount === 0">
            <el-button circle plain @click="showNotifications">
              <el-icon><Bell /></el-icon>
            </el-button>
          </el-badge>

          <el-dropdown trigger="click">
            <div class="user-panel">
              <el-avatar :size="34">{{ userInitial }}</el-avatar>
              <div>
                <div class="user-name">{{ userStore.user?.username || '未登录' }}</div>
                <div class="user-role">{{ roleLabel }}</div>
              </div>
              <el-icon><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="router.push('/app/system/settings')">系统设置</el-dropdown-item>
                <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="content-shell">
        <section class="page-header">
          <div>
            <div class="page-eyebrow">{{ activeWorkspaceName }}</div>
            <h2>{{ pageTitle }}</h2>
            <p>{{ pageDescription }}</p>
          </div>

          <div class="page-meta">
            <el-tag round effect="plain">{{ roleLabel }}</el-tag>
            <el-tag round effect="plain" type="info">{{ routeSectionLabel }}</el-tag>
          </div>
        </section>

        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowDown, Bell } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/userStore'
import { useAccountStore } from '@/stores/accountStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { APP_NAVIGATION, canAccessNavItem } from '@/constants/navigation'
import { DEFAULT_PLATFORM, getPlatform, PLATFORMS, type PlatformConfig } from '@/config/platforms'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const accountStore = useAccountStore()
const workspaceStore = useWorkspaceStore()

const notificationCount = ref(2)
const activePlatform = ref(DEFAULT_PLATFORM)

const navigationSections = computed(() => {
  return APP_NAVIGATION
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => canAccessNavItem(item, userStore.user?.role || null)),
    }))
    .filter((section) => section.items.length > 0)
})

const flatNavigationItems = computed(() => navigationSections.value.flatMap((section) => section.items))

const currentNavItem = computed(() => {
  return flatNavigationItems.value.find((item) => route.path.startsWith(item.route)) || flatNavigationItems.value[0] || null
})

const pageTitle = computed(() => {
  return (route.meta.title as string) || currentNavItem.value?.label || '工作台'
})

const pageDescription = computed(() => {
  return (route.meta.description as string) || '围绕多租户、权限、账户树、报表和风控设计的统一运营工作台。'
})

const routeSectionLabel = computed(() => {
  return navigationSections.value.find((section) => section.items.some((item) => route.path.startsWith(item.route)))?.label || '工作台'
})

const currentPlatform = computed(() => getPlatform(activePlatform.value))

const activeWorkspaceName = computed(() => workspaceStore.activeWorkspace?.name || '默认工作空间')

const roleLabel = computed(() => {
  if (userStore.user?.role === 'admin') return '系统管理员'
  if (userStore.user?.role === 'manager') return '运营经理'
  return '投放成员'
})

const userInitial = computed(() => {
  return userStore.user?.username?.slice(0, 1)?.toUpperCase() || 'U'
})

function isRouteActive(targetRoute: string): boolean {
  return route.path === targetRoute || route.path.startsWith(`${targetRoute}/`)
}

function onPlatformClick(platform: PlatformConfig) {
  if (!platform.enabled) {
    ElMessage.info(`${platform.name} 入口已预留，后续可直接挂接新平台`)
    return
  }
  activePlatform.value = platform.key
  ElMessage.success(`已切换到 ${platform.name}`)
}

function handleAccountChange(accountId: string) {
  if (!accountId) return
  accountStore.selectAccount(accountId)
}

function showNotifications() {
  ElMessage.info('已为你保留通知入口，后续可接风控告警和任务提醒。')
}

function showHelp() {
  ElMessage.info('当前结构已经为多租户、RBAC、多平台扩展预留。')
}

async function handleLogout() {
  await userStore.logout()
  router.push('/login')
}

onMounted(async () => {
  workspaceStore.initWorkspace()
  if (userStore.user && !accountStore.accounts.length) {
    await accountStore.fetchAccounts(userStore.user.id)
    accountStore.restoreSelectedAccount()
  }
})
</script>

<style scoped lang="scss">
.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  background: #edf2f7;
}

.sidebar {
  display: flex;
  flex-direction: column;
  padding: 22px 18px 18px;
  background:
    radial-gradient(circle at top, rgba(60, 111, 180, 0.18), transparent 28%),
    linear-gradient(180deg, #0d1b2a 0%, #13263b 38%, #16293e 100%);
  color: #dfe9f5;
  border-right: 1px solid rgba(255, 255, 255, 0.05);

  .brand {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 8px 8px 20px;

    .brand-mark {
      width: 46px;
      height: 46px;
      border-radius: 14px;
      display: grid;
      place-items: center;
      background: linear-gradient(135deg, #4ea1ff 0%, #7ec8ff 100%);
      color: #09233c;
      font-weight: 800;
    }

    h1 {
      margin: 0;
      font-size: 20px;
      color: #f7fbff;
    }

    p {
      margin: 4px 0 0;
      font-size: 12px;
      color: #98b3cc;
    }
  }

  .nav-scroll {
    flex: 1;
    min-height: 0;
  }

  .nav-groups {
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 6px 4px;
  }

  .nav-section {
    .section-title {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 0 10px 8px;
      color: #8ea8c3;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .nav-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 4px;
      padding: 11px 12px;
      border-radius: 12px;
      color: #d6e4f4;
      text-decoration: none;
      transition: 0.2s ease;

      &:hover {
        background: rgba(126, 172, 225, 0.1);
      }

      &.active {
        background: linear-gradient(135deg, rgba(92, 172, 255, 0.3), rgba(34, 103, 181, 0.55));
        box-shadow: inset 0 0 0 1px rgba(144, 206, 255, 0.22);
      }
    }
  }

  .sidebar-footer {
    padding: 14px 8px 0;

    .footer-label {
      margin-bottom: 10px;
      color: #8ea8c3;
      font-size: 12px;
    }

    .platform-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .platform-pill {
      border: 1px solid rgba(154, 187, 219, 0.16);
      background: rgba(255, 255, 255, 0.04);
      color: #d6e4f4;
      border-radius: 999px;
      padding: 8px 12px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;

      &.active {
        background: rgba(98, 176, 255, 0.18);
        border-color: rgba(98, 176, 255, 0.38);
      }

      &.disabled {
        opacity: 0.55;
      }
    }
  }
}

.workspace-shell {
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 18px 24px;
  background: rgba(248, 251, 255, 0.88);
  backdrop-filter: blur(18px);
  border-bottom: 1px solid rgba(16, 35, 58, 0.08);

  .topbar-left,
  .topbar-right {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
  }

  .workspace-switcher {
    width: 220px;
  }

  .workspace-option {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    width: 100%;

    small {
      color: #7a8796;
    }
  }

  .context-chip {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border-radius: 999px;
    background: #fff;
    border: 1px solid rgba(16, 35, 58, 0.08);

    .label {
      color: #72849a;
      font-size: 12px;
    }

    strong {
      color: #11263d;
      font-size: 13px;
    }
  }

  .account-chip :deep(.el-select) {
    width: 220px;
  }

  .user-panel {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 10px;
    border-radius: 14px;
    cursor: pointer;
    background: #fff;
    border: 1px solid rgba(16, 35, 58, 0.08);

    .user-name {
      color: #11263d;
      font-size: 13px;
      font-weight: 600;
    }

    .user-role {
      color: #72849a;
      font-size: 12px;
    }
  }
}

.content-shell {
  padding: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;

  .page-eyebrow {
    color: #51708d;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  h2 {
    margin: 6px 0 8px;
    color: #10233a;
    font-size: 30px;
    line-height: 1.15;
  }

  p {
    margin: 0;
    color: #60758c;
    font-size: 14px;
  }

  .page-meta {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }
}

.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.page-fade-enter-from,
.page-fade-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

@media (max-width: 1100px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    display: none;
  }

  .topbar {
    flex-direction: column;
    align-items: stretch;
  }

  .page-header {
    flex-direction: column;
  }
}
</style>
