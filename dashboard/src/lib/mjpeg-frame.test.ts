import { describe, expect, it } from 'vitest'

import { readFirstJpeg } from './mjpeg-frame'

describe('readFirstJpeg', () => {
  it('extracts one JPEG when markers cross stream chunks', async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(Uint8Array.of(0x2d, 0x2d, 0xff))
        controller.enqueue(Uint8Array.of(0xd8, 0x01, 0x02, 0xff))
        controller.enqueue(Uint8Array.of(0xd9, 0x0d, 0x0a))
        controller.close()
      },
    })

    await expect(readFirstJpeg(stream)).resolves.toEqual(
      Uint8Array.of(0xff, 0xd8, 0x01, 0x02, 0xff, 0xd9),
    )
  })
})
