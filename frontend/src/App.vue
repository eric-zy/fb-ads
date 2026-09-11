<template>
  <el-config-provider :locale="zhCn">
    <div class="app">
      <router-view />
    </div>
  </el-config-provider>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useUserStore } from '@/stores/userStore'
import { useAccountStore } from '@/stores/accountStore'

const userStore = useUserStore()
const accountStore = useAccountStore()

onMounted(async () => {
  // 初始化认证状态
  userStore.initAuth()

  // 每次启动刷新角色模板和有效权限，避免使用旧的本地权限缓存。
  if (userStore.isAuthenticated) await userStore.refreshProfile()
  
  // 如果用户已登录，加载账户列表
  if (userStore.user) {
    accountStore.fetchAccounts(userStore.user.id)
    accountStore.restoreSelectedAccount()
  }
})
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue',
    Arial, sans-serif;
  color: #333;
  background-color: #f5f7fa;
}

.app {
  width: 100%;
  min-height: 100vh;
}
</style>
