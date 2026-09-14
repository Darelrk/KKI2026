import {
  ControlAckSchema,
  ControlCommandSchema,
  ControlErrorSchema,
  MAX_SAFE_INTEGER,
  PwmPairSchema,
  type ControlAck,
  type ControlError,
  type PwmPair,
} from './control-protocol'

export interface SocketLike {
  readyState: number
  onopen: ((event?: unknown) => void) | null
  onmessage: ((event: { data: unknown }) => void) | null
  onerror: ((event?: unknown) => void) | null
  onclose: ((event?: { code?: number }) => void) | null
  send(data: string): void
  close(code?: number, reason?: string): void
}

export interface ControlTimers {
  setTimeout(callback: () => void, delay: number): unknown
  clearTimeout(handle: unknown): void
  setInterval(callback: () => void, delay: number): unknown
  clearInterval(handle: unknown): void
}

export type ControlChannelState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'

export interface ControlChannelLike {
  readonly isAvailable?: boolean
  connect(): void
  close(): void
  engage(pair?: PwmPair): void
  release(): void
  setPwmPair(pair: PwmPair): boolean
}

export interface ControlChannelOptions {
  backendOrigin: string
  asvId?: string
  webSocketFactory?: (url: string) => SocketLike
  timers?: Partial<ControlTimers>
  now?: () => number
  refreshMs?: number
  ackTimeoutMs?: number
  reconnectDelays?: readonly number[]
  onAck?: (ack: ControlAck) => void
  onError?: (error: ControlError | Error) => void
  onStateChange?: (state: ControlChannelState) => void
}

const OPEN = 1
const DEFAULT_REFRESH_MS = 200
const DEFAULT_ACK_TIMEOUT_MS = 1000
const DEFAULT_RECONNECT_DELAYS = [250, 500, 1000, 2000, 5000] as const

const nativeTimers: ControlTimers = {
  setTimeout: (callback, delay) => globalThis.setTimeout(callback, delay),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as Parameters<typeof globalThis.clearTimeout>[0]),
  setInterval: (callback, delay) => globalThis.setInterval(callback, delay),
  clearInterval: (handle) => globalThis.clearInterval(handle as Parameters<typeof globalThis.clearInterval>[0]),
}

function mergeTimers(overrides?: Partial<ControlTimers>): ControlTimers {
  return { ...nativeTimers, ...overrides }
}

function normalizeOrigin(origin: string): URL {
  const url = new URL(origin)
  if (!['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol)) {
    throw new Error('backend origin must use http, https, ws, or wss')
  }
  return url
}

export function buildControlUrl(origin: string, asvId = 'default'): string {
  const url = normalizeOrigin(origin)
  if (url.protocol === 'http:') url.protocol = 'ws:'
  if (url.protocol === 'https:') url.protocol = 'wss:'
  return new URL(`/ws/control/${encodeURIComponent(asvId)}`, url.origin).toString()
}

function isOpen(socket: SocketLike | null): socket is SocketLike {
  return socket !== null && socket.readyState === OPEN
}

export class ControlChannel implements ControlChannelLike {
  private readonly url: string
  private readonly createSocket: (url: string) => SocketLike
  private readonly timers: ControlTimers
  private readonly now: () => number
  private readonly refreshMs: number
  private readonly ackTimeoutMs: number
  private readonly reconnectDelays: readonly number[]
  private readonly onAck?: (ack: ControlAck) => void
  private readonly onError?: (error: ControlError | Error) => void
  private readonly onStateChange?: (state: ControlChannelState) => void
  private socket: SocketLike | null = null
  private state: ControlChannelState = 'idle'
  private reconnectTimer: unknown = null
  private refreshTimer: unknown = null
  private reconnectAttempt = 0
  private sequence = 0
  private engaged = false
  private manuallyClosed = false
  private handlingFailure = false
  private latestPair: PwmPair = { steering_pwm: 1500, throttle_pwm: 1500 }
  private readonly pendingAcks = new Map<number, unknown>()
  private visibilityListener: (() => void) | null = null

  constructor(options: ControlChannelOptions) {
    this.url = buildControlUrl(options.backendOrigin, options.asvId ?? 'default')
    this.createSocket = options.webSocketFactory ?? ((url) => {
      return new WebSocket(url) as unknown as SocketLike
    })
    this.timers = mergeTimers(options.timers)
    this.now = options.now ?? Date.now
    this.refreshMs = Math.min(200, Math.max(1, options.refreshMs ?? DEFAULT_REFRESH_MS))
    this.ackTimeoutMs = Math.max(1, options.ackTimeoutMs ?? DEFAULT_ACK_TIMEOUT_MS)
    this.reconnectDelays = options.reconnectDelays?.length
      ? options.reconnectDelays
      : DEFAULT_RECONNECT_DELAYS
    this.onAck = options.onAck
    this.onError = options.onError
    this.onStateChange = options.onStateChange
  }

  get isAvailable(): boolean {
    return this.state === 'open'
  }

  get currentState(): ControlChannelState {
    return this.state
  }

  get currentPair(): PwmPair {
    return { ...this.latestPair }
  }

  connect(): void {
    this.manuallyClosed = false
    this.installVisibilityListener()
    if (this.socket && (this.socket.readyState === 0 || isOpen(this.socket))) return
    this.clearReconnectTimer()
    this.openSocket(false)
  }

  close(): void {
    this.manuallyClosed = true
    this.clearReconnectTimer()
    this.stopRefresh()
    this.releaseInternal(true)
    this.clearPendingAcks()
    const socket = this.socket
    this.socket = null
    this.removeVisibilityListener()
    this.setState('closed')
    if (socket && socket.readyState !== 3) {
      try {
        socket.close(1000, 'client closed')
      } catch {
        // The socket is already unusable; closed state is the safe outcome.
      }
    }
  }

  engage(pair?: PwmPair): void {
    if (pair) this.setPwmPair(pair)
    if (this.manuallyClosed) return
    this.engaged = true
    if (isOpen(this.socket)) {
      this.sendCurrent(true)
      this.startRefresh()
    }
  }

  release(): void {
    this.releaseInternal(false)
  }

  setPwmPair(pair: PwmPair): boolean {
    const parsed = PwmPairSchema.safeParse(pair)
    if (!parsed.success) return false
    this.latestPair = parsed.data
    return true
  }

  dispose(): void {
    this.close()
  }

  private openSocket(reconnecting: boolean): void {
    if (this.manuallyClosed) return
    this.setState(reconnecting ? 'reconnecting' : 'connecting')
    let socket: SocketLike
    try {
      socket = this.createSocket(this.url)
    } catch (error) {
      this.reportError(error instanceof Error ? error : new Error('control socket creation failed'))
      this.scheduleReconnect()
      return
    }
    this.socket = socket
    socket.onopen = () => this.handleOpen(socket)
    socket.onmessage = (event) => this.handleMessage(socket, event.data)
    socket.onerror = (event) => this.handleSocketFailure(socket, this.toError(event, 'control socket error'))
    socket.onclose = (event) => this.handleClose(socket, event)
    if (isOpen(socket)) this.handleOpen(socket)
  }

  private handleOpen(socket: SocketLike): void {
    if (socket !== this.socket || this.manuallyClosed) {
      try {
        socket.close(1000, 'stale control socket')
      } catch {
        // No action needed for a stale socket.
      }
      return
    }
    this.reconnectAttempt = 0
    this.sequence = 0
    this.setState('open')
    if (this.engaged) {
      this.sendCurrent(true)
      this.startRefresh()
    }
  }

  private handleMessage(socket: SocketLike, value: unknown): void {
    if (socket !== this.socket) return
    let parsed: unknown
    try {
      parsed = typeof value === 'string' ? JSON.parse(value) : value
    } catch {
      this.reportError(new Error('invalid control response JSON'))
      return
    }
    const ack = ControlAckSchema.safeParse(parsed)
    if (ack.success) {
      const timeout = this.pendingAcks.get(ack.data.seq)
      if (timeout !== undefined) {
        this.timers.clearTimeout(timeout)
        this.pendingAcks.delete(ack.data.seq)
      }
      this.onAck?.(ack.data)
      return
    }
    const error = ControlErrorSchema.safeParse(parsed)
    if (error.success) {
      this.onError?.(error.data)
      return
    }
    this.reportError(new Error('invalid control response'))
  }

  private sendCurrent(enabled: boolean): boolean {
    const socket = this.socket
    if (!isOpen(socket)) return false
    if (this.sequence >= MAX_SAFE_INTEGER) {
      this.reportError(new Error('control sequence exhausted'))
      return false
    }
    const sequence = this.sequence + 1
    const command = ControlCommandSchema.parse({
      type: 'control',
      seq: sequence,
      client_sent_at_ms: this.timestamp(),
      steering_pwm: this.latestPair.steering_pwm,
      throttle_pwm: this.latestPair.throttle_pwm,
      enabled,
    })
    try {
      socket.send(JSON.stringify(command))
    } catch (error) {
      this.handleSocketFailure(socket, error instanceof Error ? error : new Error('control send failed'))
      return false
    }
    this.sequence = sequence
    const timeout = this.timers.setTimeout(() => {
      if (!this.pendingAcks.has(sequence)) return
      this.pendingAcks.delete(sequence)
      this.reportError(new Error(`control acknowledgement timeout for sequence ${sequence}`))
    }, this.ackTimeoutMs)
    this.pendingAcks.set(sequence, timeout)
    return true
  }

  private releaseInternal(force: boolean): void {
    const shouldSend = force || this.engaged
    this.engaged = false
    this.stopRefresh()
    if (shouldSend && isOpen(this.socket)) this.sendCurrent(false)
  }

  private startRefresh(): void {
    if (this.refreshTimer !== null || !this.engaged || !isOpen(this.socket)) return
    this.refreshTimer = this.timers.setInterval(() => {
      if (!this.engaged || !isOpen(this.socket)) {
        this.stopRefresh()
        return
      }
      this.sendCurrent(true)
    }, this.refreshMs)
  }

  private stopRefresh(): void {
    if (this.refreshTimer === null) return
    this.timers.clearInterval(this.refreshTimer)
    this.refreshTimer = null
  }

  private handleSocketFailure(socket: SocketLike, error: Error): void {
    if (socket !== this.socket || this.handlingFailure) return
    this.handlingFailure = true
    this.reportError(error)
    this.releaseInternal(true)
    try {
      if (socket.readyState !== 3) socket.close(1011, 'control socket error')
    } catch {
      // close event/reconnect still provides the safety boundary.
    } finally {
      this.handlingFailure = false
    }
  }

  private handleClose(socket: SocketLike, _event?: { code?: number }): void {
    if (socket !== this.socket) return
    this.socket = null
    this.engaged = false
    this.stopRefresh()
    this.clearPendingAcks()
    if (this.manuallyClosed) {
      this.setState('closed')
      return
    }
    this.scheduleReconnect()
  }

  private scheduleReconnect(): void {
    if (this.manuallyClosed || this.reconnectTimer !== null) return
    const index = Math.min(this.reconnectAttempt, this.reconnectDelays.length - 1)
    const delay = this.reconnectDelays[index] ?? DEFAULT_RECONNECT_DELAYS.at(-1)!
    this.reconnectAttempt += 1
    this.setState('reconnecting')
    this.reconnectTimer = this.timers.setTimeout(() => {
      this.reconnectTimer = null
      this.openSocket(true)
    }, delay)
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer === null) return
    this.timers.clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
  }

  private clearPendingAcks(): void {
    for (const timeout of this.pendingAcks.values()) this.timers.clearTimeout(timeout)
    this.pendingAcks.clear()
  }

  private setState(next: ControlChannelState): void {
    if (this.state === next) return
    this.state = next
    this.onStateChange?.(next)
  }

  private timestamp(): number {
    return Math.min(MAX_SAFE_INTEGER, Math.max(0, Math.floor(this.now())))
  }

  private reportError(error: Error): void {
    this.onError?.(error)
  }

  private toError(value: unknown, fallback: string): Error {
    return value instanceof Error ? value : new Error(fallback)
  }

  private installVisibilityListener(): void {
    if (this.visibilityListener || typeof document === 'undefined') return
    this.visibilityListener = () => {
      if (document.visibilityState === 'hidden') this.release()
    }
    document.addEventListener('visibilitychange', this.visibilityListener)
  }

  private removeVisibilityListener(): void {
    if (!this.visibilityListener || typeof document === 'undefined') return
    document.removeEventListener('visibilitychange', this.visibilityListener)
    this.visibilityListener = null
  }
}

export function createControlChannel(options: ControlChannelOptions): ControlChannel {
  return new ControlChannel(options)
}
