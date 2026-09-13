"""Adaptive decoration must preserve gameplay and expose honest frame measurements."""
import json
import unittest
from types import SimpleNamespace
import harness

gm = harness.load("performance_upgrade", crowd=1)
from gremlin_performance import PerformanceMonitor


class PerformanceUpgrade(unittest.TestCase):
    def test_sustained_pressure_and_slow_recovery(self):
        monitor = PerformanceMonitor()
        monitor.record(.1, 20, 70, 1, .04, .025)
        self.assertEqual(monitor.detail, 1.0, "one slow frame must not change detail")
        for _ in range(80):
            monitor.record(.04, 5, 28, 2, 0, .025)
        self.assertLess(monitor.detail, 1.0)
        reduced = monitor.detail
        for _ in range(80):
            monitor.record(.025, 1, 3, 1, 0, .025)
        self.assertEqual(monitor.detail, reduced, "detail recovery needs sustained headroom")
        for _ in range(200):
            monitor.record(.025, 1, 3, 1, 0, .025)
        self.assertGreater(monitor.detail, reduced)
        snapshot = monitor.snapshot()
        self.assertAlmostEqual(snapshot["fps"], 40)
        self.assertAlmostEqual(snapshot["draw_ms"], 3)
        self.assertAlmostEqual(snapshot["dropped"], .04)
        monitor.record(.025, 1, 3, 1, 0, .025, automatic=False)
        self.assertEqual(monitor.detail, 1.0)

    def test_inactive_frames_and_bad_samples(self):
        monitor = PerformanceMonitor()
        for _ in range(100):
            monitor.record(.25, 1, 1, 0, 0, .025, active=False)
        self.assertEqual(monitor.detail, 1.0)
        count = len(monitor.samples)
        monitor.record(float("nan"), 1, 1, 0, 0, .025)
        self.assertEqual(len(monitor.samples), count)

    def test_effect_detail_and_controls(self):
        app = harness.build(gm)
        harness.fake_terrain(app)
        try:
            gm.random.seed(401)
            before = gm.random.getstate()
            gm.CFG["effects_quality"] = 1.0
            app.spark(100, 100, 40, gm.FIRE, 200)
            full_count = len(app.parts)
            app.parts.clear()
            gm.CFG["effects_quality"] = .25
            app.spark(100, 100, 40, gm.FIRE, 200)
            self.assertEqual(len(app.parts), full_count // 4)
            app.shake(.3, 5)
            app.draw()
            self.assertEqual(gm.random.getstate(), before,
                             "visual detail/draws consumed gameplay randomness")
            app.open_settings()
            win = app.settings_win
            self.assertEqual(set(win.vars), set(gm.DEFAULTS))
            win.vars["body_theme"].set("light")
            win.vars["outline"].set(True)
            win.apply()
            cfg = gm.load_settings()
            self.assertEqual(cfg["body_theme"], "light")
            self.assertTrue(cfg["outline"])
            self.assertEqual(cfg["renderer"], "tk")
            win.close()
            app.open_performance()
            self.assertIsNotNone(app.performance_after)
            app.close_performance()
            self.assertIsNone(app.performance_after)
            self.assertIsNone(app.performance_win)
        finally:
            harness.teardown(gm, app)

    def test_new_settings_validate_independently(self):
        with open(gm.SETTINGS_PATH, "w", encoding="utf-8") as out:
            json.dump(dict(renderer="invalid", body_theme="light",
                           halo_strength=99, effects_quality=-5, crowd=7), out)
        cfg = gm.load_settings()
        self.assertEqual(cfg["renderer"], "tk")
        self.assertEqual(cfg["body_theme"], "light")
        self.assertEqual(cfg["halo_strength"], 2.0)
        self.assertEqual(cfg["effects_quality"], .25)
        self.assertEqual(cfg["crowd"], 7)

    def test_native_input_uses_existing_grab_and_throw_handlers(self):
        app = harness.build(gm)
        harness.fake_terrain(app)
        original = app.canvas
        events, active = [], []
        adapter = SimpleNamespace(poll_input=lambda: list(events),
                                  set_interactive=lambda *args: active.append(args))
        try:
            f = app.fighters[0]
            f.x, f.y = app.ox + 150, app.oy + 250
            app.hover = f
            app.canvas = adapter
            events[:] = [("down", f.x, f.y - 34 * f.sc)]
            app.poll_renderer_input()
            self.assertTrue(f.grabbed)
            events[:] = [("drag", f.x + 80, f.y - 60)]
            app.poll_renderer_input()
            self.assertEqual(f.gx, f.x + 80)
            events[:] = [("up", f.x + 80, f.y - 60)]
            app.poll_renderer_input()
            self.assertFalse(f.grabbed)
            self.assertEqual(f.state, "thrown")
            app.paused = True
            events[:] = [("down", f.x, f.y - 34 * f.sc)]
            app.poll_renderer_input()
            self.assertFalse(f.grabbed)
            self.assertFalse(active[-1][0])
        finally:
            app.canvas = original
            harness.teardown(gm, app)

    def test_switching_renderer_releases_grab_before_disposing_input(self):
        app = harness.build(gm)
        harness.fake_terrain(app)
        original, setting = app.canvas, gm.CFG["renderer"]
        disposed = []

        class CapturedAdapter:
            def __getattr__(self, name):
                return getattr(original, name)

            def dispose(self):
                # Native disposal queues WM_CAPTURECHANGED on the old adapter;
                # App will no longer poll that adapter after the switch.
                disposed.append(app.fighters[0].grabbed)

        try:
            f = app.fighters[0]
            f.x, f.y = app.ox + 150, app.oy + 250
            app.on_down(SimpleNamespace(x=150, y=250 - 34 * f.sc))
            self.assertTrue(f.grabbed)
            app.canvas = CapturedAdapter()
            app.renderer_mode, gm.CFG["renderer"] = "auto", "tk"
            app.configure_renderer()
            self.assertEqual(disposed, [False], "release must precede input HWND disposal")
            self.assertFalse(f.grabbed)
            self.assertEqual(f.state, "thrown")
            self.assertIs(app.canvas, original)
        finally:
            gm.CFG["renderer"] = setting
            app.canvas = original
            harness.teardown(gm, app)

    def test_native_drag_recovers_missing_mouse_messages(self):
        app = harness.build(gm)
        harness.fake_terrain(app)
        original, button_probe = app.canvas, gm.mouse_button_down
        active, button = [], [True]
        adapter = SimpleNamespace(native=object(), poll_input=lambda: [],
                                  set_interactive=lambda *args: active.append(args))
        try:
            f = app.fighters[0]
            f.x, f.y = app.ox + 150, app.oy + 250
            app.on_down(SimpleNamespace(x=150, y=250 - 34 * f.sc))
            app.canvas = adapter
            app.hover = None
            gm.mouse_button_down = lambda: button[0]
            # Simulate leaving the proxy's hit region: there is no queued
            # WM_MOUSEMOVE, but the normal cursor poll has a new position.
            app.mouse.update(x=f.x + 300, y=f.y - 150, vx=400, vy=-200)
            app.poll_renderer_input()
            self.assertTrue(f.grabbed)
            self.assertEqual((f.gx, f.gy),
                             (app.mouse["x"], app.mouse["y"] + 58 * f.sc))
            # An unavailable physical-button probe must not act as a release.
            button[0] = None
            app.poll_renderer_input()
            self.assertTrue(f.grabbed)
            # A real release must end the grab even without WM_LBUTTONUP.
            button[0] = False
            active.clear()
            app.poll_renderer_input()
            self.assertFalse(f.grabbed)
            self.assertEqual(f.state, "thrown")
            self.assertGreater(f.vx, 0)
            self.assertFalse(active[0][0], "release stale Win32 capture explicitly")
            # Tk fallback already owns normal mouse delivery; do not poll its
            # physical button or overwrite its queued drag coordinates.
            app.on_down(SimpleNamespace(x=f.x - app.ox,
                                        y=f.y - 34 * f.sc - app.oy))
            adapter.native = None
            before = f.gx, f.gy
            app.poll_renderer_input()
            self.assertTrue(f.grabbed)
            self.assertEqual((f.gx, f.gy), before)
        finally:
            gm.mouse_button_down = button_probe
            app.canvas = original
            harness.teardown(gm, app)

    def test_button_poll_respects_swapped_primary_mouse_button(self):
        original = gm.user32
        try:
            for swapped, expected in ((False, gm.win32con.VK_LBUTTON),
                                      (True, gm.win32con.VK_RBUTTON)):
                calls = []

                def key_state(key):
                    calls.append(key)
                    return 0x8000 if key == expected else 0

                gm.user32 = SimpleNamespace(GetSystemMetrics=lambda key: int(swapped),
                                            GetAsyncKeyState=key_state)
                self.assertTrue(gm.mouse_button_down())
                self.assertEqual(calls, [expected])
                gm.user32.GetAsyncKeyState = lambda key: 1
                self.assertFalse(gm.mouse_button_down(), "recent-press bit is not held state")
            gm.user32 = SimpleNamespace()
            self.assertIsNone(gm.mouse_button_down(), "failed OS reads must stay unknown")
        finally:
            gm.user32 = original


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        import os
        for name, _ in harness._FILES:
            path = getattr(gm, name)
            if os.path.exists(path):
                os.remove(path)
