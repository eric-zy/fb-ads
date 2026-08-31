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
      <template #header><span>管理后台说明</span></template>
      <el-alert type="info" :closable="false">
        用户管理、账户管理等子模块接口正在完善中。当前可正常使用的功能：
        账户同步、风险检测、批量发布、任务调度（用户端）。
      </el-alert>
    </el-card>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped lang="scss">
.admin-dashboard {
  .sub {
    color: #909399;
    font-size: 12px;
  }
}
</style>
