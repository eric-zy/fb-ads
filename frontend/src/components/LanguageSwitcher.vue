<template><el-select :model-value="locale" size="small" class="language-switcher" @update:model-value="setLocale"><el-option value="zh" label="中文"/><el-option value="en" label="English"/></el-select></template>
<script setup lang="ts">import { useLocale } from '@/stores/localeStore'; const { locale, setLocale } = useLocale()</script>
<style scoped>.language-switcher{width:108px}</style>
