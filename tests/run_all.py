#!/usr/bin/env python3
r"""Run every check. Nothing to install; each one drives the real app.

    python tests\run_all.py            all of them
    python tests\run_all.py gait joints    just those
    python tests\run_all.py -v         show each check's own output

Every one of these encodes a bug that actually shipped. They build a real Tk
window and a real App, so windows will flash on screen while they run; none of
them touch your desktop icons, because the shell is stubbed.

To prove a check still catches its bug, copy desktop_gremlin.py, put the bug
back in the copy, and point the check at it:

    set GREMLIN_SRC=C:\path\to\broken_copy.py
    python tests\run_all.py roaming

A check that passes against the broken copy is testing nothing.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

# name -> file, in rough order of how fast they are
CHECKS = [
    ("voices", "test_voices.py", "every line all ten of them can say"),
    ("settings", "test_settings.py", "saved settings surviving a restart"),
    ("memory", "test_memory.py", "what they remember between runs"),
    ("gait", "test_gait.py", "which way the legs cycle"),
    ("joints", "test_joints.py", "which way knees and elbows bow"),
    ("poses", "test_poses.py", "no broken limb in any pose"),
    ("diagnostics", "test_diagnostics.py", "logging and tray deferral"),
    ("runtime", "test_runtime.py", "the loop, the lock, the hold, the ring"),
    ("icons", "test_icons.py", "shoving real desktop icons"),
    ("range", "test_weapon_range.py", "shots reaching their target"),
    ("rides", "test_rides.py", "joyrides start, travel, end clean"),
    ("windows", "test_windows.py", "hanging, sitting, knocking on your window"),
    ("fight", "test_fight_choice.py", "firing the weapon he closed for"),
    ("behaviour", "test_behaviour.py", "greeting, context, rivalry"),
    ("crowd", "test_crowd.py", "one to ten, all behaving differently"),
    ("docs", "test_docs.py", "the docs still describe the code"),
    ("roaming", "test_roaming.py", "not getting stuck, leaving and returning"),
]


def main(argv):
    verbose = "-v" in argv or "--verbose" in argv
    wanted = [a for a in argv if not a.startswith("-")]
    picked = [c for c in CHECKS if not wanted or c[0] in wanted]
    if wanted and not picked:
        print("no such check: %s" % ", ".join(wanted))
        print("available: %s" % ", ".join(c[0] for c in CHECKS))
        return 2

    src = os.environ.get("GREMLIN_SRC")
    if src:
        print("checking %s\n" % src)

    failed = []
    t0 = time.perf_counter()
    for name, path, blurb in picked:
        print("%-12s %-42s " % (name, blurb), end="", flush=True)
        started = time.perf_counter()
        proc = subprocess.run([sys.executable, os.path.join(HERE, path)],
                              capture_output=not verbose, text=True)
        took = time.perf_counter() - started
        if proc.returncode == 0:
            print("pass  %5.1fs" % took)
        else:
            print("FAIL  %5.1fs" % took)
            failed.append((name, proc.stdout or "", proc.stderr or ""))

    print("\n%d/%d passed in %.0fs" % (len(picked) - len(failed), len(picked),
                                       time.perf_counter() - t0))
    for name, out, err in failed:
        print("\n" + "=" * 66)
        print("FAILED: %s" % name)
        print("=" * 66)
        tail = (out + err).strip().splitlines()
        for line in tail[-25:]:
            print("  " + line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
