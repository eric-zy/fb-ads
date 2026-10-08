/** Preserve an internal destination when login is needed during OAuth. */
export function safeAuthRedirect(value: unknown): string | null {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || /[\\\x00-\x1f]/.test(value)) return null
  const url = new URL(value, 'https://internal.invalid')
  if (url.origin !== 'https://internal.invalid' || !/^\/(dashboard|admin)(\/|$)/.test(url.pathname)) return null
  return url.pathname + url.search + url.hash
}
