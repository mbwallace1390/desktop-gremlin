"""Retained-scene Tk checks; native presentation is quarantined.

No real desktop icons/windows are inspected or moved. --visual creates only
owned sample windows; --benchmark renders the real ten-fighter scene on fakes.
"""
import ctypes as C
from ctypes import wintypes as W
import os
import statistics
import struct
import sys
import time
import tkinter as tk
import zlib
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
sys.path.insert(0, harness.ROOT)
import gremlin_renderer as gr

gm = harness.load("renderer")
if "--require-native" in sys.argv or "--benchmark" in sys.argv or "--visual" in sys.argv:
    raise SystemExit("Native UI checks are disabled after a desktop input-blocking regression.")
bad = []
root = tk.Tk()
root.withdraw()
root.geometry("480x320+100+100")
root.configure(bg="#183044")
widget = tk.Canvas(root, width=480, height=320, bg="#183044", highlightthickness=0)
widget.pack(fill="both", expand=True)
root.update_idletasks()
user = C.WinDLL("user32")
user.GetParent.argtypes, user.GetParent.restype = [P := C.c_void_p], P
user.WindowFromPoint.argtypes, user.WindowFromPoint.restype = [W.POINT], P
hwnd = user.GetParent(root.winfo_id()) or root.winfo_id()


def check(label, value):
    print("%-54s %s" % (label, "PASS" if value else "FAIL"))
    if not value:
        bad.append(label)


def png(path, width, height, bgra):
    """Store straight-alpha RGBA PNG using only the standard library."""
    rgba = bytearray(len(bgra))
    for i in range(0, len(bgra), 4):
        b, g, r, a = bgra[i:i + 4]
        rgba[i:i + 4] = bytes((min(255, round(r * 255 / a)) if a else 0,
                              min(255, round(g * 255 / a)) if a else 0,
                              min(255, round(b * 255 / a)) if a else 0, a))
    raw = b"".join(b"\0" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))

    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def scene(canvas):
    canvas.create_rectangle(0, 0, 480, 320, fill="#112436", outline="", tags="bg")
    canvas.create_text(24, 22, text="DIRECT2D / DESKTOP GREMLIN", anchor="nw",
                       fill="#EBF4F8", font=("Segoe UI", 16, "bold"), tags="title")
    canvas.create_text(24, 57, text="Native vectors. Real alpha. DirectWrite text.", anchor="nw",
                       fill="#98B5C8", font=("Segoe UI", 10), tags="title")
    for i, tint in enumerate(("#56D8C1", "#F7B955", "#C4A4FF")):
        x = 94 + i * 142
        canvas.create_oval(x - 33, 135, x + 33, 199, fill=tint + "22", outline="", glow=8)
        canvas.create_oval(x - 12, 123, x + 12, 147, fill="#182B3A", outline=tint,
                           width=3.4, tags="h%d" % i)
        canvas.create_line(x, 149, x - 2, 182, x - 22, 215, fill="#EDF6FA", width=4,
                           tags="b%d" % i)
        canvas.create_line(x - 2, 182, x + 21, 214, fill="#EDF6FA", width=4, tags="b%d" % i)
        canvas.create_line(x, 156, x - 22, 169, x - 34, 150, fill="#EDF6FA", width=3.4)
        canvas.create_line(x, 156, x + 22, 169, x + 40, 153, fill=tint, width=3.4, glow=5)
    canvas.create_text(24, 266, text="Rounded strokes   /   soft glow   /   translucent shadows", anchor="nw",
                       fill="#BCD0DC", font=("Segoe UI", 10))


adapter = native = proxy = None
try:
    adapter = gr.Direct2DCanvas(widget, hwnd, 480, 320, mode="tk")
    a = adapter.create_line(1, 2, 3, 4, fill="#FF3300", tags="front")
    b = adapter.create_oval(5, 6, 15, 16, fill="#88AACC", tags="back")
    adapter.tag_raise("front")
    adapter.coords(a, 2, 3, 20, 30)
    adapter.itemconfigure(b, state="hidden")
    check("retained coordinates, layers, hidden state", adapter.find_all() == (b, a)
          and adapter.coords(a) == [2, 3, 20, 30] and adapter.itemcget(b, "state") == "hidden")
    check("Tk fallback receives retained updates", widget.coords(adapter._tk_ids[a]) == [2, 3, 20, 30])
    adapter.delete("all")
    check("delete releases retained and fallback items", not adapter.find_all() and not widget.find_all())
    adapter.dispose()

    try:
        native = gr.NativeRenderer(hwnd, 480, 320)
    except Exception as exc:
        print("Native graphics unavailable on this test host:", exc)
        check("quarantined native renderer cannot create a desktop overlay",
              not gr.NATIVE_DESKTOP_ENABLED and "disabled" in str(exc))
        if "--require-native" in sys.argv:
            bad.append("native backend required")
    if native:
        print("Actual D3D11 driver:", native.driver, "feature level:", hex(native.feature_level))
        native.render([{"kind": "oval", "coords": (30, 30, 100, 100), "tags": (),
                        "options": {"fill": "#FF663380", "outline": ""}}], present=False)
        pixels = native.capture()
        center = pixels[(60 * 480 + 60) * 4:(60 * 480 + 60) * 4 + 4]
        check("native target preserves premultiplied alpha", center == bytes((26, 51, 128, 128))
              and pixels[:4] == b"\0\0\0\0")
        alphas = pixels[3::4]
        check("ellipse edges have real antialias coverage", any(0 < a < 128 for a in alphas))
        check("DirectWrite measures actual text", native.text_size("Gremlin", ("Segoe UI", 12))[0] > 35)
        native.render(())
        native.resize(240, 160)
        native.render((), present=False)
        check("resize releases and recreates swapchain target", len(native.capture()) == 240 * 160 * 4)
        native.dispose()
        native.dispose()
        native = None

        adapter = gr.Direct2DCanvas(widget, hwnd, 480, 320)
        scene(adapter)
        check("native text bbox supports speech placement", adapter.bbox(2)[2] > adapter.bbox(2)[0])
        centered = adapter.create_text(240, 160, text="centered", fill="#FFFFFF")
        bounds = adapter.bbox(centered)
        check("default text anchor is actually centered", abs((bounds[0] + bounds[2]) / 2 - 240) < 1
              and abs((bounds[1] + bounds[3]) / 2 - 160) < 1)
        adapter.delete(centered)
        adapter.native.render((adapter.items[i] for i in adapter.order), present=False)
        preview = harness.scratch("renderer", "native.png")
        png(preview, 480, 320, adapter.native.capture())
        print("Native preview:", preview)
        adapter.present()
        check("native composition presents a complete scene", adapter.stats["native"] and adapter.frames == 1)

        # Production interaction: an owned alpha=1 HWND must receive hits while
        # enabled; hiding it must immediately restore the underlying hit target.
        proxy = gr.InputProxy()
        proxy.set_interactive(True, 250, 240, 30)
        root.update()
        check("layered input proxy receives actual hit testing",
              user.WindowFromPoint(W.POINT(250, 240)) == proxy.hwnd)
        check("input proxy corners stay click-through",
              user.WindowFromPoint(W.POINT(222, 212)) != proxy.hwnd)
        proxy.capturing = True
        with mock.patch.object(proxy.user, "ReleaseCapture", return_value=1) as release_capture:
            proxy.set_interactive(False)
        check("pause/disable immediately releases capture", release_capture.called
              and not proxy.capturing and any(e[0] == "up" for e in proxy.poll()))
        proxy.hide()
        root.update()
        check("hidden input proxy returns mouse passthrough",
              user.WindowFromPoint(W.POINT(250, 240)) != proxy.hwnd)
        proxy.dispose()
        proxy = None

        # Device loss rebuilds the native resources once, without losing items.
        preserved = tuple(adapter.order)
        with mock.patch.object(adapter.native, "render", side_effect=gr.NativeError("injected device loss", 0x887A0005)):
            adapter.present()
        check("device loss reconstructs native scene once", adapter.native is not None
              and adapter._retried and tuple(adapter.order) == preserved)

        # Failure injection goes through present(), preserving every logical ID,
        # coordinate and stacking order while creating ordinary Tk items.
        original = tuple(adapter.order)
        with mock.patch.object(adapter.native, "render", side_effect=RuntimeError("injected render failure")):
            adapter.present()
        check("native failure safely replays scene into Tk", not adapter.native
              and tuple(adapter.order) == original and len(widget.find_all()) == len(original)
              and "injected" in adapter.last_error)
        adapter.delete("all")
        adapter.dispose()

    if "--benchmark" in sys.argv:
        gm.CFG["crowd"], gm.CFG["renderer"] = 10, "auto"
        gm.monitors = lambda: [((0, 0, 1280, 720), (0, 0, 1280, 680))]
        gm.virtual_screen = lambda: (0, 0, 1280, 720)
        app = harness.build(gm)
        try:
            harness.fake_terrain(app)
            samples = []
            for i in range(70):
                app.update(1 / 40)
                start = time.perf_counter()
                app.draw()
                if i >= 10:
                    samples.append((time.perf_counter() - start) * 1000)
            print("Ten-fighter 1280x720 real App draw/present: backend=%s, items=%d, median=%.2f ms, p95=%.2f ms" % (
                getattr(app.canvas, "backend_name", "Tk"), len(app.canvas.find_all()),
                statistics.median(samples), sorted(samples)[int(len(samples) * .95) - 1]))
        finally:
            app.quit()
finally:
    if proxy:
        proxy.dispose()
    if native:
        native.dispose()
    if adapter:
        adapter.dispose()
    root.destroy()
    harness.teardown(gm, None)

print("\n" + ("FAIL: " + "; ".join(bad) if bad else "PASS"))
sys.exit(1 if bad else 0)
