"""Opt-in Xvfb acceptance shared by source and frozen Linux builds.

Synthetic input is forbidden unless GREMLIN_ISOLATED_X11=1. The receiver is
another process; a successful event proves actual X-server routing, not a Tk
event_generate call or an inspection of window-style flags.
"""
import ctypes as C
import ctypes.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def _isolated():
    if not sys.platform.startswith("linux") or os.environ.get("GREMLIN_ISOLATED_X11") != "1" or not os.environ.get("DISPLAY"):
        raise RuntimeError("X11 input probes require an explicitly isolated X server")


def _write(path, value):
    temp = str(path) + ".tmp"
    with open(temp, "w", encoding="utf-8") as stream:
        json.dump(value, stream)
    os.replace(temp, path)


def receiver_main(report_path):
    """CLI entry used by the same executable, requiring no external Python."""
    _isolated()
    import tkinter as tk
    root = tk.Tk()
    root.overrideredirect(os.environ.get("GREMLIN_MANAGED_RECEIVER") != "1")
    root.title("Desktop Gremlin self-test receiver %s" % os.getpid())
    root.geometry("480x360+0+0")
    canvas = tk.Canvas(root, width=480, height=360, bg="#284737", highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)
    state = {"ready": True, "clicks": [], "pid": os.getpid(), "window": int(root.winfo_id())}

    def click(event):
        state["clicks"].append([event.x, event.y])
        _write(report_path, state)

    def check_stop():
        if os.path.exists(str(report_path) + ".stop"):
            root.destroy()
        else:
            root.after(20, check_stop)

    canvas.bind("<ButtonPress-1>", click)
    root.update()
    _write(report_path, state)
    root.after(20, check_stop)
    root.after(30000, root.destroy)
    root.mainloop()
    return 0


class _Injector:
    def __init__(self):
        _isolated()
        self.x = C.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self.test = C.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
        self.x.XOpenDisplay.argtypes, self.x.XOpenDisplay.restype = [C.c_char_p], C.c_void_p
        self.x.XCloseDisplay.argtypes = [C.c_void_p]
        self.x.XSync.argtypes = [C.c_void_p, C.c_int]
        self.x.XStringToKeysym.argtypes, self.x.XStringToKeysym.restype = [C.c_char_p], C.c_ulong
        self.x.XKeysymToKeycode.argtypes, self.x.XKeysymToKeycode.restype = [C.c_void_p, C.c_ulong], C.c_uint
        self.test.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
        self.test.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
        self.test.XTestFakeKeyEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
        self.d = self.x.XOpenDisplay(None)
        if not self.d:
            raise RuntimeError("Cannot connect XTest to isolated display")

    def motion(self, x, y):
        self.test.XTestFakeMotionEvent(self.d, -1, int(x), int(y), 0)
        self.x.XSync(self.d, 0)

    def button(self, down):
        self.test.XTestFakeButtonEvent(self.d, 1, int(down), 0)
        self.x.XSync(self.d, 0)

    def key(self, name, down):
        code = self.x.XKeysymToKeycode(self.d, self.x.XStringToKeysym(name.encode("ascii")))
        if not code:
            raise RuntimeError("XTest key is unavailable: " + name)
        self.test.XTestFakeKeyEvent(self.d, code, int(down), 0)
        self.x.XSync(self.d, 0)

    def close(self):
        if self.d:
            self.x.XCloseDisplay(self.d)
            self.d = None


def _pump(app, seconds=.12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not getattr(app, "running", True):
            return
        app.root.update()
        if hasattr(app, "tray"):
            app.tray.pump()
            if hasattr(app.tray, "drain"):
                app.tray.drain()
        time.sleep(.005)


def _receiver_command(path):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--input-receiver", str(path)]
    return [sys.executable, "-B", str(Path(__file__).resolve()), "--input-receiver", str(path)]


def _mouse_checks(app, inject, report):
    def clicks():
        with open(report, encoding="utf-8") as stream:
            return json.load(stream)["clicks"]

    deadline = time.monotonic() + 6
    while not report.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Separate X11 input receiver did not start")
        _pump(app, .03)
    if json.loads(report.read_text())["pid"] == os.getpid():
        raise RuntimeError("Input receiver must be a separate process")

    f = app.fighters[0]
    for other in app.fighters[1:]:
        other.x, other.y = -9000, -9000
    f.sc, f.x, f.y = 1, app.ox + 160, app.oy + 184
    f.grabbed = False
    actor_x = 160

    def paint():
        app.canvas.delete("all")
        app.canvas.create_oval(actor_x - 20, 130, actor_x + 20, 170,
                              fill="white", outline="white", width=2)
        app.canvas.create_line(actor_x, 150, actor_x, 185, fill="white", width=5)
        app.canvas.create_rectangle(260, 220, 280, 240, fill="cyan", outline="")
        app.x11_overlay.show()
        if not app.x11_overlay.present(app.fighters, app.ox, app.oy):
            raise RuntimeError(app.x11_overlay.error)
        _pump(app)

    def click(x, y):
        inject.motion(app.ox + x, app.oy + y)
        inject.button(True)
        _pump(app)
        inject.button(False)
        _pump(app)

    paint()
    before = len(clicks())
    click(40, 40)
    empty = len(clicks()) == before + 1
    before = len(clicks())
    click(270, 230)  # visible decorative prop must also pass input through
    decorative = len(clicks()) == before + 1

    # Pausing clears both masks, even while the top-level remains mapped.
    app.x11_overlay.clear()
    _pump(app)
    before = len(clicks())
    click(actor_x, 150)
    cleared = len(clicks()) == before + 1
    paint()

    before = len(clicks())
    inject.motion(app.ox + actor_x, app.oy + 150)
    inject.button(True)
    _pump(app)
    actor_grab = f.grabbed and len(clicks()) == before
    inject.button(False)
    _pump(app)
    actor_release = not f.grabbed

    # The old location must stop intercepting as soon as the shape moves.
    actor_x = 240
    f.x = app.ox + actor_x
    paint()
    before = len(clicks())
    click(160, 150)
    moved = len(clicks()) == before + 1

    # A real implicit Tk drag must still release after leaving every shape.
    inject.motion(app.ox + actor_x, app.oy + 150)
    inject.button(True)
    _pump(app)
    started = f.grabbed
    inject.motion(app.ox + 440, app.oy + 320)
    _pump(app)
    dragged = abs(getattr(f, "gx", -9999) - (app.ox + 440)) < 2
    inject.button(False)
    _pump(app)
    released = not f.grabbed
    before = len(clicks())
    click(40, 40)
    released_desktop = len(clicks()) == before + 1

    # Fullscreen hiding during a drag must run app's normal release path.
    inject.motion(app.ox + actor_x, app.oy + 150)
    inject.button(True)
    _pump(app)
    if hasattr(app, "set_held"):
        app.set_held(True)
    else:
        app.on_up(None)
        app.x11_overlay.hide()
    inject.button(False)
    _pump(app)
    before = len(clicks())
    click(actor_x, 150)
    hidden = len(clicks()) == before + 1 and not f.grabbed
    if hasattr(app, "set_held"):
        app.set_held(False)
    paint()
    before = len(clicks())
    click(40, 40)
    reshown = len(clicks()) == before + 1
    return {"transparent_passthrough": all((empty, decorative, cleared, moved, hidden, reshown)),
            "opaque_interaction": bool(actor_grab and actor_release),
            "outside_drag_release": bool(started and dragged and released and released_desktop)}


def run_input_probe(app, emergency=True):
    """Mutates an isolated test App; emergency exit destroys it on completion."""
    _isolated()
    inject = _Injector()
    with tempfile.TemporaryDirectory(prefix="gremlin-x11-probe-") as folder:
        report = Path(folder) / "receiver.json"
        process = subprocess.Popen(_receiver_command(report), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=os.environ.copy())
        try:
            checks = _mouse_checks(app, inject, report)
            if emergency:
                for name in ("Control_L", "Alt_L", "Shift_L", "q"):
                    inject.key(name, True)
                # Release all keys even if app.quit tears down Tk immediately.
                for name in ("q", "Shift_L", "Alt_L", "Control_L"):
                    inject.key(name, False)
                _pump(app, .3)
                checks["emergency_exit"] = not app.running
            return checks
        finally:
            inject.button(False)
            inject.close()
            Path(str(report) + ".stop").touch()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.communicate(timeout=3)


if __name__ == "__main__" and sys.argv[1:2] == ["--input-receiver"]:
    sys.exit(receiver_main(sys.argv[2]))
