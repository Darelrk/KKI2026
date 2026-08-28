import { z } from 'zod'

export const MAX_SAFE_INTEGER = Number.MAX_SAFE_INTEGER
export const PWM_MIN = 1000
export const PWM_MAX = 2000

export const CONTROL_ERROR_CODES = [
  'invalid_json',
  'invalid_message',
  'origin_not_allowed',
] as const

export const CONTROL_REJECT_REASONS = [
  'stale_sequence',
  'remote_control_disabled',
  'runtime_mode_autonomous',
  'pixhawk_unavailable',
  'flightmode_not_manual',
  'pilot_input_active',
  'superseded',
] as const

const safeInteger = z.number().finite().int().min(0).max(MAX_SAFE_INTEGER)
const sequence = safeInteger.min(1)
const pwm = z.number().finite().int().min(PWM_MIN).max(PWM_MAX)
export const PwmPairSchema = z
  .object({
    steering_pwm: pwm,
    throttle_pwm: pwm,
  })
  .strict()

export const ControlCommandSchema = z
  .object({
    type: z.literal('control'),
    seq: sequence,
    client_sent_at_ms: safeInteger,
    steering_pwm: pwm,
    throttle_pwm: pwm,
    enabled: z.boolean(),
  })
  .strict()

export const ControlAckSchema = z
  .object({
    type: z.literal('ack'),
    seq: sequence,
    accepted: z.boolean(),
    reason: z.enum(CONTROL_REJECT_REASONS).nullable(),
    client_sent_at_ms: safeInteger,
    server_received_at_ms: safeInteger,
  })
  .strict()
  .superRefine((ack, context) => {
    if (ack.accepted !== (ack.reason === null)) {
      context.addIssue({
        code: 'custom',
        path: ['reason'],
        message: 'accepted must be true exactly when reason is null',
      })
    }
  })

export const ControlErrorSchema = z
  .object({
    type: z.literal('error'),
    code: z.enum(CONTROL_ERROR_CODES),
    message: z.string().min(1),
  })
  .strict()

export const ControlInboundSchema = z.union([ControlAckSchema, ControlErrorSchema])

export type ControlCommand = z.infer<typeof ControlCommandSchema>
export type ControlAck = z.infer<typeof ControlAckSchema>
export type ControlError = z.infer<typeof ControlErrorSchema>
export type ControlInbound = z.infer<typeof ControlInboundSchema>
export type ControlRejectReason = (typeof CONTROL_REJECT_REASONS)[number]
export type ControlErrorCode = (typeof CONTROL_ERROR_CODES)[number]
export type PwmPair = z.infer<typeof PwmPairSchema>

export function parseControlInbound(value: unknown): ControlInbound | null {
  const result = ControlInboundSchema.safeParse(value)
  return result.success ? result.data : null
}
