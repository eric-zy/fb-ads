// 金额单位工具（设计文档 §9）
//
// 后端一律以 BIGINT 存储最小货币单位（分），前端负责换算展示：
//   $10.50  →  1050
//
// 派生指标（ctr / cpc / cpm / roas / risk_score）是比率不是金额，不参与换算。

/** 常见货币的小数位；未列出的按 2 位处理 */
const CURRENCY_EXPONENT: Record<string, number> = {
  USD: 2,
  EUR: 2,
  GBP: 2,
  CNY: 2,
  HKD: 2,
  TWD: 2,
  JPY: 0, // 日元无小数位
  KRW: 0,
  VND: 0,
}

const CURRENCY_SYMBOL: Record<string, string> = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  CNY: '¥',
  JPY: '¥',
}

export function exponentFor(currency?: string | null): number {
  if (!currency) return 2
  return CURRENCY_EXPONENT[currency.toUpperCase()] ?? 2
}

/** 主单位（元）→ 最小单位（分）。提交表单时用 */
export function toMinor(amount?: number | null, currency?: string | null): number {
  if (amount == null) return 0
  return Math.round(amount * 10 ** exponentFor(currency))
}

/** 最小单位（分）→ 主单位（元）。展示前用 */
export function toMajor(amountMinor?: number | null, currency?: string | null): number {
  if (amountMinor == null) return 0
  return amountMinor / 10 ** exponentFor(currency)
}

/** 格式化为带符号的金额字符串，如 1050 + USD → "$10.50" */
export function formatMoney(amountMinor?: number | null, currency?: string | null): string {
  const exp = exponentFor(currency)
  const symbol = CURRENCY_SYMBOL[(currency || '').toUpperCase()] || ''
  return `${symbol}${toMajor(amountMinor, currency).toFixed(exp)}`
}

/** 只格式化数值、不带货币符号 */
export function formatAmount(amountMinor?: number | null, currency?: string | null): string {
  return toMajor(amountMinor, currency).toFixed(exponentFor(currency))
}
