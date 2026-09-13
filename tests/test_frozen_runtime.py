"""Frozen storage/startup contracts and the real isolated diagnostic entrypoint."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import harness


class FrozenRuntime(unittest.TestCase):
    def test_data_and_resources_are_separate_when_frozen(self):
        from gremlin_paths import runtime_paths
        source = os.path.join(harness.ROOT, "_internal", "desktop_gremlin.py")
        resource, data = runtime_paths(source, frozen=True, local_app_data=harness.TMP)
        self.assertEqual(resource, os.path.dirname(source))
        self.assertEqual(data, os.path.join(harness.TMP, "DesktopGremlin"))
        self.assertEqual(runtime_paths(source, frozen=False), (resource, resource))

    def test_frozen_login_command_runs_the_exe_without_a_script_argument(self):
        from gremlin_paths import startup_command
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertEqual(startup_command(r"C:\bundle\_internal\desktop_gremlin.py",
                                            r"C:\My Apps\DesktopGremlin.exe"),
                             '"C:\\My Apps\\DesktopGremlin.exe"')
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertEqual(startup_command("main.py", "pythonw.exe"), '"pythonw.exe" "main.py"')

    def test_self_test_uses_owned_tk_and_isolated_files(self):
        # A missing diagnostic entry must fail before launching a normal overlay.
        self.assertIn('from gremlin_selftest import run',
                      Path(harness.SRC).read_text(encoding="utf-8"))
        report = Path(harness.scratch("frozen_runtime", "report.json"))
        report.unlink(missing_ok=True)
        proc = subprocess.run([sys.executable, "-B", os.path.join(harness.ROOT, "desktop_gremlin.py"),
                               "--self-test", str(report)], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["frozen"])
        self.assertFalse(result["native_enabled"])
        self.assertEqual(result["renderer"], "tk")
        self.assertTrue(all(result["checks"].values()), result["checks"])
        report.unlink()


if __name__ == "__main__":
    unittest.main()
