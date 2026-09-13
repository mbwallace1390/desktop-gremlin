"""Desktop input regression: native quarantine and a keyboard-only exit.

Win32 hotkey registration/delivery is faked; no physical input is injected.
The only real window is the ordinary Tk App, after a native-import tripwire
has been installed. All persisted files and desktop scans use the harness.
"""
import builtins
import contextlib
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import harness


@contextlib.contextmanager
def native_import_tripwire():
    """Fail before any native adapter can create an HWND, even if cached."""
    imported = []
    original = builtins.__import__

    def checked(name, *args, **kwargs):
        if name == "gremlin_renderer" or name.startswith("gremlin_renderer."):
            imported.append(name)
            raise AssertionError("Quarantined native renderer was imported")
        return original(name, *args, **kwargs)

    with mock.patch.object(builtins, "__import__", side_effect=checked):
        yield imported


class InputRecovery(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("input_recovery")

    def tearDown(self):
        harness.teardown(self.gm, None)

    @contextlib.contextmanager
    def small_app(self):
        """An owned, initially withdrawn Tk App; no tray or desktop input."""
        gm = self.gm
        make_root = gm.tk.Tk

        def withdrawn_root():
            root = make_root()
            root.withdraw()
            return root

        app = None
        try:
            with mock.patch.object(gm.tk, "Tk", withdrawn_root), \
                    mock.patch.object(gm, "virtual_screen", return_value=(80, 80, 240, 160)), \
                    mock.patch.object(gm, "monitors", return_value=[
                        ((80, 80, 320, 240), (80, 80, 320, 240))]), \
                    mock.patch.object(gm.Tray, "build", return_value=True), \
                    native_import_tripwire():
                app = harness.build(gm)
            harness.fake_terrain(app)
            yield app
        finally:
            if app is not None:
                harness.teardown(gm, app)

    def test_failed_cursor_read_preserves_last_valid_motion(self):
        # Ignoring GetCursorPos's BOOL return invents a jump to (0, 0), then
        # feeds that invented speed into scare reactions and the next throw.
        gm = self.gm
        with self.small_app() as app:
            app.mouse = dict(x=500, y=400, vx=10, vy=20, t=2)
            app.time = 3
            app.hover = app.fighters[0]
            previous = dict(app.mouse)
            for reader in (lambda pointer: 0, mock.Mock(side_effect=OSError("no cursor"))):
                with self.subTest(reader=reader), mock.patch.object(
                        gm, "user32", SimpleNamespace(GetCursorPos=reader)):
                    app.mouse = dict(previous)
                    app.hover = app.fighters[0]
                    gm.App.poll_cursor(app, .025)
                    self.assertEqual(app.mouse, previous)
                    self.assertIs(app.hover, app.fighters[0])

    def test_valid_cursor_read_still_updates_motion(self):
        gm = self.gm

        def cursor_position(pointer):
            point = gm.ctypes.cast(pointer, gm.ctypes.POINTER(gm.wt.POINT)).contents
            point.x, point.y = 510, 405
            return 1

        with self.small_app() as app, mock.patch.object(
                gm, "user32", SimpleNamespace(GetCursorPos=cursor_position)):
            app.mouse = dict(x=500, y=400, vx=10, vy=20, t=2)
            app.time = 3
            gm.App.poll_cursor(app, .025)
            self.assertEqual(app.mouse, dict(x=510, y=405, vx=400, vy=200, t=3))

    def test_fullscreen_hold_ends_tk_drag_before_hiding(self):
        # Withdrawing a grabbed fighter must not depend on a later mouse-up
        # reaching an invisible window. Drive the real handlers, no input injection.
        gm = self.gm
        with self.small_app() as app:
            fighter = app.fighters[0]
            app.on_down(SimpleNamespace(x=fighter.x - app.ox,
                                        y=fighter.y - app.oy - 34 * fighter.sc))
            self.assertTrue(fighter.grabbed)
            states_when_hidden = []
            withdraw = app.root.withdraw

            def hide():
                states_when_hidden.append(fighter.grabbed)
                withdraw()

            with mock.patch.object(app.root, "withdraw", hide):
                app.set_held(True)
            self.assertEqual(states_when_hidden, [False])
            self.assertEqual(app.root.state(), "withdrawn")
            self.assertEqual(fighter.state, "thrown")
            app.set_held(False)
            app.on_drag(SimpleNamespace(x=10, y=10))
            app.on_up(None)  # a late original release must not count twice
            self.assertFalse(fighter.grabbed)
            self.assertEqual(gm.MEM["who"][fighter.kind]["thrown"], 1)

    def test_fullscreen_hold_still_hides_if_drag_cleanup_fails(self):
        with self.small_app() as app:
            app.root.deiconify()
            self.assertEqual(app.root.state(), "normal")
            with mock.patch.object(app, "on_up", side_effect=RuntimeError("release failed")), \
                    contextlib.suppress(RuntimeError):
                app.set_held(True)
            self.assertTrue(app.held)
            self.assertEqual(app.root.state(), "withdrawn")

    def test_defaults_and_harness_use_the_same_renderer(self):
        gm = self.gm
        self.assertEqual(gm.DEFAULTS["renderer"], "tk")
        self.assertNotIn("renderer", harness.QUIET,
                         "Tests must not hide a different production default")
        self.assertEqual(gm.CFG["renderer"], gm.DEFAULTS["renderer"])

    def test_old_or_invalid_saved_renderer_cannot_enable_native(self):
        gm = self.gm
        for saved in ({}, {"renderer": "auto"}, {"renderer": "direct2d"},
                      {"renderer": "invalid"}, {"renderer": None},
                      {"renderer": "tk"}):
            with self.subTest(saved=saved):
                payload = dict(saved, crowd=7, body_theme="light")
                with open(gm.SETTINGS_PATH, "w", encoding="utf-8") as output:
                    json.dump(payload, output)
                with native_import_tripwire() as imports:
                    cfg = gm.load_settings()
                self.assertEqual(cfg["renderer"], "tk")
                self.assertEqual(cfg["crowd"], 7)
                self.assertEqual(cfg["body_theme"], "light")
                self.assertEqual(imports, [])

    def test_raw_configuration_cannot_import_or_construct_native(self):
        gm = self.gm
        app = gm.App.__new__(gm.App)
        app.tk_canvas = SimpleNamespace()
        app.canvas = app.tk_canvas
        app.renderer_error = ""
        app.hwnd, app.W, app.H = 1001, 640, 480
        app.fighters = []
        for requested in ("auto", "direct2d", "invalid", "tk", None):
            for previous in ("tk", "auto"):
                with self.subTest(requested=requested, previous=previous):
                    gm.CFG["renderer"] = requested
                    app.renderer_mode = previous
                    with native_import_tripwire() as imports:
                        app.configure_renderer()
                    self.assertEqual(imports, [])
                    self.assertIs(app.canvas, app.tk_canvas)
                    self.assertEqual(app.renderer_mode, "tk")
                    self.assertEqual(gm.CFG["renderer"], "tk")

    def test_native_guard_rejects_before_windows_or_graphics_are_created(self):
        import gremlin_renderer as renderer
        self.assertFalse(renderer.NATIVE_DESKTOP_ENABLED)
        with mock.patch.object(renderer.C, "WinDLL",
                               side_effect=AssertionError("native DLL loaded")) as dll, \
                mock.patch.object(renderer, "InputProxy",
                                  side_effect=AssertionError("native window created")) as proxy, \
                mock.patch.object(renderer.NativeRenderer, "_initialize",
                                  side_effect=AssertionError("graphics initialized")) as initialize:
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                renderer.NativeRenderer(1001, 640, 480)
            dll.assert_not_called()
            proxy.assert_not_called()
            initialize.assert_not_called()
        with mock.patch.object(renderer.C, "WinDLL",
                               side_effect=AssertionError("native DLL loaded")) as dll:
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                renderer.InputProxy(visual=True, owner=1001)
            dll.assert_not_called()

    @contextlib.contextmanager
    def fake_tray_api(self, registration=1, icon_failure=False):
        gm = self.gm
        handlers = {}

        def register_class(window_class):
            handlers.update(window_class.lpfnWndProc)
            return 1

        gui = SimpleNamespace(
            RegisterWindowMessage=lambda name: 0xC456,
            WNDCLASS=lambda: SimpleNamespace(), RegisterClass=register_class,
            CreateWindow=lambda *args: 1001, UpdateWindow=lambda *args: None,
            LoadImage=lambda *args: 1002, LoadIcon=lambda *args: 1003,
            Shell_NotifyIcon=mock.Mock(side_effect=(OSError("tray unavailable")
                                                   if icon_failure else None)),
            NIF_ICON=gm.win32gui.NIF_ICON, NIF_MESSAGE=gm.win32gui.NIF_MESSAGE,
            NIF_TIP=gm.win32gui.NIF_TIP, NIM_ADD=gm.win32gui.NIM_ADD,
            NIM_DELETE=gm.win32gui.NIM_DELETE,
        )
        user = SimpleNamespace(
            RegisterHotKey=mock.Mock(return_value=registration),
            UnregisterHotKey=mock.Mock(return_value=1),
        )
        with mock.patch.object(gm, "win32gui", gui), \
                mock.patch.object(gm, "user32", user), \
                mock.patch.object(gm, "_write_ico", return_value=gm.ICON_PATH):
            yield handlers, user

    def test_emergency_hotkey_registers_and_defers_matching_quit(self):
        gm = self.gm
        with self.fake_tray_api() as (handlers, user):
            tray = gm.Tray()
            self.assertIsNone(tray.quit_callback)
            self.assertFalse(tray.emergency_registered)
            quit_callback = tray.quit_callback = mock.Mock()
            tray.build()
            expected_modifiers = (gm.win32con.MOD_CONTROL | gm.win32con.MOD_ALT
                                  | gm.win32con.MOD_SHIFT | 0x4000)
            user.RegisterHotKey.assert_called_once_with(
                tray.hwnd, tray.HOTKEY_QUIT, expected_modifiers, ord("Q"))
            self.assertTrue(tray.emergency_registered)
            hotkey = handlers[gm.win32con.WM_HOTKEY]
            hotkey(tray.hwnd, gm.win32con.WM_HOTKEY, tray.HOTKEY_QUIT + 1, 0)
            self.assertEqual(tray.pending, [])
            hotkey(tray.hwnd, gm.win32con.WM_HOTKEY, tray.HOTKEY_QUIT, 0)
            quit_callback.assert_not_called()
            tray.drain()
            quit_callback.assert_called_once_with()
            tray.remove()
            tray.remove()
            user.UnregisterHotKey.assert_called_once_with(tray.hwnd, tray.HOTKEY_QUIT)
            self.assertFalse(tray.emergency_registered)

    def test_hotkey_registration_failure_is_not_reported_as_registered(self):
        gm = self.gm
        with self.fake_tray_api(registration=0) as (_handlers, user):
            tray = gm.Tray()
            tray.quit_callback = mock.Mock()
            tray.build()
            self.assertFalse(tray.emergency_registered)
            tray.remove()
            user.UnregisterHotKey.assert_not_called()

    def test_hotkey_does_not_depend_on_notification_icon(self):
        gm = self.gm
        with self.fake_tray_api(icon_failure=True) as (handlers, user):
            tray = gm.Tray()
            tray.quit_callback = mock.Mock()
            tray.build()
            self.assertFalse(tray.added)
            self.assertTrue(tray.emergency_registered)
            handlers[gm.win32con.WM_HOTKEY](
                tray.hwnd, gm.win32con.WM_HOTKEY, tray.HOTKEY_QUIT, 0)
            tray.drain()
            tray.quit_callback.assert_called_once_with()
            tray.remove()
            user.UnregisterHotKey.assert_called_once()

    def test_frame_loop_honors_keyboard_quit_when_paused_or_hidden(self):
        gm = self.gm
        for paused, held in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(paused=paused, held=held):
                scheduled = []
                app = gm.App.__new__(gm.App)
                app.running = True
                app.paused, app.held = paused, held
                app.settings_win = object()
                app.root = SimpleNamespace(after=lambda ms, fn: scheduled.append(fn),
                                           mainloop=lambda: None)
                app.tray = gm.Tray()
                app.tray.pump = lambda: None
                app.tray.quit_callback = lambda: setattr(app, "running", False)
                app.tray._on_hotkey(1001, gm.win32con.WM_HOTKEY,
                                    app.tray.HOTKEY_QUIT, 0)
                app.run()
                self.assertEqual(len(scheduled), 1)
                scheduled.pop()()
                self.assertFalse(app.running)
                self.assertEqual(scheduled, [], "quit must not schedule another frame")

    def test_quit_hides_overlay_and_finishes_after_cleanup_failures(self):
        gm = self.gm
        calls = []

        def fails(name):
            def operation(*args, **kwargs):
                calls.append(name)
                raise RuntimeError("injected " + name + " failure")
            return operation

        app = gm.App.__new__(gm.App)
        app.running = True
        app.hwnd = 0
        app.root = SimpleNamespace(withdraw=lambda: calls.append("hide"),
                                   destroy=lambda: calls.append("destroy"))
        app.close_performance = fails("performance")
        app.canvas = SimpleNamespace(dispose=fails("renderer"))
        app.tray = SimpleNamespace(remove=fails("tray"))
        with mock.patch.object(gm, "save_memory", side_effect=fails("memory")), \
                mock.patch.object(gm, "SHELL", SimpleNamespace(close=fails("shell"))):
            app.quit()
        self.assertFalse(app.running)
        self.assertIn("hide", calls)
        self.assertIn("destroy", calls)
        self.assertLess(calls.index("hide"), calls.index("renderer"))
        self.assertEqual(set(calls), {"hide", "performance", "renderer", "memory",
                                     "tray", "shell", "destroy"})

    def test_real_startup_with_legacy_auto_keeps_tk_and_only_tk_choice(self):
        gm = self.gm
        gm.CFG["renderer"] = "auto"
        app = None
        try:
            with native_import_tripwire() as imports:
                app = harness.build(gm)
                self.assertEqual(imports, [])
                self.assertIs(app.canvas, app.tk_canvas)
                self.assertEqual(app.renderer_mode, "tk")
                self.assertEqual(gm.CFG["renderer"], "tk")
                self.assertEqual(app.tray.quit_callback, app.quit)
                app.open_settings()
                settings = app.settings_win
                renderer_var = settings.vars["renderer"]
                self.assertEqual(renderer_var.get(), "tk")

                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)

                choices = [widget for widget in descendants(settings.win)
                           if isinstance(widget, gm.ttk.Combobox)
                           and str(widget.cget("textvariable")) == str(renderer_var)]
                self.assertEqual(len(choices), 1)
                self.assertEqual(tuple(choices[0].cget("values")), ("tk",))
                self.assertEqual(str(choices[0].cget("state")), "readonly")
        finally:
            if app is not None:
                harness.teardown(gm, app)


if __name__ == "__main__":
    unittest.main()
