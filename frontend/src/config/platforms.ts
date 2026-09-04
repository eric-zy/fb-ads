/**
 * 广告平台配置中心
 *
 * 扩展新平台（如 TikTok / Google Ads）的步骤：
 *   1. 在 PLATFORMS 数组追加一项
 *   2. 后端新增对应服务模块（参考 services/meta/*）
 *   3. 路由与页面按 /admin/<platform-key>/* 组织
 *   4. 当前 enabled=false 的平台在 Tab 中显示为「规划中」并禁用点击
 *
 * 导航设计参考：主菜单进内页后，上方横向平台 Tab 切换，
 * Tab 下是该平台的功能子页（BM/账户/授权/投放…）。
 */

export interface PlatformConfig {
  /** 唯一键，URL/路由/后端服务前缀用：meta / tiktok / google */
  key: string
  /** 完整显示名 */
  name: string
  /** 紧凑名（Tab 标签用） */
  short: string
  /** 标签前的小图标（emoji 跨字体稳定，不依赖图标库） */
  emoji: string
  /** Tab 高亮色 */
  color: string
  /** true=当前可点击切换；false=占位，提示「规划中」 */
  enabled: boolean
  /** 可选状态角标文案，如「规划中」 */
  badge?: string
}

export const PLATFORMS: PlatformConfig[] = [
  {
    key: 'meta',
    name: 'META_ADS',
    short: 'META',
    emoji: '📘',
    color: '#1877F2',
    enabled: true,
  },
  {
    key: 'tiktok',
    name: 'TIKTOK_ADS',
    short: 'TIKTOK',
    emoji: '🎵',
    color: '#161823',
    enabled: false,
    badge: '规划中',
  },
  {
    key: 'google',
    name: 'GOOGLE_ADS',
    short: 'GOOGLE',
    emoji: '🔍',
    color: '#4285F4',
    enabled: false,
    badge: '规划中',
  },
]

export const DEFAULT_PLATFORM = 'meta'

/** 按 key 查找平台配置；未找到回退到默认 */
export function getPlatform(key: string | null | undefined): PlatformConfig {
  return PLATFORMS.find((p) => p.key === key) || PLATFORMS[0]
}
