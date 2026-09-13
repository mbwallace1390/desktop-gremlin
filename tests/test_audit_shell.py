"""Recovery survives failed Explorer reads, partial restores, and disk errors.

All Windows calls are replaced before use. Only harness scratch files are written.
"""
import copy
import os
import sys
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

gm = harness.load("audit_shell")
bad = []
layout = [["A", 10, 20], ["B", 70, 80]]


def check(ok, text):
    if not ok:
        bad.append(text)


def backup(dirty=False):
    data = {"icons": copy.deepcopy(layout), "dirty": dirty, "saved": "original"}
    gm._write_backup(data)
    gm.BACKUP_OK, gm.LAYOUT_DIRTY = True, dirty
    return data


def view():
    """Run the real ShellView methods against an in-memory ListView protocol."""
    shell = gm.ShellView()
    shell.lv, shell.proc, shell.remote = 1, 1, 4096
    shell.open = lambda: True
    state = {"labels": ["A", "B"], "pos": [(300, 400), (500, 600)],
             "last": None, "buffer": None, "remote": {}, "writes": [], "fail": None,
             "fail_index": None, "write_ok": True, "read_ok": True,
             "ignore_position": None, "rearrange_previous": False}

    def write(obj, off=0):
        state["buffer"] = obj
        state["remote"][off] = obj
        return state["write_ok"]

    def read(obj, off=0):
        if not state["read_ok"]:
            return False
        msg, idx = state["last"]
        if msg == gm.LVM_GETITEMPOSITION:
            obj.x, obj.y = state["pos"][idx]
        elif msg == gm.LVM_GETITEMTEXTW:
            obj.value = state["labels"][idx]
        return True

    def send(hwnd, msg, idx, pointer):
        state["last"] = (msg, idx)
        if msg == state["fail"] and (state["fail_index"] is None
                                      or idx == state["fail_index"]):
            return None
        if msg == gm.LVM_GETITEMCOUNT:
            return len(state["labels"])
        if msg == gm.LVM_GETITEMTEXTW:
            return len(state["labels"][idx])
        if msg == gm.LVM_FINDITEMW:
            info = state["remote"][0]
            name = state["remote"][info.psz - shell.remote].value
            return next((i for i in range(idx + 1, len(state["labels"]))
                         if state["labels"][i].casefold() == name.casefold()),
                        gm.ctypes.c_size_t(-1).value)
        if msg == gm.LVM_SETITEMPOSITION32:
            state["writes"].append(idx)
            if idx != state["ignore_position"]:
                state["pos"][idx] = (state["buffer"].x, state["buffer"].y)
            if idx == 1 and state["rearrange_previous"]:
                state["pos"][0] = (333, 444)
        return 1

    shell._write, shell._read = write, read
    gm.send_msg = send
    gm.SHELL = shell
    return shell, state


try:
    # Failure is distinct from a real zero position; incomplete reads never replace undo.
    shell, state = view()
    state["pos"][0] = (0, 0)
    check(shell.item_pos(0) == (0, 0), "valid origin position was rejected")
    state["fail"] = gm.LVM_GETITEMPOSITION
    check(shell.item_pos(0) is None and shell.snapshot() == [],
          "timed-out positions became a valid origin snapshot")
    original = backup()
    check(gm.backup_layout() == "existing" and gm._read_backup() == original,
          "failed snapshot replaced the validated recovery layout")
    state["fail"] = None
    for field in ("write_ok", "read_ok"):
        state[field] = False
        check(shell.item_pos(0) is None and shell.snapshot() == [],
              field + " failure was accepted as a position")
        state[field] = True
    state["fail"], state["fail_index"] = gm.LVM_GETITEMTEXTW, 1
    check(shell.snapshot() == [], "one unreadable label left a partial valid snapshot")
    state["fail"] = gm.LVM_GETITEMCOUNT
    state["fail_index"] = None
    check(shell.snapshot() == [], "failed item count was accepted")
    state["fail"] = None
    raw = gm.ShellView()
    raw.proc, raw.remote = 1, 4096

    def short_transfer(proc, address, buffer, size, transferred):
        transferred._obj.value = size - 1
        return 1

    with mock.patch.object(gm, "kernel32", SimpleNamespace(
            WriteProcessMemory=short_transfer, ReadProcessMemory=short_transfer)):
        check(not raw._write(gm.wt.POINT()) and not raw._read(gm.wt.POINT()),
              "short remote memory transfer was accepted as complete")
    count = iter((2, 3))
    shell.count = lambda: next(count)
    check(shell.snapshot() == [], "changing inventory was accepted as a stable snapshot")
    check(not gm._valid_snapshot([['A', float('nan'), 2]]), "NaN snapshot passed validation")
    for invalid in ([['', 1, 2]], [['A', True, 2]],
                    [['A', 2 ** 31, 2]], [['A', 1]], [], {'A': (1, 2)}):
        gm.atomic_write_json(gm.BACKUP_PATH, {"icons": invalid})
        check(not gm._valid_snapshot(invalid) and gm._read_backup() is None,
              "invalid snapshot passed validation")

    # A failed flush or replace preserves exact original bytes and removes temporary files.
    backup()
    with open(gm.BACKUP_PATH, "rb") as f:
        before = f.read()
    for call in ("fsync", "replace"):
        with mock.patch.object(gm.os, call, side_effect=OSError("injected " + call)):
            try:
                gm._write_backup({"icons": [["A", 9, 9]], "dirty": True})
                check(False, call + " error was hidden")
            except OSError:
                pass
        with open(gm.BACKUP_PATH, "rb") as f:
            check(f.read() == before, call + " failure destroyed the original backup")
        leftovers = [p for p in os.listdir(harness.TMP)
                     if p.startswith("." + os.path.basename(gm.BACKUP_PATH) + ".")]
        check(not leftovers, call + " failure left an atomic-write temporary file")
    fdopen = gm.os.fdopen

    class PartialWriter:
        def __init__(self, *args, **kwargs):
            self.stream = fdopen(*args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def write(self, text):
            self.stream.write(text[:7])
            raise OSError("injected partial write")

    with mock.patch.object(gm.os, "fdopen", PartialWriter):
        try:
            gm._write_backup({"icons": [["A", 9, 9]], "dirty": True})
            check(False, "partial-write failure was hidden")
        except OSError:
            pass
    with open(gm.BACKUP_PATH, "rb") as f:
        check(f.read() == before, "partial write destroyed the original backup")

    # Recovery is marked BEFORE sending a move, and a failed mark is retried safely.
    backup()
    shell, state = view()
    with mock.patch.object(gm, "_write_backup", side_effect=OSError("read-only backup")):
        check(not shell.set_item_pos(0, 1, 2) and not state["writes"],
              "icon moved before failed protection was persisted")
        check(not gm.LAYOUT_DIRTY, "failed dirty write latched the runtime flag")
    check(shell.set_item_pos(0, 1, 2) and gm.LAYOUT_DIRTY
          and gm._read_backup()["dirty"], "successful retry did not persist protection")
    backup()
    send = gm.send_msg

    def inspect_dirty(*args):
        if args[1] == gm.LVM_SETITEMPOSITION32:
            check(gm._read_backup()["dirty"], "move reached Explorer before dirty flag")
        return send(*args)

    gm.send_msg = inspect_dirty
    check(shell.set_item_pos(0, 8, 9), "protected icon move was rejected")
    backup()
    os.remove(gm.BACKUP_PATH)
    state["writes"].clear()
    check(not shell.set_item_pos(0, 3, 4) and not state["writes"] and not gm.BACKUP_OK,
          "missing recovery file still allowed movement")

    # Count only verified restores; no-op writes, timeouts, and failed labels retain dirty.
    gm.win32gui = SimpleNamespace(InvalidateRect=lambda *a: None)
    for failure in ("write", "label", "readback", "ignored"):
        backup(True)
        shell, state = view()
        if failure == "ignored":
            state["ignore_position"] = 1
        else:
            state["fail"] = {"write": gm.LVM_SETITEMPOSITION32,
                             "label": gm.LVM_GETITEMTEXTW,
                             "readback": gm.LVM_GETITEMPOSITION}[failure]
            state["fail_index"] = 1
        n = gm.restore_layout()
        check(n == 1 and not shell.restore_complete and gm.LAYOUT_DIRTY
              and gm._read_backup()["dirty"], failure + " partial restore cleared protection")
        check(gm.backup_layout() == "kept", failure + " partial restore lost original on relaunch")
    backup(False)
    shell, state = view()
    state["ignore_position"] = 1
    check(gm.restore_layout() == 1 and gm._read_backup()["dirty"],
          "partial restore of an initially clean backup was not protected")
    backup(True)
    shell, state = view()
    state["rearrange_previous"] = True
    check(gm.restore_layout() == 1 and not shell.restore_complete and gm.LAYOUT_DIRTY,
          "later Explorer rearrangement invalidated an earlier verified icon")
    backup(True)
    shell, state = view()
    check(gm.restore_layout() == 2 and shell.restore_complete and not gm.LAYOUT_DIRTY
          and not gm._read_backup()["dirty"], "verified complete restore stayed dirty")
    backup(True)
    shell, state = view()
    with mock.patch.object(gm, "_write_backup", side_effect=OSError("cannot clear flag")):
        check(gm.restore_layout() == 2 and gm.LAYOUT_DIRTY and gm._read_backup()["dirty"],
              "failed clean-flag write incorrectly cleared runtime protection")
    backup(True)
    shell, state = view()
    state["labels"], state["pos"] = ["A", "new"], [(300, 400), (900, 900)]
    check(gm.restore_layout() == 1 and shell.restore_complete and not gm.LAYOUT_DIRTY,
          "deleted saved icon or new unrelated icon prevented verified applicable restore")
finally:
    harness.teardown(gm, None)

print("shell recovery audit: " + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
sys.exit(1 if bad else 0)
