<template>
  <div class="login-container">
    <div class="login-box">
      <div class="login-header">
        <h1>Facebook 广告自动化平台</h1>
        <p>登录您的账户以继续</p>
      </div>

      <el-form
        ref="formRef"
        :model="loginForm"
        :rules="rules"
        @keyup.enter="handleLogin"
      >
        <el-form-item prop="email">
          <el-input
            v-model="loginForm.email"
            placeholder="请输入邮箱"
            prefix-icon="Message"
            clearable
          />
        </el-form-item>

        <el-form-item prop="password">
          <el-input
            v-model="loginForm.password"
            placeholder="请输入密码"
            type="password"
            prefix-icon="Lock"
            show-password
          />
        </el-form-item>

        <el-form-item>
          <el-checkbox v-model="loginForm.rememberMe">
            记住我
          </el-checkbox>
          <el-link type="primary" href="#">忘记密码?</el-link>
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            :loading="userStore.isLoading"
            @click="handleLogin"
            class="login-button"
          >
            登 录
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-footer">
        <p>
          没有账户?
          <el-link type="primary" @click="goToRegister">立即注册</el-link>
        </p>
      </div>

      <div v-if="userStore.user" class="demo-info">
        <el-alert
          title="演示账户"
          type="info"
          :closable="false"
          description="已使用演示账户自动登录"
        />
      </div>
    </div>

    <div class="login-side">
      <div class="features">
        <h2>主要功能</h2>
        <div class="feature-item">
          <i class="icon">📊</i>
          <h3>实时数据分析</h3>
          <p>获取广告实时效果数据和性能指标</p>
        </div>
        <div class="feature-item">
          <i class="icon">🚀</i>
          <h3>批量投放</h3>
          <p>支持多账户、批量创建和定时投放</p>
        </div>
        <div class="feature-item">
          <i class="icon">🛡️</i>
          <h3>风险控制</h3>
          <p>智能风险检测和自动化防护机制</p>
        </div>
        <div class="feature-item">
          <i class="icon">⏱️</i>
          <h3>定时任务</h3>
          <p>灵活配置定时投放和自动化工作流</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/userStore'
import type { FormInstance } from 'element-plus'

const router = useRouter()
const userStore = useUserStore()
const formRef = ref<FormInstance>()

const loginForm = reactive({
  email: 'demo@example.com',
  password: 'password123',
  rememberMe: true,
})

const rules = {
  email: [
    { required: true, message: '请输入邮箱地址', trigger: 'blur' },
    { type: 'email', message: '请输入正确的邮箱地址', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少6个字符', trigger: 'blur' },
  ],
}

const handleLogin = async () => {
  if (!formRef.value) return
  
  try {
    await formRef.value.validate()
    
    const success = await userStore.login(loginForm.email, loginForm.password)
    if (success) {
      ElMessage.success('登录成功')
      // 根据角色跳转
      if (userStore.isAdmin) {
        await router.push('/admin/dashboard')
      } else {
        await router.push('/dashboard/overview')
      }
    }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '登录失败')
  }
}

const goToRegister = () => {
  router.push('/register')
}
</script>

<style scoped lang="scss">
.login-container {
  display: flex;
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

  .login-box {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    padding: 40px;
    background: white;

    .login-header {
      text-align: center;
      margin-bottom: 40px;

      h1 {
        font-size: 28px;
        font-weight: 600;
        color: #333;
        margin-bottom: 10px;
      }

      p {
        color: #666;
        font-size: 14px;
      }
    }

    :deep(.el-form) {
      width: 100%;
      max-width: 350px;

      .el-form-item {
        margin-bottom: 22px;
      }

      .el-input__wrapper {
        background-color: #f5f7fa;
        border: none;
      }
    }

    .login-button {
      width: 100%;
      height: 40px;
      font-size: 16px;
      font-weight: 600;
    }

    .login-footer {
      text-align: center;
      margin-top: 30px;
      color: #666;

      .el-link {
        margin-left: 5px;
      }
    }

    .demo-info {
      width: 100%;
      max-width: 350px;
      margin-top: 20px;
    }
  }

  .login-side {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 40px;
    color: white;

    .features {
      max-width: 400px;

      h2 {
        font-size: 32px;
        font-weight: 600;
        margin-bottom: 40px;
      }

      .feature-item {
        margin-bottom: 30px;
        display: flex;
        gap: 15px;

        .icon {
          font-size: 30px;
          min-width: 40px;
        }

        h3 {
          font-size: 16px;
          font-weight: 600;
          margin-bottom: 8px;
        }

        p {
          font-size: 14px;
          opacity: 0.9;
          line-height: 1.5;
        }
      }
    }
  }

  @media (max-width: 768px) {
    flex-direction: column;

    .login-side {
      display: none;
    }
  }
}
</style>
