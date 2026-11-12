"""
dobot_tcp_receiver.py (Real-Time Software Limit Protection)
Receiver: TCP Server (127.0.0.1:5005) -> Dobot Magician Controller
Dilengkapi proteksi Software Limit aktif (Stop otomatis saat menyentuh limit).
Dijalankan pada: Python 3.10 32-bit (x86)

Struktur folder yang dibutuhkan:
    <folder skrip>/
    ├── dobot_tcp_receiver.py
    └── SDK/
        ├── DobotDllType.py
        ├── DobotDll.dll
        └── (DLL pendukung lainnya)
"""

import os
import socket
import sys
import threading
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SDK_DIR = os.path.join(SCRIPT_DIR, "SDK")
dll_path = os.path.join(SDK_DIR, "DobotDll.dll")

# Validasi struktur folder sebelum impor
if not os.path.isdir(SDK_DIR):
    print(f"[ERROR] Folder SDK tidak ditemukan di: {SDK_DIR}")
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

# Kecepatan koordinat linier (mm/s) dan percepatan (mm/s^2)
JOG_VELOCITY = 40.0
JOG_ACCELERATION = 70.0


class DobotReceiverController:
    def __init__(self):
        self.api = None
        self.is_connected = False
        self.is_homing = False
        self.current_pose = [0.0, 0.0, 0.0, 0.0]
        self.active_jog_cmd = "STOP"

        # Batasan Software Limit (mm) sesuai spesifikasi praktikum
        self.limits = {
            "X": (150.0, 300.0),
            "Y": (-150.0, 150.0),
            "Z": (-50.0, 150.0),
        }

        self.jog_commands = {
            "X+": dType.JC.JogAPPressed,
            "X-": dType.JC.JogANPressed,
            "Y+": dType.JC.JogBPPressed,
            "Y-": dType.JC.JogBNPressed,
            "Z+": dType.JC.JogCPPressed,
            "Z-": dType.JC.JogCNPressed,
        }

    def connect(self):
        print(f"[RECEIVER] Memuat Dobot API dari: {SDK_DIR}")
        try:
            self.api = dType.load()
        except Exception as e:
            print(f"[ERROR] Gagal memuat DLL: {e}")
            return False

        state = dType.ConnectDobot(self.api, "", 115200)[0]
        if state == dType.DobotConnect.DobotConnect_NoError:
            self.is_connected = True
            dType.SetQueuedCmdClear(self.api)
            dType.SetQueuedCmdStartExec(self.api)

            # Inisialisasi rasio kecepatan dan koordinat
            dType.SetJOGJointParams(self.api, 100, 100, 100, 100, 100, 100, 100, 100, isQueued=0)
            dType.SetJOGCoordinateParams(
                self.api,
                JOG_VELOCITY, JOG_ACCELERATION,
                JOG_VELOCITY, JOG_ACCELERATION,
                JOG_VELOCITY, JOG_ACCELERATION,
                JOG_VELOCITY, JOG_ACCELERATION,
                isQueued=0
            )
            dType.SetJOGCommonParams(self.api, JOG_VELOCITY, JOG_ACCELERATION, isQueued=0)

            self.stop_jog()
            self.set_suction(False)
            self.get_actual_pose()
            print("[RECEIVER] Dobot Magician Berhasil Terhubung!")
            return True
        else:
            print(f"[ERROR] Koneksi Dobot gagal. Status code: {state}")
            return False

    def check_software_limit(self, cmd_key):
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

    def start_jog(self, cmd_key):
        if self.is_homing or not self.is_connected or not self.api:
            return

        # 1. Cek sebelum mulai bergerak
        is_safe, msg = self.check_software_limit(cmd_key)
        if not is_safe:
            print(f"[LIMIT ALERT] Ditolak: {msg}")
            self.stop_jog()
            return

        cmd = self.jog_commands.get(cmd_key)
        if cmd is not None:
            self.active_jog_cmd = cmd_key
            dType.SetJOGCmd(self.api, 0, cmd, isQueued=0)

    def stop_jog(self):
        if self.is_homing or not self.is_connected or not self.api:
            return
        self.active_jog_cmd = "STOP"
        dType.SetJOGCmd(self.api, 0, dType.JC.JogIdle, isQueued=0)

    def set_suction(self, state: bool):
        if self.is_homing or not self.is_connected or not self.api:
            return
        enable = 1 if state else 0
        on = 1 if state else 0
        dType.SetEndEffectorSuctionCup(self.api, enableCtrl=enable, on=on, isQueued=0)
        print(f"[RECEIVER] Suction Cup: {'ON' if state else 'OFF'}")

    def trigger_home(self):
        if not self.is_connected or not self.api or self.is_homing:
            return
        thread = threading.Thread(target=self._homing_worker, daemon=True)
        thread.start()

    def _homing_worker(self):
        self.is_homing = True
        self.active_jog_cmd = "STOP"
        print("[RECEIVER] >>> PROSES HOMING DIMULAI <<<")
        dType.SetJOGCmd(self.api, 0, dType.JC.JogIdle, isQueued=0)
        dType.SetQueuedCmdClear(self.api)
        dType.SetQueuedCmdStartExec(self.api)

        last_index = dType.SetHOMECmd(self.api, temp=0, isQueued=1)[0]
        while True:
            current_index = dType.GetQueuedCmdCurrentIndex(self.api)[0]
            if current_index >= last_index:
                break
            time.sleep(0.2)

        print("[RECEIVER] >>> HOMING SELESAI <<<")
        self.is_homing = False

    def get_actual_pose(self):
        """Membaca koordinat fisik aktual dan melakukan auto-stop jika menabrak limit saat bergerak."""
        if self.is_connected and self.api:
            try:
                pose = dType.GetPose(self.api)
                self.current_pose = [round(float(pose[0]), 2),
                                     round(float(pose[1]), 2),
                                     round(float(pose[2]), 2)]

                # WATCHDOG: Jika sedang bergerak aktif JOG, periksa batas setiap saat
                if self.active_jog_cmd != "STOP":
                    is_safe, msg = self.check_software_limit(self.active_jog_cmd)
                    if not is_safe:
                        print(f"[AUTO-STOP LIMIT] Robot dipaksa henti! {msg}")
                        self.stop_jog()

                return self.current_pose
            except Exception:
                pass
        return self.current_pose

    def disconnect(self):
        if self.is_connected and self.api:
            self.is_homing = False
            self.stop_jog()
            self.set_suction(False)
            dType.DisconnectDobot(self.api)
            self.is_connected = False


def telemetry_sender_loop(robot, conn, running_flag):
    """Mengirim telemetri koordinat nyata dan batas status ke Sender."""
    while running_flag[0]:
        if robot.is_connected:
            pos = robot.get_actual_pose()
            telemetry_str = f"POS:{pos[0]},{pos[1]},{pos[2]}\n"
            try:
                conn.sendall(telemetry_str.encode("utf-8"))
            except Exception:
                break
        time.sleep(0.04)  # Polling cepat tiap 40 ms untuk akurasi limit


def main():
    robot = DobotReceiverController()
    if not robot.connect():
        return

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((HOST, PORT))
        server.listen(1)
        print(f"[RECEIVER] Server aktif di {HOST}:{PORT}...")
    except Exception as e:
        print(f"[ERROR] Gagal bind: {e}")
        robot.disconnect()
        return

    conn, addr = server.accept()
    print(f"[RECEIVER] Sender terhubung dari: {addr}")

    running_flag = [True]
    t_telemetry = threading.Thread(target=telemetry_sender_loop, args=(robot, conn, running_flag), daemon=True)
    t_telemetry.start()

    buffer = ""
    current_active_cmd = "STOP"

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

                if cmd != current_active_cmd:
                    current_active_cmd = cmd

                    if robot.is_homing and cmd != "HOME":
                        continue

                    if cmd in robot.jog_commands:
                        print(f"[RECEIVER] Perintah: {cmd}")
                        robot.start_jog(cmd)
                    elif cmd == "STOP":
                        print("[RECEIVER] Perintah: STOP")
                        robot.stop_jog()
                    elif cmd == "SUCTION ON":
                        robot.set_suction(True)
                    elif cmd == "SUCTION OFF":
                        robot.set_suction(False)
                    elif cmd == "HOME":
                        robot.trigger_home()

    except Exception as e:
        print(f"[RECEIVER ERROR] {e}")
    finally:
        running_flag[0] = False
        robot.disconnect()
        conn.close()
        server.close()
        print("[RECEIVER] Server selesai.")


if __name__ == "__main__":
    main()