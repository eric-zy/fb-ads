<template>
  <PublicPage>
    <h1>{{ copy.nav.contact }}</h1>
    <h2>{{ copy.companyInfo }}</h2>
    <p>{{ copy.companyName }}: {{ copy.company }}</p>
    <p>{{ copy.addressLabel }}: {{ copy.address }}</p>
    <p>{{ copy.creditCode }}: 91340100MA2NK6PE05</p>
    <h2>{{ copy.contactEmail }}</h2>
    <p><a :href="`mailto:${CONTACT_EMAIL}`">{{ CONTACT_EMAIL }}</a></p>
    <p>{{ copy.contactHelp }}</p>
  </PublicPage>
</template>
<script setup lang="ts">
import PublicPage from '@/components/PublicPage.vue'
import { CONTACT_EMAIL, usePublicCopy } from '@/locales/public'
const copy = usePublicCopy()
</script>
