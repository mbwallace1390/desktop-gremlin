#!/usr/bin/env python3
r"""
DESKTOP GREMLIN — overlay edition
=================================
A cast of chaotic stick figures -- one to ten of them, each with its own
temperament and its own mouth -- who live ON TOP of your real Windows desktop
and treat your actual icons and open windows as their personal playground.

They read the real thing:
  * your desktop icons   — the shell's SysListView32 control
  * your open windows    — EnumWindows + the DWM frame bounds
  * what you're doing    — foreground window, window titles, idle time

And, if you let them, they physically drag your desktop icons around.
Your original layout is saved on first run; "Restore my icon layout" in the
tray menu puts everything back.

Requires: Windows, Python 3.8+, pywin32.
Run:      run_gremlin.bat      Quit: tray icon -> Quit
Debug:    run_gremlin.bat --debug
"""

import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import random
import struct
import sys
import time
import tkinter as tk

try:
    import win32api
    import win32con
    import win32gui
    import win32process
except ImportError:
    _msg = ("Desktop Gremlin needs pywin32.\n\n"
            "Install it with:   python -m pip install pywin32")
    print("\n  " + _msg + "\n")
    try:
        if sys.stdin is not None:
            input("  Press Enter to close...")
        else:
            # launched with pythonw: no console to read that in
            ctypes.windll.user32.MessageBoxW(0, _msg, "Desktop Gremlin", 0x10)
    except Exception:
        pass
    sys.exit(1)

if not sys.platform.startswith("win"):
    print("This one is Windows-only — it talks to the Windows shell directly.")
    sys.exit(1)

VERSION = "2.0"
DEBUG = "--debug" in sys.argv
HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "gremlin_settings.json")
BACKUP_PATH = os.path.join(HERE, "gremlin_icon_backup.json")
LOG_PATH = os.path.join(HERE, "gremlin_log.txt")


def start_log():
    """Launched with pythonw there is no console, so sys.stdout and sys.stderr
    are None and every diagnostic in this file goes nowhere -- including the
    tracebacks Tk catches for us. Send them to a file instead. Truncated each
    run, so it stays small and always describes the run that just failed."""
    if sys.stderr is not None:
        return None
    try:
        f = open(LOG_PATH, "w", encoding="utf-8", buffering=1)
    except Exception:
        return None
    sys.stdout = sys.stderr = f
    return f


# --------------------------------------------------------------------------
# DPI awareness — before any window exists, or every coordinate we read from
# the shell gets silently rescaled and nothing lines up.
# --------------------------------------------------------------------------
def make_dpi_aware():
    for fn in (lambda: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)),
               lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),
               lambda: ctypes.windll.user32.SetProcessDPIAware()):
        try:
            fn()
            return
        except Exception:
            continue


make_dpi_aware()

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

# Explicit prototypes. On 64-bit Windows the default restype (c_int) silently
# truncates returned pointers, which makes every cross-process read fail.
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                    wt.DWORD, wt.DWORD]
kernel32.VirtualFreeEx.restype = wt.BOOL
kernel32.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]

# A cross-process SendMessage blocks until Explorer answers it. If Explorer is
# busy — or hung — that stalls our whole frame loop with it, so every LVM_*
# call goes through a timeout instead.
SMTO_ABORTIFHUNG = 0x0002
user32.SendMessageTimeoutW.restype = wt.LPARAM
user32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM,
                                       wt.UINT, wt.UINT,
                                       ctypes.POINTER(ctypes.c_size_t)]


def send_msg(hwnd, msg, wparam, lparam, timeout=250):
    """SendMessage that cannot wedge the frame loop. None on failure/timeout."""
    res = ctypes.c_size_t(0)
    try:
        ok = user32.SendMessageTimeoutW(wt.HWND(hwnd), msg, wt.WPARAM(wparam),
                                        wt.LPARAM(lparam), SMTO_ABORTIFHUNG,
                                        timeout, ctypes.byref(res))
    except Exception:
        return None
    return int(res.value) if ok else None

# ==========================================================================
#  SETTINGS
# ==========================================================================
DEFAULTS = {
    "scale": 0.68,            # 0.68 ~= the height of a desktop icon
    "fps": 40,
    "chaos": 1.0,             # how fast they escalate
    "crowd": 2,               # how many of them, 1 to 10
    "move_icons": False,      # let them physically drag your desktop icons (opt-in)
    "react_to_windows": True, # comment on real window titles, follow focus
    "sleep_when_idle": True,
    "idle_minutes": 5.0,
    "all_monitors": True,
    "start_with_windows": False,
}


def load_settings():
    """Read the settings file if there is one, and never trust it."""
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            got = json.load(f)
        if isinstance(got, dict):
            for k, v in got.items():
                if k in s and isinstance(v, (bool, int, float)):
                    s[k] = v
    except Exception:
        pass
    try:
        s["scale"] = min(max(float(s["scale"]), 0.35), 2.5)
        s["fps"] = int(min(max(int(s["fps"]), 15), 60))
        s["chaos"] = min(max(float(s["chaos"]), 0.2), 3.0)
        s["idle_minutes"] = min(max(float(s["idle_minutes"]), 0.5), 120.0)
        s["crowd"] = int(min(max(int(s["crowd"]), 1), len(ROSTER)))
    except Exception:
        return dict(DEFAULTS)
    for k in ("move_icons", "react_to_windows", "sleep_when_idle",
              "all_monitors", "start_with_windows"):
        s[k] = bool(s[k])
    return s


def save_settings(s):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
        return True
    except Exception as exc:
        print("could not save settings:", exc)
        return False


CFG = load_settings()


# ==========================================================================
#  MEMORY  — what they remember about you between runs
# ==========================================================================
# Counters, never a log. Nothing about which applications you use is written
# to disk: the context they react to (below) lives in RAM and dies with the
# process. The only names stored are desktop icon labels, which
# gremlin_icon_backup.json already holds. Settings has a "Forget everything"
# button, and deleting the file does the same job.
# The cast, in the order they join. Declared up here rather than with the
# rest of the character data because the memory model below is keyed by it.
ROSTER = ("brawler", "sniper", "coward", "showoff", "grump",
          "magpie", "zealot", "tinkerer", "drama", "veteran")

MEMORY_PATH = os.path.join(HERE, "gremlin_memory.json")
MEM_KEYS = ("thrown", "grabbed", "wins", "losses", "icons_moved", "streak")
MEM_DIRTY = False


def blank_memory():
    # Counters live under "who" rather than as top-level names beside version /
    # runs / icons, so the set of characters can be enumerated without an
    # exclusion list.
    return {"version": 2, "runs": 0, "icons": {},
            "who": dict((n, dict.fromkeys(MEM_KEYS, 0)) for n in ROSTER)}


def load_memory():
    """Read it if it is there, and never trust a number in it."""
    m = blank_memory()
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            got = json.load(f)
    except Exception:
        return m
    if not isinstance(got, dict):
        return m
    if isinstance(got.get("runs"), int):
        m["runs"] = min(max(got["runs"], 0), 10 ** 6)
    who = got.get("who")
    if isinstance(who, dict):
        for kind in ROSTER:
            was = who.get(kind)
            if not isinstance(was, dict):
                continue
            for k in MEM_KEYS:
                v = was.get(k)
                if isinstance(v, int) and not isinstance(v, bool):
                    m["who"][kind][k] = min(max(v, -999), 10 ** 6)
    icons = got.get("icons")
    if isinstance(icons, dict):
        for name, n in list(icons.items())[:40]:
            if isinstance(name, str) and isinstance(n, int) and 0 < n < 10 ** 6:
                m["icons"][name[:40]] = n
    return m


MEM = load_memory()


def bump(kind, key, n=1):
    """Nudge a counter. The write itself is throttled by the frame loop."""
    global MEM_DIRTY
    MEM["who"][kind][key] = MEM["who"][kind].get(key, 0) + n
    MEM_DIRTY = True


def bump_icon(name):
    global MEM_DIRTY
    name = (name or "")[:40]
    if not name:
        return
    ic = MEM["icons"]
    ic[name] = ic.get(name, 0) + 1
    if len(ic) > 24:                     # keep the favourites, drop the one-offs
        for k in sorted(ic, key=ic.get)[:len(ic) - 16]:
            del ic[k]
    MEM_DIRTY = True


def favourite_icon():
    """The one they have picked on most. None on a fresh install."""
    ic = MEM["icons"]
    if not ic:
        return None
    best = max(ic, key=ic.get)
    return best if ic[best] >= 3 else None


def save_memory():
    global MEM_DIRTY
    if not MEM_DIRTY:
        return
    try:
        with open(MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(MEM, f, indent=1)
        MEM_DIRTY = False
    except Exception as exc:
        print("could not save memory:", exc)


def forget_memory():
    """Wipe what they know about you. Back to strangers."""
    global MEM, MEM_DIRTY
    MEM = blank_memory()
    MEM_DIRTY = True
    save_memory()


GREET_EVENTS = ("hello", "remember_runs", "remember_throws", "remember_fights")


def greeting_event(kind):
    """Only bring up a number that is actually worth bringing up."""
    m = MEM["who"][kind]
    if MEM["runs"] <= 1:
        return "hello"
    if m["thrown"] >= 5:
        return "remember_throws"
    if m["wins"] + m["losses"] >= 3:
        return "remember_fights"
    return "remember_runs"


# ==========================================================================
#  CONTEXT  — what you are actually doing, in RAM only
# ==========================================================================
CONTEXT_EVENTS = ("ctx_thrash", "ctx_focused", "ctx_marathon", "ctx_late",
                  "ctx_unsaved")


class Watcher:
    """Notices the shape of your session rather than its content. None of this
    is written anywhere; it is rebuilt from scratch every launch.

    Each remark has its own long cooldown on top of a global one, because the
    difference between a desktop pet you keep and one you uninstall is how
    often it decides to be clever at you."""

    def __init__(self):
        self.fg = None
        self.since = 0.0          # when the current window took focus
        self.switches = []        # recent focus-change times
        self.said = {}            # event -> when it last fired
        self.quiet_until = 45.0   # nothing at all for the first three quarters
        self.next_check = 0.0

    def note_focus(self, hwnd, now):
        if hwnd == self.fg:
            return
        self.fg = hwnd
        self.since = now
        self.switches.append(now)
        del self.switches[:-40]

    def pick(self, now, title, session):
        """The one thing worth remarking on right now, or None."""
        if now < self.quiet_until or now < self.next_check:
            return None
        self.next_check = now + 1.0       # this runs off the frame loop
        want = []
        if sum(1 for t in self.switches if now - t < 60) >= 12:
            want.append(("ctx_thrash", 300))
        if now - self.since > 900:
            want.append(("ctx_focused", 600))
        if session > 3 * 3600:
            want.append(("ctx_marathon", 1800))
        if 1 <= time.localtime().tm_hour < 5:
            want.append(("ctx_late", 1500))
        t = (title or "").strip()
        if t[:1] in ("*", "\u25cf", "\u2022") or "unsaved" in t.lower():
            want.append(("ctx_unsaved", 420))
        want = [(e, cd) for e, cd in want if now - self.said.get(e, -1e9) > cd]
        if not want:
            return None
        ev = random.choice(want)[0]
        self.said[ev] = now
        self.quiet_until = now + 120
        return ev

    def unsay(self, ev):
        """Hand a remark back because nobody was free to say it.

        pick() marks it said and goes quiet for two minutes the moment it hands
        one over, so a remark that never reached a speaker used to buy two
        minutes of silence for nothing. With a crowd all mid-swing at once that
        is most of them."""
        self.said.pop(ev, None)
        self.quiet_until = 0.0


def set_run_at_startup(on):
    """A Run-key entry, so it's trivially removable in Task Manager > Startup."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        name = "DesktopGremlin"
        if on:
            pyw = sys.executable.replace("python.exe", "pythonw.exe")
            cmd = f'"{pyw}" "{os.path.join(HERE, os.path.basename(__file__))}"'
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as exc:
        print("startup entry failed:", exc)
        return False


# ==========================================================================
#  WINDOWS SHELL
# ==========================================================================
LVM_FIRST = 0x1000
LVM_GETITEMCOUNT = LVM_FIRST + 4
LVM_GETITEMRECT = LVM_FIRST + 14
LVM_SETITEMPOSITION32 = LVM_FIRST + 49
LVM_GETITEMPOSITION = LVM_FIRST + 16
LVM_GETITEMTEXTW = LVM_FIRST + 115
LVM_REDRAWITEMS = LVM_FIRST + 21
LVIR_ICON = 1
LVS_AUTOARRANGE = 0x0100

PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04


class LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wt.UINT), ("iItem", ctypes.c_int), ("iSubItem", ctypes.c_int),
        ("state", wt.UINT), ("stateMask", wt.UINT), ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int),
        ("lParam", ctypes.c_void_p), ("iIndent", ctypes.c_int),
        ("iGroupId", ctypes.c_int), ("cColumns", wt.UINT),
        ("puColumns", ctypes.c_void_p), ("piColFmt", ctypes.c_void_p),
        ("iGroup", ctypes.c_int),
    ]


def find_desktop_listview():
    """Lives under Progman normally; slides into a WorkerW window whenever a
    live-wallpaper app (Lively, Wallpaper Engine) is running."""
    progman = win32gui.FindWindow("Progman", None)
    if progman:
        dv = win32gui.FindWindowEx(progman, 0, "SHELLDLL_DefView", None)
        if dv:
            lv = win32gui.FindWindowEx(dv, 0, "SysListView32", None)
            if lv:
                return lv
    found = []

    def cb(hwnd, _):
        dv = win32gui.FindWindowEx(hwnd, 0, "SHELLDLL_DefView", None)
        if dv:
            lv = win32gui.FindWindowEx(dv, 0, "SysListView32", None)
            if lv:
                found.append(lv)
        return True

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass
    return found[0] if found else None


def autoarrange_on(lv):
    """If Windows is auto-arranging, it snaps every icon back and the gremlins
    can never actually move anything."""
    try:
        style = win32gui.GetWindowLong(lv, win32con.GWL_STYLE)
        return bool(style & LVS_AUTOARRANGE)
    except Exception:
        return False


class ShellView:
    """A borrowed handle on Explorer's desktop ListView, plus a scratch buffer
    inside Explorer's own address space (LVM_* messages take pointers, and a
    pointer only means something in the owning process)."""

    def __init__(self):
        self.lv = None
        self.proc = None
        self.remote = None
        self._names = {}        # index -> label; reading one is the slow call
        self._names_n = -1

    def open(self):
        lv = find_desktop_listview()
        if not lv:
            return False
        if lv == self.lv and self.remote:
            return True
        self.close()
        self.lv = lv
        try:
            _, pid = win32process.GetWindowThreadProcessId(lv)
        except Exception:
            return False
        self.proc = kernel32.OpenProcess(
            PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE |
            PROCESS_QUERY_INFORMATION, False, pid)
        if not self.proc:
            return False
        self.remote = kernel32.VirtualAllocEx(self.proc, None, 4096,
                                              MEM_COMMIT, PAGE_READWRITE)
        if not self.remote:
            kernel32.CloseHandle(self.proc)
            self.proc = None
            return False
        return True

    def close(self):
        try:
            if self.remote and self.proc:
                kernel32.VirtualFreeEx(self.proc, self.remote, 0, MEM_RELEASE)
            if self.proc:
                kernel32.CloseHandle(self.proc)
        except Exception:
            pass
        self.proc = self.remote = None
        self._names.clear()
        self._names_n = -1

    # -- low level ---------------------------------------------------------
    def _write(self, obj, off=0):
        n = ctypes.c_size_t(0)
        return kernel32.WriteProcessMemory(self.proc, self.remote + off,
                                           ctypes.byref(obj), ctypes.sizeof(obj),
                                           ctypes.byref(n))

    def _read(self, obj, off=0):
        n = ctypes.c_size_t(0)
        return kernel32.ReadProcessMemory(self.proc, self.remote + off,
                                          ctypes.byref(obj), ctypes.sizeof(obj),
                                          ctypes.byref(n))

    def count(self):
        return send_msg(self.lv, LVM_GETITEMCOUNT, 0, 0) or 0

    def item_rect(self, i):
        """Icon glyph rect in SCREEN pixels."""
        r = wt.RECT(LVIR_ICON, 0, 0, 0)
        self._write(r)
        if send_msg(self.lv, LVM_GETITEMRECT, i, self.remote) is None:
            return None
        self._read(r)
        if r.right <= r.left or r.bottom <= r.top:
            return None
        try:
            l, t = win32gui.ClientToScreen(self.lv, (r.left, r.top))
            rr, b = win32gui.ClientToScreen(self.lv, (r.right, r.bottom))
        except Exception:
            return None
        return (l, t, rr, b)

    def item_pos(self, i):
        """Position in LIST coordinates — what SETITEMPOSITION32 expects."""
        p = wt.POINT(0, 0)
        self._write(p)
        send_msg(self.lv, LVM_GETITEMPOSITION, i, self.remote)
        self._read(p)
        return (p.x, p.y)

    def set_item_pos(self, i, x, y):
        p = wt.POINT(int(x), int(y))
        self._write(p)
        return send_msg(self.lv, LVM_SETITEMPOSITION32, i, self.remote) is not None

    def item_text(self, i):
        try:
            off = ctypes.sizeof(LVITEMW) + 16
            it = LVITEMW()
            ctypes.memset(ctypes.byref(it), 0, ctypes.sizeof(it))
            it.iItem = i
            it.iSubItem = 0
            it.pszText = self.remote + off
            it.cchTextMax = 260
            self._write(it)
            if send_msg(self.lv, LVM_GETITEMTEXTW, i, self.remote) is None:
                return ""
            buf = ctypes.create_unicode_buffer(260)
            n = ctypes.c_size_t(0)
            kernel32.ReadProcessMemory(self.proc, self.remote + off, buf, 520,
                                       ctypes.byref(n))
            return buf.value
        except Exception:
            return ""

    # -- the useful bits ---------------------------------------------------
    def read_icons(self):
        """[(name, l, t, r, b, index), ...] in screen pixels.

        Labels are cached. Fetching one is a whole second cross-process round
        trip per icon and they only ever feed the jokes, so the cache is kept
        until the item count changes — a rename shows up on the next add or
        delete."""
        if not self.open():
            return []
        n = min(self.count(), 400)
        if n != self._names_n:
            self._names.clear()
            self._names_n = n
        names = self._names
        out = []
        for i in range(n):
            rect = self.item_rect(i)
            if not rect:
                continue
            nm = names.get(i)
            if nm is None:
                nm = self.item_text(i) or "icon"
                names[i] = nm
            out.append((nm,) + rect + (i,))
        return out

    def snapshot(self):
        """[(name, list_x, list_y), ...] — the layout, for saving."""
        if not self.open():
            return []
        out = []
        for i in range(min(self.count(), 400)):
            x, y = self.item_pos(i)
            out.append([self.item_text(i) or "", x, y])
        return out

    def restore(self, snap):
        if not self.open() or not snap:
            return 0
        by_name = {}
        for name, x, y in snap:
            by_name.setdefault(name, []).append((x, y))
        done = 0
        for i in range(min(self.count(), 400)):
            nm = self.item_text(i) or ""
            if nm in by_name and by_name[nm]:
                x, y = by_name[nm].pop(0)
                if self.set_item_pos(i, x, y):
                    done += 1
        try:
            send_msg(self.lv, LVM_REDRAWITEMS, 0, max(0, self.count() - 1))
            win32gui.InvalidateRect(self.lv, None, True)
        except Exception:
            pass
        return done


SHELL = ShellView()

# No backup on disk means no undo, so nothing may be dragged. Set by
# backup_layout(); read by App.can_move_icons() and the settings window.
BACKUP_OK = False


def backup_layout():
    """Write the icon layout once, the first time we ever run."""
    global BACKUP_OK
    if os.path.exists(BACKUP_PATH):
        BACKUP_OK = True
        return "existing"
    snap = SHELL.snapshot()
    if not snap:
        return "failed"
    try:
        with open(BACKUP_PATH, "w", encoding="utf-8") as f:
            json.dump({"saved": time.strftime("%Y-%m-%d %H:%M:%S"), "icons": snap},
                      f, indent=1)
        BACKUP_OK = True
        return "saved"
    except Exception as exc:
        print("layout backup failed:", exc)
        return "failed"


def restore_layout():
    try:
        with open(BACKUP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return 0
    return SHELL.restore(data.get("icons", []))


# ---- windows --------------------------------------------------------------
def frame_bounds(hwnd):
    """The *visible* rect. GetWindowRect includes an invisible resize border on
    Win10/11, so a gremlin standing on it floats a few pixels off the title bar."""
    r = wt.RECT()
    try:
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wt.HWND(hwnd), ctypes.c_uint(9), ctypes.byref(r),
                ctypes.sizeof(r)) == 0 and r.right > r.left:
            return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return win32gui.GetWindowRect(hwnd)


def is_cloaked(hwnd):
    v = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), ctypes.c_uint(14),
                                                   ctypes.byref(v), 4)
    except Exception:
        return False
    return bool(v.value)


SKIP_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "Windows.UI.Core.CoreWindow", "TkTopLevel", "tooltips_class32",
}


def read_windows(own_hwnd):
    """[(title, l, t, r, b, hwnd), ...] for real, visible top-level windows."""
    out = []

    def cb(hwnd, _):
        if hwnd == own_hwnd or not win32gui.IsWindowVisible(hwnd):
            return True
        if win32gui.GetParent(hwnd):
            return True
        try:
            if win32gui.GetClassName(hwnd) in SKIP_CLASSES:
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return True
            if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
                return True
            if win32gui.IsIconic(hwnd) or is_cloaked(hwnd):
                return True
            l, t, r, b = frame_bounds(hwnd)
        except Exception:
            return True
        if r - l < 160 or b - t < 110:
            return True
        out.append((title, l, t, r, b, hwnd))
        return True

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass
    return out


def foreground_window():
    try:
        h = win32gui.GetForegroundWindow()
        if not h:
            return None
        return (win32gui.GetWindowText(h), h)
    except Exception:
        return None


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]


def idle_seconds():
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(lii)
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        now = kernel32.GetTickCount() & 0xFFFFFFFF
        return max(0.0, ((now - lii.dwTime) & 0xFFFFFFFF) / 1000.0)
    except Exception:
        return 0.0


# ---- monitors -------------------------------------------------------------
def monitors():
    """[(mon_rect, work_rect), ...] — work_rect excludes the taskbar."""
    out = []
    try:
        for h, _hdc, _r in win32api.EnumDisplayMonitors():
            info = win32api.GetMonitorInfo(h)
            out.append((tuple(info["Monitor"]), tuple(info["Work"])))
    except Exception:
        pass
    if not out:
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        out = [((0, 0, w, h), (0, 0, w, h - 48))]
    return out


def virtual_screen():
    x = user32.GetSystemMetrics(76)
    y = user32.GetSystemMetrics(77)
    w = user32.GetSystemMetrics(78)
    h = user32.GetSystemMetrics(79)
    if w <= 0 or h <= 0:
        return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    return (x, y, w, h)

# ==========================================================================
#  SYSTEM TRAY  (raw Shell_NotifyIcon — no extra dependencies)
# ==========================================================================
def _write_ico(path):
    """Build a 16x16 32bpp .ico of a little stick figure, by hand."""
    W = H = 16
    px = [[(0, 0, 0, 0)] * W for _ in range(H)]
    ink = (255, 211, 92)          # the 'hyped' yellow, BGRA-ordered later
    dim = (180, 150, 70)

    def dot(x, y, c=ink):
        if 0 <= x < W and 0 <= y < H:
            px[y][x] = c

    def line(x0, y0, x1, y1, c=ink):
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(n + 1):
            dot(round(x0 + (x1 - x0) * i / n), round(y0 + (y1 - y0) * i / n), c)

    for a in range(0, 360, 18):          # head
        r = 2.6
        dot(round(8 + math.cos(math.radians(a)) * r),
            round(3.4 + math.sin(math.radians(a)) * r))
    dot(8, 3); dot(7, 3); dot(8, 4); dot(7, 4); dot(8, 2); dot(7, 2)
    line(8, 6, 8, 10)                    # spine
    line(8, 7, 4, 6, dim)                # arms
    line(8, 7, 12, 5)
    line(8, 10, 5, 14)                   # legs
    line(8, 10, 12, 14)

    rows = b""
    for y in range(H - 1, -1, -1):       # bottom-up
        for x in range(W):
            c = px[y][x]
            if len(c) == 3:
                r, g, b, a = c[0], c[1], c[2], 255
            else:
                r, g, b, a = c
            rows += struct.pack("<BBBB", b, g, r, a)
    andmask = b"\x00" * (4 * H)

    bih = struct.pack("<IiiHHIIiiII", 40, W, H * 2, 1, 32, 0, len(rows) + len(andmask),
                      0, 0, 0, 0)
    img = bih + rows + andmask
    ico = struct.pack("<HHH", 0, 1, 1)
    ico += struct.pack("<BBBBHHII", W, H, 0, 0, 1, 32, len(img), 22)
    ico += img
    with open(path, "wb") as f:
        f.write(ico)
    return path


class Tray:
    WM_TRAY = win32con.WM_USER + 20
    ID_BASE = 1500

    def __init__(self, tip="Desktop Gremlin"):
        self.items = []              # (label, callback, kind) kind: cmd|check|sep
        self.pending = []            # menu actions waiting for the Tk loop
        self.hwnd = 0
        self.hicon = 0
        self.added = False
        self.tip = tip

    def build(self):
        msgs = {
            win32con.WM_COMMAND: self._on_command,
            self.WM_TRAY: self._on_tray,
            win32con.WM_DESTROY: self._on_destroy,
        }
        wc = win32gui.WNDCLASS()
        wc.lpszClassName = "GremlinTrayWnd"
        wc.lpfnWndProc = msgs
        try:
            cls = win32gui.RegisterClass(wc)
        except Exception:
            cls = "GremlinTrayWnd"
        self.hwnd = win32gui.CreateWindow(cls, "Desktop Gremlin", 0,
                                          0, 0, 0, 0, 0, 0, 0, None)
        win32gui.UpdateWindow(self.hwnd)

        try:
            ico = _write_ico(os.path.join(HERE, "gremlin.ico"))
            self.hicon = win32gui.LoadImage(0, ico, win32con.IMAGE_ICON, 16, 16,
                                            win32con.LR_LOADFROMFILE)
        except Exception:
            self.hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        try:
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_ADD,
                (self.hwnd, 0, flags, self.WM_TRAY, self.hicon, self.tip))
            self.added = True
        except Exception as exc:
            print("tray icon unavailable:", exc)
        return self.added

    def notify(self, title, text):
        if not self.added:
            return
        try:
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_MODIFY,
                (self.hwnd, 0, win32gui.NIF_INFO, self.WM_TRAY, self.hicon,
                 self.tip, text, 200, title))
        except Exception:
            pass

    # -- menu -------------------------------------------------------------
    def _on_tray(self, hwnd, msg, wparam, lparam):
        if lparam in (win32con.WM_RBUTTONUP, win32con.WM_LBUTTONUP):
            self._popup()
        return True

    def _popup(self):
        menu = win32gui.CreatePopupMenu()
        for i, (label, _cb, kind, checked) in enumerate(self.items):
            if kind == "sep":
                win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            else:
                flags = win32con.MF_STRING
                if kind == "check" and checked():
                    flags |= win32con.MF_CHECKED
                win32gui.AppendMenu(menu, flags, self.ID_BASE + i, label)
        pos = win32gui.GetCursorPos()
        try:
            win32gui.SetForegroundWindow(self.hwnd)
        except Exception:
            pass
        win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON,
                                pos[0], pos[1], 0, self.hwnd, None)
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)
        win32gui.DestroyMenu(menu)

    def _on_command(self, hwnd, msg, wparam, lparam):
        idx = win32api.LOWORD(wparam) - self.ID_BASE
        if 0 <= idx < len(self.items):
            cb = self.items[idx][1]
            if cb:
                # Queue it, never run it here. We are inside TrackPopupMenu's
                # own modal message loop, which is inside PumpWaitingMessages,
                # which is inside the Tk frame callback. Building or destroying
                # a widget from there re-enters the interpreter three deep.
                self.pending.append(cb)
        return True

    def drain(self):
        """Run queued menu actions on the Tk event loop, where they are safe."""
        while self.pending:
            cb = self.pending.pop(0)
            try:
                cb()
            except Exception:
                import traceback
                print("menu action failed:")
                traceback.print_exc()

    def _on_destroy(self, hwnd, msg, wparam, lparam):
        self.remove()
        return True

    def add(self, label, cb, kind="cmd", checked=None):
        self.items.append((label, cb, kind, checked or (lambda: False)))

    def sep(self):
        self.items.append(("", None, "sep", lambda: False))

    def pump(self):
        try:
            win32gui.PumpWaitingMessages()
        except Exception:
            pass

    def remove(self):
        if self.added:
            try:
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))
            except Exception:
                pass
            self.added = False


# ==========================================================================
#  SETTINGS WINDOW
# ==========================================================================
class SettingsWindow:
    def __init__(self, master, app):
        self.app = app
        self.win = tk.Toplevel(master)
        self.win.title("Desktop Gremlin — settings")
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        self.win.configure(bg="#171B2C")
        self.vars = {}

        pad = {"padx": 14, "pady": 4}
        row = 0

        def header(txt):
            nonlocal row
            tk.Label(self.win, text=txt, bg="#171B2C", fg="#8FA0CC",
                     font=("Segoe UI", 9, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 2))
            row += 1

        def slider(key, label, lo, hi, res):
            nonlocal row
            v = tk.DoubleVar(value=float(CFG[key]))
            self.vars[key] = v
            tk.Label(self.win, text=label, bg="#171B2C", fg="#E6ECFF",
                     font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", **pad)
            tk.Scale(self.win, from_=lo, to=hi, resolution=res, orient="horizontal",
                     variable=v, bg="#171B2C", fg="#E6ECFF", troughcolor="#0E1120",
                     highlightthickness=0, length=190, bd=0).grid(
                row=row, column=1, sticky="e", **pad)
            row += 1

        def check(key, label):
            nonlocal row
            v = tk.BooleanVar(value=bool(CFG[key]))
            self.vars[key] = v
            cb = tk.Checkbutton(self.win, text=label, variable=v, bg="#171B2C",
                                fg="#E6ECFF", selectcolor="#0E1120",
                                activebackground="#171B2C",
                                activeforeground="#FFFFFF", font=("Segoe UI", 9),
                                highlightthickness=0, bd=0)
            cb.grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=2)
            row += 1
            return cb

        header("Look")
        slider("scale", "Size  (0.68 = icon height)", 0.35, 2.5, 0.01)
        slider("fps", "Frames per second", 15, 60, 1)

        header("Behaviour")
        slider("chaos", "Chaos level", 0.2, 3.0, 0.1)
        slider("crowd", "How many of them", 1, 10, 1)
        check("react_to_windows", "React to my windows and follow focus")
        check("sleep_when_idle", "Sleep when I'm away")
        slider("idle_minutes", "Minutes before sleeping", 0.5, 60, 0.5)

        header("Your desktop")
        drag = check("move_icons", "Let them actually drag my desktop icons")
        if not BACKUP_OK:
            # Nothing to put the icons back with, so the switch stays off.
            self.vars["move_icons"].set(False)
            drag.config(state="disabled", disabledforeground="#6C7BB0",
                        text="Drag my desktop icons  (no layout backup — off)")
        check("all_monitors", "Use all monitors  (restart to apply)")
        check("start_with_windows", "Start with Windows")

        tk.Button(self.win, text="Restore my icon layout", command=self.restore,
                  bg="#2A3150", fg="#FFD35C", activebackground="#39426B",
                  relief="flat", font=("Segoe UI", 9), bd=0).grid(
            row=row, column=0, columnspan=2, sticky="we", padx=14, pady=(14, 4))
        row += 1
        tk.Button(self.win, text="Make them forget everything about me",
                  command=self.forget, bg="#2A3150", fg="#C9D3F0",
                  activebackground="#39426B", relief="flat",
                  font=("Segoe UI", 9), bd=0).grid(
            row=row, column=0, columnspan=2, sticky="we", padx=14, pady=(0, 4))
        row += 1

        bar = tk.Frame(self.win, bg="#171B2C")
        bar.grid(row=row, column=0, columnspan=2, sticky="we", padx=10, pady=12)
        tk.Button(bar, text="Apply", command=self.apply, bg="#3A7D5C", fg="#FFFFFF",
                  activebackground="#4A9A72", relief="flat", width=12,
                  font=("Segoe UI", 9, "bold"), bd=0).pack(side="right", padx=4)
        tk.Button(bar, text="Close", command=self.close, bg="#2A3150", fg="#C9D3F0",
                  activebackground="#39426B", relief="flat", width=10,
                  font=("Segoe UI", 9), bd=0).pack(side="right", padx=4)

        self.status = tk.Label(self.win, text="", bg="#171B2C", fg="#63E0A8",
                               font=("Segoe UI", 8))
        self.status.grid(row=row + 1, column=0, columnspan=2, pady=(0, 10))
        self.win.protocol("WM_DELETE_WINDOW", self.close)

    def restore(self):
        n = restore_layout()
        self.status.config(
            text=f"Put {n} icon(s) back." if n else "No saved layout found.",
            fg="#63E0A8" if n else "#FF5B47")

    def forget(self):
        forget_memory()
        self.status.config(text="Forgotten. You're strangers again.", fg="#63E0A8")

    def apply(self):
        for k, v in self.vars.items():
            val = v.get()
            CFG[k] = bool(val) if isinstance(DEFAULTS[k], bool) else (
                int(val) if isinstance(DEFAULTS[k], int) and not isinstance(DEFAULTS[k], bool)
                else float(val))
        save_settings(CFG)
        set_run_at_startup(CFG["start_with_windows"])
        self.app.apply_settings()
        self.status.config(text="Applied.", fg="#63E0A8")

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass
        self.app.settings_win = None

# ==========================================================================
#  math
# ==========================================================================
TAU = math.pi * 2
# How far past the side of the screen he gets before coming back on the other
# one. Wide enough that he is fully hidden first, so it reads as walking round
# the back of the screen rather than teleporting mid-stride.
WRAP = 140
# ...or this long out of sight, whichever comes first. Distance alone is not
# enough: a duel can settle a few pixels past the edge, never travel the WRAP
# needed to trigger, and carry on where you cannot see it. Measured before this
# existed: one of them spent 6.1 seconds off screen in a three minute run.
OUT_MAX = 1.2
# Headroom above the screen, so a big hit can throw him out of sight and he
# falls back in. There used to be a hard ceiling 18px down, which put the top
# row of desktop icons ABOVE it: they could never stand there, and grabbing
# that lip trapped them in a grab-jump-bounce-fall loop.
CEILING = 300


def clamp(v, a, b):
    return a if v < a else (b if v > b else v)


def lerp(a, b, t):
    return a + (b - a) * t


def approach(a, b, d):
    return b if abs(b - a) <= d else a + math.copysign(d, b - a)


def dist(ax, ay, bx, by):
    return math.hypot(bx - ax, by - ay)


def rot(x, y, a):
    c, s = math.cos(a), math.sin(a)
    return x * c - y * s, x * s + y * c


def lob_angle(dx, dy, v, g):
    """Launch angle that drops a projectile onto (dx, dy), in screen
    coordinates where +y is down. None if it simply cannot get there.

    An arrow fired flat at something 280px away lands about 100px in front of
    it: the speeds scale with how big he is, the reaches do not, and gravity
    wins. Archers lob."""
    if g <= 0:
        return math.atan2(dy, dx)
    d = abs(dx)
    if d < 1e-6:
        return math.pi / 2 if dy > 0 else -math.pi / 2
    disc = v ** 4 - g * (g * d * d - 2 * dy * v * v)
    if disc < 0:
        return None
    # the flatter of the two arcs -- the other is a mortar shot
    theta = math.atan2(v * v - math.sqrt(disc), g * d)
    return math.atan2(-v * math.sin(theta),
                      v * math.cos(theta) * (1 if dx >= 0 else -1))


def ik(ax, ay, bx, by, l1, l2, bend):
    d = math.hypot(bx - ax, by - ay) or 0.001
    d = clamp(d, abs(l1 - l2) + 0.01, l1 + l2 - 0.01)
    base = math.atan2(by - ay, bx - ax)
    a = math.acos(clamp((l1 * l1 + d * d - l2 * l2) / (2 * l1 * d), -1, 1))
    ang = base + bend * a
    return ax + math.cos(ang) * l1, ay + math.sin(ang) * l1


# ==========================================================================
#  palette
# ==========================================================================
KEY = "#010101"           # this exact color is invisible AND click-through
# Mood colours are per character now and derived from each one's base colour:
# see MOODS, BASECOL and PALETTES with the rest of the cast further down.
INK = "#0B0F22"
ROPE = "#E9D9A9"
LASER = "#7FE7FF"
FIRE = "#FFB259"
STEEL = "#E6ECFF"
GUNMETAL = "#C9D3F0"
BOMBC = "#20263F"
DUST = "#B9C4E0"
BOLT = "#BFE6FF"

# ==========================================================================
#  terrain
# ==========================================================================
class Terrain:
    def __init__(self):
        self.icons = []       # (name, l, t, r, b, index)
        self.windows = []     # (title, l, t, r, b, hwnd)
        self.platforms = []   # (x0, x1, y, kind, key)
        self._targets = []
        self.bounds = []      # (cx, cy, half_w, half_h, target) for hit tests
        self.win_pos = {}     # hwnd -> (l, t) last seen, for riding
        self.moved = {}       # hwnd -> (dx, dy) since last refresh
        self.last = 0.0
        self.icons_ok = False

    def refresh(self, own_hwnd, want_icons=True):
        prev = dict(self.win_pos)
        if want_icons:
            try:
                self.icons = SHELL.read_icons()
                self.icons_ok = bool(self.icons)
            except Exception:
                self.icons = []
        try:
            self.windows = read_windows(own_hwnd)
        except Exception:
            self.windows = []

        self.win_pos = {}
        self.moved = {}
        for title, l, t, r, b, hwnd in self.windows:
            self.win_pos[hwnd] = (l, t)
            if hwnd in prev:
                dx, dy = l - prev[hwnd][0], t - prev[hwnd][1]
                if dx or dy:
                    self.moved[hwnd] = (dx, dy)

        tg, pl = [], []
        for name, l, t, r, b, idx in self.icons:
            tg.append({"cx": (l + r) / 2, "cy": (t + b) / 2, "top": t, "name": name,
                       "w": r - l, "h": b - t, "kind": "icon", "key": idx})
            pl.append((l, r, t, "icon", idx))
        for title, l, t, r, b, hwnd in self.windows:
            tg.append({"cx": (l + r) / 2, "cy": t + 16, "top": t, "name": title,
                       "w": r - l, "h": 32, "kind": "window", "key": hwnd})
            pl.append((l + 6, r - 6, t, "window", hwnd))
        self._targets = tg
        self.platforms = pl
        # Flat tuples: the projectile loop walks these on every single frame,
        # and a tuple unpack beats four dict lookups per test.
        self.bounds = [(t["cx"], t["cy"], t["w"] / 2, max(t["h"], 26) / 2, t)
                       for t in tg]

    def targets(self):
        return self._targets


# ==========================================================================
#  what he says about your actual stuff
# ==========================================================================
TITLE_LINES = [
    (("youtube", "netflix", "twitch", "hulu", "prime video"),
     ["working hard I see", "shouldn't you be busy", "put subtitles on",
      "this is what you do all day", "four hours. FOUR."]),
    (("chrome", "firefox", "edge", "opera", "brave"),
     ["how many tabs", "close some tabs", "your RAM is crying",
      "forty tabs. FORTY.", "one of those is playing audio"]),
    (("visual studio", "vscode", "code", "pycharm", "sublime", "notepad++"),
     ["that's a bug", "line 40 is wrong", "just ship it", "add a comment",
      "you'll regret that variable name", "it compiles. barely."]),
    (("explorer", "file", "this pc", "downloads"),
     ["what a mess", "organize this", "so many files",
      "this folder is a crime scene", "final_v3_FINAL_actual, is it"]),
    (("discord", "slack", "teams", "whatsapp"),
     ["ignore them", "reply later", "brb", "they can wait", "leave them on read"]),
    (("spotify", "music", "vlc", "media player"),
     ["turn it up", "skip this one", "banger", "absolute banger", "again? again."]),
    (("steam", "epic games", "game"),
     ["let's play", "one more round", "you'll lose", "you'll lose again",
      "buy it, don't play it, classic"]),
    (("excel", "sheet", "word", "outlook", "pdf"),
     ["riveting", "*yawn*", "get a hobby", "thrilling stuff", "a spreadsheet. wow."]),
    (("task manager",), ["don't you dare", "I'm not the problem", "look away",
                         "nothing to see", "that's not for you"]),
    (("settings", "control panel"), ["breaking something?", "careful",
                                     "don't touch that", "you'll regret this"]),
]
ICON_LINES = {
    "recycle bin": ["garbage day", "into the bin", "I live here now", "my house"],
    "this pc": ["all mine", "nice PC", "mine now", "I'll be having that"],
    "network": ["is it plugged in", "no signal", "have you tried turning it off"],
}


def line_for_title(f, title):
    t = (title or "").lower()
    for keys, lines in TITLE_LINES:
        for k in keys:
            if k in t:
                return random.choice(lines)
    first = (title or "").split(" ")[0][:16]
    if first and random.random() < .5:
        return random.choice([f"{first}, huh", f"what is {first}", "seen worse"])
    return f.line("generic")


def line_for_icon(f, name):
    n = (name or "").lower()
    for k, lines in ICON_LINES.items():
        if k in n:
            return random.choice(lines)
    return f.line("generic")


# ==========================================================================
#  the fighters
# ==========================================================================
WEAPONS = ["sword", "bow", "blaster", "bomb", "rocket", "minigun", "chainsaw", "lightning"]
ATKDUR = {"sword": .42, "bow": .85, "blaster": .75, "bomb": .60,
          "rocket": .90, "minigun": 1.40, "chainsaw": 1.20, "lightning": .80}
# How far off he opens fire. A round has to comfortably outrun the number here
# or it dies in the air, and the minigun needs the widest margin of the lot
# because it streams for 1.4s while both of them keep moving. Measured before
# this changed: pellets flew 357px against a 241px firing distance, a margin of
# 1.48 where the blaster had 1.84.
REACH = {"sword": 40, "bow": 480, "blaster": 420, "bomb": 230,
         "rocket": 520, "minigun": 430, "chainsaw": 34, "lightning": 560}
MELEE = ("sword", "chainsaw")

MOODS = ("bored", "hyped", "furious", "smug", "sulking", "asleep")

# One base colour each, well apart around the wheel and all bright enough to
# read against a dark wallpaper.
BASECOL = {
    "brawler": "#FFC24A", "sniper": "#6FD8FF", "coward": "#A8E86A",
    "showoff": "#FF8AD8", "grump": "#C79A6B", "magpie": "#B79BFF",
    "zealot": "#FF6B4A", "tinkerer": "#57D9B0", "drama": "#FF5C8A",
    "veteran": "#9FB2CE",
}

# Sixty hand-picked hex values would be sixty chances to get one wrong, so the
# six moods are derived: pull the base towards a mood tint, then brighten or
# dim. Mood stays readable across the cast, character stays readable across the
# moods.
MOOD_SHIFT = {
    "bored":   ((150, 165, 200), .45, 1.00),
    "hyped":   ((255, 252, 210), .32, 1.12),
    "furious": ((255,  70,  55), .50, 1.00),
    "smug":    (( 90, 230, 165), .42, 1.00),
    "sulking": ((110, 120, 190), .50, 0.86),
    "asleep":  ((105, 120, 175), .55, 0.72),
}


def palette(base):
    """The six mood colours for one character, from its base colour."""
    r, g, b = (int(base[1:3], 16), int(base[3:5], 16), int(base[5:7], 16))
    out = {}
    for mood, (tint, amt, bright) in MOOD_SHIFT.items():
        c = [r + (tint[0] - r) * amt,
             g + (tint[1] - g) * amt,
             b + (tint[2] - b) * amt]
        out[mood] = "#%02X%02X%02X" % tuple(
            min(255, max(0, int(round(v * bright)))) for v in c)
    return out


PALETTES = dict((n, palette(c)) for n, c in BASECOL.items())

# Temperament. Every axis is wired to arithmetic that already existed except
# nerve, which is the health he breaks off a fight at -- that one is what makes
# the coward read as a coward.
TRAITS = {
    "brawler":  {"aggro": 1.60, "chatty": 1.15, "grudge": 1.35, "dash": 1.20,
                 "hops": 1.10, "thief": .25, "nerve": .05,
                 "weapons": ("chainsaw", "sword", "rocket", "bomb", "minigun")},
    "sniper":   {"aggro": 0.70, "chatty": 0.60, "grudge": 0.75, "dash": 0.85,
                 "hops": 0.60, "thief": .30, "nerve": .35,
                 "weapons": ("blaster", "lightning", "bow", "minigun", "rocket")},
    "coward":   {"aggro": 0.35, "chatty": 1.40, "grudge": 0.60, "dash": 1.30,
                 "hops": 1.40, "thief": .55, "nerve": .70,
                 "weapons": ("bow", "blaster", "bomb", "minigun", "sword")},
    "showoff":  {"aggro": 1.20, "chatty": 1.60, "grudge": 0.90, "dash": 1.05,
                 "hops": 1.35, "thief": .40, "nerve": .20,
                 "weapons": ("rocket", "lightning", "minigun", "sword", "blaster")},
    "grump":    {"aggro": 0.85, "chatty": 0.45, "grudge": 1.30, "dash": 0.70,
                 "hops": 0.45, "thief": .35, "nerve": .15,
                 "weapons": ("sword", "chainsaw", "bomb", "rocket", "blaster")},
    "magpie":   {"aggro": 0.30, "chatty": 1.10, "grudge": 0.55, "dash": 1.25,
                 "hops": 1.30, "thief": .95, "nerve": .50,
                 "weapons": ("bomb", "blaster", "bow", "sword", "minigun")},
    "zealot":   {"aggro": 1.75, "chatty": 1.25, "grudge": 1.60, "dash": 1.15,
                 "hops": 0.90, "thief": .20, "nerve": .00,
                 "weapons": ("chainsaw", "rocket", "lightning", "sword", "bomb")},
    "tinkerer": {"aggro": 0.80, "chatty": 0.75, "grudge": 0.85, "dash": 0.80,
                 "hops": 0.70, "thief": .60, "nerve": .30,
                 "weapons": ("bomb", "rocket", "minigun", "blaster", "bow")},
    "drama":    {"aggro": 0.95, "chatty": 1.75, "grudge": 1.45, "dash": 1.00,
                 "hops": 1.20, "thief": .45, "nerve": .55,
                 "weapons": ("lightning", "sword", "bow", "blaster", "bomb")},
    "veteran":  {"aggro": 1.05, "chatty": 0.35, "grudge": 0.70, "dash": 0.95,
                 "hops": 0.75, "thief": .30, "nerve": .25,
                 "weapons": ("sword", "blaster", "bow", "minigun", "chainsaw")},
}

# Every line any of them can say. {name} is an icon he has just made off with;
# {runs} {throws} {wins} {losses} are his own counters, always all supplied.
VOICES = {
    "brawler": {
        "bored":    ["...", "nothing to hit", "hm", "quiet. too quiet."],
        "hyped":    ["LET'S GO", "YES", "NOW we're talking", "GET IN"],
        "furious":  ["#@$%!", "RAAAGH", "YOU ABSOLUTE TURNIP", "I'LL END YOU"],
        "smug":     ["too easy", "nailed it", "heh", "obviously"],
        "sulking":  ["whatever", "fine.", "rude", "I'm not sulking"],
        "asleep":   ["z z z", "...zzz", "mnf"],
        "grabbed":  ["OI! HANDS", "put me DOWN", "I'll bite", "GET OFF"],
        "thrown":   ["AAAAAH", "YOU GREAT MELON", "I'll REMEMBER this"],
        "ko":       ["...", "urk", "worth it", "tell them I swung first"],
        "victory":  ["GET UP", "who's next", "and STAY down", "next contestant"],
        "hurt":     ["OW", "#@$%", "cheap shot", "that's IT"],
        "fight":    ["COME HERE", "you're MINE", "hold still", "ROUND TWO"],
        "cursor":   ["oh, YOU again", "come here", "hold still", "you and me"],
        "hook":     ["whee", "yoink", "GERONIMOOO", "out of the way"],
        "snatch":   ["mine now", "bye, {name}", "{name} lives here now"],
        "boredom":  ["I'm BORED", "nothing to DO?!", "SOMEONE FIGHT ME"],
        "rage":     ["that icon LOOKED at me", "who moved my stuff", "RAAAGH"],
        "getup":    ["ROUND TWO", "lucky hit", "doesn't count", "warm-up"],
        "wake":     ["...what", "I'm up", "WHAT. WHAT.", "who's there"],
        "summoned": ["coming", "WHAT", "this better be good"],
        "generic":  ["mine now", "what's this then", "I'll allow it", "bin it"],
        "hello":    ["right. who's in charge here", "new desktop. MINE.",
                     "let's see what you've got"],
        "remember_runs":   ["day {runs} of this", "run {runs}. still here.",
                            "back again. {runs} times now."],
        "remember_throws": ["you've thrown me {throws} times",
                            "{throws} throws. I'm counting."],
        "remember_fights": ["{wins} and {losses}. I'm rounding up.",
                            "{wins} wins. verified."],
        "fav_icon": ["you AGAIN", "we meet again, {name}", "{name}. every time."],
        "revenge":  ["not this time", "I've been practising", "THIS one's mine"],
        "gangup":   ["get it get it get it", "both of us. now.", "TEAM UP"],
        "ctx_thrash":   ["pick ONE", "make your MIND up", "nine windows a minute"],
        "ctx_focused":  ["still on this?", "blink. please blink.", "you've not moved"],
        "ctx_marathon": ["go OUTSIDE", "stand up. STAND UP.", "hours of this"],
        "ctx_late":     ["it's the middle of the night", "go to BED"],
        "ctx_unsaved":  ["SAVE IT", "ctrl-s. CTRL-S.", "you've not saved"],
    },
    "sniper": {
        "bored":    ["...", "no targets", "holding", "nothing in range"],
        "hyped":    ["target rich", "in range", "acquired", "finally, a shot"],
        "furious":  ["recalculating", "you moved", "that was my shot",
                     "I do not miss twice"],
        "smug":     ["centre mass", "as computed", "one shot", "textbook"],
        "sulking":  ["noted.", "fine.", "hm.", "wind, probably"],
        "asleep":   ["z z z", "...zzz", "eyes closed, not asleep"],
        "grabbed":  ["you have my arm", "release me", "this is not permitted",
                     "hands off the optics"],
        "thrown":   ["trajectory noted", "unhelpful", "I was aiming"],
        "ko":       ["...", "out of ammunition", "hm.", "range was wrong"],
        "victory":  ["confirmed", "one shot", "next target", "clean"],
        "hurt":     ["hit", "flesh wound", "recording that", "logged"],
        "fight":    ["ranging", "do not move", "acquiring", "in three. two."],
        "cursor":   ["I see you", "you are very large", "hold there",
                     "you blink a lot"],
        "hook":     ["repositioning", "higher ground", "moving"],
        "snatch":   ["{name} is cover now", "{name}: relocated", "requisitioned"],
        "boredom":  ["no targets. none.", "give me something", "this is a waste"],
        "rage":     ["someone moved my sightline", "unacceptable", "who fired"],
        "getup":    ["range was wrong", "adjusting", "again, correctly"],
        "wake":     ["eyes open", "...contact?", "I was resting my eyes"],
        "summoned": ["in position", "what.", "I was set up"],
        "generic":  ["low value", "not worth a round", "hm", "poor cover"],
        "hello":    ["surveying.", "let me get set up.", "good sightlines here"],
        "remember_runs":   ["run {runs}. same ground.", "{runs} deployments.",
                            "day {runs}. wind unchanged."],
        "remember_throws": ["thrown {throws} times. logged.",
                            "{throws}. I keep records."],
        "remember_fights": ["{wins} for {losses}. acceptable.",
                            "record: {wins}-{losses}."],
        "fav_icon": ["{name}. ranged and known.", "{name}, re-ranged", "zeroed on {name}"],
        "revenge":  ["adjusting", "once more, zeroed", "range corrected", "this time"],
        "gangup":   ["covering you", "I have the angle", "go, I'll shoot"],
        "ctx_thrash":   ["hold one", "pick a window", "you are jittering"],
        "ctx_focused":  ["you have not blinked", "same window, forty minutes",
                         "no movement"],
        "ctx_marathon": ["hours in this position", "get off that chair", "circulation"],
        "ctx_late":     ["it is 3am", "poor light", "nothing good at this hour"],
        "ctx_unsaved":  ["unsaved. exposed.", "one crash", "save. that is an order."],
    },
    "coward": {
        "bored":    ["...", "is it over?", "quiet is good", "quiet is nice"],
        "hyped":    ["oh! oh good", "is that for me?", "yes? YES?"],
        "furious":  ["I'm WARNING you", "don't make me", "I'll do it, I will"],
        "smug":     ["I survived", "still here", "see? see?"],
        "sulking":  ["nobody likes me", "fine.", "I'll be over here"],
        "asleep":   ["z z z", "...zzz", "shh, hiding"],
        "grabbed":  ["sorry sorry sorry", "please put me down", "I'll pay you",
                     "AAA don't"],
        "thrown":   ["AAAAAAA", "I didn't do it", "sorry! sorry!"],
        "ko":       ["...", "worth it, no it wasn't", "told you", "eep"],
        "victory":  ["did I do that?", "sorry!", "I didn't mean to", "no hard feelings?"],
        "hurt":     ["OW OW", "why me", "I wasn't even", "not the face"],
        "fight":    ["do we have to?", "let's talk about this", "I'm coming, I guess",
                     "no no no no"],
        "cursor":   ["the hand. THE HAND.", "not me", "pick someone else"],
        "hook":     ["away away away", "up here is safer", "not down there"],
        "snatch":   ["borrowing {name}", "{name} is my shield now", "just for a bit"],
        "boredom":  ["is anyone there?", "I'm lonely", "someone say something"],
        "rage":     ["that's it, I've had it", "no more", "I'm quite cross"],
        "getup":    ["I'm fine. fine.", "that didn't hurt", "walked into that"],
        "wake":     ["WHO'S THERE", "I'm awake I'm awake", "eep"],
        "summoned": ["me? really?", "coming, sorry", "am I in trouble"],
        "generic":  ["is that safe?", "I wouldn't touch it", "hm", "careful"],
        "hello":    ["hello? anyone?", "is this safe?", "I'll stay out of the way"],
        "remember_runs":   ["day {runs}. still alive.", "{runs} times now.",
                            "run {runs}. no incidents."],
        "remember_throws": ["{throws} times you've thrown me. I forgive you.", "{throws}. I count them.",
                            "{throws} throws and I never complain"],
        "remember_fights": ["{wins} wins. {losses} is fine too.",
                            "{losses} losses. it's not a competition."],
        "fav_icon": ["not {name} again", "{name} scares me", "we have history, {name}"],
        "revenge":  ["right. RIGHT.", "I've had enough", "no more running"],
        "gangup":   ["I'll help! from here", "you first", "right behind you"],
        "ctx_thrash":   ["are you alright?", "so many windows", "that's a lot"],
        "ctx_focused":  ["you've gone very still", "are you breathing", "blink?"],
        "ctx_marathon": ["you should rest", "it's been hours", "please stand up"],
        "ctx_late":     ["it's so late", "you should sleep", "everyone's asleep"],
        "ctx_unsaved":  ["save it! please", "unsaved. UNSAVED.", "oh no, save"],
    },
    "showoff": {
        "bored":    ["no audience", "...", "wasted on this crowd", "is anyone watching"],
        "hyped":    ["TA-DAA", "watch THIS", "and he's OFF", "showtime"],
        "furious":  ["how DARE you", "in front of everyone?", "UNACCEPTABLE"],
        "smug":     ["and the crowd goes wild", "flawless", "did you see that",
                     "no autographs"],
        "sulking":  ["nobody appreciates me", "fine.", "my talent is wasted"],
        "asleep":   ["z z z", "...zzz", "resting the instrument"],
        "grabbed":  ["not the FACE", "careful, I'm delicate", "unhand the talent"],
        "thrown":   ["STILL LOOKING GOOD", "wheeeee", "that was DELIBERATE"],
        "ko":       ["...", "curtain", "what a way to go", "remember me"],
        "victory":  ["THANK YOU, THANK YOU", "was that good for you", "encore?"],
        "hurt":     ["MY FACE", "not the profile", "OW, artistically"],
        "fight":    ["watch closely", "front row seats", "you'll want to see this"],
        "cursor":   ["an audience!", "watch this bit", "hello, gorgeous"],
        "hook":     ["and NOW the aerial", "ta-daa", "wheeeee"],
        "snatch":   ["and {name} DISAPPEARS", "for my next trick, {name}",
                     "nothing up my sleeves"],
        "boredom":  ["I need an AUDIENCE", "somebody watch me", "this is a tragedy"],
        "rage":     ["I was UPSTAGED", "who touched my things", "how DARE"],
        "getup":    ["and he RISES", "part two", "you thought that was it?"],
        "wake":     ["is it showtime", "I'm up, I'm up", "who woke the talent"],
        "summoned": ["you called?", "of course you did", "I'm needed"],
        "generic":  ["needs work", "no flair", "hm", "I could do better"],
        "hello":    ["and here he IS", "hello, desktop", "let's put on a show"],
        "remember_runs":   ["night {runs} of the tour", "{runs} shows now",
                            "run {runs}. still packing them in."],
        "remember_throws": ["{throws} throws. that's my record.",
                            "thrown {throws} times, landed all of them"],
        "remember_fights": ["{wins} and {losses}, and I look good either way",
                            "{wins} wins, all of them stylish"],
        "fav_icon": ["{name}, my old co-star", "{name} again! the crowd loves it"],
        "revenge":  ["the REMATCH", "act two", "this time with feeling"],
        "gangup":   ["a DUET", "together now", "on three, darling"],
        "ctx_thrash":   ["pick a scene", "so much scenery", "decide, decide"],
        "ctx_focused":  ["still watching that?", "same window, no applause"],
        "ctx_marathon": ["hours. no interval.", "even I need a break"],
        "ctx_late":     ["the late show", "it's past midnight, darling"],
        "ctx_unsaved":  ["SAVE, you fool", "unsaved! the drama!", "save it, darling"],
    },
    "grump": {
        "bored":    ["...", "*sigh*", "typical", "wonderful."],
        "hyped":    ["about time", "suppose that'll do", "fine. good."],
        "furious":  ["right. RIGHT.", "I've had it", "that's the last straw"],
        "smug":     ["told you", "as I said", "hm.", "knew it"],
        "sulking":  ["leave me alone", "fine.", "nobody listens", "typical"],
        "asleep":   ["z z z", "...zzz", "at last, quiet"],
        "grabbed":  ["put me down", "oh for-", "every time", "I'm too old for this"],
        "thrown":   ["typical", "my BACK", "wonderful. lovely."],
        "ko":       ["...", "finally, a rest", "hm.", "that'll do"],
        "victory":  ["there.", "done.", "can I sit down now", "sorted"],
        "hurt":     ["ow. right.", "was that necessary", "hm."],
        "fight":    ["let's get on with it", "fine.", "come on then", "quickly"],
        "cursor":   ["oh, it's you", "what now", "I was busy"],
        "hook":     ["up we go, I suppose", "hm", "this had better work"],
        "snatch":   ["taking {name}", "{name}'s in my way", "moving this"],
        "boredom":  ["is that it?", "nothing. as usual.", "hm."],
        "rage":     ["who moved that", "right, that's it", "I've had enough"],
        "getup":    ["not finished", "once more, then", "hm. again."],
        "wake":     ["what", "I was asleep", "this had better be good"],
        "summoned": ["what now", "I'm coming", "give me a minute"],
        "generic":  ["rubbish", "hm", "no thank you", "what's the point of that"],
        "hello":    ["hm. this again.", "right then.", "let's get it over with"],
        "remember_runs":   ["run {runs}. joy.", "{runs} times. no better.",
                            "day {runs}. wonderful."],
        "remember_throws": ["{throws} throws. my back knows.",
                            "thrown {throws} times. typical."],
        "remember_fights": ["{wins}-{losses}. about right.",
                            "{losses} losses. I remember each one."],
        "fav_icon": ["{name}. of course.", "{name}. wonderful.", "always {name}, isn't it"],
        "revenge":  ["no.", "oh no you don't", "right, properly this time"],
        "gangup":   ["fine, together", "you take that side", "hm. alright."],
        "ctx_thrash":   ["decide.", "stop that", "pick one"],
        "ctx_focused":  ["still?", "it hasn't changed", "not budged, have you"],
        "ctx_marathon": ["hours. hours.", "get up", "this isn't healthy"],
        "ctx_late":     ["it's late", "go to bed", "look at the time"],
        "ctx_unsaved":  ["just save it", "unsaved.", "you'll lose that"],
    },
    "magpie": {
        "bored":    ["...", "ooh?", "nothing shiny", "hm. dull."],
        "hyped":    ["OOH", "shiny shiny", "MINE", "look at it!"],
        "furious":  ["MINE", "give it BACK", "that's not yours"],
        "smug":     ["mine now", "collected", "one more", "into the pile"],
        "sulking":  ["you took it back", "fine.", "I only borrowed it"],
        "asleep":   ["z z z", "...zzz", "counting them"],
        "grabbed":  ["I didn't take anything", "check my pockets, nothing",
                     "down! I'll drop it!", "I found it like that"],
        "thrown":   ["I'M HOLDING SOMETHING", "careful, it's fragile", "AAA"],
        "ko":       ["...", "keep the icons", "don't touch my pile", "shiny..."],
        "victory":  ["mine", "and yours is mine", "collected", "and your stuff too"],
        "hurt":     ["ay! careful!", "not the goods", "rude", "watch the merchandise"],
        "fight":    ["what have you GOT", "give it here", "hand it over"],
        "cursor":   ["ooh, a big one", "can I have it", "what's that"],
        "hook":     ["ooh, up there", "shiny up here", "wheee"],
        "snatch":   ["ooh, {name}", "{name} is MINE", "into the pile with {name}",
                     "mine mine mine"],
        "boredom":  ["nothing left to take", "MORE", "give me something shiny"],
        "rage":     ["someone's been in my pile", "who touched it", "MINE"],
        "getup":    ["still got it", "check the pile", "up. where's my pile."],
        "wake":     ["is it still there", "...mine?", "is my pile safe"],
        "summoned": ["is there something for me", "coming!", "what've you got"],
        "generic":  ["ooh", "mine", "I'll take that", "what IS that", "shiny"],
        "hello":    ["ooh, a whole desktop", "so much STUFF", "mine, all of it"],
        "remember_runs":   ["visit {runs}", "{runs} raids now", "day {runs}. still collecting."],
        "remember_throws": ["{throws} throws and I kept hold every time",
                            "thrown {throws} times. never dropped it."],
        "remember_fights": ["{wins} wins, {losses} donations",
                            "{wins}-{losses}. I count everything."],
        "fav_icon": ["{name}! my favourite", "{name} again, lovely", "mine, {name}"],
        "revenge":  ["give it BACK", "that was mine", "you're not keeping it"],
        "gangup":   ["you distract it", "half each", "we split it"],
        "ctx_thrash":   ["ooh, and that one, and that one", "so many!", "pick one for me"],
        "ctx_focused":  ["that one? just that one?", "boring one", "still that?"],
        "ctx_marathon": ["hours on ONE thing", "get up, find me things"],
        "ctx_late":     ["late shift", "nobody's watching now", "good time for it"],
        "ctx_unsaved":  ["save it before you lose it", "unsaved, careful", "mind that"],
    },
    "zealot": {
        "bored":    ["...", "the hour approaches", "patience", "soon"],
        "hyped":    ["IT BEGINS", "AT LAST", "THE HOUR IS COME", "THE TIME IS NOW"],
        "furious":  ["HERESY", "YOU WILL ANSWER", "IT IS WRITTEN", "UNCLEAN"],
        "smug":     ["as foretold", "it was written", "inevitable", "so it is"],
        "sulking":  ["I am misunderstood", "none of you see", "so be it"],
        "asleep":   ["z z z", "...zzz", "the vigil ends"],
        "grabbed":  ["RELEASE ME", "you dare", "unhand the faithful", "SACRILEGE"],
        "thrown":   ["I AM UNBROKEN", "this too was written", "I ASCEND"],
        "ko":       ["...", "it was foretold", "I go gladly", "not the end"],
        "victory":  ["IT IS DONE", "so pass the unworthy", "as promised", "RISE, IF YOU CAN"],
        "hurt":     ["PAIN IS NOTHING", "I feel nothing", "is that all"],
        "fight":    ["JUDGEMENT", "come, then", "your hour", "I HAVE COME"],
        "cursor":   ["the great hand", "I know you", "you steer everything"],
        "hook":     ["I ASCEND", "upward", "carry me"],
        "snatch":   ["{name} is claimed", "{name} shall be moved", "so it is written"],
        "boredom":  ["GIVE ME PURPOSE", "there is nothing to smite", "I hunger"],
        "rage":     ["DEFILEMENT", "who has done this", "IT IS WRITTEN"],
        "getup":    ["I RETURN", "you cannot end me", "AGAIN", "it is not finished"],
        "wake":     ["THE HOUR", "I wake", "who calls"],
        "summoned": ["I ANSWER", "you called", "at last, purpose"],
        "generic":  ["unclean", "it must go", "hm", "this offends me"],
        "hello":    ["A NEW WORLD", "I have come", "this place needs order"],
        "remember_runs":   ["the {runs}th coming", "run {runs}. the work continues.",
                            "{runs} vigils"],
        "remember_throws": ["{throws} times cast down. {throws} times risen.",
                            "thrown {throws} times. still here."],
        "remember_fights": ["{wins} judgements delivered", "{wins}-{losses}. the work continues."],
        "fav_icon": ["{name}. AGAIN.", "my old adversary, {name}", "{name} still stands"],
        "revenge":  ["NOT AGAIN", "this time it ends", "I have prepared"],
        "gangup":   ["JOIN ME", "together, brother", "as one"],
        "ctx_thrash":   ["CHOOSE", "indecision is weakness", "pick, mortal"],
        "ctx_focused":  ["such devotion", "you have not moved", "admirable. worrying."],
        "ctx_marathon": ["HOURS of this", "rest is not weakness", "stand"],
        "ctx_late":     ["the small hours", "nothing good is written now", "rest, mortal"],
        "ctx_unsaved":  ["PRESERVE IT", "unsaved. folly.", "preserve the work"],
    },
    "tinkerer": {
        "bored":    ["...", "recalibrating", "hm", "idle cycle"],
        "hyped":    ["it works!", "excellent", "as designed", "ha!"],
        "furious":  ["you broke it", "that was CALIBRATED", "unacceptable variance"],
        "smug":     ["as designed", "within tolerance", "as calculated", "within model"],
        "sulking":  ["nobody reads the manual", "fine.", "hm."],
        "asleep":   ["z z z", "...zzz", "powered down"],
        "grabbed":  ["mind the mechanism", "you'll break something", "put me down carefully",
                     "I am not a handle"],
        "thrown":   ["ballistic. unplanned.", "recording the arc", "unstable!"],
        "ko":       ["...", "systems down", "back to the workshop", "hm."],
        "victory":  ["as designed", "test successful", "noted for the log", "next prototype"],
        "hurt":     ["structural damage", "ow. noted.", "that'll bruise"],
        "fight":    ["field test", "hold still, this is calibrated", "stand there. exactly there."],
        "cursor":   ["the operator", "you are imprecise", "steady hands, please"],
        "hook":     ["deploying line", "tension good", "up we go"],
        "snatch":   ["{name} is a component now", "salvaging {name}", "{name}: reassigned"],
        "boredom":  ["nothing to build", "give me parts", "idle. wasteful."],
        "rage":     ["someone moved my things", "my WORKBENCH", "who reorganised this"],
        "getup":    ["design flaw. corrected.", "iteration two", "again, properly"],
        "wake":     ["powering up", "...status?", "who is in my workshop"],
        "summoned": ["on my way", "what needs fixing", "bring it here"],
        "generic":  ["poorly made", "hm", "I could improve that", "shoddy"],
        "hello":    ["let me see the schematics", "a new workspace", "what have we here"],
        "remember_runs":   ["build {runs}", "iteration {runs}", "run {runs}. logged."],
        "remember_throws": ["thrown {throws} times. all logged.",
                            "{throws} data points on being thrown."],
        "remember_fights": ["{wins}-{losses}. within tolerance.",
                            "{wins} successes, {losses} failures. useful."],
        "fav_icon": ["{name}. structurally interesting.", "{name}, same tolerances", "back to {name}"],
        "revenge":  ["recalibrated", "corrected", "the flaw is fixed"],
        "gangup":   ["combined load", "you push, I'll time it", "coordinated"],
        "ctx_thrash":   ["settle on one", "context switching is expensive", "focus"],
        "ctx_focused":  ["deep in it", "same window an hour", "no state change"],
        "ctx_marathon": ["hours at the bench", "diminishing returns", "rest"],
        "ctx_late":     ["late-night work is undone in the morning", "it's 3am"],
        "ctx_unsaved":  ["unsaved. bad practice.", "save. now.", "commit that"],
    },
    "drama": {
        "bored":    ["...", "I am WASTING away", "such tedium", "nothing. NOTHING."],
        "hyped":    ["AT LONG LAST", "MY MOMENT", "I LIVE", "oh, JOY"],
        "furious":  ["BETRAYAL", "how COULD you", "I am UNDONE", "TREACHERY"],
        "smug":     ["naturally", "was there ever doubt", "I was magnificent"],
        "sulking":  ["nobody understands me", "I shall never recover", "leave me to my grief"],
        "asleep":   ["z z z", "...zzz", "even my dreams are tragic"],
        "grabbed":  ["UNHAND ME", "I am ABDUCTED", "the indignity", "HELP, someone"],
        "thrown":   ["I AM FLUNG", "my finest hour", "AAAAAA", "cruel, cruel world"],
        "ko":       ["...", "tell my story", "I regret NOTHING", "remember me kindly"],
        "victory":  ["and SO it ends", "witness it", "let this be recorded", "I weep for you"],
        "hurt":     ["I AM SLAIN", "the PAIN", "how could you", "MY SIDE"],
        "fight":    ["at LAST, a nemesis", "our moment comes", "prepare yourself"],
        "cursor":   ["the great hand returns", "you again, tormentor", "witness me"],
        "hook":     ["I FLY", "into the heavens", "I SOAR"],
        "snatch":   ["{name} comes with ME", "farewell, {name}'s home", "I take {name}"],
        "boredom":  ["I am DYING of boredom", "give me DRAMA", "somebody DO something"],
        "rage":     ["MY THINGS", "who has DONE this", "an OUTRAGE"],
        "getup":    ["I RISE", "the second act", "you thought that was the end?"],
        "wake":     ["I LIVE", "what fresh horror", "who dares wake me"],
        "summoned": ["I ANSWER THE CALL", "you need me", "of course you do"],
        "generic":  ["hideous", "who made this", "an offence", "hm"],
        "hello":    ["and so it begins", "a new stage", "I have ARRIVED"],
        "remember_runs":   ["act {runs}", "the {runs}th tragedy", "run {runs}, and still I suffer"],
        "remember_throws": ["{throws} TIMES you have thrown me",
                            "{throws}. I have counted every one."],
        "remember_fights": ["{wins} triumphs, {losses} tragedies",
                            "{wins}-{losses}. history will be kind."],
        "fav_icon": ["{name}! my NEMESIS", "{name}, we are fated", "{name}. always {name}."],
        "revenge":  ["THIS TIME", "the reckoning", "I have waited for this"],
        "gangup":   ["TOGETHER", "our alliance!", "side by side"],
        "ctx_thrash":   ["SO MANY WINDOWS", "the CHAOS", "choose, I beg you"],
        "ctx_focused":  ["such STILLNESS", "have you turned to stone", "blink, please"],
        "ctx_marathon": ["HOURS", "you will perish at that desk", "stand, I implore you"],
        "ctx_late":     ["the witching hour", "midnight, and still you toil"],
        "ctx_unsaved":  ["UNSAVED", "one crash and all is LOST", "save, save!"],
    },
    "veteran": {
        "bored":    ["...", "hm", "seen it", "quiet"],
        "hyped":    ["good", "right", "hm. good.", "now then"],
        "furious":  ["no", "don't", "that's enough", "last warning"],
        "smug":     ["hm", "thought so", "same as always", "predictable"],
        "sulking":  ["hm.", "fine", "...", "no matter"],
        "asleep":   ["z z z", "...zzz", "resting"],
        "grabbed":  ["down", "no", "let go", "hm."],
        "thrown":   ["hm", "landed worse", "again?"],
        "ko":       ["...", "hm", "that's that", "fair"],
        "victory":  ["done", "up you get", "next", "hm"],
        "hurt":     ["hm", "had worse", "noted", "fine"],
        "fight":    ["right", "come on", "let's go", "hm"],
        "cursor":   ["you", "hm", "you again", "still there"],
        "hook":     ["up", "hm", "hold on"],
        "snatch":   ["{name}", "having {name}", "{name}, then"],
        "boredom":  ["nothing", "hm.", "quiet again"],
        "rage":     ["who did that", "no", "enough"],
        "getup":    ["again", "hm", "not done", "up"],
        "wake":     ["hm", "awake", "who's that"],
        "summoned": ["moving", "hm", "right"],
        "generic":  ["hm", "seen it", "no", "fine"],
        "hello":    ["hm. this place.", "right then", "seen worse"],
        "remember_runs":   ["run {runs}", "{runs}. hm.", "day {runs}"],
        "remember_throws": ["{throws} throws", "thrown {throws} times. hm."],
        "remember_fights": ["{wins}-{losses}", "{wins} wins. hm."],
        "fav_icon": ["{name}", "{name} again", "hm. {name}."],
        "revenge":  ["no", "not again", "properly this time"],
        "gangup":   ["with you", "go on", "I've got this side"],
        "ctx_thrash":   ["settle", "one at a time", "hm"],
        "ctx_focused":  ["still on that", "hm", "long time"],
        "ctx_marathon": ["long shift", "stand up", "hm. hours."],
        "ctx_late":     ["late", "sleep", "it's gone midnight"],
        "ctx_unsaved":  ["save it", "unsaved", "hm. save."],
    },
}

class Fighter:
    def __init__(self, x, y, kind=ROSTER[0]):
        self.become(kind)
        self.x, self.y = x, y
        self.vx = self.vy = 0.0
        self.face = 1
        self.sc = CFG["scale"]
        self.on_ground = False
        self.plat = None            # (kind, key) he is standing on
        self.state = "idle"
        self.st = 0.0
        self.goal = 0.0
        self.mood = "bored"
        self.mood_t = 0.0
        self.mood_check = 0.0
        self.boredom = 0.0
        self.anger = 0.0
        self.weapon = "sword"
        self.plan = "sword"
        self.walk = 0.0
        self.target = None
        self.foe = None
        self.hp = 100.0
        self.atk = 0.0
        self.atk_dur = .4
        self.aim = 0.0
        self.fired = False
        self.burst = 0.0
        self.zip = None
        self.hook = None
        self.emote = None
        self.emote_t = 0.0
        self.grabbed = False
        self.gx = self.gy = 0.0
        self.tumble = 0.0
        self.vr = 0.0
        self.stun = 0.0
        self.blink = 1.0
        self.look = 0.0
        self.wander_to = x
        self.ledge_cd = 0.0        # no re-grabbing the lip he just left
        self.out = 0.0             # how long he has been out of sight
        self.at_foe = False        # this shot is meant for the other one
        self.squash = 0.0          # >0 land squash, <0 stretch
        self.carry = None          # (icon index, dx, dy offset to list coords)
        self.carry_t = 0.0
        self.skid = 0.0
        self.hits = 0
        self.said = 0.0
        self.mode = "roam"
        self.atk_cd = 0.0
        self.snatch = False
        self.carry_dest_y = y

    # -- helpers ----------------------------------------------------------
    def become(self, kind):
        """Colour, voice and temperament all follow from which one he is."""
        self.kind = kind
        self.pal = PALETTES[kind]
        self.per = TRAITS[kind]

    def line(self, event, **fmt):
        txt = random.choice(VOICES[self.kind][event])
        return txt.format(**fmt) if fmt else txt

    def say(self, txt, dur=1.5):
        self.emote, self.emote_t = txt, dur

    def yell(self, event, dur=1.5, **fmt):
        """Say something this particular one would say."""
        self.say(self.line(event, **fmt), dur)

    def set_state(self, s):
        self.state, self.st = s, 0.0

    def set_mood(self, m, quiet=False):
        if self.mood == m:
            return
        self.mood, self.mood_t = m, 0.0
        # The quiet ones keep it to themselves. Without this, chatty only gated
        # remarks about your windows, so a fivefold spread in the trait produced
        # barely a doubling in how much they actually said.
        if not quiet and random.random() < min(1.0, .55 * self.per["chatty"]):
            self.yell(m, 1.6)

    def color(self):
        return self.pal.get(self.mood, "#F2F5FF")

    def K(self):
        return self.sc / 1.75

    def head_y(self):
        return self.y - 66 * self.sc


def plan_weapon(per, rage=False):
    """Each favours his own half of the arsenal, most of the time. In a rage he
    reaches for his top three, which is what makes the brawler charge."""
    if rage:
        return random.choice(per["weapons"][:3])
    if random.random() < .72:
        return random.choice(per["weapons"])
    return random.choice(WEAPONS)

# ==========================================================================
#  THE APP
# ==========================================================================
class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        vx, vy, vw, vh = virtual_screen()
        self.mons = monitors()
        if not CFG["all_monitors"]:
            m = self.mons[0]
            vx, vy = m[0][0], m[0][1]
            vw, vh = m[0][2] - m[0][0], m[0][3] - m[0][1]
        self.ox, self.oy, self.W, self.H = vx, vy, vw, vh

        self.root.geometry(f"{self.W}x{self.H}+{self.ox}+{self.oy}")
        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.root.update_idletasks()
        self.root.attributes("-transparentcolor", KEY)

        try:
            try:
                self.hwnd = int(self.root.wm_frame(), 16)
            except Exception:
                self.hwnd = user32.GetParent(self.canvas.winfo_id()) or self.root.winfo_id()
            ex = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE,
                                   ex | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE)
        except Exception:
            self.hwnd = 0

        self.terrain = Terrain()
        self.terrain.refresh(self.hwnd)

        self.time = 0.0
        self.paused = False
        self.running = True
        self.settings_win = None
        self.parts, self.shots, self.slashes, self.booms, self.bolts = [], [], [], [], []
        self.shake_t = self.shake_m = 0.0
        self.sx = self.sy = 0.0
        self.mouse = {"x": -9999, "y": -9999, "t": -99, "vx": 0, "vy": 0}
        self.hover = None
        self.fg = None
        self.asleep = False
        self.icons_locked = False
        self.watch = Watcher()
        self.shove_at = -9.0      # last time a bullet nudged an icon
        self.warned = False       # only nag about errors once a run
        self.awake_since = 0.0
        self.greeted = False
        self.mem_saved = 0.0

        # Canvas item pool. Items are moved and recoloured frame to frame
        # instead of being deleted and rebuilt. Tk draws in creation order, so
        # every item carries a layer tag and _frame_end() raises those tags in a
        # fixed sequence — that, not call order, is what fixes the stacking.
        self._pool = {}       # tag -> {kind: [item ids]}
        self._used = {}       # tag -> {kind: how many this frame}
        self._prev = {}       # tag -> {kind: how many last frame}
        self._opt = {}        # item id -> options last applied, None if hidden
        self._layer = "part"
        self._layers = []
        self._ftag = []
        self._rtag = []

        self.fighters = []
        self.spawn_fighters()

        self.canvas.bind("<ButtonPress-1>", self.on_down)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_up)
        self.canvas.bind("<ButtonPress-3>", lambda e: self.open_settings())

        self.tray = Tray()
        self.tray.add("Settings...", self.open_settings)
        self.tray.add("Pause", self.toggle_pause, "check", lambda: self.paused)
        self.tray.sep()
        self.tray.add("Bring them to my cursor", self.summon)
        self.tray.add("Restore my icon layout", self.restore_icons)
        self.tray.sep()
        self.tray.add("Quit", self.quit)
        self.tray.build()

        # Tk catches exceptions raised inside callbacks and prints them to
        # stderr, which under pythonw is None -- so they vanish completely and
        # the gremlins just stop doing whatever it was. Log them and say so.
        self.root.report_callback_exception = self.on_callback_error

        # auto-arrange fights us for every icon we try to move
        if CFG["move_icons"]:
            lv = find_desktop_listview()
            if lv and autoarrange_on(lv):
                self.icons_locked = True

    # -- lifecycle ---------------------------------------------------------
    def spawn_fighters(self):
        """Build the cast up or down to whatever the setting asks for.

        Survivors are kept rather than rebuilt. This runs every time the slider
        moves, and the old version threw away everyone but the first, losing
        their health, mood, position and any icon they were holding."""
        want = int(clamp(CFG["crowd"], 1, len(ROSTER)))
        keep = self.fighters[:want]
        for f in self.fighters[want:]:
            self.drop_icon(f)          # never leave one holding a real icon
        for i in range(len(keep), want):
            x = self.ox + self.W * (i + 1.0) / (want + 1.0)
            keep.append(Fighter(x, self.ground_at(x), ROSTER[i]))
        self.fighters = keep
        for i, f in enumerate(self.fighters):
            f.become(ROSTER[i])
            f.sc = CFG["scale"]
            f.foe = None               # free-for-all; picked fresh in decide()
        self._build_layers()
        self._prune_layers()

    def _prune_layers(self):
        """Throw away pooled canvas items belonging to fighters who have gone.

        The pool is keyed by layer tag and nothing else ever removes from it, so
        without this, dropping ten to one leaves nine fighters' worth of items
        in it for the rest of the session -- hidden, but still walked and still
        raised every frame."""
        live = set(self._layers)
        for tag in [t for t in self._pool if t not in live]:
            for items in self._pool[tag].values():
                for it in items:
                    try:
                        self.canvas.delete(it)
                    except Exception:
                        pass
                    self._opt.pop(it, None)
            self._pool.pop(tag, None)
            self._used.pop(tag, None)
            self._prev.pop(tag, None)

    def _build_layers(self):
        """The draw order, as tags. _frame_end() raises them in this sequence,
        so a rope drawn before a fighter still ends up behind him however the
        pools happened to grow."""
        seq = ["dbg", "boom", "bolt", "part", "shot", "shotd", "slash"]
        self._rtag = []
        for i in range(len(self.fighters)):
            self._rtag.append(("rope%d" % i, "roped%d" % i))
            seq.extend(self._rtag[i])
        seq.append("hover")
        self._ftag = []
        for i in range(len(self.fighters)):
            # body, head, face, right arm, weapon, weapon dots,
            # then overlay: cargo/health, speech box, speech text
            self._ftag.append(("b%d" % i, "h%d" % i, "f%d" % i, "a%d" % i,
                               "w%d" % i, "wd%d" % i,
                               "o%d" % i, "ob%d" % i, "ot%d" % i))
        for t in self._ftag:
            seq.extend(t[:6])
        for t in self._ftag:
            seq.extend(t[6:])
        self._layers = seq

    def apply_settings(self):
        for f in self.fighters:
            f.sc = CFG["scale"]
        want = int(clamp(CFG["crowd"], 1, len(ROSTER)))
        if len(self.fighters) != want:
            self.spawn_fighters()

    def on_callback_error(self, exc, val, tb):
        import traceback
        print("callback error:")
        traceback.print_exception(exc, val, tb)
        if not self.warned:
            self.warned = True
            try:
                self.tray.notify("Desktop Gremlin",
                                 "Something went wrong. Details are in "
                                 "gremlin_log.txt next to the script.")
            except Exception:
                pass

    def toggle_pause(self):
        self.paused = not self.paused

    def summon(self):
        n = len(self.fighters)
        for i, f in enumerate(self.fighters):
            # fan them out, or ten of them arrive stacked on one pixel
            spread = (i - (n - 1) / 2.0) * 70
            f.wander_to = clamp(self.mouse["x"] + spread,
                                self.ox + 40, self.ox + self.W - 40)
            f.target = None
            f.set_state("walk")
            f.goal = self.time + 6
            f.yell("summoned", 1.2)

    def restore_icons(self):
        n = restore_layout()
        self.tray.notify("Desktop Gremlin",
                         f"Put {n} icon(s) back where they were."
                         if n else "No saved layout to restore.")

    def quit(self):
        self.running = False
        try:
            save_memory()
        except Exception:
            pass
        try:
            self.tray.remove()
        except Exception:
            pass
        try:
            SHELL.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # -- geometry ----------------------------------------------------------
    def ground_at(self, x, y=None):
        """Bottom of the work area of whichever monitor this x sits on."""
        for mon, work in self.mons:
            if mon[0] <= x < mon[2] and (y is None or mon[1] <= y < mon[3]):
                return work[3]
        return self.mons[0][1][3]

    def nearest_enemy(self, f):
        """Closest one still on his feet. Free-for-all: no fixed pairings, so
        this is re-asked every time he decides what to do."""
        best, bd = None, 1e9
        for o in self.fighters:
            if o is f or o.hp <= 0 or o.state in ("ko", "grabbed"):
                continue
            d = abs(o.x - f.x) + abs(o.y - f.y) * .5
            if d < bd:
                best, bd = o, d
        return best

    # -- mouse -------------------------------------------------------------
    def near_fighter(self, sx, sy):
        best, bd = None, 1e9
        for f in self.fighters:
            d = dist(sx, sy, f.x, f.y - 34 * f.sc)
            if d < bd:
                best, bd = f, d
        return best if bd < 62 else None

    def on_down(self, e):
        f = self.near_fighter(e.x + self.ox, e.y + self.oy)
        if not f:
            return
        f.grabbed = True
        f.gx, f.gy = e.x + self.ox, e.y + self.oy + 58 * f.sc
        f.set_state("grabbed")
        f.anger = clamp(f.anger + .28 * f.per["grudge"], 0, 1)
        bump(f.kind, "grabbed")
        f.boredom = 0
        self.drop_icon(f)
        f.yell("grabbed", 1.5)
        if f.anger > .5:
            f.set_mood("furious")

    def on_drag(self, e):
        for f in self.fighters:
            if f.grabbed:
                f.gx, f.gy = e.x + self.ox, e.y + self.oy + 58 * f.sc

    def on_up(self, e):
        for f in self.fighters:
            if not f.grabbed:
                continue
            f.grabbed = False
            lk = .5 + .5 * f.K()
            f.vx = clamp(self.mouse["vx"], -1300, 1300) * lk
            f.vy = clamp(self.mouse["vy"], -1300, 1300) * lk - 120 * f.K()
            f.vr = clamp(f.vx / (110 * f.K()), -13, 13)
            bump(f.kind, "thrown")
            f.set_state("thrown")
            f.yell("thrown", 1.4)

    def poll_cursor(self, dt):
        pt = wt.POINT()
        try:
            user32.GetCursorPos(ctypes.byref(pt))
        except Exception:
            return
        nx, ny = pt.x, pt.y
        if dt > 0 and self.mouse["x"] > -9000:
            self.mouse["vx"] = (nx - self.mouse["x"]) / dt
            self.mouse["vy"] = (ny - self.mouse["y"]) / dt
        if abs(nx - self.mouse["x"]) + abs(ny - self.mouse["y"]) > 1:
            self.mouse["t"] = self.time
        self.mouse["x"], self.mouse["y"] = nx, ny
        self.hover = self.near_fighter(nx, ny)

    # -- fx ----------------------------------------------------------------
    def shake(self, t, m):
        self.shake_t = max(self.shake_t, t)
        self.shake_m = max(self.shake_m, m)

    def spark(self, x, y, n, col, spd, k=1.0):
        for _ in range(n):
            a = random.random() * TAU
            s = random.uniform(spd * .3, spd) * k
            self.parts.append({"x": x, "y": y, "vx": math.cos(a) * s,
                               "vy": math.sin(a) * s - random.uniform(0, 60) * k,
                               "life": random.uniform(.3, .9), "t": 0, "col": col,
                               "r": random.uniform(1.2, 3.2) * max(.5, k),
                               "g": 900 * k, "k": "dot"})

    def puff(self, x, y, n, col=DUST, k=1.0, spread=26):
        for _ in range(n):
            self.parts.append({"x": x + random.uniform(-spread, spread) * k,
                               "y": y - random.uniform(0, 6) * k,
                               "vx": random.uniform(-70, 70) * k,
                               "vy": random.uniform(-46, -8) * k,
                               "life": random.uniform(.35, .8), "t": 0, "col": col,
                               "r": random.uniform(3, 7) * max(.5, k),
                               "g": 120 * k, "k": "dot"})

    def debris(self, cx, cy, w, h, n, col, k=1.0):
        for _ in range(n):
            self.parts.append({"x": cx + random.uniform(-w / 2, w / 2),
                               "y": cy + random.uniform(-h / 2, h / 2),
                               "vx": random.uniform(-190, 190) * k,
                               "vy": random.uniform(-330, -60) * k,
                               "life": random.uniform(.9, 1.9), "t": 0, "col": col,
                               "r": random.uniform(2.5, 6) * k, "g": 1250 * k,
                               "k": "chunk"})

    def boom(self, x, y, r, k=1.0, big=False):
        self.booms.append({"x": x, "y": y, "r": r * k, "t": 0, "life": .5 if big else .42})
        self.spark(x, y, 30 if big else 20, FIRE, 520 if big else 400, k)
        self.puff(x, y, 8 if big else 5, "#FFCF9A", k, 18)
        self.shake(.4 if big else .3, (16 if big else 10) * k)

    def bolt(self, x0, y0, x1, y1):
        pts, n = [], 9
        for i in range(n + 1):
            t = i / n
            px = lerp(x0, x1, t) + (random.uniform(-16, 16) if 0 < i < n else 0)
            py = lerp(y0, y1, t) + (random.uniform(-16, 16) if 0 < i < n else 0)
            pts += [px, py]
        self.bolts.append({"pts": pts, "t": 0, "life": .22})

    # ==================================================================
    #  icon carrying — the real ones, really moved
    # ==================================================================
    def can_move_icons(self):
        return (CFG["move_icons"] and BACKUP_OK and not self.icons_locked
                and self.terrain.icons_ok)

    def blast_icons(self, x, y, rad, power):
        """Shove real desktop icons away from an explosion.

        List coordinates differ from screen ones by the same constant for the
        whole view, so one probe read gets the offset and everything after it
        is a write. Capped at six icons a blast: each one is a round trip into
        Explorer, and a minigun should not be able to queue forty of them."""
        if not self.can_move_icons():
            return 0
        near = []
        for name, l, t, r, b, idx in self.terrain.icons:
            d = dist(x, y, (l + r) / 2, (t + b) / 2)
            if d < rad:
                near.append((d, l, t, r, b, idx))
        if not near:
            return 0
        near.sort()
        del near[6:]
        held = {f.carry["idx"] for f in self.fighters if f.carry}
        if not SHELL.open():
            return 0
        probe = SHELL.item_pos(near[0][5])
        offx, offy = probe[0] - near[0][1], probe[1] - near[0][2]
        gy = self.ground_at(x)
        moved, fresh = 0, []
        for d, l, t, r, b, idx in near:
            if idx in held:
                continue
            w, h = r - l, b - t
            ax, ay = (l + r) / 2 - x, (t + b) / 2 - y
            n = math.hypot(ax, ay)
            if n < 1.0:                       # sitting on the blast: pick a way
                a = random.random() * TAU
                ax, ay, n = math.cos(a), math.sin(a), 1.0
            push = power * (1 - d / rad)
            nx = clamp(l + ax / n * push, self.ox + 4, self.ox + self.W - w - 4)
            ny = clamp(t + ay / n * push, self.oy + 4, gy - h - 4)
            if SHELL.set_item_pos(idx, nx + offx, ny + offy):
                moved += 1
                self.puff((l + r) / 2, (t + b) / 2, 3, DUST, .7, 10)
                fresh.append((name, int(nx), int(ny), int(nx) + w, int(ny) + h, idx))
        if fresh:
            # keep our own copy honest until the next terrain refresh, or a
            # second blast in the same second shoves from stale positions
            moved_idx = {e[5] for e in fresh}
            self.terrain.icons = [e for e in self.terrain.icons
                                  if e[5] not in moved_idx] + fresh
        return moved

    def pick_up_icon(self, f, tgt):
        if not self.can_move_icons() or f.carry or tgt.get("kind") != "icon":
            return False
        idx = tgt["key"]
        try:
            if not SHELL.open():
                return False
            rect = SHELL.item_rect(idx)
            lx, ly = SHELL.item_pos(idx)
        except Exception:
            return False
        if not rect:
            return False
        f.carry = {"idx": idx, "offx": lx - rect[0], "offy": ly - rect[1],
                   "w": rect[2] - rect[0], "h": rect[3] - rect[1],
                   "name": tgt.get("name", "")}
        f.carry_t = 0.0
        f.set_state("carry")
        gy = self.ground_at(f.x)
        f.wander_to = clamp(f.x + random.uniform(-620, 620), self.ox + 90,
                            self.ox + self.W - 90)
        f.carry_dest_y = clamp(gy - random.uniform(60, 420), 40, gy - 60)
        bump(f.kind, "icons_moved")
        bump_icon(f.carry["name"])
        f.yell("snatch", 1.6, name=f.carry["name"][:12] or "that")
        return True

    def carry_tick(self, f, dt):
        if not f.carry:
            return
        f.carry_t += dt
        if f.carry_t < .12:
            return
        f.carry_t = 0.0
        c = f.carry
        sx = f.x - c["w"] / 2
        sy = f.y - 84 * f.sc - c["h"] / 2
        try:
            SHELL.set_item_pos(c["idx"], sx + c["offx"], sy + c["offy"])
        except Exception:
            f.carry = None

    def drop_icon(self, f, where=None):
        if not f.carry:
            return
        c = f.carry
        try:
            if where:
                sx, sy = where[0] - c["w"] / 2, where[1] - c["h"] / 2
            else:
                sx, sy = f.x - c["w"] / 2, f.y - 40 * f.sc
            gy = self.ground_at(f.x)
            sx = clamp(sx, self.ox + 4, self.ox + self.W - c["w"] - 4)
            sy = clamp(sy, 4, gy - c["h"] - 4)
            SHELL.set_item_pos(c["idx"], sx + c["offx"], sy + c["offy"])
            self.puff(sx + c["w"] / 2, sy + c["h"], 6, DUST, f.K())
        except Exception:
            pass
        f.carry = None

    # ==================================================================
    #  combat
    # ==================================================================
    def fire_hook(self, f, tx, ty):
        gy = self.ground_at(f.x)
        tx = clamp(tx, self.ox + 20, self.ox + self.W - 20)
        ty = clamp(ty, self.oy + 34, gy - 40)
        f.hook = {"x": f.x, "y": f.y - 60 * f.sc, "tx": tx, "ty": ty, "t": 0,
                  "dur": clamp(dist(f.x, f.y - 60, tx, ty) / 1500, .12, .5)}
        f.set_state("hookfire")
        f.face = 1 if tx > f.x else -1
        f.yell("hook", 1.0)

    def start_attack(self, f, at=None, foe=False):
        if at is not None:
            cx, cy = at
        elif foe and f.foe:
            cx, cy = f.foe.x, f.foe.y - 34 * f.foe.sc
        elif f.target:
            cx, cy = f.target["cx"], f.target["cy"]
        else:
            f.set_state("idle")
            return
        f.aim = math.atan2(cy - (f.y - 58 * f.sc), cx - f.x)
        f.face = 1 if cx > f.x else -1
        if at is not None:
            f.weapon = "sword" if abs(cx - f.x) < 70 else random.choice(["blaster", "bow"])
        elif foe:
            # Whatever he closed the distance for is what he fires. The fight
            # state walks him to REACH[f.plan]; swapping in a different weapon
            # here left him standing at lightning range swinging a sword, and
            # missing with it. Measured over four minutes of fighting before
            # this line changed: every chainsaw swing and 9 in 10 sword swings
            # were thrown from outside their own reach.
            f.weapon = f.plan
        else:
            f.weapon = f.plan
        # Shots meant for the other one ignore the desktop on the way past;
        # otherwise a row of icons between them soaks up every round.
        f.at_foe = bool(foe and f.foe)
        if f.weapon == "bow":
            k = f.K()
            ang = lob_angle(cx - f.x, cy - (f.y - 58 * f.sc), 720 * k, 420 * k)
            if ang is not None:
                f.aim = ang
        f.atk_dur = ATKDUR[f.weapon]
        f.atk = 0.0
        f.fired = False
        f.burst = 0.0
        f.set_state("attack")

    def muzzle(self, f):
        return (f.x + math.cos(f.aim) * 26 * f.sc,
                f.y - 58 * f.sc + math.sin(f.aim) * 26 * f.sc)

    def shoot(self, f, kind, speed, grav, life, extra=None):
        hx, hy = self.muzzle(f)
        k = f.K()
        s = {"k": kind, "x": hx, "y": hy, "owner": f,
             "vx": math.cos(f.aim) * speed * k, "vy": math.sin(f.aim) * speed * k,
             "g": grav * k, "life": life, "trail": [], "spin": 0.0,
             "pierce": f.at_foe}
        if extra:
            s.update(extra)
        self.shots.append(s)

    def release_attack(self, f):
        k = f.K()
        w = f.weapon
        if w == "sword":
            self.slashes.append({"x": f.x + f.face * 34 * f.sc, "y": f.y - 52 * f.sc,
                                 "a": f.aim, "t": 0, "life": .22, "sc": f.sc,
                                 "col": "#FFFFFF"})
            self.melee_hit(f, 120)
            self.shake(.12, 4 * k)
        elif w == "bow":
            self.shoot(f, "arrow", 720, 420, 3)
        elif w == "blaster":
            self.shoot(f, "laser", 900, 0, 1.4)
            self.spark(*self.muzzle(f), 5, LASER, 180, k)
        elif w == "bomb":
            hx, hy = self.muzzle(f)
            self.shots.append({"k": "bomb", "x": hx, "y": hy, "owner": f,
                               "vx": math.cos(f.aim) * 430 * k,
                               "vy": math.sin(f.aim) * 430 * k - 240 * k,
                               "g": 900 * k, "life": 2.2, "trail": [],
                               "spin": 0.0, "pierce": f.at_foe})
        elif w == "rocket":
            # Same disease the minigun had: gravity, not lifetime, was
            # what stopped these. Aimed three degrees down from a muzzle
            # only 39px up, gravity 40 buried them after 353px against a
            # 329px firing distance -- a margin of 1.07, which is none.
            # A rocket is powered; it should not arc.
            self.shoot(f, "rocket", 680, 5, 3.2)
            self.puff(*self.muzzle(f), 6, "#C9D3F0", k, 10)
            self.shake(.14, 5 * k)
        elif w == "lightning":
            hx, hy = self.muzzle(f)
            tx, ty = self.aim_point(f)
            self.bolt(hx, hy, tx, ty)
            self.spark(tx, ty, 14, BOLT, 320, k)
            self.shake(.18, 7 * k)
            self.zap_hit(f, tx, ty)

    def aim_point(self, f):
        # The foe test has to come first. It used to read `f.state == "fight" or
        # (f.foe and ...)`, which short-circuits before the None check and
        # dereferences a missing foe -- unreachable with a fixed pair, live the
        # moment foes are reassigned.
        if f.foe and f.foe.hp > 0 and (f.state == "fight" or f.mode == "fight"):
            return f.foe.x, f.foe.y - 34 * f.foe.sc
        if f.target:
            return f.target["cx"], f.target["cy"]
        return (f.x + math.cos(f.aim) * 400, f.y - 58 * f.sc + math.sin(f.aim) * 400)

    def melee_hit(self, f, reach):
        rk = .4 + .6 * f.K()
        if f.foe and f.foe.hp > 0 and dist(f.x, f.y - 30 * f.sc, f.foe.x,
                                           f.foe.y - 30 * f.foe.sc) < reach * rk:
            self.hit_fighter(f, f.foe, 16 if f.weapon == "sword" else 9)
            return
        if f.target and dist(f.x, f.y - 40 * f.sc, f.target["cx"], f.target["cy"]) < reach * rk:
            self.hit_target(f, f.target, f.target["cx"], f.target["cy"])

    def zap_hit(self, f, tx, ty):
        if f.foe and f.foe.hp > 0 and dist(tx, ty, f.foe.x, f.foe.y - 34 * f.foe.sc) < 70:
            self.hit_fighter(f, f.foe, 22)
        elif f.target and dist(tx, ty, f.target["cx"], f.target["cy"]) < 90:
            self.hit_target(f, f.target, tx, ty)

    def hit_fighter(self, att, vic, dmg):
        if vic.state in ("ko", "grabbed"):
            return
        vic.hp -= dmg
        k = vic.K()
        d = 1 if vic.x >= att.x else -1
        vic.vx = d * (250 + dmg * 9) * k
        vic.vy = -(180 + dmg * 5) * k
        vic.on_ground = False
        vic.anger = clamp(vic.anger + .07 * vic.per["grudge"], 0, 1)
        self.spark(vic.x, vic.y - 34 * vic.sc, 12, "#FFFFFF", 300, k)
        self.shake(.16, 6 * k)
        if vic.hp <= 0:
            vic.hp = 0
            vic.set_state("ko")
            vic.vr = random.uniform(-9, 9)
            # a running score, so a losing streak can mean something later
            bump(att.kind, "wins")
            bump(vic.kind, "losses")
            MEM["who"][att.kind]["streak"] = max(
                1, MEM["who"][att.kind]["streak"] + 1)
            MEM["who"][vic.kind]["streak"] = min(
                -1, MEM["who"][vic.kind]["streak"] - 1)
            vic.yell("ko", 1.6)
            att.anger = .2
            att.set_mood("smug")
            att.yell("victory", 1.8)
        else:
            vic.set_state("thrown")
            if random.random() < .6:
                vic.yell("hurt", 1.1)

    def hit_target(self, f, t, fx, fy):
        self.spark(fx, fy, 10, "#CFD8F5", 260, f.K())
        f.hits += 1
        need = 1 if (t.get("kind") == "icon" and f.snatch) \
            else (4 if t.get("kind") == "window" else 3)
        if f.hits >= need:
            f.hits = 0
            k = f.K()
            self.debris(t["cx"], t["cy"], min(t["w"], 90), min(t["h"], 60), 14, "#8095E8", k)
            self.boom(t["cx"], t["cy"], 44, k)
            f.anger = max(0, f.anger - .35)
            f.boredom = max(0, f.boredom - .45)
            if f.mode == "fight" and f.foe and f.foe.hp > 0:
                return          # wrecked in passing; he has not finished here
            if not self.pick_up_icon(f, t):
                f.set_mood("smug" if random.random() < .6 else "hyped")
                f.target = None
                f.set_state("idle")
                f.goal = self.time + random.uniform(.4, 1.2)

    # ==================================================================
    #  decisions
    # ==================================================================
    def decide(self, f):
        f.goal = self.time + random.uniform(1.4, 3.6) / CFG["chaos"]
        if f.stun > 0:
            return
        f.foe = self.nearest_enemy(f)
        alive = self.terrain.targets()
        rage = f.anger > .55 or f.mood == "furious"
        bored = f.boredom > .6
        r = random.random()

        # pick a fight with the other one
        if f.foe and f.foe.hp > 0 and f.foe.state not in ("ko", "grabbed"):
            # losing repeatedly makes him keener, and he brings it up
            losing = MEM["who"][f.kind]["streak"] <= -2
            p = (.30 if rage else .16) * f.per["aggro"] * (1.6 if losing else 1.0)
            if r < p:
                f.mode = "fight"
                f.snatch = False
                f.plan = plan_weapon(f.per, rage)
                f.set_state("fight")
                f.yell("revenge" if losing else "fight", 1.4)
                return
            # piling onto someone else's icon beats everyone picking his own
            mate = None
            for o in self.fighters:
                if o is not f and o.state == "hunt" and o.target:
                    mate = o
                    break
            if mate and r < p + .10:
                f.target = mate.target
                f.hits = 0
                f.plan = plan_weapon(f.per, rage)
                f.set_state("hunt")
                f.yell("gangup", 1.4)
                return

        if self.time - self.mouse["t"] < 4 and \
                dist(f.x, f.y - 50, self.mouse["x"], self.mouse["y"]) < 340 and \
                random.random() < .35:
            f.target = None
            f.set_state("cursor")
            f.boredom = 0
            f.yell("cursor", 1.4)
            return

        if alive and r < .18:
            t = random.choice(alive)
            self.fire_hook(f, t["cx"], t["top"] - 26)
            f.target = t if random.random() < .7 else None
            f.plan = plan_weapon(f.per, rage)
            return

        if alive and (rage or bored or r < .70):
            # they develop a grudge against one particular icon over time
            fav = favourite_icon()
            t = None
            if fav and not rage and random.random() < .20:
                for a in alive:
                    if a["kind"] == "icon" and a["name"] == fav:
                        t = a
                        break
            if t is None:
                if rage:
                    t = min(alive, key=lambda a: dist(f.x, f.y, a["cx"], a["cy"]))
                else:
                    t = random.choice(alive)
            f.target = t
            f.hits = 0
            f.plan = plan_weapon(f.per, rage)
            f.snatch = (t["kind"] == "icon" and self.can_move_icons()
                        and random.random() < f.per["thief"])
            if f.snatch:
                f.plan = "sword"
            chat = f.per["chatty"]
            if CFG["react_to_windows"] and self.time - f.said > 7 / chat \
                    and random.random() < .5 * chat:
                f.said = self.time
                if t["kind"] == "icon" and fav and t["name"] == fav:
                    f.yell("fav_icon", 1.8, name=fav[:14])
                else:
                    f.say(line_for_icon(f, t["name"]) if t["kind"] == "icon"
                          else line_for_title(f, t["name"]), 1.8)
            far = abs(t["cx"] - f.x) > 460 or t["top"] < f.y - 190
            if far and f.on_ground and random.random() < .6:
                self.fire_hook(f, t["cx"], t["top"] - 26)
                return
            f.set_state("hunt")
            return

        if not alive and r < .45:
            self.fire_hook(f, random.uniform(self.ox + self.W * .1, self.ox + self.W * .9),
                           random.uniform(self.oy + 40, self.ground_at(f.x) - 200))
            f.target = None
            return
        if r < .86:
            f.set_state("taunt")
            return
        # Always somewhere on the screen. A target out past the wrap point can
        # never be reached: he crosses the edge, reappears on the far side, and
        # sets off towards it again for as long as you leave him.
        f.target = None
        f.wander_to = random.uniform(self.ox + 60, self.ox + self.W - 60)
        f.set_state("walk")

    # ==================================================================
    #  per-fighter tick
    # ==================================================================
    def update_fighter(self, f, dt):
        f.st += dt
        f.mood_t += dt
        f.blink -= dt
        if f.blink < -.12:
            f.blink = random.uniform(1.5, 5)
        if f.emote_t > 0:
            f.emote_t -= dt
        if f.stun > 0:
            f.stun -= dt
        f.squash = approach(f.squash, 0, dt * 4.5)
        f.skid = max(0.0, f.skid - dt * 3)
        K = f.K()

        if self.asleep and f.state not in ("sleep", "grabbed", "thrown", "ko"):
            self.drop_icon(f)
            f.set_state("sleep")
            f.set_mood("asleep", quiet=True)
        if not self.asleep and f.state == "sleep":
            f.set_state("idle")
            f.set_mood("bored", quiet=True)
            f.yell("wake", 1.4)

        f.boredom = clamp(f.boredom + dt * .055 * CFG["chaos"], 0, 1)
        f.anger = clamp(f.anger - dt * .09, 0, 1)
        if f.hp < 100 and f.state != "ko":
            f.hp = min(100.0, f.hp + dt * 4.0)

        if f.state != "sleep":
            if f.boredom >= .995 and f.anger < .7:
                f.anger, f.boredom = .9, .85
                f.set_mood("furious")
                f.yell("boredom", 1.8)
                f.goal = 0
            f.mood_check -= dt
            if f.mood_check <= 0:
                f.mood_check = random.uniform(2.6, 5.2)
                if f.anger > .75:
                    f.set_mood("furious")
                elif f.mood == "furious" and f.anger < .35:
                    f.set_mood("sulking")
                elif f.mood == "sulking" and f.mood_t > 6:
                    f.set_mood("bored")
                elif f.boredom > .7:
                    f.set_mood("bored")
                elif f.mood == "smug" and f.mood_t > 5:
                    f.set_mood(random.choice(["hyped", "bored"]))
                elif random.random() < .3:
                    m = random.choice(["furious", "sulking", "hyped", "smug", "bored"])
                    if m == "furious":
                        f.anger = .72
                        f.yell("rage", 1.7)
                    f.set_mood(m)

        s = f.state
        gy = self.ground_at(f.x)

        if s == "sleep":
            f.vx = approach(f.vx, 0, 900 * K * dt)
        elif s == "ko":
            f.tumble += f.vr * dt * (1 if not f.on_ground else 0)
            if f.on_ground:
                f.vr = 0
            if f.st > 3.4:
                f.hp = 100.0
                f.tumble = 0
                f.set_state("idle")
                f.goal = self.time + .6
                f.set_mood("furious")
                f.anger = .8
                f.yell("getup", 1.7)
        elif s == "idle":
            f.vx = approach(f.vx, 0, 900 * K * dt)
            if self.time > f.goal:
                self.decide(f)
        elif s == "walk":
            d = f.wander_to - f.x
            if abs(d) < 12:
                f.set_state("idle")
                f.goal = self.time + random.uniform(.6, 1.8)
            else:
                nf = 1 if d > 0 else -1
                if nf != f.face and abs(f.vx) > 120 * K:
                    f.skid = 1.0
                    self.puff(f.x, f.y, 3, DUST, K, 8)
                f.face = nf
                f.vx = approach(f.vx, f.face * 150 * K * f.per["dash"],
                                1400 * K * dt)
        elif s == "carry":
            self.carry_tick(f, dt)
            d = f.wander_to - f.x
            f.face = 1 if d >= 0 else -1
            if abs(d) < 16 or f.st > 9:
                self.drop_icon(f, (f.x, f.carry_dest_y))
                f.set_mood("smug")
                f.set_state("idle")
                f.goal = self.time + .8
            else:
                f.vx = approach(f.vx, f.face * 175 * K * f.per["dash"],
                                1500 * K * dt)
                if f.on_ground and random.random() < dt * .8 * f.per["hops"]:
                    f.vy = -700 * K
        elif s == "fight":
            foe = f.foe
            if not foe or foe.hp <= 0 or foe.state in ("ko", "grabbed"):
                f.mode = "roam"
                f.set_state("idle")
                f.goal = self.time + .4
            elif f.st > 12:
                f.mode = "roam"
                f.set_state("idle")
            elif f.hp <= f.per["nerve"] * 100:
                # he has had enough. The coward's nerve is high so he leaves
                # early; the zealot's is zero so he never does.
                f.mode = "roam"
                f.target = None
                f.wander_to = clamp(f.x - (foe.x - f.x), self.ox + 60,
                                    self.ox + self.W - 60)
                f.set_state("walk")
                f.yell("hurt", 1.2)
            else:
                d = foe.x - f.x
                f.face = 1 if d >= 0 else -1
                reach = REACH[f.plan] * (.4 + .6 * K)
                if abs(d) > reach - 14:
                    f.vx = approach(f.vx, f.face * 290 * K * f.per["dash"],
                                    1700 * K * dt)
                    if f.on_ground and (foe.y < f.y - 60 or
                                        random.random() < dt * .55 * f.per["hops"]):
                        f.vy = -880 * K
                        f.set_state("jump")
                        f.mode = "fight"
                elif self.time >= f.atk_cd:
                    f.vx = approach(f.vx, 0, 1900 * K * dt)
                    self.start_attack(f, foe=True)
                else:
                    # circle each other between strikes
                    f.vx = approach(f.vx, -f.face * 90 * K, 900 * K * dt)
        elif s == "hunt":
            t = f.target
            if not t:
                f.set_state("idle")
                f.goal = self.time + .4
            elif f.st > 9:
                f.target = None
                f.set_state("idle")
            else:
                reach = REACH[f.plan] * (.4 + .6 * K)
                d = t["cx"] - f.x
                f.face = 1 if d >= 0 else -1
                if f.on_ground and f.st > .3 and (abs(d) > 520 or t["top"] < f.y - 165) \
                        and random.random() < dt * 2.6:
                    self.fire_hook(f, t["cx"], t["top"] - 26)
                elif abs(d) > reach - 20:
                    spd = (300 if f.mood == "furious" else 205) * K * f.per["dash"]
                    f.vx = approach(f.vx, f.face * spd, 1600 * K * dt)
                    if f.on_ground and (random.random() < dt * .7 * f.per["hops"] or
                                        (t["top"] < f.y - 70 and random.random() < dt * 3)):
                        f.vy = -880 * K
                        f.set_state("jump")
                elif self.time >= f.atk_cd:
                    f.vx = approach(f.vx, 0, 1800 * K * dt)
                    self.start_attack(f)
                else:
                    f.vx = approach(f.vx, 0, 1800 * K * dt)
        elif s in ("jump", "fall"):
            if f.on_ground:
                f.set_state("fight" if f.mode == "fight" and f.foe and f.foe.hp > 0
                            else ("hunt" if f.target else "idle"))
        elif s == "ledge":
            f.vx = f.vy = 0
            if f.st > .55:
                f.vy = -760 * K
                f.y -= 4
                f.on_ground = False
                f.ledge_cd = self.time + 1.5   # not the same lip twice running
                f.set_state("jump")
        elif s == "wallslide":
            f.vy = min(f.vy, 150 * K)
            if f.on_ground or f.st > 1.4:
                f.set_state("fall")
        elif s == "attack":
            f.atk += dt
            k = f.atk / f.atk_dur
            if f.weapon == "minigun":
                if .2 < k * f.atk_dur < f.atk_dur - .2:
                    f.burst -= dt
                    if f.burst <= 0:
                        f.burst = .07
                        f.aim = math.atan2(self.aim_point(f)[1] - (f.y - 58 * f.sc),
                                           self.aim_point(f)[0] - f.x) + random.uniform(-.06, .06)
                        # Gravity, not lifetime, was what stopped these. He aims
                        # 3 degrees down at the other one's chest, so at the old
                        # 60 they ploughed into the floor after 498px with a
                        # third of their life left. A minigun round should not
                        # arc like a thrown rock.
                        self.shoot(f, "pellet", 1350, 10, 1.15)
                        self.shake(.05, 1.6 * K)
            elif f.weapon == "chainsaw":
                if .2 < f.atk < f.atk_dur - .1:
                    f.burst -= dt
                    if f.burst <= 0:
                        f.burst = .18
                        self.melee_hit(f, 96)
                        self.spark(f.x + f.face * 30 * f.sc, f.y - 34 * f.sc,
                                   4, "#FFE7A8", 200, K)
            elif not f.fired and k > .55:
                f.fired = True
                self.release_attack(f)
            f.vx = approach(f.vx, 0, 2200 * K * dt)
            if k >= 1:
                f.fired = False
                f.atk_cd = self.time + random.uniform(.24, .62) / CFG["chaos"]
                if f.mode == "fight" and f.foe and f.foe.hp > 0:
                    if random.random() < .35:
                        # Between attacks, never inside one: a new weapon means
                        # a new distance, and the fight state has to be given
                        # the chance to close it before he swings.
                        f.plan = plan_weapon(f.per, f.mood == "furious")
                    f.set_state("fight")
                elif f.target and random.random() < .72:
                    if random.random() < .4:
                        f.plan = plan_weapon(f.per, f.mood == "furious")
                    f.set_state("hunt")
                else:
                    f.set_state("idle")
                    f.goal = self.time + random.uniform(.3, 1.1)
        elif s == "hookfire":
            h = f.hook
            if h:
                h["t"] += dt
                if h["t"] / h["dur"] >= 1:
                    f.zip = {"ax": h["tx"], "ay": h["ty"], "t": 0, "sx": f.x, "sy": f.y,
                             "dur": clamp(dist(f.x, f.y, h["tx"], h["ty"]) /
                                          (620 * (.5 + .5 * K)), .35, 1.6)}
                    f.set_state("zip")
            else:
                f.set_state("idle")
        elif s == "zip":
            z = f.zip
            z["t"] += dt
            k = clamp(z["t"] / z["dur"], 0, 1)
            e = k * k * (3 - 2 * k)
            f.x = lerp(z["sx"], z["ax"], e)
            f.y = lerp(z["sy"], z["ay"] + 34 * f.sc, e) - math.sin(k * math.pi) * 26 * (.5 + .5 * K)
            f.on_ground = False
            if k >= 1:
                f.vy = -260 * K
                f.vx = math.copysign(190 * K, z["ax"] - z["sx"] or 1)
                f.zip = f.hook = None
                f.set_state("fall")
        elif s == "taunt":
            f.vx = approach(f.vx, 0, 1400 * K * dt)
            if f.st > 1.5:
                f.set_state("idle")
                f.goal = self.time + .5
        elif s == "cursor":
            d = self.mouse["x"] - f.x
            f.face = 1 if d >= 0 else -1
            if f.st > 4.5:
                f.set_state("idle")
                f.goal = self.time + .3
            elif abs(d) > 130:
                f.vx = approach(f.vx, f.face * 250 * K * f.per["dash"],
                                1600 * K * dt)
                if f.on_ground and self.mouse["y"] < f.y - 120 * f.sc and \
                        random.random() < dt * 2.2:
                    f.vy = -880 * K
                    f.set_state("jump")
            else:
                f.vx = approach(f.vx, 0, 2000 * K * dt)
                self.start_attack(f, at=(self.mouse["x"], self.mouse["y"]))
        elif s == "grabbed":
            f.x = lerp(f.x, f.gx, 1 - pow(.0008, dt))
            f.y = lerp(f.y, f.gy, 1 - pow(.0008, dt))
            f.vx = f.vy = 0
            f.on_ground = False
        elif s == "thrown":
            f.tumble += f.vr * dt
            if f.on_ground:
                f.vr = f.tumble = 0
                f.stun = .8
                f.set_state("idle")
                f.goal = self.time + 1.0
                f.anger = clamp(f.anger + .3 * f.per["grudge"], 0, 1)
                if f.hp > 0:
                    f.set_mood("furious" if random.random() < .62 else "sulking")

        self.physics(f, dt, gy)

        sp = abs(f.vx)
        f.walk += dt * (sp / (22 * K) + (2 if sp > 8 * K else 0))
        f.look = lerp(f.look, clamp((self.mouse["x"] - f.x) / 320, -1, 1), 1 - pow(.02, dt))

    # ==================================================================
    #  physics
    # ==================================================================
    def physics(self, f, dt, gy):
        K = f.K()
        if f.state in ("zip", "grabbed", "ledge", "sleep"):
            if f.state == "sleep":
                f.vy += 1900 * K * dt
                f.y = min(gy, f.y + f.vy * dt)
                if f.y >= gy:
                    f.y, f.vy, f.on_ground = gy, 0, True
            return

        f.vy += 1900 * K * dt
        prev_y = f.y
        was_air = not f.on_ground
        fall_speed = f.vy
        f.x += f.vx * dt
        f.y += f.vy * dt

        # Off one side and back on the other, keeping height and speed. Two
        # things send him round: getting WRAP past the edge, or simply being out
        # of sight for OUT_MAX. There is no wall to fight beside any more, and
        # no way to hold a duel where you cannot watch it.
        #
        # He lands just INSIDE the far edge, not just outside it. Landing
        # outside lets an idle fighter wrap, sit out of sight, and wrap again,
        # ping-ponging between the two edges without ever being visible.
        off = f.x < self.ox - 12 or f.x > self.ox + self.W + 12
        f.out = f.out + dt if off else 0.0
        past = f.x < self.ox - WRAP or f.x > self.ox + self.W + WRAP
        if past or f.out > OUT_MAX:
            self.puff(f.x, f.y - 20 * f.sc, 4, DUST, K, 10)
            f.x = (self.ox + self.W - 24) if f.x < self.ox else (self.ox + 24)
            f.out = 0.0
            self.puff(f.x, f.y - 20 * f.sc, 4, DUST, K, 10)
        if f.y < self.oy - CEILING:
            f.y, f.vy = self.oy - CEILING, abs(f.vy) * .3

        f.on_ground = False
        f.plat = None
        landed_on = None
        for x0, x1, py, kind, key in self.terrain.platforms:
            if f.x < x0 - 6 or f.x > x1 + 6:
                continue
            if f.vy >= 0 and prev_y <= py + 2 and f.y >= py:
                f.y, f.vy, f.on_ground = py, 0, True
                f.plat = (kind, key)
                landed_on = (x0, x1, py)
                break
        if not f.on_ground and f.vy >= 0 and prev_y <= gy + 2 and f.y >= gy:
            f.y, f.vy, f.on_ground = gy, 0, True
            f.plat = ("floor", None)

        if f.on_ground and was_air:
            if fall_speed > 520 * K:
                f.squash = 1.0
                self.puff(f.x, f.y, 5, DUST, K, 12)
                self.shake(.08, 2.5 * K)
            elif fall_speed > 200 * K:
                f.squash = .5
                self.puff(f.x, f.y, 2, DUST, K, 8)
            if f.state in ("fall", "jump", "wallslide") and f.state != "thrown":
                f.set_state("fight" if f.mode == "fight" and f.foe and f.foe.hp > 0
                            else ("hunt" if f.target else "idle"))
        if not f.on_ground and f.vy < -30 * K:
            f.squash = -.35

        # ledge grab: falling past the lip of something, close enough to catch
        if not f.on_ground and f.vy > 0 and f.state in ("fall", "wallslide") \
                and self.time >= f.ledge_cd:
            for x0, x1, py, kind, key in self.terrain.platforms:
                if py < f.y - 90 * f.sc or py > f.y + 6:
                    continue
                for edge in (x0, x1):
                    if abs(f.x - edge) < 16 and random.random() < .55:
                        f.x = edge + (10 if edge == x0 else -10)
                        f.y = py + 44 * f.sc
                        f.vx = f.vy = 0
                        f.face = 1 if edge == x0 else -1
                        f.set_state("ledge")
                        return

        if not f.on_ground and f.vy > 60 * K and \
                f.state not in ("thrown", "attack", "hookfire", "zip", "ko",
                                "wallslide", "carry"):
            f.set_state("fall")
        if f.on_ground and f.state not in ("walk", "hunt", "fight", "carry"):
            f.vx = approach(f.vx, 0, 2000 * K * dt)

    # ==================================================================
    #  global tick
    # ==================================================================
    def update(self, dt):
        self.time += dt

        was_asleep = self.asleep
        if CFG["sleep_when_idle"]:
            self.asleep = idle_seconds() > CFG["idle_minutes"] * 60
        else:
            self.asleep = False
        if was_asleep and not self.asleep:
            self.awake_since = self.time      # a nap ends the sitting

        if not self.greeted and self.time > 5 and not self.asleep:
            self.greeted = True
            f = random.choice(self.fighters)
            m = MEM["who"][f.kind]
            f.yell(greeting_event(f.kind), 2.6, runs=MEM["runs"],
                   throws=m["thrown"], wins=m["wins"], losses=m["losses"])

        if MEM_DIRTY and self.time - self.mem_saved > 60:
            self.mem_saved = self.time
            save_memory()

        if self.time - self.terrain.last > TERRAIN_HZ:
            self.terrain.last = self.time
            self.terrain.refresh(self.hwnd, want_icons=not self.asleep)
            new = {(t["kind"], t["key"]): t for t in self.terrain.targets()}
            for f in self.fighters:
                # ride a window that got dragged
                if f.plat and f.plat[0] == "window" and f.plat[1] in self.terrain.moved:
                    dx, dy = self.terrain.moved[f.plat[1]]
                    f.x += dx
                    f.y += dy
                if f.target:
                    key = (f.target["kind"], f.target["key"])
                    f.target = new.get(key)
                    if f.target is None and f.state == "hunt":
                        f.set_state("idle")
                        f.goal = self.time + .3

        if CFG["react_to_windows"] and not self.asleep:
            fg = foreground_window()
            if fg and fg[1] != (self.fg[1] if self.fg else None):
                self.fg = fg
                awake = [f for f in self.fighters
                         if f.state in ("idle", "walk", "taunt", "hunt")]
                if awake and fg[0] and random.random() < .55:
                    f = random.choice(awake)
                    if self.time - f.said > 5:
                        f.said = self.time
                        f.say(line_for_title(f, fg[0]), 2.0)
                    if random.random() < .45:
                        for t in self.terrain.targets():
                            if t["kind"] == "window" and t["key"] == fg[1]:
                                f.target = t
                                f.hits = 0
                                f.plan = plan_weapon(f.per)
                                f.set_state("hunt")
                                break
            self.watch.note_focus(fg[1] if fg else None, self.time)
            ev = self.watch.pick(self.time, fg[0] if fg else "",
                                 self.time - self.awake_since)
            if ev:
                # "fight" is circling between swings, which is fine to talk
                # through. Without it, a crowd all brawling at once means the
                # remark never finds a speaker and the feature goes silent.
                free = [f for f in self.fighters
                        if f.state in ("idle", "walk", "taunt", "hunt", "fight")]
                if free:
                    f = random.choice(free)
                    f.said = self.time
                    f.yell(ev, 2.6)
                else:
                    self.watch.unsay(ev)   # try again once someone is free

        for f in self.fighters:
            self.update_fighter(f, dt)
        self.projectiles(dt)
        self.fx_tick(dt)

    def projectiles(self, dt):
        # Rebuilt rather than removed from in place: list.remove() on a dict is a
        # linear scan with a full dict comparison at every step, and a minigun
        # burst plus a bomb can retire a dozen shots in one frame.
        live = []
        bounds = self.terrain.bounds
        for s in self.shots:
            s["life"] -= dt
            s["vy"] += s["g"] * dt
            s["x"] += s["vx"] * dt
            s["y"] += s["vy"] * dt
            k = s["owner"].K()
            if s["k"] in ("laser", "pellet"):
                s["trail"].append((s["x"], s["y"]))
                if len(s["trail"]) > (5 if s["k"] == "laser" else 3):
                    s["trail"].pop(0)
            elif s["k"] == "bomb":
                s["spin"] += dt * 9
            elif s["k"] == "rocket":
                s["spin"] = math.atan2(s["vy"], s["vx"])
                self.puff(s["x"], s["y"], 1, "#C9D3F0", k * .8, 3)

            sx, sy = s["x"], s["y"]
            hit_t = None
            if not s.get("pierce"):
                for cx, cy, hw, hh, t in bounds:
                    if -hw < sx - cx < hw and -hh < sy - cy < hh:
                        hit_t = t
                        break
            hit_f = None
            for f in self.fighters:
                if f is s["owner"] or f.hp <= 0:
                    continue
                if abs(sx - f.x) < 18 * f.sc and f.y - 80 * f.sc < sy < f.y + 8:
                    hit_f = f
                    break

            gy = self.ground_at(sx)
            floor = sy >= gy
            gone = s["life"] <= 0 or not (self.ox - 60 < sx < self.ox + self.W + 60)
            if not (hit_t or hit_f or floor or gone):
                live.append(s)
                continue

            if s["k"] in ("bomb", "rocket"):
                big = s["k"] == "rocket"
                self.boom(sx, min(sy, gy), 70 if big else 56, k, big)
                rad = (150 if big else 110) * (.5 + .5 * k)
                # the blast physically clears icons, which is separate from the
                # hit bookkeeping below and does not need a target to have been
                # aimed at
                self.blast_icons(sx, min(sy, gy), rad * 2.0,
                                 (130 if big else 95) * (.5 + .5 * k))
                rad2 = rad * rad
                for cx, cy, _hw, _hh, t in bounds:
                    if (cx - sx) ** 2 + (cy - sy) ** 2 < rad2:
                        self.hit_target(s["owner"], t, sx, sy)
                        break
                for f in self.fighters:
                    if f is not s["owner"] and f.hp > 0 and \
                            dist(sx, sy, f.x, f.y - 30 * f.sc) < rad:
                        self.hit_fighter(s["owner"], f, 26 if big else 18)
            elif hit_f:
                self.hit_fighter(s["owner"], hit_f,
                                 {"arrow": 10, "laser": 13, "pellet": 4}.get(s["k"], 8))
            elif hit_t:
                self.hit_target(s["owner"], hit_t, sx, sy)
                self.spark(sx, sy, 8,
                           LASER if s["k"] in ("laser", "pellet") else ROPE, 240, k)
                # a bullet knocks one aside rather than clearing the area, and
                # is throttled so a minigun burst cannot flood Explorer
                if hit_t["kind"] == "icon" and self.time - self.shove_at > .2:
                    self.shove_at = self.time
                    self.blast_icons(sx, sy, 76, 30 + 40 * k)
            elif floor:
                self.spark(sx, gy, 5, "#8EA0CC", 150, k)
        self.shots = live

    @staticmethod
    def _age(lst, dt):
        """Advance short-lived fx and drop the expired ones."""
        keep = []
        for o in lst:
            o["t"] += dt
            if o["t"] <= o["life"]:
                keep.append(o)
        return keep

    def fx_tick(self, dt):
        live = []
        for p in self.parts:
            p["t"] += dt
            if p["t"] >= p["life"]:
                continue
            p["vy"] += p["g"] * dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            if p["k"] == "chunk":
                gy = self.ground_at(p["x"])
                if p["y"] > gy:
                    p["y"] = gy
                    p["vy"] *= -.34
                    p["vx"] *= .7
            live.append(p)
        if len(live) > 300:
            del live[:len(live) - 300]
        self.parts = live
        self.slashes = self._age(self.slashes, dt)
        self.booms = self._age(self.booms, dt)
        self.bolts = self._age(self.bolts, dt)
        if self.shake_t > 0:
            self.shake_t -= dt
            if self.shake_t <= 0:
                self.shake_m = 0

    # ==================================================================
    #  drawing
    # ==================================================================
    # ---- item pool -------------------------------------------------------
    def layer(self, tag):
        """Everything drawn from here on belongs to this layer."""
        self._layer = tag

    def _make(self, kind, tag):
        c = self.canvas
        if kind == "line":
            return c.create_line(0, 0, 1, 1, capstyle="round",
                                 joinstyle="round", tags=tag)
        if kind == "oval":
            return c.create_oval(0, 0, 1, 1, tags=tag)
        if kind == "rect":
            return c.create_rectangle(0, 0, 1, 1, tags=tag)
        return c.create_text(0, 0, tags=tag)

    def _item(self, kind):
        """Next free item of this kind in the current layer, made if needed.

        Within one (layer, kind) pool the slots are handed out in call order
        every frame, and they were created in that same order, so their relative
        stacking already matches. Only the layers need raising."""
        tag = self._layer
        pools = self._pool.get(tag)
        if pools is None:
            pools = self._pool[tag] = {}
            self._used[tag] = {}
            self._prev[tag] = {}
        used = self._used[tag]
        i = used.get(kind, 0)
        used[kind] = i + 1
        lst = pools.get(kind)
        if lst is None:
            lst = pools[kind] = []
        if i < len(lst):
            return lst[i]
        item = self._make(kind, tag)
        lst.append(item)
        return item

    def _frame_begin(self):
        for used in self._used.values():
            for kind in used:
                used[kind] = 0

    def _frame_end(self):
        c = self.canvas
        opt = self._opt
        for tag, pools in self._pool.items():
            used = self._used[tag]
            prev = self._prev[tag]
            for kind, lst in pools.items():
                u = used.get(kind, 0)
                p = prev.get(kind, 0)
                for it in lst[u:p]:
                    c.itemconfigure(it, state="hidden")
                    opt[it] = None       # forces a reconfigure when reused
                prev[kind] = u
        for tag in self._layers:
            c.tag_raise(tag)

    def clear_canvas(self):
        self.canvas.delete("all")
        self._pool.clear()
        self._used.clear()
        self._prev.clear()
        self._opt.clear()

    # ---- primitives ------------------------------------------------------
    def line(self, pts, col, w):
        ox, oy = self.ox + self.sx, self.oy + self.sy
        flat = []
        for i in range(0, len(pts) - 1, 2):
            flat += [pts[i] - ox, pts[i + 1] - oy]
        it = self._item("line")
        self.canvas.coords(it, *flat)
        key = (col, w)
        if self._opt.get(it) != key:
            self._opt[it] = key
            self.canvas.itemconfigure(it, fill=col, width=max(1, w),
                                      state="normal")

    def dot(self, x, y, r, col, outline=""):
        x -= self.ox + self.sx
        y -= self.oy + self.sy
        it = self._item("oval")
        self.canvas.coords(it, x - r, y - r, x + r, y + r)
        key = (col, outline, 1)
        if self._opt.get(it) != key:
            self._opt[it] = key
            self.canvas.itemconfigure(it, fill=col, outline=outline, width=1,
                                      state="normal")

    def ring(self, x, y, r, col, w):
        x -= self.ox + self.sx
        y -= self.oy + self.sy
        it = self._item("oval")
        self.canvas.coords(it, x - r, y - r, x + r, y + r)
        key = ("", col, w)
        if self._opt.get(it) != key:
            self._opt[it] = key
            self.canvas.itemconfigure(it, fill="", outline=col, width=w,
                                      state="normal")

    def _rect(self, x0, y0, x1, y1, fill, outline, w):
        """Canvas coordinates, already offset."""
        it = self._item("rect")
        self.canvas.coords(it, x0, y0, x1, y1)
        key = (fill, outline, w)
        if self._opt.get(it) != key:
            self._opt[it] = key
            self.canvas.itemconfigure(it, fill=fill, outline=outline, width=w,
                                      state="normal")

    def box(self, x0, y0, x1, y1, fill, outline="", w=1):
        ox, oy = self.ox + self.sx, self.oy + self.sy
        self._rect(x0 - ox, y0 - oy, x1 - ox, y1 - oy, fill, outline, w)

    def text(self, x, y, txt, col, font):
        it = self._item("text")
        self.canvas.coords(it, x, y)
        key = (txt, col, font)
        if self._opt.get(it) != key:
            self._opt[it] = key
            self.canvas.itemconfigure(it, text=txt, fill=col, font=font,
                                      anchor="w", state="normal")
        return it

    def draw(self):
        self._frame_begin()
        self.sx = self.sy = 0.0
        if self.shake_t > 0:
            m = self.shake_m * (self.shake_t / .4)
            self.sx, self.sy = random.uniform(-m, m), random.uniform(-m, m)

        if DEBUG:
            self.layer("dbg")
            for x0, x1, py, kind, key in self.terrain.platforms:
                self.line((x0, py, x1, py), "#3CE0A0" if kind == "icon" else "#5CA8FF", 2)
            for mon, work in self.mons:
                self.line((work[0], work[3], work[2], work[3]), "#FF5B47", 2)

        self.layer("boom")
        for b in self.booms:
            k = b["t"] / b["life"]
            self.ring(b["x"], b["y"], b["r"] * (.25 + k * 1.15), FIRE,
                      max(1, int(6 * (1 - k)) + 1))
        self.layer("bolt")
        for bo in self.bolts:
            k = bo["t"] / bo["life"]
            self.line(bo["pts"], BOLT if k < .5 else "#7FE7FF", max(1, int(5 * (1 - k)) + 1))

        self.layer("part")
        for p in self.parts:
            a = 1 - p["t"] / p["life"]
            r = p["r"] * (1 if p["k"] == "chunk" else a)
            if r < .6:
                continue
            if p["k"] == "chunk":
                self.box(p["x"] - r, p["y"] - r * .7, p["x"] + r, p["y"] + r * .7, p["col"])
            else:
                self.dot(p["x"], p["y"], r, p["col"])

        # Projectiles stack by part (all shafts, then all tips) rather than by
        # spawn order — only visible where two projectiles overlap, and a layer
        # per shot would cost more in raises than the pool saves.
        for s in self.shots:
            k = s["owner"].K()
            if s["k"] == "arrow":
                a = math.atan2(s["vy"], s["vx"])
                dx, dy = math.cos(a) * 9, math.sin(a) * 9
                self.layer("shot")
                self.line((s["x"] - dx, s["y"] - dy, s["x"] + dx, s["y"] + dy), ROPE, 2)
                self.layer("shotd")
                self.dot(s["x"] + dx, s["y"] + dy, 2.2, STEEL)
            elif s["k"] in ("laser", "pellet"):
                pts = []
                for tx, ty in s["trail"]:
                    pts += [tx, ty]
                pts += [s["x"], s["y"]]
                if len(pts) >= 4:
                    self.layer("shot")
                    self.line(pts, LASER if s["k"] == "laser" else "#FFE7A8",
                              3 if s["k"] == "laser" else 2)
            elif s["k"] == "rocket":
                a = s["spin"]
                dx, dy = math.cos(a) * 9, math.sin(a) * 9
                self.layer("shot")
                self.line((s["x"] - dx, s["y"] - dy, s["x"] + dx, s["y"] + dy),
                          "#D8DEF2", max(3, int(6 * k)))
                self.layer("shotd")
                self.dot(s["x"] - dx, s["y"] - dy, max(2, 3.4 * k), FIRE)
            else:
                self.layer("shotd")
                self.dot(s["x"], s["y"], max(3, 5 * k), BOMBC)
                self.dot(s["x"] + 3, s["y"] - 8, max(1.4, 2 * k), FIRE)

        self.layer("slash")
        for sl in self.slashes:
            k = sl["t"] / sl["life"]
            a = sl["a"] - .9 + k * 1.8
            r = 46 * sl["sc"]
            pts = []
            for i in range(7):
                ang = a - .8 + (1.6 * i / 6)
                pts += [sl["x"] + math.cos(ang) * r, sl["y"] + math.sin(ang) * r]
            self.line(pts, sl["col"], max(1, int(4 * (1 - k)) + 1))

        for i, f in enumerate(self.fighters):
            tr, trd = self._rtag[i]
            if f.hook and f.state == "hookfire":
                k = clamp(f.hook["t"] / f.hook["dur"], 0, 1)
                hx = lerp(f.hook["x"], f.hook["tx"], k)
                hy = lerp(f.hook["y"], f.hook["ty"], k)
                self.layer(tr)
                self.line((f.x + 20 * f.sc * f.face, f.y - 56 * f.sc, hx, hy), ROPE,
                          max(1, int(2.5 * f.K())))
                self.layer(trd)
                self.dot(hx, hy, max(2.5, 5 * f.K()), ROPE)
            if f.zip:
                self.layer(tr)
                self.line((f.x + 3 * f.sc * f.face, f.y - 78 * f.sc,
                           f.zip["ax"], f.zip["ay"]), ROPE, max(1, int(2.5 * f.K())))
                self.layer(trd)
                self.dot(f.zip["ax"], f.zip["ay"], max(2.5, 5 * f.K()), ROPE)

        if self.hover is not None and not self.hover.grabbed:
            col = self.hover.color()
            self.layer("hover")
            for r, w in ((36, 7), (18, 5)):
                self.ring(self.hover.x, self.hover.y - 30 * self.hover.sc, r, col, w)

        for i, f in enumerate(self.fighters):
            self.draw_fighter(f, i)
        for i, f in enumerate(self.fighters):
            self.draw_overlay(f, i)
        self._frame_end()

    # ---- the figure ------------------------------------------------------
    def draw_fighter(self, f, fi):
        tb, th, tf, ta, tw, twd = self._ftag[fi][:6]
        S = f.sc
        st = f.state
        # The gait runs on -walk. The planted foot has to travel backwards while
        # it is on the ground, which is what pushes him along, and the lifted one
        # swings forward; the other way round is a moonwalk. Negating the phase
        # reverses the cycle without disturbing the arm/leg opposition.
        ph = -f.walk
        col = f.color()
        px, py, lean, tilt = 0.0, -30.0, 0.0, 0.0
        fL, fR = (-5.0, 0.0), (6.0, 0.0)
        hL, hR = (-9.0, -38.0), (9.0, -38.0)
        K = f.K()

        if st == "sleep":
            py, lean, tilt = -14, -.30, .55
            fL, fR = (-16, -2), (-4, 2)
            hL, hR = (-20, -18), (-6, -14)
        elif st == "ko":
            py, lean, tilt = -12, -1.35, .2
            fL, fR = (-26, 6), (-18, 12)
            hL, hR = (16, -6), (10, 4)
        elif st == "ledge":
            py, lean = -46, .1
            fL, fR = (-8, -8), (2, 6)
            hL, hR = (8, -84), (14, -80)
        elif st == "wallslide":
            py, lean = -30, -.12
            fL, fR = (2, -6), (8, 4)
            hL, hR = (14, -58), (16, -40)
        elif st == "carry":
            bob = math.sin(ph) * 2
            stride = 12
            fL = (math.cos(ph) * stride, -max(0, math.sin(ph)) * 7)
            fR = (math.cos(ph + math.pi) * stride, -max(0, math.sin(ph + math.pi)) * 7)
            py, lean = -30 - abs(bob) * .4, -.06
            hL, hR = (-6, -74), (7, -76)
        elif st in ("walk", "hunt", "fight"):
            run = abs(f.vx) > 210 * K
            stride = 19 if run else 13
            lift = 13 if run else 8
            fL = (math.cos(ph) * stride, -max(0, math.sin(ph)) * lift)
            fR = (math.cos(ph + math.pi) * stride, -max(0, math.sin(ph + math.pi)) * lift)
            py = -30 - abs(math.sin(ph)) * 1.6
            lean = .30 if run else .10
            hL = (-math.cos(ph) * 13 + 2, -40 + math.sin(ph) * 2)
            hR = (-math.cos(ph + math.pi) * 13 + 2, -40 - math.sin(ph) * 2)
            if f.skid > 0:
                lean = -.34
                fL, fR = (-16, 0), (10, 0)
                hL, hR = (-18, -50), (16, -46)
        elif st in ("jump", "fall"):
            up = f.vy < 0
            py, lean = -32, (.16 if up else -.10)
            fL = (-2, -12 if up else -4)
            fR = (13, -6 if up else 2)
            hL = (-12, -58 if up else -48)
            hR = (14, -56 if up else -50)
        elif st == "zip":
            py, lean = -34, .22
            k = math.sin(self.time * 12)
            fL, fR = (16 + k * 5, -6), (8 - k * 5, 4)
            hL, hR = (-3, -76), (3, -78)
        elif st == "hookfire":
            py, lean = -30, .05
            hR, hL = (20, -56), (-4, -44)
        elif st == "grabbed":
            k = self.time * 16
            py = -28
            lean = math.sin(k * .7) * .25
            fL = (math.sin(k) * 16 - 4, 6 + math.cos(k) * 8)
            fR = (math.sin(k + 2) * 16 + 4, 4 + math.cos(k + 1) * 8)
            hL = (math.sin(k + 1) * 18 - 8, -50 + math.cos(k) * 10)
            hR = (math.sin(k + 3) * 18 + 8, -50 + math.cos(k + 2) * 10)
            tilt = math.sin(k * .9) * .2
        elif st == "thrown":
            py, lean = -30, .1
            fL, fR = (-10, -8), (12, -2)
            hL, hR = (-14, -52), (15, -54)
        elif st == "taunt":
            k = f.st * 7
            py = -30 + math.sin(k) * 2
            lean = .06
            hR = (16, -66 + math.sin(k) * 7)
            hL = (-10, -34)
            tilt = math.sin(k * .5) * .12
        elif st == "attack":
            k = clamp(f.atk / f.atk_dur, 0, 1)
            aimL = math.atan2(math.sin(f.aim), math.cos(f.aim) * f.face)
            py, lean = -30, .12
            fL, fR = (-12, 0), (14, 0)
            w = f.weapon
            if w == "sword":
                sw = lerp(-2.2, -2.6, k / .55) if k < .55 else lerp(-2.6, .9, (k - .55) / .45)
                hR = (math.cos(sw) * 30 + 8, math.sin(sw) * 30 - 48)
                hL = (-14, -44)
                lean = .3 if k > .55 else -.12
            elif w == "chainsaw":
                r = 30 + math.sin(self.time * 26) * 2
                hR = (math.cos(aimL) * r + 6, -44 + math.sin(aimL) * r)
                hL = (math.cos(aimL) * 16 - 6, -40 + math.sin(aimL) * 16)
                lean = .22
            elif w == "bow":
                draw = k / .55 if k < .55 else 0
                hL = (math.cos(aimL) * 33 + 4, -45 + math.sin(aimL) * 33)
                hR = (math.cos(aimL) * (19 - draw * 13) + 4,
                      -45 + math.sin(aimL) * (19 - draw * 13))
            elif w in ("blaster", "lightning"):
                kick = -7 if .55 < k < .7 else 0
                hR = (math.cos(aimL) * (35 + kick) + 4, -44 + math.sin(aimL) * (35 + kick))
                hL = (math.cos(aimL) * 20 - 3, -42 + math.sin(aimL) * 20)
            elif w in ("rocket", "minigun"):
                rec = math.sin(self.time * 40) * (3 if w == "minigun" else 0)
                hR = (math.cos(aimL) * (34 - rec) + 6, -46 + math.sin(aimL) * (34 - rec))
                hL = (math.cos(aimL) * 14 - 8, -36 + math.sin(aimL) * 14)
                lean = .18
            else:  # bomb — the hand arcs up and over, clear of his own head
                if k < .55:
                    u = k / .55
                    hR = (lerp(8, -30, u), lerp(-48, -58, u))
                    lean = lerp(.10, -.16, u)
                else:
                    u = (k - .55) / .45
                    hR = (lerp(-30, 42, u), lerp(-58, -56, u) - 16 * math.sin(math.pi * u))
                    lean = lerp(-.16, .30, u)
                hL = (-14, -42)
        else:  # idle
            br = math.sin(self.time * 2.1) * 1.4
            py = -30 + br * .5
            fL, fR = (-7, 0), (7, 0)
            hL, hR = (-11, -36 + br), (11, -36 - br)
            lean = .02
            if f.mood == "bored":
                lean, tilt = -.08, .18
                hL, hR = (-13, -34), (12, -33)
            elif f.mood == "sulking":
                lean, tilt = -.14, .30
                hL, hR = (-9, -30), (9, -30)
            elif f.mood == "furious":
                py = -29 + math.sin(self.time * 22) * 1.2
                hL, hR = (-15, -46), (15, -46)
            elif f.mood == "smug":
                lean, tilt = .05, -.10
                hL, hR = (-13, -33), (13, -33)

        if f.stun > 0:
            tilt += math.sin(self.time * 30) * .1

        sqx = 1 + f.squash * .22
        sqy = 1 - f.squash * .28
        fx, fy = f.face * S * sqx, S * sqy
        ca, sa = math.cos(f.tumble), math.sin(f.tumble)

        def P(lx, ly):
            X, Y = lx * fx, ly * fy
            return f.x + X * ca - Y * sa, f.y + X * sa + Y * ca

        nx, ny = rot(0, -26, lean)
        neck = (px + nx, py + ny)
        hx2, hy2 = rot(0, -11, lean + tilt)
        head = (neck[0] + hx2, neck[1] + hy2)

        lw = max(2, round(4.6 * S))
        # Bend signs are which side the joint bulges towards, in local space
        # where +x is the way he faces. A knee leads and the shin trails it; an
        # elbow trails and the forearm swings ahead of it. Reversed, the knees
        # bow like a bird's and he reads as running the other way.
        kneeL = ik(px, py, fL[0], fL[1], 16, 16, -1)
        kneeR = ik(px, py, fR[0], fR[1], 16, 16, -1)
        elbL = ik(neck[0], neck[1] - 1, hL[0], hL[1], 13, 13, 1)
        elbR = ik(neck[0], neck[1] - 1, hR[0], hR[1], 13, 13, 1)

        self.layer(tb)
        self.line((*P(px, py), *P(*kneeL), *P(*fL)), col, lw)
        self.line((*P(px, py), *P(*kneeR), *P(*fR)), col, lw)
        self.line((*P(neck[0], neck[1] - 1), *P(*elbL), *P(*hL)), col, lw)
        self.line((*P(px, py), *P(*neck)), col, lw + 1)

        hxp, hyp = P(*head)
        self.layer(th)
        self.dot(hxp, hyp, 11.5 * S, col)
        self.layer(tf)
        self.draw_face(f, hxp, hyp, S, lean + tilt)
        self.layer(ta)
        self.line((*P(neck[0], neck[1] - 1), *P(*elbR), *P(*hR)), col, lw)
        self.draw_weapon(f, P, hR, elbR, hL, tw, twd)

    def draw_face(self, f, cx, cy, e, tilt):
        lookx = f.look * 2.2

        def pt(lx, ly):
            x, y = rot(lx, ly, tilt)
            x, y = rot(x * e * f.face, y * e, f.tumble)
            return cx + x, cy + y

        w = max(1, round(1.9 * e))
        if f.state == "sleep" or f.mood == "asleep":
            self.line((*pt(-5.4, -1.4), *pt(-1.0, -1.4)), INK, w)
            self.line((*pt(1.0, -1.4), *pt(5.4, -1.4)), INK, w)
            self.line((*pt(-3, 5), *pt(3, 5)), INK, w)
            return
        if f.state == "ko":
            for sx in (3.7, -3.3):
                self.line((*pt(sx - 2.4, -4.2), *pt(sx + 2.4, .6)), INK, w)
                self.line((*pt(sx + 2.4, -4.2), *pt(sx - 2.4, .6)), INK, w)
            self.line((*pt(-3.4, 5.2), *pt(3.4, 5.2)), INK, w)
            return

        if f.blink < 0:
            self.line((*pt(.7 + lookx, -1.7), *pt(6.2 + lookx, -1.7)), INK, w)
            self.line((*pt(-6.2 + lookx, -1.7), *pt(-1.7 + lookx, -1.7)), INK, w)
        else:
            eo = 1.4 if f.mood == "furious" else 0
            for ex in (3.7, -3.3):
                self.dot(*pt(ex + lookx, -1.8 + eo), max(1.1, 2.2 * e), INK)

        m = f.mood
        if m == "furious":
            self.line((*pt(-6.5, -6.5), *pt(-1.0, -4.2)), INK, w)
            self.line((*pt(6.5, -6.5), *pt(1.0, -4.2)), INK, w)
            self.line((*pt(-4, 5.4), *pt(0, 2.8), *pt(4, 5.4)), INK, w)
        elif m == "hyped":
            self.line((*pt(-4.2, 1.6), *pt(0, 6.2), *pt(4.2, 1.6)), INK, w)
        elif m == "smug":
            self.line((*pt(-4, 4.4), *pt(.5, 6.4), *pt(4.2, 3.0)), INK, w)
            self.line((*pt(1.0, -6.2), *pt(6.4, -7.4)), INK, w)
        elif m == "sulking":
            self.line((*pt(-3.6, 5.6), *pt(0, 3.4), *pt(3.6, 5.6)), INK, w)
            self.line((*pt(-6.4, -5.6), *pt(-1.6, -6.6)), INK, w)
            self.line((*pt(6.4, -5.6), *pt(1.6, -6.6)), INK, w)
        else:
            self.line((*pt(-3.2, 4.6), *pt(3.2, 4.6)), INK, w)

    def draw_weapon(self, f, P, hR, elbR, hL, tw, twd):
        st, S = f.state, f.sc
        a = math.atan2(hR[1] - elbR[1], hR[0] - elbR[0])

        def rel(lx, ly):
            x, y = rot(lx, ly, a)
            return P(hR[0] + x, hR[1] + y)

        self.layer(tw)
        if st in ("hookfire", "zip"):
            ang = -1.2 if st == "zip" else a
            x1, y1 = rot(-4, 0, ang)
            x2, y2 = rot(14, 0, ang)
            self.line((*P(hR[0] + x1, hR[1] + y1), *P(hR[0] + x2, hR[1] + y2)),
                      GUNMETAL, max(2, round(3.4 * S)))
            return
        if st != "attack":
            return
        w = f.weapon
        if w == "sword":
            self.line((*rel(0, 0), *rel(40, 0)), STEEL, max(2, round(4.2 * S)))
            self.line((*rel(-1, -6), *rel(-1, 6)), "#8FA0CC", max(2, round(4 * S)))
        elif w == "chainsaw":
            self.line((*rel(0, 0), *rel(34, 0)), "#8FA0CC", max(3, round(7 * S)))
            jit = 1.6 if int(self.time * 40) % 2 else -1.6
            for i in range(5):
                self.line((*rel(8 + i * 6, -4 + jit), *rel(11 + i * 6, -7 + jit)),
                          "#FFE7A8", max(1, round(2 * S)))
            self.layer(twd)
            self.dot(*rel(2, 2), max(2, 4 * S), "#E05A3A")
        elif w == "bow":
            aim = math.atan2(hL[1] - hR[1], hL[0] - hR[0])
            pts = []
            for i in range(9):
                ang = aim - 1.9 + (3.8 * i / 8)
                pts += list(P(hL[0] + math.cos(ang) * 20, hL[1] + math.sin(ang) * 20))
            self.line(pts, ROPE, max(2, round(3.2 * S)))
            k = clamp(f.atk / f.atk_dur, 0, 1)
            pull = -(k / .55) * 16 if k < .55 else 0
            bx, by = rot(pull, 0, aim)
            e1x, e1y = math.cos(aim - 1.9) * 20, math.sin(aim - 1.9) * 20
            e2x, e2y = math.cos(aim + 1.9) * 20, math.sin(aim + 1.9) * 20
            self.line((*P(hL[0] + e1x, hL[1] + e1y), *P(hL[0] + bx, hL[1] + by),
                       *P(hL[0] + e2x, hL[1] + e2y)), STEEL, max(1, round(1.6 * S)))
        elif w == "blaster":
            self.line((*rel(-4, 0), *rel(18, 0)), GUNMETAL, max(2, round(8 * S)))
            self.layer(twd)
            self.dot(*rel(20, 0), max(1.5, 3.4 * S), LASER)
        elif w == "lightning":
            self.line((*rel(-4, 0), *rel(20, 0)), "#9FB0D8", max(2, round(6 * S)))
            self.layer(twd)
            self.ring(*rel(24, 0), max(2.5, 5 * S), BOLT, max(1, round(2 * S)))
            self.dot(*rel(24, 0), max(1.2, 2.2 * S), "#FFFFFF")
        elif w == "rocket":
            self.line((*rel(-8, 0), *rel(26, 0)), "#7E8AB4", max(4, round(10 * S)))
            self.line((*rel(26, 0), *rel(30, 0)), "#5C6690",
                      max(4, round(11 * S)))
            self.layer(twd)
            self.dot(*rel(6, -6), max(1.5, 3 * S), "#3A4468")
        elif w == "minigun":
            spin = math.sin(self.time * 40) * 3 * S
            self.line((*rel(-6, 0), *rel(24, 0)), "#7E8AB4", max(3, round(7 * S)))
            self.line((*rel(4, -3), *rel(26, -3)), "#9AA6CC", max(1, round(2.4 * S)))
            self.line((*rel(4, 3), *rel(26, 3)), "#6B769C", max(1, round(2.4 * S)))
            self.layer(twd)
            self.dot(rel(26, 0)[0], rel(26, 0)[1] + spin, max(1.4, 2.6 * S), FIRE)
        else:  # bomb
            self.layer(twd)
            self.dot(*rel(12, 0), max(2.5, 6.2 * S), BOMBC)
            self.dot(*rel(15, -16), max(1.2, 2.2 * S), FIRE)

    # ---- speech, health, cargo ------------------------------------------
    def draw_overlay(self, f, fi):
        to, tob, tot = self._ftag[fi][6:]
        S = f.sc
        self.layer(to)
        if f.carry:
            c = f.carry
            w = min(c["w"], 46) * .8
            h = min(c["h"], 46) * .7
            cx, cy = f.x, f.y - 92 * S
            self.box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, "#5F73C4",
                     "#8095E8", 2)
            self.box(cx - w / 2, cy - h / 2, cx - w / 6, cy - h / 2 + 4, "#8095E8")

        if f.foe and 0 < f.hp < 100 and f.state != "ko":
            w = 30 * S
            y = f.y - 96 * S
            self.box(f.x - w, y, f.x + w, y + 4 * S, "#2A3150")
            self.box(f.x - w, y, f.x - w + 2 * w * (f.hp / 100), y + 4 * S,
                     "#63E0A8" if f.hp > 40 else "#FF5B47")

        if f.emote_t > 0 and f.emote:
            fs = int(clamp(round(9 * S + 4), 9, 18))
            bx = f.x + 16 * S - self.ox - self.sx
            by = f.y - 102 * S - self.oy - self.sy
            col = f.color()
            self.layer(tot)
            t = self.text(bx, by, f.emote, col, ("Segoe UI", fs, "bold"))
            bb = self.canvas.bbox(t)
            if bb:
                # the box layer is raised before the text layer, so it lands behind
                pad = fs * .55
                self.layer(tob)
                self._rect(bb[0] - pad, bb[1] - pad * .7, bb[2] + pad,
                           bb[3] + pad * .7, "#0C1024", col, 2)

    # ==================================================================
    #  loop
    # ==================================================================
    def open_settings(self):
        if self.settings_win is not None:
            try:
                self.settings_win.win.lift()
                return
            except Exception:
                self.settings_win = None
        self.settings_win = SettingsWindow(self.root, self)

    def run(self):
        last = time.perf_counter()

        def tick():
            if not self.running:
                return
            nonlocal last
            now = time.perf_counter()
            dt = min(now - last, .05)
            last = now
            self.tray.pump()
            self.tray.drain()      # menu actions, clear of the Win32 modal loop
            if not self.running:   # Quit is one of them
                return
            try:
                self.poll_cursor(dt)
                if not self.paused:
                    self.update(dt)
                    self.draw()
                elif self._pool:
                    self.clear_canvas()
            except Exception as exc:
                if DEBUG:
                    import traceback
                    traceback.print_exc()
                else:
                    print("frame error:", exc)
            self.root.after(max(8, int(1000 / CFG["fps"])), tick)

        self.root.after(30, tick)
        self.root.mainloop()


TERRAIN_HZ = 1.6


def fatal(msg):
    """Say it in a box. Launched with pythonw there is no console, and a
    crash that prints into the void looks like nothing happened at all."""
    print(msg)
    try:
        user32.MessageBoxW(0, msg, "Desktop Gremlin", 0x10)
    except Exception:
        pass


def main():
    print("=" * 60)
    print(f"  DESKTOP GREMLIN v{VERSION} — overlay edition")
    print("=" * 60)

    start_log()
    MEM["runs"] += 1
    state = backup_layout()
    if state == "saved":
        print("  Saved your desktop icon layout to gremlin_icon_backup.json")
    elif state == "existing":
        print("  Icon layout backup already on file.")
    else:
        print("  Could not read your icon layout (so nothing will be moved).")

    app = App()
    n_i, n_w = len(app.terrain.icons), len(app.terrain.windows)
    print(f"  Found {n_i} desktop icon(s) and {n_w} open window(s).")
    if n_i == 0:
        print("  (Couldn't read your desktop icons — they'll use your open windows")
        print("   and the desktop floor instead. Everything else still works.)")
    if app.icons_locked:
        print("  NOTE: 'Auto arrange icons' is ON, so Windows snaps every icon back.")
        print("        Right-click desktop > View > untick it to let them move things.")
    # Never move an icon we cannot put back.
    if state == "failed" or n_i == 0:
        if CFG["move_icons"]:
            print("  Icon dragging is OFF this run (no layout backup = no undo).")
        CFG["move_icons"] = False
    if not CFG["move_icons"] and n_i and state != "failed":
        print("  Icon dragging is OFF. Tray > Settings > 'Let them actually drag my")
        print("  desktop icons' turns it on. Your layout is backed up either way.")
    print()
    print("  Tray icon (bottom-right) has Settings, Pause, Restore layout, Quit.")
    print("  Grab one: hover until the rings appear, then click and drag.")
    print("  Right-click one to open Settings.")
    print()

    # None of the above is readable when we are started with pythonw, so
    # anything that actually needs attention goes to the tray as well.
    notes = []
    if n_i == 0:
        notes.append("Can't read your desktop icons - using your open "
                     "windows and the floor instead.")
    if app.icons_locked:
        notes.append("'Auto arrange icons' is on, so Windows snaps every "
                     "icon back. Right-click desktop > View > untick it.")
    if state == "failed":
        notes.append("No layout backup saved, so icon dragging stays off.")
    if notes:
        app.tray.notify("Desktop Gremlin", "\n".join(notes))

    app.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        fatal("Desktop Gremlin stopped with an error:\n\n"
              + traceback.format_exc()[-1400:])
        sys.exit(1)
