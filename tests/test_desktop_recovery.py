"""Only identifiable saved icons may move; failed window undo remains retryable.

Real shell/App methods run through the shared harness. The ListView protocol
and window placement boundary are in-memory stand-ins, never the desktop.
"""
import ctypes
import os
import unittest
from types import SimpleNamespace

import commctrl
import harness


class DesktopRecovery(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("desktop_recovery", crowd=1, move_windows=True)
        self.gm.monitors = lambda: [((0, 0, 1000, 800), (0, 0, 1000, 760))]
        self.gm.virtual_screen = lambda: (0, 0, 1000, 800)
        self.app = None

    def tearDown(self):
        harness.teardown(self.gm, self.app)

    def shell(self, labels=("A", "B"), positions=((10, 20), (70, 80))):
        gm = self.gm
        shell = gm.ShellView()
        shell.lv, shell.proc, shell.remote = 1, 1, 4096
        shell.open = lambda: True
        state = {"labels": list(labels), "positions": list(positions),
                 "remote": {}, "last": None, "messages": [], "fail": None}

        def write(obj, off=0):
            state["remote"][off] = obj
            return True

        def read(obj, off=0):
            msg, index = state["last"]
            if msg == gm.LVM_GETITEMPOSITION:
                obj.x, obj.y = state["positions"][index]
            elif msg == gm.LVM_GETITEMTEXTW:
                obj.value = state["labels"][index]
            return True

        def send(hwnd, msg, index, pointer):
            state["messages"].append((msg, index))
            state["last"] = (msg, index)
            if msg == state["fail"]:
                return None
            if msg == gm.LVM_GETITEMCOUNT:
                return len(state["labels"])
            if msg == gm.LVM_GETITEMTEXTW:
                return len(state["labels"][index])
            if msg == commctrl.LVM_FINDITEMW:
                if "find_result" in state:
                    return state["find_result"]
                info = state["remote"][0]
                self.assertEqual(info.flags, commctrl.LVFI_STRING)
                name = state["remote"][info.psz - shell.remote].value
                for candidate in range(index + 1, len(state["labels"])):
                    if state["labels"][candidate].casefold() == name.casefold():
                        return candidate
                # send_msg returns DWORD_PTR, so Windows' -1 arrives unsigned.
                return ctypes.c_size_t(-1).value
            if msg == gm.LVM_SETITEMPOSITION32:
                point = state["remote"][0]
                state["positions"][index] = (point.x, point.y)
            return 1

        shell._write, shell._read = write, read
        gm.SHELL, gm.send_msg = shell, send
        gm.win32gui = SimpleNamespace(InvalidateRect=lambda *args: None)
        if os.path.exists(gm.BACKUP_PATH):
            os.remove(gm.BACKUP_PATH)
        self.assertEqual(gm.backup_layout(), "saved")
        return shell, state

    def test_new_icon_is_untouched_while_saved_icon_moves_and_restores(self):
        shell, state = self.shell()
        state["labels"].append("New file")
        state["positions"].append((130, 140))
        self.assertFalse(shell.set_item_pos(2, 500, 600))
        self.assertTrue(shell.set_item_pos(0, 300, 400))
        self.assertEqual(self.gm.restore_layout(), 2)
        self.assertEqual(state["positions"], [(10, 20), (70, 80), (130, 140)])
        self.assertFalse(self.gm.LAYOUT_DIRTY)
        self.assertEqual(self.gm._read_backup()["icons"], [["A", 10, 20], ["B", 70, 80]])

    def test_rename_during_carry_cannot_reuse_earlier_movement_permission(self):
        shell, state = self.shell()
        self.assertTrue(shell.set_item_pos(0, 300, 400))
        state["labels"][0] = "Renamed"
        self.assertFalse(shell.set_item_pos(0, 500, 600))
        self.assertEqual(state["positions"][0], (300, 400))
        self.assertTrue(self.gm.LAYOUT_DIRTY)
        self.assertEqual(self.gm._read_backup()["icons"], [["A", 10, 20], ["B", 70, 80]])

    def test_duplicate_labels_in_saved_layout_cannot_be_moved_ambiguously(self):
        shell, state = self.shell(labels=("Same", "Same"))
        self.assertFalse(shell.set_item_pos(0, 300, 400))
        self.assertFalse(shell.set_item_pos(1, 500, 600))
        self.assertEqual(state["positions"], [(10, 20), (70, 80)])

    def test_same_count_rename_to_duplicate_is_rechecked_before_every_move(self):
        shell, state = self.shell()
        self.assertTrue(shell.set_item_pos(1, 300, 400))
        state["labels"][0] = "B"
        self.assertFalse(shell.set_item_pos(0, 500, 600))
        self.assertFalse(shell.set_item_pos(1, 500, 600))
        self.assertEqual(state["positions"], [(10, 20), (300, 400)])

    def test_saved_unique_icon_stays_recoverable_after_indices_change(self):
        shell, state = self.shell()
        state["labels"][:] = ["B", "A"]
        state["positions"][:] = [(70, 80), (10, 20)]
        state["messages"].clear()
        self.assertTrue(shell.set_item_pos(1, 300, 400))
        self.assertTrue(shell.set_item_pos(1, 500, 600))
        # Identity checks stay bounded even on a desktop with hundreds of icons.
        self.assertLessEqual(len(state["messages"]), 8)
        self.assertEqual(self.gm.restore_layout(), 2)
        self.assertEqual(state["positions"], [(70, 80), (10, 20)])

    def test_unavailable_name_or_uniqueness_check_forbids_movement(self):
        for failure in (self.gm.LVM_GETITEMTEXTW, commctrl.LVM_FINDITEMW):
            with self.subTest(message=failure):
                shell, state = self.shell()
                state["fail"] = failure
                self.assertFalse(shell.set_item_pos(0, 500, 600))
                self.assertEqual(state["positions"], [(10, 20), (70, 80)])

    def test_malformed_identity_results_leave_icon_and_backup_unchanged(self):
        for result in (-2, 99999, False):
            with self.subTest(result=result):
                shell, state = self.shell()
                state["find_result"] = result
                self.assertFalse(shell.set_item_pos(0, 500, 600))
                self.assertEqual(state["positions"], [(10, 20), (70, 80)])
                self.assertFalse(self.gm._read_backup()["dirty"])

    def test_partial_window_restore_retries_only_the_failed_live_window(self):
        gm = self.gm
        app = self.app = harness.build(gm)
        windows = [("A", 200, 300, 400, 500, 42),
                   ("B", 400, 300, 600, 500, 43),
                   ("C", 600, 300, 800, 500, 44)]
        harness.fake_terrain(app, windows=windows)
        positions = {42: (200, 300), 43: (400, 300), 44: (600, 300)}
        failed, closed, writes, notices = set(), set(), [], []
        gm.window_rect = lambda hwnd: (*positions[hwnd], positions[hwnd][0] + 200,
                                      positions[hwnd][1] + 200)
        gm.window_alive = lambda hwnd: hwnd not in closed

        def place(hwnd, x, y):
            writes.append(hwnd)
            if hwnd in failed:
                return False
            positions[hwnd] = (x, y)
            return True

        gm.place_window = place
        app.tray.notify = lambda title, body: notices.append(body)
        for hwnd in (42, 43, 44):
            self.assertTrue(app.nudge_window(hwnd, 20, 0))
        failed.add(43)
        closed.add(44)
        self.assertEqual(app.restore_windows(), 1)
        self.assertEqual(app.nudged, {43: (400, 300)})
        self.assertEqual(set(app.nudged_at), {43})
        self.assertIn("incomplete", notices[-1].lower())
        writes.clear()
        failed.clear()
        self.assertEqual(app.restore_windows(), 1)
        self.assertEqual(writes, [43])
        self.assertEqual(positions[43], (400, 300))
        self.assertFalse(app.nudged)
        self.assertFalse(app.nudged_at)
        self.assertNotIn("incomplete", notices[-1].lower())


if __name__ == "__main__":
    unittest.main()
