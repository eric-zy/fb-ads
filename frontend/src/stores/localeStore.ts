import { computed, ref, watch } from 'vue'
import zh from '@/locales/zh'
import en from '@/locales/en'
export type Locale = 'zh' | 'en'
const detect = (): Locale => /^zh/i.test(navigator.language || '') ? 'zh' : 'en'
const savedLocale = localStorage.getItem('site-locale')
const locale = ref<Locale>(savedLocale === 'zh' || savedLocale === 'en' ? savedLocale : detect())
watch(locale, value => { document.documentElement.lang = value === 'zh' ? 'zh-CN' : 'en' }, { immediate: true })
let publicLocaleRequest: Promise<void> | undefined
export function initializePublicLocale(): Promise<void> {
  if (localStorage.getItem('site-locale')) return Promise.resolve()
  publicLocaleRequest ??= (async () => {
    try {
      const response = await fetch('/api/v1/public/locale')
      if (!response.ok) return
      const data = await response.json()
      // An explicit choice made while geo-detection is pending takes priority.
      if (!localStorage.getItem('site-locale') && (data.locale === 'zh' || data.locale === 'en')) {
        useLocale().setLocale(data.locale)
      }
    } catch { /* 浏览器语言作为离线时的默认值 */ }
  })()
  return publicLocaleRequest
}
export function translate(key: string): string { const source: any = locale.value === 'zh' ? zh : en; return key.split('.').reduce((v, part) => v?.[part], source) || key }
export function useLocale() { const setLocale = (value: Locale) => { locale.value = value; localStorage.setItem('site-locale', value) }; return { locale, isZh: computed(() => locale.value === 'zh'), setLocale, t: translate } }
