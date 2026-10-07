<template>
  <PublicPage>
    <h1>{{ copy.nav.deletion }}</h1>
    <p>{{ copy.deletion.before }} <a :href="`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(copy.deletion.subject)}`">{{ CONTACT_EMAIL }}</a> {{ copy.deletion.after }}</p>
    <h2>{{ copy.deletion.process }}</h2>
    <ol><li v-for="step in copy.deletion.steps" :key="step">{{ step }}</li></ol>
    <p>{{ copy.deletion.note }}</p>
  </PublicPage>
</template>
<script setup lang="ts">
import PublicPage from '@/components/PublicPage.vue'
import { CONTACT_EMAIL, usePublicCopy } from '@/locales/public'
const copy = usePublicCopy()
</script>
