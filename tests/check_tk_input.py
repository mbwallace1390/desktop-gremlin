r"""Bounded foreign-process hit lookup for the real App's Tk startup path.

    .venv\Scripts\python.exe -B tests\check_tk_input.py

This checks window lookup, NOT actual mouse-message delivery. No input is
injected or cursor moved. A controller kills the window-owning worker after
eight seconds even if its Tk event loop or cleanup stops responding.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
import subprocess
import sys

import harness


def user_api():
    user = C.WinDLL("user32", use_last_error=True)
    declarations = {
        "WindowFromPoint": ([W.POINT], W.HWND),
        "GetAncestor": ([W.HWND, W.UINT], W.HWND),
        "GetWindowThreadProcessId": ([W.HWND, C.POINTER(W.DWORD)], W.DWORD),
        "ClientToScreen": ([W.HWND, C.POINTER(W.POINT)], W.BOOL),
        "GetWindowRect": ([W.HWND, C.POINTER(W.RECT)], W.BOOL),
    }
    for name, (arguments, result) in declarations.items():
        function = getattr(user, name)
        function.argtypes, function.restype = arguments, result
    return user


def probe(points):
    """Run on a foreign UI thread/process; never send a hit test ourselves."""
    user = user_api()
    # Match App's physical screen coordinate system on scaled displays.
    user.SetProcessDpiAwarenessContext.argtypes = [C.c_void_p]
    user.SetProcessDpiAwarenessContext.restype = W.BOOL
    user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    hits = []
    for x, y in points:
        hwnd = user.WindowFromPoint(W.POINT(x, y))
        pid = W.DWORD()
        user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        hits.append({"hwnd": hwnd or 0,
                     "root": user.GetAncestor(hwnd, 2) or 0,
                     "pid": pid.value})
    print(json.dumps({"observer_pid": os.getpid(), "hits": hits}), flush=True)


def worker():
    # The normal harness redirects persistent files and stubs desktop readers
    # before App construction. An old raw "auto" value must still choose Tk.
    gm = harness.load("tk_input", crowd=1)
    gm.CFG["renderer"] = "auto"
    gm.virtual_screen = lambda: (100, 100, 480, 320)
    gm.monitors = lambda: [((100, 100, 580, 420), (100, 100, 580, 420))]
    user = user_api()
    backing = app = None
    try:
        backing = gm.tk.Tk()
        backing.overrideredirect(True)
        backing.geometry("640x420+80+80")
        backing.configure(bg="#226688")
        backing.attributes("-topmost", True)
        backing.update()
        app = harness.build(gm)
        assert app.canvas is app.tk_canvas, "Startup did not retain the Tk canvas"
        assert app.renderer_mode == "tk", "Raw auto setting enabled a native renderer"
        assert gm.CFG["renderer"] == "tk", "Raw auto setting was not normalized"
        assert (app.ox, app.oy, app.W, app.H) == (100, 100, 480, 320)

        # A single actual Canvas item is the only nontransparent App content.
        app.canvas.create_rectangle(40, 40, 80, 80, fill="#FF3300", outline="")
        app.root.update()
        origin = W.POINT(0, 0)
        assert user.ClientToScreen(app.canvas.winfo_id(), C.byref(origin))
        points = [(origin.x + 300, origin.y + 200),
                  (origin.x + 60, origin.y + 60)]
        backing_root = user.GetAncestor(backing.winfo_id(), 2)
        app_root = user.GetAncestor(app.canvas.winfo_id(), 2)
        assert backing_root and app_root and backing_root != app_root
        bounds = W.RECT()
        assert user.GetWindowRect(backing_root, C.byref(bounds))
        assert all(bounds.left < x < bounds.right and bounds.top < y < bounds.bottom
                   for x, y in points), "Probe escaped the owned backing fixture"

        result = subprocess.run(
            [sys.executable, "-B", os.path.abspath(__file__), "--probe", json.dumps(points)],
            capture_output=True, text=True, timeout=2, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        data = json.loads(result.stdout)
        assert data["observer_pid"] != os.getpid(), "Probe ran in the overlay process"
        blank, marker = data["hits"]
        assert blank["pid"] == os.getpid() and blank["root"] == backing_root, (
            "Empty Tk pixels blocked the owned backing window: %r" % blank)
        assert marker["pid"] == os.getpid() and marker["root"] == app_root, (
            "Painted Tk marker did not retain its input region: %r; expected %s, backing %s"
            % (marker, app_root, backing_root))
        assert marker["hwnd"] in (app.canvas.winfo_id(), app.root.winfo_id(), app.hwnd)
        print("PASS: raw auto startup uses Tk; foreign-process lookup reaches the "
              "backing window through empty pixels and finds the painted App marker.", flush=True)
        print("LIMIT: this verifies hit lookup, not actual mouse-message delivery.", flush=True)
    finally:
        harness.teardown(gm, app)
        if backing is not None:
            backing.destroy()


def main():
    if "--probe" in sys.argv:
        probe(json.loads(sys.argv[sys.argv.index("--probe") + 1]))
    elif "--worker" in sys.argv:
        worker()
    else:
        # subprocess.run kills and waits for this exact worker on timeout;
        # Windows then destroys every HWND it owns, independent of Tk cleanup.
        try:
            result = subprocess.run(
                [sys.executable, "-B", os.path.abspath(__file__), "--worker"],
                capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise SystemExit("FAIL: eight-second watchdog terminated the owned test worker.")
        finally:
            # A killed worker cannot reach harness.teardown. Sweep only this
            # fixture's five redirected files, after the worker has exited.
            for _constant, suffix in harness._FILES:
                path = os.path.join(harness.TMP, "tk_input_" + suffix)
                if os.path.isfile(path):
                    os.remove(path)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
