import { useState } from 'react'

import type { PointerEvent as ReactPointerEvent, WheelEvent } from 'react'

const storageKey = 'kki2026.site-overlay-nudge'
const neutralNudge: OverlayNudge = { x: 0, y: 0, scale: 1 }
const scaleStep = 1.08
const minimumScale = 0.3
const maximumScale = 3

export type OverlayNudge = { x: number; y: number; scale: number }

type DragOrigin = {
  pointerX: number
  pointerY: number
  nudgeX: number
  nudgeY: number
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000
}

function readStoredNudge(): OverlayNudge {
  if (typeof window === 'undefined') {
    return neutralNudge
  }
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) {
      return neutralNudge
    }
    const parsed = JSON.parse(raw) as Partial<OverlayNudge> | null
    if (
      typeof parsed !== 'object' ||
      parsed === null ||
      !Number.isFinite(parsed.x) ||
      !Number.isFinite(parsed.y)
    ) {
      return neutralNudge
    }
    const scale = Number.isFinite(parsed.scale)
      ? Math.min(maximumScale, Math.max(minimumScale, parsed.scale as number))
      : 1
    return { x: parsed.x as number, y: parsed.y as number, scale }
  } catch {
    return neutralNudge
  }
}

function persist(nudge: OverlayNudge): void {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(nudge))
  } catch {
    // A blocked storage quota must not break the map interaction.
  }
}

/**
 * Lets the operator drag and resize the course overlay so it lines up with the
 * pool on the satellite base map: press and move to reposition, wheel to
 * resize. Offsets are kept in overlay (viewBox) units and persisted locally,
 * because the right values depend on the imagery Google happens to serve
 * rather than on anything we can compute.
 */
export function useOverlayNudge() {
  const [nudge, setNudge] = useState<OverlayNudge>(readStoredNudge)
  const [origin, setOrigin] = useState<DragOrigin | null>(null)

  const onPointerDown = (event: ReactPointerEvent<SVGGElement>) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    setOrigin({
      pointerX: event.clientX,
      pointerY: event.clientY,
      nudgeX: nudge.x,
      nudgeY: nudge.y,
    })
  }

  const onPointerMove = (event: ReactPointerEvent<SVGGElement>) => {
    if (!origin) {
      return
    }
    const rect = event.currentTarget.ownerSVGElement?.getBoundingClientRect()
    // The overlay uses a square viewBox fitted with `meet`, so one viewBox
    // unit is the shorter rendered side divided by 100.
    const renderedSize = Math.min(rect?.width ?? 0, rect?.height ?? 0)
    if (renderedSize <= 0) {
      return
    }
    const unitsPerPixel = 100 / renderedSize
    setNudge((current) => ({
      ...current,
      x: origin.nudgeX + (event.clientX - origin.pointerX) * unitsPerPixel,
      y: origin.nudgeY + (event.clientY - origin.pointerY) * unitsPerPixel,
    }))
  }

  const endDrag = (event: ReactPointerEvent<SVGGElement>) => {
    if (!origin) {
      return
    }
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    setOrigin(null)
    persist(nudge)
  }

  const onWheel = (event: WheelEvent<SVGGElement>) => {
    if (event.deltaY === 0) {
      return
    }
    const factor = event.deltaY < 0 ? scaleStep : 1 / scaleStep
    setNudge((current) => {
      const next = {
        ...current,
        scale: round(
          Math.min(
            maximumScale,
            Math.max(minimumScale, current.scale * factor),
          ),
        ),
      }
      persist(next)
      return next
    })
  }

  return {
    nudge,
    dragging: origin !== null,
    dragHandlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
      onWheel,
    },
  }
}
