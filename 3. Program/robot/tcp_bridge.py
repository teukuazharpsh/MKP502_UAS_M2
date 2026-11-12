"""
tcp_bridge.py
TCP Client bridge antara Flask backend (server/app.py) dan dobot_tcp_receiver.py (127.0.0.1:5005).
"""

import json
import socket
import threading
import time


class DobotTCPBridge:
    def __init__(self, host: str = "127.0.0.1", port: int = 5005):
        self.host = host
        self.port = port

        self._sock = None
        self._sock_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()

        self._state = {
            "tcp_connected": False,
            "connected": False,
            "homing": False,
            "moving": False,
            "suction": False,
            "active_jog": "STOP",
            "detected_port": "",
            "pose": {"x": 0.0, "y": 0.0, "z": 0.0, "r": 0.0},
            "speed": {"x": 5.0, "y": 5.0, "z": 5.0},
            "limits": {
                "X": [150.0, 300.0],
                "Y": [-150.0, 150.0],
                "Z": [-50.0, 150.0],
                "R": [-135.0, 135.0],
            },
            "message": "Menunggu koneksi ke dobot_tcp_receiver.py (port 5005)...",
            "level": "warning",
            "updated_at": 0.0,
        }

        self._worker = threading.Thread(target=self._connection_loop, daemon=True)
        self._worker.start()

    def _connection_loop(self):
        while not self._stop_event.is_set():
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect((self.host, self.port))
                sock.settimeout(1.0)

                with self._sock_lock:
                    self._sock = sock

                with self._state_lock:
                    self._state["tcp_connected"] = True
                    self._state["message"] = "Terhubung ke dobot_tcp_receiver.py. Klik CONNECT untuk menghubungkan robot."
                    self._state["level"] = "info"

                buffer = ""
                while not self._stop_event.is_set():
                    try:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        buffer += chunk.decode("utf-8", errors="ignore")
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if line:
                                self._process_telemetry_line(line)
                    except socket.timeout:
                        continue
            except Exception:
                pass
            finally:
                with self._sock_lock:
                    if self._sock is not None:
                        try:
                            self._sock.close()
                        except Exception:
                            pass
                        self._sock = None
                    elif sock is not None:
                        try:
                            sock.close()
                        except Exception:
                            pass

                with self._state_lock:
                    self._state["tcp_connected"] = False
                    self._state["connected"] = False
                    self._state["homing"] = False
                    self._state["moving"] = False
                    self._state["active_jog"] = "STOP"
                    self._state["message"] = (
                        f"dobot_tcp_receiver.py belum aktif di {self.host}:{self.port}. "
                        "Jalankan dobot_tcp_receiver.py terlebih dahulu."
                    )
                    self._state["level"] = "warning"

            time.sleep(1.0)

    def _process_telemetry_line(self, line: str):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return

        with self._state_lock:
            self._state["tcp_connected"] = True
            self._state["connected"] = bool(payload.get("connected", False))
            self._state["homing"] = bool(payload.get("homing", False))
            self._state["moving"] = bool(payload.get("moving", False))
            self._state["suction"] = bool(payload.get("suction", False))
            self._state["active_jog"] = payload.get("active_jog", "STOP")
            self._state["detected_port"] = payload.get("detected_port", "")
            if isinstance(payload.get("pose"), dict):
                self._state["pose"] = payload["pose"]
            if isinstance(payload.get("speed"), dict):
                self._state["speed"] = payload["speed"]
            if isinstance(payload.get("limits"), dict):
                self._state["limits"] = payload["limits"]
            if payload.get("message"):
                self._state["message"] = payload["message"]
                self._state["level"] = payload.get("level", "info")
            self._state["updated_at"] = time.time()

    def send_command(self, cmd: str):
        with self._sock_lock:
            if self._sock is None:
                return False, (
                    f"Tidak terhubung ke TCP Receiver ({self.host}:{self.port}). "
                    "Pastikan dobot_tcp_receiver.py sedang berjalan."
                )
            try:
                self._sock.sendall((cmd.strip() + "\n").encode("utf-8"))
                return True, f"Perintah '{cmd}' dikirim."
            except Exception as e:
                return False, f"Gagal mengirim perintah ke receiver: {e}"

    def get_status(self):
        with self._state_lock:
            return json.loads(json.dumps(self._state))

    def connect_robot(self, port: str = ""):
        cmd = f"CONNECT:{port.strip()}" if port.strip() else "CONNECT"
        return self.send_command(cmd)

    def disconnect_robot(self):
        return self.send_command("DISCONNECT")

    def home(self):
        return self.send_command("HOME")

    def stop(self):
        return self.send_command("STOP")

    def start_jog(self, direction: str):
        valid = {"X+", "X-", "Y+", "Y-", "Z+", "Z-"}
        direction = direction.strip().upper()
        if direction not in valid:
            return False, f"Arah JOG tidak valid: {direction}"
        return self.send_command(direction)

    def stop_jog(self):
        return self.send_command("JOG STOP")

    def set_suction(self, state: bool):
        return self.send_command("SUCTION ON" if state else "SUCTION OFF")

    def set_speed(self, vx: float, vy: float, vz: float):
        return self.send_command(f"SPEED:{vx},{vy},{vz}")

    def move_to(self, x: float, y: float, z: float, r: float):
        return self.send_command(f"MOVE:{x},{y},{z},{r}")

    def close(self):
        self._stop_event.set()

