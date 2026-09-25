"""The runner must never turn a partly invalid request into a green result."""
import contextlib
import io
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_all


class RunnerChecks(unittest.TestCase):
    def invoke(self, args, platform="win32", isolated=True):
        output = io.StringIO()
        child = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(run_all.sys, "platform", platform), \
                mock.patch.dict(os.environ, {"GREMLIN_ISOLATED_X11": "1" if isolated else "0"}), \
                mock.patch.object(run_all.subprocess, "run", return_value=child) as launch, \
                contextlib.redirect_stdout(output):
            code = run_all.main(args)
        return code, output.getvalue(), launch.call_args_list

    def test_unknown_name_does_not_run_the_valid_subset(self):
        code, output, calls = self.invoke(["gait", "not_a_check"])
        self.assertEqual(code, 2)
        self.assertIn("no such check: not_a_check", output)
        self.assertFalse(calls)

    def test_unknown_options_do_not_start_checks(self):
        for option in ("--quite", "-x", "--verbose=true"):
            with self.subTest(option=option):
                code, output, calls = self.invoke(["gait", option])
                self.assertEqual(code, 2)
                self.assertIn("unknown option: " + option, output)
                self.assertFalse(calls)

    def test_unavailable_check_does_not_run_the_valid_subset(self):
        code, output, calls = self.invoke(["gait", "icons"], platform="linux")
        self.assertEqual(code, 2)
        self.assertIn("check unavailable on linux: icons", output)
        self.assertNotIn("no such check", output)
        self.assertFalse(calls)

    def test_reports_unknown_and_unavailable_together(self):
        code, output, calls = self.invoke(["gait", "icons", "not_a_check"], platform="linux")
        self.assertEqual(code, 2)
        self.assertIn("no such check: not_a_check", output)
        self.assertIn("check unavailable on linux: icons", output)
        self.assertFalse(calls)

    def test_linux_still_requires_an_isolated_desktop(self):
        code, output, calls = self.invoke(["gait"], platform="linux", isolated=False)
        self.assertEqual(code, 2)
        self.assertIn("isolated Xvfb", output)
        self.assertFalse(calls)

    def test_valid_selection_and_verbose_options(self):
        for args in (["gait", "joints"], ["gait", "-v"], ["--verbose", "gait"]):
            with self.subTest(args=args):
                code, output, calls = self.invoke(args)
                self.assertEqual(code, 0)
                expected = [name for name in ("gait", "joints") if name in args]
                self.assertEqual([os.path.basename(call.args[0][1]) for call in calls],
                                 ["test_" + name + ".py" for name in expected])
                capture = not any(arg in ("-v", "--verbose") for arg in args)
                self.assertTrue(all(call.kwargs["capture_output"] == capture
                                    for call in calls))

    def test_linux_runs_shared_visual_checks(self):
        code, output, calls = self.invoke(["polish", "speech_layout", "settings_layout"], platform="linux")
        self.assertEqual(code, 0)
        self.assertEqual([os.path.basename(call.args[0][1]) for call in calls],
                         ["test_polish.py", "test_speech_layout.py", "test_settings_layout.py"])


if __name__ == "__main__":
    unittest.main()
