"""
rotator_gui.py - 로테이터(포지셔너 TC-5594A) AZ/EL 제어 GUI (노트북에서 실행)

rotator_control.py 의 통신 코드(Positioner)를 그대로 사용하고, 화면에서
연결/이동/속도/조그를 조작한다. 포지셔너 통신은 전용 작업 스레드 하나에서만
처리하므로 이동 중에도 화면이 멈추지 않는다.

사용법
  pip install pyserial
  python rotator_gui.py
"""
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext
from datetime import datetime

import rotator_control as rc
from rotator_control import Positioner, PositionerError, AZ_AXIS, EL_AXIS

POLL_INTERVAL_S = 0.5      # 대기 중 현재각 갱신 주기
MOVE_POLL_S = 0.2          # 이동 중 현재각 폴링 주기


def list_serial_ports():
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


# ==========================================================================
# 포지셔너 작업 스레드 (모든 통신은 여기서만)
# ==========================================================================
class PositionerWorker(threading.Thread):
    def __init__(self, ui_queue):
        super().__init__(daemon=True)
        self.cmds = queue.Queue()
        self.ui = ui_queue
        self.pos = None
        self.cancel = threading.Event()
        self.poll_error = False

    # --- UI 로 메시지 전달 ---
    def emit(self, *msg):
        self.ui.put(msg)

    def log(self, text):
        self.emit("log", text)

    # --- UI 에서 호출 ---
    def submit(self, name, *args):
        self.cmds.put((name, args))

    # --- 스레드 본체 ---
    def run(self):
        while True:
            try:
                name, args = self.cmds.get(timeout=POLL_INTERVAL_S)
            except queue.Empty:
                if self.pos is not None:
                    self._poll()
                continue

            if name == "quit":
                self._do_disconnect()
                return
            try:
                getattr(self, "_do_" + name)(*args)
            except (PositionerError, ValueError) as e:
                self.log(f"[ERROR] {e}")
            except Exception as e:
                self.log(f"[ERROR] {type(e).__name__}: {e}")
            finally:
                self.emit("busy", False)

    def _read_both(self):
        return self.pos.angle(AZ_AXIS), self.pos.angle(EL_AXIS)

    def _poll(self):
        try:
            az, el = self._read_both()
            self.emit("pos", az, el)
            if self.poll_error:
                self.log("position read recovered")
            self.poll_error = False
        except Exception as e:
            if not self.poll_error:          # 같은 오류를 반복해서 찍지 않음
                self.log(f"[WARN] position read failed: {e}")
            self.poll_error = True

    # --- 명령 처리 ---
    def _do_connect(self, transport, host, port, com, baud, speed):
        self._do_disconnect(quiet=True)
        where = f"{host}:{port}" if transport == "tcp" else f"{com} @ {baud}"
        self.log(f"connecting ({transport} {where}) ...")
        pos = Positioner(transport, host, port, com, baud, rc.POS_EOL)
        pos.open()
        try:
            model = pos.query("MODEL?")
            for ax in (AZ_AXIS, EL_AXIS):
                pos.command(f"{ax}:TORQ ON")
                pos.command(f"{ax}:SPD {speed}")
        except Exception:
            pos.close()
            raise
        self.pos = pos
        self.log(f"connected: {model} (torque ON, speed {speed})")
        self.emit("connected", True)
        self._poll()

    def _do_disconnect(self, quiet=False):
        if self.pos is not None:
            try:
                self.pos.close()
            finally:
                self.pos = None
            if not quiet:
                self.log("disconnected")
        self.emit("connected", False)

    def _do_speed(self, speed):
        self._require()
        if not (1 <= speed <= 10):
            raise ValueError("speed must be 1 ~ 10")
        for ax in (AZ_AXIS, EL_AXIS):
            self.pos.command(f"{ax}:SPD {speed}")
        self.log(f"speed set to {speed}")

    def _do_move(self, az, el):
        self._require()
        targets = {}
        if az is not None:
            rc.check_limit("AZ", az, rc.AZ_LIMIT)
            targets[AZ_AXIS] = az
        if el is not None:
            rc.check_limit("EL", el, rc.EL_LIMIT)
            targets[EL_AXIS] = el
        if not targets:
            return

        desc = ", ".join(f"{'AZ' if ax == AZ_AXIS else 'EL'} {deg:+g}" for ax, deg in targets.items())
        self.log(f"move: {desc} deg")
        for ax, deg in targets.items():
            self.pos.move(ax, deg)

        self.cancel.clear()
        self.emit("state", f"Moving -> {desc}")
        t0 = time.monotonic()
        deadline = t0 + rc.POS_MOVE_TIMEOUT_S
        hits = {ax: 0 for ax in targets}
        while True:
            if self.cancel.is_set():
                self.log("wait cancelled (rotator may still be moving)")
                return
            if time.monotonic() > deadline:
                raise PositionerError(f"move timeout ({rc.POS_MOVE_TIMEOUT_S}s): {desc}")
            az_now, el_now = self._read_both()
            self.emit("pos", az_now, el_now)
            cur = {AZ_AXIS: az_now, EL_AXIS: el_now}
            for ax, tgt in targets.items():
                hits[ax] = hits[ax] + 1 if abs(cur[ax] - tgt) <= rc.POS_TOL_DEG else 0
            if all(h >= 2 for h in hits.values()):
                self.log(f"arrived ({time.monotonic() - t0:.1f}s): AZ {az_now:+.2f}, EL {el_now:+.2f} deg")
                return
            time.sleep(MOVE_POLL_S)

    def _require(self):
        if self.pos is None:
            raise PositionerError("not connected")


# ==========================================================================
# GUI
# ==========================================================================
class RotatorApp:
    def __init__(self, root):
        self.root = root
        self.ui_queue = queue.Queue()
        self.worker = PositionerWorker(self.ui_queue)
        self.worker.start()
        self.connected = False
        self.busy = False
        self.cur_az = None
        self.cur_el = None

        root.title("Rotator Control (TC-5594A)")
        root.minsize(560, 560)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_connection()
        self._build_position()
        self._build_move()
        self._build_jog()
        self._build_log()

        self._update_enable()
        self.root.after(50, self._drain_ui_queue)

    # ---------------- 화면 구성 ----------------
    def _build_connection(self):
        f = ttk.LabelFrame(self.root, text="Connection", padding=8)
        f.pack(fill="x", padx=10, pady=(10, 5))

        self.transport = tk.StringVar(value=rc.POS_TRANSPORT)
        ttk.Radiobutton(f, text="Serial", value="serial", variable=self.transport,
                        command=self._update_enable).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(f, text="TCP", value="tcp", variable=self.transport,
                        command=self._update_enable).grid(row=1, column=0, sticky="w")

        ttk.Label(f, text="COM").grid(row=0, column=1, sticky="e", padx=(10, 2))
        self.com = tk.StringVar(value=rc.POS_COM)
        self.com_box = ttk.Combobox(f, textvariable=self.com, width=10,
                                    values=list_serial_ports() or [rc.POS_COM])
        self.com_box.grid(row=0, column=2, sticky="w")
        self.refresh_btn = ttk.Button(f, text="↻", width=3, command=self._refresh_ports)
        self.refresh_btn.grid(row=0, column=3, padx=2)
        ttk.Label(f, text="Baud").grid(row=0, column=4, sticky="e", padx=(10, 2))
        self.baud = tk.StringVar(value=str(rc.POS_BAUD))
        self.baud_box = ttk.Combobox(f, textvariable=self.baud, width=8,
                                     values=["9600", "19200", "38400", "57600", "115200"])
        self.baud_box.grid(row=0, column=5, sticky="w")

        ttk.Label(f, text="Host").grid(row=1, column=1, sticky="e", padx=(10, 2))
        self.host = tk.StringVar(value=rc.POS_HOST)
        self.host_entry = ttk.Entry(f, textvariable=self.host, width=15)
        self.host_entry.grid(row=1, column=2, columnspan=2, sticky="w")
        ttk.Label(f, text="Port").grid(row=1, column=4, sticky="e", padx=(10, 2))
        self.port = tk.StringVar(value=str(rc.POS_PORT))
        self.port_entry = ttk.Entry(f, textvariable=self.port, width=8)
        self.port_entry.grid(row=1, column=5, sticky="w")

        self.conn_btn = ttk.Button(f, text="Connect", command=self.on_connect)
        self.conn_btn.grid(row=0, column=6, rowspan=2, padx=(15, 0), sticky="ns")

        self.status = tk.StringVar(value="Disconnected")
        self.status_label = tk.Label(f, textvariable=self.status, fg="gray", anchor="w")
        self.status_label.grid(row=2, column=0, columnspan=7, sticky="we", pady=(6, 0))

    def _build_position(self):
        f = ttk.LabelFrame(self.root, text="Current position", padding=8)
        f.pack(fill="x", padx=10, pady=5)
        big = ("Consolas", 22, "bold")
        ttk.Label(f, text="AZ").grid(row=0, column=0, padx=(10, 5))
        self.az_disp = tk.StringVar(value="---.--")
        ttk.Label(f, textvariable=self.az_disp, font=big, width=8, anchor="e").grid(row=0, column=1)
        ttk.Label(f, text="deg").grid(row=0, column=2, padx=(2, 30))
        ttk.Label(f, text="EL").grid(row=0, column=3, padx=(10, 5))
        self.el_disp = tk.StringVar(value="---.--")
        ttk.Label(f, textvariable=self.el_disp, font=big, width=8, anchor="e").grid(row=0, column=4)
        ttk.Label(f, text="deg").grid(row=0, column=5, padx=2)

    def _build_move(self):
        f = ttk.LabelFrame(self.root, text="Move", padding=8)
        f.pack(fill="x", padx=10, pady=5)

        ttk.Label(f, text=f"Azimuth ({rc.AZ_LIMIT[0]:g} ~ {rc.AZ_LIMIT[1]:g})").grid(row=0, column=0, sticky="w")
        self.az_target = tk.StringVar(value="0")
        self.az_entry = ttk.Entry(f, textvariable=self.az_target, width=10)
        self.az_entry.grid(row=0, column=1, padx=5)
        self.az_btn = ttk.Button(f, text="Move AZ", command=lambda: self.on_move(True, False))
        self.az_btn.grid(row=0, column=2, padx=2)

        ttk.Label(f, text=f"Elevation ({rc.EL_LIMIT[0]:g} ~ {rc.EL_LIMIT[1]:g})").grid(row=1, column=0, sticky="w")
        self.el_target = tk.StringVar(value="0")
        self.el_entry = ttk.Entry(f, textvariable=self.el_target, width=10)
        self.el_entry.grid(row=1, column=1, padx=5)
        self.el_btn = ttk.Button(f, text="Move EL", command=lambda: self.on_move(False, True))
        self.el_btn.grid(row=1, column=2, padx=2)

        self.both_btn = ttk.Button(f, text="Move AZ + EL", command=lambda: self.on_move(True, True))
        self.both_btn.grid(row=0, column=3, rowspan=2, padx=(10, 2), sticky="ns")
        self.home_btn = ttk.Button(f, text="Home (0, 0)", command=self.on_home)
        self.home_btn.grid(row=0, column=4, rowspan=2, padx=2, sticky="ns")
        self.cancel_btn = ttk.Button(f, text="Cancel wait", command=self.on_cancel)
        self.cancel_btn.grid(row=0, column=5, rowspan=2, padx=2, sticky="ns")

        ttk.Label(f, text="Speed (1~10)").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.speed = tk.StringVar(value=str(rc.POS_SPEED))
        self.speed_spin = ttk.Spinbox(f, from_=1, to=10, textvariable=self.speed, width=8)
        self.speed_spin.grid(row=2, column=1, padx=5, pady=(8, 0))
        self.speed_btn = ttk.Button(f, text="Set speed", command=self.on_speed)
        self.speed_btn.grid(row=2, column=2, padx=2, pady=(8, 0))

        for e in (self.az_entry, self.el_entry):
            e.bind("<Return>", lambda ev: self.on_move(True, True))

    def _build_jog(self):
        f = ttk.LabelFrame(self.root, text="Jog (relative to current position)", padding=8)
        f.pack(fill="x", padx=10, pady=5)
        ttk.Label(f, text="Step [deg]").grid(row=0, column=0, padx=(0, 5))
        self.jog_step = tk.StringVar(value="1")
        ttk.Combobox(f, textvariable=self.jog_step, width=6,
                     values=["0.1", "0.5", "1", "5", "10", "30"]).grid(row=0, column=1, padx=(0, 15))
        self.jog_btns = []
        for col, (text, daz, delv) in enumerate([("AZ −", -1, 0), ("AZ +", 1, 0),
                                                 ("EL −", 0, -1), ("EL +", 0, 1)]):
            b = ttk.Button(f, text=text, width=7, command=lambda a=daz, e=delv: self.on_jog(a, e))
            b.grid(row=0, column=2 + col, padx=2)
            self.jog_btns.append(b)

    def _build_log(self):
        f = ttk.LabelFrame(self.root, text="Log", padding=4)
        f.pack(fill="both", expand=True, padx=10, pady=(5, 10))
        self.log_text = scrolledtext.ScrolledText(f, height=10, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

    # ---------------- 상태 ----------------
    def log(self, text):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {text}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_status(self, text, color):
        self.status.set(text)
        self.status_label.configure(fg=color)

    def _update_enable(self):
        tcp = self.transport.get() == "tcp"
        conn_cfg = "disabled" if (self.connected or self.busy) else "normal"
        for w in (self.com_box, self.refresh_btn, self.baud_box):
            w.configure(state="disabled" if tcp else conn_cfg)
        for w in (self.host_entry, self.port_entry):
            w.configure(state=conn_cfg if tcp else "disabled")

        self.conn_btn.configure(text="Disconnect" if self.connected else "Connect",
                                state="disabled" if (self.busy and not self.connected) else "normal")
        ctl = "normal" if (self.connected and not self.busy) else "disabled"
        for w in [self.az_btn, self.el_btn, self.both_btn, self.home_btn,
                  self.speed_btn, *self.jog_btns]:
            w.configure(state=ctl)
        self.cancel_btn.configure(state="normal" if (self.connected and self.busy) else "disabled")

    def _set_busy(self, busy):
        self.busy = busy
        if self.connected:
            self.set_status("Moving..." if busy else "Connected - idle", "orange" if busy else "green")
        self._update_enable()

    def _drain_ui_queue(self):
        try:
            while True:
                msg = self.ui_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.log(msg[1])
                elif kind == "pos":
                    self.cur_az, self.cur_el = msg[1], msg[2]
                    self.az_disp.set(f"{self.cur_az:+.2f}")
                    self.el_disp.set(f"{self.cur_el:+.2f}")
                elif kind == "connected":
                    self.connected = msg[1]
                    if not self.connected:
                        self.az_disp.set("---.--")
                        self.el_disp.set("---.--")
                        self.cur_az = self.cur_el = None
                        self.set_status("Disconnected", "gray")
                    else:
                        self.set_status("Connected - idle", "green")
                    self._update_enable()
                elif kind == "state":
                    self.set_status(msg[1], "orange")
                elif kind == "busy":
                    self._set_busy(msg[1])
        except queue.Empty:
            pass
        self.root.after(50, self._drain_ui_queue)

    def _submit(self, name, *args):
        self._set_busy(True)
        self.worker.submit(name, *args)

    # ---------------- 이벤트 ----------------
    def _refresh_ports(self):
        ports = list_serial_ports()
        self.com_box.configure(values=ports or [rc.POS_COM])
        self.log("serial ports: " + (", ".join(ports) if ports else "(none found)"))

    def on_connect(self):
        if self.connected:
            self._submit("disconnect")
            return
        try:
            port = int(self.port.get())
            baud = int(self.baud.get())
            speed = int(self.speed.get())
        except ValueError:
            self.log("[ERROR] port / baud / speed must be integers")
            return
        self.set_status("Connecting...", "orange")
        self._submit("connect", self.transport.get(), self.host.get().strip(), port,
                     self.com.get().strip(), baud, speed)

    def _read_float(self, var, name):
        try:
            return float(var.get())
        except ValueError:
            self.log(f"[ERROR] invalid {name}: '{var.get()}'")
            return None

    def on_move(self, use_az, use_el):
        az = el = None
        if use_az:
            az = self._read_float(self.az_target, "azimuth")
            if az is None:
                return
        if use_el:
            el = self._read_float(self.el_target, "elevation")
            if el is None:
                return
        self._submit("move", az, el)

    def on_home(self):
        self.az_target.set("0")
        self.el_target.set("0")
        self._submit("move", 0.0, 0.0)

    def on_jog(self, daz, delv):
        step = self._read_float(self.jog_step, "jog step")
        if step is None:
            return
        if self.cur_az is None or self.cur_el is None:
            self.log("[ERROR] current position unknown")
            return
        az = round(self.cur_az + daz * step, 3) if daz else None
        el = round(self.cur_el + delv * step, 3) if delv else None
        if az is not None:
            self.az_target.set(f"{az:g}")
        if el is not None:
            self.el_target.set(f"{el:g}")
        self._submit("move", az, el)

    def on_speed(self):
        try:
            speed = int(self.speed.get())
        except ValueError:
            self.log("[ERROR] speed must be an integer 1 ~ 10")
            return
        self._submit("speed", speed)

    def on_cancel(self):
        self.worker.cancel.set()

    def on_close(self):
        self.worker.cancel.set()
        self.worker.submit("quit")
        self.worker.join(timeout=3)
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    RotatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
