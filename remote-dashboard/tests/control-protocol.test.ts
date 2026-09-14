import {
  CONTROL_ERROR_CODES,
  MAX_SAFE_INTEGER,
  ControlAckSchema,
  ControlCommandSchema,
  ControlErrorSchema,
} from '../src/lib/control-protocol'

const validCommand = {
  type: 'control' as const,
  seq: 1,
  client_sent_at_ms: 1_787_923_200_123,
  steering_pwm: 1490,
  throttle_pwm: 1550,
  enabled: true,
}

describe('remote control protocol', () => {
  it('accepts the strict backend command shape and safe integer maximum', () => {
    expect(ControlCommandSchema.safeParse(validCommand).success).toBe(true)
    expect(
      ControlCommandSchema.safeParse({
        ...validCommand,
        seq: MAX_SAFE_INTEGER,
        client_sent_at_ms: MAX_SAFE_INTEGER,
        steering_pwm: 1000,
        throttle_pwm: 2000,
      }).success,
    ).toBe(true)
  })

  it('rejects uppercase or non-literal message types', () => {
    expect(ControlCommandSchema.safeParse({ ...validCommand, type: 'CONTROL' }).success).toBe(false)
    expect(ControlAckSchema.safeParse({
      type: 'ACK',
      seq: 1,
      accepted: true,
      reason: null,
      client_sent_at_ms: 1,
      server_received_at_ms: 2,
    }).success).toBe(false)
  })

  it('rejects non-object command payloads', () => {
    for (const value of [null, [], 'control', 1, true]) {
      expect(ControlCommandSchema.safeParse(value).success).toBe(false)
    }
  })

  it.each([
    ['fractional sequence', { seq: 1.5 }],
    ['string PWM', { steering_pwm: '1500' }],
    ['boolean sequence', { seq: true }],
    ['low steering PWM', { steering_pwm: 999 }],
    ['high throttle PWM', { throttle_pwm: 2001 }],
    ['negative timestamp', { client_sent_at_ms: -1 }],
    ['unsafe timestamp', { client_sent_at_ms: MAX_SAFE_INTEGER + 1 }],
    ['extra field', { extra: true }],
    ['missing field', { throttle_pwm: undefined }],
  ])('rejects %s', (_name, patch) => {
    expect(ControlCommandSchema.safeParse({ ...validCommand, ...patch }).success).toBe(false)
  })

  it('keeps acknowledgement and error schemas strict and coherent', () => {
    expect(ControlAckSchema.safeParse({
      type: 'ack',
      seq: 2,
      accepted: false,
      reason: 'runtime_mode_autonomous',
      client_sent_at_ms: 10,
      server_received_at_ms: 11,
    }).success).toBe(true)
    expect(ControlAckSchema.safeParse({
      type: 'ack',
      seq: 2,
      accepted: true,
      reason: 'runtime_mode_autonomous',
      client_sent_at_ms: 10,
      server_received_at_ms: 11,
    }).success).toBe(false)

    expect(ControlErrorSchema.safeParse({
      type: 'error',
      code: CONTROL_ERROR_CODES[0],
      message: 'invalid control frame',
    }).success).toBe(true)
    expect(ControlErrorSchema.safeParse({
      type: 'error',
      code: 'secret_leak',
      message: 'bad',
      extra: true,
    }).success).toBe(false)
  })
  it.each([
    ['zero sequence', { seq: 0 }],
    ['negative client timestamp', { client_sent_at_ms: -1 }],
    ['unsafe server timestamp', { server_received_at_ms: MAX_SAFE_INTEGER + 1 }],
    ['unknown rejection reason', { accepted: false, reason: 'unknown' }],
  ])('rejects invalid acknowledgement %s', (_name, patch) => {
    expect(ControlAckSchema.safeParse({
      type: 'ack',
      seq: 2,
      accepted: true,
      reason: null,
      client_sent_at_ms: 10,
      server_received_at_ms: 11,
      ...patch,
    }).success).toBe(false)
  })
})
