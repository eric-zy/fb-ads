import type { ReportQuality } from '@/api/reports'

export function hasCompleteCoverage(quality: ReportQuality[] | undefined, accountId: string, days: number): boolean {
  const account = quality?.find(item => item.account_id === accountId)
  return !!account && account.complete === true && account.expected_days === days
    && account.covered_days === days && ['FRESH', 'STALE'].includes(account.status)
}

export function percentageChange(current: number | null | undefined, previous: number | null | undefined): string {
  if (current == null || previous == null || !Number.isFinite(current) || !Number.isFinite(previous)) return '—'
  if (previous === 0) return current === 0 ? '0%' : '新增'
  const change = (current - previous) / Math.abs(previous) * 100
  return `${change > 0 ? '+' : ''}${change.toFixed(1)}%`
}
