import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DashboardShell } from './dashboard-shell'
import { captureMediaFrame, downloadCameraCapture } from '../lib/camera-capture'

import type * as CameraCaptureModule from '../lib/camera-capture'

vi.mock('../lib/camera-capture', async () => {
  const actual = await vi.importActual<typeof CameraCaptureModule>(
    '../lib/camera-capture',
  )
  return {
    ...actual,
    captureMediaFrame: vi.fn(),
    downloadCameraCapture: vi.fn(),
  }
})

const canvasContext = {
  clearRect: vi.fn(),
  fillRect: vi.fn(),
  drawImage: vi.fn(),
  strokeRect: vi.fn(),
  fillText: vi.fn(),
  strokeStyle: '',
  fillStyle: '',
  lineWidth: 0,
  font: '',
}

beforeEach(() => {
  vi.mocked(captureMediaFrame).mockReset()
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
  it('downloads separate surface and underwater captures per request', async () => {
    const surface = document.createElement('canvas')
    const underwater = document.createElement('canvas')
    surface.width = underwater.width = 640
    surface.height = underwater.height = 360
    vi.mocked(captureMediaFrame)
      .mockReturnValueOnce(surface)
      .mockReturnValueOnce(underwater)
      .mockReturnValueOnce(surface)
      .mockReturnValueOnce(underwater)
    vi.mocked(downloadCameraCapture)
      .mockReturnValueOnce('asv-surface-20260809-123456.jpg')
      .mockReturnValueOnce('asv-underwater-20260809-123456.jpg')
      .mockReturnValueOnce('asv-surface-20260809-123457.jpg')
      .mockReturnValueOnce('asv-underwater-20260809-123457.jpg')

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
        screen.getByText(
          'Capture saved: asv-surface-20260809-123456.jpg, asv-underwater-20260809-123456.jpg',
        ),
      ).toBeInTheDocument()
    })
    expect(downloadCameraCapture).toHaveBeenCalledTimes(2)
    expect(downloadCameraCapture).toHaveBeenNthCalledWith(
      1,
      surface,
      'surface',
      expect.any(Date),
    )
    expect(downloadCameraCapture).toHaveBeenNthCalledWith(
      2,
      underwater,
      'underwater',
      expect.any(Date),
    )
    expect(vi.mocked(downloadCameraCapture).mock.calls[0]?.[2]).toBe(
      vi.mocked(downloadCameraCapture).mock.calls[1]?.[2],
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

    view.rerender(
      <DashboardShell
        live={null}
        underwaterFrame={null}
        captureRequestCount={2}
      />,
    )
    await waitFor(() => {
      expect(downloadCameraCapture).toHaveBeenCalledTimes(4)
    })
  })

  it('does not download when the surface frame fails', async () => {
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
    expect(downloadCameraCapture).not.toHaveBeenCalled()
  })

  it('does not download a partial capture when the underwater frame fails', async () => {
    const surface = document.createElement('canvas')
    vi.mocked(captureMediaFrame)
      .mockReturnValueOnce(surface)
      .mockImplementationOnce(() => {
        throw new Error('Underwater camera frame is not ready')
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
    expect(downloadCameraCapture).not.toHaveBeenCalled()
  })
})
