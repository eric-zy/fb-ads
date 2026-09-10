import { computed, ref } from 'vue'
import zh from '@/locales/zh'
import en from '@/locales/en'
export type Locale = 'zh' | 'en'
const detect = (): Locale => /^zh/i.test(navigator.language || '') ? 'zh' : 'en'
const locale = ref<Locale>((localStorage.getItem('site-locale') as Locale) || detect())
export function translate(key: string): string { const source: any = locale.value === 'zh' ? zh : en; return key.split('.').reduce((v, part) => v?.[part], source) || key }
export function useLocale() { const setLocale = (value: Locale) => { locale.value = value; localStorage.setItem('site-locale', value) }; return { locale, isZh: computed(() => locale.value === 'zh'), setLocale, t: translate } }
