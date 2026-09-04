<template>
  <div class="section-placeholder">
    <div class="hero">
      <div>
        <p class="eyebrow">{{ eyebrow }}</p>
        <h1>{{ title }}</h1>
        <p class="description">{{ description }}</p>
      </div>
      <el-tag v-if="status" size="large" effect="plain" round>{{ status }}</el-tag>
    </div>

    <el-row :gutter="16" class="metrics">
      <el-col v-for="item in metrics" :key="item.label" :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="metric-card">
          <div class="metric-label">{{ item.label }}</div>
          <div class="metric-value">{{ item.value }}</div>
          <div class="metric-note">{{ item.note }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="roadmap-card">
      <template #header>
        <div class="card-head">
          <span>模块规划</span>
          <el-tag type="info" effect="plain">结构已预留</el-tag>
        </div>
      </template>

      <ul class="roadmap-list">
        <li v-for="item in bullets" :key="item">{{ item }}</li>
      </ul>
    </el-card>
  </div>
</template>

<script setup lang="ts">
interface MetricItem {
  label: string
  value: string
  note: string
}

withDefaults(defineProps<{
  eyebrow?: string
  title: string
  description: string
  status?: string
  bullets?: string[]
  metrics?: MetricItem[]
}>(), {
  eyebrow: 'SaaS Frontend',
  status: '',
  bullets: () => [],
  metrics: () => [],
})
</script>

<style scoped lang="scss">
.section-placeholder {
  display: flex;
  flex-direction: column;
  gap: 18px;

  .hero {
    display: flex;
    justify-content: space-between;
    gap: 20px;
    padding: 24px 28px;
    border-radius: 20px;
    background:
      radial-gradient(circle at top right, rgba(194, 224, 255, 0.95), transparent 34%),
      linear-gradient(135deg, #fcfdff 0%, #eef4fb 55%, #f7fafc 100%);
    border: 1px solid rgba(21, 77, 145, 0.08);

    .eyebrow {
      margin: 0 0 8px;
      color: #40617f;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      font-size: 28px;
      line-height: 1.15;
      color: #10233a;
    }

    .description {
      margin: 12px 0 0;
      max-width: 720px;
      color: #4c6279;
      font-size: 14px;
      line-height: 1.7;
    }
  }

  .metrics {
    margin: 0;
  }

  .metric-card {
    border-radius: 18px;

    .metric-label {
      color: #6b7d90;
      font-size: 12px;
    }

    .metric-value {
      margin-top: 10px;
      color: #10233a;
      font-size: 28px;
      font-weight: 700;
    }

    .metric-note {
      margin-top: 8px;
      color: #7e8ea0;
      font-size: 13px;
    }
  }

  .roadmap-card {
    border-radius: 18px;

    .card-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .roadmap-list {
      margin: 0;
      padding-left: 18px;
      color: #4c6279;
      line-height: 1.9;
    }
  }
}
</style>
