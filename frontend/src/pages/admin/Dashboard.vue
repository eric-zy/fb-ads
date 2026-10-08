<template>
  <div class="admin-dashboard">
    <el-row :gutter="20">
      <el-col :xs="24" :sm="8">
        <el-card>
          <template #header><span>系统概览</span></template>
          <el-statistic title="应用" :value="1" />
          <p class="sub">FB 广告代理系统 v1.0.0</p>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card>
          <template #header><span>运行环境</span></template>
          <el-tag type="success">已就绪</el-tag>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="8">
        <el-card>
          <template #header><span>定时任务</span></template>
          <el-tag type="info">Scheduler 运行中</el-tag>
        </el-card>
      </el-col>
    </el-row>

    <el-card style="margin-top: 20px">
      <template #header><span>广告账户分配</span></template>
      <el-alert type="info" :closable="false">
        先在用户管理中创建投手账号，再到广告账户分配中选择账户、勾选用户并指定主投手。
        进入用户端后，可点击「返回管理后台」回到之前的管理页面。
      </el-alert>
      <div class="quick-actions">
        <el-button type="primary" @click="$router.push('/admin/accounts')">分配广告账户给投手</el-button>
        <el-button @click="$router.push('/admin/users')">用户管理</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped lang="scss">
.admin-dashboard {
  .quick-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; }
  .sub {
    color: #909399;
    font-size: 12px;
  }
}
</style>
