"""Script diagnostik read-only pre-arm Pixhawk / ArduPilot.

Mendengarkan pesan STATUSTEXT dan HEARTBEAT dari Pixhawk tanpa mengirim
perintah MAVLink atau mengubah parameter.
"""

from __future__ import annotations

import argparse
import sys
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnostik pre-arm read-only untuk Pixhawk/ArduPilot"
    )
    parser.add_argument(
        "--endpoint",
        default="COM5",
        help="Port serial atau URI MAVLink (misal: COM5, /dev/ttyACM0, tcp:127.0.0.1:5760)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="Baud rate koneksi serial (default: 115200)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Durasi maksimum mendengarkan dalam detik (0 = tanpa batas)",
    )
    return parser.parse_args()


def run_diagnostics(endpoint: str, baud: int, timeout: float) -> None:
    try:
        from pymavlink import mavutil
    except ImportError:
        print("Error: `pymavlink` tidak terpasang. Jalankan: pip install pymavlink")
        sys.exit(1)

    print(f"[*] Menghubungkan ke Pixhawk di {endpoint} ({baud} baud)...")
    try:
        connection = mavutil.mavlink_connection(
            endpoint,
            baud=baud,
            autoreconnect=True,
            source_system=255,
            source_component=190,
        )
    except Exception as exc:
        print(f"[!] Gagal membuka {endpoint}: {type(exc).__name__}: {exc}")
        print("[!] Pastikan Mission Planner, QGroundControl, atau backend bridge ditutup.")
        sys.exit(1)

    print("[+] Terhubung! Mendengarkan MAVLink telemetry...")
    print("[*] SILAKAN COBA ARM MELALUI REMOTE FLYSKY FS-i6 SEKARANG.")
    print("    Pesan penolakan 'PreArm: ...' akan muncul di bawah ini secara realtime.\n")

    start_time = time.monotonic()
    last_heartbeat = 0.0

    try:
        while True:
            if timeout > 0 and (time.monotonic() - start_time) > timeout:
                print(f"\n[*] Waktu batas diagnostik ({timeout}s) selesai.")
                break

            try:
                msg = connection.recv_match(
                    type=["HEARTBEAT", "STATUSTEXT"],
                    blocking=True,
                    timeout=1.0,
                )
            except Exception as exc:
                print(f"[!] Exception saat membaca serial: {exc}")
                print("[!] Kemungkinan port terputus atau bentrok dengan aplikasi lain.")
                break

            if msg is None:
                continue

            msg_type = msg.get_type()

            if msg_type == "HEARTBEAT":
                now = time.monotonic()
                if now - last_heartbeat >= 5.0:
                    last_heartbeat = now
                    base_mode = getattr(msg, "base_mode", 0)
                    armed = bool(base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                    system_status = getattr(msg, "system_status", "UNKNOWN")
                    print(f"[HEARTBEAT] Armed: {armed} | Status: {system_status}")

            elif msg_type == "STATUSTEXT":
                text = getattr(msg, "text", "").strip()
                severity = getattr(msg, "severity", None)
                if text:
                    prefix = "[STATUSTEXT]"
                    if "PreArm" in text or "Arm" in text:
                        prefix = "[PRE-ARM REJECT]"
                    print(f"{prefix} (severity {severity}): {text}")

    except KeyboardInterrupt:
        print("\n[*] Diagnostik dihentikan oleh pengguna.")
    finally:
        try:
            connection.close()
        except Exception:
            pass
        print("[*] Koneksi ditutup.")


def main() -> None:
    args = parse_args()
    run_diagnostics(args.endpoint, args.baud, args.timeout)


if __name__ == "__main__":
    main()
