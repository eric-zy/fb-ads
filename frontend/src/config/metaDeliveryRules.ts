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

// Meta AdCreative.CallToActionType；NO_BUTTON 在后端会转换为不发送 call_to_action。
export const CTA_OPTIONS = [
  { value: 'NO_BUTTON', label: '无按钮' },
  { value: 'LEARN_MORE', label: '了解更多' },
  { value: 'GET_DETAILS', label: '查看详情' },
  { value: 'SEE_MORE', label: '查看更多' },
  { value: 'WATCH_MORE', label: '查看更多' },
  { value: 'GET_OFFER', label: '获取优惠' },
  { value: 'APPLY_NOW', label: '立即申请' },
  { value: 'BOOK_NOW', label: '立即预订' },
  { value: 'CONTACT_US', label: '联系我们' },
  { value: 'DONATE_NOW', label: '立即捐款' },
  { value: 'DOWNLOAD', label: '下载' },
  { value: 'GET_QUOTE', label: '获取报价' },
  { value: 'SHOP_NOW', label: '立即购买' },
  { value: 'BUY_NOW', label: '立即购买' },
  { value: 'SIGN_UP', label: '注册' },
  { value: 'SUBSCRIBE', label: '订阅' },
  { value: 'MESSAGE_PAGE', label: '发送消息' },
  { value: 'CHAT_NOW', label: '立即聊天' },
  { value: 'WHATSAPP_MESSAGE', label: 'WhatsApp 消息' },
  { value: 'ORDER_NOW', label: '立即订购' },
  { value: 'CALL_NOW', label: '立即致电' },
  { value: 'EVENT_RSVP', label: '参加活动' },
  { value: 'FIND_OUT_MORE', label: '了解更多' },
  // 视频广告/互动场景常用 CTA；可用项仍会受到 Meta 目标和版位限制。
  { value: 'PAY_TO_ACCESS', label: '获取访问权限' },
  { value: 'REQUEST_TIME', label: '预约时间' },
  { value: 'SEE_MENU', label: '查看菜单' },
  { value: 'SEND_UPDATES', label: '接收动态更新' },
  { value: 'BROWSE_SHOP', label: '去逛逛' },
  { value: 'WATCH_VIDEO', label: '观看视频' },
  { value: 'WATCH_LIVE_VIDEO', label: '观看直播' },
  { value: 'JOIN_LIVE_VIDEO', label: '加入直播' },
  { value: 'LISTEN_NOW', label: '立即收听' },
  { value: 'GET_SHOWTIMES', label: '查看场次' },
  { value: 'VISIT_WEBSITE', label: '访问网站' },
  { value: 'MAKE_AN_APPOINTMENT', label: '立即预约' },
] as const

export const OPTIMIZATION_GOAL_LABELS: Record<string, string> = {
  LANDING_PAGE_VIEWS: '落地页浏览量最大化',
  LINK_CLICKS: '链接点击量最大化',
  REACH: '单日独立覆盖人数最大化',
  CONVERSATIONS: '对话次数最大化',
  IMPRESSIONS: '展示次数最大化',
  OFFSITE_CONVERSIONS: '网站转化量最大化',
  VALUE: '转化价值最大化',
  CONVERSIONS: '转化次数最大化',
  POST_ENGAGEMENT: '互动次数最大化',
  THRUPLAY: '视频观看次数最大化',
  EVENT_RESPONSES: '活动响应次数最大化',
  LEAD_GENERATION: '潜在客户数量最大化',
}

export const OPTIMIZATION_GOAL_OPTIONS: Record<string, string[]> = {
  // 顺序与 Meta 页面一致：核心成效目标在前，其它可用目标在后。
  OUTCOME_TRAFFIC: ['LANDING_PAGE_VIEWS', 'LINK_CLICKS', 'REACH', 'CONVERSATIONS', 'IMPRESSIONS', 'OFFSITE_CONVERSIONS'],
  OUTCOME_SALES: ['OFFSITE_CONVERSIONS', 'VALUE', 'CONVERSIONS'],
  OUTCOME_ENGAGEMENT: ['POST_ENGAGEMENT', 'THRUPLAY', 'EVENT_RESPONSES', 'CONVERSATIONS', 'IMPRESSIONS'],
  OUTCOME_LEADS: ['LEAD_GENERATION', 'OFFSITE_CONVERSIONS', 'CONVERSATIONS', 'IMPRESSIONS'],
}

export const optimizationGoalOptions = (objective: string) =>
  (OPTIMIZATION_GOAL_OPTIONS[objective] || ['LINK_CLICKS']).map(value => ({
    value,
    label: OPTIMIZATION_GOAL_LABELS[value] || value,
  }))

export const optimizationGoalLabel = (goal: string | null | undefined) =>
  OPTIMIZATION_GOAL_LABELS[String(goal || '').toUpperCase()] || goal || '-'

export const isOptimizationGoalAllowed = (objective: string, goal: string) =>
  !OPTIMIZATION_GOAL_OPTIONS[objective] || OPTIMIZATION_GOAL_OPTIONS[objective].includes(goal)

export const defaultOptimizationGoal = (objective: string) => {
  if (objective === 'OUTCOME_SALES') return 'OFFSITE_CONVERSIONS'
  if (objective === 'OUTCOME_ENGAGEMENT') return 'POST_ENGAGEMENT'
  if (objective === 'OUTCOME_LEADS') return 'LEAD_GENERATION'
  return 'LANDING_PAGE_VIEWS'
}

export const isConversionOptimizationGoal = (goal: string) =>
  CONVERSION_OPTIMIZATION_GOALS.includes(goal as typeof CONVERSION_OPTIMIZATION_GOALS[number])
