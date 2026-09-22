/** 小型浏览器端 MD5 实现，仅用于素材去重指纹，不用于安全校验。 */
const shifts = [
  7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
  5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
  4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
  6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
]
const constants = Array.from({ length: 64 }, (_, i) => Math.floor(Math.abs(Math.sin(i + 1)) * 0x100000000))

const add = (...values: number[]) => values.reduce((sum, value) => (sum + value) >>> 0, 0)
const rotate = (value: number, count: number) => (value << count) | (value >>> (32 - count))

export function md5ArrayBuffer(buffer: ArrayBuffer): string {
  const input = new Uint8Array(buffer)
  const bitLength = input.length * 8
  const paddedLength = (((input.length + 8) >> 6) + 1) * 64
  const data = new Uint8Array(paddedLength)
  data.set(input)
  data[input.length] = 0x80
  const view = new DataView(data.buffer)
  view.setUint32(paddedLength - 8, bitLength >>> 0, true)
  view.setUint32(paddedLength - 4, Math.floor(bitLength / 0x100000000), true)

  let a0 = 0x67452301
  let b0 = 0xefcdab89
  let c0 = 0x98badcfe
  let d0 = 0x10325476

  for (let offset = 0; offset < paddedLength; offset += 64) {
    const words = new Uint32Array(16)
    for (let i = 0; i < 16; i += 1) words[i] = view.getUint32(offset + i * 4, true)
    let a = a0; let b = b0; let c = c0; let d = d0
    for (let i = 0; i < 64; i += 1) {
      let f: number; let g: number
      if (i < 16) { f = (b & c) | (~b & d); g = i }
      else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) % 16 }
      else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) % 16 }
      else { f = c ^ (b | ~d); g = (7 * i) % 16 }
      const next = add(b, rotate(add(a, f, constants[i], words[g]), shifts[i]))
      a = d; d = c; c = b; b = next
    }
    a0 = add(a0, a); b0 = add(b0, b); c0 = add(c0, c); d0 = add(d0, d)
  }

  const hex = (value: number) => Array.from({ length: 4 }, (_, i) => ((value >>> (i * 8)) & 0xff).toString(16).padStart(2, '0')).join('')
  return hex(a0) + hex(b0) + hex(c0) + hex(d0)
}

export class Md5Stream {
  private a0 = 0x67452301
  private b0 = 0xefcdab89
  private c0 = 0x98badcfe
  private d0 = 0x10325476
  private pending = new Uint8Array(0)
  private totalLength = 0

  update(input: Uint8Array) {
    this.totalLength += input.length
    const data = this.pending.length
      ? (() => {
          const combined = new Uint8Array(this.pending.length + input.length)
          combined.set(this.pending)
          combined.set(input, this.pending.length)
          return combined
        })()
      : input
    const fullLength = data.length - (data.length % 64)
    for (let offset = 0; offset < fullLength; offset += 64) this.process(data, offset)
    this.pending = data.slice(fullLength)
  }

  private process(data: Uint8Array, offset: number) {
    const view = new DataView(data.buffer, data.byteOffset + offset, 64)
    const words = new Uint32Array(16)
    for (let i = 0; i < 16; i += 1) words[i] = view.getUint32(i * 4, true)
    let a = this.a0; let b = this.b0; let c = this.c0; let d = this.d0
    for (let i = 0; i < 64; i += 1) {
      let f: number; let g: number
      if (i < 16) { f = (b & c) | (~b & d); g = i }
      else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) % 16 }
      else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) % 16 }
      else { f = c ^ (b | ~d); g = (7 * i) % 16 }
      const next = add(b, rotate(add(a, f, constants[i], words[g]), shifts[i]))
      a = d; d = c; c = b; b = next
    }
    this.a0 = add(this.a0, a); this.b0 = add(this.b0, b)
    this.c0 = add(this.c0, c); this.d0 = add(this.d0, d)
  }

  digest(): string {
    const bitLength = this.totalLength * 8
    const finalLength = (((this.pending.length + 8) >> 6) + 1) * 64
    const final = new Uint8Array(finalLength)
    final.set(this.pending)
    final[this.pending.length] = 0x80
    const view = new DataView(final.buffer)
    view.setUint32(finalLength - 8, bitLength >>> 0, true)
    view.setUint32(finalLength - 4, Math.floor(bitLength / 0x100000000), true)
    for (let offset = 0; offset < final.length; offset += 64) this.process(final, offset)
    const hex = (value: number) => Array.from({ length: 4 }, (_, i) => ((value >>> (i * 8)) & 0xff).toString(16).padStart(2, '0')).join('')
    return hex(this.a0) + hex(this.b0) + hex(this.c0) + hex(this.d0)
  }
}
