<template>
  <div class="reports-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>数据报表</span>
        </div>
      </template>
      <el-alert type="warning" :closable="false" show-icon>
        <template #title>功能开发中</template>
        报表数据来自后端 <code>/api/v1/accounts/{id}/daily-report</code> 与
        <code>/api/v1/accounts/{id}/weekly-report</code> 接口。请在账户列表中选择账户后查看。
      </el-alert>
    </el-card>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped lang="scss">
.reports-page {
  padding: 4px;
}
</style>
