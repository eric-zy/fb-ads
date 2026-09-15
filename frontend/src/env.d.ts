/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

declare module 'js-cookie' {
  interface CookiesStatic {
    get(name: string): string | undefined
    set(name: string, value: string, options?: Record<string, unknown>): string
    remove(name: string, options?: Record<string, unknown>): void
  }
  const Cookies: CookiesStatic
  export default Cookies
}
