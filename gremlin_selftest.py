"""Bounded packaged smoke test. Desktop I/O is replaced before App is built."""
import contextlib
import importlib
import json
import math
import os
import sys
import tempfile
import traceback
import uuid
from unittest import mock


def run(gm, report_path):
    if not report_path or not os.path.isabs(report_path):
        return 2
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)),
              "version": gm.VERSION, "data_dir": gm.DATA_DIR, "resource_dir": gm.HERE,
              "checks": {}, "modules": []}
    app = None
    report_written = True
    try:
        import gremlin_renderer
        report["native_enabled"] = gremlin_renderer.NATIVE_DESKTOP_ENABLED
        if report["native_enabled"]:
            raise AssertionError("Native desktop presentation must remain quarantined")
        with tempfile.TemporaryDirectory(prefix="gremlin-selftest-", dir=os.path.dirname(report_path)) as scratch, \
                contextlib.ExitStack() as patches:
            for name, filename in (("SETTINGS_PATH", "settings.json"), ("MEMORY_PATH", "memory.json"),
                                   ("BACKUP_PATH", "backup.json"), ("LOG_PATH", "log.txt"),
                                   ("ICON_PATH", "gremlin.ico")):
                patches.enter_context(mock.patch.object(gm, name, os.path.join(scratch, filename)))
            patches.enter_context(mock.patch.dict(gm.CFG, dict(gm.DEFAULTS, crowd=4,
                move_icons=False, move_windows=False, all_monitors=False, sleep_when_idle=False,
                react_to_windows=False, group_scenes=True, parkour=True, toy_props=True), clear=True))
            patches.enter_context(mock.patch.object(gm, "MEM", gm.blank_memory()))
            patches.enter_context(mock.patch.object(gm, "MEM_DIRTY", False))
            make_root = gm.tk.Tk

            def owned_root():
                root = make_root()
                root.withdraw()
                return root

            overrides = {"virtual_screen": lambda: (0, 0, 900, 700),
                         "monitors": lambda: [((0, 0, 900, 700), (0, 0, 900, 660))],
                         "idle_seconds": lambda: 0, "foreground_window": lambda: None,
                         "find_desktop_listview": lambda: None, "read_windows": lambda own=0: [],
                         "place_window": lambda *args: False, "window_alive": lambda hwnd: False,
                         "window_rect": lambda hwnd: None, "tracked_window_rect": lambda hwnd: None,
                         "set_run_at_startup": lambda on: True, "fullscreen_app": lambda own=0: False,
                         "on_battery": lambda: False}
            for name, value in overrides.items():
                patches.enter_context(mock.patch.object(gm, name, value))
            patches.enter_context(mock.patch.object(gm.tk, "Tk", owned_root))
            patches.enter_context(mock.patch.object(gm.Tray, "build", return_value=True))
            patches.enter_context(mock.patch.object(gm.Tray, "notify", return_value=None))
            patches.enter_context(mock.patch.object(gm.Terrain, "refresh", return_value=None))
            patches.enter_context(mock.patch.object(gm.Terrain, "track_windows", return_value=False))
            patches.enter_context(mock.patch.object(gm.SHELL, "close", return_value=None))
            # The test mutex is unique and never claims the user's live app name.
            mutex = "Local\\DesktopGremlin.selftest." + uuid.uuid4().hex
            patches.enter_context(mock.patch.object(gm, "_INSTANCE", None))
            first = gm.claim_instance(mutex)
            handle = gm._INSTANCE
            try:
                report["checks"]["single_instance"] = first and not gm.claim_instance(mutex)
            finally:
                if handle:
                    gm._k32.CloseHandle(handle)
                gm._INSTANCE = None
            app = gm.App()
            app.poll_cursor = lambda dt: None
            report["renderer"] = app.renderer_mode
            report["modules"] = ["tkinter", "win32api", "win32gui", "win32process", "win32con",
                "gremlin_profiles", "gremlin_paths", "gremlin_arsenal", "gremlin_motion",
                "gremlin_social", "gremlin_performance", "gremlin_renderer"]
            report["module_paths"] = {name: importlib.import_module(name).__file__
                                      for name in report["modules"]}
            report["executable"] = sys.executable
            report["checks"]["bundled_imports"] = not report["frozen"] or all(
                os.path.normcase(os.path.commonpath((gm.HERE, path))) == os.path.normcase(gm.HERE)
                for path in report["module_paths"].values())
            report["checks"]["owned_withdrawn_tk"] = (app.root.state() == "withdrawn"
                and isinstance(app.canvas, gm.tk.Canvas) and app.renderer_mode == "tk")
            for fighter in app.fighters:
                fighter.goal = 60.0  # Keep the startup fixture free of random duels.
            app.update(1 / 60)  # Land the freshly spawned actors through real physics.
            coffee = app.social.start_scene("coffee", app.fighters[:2])
            crate = app.motion.add_prop("crate", 500, 660)
            shield = app.arsenal.apply_effect(app.fighters[2], "shield", 3.0)
            for _ in range(120):
                app.update(1 / 60)
            app.draw()
            report["checks"]["expansion_engines"] = bool(coffee and crate and shield and all(
                app.canvas.find_withtag(layer) for layer in ("social", "toys", "arsenal")))
            report["checks"]["simulation_and_canvas"] = bool(app.canvas.find_all()) and all(
                math.isfinite(v) for f in app.fighters for v in (f.x, f.y, f.hp))
            # Settings are exercised in a second owned, immediately hidden window.
            window = gm.SettingsWindow(app.root, app)
            window.win.withdraw()
            window.vars["cast"].set("veteran,tinkerer")
            window.vars["profiles"].set(json.dumps({"veteran": {"nickname": "Test", "hat": "cap"}}))
            window.vars["play_mode"].set("peaceful")
            window.apply()
            report["checks"]["settings_roundtrip"] = (gm.load_settings()["cast"] == "veteran,tinkerer"
                and app.fighters[0].nickname == "Test" and not app.combat_allowed())
            gm.bump("veteran", "grabbed")
            report["checks"]["memory_roundtrip"] = (gm.save_memory()
                and gm.load_memory()["who"]["veteran"]["grabbed"] == 1)
            app.set_held(True)
            report["checks"]["hide_cleanup"] = (app.root.state() == "withdrawn" and
                not app.motion.props and not app.social.scenes and not app.arsenal.effects)
            # Verify the real queued emergency-exit path without registering or
            # injecting a global keyboard shortcut on the user's desktop.
            app.tray._on_hotkey(0, gm.win32con.WM_HOTKEY, app.tray.HOTKEY_QUIT, 0)
            queued = bool(app.tray.pending) and app.running
            app.tray.drain()
            report["checks"]["emergency_exit_dispatch"] = queued and not app.running
            app = None
            report["ok"] = all(report["checks"].values())
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if app is not None:
            # Never let failure cleanup write restored production paths.
            with contextlib.suppress(Exception):
                app.root.destroy()
        try:
            with open(report_path, "w", encoding="utf-8") as output:
                json.dump(report, output, indent=2)
        except OSError:
            report_written = False
    return (0 if report["ok"] else 1) if report_written else 2
