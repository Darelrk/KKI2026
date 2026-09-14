import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { ControlChannel, type SocketLike } from '../src/lib/control-channel'

type Handler = ((event?: unknown) => void) | null

class FakeSocket implements SocketLike {
  static instances: FakeSocket[] = []
  readonly url: string
  readonly sent: string[] = []
  readyState = 0
  onopen: Handler = null
  onmessage: Handler = null
  onerror: Handler = null
  onclose: Handler = null

  constructor(url: string) {
    this.url = url
    FakeSocket.instances.push(this)
  }

  send(payload: string) {
    if (this.readyState !== 1) throw new Error('socket is not open')
    this.sent.push(payload)
  }

  close() {
    if (this.readyState === 3) return
    this.readyState = 3
    this.onclose?.({ code: 1000 })
  }

  open() {
    this.readyState = 1
    this.onopen?.()
  }

  message(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }

  fail() {
    this.onerror?.(new Error('socket failure'))
  }

  remoteClose() {
    this.readyState = 3
    this.onclose?.({ code: 1006 })
  }
}

const lastCommand = (socket: FakeSocket) => JSON.parse(socket.sent.at(-1) ?? '{}')

beforeEach(() => {
  vi.useFakeTimers()
  FakeSocket.instances = []
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ControlChannel', () => {
  it('owns one socket, starts sequence at one, and sends the latest PWM pair', () => {
    const channel = new ControlChannel({
      backendOrigin: 'https://remote.example.test',
      webSocketFactory: (url) => new FakeSocket(url),
      now: () => 100,
    })
    channel.connect()
    channel.connect()
    expect(FakeSocket.instances).toHaveLength(1)
    expect(FakeSocket.instances[0]?.url).toBe('wss://remote.example.test/ws/control/default')

    const socket = FakeSocket.instances[0]!
    socket.open()
    channel.setPwmPair({ steering_pwm: 1400, throttle_pwm: 1600 })
    channel.engage()
    expect(lastCommand(socket)).toMatchObject({
      type: 'control',
      seq: 1,
      steering_pwm: 1400,
      throttle_pwm: 1600,
      enabled: true,
    })
    channel.setPwmPair({ steering_pwm: 1450, throttle_pwm: 1650 })
    expect(socket.sent).toHaveLength(1)
    vi.advanceTimersByTime(200)
    expect(lastCommand(socket)).toMatchObject({
      type: 'control',
      seq: 2,
      steering_pwm: 1450,
      throttle_pwm: 1650,
      enabled: true,
    })
    expect(socket.sent).toHaveLength(2)
  })

  it('refreshes enabled control at most 200ms and coalesces pending latest values', () => {
    const channel = new ControlChannel({
      backendOrigin: 'https://remote.example.test',
      webSocketFactory: (url) => new FakeSocket(url),
      now: () => 100,
      refreshMs: 200,
    })
    channel.connect()
    const socket = FakeSocket.instances[0]!
    socket.open()
    channel.engage()
    channel.setPwmPair({ steering_pwm: 1100, throttle_pwm: 1900 })
    channel.setPwmPair({ steering_pwm: 1200, throttle_pwm: 1800 })
    expect(socket.sent).toHaveLength(1)

    const beforeRefresh = socket.sent.length
    vi.advanceTimersByTime(199)
    expect(socket.sent).toHaveLength(beforeRefresh)
    vi.advanceTimersByTime(1)
    expect(socket.sent).toHaveLength(beforeRefresh + 1)
    expect(lastCommand(socket)).toMatchObject({
      steering_pwm: 1200,
      throttle_pwm: 1800,
      enabled: true,
    })
  })

  it('releases on explicit release, socket errors, and close without auto-enable', () => {
    const channel = new ControlChannel({
      backendOrigin: 'https://remote.example.test',
      webSocketFactory: (url) => new FakeSocket(url),
      now: () => 100,
    })
    channel.connect()
    const socket = FakeSocket.instances[0]!
    socket.open()
    channel.engage()
    channel.release()
    expect(lastCommand(socket)).toMatchObject({ enabled: false })
    channel.engage()
    const sentBeforeError = socket.sent.length
    socket.fail()
    expect(socket.sent.length).toBe(sentBeforeError + 1)
    expect(lastCommand(socket)).toMatchObject({ enabled: false })

    socket.remoteClose()
    vi.advanceTimersByTime(250)
    const reconnect = FakeSocket.instances[1]!
    reconnect.open()
    expect(reconnect.sent).toHaveLength(0)
    channel.close()
    expect(lastCommand(reconnect)).toMatchObject({ enabled: false })
  })

  it('handles internal ack/error callbacks and bounded reconnect backoff', () => {
    const onAck = vi.fn()
    const onError = vi.fn()
    const channel = new ControlChannel({
      backendOrigin: 'https://remote.example.test',
      webSocketFactory: (url) => new FakeSocket(url),
      onAck,
      onError,
    })
    channel.connect()
    const socket = FakeSocket.instances[0]!
    socket.open()
    socket.message({
      type: 'ack',
      seq: 1,
      accepted: true,
      reason: null,
      client_sent_at_ms: 1,
      server_received_at_ms: 2,
    })
    socket.message({ type: 'error', code: 'invalid_json', message: 'bad frame' })
    expect(onAck).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledTimes(1)

    socket.remoteClose()
    vi.advanceTimersByTime(249)
    expect(FakeSocket.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeSocket.instances).toHaveLength(2)
    FakeSocket.instances[1]!.remoteClose()
    vi.advanceTimersByTime(500)
    expect(FakeSocket.instances).toHaveLength(3)
    FakeSocket.instances[2]!.remoteClose()
    vi.advanceTimersByTime(1000)
    expect(FakeSocket.instances).toHaveLength(4)
    channel.close()
  })

  it('does not use fetch or POST for control', () => {
    const fetch = vi.fn(() => Promise.reject(new Error('fetch must not be called')))
    vi.stubGlobal('fetch', fetch)
    const channel = new ControlChannel({
      backendOrigin: 'https://remote.example.test',
      webSocketFactory: (url) => new FakeSocket(url),
    })
    channel.connect()
    FakeSocket.instances[0]!.open()
    channel.engage()
    expect(fetch).not.toHaveBeenCalled()
  })
})
