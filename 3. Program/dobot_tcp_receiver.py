"""
dobot_tcp_receiver.py (Web + TCP Real-Time Controller dengan Software Limit)
Receiver: TCP Server (127.0.0.1:5005) -> Dobot Magician Controller
Dijalankan pada: Python 3.10 32-bit (x86)

Struktur folder yang didukung:
    8. UAS/
    ├── SDK/
    │   ├── DobotDllType.py
    │   ├── DobotDll.dll
    │   └── (DLL pendukung lainnya)
    └── 3. Program/
        └── dobot_tcp_receiver.py
"""

import argparse
import json
import os
import socket
import sys
import threading
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CANDIDATE_SDK_DIRS = [
    os.path.join(SCRIPT_DIR, "SDK"),
    os.path.abspath(os.path.join(SCRIPT_DIR, "..", "SDK")),
]
SDK_DIR = next((p for p in CANDIDATE_SDK_DIRS if os.path.isdir(p)), CANDIDATE_SDK_DIRS[1])
dll_path = os.path.join(SDK_DIR, "DobotDll.dll")

# Validasi struktur folder sebelum impor
if not os.path.isdir(SDK_DIR):
    print(f"[ERROR] Folder SDK tidak ditemukan di: {CANDIDATE_SDK_DIRS}")
    sys.exit(1)

if not os.path.isfile(os.path.join(SDK_DIR, "DobotDllType.py")):
    print(f"[ERROR] DobotDllType.py tidak ada di dalam: {SDK_DIR}")
    sys.exit(1)

if not os.path.isfile(dll_path):
    print(f"[ERROR] DobotDll.dll tidak ada di dalam: {SDK_DIR}")
    sys.exit(1)

# Daftarkan folder SDK sebagai lokasi modul Python dan lokasi DLL
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)
if hasattr(os, "add_dll_directory"):
    os.add_dll_directory(SDK_DIR)

# DLL dimuat secara relatif, jadi direktori kerja diarahkan ke SDK
os.chdir(SDK_DIR)

try:
    import DobotDllType as dType  # type: ignore
except ImportError as e:
    print(f"[ERROR] Gagal mengimpor DobotDllType: {e}")
    sys.exit(1)

HOST = "127.0.0.1"
PORT = 5005

# Nilai awal kecepatan sesuai tampilan web pada soal (mm/s)
DEFAULT_JOG_SPEED = {"x": 5.0, "y": 5.0, "z": 5.0}
DEFAULT_PTP_VELOCITY = 50.0
DEFAULT_PTP_ACCELERATION = 50.0

CON_STR = {
    dType.DobotConnect.DobotConnect_NoError: "DobotConnect_NoError",
    dType.DobotConnect.DobotConnect_NotFound: "DobotConnect_NotFound (Dobot tidak ditemukan/USB belum terhubung)",
    dType.DobotConnect.DobotConnect_Occupied: "DobotConnect_Occupied (Port sedang dipakai aplikasi lain)",
}


class DobotReceiverController:
    def __init__(self):
        self.api = None
        self.api_lock = threading.RLock()
        self.is_connected = False
        self.is_homing = False
        self.is_moving_ptp = False
        self.suction_on = False
        self.current_pose = [0.0, 0.0, 0.0, 0.0]  # X, Y, Z, R
        self.jog_speed = dict(DEFAULT_JOG_SPEED)
        self.active_jog_cmd = "STOP"
        self.detected_port = ""

        self.last_message = "Siap menghubungkan Dobot Magician."
        self.last_level = "info"
        self._cancel_motion = threading.Event()
        self._event_callbacks = []

        # Batasan Software Limit sesuai spesifikasi praktikum
        self.limits = {
            "X": (150.0, 300.0),
            "Y": (-150.0, 150.0),
            "Z": (-50.0, 150.0),
            "R": (-135.0, 135.0),
        }

        self.jog_commands = {
            "X+": dType.JC.JogAPPressed,
            "X-": dType.JC.JogANPressed,
            "Y+": dType.JC.JogBPPressed,
            "Y-": dType.JC.JogBNPressed,
            "Z+": dType.JC.JogCPPressed,
            "Z-": dType.JC.JogCNPressed,
        }

    def _emit_status(self, message: str, level: str = "info"):
        self.last_message = message
        self.last_level = level
        print(f"[{level.upper()}] {message}")

    def _ensure_api_loaded(self):
        if self.api is None:
            print(f"[RECEIVER] Memuat Dobot API dari: {SDK_DIR}")
            self.api = dType.load()

    def connect(self, port: str = ""):
        with self.api_lock:
            if self.is_connected:
                self._emit_status("Dobot sudah terhubung.", "info")
                return True

            try:
                self._ensure_api_loaded()
            except Exception as e:
                self._emit_status(f"Gagal memuat DobotDll.dll: {e}", "error")
                return False

            try:
                ports = [p for p in dType.SearchDobot(self.api) if p.strip()]
                self.detected_port = ports[0] if ports else ""
                if ports:
                    print(f"[RECEIVER] Port Dobot terdeteksi: {', '.join(ports)}")
            except Exception:
                self.detected_port = ""

            target_port = port.strip()
            result = dType.ConnectDobot(self.api, target_port, 115200)
            state = result[0]

            if state == dType.DobotConnect.DobotConnect_NoError:
                self.is_connected = True
                self.is_homing = False
                self.is_moving_ptp = False
                self._cancel_motion.clear()

                dType.SetQueuedCmdClear(self.api)
                dType.SetQueuedCmdStartExec(self.api)

                # Set common ratio 100% agar nilai velocity pada CoordinateParams langsung dalam mm/s
                dType.SetJOGJointParams(self.api, 50, 100, 50, 100, 50, 100, 50, 100, isQueued=0)
                dType.SetJOGCommonParams(self.api, 100, 100, isQueued=0)
                self._apply_jog_speed_locked(
                    self.jog_speed["x"],
                    self.jog_speed["y"],
                    self.jog_speed["z"],
                )

                # Inisialisasi parameter gerak PTP (untuk input X, Y, Z, R)
                dType.SetPTPJointParams(self.api, 100, 100, 100, 100, 100, 100, 100, 100, isQueued=0)
                dType.SetPTPCoordinateParams(
                    self.api,
                    DEFAULT_PTP_VELOCITY,
                    DEFAULT_PTP_ACCELERATION,
                    DEFAULT_PTP_VELOCITY,
                    DEFAULT_PTP_ACCELERATION,
                    isQueued=0,
                )
                dType.SetPTPCommonParams(self.api, 50, 50, isQueued=0)

                self.stop_jog()
                self.set_suction(False)
                self.get_actual_pose()

                port_info = target_port or self.detected_port or "Auto"
                self._emit_status(f"Dobot Magician berhasil terhubung ({port_info}).", "success")
                return True

            err_desc = CON_STR.get(state, f"Status code: {state}")
            self._emit_status(f"Koneksi Dobot gagal: {err_desc}", "error")
            return False

    def disconnect(self):
        with self.api_lock:
            self._cancel_motion.set()
            self.is_homing = False
            self.is_moving_ptp = False
            if self.is_connected and self.api:
                try:
                    self.stop_jog()
                    self.set_suction(False)
                    dType.SetQueuedCmdForceStopExec(self.api)
                    dType.SetQueuedCmdClear(self.api)
                    dType.DisconnectDobot(self.api)
                except Exception as e:
                    print(f"[WARN] Saat disconnect: {e}")
                self.is_connected = False
            self._emit_status("Koneksi Dobot diputus (DISCONNECTED).", "warning")

    def _apply_jog_speed_locked(self, vx: float, vy: float, vz: float):
        vx = max(1.0, min(100.0, float(vx)))
        vy = max(1.0, min(100.0, float(vy)))
        vz = max(1.0, min(100.0, float(vz)))
        vr = vx
        dType.SetJOGCoordinateParams(
            self.api,
            vx, vx * 2.0,
            vy, vy * 2.0,
            vz, vz * 2.0,
            vr, vr * 2.0,
            isQueued=0,
        )
        self.jog_speed = {"x": round(vx, 2), "y": round(vy, 2), "z": round(vz, 2)}

    def set_speed(self, vx: float, vy: float, vz: float):
        with self.api_lock:
            try:
                vx_f = float(vx)
                vy_f = float(vy)
                vz_f = float(vz)
            except (TypeError, ValueError):
                self._emit_status("Nilai kecepatan harus berupa angka.", "error")
                return False

            if not (1.0 <= vx_f <= 100.0 and 1.0 <= vy_f <= 100.0 and 1.0 <= vz_f <= 100.0):
                self._emit_status("Kecepatan harus berada pada rentang 1-100 mm/s.", "error")
                return False

            if not self.is_connected or not self.api:
                self.jog_speed = {"x": round(vx_f, 2), "y": round(vy_f, 2), "z": round(vz_f, 2)}
                self._emit_status("Robot belum terhubung. Kecepatan disimpan untuk koneksi berikutnya.", "warning")
                return False

            self._apply_jog_speed_locked(vx_f, vy_f, vz_f)
            self._emit_status(
                f"Kecepatan JOG diterapkan: X={self.jog_speed['x']} Y={self.jog_speed['y']} Z={self.jog_speed['z']} mm/s.",
                "success",
            )
            return True

    def check_software_limit(self, cmd_key: str):
        """Memeriksa apakah arah JOG melanggar batas software limit."""
        if cmd_key not in self.jog_commands:
            return True, "Valid"

        axis = cmd_key[0]
        sign = +1 if cmd_key[1] == "+" else -1
        x, y, z = self.current_pose[:3]

        if axis == "X":
            if sign > 0 and x >= self.limits["X"][1]:
                return False, f"Batas MAX X tercapai ({self.limits['X'][1]} mm)"
            if sign < 0 and x <= self.limits["X"][0]:
                return False, f"Batas MIN X tercapai ({self.limits['X'][0]} mm)"
        elif axis == "Y":
            if sign > 0 and y >= self.limits["Y"][1]:
                return False, f"Batas MAX Y tercapai ({self.limits['Y'][1]} mm)"
            if sign < 0 and y <= self.limits["Y"][0]:
                return False, f"Batas MIN Y tercapai ({self.limits['Y'][0]} mm)"
        elif axis == "Z":
            if sign > 0 and z >= self.limits["Z"][1]:
                return False, f"Batas MAX Z tercapai ({self.limits['Z'][1]} mm)"
            if sign < 0 and z <= self.limits["Z"][0]:
                return False, f"Batas MIN Z tercapai ({self.limits['Z'][0]} mm)"

        return True, "Aman"

    def check_target_pose_limits(self, x: float, y: float, z: float, r: float):
        """Memeriksa apakah target posisi (X, Y, Z, R) berada di dalam software limit."""
        checks = [
            ("X", x, "mm"),
            ("Y", y, "mm"),
            ("Z", z, "mm"),
            ("R", r, "derajat"),
        ]
        for axis, val, unit in checks:
            min_v, max_v = self.limits[axis]
            if val < min_v or val > max_v:
                return False, f"Target {axis}={val} {unit} di luar batas aman ({min_v} s/d {max_v} {unit})."
        return True, "Aman"

    def start_jog(self, cmd_key: str):
        with self.api_lock:
            if not self.is_connected or not self.api:
                self._emit_status("JOG ditolak: Robot belum terhubung (klik CONNECT dahulu).", "warning")
                return
            if self.is_homing or self.is_moving_ptp:
                self._emit_status("JOG ditolak: Robot sedang menjalankan HOME/PTP.", "warning")
                return

            self.get_actual_pose()
            is_safe, msg = self.check_software_limit(cmd_key)
            if not is_safe:
                self.stop_jog(silent=True)
                self._emit_status(f"LIMIT ALERT: {msg}", "warning")
                return

            cmd = self.jog_commands.get(cmd_key)
            if cmd is not None:
                self.active_jog_cmd = cmd_key
                dType.SetJOGCmd(self.api, 0, cmd, isQueued=0)
                self._emit_status(f"Continuous JOG aktif: {cmd_key}", "info")

    def stop_jog(self, silent: bool = False):
        with self.api_lock:
            self.active_jog_cmd = "STOP"
            if self.is_connected and self.api:
                dType.SetJOGCmd(self.api, 0, dType.JC.JogIdle, isQueued=0)
            if not silent:
                self._emit_status("Gerakan JOG dihentikan (STOP).", "info")

    def stop_all(self):
        """Menghentikan JOG maupun gerakan antrean (HOME / PTP)."""
        with self.api_lock:
            self._cancel_motion.set()
            self.active_jog_cmd = "STOP"
            if self.is_connected and self.api:
                dType.SetJOGCmd(self.api, 0, dType.JC.JogIdle, isQueued=0)
                dType.SetQueuedCmdForceStopExec(self.api)
                dType.SetQueuedCmdClear(self.api)
                dType.SetQueuedCmdStartExec(self.api)
            self.is_homing = False
            self.is_moving_ptp = False
            self._emit_status("Perintah STOP dikirim. Semua gerakan dihentikan.", "warning")

    def set_suction(self, state: bool):
        with self.api_lock:
            if not self.is_connected or not self.api:
                self._emit_status("Suction ditolak: Robot belum terhubung.", "warning")
                return
            enable = 1 if state else 0
            on = 1 if state else 0
            dType.SetEndEffectorSuctionCup(self.api, enableCtrl=enable, on=on, isQueued=0)
            self.suction_on = bool(state)
            self._emit_status(f"Perintah Suction {'ON' if state else 'OFF'} berhasil dikirim.", "success")

    def trigger_home(self):
        with self.api_lock:
            if not self.is_connected or not self.api:
                self._emit_status("HOME ditolak: Robot belum terhubung.", "warning")
                return
            if self.is_homing:
                self._emit_status("Proses HOMING sedang berlangsung.", "warning")
                return
            if self.is_moving_ptp:
                self._emit_status("HOME ditolak: Robot sedang bergerak ke target XYZR.", "warning")
                return

            self.active_jog_cmd = "STOP"
            self._cancel_motion.clear()
            self.is_homing = True
            self._emit_status("Proses HOMING dimulai...", "info")

        thread = threading.Thread(target=self._homing_worker, daemon=True)
        thread.start()

    def _homing_worker(self):
        try:
            with self.api_lock:
                if not self.is_connected or not self.api:
                    return
                dType.SetJOGCmd(self.api, 0, dType.JC.JogIdle, isQueued=0)
                dType.SetQueuedCmdClear(self.api)
                dType.SetQueuedCmdStartExec(self.api)
                last_index = dType.SetHOMECmd(self.api, temp=0, isQueued=1)[0]

            while not self._cancel_motion.is_set() and self.is_connected:
                with self.api_lock:
                    if not self.is_connected or not self.api:
                        break
                    current_index = dType.GetQueuedCmdCurrentIndex(self.api)[0]
                if current_index >= last_index:
                    self._emit_status("HOMING selesai. Robot berada di posisi referensi.", "success")
                    break
                time.sleep(0.2)
        except Exception as e:
            self._emit_status(f"Error saat HOMING: {e}", "error")
        finally:
            self.is_homing = False

    def trigger_move_xyzr(self, x: float, y: float, z: float, r: float):
        with self.api_lock:
            if not self.is_connected or not self.api:
                self._emit_status("Gerak target ditolak: Robot belum terhubung.", "warning")
                return
            if self.is_homing:
                self._emit_status("Gerak target ditolak: Robot sedang proses HOMING.", "warning")
                return
            if self.is_moving_ptp:
                self._emit_status("Gerak target ditolak: Gerakan sebelumnya masih berlangsung.", "warning")
                return

            try:
                tx, ty, tz, tr = float(x), float(y), float(z), float(r)
            except (TypeError, ValueError):
                self._emit_status("Input X, Y, Z, R harus berupa angka valid.", "error")
                return

            is_safe, msg = self.check_target_pose_limits(tx, ty, tz, tr)
            if not is_safe:
                self._emit_status(f"LIMIT ALERT: {msg}", "error")
                return

            self.active_jog_cmd = "STOP"
            self._cancel_motion.clear()
            self.is_moving_ptp = True
            self._emit_status(
                f"Bergerak ke target X={tx:.2f}, Y={ty:.2f}, Z={tz:.2f}, R={tr:.2f}...",
                "info",
            )

        thread = threading.Thread(
            target=self._ptp_worker,
            args=(tx, ty, tz, tr),
            daemon=True,
        )
        thread.start()

    def _ptp_worker(self, x: float, y: float, z: float, r: float):
        try:
            with self.api_lock:
                if not self.is_connected or not self.api:
                    return
                dType.SetJOGCmd(self.api, 0, dType.JC.JogIdle, isQueued=0)
                dType.SetQueuedCmdClear(self.api)
                dType.SetQueuedCmdStartExec(self.api)
                last_index = dType.SetPTPCmd(
                    self.api,
                    dType.PTPMode.PTPMOVLXYZMode,
                    x, y, z, r,
                    isQueued=1,
                )[0]

            while not self._cancel_motion.is_set() and self.is_connected:
                with self.api_lock:
                    if not self.is_connected or not self.api:
                        break
                    current_index = dType.GetQueuedCmdCurrentIndex(self.api)[0]
                if current_index >= last_index:
                    self.get_actual_pose()
                    self._emit_status(
                        f"Target tercapai: X={x:.2f}, Y={y:.2f}, Z={z:.2f}, R={r:.2f}.",
                        "success",
                    )
                    break
                time.sleep(0.1)
        except Exception as e:
            self._emit_status(f"Error saat gerak PTP XYZR: {e}", "error")
        finally:
            self.is_moving_ptp = False

    def get_actual_pose(self):
        """Membaca koordinat fisik aktual (X, Y, Z, R) dan auto-stop jika menyentuh limit."""
        with self.api_lock:
            if self.is_connected and self.api:
                try:
                    pose = dType.GetPose(self.api)
                    self.current_pose = [
                        round(float(pose[0]), 2),
                        round(float(pose[1]), 2),
                        round(float(pose[2]), 2),
                        round(float(pose[3]), 2),
                    ]

                    if self.active_jog_cmd != "STOP":
                        is_safe, msg = self.check_software_limit(self.active_jog_cmd)
                        if not is_safe:
                            self.stop_jog(silent=True)
                            self._emit_status(f"AUTO-STOP LIMIT: {msg}", "warning")
                except Exception:
                    pass
            return self.current_pose

    def build_telemetry_payload(self):
        pos = self.get_actual_pose()
        return {
            "type": "telemetry",
            "connected": self.is_connected,
            "homing": self.is_homing,
            "moving": self.is_moving_ptp,
            "suction": self.suction_on,
            "active_jog": self.active_jog_cmd,
            "detected_port": self.detected_port,
            "pose": {
                "x": pos[0],
                "y": pos[1],
                "z": pos[2],
                "r": pos[3],
            },
            "speed": dict(self.jog_speed),
            "limits": {k: list(v) for k, v in self.limits.items()},
            "message": self.last_message,
            "level": self.last_level,
        }


def telemetry_sender_loop(robot: DobotReceiverController, conn: socket.socket, running_flag: list):
    """Mengirim telemetri JSON secara berkala ke client TCP."""
    while running_flag[0]:
        try:
            payload = robot.build_telemetry_payload()
            line = json.dumps(payload) + "\n"
            conn.sendall(line.encode("utf-8"))
        except Exception:
            break
        time.sleep(0.05)  # 50 ms polling untuk akurasi software limit & UI realtime


def handle_command(robot: DobotReceiverController, cmd: str):
    if cmd == "CONNECT":
        robot.connect()
    elif cmd.startswith("CONNECT:"):
        port = cmd.split(":", 1)[1].strip()
        robot.connect(port=port)
    elif cmd == "DISCONNECT":
        robot.disconnect()
    elif cmd in robot.jog_commands:
        robot.start_jog(cmd)
    elif cmd == "STOP":
        robot.stop_all()
    elif cmd == "JOG STOP":
        robot.stop_jog()
    elif cmd == "SUCTION ON":
        robot.set_suction(True)
    elif cmd == "SUCTION OFF":
        robot.set_suction(False)
    elif cmd == "HOME":
        robot.trigger_home()
    elif cmd.startswith("SPEED:"):
        parts = cmd.split(":", 1)[1].split(",")
        if len(parts) == 3:
            robot.set_speed(parts[0], parts[1], parts[2])
        else:
            robot._emit_status("Format perintah SPEED tidak valid (harus SPEED:vx,vy,vz).", "error")
    elif cmd.startswith("MOVE:"):
        parts = cmd.split(":", 1)[1].split(",")
        if len(parts) == 4:
            robot.trigger_move_xyzr(parts[0], parts[1], parts[2], parts[3])
        else:
            robot._emit_status("Format perintah MOVE tidak valid (harus MOVE:x,y,z,r).", "error")
    elif cmd in ("PING", "STATUS"):
        pass


def main():
    parser = argparse.ArgumentParser(description="Dobot Magician TCP Receiver (Python 3.10 32-bit)")
    parser.add_argument(
        "--auto-connect",
        action="store_true",
        help="Langsung hubungkan ke Dobot saat receiver dijalankan.",
    )
    args = parser.parse_args()

    robot = DobotReceiverController()
    if args.auto_connect:
        robot.connect()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((HOST, PORT))
        server.listen(1)
        print(f"[RECEIVER] TCP Server aktif di {HOST}:{PORT} (Python {sys.version.split()[0]} 32-bit)")
        print(f"[RECEIVER] Menggunakan SDK di: {SDK_DIR}")
        print("[RECEIVER] Menunggu koneksi dari Flask Server / Sender...")
    except Exception as e:
        print(f"[ERROR] Gagal bind ke {HOST}:{PORT}: {e}")
        robot.disconnect()
        return

    try:
        while True:
            conn, addr = server.accept()
            print(f"[RECEIVER] Client TCP terhubung dari: {addr}")

            running_flag = [True]
            t_telemetry = threading.Thread(
                target=telemetry_sender_loop,
                args=(robot, conn, running_flag),
                daemon=True,
            )
            t_telemetry.start()

            buffer = ""
            try:
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break

                    buffer += data.decode("utf-8", errors="ignore")
                    while "\n" in buffer:
                        cmd, buffer = buffer.split("\n", 1)
                        cmd = cmd.strip()
                        if not cmd:
                            continue
                        handle_command(robot, cmd)
            except Exception as e:
                print(f"[RECEIVER WARN] Koneksi client terputus: {e}")
            finally:
                running_flag[0] = False
                if robot.is_connected:
                    robot.stop_jog(silent=True)
                try:
                    conn.close()
                except Exception:
                    pass
                print("[RECEIVER] Client TCP terputus. Menunggu koneksi ulang...")
    except KeyboardInterrupt:
        print("\n[RECEIVER] Dihentikan oleh pengguna (Ctrl+C).")
    finally:
        robot.disconnect()
        try:
            server.close()
        except Exception:
            pass
        print("[RECEIVER] Server selesai.")


if __name__ == "__main__":
    main()

