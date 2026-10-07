<template>
  <PublicPage>
    <h1>{{ copy.nav.privacy }}</h1>
    <p>{{ copy.privacy.updated }}</p>
    <p>{{ copy.privacy.intro }}</p>
    <section v-for="section in copy.privacy.sections" :key="section.title"><h2>{{ section.title }}</h2><p>{{ section.text }}</p></section>
    <h2>{{ copy.privacy.deletionTitle }}</h2>
    <p>{{ copy.privacy.deletionBefore }} <RouterLink to="/data-deletion">{{ copy.privacy.deletionLink }}</RouterLink> {{ copy.privacy.deletionAfter }} <a :href="`mailto:${CONTACT_EMAIL}`">{{ CONTACT_EMAIL }}</a>.</p>
  </PublicPage>
</template>
<script setup lang="ts">
import PublicPage from '@/components/PublicPage.vue'
import { CONTACT_EMAIL, usePublicCopy } from '@/locales/public'
const copy = usePublicCopy()
</script>
