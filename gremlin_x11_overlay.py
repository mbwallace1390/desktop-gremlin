"""Tk's real canvas presented as an X11 SHAPE window.

The top-level starts withdrawn, with empty bounding AND input shapes. Every
frame replaces the bounding shape with its painted canvas geometry and limits
input to the shared fighter picker. X11 then delivers empty-space clicks to
the actual underlying process. No pointer/keyboard grabs or pixel readbacks.

SHAPE 1.1 protocol: https://www.x.org/archive/X11R7.5/doc/Xext/shape.pdf
"""
import ctypes as C
import ctypes.util
import math
import os
import sys
import threading


MAX_ITEMS = 12000
MAX_PIXELS = 128 * 1024 * 1024


def _dimensions(width, height):
    width, height = int(width), int(height)
    if not (0 < width <= 32767 and 0 < height <= 32767 and width * height <= MAX_PIXELS):
        raise ValueError("Unsupported X11 overlay dimensions")
    return width, height


def clip_line(x0, y0, x1, y1, width, height, margin=0):
    """Liang-Barsky clips before X11's signed 16-bit coordinate encoding."""
    dx, dy = x1 - x0, y1 - y0
    lo, hi = 0.0, 1.0
    for p, q in ((-dx, x0 + margin), (dx, width + margin - x0),
                 (-dy, y0 + margin), (dy, height + margin - y0)):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            lo = max(lo, r)
        else:
            hi = min(hi, r)
        if lo > hi:
            return None
    return tuple(int(round(v)) for v in (x0 + lo * dx, y0 + lo * dy,
                                        x0 + hi * dx, y0 + hi * dy))


def canvas_commands(canvas, width, height):
    """Capture only painted primitives; an invisible pooled item has no shape."""
    _dimensions(width, height)
    items = canvas.find_all()
    if len(items) > MAX_ITEMS:
        raise ValueError("X11 overlay canvas item limit exceeded")
    commands = []
    for item in items:
        if canvas.itemcget(item, "state") == "hidden":
            continue
        kind = canvas.type(item)
        if kind not in ("line", "oval", "rectangle", "text"):
            continue
        fill = bool(canvas.itemcget(item, "fill"))
        outline = kind in ("oval", "rectangle") and bool(canvas.itemcget(item, "outline"))
        if not (fill or outline):
            continue
        if kind == "text":
            if not canvas.itemcget(item, "text"):
                continue
            coords = canvas.bbox(item)
            if coords is None:
                continue
            stroke = 0
        else:
            coords = canvas.coords(item)
            stroke = float(canvas.itemcget(item, "width") or 1)
        coords = tuple(float(v) for v in coords)
        if len(coords) < 4 or len(coords) > 2048 or len(coords) % 2:
            raise ValueError("Invalid X11 canvas coordinates")
        if not all(math.isfinite(v) and abs(v) <= 1e9 for v in coords):
            raise ValueError("Invalid X11 canvas coordinate")
        if not math.isfinite(stroke) or not 0 <= stroke <= 2048:
            raise ValueError("Invalid X11 canvas stroke")
        # Fully distant effects are absent, rather than wrapping in X protocol.
        pad = max(1, stroke)
        if (max(coords[::2]) < -pad or min(coords[::2]) > width + pad or
                max(coords[1::2]) < -pad or min(coords[1::2]) > height + pad):
            continue
        commands.append((kind, coords, fill, outline, max(1, int(round(stroke)))))
    return commands


def fighter_regions(fighters, ox, oy, width, height):
    """Circles match App.near_fighter: radius 62, centre y - 34 * scale."""
    result = []
    for f in fighters:
        cx, cy = float(f.x) - ox, float(f.y) - 34 * float(f.sc) - oy
        if not (math.isfinite(cx) and math.isfinite(cy)):
            raise ValueError("Invalid fighter input position")
        if cx + 62 < 0 or cy + 62 < 0 or cx - 62 > width or cy - 62 > height:
            continue
        result.append((int(round(cx - 62)), int(round(cy - 62)), 124, 124))
    return result


class X11Overlay:
    """Main-thread-owned presentation; any failed frame withdraws permanently."""
    def __init__(self, root, canvas, quit_callback):
        self.root, self.canvas, self.quit_callback = root, canvas, quit_callback
        self.thread = threading.get_ident()
        self.display = None
        self.windows = ()
        self.closed = False
        self.failed = False
        self.error = ""
        self.visible = True
        self._mapped = False
        self._prepared = False
        self._errors = []
        self._size = None
        self._pixmaps = []
        self._gcs = []
        root.withdraw()
        try:
            if not sys.platform.startswith("linux"):
                raise RuntimeError("X11 desktop overlay requires Linux")
            if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
                raise RuntimeError("Wayland desktop interaction is not supported; sign in to an X11 session")
            if root.tk.call("tk", "windowingsystem") != "x11":
                raise RuntimeError("The desktop overlay requires Tk on X11")
            if not root.overrideredirect():
                raise RuntimeError("The X11 overlay must own an undecorated top-level")
            self._load()
            self.display = self.x.XOpenDisplay(None)
            if not self.display:
                raise RuntimeError("Cannot connect to the X11 desktop")
            from gremlin_x11 import register_error_display
            register_error_display(self.display, self._on_error)
            major, minor = C.c_int(), C.c_int()
            if not self.shape.XShapeQueryVersion(self.display, C.byref(major), C.byref(minor)):
                raise RuntimeError("X11 SHAPE extension is unavailable")
            if (major.value, minor.value) < (1, 1):
                raise RuntimeError("X11 SHAPE 1.1 input masks are required")
            root.update_idletasks()
            self.windows = self._top_levels(int(root.winfo_id()))
            self._allocate(1, 1)
            self._clear_masks(1, 1)
            self._apply_masks()
            self._sync()
        except Exception:
            self.close()
            raise

    def _load(self):
        self.x = C.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self.shape = C.CDLL(ctypes.util.find_library("Xext") or "libXext.so.6")
        ptr, xid, integer, uint = C.c_void_p, C.c_ulong, C.c_int, C.c_uint
        signatures = {
            "XOpenDisplay": (ptr, [C.c_char_p]), "XCloseDisplay": (integer, [ptr]),
            "XSync": (integer, [ptr, integer]), "XFree": (integer, [ptr]),
            "XQueryTree": (integer, [ptr, xid, C.POINTER(xid), C.POINTER(xid), C.POINTER(C.POINTER(xid)), C.POINTER(uint)]),
            "XCreatePixmap": (xid, [ptr, xid, uint, uint, uint]),
            "XFreePixmap": (integer, [ptr, xid]), "XCreateGC": (ptr, [ptr, xid, xid, ptr]),
            "XFreeGC": (integer, [ptr, ptr]), "XSetForeground": (integer, [ptr, ptr, xid]),
            "XSetLineAttributes": (integer, [ptr, ptr, uint, integer, integer, integer]),
            "XFillRectangle": (integer, [ptr, xid, ptr, integer, integer, uint, uint]),
            "XDrawRectangle": (integer, [ptr, xid, ptr, integer, integer, uint, uint]),
            "XDrawLine": (integer, [ptr, xid, ptr, integer, integer, integer, integer]),
            "XFillArc": (integer, [ptr, xid, ptr, integer, integer, uint, uint, integer, integer]),
            "XDrawArc": (integer, [ptr, xid, ptr, integer, integer, uint, uint, integer, integer]),
            "XUnmapWindow": (integer, [ptr, xid]),
        }
        for name, (restype, args) in signatures.items():
            function = getattr(self.x, name)
            function.restype, function.argtypes = restype, args
        self.shape.XShapeQueryVersion.restype = integer
        self.shape.XShapeQueryVersion.argtypes = [ptr, C.POINTER(integer), C.POINTER(integer)]
        self.shape.XShapeCombineMask.restype = None
        self.shape.XShapeCombineMask.argtypes = [ptr, xid, integer, integer, integer, xid, integer]

    def _top_levels(self, client):
        """Tk X11 owns a wrapper above winfo_id; mask the actual root child."""
        result = [client]
        child = client
        for _ in range(8):
            root, parent, count = C.c_ulong(), C.c_ulong(), C.c_uint()
            children = C.POINTER(C.c_ulong)()
            ok = self.x.XQueryTree(self.display, child, C.byref(root), C.byref(parent),
                                  C.byref(children), C.byref(count))
            if children:
                self.x.XFree(children)
            if not ok:
                raise RuntimeError("Cannot identify X11 overlay top-level")
            if not parent.value or parent.value == root.value:
                return tuple(result)
            child = parent.value
            result.append(child)
        raise RuntimeError("Unexpected X11 overlay parent hierarchy")

    def _on_error(self, event):
        if len(self._errors) < 8:
            self._errors.append((int(event.error_code), int(event.request_code)))

    def _sync(self):
        self.x.XSync(self.display, 0)
        if self._errors:
            errors, self._errors = self._errors, []
            raise RuntimeError("X11 overlay request failed: %r" % errors)

    def _check_thread(self):
        if threading.get_ident() != self.thread:
            raise RuntimeError("X11 overlay must run on Tk's main thread")

    def _free_masks(self):
        for gc in self._gcs:
            self.x.XFreeGC(self.display, gc)
        for pixmap in self._pixmaps:
            self.x.XFreePixmap(self.display, pixmap)
        self._gcs, self._pixmaps = [], []

    def _allocate(self, width, height):
        if self._size == (width, height):
            return
        self._free_masks()
        self._size = (width, height)
        for _ in range(2):
            pixmap = self.x.XCreatePixmap(self.display, self.windows[-1], width, height, 1)
            if not pixmap:
                raise RuntimeError("Cannot allocate X11 overlay mask")
            self._pixmaps.append(pixmap)
            gc = self.x.XCreateGC(self.display, pixmap, 0, None)
            if not gc:
                raise RuntimeError("Cannot allocate X11 overlay drawing context")
            self._gcs.append(gc)

    def _clear_masks(self, width, height):
        for pixmap, gc in zip(self._pixmaps, self._gcs):
            self.x.XSetForeground(self.display, gc, 0)
            self.x.XFillRectangle(self.display, pixmap, gc, 0, 0, width, height)
            self.x.XSetForeground(self.display, gc, 1)

    def _apply_masks(self):
        for window in self.windows:
            # Bounding first: moving actors never temporarily enlarge the input
            # region outside either the old or the new visible geometry.
            self.shape.XShapeCombineMask(self.display, window, 0, 0, 0, self._pixmaps[0], 0)
            self.shape.XShapeCombineMask(self.display, window, 2, 0, 0, self._pixmaps[1], 0)

    def _paint(self, commands, width, height):
        pixmap, gc = self._pixmaps[0], self._gcs[0]
        d, x = self.display, self.x
        for kind, coords, fill, outline, stroke in commands:
            x.XSetLineAttributes(d, gc, stroke, 0, 2, 1)  # Solid, CapRound, JoinRound.
            if kind == "line":
                for i in range(0, len(coords) - 2, 2):
                    segment = clip_line(*coords[i:i + 4], width, height, min(stroke, 2048))
                    if segment:
                        bounded = [max(-32768, min(32767, v)) for v in segment]
                        x.XDrawLine(d, pixmap, gc, *bounded)
                continue
            left, right = sorted((coords[0], coords[2]))
            top, bottom = sorted((coords[1], coords[3]))
            # Shapes generated by the engine are small. Refuse oversized ovals
            # instead of silently wrapping the X11 protocol and masking a screen.
            if left < -32768 or top < -32768 or right > 32767 or bottom > 32767:
                if kind == "oval":
                    raise ValueError("Oversized X11 oval")
                left, top = max(0, left), max(0, top)
                right, bottom = min(width, right), min(height, bottom)
            a, b = int(round(left)), int(round(top))
            w, h = max(1, int(round(right - left))), max(1, int(round(bottom - top)))
            if kind == "oval":
                if fill:
                    x.XFillArc(d, pixmap, gc, a, b, w, h, 0, 360 * 64)
                if outline:
                    x.XDrawArc(d, pixmap, gc, a, b, w, h, 0, 360 * 64)
            elif kind == "text":
                x.XFillRectangle(d, pixmap, gc, a, b, w, h)
            else:
                if fill:
                    x.XFillRectangle(d, pixmap, gc, a, b, w, h)
                if outline:
                    x.XDrawRectangle(d, pixmap, gc, a, b, w, h)

    def present(self, fighters, ox=0, oy=0):
        self._check_thread()
        if self.closed or self.failed:
            return False
        try:
            # Idle tasks settle canvas dimensions and render Tk's own pixels;
            # they cannot map the initially withdrawn top-level.
            self.root.update_idletasks()
            width = max(int(self.canvas.winfo_width()), int(float(self.canvas.cget("width"))))
            height = max(int(self.canvas.winfo_height()), int(float(self.canvas.cget("height"))))
            width, height = _dimensions(width, height)
            commands = canvas_commands(self.canvas, width, height)
            regions = fighter_regions(fighters, ox, oy, width, height)
            self._allocate(width, height)
            self._clear_masks(width, height)
            self._paint(commands, width, height)
            for region in regions:
                self.x.XFillArc(self.display, self._pixmaps[1], self._gcs[1], *region, 0, 360 * 64)
            self._apply_masks()
            self._sync()  # Accepted by the X server before the first map.
            self._prepared = True
            if self.visible and not self._mapped:
                self.root.deiconify()
                self.root.lift()
                self._mapped = True
                self.root.update_idletasks()
                # Override-redirect keeps Tk's wrapper stable. If a platform
                # changes it on map, withdraw immediately instead of proceeding.
                if self._top_levels(int(self.root.winfo_id())) != self.windows:
                    raise RuntimeError("X11 overlay wrapper changed during mapping")
            return True
        except Exception as exc:
            self.error = str(exc)
            self.failed = True
            self.hide()
            try:
                self.quit_callback()
            except Exception:
                pass
            return False

    def hide(self):
        self._check_thread()
        self.visible = False
        self._mapped = False
        try:
            self.root.withdraw()
        except Exception:
            pass
        if self.display and self.windows:
            self.x.XUnmapWindow(self.display, self.windows[-1])
            self.x.XSync(self.display, 0)

    def clear(self):
        """Remove painted and interactive regions without mapping the window."""
        self._check_thread()
        if self.closed or self.failed:
            return False
        try:
            self._clear_masks(*self._size)
            self._apply_masks()
            self._sync()
            self._prepared = False
            return True
        except Exception as exc:
            self.error = str(exc)
            self.failed = True
            self.hide()
            try:
                self.quit_callback()
            except Exception:
                pass
            return False

    def show(self):
        self._check_thread()
        if self.closed or self.failed:
            return False
        # Mapping is deferred until present rebuilds the current frame's masks.
        self.visible = True
        return True

    def close(self):
        self._check_thread()
        if self.closed:
            return
        self.hide()
        self.closed = True
        if self.display:
            self._free_masks()
            self.x.XSync(self.display, 0)
            from gremlin_x11 import unregister_error_display
            unregister_error_display(self.display)
            self.x.XCloseDisplay(self.display)
            self.display = None
