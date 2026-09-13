"""Linux desktop boundaries and a small, always available control window."""
import hashlib
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk

_desktop = None
_closed = False
_service_lock = threading.RLock()
_instances = {}


def desktop():
    global _desktop
    with _service_lock:
        if _closed:
            raise RuntimeError("Desktop Gremlin's X11 session is closed")
        if _desktop is None:
            from gremlin_x11 import X11Desktop
            _desktop = X11Desktop()
        return _desktop


def start():
    global _closed
    with _service_lock:
        _closed = False
        return desktop()


def close():
    global _desktop, _closed
    with _service_lock:
        _closed = True
        if _desktop is not None:
            _desktop.close()
            _desktop = None


def claim_instance(data_dir, name="DesktopGremlin"):
    import fcntl
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, ".instance-" + hashlib.sha256(name.encode()).hexdigest()[:16])
    if path in _instances:
        return False
    handle = open(path, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return False
    except Exception:
        handle.close()
        raise
    _instances[path] = handle
    return True


def release_instances():
    for handle in _instances.values():
        handle.close()
    _instances.clear()


def _desktop_arg(value):
    # Desktop Entry Exec quoting has two escaping layers, including literal %.
    value = value.replace("%", "%%")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return '"' + value.replace("\\", "\\\\") + '"'


def set_run_at_startup(on, script_path=None):
    base = os.environ.get("XDG_CONFIG_HOME", "")
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "autostart", "DesktopGremlin.desktop")
    try:
        if not on:
            if os.path.isfile(path):
                os.remove(path)
            return True
        args = [sys.executable]
        if not getattr(sys, "frozen", False):
            args.append(os.path.abspath(script_path))
        if any("\n" in arg or "\r" in arg for arg in args):
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as out:
            out.write("[Desktop Entry]\nType=Application\nName=Desktop Gremlin\n"
                      "Comment=Animated desktop companions\nTerminal=false\nExec=" +
                      " ".join(_desktop_arg(arg) for arg in args) + "\n")
        os.replace(path + ".tmp", path)
        return True
    except (OSError, TypeError):
        return False


class NullShell:
    """Desktop icon manipulation has no common Linux file-manager API."""
    restore_complete = False
    def open(self): return False
    def read_icons(self): return []
    def snapshot(self): return None
    def item_pos(self, index): return None
    def item_rect(self, index): return None
    def set_item_pos(self, index, x, y): return False
    def restore(self, icons): return 0
    def close(self): pass


class LinuxControls:
    def __init__(self, root):
        self.root = root
        self.win = None
        self.items = []
        self.pending = []
        self.quit_callback = None
        self.emergency_registered = False
        self.status = None

    def add(self, label, callback, kind=None, checked=None):
        self.items.append((label, callback, kind, checked))

    def sep(self):
        self.items.append(None)

    def _enqueue_quit(self):
        if self.quit_callback:
            self.pending.append(self.quit_callback)

    def build(self):
        self.win = tk.Toplevel(self.root)
        self.win.title("Desktop Gremlin")
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self._enqueue_quit)
        frame = ttk.Frame(self.win, padding=12)
        frame.pack(fill="both", expand=True)
        for item in self.items:
            if item is None:
                ttk.Separator(frame).pack(fill="x", pady=5)
            else:
                label, callback, kind, checked = item
                ttk.Button(frame, text="Pause / Resume" if kind == "check" else label,
                           command=lambda fn=callback: self.pending.append(fn)).pack(fill="x", pady=2)
        self.emergency_registered = desktop().register_quit(self.root, self._enqueue_quit)
        self.status = tk.StringVar(value=("Exit: Ctrl+Alt+Shift+Q" if self.emergency_registered
                                         else "Use Quit or close this window to exit."))
        ttk.Label(frame, textvariable=self.status, wraplength=240).pack(pady=(8, 0))
        return True

    def popup(self, event=None):
        if self.win is not None:
            self.win.deiconify()
            self.win.lift()

    def notify(self, title, text):
        if self.status is not None:
            self.status.set(text)

    def pump(self):
        desktop().pump()

    def drain(self):
        pending, self.pending = self.pending, []
        for callback in pending:
            callback()

    def remove(self):
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None
        close()
