"""
server/app.py
Flask Backend Server untuk Dobot Magician Smartphone Controller.
Menyajikan antarmuka web (web/) dan meneruskan perintah ke dobot_tcp_receiver.py (127.0.0.1:5005).
"""

import os
import socket
import sys
import time
from flask import Flask, jsonify, request, send_from_directory

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.abspath(os.path.join(SERVER_DIR, ".."))
WEB_DIR = os.path.join(PROJECT_DIR, "web")

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from robot.tcp_bridge import DobotTCPBridge  # noqa: E402

HOST = "0.0.0.0"
PORT = 5000
TCP_RECEIVER_HOST = "127.0.0.1"
TCP_RECEIVER_PORT = 5005

app = Flask(__name__, static_folder=None)
bridge = DobotTCPBridge(host=TCP_RECEIVER_HOST, port=TCP_RECEIVER_PORT)


def get_local_ip() -> str:
    """Mendeteksi alamat IP LAN/Wi-Fi laptop agar mudah diakses dari smartphone."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/<path:filename>")
def web_assets(filename: str):
    return send_from_directory(WEB_DIR, filename)


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify(bridge.get_status())


@app.route("/api/connect", methods=["POST"])
def api_connect():
    data = request.get_json(silent=True) or {}
    port = str(data.get("port", "")).strip()
    ok, msg = bridge.connect_robot(port=port)
    if not ok:
        return jsonify({"ok": False, "message": msg, "status": bridge.get_status()}), 503

    # Beri jeda singkat agar hasil ConnectDobot & pose awal terbaca dari receiver
    time.sleep(0.35)
    status = bridge.get_status()
    return jsonify({"ok": status.get("connected", False), "message": status.get("message", msg), "status": status})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    ok, msg = bridge.disconnect_robot()
    time.sleep(0.15)
    status = bridge.get_status()
    return jsonify({"ok": ok, "message": status.get("message", msg), "status": status}), (200 if ok else 503)


@app.route("/api/home", methods=["POST"])
def api_home():
    ok, msg = bridge.home()
    time.sleep(0.1)
    status = bridge.get_status()
    return jsonify({"ok": ok, "message": status.get("message", msg), "status": status}), (200 if ok else 503)


@app.route("/api/stop", methods=["POST"])
def api_stop():
    ok, msg = bridge.stop()
    time.sleep(0.08)
    status = bridge.get_status()
    return jsonify({"ok": ok, "message": status.get("message", msg), "status": status}), (200 if ok else 503)


@app.route("/api/jog/start", methods=["POST"])
def api_jog_start():
    data = request.get_json(silent=True) or {}
    direction = str(data.get("direction", "")).strip().upper()
    ok, msg = bridge.start_jog(direction)
    if not ok:
        return jsonify({"ok": False, "message": msg, "status": bridge.get_status()}), 400
    time.sleep(0.06)
    status = bridge.get_status()
    return jsonify({"ok": True, "message": status.get("message", msg), "status": status})


@app.route("/api/jog/stop", methods=["POST"])
def api_jog_stop():
    ok, msg = bridge.stop_jog()
    time.sleep(0.05)
    status = bridge.get_status()
    return jsonify({"ok": ok, "message": status.get("message", msg), "status": status}), (200 if ok else 503)


@app.route("/api/suction", methods=["POST"])
def api_suction():
    data = request.get_json(silent=True) or {}
    state = bool(data.get("state", False))
    ok, msg = bridge.set_suction(state)
    time.sleep(0.08)
    status = bridge.get_status()
    return jsonify({"ok": ok, "message": status.get("message", msg), "status": status}), (200 if ok else 503)


@app.route("/api/speed", methods=["POST"])
def api_speed():
    data = request.get_json(silent=True) or {}
    try:
        vx = float(data.get("x", 5))
        vy = float(data.get("y", 5))
        vz = float(data.get("z", 5))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Nilai kecepatan harus berupa angka."}), 400

    if not (1.0 <= vx <= 100.0 and 1.0 <= vy <= 100.0 and 1.0 <= vz <= 100.0):
        return jsonify({"ok": False, "message": "Kecepatan harus antara 1 - 100 mm/s."}), 400

    ok, msg = bridge.set_speed(vx, vy, vz)
    time.sleep(0.08)
    status = bridge.get_status()
    return jsonify({"ok": ok, "message": status.get("message", msg), "status": status}), (200 if ok else 503)


@app.route("/api/move", methods=["POST"])
def api_move():
    data = request.get_json(silent=True) or {}
    try:
        x = float(data.get("x"))
        y = float(data.get("y"))
        z = float(data.get("z"))
        r = float(data.get("r", 0.0))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Input X, Y, Z, R harus berupa angka valid."}), 400

    status_before = bridge.get_status()
    limits = status_before.get("limits", {})
    for axis, val in (("X", x), ("Y", y), ("Z", z), ("R", r)):
        min_v, max_v = limits.get(axis, (-9999, 9999))
        if val < min_v or val > max_v:
            return (
                jsonify(
                    {
                        "ok": False,
                        "message": f"Target {axis}={val} di luar software limit ({min_v} s/d {max_v}).",
                        "status": status_before,
                    }
                ),
                400,
            )

    ok, msg = bridge.move_to(x, y, z, r)
    time.sleep(0.1)
    status = bridge.get_status()
    return jsonify({"ok": ok, "message": status.get("message", msg), "status": status}), (200 if ok else 503)


if __name__ == "__main__":
    local_ip = get_local_ip()
    print("=" * 60)
    print("  DOBOT MAGICIAN - SMARTPHONE WEB CONTROLLER (FLASK SERVER)")
    print("=" * 60)
    print(f"  Folder Web      : {WEB_DIR}")
    print(f"  TCP Receiver    : {TCP_RECEIVER_HOST}:{TCP_RECEIVER_PORT}")
    print(f"  Akses Lokal PC  : http://127.0.0.1:{PORT}")
    print(f"  Akses Smartphone: http://{local_ip}:{PORT}")
    print("=" * 60)
    print("  Pastikan 'dobot_tcp_receiver.py' sudah dijalankan pada Python 3.10 32-bit.")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)

