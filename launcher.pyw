"""Desktop control panel for BlueMuse, the EEG bridge, and TouchDesigner."""

import csv
import ctypes
import os
import queue
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox


ROOT = Path(__file__).resolve().parent
LOG_FILE = ROOT / "launcher.log"
BRIDGE = ROOT / "eeg_to_osc.py"
PROJECT = ROOT / "MuseTouchDesigner.toe"
TOUCHDESIGNER = Path(r"C:\Program Files\Derivative\TouchDesigner\bin\TouchDesigner.exe")
PYTHON = Path(sys.executable).with_name("python.exe")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

BG = "#101521"
PANEL = "#1b2333"
TEXT = "#f2f5fb"
MUTED = "#a9b4c7"
TEAL = "#49dfc4"
YELLOW = "#f6c86b"
RED = "#f07d83"
DIM = "#4b5970"


def send_osc(address, value):
    """Send one OSC float without depending on the bridge's third-party packages."""
    def pad(value_bytes):
        value_bytes += b"\0"
        return value_bytes + b"\0" * (-len(value_bytes) % 4)

    packet = pad(address.encode("utf-8")) + pad(b",f") + struct.pack(">f", float(value))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(packet, ("127.0.0.1", 9000))


def process_running(name):
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=3,
            check=False,
        )
        return any(row and row[0].lower() == name.lower() for row in csv.reader(result.stdout.splitlines()))
    except (OSError, subprocess.TimeoutExpired):
        return False


def touchdesigner_windows():
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq TouchDesigner.exe", "/FO", "CSV", "/V", "/NH"],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
            timeout=3, check=False,
        )
        return [(int(row[1]), row[-1]) for row in csv.reader(result.stdout.splitlines())
                if len(row) >= 9 and row[0].lower() == "touchdesigner.exe" and row[1].isdigit()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def existing_bridge_pids():
    """Find an independently started copy of this bridge before launching another."""
    command = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" "
        "| Where-Object { $_.CommandLine -like '*eeg_to_osc.py*' } "
        "| Select-Object -ExpandProperty ProcessId"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
            timeout=5, check=False,
        )
        return [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]
    except (OSError, subprocess.TimeoutExpired):
        return []


def request_normal_close(pid):
    """Ask a TouchDesigner window to close, allowing its normal Save prompt."""
    user32 = ctypes.windll.user32
    matched = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def each_window(hwnd, _):
        window_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value == pid and user32.IsWindowVisible(hwnd):
            matched.append(hwnd)
        return True

    callback = callback_type(each_window)
    user32.EnumWindows(callback, 0)
    for hwnd in matched:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    return bool(matched)


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Muse + TouchDesigner")
        self.geometry("650x590")
        self.minsize(590, 540)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.events = queue.Queue()
        self.bridge = None
        self.touchdesigner = None
        self.touchdesigner_pid = None
        self.want_running = False
        self.stopping = False
        self.headset_connected = False
        self.level = 0.0
        self.last_level_at = 0.0
        self.restart_attempts = 0
        self.next_restart_at = 0.0
        self.last_bluemuse_launch = 0.0
        self.last_process_check = 0.0
        self.bluemuse_open = False

        self._build_ui()
        self.after(200, self._poll)
        self.after(600, self.start_all)

    def _build_ui(self):
        outer = tk.Frame(self, bg=BG, padx=28, pady=23)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text="MUSE  /  TOUCHDESIGNER", bg=BG, fg=TEAL,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(outer, text="Your live EEG setup", bg=BG, fg=TEXT,
                 font=("Segoe UI", 23, "bold")).pack(anchor="w", pady=(4, 2))
        tk.Label(outer, text="Open once. Reconnect automatically. Close safely.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 18))

        cards = tk.Frame(outer, bg=BG)
        cards.pack(fill="x")
        self.status_labels = {}
        for column, (key, title) in enumerate([
            ("bluemuse", "BlueMuse"), ("headset", "Headset"),
            ("bridge", "Data bridge"), ("touchdesigner", "TouchDesigner"),
        ]):
            card = tk.Frame(cards, bg=PANEL, padx=12, pady=11)
            card.grid(row=0, column=column, sticky="ew", padx=(0, 6 if column < 3 else 0))
            cards.grid_columnconfigure(column, weight=1)
            tk.Label(card, text=title, bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9)).pack(anchor="w")
            value = tk.Label(card, text="Waiting", bg=PANEL, fg=YELLOW,
                             font=("Segoe UI", 11, "bold"))
            value.pack(anchor="w", pady=(5, 0))
            self.status_labels[key] = value

        signal = tk.Frame(outer, bg=PANEL, padx=17, pady=15)
        signal.pack(fill="x", pady=(16, 0))
        top = tk.Frame(signal, bg=PANEL)
        top.pack(fill="x")
        tk.Label(top, text="AF7 signal variation", bg=PANEL, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(side="left")
        self.level_label = tk.Label(top, text="0.000", bg=PANEL, fg=TEAL,
                                    font=("Consolas", 14, "bold"))
        self.level_label.pack(side="right")
        self.meter = tk.Canvas(signal, height=16, bg=DIM, highlightthickness=0)
        self.meter.pack(fill="x", pady=(12, 5))
        self.meter.bind("<Configure>", lambda _: self._draw_meter())
        tk.Label(signal, text="Visual control level  ·  OSC /eeg/level  ·  port 9000",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")

        buttons = tk.Frame(outer, bg=BG)
        buttons.pack(fill="x", pady=(17, 0))
        self.start_button = tk.Button(buttons, text="Start all", command=self.start_all,
                                      bg=TEAL, fg=BG, activebackground="#81f4df",
                                      relief="flat", padx=18, pady=10,
                                      font=("Segoe UI", 11, "bold"), cursor="hand2")
        self.start_button.pack(side="left")
        self.stop_button = tk.Button(buttons, text="Stop all", command=self.stop_all,
                                     bg=PANEL, fg=TEXT, activebackground=DIM,
                                     relief="flat", padx=18, pady=10,
                                     font=("Segoe UI", 11, "bold"), cursor="hand2")
        self.stop_button.pack(side="left", padx=(9, 0))
        tk.Button(buttons, text="Open project folder", command=self.open_folder,
                  bg=BG, fg=MUTED, activebackground=BG, relief="flat",
                  font=("Segoe UI", 10, "underline"), cursor="hand2").pack(side="right")

        tk.Label(outer, text="Activity", bg=BG, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(19, 7))
        log_frame = tk.Frame(outer, bg=PANEL)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, bg=PANEL, fg=MUTED, insertbackground=TEXT,
                                relief="flat", wrap="word", padx=12, pady=10,
                                font=("Consolas", 9), state="disabled", height=9)
        self.log_text.pack(fill="both", expand=True)
        self._log("Ready. The setup starts automatically when this window opens.")

    def _log(self, message):
        stamp = time.strftime("%H:%M:%S")
        try:
            with LOG_FILE.open("a", encoding="utf-8") as log:
                log.write(f"{stamp}  {message}\n")
        except OSError:
            pass
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{stamp}  {message}\n")
        if int(self.log_text.index("end-1c").split(".")[0]) > 200:
            self.log_text.delete("1.0", "50.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _status(self, key, label, color):
        self.status_labels[key].configure(text=label, fg=color)

    def _draw_meter(self):
        width = max(self.meter.winfo_width(), 1)
        self.meter.delete("all")
        self.meter.create_rectangle(0, 0, width * self.level, 16, fill=TEAL, outline="")

    def _set_level(self, level):
        self.level = max(0.0, min(float(level), 1.0))
        self.level_label.configure(text=f"{self.level:.3f}")
        self._draw_meter()

    def _start_bluemuse(self):
        try:
            os.startfile("bluemuse://start?startall")
            self.last_bluemuse_launch = time.monotonic()
            self._log("BlueMuse start-on-discovery requested.")
        except OSError as exc:
            self._status("bluemuse", "Error", RED)
            self._log(f"Could not open BlueMuse: {exc}")

    def _start_touchdesigner(self):
        windows = touchdesigner_windows()
        if windows:
            matching = [(pid, title) for pid, title in windows
                        if "MuseTouchDesigner" in title or "NewProject." in title]
            if len(matching) == 1:
                self.touchdesigner_pid = matching[0][0]
                self._log("Using the already-open Muse TouchDesigner project; it will close with this setup.")
            else:
                self._log("TouchDesigner is already open with another project; leaving it alone.")
            self._status("touchdesigner", "Already open", TEAL)
            return
        if not TOUCHDESIGNER.is_file() or not PROJECT.is_file():
            self._status("touchdesigner", "Missing", RED)
            self._log("TouchDesigner or the .toe project file is missing.")
            return
        try:
            self.touchdesigner = subprocess.Popen(
                [str(TOUCHDESIGNER), str(PROJECT)], cwd=str(ROOT)
            )
            self.touchdesigner_pid = self.touchdesigner.pid
            self._status("touchdesigner", "Opening", YELLOW)
            self._log("Opening the saved TouchDesigner project.")
        except OSError as exc:
            self._status("touchdesigner", "Error", RED)
            self._log(f"Could not open TouchDesigner: {exc}")

    def _start_bridge(self):
        if self.bridge is not None and self.bridge.poll() is None:
            return
        if not BRIDGE.is_file() or not PYTHON.is_file():
            self._status("bridge", "Missing", RED)
            self._log("Python or eeg_to_osc.py is missing.")
            return
        try:
            self.bridge = subprocess.Popen(
                [str(PYTHON), "-u", str(BRIDGE)], cwd=str(ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", bufsize=1, creationflags=CREATE_NO_WINDOW,
            )
            threading.Thread(target=self._read_bridge, args=(self.bridge,), daemon=True).start()
            self._status("bridge", "Running", TEAL)
            self._status("headset", "Searching", YELLOW)
            self._log("EEG bridge started; searching for the headset.")
        except OSError as exc:
            self._status("bridge", "Error", RED)
            self._log(f"Could not start the bridge: {exc}")

    def _read_bridge(self, process):
        try:
            for line in process.stdout:
                line = line.strip()
                if line and "INFO|" not in line:
                    self.events.put((process.pid, line))
        except (OSError, ValueError):
            pass

    def start_all(self):
        if self.stopping:
            return
        if self.bridge is None and existing_bridge_pids():
            self._status("bridge", "Already open", YELLOW)
            self._log("The manual EEG bridge is already running. Press Ctrl+C in its PowerShell window, then click Start all here.")
            return
        first_start = not self.want_running
        self.want_running = True
        if first_start:
            self._log("Starting the full setup...")
        self.restart_attempts = 0
        self._start_bluemuse()
        self._start_touchdesigner()
        self._start_bridge()
        self.start_button.configure(state="disabled" if self.bridge is not None else "normal")
        self.stop_button.configure(state="normal")

    def stop_all(self):
        if self.stopping:
            return
        if not self.want_running and self.bridge is None and self.touchdesigner_pid is None:
            return
        self.stopping = True
        self.want_running = False
        self._log("Stopping the setup...")

        if self.bridge is not None and self.bridge.poll() is None:
            self.bridge.terminate()
            try:
                self.bridge.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.bridge.kill()
            self._log("EEG bridge stopped.")
        self.bridge = None
        try:
            send_osc("/eeg/level", 0)
            send_osc("/eeg/connected", 0)
        except OSError:
            pass

        try:
            os.startfile("bluemuse://stop?stopall")
            os.startfile("bluemuse://shutdown")
            self._log("BlueMuse stop and close requested.")
        except OSError as exc:
            self._log(f"Could not close BlueMuse: {exc}")

        if self.touchdesigner_pid is not None:
            if request_normal_close(self.touchdesigner_pid):
                self._log("TouchDesigner close requested; save if it asks.")
            else:
                self._log("TouchDesigner had already closed or needs to be closed manually.")
        self.touchdesigner = None
        self.touchdesigner_pid = None

        self.headset_connected = False
        self._set_level(0)
        self._status("headset", "Stopped", MUTED)
        self._status("bridge", "Stopped", MUTED)
        self._status("bluemuse", "Stopping", YELLOW)
        self._status("touchdesigner", "Closing", YELLOW)
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.stopping = False

    def _handle_bridge_line(self, line):
        if "EEG connected." in line:
            self.headset_connected = True
            self.last_level_at = time.monotonic()
            self._status("headset", "Connected", TEAL)
            self._log("Headset connected. Sending live data to TouchDesigner.")
        elif "EEG stopped." in line or "EEG stream lost:" in line:
            self.headset_connected = False
            self._set_level(0)
            self._status("headset", "Reconnecting", YELLOW)
            self._log("Headset signal stopped. Reconnecting automatically...")
        elif "level:" in line:
            match = re.search(r"level:\s*([0-9.]+)", line)
            if match:
                self._set_level(float(match.group(1)))
                self.last_level_at = time.monotonic()
                self.headset_connected = True
                self._status("headset", "Connected", TEAL)
        elif "Waiting for BlueMuse" in line or "Found " in line:
            self._log(line)
        elif "ModuleNotFoundError" in line:
            self._log("Python packages missing. Run: py -m pip install pylsl python-osc")
            self.restart_attempts = 3
        elif "Traceback" in line or "Error" in line or "failed" in line:
            self._log(line)

    def _poll(self):
        while True:
            try:
                pid, line = self.events.get_nowait()
            except queue.Empty:
                break
            if self.bridge is not None and pid == self.bridge.pid:
                self._handle_bridge_line(line)

        now = time.monotonic()
        if self.want_running and self.bridge is not None and self.bridge.poll() is not None:
            self._status("bridge", "Restarting", YELLOW)
            self.headset_connected = False
            self._set_level(0)
            if now >= self.next_restart_at and self.restart_attempts < 3:
                self.restart_attempts += 1
                self.next_restart_at = now + 3.0
                self._log(f"Bridge exited. Restarting ({self.restart_attempts}/3)...")
                self._start_bridge()
            elif self.restart_attempts >= 3:
                self._status("bridge", "Needs help", RED)
                self.start_button.configure(state="normal")
        if self.want_running and self.headset_connected:
            self.restart_attempts = 0

        if now - self.last_process_check >= 2:
            self.last_process_check = now
            self.bluemuse_open = process_running("BlueMuse.exe")
            self._status("bluemuse", "Open" if self.bluemuse_open else "Closed",
                         TEAL if self.bluemuse_open else MUTED)
            td_open = process_running("TouchDesigner.exe")
            self._status("touchdesigner", "Open" if td_open else "Closed",
                         TEAL if td_open else MUTED)
            if self.want_running and not self.bluemuse_open and now - self.last_bluemuse_launch > 10:
                self._start_bluemuse()

        if self.want_running and self.headset_connected and now - self.last_level_at > 4:
            self.headset_connected = False
            self._set_level(0)
            self._status("headset", "Reconnecting", YELLOW)

        self.after(250, self._poll)

    def open_folder(self):
        os.startfile(str(ROOT))

    def close(self):
        self.stop_all()
        self.destroy()


if __name__ == "__main__":
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", 45981))
        lock.listen(1)
    except OSError:
        messagebox.showinfo("Already open", "The Muse + TouchDesigner launcher is already open.")
        sys.exit(0)
    try:
        Launcher().mainloop()
    except Exception:
        details = traceback.format_exc()
        try:
            with LOG_FILE.open("a", encoding="utf-8") as log:
                log.write(details)
        except OSError:
            pass
        messagebox.showerror("Launcher error", f"The launcher stopped unexpectedly.\n\n{details[-1200:]}")
    finally:
        lock.close()
