<template>
  <div class="page-container">
    <div class="page-head"><div><h2 class="page-title">司南分销平台</h2><p class="page-subtitle">配置司南账号，验证成功后开放司南推广链功能。</p></div></div>
    <el-alert v-if="notice" :title="notice" :type="noticeType" show-icon closable @close="notice=''" />
    <el-card shadow="never" class="card-shadow">
      <el-form :model="form" label-width="140px" style="max-width:680px">
        <el-form-item label="API 地址"><el-input v-model="form.base_url" /></el-form-item>
        <el-form-item label="App ID" required><el-input v-model="form.app_id" /></el-form-item>
        <el-form-item label="司南账号" required><el-input v-model="form.account" autocomplete="off" /></el-form-item>
        <el-form-item label="司南密码" required><el-input v-model="form.password" type="password" show-password autocomplete="new-password" placeholder="不会回显已保存密码" /></el-form-item>
        <el-form-item label="Distributor Menu ID" required><el-input v-model="form.menu_id" /></el-form-item>
        <el-form-item label="当前状态"><el-tag :type="status.verified ? 'success' : status.configured ? 'warning' : 'info'">{{ status.verified ? '已验证' : status.configured ? '待验证' : '未配置' }}</el-tag></el-form-item>
        <el-form-item><el-button type="primary" :loading="saving" @click="save">保存并测试登录</el-button><el-button :loading="testing" :disabled="!status.configured" @click="test">重新测试</el-button></el-form-item>
      </el-form>
    </el-card>
  </div>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { sinanApi, type SinanStatus } from '@/api/sinan'
const form = reactive({ base_url: 'https://api.sinan-partner.com', app_id: '894783', account: '', password: '', menu_id: '' })
const status = ref<SinanStatus>({ configured: false, verified: false }); const saving = ref(false); const testing = ref(false); const notice = ref(''); const noticeType = ref<'success'|'warning'|'error'>('success')
async function load() { try { const { data } = await sinanApi.status(); status.value = data } catch {} }
async function save() { saving.value = true; try { await sinanApi.save(form); await load(); noticeType.value='success'; notice.value='配置已保存，司南登录验证成功'; ElMessage.success(notice.value) } catch { noticeType.value='error'; notice.value='保存或登录验证失败' } finally { saving.value=false } }
async function test() { testing.value=true; try { await sinanApi.testLogin(); await load(); noticeType.value='success'; notice.value='司南账号验证成功' } catch { noticeType.value='error'; notice.value='司南账号验证失败' } finally { testing.value=false } }
onMounted(load)
</script>
