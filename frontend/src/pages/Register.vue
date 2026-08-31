<template>
  <div class="register-page">
    <el-card class="register-card">
      <template #header>
        <div class="card-header">
          <span>注册新账户</span>
        </div>
      </template>
      <el-alert type="info" :closable="false" title="注册功能开发中">
        <p>当前后端尚未开放注册接口（POST /api/v1/auth/register）。</p>
        <p>请使用已有账户登录，或联系管理员创建账户。</p>
      </el-alert>
      <el-button type="primary" class="back-btn" @click="goLogin">返回登录</el-button>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
const goLogin = () => router.push('/login')
</script>

<style scoped lang="scss">
.register-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #5aa9e6 0%, #7fc8f8 100%);

  .register-card {
    width: 420px;
    max-width: 90vw;
  }

  .back-btn {
    margin-top: 20px;
    width: 100%;
  }
}
</style>
