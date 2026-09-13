r"""Controlled, reproducible DWM composition / cross-process mouse-hit proof.

Run outside a graphics-isolated sandbox:
    .venv\Scripts\python.exe -B tests\check_renderer_desktop.py

Creates two owned test processes/windows, checks displayed pixels and native
hit testing, writes a small test-only screenshot, then closes both windows.
No input is injected, and no pre-existing application/icon/window is moved.
"""
import ctypes as C
from ctypes import wintypes as W
import os
import struct
import subprocess
import sys
import time
import tkinter as tk
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
sys.path.insert(0, harness.ROOT)
import gremlin_renderer as gr

if not gr.NATIVE_DESKTOP_ENABLED:
    raise SystemExit("DISABLED: this probe checked same-thread window lookup, not actual mouse delivery. "
                     "It incorrectly reported desktop input passthrough.")


def fixture():
    user = C.WinDLL("user32")
    user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry("640x420+80+80")
    root.configure(bg="#226688")
    root.attributes("-topmost", True)
    root.update()
    print(os.getpid(), flush=True)
    root.after(30000, root.destroy)
    root.mainloop()


def screenshot(user, gdi, path, x, y, width, height):
    """Capture only the test-owned rectangle into a standard-library PNG."""
    class Header(C.Structure):
        _fields_ = [("size", W.DWORD), ("width", W.LONG), ("height", W.LONG),
                    ("planes", W.WORD), ("bits", W.WORD), ("compression", W.DWORD),
                    ("image_size", W.DWORD), ("xppm", W.LONG), ("yppm", W.LONG),
                    ("colors", W.DWORD), ("important", W.DWORD)]
    functions = {
        "CreateCompatibleDC": ([W.HDC], W.HDC),
        "CreateDIBSection": ([W.HDC, C.c_void_p, W.UINT, C.c_void_p, W.HANDLE, W.DWORD], W.HBITMAP),
        "SelectObject": ([W.HDC, W.HANDLE], W.HANDLE),
        "BitBlt": ([W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.HDC,
                    C.c_int, C.c_int, W.DWORD], W.BOOL),
        "DeleteObject": ([W.HANDLE], W.BOOL), "DeleteDC": ([W.HDC], W.BOOL),
    }
    for name, (arguments, result) in functions.items():
        fn = getattr(gdi, name)
        fn.argtypes, fn.restype = arguments, result
    dc = user.GetDC(None)
    memory = gdi.CreateCompatibleDC(dc)
    data = C.c_void_p()
    header = Header(40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    bitmap = gdi.CreateDIBSection(dc, C.byref(header), 0, C.byref(data), None, 0)
    old = gdi.SelectObject(memory, bitmap)
    try:
        if not gdi.BitBlt(memory, 0, 0, width, height, dc, x, y, 0x40CC0020):
            raise RuntimeError("Screen capture unavailable; use the desktop session")
        pixels = bytearray(C.string_at(data, width * height * 4))
        for i in range(0, len(pixels), 4):
            pixels[i], pixels[i + 2], pixels[i + 3] = pixels[i + 2], pixels[i], 255
        raw = b"".join(b"\0" + pixels[y * width * 4:(y + 1) * width * 4] for y in range(height))
        def chunk(name, value):
            return struct.pack(">I", len(value)) + name + value + struct.pack(">I", zlib.crc32(name + value))
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    finally:
        gdi.SelectObject(memory, old)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(None, dc)


def main():
    gm = harness.load("renderer_desktop")
    user, gdi = C.WinDLL("user32"), C.WinDLL("gdi32")
    declarations = {
        "GetParent": ([W.HWND], W.HWND), "WindowFromPoint": ([W.POINT], W.HWND),
        "GetWindowThreadProcessId": ([W.HWND, C.POINTER(W.DWORD)], W.DWORD),
        "GetDC": ([W.HWND], W.HDC), "ReleaseDC": ([W.HWND, W.HDC], C.c_int),
        "IsWindowVisible": ([W.HWND], W.BOOL), "IsWindow": ([W.HWND], W.BOOL),
    }
    for name, (arguments, result) in declarations.items():
        fn = getattr(user, name)
        fn.argtypes, fn.restype = arguments, result
    gdi.GetPixel.argtypes, gdi.GetPixel.restype = [W.HDC, C.c_int, C.c_int], W.DWORD
    child = subprocess.Popen([sys.executable, "-B", os.path.abspath(__file__), "--fixture"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    root = renderer = proxy = None
    try:
        child_pid = int(child.stdout.readline())
        root = tk.Tk()
        root.overrideredirect(True)
        root.geometry("480x320+100+100")
        root.configure(bg="#010101")
        root.attributes("-transparentcolor", "#010101")
        root.attributes("-topmost", True)
        root.update()
        hwnd = user.GetParent(root.winfo_id()) or root.winfo_id()
        renderer = gr.NativeRenderer(hwnd, 480, 320)
        items = [
            {"kind": "rectangle", "coords": (8, 8, 168, 168), "tags": (),
             "options": {"fill": "#FF3300", "outline": ""}},
            {"kind": "oval", "coords": (200, 35, 280, 115), "tags": (),
             "options": {"fill": "#88FF8870", "outline": "#AAFFAA", "width": 2, "glow": 9}},
            {"kind": "text", "coords": (24, 230), "tags": (),
             "options": {"text": "DIRECTCOMPOSITION / LIVE DESKTOP", "font": ("Segoe UI", 14, "bold"),
                         "anchor": "nw", "fill": "#FFFFFF"}},
            {"kind": "text", "coords": (24, 265), "tags": (),
             "options": {"text": "Transparent visuals, isolated interactive hit target.", "font": ("Segoe UI", 10),
                         "anchor": "nw", "fill": "#DAF3FF"}},
        ]
        renderer.render(items)
        for _ in range(10):
            root.update()
            time.sleep(.02)
        dc = user.GetDC(None)
        try:
            red, background = gdi.GetPixel(dc, 160, 160), gdi.GetPixel(dc, 460, 300)
        finally:
            user.ReleaseDC(None, dc)
        assert red == 0x0033FF, "Native pixels not visible (or sandbox blocks screen reads): %x" % red
        assert background == 0x886622, "Empty composition did not preserve the underlying window"

        def hit_pid(x, y):
            hit = user.WindowFromPoint(W.POINT(x, y))
            pid = W.DWORD()
            user.GetWindowThreadProcessId(hit, C.byref(pid))
            return pid.value

        assert hit_pid(160, 160) == child_pid and hit_pid(460, 300) == child_pid
        proxy = gr.InputProxy()
        proxy.set_interactive(True, 160, 160, 30)
        root.update()
        assert user.WindowFromPoint(W.POINT(160, 160)) == proxy.hwnd
        assert hit_pid(132, 132) == child_pid, "Proxy corners must pass through"
        proxy.set_interactive(False)
        assert hit_pid(160, 160) == child_pid
        print("PASS: visible native pixels, empty alpha, separate-process passthrough, circular input proxy")
        path = harness.scratch("renderer", "composed.png")
        screenshot(user, gdi, path, 100, 100, 480, 320)
        print("Actual composed screenshot:", path)

        # Position-only changes must move the owned visual, with no resize needed.
        root.geometry("480x320+120+110")
        root.update()
        renderer.render(items)
        root.withdraw()
        root.update()
        renderer.render(items)
        assert not user.IsWindowVisible(renderer.window.hwnd)
        old_hwnd = renderer.window.hwnd
        renderer.dispose()
        renderer = None
        assert not user.IsWindow(old_hwnd)
        print("PASS: host follow/hide and native HWND disposal")
    finally:
        if proxy:
            proxy.dispose()
        if renderer:
            renderer.dispose()
        if root:
            root.destroy()
        child.terminate()
        child.wait(timeout=5)
        harness.teardown(gm, None)


if __name__ == "__main__":
    fixture() if "--fixture" in sys.argv else main()
