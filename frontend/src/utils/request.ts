// 统一请求封装
//
// 背景：此前项目裸用全局 axios 实例，Token 由 userStore / useAuth 两处
// 手工写入 axios.defaults.headers.common，既重复又缺少 401 统一处理。
// 后端已启用全局鉴权中间件（所有 /api/ 路径需 Bearer Token），
// 因此统一收敛到这里：请求自动带 Token，401 自动清理登录态并跳转。
//
// 全局错误弹框：所有非 2xx 响应 / 网络异常 / 超时，统一在此处弹出
// ElMessage.error（带后端 detail 或友好文案），避免每个页面 catch 里
// 重复写 `ElMessage.error('xxx失败：' + (e.response?.data?.detail || e.message))`。
// 业务方若需自定义提示或静默，可在请求配置上传入 `skipErrorMessage: true`。
import axios, { AxiosError, type AxiosProgressEvent } from 'axios'
import { ElMessage } from 'element-plus'
import Cookies from 'js-cookie'

// 扩展 axios 请求配置：业务方可声明静默，跳过全局错误弹框
declare module 'axios' {
  interface AxiosRequestConfig {
    /** 静默错误：不弹出全局错误提示，由调用方自行处理 */
    skipErrorMessage?: boolean
  }
}

export const TOKEN_KEY = 'auth_token'
export const USER_KEY = 'user'

const request = axios.create({
  // vite 已将 /api 代理到 http://localhost:8000，此处保持相对路径
  timeout: 60_000,
})

// ---------- 请求拦截器：注入 Token ----------
request.interceptors.request.use((config) => {
  const token = Cookies.get(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 后端错误体常见字段：FastAPI 用 detail，部分接口用 message
type BackendErrorBody = { detail?: string | Array<{ msg?: string; message?: string }>; message?: string; error?: string }

/** 将后端返回的 detail（可能是字符串或 FastAPI 校验错误数组）规整为可读字符串 */
function normalizeDetail(detail: BackendErrorBody['detail']): string {
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item, i) => {
        const loc = (item as any).loc
        const field = Array.isArray(loc) && loc.length ? loc[loc.length - 1] : ''
        const msg = item.msg || item.message || ''
        return field ? `${field}: ${msg}` : msg
      })
      .filter(Boolean)
      .join('；')
  }
  return ''
}

/** 从 axios 错误中提取后端返回的人类可读消息 */
export function formatRequestError(error: unknown): string {
  if (error && typeof error === 'object' && 'isAxiosError' in error) {
    const e = error as AxiosError<BackendErrorBody>
    const body = e.response?.data
    return normalizeDetail(body?.detail) || body?.message || body?.error || e.message || '请求失败'
  }
  if (error instanceof Error) return error.message
  return '请求失败'
}

/** 根据 HTTP 状态码 / 错误类型给出友好文案 */
function friendlyMessage(error: AxiosError<BackendErrorBody>): string {
  const status = error.response?.status
  const detail = normalizeDetail(error.response?.data?.detail) ||
    error.response?.data?.message ||
    error.response?.data?.error ||
    error.message

  if (error.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  if (error.code === 'ERR_NETWORK' || !error.response) return '网络异常，请检查网络连接'
  switch (status) {
    case 400: return detail || '请求参数有误'
    case 401: return '登录已过期，请重新登录'
    case 403: return '权限不足：' + (detail || '无访问权限')
    case 404: return detail || '请求的资源不存在'
    case 409: return detail || '资源冲突'
    case 422: return detail || '请求数据校验失败'
    case 429: return '请求过于频繁，请稍后再试'
    case 500: return '服务器内部错误，请稍后重试'
    case 502:
    case 503:
    case 504: return '服务暂时不可用，请稍后重试'
    default: return detail || '请求失败'
  }
}

// ---------- 响应拦截器：统一错误处理 + 全局弹框 ----------
request.interceptors.response.use(
  (response) => response,
  (error: AxiosError<BackendErrorBody>) => {
    const status = error.response?.status

    // 业务侧若声明静默（自行处理提示），则不弹
    const silent = (error.config as any)?.skipErrorMessage === true

    // 401 登录态失效：跳转登录页（登录接口自身的 401 当作业务失败处理）
    if (status === 401) {
      const url = error.config?.url || ''
      // 登录接口 401 = 账号或密码错误，仅全局弹框提示，不清理登录态、不跳转
      if (url.includes('/auth/login')) {
        if (!silent) {
          ElMessage.error(formatRequestError(error) || '登录失败')
        }
        return Promise.reject(new Error(formatRequestError(error) || '登录失败'))
      }
      // 其它接口 401 = 登录态失效：清理本地凭证，跳回登录页
      Cookies.remove(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      if (!window.location.pathname.includes('/login')) {
        ElMessage.error('登录已过期，请重新登录')
        window.location.href = '/login'
      }
      return Promise.reject(new Error(formatRequestError(error) || '登录已过期'))
    }

    // 全局弹框：非静默 + 非已被 401 跳转逻辑覆盖的场景
    if (!silent) {
      ElMessage({
        type: 'error',
        message: friendlyMessage(error),
        grouping: true,
        duration: 4000,
      })
    }

    return Promise.reject(error)
  }
)

export { AxiosProgressEvent }
export default request
