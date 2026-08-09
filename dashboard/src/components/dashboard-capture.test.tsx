import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  it('downloads one combined capture from both camera feeds', async () => {
    const surface = document.createElement('canvas')
    const underwater = document.createElement('canvas')
    const combined = document.createElement('canvas')
    vi.mocked(captureMediaFrame)
      .mockReturnValueOnce(surface)
      .mockReturnValueOnce(underwater)
    vi.mocked(combineCameraFrames).mockReturnValue(combined)
    vi.mocked(downloadCameraCapture).mockReturnValue(
      'asv-capture-20260809-123456.jpg',
    )

    render(<DashboardShell live={null} underwaterFrame={null} />)
    fireEvent.click(
      screen.getByRole('button', { name: 'Capture both cameras' }),
    )

    await waitFor(() => {
      expect(
        screen.getByText('Capture saved: asv-capture-20260809-123456.jpg'),
      ).toBeInTheDocument()
    })
    expect(downloadCameraCapture).toHaveBeenCalledOnce()
    expect(combineCameraFrames).toHaveBeenCalledWith(surface, underwater)
    expect(
      screen.getByRole('button', { name: 'Capture both cameras' }),
    ).toBeEnabled()
  })

  it('does not download a partial capture when either feed fails', async () => {
    vi.mocked(captureMediaFrame).mockImplementationOnce(() => {
      throw new Error('Surface camera frame is not ready')
    })

    render(<DashboardShell live={null} underwaterFrame={null} />)
    fireEvent.click(
      screen.getByRole('button', { name: 'Capture both cameras' }),
    )

    expect(
      await screen.findByRole('alert'),
    ).toHaveTextContent('Capture failed. Verify both camera feeds.')
    expect(combineCameraFrames).not.toHaveBeenCalled()
    expect(downloadCameraCapture).not.toHaveBeenCalled()
  })
})
