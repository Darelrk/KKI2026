const MAX_JPEG_BYTES = 5 * 1024 * 1024

export async function readFirstJpeg(
  stream: ReadableStream<Uint8Array>,
): Promise<Uint8Array> {
  const reader = stream.getReader()
  let bytes = new Uint8Array()
  let start = -1

  try {
    while (bytes.length < MAX_JPEG_BYTES) {
      const { done, value } = await reader.read()
      if (done) break

      const previousLength = bytes.length
      const next = new Uint8Array(previousLength + value.length)
      next.set(bytes)
      next.set(value, previousLength)
      bytes = next

      if (start < 0) {
        start = findMarker(bytes, 0xff, 0xd8, Math.max(0, previousLength - 1))
      }
      if (start >= 0) {
        const end = findMarker(
          bytes,
          0xff,
          0xd9,
          Math.max(start + 2, previousLength - 1),
        )
        if (end >= 0) return bytes.slice(start, end + 2)
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined)
  }

  throw new Error('Camera frame is unavailable')
}

function findMarker(
  bytes: Uint8Array,
  first: number,
  second: number,
  from: number,
): number {
  for (let index = from; index < bytes.length - 1; index += 1) {
    if (bytes[index] === first && bytes[index + 1] === second) return index
  }
  return -1
}
