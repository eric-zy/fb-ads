<template>
  <div class="app">
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useUserStore } from '@/stores/userStore'
import { useAccountStore } from '@/stores/accountStore'

const userStore = useUserStore()
const accountStore = useAccountStore()

onMounted(() => {
  // 初始化认证状态
  userStore.initAuth()
  
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
