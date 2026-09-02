"""The machinery around the simulation, which nothing else checks.

  1. the frame loop paces from a deadline, so 40 fps configured is 40 fps run
  2. a second launch is refused (one instance per desktop)
  3. the icon layout backup is re-taken every launch, kept when the last run
     left icons moved, cleared by a restore; first and previous stay in the file
  4. the terrain scan runs off the frame thread and lands through poll()
  5. a fullscreen app in front hides the overlay, and it comes back after,
     the same window with the same click-through styles
  6. the overlay re-covers the desktop when the monitors change
  7. the tick slows asleep and on battery without slowing the simulation
  8. the source id printed in the log is the commit git says is checked out

Every one of these shipped wrong or shipped absent: the loop ran at 32 of a
configured 40 (each frame's own cost was added to every gap), two launches
meant two casts and two tray icons, Restore returned a months-old desktop, a
dock changed nothing until a restart, and a borderless game had a topmost
layered window composited over it forty times a second.
"""
import os
import subprocess
import sys
import threading
import time
import types

import win32con
import win32gui

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

gm = harness.load("runtime", crowd=2)
gm.fullscreen_app = lambda own=0: False    # the real machine stays out of this
gm.on_battery = lambda: False
app = harness.build(gm)
ICONS = [("Icon %d" % i, 200 + i * 130, 500, 264 + i * 130, 564, i) for i in range(6)]
harness.fake_terrain(app, ICONS)
bad = []
DT = 1 / 40.0


# --- 1. the frame loop paces from a deadline ---------------------------------
# Drive the REAL run(): its after() calls are captured and replayed against a
# fake clock, with 6 ms of pretend work inside every draw -- the measured cost
# of ten fighters. after(period) from the end of that work gave 31 ms frames.
class Clock:
    def __init__(self):
        self.t = 100.0

    def perf_counter(self):
        return self.t


clock = Clock()
gm.time = types.SimpleNamespace(perf_counter=clock.perf_counter,
                                strftime=time.strftime, localtime=time.localtime)
scheduled = []
app.root.after = lambda ms, fn=None: scheduled.append((ms, fn))
app.root.mainloop = lambda: None
_draw = app.draw


def slow_draw():
    clock.t += .006
    _draw()


app.draw = slow_draw


def run_ticks(n):
    """Replay n scheduled ticks; returns the clock at the start of each."""
    starts = []
    for _ in range(n):
        ms, fn = scheduled.pop()
        clock.t += ms / 1000.0
        starts.append(clock.t)
        fn()
    return starts


app.run()                                  # schedules the first tick
run_ticks(3)                               # settle
starts = run_ticks(40)
gaps = [b - a for a, b in zip(starts, starts[1:])]
mean_ms = sum(gaps) / len(gaps) * 1000
want_ms = 1000.0 / gm.CFG["fps"]
print("frame period          : %.2f ms against %.0f ms configured (work 6 ms)"
      % (mean_ms, want_ms))
if abs(mean_ms - want_ms) > 1.0:
    bad.append("loop paced at %.1f ms, not %.0f: the frame's cost is being added to the gap"
               % (mean_ms, want_ms))

# --- 7. slow ticks asleep and on battery, without slow motion ----------------
periods = {}
app.asleep, app.on_battery, app.held = False, False, False
periods["awake"] = app.frame_period()
app.on_battery = True
periods["battery"] = app.frame_period()
app.on_battery = False
app.asleep = True
periods["asleep"] = app.frame_period()
app.held = True
periods["held"] = app.frame_period()
app.held = False
print("tick period           : awake %.0f ms, battery %.0f, asleep %.0f, held %.0f"
      % tuple(periods[k] * 1000 for k in ("awake", "battery", "asleep", "held")))
if not (periods["awake"] < periods["battery"] < periods["asleep"] < periods["held"]):
    bad.append("tick period does not slow through battery, asleep, held: %s" % periods)
# asleep: 100 ms ticks must still advance the simulation 100 ms at a time
gm.idle_seconds = lambda: 1e9
gm.CFG["sleep_when_idle"] = True
run_ticks(2)
t0, c0 = app.time, clock.t
run_ticks(10)
sim, wall = app.time - t0, clock.t - c0
print("asleep, 10 ticks      : simulation %.2fs over %.2fs of clock" % (sim, wall))
if abs(sim - wall) > .05:
    bad.append("asleep the simulation ran at %.0f%% speed" % (100 * sim / wall))
gm.CFG["sleep_when_idle"] = False
gm.idle_seconds = lambda: 0.0
run_ticks(2)

# --- 5. a fullscreen app in front hides the overlay --------------------------
fs = {"on": False}
gm.fullscreen_app = lambda own=0: fs["on"]
hwnd = app.hwnd
ex_before = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
fs["on"] = True
app.env_at = -9.0
run_ticks(1)                               # the environment check runs in the tick
held_hidden = app.held and not win32gui.IsWindowVisible(hwnd)
t_held = app.time
run_ticks(5)
frozen = app.time == t_held                # nothing simulated behind a game
fs["on"] = False
app.env_at = -9.0
run_ticks(1)
app.root.update_idletasks()
back = (not app.held) and win32gui.IsWindowVisible(hwnd)
ex_after = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
tc = str(app.root.attributes("-transparentcolor"))    # a Tcl colour object
same = app.hwnd == hwnd and ex_after == ex_before and tc.lower() == gm.KEY.lower()
print("fullscreen app        : hidden %s, frozen %s, back %s, same window %s"
      % (held_hidden, frozen, bool(back), same))
if not same:
    print("   hwnd %s -> %s, exstyle %#x -> %#x, transparent %r"
          % (hwnd, app.hwnd, ex_before, ex_after, tc))
if not held_hidden:
    bad.append("a fullscreen foreground app did not hide the overlay")
if not frozen:
    bad.append("the simulation kept running while hidden")
if not back or not same:
    bad.append("the overlay did not come back as the same click-through window")
gm.CFG["pause_fullscreen"] = False
fs["on"] = True
app.env_at = -9.0
run_ticks(1)
print("with the setting off  : held %s" % app.held)
if app.held:
    bad.append("pause_fullscreen off still hid the overlay")
fs["on"] = False
gm.CFG["pause_fullscreen"] = True

# --- 6. the overlay follows the monitors -------------------------------------
real_vs, real_mons = gm.virtual_screen, gm.monitors
box0 = (app.ox, app.oy, app.W, app.H)
gm.virtual_screen = lambda: (0, 0, 1200, 700)
gm.monitors = lambda: [((0, 0, 1200, 700), (0, 0, 1200, 660))]
app.fighters[0].x, app.fighters[0].y = 1900.0, 1000.0    # off the new screen
changed = app.fit_screen()
app.root.update_idletasks()
geom = app.root.geometry()
inside = all(app.ox + 40 <= f.x <= app.ox + app.W - 40 and f.y <= app.ground_at(f.x)
             for f in app.fighters)
print("monitors changed      : refit %s, window %s, everyone inside %s"
      % (changed, geom.split("+")[0], inside))
if not changed or (app.W, app.H) != (1200, 700) or not geom.startswith("1200x700"):
    bad.append("a monitor change did not re-cover the desktop: %s" % geom)
if not inside:
    bad.append("a fighter was left outside the new screen")
gm.virtual_screen, gm.monitors = real_vs, real_mons
app.fit_screen()
if (app.ox, app.oy, app.W, app.H) != box0:
    bad.append("did not fit back to the real screen")

gm.time = time                              # the real clock again

# --- 2. one instance per desktop --------------------------------------------
name = "Local\\DesktopGremlin.check.%d" % os.getpid()
first, second = gm.claim_instance(name), gm.claim_instance(name)
print("second launch refused : %s (first %s)" % (not second, first))
if not first or second:
    bad.append("the instance mutex let a second launch through")


# --- 3. the layout backup ----------------------------------------------------
class SnapShell:
    """Only what backup and restore need: the layout as it is right now."""

    def __init__(self):
        self.layout = []
        self.restored = None

    def snapshot(self):
        return [list(p) for p in self.layout]

    def restore(self, snap):
        self.restored = snap
        self.layout = [list(p) for p in snap]
        return len(snap)


snap = SnapShell()
gm.SHELL = snap
A = [["Steam", 10, 10], ["Bin", 10, 120], ["Docs", 110, 10]]
B = [["Steam", 400, 300], ["Bin", 10, 120], ["Docs", 500, 500]]
C = [["Steam", 10, 10], ["Bin", 200, 120], ["Docs", 110, 10]]
gm.BACKUP_OK, gm.LAYOUT_DIRTY = False, False
snap.layout = A
s1 = gm.backup_layout()                    # launch 1: first ever
gm.mark_layout_dirty()                     # ...a gremlin moves something
snap.layout = B                            # ...and the desktop is left like that
gm.LAYOUT_DIRTY = False                    # a new process knows nothing
s2 = gm.backup_layout()                    # launch 2: must keep A, not photograph B
kept = gm._read_backup()
n = gm.restore_layout()                    # the user puts it back
after_restore = gm._read_backup()
snap.layout = C                            # launch 3, desktop rearranged by hand
gm.LAYOUT_DIRTY = False
s3 = gm.backup_layout()
third = gm._read_backup()
s4 = gm.backup_layout()                    # launch 4, nothing changed
fourth = gm._read_backup()
print("backup launches       : %s, %s, %s, %s" % (s1, s2, s3, s4))
print("kept while dirty      : %s   restored %d, flag cleared %s"
      % (kept["icons"] == A, n, after_restore["dirty"] is False))
print("fresh after restore   : %s   first %s   previous %s"
      % (third["icons"] == C, third["first"]["icons"] == A,
         [p["icons"] == A for p in third["previous"]]))
if (s1, s2, s3, s4) != ("saved", "kept", "saved", "saved"):
    bad.append("backup states were %s" % ((s1, s2, s3, s4),))
if kept["icons"] != A or not kept.get("dirty"):
    bad.append("a launch after a dirty run replaced the good snapshot")
if n != len(A) or snap.restored != A or after_restore.get("dirty"):
    bad.append("restore did not put A back and clear the flag")
if third["icons"] != C or third["first"]["icons"] != A \
        or [p["icons"] for p in third["previous"]] != [A]:
    bad.append("launch 3 should snapshot C, keep A as first and previous")
if fourth["previous"] != third["previous"]:
    bad.append("an unchanged layout was pushed into previous again")
if not gm.BACKUP_OK:
    bad.append("BACKUP_OK is off with a good file on disk")
# the flag is set by the shell's own write, and not by a restore's writes
sv = gm.ShellView()
sv.lv, sv.proc, sv.remote = 1, 1, 4096
sv._write = lambda obj, off=0: 1
sv._read = lambda obj, off=0: 1
sv.open = lambda: True
sv.count = lambda: 2
sv.item_text = lambda i: "A" if i == 0 else "B"
gm.send_msg = lambda *a, **k: 1
gm.LAYOUT_DIRTY = False
sv.set_item_pos(0, 5, 5)
by_move = gm.LAYOUT_DIRTY
gm.LAYOUT_DIRTY = False
sv.restore([["A", 1, 2], ["B", 3, 4]])
by_restore = gm.LAYOUT_DIRTY
print("dirty by a move       : %s   by a restore: %s" % (by_move, by_restore))
if not by_move:
    bad.append("moving an icon through the shell did not flag the backup")
if by_restore:
    bad.append("a restore's own writes flagged the backup")

# --- 4. the scan runs off the frame thread ----------------------------------
seen = {"thread": None, "calls": 0}


class SlowShell:
    def read_icons(self):
        seen["thread"] = threading.get_ident()
        seen["calls"] += 1
        time.sleep(.25)                    # a busy Explorer
        return [("Icon", 100, 100, 164, 164, 0)]


gm.SHELL = SlowShell()
gm.read_windows = lambda own: [("Pad", 300, 300, 900, 800, 77)]
t = gm.Terrain()
t.threaded = True
t0 = time.perf_counter()
t.refresh(0)
asked = time.perf_counter() - t0
landed = False
deadline = time.perf_counter() + 3
while time.perf_counter() < deadline and not landed:
    landed = t.poll()
    if not landed:
        time.sleep(.01)
print("background scan       : asked in %.1f ms, landed %s, on another thread %s"
      % (asked * 1000, landed, seen["thread"] not in (None, threading.get_ident())))
if asked > .05:
    bad.append("refresh() blocked the frame for %.0f ms" % (asked * 1000))
if not landed or len(t.icons) != 1 or len(t.windows) != 1:
    bad.append("the background scan never landed: %s icons, %s windows"
               % (len(t.icons), len(t.windows)))
if seen["thread"] in (None, threading.get_ident()):
    bad.append("the scan ran on the frame thread")
# the one synchronous look, for startup and the checks
t2 = gm.Terrain()
t2.refresh(0)
if len(t2.icons) != 1:
    bad.append("the synchronous refresh did not read the shell")

# --- 8. the source id is the checked-out commit -----------------------------
sid = gm.source_id()
try:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=gm.HERE,
                          capture_output=True, text=True, timeout=10).stdout.strip()
except Exception:
    head = ""
if head:
    print("source id             : %s (git says %s)" % (sid, head[:9]))
    if sid != head[:9]:
        bad.append("source_id() says %s, git says %s" % (sid, head[:9]))
else:
    print("source id             : %s (no git here to compare against)" % sid)

print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
harness.finish(gm, app, bad)
