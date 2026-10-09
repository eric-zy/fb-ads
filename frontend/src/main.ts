import { createApp } from 'vue'
import { createPinia } from 'pinia'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import '@/styles/theme.scss'

import App from './App.vue'
import router from './router'

// A stale HTML document can point at hashed chunks removed by a newer deploy.
// Reload once so the browser can pick up the current entry document without
// creating an infinite reload loop if the server still serves an incomplete build.
const preloadReloadKey = 'vite-preload-error-reload-at'
window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  const lastReloadAt = Number(sessionStorage.getItem(preloadReloadKey) || '0')
  if (Date.now() - lastReloadAt < 30_000) return
  sessionStorage.setItem(preloadReloadKey, String(Date.now()))
  window.location.reload()
})

const app = createApp(App)

app.use(createPinia())
app.use(router)

app.mount('#app')
