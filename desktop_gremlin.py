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
import threading
import time
import tkinter as tk
from tkinter import ttk
from gremlin_profiles import (normalize_cast, normalize_profiles, selected_cast,
                              apply_profile, draw_accessory, ProfilesPanel)
from gremlin_paths import runtime_paths, startup_command

IS_WINDOWS = sys.platform.startswith("win")
if IS_WINDOWS:
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
elif sys.platform != "linux":
    raise RuntimeError("Desktop Gremlin supports Windows and Linux X11.")

VERSION = "3.1.0"
DEBUG = "--debug" in sys.argv
HERE, DATA_DIR = runtime_paths(__file__)
SETTINGS_PATH = os.path.join(DATA_DIR, "gremlin_settings.json")
BACKUP_PATH = os.path.join(DATA_DIR, "gremlin_icon_backup.json")
LOG_PATH = os.path.join(DATA_DIR, "gremlin_log.txt")
ICON_PATH = os.path.join(DATA_DIR, "gremlin.ico")


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


def source_id():
    """Which commit is running, read straight out of .git.

    No subprocess (under pythonw there is no console to inherit) and no git
    needed on the machine. Printed at the top of the log, because a fix that
    "didn't work" is usually a fix that was not the code running."""
    try:
        git = os.path.join(HERE, ".git")
        if os.path.isfile(git):
            # a worktree: .git is a one-line pointer to the real directory
            with open(git, encoding="utf-8") as f:
                git = f.read().split("gitdir:", 1)[1].strip()
            git = os.path.normpath(os.path.join(HERE, git))
        common = git
        cd = os.path.join(git, "commondir")
        if os.path.isfile(cd):
            with open(cd, encoding="utf-8") as f:
                common = os.path.normpath(os.path.join(git, f.read().strip()))
        with open(os.path.join(git, "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
        if not head.startswith("ref: "):
            return head[:9]
        ref = head[5:]
        p = os.path.join(common, *ref.split("/"))
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return f.read().strip()[:9]
        with open(os.path.join(common, "packed-refs"), encoding="utf-8") as f:
            for line in f:
                if line.strip().endswith(" " + ref):
                    return line.split()[0][:9]
    except Exception:
        pass
    return "unknown"


def pythonw_path():
    """The console-less interpreter beside the one running us.

    This used to be sys.executable with 'python.exe' swapped for 'pythonw.exe',
    which did nothing for a launcher named anything else -- and the Run key
    then opened a console window at every login."""
    if getattr(sys, "frozen", False):
        return sys.executable
    p = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return p if os.path.exists(p) else sys.executable


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


if IS_WINDOWS:
    make_dpi_aware()

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
    user32.RegisterHotKey.restype = wt.BOOL
    user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wt.BOOL

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


# One overlay per desktop. GetLastError has to be read straight after the
# call, so this goes through its own handle with use_last_error set.
if IS_WINDOWS:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateMutexW.restype = wt.HANDLE
    _k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    _k32.CloseHandle.argtypes = [wt.HANDLE]
ERROR_ALREADY_EXISTS = 183
_INSTANCE = None


def claim_instance(name="Local\\DesktopGremlin.one"):
    """True if we are the only one. The Run key plus a double-click on the
    .bat used to give two overlays and two tray icons, both moving icons and
    both writing the memory file. The handle is kept for the life of the
    process; Windows drops the mutex when we exit, however we exit."""
    global _INSTANCE
    if not IS_WINDOWS:
        return LINUX.claim_instance(DATA_DIR, name)
    try:
        h = _k32.CreateMutexW(None, False, name)
        if not h:
            return True                # cannot tell; let it run
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            _k32.CloseHandle(h)
            return False
        _INSTANCE = h
        return True
    except Exception:
        return True

# ==========================================================================
#  SETTINGS
# ==========================================================================
# The cast, in the order they join. Declared before everything else because
# both the settings clamp below and the memory model are keyed by it — it used
# to live with the character data, which put it AFTER load_settings() ran:
# len(ROSTER) raised NameError inside the validation try, and every saved
# settings file was silently replaced with the defaults on every launch.
ROSTER = ("brawler", "sniper", "coward", "showoff", "grump",
          "magpie", "zealot", "tinkerer", "drama", "veteran")

DEFAULTS = {
    "scale": 0.68,            # 0.68 ~= the height of a desktop icon
    "fps": 40,
    "chaos": 1.0,             # how fast they escalate
    "crowd": 2,               # how many of them, 1 to 10
    "cast": "",
    "profiles": "{}",
    "play_mode": "mischief",
    "group_scenes": True,
    "parkour": True,
    "toy_props": True,
    "renderer": "tk",        # native desktop presentation is quarantined
    "body_theme": "dark",
    "halo_strength": 1.0,
    "outline": False,
    "effects_quality": 1.0,
    "auto_quality": True,
    "move_icons": False,      # let them physically drag your desktop icons (opt-in)
    "move_windows": False,    # let them nudge your windows a few pixels (opt-in)
    "shots_over_icons": True, # stray fire passes over icons instead of into them
    "blood": False,           # cartoon blood and floor stains (opt-in)
    "react_to_windows": True, # comment on real window titles, follow focus
    "sleep_when_idle": True,
    "idle_minutes": 5.0,
    "all_monitors": True,
    "pause_fullscreen": True, # hide while a fullscreen app (a game, a film) is in front
    "start_with_windows": False,
}


def load_settings():
    """Read the settings file if there is one, and never trust it."""
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            got = json.load(f)
    except Exception:
        return s
    if not isinstance(got, dict):
        return s
    bounds = {"scale": (.35, 2.5), "fps": (15, 60), "chaos": (.2, 3.0),
              "idle_minutes": (.5, 120.0), "crowd": (1, len(ROSTER)),
              "halo_strength": (.5, 2.0), "effects_quality": (.25, 1.0)}
    choices = {"renderer": ("tk",), "body_theme": ("dark", "light"),
               "play_mode": ("peaceful", "mischief", "battle")}
    for k, v in got.items():
        if k in ("cast", "profiles"):
            s[k] = (normalize_cast if k == "cast" else normalize_profiles)(v, ROSTER)
            continue
        if k in choices:
            if isinstance(v, str) and v in choices[k]:
                s[k] = v
            continue
        if k not in s or not isinstance(v, (bool, int, float)):
            continue
        try:
            # NaN survives min/max clamps; reject it before it reaches drawing.
            # Validate separately so one bad field cannot discard the others.
            if not math.isfinite(v):
                continue
            if isinstance(DEFAULTS[k], bool):
                s[k] = bool(v)
            elif not isinstance(v, bool):
                lo, hi = bounds[k]
                v = min(max(v, lo), hi)
                s[k] = int(v) if isinstance(DEFAULTS[k], int) else float(v)
        except (ValueError, OverflowError, TypeError):
            continue
    return s


def save_settings(s):
    try:
        atomic_write_json(SETTINGS_PATH, s, indent=2)
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
MEMORY_PATH = os.path.join(DATA_DIR, "gremlin_memory.json")
MEM_KEYS = ("thrown", "grabbed", "wins", "losses", "icons_moved", "streak")
MEM_DIRTY = False


def blank_memory():
    # Counters live under "who" rather than as top-level names beside version /
    # runs / icons, so the set of characters can be enumerated without an
    # exclusion list.
    return {"version": 3, "runs": 0, "icons": {}, "relationships": {},
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
    relationships = got.get("relationships", {})
    if isinstance(relationships, dict):
        for key, value in relationships.items():
            pair = key.split("|") if isinstance(key, str) else []
            if len(pair) == 2 and pair[0] != pair[1] and all(p in ROSTER for p in pair) \
                    and isinstance(value, (int, float)) and not isinstance(value, bool) \
                    and (isinstance(value, int) or math.isfinite(value)):
                m["relationships"]["|".join(sorted(pair))] = min(100, max(-100, value))
    return m


MEM = load_memory()


def mark_memory_dirty():
    global MEM_DIRTY
    MEM_DIRTY = True


def bump(kind, key, n=1):
    """Nudge a counter. The write itself is throttled by the frame loop."""
    global MEM_DIRTY
    MEM["who"][kind][key] = MEM["who"][kind].get(key, 0) + n
    MEM_DIRTY = True


def count_run():
    """The one write main() makes itself. It has to mark the memory dirty:
    a bare MEM["runs"] += 1 never reached disk on a run where nothing else
    dirtied it, so a user who only ever watched stayed on day one forever."""
    global MEM_DIRTY
    MEM["runs"] += 1
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
        return True
    try:
        atomic_write_json(MEMORY_PATH, MEM, indent=1)
        MEM_DIRTY = False
        return True
    except Exception as exc:
        print("could not save memory:", exc)
        return False


def forget_memory():
    """Wipe what they know about you. Back to strangers."""
    global MEM, MEM_DIRTY
    MEM = blank_memory()
    MEM_DIRTY = True
    return save_memory()


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
            cmd = startup_command(os.path.join(HERE, os.path.basename(__file__)), pythonw_path())
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
LVM_FINDITEMW = LVM_FIRST + 83
LVM_REDRAWITEMS = LVM_FIRST + 21
LVIR_ICON = 1
LVFI_STRING = 0x0002
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


class LVFINDINFOW(ctypes.Structure):
    _fields_ = [("flags", wt.UINT), ("psz", ctypes.c_void_p),
                ("lParam", wt.LPARAM), ("pt", wt.POINT), ("vkDirection", wt.UINT)]


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


def _locked(fn):
    """Serialise one shell round trip. The scanner thread reads icon rects
    through the same remote buffer the frame thread writes positions with, and
    a write landing between another call's write and its read would hand
    Explorer the wrong struct. Per call, not per scan: a carry in progress
    waits for one message, never for four hundred."""
    def wrapped(self, *a, **k):
        with self._lock:
            return fn(self, *a, **k)
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


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
        self._lock = threading.RLock()
        self._restoring = False # a restore's writes do not dirty the backup
        self.restore_complete = False  # set only after every applicable icon is verified

    @_locked
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

    @_locked
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
        size = ctypes.sizeof(obj)
        ok = kernel32.WriteProcessMemory(self.proc, self.remote + off,
                                         ctypes.byref(obj), size, ctypes.byref(n))
        return bool(ok) and n.value == size

    def _read(self, obj, off=0):
        n = ctypes.c_size_t(0)
        size = ctypes.sizeof(obj)
        ok = kernel32.ReadProcessMemory(self.proc, self.remote + off,
                                        ctypes.byref(obj), size, ctypes.byref(n))
        return bool(ok) and n.value == size

    @_locked
    def count(self):
        return send_msg(self.lv, LVM_GETITEMCOUNT, 0, 0)

    @_locked
    def item_rect(self, i):
        """Icon glyph rect in SCREEN pixels."""
        r = wt.RECT(LVIR_ICON, 0, 0, 0)
        if not self._write(r) or not send_msg(self.lv, LVM_GETITEMRECT, i, self.remote):
            return None
        if not self._read(r):
            return None
        if r.right <= r.left or r.bottom <= r.top:
            return None
        try:
            l, t = win32gui.ClientToScreen(self.lv, (r.left, r.top))
            rr, b = win32gui.ClientToScreen(self.lv, (r.right, r.bottom))
        except Exception:
            return None
        return (l, t, rr, b)

    @_locked
    def item_pos(self, i):
        """Position in LIST coordinates, or None when the shell cannot read it."""
        p = wt.POINT(0, 0)
        if not self._write(p) or not send_msg(self.lv, LVM_GETITEMPOSITION, i, self.remote):
            return None
        if not self._read(p):
            return None
        return (p.x, p.y)

    @_locked
    def set_item_pos(self, i, x, y):
        global BACKUP_OK
        if not self._restoring:
            # A launch snapshot cannot undo icons added or renamed afterward.
            # Require one unambiguous saved/current label before protecting a move.
            data = _read_backup()
            if data is None:
                BACKUP_OK = False
                return False
            name = self.item_text(i)
            if not name or sum(row[0] == name for row in data["icons"]) != 1 \
                    or not self.unique_item(i, name):
                return False
            # Persist recovery protection BEFORE Explorer can change the desktop.
            if not mark_layout_dirty():
                return False
        p = wt.POINT(int(x), int(y))
        if not self._write(p):
            return False
        return send_msg(self.lv, LVM_SETITEMPOSITION32, i, self.remote) is not None

    @_locked
    def unique_item(self, i, name):
        """Check current identity with two bounded lookups, not a full icon scan."""
        off = ctypes.sizeof(LVFINDINFOW) + 16
        text = ctypes.create_unicode_buffer(name)
        if off + ctypes.sizeof(text) > 4096:
            return False
        info = LVFINDINFOW()
        info.flags, info.psz = LVFI_STRING, self.remote + off
        if not self._write(text, off) or not self._write(info):
            return False
        # LVFI_STRING is exact (case-insensitive), without prefix matching/wrap.
        # Starting at -1 includes item zero; starting at i excludes i itself.
        first = send_msg(self.lv, LVM_FINDITEMW, -1, self.remote)
        if type(first) is not int or first != i:
            return False
        duplicate = send_msg(self.lv, LVM_FINDITEMW, i, self.remote)
        # send_msg stores DWORD_PTR, so native -1 can arrive unsigned.
        return type(duplicate) is int and duplicate in (-1, ctypes.c_size_t(-1).value)

    @_locked
    def item_text(self, i):
        try:
            off = ctypes.sizeof(LVITEMW) + 16
            it = LVITEMW()
            ctypes.memset(ctypes.byref(it), 0, ctypes.sizeof(it))
            it.iItem = i
            it.iSubItem = 0
            it.pszText = self.remote + off
            it.cchTextMax = 260
            if not self._write(it):
                return ""
            length = send_msg(self.lv, LVM_GETITEMTEXTW, i, self.remote)
            if length is None or length <= 0 or length >= it.cchTextMax - 1:
                return ""                 # empty or truncated labels cannot identify a backup
            buf = ctypes.create_unicode_buffer(260)
            return buf.value if self._read(buf, off) else ""
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
        count = self.count()
        if count is None:
            return []
        n = min(count, 400)
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
        count = self.count()
        if count is None:
            return []
        out = []
        for i in range(count):
            name = self.item_text(i)
            pos = self.item_pos(i)
            if not name or pos is None or self.item_text(i) != name:
                return []
            out.append([name, pos[0], pos[1]])
        if self.count() != count:
            return []                    # an add/delete during the scan invalidates the snapshot
        return out

    def restore(self, snap):
        self.restore_complete = False
        if not _valid_snapshot(snap) or not self.open():
            return 0
        count = self.count()
        if count is None:
            return 0
        by_name = {}
        for name, x, y in snap:
            by_name.setdefault(name, []).append((x, y))
        done = 0
        complete = True
        pending = []
        self._restoring = True
        try:
            for i in range(count):
                nm = self.item_text(i)
                if not nm:
                    complete = False     # a failed label read may hide an unrestored icon
                    continue
                if nm in by_name and by_name[nm]:
                    x, y = by_name[nm].pop(0)
                    if self.set_item_pos(i, x, y):
                        pending.append((i, nm, x, y))
                    else:
                        complete = False
        finally:
            self._restoring = False
        # A later move can auto-arrange earlier icons again. Verify the final
        # layout after ALL writes, rather than accepting intermediate positions.
        for i, nm, x, y in pending:
            if self.item_text(i) == nm and self.item_pos(i) == (x, y):
                done += 1
            else:
                complete = False
        self.restore_complete = complete and self.count() == count
        try:
            send_msg(self.lv, LVM_REDRAWITEMS, 0, max(0, count - 1))
            win32gui.InvalidateRect(self.lv, None, True)
        except Exception:
            pass
        return done


SHELL = ShellView()

# No backup on disk means no undo, so nothing may be dragged. Set by
# backup_layout(); read by App.can_move_icons() and the settings window.
BACKUP_OK = False
# Icons this run has moved and not put back. Mirrored into the backup file,
# so the next launch knows not to photograph the mess.
LAYOUT_DIRTY = False
BACKUP_KEEP = 3          # older launch snapshots kept in the file, for hand recovery


def _valid_snapshot(icons):
    """Only complete, identifiable, representable icon positions are recoverable."""
    return (isinstance(icons, list) and bool(icons)
            and all(isinstance(row, (list, tuple)) and len(row) == 3
                    and isinstance(row[0], str) and bool(row[0])
                    and all(isinstance(v, int) and not isinstance(v, bool)
                            and -(2 ** 31) <= v < 2 ** 31 for v in row[1:])
                    for row in icons))


def atomic_write_json(path, data, indent=1):
    """Replace a JSON file only after its new contents are written and flushed."""
    import tempfile
    # Serialization failure must leave even the temporary file untouched.
    text = json.dumps(data, indent=indent, allow_nan=False)
    parent = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".",
                                     suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _read_backup():
    try:
        with open(BACKUP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if (isinstance(data, dict) and _valid_snapshot(data.get("icons"))
                and isinstance(data.get("dirty", False), bool)):
            return data
    except Exception:
        pass
    return None


def _write_backup(data):
    atomic_write_json(BACKUP_PATH, data)


def backup_layout():
    """Snapshot the icon layout at launch, so Restore puts the desktop back the
    way it was when THIS run started.

    It used to be written once, ever, and Restore then returned a desktop you
    had rearranged yourself in the months since. The one time the old
    snapshot is kept is when the last run moved icons and never put them back
    (a crash, or a quit with the desktop still scattered): that copy is the
    only good one, so it stands until Restore has been used. The first layout
    ever seen stays in the file as "first", the last few launches as
    "previous" -- neither is on a menu; they are there to be recovered by hand.

    Returns "saved" (fresh snapshot), "kept" (last run left icons moved),
    "existing" (the shell would not answer but an older file stands) or
    "failed" (no undo at all, so nothing may be moved)."""
    global BACKUP_OK, LAYOUT_DIRTY
    BACKUP_OK = False
    old = _read_backup()
    if old and old.get("dirty"):
        BACKUP_OK = True
        LAYOUT_DIRTY = True
        return "kept"
    try:
        snap = SHELL.snapshot()
    except Exception as exc:
        print("layout snapshot failed:", exc)
        snap = []
    if not _valid_snapshot(snap):
        if old:
            BACKUP_OK = True
            return "existing"
        return "failed"
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    if old:
        first = old.get("first")
        if not isinstance(first, dict) or not _valid_snapshot(first.get("icons")):
            first = {"saved": old.get("saved", ""), "icons": old["icons"]}
        history = old.get("previous", [])
        previous = [p for p in history if isinstance(p, dict)
                    and _valid_snapshot(p.get("icons"))] if isinstance(history, list) else []
        if old["icons"] != snap:
            previous.insert(0, {"saved": old.get("saved", ""), "icons": old["icons"]})
        del previous[BACKUP_KEEP:]
    else:
        first = {"saved": stamp, "icons": snap}
        previous = []
    try:
        _write_backup({"saved": stamp, "icons": snap, "dirty": False,
                       "first": first, "previous": previous})
    except Exception as exc:
        print("layout backup failed:", exc)
        if old:
            BACKUP_OK = True
            return "existing"
        return "failed"
    BACKUP_OK = True
    LAYOUT_DIRTY = False
    return "saved"


def mark_layout_dirty():
    """Persist protection before the first move; False forbids that move."""
    global LAYOUT_DIRTY, BACKUP_OK
    if LAYOUT_DIRTY:
        return BACKUP_OK
    data = _read_backup()
    if not data:
        BACKUP_OK = False
        return False
    if not data.get("dirty"):
        data["dirty"] = True
        try:
            _write_backup(data)
        except Exception as exc:
            print("could not flag the layout backup:", exc)
            return False                 # remain clean in RAM, so a later attempt retries
    LAYOUT_DIRTY = True
    BACKUP_OK = True
    return True


def restore_layout():
    global LAYOUT_DIRTY
    data = _read_backup()
    if not data or not mark_layout_dirty():
        return 0
    try:
        n = SHELL.restore(data["icons"])
    except Exception as exc:
        print("layout restore failed:", exc)
        return 0
    if getattr(SHELL, "restore_complete", False):
        data["dirty"] = False
        try:
            _write_backup(data)
        except Exception as exc:
            print("could not clear the layout flag:", exc)
        else:
            LAYOUT_DIRTY = False          # both verified layout and recovery flag are durable
    return n


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


def window_rect(hwnd):
    """The rect Windows positions a window BY, which on Win10/11 is a few
    pixels bigger than the frame you can see (frame_bounds). Nudges move by a
    delta, so the two never have to agree."""
    try:
        return win32gui.GetWindowRect(hwnd)
    except Exception:
        return None


def place_window(hwnd, x, y):
    """Move a top-level window: no resize, no raise, no activation."""
    try:
        win32gui.SetWindowPos(hwnd, 0, int(x), int(y), 0, 0,
                              win32con.SWP_NOSIZE | win32con.SWP_NOZORDER
                              | win32con.SWP_NOACTIVATE)
        return True
    except Exception:
        return False


def window_alive(hwnd):
    try:
        return bool(win32gui.IsWindow(hwnd))
    except Exception:
        return False


def tracked_window_rect(hwnd):
    """A lightweight read of one occupied window; never sends it a message."""
    try:
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd) \
                or win32gui.IsIconic(hwnd) or is_cloaked(hwnd):
            return None
        return frame_bounds(hwnd)
    except Exception:
        return None


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


def mouse_button_down():
    """Logical primary-button state; unavailable reads cannot invent a release."""
    try:
        key = (win32con.VK_RBUTTON if user32.GetSystemMetrics(win32con.SM_SWAPBUTTON)
               else win32con.VK_LBUTTON)
        return bool(user32.GetAsyncKeyState(key) & 0x8000)
    except Exception:
        return None


def foreground_window():
    try:
        h = win32gui.GetForegroundWindow()
        if not h:
            return None
        return (win32gui.GetWindowText(h), h)
    except Exception:
        return None


def fullscreen_app(own_hwnd=0):
    """Is a fullscreen application in front -- a game, a film, a slideshow?

    Judged from the foreground window's visible frame covering its whole
    monitor, taskbar included. Not from SHQueryUserNotificationState: our own
    overlay is a fullscreen window, and the shell reports BUSY the moment it
    appears, which would have paused us against ourselves. We are never the
    foreground window (WS_EX_NOACTIVATE), so this cannot see us. A maximised
    window stops at the work area and does not count."""
    try:
        h = win32gui.GetForegroundWindow()
        if not h or h == own_hwnd:
            return False
        if win32gui.GetClassName(h) in ("Progman", "WorkerW", "Shell_TrayWnd",
                                        "Shell_SecondaryTrayWnd"):
            return False
        l, t, r, b = frame_bounds(h)
        mon = win32api.MonitorFromWindow(h, win32con.MONITOR_DEFAULTTONEAREST)
        ml, mt, mr, mb = win32api.GetMonitorInfo(mon)["Monitor"]
        return l <= ml + 2 and t <= mt + 2 and r >= mr - 2 and b >= mb - 2
    except Exception:
        return False


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", wt.DWORD), ("BatteryFullLifeTime", wt.DWORD)]


def on_battery():
    """True on battery power. Unknown (255) counts as mains."""
    try:
        s = SYSTEM_POWER_STATUS()
        if not kernel32.GetSystemPowerStatus(ctypes.byref(s)):
            return False
        return s.ACLineStatus == 0
    except Exception:
        return False


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
    WM_TRAY = 0x400 + 20
    ID_BASE = 1500
    HOTKEY_QUIT = 0x4752

    def __init__(self, tip="Desktop Gremlin"):
        self.items = []              # (label, callback, kind) kind: cmd|check|sep
        self.pending = []            # menu actions waiting for the Tk loop
        self.hwnd = 0
        self.hicon = 0
        self.added = False
        self.tip = tip
        self.quit_callback = None
        self.emergency_registered = False

    def build(self):
        taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
        msgs = {
            win32con.WM_COMMAND: self._on_command,
            self.WM_TRAY: self._on_tray,
            win32con.WM_DESTROY: self._on_destroy,
            win32con.WM_HOTKEY: self._on_hotkey,
            taskbar_created: self._on_taskbar_created,
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
            self.emergency_registered = bool(user32.RegisterHotKey(
                self.hwnd, self.HOTKEY_QUIT,
                win32con.MOD_CONTROL | win32con.MOD_ALT | win32con.MOD_SHIFT | 0x4000,
                ord("Q")))
        except Exception:
            self.emergency_registered = False
        if not self.emergency_registered:
            print("Emergency exit shortcut could not be registered.")

        try:
            ico = _write_ico(ICON_PATH)
            self.hicon = win32gui.LoadImage(0, ico, win32con.IMAGE_ICON, 16, 16,
                                            win32con.LR_LOADFROMFILE)
        except Exception:
            self.hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        return self._add_icon()

    def _add_icon(self):
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
        try:
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_ADD,
                (self.hwnd, 0, flags, self.WM_TRAY, self.hicon, self.tip))
            self.added = True
        except Exception as exc:
            print("tray icon unavailable:", exc)
        return self.added

    def _on_taskbar_created(self, hwnd, msg, wparam, lparam):
        # Explorer has discarded its icons; keep our window and menu callbacks.
        self.added = False
        self._add_icon()
        return True

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

    def _on_hotkey(self, hwnd, msg, wparam, lparam):
        # A global shortcut works without clicking the overlay or tray. Keep
        # destruction out of this Win32 callback, like ordinary tray actions.
        if wparam == self.HOTKEY_QUIT and self.quit_callback is not None:
            if self.quit_callback not in self.pending:
                self.pending.insert(0, self.quit_callback)
        return True

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
        if self.emergency_registered:
            try:
                user32.UnregisterHotKey(self.hwnd, self.HOTKEY_QUIT)
            except Exception:
                pass
            self.emergency_registered = False
        if self.added:
            try:
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))
            except Exception:
                pass
            self.added = False


# ==========================================================================
#  SETTINGS WINDOW
# ==========================================================================
if not IS_WINDOWS:
    import gremlin_linux as LINUX
    SHELL = LINUX.NullShell()
    Tray = LINUX.LinuxControls
    def find_desktop_listview(): return None
    def read_windows(own_hwnd): return LINUX.desktop().read_windows(own_hwnd)
    def frame_bounds(hwnd): return LINUX.desktop().window_rect(hwnd)
    def window_rect(hwnd): return LINUX.desktop().window_rect(hwnd)
    def tracked_window_rect(hwnd): return LINUX.desktop().tracked_window_rect(hwnd)
    def window_alive(hwnd): return LINUX.desktop().window_alive(hwnd)
    def place_window(hwnd, x, y): return LINUX.desktop().place_window(hwnd, x, y)
    def confirm_window_position(hwnd, x, y): return LINUX.desktop().confirm_position(hwnd, x, y)
    def foreground_window(): return LINUX.desktop().foreground_window()
    def fullscreen_app(own_hwnd): return LINUX.desktop().fullscreen_app(own_hwnd)
    def idle_seconds(): return LINUX.desktop().idle_seconds()
    def on_battery(): return LINUX.desktop().on_battery()
    def monitors(): return LINUX.desktop().monitors()
    def virtual_screen(): return LINUX.desktop().virtual_screen()
    def mouse_button_down():
        sample = LINUX.desktop().mouse()
        return bool(sample and sample[2])
    def set_run_at_startup(on): return LINUX.set_run_at_startup(on, __file__)


class SettingsWindow:
    def __init__(self, master, app):
        self.app = app
        self.win = tk.Toplevel(master)
        self.win.title("Desktop Gremlin — settings")
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        self.win.configure(bg="#171B2C")
        self.vars = {}
        tabs = ttk.Notebook(self.win)
        tabs.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        page = None
        pad = {"padx": 14, "pady": 4}
        row = 0

        def header(txt):
            nonlocal row, page
            page = tk.Frame(tabs, bg="#171B2C")
            tabs.add(page, text=txt)
            row = 0
            tk.Label(page, text=txt, bg="#171B2C", fg="#8FA0CC",
                     font=("Segoe UI", 9, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 2))
            row += 1

        def slider(key, label, lo, hi, res):
            nonlocal row
            v = tk.DoubleVar(value=float(CFG[key]))
            self.vars[key] = v
            tk.Label(page, text=label, bg="#171B2C", fg="#E6ECFF",
                     font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", **pad)
            tk.Scale(page, from_=lo, to=hi, resolution=res, orient="horizontal",
                     variable=v, bg="#171B2C", fg="#E6ECFF", troughcolor="#0E1120",
                     highlightthickness=0, length=190, bd=0).grid(
                row=row, column=1, sticky="e", **pad)
            row += 1

        def check(key, label):
            nonlocal row
            v = tk.BooleanVar(value=bool(CFG[key]))
            self.vars[key] = v
            cb = tk.Checkbutton(page, text=label, variable=v, bg="#171B2C",
                                fg="#E6ECFF", selectcolor="#0E1120",
                                activebackground="#171B2C",
                                activeforeground="#FFFFFF", font=("Segoe UI", 9),
                                highlightthickness=0, bd=0)
            cb.grid(row=row, column=0, columnspan=2, sticky="w", padx=12, pady=2)
            row += 1
            return cb

        def choice(key, label, values):
            nonlocal row
            v = tk.StringVar(value=CFG[key])
            self.vars[key] = v
            tk.Label(page, text=label, bg="#171B2C", fg="#E6ECFF",
                     font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", **pad)
            ttk.Combobox(page, textvariable=v, values=values, state="readonly",
                         width=24).grid(row=row, column=1, sticky="e", **pad)
            row += 1

        header("Look")
        slider("scale", "Size  (0.68 = icon height)", 0.35, 2.5, 0.01)
        choice("body_theme", "Body colour", ("dark", "light"))
        slider("halo_strength", "Mood halo strength", .5, 2.0, .1)
        check("outline", "Contrast outlines around arms, legs and body")
        check("blood", "Blood and gore  (cartoon red, stains wash off)")

        header("Performance")
        choice("renderer", "Renderer", ("tk",))
        slider("fps", "Frames per second", 15, 60, 1)
        slider("effects_quality", "Decorative effects detail", .25, 1.0, .05)
        check("auto_quality", "Reduce decorative effects when frames run late")
        tk.Button(page, text="Open live performance", command=app.open_performance,
                  bg="#2A3150", fg="#C9D3F0", relief="flat").grid(
            row=row, column=0, columnspan=2, sticky="we", padx=14, pady=14)

        header("Behaviour")
        slider("chaos", "Chaos level", 0.2, 3.0, 0.1)
        slider("crowd", "How many of them", 1, 10, 1)
        choice("play_mode", "Play mode", ("peaceful", "mischief", "battle"))
        check("group_scenes", "Friendships and group scenes")
        check("parkour", "Parkour, swings and paper planes")
        check("toy_props", "Build temporary playground toys")
        check("react_to_windows", "React to my windows and follow focus")
        check("sleep_when_idle", "Sleep when I'm away")
        slider("idle_minutes", "Minutes before sleeping", 0.5, 120, 0.5)

        header("Cast")
        self.vars["cast"] = tk.StringVar(value=CFG["cast"])
        self.vars["profiles"] = tk.StringVar(value=CFG["profiles"])
        cast_frame = ttk.Frame(page)
        cast_frame.grid(row=row, column=0, columnspan=2, padx=14, pady=8)
        self.profiles_panel = ProfilesPanel(cast_frame, self.vars, ROSTER, WEAPONS)

        header("Your desktop")
        drag = check("move_icons", "Let them actually drag my desktop icons")
        if not IS_WINDOWS:
            self.vars["move_icons"].set(False)
            drag.config(state="disabled", text="Desktop icon dragging is unavailable on Linux")
        elif not BACKUP_OK:
            # Nothing to put the icons back with, so the switch stays off.
            self.vars["move_icons"].set(False)
            drag.config(state="disabled", disabledforeground="#6C7BB0",
                        text="Drag my desktop icons  (no layout backup — off)")
        check("shots_over_icons", "Stray shots fly over my icons  (aimed fire still hits)")
        check("move_windows", "Let them nudge my windows  (use Put my windows back to undo)")
        check("all_monitors", "Use all monitors")
        check("pause_fullscreen", "Hide while a fullscreen app is in front  (games, films)")
        check("start_with_windows", "Start with Windows" if IS_WINDOWS else "Start when I sign in")

        tk.Button(page, text="Restore my icon layout", command=self.restore,
                  state="normal" if IS_WINDOWS else "disabled",
                  bg="#2A3150", fg="#FFD35C", activebackground="#39426B",
                  relief="flat", font=("Segoe UI", 9), bd=0).grid(
            row=row, column=0, columnspan=2, sticky="we", padx=14, pady=(14, 4))
        row += 1
        tk.Button(page, text="Make them forget everything about me",
                  command=self.forget, bg="#2A3150", fg="#C9D3F0",
                  activebackground="#39426B", relief="flat",
                  font=("Segoe UI", 9), bd=0).grid(
            row=row, column=0, columnspan=2, sticky="we", padx=14, pady=(0, 4))
        row += 1

        bar = tk.Frame(self.win, bg="#171B2C")
        bar.pack(fill="x", padx=10, pady=12)
        tk.Button(bar, text="Apply", command=self.apply, bg="#3A7D5C", fg="#FFFFFF",
                  activebackground="#4A9A72", relief="flat", width=12,
                  font=("Segoe UI", 9, "bold"), bd=0).pack(side="right", padx=4)
        tk.Button(bar, text="Close", command=self.close, bg="#2A3150", fg="#C9D3F0",
                  activebackground="#39426B", relief="flat", width=10,
                  font=("Segoe UI", 9), bd=0).pack(side="right", padx=4)

        self.status = tk.Label(self.win, text="", bg="#171B2C", fg="#63E0A8",
                               font=("Segoe UI", 8))
        self.status.pack(pady=(0, 10))
        registered = getattr(getattr(app, "tray", None), "emergency_registered", False)
        tk.Label(self.win, text=("Keyboard exit: Ctrl+Alt+Shift+Q" if registered else
                                 "Keyboard exit shortcut unavailable; details are in the log."),
                 bg="#171B2C", fg="#8FA0CC", font=("Segoe UI", 8)).pack(pady=(0, 10))
        self.win.protocol("WM_DELETE_WINDOW", self.close)

    def restore(self):
        self.app.cancel_icon_moves()
        n = restore_layout()
        self.status.config(
            text=(f"Put {n} icon(s) back. Restore is incomplete; backup kept."
                  if n and LAYOUT_DIRTY else
                  (f"Put {n} icon(s) back." if n else "No icons restored; check the saved layout.")),
            fg="#63E0A8" if n and not LAYOUT_DIRTY else "#FF5B47")

    def forget(self):
        social = getattr(self.app, "social", None)
        if social is not None:
            social.clear()
        if forget_memory():
            self.status.config(text="Forgotten. You're strangers again.", fg="#63E0A8")
        else:
            self.status.config(text="Could not erase saved memory. Please try again.",
                               fg="#FF5B47")

    def apply(self):
        if hasattr(self, "profiles_panel"):
            self.profiles_panel.flush()
        for k, v in self.vars.items():
            val = v.get()
            CFG[k] = str(val) if isinstance(DEFAULTS[k], str) else (
                bool(val) if isinstance(DEFAULTS[k], bool) else (
                int(val) if isinstance(DEFAULTS[k], int) and not isinstance(DEFAULTS[k], bool)
                else float(val)))
        CFG["cast"] = normalize_cast(CFG["cast"], ROSTER)
        CFG["profiles"] = normalize_profiles(CFG["profiles"], ROSTER)
        failures = []
        if not save_settings(CFG):
            failures.append("settings could not be saved")
        if not set_run_at_startup(CFG["start_with_windows"]):
            failures.append("Windows startup could not be updated")
        self.app.apply_settings()
        self.status.config(
            text=("Applied for this session; " + "; ".join(failures) + "."
                  if failures else "Applied."),
            fg="#FF5B47" if failures else "#63E0A8")

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
BODY = "#0A0A0C"          # the figures themselves; the halo carries the mood
# The face sits ON the black head, so it has to be light -- it used to be a
# near-black ink on a coloured head, which is why you could barely read it.
# Every mood already draws a different face; this is what makes that visible.
FACE = "#E8EDFF"
ROPE = "#E9D9A9"
LASER = "#7FE7FF"
FIRE = "#FFB259"
STEEL = "#E6ECFF"
GUNMETAL = "#C9D3F0"
BOMBC = "#20263F"
DUST = "#B9C4E0"
BOLT = "#BFE6FF"
BLOODC = ("#B0202B", "#8E1620", "#C4303A")   # spray shades; stains use the dark one

# ==========================================================================
#  terrain
# ==========================================================================
class Scanner:
    """Reads the desktop on its own thread, so a busy Explorer stalls the scan
    and never the frame. Every LVM_* round trip already has a timeout, but a
    busy Explorer can take the full 250 ms on each one, and even a quick one
    is 16 ms for 400 icons -- more than half a frame, every 1.6 s, on the
    thread that paints. One request in flight at a time; a request made while
    one is running simply replaces it."""

    def __init__(self):
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._req = None
        self._result = None
        self._thread = None
        self._closed = False

    def request(self, own_hwnd, want_icons):
        if self._closed:
            return
        self._req = (own_hwnd, want_icons)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="gremlin-scan",
                                            daemon=True)
            self._thread.start()
        self._wake.set()

    def take(self):
        """The last finished scan, once; None when nothing new has landed."""
        with self._lock:
            r, self._result = self._result, None
        return r

    def _run(self):
        while True:
            self._wake.wait()
            self._wake.clear()
            if self._closed:
                return
            own_hwnd, want_icons = self._req
            # Shell IPC can be slow. Only publishing the completed result shares
            # the frame thread's lock, so take() never waits for the scan itself.
            result = scan_desktop(own_hwnd, want_icons)
            with self._lock:
                if not self._closed:
                    self._result = result

    def close(self):
        self._closed = True
        self._wake.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=.3)


def scan_desktop(own_hwnd, want_icons):
    """(icons or None, windows): one look at the desktop, on whichever thread."""
    icons = None
    if want_icons:
        try:
            icons = SHELL.read_icons()
        except Exception:
            icons = []
    try:
        windows = read_windows(own_hwnd)
    except Exception:
        windows = []
    return icons, windows


class Terrain:
    def __init__(self):
        self.icons = []       # (name, l, t, r, b, index)
        self.windows = []     # (title, l, t, r, b, hwnd)
        self.platforms = []   # (x0, x1, y, kind, key)
        self._targets = []
        self.bounds = []      # (cx, cy, half_w, half_h, target) for hit tests
        self.win_pos = {}     # hwnd -> (l, t) last seen, for riding
        self.win_rect = {}    # hwnd -> (l, t, r, b): all four edges, for playing on
        self.moved = {}       # hwnd -> (dx, dy) since last refresh
        self.last = 0.0
        self.icons_ok = False
        self.threaded = False # off until App has its first, synchronous look
        self.scanner = Scanner()
        self.fast_tracking = True
        self._tracked = {}     # occupied hwnd -> (last visible rect, read time)

    def refresh(self, own_hwnd=0, want_icons=True):
        """Look at the desktop again. Synchronous until `threaded` is set --
        startup wants its answer now, and so do the checks. After that it only
        asks the scanner, and the answer lands through poll() a frame or two
        later; the frame loop calls both."""
        if self.threaded:
            self.scanner.request(own_hwnd, want_icons)
            return
        self.apply(*scan_desktop(own_hwnd, want_icons))

    def poll(self):
        """Take in a finished background scan. True if one landed."""
        r = self.scanner.take()
        if r is None:
            return False
        icons, windows = r
        # A slow full scan can predate a recent drag. Overlay our newer occupied
        # window samples before applying it, so attached fighters never jump back.
        if self.fast_tracking and self._tracked:
            windows = self._tracked_windows(windows)
        self.apply(icons, windows)
        return True

    def _tracked_windows(self, windows):
        merged = []
        seen = set()
        for title, l, t, r, b, hwnd in windows:
            seen.add(hwnd)
            sample = self._tracked.get(hwnd)
            rect = sample[0] if sample is not None else (l, t, r, b)
            if rect is not None:
                merged.append((title, *rect, hwnd))
        for title, l, t, r, b, hwnd in self.windows:
            if hwnd not in seen and hwnd in self._tracked:
                rect = self._tracked[hwnd][0]
                if rect is not None:
                    merged.append((title, *rect, hwnd))
        return merged

    def track_windows(self, occupied, now, read_rect=None):
        """Refresh only windows carrying fighters, at most 30 reads/s each."""
        if not self.fast_tracking:
            return False
        occupied = set(occupied)
        for hwnd in list(self._tracked):
            if hwnd not in occupied:
                del self._tracked[hwnd]
        read_rect = read_rect or tracked_window_rect
        changed = False
        for hwnd in occupied:
            previous = self._tracked.get(hwnd)
            if previous is not None and now - previous[1] < 1 / 30.0 - 1e-9:
                continue
            rect = read_rect(hwnd)
            self._tracked[hwnd] = (rect, now)
            if rect != self.win_rect.get(hwnd) or (rect is not None
                    and rect[:2] != self.win_pos.get(hwnd)):
                changed = True
        if changed:
            self.apply(None, self._tracked_windows(self.windows))
        return changed

    def apply(self, icons, windows):
        prev = dict(self.win_pos)
        if icons is not None:
            self.icons = icons
            self.icons_ok = bool(icons)
        self.windows = windows

        self.win_pos = {}
        self.win_rect = {}
        self.moved = {}
        for title, l, t, r, b, hwnd in self.windows:
            self.win_pos[hwnd] = (l, t)
            self.win_rect[hwnd] = (l, t, r, b)
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
WEAPONS = ["sword", "bow", "blaster", "bomb", "rocket", "minigun", "chainsaw",
           "lightning", "fish", "pan", "confetti", "balloon", "harpoon",
           "magnet", "blackhole", "anvil", "piano", "peel", "spring",
           "boomerang", "bubble", "freeze", "swap", "glove", "rubber", "foam"]
ATKDUR = {"sword": .42, "bow": .85, "blaster": .75, "bomb": .60,
          "rocket": .90, "minigun": 1.40, "chainsaw": 1.20, "lightning": .80,
          "fish": .48, "pan": .40, "confetti": .55, "balloon": .60,
          "harpoon": .70, "magnet": .65, "blackhole": .60, "anvil": .75,
          "piano": .75, "peel": .55, "spring": .60, "boomerang": .70,
          "bubble": .80, "freeze": .80, "swap": .90, "glove": .95,
          "rubber": .70, "foam": .80}
# How far into the swing the round leaves, as a fraction of ATKDUR. Guns fire
# just past the halfway kick. The thrown things arc the hand up and over from
# behind the head, and leave when it is out in FRONT -- at .55 they left from
# behind the ear.
RELEASE_AT = {"bomb": .80, "balloon": .80, "blackhole": .80, "peel": .80,
              "spring": .80}
# How far off he opens fire. A round has to comfortably outrun the number here
# or it dies in the air, and the minigun needs the widest margin of the lot
# because it streams for 1.4s while both of them keep moving. Measured before
# this changed: pellets flew 357px against a 241px firing distance, a margin of
# 1.48 where the blaster had 1.84. The droppers (anvil, piano) deliver from the
# sky, so their number is only how close he bothers to walk.
REACH = {"sword": 40, "bow": 480, "blaster": 420, "bomb": 230,
         "rocket": 520, "minigun": 430, "chainsaw": 34, "lightning": 560,
         "fish": 44, "pan": 38, "confetti": 150, "balloon": 210,
         "harpoon": 380, "magnet": 300, "blackhole": 240, "anvil": 260,
         "piano": 300, "peel": 120, "spring": 120, "boomerang": 300,
         "bubble": 350, "freeze": 380, "swap": 420, "glove": 300,
         "rubber": 400, "foam": 280}
MELEE = ("sword", "chainsaw", "fish", "pan")
MELEE_DMG = {"sword": 16, "chainsaw": 9, "fish": 12, "pan": 13}
# How far each weapon reaches past the hand along the forearm, in the same
# local units draw_weapon uses -- the round leaves the END of the weapon, and
# these mirror the furthest rel() point draw_weapon puts on the canvas for it.
# The thrown things leave from where they are drawn in the hand. The bow is
# not here: the arrow leaves the bow in the front hand (see muzzle).
MUZZLE_TIP = {"blaster": 20, "lightning": 24, "minigun": 26, "rocket": 30,
              "harpoon": 34, "magnet": 14, "confetti": 24, "blackhole": 12,
              "bomb": 12, "balloon": 12, "peel": 10, "spring": 10,
              "boomerang": 22, "bubble": 26, "freeze": 26, "swap": 26,
              "glove": 26, "rubber": 26, "foam": 26}
# The four families beyond plain guns, so the code can ask what a weapon IS
# instead of listing names at every site.
PULLERS = ("harpoon", "magnet")           # hits drag the victim closer
DROPPERS = ("anvil", "piano")             # delivered from the sky, straight down
TRAPS = ("peel", "spring")                # placed on the ground, sprung later
SOFT = ("confetti", "balloon")            # ammunition is a mood, barely a wound
FUSED_PROJECTILES = ("bomb", "blackhole")
# These can travel above the desktop and arc back into view. Straight shots
# that exit the top are spent; keeping their tiny gravity would retain them
# invisibly for minutes before they returned.
ARC_PROJECTILES = ("arrow", "bomb", "blackhole", "wballoon",
                   "anvil", "piano", "peel", "spring")

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
                 "weapons": ("chainsaw", "glove", "harpoon", "sword", "fish", "rocket")},
    "sniper":   {"aggro": 0.70, "chatty": 0.60, "grudge": 0.75, "dash": 0.85,
                 "hops": 0.60, "thief": .30, "nerve": .35,
                 "weapons": ("blaster", "freeze", "lightning", "bow", "minigun", "harpoon")},
    "coward":   {"aggro": 0.35, "chatty": 1.40, "grudge": 0.60, "dash": 1.30,
                 "hops": 1.40, "thief": .55, "nerve": .70,
                 "weapons": ("bubble", "peel", "bow", "balloon", "spring", "blaster")},
    "showoff":  {"aggro": 1.20, "chatty": 1.60, "grudge": 0.90, "dash": 1.05,
                 "hops": 1.35, "thief": .40, "nerve": .20,
                 "weapons": ("boomerang", "confetti", "rocket", "lightning", "piano", "minigun")},
    "grump":    {"aggro": 0.85, "chatty": 0.45, "grudge": 1.30, "dash": 0.70,
                 "hops": 0.45, "thief": .35, "nerve": .15,
                 "weapons": ("anvil", "foam", "sword", "chainsaw", "pan", "bomb")},
    "magpie":   {"aggro": 0.30, "chatty": 1.10, "grudge": 0.55, "dash": 1.25,
                 "hops": 1.30, "thief": .95, "nerve": .50,
                 "weapons": ("swap", "magnet", "bomb", "peel", "blaster", "bow")},
    "zealot":   {"aggro": 1.75, "chatty": 1.25, "grudge": 1.60, "dash": 1.15,
                 "hops": 0.90, "thief": .20, "nerve": .00,
                 "weapons": ("chainsaw", "glove", "blackhole", "rocket", "lightning", "anvil")},
    "tinkerer": {"aggro": 0.80, "chatty": 0.75, "grudge": 0.85, "dash": 0.80,
                 "hops": 0.70, "thief": .60, "nerve": .30,
                 "weapons": ("rubber", "swap", "spring", "magnet", "bomb", "blackhole", "rocket")},
    "drama":    {"aggro": 0.95, "chatty": 1.75, "grudge": 1.45, "dash": 1.00,
                 "hops": 1.20, "thief": .45, "nerve": .55,
                 "weapons": ("bubble", "fish", "lightning", "piano", "sword", "balloon")},
    "veteran":  {"aggro": 1.05, "chatty": 0.35, "grudge": 0.70, "dash": 0.95,
                 "hops": 0.75, "thief": .30, "nerve": .25,
                 "weapons": ("boomerang", "pan", "sword", "blaster", "bow", "minigun")},
}

# Every line any of them can say. {name} is an icon he has just made off with;
# {runs} {throws} {wins} {losses} are his own counters, always all supplied.
VOICES = {
    "brawler": {
        "bored":    ["...", "nothing to hit", "hm", "quiet. too quiet."],
        "perch":    ["best seat in the house", "I can see EVERYTHING from up here",
                     "king of the window"],
        "hang":     ["look, no feet", "ONE hand. watch this", "arms of steel"],
        "knock":    ["OPEN UP", "anybody in there?", "I know you're in there"],
        "scramble": ["I wasn't touching it", "NOPE", "you'll never take me"],
        "shove":    ["budge up", "MOVE", "that's better"],
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
        "flee":     ["tactical retreat", "I'll be BACK", "this isn't OVER"],
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
        "perch":    ["good vantage", "overwatch", "clear sightlines up here"],
        "hang":     ["holding position", "grip is fine", "no movement below"],
        "knock":    ["knock knock. no joke.", "occupied?", "checking the perimeter"],
        "scramble": ["compromised", "relocating", "spotted"],
        "shove":    ["adjusting", "two inches left", "better angle"],
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
        "flee":     ["relocating", "this position is burnt", "smoke out"],
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
        "perch":    ["it's safer up here", "nobody can reach me", "I'll just sit here quietly"],
        "hang":     ["don't let go don't let go", "this was a bad idea", "how do I get down"],
        "knock":    ["um, hello?", "sorry to bother you", "is anyone home? sorry"],
        "scramble": ["sorry sorry sorry", "I'll go", "wasn't me"],
        "shove":    ["oops", "sorry about the window", "it slipped"],
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
        "flee":     ["NOPE", "nope nope nope", "LEGS, DO YOUR THING"],
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
        "perch":    ["throne acquired", "admire me", "I look great up here"],
        "hang":     ["no hands! ok, hands", "ta-daaa", "watch the swing"],
        "knock":    ["autograph? no? fine", "let me IN, fans", "your window needs me"],
        "scramble": ["you saw NOTHING", "exit, stage left", "graceful, wasn't it"],
        "shove":    ["a little to the left", "there. art.", "feng shui"],
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
        "flee":     ["INTERMISSION", "exit, stage left", "hold my applause"],
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
        "perch":    ["my back", "cold up here", "someone dust this"],
        "hang":     ["arms hurt", "why am I doing this", "not built for this"],
        "knock":    ["shut it properly", "answer the door", "this window sticks"],
        "scramble": ["fine. FINE.", "I was leaving anyway", "don't touch me"],
        "shove":    ["it was crooked", "there. happy?", "better. still ugly"],
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
        "flee":     ["not worth it", "have it your way then", "I'm going home"],
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
        "perch":    ["ooh, high up", "I can see the icons from here", "mine. this too."],
        "hang":     ["upside down icons", "is there anything under here", "dangle time"],
        "knock":    ["what's inside?", "hello? treasures?", "let me see in"],
        "scramble": ["not stealing! probably", "bye bye", "can't catch me"],
        "shove":    ["scoot", "over you go", "more room for shiny"],
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
        "flee":     ["grab and go", "me and the pile are LEAVING",
                     "keep the fight, I've got stuff"],
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
        "perch":    ["I watch from on high", "the summit is mine", "behold"],
        "hang":     ["pain is fuel", "I do not tire", "grip of the righteous"],
        "knock":    ["open, in the name of chaos", "REPENT", "come out and face me"],
        "scramble": ["a strategic withdrawal", "you cannot scare the faithful",
                     "I retreat to strike again"],
        "shove":    ["it moved. good.", "make way", "the wall yields"],
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
        # nerve 0: he never actually says these. The bank still has to be
        # complete -- a missing key is a KeyError the day his nerve changes.
        "flee":     ["a tactical pilgrimage", "the faith regroups",
                     "this is not retreat, it is prophecy"],
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
        "perch":    ["structural check: fine", "load test passed", "good view of the wiring"],
        "hang":     ["testing the tensile strength", "hinge seems sound", "grip: nominal"],
        "knock":    ["hollow. interesting", "inspecting the frame", "tap tap. measurement."],
        "scramble": ["abort test", "recording the result", "unscheduled dismount"],
        "shove":    ["recalibrated", "there. level.", "adjusted by a quarter"],
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
        "flee":     ["withdrawing for repairs", "back to the bench",
                     "aborting the field test"],
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
        "perch":    ["I sit ABOVE it all", "a balcony scene", "gaze up at me"],
        "hang":     ["I'm SLIPPING", "hanging by a THREAD", "goodbye cruel desktop"],
        "knock":    ["LET ME IN", "I am LOCKED OUT", "abandoned on the doorstep"],
        "scramble": ["I've been SEEN", "flee! FLEE!", "the shame of it"],
        "shove":    ["it MOVED", "did you see that", "my strength is BOUNDLESS"],
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
        "flee":     ["I FLEE", "away, AWAY", "exit, pursued by a bear"],
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
        "perch":    ["nice spot", "high ground", "quiet up here"],
        "hang":     ["still got it", "one pull-up", "decent grip"],
        "knock":    ["anyone in", "hello", "checking"],
        "scramble": ["moving", "noted", "out"],
        "shove":    ["nudge", "that'll do", "shifted"],
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
        "flee":     ["falling back", "not today", "hm. no."],
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

# A voice you can see. Only where the family itself says something -- the
# tinkerer speaks in the monospace of his own labels, the drama in the italics
# of a playbill. Everyone else shares the default, because ten novelty fonts
# would read as a ransom note.
SPEECH_FONT = {"tinkerer": ("Consolas", "bold"),
               "drama": ("Segoe UI", "bold italic")}

# How each of them gets around when nobody is fighting. Not a TRAITS axis:
# temperament numbers feed arithmetic, this is a menu. surf needs move_icons
# and rides a real icon; shoulders needs a willing colleague standing about;
# the grump rides nothing, which is the most in-character line in the table.
RIDES = {
    "brawler":  ("cannon", "pogo"),
    "sniper":   ("float",),
    "coward":   ("pogo", "float", "shoulders"),
    "showoff":  ("skate", "cannon", "shoulders", "jet"),
    "grump":    (),
    "magpie":   ("surf", "shoulders"),
    "zealot":   ("cannon", "jet"),
    "tinkerer": ("skate", "float", "jet"),
    "drama":    ("float", "cannon"),
    "veteran":  ("skate", "pogo"),
}
# the rides that go SOMEWHERE -- these can inherit a walk's destination;
# the rest (float, surf, shoulders) go where they please. The cannon counts:
# it is a ballistic commute, and keeping it leisure-only made it nearly
# extinct once travel became how rides mostly start.
TRAVEL_RIDES = ("pogo", "skate", "jet", "cannon")

# What each of them does with one of your windows, tried in this order until
# one fits the window's shape. perch = sit on the title bar, legs over the
# front; hang = from the bottom edge, swinging; cling = a side edge, peeking
# round it; knock = bang on it and lean on it. The grump only ever leans.
PLAYS = {
    "brawler":  ("knock", "perch"),
    "sniper":   ("perch", "cling"),
    "coward":   ("hang", "cling", "perch"),
    "showoff":  ("perch", "hang", "knock"),
    "grump":    ("knock",),
    "magpie":   ("cling", "hang", "perch"),
    "zealot":   ("knock", "cling"),
    "tinkerer": ("perch", "knock", "hang"),
    "drama":    ("perch", "hang", "knock"),
    "veteran":  ("perch", "cling"),
}
PLAY_STATES = ("perch", "hang", "cling", "knock")
# how long each play lasts, seconds; the knock is paced by its own phases
PLAY_TIME = {"perch": (8.0, 22.0), "hang": (5.0, 14.0), "cling": (5.0, 12.0),
             "knock": (30.0, 30.0)}
# The states a fighter may pass through on the way to a window and keep his
# plan. Anything else -- grabbed, thrown, a fight, sleep -- lets go of it.
KEEP_PLAY = ("walk", "hunt", "jump", "fall", "ledge", "climb", "hookfire",
             "zip") + PLAY_STATES
NUDGE_PER_MINUTE = 6
CONFETTI_COLS = ("#FF8AD8", "#6FD8FF", "#FFD35C", "#A8E86A", "#B79BFF")
WATER = "#7FBBFF"
WOOD = "#C89A66"


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
        self.shot_pierce = False   # this shot flies over the desktop
        self.shot_tgt = None       # ...except this (kind, key), which it may hit
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
        self.mount = None          # the colleague he is riding, in "ride"
        self.ridden_by = None      # ...and the back-reference on the mount
        self.chute = False         # parachute open mid-fall
        self.surf_idx = None       # (idx, offx, offy, w, h) of the icon under him
        self.surf_t = 0.0          # throttle for surf writes, like carry_t
        self.stunt = False         # this flight was his own idea (cannon)
        self.jet_y = y             # cruise height while on the jetpack
        self.climb_top = 0.0       # the platform top a climb is heading for
        self.climb_bot = 0.0       # ...and where its wall ends, for the grips
        self.climb_x = 0.0         # the edge being scaled
        self.climb_side = 1        # +1 = left edge, moving right onto the top
        self.play = None           # what he is doing with a window, and which
        self.window_shy = None     # the window he last scrambled off...
        self.window_cd = 0.0       # ...and until when he leaves it alone
        self.route = []            # short sequence of (kind, key) stepping stones
        self.route_goal = None
        self.route_from = None
        self.route_geometry = ()
        self.route_since = 0.0
        self.route_best = float("inf")
        self.route_retry = 0.0
        self.route_failed = {}     # failed (from, to) edge -> retry time, RAM only
        self.pose_last = self.pose_from = None
        self.pose_last_state = self.pose_to = self.state
        self.pose_time = self.pose_started = 0.0
        self.hit_at = -1000.0
        self.hit_power = 0.0
        self.hit_side = 1

    # -- helpers ----------------------------------------------------------
    def become(self, kind):
        """Colour, voice and temperament all follow from which one he is."""
        self.kind = kind
        self.pal = PALETTES[kind]
        self.per = TRAITS[kind]
        # A stable per-character phase for sway and bobbing. Not id(): that
        # varies run to run, and one non-deterministic input unseeds every
        # simulation the checks run.
        self.seedp = sum(map(ord, kind)) % 7

    def line(self, event, **fmt):
        txt = random.choice(VOICES[self.kind][event])
        return txt.format(**fmt) if fmt else txt

    def say(self, txt, dur=1.5):
        self.emote, self.emote_t = txt, dur

    def yell(self, event, dur=1.5, **fmt):
        """Say something this particular one would say."""
        self.say(self.line(event, **fmt), dur)

    def chat(self, event, dur=1.5, **fmt):
        """A remark rather than a report -- hook whoops, getting back up,
        announcing a fight. Those the quiet ones keep to themselves, which is
        most of what separates the veteran from the drama once a brawl starts.
        Reactions to being grabbed, thrown or beaten stay on yell(): silence
        there reads as the app missing the event. The roll happens HERE,
        before yell, so anything counting yells is counting actual speech."""
        if random.random() < min(1.0, .30 + .42 * self.per["chatty"]):
            self.yell(event, dur, **fmt)

    def set_state(self, s):
        if s != self.state:
            # Carry the displayed upper-body pose into the next state. Feet
            # and actual grips are resolved by the new state's contact rules.
            self.pose_from = self.pose_last if self.pose_last_state == self.state else None
            self.pose_started, self.pose_to = self.pose_time, s
        if self.play is not None and s not in KEEP_PLAY:
            # grabbed, thrown, a fight, sleep: he lets go of the window plan
            # here, the one place every state change passes through
            self.play = None
        if s not in ("hookfire", "zip"):
            # ...and of the grapple line. Only the zip's own end used to clear
            # it, so a hit or a grab mid-swing left the rope drawn on him
            # while he ran and jumped about.
            self.hook = self.zip = None
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
        """His mood, as a colour. The halo round his head, the speech bubble
        and the grab rings; no longer the body."""
        return self.pal.get(self.mood, "#F2F5FF")

    def body(self):
        """Body contrast is a preference; identity and mood stay in the halo."""
        return "#F3F5FB" if CFG.get("body_theme", "dark") == "light" else BODY

    def face_color(self):
        return "#171923" if CFG.get("body_theme", "dark") == "light" else FACE

    def K(self):
        return self.sc / 1.75

    def head_y(self):
        return self.y - 66 * self.sc


def plan_weapon(per, rage=False):
    """A profile's loadout is a boundary, including an intentionally empty one."""
    allowed = per.get("weapons", ())
    if not allowed:
        return "sword"  # inert plan; combat_allowed prevents a disarmed attack
    return random.choice(allowed[:3] if rage else allowed)

# ==========================================================================
#  THE APP
# ==========================================================================
class App:
    def __init__(self):
        if not IS_WINDOWS:
            LINUX.start()  # XInitThreads and session validation precede Tk.
            CFG["move_icons"] = False
        self.root = tk.Tk()
        self.x11_overlay = None
        if not IS_WINDOWS:
            self.root.withdraw()  # Never map an unshaped desktop-sized window.
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        (self.ox, self.oy, self.W, self.H), self.mons = self.screen_box()

        self.root.geometry(f"{self.W}x{self.H}+{self.ox}+{self.oy}")
        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.root.update_idletasks()
        if IS_WINDOWS:
            self.root.attributes("-transparentcolor", KEY)

        if IS_WINDOWS:
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

        else:
            self.hwnd = self.root.winfo_id()
            from gremlin_x11_overlay import X11Overlay
            self.x11_overlay = X11Overlay(self.root, self.canvas, self.quit)

        self.tk_canvas = self.canvas
        self.renderer_mode = "tk"
        self.renderer_error = ""
        self.configure_renderer()
        from gremlin_performance import PerformanceMonitor
        self.performance = PerformanceMonitor()
        self.performance_win = None
        self.performance_after = None
        # Decorative randomness must never consume the AI's random sequence.
        self.fx_random = random.Random()

        self.terrain = Terrain()
        self.terrain.refresh(self.hwnd)       # the one synchronous look
        self.terrain.threaded = True

        self.time = 0.0
        self.paused = False
        self.held = False         # hidden behind a fullscreen app; not the user's pause
        self.on_battery = False
        self.env_at = -9.0        # when check_environment last ran (loop clock)
        self.running = True
        self.settings_win = None
        self.parts, self.shots, self.slashes, self.booms, self.bolts = [], [], [], [], []
        self.traps = []           # placed peels and springboards, ground props
        self.stains = []          # where the blood setting leaves its mark
        self.shake_t = self.shake_m = 0.0
        self.sx = self.sy = 0.0
        self.mouse = {"x": -9999, "y": -9999, "t": -99, "vx": 0, "vy": 0}
        self.hover = None
        self.fg = None
        self.asleep = False
        self.icons_locked = False
        self.watch = Watcher()
        self.shove_at = -9.0      # last time a bullet nudged an icon
        self.nudged = {}          # hwnd -> where the window was before its first nudge
        self.nudged_at = {}       # hwnd -> when it was last nudged
        self.nudges = []          # when any window was nudged, for the rate limit
        self.magnet_at = 0.0      # when the window in use last drew a visitor
        self.warned = False       # only nag about errors once a run
        self.awake_since = 0.0
        self.greeted = False
        self.mem_saved = 0.0
        self._frame_errs = 0

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
        from gremlin_arsenal import Arsenal
        from gremlin_motion import MotionEngine
        from gremlin_social import SocialDirector
        self.arsenal = Arsenal(self, CFG)
        self.motion = MotionEngine(self, CFG)
        self.social = SocialDirector(self, CFG, lambda: MEM, mark_memory_dirty)
        self._play_mode = CFG["play_mode"]
        self._social_windows = dict(self.terrain.win_rect)
        self.spawn_fighters()

        self.canvas.bind("<ButtonPress-1>", self.on_down)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_up)
        self.canvas.bind("<ButtonPress-3>", lambda e: self.open_settings())

        self.tray = Tray() if IS_WINDOWS else Tray(self.root)
        self.tray.quit_callback = self.quit
        self.tray.add("Settings...", self.open_settings)
        self.tray.add("Performance...", self.open_performance)
        self.tray.add("Pause", self.toggle_pause, "check", lambda: self.paused)
        self.tray.sep()
        self.tray.add("Bring them to my cursor", self.summon)
        if IS_WINDOWS:
            self.tray.add("Restore my icon layout", self.restore_icons)
        self.tray.add("Put my windows back", self.restore_windows)
        self.tray.sep()
        self.tray.add("Quit", self.quit)
        self.tray.build()
        if not IS_WINDOWS:
            self.canvas.bind("<ButtonPress-3>", self.tray.popup)

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
    def begin_frame(self):
        """Coalesce desktop writes while fixed simulation steps catch up."""
        self._icon_batch = {}
        self._icon_geometry = {}
        self._window_batch = {}
        self._frame_environment_done = False

    def move_icon(self, index, x, y):
        x, y = int(x), int(y)       # the real list-view primitive stores integers
        batch = getattr(self, "_icon_batch", None)
        if batch is None:
            return SHELL.set_item_pos(index, x, y)
        if not self.can_move_icons():
            return False
        batch[index] = (x, y)
        return True

    def icon_position(self, index):
        pending = getattr(self, "_icon_batch", None) or {}
        return pending[index] if index in pending else SHELL.item_pos(index)

    def icon_rectangle(self, index):
        pending = getattr(self, "_icon_batch", None) or {}
        if index not in pending:
            return SHELL.item_rect(index)
        cached = self._icon_geometry.get(index)
        if cached is None:
            rect, position = SHELL.item_rect(index), SHELL.item_pos(index)
            if rect is None or position is None:
                return None
            cached = (position[0] - rect[0], position[1] - rect[1],
                      rect[2] - rect[0], rect[3] - rect[1])
            self._icon_geometry[index] = cached
        offx, offy, width, height = cached
        x, y = pending[index]
        return (x - offx, y - offy, x - offx + width, y - offy + height)

    def move_window(self, hwnd, x, y, on_success=None):
        batch = getattr(self, "_window_batch", None)
        if batch is None:
            moved = place_window(hwnd, x, y)
            if moved and on_success is not None:
                on_success()
            return moved
        batch[hwnd] = (x, y, on_success)
        return True

    def flush_frame(self):
        """One real write per affected icon/window, with the normal safety gates."""
        icons = getattr(self, "_icon_batch", None) or {}
        windows = getattr(self, "_window_batch", None) or {}
        self._icon_batch = self._window_batch = None
        self._frame_environment_done = False
        for index, (x, y) in icons.items():
            try:
                moved = self.can_move_icons() and SHELL.set_item_pos(index, x, y)
            except Exception:
                moved = False
            if not moved:
                for f in self.fighters:
                    if f.carry and f.carry["idx"] == index:
                        f.carry = None
                    if f.surf_idx and f.surf_idx[0] == index:
                        f.surf_idx = None
        for hwnd, (x, y, on_success) in windows.items():
            fg = foreground_window()
            if CFG["move_windows"] and not (fg and fg[1] == hwnd and idle_seconds() < 2):
                if place_window(hwnd, x, y) and on_success is not None:
                    on_success()

    def spawn_fighters(self):
        """Build the cast up or down to whatever the setting asks for.

        Survivors are kept rather than rebuilt. This runs every time the slider
        moves, and the old version threw away everyone but the first, losing
        their health, mood, position and any icon they were holding."""
        desired = selected_cast(CFG, ROSTER)
        existing = {f.kind: f for f in self.fighters}
        newcomers = []
        for f in self.fighters:
            if f.kind in desired:
                continue
            self.clear_expansion(f)
            self.drop_icon(f)          # never leave one holding a real icon
            self.end_ride(f)           # ...or a rider sat on a ghost
        keep = []
        for i, kind in enumerate(desired):
            f = existing.get(kind)
            if f is None:
                x = self.ox + self.W * (i + 1.0) / (len(desired) + 1.0)
                f = Fighter(x, self.ground_at(x), kind)
                newcomers.append(f)
            keep.append(f)
        self.fighters = keep
        for i, f in enumerate(self.fighters):
            f.become(f.kind)
            apply_profile(f, CFG, ROSTER, WEAPONS, palette)
            f.sc = CFG["scale"]
            f.foe = None               # free-for-all; picked fresh in decide()
        self._build_layers()
        self._prune_layers()
        # Latecomers off the slider announce themselves. Not at startup: the
        # greeting five seconds in covers that, and ten hellos at once is a
        # wall of text.
        if self.time > 1:
            for f in newcomers:
                self.puff(f.x, f.y, 6, DUST, f.K())
                f.yell("hello", 1.6)

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
        seq = ["dbg", "gore", "toys", "trap", "boom", "bolt", "part", "shot", "shotd", "arsenal", "slash"]
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
        seq.extend(("costume", "social"))
        for t in self._ftag:
            seq.extend(t[6:])
        self._layers = seq

    def apply_settings(self):
        self.configure_renderer()
        if not self.can_move_icons():
            self.cancel_icon_moves()
        for f in self.fighters:
            f.sc = CFG["scale"]
            f.become(f.kind)
            apply_profile(f, CFG, ROSTER, WEAPONS, palette)
        if [f.kind for f in self.fighters] != selected_cast(CFG, ROSTER):
            self.spawn_fighters()
        if self._play_mode != CFG["play_mode"]:
            self.clear_expansion()
            self.shots.clear()
            self.traps.clear()
            self._play_mode = CFG["play_mode"]
        for f in self.fighters:
            if not self.combat_allowed(f):
                # Airborne fighters also carry a pending duel/hunt. Clear that
                # intent now, before a landing can resume it in Peaceful mode.
                f.foe, f.mode = None, "roam"
                if not f.play:
                    f.target = None
                if f.state in ("attack", "fight") or (f.state == "hunt" and not f.play):
                    f.set_state("idle" if f.on_ground else "fall")
        if not CFG["parkour"]:
            for actor in list(self.motion.actions):
                self.motion.clear(actor)
        if not CFG["toy_props"]:
            self.motion.props.clear()
            for actor in self.fighters:
                if actor.plat and actor.plat[0] == "toy":
                    actor.plat, actor.on_ground = None, False
        if not CFG["group_scenes"]:
            self.social.clear()
        self.fit_screen()             # all_monitors no longer needs a restart

    def combat_allowed(self, f=None):
        return CFG["play_mode"] != "peaceful" and (f is None or bool(f.per["weapons"]))

    def clear_expansion(self, f=None):
        for name in ("social", "motion", "arsenal"):
            engine = getattr(self, name, None)
            if engine is not None:
                engine.clear(f)

    # -- the machine around us -------------------------------------------
    def screen_box(self):
        """((ox, oy, W, H), monitors) for the display setup as it is now."""
        vx, vy, vw, vh = virtual_screen()
        mons = monitors()
        if not CFG["all_monitors"]:
            # Windows places the primary monitor at the desktop origin; the
            # enumeration order does not identify it.
            m = (next((m for m in mons if m[0][:2] == (0, 0)), mons[0])
                 if IS_WINDOWS else mons[0])
            vx, vy = m[0][0], m[0][1]
            vw, vh = m[0][2] - m[0][0], m[0][3] - m[0][1]
            mons = [m]
        return (vx, vy, vw, vh), mons

    def fit_screen(self):
        """Re-cover the desktop when the monitors change: a dock, an undock, a
        resolution change. The window used to be sized once at startup, so
        after any of those the floor sat at the wrong height and half the
        desktop went uncovered until a restart. True if anything moved."""
        box, mons = self.screen_box()
        if box == (self.ox, self.oy, self.W, self.H) and mons == self.mons:
            return False
        self.ox, self.oy, self.W, self.H = box
        self.mons = mons
        try:
            self.root.geometry(f"{self.W}x{self.H}+{self.ox}+{self.oy}")
            self.canvas.config(width=self.W, height=self.H)
            if hasattr(self.canvas, "resize"):
                self.canvas.resize(self.W, self.H)
        except Exception:
            pass
        for f in self.fighters:
            # A virtual desktop can contain empty gaps. Refit into an actual
            # monitor, including when a removed monitor used to be above us.
            mon, work = self.monitor_at(f.x, f.y)
            f.x = clamp(f.x, mon[0] + 40, mon[2] - 40)
            f.y = clamp(f.y, mon[1] + 40, work[3])
        return True

    def check_environment(self):
        """Once a terrain cycle, from the frame loop, held or not: is a
        fullscreen app in front, are we on battery, did the monitors change."""
        self.on_battery = on_battery()
        hold = bool(CFG["pause_fullscreen"]) and fullscreen_app(self.hwnd)
        if hold != self.held:
            self.set_held(hold)
        if not self.held:
            self.fit_screen()

    def set_held(self, hold):
        """Hide behind a fullscreen app, and come back when it goes. The
        window is withdrawn rather than left transparent on top: a topmost
        layered window over a borderless game is still composited every
        frame, and still sits above the game."""
        self.held = hold
        if hold:
            self.clear_expansion()
            # A hidden Tk window may miss mouse-up. Finish its drag before
            # withdrawing so the fighter cannot return permanently grabbed.
            try:
                self.on_up(None)
            except Exception:
                pass  # hiding must still complete if drag cleanup fails
        try:
            if hasattr(self.canvas, "set_visible"):
                self.canvas.set_visible(not hold)
            if self.x11_overlay is not None:
                if hold:
                    self.clear_canvas()
                    self.x11_overlay.hide()
                else:
                    self.x11_overlay.show()  # Only present() may map a fresh mask.
                return
            if hold:
                self.clear_canvas()
                self.root.withdraw()
            else:
                self.root.deiconify()
                self.root.attributes("-topmost", True)
        except Exception:
            pass

    def frame_period(self):
        """Seconds between frames: the configured rate, slowed when nobody
        would notice. Asleep they only breathe; on battery paint is the cost;
        held for a fullscreen app there is nothing to draw at all."""
        p = 1.0 / CFG["fps"]
        if self.held:
            return .25
        if self.asleep:
            return max(p, .1)
        if self.on_battery:
            return max(p, .05)
        return p

    def on_callback_error(self, exc, val, tb):
        import traceback
        print("callback error:")
        traceback.print_exception(exc, val, tb)
        if not self.warned:
            self.warned = True
            try:
                self.tray.notify("Desktop Gremlin",
                                 "Something went wrong. Details are in " + LOG_PATH)
            except Exception:
                pass

    def toggle_pause(self):
        self.paused = not self.paused

    def summon(self):
        self.clear_expansion()
        n = len(self.fighters)
        for i, f in enumerate(self.fighters):
            self.drop_icon(f)
            self.end_ride(f)
            # fan them out, or ten of them arrive stacked on one pixel
            spread = (i - (n - 1) / 2.0) * 70
            f.wander_to = clamp(self.mouse["x"] + spread,
                                self.ox + 40, self.ox + self.W - 40)
            f.target = None
            f.set_state("walk")
            f.goal = self.time + 6
            f.yell("summoned", 1.2)

    def restore_icons(self):
        self.cancel_icon_moves()
        n = restore_layout()
        self.tray.notify("Desktop Gremlin",
                         f"Put {n} icon(s) back. Restore is incomplete; backup kept."
                         if n and LAYOUT_DIRTY else
                         (f"Put {n} icon(s) back where they were."
                          if n else "No icons restored; check the saved layout."))

    def quit(self):
        self.running = False
        # Hide first: a cleanup failure must never leave an input-blocking
        # window behind while the animation loop has already stopped.
        try:
            self.root.withdraw()
        except Exception:
            pass
        try:
            overlay = getattr(self, "x11_overlay", None)
            if overlay is not None:
                overlay.close()
        except Exception:
            pass
        try:
            if hasattr(self.canvas, "set_visible"):
                self.canvas.set_visible(False)
        except Exception:
            pass
        try:
            self.close_performance()
        except Exception:
            pass
        try:
            self.clear_expansion()
        except Exception:
            pass
        try:
            if hasattr(self.canvas, "dispose"):
                self.canvas.dispose()
        except Exception:
            pass
        try:
            save_memory()
        except Exception:
            pass
        try:
            self.terrain.scanner.close()
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
    def monitor_at(self, x, y=None):
        """Containing monitor, or the nearest one in this vertical column.

        Prefer the X column when a fighter crosses into a shorter display below
        its floor. Distance alone would keep choosing the taller one behind him.
        Callers with only X retain the first matching monitor for spawn defaults.
        """
        column = [m for m in self.mons if m[0][0] <= x < m[0][2]]
        candidates = column or self.mons
        if y is None:
            return min(candidates, key=lambda m: max(m[0][0] - x, 0, x - m[0][2]))
        for mon, work in candidates:
            if mon[0] <= x < mon[2] and mon[1] <= y < mon[3]:
                return mon, work
        return min(candidates, key=lambda m:
                   max(m[0][0] - x, 0, x - m[0][2]) ** 2
                   + max(m[0][1] - y, 0, y - m[0][3]) ** 2)

    def ground_at(self, x, y=None):
        """Work-area floor on the fighter's display, including stacked ones."""
        return self.monitor_at(x, y)[1][3]

    def nearest_enemy(self, f):
        """Closest one still on his feet. Free-for-all: no fixed pairings, so
        this is re-asked every time he decides what to do."""
        target = self.social.alliance_target(f) if hasattr(self, "social") else None
        if target is not None:
            return target
        best, bd = None, 1e9
        for o in self.fighters:
            if o is f or o.hp <= 0 or o.state in ("ko", "grabbed"):
                continue
            affinity = self.social.affinity(f, o) if hasattr(self, "social") else 0
            if affinity >= 80:
                continue
            d = abs(o.x - f.x) + abs(o.y - f.y) * .5
            d *= 1 + affinity * .003
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
        self.clear_expansion(f)
        f.grabbed = True
        self.end_ride(f)
        f.stunt = False
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
        if not IS_WINDOWS:
            sample = LINUX.desktop().mouse()
            if sample is None:
                return
            nx, ny, pressed = sample
            if not pressed and any(f.grabbed for f in self.fighters):
                self.on_up(None)
        else:
            pt = wt.POINT()
            try:
                if not user32.GetCursorPos(ctypes.byref(pt)):
                    return  # failed reads must not invent motion toward (0, 0)
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
        self.poll_renderer_input()
        self.scare(dt)

    def poll_renderer_input(self):
        if not hasattr(self.canvas, "poll_input"):
            return
        # Native window messages are queued, then dispatched outside the Win32
        # callback so opening Settings cannot re-enter Tk's interpreter.
        for action, x, y in self.canvas.poll_input():
            event = tk.Event()
            event.x, event.y = x - self.ox, y - self.oy
            if action == "down" and not (self.paused or self.held):
                self.on_down(event)
            elif action == "drag":
                self.on_drag(event)
            elif action == "up":
                self.on_up(event)
            elif action == "right" and not self.held:
                self.open_settings()
        grabbed = next((f for f in self.fighters if f.grabbed), None)
        if grabbed is not None and getattr(self.canvas, "native", None) is not None:
            # A nonactivating proxy can lose mouse messages outside its small
            # hit region. The cursor already sampled this frame keeps dragging
            # responsive, and a physical release cannot strand the fighter.
            mx, my = self.mouse["x"], self.mouse["y"]
            if mx > -9000 and my > -9000:
                grabbed.gx, grabbed.gy = mx, my + 58 * grabbed.sc
            if mouse_button_down() is False:
                self.on_up(None)
                self.canvas.set_interactive(False)  # relinquish stale capture
                grabbed = None
        target = grabbed or self.hover
        active = target is not None and not (self.paused or self.held)
        self.canvas.set_interactive(active, target.x if target else 0,
                                    target.y - 34 * target.sc if target else 0, 62)

    # -- fx ----------------------------------------------------------------
    def shake(self, t, m):
        self.shake_t = max(self.shake_t, t)
        self.shake_m = max(self.shake_m, m)

    def spark(self, x, y, n, col, spd, k=1.0):
        for _ in range(self.effect_count(n)):
            a = self.fx_random.random() * TAU
            s = self.fx_random.uniform(spd * .3, spd) * k
            self.parts.append({"x": x, "y": y, "vx": math.cos(a) * s,
                               "vy": math.sin(a) * s - self.fx_random.uniform(0, 60) * k,
                               "life": self.fx_random.uniform(.3, .9), "t": 0, "col": col,
                               "r": self.fx_random.uniform(1.2, 3.2) * max(.5, k),
                               "g": 900 * k, "k": "dot"})

    def puff(self, x, y, n, col=DUST, k=1.0, spread=26):
        for _ in range(self.effect_count(n)):
            self.parts.append({"x": x + self.fx_random.uniform(-spread, spread) * k,
                               "y": y - self.fx_random.uniform(0, 6) * k,
                               "vx": self.fx_random.uniform(-70, 70) * k,
                               "vy": self.fx_random.uniform(-46, -8) * k,
                               "life": self.fx_random.uniform(.35, .8), "t": 0, "col": col,
                               "r": self.fx_random.uniform(3, 7) * max(.5, k),
                               "g": 120 * k, "k": "dot"})

    def debris(self, cx, cy, w, h, n, col, k=1.0):
        for _ in range(self.effect_count(n)):
            self.parts.append({"x": cx + self.fx_random.uniform(-w / 2, w / 2),
                               "y": cy + self.fx_random.uniform(-h / 2, h / 2),
                               "vx": self.fx_random.uniform(-190, 190) * k,
                               "vy": self.fx_random.uniform(-330, -60) * k,
                               "life": self.fx_random.uniform(.9, 1.9), "t": 0, "col": col,
                               "r": self.fx_random.uniform(2.5, 6) * k, "g": 1250 * k,
                               "k": "chunk"})

    def boom(self, x, y, r, k=1.0, big=False):
        self.booms.append({"x": x, "y": y, "r": r * k, "t": 0, "life": .5 if big else .42})
        self.spark(x, y, 30 if big else 20, FIRE, 520 if big else 400, k)
        self.puff(x, y, 8 if big else 5, "#FFCF9A", k, 18)
        self.shake(.4 if big else .3, (16 if big else 10) * k)

    def blood(self, x, y, n, k=1.0, spd=250):
        """Red spray, only when the setting says so. Anything that lands
        becomes a stain on the floor via fx_tick; nothing else in the fx
        system persists, which is the whole point of gore."""
        if not CFG["blood"]:
            return
        for _ in range(self.effect_count(n)):
            a = self.fx_random.random() * TAU
            s = self.fx_random.uniform(spd * .3, spd) * k
            self.parts.append({"x": x, "y": y, "vx": math.cos(a) * s,
                               "vy": math.sin(a) * s - self.fx_random.uniform(30, 90) * k,
                               "life": self.fx_random.uniform(.4, 1.0), "t": 0,
                               "col": self.fx_random.choice(BLOODC),
                               "r": self.fx_random.uniform(1.4, 3.0) * max(.5, k),
                               "g": 1050 * k, "k": "blood"})

    def bolt(self, x0, y0, x1, y1):
        pts, n = [], 9
        for i in range(n + 1):
            t = i / n
            px = lerp(x0, x1, t) + (self.fx_random.uniform(-16, 16) if 0 < i < n else 0)
            py = lerp(y0, y1, t) + (self.fx_random.uniform(-16, 16) if 0 < i < n else 0)
            pts += [px, py]
        self.bolts.append({"pts": pts, "t": 0, "life": .22})

    # ==================================================================
    #  icon carrying — the real ones, really moved
    # ==================================================================
    def can_move_icons(self):
        return (CFG["move_icons"] and BACKUP_OK and not self.icons_locked
                and self.terrain.icons_ok)

    def cancel_icon_moves(self):
        """Release icon claims without another write, especially before undo."""
        for f in self.fighters:
            f.carry = None
            if f.surf_idx is not None or f.state == "surf":
                self.end_ride(f)
                f.on_ground = False
                f.set_state("fall")
            elif f.state == "carry":
                f.set_state("idle")
                f.goal = self.time + .4

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
                near.append((d, l, t, r, b, idx, name))
        if not near:
            return 0
        near.sort()
        del near[6:]
        held = {f.carry["idx"] for f in self.fighters if f.carry}
        held |= {f.surf_idx[0] for f in self.fighters if f.surf_idx}
        if not SHELL.open():
            return 0
        probe = self.icon_position(near[0][5])
        if probe is None:
            return 0
        offx, offy = probe[0] - near[0][1], probe[1] - near[0][2]
        gy = self.ground_at(x, y)
        moved, fresh = 0, []
        for d, l, t, r, b, idx, name in near:
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
            if self.move_icon(idx, nx + offx, ny + offy):
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

    def yank_icon(self, t, toward_x):
        """The magnet's icon shot: drag one real icon 120px toward the owner.
        Same probe-offset dance as blast_icons, same undo rules."""
        if not self.can_move_icons() or t.get("kind") != "icon":
            return False
        held = {o.carry["idx"] for o in self.fighters if o.carry}
        held |= {o.surf_idx[0] for o in self.fighters if o.surf_idx}
        idx = t["key"]
        if idx in held or not SHELL.open():
            return False
        try:
            rect = self.icon_rectangle(idx)
            probe = self.icon_position(idx)
        except Exception:
            return False
        if not rect or probe is None:
            return False
        offx, offy = probe[0] - rect[0], probe[1] - rect[1]
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        d = 1 if toward_x > rect[0] else -1
        gy = self.ground_at(rect[0], rect[1])
        nx = clamp(rect[0] + d * 120, self.ox + 4, self.ox + self.W - w - 4)
        ny = clamp(rect[1], self.oy + 4, gy - h - 4)
        if self.move_icon(idx, nx + offx, ny + offy):
            self.puff(rect[0] + w / 2, rect[1] + h, 4, DUST, .7, 10)
            return True
        return False

    def pick_up_icon(self, f, tgt):
        if not self.can_move_icons() or f.carry or tgt.get("kind") != "icon":
            return False
        idx = tgt["key"]
        try:
            if not SHELL.open():
                return False
            rect = self.icon_rectangle(idx)
            lx, ly = self.icon_position(idx)
        except Exception:
            return False
        if not rect:
            return False
        f.carry = {"idx": idx, "offx": lx - rect[0], "offy": ly - rect[1],
                   "w": rect[2] - rect[0], "h": rect[3] - rect[1],
                   "name": tgt.get("name", "")}
        f.carry_t = 0.0
        f.set_state("carry")
        gy = self.ground_at(f.x, f.y)
        f.wander_to = clamp(f.x + random.uniform(-620, 620), self.ox + 90,
                            self.ox + self.W - 90)
        # self.oy, not 0: the virtual screen goes negative when a monitor
        # sits above or left of the primary, and an absolute clamp there
        # pins every drop to the primary's top edge.
        f.carry_dest_y = clamp(gy - random.uniform(60, 420), self.oy + 40, gy - 60)
        bump(f.kind, "icons_moved")
        bump_icon(f.carry["name"])
        f.yell("snatch", 1.6, name=f.carry["name"][:12] or "that")
        return True

    def carry_tick(self, f, dt):
        if not f.carry:
            return
        if not self.can_move_icons():
            f.carry = None
            return
        f.carry_t += dt
        if f.carry_t < .12:
            return
        f.carry_t = 0.0
        c = f.carry
        sx = f.x - c["w"] / 2
        sy = f.y - 84 * f.sc - c["h"] / 2
        try:
            if not self.move_icon(c["idx"], sx + c["offx"], sy + c["offy"]):
                f.carry = None
        except Exception:
            f.carry = None

    def drop_icon(self, f, where=None):
        if not f.carry:
            return
        c = f.carry
        f.carry = None             # release the claim even when movement is disabled
        if not self.can_move_icons():
            return
        try:
            if where:
                sx, sy = where[0] - c["w"] / 2, where[1] - c["h"] / 2
            else:
                sx, sy = f.x - c["w"] / 2, f.y - 40 * f.sc
            gy = self.ground_at(f.x, f.y)
            sx = clamp(sx, self.ox + 4, self.ox + self.W - c["w"] - 4)
            sy = clamp(sy, self.oy + 4, gy - c["h"] - 4)
            self.move_icon(c["idx"], sx + c["offx"], sy + c["offy"])
            self.puff(sx + c["w"] / 2, sy + c["h"], 6, DUST, f.K())
        except Exception:
            pass

    # ==================================================================
    #  joyrides — getting around when nobody is fighting
    # ==================================================================
    def end_ride(self, f):
        """Put every ride field away: mount references both ways, the open
        parachute, the icon he was surfing. Callers set the next state; this
        only guarantees nothing dangles. A dangling mount is the crowd-slider
        bug all over again -- a reference to a fighter who no longer exists."""
        if f.mount is not None:
            if f.mount.ridden_by is f:
                f.mount.ridden_by = None
            f.mount = None
        if f.ridden_by is not None:
            r = f.ridden_by
            f.ridden_by = None
            if r.mount is f:
                r.mount = None
            if r.state == "ride":
                r.vy = -260 * r.K()
                r.set_state("fall")
        f.chute = False
        f.surf_idx = None

    def joyride(self, f, dest=None, travel_only=False):
        """Try the character's transport menu until one starts. One miss --
        nobody nearby to sit on, no icon in reach -- used to end the whole
        idea, which was half of why the grapple hook outdrew every ride 13:1
        (67 hooks to 5 rides, measured over four minutes at crowd five).
        The other half was the rage gate: in a standing brawl 127 of 156
        decides were made angry, so leisure never got a turn. With a dest or
        travel_only, only the rides that actually go somewhere qualify --
        rage may not lounge on a balloon, but it will absolutely pogo at you."""
        rides = RIDES[f.kind]
        if dest is not None or travel_only:
            rides = tuple(k for k in rides if k in TRAVEL_RIDES)
        if not rides:
            return False
        for kind in random.sample(rides, len(rides)):
            if self.start_ride(f, kind, dest=dest):
                f.boredom = max(0.0, f.boredom - .35)
                return True
        return False

    def start_ride(self, f, kind, dest=None):
        """Begin one of RIDES[f.kind]. False when the preconditions are not
        there -- no icon to surf, nobody to sit on -- so decide() can fall
        through to something else instead of stalling on a wish."""
        self.end_ride(f)
        K = f.K()
        if kind in ("pogo", "skate"):
            if not f.on_ground:
                return False
            f.wander_to = clamp(dest, self.ox + 70, self.ox + self.W - 70) \
                if dest is not None else \
                clamp(f.x + random.choice((-1, 1)) * random.uniform(340, 900),
                      self.ox + 70, self.ox + self.W - 70)
            f.face = 1 if f.wander_to >= f.x else -1
            f.set_state(kind)
            return True
        if kind == "float":
            f.set_state("float")
            f.vx = random.uniform(-40, 40) * K
            f.goal = self.time + random.uniform(4.0, 7.5)
            return True
        if kind == "jet":
            gy = self.ground_at(f.x, f.y)
            f.wander_to = clamp(dest, self.ox + 80, self.ox + self.W - 80) \
                if dest is not None else \
                clamp(f.x + random.choice((-1, 1)) * random.uniform(320, 900),
                      self.ox + 80, self.ox + self.W - 80)
            f.jet_y = clamp(gy - random.uniform(180, 340), self.oy + 130, gy - 120)
            f.goal = self.time + random.uniform(3.5, 6.0)
            f.face = 1 if f.wander_to >= f.x else -1
            f.set_state("jet")
            f.chat("hook", 1.0)      # the ascent lines fit the lift-off
            return True
        if kind == "cannon":
            if not f.on_ground:
                return False
            f.wander_to = clamp(dest, self.ox + 80, self.ox + self.W - 80) \
                if dest is not None else \
                clamp(f.x + random.choice((-1, 1)) * random.uniform(380, 950),
                      self.ox + 80, self.ox + self.W - 80)
            f.set_state("cannonwind")
            return True
        if kind == "surf":
            # Rides a REAL icon, so it wants everything icon-dragging wants:
            # the move_icons switch, a backup to undo with, auto-arrange off.
            if not self.can_move_icons():
                return False
            held = {o.carry["idx"] for o in self.fighters if o.carry}
            held |= {o.surf_idx[0] for o in self.fighters if o.surf_idx}
            picks = [t for t in self.terrain.targets()
                     if t["kind"] == "icon" and t["key"] not in held
                     and abs(t["cx"] - f.x) < 260]
            if not picks or not SHELL.open():
                return False
            t = min(picks, key=lambda p: abs(p["cx"] - f.x))
            try:
                rect = self.icon_rectangle(t["key"])
                lx, ly = self.icon_position(t["key"])
            except Exception:
                return False
            if not rect:
                return False
            self.puff(f.x, f.y, 3, DUST, K, 8)
            f.surf_idx = (t["key"], lx - rect[0], ly - rect[1],
                          rect[2] - rect[0], rect[3] - rect[1])
            f.x, f.y = t["cx"], t["top"]
            f.on_ground = False
            f.surf_t = 0.0
            f.wander_to = clamp(f.x + random.choice((-1, 1)) * random.uniform(300, 800),
                                self.ox + 90, self.ox + self.W - 90)
            f.set_state("surf")
            f.chat("hook", 1.0)
            return True
        if kind == "shoulders":
            mounts = [o for o in self.fighters
                      if o is not f and o.ridden_by is None and o.on_ground
                      and o.state in ("idle", "walk", "taunt")
                      and not o.carry and abs(o.x - f.x) < 90]
            if not mounts:
                return False
            m = min(mounts, key=lambda o: abs(o.x - f.x))
            f.mount, m.ridden_by = m, f
            f.on_ground = False
            f.goal = self.time + random.uniform(5.0, 9.0)
            f.set_state("ride")
            f.chat(f.mood, 1.4)
            return True
        return False

    def traps_tick(self, dt):
        """Age the placed peels and springboards, and spring them on whoever
        steps there. A peel thrown at a foe registers through hit_fighter so
        a trap fight is still a fight; stepping on your own is just comedy."""
        if not self.traps:
            return
        live = []
        for tr in self.traps:
            tr["t"] += dt
            if tr["t"] > tr["life"]:
                self.puff(tr["x"], tr["y"], 2, DUST, .6, 6)
                continue
            sprung = False
            if tr["t"] > tr["arm"]:
                for f in self.fighters:
                    if f.hp <= 0 or not f.on_ground or \
                            f.state in ("ko", "grabbed", "sleep", "ledge"):
                        continue
                    if abs(f.x - tr["x"]) > 20 or abs(f.y - tr["y"]) > 8:
                        continue
                    K = f.K()
                    if tr["k"] == "peel":
                        own = tr["owner"]
                        if own is not None and own is not f and own.hp > 0:
                            self.hit_fighter(own, f, 3)
                        else:
                            f.vr = math.copysign(random.uniform(5, 9), f.vx or 1)
                            f.vy = -300 * K
                            f.on_ground = False
                            f.set_state("thrown")
                        self.puff(f.x, tr["y"], 4, "#FFE97A", K, 10)
                        sprung = True
                    else:
                        # springboard: transport for anyone, owner included
                        f.vy = -1250 * K
                        f.vx = clamp(f.vx * 1.2, -420 * K, 420 * K)
                        f.on_ground = False
                        f.squash = -.5
                        f.set_state("jump")
                        self.puff(f.x, tr["y"], 4, DUST, K, 8)
                        self.shake(.06, 2)
                        tr["arm"] = tr["t"] + 1.0   # re-arm, multi-use
                    break
            if sprung:
                continue                            # a peel is consumed
            live.append(tr)
        self.traps = live

    def navigation_targets(self):
        targets = self.terrain.targets()
        if getattr(self, "_nav_source", None) is not targets:
            self._nav_source = targets
            self._nav_targets = {(t["kind"], t["key"]): t for t in targets}
        targets = dict(self._nav_targets)
        for prop in self.motion.props:
            if prop["kind"] == "fan" or not CFG["toy_props"]:
                continue
            targets[("toy", prop["id"])] = {
                "kind": "toy", "key": prop["id"], "name": prop["kind"],
                "cx": prop["x"], "cy": prop["y"] - prop["h"] / 2,
                "top": self.motion._height(prop, prop["x"]),
                "w": prop["w"], "h": prop["h"]}
        return targets

    def route_surface(self, target):
        left = target["cx"] - target["w"] / 2
        right = target["cx"] + target["w"] / 2
        if target["kind"] == "window":
            left, right = left + 6, right - 6
        return left, right, target["top"]

    def route_edge(self, source, destination, f):
        """Can this cast member cross the gap with his existing jump or climb?"""
        left, right, y = source
        dl, dr, dy = destination
        gap = max(dl - right, left - dr, 0)
        rise = y - dy
        if 20 < rise < 165 and gap <= 26:
            return "climb"
        K = f.K()
        velocity, gravity = 880 * K, 1900 * K
        discriminant = velocity * velocity - 2 * gravity * rise
        if discriminant < 0 or rise < -350:
            return None
        flight = (velocity + math.sqrt(discriminant)) / gravity
        reach = 260 * K * f.per["dash"] * flight * .85
        return "jump" if gap <= reach else None

    def route_blocked(self, f, target):
        """Direct hunt movement must honor the route planner's failed edges."""
        source = f.plat
        if source is None or source[0] == "floor":
            source = ("floor", tuple(self.monitor_at(f.x, f.y)[0]))
        goal = (target["kind"], target["key"])
        return f.route_failed.get((source, goal), 0.0) > self.time

    def plan_route(self, f, target):
        """At most three hops through nearby reachable surfaces; no global graph."""
        goal = (target["kind"], target["key"])
        current = f.plat
        if current and current[0] != "floor":
            start = next((self.route_surface(t) for t in self.navigation_targets().values()
                          if (t["kind"], t["key"]) == current), (f.x, f.x, f.y))
        else:
            mon, work = self.monitor_at(f.x, f.y)
            current = ("floor", tuple(mon))
            start = (mon[0] + 12, mon[2] - 12, f.y)
        f.route_failed = {edge: until for edge, until in f.route_failed.items()
                          if until > self.time}
        candidates = [t for t in self.navigation_targets().values()
                      if (t["kind"], t["key"]) != current
                      and self.ox <= t["cx"] <= self.ox + self.W
                      and t["top"] >= self.oy]
        candidates.sort(key=lambda t: abs(t["cx"] - f.x)
                        + abs(t["cx"] - target["cx"])
                        + abs(t["top"] - target["top"]))
        candidates = candidates[:32]
        if not any((t["kind"], t["key"]) == goal for t in candidates):
            candidates.append(target)
        # A tiny uniform-cost frontier avoids recursion and caps exploration.
        frontier = [(0.0, current, start, [])]
        best = {(current, 0): 0.0}
        for _ in range(100):
            if not frontier:
                break
            cheapest = min(range(len(frontier)), key=lambda i: frontier[i][0])
            cost, key, surface, path = frontier.pop(cheapest)
            if cost > best.get((key, len(path)), float("inf")):
                continue
            if key == goal:
                return path, current
            if len(path) >= 3:
                continue
            for candidate in candidates:
                other = (candidate["kind"], candidate["key"])
                if other == key or other in path \
                        or (key, other) in f.route_failed:
                    continue
                dest = self.route_surface(candidate)
                action = self.route_edge(surface, dest, f)
                if action is None:
                    continue
                # Walking distance plus the climb's vertical cost favours a
                # nearby staircase without making every detour look cheaper.
                from_x = f.x if not path else (surface[0] + surface[1]) / 2
                added = abs(candidate["cx"] - from_x) / max(60, 260 * f.K())
                added += .7 + max(0, surface[2] - dest[2]) / (65 if action == "climb" else 200)
                total = cost + added
                state = (other, len(path) + 1)
                if total < best.get(state, float("inf")):
                    best[state] = total
                    frontier.append((total, other, dest, path + [other]))
        return [], current

    def navigate(self, f, dt, K):
        """Follow a short route while preserving the actual attack/play target."""
        target = f.target
        if target is None or not f.on_ground:
            return False
        goal = (target["kind"], target["key"])
        if f.route_goal != goal:
            f.route = []
            f.route_goal = goal
            f.route_retry = 0.0
        if not f.route and (self.time < f.route_retry
                            or (f.y - target["top"] <= 170 and not f.play)):
            return False
        targets = self.navigation_targets()
        geometry = tuple((key, self.route_surface(targets[key]))
                         for key in f.route if key in targets)
        if f.route and geometry != f.route_geometry:
            # Moving or closed windows invalidate the cached edge geometry.
            f.route = []
            f.route_retry = 0.0
        if not f.route:
            if self.time < f.route_retry or (f.y - target["top"] <= 170 and not f.play):
                return False
            f.route, f.route_from = self.plan_route(f, target)
            f.route_geometry = tuple((key, self.route_surface(targets[key]))
                                     for key in f.route if key in targets)
            f.route_since = self.time
            f.route_best = float("inf")
            f.route_retry = self.time + 1.0
            if not f.route:
                return False
        waypoint = targets.get(f.route[0])
        if waypoint is None:
            f.route = []
            return False
        left, right, top = self.route_surface(waypoint)
        if left - 6 <= f.x <= right + 6 and abs(f.y - top) < 4:
            f.route_from = f.route.pop(0)
            f.route_geometry = f.route_geometry[1:]
            f.route_since = self.time
            f.route_best = float("inf")
            if not f.route:
                return False
            waypoint = targets[f.route[0]]
            left, right, top = self.route_surface(waypoint)
        distance = abs(f.x - clamp(f.x, left, right)) + abs(f.y - top)
        if distance < f.route_best - 6:
            f.route_best, f.route_since = distance, self.time
        elif self.time - f.route_since > 4.5:
            # A failed jump/climb should lead to a different approach next time.
            f.route_failed[(f.route_from, f.route[0])] = self.time + 12.0
            if len(f.route_failed) > 12:
                oldest = min(f.route_failed, key=f.route_failed.get)
                del f.route_failed[oldest]
            f.route = []
            f.route_retry = self.time + .3
            return False
        edge = left if f.x <= (left + right) / 2 else right
        f.face = 1 if edge >= f.x else -1
        if self.try_climb(f, waypoint):
            return True
        rise = f.y - top
        velocity, gravity = 880 * K, 1900 * K
        discriminant = velocity * velocity - 2 * gravity * rise
        landing = clamp(f.x, left + 8, max(left + 8, right - 8))
        source = targets.get(f.plat)
        if source is not None:
            sl, sr, _ = self.route_surface(source)
        else:
            mon, _ = self.monitor_at(f.x, f.y)
            sl, sr = mon[0], mon[2]
        climbable = 20 < rise < 165 and max(left - sr, sl - right, 0) <= 26
        if discriminant >= 0 and not climbable:
            flight = (velocity + math.sqrt(discriminant)) / gravity
            speed = 260 * K * f.per["dash"]
            if flight > 0 and abs(landing - f.x) <= speed * flight * .85:
                f.vx = (landing - f.x) / flight
                f.vy = -velocity
                f.on_ground = False
                f.set_state("jump")
                return True
        f.vx = approach(f.vx, f.face * 205 * K * f.per["dash"], 1600 * K * dt)
        return True

    def try_climb(self, f, t):
        """Scale the target's own platform edge instead of leaping at it.
        Only from the ground, only when the top is a climbable 20..170px up,
        and only once he has walked within arm's reach of the near edge --
        which the hunt walk does on its own, since the centre lies past it."""
        if not f.on_ground:
            return False
        top = t.get("top")
        if top is None or not (20 < f.y - top < 170):
            return False
        l = t["cx"] - t["w"] / 2
        r = t["cx"] + t["w"] / 2
        if t.get("kind") == "window":
            l, r = l + 6, r - 6
        edge, side = (l, 1) if abs(f.x - l) <= abs(f.x - r) else (r, -1)
        if abs(f.x - edge) > 26:
            return False
        f.climb_top = top
        f.climb_bot = top + t.get("h", 64)
        f.climb_x = edge
        f.climb_side = side
        f.x = edge - side * 6
        f.face = side
        f.vx = f.vy = 0.0
        f.on_ground = False
        f.set_state("climb")
        return True

    # ==================================================================
    #  playing on your windows
    # ==================================================================
    def covers_monitor(self, l, t, r, b):
        """Maximised or fullscreen: nothing to hang off, nowhere to nudge it."""
        for mon, work in self.mons:
            if l <= work[0] + 2 and t <= work[1] + 2 and r >= work[2] - 2 \
                    and b >= work[3] - 2:
                return True
        return False

    def work_area_at(self, x, y):
        for mon, work in self.mons:
            if mon[0] <= x < mon[2] and mon[1] <= y < mon[3]:
                return work
        return self.mons[0][1]

    def pick_window(self, f):
        """A window to play on: the one you are using, seven times in ten,
        while react_to_windows is on. Maximised windows have no edges, and a
        window he has just scrambled off is left alone for a while."""
        picks = []
        for hwnd, rect in self.terrain.win_rect.items():
            if hwnd == f.window_shy and self.time < f.window_cd:
                continue
            if not self.playable(rect):
                continue
            picks.append(hwnd)
        if not picks:
            return None
        if CFG["react_to_windows"] and self.fg and self.fg[1] in picks \
                and random.random() < .7:
            return self.fg[1]
        return random.choice(picks)

    def play_spot(self, f, kind, hwnd):
        """Where this play happens on this window, or None when the window's
        shape does not allow it: on the top edge for a perch, an arm's length
        under the bottom edge for a hang, part-way up a side for a cling, on
        the floor beside a side for a knock."""
        rect = self.terrain.win_rect.get(hwnd)
        if not rect:
            return None
        l, t, r, b = rect
        S = f.sc
        gy = self.ground_at(clamp((l + r) / 2, self.ox + 1, self.ox + self.W - 1), t)
        lo, hi = self.ox + 40, self.ox + self.W - 40
        if kind == "perch":
            if not (self.oy + 30 < t < gy - 60):
                return None
            return {"x": clamp(random.uniform(l + 30, r - 30), lo, hi), "side": 0}
        if kind == "hang":
            feet = b + 82 * S
            # the edge has to be above him, and within a jump of the floor
            if not (feet < gy - 4 and gy - feet < 170) or b < self.oy + 60:
                return None
            return {"x": clamp(random.uniform(l + 30, r - 30), lo, hi), "side": 0}
        sides = [(l, 1), (r, -1)]
        random.shuffle(sides)
        for edge, side in sides:
            if not (lo < edge < hi):
                continue
            if kind == "knock" and b > gy - 60 and t < gy - 90:
                return {"x": edge - side * 22, "side": side}
            if kind == "cling" and b > gy - 170 and t < gy - 130 and t > self.oy + 10:
                top = t + 110 * S
                y = random.uniform(top, max(top, min(b + 20, gy)))
                return {"x": edge - side * 6, "y": y, "side": side}
        return None

    def go_play(self, f, kind, hwnd):
        """Set off to play on a window. False when its shape says no."""
        spot = self.play_spot(f, kind, hwnd)
        if spot is None:
            return False
        f.play = {"kind": kind, "hwnd": hwnd, "x": spot["x"], "y": spot.get("y"),
                  "side": spot["side"], "until": 0.0, "phase": 0, "t0": 0.0,
                  "from_y": f.y}
        f.foe = None
        f.mode = "roam"
        f.target = None
        if kind == "perch":
            # the top edge the way a hunt gets there: walk, hook, climb.
            # _st_hunt begins the perch instead of an attack once he stands
            # on the window.
            for tg in self.terrain.targets():
                if tg["kind"] == "window" and tg["key"] == hwnd:
                    f.target = tg
                    break
            if f.target is None:
                f.play = None
                return False
            f.hits = 0
            f.snatch = False
            f.plan = "sword"
            f.set_state("hunt")
        else:
            f.wander_to = spot["x"]
            if abs(spot["x"] - f.x) > 420 and f.on_ground and random.random() < .7:
                # a long way at walking pace is a long time to get shot:
                # swing most of it and finish on foot -- landing with a plan
                # resumes the walk
                self.fire_hook(f, spot["x"], self.ground_at(spot["x"], f.y) - 160)
            else:
                f.set_state("walk")
        return True

    def playable(self, rect):
        """Big enough to have edges, and not filling a monitor."""
        l, t, r, b = rect
        return r - l >= 200 and b - t >= 120 and not self.covers_monitor(l, t, r, b)

    def visit_window(self, f, hwnd):
        """Send him to this window with whichever of his plays fits it. A
        furious one bangs on it if banging is in his repertoire, and sits or
        hangs scowling if not -- the mood is the halo and the face, and those
        go up there with him."""
        rect = self.terrain.win_rect.get(hwnd)
        if not rect or not self.playable(rect):
            return False
        kinds = random.sample(PLAYS[f.kind], len(PLAYS[f.kind]))
        if f.mood == "furious" and "knock" in kinds:
            kinds.remove("knock")
            kinds.insert(0, "knock")
        for kind in kinds:
            if self.go_play(f, kind, hwnd):
                return True
        return False

    def window_magnet(self):
        """The window you are using draws a visitor now and then, when nobody
        is on it or on the way to it. That is the point of the whole thing:
        it is YOUR window they climb on, not just any window."""
        hwnd = self.fg[1] if self.fg else None
        if not hwnd or hwnd not in self.terrain.win_rect or random.random() > .18:
            return
        if any(f.play and f.play["hwnd"] == hwnd for f in self.fighters):
            return
        # anyone not mid-brawl: an icon hunt is dropped for it, and a furious
        # one comes too, to bang on it if he can. With two of them fighting
        # most of the time, calm idlers alone were too rare to see.
        free = [f for f in self.fighters
                if f.state in ("idle", "walk", "taunt", "hunt") and PLAYS[f.kind]
                and not (f.window_shy == hwnd and self.time < f.window_cd)]
        if free:
            self.visit_window(random.choice(free), hwnd)

    def begin_play(self, f):
        """He has arrived: pin him to the window and start the play. False
        when the window has gone in the meantime."""
        p = f.play
        rect = self.terrain.win_rect.get(p["hwnd"]) if p else None
        if not rect:
            f.play = None
            return False
        l, t, r, b = rect
        kind = p["kind"]
        K = f.K()
        p["until"] = self.time + random.uniform(*PLAY_TIME[kind])
        p["phase"] = 0
        p["t0"] = self.time
        p["from_y"] = f.y
        f.vx = f.vy = 0.0
        f.foe = None
        f.target = None
        f.plat = None            # or the window-rider pass moves him twice
        if kind == "perch":
            p["x"] = clamp(f.x, l + 30, r - 30)
            f.x, f.y = p["x"], float(t)
            f.on_ground = False
            f.chat("perch", 1.6)
        elif kind == "hang":
            f.x = p["x"]
            f.on_ground = False
            self.puff(f.x, f.y, 2, DUST, K, 6)          # the jump for the edge
            f.chat("hang", 1.6)
        elif kind == "cling":
            edge = l if p["side"] == 1 else r
            f.climb_top, f.climb_bot = float(t), float(b)
            f.climb_x, f.climb_side = float(edge), p["side"]
            f.x = edge - p["side"] * 6
            p["y"] = clamp(p["y"], t + 110 * f.sc, min(b + 20, self.ground_at(f.x, f.y)))
            f.face = p["side"]
            f.on_ground = False
            f.chat("hang", 1.4)
        else:                                            # knock
            edge = l if p["side"] == 1 else r
            f.x = edge - p["side"] * 22
            f.y = self.ground_at(f.x, f.y)
            f.face = p["side"]
            f.on_ground = True
            f.chat("knock", 1.6)
        f.set_state(kind)
        return True

    def end_play(self, f):
        """Let go of the window. Callers set the next state; this only makes
        sure nothing refers to it any more."""
        f.play = None

    def scare(self, dt):
        """Anyone on a window gets out of the cursor's way when it comes at
        him, so a click on a title-bar button, a scrollbar or an edge gets
        through. Gated on the cursor's SPEED towards him: one that stops on
        him is a grab, and the rings appear as usual."""
        mx, my = self.mouse["x"], self.mouse["y"]
        vx, vy = self.mouse["vx"], self.mouse["vy"]
        if mx < -9000:
            return
        speed = math.hypot(vx, vy)
        for f in self.fighters:
            if not f.play or f.state not in PLAY_STATES:
                continue
            bx, by = f.x, f.y - 40 * f.sc
            d = dist(mx, my, bx, by)
            if d > 120:
                continue
            toward = ((bx - mx) * vx + (by - my) * vy) / max(d, 1.0)
            if toward > 150 or (d < 60 and speed > 60):
                self.scramble(f, mx)

    def scramble(self, f, from_x):
        """Off the window, away from the cursor, and not back for a while."""
        K = f.K()
        f.window_shy = f.play["hwnd"]
        f.window_cd = self.time + 8
        self.end_play(f)
        away = 1 if f.x >= from_x else -1
        f.vx = away * 260 * K
        f.vy = -300 * K
        f.on_ground = False
        f.set_state("fall")
        f.chat("scramble", 1.2)

    def nudge_window(self, hwnd, dx, dy):
        """Slide one of your windows a few pixels. Off unless move_windows is
        on; never a maximised one, never the one you are typing in, never off
        its monitor, never more than one every few seconds. The first nudge of
        a window remembers where it was, for the tray."""
        if not CFG["move_windows"] or not hwnd:
            return False
        rect = self.terrain.win_rect.get(hwnd)
        if not rect or self.covers_monitor(*rect):
            return False
        foreground = foreground_window()
        if foreground and foreground[1] == hwnd and idle_seconds() < 2.0:
            return False
        now = self.time
        self.nudges = [x for x in self.nudges if now - x < 60]
        pending = getattr(self, "_window_batch", None) or {}
        if hwnd in pending or len(self.nudges) + len(pending) >= NUDGE_PER_MINUTE \
                or now - self.nudged_at.get(hwnd, -99.0) < 4:
            return False
        l, t, r, b = rect
        cx, cy = (l + r) / 2, (t + b) / 2
        # The overlay may be restricted to the primary display; a real window
        # still belongs to its actual monitor, including secondary displays.
        work = next((work for mon, work in monitors()
                     if mon[0] <= cx < mon[2] and mon[1] <= cy < mon[3]), None)
        if work is None:
            return False
        dx = int(round(clamp(dx, work[0] - l, max(work[0] - l, work[2] - r))))
        dy = int(round(clamp(dy, work[1] - t, max(work[1] - t, work[3] - b))))
        if not dx and not dy:
            return False
        wr = window_rect(hwnd)
        if not wr:
            return False

        def committed():
            # A staged write may fail or lose permission before the frame ends.
            # Only a real movement earns an undo entry or consumes its quota.
            self.nudged.setdefault(hwnd, (wr[0], wr[1]))
            self.nudged_at[hwnd] = now
            self.nudges.append(now)
            self.terrain.win_rect[hwnd] = (l + dx, t + dy, r + dx, b + dy)

        return self.move_window(hwnd, wr[0] + dx, wr[1] + dy, committed)

    def restore_windows(self):
        """Put every nudged window back where it was before its first nudge."""
        n = 0
        for hwnd, (x, y) in list(self.nudged.items()):
            if window_alive(hwnd):
                if not place_window(hwnd, x, y):
                    continue             # preserve the original position for another try
                if not IS_WINDOWS and not confirm_window_position(hwnd, x, y):
                    continue
                n += 1
            # Closed windows and successful restores no longer need an undo entry.
            del self.nudged[hwnd]
            self.nudged_at.pop(hwnd, None)
        try:
            self.tray.notify("Desktop Gremlin",
                             f"Put {n} window(s) back. Restore is incomplete; try again."
                             if self.nudged else
                             (f"Put {n} window(s) back." if n
                              else "No window has been nudged."))
        except Exception:
            pass
        return n

    # ==================================================================
    #  combat
    # ==================================================================
    def fire_hook(self, f, tx, ty):
        gy = self.ground_at(tx, ty)
        tx = clamp(tx, self.ox + 20, self.ox + self.W - 20)
        ty = clamp(ty, self.oy + 34, gy - 40)
        f.hook = {"x": f.x, "y": f.y - 60 * f.sc, "tx": tx, "ty": ty, "t": 0,
                  "dur": clamp(dist(f.x, f.y - 60, tx, ty) / 1500, .12, .5)}
        f.set_state("hookfire")
        f.face = 1 if tx > f.x else -1
        f.chat("hook", 1.0)

    def start_attack(self, f, at=None, foe=False):
        if not self.combat_allowed(f):
            f.target, f.foe, f.mode = None, None, "roam"
            f.set_state("idle")
            return
        if at is not None:
            cx, cy = at
        elif foe and f.foe:
            cx, cy = f.foe.x, f.foe.y - 34 * f.foe.sc
        elif f.target:
            cx, cy = f.target["cx"], f.target["cy"]
        else:
            f.set_state("idle")
            return
        f.aim = math.atan2(cy - (f.y - 44 * f.sc), cx - f.x)
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
        allowed = f.per.get("weapons", ())
        if not allowed:
            f.set_state("idle")
            return
        if f.weapon not in allowed:
            # A cursor attack or stale plan cannot bypass a changed loadout.
            f.weapon = plan_weapon(f.per, f.mood == "furious")
        f.plan = f.weapon
        # Shots meant for the other one ignore the desktop on the way past;
        # otherwise a row of icons between them soaks up every round. With
        # shots_over_icons on, fire at the cursor or at a picked target gets
        # the same treatment -- but an aimed round has to carry WHICH target
        # it is for, or the pierce would carry it through the very window it
        # was fired at.
        f.at_foe = bool(foe and f.foe)
        f.shot_pierce = f.at_foe
        f.shot_tgt = None
        if not f.at_foe and CFG["shots_over_icons"]:
            if at is not None:
                f.shot_pierce = True
            elif f.target is not None:
                f.shot_pierce = True
                f.shot_tgt = (f.target["kind"], f.target["key"])
        if f.weapon == "bow":
            k = f.K()
            ang = lob_angle(cx - f.x, cy - (f.y - 44 * f.sc), 720 * k, 420 * k)
            if ang is not None:
                f.aim = ang
        f.atk_dur = ATKDUR[f.weapon]
        f.atk = 0.0
        f.fired = False
        f.burst = 0.0
        f.set_state("attack")

    def muzzle(self, f):
        """Where a round leaves: the END of the weapon as it is drawn. The
        same blended stance (pose), the same elbow (ik), the same barrel
        (MUZZLE_TIP mirrors the furthest point draw_weapon puts on the canvas)
        and the same body transform (frame) as the drawing, so if a pose moves
        this moves with it. Three earlier versions modelled the pose instead of
        sharing it -- from the shoulder, then from the hand, then along an
        idealised aim ray -- and each sat a few pixels off every barrel, so
        the round appeared beside the gun. tests/test_muzzle.py reads the drawn
        tip back off the canvas and holds this to 4px.

        The bow is the odd one out: the arrow leaves the bow, which is in the
        FRONT hand, from the middle of its curve."""
        px, py, lean, _tilt, _fL, _fR, hL, hR = self.pose(f)
        P = self.frame(f)
        if f.weapon == "bow":
            aim = math.atan2(hL[1] - hR[1], hL[0] - hR[0])
            return P(hL[0] + math.cos(aim) * 20, hL[1] + math.sin(aim) * 20)
        nx, ny = rot(0, -26, lean)
        neck = (px + nx, py + ny)
        elb = ik(neck[0], neck[1] - 1, hR[0], hR[1], 13, 13, 1)
        a = math.atan2(hR[1] - elb[1], hR[0] - elb[0])
        tx, ty = rot(MUZZLE_TIP.get(f.weapon, 0), 0, a)
        return P(hR[0] + tx, hR[1] + ty)

    def shoot(self, f, kind, speed, grav, life, extra=None, at=None):
        if f.weapon not in f.per.get("weapons", ()):
            return
        hx, hy = at if at is not None else self.muzzle(f)
        k = f.K()
        s = {"k": kind, "x": hx, "y": hy, "owner": f,
             "vx": math.cos(f.aim) * speed * k, "vy": math.sin(f.aim) * speed * k,
             "g": grav * k, "life": life, "trail": [], "spin": 0.0,
             "pierce": f.shot_pierce, "tgt": f.shot_tgt}
        if extra:
            s.update(extra)
        self.shots.append(s)

    def release_attack(self, f):
        if f.weapon not in f.per.get("weapons", ()):
            return
        arsenal = getattr(self, "arsenal", None)
        if arsenal is not None and arsenal.release(f):
            return
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
            self.lob(f, "bomb")
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
        elif w == "fish":
            self.slashes.append({"x": f.x + f.face * 34 * f.sc, "y": f.y - 52 * f.sc,
                                 "a": f.aim, "t": 0, "life": .26, "sc": f.sc,
                                 "col": "#9FD8E8"})
            self.melee_hit(f, 130)
            self.puff(f.x + f.face * 30 * f.sc, f.y - 40 * f.sc, 3, WATER, k, 8)
            self.shake(.10, 3 * k)
        elif w == "pan":
            self.slashes.append({"x": f.x + f.face * 30 * f.sc, "y": f.y - 50 * f.sc,
                                 "a": f.aim, "t": 0, "life": .18, "sc": f.sc,
                                 "col": GUNMETAL})
            self.melee_hit(f, 110)
            self.shake(.14, 5 * k)
        elif w == "confetti":
            base = f.aim
            hx, hy = self.muzzle(f)         # one barrel; the spread is in the aim
            for _ in range(7):
                f.aim = base + random.uniform(-.24, .24)
                self.shoot(f, "confetti", 780, 25, .75,
                           extra={"col": random.choice(CONFETTI_COLS)}, at=(hx, hy))
            f.aim = base
            self.spark(hx, hy, 6, random.choice(CONFETTI_COLS), 200, k)
        elif w == "balloon":
            self.lob(f, "wballoon")
        elif w == "harpoon":
            self.shoot(f, "harpoon", 800, 8, 1.4)
            self.shake(.10, 3 * k)
        elif w == "magnet":
            self.shoot(f, "magnet", 780, 0, 1.2)
            self.spark(*self.muzzle(f), 4, "#E05A3A", 160, k)
        elif w == "blackhole":
            self.lob(f, "blackhole")
        elif w in DROPPERS:
            # Delivered from the sky, straight down onto where he is looking.
            # pierce is free here -- nothing on the way matters but the target.
            tx, ty = self.aim_point(f)
            self.shots.append({"k": w, "x": tx + random.uniform(-8, 8),
                               "y": min(f.y - 80 * f.sc, ty) - 430,
                               "owner": f, "vx": 0.0, "vy": 30 * k,
                               "g": 1500 * k, "life": 3.0, "trail": [],
                               "spin": 0.0, "pierce": True, "tgt": f.shot_tgt})
        elif w in TRAPS:
            # tossed a short way ahead, from the hand it is drawn in; becomes
            # a ground prop where it lands
            hx, hy = self.muzzle(f)
            self.shots.append({"k": w, "x": hx, "y": hy, "owner": f,
                               "vx": math.cos(f.aim) * 360 * k,
                               "vy": math.sin(f.aim) * 360 * k - 200 * k,
                               "g": 900 * k, "life": 2.0, "trail": [],
                               "spin": 0.0, "pierce": True, "tgt": None})

    def lob(self, f, kind):
        """Throw something from the hand onto where he is looking. The angle
        comes from where it actually leaves (the muzzle, wherever the swing has
        put the hand) to the aim point, the way the bow already aims, so the
        throw lands whatever the release point. A fixed velocity plus an
        upward kick used to be the throw; moving the spawn to the drawn hand
        then put every lob short, because the hand is higher and further back
        than the idealised muzzle was. 45 degrees, as far as it goes, when the
        target is out of range."""
        k = f.K()
        hx, hy = self.muzzle(f)
        tx, ty = self.aim_point(f)
        v, g = 650 * k, 900 * k
        ang = lob_angle(tx - hx, ty - hy, v, g)
        if ang is None:
            ang = math.atan2(-1, 1 if tx >= hx else -1)
        self.shots.append({"k": kind, "x": hx, "y": hy, "owner": f,
                           "vx": math.cos(ang) * v, "vy": math.sin(ang) * v,
                           "g": g, "life": 2.2, "trail": [], "spin": 0.0,
                           "pierce": f.shot_pierce, "tgt": f.shot_tgt})

    def aim_point(self, f):
        # The foe test has to come first. It used to read `f.state == "fight" or
        # (f.foe and ...)`, which short-circuits before the None check and
        # dereferences a missing foe -- unreachable with a fixed pair, live the
        # moment foes are reassigned.
        if f.foe and f.foe.hp > 0 and (f.state == "fight" or f.mode == "fight"):
            return f.foe.x, f.foe.y - 34 * f.foe.sc
        if f.target:
            return f.target["cx"], f.target["cy"]
        return (f.x + math.cos(f.aim) * 400, f.y - 44 * f.sc + math.sin(f.aim) * 400)

    def melee_hit(self, f, reach):
        rk = .4 + .6 * f.K()
        if f.foe and f.foe.hp > 0 and dist(f.x, f.y - 30 * f.sc, f.foe.x,
                                           f.foe.y - 30 * f.foe.sc) < reach * rk:
            self.hit_fighter(f, f.foe, MELEE_DMG.get(f.weapon, 9))
            return
        if f.target and dist(f.x, f.y - 40 * f.sc, f.target["cx"], f.target["cy"]) < reach * rk:
            self.hit_target(f, f.target, f.target["cx"], f.target["cy"])

    def zap_hit(self, f, tx, ty):
        if f.foe and f.foe.hp > 0 and dist(tx, ty, f.foe.x, f.foe.y - 34 * f.foe.sc) < 70:
            self.hit_fighter(f, f.foe, 22)
        elif f.target and dist(tx, ty, f.target["cx"], f.target["cy"]) < 90:
            self.hit_target(f, f.target, tx, ty)

    def impact_visual(self, att, vic, dmg):
        """Weapon-family contact cues, separate from damage and knockback."""
        weapon, k = att.weapon, vic.K()
        x, y = vic.x, vic.y - 34 * vic.sc
        color = {"fish": WATER, "balloon": WATER, "pan": STEEL,
                 "anvil": STEEL, "piano": WOOD, "blaster": LASER,
                 "minigun": FIRE, "rocket": FIRE, "bomb": FIRE,
                 "lightning": BOLT, "magnet": "#E05A3A",
                 "blackhole": "#B79BFF", "harpoon": STEEL}.get(weapon, "#FFFFFF")
        if weapon == "confetti":
            color = self.fx_random.choice(CONFETTI_COLS)
        self.spark(x, y, 12, color, 180 if weapon in ("pan", "anvil", "piano") else 300, k)
        if weapon in MELEE:
            self.slashes.append({"x": x, "y": y,
                                 "a": .4 if vic.x >= att.x else math.pi + .4,
                                 "t": 0.0, "life": .14 if weapon != "pan" else .22,
                                 "sc": vic.sc * (.52 if weapon == "chainsaw" else .7),
                                 "col": color})
        elif weapon in ("fish", "balloon", "anvil", "piano"):
            self.puff(x, y, 4, color, k, 9)

    def hit_fighter(self, att, vic, dmg):
        if not self.combat_allowed():
            return
        if vic.state in ("ko", "grabbed"):
            return
        arsenal = getattr(self, "arsenal", None)
        if arsenal is not None:
            dmg = arsenal.filter_damage(att, vic, dmg)
            if dmg <= 0:
                return
        self.social.on_hit(att, vic, dmg)
        self.clear_expansion(vic)
        self.drop_icon(vic)         # damage interrupts carrying, including a knockout
        if vic.state in ("float", "ride", "surf"):
            # a hit pops the balloon, knocks him off the shoulders or the icon
            self.end_ride(vic)
        vic.hp -= dmg
        k = vic.K()
        d = 1 if vic.x >= att.x else -1
        vic.vx = d * (250 + dmg * 9) * k
        vic.vy = -(180 + dmg * 5) * k
        vic.on_ground = False
        vic.anger = clamp(vic.anger + .07 * vic.per["grudge"], 0, 1)
        vic.hit_at, vic.hit_power, vic.hit_side = self.time, min(1.0, dmg / 22.0), d
        self.impact_visual(att, vic, dmg)
        # only flesh bleeds -- icons and windows keep their sparks
        self.blood(vic.x, vic.y - 34 * vic.sc, min(3 + dmg // 3, 10), k)
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
            if CFG["blood"]:
                self.blood(vic.x, vic.y - 24 * vic.sc, 12, k)
                self.stains.append({"x": vic.x + self.fx_random.uniform(-6, 6),
                                    "y": self.ground_at(vic.x, vic.y),
                                    "r": self.fx_random.uniform(5.5, 8.5), "t": 0.0,
                                    "life": self.fx_random.uniform(10.0, 16.0)})
            att.anger = .2
            att.set_mood("smug")
            att.yell("victory", 1.8)
            # Stand over the body for a beat. Only from combat states: a
            # ranged kill can land while the owner is carrying an icon, and
            # yanking him out of "carry" strands the icon in mid-air with
            # nothing ticking it.
            if att.state in ("attack", "fight"):
                att.set_state("taunt")
        else:
            vic.set_state("thrown")
            # The commonest yell in a brawl by an order of magnitude -- a
            # minigun stream lands a hit every 70ms. The health bar already
            # reports the damage; saying "ow" is theatre, so chatty owns it.
            if random.random() < .6:
                vic.chat("hurt", 1.1)

    def hit_target(self, f, t, fx, fy):
        self.spark(fx, fy, 10, "#CFD8F5", 260, f.K())
        current_target = f.target is not None and \
            (f.target["kind"], f.target["key"]) == (t["kind"], t["key"])
        if f.target is not None and not current_target:
            # A round from an earlier hunt still hits, but cannot add to the
            # new target's progress or complete it with borrowed hits.
            return
        f.hits += 1
        need = 1 if (t.get("kind") == "icon" and f.snatch) \
            else (4 if t.get("kind") == "window" else 3)
        if f.hits >= need:
            f.hits = 0
            k = f.K()
            self.debris(t["cx"], t["cy"], min(t["w"], 90), min(t["h"], 60), 14, "#8095E8", k)
            self.boom(t["cx"], t["cy"], 44, k)
            if t.get("kind") == "window":
                # a finished window slides a little, away from the shot --
                # only ever under move_windows, and nudge_window says no to
                # the one you are typing in
                self.nudge_window(t["key"],
                                  math.copysign(random.uniform(8, 16), t["cx"] - fx),
                                  clamp((t["cy"] - fy) * .2, -8, 8))
            f.anger = max(0, f.anger - .35)
            f.boredom = max(0, f.boredom - .45)
            if f.mode == "fight" and f.foe and f.foe.hp > 0:
                return          # wrecked in passing; he has not finished here
            if not current_target or f.state not in ("attack", "hunt", "idle") \
                    or f.play is not None or f.carry:
                # Only the matching active hunt may finish its owner's action.
                # Late contact cannot cancel a grab, KO, ride or window visit.
                return
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
        if self.motion.consider(f):
            return
        if not self.combat_allowed(f):
            f.foe, f.target, f.mode = None, None, "roam"
            hwnd = self.pick_window(f)
            if hwnd and random.random() < .4 and self.visit_window(f, hwnd):
                return
            if random.random() < .25 and self.joyride(f, travel_only=True):
                return
            f.wander_to = random.uniform(self.ox + 60, self.ox + self.W - 60)
            f.set_state("walk")
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
            if CFG["play_mode"] == "battle":
                p = min(.9, p * 3.5)
            if r < p:
                f.mode = "fight"
                f.snatch = False
                f.plan = plan_weapon(f.per, rage)
                f.set_state("fight")
                # revenge is the memory feature talking; it always gets said
                if losing:
                    f.yell("revenge", 1.4)
                else:
                    f.chat("fight", 1.4)
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
                f.chat("gangup", 1.4)
                return

        if self.time - self.mouse["t"] < 4 and \
                dist(f.x, f.y - 50, self.mouse["x"], self.mouse["y"]) < 340 and \
                random.random() < .35:
            f.target = None
            f.set_state("cursor")
            f.boredom = 0
            f.chat("cursor", 1.4)
            return

        # A window is a climbing frame, and never the one he just scrambled
        # off: sit on it, hang under it, cling to its side, bang on it --
        # whichever of his own repertoire fits the window's shape. A furious
        # one goes too (the halo and the face carry the mood up there), and
        # reaches for the knock first if he has one.
        if PLAYS[f.kind] and random.random() < .34 + .30 * f.boredom:
            hwnd = self.pick_window(f)
            if hwnd and self.visit_window(f, hwnd):
                f.boredom = max(0.0, f.boredom - .3)
                return

        # Not everything is a fight. With his own way of getting around, a
        # bored one is now as likely to take a joyride, or wander over to
        # bother a colleague, as to start something. Rage still fights --
        # but rage travels too, it just doesn't lounge.
        if random.random() < .30 + .25 * f.boredom \
                and self.joyride(f, travel_only=rage):
            return
        if not rage and random.random() < .07:
            others = [o for o in self.fighters
                      if o is not f and o.hp > 0
                      and o.state in ("idle", "walk", "taunt")]
            if others:
                o = random.choice(others)
                f.target = None
                f.wander_to = clamp(o.x + random.uniform(-80, 80),
                                    self.ox + 60, self.ox + self.W - 60)
                f.set_state("walk")
                f.chat(f.mood, 1.6)
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
            if f.snatch and "sword" in f.per["weapons"]:
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
            # travel for its own sake: half the time that is a ride now,
            # not another zip line
            if random.random() < .5 and self.joyride(f):
                return
            self.fire_hook(f, random.uniform(self.ox + self.W * .1, self.ox + self.W * .9),
                           random.uniform(self.oy + 40, self.ground_at(f.x, f.y) - 200))
            f.target = None
            return
        if r < .86:
            f.set_state("taunt")
            return
        # Always somewhere on the screen. A target out past the wrap point can
        # never be reached: he crosses the edge, reappears on the far side, and
        # sets off towards it again for as long as you leave him.
        if random.random() < .25 and self.joyride(f):
            return
        f.target = None
        f.wander_to = random.uniform(self.ox + 60, self.ox + self.W - 60)
        f.set_state("walk")

    # ==================================================================
    #  per-fighter tick
    # ==================================================================
    def update_fighter(self, f, dt):
        if f.carry and f.state != "carry":
            self.drop_icon(f)     # every other interruption releases stale cargo too
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
            self.end_ride(f)
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
                        f.chat("rage", 1.7)
                    f.set_mood(m)

        for engine in (self.social, self.arsenal, self.motion):
            if engine.control(f, dt):
                return
        s = f.state
        gy = self.ground_at(f.x, f.y)
        step = self.STATES.get(s)
        if step is not None and step(self, f, dt, K):
            return

        # parachute: the nervous deploy on any long fall (their idea of a
        # transport is not hitting the ground), the fearless mostly plummet
        if not f.on_ground and f.vy > 640 * K and not f.chute \
                and f.state in ("fall", "thrown") and f.y < gy - 220 \
                and random.random() < dt * (2.2 * f.per["nerve"] + .15):
            f.chute = True
            f.vy = min(f.vy, 300 * K)

        self.physics(f, dt, gy)

        if f.chute:
            if f.on_ground or f.state not in ("fall", "thrown"):
                f.chute = False
            else:
                f.vy = min(f.vy, 190 * K)
                f.vx += math.sin(self.time * 2.2 + f.seedp) * 26 * K * dt

        sp = abs(f.vx)
        f.walk += dt * (sp / (22 * K) + (2 if sp > 8 * K else 0))
        f.look = lerp(f.look, clamp((self.mouse["x"] - f.x) / 320, -1, 1), 1 - pow(.02, dt))

    # ------------------------------------------------------------------
    # one method per state. Each gets the fighter, the frame time and his
    # speed scale, and may return True to end his update early -- that is
    # what a joyride does, because start_ride has already moved him.
    # STATES, at the bottom, is the whole state machine in one place.
    # ------------------------------------------------------------------
    def _st_sleep(self, f, dt, K):
        f.vx = approach(f.vx, 0, 900 * K * dt)

    def _st_ko(self, f, dt, K):
        f.tumble += f.vr * dt * (1 if not f.on_ground else 0)
        if f.on_ground:
            f.vr = 0
            if CFG["blood"] and random.random() < dt * 1.6:
                self.blood(f.x + random.uniform(-10, 10) * f.sc,
                           f.y - 10 * f.sc, 1, K, 60)
        if f.st > 3.4:
            f.hp = 100.0
            f.tumble = 0
            f.set_state("idle")
            f.goal = self.time + .6
            self.arsenal.apply_effect(f, "shield", 3.0)
            f.set_mood("furious")
            f.anger = .8
            f.chat("getup", 1.7)

    def _st_idle(self, f, dt, K):
        f.vx = approach(f.vx, 0, 900 * K * dt)
        if self.time > f.goal:
            self.decide(f)

    def _st_walk(self, f, dt, K):
        d = f.wander_to - f.x
        if abs(d) < 12:
            # a walk that was the way to a window ends by playing on it --
            # from the ground only; a plan carried through a fall or a fight
            # is stale, and a stale one is dropped, not acted on
            if f.play and f.on_ground and abs(f.x - f.play["x"]) < 30 \
                    and self.begin_play(f):
                return
            f.play = None
            f.set_state("idle")
            f.goal = self.time + random.uniform(.6, 1.8)
        else:
            # a long trudge upgrades itself into transport, same
            # destination -- walking is constant, so this is where the
            # rides actually get used rather than the rare idle roll.
            # Not on the way to a window: a ride ends in idle and forgets
            # the plan, and most trips there are long enough to qualify.
            if f.on_ground and abs(d) > 300 and f.mode != "fight" \
                    and not f.play and random.random() < dt * .35 \
                    and self.joyride(f, dest=f.wander_to):
                return True
            nf = 1 if d > 0 else -1
            if nf != f.face and abs(f.vx) > 120 * K:
                f.skid = 1.0
                self.puff(f.x, f.y, 3, DUST, K, 8)
            f.face = nf
            f.vx = approach(f.vx, f.face * 150 * K * f.per["dash"],
                            1400 * K * dt)

    def _st_carry(self, f, dt, K):
        self.carry_tick(f, dt)
        if not f.carry:
            f.set_state("idle")
            f.goal = self.time + .4
            return
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

    def _st_pogo(self, f, dt, K):
        d = f.wander_to - f.x
        f.face = 1 if d >= 0 else -1
        if (abs(d) < 46 and f.on_ground) or f.st > 9:
            f.set_state("idle")
            f.goal = self.time + random.uniform(.5, 1.4)
        elif f.on_ground:
            # the stick does the walking: one bounce per contact
            f.vy = -820 * K
            f.vx = math.copysign(min(abs(d), 200), d) * K * 1.15
            f.squash = .6
            self.puff(f.x, f.y, 2, DUST, K, 6)

    def _st_skate(self, f, dt, K):
        d = f.wander_to - f.x
        f.face = 1 if d >= 0 else -1
        if (abs(d) < 30 and f.on_ground) or f.st > 8:
            f.vx *= .4
            f.set_state("idle")
            f.goal = self.time + random.uniform(.4, 1.2)
        else:
            f.vx = approach(f.vx, f.face * 330 * K, 900 * K * dt)
            if f.on_ground and random.random() < dt * 1.1:
                f.vy = -560 * K            # ollie, for the fun of it
            if f.on_ground and random.random() < dt * 6:
                self.puff(f.x - f.face * 10, f.y, 1, DUST, K * .7, 4)

    def _st_float(self, f, dt, K):
        # balloon ride: no physics, the string does the flying. Never
        # above oy+120 -- out of sight upward is still out of sight.
        rise = -44 * K if f.y > self.oy + 120 else 0.0
        f.x += (f.vx + math.sin(self.time * 1.1 + f.seedp) * 34 * K) * dt
        f.y += rise * dt + math.sin(self.time * 2.3 + f.seedp) * 10 * K * dt
        f.x = clamp(f.x, self.ox + 40, self.ox + self.W - 40)
        f.on_ground = False
        if self.time > f.goal or f.st > 10:
            self.spark(f.x + 9 * f.sc, f.y - 112 * f.sc, 8, f.color(), 240, K)
            f.vy = 40 * K
            f.set_state("fall")

    def _st_jet(self, f, dt, K):
        # no physics: the pack is the physics. Chases a cruise point,
        # wobbles, and cuts out either on arrival or when the tank
        # (f.goal) runs dry -- the landing is an ordinary fall.
        dx = f.wander_to - f.x
        dy = f.jet_y - f.y
        f.face = 1 if dx >= 0 else -1
        wob = math.sin(self.time * 5 + f.seedp) * 30
        f.vx = approach(f.vx, clamp(dx * 2.0 + wob, -320, 320) * K,
                        700 * K * dt)
        f.vy = approach(f.vy, clamp(dy * 2.0, -260, 260) * K, 900 * K * dt)
        f.x = clamp(f.x + f.vx * dt, self.ox + 40, self.ox + self.W - 40)
        f.y = max(f.y + f.vy * dt, self.oy + 110)
        f.on_ground = False
        if random.random() < dt * 26:
            self.spark(f.x - f.face * 7 * f.sc, f.y - 34 * f.sc, 1,
                       FIRE, 90, K * .6)
        if random.random() < dt * 7:
            self.puff(f.x - f.face * 8 * f.sc, f.y - 28 * f.sc, 1,
                      DUST, K * .5, 4)
        if (abs(dx) < 30 and abs(dy) < 60) or self.time > f.goal or f.st > 9:
            self.puff(f.x, f.y - 30 * f.sc, 3, DUST, K * .7, 8)
            f.set_state("fall")

    def _st_surf(self, f, dt, K):
        si = f.surf_idx
        if si is None or not self.can_move_icons():
            # the ride is tied to the setting; flipping it off mid-surf
            # (or losing the icon) just tips him off where he is
            f.surf_idx = None
            f.set_state("fall")
        else:
            d = f.wander_to - f.x
            f.face = 1 if d >= 0 else -1
            f.x += clamp(d, -190, 190) * K * dt
            f.on_ground = False
            f.vx = f.vy = 0
            f.surf_t += dt
            if f.surf_t >= .12:
                f.surf_t = 0.0
                idx, offx, offy, w, h = si
                try:
                    if not self.move_icon(idx, f.x - w / 2 + offx, f.y + offy):
                        f.surf_idx = None
                except Exception:
                    f.surf_idx = None
            if random.random() < dt * 5:
                self.puff(f.x - f.face * 16, f.y + 8, 1, DUST, K * .7, 5)
            if abs(d) < 24 or f.st > 10:
                f.surf_idx = None
                f.vy = -300 * K
                f.vx = f.face * 120 * K
                f.set_mood("smug")
                f.set_state("fall")

    def _st_ride(self, f, dt, K):
        m = f.mount
        if (m is None or m.hp <= 0 or m not in self.fighters or
                m.state in ("ko", "grabbed", "thrown", "sleep", "fight",
                            "attack", "float", "ride", "surf")):
            self.end_ride(f)
            f.vy = -240 * K
            f.set_state("fall")
        elif self.time > f.goal:
            self.end_ride(f)
            f.vy = -380 * K
            f.vx = f.face * 130 * K
            f.set_state("fall")
        else:
            f.x = m.x
            f.y = m.y - 58 * m.sc
            f.face = m.face
            f.on_ground = False

    def _st_cannonwind(self, f, dt, K):
        f.vx = 0
        d = f.wander_to - f.x
        f.face = 1 if d >= 0 else -1
        if f.st > .7:
            self.boom(f.x + f.face * 26 * f.sc, f.y - 16 * f.sc, 40, K)
            # aimed at where he is going; far means flatter and harder
            f.vx = math.copysign(clamp(abs(d) * 1.15, 420, 1100), d) * K
            f.vy = -clamp(300 + abs(d) * .45, 520, 820) * K
            f.vr = f.face * random.uniform(6, 11)
            f.on_ground = False
            f.stunt = True
            f.set_mood("hyped", quiet=random.random() < .4)
            f.set_state("thrown")

    def _st_fight(self, f, dt, K):
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
            # Breaking off is the nerve trait's one visible moment, so it
            # gets its own line instead of borrowing the generic ouch.
            f.yell("flee", 1.4)
        else:
            d = foe.x - f.x
            f.face = 1 if d >= 0 else -1
            reach = REACH[f.plan] * (.4 + .6 * K)
            if abs(d) > reach - 14:
                # a big gap is a travel problem: sometimes he closes it
                # on wheels or a jet instead of trudging. Landing puts
                # him straight back into the fight -- mode survives.
                if abs(d) > 460 and f.on_ground and random.random() < dt * .5 \
                        and self.joyride(f, dest=foe.x):
                    return True
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

    def _st_hunt(self, f, dt, K):
        t = f.target
        if not t:
            f.set_state("idle")
            f.goal = self.time + .4
        elif f.st > 9:
            f.target = None
            f.set_state("idle")
        elif f.play and f.on_ground and f.plat == ("window", f.play["hwnd"]):
            # the hunt was the way up: standing on the window, he sits down
            self.begin_play(f)
        elif self.navigate(f, dt, K):
            pass                         # walking/jumping still runs normal physics
        else:
            reach = REACH[f.plan] * (.4 + .6 * K)
            d = t["cx"] - f.x
            blocked = self.route_blocked(f, t)
            f.face = 1 if d >= 0 else -1
            if f.on_ground and f.st > .3 and (abs(d) > 520 or t["top"] < f.y - 175) \
                    and random.random() < dt * 2.6:
                self.fire_hook(f, t["cx"], t["top"] - 26)
            elif abs(d) > reach - 20:
                spd = (300 if f.mood == "furious" else 205) * K * f.per["dash"]
                f.vx = approach(f.vx, f.face * spd, 1600 * K * dt)
                # something climbable overhead gets scaled, not bounced
                # at; the leap is kept for the tall, the far, and the
                # characters who were always going to bounce anyway
                if not blocked and t["top"] < f.y - 40 and self.try_climb(f, t):
                    pass
                elif not blocked and f.on_ground and (random.random() < dt * .35 * f.per["hops"] or
                                      (t["top"] < f.y - 70 and f.y - t["top"] >= 170
                                       and random.random() < dt * 3)):
                    f.vy = -880 * K
                    f.set_state("jump")
            elif self.time >= f.atk_cd:
                f.vx = approach(f.vx, 0, 1800 * K * dt)
                if f.play:
                    # within reach but not up top yet: a hook to the edge
                    # instead of a swing at it
                    f.atk_cd = self.time + 1.2
                    if f.on_ground:
                        self.fire_hook(f, f.play["x"], t["top"] - 26)
                else:
                    self.start_attack(f)
            else:
                f.vx = approach(f.vx, 0, 1800 * K * dt)

    def _st_airborne(self, f, dt, K):
        if f.on_ground:
            f.set_state("fight" if f.mode == "fight" and f.foe and f.foe.hp > 0
                        else ("hunt" if f.target else
                              ("walk" if f.play else "idle")))

    def _st_ledge(self, f, dt, K):
        f.vx = f.vy = 0
        if f.st > .5:
            # haul up over the lip. This used to be a spring-jump off the
            # ledge, which read as a pinball, not a person.
            f.ledge_cd = self.time + 1.5   # not the same lip twice running
            f.set_state("climb")

    def _st_climb(self, f, dt, K):
        # hand over hand up the side; physics is off, the wall is the
        # physics. Terrain can shift underneath mid-climb -- the mantle
        # onto empty air just becomes a fall, which reads fine.
        f.vx = f.vy = 0.0
        f.on_ground = False
        f.face = f.climb_side
        lip = f.climb_top + 44 * f.sc
        if f.y > lip:
            # he moves in PULLS: surge while an arm hauls, hang while it
            # reaches for the next hold. A constant glide read as
            # levitation, and the speed is paced so the pinned grips
            # re-grab about twice a second, not in a blur.
            pull = .55 + .9 * max(0.0, math.sin(self.time * 4.4))
            f.y = max(f.y - (45 + 45 * K) * pull * dt, lip)
            if random.random() < dt * 2.5:
                self.puff(f.x + f.face * 8 * f.sc,
                          f.y - 16 * f.sc, 1, DUST, K * .5, 3)
        else:
            # the mantle: up and over in one motion
            f.y = max(f.y - (70 + 80 * K) * dt, f.climb_top)
            f.x = approach(f.x, f.climb_x + f.climb_side * 11,
                           (60 + 40 * K) * dt)
            if f.y <= f.climb_top + .5:
                f.y = f.climb_top
                f.x = f.climb_x + f.climb_side * 11
                f.on_ground = True
                f.squash = .3
                if f.play and f.play["kind"] == "perch":
                    self.begin_play(f)         # a cling that climbed up to sit
                elif f.target:
                    f.set_state("hunt")
                else:
                    f.set_state("idle")
                    f.goal = self.time + .4
        if f.st > 3.5:
            f.set_state("fall")

    # -- on one of your windows --------------------------------------
    def _st_perch(self, f, dt, K):
        p = f.play
        rect = self.terrain.win_rect.get(p["hwnd"]) if p else None
        if not rect:
            self.end_play(f)
            f.set_state("fall")
            return
        l, t, r, b = rect
        p["x"] = clamp(p["x"], l + 30, r - 30)
        f.x, f.y = p["x"], float(t)
        f.vx = f.vy = 0.0
        f.on_ground = False
        if p["phase"] == 0:
            if random.random() < dt * .25:
                f.face = -f.face                   # looking about
            if f.st > 8 and random.random() < dt * .12:
                p["phase"] = 1                     # lie back along the bar
        elif p["phase"] == 1 and f.st > 14 and random.random() < dt * .1:
            p["phase"] = 2                         # and doze off up there
            f.set_mood("asleep", quiet=True)
        if self.time > p["until"]:
            self.end_play(f)
            if f.mood == "asleep":
                f.set_mood("bored", quiet=True)
            f.vx = f.face * 120 * K
            f.vy = -240 * K
            f.set_state("fall")

    def _st_hang(self, f, dt, K):
        p = f.play
        rect = self.terrain.win_rect.get(p["hwnd"]) if p else None
        if not rect:
            self.end_play(f)
            f.set_state("fall")
            return
        l, t, r, b = rect
        hang_y = b + 82 * f.sc                     # hands on the edge, feet here
        k = clamp((self.time - p["t0"]) / .28, 0.0, 1.0)   # the leap for the edge
        p["x"] = clamp(p["x"] + math.sin(self.time * 2.2 + f.seedp) * 12 * dt,
                       l + 30, r - 30)
        f.x = p["x"]
        f.y = lerp(p["from_y"], hang_y, 1 - (1 - k) * (1 - k))
        f.vx = f.vy = 0.0
        f.on_ground = False
        if k >= 1:
            if p["phase"] == 0 and random.random() < dt * .18:
                p["phase"], p["t1"] = 1, self.time # a pull-up
            elif p["phase"] == 1 and self.time - p["t1"] > 1.2:
                p["phase"] = 0
        if self.time > p["until"]:
            self.end_play(f)
            f.vy = 60 * K
            f.set_state("fall")

    def _st_cling(self, f, dt, K):
        p = f.play
        rect = self.terrain.win_rect.get(p["hwnd"]) if p else None
        if not rect:
            self.end_play(f)
            f.set_state("fall")
            return
        l, t, r, b = rect
        S = f.sc
        edge = l if p["side"] == 1 else r
        f.climb_top, f.climb_bot = float(t), float(b)  # follow the window
        f.climb_x, f.climb_side = float(edge), p["side"]
        f.x = edge - p["side"] * 6
        f.face = p["side"]
        f.vx = f.vy = 0.0
        f.on_ground = False
        top = t + 110 * S
        bot = max(top, min(b + 20, self.ground_at(f.x, f.y)))
        k = clamp((self.time - p["t0"]) / .3, 0.0, 1.0)
        if k < 1:
            f.y = lerp(p["from_y"], p["y"], 1 - (1 - k) * (1 - k))
            return
        if p["phase"] == 0:
            if random.random() < dt * .3:
                p["phase"] = random.choice((1, 2, 2))
                p["t1"] = self.time
                p["dir"] = random.choice((-1, 1))
        elif p["phase"] == 1:                      # a peek round the edge
            if self.time - p["t1"] > 1.5:
                p["phase"] = 0
        else:                                      # a few holds up or down
            pull = .55 + .9 * max(0.0, math.sin(self.time * 4.4))
            f.y = clamp(f.y + p["dir"] * (45 + 45 * K) * pull * dt, top, bot)
            if self.time - p["t1"] > 1.6:
                p["phase"] = 0
        p["y"] = f.y
        if self.time > p["until"]:
            if f.y - t < 220 and random.random() < .35:
                # up the rest of the way, and sit on the top
                f.play = {"kind": "perch", "hwnd": p["hwnd"], "x": f.x, "y": None,
                          "side": 0, "until": 0.0, "phase": 0, "t0": self.time,
                          "from_y": f.y}
                f.set_state("climb")
            else:
                self.end_play(f)
                f.vx = -f.face * 90 * K
                f.vy = 40 * K
                f.set_state("fall")

    def _st_knock(self, f, dt, K):
        p = f.play
        rect = self.terrain.win_rect.get(p["hwnd"]) if p else None
        if not rect:
            self.end_play(f)
            f.set_state("idle")
            f.goal = self.time + .3
            return
        l, t, r, b = rect
        edge = l if p["side"] == 1 else r
        f.x = edge - p["side"] * 22
        f.y = self.ground_at(f.x, f.y)
        f.face = p["side"]
        f.vx = f.vy = 0.0
        f.on_ground = True
        # knock, lean, face to the glass, then one shove -- if allowed
        ph = 0 if f.st < 3 else 1 if f.st < 7 else 2 if f.st < 9 else 3
        if ph != p["phase"] and p["phase"] != 4:
            p["phase"] = ph
            if ph == 3:
                if self.nudge_window(p["hwnd"], p["side"] * random.uniform(8, 24), 0):
                    f.chat("shove", 1.4)
                    self.shake(.15, 3 * K)
                else:
                    p["phase"] = 4                 # nothing to push; done
        if ph == 0 and random.random() < dt * 2.5:
            self.puff(edge, f.y - 54 * f.sc, 1, DUST, K * .5, 3)   # knuckles
        if f.st > 10.5 or (p["phase"] == 4 and f.st > 9.4):
            self.end_play(f)
            f.set_state("idle")
            f.goal = self.time + random.uniform(.4, 1.0)

    def _st_wallslide(self, f, dt, K):
        f.vy = min(f.vy, 150 * K)
        if f.on_ground or f.st > 1.4:
            f.set_state("fall")

    def _st_attack(self, f, dt, K):
        f.atk += dt
        k = f.atk / f.atk_dur
        if f.weapon == "minigun":
            if .2 < k * f.atk_dur < f.atk_dur - .2:
                f.burst -= dt
                if f.burst <= 0:
                    f.burst = .07
                    f.aim = math.atan2(self.aim_point(f)[1] - (f.y - 44 * f.sc),
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
        elif not f.fired and k > RELEASE_AT.get(f.weapon, .55):
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

    def _st_hookfire(self, f, dt, K):
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

    def _st_zip(self, f, dt, K):
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

    def _st_taunt(self, f, dt, K):
        f.vx = approach(f.vx, 0, 1400 * K * dt)
        if f.st > 1.5:
            f.set_state("idle")
            f.goal = self.time + .5

    def _st_cursor(self, f, dt, K):
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

    def _st_grabbed(self, f, dt, K):
        f.x = lerp(f.x, f.gx, 1 - pow(.0008, dt))
        f.y = lerp(f.y, f.gy, 1 - pow(.0008, dt))
        f.vx = f.vy = 0
        f.on_ground = False

    def _st_thrown(self, f, dt, K):
        f.tumble += f.vr * dt
        if f.on_ground:
            f.vr = f.tumble = 0
            f.stun = .8
            f.set_state("idle")
            f.goal = self.time + 1.0
            if f.stunt:
                # he launched himself; landing is the good part
                f.stunt = False
                self.puff(f.x, f.y, 4, DUST, K, 10)
                if f.hp > 0:
                    f.set_mood("smug" if random.random() < .6 else "hyped")
            else:
                f.anger = clamp(f.anger + .3 * f.per["grudge"], 0, 1)
                if f.hp > 0:
                    f.set_mood("furious" if random.random() < .62 else "sulking")

    STATES = {
        "sleep": _st_sleep,
        "ko": _st_ko,
        "idle": _st_idle,
        "walk": _st_walk,
        "carry": _st_carry,
        "pogo": _st_pogo,
        "skate": _st_skate,
        "float": _st_float,
        "jet": _st_jet,
        "surf": _st_surf,
        "ride": _st_ride,
        "cannonwind": _st_cannonwind,
        "fight": _st_fight,
        "hunt": _st_hunt,
        "jump": _st_airborne,
        "fall": _st_airborne,
        "ledge": _st_ledge,
        "climb": _st_climb,
        "perch": _st_perch,
        "hang": _st_hang,
        "cling": _st_cling,
        "knock": _st_knock,
        "wallslide": _st_wallslide,
        "attack": _st_attack,
        "hookfire": _st_hookfire,
        "zip": _st_zip,
        "taunt": _st_taunt,
        "cursor": _st_cursor,
        "grabbed": _st_grabbed,
        "thrown": _st_thrown,
    }

    # ==================================================================
    #  physics
    # ==================================================================
    def physics(self, f, dt, gy):
        K = f.K()
        if f.state in ("zip", "grabbed", "ledge", "sleep",
                       "float", "ride", "surf", "jet", "climb",
                       "perch", "hang", "cling", "knock"):
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
        # Judged from the centre crossing the edge, and the clock DRAINS
        # rather than resets when he pokes back in: a duel hopping right on
        # the seam used to reset it on every bounce and hold him out of sight
        # past any limit. A beat of fully visible play still clears it.
        off_side = f.x < self.ox or f.x > self.ox + self.W
        # Unequal displays leave holes inside the virtual bounding box. Count
        # those and below-screen falls too, so they cannot hide a fighter forever.
        off = not any(m[0] <= f.x < m[2] and m[1] <= f.y <= m[3]
                      for m, _work in self.mons)
        f.out = f.out + dt if off else max(0.0, f.out - 4 * dt)
        past = f.x < self.ox - WRAP or f.x > self.ox + self.W + WRAP
        if past or (off_side and f.out > OUT_MAX):
            self.puff(f.x, f.y - 20 * f.sc, 4, DUST, K, 10)
            f.x = (self.ox + self.W - 24) if f.x < self.ox else (self.ox + 24)
            f.out = 0.0
            self.puff(f.x, f.y - 20 * f.sc, 4, DUST, K, 10)
        elif f.out > OUT_MAX:
            # A hole between monitors is not a side to wrap around. Put him on
            # the nearest real display and stop any invisible downward fall.
            mon, work = self.monitor_at(f.x, f.y)
            f.x = clamp(f.x, mon[0] + 24, mon[2] - 24)
            f.y = clamp(f.y, mon[1] + 40, work[3])
            f.vy = min(f.vy, 0)
            f.out = 0.0
        if f.y < self.oy - CEILING:
            f.y, f.vy = self.oy - CEILING, abs(f.vy) * .3

        # Crossing a horizontal seam (or wrapping) changes the floor in this
        # very frame. Use the pre-fall height to retain the upper display's floor
        # when a fast descent crosses a stacked-monitor boundary.
        gy = self.ground_at(f.x, prev_y)

        f.on_ground = False
        f.plat = None
        landed_on = (gy, "floor", None) if f.vy >= 0 and f.y >= gy else None
        for x0, x1, py, kind, key in self.terrain.platforms + self.motion.platforms():
            if f.x < x0 - 6 or f.x > x1 + 6:
                continue
            if f.vy >= 0 and prev_y <= py + 2 and f.y >= py \
                    and (landed_on is None or py < landed_on[0]):
                # Icons arrive before windows, not in collision order. The
                # highest crossed surface wins, including the work-area floor.
                landed_on = (py, kind, key)
        if landed_on is not None:
            f.y, kind, key = landed_on
            f.vy, f.on_ground, f.plat = 0, True, (kind, key)

        if f.on_ground and was_air:
            if fall_speed > 520 * K:
                f.squash = 1.0
                self.puff(f.x, f.y, 5, DUST, K, 12)
                self.shake(.08, 2.5 * K)
            elif fall_speed > 200 * K:
                f.squash = .5
                self.puff(f.x, f.y, 2, DUST, K, 8)
            if f.state in ("fall", "jump", "wallslide") and f.state != "thrown":
                # a landing on the way to a window carries on walking there
                f.set_state("fight" if f.mode == "fight" and f.foe and f.foe.hp > 0
                            else ("hunt" if f.target else
                                  ("walk" if f.play else "idle")))
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
                        # hang OUTSIDE the edge, same side the climb expects,
                        # or the climb pose puts his hands behind his back
                        f.x = edge - (6 if edge == x0 else -6)
                        f.y = py + 44 * f.sc
                        f.vx = f.vy = 0
                        f.face = 1 if edge == x0 else -1
                        # the ledge resolves by climbing now, so it needs to
                        # know what it caught
                        f.climb_top = py
                        f.climb_bot = py + 70
                        f.climb_x = edge
                        f.climb_side = f.face
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
    def terrain_changed(self):
        """Re-point everyone at the terrain as it is now: targets by key, and
        anyone standing on a window that got dragged rides along. `moved` is
        consumed here, so a scan that changed nothing moves nobody twice."""
        self.social.on_windows_changed(self._social_windows, self.terrain.win_rect)
        self._social_windows = dict(self.terrain.win_rect)
        moved, self.terrain.moved = self.terrain.moved, {}
        new = {(t["kind"], t["key"]): t for t in self.terrain.targets()}
        for f in self.fighters:
            if f.plat and f.plat[0] == "window" and f.plat[1] in moved \
                    and f.state not in PLAY_STATES:
                dx, dy = moved[f.plat[1]]
                f.x += dx
                f.y += dy
            if f.play:
                # whoever is on a window, or on his way to one, follows it;
                # a window that has gone is let go of
                hw = f.play["hwnd"]
                if hw in moved:
                    dx, dy = moved[hw]
                    f.play["x"] += dx
                    if f.state in PLAY_STATES:
                        f.x += dx
                        f.y += dy
                elif hw not in self.terrain.win_rect:
                    was = f.state in PLAY_STATES
                    self.end_play(f)
                    if was:
                        f.set_state("fall")
            if f.target:
                key = (f.target["kind"], f.target["key"])
                f.target = new.get(key)
                if f.target is None and f.state == "hunt":
                    f.set_state("idle")
                    f.goal = self.time + .3

    def update_environment(self):
        """Sample the desktop once per rendered frame, outside physics catch-up."""
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
            self.terrain_changed()
        if self.terrain.poll():
            self.terrain_changed()        # a background scan just landed
        occupied = {f.play["hwnd"] for f in self.fighters if f.play}
        occupied.update(f.plat[1] for f in self.fighters
                        if f.plat and f.plat[0] == "window")
        if self.terrain.track_windows(occupied, self.time):
            self.terrain_changed()
        if CFG["react_to_windows"] and not self.asleep \
                and self.time - self.magnet_at > 1.6:
            self.magnet_at = self.time
            self.window_magnet()

        if CFG["react_to_windows"] and not self.asleep:
            fg = foreground_window()
            if fg and fg[1] != (self.fg[1] if self.fg else None):
                self.fg = fg
                awake = [f for f in self.fighters
                         if f.state in ("idle", "walk", "taunt", "hunt")
                         or f.state in PLAY_STATES]
                if awake and fg[0] and random.random() < .55:
                    f = random.choice(awake)
                    if self.time - f.said > 5:
                        f.said = self.time
                        f.say(line_for_title(f, fg[0]), 2.0)
                    r2 = random.random()
                    if r2 < .30 and self.combat_allowed(f):
                        for t in self.terrain.targets():
                            if t["kind"] == "window" and t["key"] == fg[1]:
                                f.target = t
                                f.hits = 0
                                f.plan = plan_weapon(f.per)
                                f.set_state("hunt")
                                break
                    elif r2 < .80:
                        # the window you just switched to gets a visitor
                        self.visit_window(f, fg[1])
            self.watch.note_focus(fg[1] if fg else None, self.time)
            ev = self.watch.pick(self.time, fg[0] if fg else "",
                                 self.time - self.awake_since)
            if ev:
                # "fight" is circling between swings, which is fine to talk
                # through. Without it, a crowd all brawling at once means the
                # remark never finds a speaker and the feature goes silent.
                # ...and so is sitting on the window in question: with the
                # magnet drawing them there, everyone on it counted as busy
                # and the remark never found a mouth
                free = [f for f in self.fighters
                        if f.state in ("idle", "walk", "taunt", "hunt", "fight")
                        or f.state in PLAY_STATES]
                if free:
                    f = random.choice(free)
                    f.said = self.time
                    f.yell(ev, 2.6)
                else:
                    self.watch.unsay(ev)   # try again once someone is free

    def update(self, dt):
        self.time += dt
        if not getattr(self, "_frame_environment_done", False):
            self.update_environment()
            if getattr(self, "_icon_batch", None) is not None:
                self._frame_environment_done = True
        for engine in (self.arsenal, self.motion, self.social):
            engine.update(dt)
        for f in self.fighters:
            self.update_fighter(f, dt)
        self.projectiles(dt)
        self.traps_tick(dt)
        self.fx_tick(dt)

    @staticmethod
    def segment_box(x0, y0, x1, y1, left, top, right, bottom):
        """First contact along a frame's travel, or None when it misses."""
        enter, leave = 0.0, 1.0
        # Clip the segment against each pair of parallel sides. The overlap
        # of both intervals is precisely the time spent inside the box.
        for start, delta, low, high in ((x0, x1 - x0, left, right),
                                         (y0, y1 - y0, top, bottom)):
            if abs(delta) < 1e-12:
                if start < low or start > high:
                    return None
                continue
            a, b = (low - start) / delta, (high - start) / delta
            if a > b:
                a, b = b, a
            enter, leave = max(enter, a), min(leave, b)
            if enter > leave:
                return None
        return enter

    def floor_contact(self, x0, y0, x1, y1):
        """First floor contact across monitor seams along this frame's path."""
        cuts = [0.0, 1.0]
        dx, dy = x1 - x0, y1 - y0
        if dx:
            for mon, _work in self.mons:
                for edge in (mon[0], mon[2]):
                    at = (edge - x0) / dx
                    if 0.0 < at < 1.0:
                        cuts.append(at)
        cuts = sorted(set(cuts))
        # Each X interval stays in one monitor column. Retain the starting Y
        # so a fast fall cannot skip an upper monitor into one stacked below.
        for lo, hi in zip(cuts, cuts[1:]):
            gy = self.ground_at(x0 + dx * (lo + hi) / 2, y0)
            if y0 + dy * lo >= gy:
                return lo, gy
            if dy > 0 and y0 + dy * hi >= gy:
                return clamp((gy - y0) / dy, lo, hi), gy
        return None

    def projectiles(self, dt):
        # Rebuilt rather than removed from in place: list.remove() on a dict is a
        # linear scan with a full dict comparison at every step, and a minigun
        # burst plus a bomb can retire a dozen shots in one frame.
        live = []
        bounds = self.terrain.bounds
        for s in self.shots:
            # A malformed motion value must not poison collision math or keep
            # an invisible shot alive. Cleanup is not an impact.
            if not all(math.isfinite(s[name]) for name in
                       ("x", "y", "vx", "vy", "g", "life")):
                continue
            x0, y0 = s["x"], s["y"]
            s["life"] -= dt
            s["vy"] += s["g"] * dt
            s["x"] += s["vx"] * dt
            s["y"] += s["vy"] * dt
            k = s["owner"].K()
            sx, sy = s["x"], s["y"]
            hit_t = hit_f = None
            first = 1.0
            tgt = s.get("tgt")
            if not s.get("pierce") or tgt is not None:
                for cx, cy, hw, hh, t in bounds:
                    if s.get("pierce") and (t["kind"], t["key"]) != tgt:
                        continue
                    at = self.segment_box(x0, y0, sx, sy, cx - hw, cy - hh,
                                          cx + hw, cy + hh)
                    if at is not None and at <= first:
                        first, hit_t = at, t
            for f in self.fighters:
                if f is s["owner"] or f.hp <= 0 or getattr(f, "motion_dodging", False):
                    continue
                at = self.segment_box(x0, y0, sx, sy, f.x - 18 * f.sc,
                                      f.y - 80 * f.sc, f.x + 18 * f.sc, f.y + 8)
                if at is not None and at <= first:
                    first, hit_f, hit_t = at, f, None
            gy = self.ground_at(sx, y0)
            contact = self.floor_contact(x0, y0, sx, sy)
            floor = contact is not None
            if floor:
                at, floor_y = contact
                if at < first or (hit_t is None and hit_f is None):
                    first, hit_t, hit_f = at, None, None
                    gy = floor_y
                else:
                    floor = False
            if hit_t or hit_f or floor:
                # Stop at first contact, so a later target in this frame
                # cannot take the hit or move the explosion past its victim.
                sx, sy = lerp(x0, sx, first), lerp(y0, sy, first)
                s["x"], s["y"] = sx, sy
                if not floor:
                    gy = self.ground_at(sx, y0)
            if s["k"] in ("laser", "pellet"):
                s["trail"].append((s["x"], s["y"]))
                if len(s["trail"]) > (5 if s["k"] == "laser" else 3):
                    s["trail"].pop(0)
            elif s["k"] == "bomb":
                s["spin"] += dt * 9
            elif s["k"] == "rocket":
                s["spin"] = math.atan2(s["vy"], s["vx"])
                self.puff(s["x"], s["y"], 1, "#C9D3F0", k * .8, 3)
            elif s["k"] == "harpoon":
                s["spin"] = math.atan2(s["vy"], s["vx"])
            elif s["k"] in ("wballoon", "blackhole", "peel", "spring",
                            "anvil", "piano"):
                s["spin"] += dt * (9 if s["k"] in TRAPS else 3)

            if hit_f and hit_f.state == "attack" and hit_f.weapon == "pan" \
                    and .1 < hit_f.atk < hit_f.atk_dur \
                    and (s["vx"] > 0) != (hit_f.face > 0) \
                    and s["k"] in ("arrow", "laser", "pellet", "confetti",
                                   "harpoon", "magnet"):
                # Reflection transfers ownership at the contact point; the
                # return trip can hit the original shooter on a later frame.
                s["vx"] = -s["vx"] * .92
                s["vy"] = -abs(s["vy"]) * .4 - 40 * hit_f.K()
                s["owner"] = hit_f
                s["pierce"], s["tgt"] = True, None
                s["life"] = max(s["life"], .8)
                self.spark(sx, sy, 6, STEEL, 260, hit_f.K())
                self.shake(.08, 3 * hit_f.K())
                live.append(s)
                continue
            outside = (not (self.ox - 60 < sx < self.ox + self.W + 60)
                       or sy > self.oy + self.H + 60
                       or (sy < self.oy - 60 and s["k"] not in ARC_PROJECTILES))
            if outside:
                # Leaving the desktop must not detonate a rocket, shove icons
                # or teleport a falling trap onto a floor it never reached.
                continue
            fused = s["k"] in FUSED_PROJECTILES
            stationary = abs(s["vx"]) + abs(s["vy"]) + abs(s["g"]) < 1e-6
            if not fused and stationary and s["life"] <= 0 and not (hit_t or hit_f or floor):
                continue
            # Ordinary rounds finish their visible flight. Their short old
            # timers limited small gremlins to a few hundred pixels and also
            # made elevated arrows/balloons disappear before landing. Only
            # actual explosive fuses may end a moving shot in mid-air.
            fuse_expired = fused and s["life"] <= 0
            if not (hit_t or hit_f or floor or fuse_expired):
                live.append(s)
                continue

            if s["k"] == "blackhole":
                # implodes: everything nearby is pulled IN, icons included --
                # blast_icons with a negative power walks its push backwards
                self.booms.append({"x": sx, "y": min(sy, gy), "r": 90 * k,
                                   "t": 0, "life": .55, "in": True})
                self.spark(sx, min(sy, gy), 16, "#B79BFF", 300, k)
                self.shake(.3, 9 * k)
                rad = 150 * (.5 + .5 * k)
                self.blast_icons(sx, min(sy, gy), rad * 2.2,
                                 -70 * (.5 + .5 * k))
                for cx2, cy2, _hw, _hh, t in bounds:
                    if (cx2 - sx) ** 2 + (cy2 - sy) ** 2 < rad * rad:
                        self.hit_target(s["owner"], t, sx, sy)
                        break
                for f in self.fighters:
                    if f is s["owner"] or f.hp <= 0:
                        continue
                    if dist(sx, sy, f.x, f.y - 30 * f.sc) < rad:
                        self.hit_fighter(s["owner"], f, 8)
                        f.vx = (1 if sx > f.x else -1) * 300 * f.K()
            elif s["k"] in ("bomb", "rocket"):
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
            elif s["k"] in DROPPERS:
                self.puff(sx, min(sy, gy), 8, DUST, k, 14)
                self.shake(.22, 8 * k)
                self.blast_icons(sx, min(sy, gy), 90, 40 * (.5 + .5 * k))
                if hit_f:
                    self.hit_fighter(s["owner"], hit_f,
                                     24 if s["k"] == "anvil" else 20)
                    hit_f.squash = 1.3          # flattened, cartoon-law
                elif hit_t:
                    self.hit_target(s["owner"], hit_t, sx, sy)
            elif s["k"] in TRAPS:
                # wherever it stops, it becomes a ground prop and waits
                lx = clamp(sx, self.ox + 30, self.ox + self.W - 30)
                self.traps.append({"k": s["k"], "x": lx,
                                   "y": self.ground_at(lx, y0), "owner": s["owner"],
                                   "t": 0.0, "life": 26.0, "arm": .4})
                del self.traps[:-12]      # a floor of peels, not a carpet
                self.puff(lx, self.ground_at(lx, y0), 2, DUST, k, 6)
            elif s["k"] == "wballoon":
                if hit_f:
                    self.hit_fighter(s["owner"], hit_f, 3)
                elif hit_t:
                    self.hit_target(s["owner"], hit_t, sx, sy)
                self.puff(sx, min(sy, gy), 10, WATER, k, 16)
                self.spark(sx, min(sy, gy), 8, WATER, 260, k)
                rad = 90 * (.5 + .5 * k)
                for f in self.fighters:
                    # a soaking is not damage, it is a mood
                    if f is not s["owner"] and f.hp > 0 and \
                            dist(sx, sy, f.x, f.y - 30 * f.sc) < rad:
                        f.anger = 0.0
                        f.set_mood("sulking")
                if self.stains:
                    # a soaking also mops the floor
                    self.stains = [st for st in self.stains
                                   if dist(sx, sy, st["x"], st["y"]) > rad]
            elif hit_f:
                self.hit_fighter(s["owner"], hit_f,
                                 {"arrow": 10, "laser": 13, "pellet": 4,
                                  "harpoon": 8, "magnet": 6,
                                  "confetti": 1}.get(s["k"], 8))
                if s["k"] == "confetti":
                    # ammunition is a mood: whatever he was feeling, now he
                    # is having a wonderful time
                    hit_f.anger = max(0.0, hit_f.anger - .5)
                    hit_f.set_mood("hyped")
                    self.spark(sx, sy, 10, random.choice(CONFETTI_COLS), 240, k)
                elif s["k"] in PULLERS:
                    # hit_fighter knocked him away; the whole point of these
                    # is the opposite, so the pull overrides it
                    o = s["owner"]
                    hit_f.vx = (1 if o.x > hit_f.x else -1) * \
                        (330 if s["k"] == "harpoon" else 240) * hit_f.K()
                    hit_f.vy = -140 * hit_f.K()
            elif hit_t:
                self.hit_target(s["owner"], hit_t, sx, sy)
                self.spark(sx, sy, 8,
                           LASER if s["k"] in ("laser", "pellet") else ROPE, 240, k)
                if s["k"] == "magnet" and hit_t["kind"] == "icon":
                    self.yank_icon(hit_t, s["owner"].x)
                # a bullet knocks one aside rather than clearing the area, and
                # is throttled so a minigun burst cannot flood Explorer
                elif hit_t["kind"] == "icon" and self.time - self.shove_at > .2:
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
                gy = self.ground_at(p["x"], p["y"])
                if p["y"] > gy:
                    p["y"] = gy
                    p["vy"] *= -.34
                    p["vx"] *= .7
            elif p["k"] == "blood":
                gy = self.ground_at(p["x"], p["y"])
                if p["y"] >= gy:
                    if self.fx_random.random() < .7:
                        self.stains.append({"x": p["x"], "y": gy,
                                            "r": self.fx_random.uniform(1.8, 4.2),
                                            "t": 0.0,
                                            "life": self.fx_random.uniform(8.0, 15.0)})
                    continue                      # the drop is spent
            live.append(p)
        cap = max(40, round(300 * self.effect_detail()))
        if len(live) > cap:
            del live[:len(live) - cap]
        self.parts = live
        self.slashes = self._age(self.slashes, dt)
        self.booms = self._age(self.booms, dt)
        self.bolts = self._age(self.bolts, dt)
        self.stains = self._age(self.stains, dt)
        del self.stains[:-40]         # a crime scene, not a flood
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
        if hasattr(c, "present"):
            c.effects = self.effect_detail() >= .5
            c.present()

    def clear_canvas(self):
        self.canvas.delete("all")
        overlay = getattr(self, "x11_overlay", None)
        if overlay is not None:
            overlay.clear()
        if hasattr(self.canvas, "present"):
            self.canvas.present()
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

    def dot(self, x, y, r, col, outline="", w=1):
        x -= self.ox + self.sx
        y -= self.oy + self.sy
        it = self._item("oval")
        self.canvas.coords(it, x - r, y - r, x + r, y + r)
        key = (col, outline, w)
        if self._opt.get(it) != key:
            self._opt[it] = key
            self.canvas.itemconfigure(it, fill=col, outline=outline, width=w,
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
        return it

    def box(self, x0, y0, x1, y1, fill, outline="", w=1):
        ox, oy = self.ox + self.sx, self.oy + self.sy
        self._rect(x0 - ox, y0 - oy, x1 - ox, y1 - oy, fill, outline, w)

    def text(self, x, y, txt, col, font, backing=True):
        it = self._item("text")
        self.canvas.coords(it, x, y)
        key = (txt, col, font)
        if self._opt.get(it) != key:
            self._opt[it] = key
            self.canvas.itemconfigure(it, text=txt, fill=col, font=font,
                                      anchor="w", state="normal")
        if not IS_WINDOWS and backing and txt:
            # X11 uses a text bounding shape. Make that area an intentional,
            # contrasting label plate rather than exposing the canvas key colour.
            bb = self.canvas.bbox(it)
            if bb:
                red, green, blue = self.canvas.winfo_rgb(col)
                light_text = (.2126 * red + .7152 * green + .0722 * blue) > 32767
                fill = "#0C1024" if light_text else "#E6ECFF"
                plate = self._rect(bb[0] - 3, bb[1] - 2, bb[2] + 3, bb[3] + 2,
                                   fill, "", 0)
                self.canvas.tag_lower(plate, it)
        return it

    def draw(self):
        self._frame_begin()
        self.sx = self.sy = 0.0
        if self.shake_t > 0:
            m = self.shake_m * (self.shake_t / .4)
            self.sx, self.sy = self.fx_random.uniform(-m, m), self.fx_random.uniform(-m, m)

        if DEBUG:
            self.layer("dbg")
            for x0, x1, py, kind, key in self.terrain.platforms:
                self.line((x0, py, x1, py), "#3CE0A0" if kind == "icon" else "#5CA8FF", 2)
            for mon, work in self.mons:
                self.line((work[0], work[3], work[2], work[3]), "#FF5B47", 2)

        self.layer("gore")
        for st in self.stains:
            fade = clamp((st["life"] - st["t"]) / 3.0, 0.0, 1.0)
            self.dot(st["x"], st["y"] - 1, st["r"] * (.5 + .5 * fade), BLOODC[1])

        self.layer("trap")
        for tr in self.traps:
            tx, ty = tr["x"], tr["y"]
            if tr["k"] == "peel":
                self.line((tx - 8, ty - 1, tx - 3, ty - 6, tx + 2, ty - 2,
                           tx + 8, ty - 6), "#FFE97A", 3)
            else:
                zig = [tx - 8, ty]
                for i in range(4):
                    zig += [tx - 5 + i * 3.4, ty - (9 if i % 2 == 0 else 4)]
                zig += [tx + 8, ty]
                self.line(zig, GUNMETAL, 2)
                self.line((tx - 10, ty - 11, tx + 10, ty - 11), STEEL, 3)

        self.layer("boom")
        for b in self.booms:
            k = b["t"] / b["life"]
            if b.get("in"):
                # a blackhole implodes: the ring runs inward and the core
                # darkens, the reverse of every other bang on the screen
                self.ring(b["x"], b["y"], max(3, b["r"] * (1.3 - k * 1.15)),
                          "#B79BFF", max(1, int(5 * (1 - k)) + 1))
                self.dot(b["x"], b["y"], 7 * (1 - k) + 2, "#1A1030")
                continue
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
            elif s["k"] == "confetti":
                self.layer("shotd")
                self.dot(s["x"], s["y"], max(1.6, 2.6 * k), s.get("col", ROPE))
            elif s["k"] == "wballoon":
                self.layer("shotd")
                self.dot(s["x"], s["y"], max(3, 5.5 * k), WATER)
                self.dot(s["x"] - 2, s["y"] - 2, max(1, 1.6 * k), "#DFF1FF")
            elif s["k"] == "harpoon":
                o = s["owner"]
                a = s["spin"]
                dx, dy = math.cos(a) * 10, math.sin(a) * 10
                self.layer("shot")
                # the rope back to whoever fired it is the whole joke
                self.line((o.x + o.face * 20 * o.sc, o.y - 44 * o.sc,
                           s["x"] - dx, s["y"] - dy), ROPE, 1)
                self.line((s["x"] - dx, s["y"] - dy, s["x"] + dx, s["y"] + dy),
                          STEEL, 2)
                self.layer("shotd")
                self.dot(s["x"] + dx, s["y"] + dy, 2.4, STEEL)
            elif s["k"] == "magnet":
                self.layer("shotd")
                self.dot(s["x"], s["y"], max(2.4, 4 * k), "#E05A3A")
                self.dot(s["x"], s["y"], max(1.2, 2 * k), STEEL)
            elif s["k"] == "blackhole":
                self.layer("shotd")
                self.dot(s["x"], s["y"], max(3, 5 * k), "#1A1030")
                self.layer("shot")
                self.ring(s["x"], s["y"], max(4, 7 * k), "#B79BFF", 1)
            elif s["k"] in ("anvil", "piano"):
                self.layer("shot")
                gy2 = self.ground_at(s["x"], s["y"])
                # the landing spot telegraphs itself; the dread is the point
                self.ring(s["x"], gy2 - 4, 10 + 8 * k, "#8FA0CC", 2)
                x, y = s["x"], s["y"]
                if s["k"] == "anvil":
                    self.box(x - 9 * k - 2, y - 7 * k, x + 9 * k + 2, y, "#39415F")
                    self.box(x - 5 * k, y - 12 * k, x + 5 * k, y - 7 * k, "#39415F")
                else:
                    self.box(x - 12 * k - 2, y - 10 * k, x + 12 * k + 2, y, "#20263F")
                    self.box(x - 12 * k - 2, y - 3 * k, x + 12 * k + 2, y, "#E6ECFF")
            elif s["k"] in ("peel", "spring"):
                self.layer("shotd")
                col = "#FFE97A" if s["k"] == "peel" else GUNMETAL
                a = s["spin"]
                dx, dy = math.cos(a) * 5, math.sin(a) * 5
                self.layer("shot")
                self.line((s["x"] - dx, s["y"] - dy, s["x"] + dx, s["y"] + dy),
                          col, 3)
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
            # Name the one under the cursor. Ten of them, and the halo only
            # says who once you have learned the colours.
            name = "the " + self.hover.kind
            self.text(self.hover.x - self.ox - self.sx - len(name) * 3.4,
                      self.hover.y - self.oy - self.sy + 16,
                      name, col, ("Segoe UI", 10, "bold"))

        for i, f in enumerate(self.fighters):
            self.draw_fighter(f, i)
        for i, f in enumerate(self.fighters):
            self.draw_overlay(f, i)
        self.motion.draw()
        self.arsenal.draw()
        self.social.draw()
        self._frame_end()
        if self.x11_overlay is not None:
            self.x11_overlay.present(self.fighters, self.ox, self.oy)

    # ---- the figure ------------------------------------------------------
    def frame(self, f):
        """Body-local units to the screen: the way he faces, his size, the
        landing squash and the tumble. One function for the drawing and for
        muzzle(), so a round leaves the weapon as it is actually drawn."""
        S = f.sc
        sqx = 1 + f.squash * .22
        sqy = 1 - f.squash * .28
        fx, fy = f.face * S * sqx, S * sqy
        ca, sa = math.cos(f.tumble), math.sin(f.tumble)

        def P(lx, ly):
            X, Y = lx * fx, ly * fy
            return f.x + X * ca - Y * sa, f.y + X * sa + Y * ca
        return P

    def attack_pose(self, f):
        """The stance for this weapon at this moment of the swing:
        (px, py, lean, fL, fR, hL, hR), body-local. Shared by draw_fighter
        and muzzle(): the two used to be separate arithmetic, and every barrel
        sat a few pixels from where its rounds appeared."""
        k = clamp(f.atk / f.atk_dur, 0, 1)
        aimL = math.atan2(math.sin(f.aim), math.cos(f.aim) * f.face)
        px, py, lean = 0.0, -30, .12
        fL, fR = (-12, 0), (14, 0)
        w = f.weapon
        release = RELEASE_AT.get(w, .55)

        def ease(t):
            t = clamp(t, 0.0, 1.0)
            return t * t * (3 - 2 * t)

        # Recoil rises and settles continuously after the unchanged release
        # point. It moves the shared hand pose, so the barrel stays attached.
        recoil_t = clamp((k - release) / .24, 0.0, 1.0)
        recoil = math.sin(math.pi * recoil_t) * (1 - recoil_t) ** .35
        if w in ("sword", "fish", "pan"):
            wind_end, swing_end = release - .14, release + .16
            if k < wind_end:
                u = ease(k / wind_end)
                sw, lean = lerp(-2.05, -2.65, u), lerp(-.04, -.18, u)
            elif k < swing_end:
                u = ease((k - wind_end) / (swing_end - wind_end))
                sw, lean = lerp(-2.65, .95, u), lerp(-.18, .30, u)
            else:
                u = ease((k - swing_end) / (1 - swing_end))
                sw, lean = lerp(.95, .55, u), lerp(.30, .14, u)
            hR = (math.cos(sw) * 30 + 8, math.sin(sw) * 30 - 48)
            hL = (-14, -44)
        elif w == "chainsaw":
            r = 30 + math.sin(self.time * 26) * 2
            hR = (math.cos(aimL) * r + 6, -44 + math.sin(aimL) * r)
            hL = (math.cos(aimL) * 16 - 6, -40 + math.sin(aimL) * 16)
            lean = .22
        elif w == "bow":
            draw = ease(k / release) if k < release else 1 - ease((k - release) / .10)
            hL = (math.cos(aimL) * 33 + 4, -45 + math.sin(aimL) * 33)
            hR = (math.cos(aimL) * (19 - draw * 13) + 4,
                  -45 + math.sin(aimL) * (19 - draw * 13))
        elif w in ("blaster", "lightning", "confetti", "harpoon", "magnet",
                   "boomerang", "bubble", "freeze", "swap", "glove", "rubber", "foam"):
            kick = -7 * recoil
            hR = (math.cos(aimL) * (35 + kick) + 4, -44 + math.sin(aimL) * (35 + kick))
            hL = (math.cos(aimL) * 20 - 3, -42 + math.sin(aimL) * 20)
        elif w in ("rocket", "minigun"):
            rec = (math.sin(self.time * 40) * 3 * ease(f.atk / .2)
                   if w == "minigun" else 9 * recoil)
            hR = (math.cos(aimL) * (34 - rec) + 6, -46 + math.sin(aimL) * (34 - rec))
            hL = (math.cos(aimL) * 14 - 8, -36 + math.sin(aimL) * 14)
            lean = .18
        else:  # bomb and the rest of the thrown things: up and over, clear of his own head
            if k < .55:
                u = ease(k / .55)
                hR = (lerp(8, -30, u), lerp(-48, -58, u))
                lean = lerp(.10, -.16, u)
            else:
                u = ease((k - .55) / .45)
                hR = (lerp(-30, 42, u), lerp(-58, -56, u) - 16 * math.sin(math.pi * u))
                lean = lerp(-.16, .30, u)
            hL = (-14, -42)
        return px, py, lean, fL, fR, hL, hR

    def raw_pose(self, f):
        """Unblended body-local pose, including exact foot and hand contacts."""
        for name in ("motion", "social"):
            engine = getattr(self, name, None)
            pose = engine.pose(f) if engine is not None else None
            if pose is not None:
                return pose
        S, st, K = f.sc, f.state, f.K()
        # Negative gait phase plants the supporting foot as the body advances.
        ph = -f.walk
        px, py, lean, tilt = 0.0, -30.0, 0.0, 0.0
        fL, fR = (-5.0, 0.0), (6.0, 0.0)
        hL, hR = (-9.0, -38.0), (9.0, -38.0)

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
        elif st in ("climb", "cling"):
            # Hands GRAB. Each grip is a world-space hold on the edge line,
            # quantized so it stays planted while the body rises and then
            # snaps to the next hold -- offset half a step so the arms
            # alternate. Both clamp at the lip, so near the top he is
            # visibly hanging off the icon's top edge before the mantle.
            # (Everything swinging on one shared sine read as doing the worm.)
            py, lean = -28, .34
            px = -3                                    # hips out, chest to the wall
            # clamped hard: the fields describe a wall an arm's length away,
            # and garbage in them must bend the pose, not fling the joints
            ex = clamp((f.climb_x - f.x) / (f.face * S), 4, 18)
            step = 34.0 * S
            # grips ABOVE the head, past the edge line onto the face -- the
            # ik straightens the arm to reach them, which is the whole
            # hanging-on silhouette. Chest-height grips read as hugging.
            bot = f.climb_bot - 6
            gl = clamp(math.floor((f.y - 96 * S) / step) * step,
                       f.climb_top, bot)
            gr = clamp(math.floor((f.y - 78 * S) / step + .5) * step,
                       f.climb_top, bot)
            hL = (ex + 2, clamp((gl - f.y) / S, -100, 6))
            hR = (ex + 4, clamp((gr - f.y) / S, -100, 6))
            fstep = 30.0 * S
            flw = clamp(math.floor((f.y - 4 * S) / fstep) * fstep,
                        f.climb_top + 8, f.climb_bot + 16)
            frw = clamp(math.floor((f.y + 8 * S) / fstep + .5) * fstep,
                        f.climb_top + 8, f.climb_bot + 16)
            fL = (ex + .5, clamp((flw - f.y) / S, -34, 2))
            fR = (ex + 2, clamp((frw - f.y) / S, -34, 2))
            if st == "cling" and f.play and f.play.get("phase") == 1:
                tilt = .5                              # the peek round the edge
        elif st == "perch":
            ph = f.play.get("phase", 0) if f.play else 0
            k = f.st * 3
            if ph == 0:
                # sat on the edge, legs over the front, hands beside the hips
                py, lean = -8, -.06
                fL = (4, 12 + 3 * max(0.0, math.sin(k)))
                fR = (11 + 3 * math.sin(k), 15 - 4 * max(0.0, math.sin(k + 1.3)))
                hL, hR = (-9, -6), (9, -6)
                if f.emote_t > 0 and f.emote:
                    hR = (15, -40 + math.sin(self.time * 9) * 4)
            elif ph == 1:
                # lying back along the bar, hands behind the head
                py, lean, tilt = -8, -1.15, .1
                fL, fR = (6, 12), (13, 14)
                hL, hR = (14, -14), (10, -6)
            else:
                # dozed off up there
                py, lean, tilt = -8, -.9, .5
                fL, fR = (5, 13), (12, 15)
                hL, hR = (2, -12), (10, -4)
        elif st == "hang":
            ph = f.play.get("phase", 0) if f.play else 0
            sw = math.sin(self.time * 2.2 + f.seedp)
            py = -30 - (18 if ph == 1 else 0)         # the pull-up lifts the hips
            lean = .18 * sw
            fL = (-4 + 5 * sw, 0)
            fR = (5 + 5 * sw, 1)
            hL, hR = (-7, -82), (7, -82)              # both hands on the edge
        elif st == "knock":
            ph = f.play.get("phase", 0) if f.play else 0
            py = -30
            fL, fR = (-7, 0), (7, 0)
            hL = (-11, -36)
            if ph == 0:
                hR = (16, -54 + 6 * math.sin(f.st * 9))       # knuckles on the glass
            elif ph == 1:
                lean, tilt = .12, -.1                          # leaning, ankles crossed
                hR = (18, -46)
                fL, fR = (-2, 0), (9, 0)
            elif ph == 2:
                px, tilt = 6, .25                              # face to the glass
                hL, hR = (10, -40), (14, -42)
            else:
                lean = .3                                      # the shove
                fL, fR = (-12, 0), (4, 0)
                hL, hR = (16, -44), (18, -40)
        elif st == "carry":
            bob = math.sin(ph) * 2
            stride = 12
            fL = (math.cos(ph) * stride, -max(0, math.sin(ph)) * 7)
            fR = (math.cos(ph + math.pi) * stride, -max(0, math.sin(ph + math.pi)) * 7)
            py, lean = -30 - abs(bob) * .4, -.06
            hL, hR = (-6, -74), (7, -76)
        elif st == "float":
            k2 = math.sin(self.time * 2 + f.seedp)
            py, lean = -32, .04
            fL, fR = (-4 + k2 * 2, 6), (7, 10 - k2 * 2)   # legs dangle
            hL, hR = (-8, -40), (7, -84)                  # one hand on the string
        elif st == "pogo":
            c = 1 if f.on_ground else 0
            py = -26 - (0 if c else 6)
            fL, fR = (-3, -6 + c * 6), (5, -6 + c * 6)
            hL, hR = (-9, -52), (11, -52)                 # both hands on the bar
        elif st == "skate":
            py, lean = -30, .26
            k2 = math.sin(ph)
            fL = (-8, -2)
            fR = (10 + (k2 * 6 if f.on_ground else 0), -2)
            hL, hR = (-16, -44), (10, -50)
        elif st == "jet":
            py, lean = -32, .34                           # leaning into it
            fL, fR = (-10, 2), (-4, 5)                    # legs trailing
            hL, hR = (-14, -34), (16, -56)                # one fist forward
        elif st == "surf":
            py, lean = -28, .18
            fL, fR = (-11, -1), (11, -2)
            hL, hR = (-18, -46), (16, -52)                # arms out for balance
        elif st == "ride":
            py = -26
            fL, fR = (8, -12), (12, -8)                   # sat up top, legs forward
            hL, hR = (-6, -50), (8, -52)
        elif st == "cannonwind":
            py, lean = -18, .1
            fL, fR = (-4, -2), (8, -8)
            hL, hR = (-8, -34), (12, -40)
        elif st in ("walk", "hunt", "fight"):
            run = abs(f.vx) > 210 * K
            # The walk is temperament too: dash lengthens the stride, hops
            # puts spring in it, aggro swings the arms. Factors sit near 1 so
            # no gait strains the leg IK -- the grump shuffles, the showoff
            # bounces, the coward scurries, and you can tell from across the
            # screen before anyone says a word.
            stk = .78 + .27 * f.per["dash"]
            lfk = .66 + .50 * f.per["hops"]
            ark = .75 + .30 * f.per["aggro"]
            stride = (19 if run else 13) * stk
            lift = (13 if run else 8) * lfk
            fL = (math.cos(ph) * stride, -max(0, math.sin(ph)) * lift)
            fR = (math.cos(ph + math.pi) * stride, -max(0, math.sin(ph + math.pi)) * lift)
            py = -30 - abs(math.sin(ph)) * 1.6 * lfk
            lean = .30 if run else .10
            hL = (-math.cos(ph) * 13 * ark + 2, -40 + math.sin(ph) * 2)
            hR = (-math.cos(ph + math.pi) * 13 * ark + 2, -40 - math.sin(ph) * 2)
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
            px, py, lean, fL, fR, hL, hR = self.attack_pose(f)
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
            if f.emote_t > 0 and f.emote:
                # talking with the hands: the front one conducts the sentence
                hR = (15, -54 + math.sin(self.time * 9) * 4)

        if f.stun > 0:
            tilt += math.sin(self.time * 30) * .1

        # A brief recoil silhouette follows damage without changing velocity,
        # release timing, or the state machine's recovery duration.
        hurt = max(0.0, 1.0 - (self.time - f.hit_at) / .22) ** 2 * f.hit_power
        if hurt and st in ("thrown", "ko"):
            away = f.hit_side * f.face
            px -= away * 4 * hurt
            lean -= away * .38 * hurt
            tilt += away * .24 * hurt
        return px, py, lean, tilt, fL, fR, hL, hR

    def pose(self, f):
        """Displayed pose shared by the figure and every weapon muzzle."""
        target = self.raw_pose(f)
        previous = f.pose_from if f.pose_to == f.state else None
        duration = .10 if f.state in ("thrown", "ko", "attack") else .16
        elapsed = max(self.time - f.pose_started, f.st)
        if previous is not None and elapsed < duration:
            u = clamp(elapsed / duration, 0.0, 1.0)
            u = u * u * (3 - 2 * u)
            torso = tuple(lerp(previous[i], target[i], u) for i in range(4))
            hands = target[6:]
            if f.state not in ("ledge", "climb", "cling", "hang", "knock",
                               "carry", "float", "pogo", "zip", "parkour"):
                hands = tuple(tuple(lerp(a, b, u) for a, b in zip(old, new))
                              for old, new in zip(previous[6:], target[6:]))
            # Planted feet remain exact; blending them would reintroduce the
            # backwards gait and make a new grip slide along its window.
            target = torso + target[4:6] + hands
        else:
            f.pose_from = None
        f.pose_last, f.pose_last_state, f.pose_time = target, f.state, self.time
        return target

    def draw_fighter(self, f, fi):
        tb, th, tf, ta, tw, twd = self._ftag[fi][:6]
        S, st, K = f.sc, f.state, f.K()
        col = f.color()
        px, py, lean, tilt, fL, fR, hL, hR = self.pose(f)

        P = self.frame(f)
        nx, ny = rot(0, -26, lean)
        neck = (px + nx, py + ny)
        hx2, hy2 = rot(0, -11, lean + tilt)
        head = (neck[0] + hx2, neck[1] + hy2)
        draw_accessory(self, f, head, P)

        lw = max(2, round(4.6 * S))
        # Bend signs are which side the joint bulges towards, in local space
        # where +x is the way he faces. A knee leads and the shin trails it; an
        # elbow trails and the forearm swings ahead of it. Reversed, the knees
        # bow like a bird's and he reads as running the other way.
        kneeL = ik(px, py, fL[0], fL[1], 16, 16, -1)
        kneeR = ik(px, py, fR[0], fR[1], 16, 16, -1)
        elbL = ik(neck[0], neck[1] - 1, hL[0], hL[1], 13, 13, 1)
        elbR = ik(neck[0], neck[1] - 1, hR[0], hR[1], 13, 13, 1)

        dark = f.body()
        self.layer(tb)
        outline = CFG.get("outline", False)
        contrast = FACE if CFG.get("body_theme", "dark") == "dark" else BODY
        if outline:
            # Optional silhouette strokes reuse the body layer and item pool;
            # each is underneath its normal limb, with no extra render pass.
            for pts, width in (( (*P(px, py), *P(*kneeL), *P(*fL)), lw),
                               ( (*P(px, py), *P(*kneeR), *P(*fR)), lw),
                               ( (*P(neck[0], neck[1] - 1), *P(*elbL), *P(*hL)), lw),
                               ( (*P(neck[0], neck[1] - 1), *P(*elbR), *P(*hR)), lw),
                               ( (*P(px, py), *P(*neck)), lw + 1)):
                self.line(pts, contrast, width + max(2, round(3 * S)))
        self.line((*P(px, py), *P(*kneeL), *P(*fL)), dark, lw)
        self.line((*P(px, py), *P(*kneeR), *P(*fR)), dark, lw)
        self.line((*P(neck[0], neck[1] - 1), *P(*elbL), *P(*hL)), dark, lw)
        self.line((*P(px, py), *P(*neck)), dark, lw + 1)

        # A Tk oval carries a fill AND an outline in the same canvas item, so
        # the halo is free: no extra item, no extra frame time. Outlining every
        # limb the same way would need a second line under each one -- measured
        # at ten of them, +168 items and +25% of the frame.
        hxp, hyp = P(*head)
        self.layer(th)
        hw = max(3, round(5.0 * S))
        if f.mood == "furious":
            # The halo seethes. Width, not colour: the shade is his identity
            # and has to stay readable while it pulses.
            hw = max(3, hw + round(1.6 * math.sin(self.time * 16)))
        hw = max(1, round(hw * CFG.get("halo_strength", 1.0)))
        if outline:
            self.dot(hxp, hyp, 11.5 * S + hw / 2 + max(1, S), contrast)
        self.dot(hxp, hyp, 11.5 * S, dark, col, hw)
        self.layer(tf)
        self.draw_face(f, hxp, hyp, S, lean + tilt)
        self.layer(ta)
        self.line((*P(neck[0], neck[1] - 1), *P(*elbR), *P(*hR)), dark, lw)
        self.draw_weapon(f, P, hR, elbR, hL, tw, twd)

        # ride props. Drawn after the weapon so nothing here can shuffle the
        # limb items the geometry checks read by position in the pool.
        if st == "pogo":
            self.layer(tw)
            self.line((*P(1, -22), *P(1, 10)), GUNMETAL, max(2, round(3 * S)))
            self.line((*P(-7, -22), *P(9, -22)), STEEL, max(2, round(3 * S)))
            self.line((*P(-4, 10), *P(6, 10)), STEEL, max(2, round(3 * S)))
        elif st == "skate":
            self.layer(tw)
            self.line((*P(-15, 3), *P(17, 3)), WOOD, max(2, round(4 * S)))
            self.layer(twd)
            self.dot(*P(-9, 6), max(1.4, 2.6 * S), "#39415F")
            self.dot(*P(11, 6), max(1.4, 2.6 * S), "#39415F")
        elif st == "float":
            self.layer(tw)
            self.line((*P(hR[0], hR[1]), *P(9, -98)), ROPE, 1)
            self.layer(twd)
            self.dot(*P(9, -112), 13 * S, col)
            self.dot(*P(5, -117), 3 * S, "#FFFFFF")
        elif st == "cannonwind":
            self.layer(tw)
            self.line((*P(4, 2), *P(30, -18)), "#5C6690", max(6, round(11 * S)))
            self.layer(twd)
            self.dot(*P(8, 4), max(3, 6 * S), "#39415F")
        elif st == "jet":
            # the pack rides his back -- local -x, whichever way he faces
            self.layer(tw)
            self.line((*P(-11, -56), *P(-11, -36)), GUNMETAL, max(3, round(5 * S)))
            self.line((*P(-16, -54), *P(-16, -38)), "#7E8AB4", max(2, round(4 * S)))
            self.layer(twd)
            fl = 1 + (int(self.time * 30) % 2)            # flame flicker
            self.dot(*P(-11, -32 + fl), max(1.6, 3 * S), FIRE)
            self.dot(*P(-16, -34 + fl), max(1.2, 2.2 * S), "#FFE7A8")
        if f.chute:
            self.layer(tw)
            pts = []
            for i in range(5):
                a2 = math.pi + i * math.pi / 4
                pts += list(P(math.cos(a2) * 26, -96 + math.sin(a2) * 16))
            self.line(pts, ROPE, max(2, round(3 * S)))
            self.line((*P(-26, -96), *P(-9, -50)), ROPE, 1)
            self.line((*P(26, -96), *P(9, -50)), ROPE, 1)

    def draw_face(self, f, cx, cy, e, tilt):
        lookx = f.look * 2.2
        face_col = f.face_color()

        def pt(lx, ly):
            x, y = rot(lx, ly, tilt)
            x, y = rot(x * e * f.face, y * e, f.tumble)
            return cx + x, cy + y

        w = max(1, round(1.9 * e))
        if f.state == "sleep" or f.mood == "asleep":
            self.line((*pt(-5.4, -1.4), *pt(-1.0, -1.4)), face_col, w)
            self.line((*pt(1.0, -1.4), *pt(5.4, -1.4)), face_col, w)
            self.line((*pt(-3, 5), *pt(3, 5)), face_col, w)
            return
        if f.state == "ko":
            for sx in (3.7, -3.3):
                self.line((*pt(sx - 2.4, -4.2), *pt(sx + 2.4, .6)), face_col, w)
                self.line((*pt(sx + 2.4, -4.2), *pt(sx - 2.4, .6)), face_col, w)
            self.line((*pt(-3.4, 5.2), *pt(3.4, 5.2)), face_col, w)
            return

        if f.blink < 0:
            self.line((*pt(.7 + lookx, -1.7), *pt(6.2 + lookx, -1.7)), face_col, w)
            self.line((*pt(-6.2 + lookx, -1.7), *pt(-1.7 + lookx, -1.7)), face_col, w)
        else:
            eo = 1.4 if f.mood == "furious" else 0
            for ex in (3.7, -3.3):
                self.dot(*pt(ex + lookx, -1.8 + eo), max(1.1, 2.2 * e), face_col)

        m = f.mood
        if m == "furious":
            self.line((*pt(-6.5, -6.5), *pt(-1.0, -4.2)), face_col, w)
            self.line((*pt(6.5, -6.5), *pt(1.0, -4.2)), face_col, w)
            self.line((*pt(-4, 5.4), *pt(0, 2.8), *pt(4, 5.4)), face_col, w)
        elif m == "hyped":
            self.line((*pt(-4.2, 1.6), *pt(0, 6.2), *pt(4.2, 1.6)), face_col, w)
        elif m == "smug":
            self.line((*pt(-4, 4.4), *pt(.5, 6.4), *pt(4.2, 3.0)), face_col, w)
            self.line((*pt(1.0, -6.2), *pt(6.4, -7.4)), face_col, w)
        elif m == "sulking":
            self.line((*pt(-3.6, 5.6), *pt(0, 3.4), *pt(3.6, 5.6)), face_col, w)
            self.line((*pt(-6.4, -5.6), *pt(-1.6, -6.6)), face_col, w)
            self.line((*pt(6.4, -5.6), *pt(1.6, -6.6)), face_col, w)
        else:
            self.line((*pt(-3.2, 4.6), *pt(3.2, 4.6)), face_col, w)

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
            u = clamp(k / .55 if k < .55 else (k - .55) / .10, 0, 1)
            u = u * u * (3 - 2 * u)
            pull = -16 * (u if k < .55 else 1 - u)
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
        elif w == "fish":
            self.line((*rel(0, 0), *rel(14, -3), *rel(28, 0), *rel(38, -4)),
                      "#8FD0E8", max(3, round(6 * S)))
            self.line((*rel(38, -8), *rel(44, -4), *rel(38, 2)),
                      "#8FD0E8", max(2, round(3 * S)))
            self.layer(twd)
            self.dot(*rel(7, -2), max(1, 1.8 * S), "#0A0A0C")
        elif w == "pan":
            self.line((*rel(0, 0), *rel(16, 0)), GUNMETAL, max(2, round(3.4 * S)))
            self.layer(twd)
            self.dot(*rel(24, 0), max(4, 8 * S), "#3A4468")
        elif w == "confetti":
            self.line((*rel(-2, 0), *rel(16, -4)), "#C89A66", max(3, round(6 * S)))
            self.line((*rel(-2, 0), *rel(16, 4)), "#B0854F", max(3, round(6 * S)))
            self.layer(twd)
            for i, col in enumerate(CONFETTI_COLS[:3]):
                self.dot(*rel(19 + i * 3, -4 + i * 4), max(1, 1.8 * S), col)
        elif w == "harpoon":
            self.line((*rel(-8, 0), *rel(34, 0)), STEEL, max(2, round(3 * S)))
            self.line((*rel(34, 0), *rel(28, -5)), STEEL, max(1, round(2 * S)))
            self.line((*rel(34, 0), *rel(28, 5)), STEEL, max(1, round(2 * S)))
            self.layer(twd)
            self.dot(*rel(-8, 2), max(1.5, 3 * S), ROPE)
        elif w == "magnet":
            self.line((*rel(2, -5), *rel(14, -5)), "#E05A3A", max(2, round(4 * S)))
            self.line((*rel(2, 5), *rel(14, 5)), "#E05A3A", max(2, round(4 * S)))
            self.line((*rel(2, -5), *rel(-4, 0), *rel(2, 5)), "#B44A30",
                      max(2, round(4 * S)))
            self.layer(twd)
            self.dot(*rel(14, -5), max(1.2, 2.4 * S), STEEL)
            self.dot(*rel(14, 5), max(1.2, 2.4 * S), STEEL)
        elif w == "boomerang":
            self.line((*rel(-5, -9), *rel(22, 0), *rel(-5, 9)),
                      "#EDB16C", max(2, round(4 * S)))
        elif w in ("bubble", "freeze", "swap", "glove", "rubber", "foam"):
            col = {"bubble": "#A9EEFF", "freeze": "#7ADFFF", "swap": "#D49CFF",
                   "glove": "#FF6375", "rubber": "#FFD65B", "foam": "#CEFFB8"}[w]
            self.line((*rel(-5, 0), *rel(26, 0)), "#7B88AF", max(3, round(7 * S)))
            self.line((*rel(3, 2), *rel(0, 11)), "#596786", max(2, round(4 * S)))
            self.layer(twd)
            if w == "glove":
                self.dot(*rel(26, 0), max(3, 7 * S), col)
                self.dot(*rel(21, 5), max(2, 4 * S), col)
            elif w == "bubble":
                self.ring(*rel(26, 0), max(3, 7 * S), col, max(1, round(2 * S)))
            elif w == "freeze":
                self.line((*rel(18, -5), *rel(26, 0), *rel(18, 5)), col, max(1, round(2 * S)))
            elif w == "swap":
                self.line((*rel(10, -4), *rel(21, -4), *rel(18, -7)), col, max(1, round(2 * S)))
                self.line((*rel(21, 4), *rel(10, 4), *rel(13, 7)), col, max(1, round(2 * S)))
                self.dot(*rel(26, 0), max(1, 2 * S), col)
            elif w == "foam":
                for dx, dy in ((20, -3), (21, 4), (26, 0)):
                    self.dot(*rel(dx, dy), max(2, 4 * S), col)
            else:
                self.dot(*rel(26, 0), max(2, 5 * S), col)
                self.line((*rel(5, -4), *rel(9, 4), *rel(13, -4), *rel(17, 4)), col, 1)
        elif w == "blackhole":
            self.layer(twd)
            self.dot(*rel(12, 0), max(2.5, 6 * S), "#1A1030")
            self.ring(*rel(12, 0), max(4, 8.5 * S), "#B79BFF", max(1, round(1.6 * S)))
        elif w in ("anvil", "piano"):
            # nothing in hand: he calls it down, and the pointing IS the prop
            self.line((*rel(0, 0), *rel(20, -12)), GUNMETAL, max(2, round(3 * S)))
        elif w == "peel":
            self.layer(twd)
            self.dot(*rel(10, 0), max(2, 4 * S), "#FFE97A")
        elif w == "spring":
            self.line((*rel(4, 3), *rel(8, -3), *rel(12, 3), *rel(16, -3)),
                      GUNMETAL, max(1, round(2 * S)))
        else:  # bomb
            self.layer(twd)
            self.dot(*rel(12, 0), max(2.5, 6.2 * S), BOMBC)
            self.dot(*rel(15, -16), max(1.2, 2.2 * S), FIRE)

    # ---- speech, health, cargo ------------------------------------------
    def draw_overlay(self, f, fi):
        to, tob, tot = self._ftag[fi][6:]
        S = f.sc
        self.layer(to)
        if self.hover is f or f.grabbed:
            self.text(f.x - self.ox - self.sx,
                      min(self.H - 14, f.y - self.oy - self.sy + 14),
                      getattr(f, "nickname", f.kind.title()), f.color(),
                      ("Segoe UI", 9, "bold"))
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

        if f.state == "ko":
            # Dizzy orbit over the fallen. Two dots on opposite phases; the
            # ellipse is squashed flat so it reads as circling, not bouncing.
            a = self.time * 7
            for phk in (0.0, math.pi):
                self.dot(f.x + math.cos(a + phk) * 15 * S,
                         f.y - 36 * S + math.sin(a + phk) * 4 * S,
                         2.3 * S, f.color())

        if f.emote_t > 0 and f.emote:
            fs = int(clamp(round(9 * S + 4), 9, 18))
            bx = f.x + 16 * S - self.ox - self.sx
            by = f.y - 102 * S - self.oy - self.sy
            col = f.color()
            fam, style = SPEECH_FONT.get(f.kind, ("Segoe UI", "bold"))
            self.layer(tot)
            t = self.text(bx, by, f.emote, col, (fam, fs, style), backing=False)
            bb = self.canvas.bbox(t)
            if bb:
                # Keep the bubble on screen. A long line from someone near the
                # right edge used to run straight off it, and the tail below is
                # what keeps a shoved bubble pointing at its speaker.
                dx = min(0, (self.W - 10) - bb[2])
                if bb[0] + dx < 10:
                    dx = 10 - bb[0]
                dy = max(0, 8 - bb[1])
                if dx or dy:
                    self.canvas.coords(t, bx + dx, by + dy)
                    bb = (bb[0] + dx, bb[1] + dy, bb[2] + dx, bb[3] + dy)
                # the box layer is raised before the text layer, so it lands behind
                pad = fs * .55
                self.layer(tob)
                self._rect(bb[0] - pad, bb[1] - pad * .7, bb[2] + pad,
                           bb[3] + pad * .7, "#0C1024", col, 2)
                wx, wy = self.ox + self.sx, self.oy + self.sy
                self.line((bb[0] + wx + 6, bb[3] + wy + pad * .7,
                           f.x + 6 * S * f.face, f.y - 82 * S), col, 2)

    # ==================================================================
    #  loop
    # ==================================================================
    def configure_renderer(self):
        if not IS_WINDOWS:
            CFG["renderer"] = "tk"
            self.renderer_mode = "x11"
            return
        # DirectComposition's non-layered visual HWND can intercept the entire
        # desktop despite transparent pixels and HTTRANSPARENT. Old saved
        # "auto" settings must not reactivate it; no native constructor is
        # reachable from the application until actual input delivery is proved.
        want = "tk"
        CFG["renderer"] = want
        if want == self.renderer_mode:
            return
        if any(f.grabbed for f in getattr(self, "fighters", ())):
            # Disposing a captured input HWND queues a release on the old
            # adapter. End the drag now so switching renderers cannot lose it.
            self.on_up(None)
        if hasattr(self, "_pool"):
            self.clear_canvas()
        if hasattr(self.canvas, "dispose"):
            self.canvas.dispose()
        self.canvas = self.tk_canvas
        self.renderer_error = ""
        self.renderer_mode = want

    def record_performance(self, frame_dt, update_ms, draw_ms, steps, dropped):
        monitor = getattr(self, "performance", None)
        if monitor is None:
            return
        monitor.record(frame_dt, update_ms, draw_ms, steps, dropped,
                       self.frame_period(), CFG.get("auto_quality", True),
                       not (self.paused or self.held or self.asleep))

    def effect_detail(self):
        automatic = (self.performance.detail if CFG.get("auto_quality", True)
                     and hasattr(self, "performance") else 1.0)
        return CFG.get("effects_quality", 1.0) * automatic

    def effect_count(self, count):
        return max(1, round(count * self.effect_detail())) if count else 0

    def open_performance(self):
        if self.performance_win is not None:
            self.performance_win.lift()
            return
        win = self.performance_win = tk.Toplevel(self.root)
        win.title("Desktop Gremlin — performance")
        win.attributes("-topmost", True)
        win.configure(bg="#171B2C")
        win.resizable(False, False)
        label = tk.Label(win, bg="#171B2C", fg="#E6ECFF", justify="left",
                         font=("Consolas", 10), padx=22, pady=18)
        label.pack(fill="both", expand=True)
        tk.Label(win, text="Draw time includes submission and presentation; GPU completion is not timed.",
                 bg="#171B2C", fg="#8FA0CC", font=("Segoe UI", 8),
                 wraplength=460, padx=16, pady=10).pack()

        def refresh():
            if self.performance_win is None:
                return
            s = self.performance.snapshot()
            renderer = getattr(self.canvas, "stats", {})
            state = "Hidden" if self.held else "Paused" if self.paused else "Sleeping" if self.asleep else "Running"
            error = renderer.get("last_error", "") or self.renderer_error
            label.configure(text=(
                "Renderer    {renderer}\nState       {state}\n\n"
                "Actual FPS  {fps:.1f}  (target {target:.0f})\n"
                "Simulation  {update_ms:.2f} ms/frame\n"
                "Drawing     {draw_ms:.2f} ms/frame\n"
                "95% cost    {p95_ms:.2f} ms/frame\n"
                "Sim steps   {steps:.2f}/frame at 60 Hz\n"
                "Dropped     {dropped:.3f} seconds total\n\n"
                "FX detail   {detail:.0%}\nParticles   {particles}\n"
                "Fighters    {fighters}").format(
                    renderer=renderer.get("backend", "Tk"), state=state,
                    target=1 / self.frame_period(), particles=len(self.parts),
                    fighters=len(self.fighters), **dict(s, detail=self.effect_detail()))
                + ("\n\nFallback: " + error[:180] if error else ""))
            self.performance_after = self.root.after(500, refresh)

        win.protocol("WM_DELETE_WINDOW", self.close_performance)
        refresh()

    def close_performance(self):
        if getattr(self, "performance_after", None) is not None:
            try:
                self.root.after_cancel(self.performance_after)
            except tk.TclError:
                pass
            self.performance_after = None
        if getattr(self, "performance_win", None) is not None:
            self.performance_win.destroy()
            self.performance_win = None

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
        due = last                 # when the frame after this one should start
        accumulator = 0.0
        suspended = self.paused or self.held

        def tick():
            if not self.running:
                return
            nonlocal last, due, accumulator, suspended
            now = time.perf_counter()
            frame_dt = max(0.0, now - last)
            last = now
            steps, dropped = 0, 0.0
            update_ms = draw_ms = 0.0
            self.tray.pump()
            self.tray.drain()      # menu actions, clear of the Win32 modal loop
            if not self.running:   # Quit is one of them
                return
            try:
                if now - self.env_at > TERRAIN_HZ:
                    self.env_at = now
                    self.check_environment()
                if not self.held:
                    self.poll_cursor(min(frame_dt, .1))
                    if not self.paused:
                        # Fixed physics steps keep flight and combat independent
                        # of drawing FPS. A resumed pause starts with no debt.
                        accumulator = 0.0 if suspended else accumulator + frame_dt
                        available = int((accumulator + 1e-9) / SIM_STEP)
                        if available > MAX_CATCHUP_STEPS:
                            dropped = (available - MAX_CATCHUP_STEPS) * SIM_STEP
                            accumulator -= dropped
                        self.begin_frame()
                        started = time.perf_counter()
                        try:
                            for _ in range(min(available, MAX_CATCHUP_STEPS)):
                                self.update(SIM_STEP)
                                accumulator = max(0.0, accumulator - SIM_STEP)
                                steps += 1
                        finally:
                            self.flush_frame()
                            update_ms = (time.perf_counter() - started) * 1000
                        started = time.perf_counter()
                        self.draw()
                        draw_ms = (time.perf_counter() - started) * 1000
                    elif self._pool:
                        self.clear_canvas()
            except Exception as exc:
                if DEBUG:
                    import traceback
                    traceback.print_exc()
                elif self._frame_errs < 20:
                    # A persistent fault fires every frame, and under pythonw
                    # every print lands in gremlin_log.txt -- 40 a second
                    # breaks the promise that the log stays small.
                    self._frame_errs += 1
                    print("frame error:", exc)
                    if self._frame_errs == 1:
                        import traceback
                        traceback.print_exc()
                    if self._frame_errs == 20:
                        print("(more of the same; going quiet about it)")
            if not self.running:
                return  # A failed X11 presentation can quit during draw().
            suspended = self.paused or self.held
            if suspended:
                accumulator = 0.0
            record = getattr(self, "record_performance", None)
            if record is not None:
                record(frame_dt, update_ms, draw_ms, steps, dropped)
            # Paced from a deadline, not from the end of the work. after(period)
            # here used to add each frame's own cost to every gap, so 40 fps
            # configured ran at about 32 with ten of them on screen.
            due += self.frame_period()
            done = time.perf_counter()
            if due < done:
                due = done         # fell behind: catch up, never pile up
            self.root.after(max(1, int((due - done) * 1000 + .5)), tick)

        self.root.after(30, tick)
        self.root.mainloop()


TERRAIN_HZ = 1.6
SIM_STEP = 1 / 60.0
MAX_CATCHUP_STEPS = 8


def fatal(msg, icon=0x10):
    """Say it in a box. Launched with pythonw there is no console, and a
    crash that prints into the void looks like nothing happened at all."""
    print(msg)
    try:
        if IS_WINDOWS:
            user32.MessageBoxW(0, msg, "Desktop Gremlin", icon)
        else:
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Desktop Gremlin", msg, parent=root)
            root.destroy()
    except Exception:
        pass


def main():
    if not claim_instance():
        fatal("Desktop Gremlin is already running.\n\n"
              "Look for its icon in the tray, bottom-right: Settings, Pause "
              "and Quit are on that menu.", icon=0x40)
        return
    # Refusing a duplicate must not truncate the active instance's diagnostics.
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except OSError as exc:
        fatal("Desktop Gremlin cannot create its settings folder:\n\n" + DATA_DIR + "\n\n" + str(exc))
        return
    start_log()      # before the banner, or under pythonw it goes nowhere
    print("=" * 60)
    print(f"  DESKTOP GREMLIN v{VERSION} — overlay edition   [{source_id()}]")
    print("=" * 60)
    count_run()
    state = backup_layout() if IS_WINDOWS else "unsupported"
    if state == "unsupported":
        print("  Linux X11 desktop: open windows and floor; icon rearrangement unavailable.")
    elif state == "saved":
        print("  Saved your desktop icon layout to gremlin_icon_backup.json")
    elif state == "kept":
        print("  Last run left icons moved, so the layout backup from before that")
        print("  is kept. Tray > Restore my icon layout puts them back.")
    elif state == "existing":
        print("  Icon layout backup already on file.")
    else:
        print("  Could not read your icon layout (so nothing will be moved).")

    app = App()
    n_i, n_w = len(app.terrain.icons), len(app.terrain.windows)
    print(f"  Found {n_i} desktop icon(s) and {n_w} open window(s).")
    if IS_WINDOWS and n_i == 0:
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
    print("  Tray icon (bottom-right) has Settings, Pause, Restore layout, Quit." if IS_WINDOWS
          else "  Desktop Gremlin controls has Settings, Pause, Restore windows, Quit.")
    print("  Grab one: hover until the rings appear, then click and drag.")
    print("  Right-click one to open Settings." if IS_WINDOWS else "  Right-click one to show controls.")
    if app.tray.emergency_registered:
        print("  Emergency exit: Ctrl+Alt+Shift+Q (no mouse needed).")
    print()

    # None of the above is readable when we are started with pythonw, so
    # anything that actually needs attention goes to the tray as well.
    notes = []
    if IS_WINDOWS and n_i == 0:
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
        if sys.argv[1:2] == ["--self-test"]:
            if IS_WINDOWS:
                from gremlin_selftest import run
            else:
                from gremlin_linux_selftest import run
            sys.exit(run(sys.modules[__name__], sys.argv[2] if len(sys.argv) == 3 else None))
        if sys.argv[1:2] == ["--input-receiver"] and not IS_WINDOWS:
            from gremlin_x11_probe import receiver_main
            sys.exit(receiver_main(sys.argv[2]) if len(sys.argv) == 3 else 2)
        if any(arg != "--debug" for arg in sys.argv[1:]):
            print("Unknown option. Use --debug for diagnostics.", file=sys.stderr)
            sys.exit(2)
        main()
    except Exception:
        import traceback
        fatal("Desktop Gremlin stopped with an error:\n\n"
              + traceback.format_exc()[-1400:])
        sys.exit(1)
