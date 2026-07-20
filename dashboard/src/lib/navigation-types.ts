export type GpsPoint = {
  latitude: number
  longitude: number
  captured_at: string
}

export type NavigationTelemetry = {
  position: GpsPoint | null
  heading_deg: number | null
  speed_mps: number | null
  track: readonly GpsPoint[]
}

export const emptyNavigationTelemetry: NavigationTelemetry = {
  position: null,
  heading_deg: null,
  speed_mps: null,
  track: [],
}
