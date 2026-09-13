"""Platform import, XDG storage and safe Linux lifecycle regression checks."""
import os
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gremlin_paths


class RuntimeTests(unittest.TestCase):
    def test_linux_frozen_and_source_use_user_storage(self):
        data = os.path.abspath(tempfile.gettempdir())
        with mock.patch.object(sys, "platform", "linux"), mock.patch.dict(os.environ, {"XDG_DATA_HOME": data}):
            for frozen in (True, False):
                self.assertEqual(gremlin_paths.runtime_paths(__file__, frozen=frozen)[1],
                                 os.path.join(data, "DesktopGremlin"))

    @unittest.skipUnless(sys.platform == "linux", "Linux import and POSIX lock")
    def test_import_and_lock(self):
        import desktop_gremlin as gm
        self.assertFalse(gm.IS_WINDOWS)
        self.assertNotIn("win32gui", sys.modules)
        with tempfile.TemporaryDirectory() as scratch:
            self.assertTrue(gm.LINUX.claim_instance(scratch, "test"))
            self.assertFalse(gm.LINUX.claim_instance(scratch, "test"))
            gm.LINUX.release_instances()
            self.assertTrue(gm.LINUX.claim_instance(scratch, "test"))
            gm.LINUX.release_instances()

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("GREMLIN_ISOLATED_X11") == "1", "isolated Linux X server required")
    def test_withdrawn_start_and_shaped_lifecycle(self):
        import harness
        gm = harness.load("linux_runtime", crowd=2)
        app = None
        try:
            app = harness.build(gm)
            self.assertEqual(app.renderer_mode, "x11")
            self.assertEqual(app.root.state(), "withdrawn")
            self.assertFalse(app.can_move_icons())
            app.draw()
            app.root.update()
            self.assertNotEqual(app.root.state(), "withdrawn")
            app.set_held(True)
            self.assertEqual(app.root.state(), "withdrawn")
            app.set_held(False)
            self.assertEqual(app.root.state(), "withdrawn")
            app.draw()
            app.root.update()
            self.assertNotEqual(app.root.state(), "withdrawn")
            app.quit()
            self.assertFalse(app.running)
        finally:
            if app is not None:
                harness.teardown(gm, app)

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("GREMLIN_ISOLATED_X11") == "1", "isolated Linux X server required")
    def test_failed_presentation_cannot_schedule_after_quit(self):
        import harness
        gm = harness.load("linux_runtime_exit")
        app = harness.build(gm)
        scheduled = []
        try:
            app.check_environment = lambda: None
            app.draw = app.quit  # Same synchronous shutdown as a failed X request.
            with mock.patch.object(app.root, "after", side_effect=lambda delay, fn: scheduled.append(fn)), \
                    mock.patch.object(app.root, "mainloop", return_value=None):
                app.run()
                self.assertEqual(len(scheduled), 1)
                scheduled.pop()()
                self.assertFalse(app.running)
                self.assertEqual(scheduled, [])
                self.assertTrue(app.x11_overlay.closed)
                with self.assertRaisesRegex(RuntimeError, "closed"):
                    gm.LINUX.desktop()
        finally:
            harness.teardown(gm, app)

    @unittest.skipUnless(sys.platform == "linux" and os.environ.get("GREMLIN_ISOLATED_X11") == "1", "isolated Linux X server required")
    def test_restore_keeps_undo_until_window_manager_confirms(self):
        import harness
        gm = harness.load("linux_runtime_restore")
        app = harness.build(gm)
        try:
            app.nudged = {123: (20, 30)}
            gm.window_alive = lambda hwnd: True
            gm.place_window = lambda *args: True
            gm.confirm_window_position = lambda *args: False
            self.assertEqual(app.restore_windows(), 0)
            self.assertEqual(app.nudged, {123: (20, 30)})
            gm.confirm_window_position = lambda *args: True
            self.assertEqual(app.restore_windows(), 1)
            self.assertEqual(app.nudged, {})
        finally:
            harness.teardown(gm, app)


if __name__ == "__main__":
    unittest.main()
