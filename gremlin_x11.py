"""Bounded desktop services for an X11 session, with no desktop icon writes.

All Xlib calls use a dedicated Display guarded by one RLock. Initialize this
service before Tk so XInitThreads runs before the first Xlib connection. The
only input grab is the emergency quit chord; pointer/keyboard grabs are absent.
"""
import ctypes as C
import os
import sys
import threading
import time


Window = Atom = C.c_ulong
Display = C.c_void_p


class XWindowAttributes(C.Structure):
    _fields_ = [("x", C.c_int), ("y", C.c_int), ("width", C.c_int),
                ("height", C.c_int), ("border_width", C.c_int), ("depth", C.c_int),
                ("visual", C.c_void_p), ("root", Window), ("class_", C.c_int),
                ("bit_gravity", C.c_int), ("win_gravity", C.c_int),
                ("backing_store", C.c_int), ("backing_planes", C.c_ulong),
                ("backing_pixel", C.c_ulong), ("save_under", C.c_int),
                ("colormap", C.c_ulong), ("map_installed", C.c_int),
                ("map_state", C.c_int), ("all_event_masks", C.c_long),
                ("your_event_mask", C.c_long), ("do_not_propagate_mask", C.c_long),
                ("override_redirect", C.c_int), ("screen", C.c_void_p)]


class XErrorEvent(C.Structure):
    _fields_ = [("type", C.c_int), ("display", Display), ("resourceid", C.c_ulong),
                ("serial", C.c_ulong), ("error_code", C.c_ubyte),
                ("request_code", C.c_ubyte), ("minor_code", C.c_ubyte)]


class XMessageData(C.Union):
    _fields_ = [("b", C.c_char * 20), ("s", C.c_short * 10), ("l", C.c_long * 5)]


class XClientMessageEvent(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", Display), ("window", Window), ("message_type", Atom),
                ("format", C.c_int), ("data", XMessageData)]


class XKeyEvent(C.Structure):
    _fields_ = [("type", C.c_int), ("serial", C.c_ulong), ("send_event", C.c_int),
                ("display", Display), ("window", Window), ("root", Window),
                ("subwindow", Window), ("time", C.c_ulong), ("x", C.c_int),
                ("y", C.c_int), ("x_root", C.c_int), ("y_root", C.c_int),
                ("state", C.c_uint), ("keycode", C.c_uint), ("same_screen", C.c_int)]


class XEvent(C.Union):
    _fields_ = [("type", C.c_int), ("xclient", XClientMessageEvent),
                ("xkey", XKeyEvent), ("pad", C.c_long * 24)]


class XModifierKeymap(C.Structure):
    _fields_ = [("max_keypermod", C.c_int), ("modifiermap", C.POINTER(C.c_ubyte))]


class XRRMonitorInfo(C.Structure):
    _fields_ = [("name", Atom), ("primary", C.c_int), ("automatic", C.c_int),
                ("noutput", C.c_int), ("x", C.c_int), ("y", C.c_int),
                ("width", C.c_int), ("height", C.c_int), ("mwidth", C.c_int),
                ("mheight", C.c_int), ("outputs", C.POINTER(C.c_ulong))]


class XScreenSaverInfo(C.Structure):
    _fields_ = [("window", Window), ("state", C.c_int), ("kind", C.c_int),
                ("til_or_since", C.c_ulong), ("idle", C.c_ulong),
                ("event_mask", C.c_ulong)]


_ERROR_CALLBACK = C.CFUNCTYPE(C.c_int, Display, C.POINTER(XErrorEvent))
_error_lock = threading.RLock()
_error_displays = {}
_error_dispatcher = None
_previous_error_handler = None
_error_library = None


def _pointer_value(display):
    return int(display.value if hasattr(display, "value") else display or 0)


def register_error_display(display, callback):
    """Route errors on this connection; preserve other libraries' handlers."""
    global _error_dispatcher, _previous_error_handler, _error_library
    with _error_lock:
        if _error_dispatcher is None:
            _error_library = C.CDLL("libX11.so.6")
            _error_library.XSetErrorHandler.argtypes = [C.c_void_p]
            _error_library.XSetErrorHandler.restype = C.c_void_p

            @_ERROR_CALLBACK
            def dispatch(dpy, event):
                handler = _error_displays.get(_pointer_value(dpy))
                if handler is not None:
                    try:
                        handler(event.contents)
                    except Exception:
                        pass  # exceptions may never escape a C callback
                    return 0
                if _previous_error_handler is not None:
                    return _previous_error_handler(dpy, event)
                return 0

            _error_dispatcher = dispatch  # retain C callback for process lifetime
            previous = _error_library.XSetErrorHandler(C.cast(dispatch, C.c_void_p))
            if previous:
                _previous_error_handler = _ERROR_CALLBACK(previous)
        _error_displays[_pointer_value(display)] = callback


def unregister_error_display(display):
    with _error_lock:
        _error_displays.pop(_pointer_value(display), None)


def _bind(lib, name, result, args):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, args
    return fn


class X11Desktop:
    """Real X11 windows, work areas, pointer position and emergency quit."""
    icons_supported = False

    def __init__(self):
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
            raise RuntimeError("Desktop Gremlin requires an X11 desktop session. Sign in using Xorg/X11; Wayland desktop interaction is unsupported.")
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("No X11 DISPLAY is available. Start Desktop Gremlin from a graphical X11 session.")
        if not sys.platform.startswith("linux"):
            raise RuntimeError("The X11 desktop backend runs on Linux.")
        self._lock = threading.RLock()
        self._atoms, self._errors = {}, []
        self._quit, self._quit_key, self._quit_modifiers = None, 0, []
        self._closed = False
        self.display = None
        self._xrandr = self._xss = None
        try:
            self.lib = C.CDLL("libX11.so.6")
        except OSError as exc:
            raise RuntimeError("The X11 desktop library is unavailable: %s" % exc)
        if not _bind(self.lib, "XInitThreads", C.c_int, [])():
            raise RuntimeError("X11 thread initialization failed; Desktop Gremlin cannot safely start its desktop scanner.")
        self._bind_xlib()
        self.display = self.lib.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("Cannot connect to X11 DISPLAY. Check that the app is running in your own graphical session.")
        register_error_display(self.display, self._record_error)
        self.screen = self.lib.XDefaultScreen(self.display)
        self.root = self.lib.XRootWindow(self.display, self.screen)
        self._load_optional()

    def _bind_xlib(self):
        ptr_int = C.POINTER(C.c_int)
        ptr_ulong = C.POINTER(C.c_ulong)
        funcs = {
            "XOpenDisplay": (Display, [C.c_char_p]),
            "XCloseDisplay": (C.c_int, [Display]),
            "XDefaultScreen": (C.c_int, [Display]),
            "XRootWindow": (Window, [Display, C.c_int]),
            "XDisplayWidth": (C.c_int, [Display, C.c_int]),
            "XDisplayHeight": (C.c_int, [Display, C.c_int]),
            "XInternAtom": (Atom, [Display, C.c_char_p, C.c_int]),
            "XGetWindowProperty": (C.c_int, [Display, Window, Atom, C.c_long, C.c_long,
                                            C.c_int, Atom, ptr_ulong, ptr_int, ptr_ulong,
                                            ptr_ulong, C.POINTER(C.POINTER(C.c_ubyte))]),
            "XFree": (C.c_int, [C.c_void_p]),
            "XGetWindowAttributes": (C.c_int, [Display, Window, C.POINTER(XWindowAttributes)]),
            "XTranslateCoordinates": (C.c_int, [Display, Window, Window, C.c_int, C.c_int,
                                                ptr_int, ptr_int, ptr_ulong]),
            "XQueryPointer": (C.c_int, [Display, Window, ptr_ulong, ptr_ulong,
                                       ptr_int, ptr_int, ptr_int, ptr_int, C.POINTER(C.c_uint)]),
            "XSendEvent": (C.c_int, [Display, Window, C.c_int, C.c_long, C.POINTER(XEvent)]),
            "XFlush": (C.c_int, [Display]),
            "XSync": (C.c_int, [Display, C.c_int]),
            "XKeysymToKeycode": (C.c_ubyte, [Display, C.c_ulong]),
            "XGetModifierMapping": (C.POINTER(XModifierKeymap), [Display]),
            "XFreeModifiermap": (C.c_int, [C.POINTER(XModifierKeymap)]),
            "XGrabKey": (C.c_int, [Display, C.c_int, C.c_uint, Window, C.c_int, C.c_int, C.c_int]),
            "XUngrabKey": (C.c_int, [Display, C.c_int, C.c_uint, Window]),
            "XPending": (C.c_int, [Display]),
            "XNextEvent": (C.c_int, [Display, C.POINTER(XEvent)]),
        }
        for name, (result, args) in funcs.items():
            _bind(self.lib, name, result, args)

    def _load_optional(self):
        try:
            lib = C.CDLL("libXrandr.so.2")
            _bind(lib, "XRRGetMonitors", C.POINTER(XRRMonitorInfo),
                  [Display, Window, C.c_int, C.POINTER(C.c_int)])
            _bind(lib, "XRRFreeMonitors", None, [C.POINTER(XRRMonitorInfo)])
            self._xrandr = lib
        except (OSError, AttributeError):
            pass
        try:
            lib = C.CDLL("libXss.so.1")
            _bind(lib, "XScreenSaverQueryExtension", C.c_int,
                  [Display, C.POINTER(C.c_int), C.POINTER(C.c_int)])
            _bind(lib, "XScreenSaverQueryInfo", C.c_int,
                  [Display, Window, C.POINTER(XScreenSaverInfo)])
            first, error = C.c_int(), C.c_int()
            if lib.XScreenSaverQueryExtension(self.display, C.byref(first), C.byref(error)):
                self._xss = lib
        except (OSError, AttributeError):
            pass

    def _record_error(self, event):
        # Bounded diagnostics also let a synchronous request detect its failure.
        self._errors.append(event.error_code)
        del self._errors[:-32]

    def atom(self, name):
        with self._lock:
            if not self.display:
                return 0
            if name not in self._atoms:
                self._atoms[name] = int(self.lib.XInternAtom(self.display, name.encode("ascii"), 0))
            return self._atoms[name]

    def _property(self, window, name):
        """Read at most 16KiB; Xlib format-32 items occupy native longs."""
        with self._lock:
            if not self.display or not window:
                return []
            actual, count, remaining = Atom(), C.c_ulong(), C.c_ulong()
            fmt = C.c_int()
            data = C.POINTER(C.c_ubyte)()
            try:
                status = self.lib.XGetWindowProperty(self.display, window, self.atom(name),
                    0, 4096, 0, 0, C.byref(actual), C.byref(fmt), C.byref(count),
                    C.byref(remaining), C.byref(data))
                if status != 0 or not data:
                    return []
                if fmt.value == 32:
                    longs = C.cast(data, C.POINTER(C.c_ulong))
                    return [int(longs[i]) & 0xffffffff for i in range(min(count.value, 4096))]
                if fmt.value == 8:
                    return C.string_at(data, min(count.value, 16384))
                return []
            finally:
                if data:
                    self.lib.XFree(data)

    def _title(self, window):
        value = self._property(window, "_NET_WM_NAME") or self._property(window, "WM_NAME")
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace").replace("\x00", "").strip()[:512]
        return ""

    def _attributes(self, window):
        if not self.display or not window:
            return None
        attr = XWindowAttributes()
        if not self.lib.XGetWindowAttributes(self.display, window, C.byref(attr)):
            return None
        return attr

    def window_alive(self, window):
        with self._lock:
            return self._attributes(window) is not None

    def window_rect(self, window):
        with self._lock:
            attr = self._attributes(window)
            if attr is None or attr.width <= 0 or attr.height <= 0:
                return None
            x, y, child = C.c_int(), C.c_int(), Window()
            if not self.lib.XTranslateCoordinates(self.display, window, self.root, 0, 0,
                                                  C.byref(x), C.byref(y), C.byref(child)):
                return None
            extents = self._property(window, "_NET_FRAME_EXTENTS")
            left, right, top, bottom = (extents[:4] if len(extents) >= 4 else (0, 0, 0, 0))
            # Ignore malformed decorations rather than create giant platforms.
            if any(type(v) is not int or v < 0 or v > 2048 for v in (left, right, top, bottom)):
                left = right = top = bottom = 0
            return x.value - left, y.value - top, x.value + attr.width + right, y.value + attr.height + bottom

    def tracked_window_rect(self, window):
        with self._lock:
            attr = self._attributes(window)
            if attr is None or attr.map_state != 2 or attr.override_redirect:
                return None
            return self.window_rect(window)

    def read_windows(self, own_hwnd=0):
        with self._lock:
            clients = self._property(self.root, "_NET_CLIENT_LIST_STACKING") or self._property(self.root, "_NET_CLIENT_LIST")
            current = self._property(self.root, "_NET_CURRENT_DESKTOP")
            desktop = current[0] if current else 0
            hidden = self.atom("_NET_WM_STATE_HIDDEN")
            allowed = {self.atom("_NET_WM_WINDOW_TYPE_NORMAL"), self.atom("_NET_WM_WINDOW_TYPE_DIALOG")}
        result = []
        for window in list(dict.fromkeys(clients))[:1024]:
            # Release between clients: a long background scan must not hold
            # the display lock across every window and delay the quit chord.
            with self._lock:
                if window == own_hwnd:
                    continue
                kinds = self._property(window, "_NET_WM_WINDOW_TYPE")
                if kinds and not any(kind in allowed for kind in kinds):
                    continue
                if hidden in self._property(window, "_NET_WM_STATE"):
                    continue
                location = self._property(window, "_NET_WM_DESKTOP")
                if location and location[0] not in (desktop, 0xffffffff):
                    continue
                pid = self._property(window, "_NET_WM_PID")
                if pid and pid[0] == os.getpid():
                    continue  # includes our settings and performance windows
                rect = self.tracked_window_rect(window)
                title = self._title(window)
                if rect is not None and title and rect[2] - rect[0] >= 80 and rect[3] - rect[1] >= 50:
                    result.append((title,) + tuple(rect) + (window,))
        return result

    def place_window(self, window, x, y):
        """Ask the WM to move a frame. True means accepted for delivery only."""
        with self._lock:
            if not self.display or not self.window_alive(window):
                return False
            message = self.atom("_NET_MOVERESIZE_WINDOW")
            if message not in self._property(self.root, "_NET_SUPPORTED"):
                return False
            event = XEvent()
            event.xclient.type, event.xclient.send_event = 33, 1
            event.xclient.display, event.xclient.window = self.display, window
            event.xclient.message_type, event.xclient.format = message, 32
            # NorthWest gravity, x/y present, pager source. Width/height absent:
            # this never resizes, focuses, restacks or activates another window.
            event.xclient.data.l[:] = (1 | (3 << 8) | (2 << 12), int(x), int(y), 0, 0)
            self._errors.clear()
            sent = self.lib.XSendEvent(self.display, self.root, 0, (1 << 19) | (1 << 20), C.byref(event))
            self.lib.XSync(self.display, 0)
            return bool(sent) and not self._errors

    def foreground_window(self):
        with self._lock:
            active = self._property(self.root, "_NET_ACTIVE_WINDOW")
            if not active or not active[0] or not self.window_alive(active[0]):
                return None
            return self._title(active[0]), active[0]

    def confirm_position(self, window, x, y, timeout=.12):
        """Bounded verification for an explicit Restore, never a frame nudge.

        A delivered EWMH request can be ignored or delayed by the manager. The
        caller keeps its undo entry unless the real outer frame reaches x/y.
        The lock is released between samples so scans/hotkey pumping can run.
        """
        deadline = time.monotonic() + min(.25, max(0.0, float(timeout)))
        expected = int(x), int(y)
        while True:
            rect = self.window_rect(window)
            if rect is None:
                return False
            if rect[:2] == expected:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(.01, remaining))

    def virtual_screen(self):
        with self._lock:
            if not self.display:
                return 0, 0, 1280, 720
            # DisplayWidth/Height are cached at connection time. Query the root
            # so a dock/undock or resolution change updates the desktop bounds.
            attr = self._attributes(self.root)
            width = attr.width if attr is not None else self.lib.XDisplayWidth(self.display, self.screen)
            height = attr.height if attr is not None else self.lib.XDisplayHeight(self.display, self.screen)
            return 0, 0, max(1, width), max(1, height)

    def monitors(self):
        with self._lock:
            rectangles = []
            if self.display and self._xrandr is not None:
                count = C.c_int()
                ptr = self._xrandr.XRRGetMonitors(self.display, self.root, 1, C.byref(count))
                if ptr:
                    try:
                        for i in range(min(max(0, count.value), 64)):
                            mon = ptr[i]
                            if mon.width > 0 and mon.height > 0:
                                rect = (mon.x, mon.y, mon.x + mon.width, mon.y + mon.height)
                                if mon.primary:
                                    rectangles.insert(0, rect)
                                else:
                                    rectangles.append(rect)
                    finally:
                        self._xrandr.XRRFreeMonitors(ptr)
            if not rectangles:
                x, y, width, height = self.virtual_screen()
                rectangles = [(x, y, x + width, y + height)]
            areas = self._property(self.root, "_NET_WORKAREA")
            current = self._property(self.root, "_NET_CURRENT_DESKTOP")
            start = 4 * (current[0] if current else 0)
            area = None
            if start + 4 <= len(areas):
                x, y, width, height = areas[start:start + 4]
                # CARDINAL coordinates may encode negative values modulo 2^32.
                x = x - (1 << 32) if x >= (1 << 31) else x
                y = y - (1 << 32) if y >= (1 << 31) else y
                if width > 0 and height > 0:
                    area = (x, y, x + width, y + height)
            result = []
            for rect in rectangles:
                work = rect if area is None else (max(rect[0], area[0]), max(rect[1], area[1]),
                                                   min(rect[2], area[2]), min(rect[3], area[3]))
                result.append((rect, work if work[2] > work[0] and work[3] > work[1] else rect))
            return result

    def mouse(self):
        with self._lock:
            if not self.display:
                return None
            root, child = Window(), Window()
            rx, ry, wx, wy, mask = C.c_int(), C.c_int(), C.c_int(), C.c_int(), C.c_uint()
            if not self.lib.XQueryPointer(self.display, self.root, C.byref(root), C.byref(child),
                                         C.byref(rx), C.byref(ry), C.byref(wx), C.byref(wy), C.byref(mask)):
                return None
            return rx.value, ry.value, bool(mask.value & (1 << 8))

    def idle_seconds(self):
        with self._lock:
            if not self.display or self._xss is None:
                return 0.0
            info = XScreenSaverInfo()
            if not self._xss.XScreenSaverQueryInfo(self.display, self.root, C.byref(info)):
                return 0.0
            return max(0.0, info.idle / 1000.0)

    def fullscreen_app(self, own_hwnd=0):
        with self._lock:
            foreground = self.foreground_window()
            if not foreground or foreground[1] == own_hwnd:
                return False
            return self.atom("_NET_WM_STATE_FULLSCREEN") in self._property(foreground[1], "_NET_WM_STATE")

    @staticmethod
    def on_battery():
        """Read Linux power-supply state; unknown states do not throttle."""
        found_battery = False
        try:
            for name in os.listdir("/sys/class/power_supply")[:64]:
                path = os.path.join("/sys/class/power_supply", name)
                try:
                    with open(os.path.join(path, "type"), encoding="ascii") as file:
                        kind = file.read(64).strip()
                    if kind in ("Mains", "USB", "USB_C", "USB_PD"):
                        with open(os.path.join(path, "online"), encoding="ascii") as file:
                            if file.read(8).strip() == "1":
                                return False
                    elif kind == "Battery":
                        with open(os.path.join(path, "status"), encoding="ascii") as file:
                            found_battery |= file.read(64).strip() == "Discharging"
                except (OSError, UnicodeError):
                    continue
        except OSError:
            pass
        return found_battery

    def _numlock_mask(self):
        keycode = self.lib.XKeysymToKeycode(self.display, 0xff7f)  # XK_Num_Lock
        mapping = self.lib.XGetModifierMapping(self.display)
        if not mapping:
            return 0
        try:
            size = mapping.contents.max_keypermod
            if size <= 0 or size > 256:
                return 0
            for index in range(8 * size):
                if keycode and mapping.contents.modifiermap[index] == keycode:
                    return 1 << (index // size)
            return 0
        finally:
            self.lib.XFreeModifiermap(mapping)

    def register_quit(self, root, callback):
        """Register only Ctrl+Alt+Shift+Q. No Tk method is called here."""
        with self._lock:
            if not self.display:
                return False
            self._unregister_quit()
            keycode = int(self.lib.XKeysymToKeycode(self.display, ord("q")))
            if not keycode:
                return False
            base, numlock = 1 | 4 | 8, self._numlock_mask()
            variants = sorted({base, base | 2, base | numlock, base | numlock | 2})
            self._errors.clear()
            for modifiers in variants:
                self.lib.XGrabKey(self.display, keycode, modifiers, self.root, 0, 1, 1)
            self.lib.XSync(self.display, 0)
            self._quit_key, self._quit_modifiers = keycode, variants
            if self._errors:
                self._unregister_quit()
                return False
            self._quit = callback
            return True

    def _unregister_quit(self):
        if self.display:
            for modifiers in self._quit_modifiers:
                self.lib.XUngrabKey(self.display, self._quit_key, modifiers, self.root)
        self._quit, self._quit_modifiers = None, []

    def pump(self):
        """Drain a bounded queue; dispatch on the caller's Tk/main thread."""
        callback = None
        with self._lock:
            if not self.display:
                return
            for _ in range(64):
                if not self.lib.XPending(self.display):
                    break
                event = XEvent()
                self.lib.XNextEvent(self.display, C.byref(event))
                if event.type == 2 and event.xkey.keycode == self._quit_key:
                    # XKeyEvent.state also contains held pointer buttons. The
                    # emergency chord must still exit during a stuck drag.
                    if (event.xkey.state & 0xff) in self._quit_modifiers:
                        callback = self._quit
        if callback is not None:
            callback()

    def close(self):
        with self._lock:
            if not self.display:
                return
            self._unregister_quit()
            self.lib.XSync(self.display, 0)
            self.lib.XCloseDisplay(self.display)
            unregister_error_display(self.display)
            self.display = None
            self._closed = True
