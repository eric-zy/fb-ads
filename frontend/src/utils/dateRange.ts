export function dateOnly(value = new Date()): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`
}

export function shiftDateOnly(value: string, days: number): string {
  const date = new Date(`${value}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

export function rangeForDays(days: number, today = dateOnly()): [string, string] {
  return [shiftDateOnly(today, 1 - days), today]
}

export function inclusiveDays(start: string, end: string): number {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000) + 1
}

export function rangeError(start: string, end: string, maxDays = 90): string {
  if (!start && !end) return ''
  if (!start || !end) return '请选择开始日期和结束日期'
  for (const value of [start, end]) {
    const parsed = new Date(`${value}T00:00:00Z`)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) return '请输入有效日期，格式为 YYYY-MM-DD'
  }
  if (start > end) return '开始日期不能晚于结束日期'
  if (inclusiveDays(start, end) > maxDays) return `日期范围最多 ${maxDays} 天（含起止日期）`
  return ''
}
