"""Source/frozen Linux smoke and actual cross-process X11 input acceptance.

This may run only against an explicitly isolated X server. Every persistence
path remains redirected until App shutdown has finished, including failures.
"""
import contextlib
import importlib
import json
import math
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from unittest import mock


def _instance_check(gm, scratch):
    """Prove an independent process cannot acquire the live flock."""
    name = "selftest-" + uuid.uuid4().hex
    if not gm.LINUX.claim_instance(scratch, name) or gm.LINUX.claim_instance(scratch, name):
        return False
    reader, writer = os.pipe()
    child = os.fork()  # before Tk/App or the background scanner is constructed
    if child == 0:
        os.close(reader)
        try:
            # Close inherited descriptor copies; the parent still owns its lock.
            gm.LINUX.release_instances()
            result = not gm.LINUX.claim_instance(scratch, name)
            os.write(writer, b"1" if result else b"0")
        except Exception:
            os.write(writer, b"0")
        finally:
            os.close(writer)
            os._exit(0)
    os.close(writer)
    try:
        ready = select.select([reader], [], [], 3)[0]
        if not ready:
            os.kill(child, signal.SIGKILL)
            return False
        return os.read(reader, 1) == b"1"
    finally:
        os.close(reader)
        os.waitpid(child, 0)
        gm.LINUX.release_instances()


def _window_check(gm, app, scratch, report):
    """Move and restore only a separately owned, isolated receiver process."""
    from gremlin_x11_probe import _receiver_command
    state_path = Path(scratch) / "managed-receiver.json"
    environment = dict(os.environ, GREMLIN_MANAGED_RECEIVER="1")
    process = subprocess.Popen(_receiver_command(state_path), env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    desktop = gm.LINUX.desktop()
    original = window = None
    try:
        deadline = time.monotonic() + 6
        wanted = "Desktop Gremlin self-test receiver %d" % process.pid
        while time.monotonic() < deadline:
            matches = [entry for entry in desktop.read_windows(app.hwnd) if entry[0] == wanted]
            if matches:
                window = matches[0][-1]
                original = desktop.window_rect(window)
                break
            if process.poll() is not None:
                raise RuntimeError("Managed X11 receiver stopped before its window appeared")
            app.root.update()
            time.sleep(.02)
        if original is None:
            raise RuntimeError("The X11 window manager did not publish the owned receiver")
        _ox, _oy, width, height = desktop.virtual_screen()
        x = min(max(20, original[0] + 80), max(20, width - (original[2] - original[0]) - 12))
        y = min(max(20, original[1] + 65), max(20, height - (original[3] - original[1]) - 12))
        moved = desktop.place_window(window, x, y) and desktop.confirm_position(window, x, y, timeout=.25)
        actual = desktop.window_rect(window)
        tracked = next((entry for entry in desktop.read_windows(app.hwnd) if entry[-1] == window), None)
        restored = desktop.place_window(window, *original[:2]) and desktop.confirm_position(window, *original[:2], timeout=.25)
        report["desktop_window"] = {"original": original, "requested": (x, y),
            "actual": actual, "restored": desktop.window_rect(window), "receiver_pid": process.pid}
        return bool(moved and tracked and tuple(tracked[1:5]) == actual and restored)
    finally:
        if original is not None and window is not None:
            with contextlib.suppress(Exception):
                desktop.place_window(window, *original[:2])
                desktop.confirm_position(window, *original[:2], timeout=.25)
        Path(str(state_path) + ".stop").touch()
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=2)


def run(gm, report_path):
    if not report_path or not os.path.isabs(report_path):
        return 2
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)),
              "version": gm.VERSION, "data_dir": gm.DATA_DIR, "resource_dir": gm.HERE,
              "checks": {}, "desktop_checks": {}, "modules": []}
    report_written = True
    try:
        if not sys.platform.startswith("linux") or os.environ.get("GREMLIN_ISOLATED_X11") != "1":
            raise RuntimeError("Linux self-test requires GREMLIN_ISOLATED_X11=1 and an isolated X11 server")
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("Linux self-test requires an isolated X11 DISPLAY")
        if gm.IS_WINDOWS:
            raise AssertionError("Linux self-test loaded the Windows backend")
        from gremlin_x11_probe import run_input_probe
        # Linux does not import or package the quarantined Windows renderer.
        report["native_enabled"] = False
        with tempfile.TemporaryDirectory(prefix="gremlin-linux-selftest-", dir=os.path.dirname(report_path)) as scratch, \
                contextlib.ExitStack() as patches:
            # Applying Settings also updates login startup. Keep that actual
            # Linux desktop-entry path isolated, including default-off removal.
            patches.enter_context(mock.patch.dict(os.environ, {
                "XDG_CONFIG_HOME": os.path.join(scratch, "config"),
                "XDG_DATA_HOME": os.path.join(scratch, "data")}))
            for name, filename in (("SETTINGS_PATH", "settings.json"), ("MEMORY_PATH", "memory.json"),
                                   ("BACKUP_PATH", "backup.json"), ("LOG_PATH", "log.txt"),
                                   ("ICON_PATH", "gremlin.ico")):
                patches.enter_context(mock.patch.object(gm, name, os.path.join(scratch, filename)))
            patches.enter_context(mock.patch.dict(gm.CFG, dict(gm.DEFAULTS, crowd=4, cast="", profiles="{}",
                move_icons=False, move_windows=False, all_monitors=False, sleep_when_idle=False,
                pause_fullscreen=False, react_to_windows=False, group_scenes=True,
                parkour=True, toy_props=True), clear=True))
            patches.enter_context(mock.patch.object(gm, "MEM", gm.blank_memory()))
            patches.enter_context(mock.patch.object(gm, "MEM_DIRTY", False))
            app = None
            try:
                # A unique lock directory/name cannot collide with a live user's
                # application. Real flock checks run without Windows stubs.
                report["checks"]["single_instance"] = _instance_check(gm, scratch)
                app = gm.App()
                if getattr(app.tray, "win", None) is not None:
                    app.tray.win.withdraw()
                report["renderer"] = app.renderer_mode
                report["modules"] = ["tkinter", "gremlin_profiles", "gremlin_paths", "gremlin_arsenal",
                    "gremlin_motion", "gremlin_social", "gremlin_performance",
                    "gremlin_linux", "gremlin_x11", "gremlin_x11_overlay", "gremlin_x11_probe"]
                report["module_paths"] = {name: importlib.import_module(name).__file__
                                          for name in report["modules"]}
                report["executable"] = sys.executable
                report["checks"]["bundled_imports"] = not report["frozen"] or all(
                    os.path.commonpath((gm.HERE, path)) == gm.HERE for path in report["module_paths"].values())
                report["checks"]["owned_withdrawn_tk"] = (app.root.state() == "withdrawn"
                    and isinstance(app.canvas, gm.tk.Canvas) and app.renderer_mode == "x11"
                    and app.x11_overlay is not None and not app.x11_overlay.failed)
                for fighter in app.fighters:
                    fighter.goal = 60.0
                app.update(1 / 60)
                coffee = app.social.start_scene("coffee", app.fighters[:2])
                crate_x = app.ox + min(500, app.W * .6)
                crate = app.motion.add_prop("crate", crate_x, app.ground_at(crate_x))
                shield = app.arsenal.apply_effect(app.fighters[2], "shield", 3.0)
                for _ in range(120):
                    app.update(1 / 60)
                app.draw()
                report["checks"]["expansion_engines"] = bool(coffee and crate and shield and all(
                    app.canvas.find_withtag(layer) for layer in ("social", "toys", "arsenal")))
                report["checks"]["simulation_and_canvas"] = (bool(app.canvas.find_all())
                    and not app.x11_overlay.failed and all(
                        math.isfinite(value) for fighter in app.fighters
                        for value in (fighter.x, fighter.y, fighter.hp)))
                window = gm.SettingsWindow(app.root, app)
                window.win.withdraw()
                window.vars["cast"].set("veteran,tinkerer")
                window.vars["profiles"].set(json.dumps({"veteran": {"nickname": "Test", "hat": "cap"}}))
                window.vars["play_mode"].set("peaceful")
                window.apply()
                report["checks"]["settings_roundtrip"] = (gm.load_settings()["cast"] == "veteran,tinkerer"
                    and app.fighters[0].nickname == "Test" and not app.combat_allowed())
                gm.bump("veteran", "grabbed")
                report["checks"]["memory_roundtrip"] = bool(gm.save_memory()
                    and gm.load_memory()["who"]["veteran"]["grabbed"] == 1)
                app.set_held(True)
                report["checks"]["hide_cleanup"] = (app.root.state() == "withdrawn"
                    and not app.motion.props and not app.social.scenes and not app.arsenal.effects)
                app.set_held(False)
                report["checks"]["window_tracking_and_restore"] = _window_check(gm, app, scratch, report)
                # This must remain last: the probe sends real XTest input to a
                # separate process and verifies the real quit chord destroys App.
                report["desktop_checks"] = run_input_probe(app)
                report["checks"]["emergency_exit_dispatch"] = bool(
                    report["desktop_checks"].get("emergency_exit") and not app.running)
                report["ok"] = all(report["checks"].values()) and all(report["desktop_checks"].values())
            finally:
                # Cleanup occurs inside all path patches. Even a failed scene,
                # window, input or save check cannot touch normal user settings.
                if app is not None:
                    with contextlib.suppress(Exception):
                        app.quit()
                    with contextlib.suppress(Exception):
                        app.x11_overlay.close()
                    with contextlib.suppress(Exception):
                        app.root.destroy()
                gm.LINUX.release_instances()
    except Exception:
        report["error"] = traceback.format_exc()
    try:
        with open(report_path, "w", encoding="utf-8") as output:
            json.dump(report, output, indent=2)
    except OSError:
        report_written = False
    return (0 if report["ok"] else 1) if report_written else 2
