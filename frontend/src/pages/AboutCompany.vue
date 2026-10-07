<template>
  <PublicPage>
    <h1>{{ copy.nav.about }}</h1>
    <p>{{ copy.about.intro }}</p>
    <h2>{{ copy.companyInfo }}</h2>
    <p>{{ copy.companyName }}: {{ copy.company }}</p>
    <p>{{ copy.creditCode }}: 91340100MA2NK6PE05</p>
    <p>{{ copy.about.typeLabel }}: {{ copy.about.type }}</p>
    <p>{{ copy.registeredAddressLabel }}: {{ copy.address }}</p>
    <p>{{ copy.about.foundedLabel }}: {{ copy.about.founded }}</p>
    <h2>{{ copy.about.serviceTitle }}</h2>
    <p>{{ copy.about.service }}</p>
  </PublicPage>
</template>
<script setup lang="ts">
import PublicPage from '@/components/PublicPage.vue'
import { usePublicCopy } from '@/locales/public'
const copy = usePublicCopy()
</script>
