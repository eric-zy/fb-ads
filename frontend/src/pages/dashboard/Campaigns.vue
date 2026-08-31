<template>
  <div class="campaigns-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>广告系列管理</span>
        </div>
      </template>
      <el-alert type="warning" :closable="false" show-icon>
        <template #title>功能开发中</template>
        该模块依赖后端 <code>/api/v1/campaigns</code> 系列接口，当前后端尚未开放。
        你可以在 <b>批量发布</b> 页面通过账户同步获取系列数据。
      </el-alert>
    </el-card>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped lang="scss">
.campaigns-page {
  padding: 4px;
}
</style>
