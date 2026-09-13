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
    ("physics_mixed", "test_physics_mixed.py", "all physics presets, sizes and cleanup"),
    ("physics_upgrade", "test_physics_upgrade.py", "momentum, body sweeps, materials and grabs"),
    ("physics_arsenal", "test_physics_arsenal.py", "surface normals, ricochets and toy cover"),
    ("physical_props", "test_physical_props.py", "dynamic crates, seesaws and moving ropes"),
    ("ragdoll_physics", "test_ragdoll_physics.py", "joint limits, inertia and drawn recovery"),
    ("linux_runtime", "test_linux_runtime.py", "Linux storage, import and shaped lifecycle"),
    ("linux_desktop", "test_linux_desktop.py", "X11 windows, monitors and emergency exit"),
    ("linux_overlay", "test_linux_overlay.py", "real X11 cross-process input delivery"),
    ("linux_packaging", "test_linux_packaging.py", "Linux archive and frozen input gates"),
    ("frozen_runtime", "test_frozen_runtime.py", "bundled paths and isolated startup"),
    ("packaging", "test_packaging.py", "archive contents, privacy and checksums"),
    ("expansion_mixed", "test_expansion_mixed.py", "all engines, sizes and mode changes"),
    ("expansion_integration", "test_expansion_integration.py", "cast profiles and play modes"),
    ("expansion_arsenal", "test_expansion_arsenal.py", "seven weapons and timed effects"),
    ("expansion_motion", "test_expansion_motion.py", "parkour, planes, ropes and toys"),
    ("expansion_social", "test_expansion_social.py", "relationships and coordinated scenes"),
    ("input_recovery", "test_input_recovery.py", "Tk-only startup and keyboard escape"),
    ("desktop_recovery", "test_desktop_recovery.py", "backup coverage and retryable window undo"),
    ("behavior_recovery", "test_behavior_recovery.py", "first landings and delayed-shot ownership"),
    ("engine_upgrade", "test_engine_upgrade.py", "fixed timing, window tracking and routes"),
    ("visual_upgrade", "test_visual_upgrade.py", "pose transitions, contrast and impacts"),
    ("performance_upgrade", "test_performance_upgrade.py", "adaptive effects and live measurements"),
    ("renderer", "test_renderer.py", "native quarantine and Tk compatibility"),
    ("audit_settings", "test_audit_settings.py", "settings failures and test isolation"),
    ("audit_shell", "test_audit_shell.py", "verified icon backup and recovery"),
    ("audit_runtime", "test_audit_runtime.py", "scanner, monitors, tray and diagnostics"),
    ("audit_behaviour", "test_audit_behaviour.py", "carry cleanup and swept collisions"),
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
    ("projectile_flight", "test_projectile_flight.py", "full flights, real landings and fuses"),
    ("muzzle", "test_muzzle.py", "rounds leaving the end of the barrel"),
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
    windows_only = {"frozen_runtime", "input_recovery", "desktop_recovery", "renderer",
                    "audit_shell", "audit_runtime", "diagnostics", "runtime",
                    "performance_upgrade", "audit_settings", "settings", "icons"}
    available = [c for c in CHECKS if sys.platform != "linux" or c[0] not in windows_only]
    if sys.platform == "linux" and os.environ.get("GREMLIN_ISOLATED_X11") != "1":
        print("Run Linux acceptance on isolated Xvfb with GREMLIN_ISOLATED_X11=1.")
        return 2
    picked = [c for c in available if not wanted or c[0] in wanted]
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
