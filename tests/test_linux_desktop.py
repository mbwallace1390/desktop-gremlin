"""X11 desktop contract checks; no user's windows or mouse are touched."""
import ctypes as C
import importlib.util
import os
import sys
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class DesktopContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = importlib.util.find_spec("gremlin_x11")

    def api(self):
        self.assertIsNotNone(self.spec, "Linux X11 desktop service is missing")
        import gremlin_x11
        return gremlin_x11

    def service(self):
        api = self.api()
        desktop = api.X11Desktop.__new__(api.X11Desktop)
        desktop._lock = threading.RLock()
        desktop.display = 1
        desktop.root = 100
        desktop.screen = 0
        desktop._atoms = {}
        desktop._errors = []
        desktop._quit = None
        desktop._quit_key = 24
        desktop._quit_modifiers = []
        desktop._closed = False
        desktop._xrandr = None
        desktop._xss = None
        desktop.lib = mock.Mock()
        desktop.atom = lambda name: name
        desktop._property = lambda window, name: []
        return desktop

    def test_wayland_is_rejected_before_loading_x11(self):
        api = self.api()
        with mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":3"}, clear=True):
            with mock.patch.object(api.C, "CDLL") as dll:
                with self.assertRaisesRegex(RuntimeError, "X11"):
                    api.X11Desktop()
                dll.assert_not_called()

    def test_missing_display_is_clear_error(self):
        api = self.api()
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DISPLAY"):
                api.X11Desktop()

    def test_lists_only_visible_current_desktop_normal_windows(self):
        d = self.service()
        props = {(100, "_NET_CLIENT_LIST_STACKING"): [1, 2, 3, 4, 5, 6],
                 (100, "_NET_CURRENT_DESKTOP"): [2],
                 (2, "_NET_WM_WINDOW_TYPE"): ["_NET_WM_WINDOW_TYPE_DOCK"],
                 (3, "_NET_WM_STATE"): ["_NET_WM_STATE_HIDDEN"],
                 (4, "_NET_WM_DESKTOP"): [1],
                 (5, "_NET_WM_DESKTOP"): [0xffffffff]}
        d._property = lambda w, n: props.get((w, n), [])
        d.tracked_window_rect = lambda w: (10, 20, 310, 220) if w != 6 else None
        d._title = lambda w: "Window %s" % w
        self.assertEqual(d.read_windows(1), [("Window 5", 10, 20, 310, 220, 5)])

    def test_frame_extents_correct_negative_coordinates(self):
        api = self.api()
        d = self.service()
        d._property = lambda w, n: [8, 8, 30, 8] if n == "_NET_FRAME_EXTENTS" else []
        attr = api.XWindowAttributes()
        attr.width, attr.height, attr.map_state = 800, 600, 2
        d._attributes = lambda w: attr
        def translate(display, win, root, x, y, out_x, out_y, child):
            C.cast(out_x, C.POINTER(C.c_int))[0] = -1800
            C.cast(out_y, C.POINTER(C.c_int))[0] = 70
            return 1
        d.lib.XTranslateCoordinates.side_effect = translate
        self.assertEqual(d.window_rect(42), (-1808, 40, -992, 678))

    def test_missing_or_unmapped_windows_are_not_platforms(self):
        api = self.api()
        d = self.service()
        d._attributes = lambda w: None
        self.assertIsNone(d.tracked_window_rect(2))
        self.assertFalse(d.window_alive(2))
        attr = api.XWindowAttributes()
        attr.map_state = 0
        d._attributes = lambda w: attr
        self.assertIsNone(d.tracked_window_rect(2))

    def test_move_sends_ewmh_position_only_without_focus_or_resize(self):
        api = self.api()
        d = self.service()
        d.atom = lambda name: 97
        d.window_alive = lambda w: True
        d._property = lambda w, n: [97] if n == "_NET_SUPPORTED" else []
        events = []
        def send(display, root, propagate, mask, event):
            ev = C.cast(event, C.POINTER(api.XEvent)).contents.xclient
            events.append((root, propagate, mask, ev.type, ev.window, ev.message_type,
                           ev.format, list(ev.data.l)))
            return 1
        d.lib.XSendEvent.side_effect = send
        self.assertTrue(d.place_window(22, -400, 50))
        event = events[0]
        self.assertEqual(event[3:7], (33, 22, 97, 32))
        flags = event[7][0]
        self.assertEqual(event[7][1:3], [-400, 50])
        self.assertEqual(flags & (3 << 8), 3 << 8)
        self.assertEqual(flags & (3 << 10), 0)
        self.assertFalse(d.lib.XSetInputFocus.called)

    def test_unsupported_move_is_not_reported_successful(self):
        d = self.service()
        d.window_alive = lambda w: True
        self.assertFalse(d.place_window(22, 100, 100))
        d.lib.XSendEvent.assert_not_called()

    def test_pointer_failure_is_not_origin_motion(self):
        d = self.service()
        d.lib.XQueryPointer.return_value = 0
        self.assertIsNone(d.mouse())

    def test_quit_registers_only_one_chord_with_lock_variants(self):
        d = self.service()
        d.lib.XKeysymToKeycode.return_value = 24
        d._numlock_mask = lambda: 16
        callback = mock.Mock()
        self.assertTrue(d.register_quit(None, callback))
        masks = {call.args[2] for call in d.lib.XGrabKey.call_args_list}
        self.assertEqual(masks, {13, 15, 29, 31})
        self.assertFalse(d.lib.XGrabKeyboard.called)
        self.assertFalse(d.lib.XGrabPointer.called)

    def test_quit_partial_grab_failure_releases_every_variant(self):
        d = self.service()
        d.lib.XKeysymToKeycode.return_value = 24
        d._numlock_mask = lambda: 16
        def sync(*args):
            d._errors.append(10)
        d.lib.XSync.side_effect = sync
        self.assertFalse(d.register_quit(None, mock.Mock()))
        self.assertEqual(d.lib.XUngrabKey.call_count, 4)
        self.assertIsNone(d._quit)

    def test_close_is_idempotent(self):
        d = self.service()
        d.close()
        d.close()
        self.assertEqual(d.lib.XCloseDisplay.call_count, 1)

    def test_emergency_quit_works_while_a_mouse_button_is_held(self):
        api = self.api()
        d = self.service()
        callback = mock.Mock()
        d._quit, d._quit_modifiers = callback, [13, 15, 29, 31]
        d.lib.XPending.side_effect = [1, 0]
        def read_event(display, pointer):
            event = C.cast(pointer, C.POINTER(api.XEvent)).contents
            event.type, event.xkey.keycode = 2, 24
            event.xkey.state = 13 | (1 << 8)
        d.lib.XNextEvent.side_effect = read_event
        d.pump()
        callback.assert_called_once_with()

    def test_property_32_uses_native_long_stride_and_frees_buffer(self):
        api = self.api()
        d = self.service()
        values = (C.c_ulong * 3)(123, 0xffffffff, 456)
        def get_property(display, window, atom, offset, length, delete, requested,
                         actual, fmt, count, remaining, data):
            C.cast(fmt, C.POINTER(C.c_int))[0] = 32
            C.cast(count, C.POINTER(C.c_ulong))[0] = 3
            C.cast(data, C.POINTER(C.POINTER(C.c_ubyte)))[0] = C.cast(values, C.POINTER(C.c_ubyte))
            return 0
        d.lib.XGetWindowProperty.side_effect = get_property
        self.assertEqual(api.X11Desktop._property(d, 1, "prop"), [123, 0xffffffff, 456])
        d.lib.XFree.assert_called_once()

    def test_monitors_intersect_workarea_for_current_workspace(self):
        d = self.service()
        d.virtual_screen = lambda: (0, 0, 1920, 1080)
        props = {"_NET_CURRENT_DESKTOP": [1],
                 "_NET_WORKAREA": [0, 0, 1920, 1080, 0, 32, 1920, 1048]}
        d._property = lambda w, name: props.get(name, [])
        self.assertEqual(d.monitors(), [((0, 0, 1920, 1080), (0, 32, 1920, 1080))])

    def test_idle_milliseconds_are_seconds_and_missing_extension_is_zero(self):
        api = self.api()
        d = self.service()
        self.assertEqual(d.idle_seconds(), 0)
        d._xss = mock.Mock()
        def query(display, root, info):
            C.cast(info, C.POINTER(api.XScreenSaverInfo))[0].idle = 90123
            return 1
        d._xss.XScreenSaverQueryInfo.side_effect = query
        self.assertAlmostEqual(d.idle_seconds(), 90.123)

    def test_restore_confirmation_checks_real_position_not_delivery(self):
        d = self.service()
        self.assertTrue(hasattr(d, "confirm_position"), "Restore verification is missing")
        d.window_rect = lambda w: (800, 100, 1100, 500)
        self.assertFalse(d.confirm_position(2, 20, 30, timeout=0))
        d.window_rect = lambda w: (20, 30, 320, 430)
        self.assertTrue(d.confirm_position(2, 20, 30, timeout=0))

    def test_restore_confirmation_allows_delayed_window_manager(self):
        api = self.api()
        d = self.service()
        self.assertTrue(hasattr(d, "confirm_position"), "Restore verification is missing")
        d.window_rect = mock.Mock(side_effect=[(800, 100, 1100, 500), (20, 30, 320, 430)])
        with mock.patch.object(api.time, "sleep"):
            self.assertTrue(d.confirm_position(2, 20, 30))

    def test_virtual_screen_refreshes_after_resolution_change(self):
        api = self.api()
        d = self.service()
        attr = api.XWindowAttributes()
        attr.width, attr.height = 2560, 1440
        d._attributes = lambda w: attr
        d.lib.XDisplayWidth.return_value = 1280
        d.lib.XDisplayHeight.return_value = 720
        self.assertEqual(d.virtual_screen(), (0, 0, 2560, 1440))

    def test_primary_monitor_is_first_even_away_from_desktop_origin(self):
        api = self.api()
        d = self.service()
        monitors = (api.XRRMonitorInfo * 2)()
        monitors[0].x, monitors[0].width, monitors[0].height = 0, 1280, 720
        monitors[1].x, monitors[1].width, monitors[1].height = 1280, 1920, 1080
        monitors[1].primary = 1
        def get_monitors(display, root, active, count):
            C.cast(count, C.POINTER(C.c_int))[0] = 2
            return monitors
        d._xrandr = mock.Mock()
        d._xrandr.XRRGetMonitors.side_effect = get_monitors
        result = d.monitors()
        self.assertEqual(result[0][0], (1280, 0, 3200, 1080))
        self.assertEqual(result[1][0], (0, 0, 1280, 720))
        d._xrandr.XRRFreeMonitors.assert_called_once()


if __name__ == "__main__":
    unittest.main()
