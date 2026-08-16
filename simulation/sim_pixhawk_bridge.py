"""Multi-client Simulated Pixhawk MAVLink Bridge for KKI2026 Webots ASV.

- Listens on TCP 0.0.0.0:5762 and supports multiple concurrent MAVLink clients
  (e.g. asv_backend + vision_test + Mission Planner).
- Generates 1 Hz HEARTBEAT and 10 Hz telemetry (GLOBAL_POSITION_INT, VFR_HUD, RC_CHANNELS_RAW).
- Forwards incoming RC_CHANNELS_OVERRIDE from any client to Webots UDP 127.0.0.1:9090.
- Reads live position & heading from Webots telemetry on UDP 127.0.0.1:14550.
"""

from __future__ import annotations

import argparse
import math
import socket
import socketserver
import sys
import threading
import time
from typing import Any

try:
    from pymavlink import mavutil
    from pymavlink.dialects.v20 import common as mavlink2
except ImportError:
    print("pymavlink is required: python -m pip install pymavlink")
    sys.exit(1)


BASE_LAT = -6.200000
BASE_LON = 106.816666
METERS_PER_DEG_LAT = 111320.0


class BridgeState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.x: float = 0.0
        self.y: float = 0.0
        self.heading_deg: float = 0.0
        self.speed_mps: float = 0.0
        self.steering_pwm: int = 1500
        self.throttle_pwm: int = 1500
        self.last_webots_msg_at: float = 0.0
        self.clients: set[socket.socket] = set()
        self.clients_lock = threading.Lock()


state = BridgeState()
actuator_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
webots_actuator_target = ("127.0.0.1", 9090)


class MavlinkClientHandler(socketserver.BaseRequestHandler):
    """Handle one connected MAVLink TCP client."""

    def handle(self) -> None:
        client_sock: socket.socket = self.request
        client_addr = self.client_address
        print(f"[SimPixhawk] Client connected: {client_addr}")

        with state.clients_lock:
            state.clients.add(client_sock)

        # MAVLink parser for this client stream
        mav_in = mavlink2.MAVLink(None, srcSystem=1, srcComponent=1)
        client_sock.settimeout(0.2)

        try:
            while True:
                try:
                    data = client_sock.recv(1024)
                    if not data:
                        break
                    msgs = mav_in.parse_buffer(data)
                    if msgs:
                        for msg in msgs:
                            msg_type = msg.get_type()
                            if msg_type == "RC_CHANNELS_OVERRIDE":
                                steer = getattr(msg, "chan1_raw", 65535)
                                thr = getattr(msg, "chan3_raw", 65535)
                                with state.lock:
                                    if steer != 65535 and 900 <= steer <= 2100:
                                        state.steering_pwm = steer
                                    if thr != 65535 and 900 <= thr <= 2100:
                                        state.throttle_pwm = thr
                                    steer_val = state.steering_pwm
                                    thr_val = state.throttle_pwm

                                payload = f"{steer_val},{thr_val}".encode("utf-8")
                                actuator_sock.sendto(payload, webots_actuator_target)

                except socket.timeout:
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    break
                except Exception:
                    time.sleep(0.01)
        finally:
            with state.clients_lock:
                state.clients.discard(client_sock)
            print(f"[SimPixhawk] Client disconnected: {client_addr}")


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_telemetry_broadcast_loop() -> None:
    """Continuously broadcast MAVLink telemetry to all connected TCP clients."""
    mav_out = mavlink2.MAVLink(None, srcSystem=1, srcComponent=1)
    last_hb = 0.0
    last_pos = 0.0

    while True:
        now = time.monotonic()
        with state.clients_lock:
            active_clients = list(state.clients)

        if active_clients:
            # 1 Hz HEARTBEAT
            if now - last_hb >= 1.0:
                hb_msg = mav_out.heartbeat_encode(
                    mavlink2.MAV_TYPE_GROUND_ROVER,
                    mavlink2.MAV_AUTOPILOT_ARDUPILOTMEGA,
                    mavlink2.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
                    | mavlink2.MAV_MODE_FLAG_MANUAL_INPUT_ENABLED
                    | mavlink2.MAV_MODE_FLAG_SAFETY_ARMED,
                    0,
                    mavlink2.MAV_STATE_ACTIVE,
                )
                hb_buf = hb_msg.pack(mav_out)
                for sock in active_clients:
                    try:
                        sock.sendall(hb_buf)
                    except Exception:
                        pass
                last_hb = now

            # 10 Hz Telemetry (GPS, VFR_HUD, RC_CHANNELS_RAW)
            if now - last_pos >= 0.1:
                with state.lock:
                    x = state.x
                    y = state.y
                    hdg = state.heading_deg
                    spd = state.speed_mps
                    steer = state.steering_pwm
                    thr = state.throttle_pwm

                lat = BASE_LAT + (y / METERS_PER_DEG_LAT)
                lon = BASE_LON + (
                    x
                    / (METERS_PER_DEG_LAT * math.cos(math.radians(BASE_LAT)))
                )

                # GLOBAL_POSITION_INT
                pos_msg = mav_out.global_position_int_encode(
                    int(now * 1000) & 0xFFFFFFFF,
                    int(lat * 1e7),
                    int(lon * 1e7),
                    10000,
                    0,
                    int(spd * 100 * math.cos(math.radians(hdg))),
                    int(spd * 100 * math.sin(math.radians(hdg))),
                    0,
                    int(hdg * 100),
                )
                pos_buf = pos_msg.pack(mav_out)

                # VFR_HUD
                hud_msg = mav_out.vfr_hud_encode(
                    spd,
                    spd,
                    int(hdg),
                    50,
                    0.0,
                    0.0,
                )
                hud_buf = hud_msg.pack(mav_out)

                # RC_CHANNELS_RAW
                rc_msg = mav_out.rc_channels_raw_encode(
                    int(now * 1000) & 0xFFFFFFFF,
                    0,
                    steer,
                    1500,
                    thr,
                    1500,
                    1500,
                    1500,
                    1500,
                    1500,
                    255,
                )
                rc_buf = rc_msg.pack(mav_out)

                total_buf = pos_buf + hud_buf + rc_buf
                for sock in active_clients:
                    try:
                        sock.sendall(total_buf)
                    except Exception:
                        pass
                last_pos = now

        time.sleep(0.02)


def start_webots_udp_listener(port: int = 14550) -> None:
    """Receive telemetry packets from Webots controller on UDP."""
    try:
        webots_telemetry = mavutil.mavlink_connection(
            f"udpin:127.0.0.1:{port}",
            source_system=255,
            source_component=190,
        )
    except Exception as exc:
        print(f"[SimPixhawk] Could not bind Webots UDP {port}: {exc}")
        return

    def listener_loop() -> None:
        while True:
            try:
                msg = webots_telemetry.recv_match(blocking=True, timeout=0.2)
                if msg is not None:
                    msg_type = msg.get_type()
                    now = time.monotonic()
                    with state.lock:
                        state.last_webots_msg_at = now
                        if msg_type == "GLOBAL_POSITION_INT":
                            lat = getattr(msg, "lat", 0) / 1e7
                            lon = getattr(msg, "lon", 0) / 1e7
                            state.y = (lat - BASE_LAT) * METERS_PER_DEG_LAT
                            state.x = (lon - BASE_LON) * (
                                METERS_PER_DEG_LAT
                                * math.cos(math.radians(BASE_LAT))
                            )
                            hdg = getattr(msg, "hdg", 0)
                            if hdg != 65535:
                                state.heading_deg = hdg / 100.0
                        elif msg_type == "VFR_HUD":
                            state.speed_mps = float(getattr(msg, "groundspeed", 0.0))
                            state.heading_deg = float(getattr(msg, "heading", state.heading_deg))
            except Exception:
                time.sleep(0.01)

    thread = threading.Thread(target=listener_loop, daemon=True, name="webots-udp-listener")
    thread.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Client Simulated Pixhawk MAVLink Bridge")
    parser.add_argument(
        "--tcp-port",
        type=int,
        default=5762,
        help="TCP port to listen on for backend/vision_test connection (default 5762)",
    )
    parser.add_argument(
        "--webots-telemetry-udp",
        type=int,
        default=14550,
        help="UDP port to receive telemetry from Webots (default 14550)",
    )
    parser.add_argument(
        "--webots-actuator-udp",
        type=int,
        default=9090,
        help="UDP port to send PWM commands to Webots (default 9090)",
    )
    args = parser.parse_args()

    global webots_actuator_target
    webots_actuator_target = ("127.0.0.1", args.webots_actuator_udp)

    start_webots_udp_listener(args.webots_telemetry_udp)

    broadcaster_thread = threading.Thread(
        target=start_telemetry_broadcast_loop, daemon=True, name="mavlink-broadcaster"
    )
    broadcaster_thread.start()

    print(f"[SimPixhawk] Starting Multi-Client TCP MAVLink Server on 0.0.0.0:{args.tcp_port}...")
    server = ThreadedTCPServer(("0.0.0.0", args.tcp_port), MavlinkClientHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
