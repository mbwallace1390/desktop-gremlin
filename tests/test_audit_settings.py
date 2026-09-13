"""Settings failures must be visible, and checks must leave the desktop alone."""
import json
import math
import os
import unittest
from types import SimpleNamespace
from unittest import mock

import harness


class SettingsAudit(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("audit_settings")

    def tearDown(self):
        for const, _ in harness._FILES:
            path = getattr(self.gm, const)
            if os.path.exists(path):
                os.remove(path)

    def write_settings(self, values):
        with open(self.gm.SETTINGS_PATH, "w", encoding="utf-8") as out:
            json.dump(values, out)

    def window(self):
        window = self.gm.SettingsWindow.__new__(self.gm.SettingsWindow)
        window.vars = {"crowd": SimpleNamespace(get=lambda: 3)}
        window.app = SimpleNamespace(apply_settings=mock.Mock())
        window.status = SimpleNamespace(config=mock.Mock())
        return window

    def test_invalid_numbers_do_not_discard_valid_settings(self):
        for invalid in (float("nan"), float("inf"), -float("inf"), 10 ** 400):
            self.write_settings({"scale": invalid, "fps": invalid, "chaos": invalid,
                                 "idle_minutes": invalid, "crowd": 7,
                                 "move_icons": True})
            cfg = self.gm.load_settings()
            for key in ("scale", "fps", "chaos", "idle_minutes"):
                self.assertEqual(cfg[key], self.gm.DEFAULTS[key])
                self.assertTrue(math.isfinite(cfg[key]))
            self.assertEqual(cfg["crowd"], 7)
            self.assertTrue(cfg["move_icons"])

    def test_failed_settings_save_preserves_previous_file(self):
        self.write_settings({"crowd": 4})
        with mock.patch.object(self.gm.os, "replace", side_effect=OSError("disk unavailable")):
            self.assertFalse(self.gm.save_settings({"crowd": 8}))
        with open(self.gm.SETTINGS_PATH, encoding="utf-8") as saved:
            self.assertEqual(json.load(saved), {"crowd": 4})
        self.assertTrue(self.gm.save_settings({"crowd": 8}))
        self.assertEqual(self.gm.load_settings()["crowd"], 8)

    def test_forget_failure_is_reported_and_can_be_retried(self):
        gm = self.gm
        gm.bump(gm.ROSTER[0], "thrown", 12)
        self.assertTrue(gm.save_memory())
        window = self.window()
        with mock.patch.object(gm.os, "replace", side_effect=OSError("disk unavailable")):
            window.forget()
        message = window.status.config.call_args.kwargs["text"]
        self.assertIn("Could not erase", message)
        self.assertTrue(gm.MEM_DIRTY)
        self.assertEqual(gm.load_memory()["who"][gm.ROSTER[0]]["thrown"], 12)
        window.forget()
        self.assertIn("Forgotten", window.status.config.call_args.kwargs["text"])
        self.assertFalse(gm.MEM_DIRTY)
        self.assertEqual(gm.load_memory()["who"][gm.ROSTER[0]]["thrown"], 0)

    def test_apply_reports_each_failed_operation(self):
        for save_ok, startup_ok in ((False, True), (True, False), (False, False), (True, True)):
            window = self.window()
            with mock.patch.object(self.gm, "save_settings", return_value=save_ok), \
                    mock.patch.object(self.gm, "set_run_at_startup", return_value=startup_ok):
                window.apply()
            message = window.status.config.call_args.kwargs["text"]
            self.assertEqual("settings could not be saved" in message, not save_ok)
            self.assertEqual("startup could not be updated" in message, not startup_ok)
            window.app.apply_settings.assert_called_once_with()
            self.assertEqual(self.gm.CFG["crowd"], 3)

    def test_harness_isolates_initial_scan_and_icon_file(self):
        gm = self.gm
        app = None
        try:
            with mock.patch.object(gm.win32gui, "EnumWindows") as enumerate_windows, \
                    mock.patch.object(gm.win32process, "GetWindowThreadProcessId") as explorer, \
                    mock.patch.object(gm, "_write_ico", wraps=gm._write_ico) as icon:
                app = harness.build(gm)
            enumerate_windows.assert_not_called()
            explorer.assert_not_called()
            icon.assert_called_once_with(gm.ICON_PATH)
            self.assertEqual(os.path.commonpath((harness.TMP, gm.ICON_PATH)), harness.TMP)
            self.assertTrue(os.path.isfile(gm.ICON_PATH))
            self.assertEqual(app.terrain.icons, [])
            self.assertEqual(app.terrain.windows, [])
        finally:
            if app is not None:
                harness.teardown(gm, app)

    def test_apply_preserves_supported_long_idle_preference(self):
        gm = self.gm
        gm.virtual_screen = lambda: (0, 0, 480, 320)
        gm.monitors = lambda: [((0, 0, 480, 320), (0, 0, 480, 300))]
        gm.CFG["idle_minutes"] = 90.0
        self.assertTrue(gm.save_settings(gm.CFG))
        gm.CFG.update(gm.load_settings())
        app = harness.build(gm)
        app.root.withdraw()
        try:
            app.open_settings()
            window = app.settings_win
            window.win.withdraw()
            self.assertEqual(window.vars["idle_minutes"].get(), 90.0)
            window.vars["body_theme"].set("light")
            window.apply()
            self.assertEqual(gm.load_settings()["idle_minutes"], 90.0)
            self.assertEqual(gm.load_settings()["body_theme"], "light")
        finally:
            harness.teardown(gm, app)


if __name__ == "__main__":
    unittest.main()
