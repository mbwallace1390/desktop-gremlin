"""The start every check shares, done once, here.

    gm = harness.load("gait", crowd=1)      import the script, sandbox it
    app = harness.build(gm)                 a real App, cursor poll stubbed
    harness.fake_terrain(app, ICONS)        serve these icons instead of the desktop
    harness.finish(gm, app, bad)            tear down, sweep, exit

load() redirects EVERY file the script persists to -- settings, icon backup,
memory, log, tray icon -- into tests/.tmp before anything can write, then resets the
settings to the defaults and stubs the idle clock. That order is the point:
a check that drives the settings window used to drop a real
gremlin_settings.json into the repo carrying whatever it had forced, and the
app then started with those values. Twice. A rule saying "redirect the paths
first" did not stop the second one; a function that cannot be called without
doing it does.

Each check names its scratch files with a tag, so two of them cannot tread on
each other, and finish() removes them again.
"""
import importlib.util
import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
SRC = os.environ.get("GREMLIN_SRC", os.path.join(ROOT, "desktop_gremlin.py"))
TMP = os.path.join(TESTS, ".tmp")

_FILES = (("SETTINGS_PATH", "settings.json"), ("BACKUP_PATH", "backup.json"),
          ("MEMORY_PATH", "memory.json"), ("LOG_PATH", "log.txt"),
          ("ICON_PATH", "gremlin.ico"))

# the machine stubbed out of every check: nobody is idle, one monitor, no
# real icon ever moves unless a check asks for it
QUIET = {"sleep_when_idle": False, "all_monitors": False, "move_icons": False,
         "auto_quality": False, "group_scenes": False, "parkour": False,
         "toy_props": False}
# Focused legacy fixtures keep ownership of their actors. Expansion and mixed
# acceptance checks explicitly enable the production-default scene systems.


def scratch(tag, ext):
    """A scratch path for this check: tests/.tmp/<tag>_<ext>."""
    os.makedirs(TMP, exist_ok=True)
    return os.path.join(TMP, "%s_%s" % (tag, ext))


def load(tag, **cfg):
    """Import the script fresh, sandboxed. Keyword arguments are settings."""
    spec = importlib.util.spec_from_file_location("gm", SRC)
    gm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gm)
    for const, ext in _FILES:
        path = scratch(tag, ext)
        setattr(gm, const, path)
        if os.path.exists(path):
            os.remove(path)               # a crashed earlier run's leftovers
    gm.MEM = gm.blank_memory()
    gm.MEM_DIRTY = False
    gm.CFG.update(gm.DEFAULTS)
    gm.CFG.update(QUIET)
    gm.CFG.update(cfg)
    gm.idle_seconds = lambda: 0.0
    # Install the desktop boundary BEFORE App's synchronous startup scan.
    # Individual checks can replace these with their own fakes after load().
    gm.SHELL = FakeShell([])
    gm.find_desktop_listview = lambda: None
    gm.read_windows = lambda own=0: []
    gm.foreground_window = lambda: None
    gm.place_window = lambda hwnd, x, y: False
    if not gm.IS_WINDOWS:
        gm.confirm_window_position = lambda hwnd, x, y: True
    gm.window_rect = lambda hwnd: None
    gm.window_alive = lambda hwnd: False
    gm.tracked_window_rect = lambda hwnd: None
    gm.set_run_at_startup = lambda on: True
    gm.fullscreen_app = lambda own=0: False
    gm.on_battery = lambda: False
    gm.Tray.notify = lambda self, title, text: None
    return gm


def build(gm, shell=None):
    """A real App. poll_cursor reads the real mouse, so it is stubbed. With a
    fake shell installed the icon gates are opened too: the backup is
    declared present and auto-arrange off, so icons may actually move."""
    if shell is not None:
        gm.SHELL = shell
        gm.BACKUP_OK = True
    app = gm.App()
    app.poll_cursor = lambda dt: None
    if shell is not None:
        app.icons_locked = False
    return app


def fake_terrain(app, icons=(), windows=()):
    """Serve this desktop instead of the real one, in the exact shape
    Terrain.apply builds. Icons are (name, l, t, r, b, index); windows are
    (title, l, t, r, b, hwnd). Either may be a callable, for a layout that
    changes as the check runs. Installs the stub, calls it once, returns it."""
    app.terrain.fast_tracking = False
    def refresh(own=0, want_icons=True):
        t = app.terrain
        t.icons = list(icons() if callable(icons) else icons)
        t.windows = list(windows() if callable(windows) else windows)
        t.moved = {}
        t.win_pos = {h: (l, tp) for _title, l, tp, _r, _b, h in t.windows}
        t.win_rect = {h: (l, tp, r, b) for _title, l, tp, r, b, h in t.windows}
        t.icons_ok = True
        tg, pl = [], []
        for name, l, tp, r, b, idx in t.icons:
            tg.append({"cx": (l + r) / 2, "cy": (tp + b) / 2, "top": tp, "name": name,
                       "w": r - l, "h": b - tp, "kind": "icon", "key": idx})
            pl.append((l, r, tp, "icon", idx))
        for title, l, tp, r, b, h in t.windows:
            tg.append({"cx": (l + r) / 2, "cy": tp + 16, "top": tp, "name": title,
                       "w": r - l, "h": 32, "kind": "window", "key": h})
            pl.append((l + 6, r - 6, tp, "window", h))
        t._targets, t.platforms = tg, pl
        t.bounds = [(x["cx"], x["cy"], x["w"] / 2, max(x["h"], 26) / 2, x) for x in tg]

    app.terrain.refresh = refresh
    refresh()
    return refresh


class FakeShell:
    """A stand-in for Explorer's list view. Screen rect and list position
    differ by a constant, like the real one, and every write is recorded."""
    OFF = (7000, 9000)

    def __init__(self, grid):
        self.pos = {i: grid[i] for i in range(len(grid))}
        self.writes = []

    def open(self):
        return True

    def item_rect(self, i):
        x, y = self.pos[i]
        return (x, y, x + 64, y + 64)

    def item_pos(self, i):
        x, y = self.pos[i]
        return (x + self.OFF[0], y + self.OFF[1])

    def read_icons(self):
        return shell_icons(self)()

    def set_item_pos(self, i, x, y):
        self.writes.append(i)
        self.pos[i] = (x - self.OFF[0], y - self.OFF[1])
        return True

    def close(self):
        pass


def shell_icons(shell, size=64):
    """A live icon list for fake_terrain: wherever the fake shell has them now."""
    return lambda: [("Icon %d" % i, x, y, x + size, y + size, i)
                    for i, (x, y) in sorted(shell.pos.items())]


def teardown(gm, app):
    """Close the window and sweep this check's scratch files."""
    try:
        app.close_performance()
        if hasattr(app.canvas, "dispose"):
            app.canvas.dispose()
        if getattr(app, "x11_overlay", None) is not None:
            app.x11_overlay.close()
        app.terrain.scanner.close()
        app.tray.remove()
        app.root.destroy()
    except Exception:
        pass
    for const, _ext in _FILES:
        path = getattr(gm, const, None)
        if path and path.startswith(TMP) and os.path.exists(path):
            os.remove(path)


def finish(gm, app, failed):
    """teardown(), then exit 1 if `failed` is truthy (a list of complaints or
    a flag), else 0."""
    teardown(gm, app)
    sys.exit(1 if failed else 0)
