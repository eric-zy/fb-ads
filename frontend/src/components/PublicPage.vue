<template>
  <main class="public-page"><article class="public-card">
    <header><div class="brand">myAds</div><nav><RouterLink to="/">{{ copy.nav.home }}</RouterLink><RouterLink to="/about">{{ copy.nav.about }}</RouterLink><RouterLink to="/privacy-policy">{{ copy.nav.privacy }}</RouterLink><RouterLink to="/terms">{{ copy.nav.terms }}</RouterLink><RouterLink to="/data-deletion">{{ copy.nav.deletion }}</RouterLink><RouterLink to="/contact">{{ copy.nav.contact }}</RouterLink><RouterLink to="/login">{{ copy.nav.login }}</RouterLink><LanguageSwitcher /></nav></header>
    <slot /><footer>{{ copy.company }} · <a :href="`mailto:${CONTACT_EMAIL}`">{{ CONTACT_EMAIL }}</a></footer>
  </article></main>
 </template>
<script setup lang="ts">
import { onMounted } from 'vue'
import LanguageSwitcher from '@/components/LanguageSwitcher.vue'
import { CONTACT_EMAIL, usePublicCopy } from '@/locales/public'
import { initializePublicLocale } from '@/stores/localeStore'
const copy = usePublicCopy()
onMounted(() => { void initializePublicLocale() })
</script>
<style scoped>
.public-page{min-height:100vh;padding:36px 20px;background:#f5f7fb;color:#1f2937}.public-card{max-width:900px;margin:0 auto;padding:34px 46px;background:#fff;border-radius:12px;box-shadow:0 8px 30px rgba(15,23,42,.08);line-height:1.8}header{display:flex;align-items:center;justify-content:space-between;gap:20px;padding-bottom:24px;border-bottom:1px solid #e5e7eb}.brand{color:#1877f2;font-size:22px;font-weight:700}nav{display:flex;flex-wrap:wrap;gap:14px}nav a{color:#52606d;text-decoration:none;font-size:14px}nav a.router-link-active{color:#1877f2}h1{margin:30px 0 6px;font-size:30px}h2{margin:26px 0 6px;font-size:19px}p{margin:8px 0}ul,ol{padding-left:22px}a{color:#1877f2}footer{margin-top:32px;padding-top:18px;border-top:1px solid #e5e7eb;color:#829ab1;font-size:13px}@media(max-width:640px){.public-card{padding:24px 20px}header{align-items:flex-start;flex-direction:column}}
</style>
