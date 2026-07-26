"""Bench-test steering servo through MAVLink RC override.

The script never arms, disarms, changes mode, or writes parameters. It injects
steering/throttle RC values for a short sequence, then returns both channels to
neutral and releases the override.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

MAV_IGNORE = 65535
MAV_RELEASE = 0


def _validate_channel(channel: int, name: str) -> None:
    if not 1 <= channel <= 8:
        raise ValueError(f"{name} harus antara 1 dan 8")


def _validate_pwm(pwm: int, name: str) -> None:
    if not 1000 <= pwm <= 2000:
        raise ValueError(f"{name} harus antara 1000 dan 2000 us")


def build_rc_override(
    *,
    steering_channel: int,
    steering_pwm: int,
    throttle_channel: int,
    throttle_pwm: int,
) -> tuple[int, ...]:
    """Build MAVLink RC_CHANNELS_OVERRIDE values for channels 1-8."""
    _validate_channel(steering_channel, "steering_channel")
    _validate_channel(throttle_channel, "throttle_channel")
    if steering_channel == throttle_channel:
        raise ValueError("steering_channel dan throttle_channel harus berbeda")
    _validate_pwm(steering_pwm, "steering_pwm")
    _validate_pwm(throttle_pwm, "throttle_pwm")

    channels = [MAV_IGNORE] * 8
    channels[steering_channel - 1] = steering_pwm
    channels[throttle_channel - 1] = throttle_pwm
    return tuple(channels)


def _send_override(master: Any, channels: tuple[int, ...]) -> None:
    master.mav.rc_channels_override_send(
        master.target_system,
        master.target_component,
        *channels,
    )


def _hold_override(master: Any, channels: tuple[int, ...], seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _send_override(master, channels)
        time.sleep(0.1)


def _neutral_and_release(
    master: Any,
    *,
    steering_channel: int,
    throttle_channel: int,
) -> None:
    neutral = build_rc_override(
        steering_channel=steering_channel,
        steering_pwm=1500,
        throttle_channel=throttle_channel,
        throttle_pwm=1500,
    )
    for _ in range(5):
        _send_override(master, neutral)
        time.sleep(0.1)

    release = (MAV_RELEASE,) * 8
    for _ in range(3):
        _send_override(master, release)
        time.sleep(0.1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Uji gerak steering servo melalui MAVLink RC override"
    )
    parser.add_argument(
        "--bench-test",
        action="store_true",
        help="Konfirmasi propeller dilepas dan kapal diamankan",
    )
    parser.add_argument(
        "--endpoint",
        default="COM5",
        help="Port/URI MAVLink, misalnya COM5 atau /dev/ttyACM0",
    )
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--steering-channel", type=int, default=1)
    parser.add_argument("--throttle-channel", type=int, default=3)
    parser.add_argument("--left", type=int, default=1100)
    parser.add_argument("--center", type=int, default=1500)
    parser.add_argument("--right", type=int, default=1900)
    parser.add_argument("--throttle-neutral", type=int, default=1500)
    parser.add_argument("--hold", type=float, default=1.5)
    return parser.parse_args()


def run_test(args: argparse.Namespace) -> None:
    if not args.bench_test:
        raise SystemExit(
            "Tambahkan --bench-test setelah propeller dilepas dan kapal diamankan."
        )

    try:
        from pymavlink import mavutil
    except ImportError as exc:
        raise SystemExit("pymavlink belum terpasang: python -m pip install pymavlink") from exc

    for name, pwm in (
        ("left", args.left),
        ("center", args.center),
        ("right", args.right),
        ("throttle-neutral", args.throttle_neutral),
    ):
        _validate_pwm(pwm, name)

    master = None
    try:
        print(f"Menghubungkan ke {args.endpoint}...")
        try:
            master = mavutil.mavlink_connection(
                args.endpoint,
                baud=args.baud,
                autoreconnect=False,
                source_system=255,
                source_component=190,
            )
        except (PermissionError, OSError) as exc:
            raise SystemExit(
                f"Port {args.endpoint} tidak bisa dibuka: {exc}\n"
                "Tutup QGroundControl, Mission Planner, dan backend bridge, "
                "lalu coba lagi."
            ) from exc

        try:
            master.wait_heartbeat(timeout=10)
        except Exception as exc:
            raise SystemExit(f"Heartbeat Pixhawk tidak diterima: {exc}") from exc

        print(
            "Terhubung. Script tidak mengirim ARM/DISARM, tidak mengubah mode, "
            "dan tidak menulis parameter."
        )
        print(
            f"Uji steering CH{args.steering_channel}; throttle CH{args.throttle_channel} "
            "dipertahankan netral."
        )

        for label, pwm in (
            ("KIRI", args.left),
            ("TENGAH", args.center),
            ("KANAN", args.right),
            ("TENGAH", args.center),
        ):
            print(f"{label}: steering={pwm}us")
            channels = build_rc_override(
                steering_channel=args.steering_channel,
                steering_pwm=pwm,
                throttle_channel=args.throttle_channel,
                throttle_pwm=args.throttle_neutral,
            )
            _hold_override(master, channels, args.hold)
    except KeyboardInterrupt:
        print("\nDihentikan pengguna.")
    finally:
        if master is not None:
            try:
                _neutral_and_release(
                    master,
                    steering_channel=args.steering_channel,
                    throttle_channel=args.throttle_channel,
                )
            except Exception as exc:
                print(f"Peringatan: gagal mengirim neutral/release: {exc}")
            master.close()
            print("Koneksi ditutup.")


def main() -> None:
    run_test(parse_args())


if __name__ == "__main__":
    main()
