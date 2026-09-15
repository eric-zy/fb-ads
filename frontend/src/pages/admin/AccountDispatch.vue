<template>
  <div class="page">
    <div class="toolbar"><h2>账户调度中心</h2><div><el-button @click="load">刷新</el-button><el-button @click="ruleDialog=true">新增规则</el-button><el-button type="primary" @click="dispatch">自动分配未分配账户</el-button></div></div>
    <el-alert title="账户池仅展示 BM、授权关系和系统状态均可用的广告账户。" type="info" :closable="false" />
    <el-table v-loading="loading" :data="items" style="margin-top: 16px" stripe>
      <el-table-column prop="account_name" label="广告账户" min-width="180" />
      <el-table-column label="BM" min-width="180"><template #default="s">{{ s.row.bm?.name }}<small>{{ s.row.bm?.business_id }}</small></template></el-table-column>
      <el-table-column prop="currency" label="币种" width="90" />
      <el-table-column prop="meta_status" label="Meta 状态" width="130" />
      <el-table-column label="分配人员" min-width="180"><template #default="s">{{ s.row.assigned_user_ids?.join(', ') || '未分配' }}</template></el-table-column>
      <el-table-column label="操作" width="110"><template #default="s"><el-button v-if="s.row.assigned" link type="danger" @click="release(s.row.account_id)">释放</el-button></template></el-table-column>
    </el-table>
    <h3>当前规则</h3>
    <el-table :data="rules" stripe><el-table-column prop="name" label="名称" /><el-table-column prop="rule_type" label="类型" /><el-table-column prop="priority" label="优先级" width="90" /><el-table-column prop="status" label="状态" width="100" /></el-table>
    <el-dialog v-model="ruleDialog" title="新增分配规则" width="520px">
      <el-form label-width="100px">
        <el-form-item label="规则名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="目标用户"><el-input v-model="form.userIds" placeholder="用户 ID，多个用逗号分隔" /></el-form-item>
        <el-form-item label="优先级"><el-input-number v-model="form.priority" :min="1" /></el-form-item>
        <el-form-item label="BM ID"><el-input v-model="form.businessId" /></el-form-item>
        <el-form-item label="币种"><el-input v-model="form.currency" placeholder="如 USD / TWD" /></el-form-item>
        <el-form-item label="时区"><el-input v-model="form.timezone" placeholder="如 Asia/Taipei" /></el-form-item>
        <el-form-item label="账户标签"><el-input v-model="form.tag" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="ruleDialog=false">取消</el-button><el-button type="primary" @click="createRule">保存</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { accountDispatchApi } from '@/api/accountDispatch'
const loading = ref(false); const items = ref<any[]>([]); const rules = ref<any[]>([]); const ruleDialog = ref(false)
const form = ref({ name: '', userIds: '', priority: 100, businessId: '', currency: '', timezone: '', tag: '' })
async function load() { loading.value = true; try { const [p, r] = await Promise.all([accountDispatchApi.pool(), accountDispatchApi.rules()]); items.value = (p.data as any).items || []; rules.value = (r.data as any).items || [] } finally { loading.value = false } }
async function dispatch() { await accountDispatchApi.dispatchUnassigned(); ElMessage.success('自动分配完成'); await load() }
async function release(id: string) { await accountDispatchApi.release(id); ElMessage.success('账户已释放'); await load() }
async function createRule() { const f = form.value; if (!f.name || !f.userIds) { ElMessage.warning('请填写规则名称和用户 ID'); return }; const cfg: any = { user_ids: f.userIds.split(',').map(x => x.trim()).filter(Boolean) }; if (f.businessId) cfg.business_id = f.businessId; if (f.currency) cfg.currency = f.currency; if (f.timezone) cfg.timezone = f.timezone; if (f.tag) cfg.tag = f.tag; await accountDispatchApi.createRule({ name: f.name, priority: f.priority, rule_type: 'LEAST_LOAD', rule_config: cfg }); ruleDialog.value = false; ElMessage.success('规则已创建'); form.value = { name: '', userIds: '', priority: 100, businessId: '', currency: '', timezone: '', tag: '' }; await load() }
onMounted(load)
</script>
<style scoped>.page{padding:24px}.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}h2{margin:0 0 12px}h3{margin-top:28px}small{display:block;color:#909399}</style>
