<template>
  <div class="page-container">
    <div class="page-head"><div><h2 class="page-title">账户组</h2><p class="page-subtitle">按团队或业务线管理广告账户访问范围</p></div><el-button type="primary" @click="openCreate">新建账户组</el-button></div>
    <el-card shadow="never"><el-table :data="groups" v-loading="loading" stripe><el-table-column prop="name" label="账户组"/><el-table-column prop="description" label="说明"/><el-table-column prop="account_count" label="广告账户" width="110"/><el-table-column prop="user_count" label="用户" width="90"/><el-table-column label="操作" width="150"><template #default="{row}"><el-button link type="primary" @click="openEdit(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column></el-table></el-card>
    <el-dialog v-model="visible" :title="editing ? '编辑账户组' : '新建账户组'" width="620px"><el-form :model="form" label-width="90px"><el-form-item label="名称"><el-input v-model="form.name" placeholder="例如：东南亚投放组"/></el-form-item><el-form-item label="说明"><el-input v-model="form.description"/></el-form-item><el-form-item label="广告账户"><el-select v-model="form.account_ids" multiple filterable collapse-tags style="width:100%" placeholder="选择账户"><el-option v-for="a in accounts" :key="a.id" :label="`${a.account_name || a.account_id}（${a.account_id}）`" :value="a.id"/></el-select></el-form-item><el-form-item label="用户"><el-select v-model="form.user_ids" multiple filterable collapse-tags style="width:100%" placeholder="选择用户"><el-option v-for="u in users" :key="u.id" :label="`${u.username}（${u.email}）`" :value="u.id"/></el-select></el-form-item></el-form><template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template></el-dialog>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountGroupApi, accountApi, userApi } from '@/api/admin'
const groups=ref<any[]>([]), accounts=ref<any[]>([]), users=ref<any[]>([]), loading=ref(false), saving=ref(false), visible=ref(false), editing=ref<any>(null)
const form=ref({name:'',description:'',account_ids:[] as string[],user_ids:[] as string[]})
async function load(){loading.value=true;try{groups.value=(await accountGroupApi.list()).data}finally{loading.value=false}}
async function loadOptions(){try{const [a,u]=await Promise.all([accountApi.list({page:1,page_size:100}),userApi.list({page:1,page_size:100})]);accounts.value=a.data;users.value=u.data}catch{}}
function openCreate(){editing.value=null;form.value={name:'',description:'',account_ids:[],user_ids:[]};visible.value=true}
function openEdit(row:any){editing.value=row;form.value={name:row.name,description:row.description||'',account_ids:[...(row.account_ids||[])],user_ids:[...(row.user_ids||[])]};visible.value=true}
async function save(){if(!form.value.name.trim()){ElMessage.warning('请输入账户组名称');return} saving.value=true;try{if(editing.value)await accountGroupApi.update(editing.value.id,form.value);else await accountGroupApi.create(form.value);visible.value=false;await load();ElMessage.success('已保存')}finally{saving.value=false}}
async function remove(row:any){try{await ElMessageBox.confirm(`确认删除账户组「${row.name}」？`,'提示',{type:'warning'});await accountGroupApi.remove(row.id);await load()}catch{}}
onMounted(async()=>{await Promise.all([load(),loadOptions()])})
</script>
