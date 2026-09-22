/**
 * 前端投放表单使用的 Meta 目标规则。
 *
 * 这里只负责交互层的可选项和提示；真正提交前的合法性仍由后端预检裁决。
 * 新增目标或追踪资产类型时，优先在这里扩展，避免多个页面规则漂移。
 */
export const CONVERSION_OPTIMIZATION_GOALS = [
  'OFFSITE_CONVERSIONS',
  'VALUE',
  'CONVERSIONS',
] as const

export const STANDARD_CONVERSION_EVENTS = [
  { value: 'PURCHASE', label: '购买' },
  { value: 'LEAD', label: '提交线索' },
  { value: 'COMPLETE_REGISTRATION', label: '完成注册' },
  { value: 'ADD_TO_CART', label: '添加到购物车' },
  { value: 'INITIATED_CHECKOUT', label: '发起结账' },
  { value: 'ADD_PAYMENT_INFO', label: '添加支付信息' },
  { value: 'VIEW_CONTENT', label: '查看内容' },
  { value: 'SEARCH', label: '搜索' },
  { value: 'CONTACT', label: '联系' },
  { value: 'CUSTOMIZE_PRODUCT', label: '自定义产品' },
  { value: 'SUBMIT_APPLICATION', label: '提交申请' },
  { value: 'START_TRIAL', label: '开始试用' },
  { value: 'SUBSCRIBE', label: '订阅' },
  { value: 'SCHEDULE', label: '预约' },
  { value: 'FIND_LOCATION', label: '查找地点' },
  { value: 'DONATE', label: '捐赠' },
] as const

export const OPTIMIZATION_GOAL_OPTIONS: Record<string, string[]> = {
  OUTCOME_TRAFFIC: ['LINK_CLICKS', 'LANDING_PAGE_VIEWS', 'OFFSITE_CONVERSIONS', 'IMPRESSIONS', 'REACH'],
  OUTCOME_SALES: ['OFFSITE_CONVERSIONS', 'VALUE', 'CONVERSIONS'],
  OUTCOME_ENGAGEMENT: ['POST_ENGAGEMENT', 'THRUPLAY', 'EVENT_RESPONSES', 'IMPRESSIONS'],
  OUTCOME_LEADS: ['LEAD_GENERATION', 'OFFSITE_CONVERSIONS', 'IMPRESSIONS'],
}

export const isOptimizationGoalAllowed = (objective: string, goal: string) =>
  !OPTIMIZATION_GOAL_OPTIONS[objective] || OPTIMIZATION_GOAL_OPTIONS[objective].includes(goal)

export const defaultOptimizationGoal = (objective: string) => {
  if (objective === 'OUTCOME_SALES') return 'OFFSITE_CONVERSIONS'
  if (objective === 'OUTCOME_ENGAGEMENT') return 'POST_ENGAGEMENT'
  if (objective === 'OUTCOME_LEADS') return 'LEAD_GENERATION'
  return 'LINK_CLICKS'
}

export const isConversionOptimizationGoal = (goal: string) =>
  CONVERSION_OPTIMIZATION_GOALS.includes(goal as typeof CONVERSION_OPTIMIZATION_GOALS[number])
