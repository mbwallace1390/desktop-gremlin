"""QUARANTINED: native desktop presentation can block input to other apps.

Retained canvas drawing through Direct2D/DirectWrite and DirectComposition.

Only ctypes and Windows system DLLs are needed. Hardware D3D11 is attempted
first; WARP is explicitly reported as software. No pixels cross back to the
CPU during normal presentation. ``capture`` is an opt-in test/diagnostic path.

The host keeps its layered HWND. An owned NOREDIRECTIONBITMAP window carries
the composition visual because color-keyed Tk targets suppress that visual.
A small input proxy handles interaction; failure replays the scene into Tk.

API references (the COM slots below follow the Windows SDK interfaces):
https://learn.microsoft.com/windows/win32/directcomp/basic-concepts
https://learn.microsoft.com/windows/win32/api/dxgi1_2/nf-dxgi1_2-idxgifactory2-createswapchainforcomposition
https://learn.microsoft.com/windows/win32/direct2d/direct2d-and-direct3d-interoperation-overview
"""
import ctypes as C
import math
import os
import threading
import time
import uuid
from collections import OrderedDict, deque

# Do not re-enable from settings, CLI flags or an automatic graphics test.
# WindowFromPoint on this renderer's own thread falsely reported passthrough.
# A replacement needs independent-process actual mouse-delivery verification.
NATIVE_DESKTOP_ENABLED = False


P = C.c_void_p
U = C.c_uint32
F = C.c_float
HR = C.c_int32
WINCALL = getattr(C, "WINFUNCTYPE", C.CFUNCTYPE)


class GUID(C.Structure):
    _fields_ = [("data", C.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__((C.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


class Point(C.Structure):
    _fields_ = [("x", F), ("y", F)]


class Rect(C.Structure):
    _fields_ = [("left", F), ("top", F), ("right", F), ("bottom", F)]


class Color(C.Structure):
    _fields_ = [("r", F), ("g", F), ("b", F), ("a", F)]


class Ellipse(C.Structure):
    _fields_ = [("point", Point), ("rx", F), ("ry", F)]


class PixelFormat(C.Structure):
    _fields_ = [("format", U), ("alpha", U)]


class TargetProps(C.Structure):
    _fields_ = [("type", U), ("pixel", PixelFormat), ("dpi_x", F),
                ("dpi_y", F), ("usage", U), ("minimum", U)]


class SampleDesc(C.Structure):
    _fields_ = [("count", U), ("quality", U)]


class SwapDesc(C.Structure):
    _fields_ = [("width", U), ("height", U), ("format", U), ("stereo", U),
                ("sample", SampleDesc), ("usage", U), ("buffers", U),
                ("scaling", U), ("effect", U), ("alpha", U), ("flags", U)]


class StrokeProps(C.Structure):
    _fields_ = [("start", U), ("end", U), ("dash_cap", U), ("join", U),
                ("miter", F), ("dash", U), ("offset", F)]


class TextMetrics(C.Structure):
    _fields_ = [(name, F) for name in ("left", "top", "width", "width_space",
                                      "height", "layout_width", "layout_height")] + [
                ("bidi", U), ("lines", U)]


class TextureDesc(C.Structure):
    _fields_ = [("width", U), ("height", U), ("mips", U), ("array", U),
                ("format", U), ("sample", SampleDesc), ("usage", U),
                ("bind", U), ("cpu", U), ("misc", U)]


class Mapped(C.Structure):
    _fields_ = [("data", P), ("row_pitch", U), ("depth_pitch", U)]


class NativeError(RuntimeError):
    def __init__(self, operation, hr):
        self.hr = int(hr) & 0xFFFFFFFF
        super().__init__("%s failed (0x%08X)" % (operation, self.hr))


def checked(hr, operation):
    if int(hr) < 0:
        raise NativeError(operation, hr)


_methods = {}


def invoke(obj, slot, result, arguments, *values):
    """Typed COM dispatch; cache ABI wrappers, never COM-owned pointers."""
    address = C.cast(obj, C.POINTER(C.POINTER(P))).contents[slot]
    key = (address, result, arguments)
    fn = _methods.get(key)
    if fn is None:
        fn = _methods[key] = WINCALL(result, P, *arguments)(address)
    return fn(obj, *values)


def release(obj):
    if obj:
        invoke(obj, 2, U, ())


def query(obj, iid):
    out = P()
    checked(invoke(obj, 0, HR, (P, P), C.byref(GUID(iid)), C.byref(out)), "QueryInterface")
    return out


def color(value, opacity=1.0):
    """#RGB, #RRGGBB and #RRGGBBAA; alpha stays straight until D2D blends."""
    if not value:
        return Color(0, 0, 0, 0)
    names = {"black": "#000000", "white": "#FFFFFF", "red": "#FF0000",
             "transparent": "#00000000"}
    value = names.get(str(value).lower(), str(value)).lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) not in (6, 8):
        raise ValueError("Unsupported renderer color: " + value)
    rgba = [int(value[i:i + 2], 16) / 255.0 for i in range(0, len(value), 2)]
    if len(rgba) == 3:
        rgba.append(1.0)
    rgba[3] *= max(0.0, min(1.0, float(opacity)))
    return Color(*rgba)


class NativeRenderer:
    """Native premultiplied BGRA swap chain; use only on its creating thread."""
    def __init__(self, hwnd, width, height, driver="auto"):
        if not NATIVE_DESKTOP_ENABLED:
            raise RuntimeError("Native desktop renderer disabled after an input-blocking regression")
        if os.name != "nt":
            raise RuntimeError("Direct2D requires Windows")
        self.hwnd = int(hwnd)
        self.width, self.height = max(1, int(width)), max(1, int(height))
        self.thread = threading.get_ident()
        self.closed = False
        self.visible = True
        self.frames = 0
        self.frame_ms = 0.0
        self.driver = "unavailable"
        self._owned = []
        self.layouts = OrderedDict()
        self.formats = {}
        self.target = self.brush = self.surface = None
        self.window = None
        try:
            self._initialize(driver)
        except Exception:
            self.dispose()
            raise

    def _own(self, pointer):
        self._owned.append(pointer)
        return pointer

    def _create(self, obj, slot, types, *args):
        out = P()
        checked(invoke(obj, slot, HR, types + (P,), *args, C.byref(out)),
                "COM creation slot %d" % slot)
        return self._own(out)

    def _initialize(self, driver):
        self.d3d_dll = C.WinDLL("d3d11")
        create = self.d3d_dll.D3D11CreateDevice
        create.argtypes = [P, U, P, U, P, U, U, P, P, P]
        create.restype = HR
        last = 0
        candidates = [(1, "hardware"), (5, "WARP software")] if driver == "auto" else [
            (5, "WARP software") if driver == "warp" else (1, "hardware")]
        for kind, name in candidates:
            device, context, level = P(), P(), U()
            last = create(None, kind, None, 0x20, None, 0, 7,
                          C.byref(device), C.byref(level), C.byref(context))
            if last >= 0:
                self.driver, self.feature_level = name, level.value
                self.device, self.context = self._own(device), self._own(context)
                break
        else:
            checked(last, "D3D11CreateDevice")
        dxgi = self._own(query(self.device, "54ec77fa-1377-44e6-8c32-88fd5f44c84c"))
        adapter = self._create(dxgi, 7, ())
        factory = self._create(adapter, 6, (P,), C.byref(GUID("50c83a1c-e072-4c48-87b0-3630fa36a6d0")))
        desc = SwapDesc(self.width, self.height, 87, 0, SampleDesc(1, 0),
                        0x20, 2, 0, 3, 1, 0)
        self.swap = self._create(factory, 24, (P, P, P), self.device, C.byref(desc), None)

        self.d2d_dll = C.WinDLL("d2d1")
        factory_fn = self.d2d_dll.D2D1CreateFactory
        factory_fn.argtypes, factory_fn.restype = [U, P, P, P], HR
        out = P()
        checked(factory_fn(0, C.byref(GUID("06152247-6f50-465a-9245-118bfd3b6007")),
                           None, C.byref(out)), "D2D1CreateFactory")
        self.factory = self._own(out)
        stroke = StrokeProps(2, 2, 2, 2, 10.0, 0, 0.0)
        self.stroke = self._create(self.factory, 11, (P, P, U), C.byref(stroke), None, 0)
        self._make_target()

        self.write_dll = C.WinDLL("dwrite")
        write_fn = self.write_dll.DWriteCreateFactory
        write_fn.argtypes, write_fn.restype = [U, P, P], HR
        out = P()
        checked(write_fn(0, C.byref(GUID("b859ee5a-d838-4b5b-a2e8-1adc7d93db48")),
                         C.byref(out)), "DWriteCreateFactory")
        self.write_factory = self._own(out)

        self.comp_dll = C.WinDLL("dcomp")
        comp_fn = self.comp_dll.DCompositionCreateDevice
        comp_fn.argtypes, comp_fn.restype = [P, P, P], HR
        out = P()
        checked(comp_fn(dxgi, C.byref(GUID("c37ea93a-e7aa-450d-b16f-9746cb0407f3")),
                        C.byref(out)), "DCompositionCreateDevice")
        self.composition = self._own(out)
        self.window = InputProxy(visual=True, owner=self.hwnd)
        self.comp_target = self._create(self.composition, 6, (P, U), P(self.window.hwnd), 1)
        self.visual = self._create(self.composition, 7, ())
        checked(invoke(self.visual, 15, HR, (P,), self.swap), "SetContent")
        checked(invoke(self.comp_target, 3, HR, (P,), self.visual), "SetRoot")
        checked(invoke(self.composition, 3, HR, ()), "Commit")

    def _make_target(self):
        self.surface = P()
        checked(invoke(self.swap, 9, HR, (U, P, P), 0,
                       C.byref(GUID("cafcb56c-6ac3-4889-bf47-9e23bbd260ec")),
                       C.byref(self.surface)), "GetBuffer")
        props = TargetProps(0, PixelFormat(87, 1), 96, 96, 0, 0)
        self.target = P()
        checked(invoke(self.factory, 15, HR, (P, P, P), self.surface,
                       C.byref(props), C.byref(self.target)), "CreateDxgiSurfaceRenderTarget")
        self.brush = P()
        checked(invoke(self.target, 8, HR, (P, P, P), C.byref(Color(1, 1, 1, 1)),
                       None, C.byref(self.brush)), "CreateSolidColorBrush")
        invoke(self.target, 34, None, (U,), 2)   # grayscale text on transparent pixels

    def _check_thread(self):
        if self.closed or threading.get_ident() != self.thread:
            raise RuntimeError("Renderer is closed or called from a different thread")

    def _ink(self, value, opacity=1.0):
        invoke(self.brush, 8, None, (P,), C.byref(color(value, opacity)))

    def _layout(self, text, font):
        font = tuple(font) if isinstance(font, (tuple, list)) else (str(font), 10)
        key = (text, font)
        if key in self.layouts:
            self.layouts.move_to_end(key)
            return self.layouts[key]
        fmt = self.formats.get(font)
        if fmt is None:
            family, size = font[0], float(font[1] if len(font) > 1 else 10)
            style = " ".join(str(s) for s in font[2:]).lower()
            fmt = P()
            checked(invoke(self.write_factory, 15, HR, (C.c_wchar_p, P, U, U, U, F, C.c_wchar_p, P),
                           family, None, 700 if "bold" in style else 400,
                           2 if "italic" in style else 0, 5,
                           abs(size) if size < 0 else size * 4 / 3,
                           "en-us", C.byref(fmt)), "CreateTextFormat")
            self.formats[font] = fmt
        layout = P()
        checked(invoke(self.write_factory, 18, HR, (C.c_wchar_p, U, P, F, F, P),
                       text, len(text.encode("utf-16-le")) // 2, fmt,
                       32768.0, 32768.0, C.byref(layout)), "CreateTextLayout")
        metrics = TextMetrics()
        checked(invoke(layout, 60, HR, (P,), C.byref(metrics)), "GetMetrics")
        value = (layout, metrics.width_space, metrics.height)
        self.layouts[key] = value
        while len(self.layouts) > 256:
            release(self.layouts.popitem(last=False)[1][0])
        return value

    def text_size(self, text, font):
        return self._layout(str(text), font)[1:]

    def _draw(self, item, opacity=1.0, offset=(0, 0), extra=0, tint=None):
        kind, points, opts = item["kind"], item["coords"], item["options"]
        opacity *= float(opts.get("opacity", 1.0))
        width = max(.1, float(opts.get("width", 1))) + extra
        ox, oy = offset
        if kind == "text":
            text = str(opts.get("text", ""))
            if not text:
                return
            layout, tw, th = self._layout(text, opts.get("font", ("Segoe UI", 10)))
            x, y = points[:2]
            anchor = opts.get("anchor", "center")
            anchor = "" if anchor == "center" else anchor
            x -= 0 if "w" in anchor else tw if "e" in anchor else tw / 2
            y -= 0 if "n" in anchor else th if "s" in anchor else th / 2
            self._ink(tint or opts.get("fill", "#000000"), opacity)
            invoke(self.target, 28, None, (Point, P, P, U), Point(x + ox, y + oy),
                   layout, self.brush, 0)
            return
        fill = tint or opts.get("fill", "#000000" if kind == "line" else "")
        outline = tint or opts.get("outline", "#000000" if kind != "line" else "")
        if kind == "line":
            if not fill:
                return
            self._ink(fill, opacity)
            for i in range(0, len(points) - 2, 2):
                invoke(self.target, 15, None, (Point, Point, P, F, P),
                       Point(points[i] + ox, points[i + 1] + oy),
                       Point(points[i + 2] + ox, points[i + 3] + oy), self.brush, width, self.stroke)
            return
        x0, y0, x1, y1 = points[:4]
        x0, x1 = min(x0, x1) + ox, max(x0, x1) + ox
        y0, y1 = min(y0, y1) + oy, max(y0, y1) + oy
        shape = (Ellipse(Point((x0 + x1) / 2, (y0 + y1) / 2),
                         (x1 - x0 + extra) / 2, (y1 - y0 + extra) / 2)
                 if kind == "oval" else Rect(x0 - extra / 2, y0 - extra / 2,
                                              x1 + extra / 2, y1 + extra / 2))
        if fill:
            self._ink(fill, opacity)
            invoke(self.target, 21 if kind == "oval" else 17, None, (P, P),
                   C.byref(shape), self.brush)
        if outline and width > 0:
            self._ink(outline, opacity)
            invoke(self.target, 20 if kind == "oval" else 16, None, (P, P, F, P),
                   C.byref(shape), self.brush, width, self.stroke)

    def render(self, items, present=True, effects=True):
        self._check_thread()
        started = time.perf_counter()
        invoke(self.target, 48, None, ())
        try:
            invoke(self.target, 47, None, (P,), C.byref(Color(0, 0, 0, 0)))
            if self.visible:
                for item in items:
                    opts = item["options"]
                    if opts.get("state") == "hidden":
                        continue
                    tags = item["tags"]
                    glow = float(opts.get("glow", 0))
                    if effects and not glow and any(t in ("shot", "bolt", "boom") for t in tags):
                        glow = 5.0
                    if glow:
                        tint = opts.get("glow_color") or opts.get("fill") or opts.get("outline", "#FFFFFF")
                        for width, alpha in ((glow * 2, .035), (glow, .075), (glow * .4, .12)):
                            self._draw(item, alpha, extra=width, tint=tint)
                    shadow = opts.get("shadow")
                    if effects and shadow is None and any(
                            len(tag) > 1 and tag[0] in "bh" and tag[1:].isdigit() for tag in tags):
                        shadow = (1.5, 2.5, 2.0)
                    if shadow:
                        dx, dy, blur = shadow if isinstance(shadow, (tuple, list)) else (2, 3, 3)
                        self._draw(item, .07, (dx, dy), float(blur) * 2, "#000000")
                        self._draw(item, .14, (dx, dy), float(blur), "#000000")
                    self._draw(item)
        finally:
            checked(invoke(self.target, 49, HR, (P, P), None, None), "EndDraw")
        if present:
            self.window.follow(self.hwnd, self.width, self.height, self.visible)
            checked(invoke(self.swap, 8, HR, (U, U), 0, 0), "Present")
        self.frames += 1
        self.frame_ms = (time.perf_counter() - started) * 1000

    def resize(self, width, height):
        self._check_thread()
        width, height = max(1, int(width)), max(1, int(height))
        if (width, height) == (self.width, self.height):
            return
        for name in ("brush", "target", "surface"):
            release(getattr(self, name))
            setattr(self, name, None)
        checked(invoke(self.swap, 13, HR, (U, U, U, U, U), 2, width, height, 87, 0), "ResizeBuffers")
        self.width, self.height = width, height
        self._make_target()

    def set_visible(self, visible):
        self.visible = bool(visible)
        if not visible:
            self.render(())

    def capture(self):
        """Read the current render buffer BEFORE Present; BGRA rows, premultiplied alpha."""
        self._check_thread()
        source = query(self.surface, "6f15aaf2-d208-4e89-9ab4-489535d34f9c")
        staging = P()
        mapped = False
        try:
            desc = TextureDesc(self.width, self.height, 1, 1, 87,
                               SampleDesc(1, 0), 3, 0, 0x20000, 0)
            checked(invoke(self.device, 5, HR, (P, P, P), C.byref(desc), None,
                           C.byref(staging)), "Create staging texture")
            invoke(self.context, 47, None, (P, P), staging, source)
            data = Mapped()
            checked(invoke(self.context, 14, HR, (P, U, U, U, P), staging, 0, 1, 0,
                           C.byref(data)), "Map staging texture")
            mapped = True
            return b"".join(C.string_at(data.data + row * data.row_pitch, self.width * 4)
                            for row in range(self.height))
        finally:
            if mapped:
                invoke(self.context, 15, None, (P, U), staging, 0)
            release(staging)
            release(source)

    def dispose(self):
        if self.closed:
            return
        self.closed = True
        if getattr(self, "comp_target", None):
            invoke(self.comp_target, 3, HR, (P,), None)
            invoke(self.composition, 3, HR, ())
        for layout, _w, _h in self.layouts.values():
            release(layout)
        self.layouts.clear()
        for fmt in self.formats.values():
            release(fmt)
        self.formats.clear()
        for name in ("brush", "target", "surface"):
            release(getattr(self, name, None))
            setattr(self, name, None)
        for obj in reversed(self._owned):
            release(obj)
        self._owned.clear()
        if self.window:
            self.window.dispose()
            self.window = None


class InputProxy:
    """Nearly invisible, nonactivating hit target for composition-only pixels.

    The visual host remains click-through. This small alpha=1 layered HWND is
    enabled only near a fighter; it queues mouse messages without reentering Tk.
    No hooks, injected input, or desktop-wide input interception are involved.
    """
    def __init__(self, visual=False, owner=0):
        if visual and not NATIVE_DESKTOP_ENABLED:
            raise RuntimeError("Native visual windows are disabled after an input-blocking regression")
        from ctypes import wintypes as W
        self.user = C.WinDLL("user32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.gdi = C.WinDLL("gdi32")
        self.events = deque(maxlen=128)
        self.capturing = False
        self.hwnd = None
        self.closed = False
        self.visual = bool(visual)
        self.x = self.y = 0
        self._radius = None
        self._last_point = (0, 0)
        self._point_type = W.POINT
        self._wndproc_type = WINCALL(C.c_ssize_t, P, U, C.c_size_t, C.c_ssize_t)

        class WindowClass(C.Structure):
            _fields_ = [("style", U), ("proc", self._wndproc_type),
                        ("class_extra", C.c_int), ("window_extra", C.c_int),
                        ("instance", P), ("icon", P), ("cursor", P),
                        ("background", P), ("menu", C.c_wchar_p), ("name", C.c_wchar_p)]

        declarations = {
            "RegisterClassW": ([P], C.c_uint16),
            "UnregisterClassW": ([C.c_wchar_p, P], C.c_int),
            "CreateWindowExW": ([U, C.c_wchar_p, C.c_wchar_p, U, C.c_int, C.c_int,
                                  C.c_int, C.c_int, P, P, P, P], P),
            "DefWindowProcW": ([P, U, C.c_size_t, C.c_ssize_t], C.c_ssize_t),
            "SetLayeredWindowAttributes": ([P, U, C.c_ubyte, U], C.c_int),
            "SetWindowPos": ([P, P, C.c_int, C.c_int, C.c_int, C.c_int, U], C.c_int),
            "ShowWindow": ([P, C.c_int], C.c_int), "DestroyWindow": ([P], C.c_int),
            "SetCapture": ([P], P), "ReleaseCapture": ([], C.c_int),
            "ClientToScreen": ([P, P], C.c_int), "GetCursorPos": ([P], C.c_int),
            "UpdateWindow": ([P], C.c_int),
            "IsWindowVisible": ([P], C.c_int),
            "SetWindowRgn": ([P, P, C.c_int], C.c_int),
        }
        for name, (args, result) in declarations.items():
            fn = getattr(self.user, name)
            fn.argtypes, fn.restype = args, result
        self.kernel.GetModuleHandleW.argtypes, self.kernel.GetModuleHandleW.restype = [C.c_wchar_p], P
        self.gdi.GetStockObject.argtypes, self.gdi.GetStockObject.restype = [C.c_int], P
        self.gdi.CreateEllipticRgn.argtypes = [C.c_int, C.c_int, C.c_int, C.c_int]
        self.gdi.CreateEllipticRgn.restype = P
        self.gdi.DeleteObject.argtypes, self.gdi.DeleteObject.restype = [P], C.c_int
        self.instance = self.kernel.GetModuleHandleW(None)
        self.class_name = "GremlinInputProxy_%x" % id(self)
        self.callback = self._wndproc_type(self._message)
        self.window_class = WindowClass(0, self.callback, 0, 0, self.instance,
                                       None, None, None if visual else self.gdi.GetStockObject(4),
                                       None, self.class_name)
        if not self.user.RegisterClassW(C.byref(self.window_class)):
            raise C.WinError(C.get_last_error())
        try:
            style = 0x082000A8 if visual else 0x08080088
            self.hwnd = self.user.CreateWindowExW(style, self.class_name,
                                                  "Gremlin input", 0x80000000,
                                                  0, 0, 1, 1, P(owner) if owner else None,
                                                  None, self.instance, None)
            if not self.hwnd:
                raise C.WinError(C.get_last_error())
            # Alpha zero would be ignored by hit testing; one is visually
            # negligible yet has an input surface unlike a color-keyed host.
            if not visual and not self.user.SetLayeredWindowAttributes(self.hwnd, 0, 1, 2):
                raise C.WinError(C.get_last_error())
        except Exception:
            self.dispose()
            raise

    def _queue(self, kind, x, y):
        event = (kind, int(x), int(y))
        self._last_point = event[1:]
        if kind == "drag" and self.events and self.events[-1][0] == "drag":
            self.events[-1] = event
        else:
            self.events.append(event)

    def _message(self, hwnd, msg, wparam, lparam):
        if msg == 0x21:                 # WM_MOUSEACTIVATE: preserve foreground app
            return 3
        if msg == 0x84:                 # WM_NCHITTEST
            return -1 if self.visual else 1
        if msg in (0x200, 0x201, 0x202, 0x205):
            point = self._point_type(C.c_short(lparam & 0xFFFF).value,
                                     C.c_short((lparam >> 16) & 0xFFFF).value)
            self.user.ClientToScreen(hwnd, C.byref(point))
            if msg == 0x201:
                self.capturing = True
                self.user.SetCapture(hwnd)
                self._queue("down", point.x, point.y)
            elif msg == 0x202:
                self.capturing = False
                self._queue("up", point.x, point.y)
                self.user.ReleaseCapture()
            elif msg == 0x205:
                self._queue("right", point.x, point.y)
            elif self.capturing:
                self._queue("drag", point.x, point.y)
            return 0
        if msg == 0x215 and self.capturing:   # capture lost to another window
            self.capturing = False
            point = self._point_type()
            if self.user.GetCursorPos(C.byref(point)):
                self._queue("up", point.x, point.y)
            else:
                self._queue("up", *self._last_point)
        return self.user.DefWindowProcW(hwnd, msg, wparam, lparam)

    def follow(self, owner, width, height, visible):
        if not visible or not self.user.IsWindowVisible(P(owner)):
            self.user.ShowWindow(self.hwnd, 0)
            return
        point = self._point_type(0, 0)
        if not self.user.ClientToScreen(P(owner), C.byref(point)):
            raise C.WinError(C.get_last_error())
        self.user.SetWindowPos(self.hwnd, P(-1), point.x, point.y, width, height,
                               0x10 | 0x40 | 0x200)

    def set_interactive(self, active, x=0, y=0, radius=62):
        if self.closed:
            return
        if not active:
            self.hide()                # pause/hold must relinquish capture immediately
            return
        radius = max(4, min(160, int(radius)))
        if radius != self._radius:
            region = self.gdi.CreateEllipticRgn(0, 0, radius * 2, radius * 2)
            if not region or not self.user.SetWindowRgn(self.hwnd, region, 0):
                if region:
                    self.gdi.DeleteObject(region)
                raise RuntimeError("Cannot create the circular input region")
            self._radius = radius      # Windows owns a successful SetWindowRgn region
        self.x, self.y = int(x) - radius, int(y) - radius
        self.user.SetWindowPos(self.hwnd, P(-1), self.x, self.y, radius * 2, radius * 2,
                               0x10 | 0x40 | 0x200)
        self.user.UpdateWindow(self.hwnd)

    def poll(self):
        result = list(self.events)
        self.events.clear()
        return result

    def hide(self):
        if self.capturing:
            self.capturing = False
            self.user.ReleaseCapture()
            point = self._point_type()
            if self.user.GetCursorPos(C.byref(point)):
                self._queue("up", point.x, point.y)
            else:
                self._queue("up", *self._last_point)
        if self.hwnd:
            self.user.ShowWindow(self.hwnd, 0)

    def dispose(self):
        if self.closed:
            return
        self.hide()
        self.closed = True
        if self.hwnd:
            self.user.DestroyWindow(self.hwnd)
            self.hwnd = None
        self.user.UnregisterClassW(self.class_name, self.instance)


class Direct2DCanvas:
    """Canvas-compatible retained scene with automatic native-to-Tk recovery."""
    _extra = {"opacity", "glow", "glow_color", "shadow"}

    def __init__(self, tk_canvas, hwnd, width, height, mode="auto", effects=True):
        self.widget, self.hwnd = tk_canvas, int(hwnd)
        self.width, self.height = int(width), int(height)
        self.effects, self.visible = bool(effects), True
        self.items, self.order, self._tk_ids = {}, [], {}
        self._next = 1
        self.native = None
        self.last_error = ""
        self.frame_ms, self.frames = 0.0, 0
        self._retried = False
        self._input = None
        self._pending_input = []
        if mode != "tk":
            try:
                self.native = NativeRenderer(hwnd, width, height)
            except Exception as exc:
                self.last_error = str(exc)

    @property
    def backend_name(self):
        return "Direct2D / " + self.native.driver if self.native else "Tk fallback"

    @property
    def stats(self):
        return {"backend": self.backend_name, "native": bool(self.native),
                "frame_ms": self.frame_ms, "frames": self.frames,
                "last_error": self.last_error}

    def __getattr__(self, name):
        return getattr(self.widget, name)

    @staticmethod
    def _flatten(points):
        if len(points) == 1 and isinstance(points[0], (tuple, list)):
            points = points[0]
        out = tuple(float(v) for v in points)
        if any(not math.isfinite(v) for v in out):
            raise ValueError("Canvas coordinates must be finite")
        return out

    def _create(self, kind, points, options):
        tags = options.pop("tags", ())
        tags = (tags,) if isinstance(tags, str) else tuple(tags)
        ident, self._next = self._next, self._next + 1
        self.items[ident] = {"kind": kind, "coords": self._flatten(points),
                             "options": dict(options), "tags": tags}
        self.order.append(ident)
        if not self.native:
            self._create_tk(ident)
        return ident

    def create_line(self, *points, **options):
        return self._create("line", points, options)

    def create_oval(self, *points, **options):
        return self._create("oval", points, options)

    def create_rectangle(self, *points, **options):
        return self._create("rectangle", points, options)

    def create_text(self, *points, **options):
        return self._create("text", points, options)

    def _selected(self, target):
        if target == "all":
            return list(self.order)
        if target in self.items:
            return [target]
        return [i for i in self.order if target in self.items[i]["tags"]]

    def coords(self, ident, *points):
        item = self.items[ident]
        if points:
            item["coords"] = self._flatten(points)
            if not self.native:
                self.widget.coords(self._tk_ids[ident], *item["coords"])
        return list(item["coords"])

    def itemconfigure(self, target, **options):
        for ident in self._selected(target):
            self.items[ident]["options"].update(options)
            if not self.native:
                self.widget.itemconfigure(self._tk_ids[ident], **self._tk_options(options))

    itemconfig = itemconfigure

    def itemcget(self, ident, name):
        return str(self.items[ident]["options"].get(name, ""))

    def find_all(self):
        return tuple(self.order)

    def find_withtag(self, tag):
        return tuple(self._selected(tag))

    def gettags(self, ident):
        return self.items[ident]["tags"]

    def type(self, ident):
        return self.items[ident]["kind"]

    def tag_raise(self, tag, above=None):
        chosen = self._selected(tag)
        selected = set(chosen)
        remaining = [i for i in self.order if i not in selected]
        at = len(remaining)
        if above is not None:
            refs = self._selected(above)
            at = max((remaining.index(i) + 1 for i in refs if i in remaining), default=at)
        self.order = remaining[:at] + chosen + remaining[at:]
        if not self.native:
            for ident in self.order:
                self.widget.tag_raise(self._tk_ids[ident])

    def delete(self, *targets):
        selected = set(i for t in targets for i in self._selected(t))
        for ident in selected:
            if ident in self._tk_ids:
                self.widget.delete(self._tk_ids.pop(ident))
            self.items.pop(ident, None)
        self.order = [i for i in self.order if i not in selected]

    def bbox(self, target):
        boxes = []
        for ident in self._selected(target):
            item = self.items[ident]
            if item["options"].get("state") == "hidden":
                continue
            if not self.native:
                box = self.widget.bbox(self._tk_ids[ident])
                if box:
                    boxes.append(box)
                continue
            co, op = item["coords"], item["options"]
            if item["kind"] == "text":
                try:
                    w, h = self.native.text_size(str(op.get("text", "")), op.get("font", ("Segoe UI", 10)))
                except Exception as exc:
                    self._fallback(exc)
                    return self.bbox(target)
                anchor = op.get("anchor", "center")
                anchor = "" if anchor == "center" else anchor
                x = co[0] - (0 if "w" in anchor else w if "e" in anchor else w / 2)
                y = co[1] - (0 if "n" in anchor else h if "s" in anchor else h / 2)
                boxes.append((x - 1, y, x + w + 1, y + h))
            else:
                pad = float(op.get("width", 1)) / 2
                boxes.append((min(co[::2]) - pad, min(co[1::2]) - pad,
                              max(co[::2]) + pad, max(co[1::2]) + pad))
        if not boxes:
            return None
        return (math.floor(min(b[0] for b in boxes)), math.floor(min(b[1] for b in boxes)),
                math.ceil(max(b[2] for b in boxes)), math.ceil(max(b[3] for b in boxes)))

    def _tk_options(self, options):
        out = {k: v for k, v in options.items() if k not in self._extra}
        for name in ("fill", "outline"):
            value = out.get(name)
            if isinstance(value, str) and value.startswith("#") and len(value) == 9:
                out[name] = value[:7]
        return out

    def _create_tk(self, ident):
        item = self.items[ident]
        method = getattr(self.widget, "create_" + item["kind"])
        self._tk_ids[ident] = method(*item["coords"], tags=item["tags"],
                                    **self._tk_options(item["options"]))

    def _fallback(self, reason):
        self.last_error = str(reason)
        if self.native:
            self.native.dispose()
            self.native = None
        self._dispose_input()
        for ident in self.order:
            if ident not in self._tk_ids:
                self._create_tk(ident)

    def present(self):
        started = time.perf_counter()
        if self.native:
            try:
                self.native.render((self.items[i] for i in self.order), effects=self.effects)
            except Exception as exc:
                # A removed/reset device gets one reconstruction, never a retry
                # loop in every frame. The retained scene survives either route.
                if isinstance(exc, NativeError) and not self._retried:
                    self._retried = True
                    self.native.dispose()
                    self.native = None
                    try:
                        self.native = NativeRenderer(self.hwnd, self.width, self.height)
                        self.native.visible = self.visible
                        self.native.render((self.items[i] for i in self.order), effects=self.effects)
                    except Exception as retry:
                        self._fallback(retry)
                else:
                    self._fallback(exc)
        self.frames += 1
        self.frame_ms = (time.perf_counter() - started) * 1000

    def resize(self, width, height):
        self.width, self.height = int(width), int(height)
        if self.native:
            try:
                self.native.resize(width, height)
            except Exception as exc:
                self._fallback(exc)

    def set_visible(self, visible):
        self.visible = bool(visible)
        if not visible and self._input:
            self._input.hide()
        if self.native:
            try:
                self.native.set_visible(visible)
            except Exception as exc:
                self._fallback(exc)

    def set_interactive(self, active, x=0, y=0, radius=62):
        if not self.native or not self.visible:
            return
        try:
            if active and self._input is None:
                self._input = InputProxy()
            if self._input:
                self._input.set_interactive(active, x, y, radius)
        except Exception as exc:
            # Native pixels without working interaction would strand controls.
            self._fallback(exc)

    def poll_input(self):
        events, self._pending_input = self._pending_input, []
        if self._input:
            events.extend(self._input.poll())
        return events

    def _dispose_input(self):
        if self._input:
            self._input.dispose()
            self._pending_input.extend(self._input.poll())
            self._input = None

    def dispose(self):
        self._dispose_input()
        if self.native:
            self.native.dispose()
            self.native = None
