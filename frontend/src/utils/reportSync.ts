import { reportsApi } from '@/api/reports'

export async function waitForReportSync(taskIds: string[], signal?: AbortSignal): Promise<void> {
  const deadline = Date.now() + 180_000
  const pending = new Set(taskIds)
  const failed: string[] = []
  while (pending.size) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const statuses = await Promise.all([...pending].map(async id => {
      try { const { data } = await reportsApi.taskStatus(id); return { id, ...data } }
      catch { return { id, state: 'UNKNOWN', result: undefined } }
    }))
    for (const item of statuses) {
      if (!['SUCCESS', 'FAILURE', 'REVOKED'].includes(item.state)) continue
      pending.delete(item.id)
      if (item.state !== 'SUCCESS' || item.result?.status !== 'success' || Number(item.result?.error_count || 0) > 0) failed.push(item.id)
    }
    if (!pending.size) break
    if (Date.now() >= deadline) throw new Error('同步仍在执行或状态暂不可用，请在任务中心查看进度')
    await new Promise<void>((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
      const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve() }, 2000)
      signal?.addEventListener('abort', abort, { once: true })
    })
  }
  if (failed.length) throw new Error(`${failed.length} 个账户同步失败，请查看同步错误后重试`)
}
