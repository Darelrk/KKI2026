import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DashboardShell } from './dashboard-shell'
import { downloadCameraCapture } from '../lib/camera-capture'

import type * as CameraCaptureModule from '../lib/camera-capture'

vi.mock('../lib/camera-capture', async () => {
  const actual = await vi.importActual<typeof CameraCaptureModule>(
    '../lib/camera-capture',
  )
  return { ...actual, downloadCameraCapture: vi.fn() }
})

const canvasContext = {
  clearRect: vi.fn(),
  strokeRect: vi.fn(),
  fillText: vi.fn(),
  strokeStyle: '',
  fillStyle: '',
  lineWidth: 0,
  font: '',
}

beforeEach(() => {
  vi.mocked(downloadCameraCapture).mockReset()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    canvasContext as unknown as CanvasRenderingContext2D,
  )
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function requestCapture() {
  const view = render(
    <DashboardShell
      live={null}
      underwaterFrame={null}
      captureRequestCount={0}
    />,
  )
  view.rerender(
    <DashboardShell
      live={null}
      underwaterFrame={null}
      captureRequestCount={1}
    />,
  )
  return view
}

describe('Dashboard camera capture', () => {
  it('downloads separate surface and underwater captures per request', async () => {
    vi.mocked(downloadCameraCapture).mockImplementation(async (source) =>
      source === 'surface'
        ? 'asv-surface-20260809-123456.jpg'
        : 'asv-underwater-20260809-123456.jpg',
    )

    const view = requestCapture()

    expect(
      await screen.findByText(
        'Capture saved: asv-surface-20260809-123456.jpg, asv-underwater-20260809-123456.jpg',
      ),
    ).toBeInTheDocument()
    expect(downloadCameraCapture).toHaveBeenCalledTimes(2)
    expect(downloadCameraCapture).toHaveBeenNthCalledWith(
      1,
      'surface',
      expect.any(Date),
    )
    expect(downloadCameraCapture).toHaveBeenNthCalledWith(
      2,
      'underwater',
      expect.any(Date),
    )
    expect(vi.mocked(downloadCameraCapture).mock.calls[0]?.[1]).toBe(
      vi.mocked(downloadCameraCapture).mock.calls[1]?.[1],
    )
    expect(screen.queryByRole('button', { name: /capture/i })).toBeNull()

    view.rerender(
      <DashboardShell
        live={null}
        underwaterFrame={null}
        captureRequestCount={1}
      />,
    )
    expect(downloadCameraCapture).toHaveBeenCalledTimes(2)
  })

  it('saves surface without waiting for underwater to settle', async () => {
    let finishUnderwater: (filename: string) => void = () => undefined
    vi.mocked(downloadCameraCapture).mockImplementation((source) => {
      if (source === 'surface') {
        return Promise.resolve('asv-surface-20260809-123456.jpg')
      }
      return new Promise((resolve) => {
        finishUnderwater = resolve
      })
    })

    requestCapture()

    expect(
      await screen.findByText('Capture saved: asv-surface-20260809-123456.jpg'),
    ).toBeInTheDocument()

    finishUnderwater('asv-underwater-20260809-123456.jpg')
    expect(
      await screen.findByText(
        'Capture saved: asv-surface-20260809-123456.jpg, asv-underwater-20260809-123456.jpg',
      ),
    ).toBeInTheDocument()
  })
  it('saves the surface capture when the underwater feed is unavailable', async () => {
    vi.mocked(downloadCameraCapture).mockImplementation(async (source) => {
      if (source === 'underwater') throw new Error('Underwater feed offline')
      return 'asv-surface-20260809-123456.jpg'
    })

    requestCapture()

    expect(
      await screen.findByText('Capture saved: asv-surface-20260809-123456.jpg'),
    ).toBeInTheDocument()
    expect(downloadCameraCapture).toHaveBeenCalledTimes(2)
  })

  it('saves the underwater capture when the surface feed is unavailable', async () => {
    vi.mocked(downloadCameraCapture).mockImplementation(async (source) => {
      if (source === 'surface') throw new Error('Surface feed offline')
      return 'asv-underwater-20260809-123456.jpg'
    })

    requestCapture()

    expect(
      await screen.findByText(
        'Capture saved: asv-underwater-20260809-123456.jpg',
      ),
    ).toBeInTheDocument()
    expect(downloadCameraCapture).toHaveBeenCalledTimes(2)
  })

  it('reports failure only when neither feed can be captured', async () => {
    vi.mocked(downloadCameraCapture).mockRejectedValue(
      new Error('Camera feed offline'),
    )

    requestCapture()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Capture failed. Verify both camera feeds.',
    )
  })
})
