import { Md5Stream } from '@/utils/md5'
import { Sha256Stream } from '@/utils/sha256'

const scope = self as unknown as {
  onmessage: ((event: MessageEvent<{ file: File }>) => void) | null
  postMessage: (message: unknown) => void
}

scope.onmessage = async (event) => {
  try {
    const file = event.data.file
    const chunkSize = 16 * 1024 * 1024
    const md5 = new Md5Stream()
    const sha256 = new Sha256Stream()
    let loaded = 0
    for (let start = 0; start < file.size; start += chunkSize) {
      const chunk = await file.slice(start, Math.min(start + chunkSize, file.size)).arrayBuffer()
      const bytes = new Uint8Array(chunk)
      md5.update(bytes)
      sha256.update(bytes)
      loaded += chunk.byteLength
      scope.postMessage({ type: 'progress', loaded, total: file.size })
    }
    scope.postMessage({ type: 'done', md5: md5.digest(), sha256: sha256.digest() })
  } catch (error) {
    scope.postMessage({ type: 'error', error: error instanceof Error ? error.message : String(error) })
  }
}
