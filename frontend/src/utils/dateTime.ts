/** 后端无偏移的日期时间为 UTC；界面统一按浏览器本地时区显示，精确到秒。 */
export function parseDateTime(value?: string | null): Date | null {
  if (!value) return null
  const normalized = value.trim().replace(' ', 'T')
  const utcValue = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(normalized)
    ? `${normalized}Z` : normalized
  const date = new Date(utcValue)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatDateTime(value?: string | null, fallback = '-'): string {
  if (value && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  const date = parseDateTime(value)
  if (!date) return fallback
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function formatDateTimeCell(_row: unknown, _column: unknown, value?: string | null): string {
  return formatDateTime(value)
}
