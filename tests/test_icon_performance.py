"""Recovery caching and bounded shell work, using only isolated fake Explorer IPC."""
import os
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import harness


class IconPerformance(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("icon_performance")
        self.app = None
        self.shell = self.gm.ShellView()
        self.shell.lv, self.shell.proc, self.shell.remote = 1, 1, 4096
        self.labels = ["A", "B"]
        self.remote, self.messages, self.moves = {}, [], []
        self.last = None
        self.send_cost = 0.0
        self.clock = None

        def write(obj, off=0):
            self.remote[off] = obj
            return True

        def read(obj, off=0):
            message, index = self.last
            if message == self.gm.LVM_GETITEMTEXTW:
                obj.value = self.labels[index]
            elif message == self.gm.LVM_GETITEMPOSITION:
                obj.x, obj.y = 10, 20
            return True

        def send(hwnd, message, index, pointer, timeout=250):
            self.messages.append((message, index, timeout))
            self.last = message, index
            if self.clock is not None:
                self.clock[0] += self.send_cost
            if message == self.gm.LVM_GETITEMCOUNT:
                return len(self.labels)
            if message == self.gm.LVM_GETITEMTEXTW:
                return len(self.labels[index])
            if message == self.gm.LVM_FINDITEMW:
                info = self.remote[0]
                name = self.remote[info.psz - self.shell.remote].value
                return next((candidate for candidate in range(index + 1, len(self.labels))
                             if self.labels[candidate].casefold() == name.casefold()),
                            self.gm.ctypes.c_size_t(-1).value)
            if message == self.gm.LVM_SETITEMPOSITION32:
                self.assertTrue(self.gm._read_backup()["dirty"])
                point = self.remote[0]
                self.moves.append((index, point.x, point.y))
            return 1

        self.shell._write, self.shell._read = write, read
        self.gm.send_msg = send
        self.gm.SHELL = self.shell
        self.backup(dirty=True)

    def tearDown(self):
        extra = self.gm.BACKUP_PATH + ".replacement"
        if os.path.exists(extra):
            os.remove(extra)
        harness.teardown(self.gm, self.app)

    def backup(self, dirty=True, labels=None):
        labels = self.labels if labels is None else labels
        self.gm._write_backup({"icons": [[label, 10, 20] for label in labels],
                               "dirty": dirty})
        self.gm.BACKUP_OK, self.gm.LAYOUT_DIRTY = True, dirty

    def test_unchanged_recovery_is_parsed_once_but_identity_is_always_live(self):
        # The fake move checks persisted protection separately; exclude that
        # test-only read from the actual cache's parser-call measurement.
        protection = self.gm._backup_protection
        with mock.patch.object(self.gm.json, "loads", wraps=self.gm.json.loads) as read:
            for _ in range(200):
                self.assertEqual(protection()[1], {"A": 1, "B": 1})
            self.assertEqual(read.call_count, 1)
        for step in range(50):
            self.assertTrue(self.shell.set_item_pos(0, step, step))
        self.assertEqual(len(self.messages), 200)
        self.assertEqual(sum(message == self.gm.LVM_GETITEMTEXTW
                             for message, _i, _timeout in self.messages), 50)
        self.labels[0] = "Renamed"
        self.assertFalse(self.shell.set_item_pos(0, 500, 600))
        self.assertEqual(len(self.moves), 50)
        self.labels[:] = ["A", "A"]
        self.assertFalse(self.shell.set_item_pos(0, 500, 600))
        self.assertEqual(len(self.moves), 50)

    def test_deletion_and_external_corruption_invalidate_warmed_protection(self):
        self.assertTrue(self.shell.set_item_pos(0, 1, 2))
        os.remove(self.gm.BACKUP_PATH)
        self.assertFalse(self.shell.set_item_pos(0, 3, 4))
        self.assertFalse(self.gm.BACKUP_OK)
        self.backup()
        self.assertTrue(self.shell.set_item_pos(0, 5, 6))
        with open(self.gm.BACKUP_PATH, "w", encoding="utf-8") as out:
            out.write("broken")
        self.assertFalse(self.shell.set_item_pos(0, 7, 8))
        self.assertEqual(len(self.moves), 2)

    def test_atomic_replacement_with_same_size_and_mtime_rechecks_saved_names(self):
        self.assertTrue(self.shell.set_item_pos(0, 1, 2))
        path = self.gm.BACKUP_PATH
        stat = os.stat(path)
        with open(path, "r", encoding="utf-8") as original:
            changed = original.read().replace('"A"', '"C"')
        replacement = path + ".replacement"
        with open(replacement, "w", encoding="utf-8") as out:
            out.write(changed)
        os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        os.replace(replacement, path)
        self.assertEqual(os.stat(path).st_size, stat.st_size)
        self.assertEqual(os.stat(path).st_mtime_ns, stat.st_mtime_ns)
        self.assertFalse(self.shell.set_item_pos(0, 3, 4))
        self.assertEqual(len(self.moves), 1)

    def test_external_clean_replacement_is_durable_before_another_move(self):
        self.assertTrue(self.shell.set_item_pos(0, 1, 2))
        self.gm.atomic_write_json(self.gm.BACKUP_PATH,
                                  {"icons": [["A", 10, 20]], "dirty": False})
        self.assertTrue(self.gm.LAYOUT_DIRTY)
        with mock.patch.object(self.gm, "_write_backup", side_effect=OSError("injected")):
            self.assertFalse(self.shell.set_item_pos(0, 3, 4))
        self.assertEqual(len(self.moves), 1)
        self.assertFalse(self.gm._read_backup()["dirty"])
        self.assertTrue(self.shell.set_item_pos(0, 5, 6))
        self.assertTrue(self.gm._read_backup()["dirty"])

    def test_in_place_corruption_with_same_length_and_restored_mtime_is_rejected(self):
        self.assertTrue(self.shell.set_item_pos(0, 1, 2))
        path = self.gm.BACKUP_PATH
        stat = os.stat(path)
        with open(path, "rb") as source:
            original = source.read()
        with open(path, "wb") as changed:
            changed.write(b"!" + original[1:])
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        after = os.stat(path)
        self.assertEqual((after.st_ino, after.st_size, after.st_mtime_ns),
                         (stat.st_ino, stat.st_size, stat.st_mtime_ns))
        self.assertFalse(self.shell.set_item_pos(0, 3, 4))
        self.assertEqual(len(self.moves), 1)

    def test_read_denied_after_cache_warmup_cannot_authorize_a_move(self):
        self.assertTrue(self.shell.set_item_pos(0, 1, 2))
        with mock.patch("builtins.open", side_effect=PermissionError("injected")):
            self.assertFalse(self.shell.set_item_pos(0, 3, 4))
        self.assertFalse(self.gm.BACKUP_OK)
        self.assertEqual(len(self.moves), 1)
        self.assertTrue(self.shell.set_item_pos(0, 5, 6))

    def test_file_changed_during_validation_cannot_be_cached(self):
        actual_stamp = self.gm._backup_stamp
        reads = [0]

        def replace_while_reading():
            reads[0] += 1
            if reads[0] == 2:
                self.gm.atomic_write_json(self.gm.BACKUP_PATH,
                                          {"icons": [["C", 10, 20]], "dirty": True})
            return actual_stamp()

        with mock.patch.object(self.gm, "_backup_stamp", side_effect=replace_while_reading):
            self.assertFalse(self.shell.set_item_pos(0, 1, 2))
        self.assertFalse(self.moves)
        self.assertFalse(self.shell.set_item_pos(0, 3, 4))

    def test_frame_does_not_wait_for_scanner_lock(self):
        held, release = threading.Event(), threading.Event()

        def scan():
            with self.shell._lock:
                held.set()
                release.wait(2)

        worker = threading.Thread(target=scan)
        worker.start()
        try:
            self.assertTrue(held.wait(1))
            with self.shell.frame_budget():
                self.assertIsNone(self.shell.item_pos(0))
                self.assertFalse(self.shell.set_item_pos(0, 1, 2))
            self.assertFalse(self.messages)
        finally:
            release.set()
            worker.join(2)
        self.assertEqual(self.shell.item_pos(0), (10, 20))

    def test_allowance_is_cumulative_excludes_physics_and_is_thread_local(self):
        self.clock, self.send_cost = [0.0], .002
        with mock.patch.object(self.gm.time, "perf_counter", side_effect=lambda: self.clock[0]):
            with self.shell.frame_budget():
                self.clock[0] += .1  # expensive physics consumes no shell budget
                self.assertEqual(self.shell.count(), 2)
                self.clock[0] += .1
                with self.shell.frame_budget():  # nesting cannot reset allowance
                    self.assertEqual(self.shell.count(), 2)
                self.assertIsNone(self.shell.count())
                worker = threading.Thread(target=self.shell.count)
                worker.start()
                worker.join(1)
            self.assertEqual(self.shell.count(), 2)
        self.assertEqual(len(self.messages), 4)
        self.assertLessEqual(self.messages[0][2], 4)
        self.assertLessEqual(self.messages[1][2], 2)
        self.assertEqual([row[2] for row in self.messages[2:]], [250, 250])

    def test_expired_nested_identity_checks_never_send_a_move(self):
        self.clock, self.send_cost = [0.0], .0021
        with mock.patch.object(self.gm.time, "perf_counter", side_effect=lambda: self.clock[0]):
            with self.shell.frame_budget():
                self.assertFalse(self.shell.set_item_pos(0, 1, 2))
        self.assertFalse(self.moves)
        self.assertNotIn(self.gm.LVM_SETITEMPOSITION32, [row[0] for row in self.messages])
        self.assertTrue(self.shell.set_item_pos(0, 3, 4))

    def test_grabbing_a_carrier_budgets_the_actual_non_frame_drop_path(self):
        gm = self.gm
        gm.SHELL = harness.FakeShell([])
        real_tk = gm.tk.Tk

        def hidden_root():
            root = real_tk()
            root.withdraw()
            return root

        with mock.patch.object(gm.tk, "Tk", hidden_root):
            app = self.app = harness.build(gm)
        harness.fake_terrain(app, icons=[("A", 10, 20, 74, 84, 0)])
        gm.SHELL = self.shell
        gm.CFG["move_icons"] = True
        app.icons_locked = False
        fighter = app.fighters[0]
        fighter.x, fighter.y = app.ox + 200, app.oy + 300
        fighter.carry = {"idx": 0, "w": 64, "h": 64, "offx": 0, "offy": 0}
        timeouts = []

        def busy_shell(hwnd, message, index, pointer, timeout=250):
            timeouts.append(timeout)
            return None

        gm.send_msg = busy_shell
        app.on_down(SimpleNamespace(x=fighter.x - app.ox,
                                    y=fighter.y - 34 * fighter.sc - app.oy))
        self.assertTrue(fighter.grabbed)
        self.assertIsNone(fighter.carry)
        self.assertEqual(len(timeouts), 1)
        self.assertLessEqual(timeouts[0], 4)
        self.assertFalse(self.moves)
        self.assertIsNone(self.shell._frame_local.budget)


if __name__ == "__main__":
    unittest.main()
