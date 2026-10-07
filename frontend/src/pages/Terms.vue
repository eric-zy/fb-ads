<template>
  <PublicPage>
    <h1>{{ copy.nav.terms }}</h1>
    <p>{{ copy.terms.updated }}</p>
    <p>{{ copy.terms.intro }}</p>
    <section v-for="section in copy.terms.sections" :key="section.title"><h2>{{ section.title }}</h2><p>{{ section.text }}</p></section>
    <h2>{{ copy.nav.contact }}</h2>
    <p>{{ copy.contactEmail }}: <a :href="`mailto:${CONTACT_EMAIL}`">{{ CONTACT_EMAIL }}</a></p>
  </PublicPage>
</template>
<script setup lang="ts">
import PublicPage from '@/components/PublicPage.vue'
import { CONTACT_EMAIL, usePublicCopy } from '@/locales/public'
const copy = usePublicCopy()
</script>
