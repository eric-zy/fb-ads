import { md5ArrayBuffer } from '@/utils/md5'
import { sha256ArrayBuffer } from '@/utils/sha256'

type HashProgress = (loaded: number, total: number) => void

/**
 * Move the expensive video fingerprint calculation off the Vue main thread.
 * The worker reads the File in bounded chunks and reports progress while the
 * final digest is calculated, so a 250MB+ upload does not freeze the page.
 */
export function fingerprintFile(file: File, onProgress?: HashProgress): Promise<{ md5: string; sha256: string }> {
  return new Promise((resolve, reject) => {
    const fallback = async () => {
      const buffer = await file.arrayBuffer()
      const [sha256, md5] = await Promise.all([
        sha256ArrayBuffer(buffer),
        Promise.resolve(md5ArrayBuffer(buffer)),
      ])
      onProgress?.(file.size, file.size)
      resolve({ md5, sha256 })
    }
    let worker: Worker
    try {
      worker = new Worker(new URL('../workers/mediaFingerprint.worker.ts', import.meta.url), { type: 'module' })
    } catch {
      void fallback().catch(reject)
      return
    }
    worker.onmessage = (event) => {
      const message = event.data as { type: string; loaded?: number; total?: number; md5?: string; sha256?: string; error?: string }
      if (message.type === 'progress') {
        onProgress?.(message.loaded || 0, message.total || file.size)
        return
      }
      worker.terminate()
      if (message.type === 'done' && message.md5 && message.sha256) {
        resolve({ md5: message.md5, sha256: message.sha256 })
      } else {
        reject(new Error(message.error || '素材指纹计算失败'))
      }
    }
    worker.onerror = (event) => {
      worker.terminate()
      void fallback().catch(() => reject(new Error(event.message || '素材指纹计算线程失败')))
    }
    worker.postMessage({ file })
  })
}

// Keep the imports in the frontend bundle available for older browsers that
// reject module workers; the worker is the normal execution path.
export { md5ArrayBuffer, sha256ArrayBuffer }
