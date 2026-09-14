import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DashboardShell } from './dashboard-shell'
import {
  captureMediaFrame,
  combineCameraFrames,
  downloadCameraCapture,
} from '../lib/camera-capture'

import type * as CameraCaptureModule from '../lib/camera-capture'

vi.mock('../lib/camera-capture', async () => {
  const actual = await vi.importActual<typeof CameraCaptureModule>(
    '../lib/camera-capture',
  )
  return {
    ...actual,
    captureMediaFrame: vi.fn(),
    combineCameraFrames: vi.fn(),
    downloadCameraCapture: vi.fn(),
  }
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
  vi.mocked(captureMediaFrame).mockReset()
  vi.mocked(combineCameraFrames).mockReset()
  vi.mocked(downloadCameraCapture).mockReset()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    canvasContext as unknown as CanvasRenderingContext2D,
  )
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('Dashboard camera capture', () => {
  it('downloads one combined capture from both camera feeds per request', async () => {
    const surface = document.createElement('canvas')
    const underwater = document.createElement('canvas')
    const combined = document.createElement('canvas')
    vi.mocked(captureMediaFrame)
      .mockReturnValueOnce(surface)
      .mockReturnValueOnce(underwater)
      .mockReturnValueOnce(surface)
      .mockReturnValueOnce(underwater)
    vi.mocked(combineCameraFrames).mockReturnValue(combined)
    vi.mocked(downloadCameraCapture)
      .mockReturnValueOnce('asv-capture-20260809-123456.jpg')
      .mockReturnValueOnce('asv-capture-20260809-123457.jpg')

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

    await waitFor(() => {
      expect(
        screen.getByText('Capture saved: asv-capture-20260809-123456.jpg'),
      ).toBeInTheDocument()
    })
    expect(downloadCameraCapture).toHaveBeenCalledOnce()
    expect(combineCameraFrames).toHaveBeenCalledWith(surface, underwater)
    expect(screen.queryByRole('button', { name: /capture/i })).toBeNull()

    view.rerender(
      <DashboardShell
        live={null}
        underwaterFrame={null}
        captureRequestCount={1}
      />,
    )
    expect(downloadCameraCapture).toHaveBeenCalledOnce()

    view.rerender(
      <DashboardShell
        live={null}
        underwaterFrame={null}
        captureRequestCount={2}
      />,
    )
    await waitFor(() => {
      expect(downloadCameraCapture).toHaveBeenCalledTimes(2)
    })
  })

  it('does not download a partial capture when either feed fails', async () => {
    vi.mocked(captureMediaFrame).mockImplementationOnce(() => {
      throw new Error('Surface camera frame is not ready')
    })

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

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Capture failed. Verify both camera feeds.',
    )
    expect(combineCameraFrames).not.toHaveBeenCalled()
    expect(downloadCameraCapture).not.toHaveBeenCalled()
  })
})
