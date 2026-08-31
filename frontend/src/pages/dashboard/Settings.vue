<template>
  <div class="settings">
    <h2>账户设置</h2>
    <p class="sub">配置通知偏好与界面语言</p>

    <div class="card">
      <h3>通知偏好</h3>
      <label class="switch">
        <input type="checkbox" v-model="settings.email_notifications" />
        邮件通知（账户异常 / 风险告警）
      </label>
      <label class="switch">
        <input type="checkbox" v-model="settings.daily_report" />
        每日数据报告
      </label>
      <label class="switch">
        <input type="checkbox" v-model="settings.risk_alert" />
        风险实时告警
      </label>

      <div class="field">
        <label>语言</label>
        <select v-model="settings.language" class="input">
          <option value="zh-CN">简体中文</option>
          <option value="en">English</option>
        </select>
      </div>

      <div class="actions">
        <button class="btn btn-primary" :disabled="saving" @click="save">保存设置</button>
        <span v-if="saved" class="ok">已保存 ✓</span>
      </div>
    </div>

    <div class="card">
      <h3>账户信息</h3>
      <div class="info-row"><span>用户名</span><b>{{ user?.username }}</b></div>
      <div class="info-row"><span>邮箱</span><b>{{ user?.email }}</b></div>
      <div class="info-row"><span>角色</span><b>{{ roleLabel(user?.role) }}</b></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useUserStore } from '../../stores/userStore'

const userStore = useUserStore()
const user = userStore.user

const settings = ref({
  email_notifications: true,
  daily_report: true,
  risk_alert: true,
  language: 'zh-CN',
})
const saving = ref(false)
const saved = ref(false)

function roleLabel(r?: string) {
  return { admin: '管理员', manager: '经理', user: '普通用户' }[r || ''] || r || '-'
}

onMounted(() => {
  const s = (userStore.user?.settings as Record<string, any>) || {}
  settings.value = { ...settings.value, ...s }
})

async function save() {
  saving.value = true
  saved.value = false
  try {
    await userStore.updateSettings({ ...settings.value })
    saved.value = true
    setTimeout(() => (saved.value = false), 2000)
  } catch (e: any) {
    alert('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.settings {
  padding: 24px;
  max-width: 640px;
  color: #1f2937;
}
.settings h2 {
  margin: 0;
  font-size: 20px;
}
.sub {
  color: #6b7280;
  font-size: 13px;
  margin-top: 4px;
}
.card {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  margin-top: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.card h3 {
  margin: 0 0 12px;
  font-size: 15px;
}
.switch {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  font-size: 14px;
  cursor: pointer;
}
.field {
  margin-top: 8px;
}
.field label {
  display: block;
  font-size: 13px;
  color: #4b5563;
  margin-bottom: 4px;
}
.input {
  padding: 8px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  min-width: 200px;
}
.input:focus {
  border-color: #4f46e5;
}
.actions {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.btn {
  padding: 8px 16px;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 6px;
  cursor: pointer;
}
.btn-primary {
  background: #4f46e5;
  color: #fff;
  border-color: #4f46e5;
}
.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.ok {
  color: #15803d;
  font-size: 13px;
}
.info-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #f3f4f6;
  font-size: 14px;
}
.info-row:last-child {
  border-bottom: none;
}
.info-row span {
  color: #6b7280;
}
</style>
