"""Everything the icon shove has to get right.

Positions are tracked in a fake shell so nothing touches the real desktop.
"""
import importlib.util
import math
import os
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get(
    "GREMLIN_SRC",
    os.path.join(os.path.dirname(_TESTS), "desktop_gremlin.py"))
HERE = os.path.join(_TESTS, ".tmp")          # scratch; never the repo itself
os.makedirs(HERE, exist_ok=True)
bad = []

GRID = [(100 + (i % 6) * 110, 300 + (i // 6) * 130) for i in range(12)]


class FakeShell:
    """Screen rect and list position differ by a constant, like the real one."""
    OFF = (7000, 9000)

    def __init__(self):
        self.pos = {i: GRID[i] for i in range(len(GRID))}
        self.writes = []

    def open(self):
        return True

    def item_rect(self, i):
        x, y = self.pos[i]
        return (x, y, x + 64, y + 64)

    def item_pos(self, i):
        x, y = self.pos[i]
        return (x + self.OFF[0], y + self.OFF[1])

    def set_item_pos(self, i, x, y):
        self.writes.append(i)
        self.pos[i] = (x - self.OFF[0], y - self.OFF[1])
        return True

    def close(self):
        pass


def build(move_icons=True):
    spec = importlib.util.spec_from_file_location("gm", SRC)
    gm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gm)
    gm.MEMORY_PATH = os.path.join(HERE, "sv_memory.json")
    gm.MEM = gm.blank_memory()
    gm.CFG.update(gm.DEFAULTS)
    gm.CFG["rival"] = True
    gm.CFG["sleep_when_idle"] = False
    gm.CFG["all_monitors"] = False
    gm.CFG["move_icons"] = move_icons
    gm.BACKUP_OK = True
    gm.idle_seconds = lambda: 0.0
    shell = FakeShell()
    gm.SHELL = shell
    app = gm.App()
    app.poll_cursor = lambda dt: None
    app.icons_locked = False

    def refresh(own=0, want_icons=True):
        t = app.terrain
        t.icons = [("Icon %d" % i, shell.pos[i][0], shell.pos[i][1],
                    shell.pos[i][0] + 64, shell.pos[i][1] + 64, i)
                   for i in range(len(GRID))]
        t.windows, t.moved, t.win_pos, t.icons_ok = [], {}, {}, True
        tg, pl = [], []
        for name, l, tp, r, b, idx in t.icons:
            tg.append({"cx": (l + r) / 2, "cy": (tp + b) / 2, "top": tp,
                       "name": name, "w": r - l, "h": b - tp,
                       "kind": "icon", "key": idx})
            pl.append((l, r, tp, "icon", idx))
        t._targets, t.platforms = tg, pl
        t.bounds = [(x["cx"], x["cy"], x["w"] / 2, max(x["h"], 26) / 2, x)
                    for x in tg]

    app.terrain.refresh = refresh
    refresh()
    return gm, app, shell


def teardown(gm, app):
    try:
        app.tray.remove()
        app.root.destroy()
    except Exception:
        pass
    if os.path.exists(gm.MEMORY_PATH):
        os.remove(gm.MEMORY_PATH)


# --- 1. a blast pushes icons AWAY, and further the closer they were ---------
gm, app, shell = build()
before = dict(shell.pos)
cx, cy = 350.0, 332.0
n = app.blast_icons(cx, cy, 300.0, 120.0)
outward = 0
for i, (x, y) in shell.pos.items():
    if before[i] == (x, y):
        continue
    d0 = math.hypot(before[i][0] + 32 - cx, before[i][1] + 32 - cy)
    d1 = math.hypot(x + 32 - cx, y + 32 - cy)
    if d1 > d0:
        outward += 1
    else:
        bad.append("icon %d moved toward the blast (%.0f -> %.0f)" % (i, d0, d1))
print("blast moved           : %d icons, %d of them outward" % (n, outward))
if n < 2:
    bad.append("a 300px blast over a 6-wide grid only moved %d" % n)

# --- 2. capped, so one blast is never forty round trips --------------------
shell.writes.clear()
app.blast_icons(400.0, 360.0, 5000.0, 200.0)
print("huge blast writes     : %d (cap is 6)" % len(shell.writes))
if len(shell.writes) > 6:
    bad.append("blast cap not honoured: %d writes" % len(shell.writes))

# --- 3. icons stay on the screen ------------------------------------------
for _ in range(12):
    app.blast_icons(app.ox + 20.0, app.oy + 20.0, 4000.0, 3000.0)
    app.terrain.refresh()
gy = app.ground_at(app.ox + 100)
off = [(i, p) for i, p in shell.pos.items()
       if p[0] < app.ox or p[0] + 64 > app.ox + app.W or p[1] < app.oy
       or p[1] + 64 > gy]
print("after 12 huge blasts  : %d icons off-screen" % len(off))
if off:
    bad.append("icons pushed off screen: %s" % off[:3])

# --- 4. an icon being carried is never shoved ------------------------------
gm2, app2, shell2 = build()
f = app2.fighters[0]
f.carry = {"idx": 3, "offx": 0, "offy": 0, "w": 64, "h": 64, "name": "Icon 3"}
shell2.writes.clear()
app2.blast_icons(shell2.pos[3][0] + 32.0, shell2.pos[3][1] + 32.0, 400.0, 150.0)
print("carried icon shoved   : %s" % (3 in shell2.writes))
if 3 in shell2.writes:
    bad.append("the icon being carried got shoved out from under him")

# --- 5. dragging off means the desktop is never touched --------------------
gm3, app3, shell3 = build(move_icons=False)
app3.blast_icons(350.0, 332.0, 900.0, 200.0)
print("writes, dragging off  : %d" % len(shell3.writes))
if shell3.writes:
    bad.append("wrote to the desktop with dragging off")

# --- 6. a bullet nudges one icon, and is throttled -------------------------
gm4, app4, shell4 = build()
g = app4.fighters[0]
app4.time = 100.0
tgt = app4.terrain.targets()[4]
shell4.writes.clear()
for _ in range(5):                       # five hits in the same instant
    app4.shots = [{"k": "laser", "x": tgt["cx"], "y": tgt["cy"], "owner": g,
                   "vx": 400.0, "vy": 0.0, "g": 0.0, "life": -1.0,
                   "trail": [], "spin": 0.0}]
    app4.projectiles(1 / 40.0)
burst = len(shell4.writes)
# three hits is enough to wreck one, and he carries it off; clear that so the
# next shot is testing the throttle and not the carried-icon exclusion
for fr in app4.fighters:
    fr.carry, fr.hits = None, 0
app4.time += 1.0                          # ...and one a second later
tgt2 = app4.terrain.targets()[7]
app4.shots = [{"k": "laser", "x": tgt2["cx"], "y": tgt2["cy"], "owner": g,
               "vx": 400.0, "vy": 0.0, "g": 0.0, "life": -1.0,
               "trail": [], "spin": 0.0}]
app4.projectiles(1 / 40.0)
later = len(shell4.writes) - burst
print("bullet burst writes   : %d for 5 simultaneous hits, %d one second on"
      % (burst, later))
if burst == 0:
    bad.append("a bullet hitting an icon moved nothing")
if burst > 2:
    bad.append("bullet throttle not working: %d writes at once" % burst)
if later == 0:
    bad.append("throttle never released")

# --- 7. a stray shot must not end a fight ----------------------------------
gm5, app5, shell5 = build()
a, b = app5.fighters
a.foe, b.foe = b, a
a.mode, a.state = "fight", "fight"
a.hits, a.snatch = 2, False
app5.hit_target(a, app5.terrain.targets()[0], 300.0, 330.0)
print("after wrecking an icon: state=%s mode=%s carry=%s"
      % (a.state, a.mode, bool(a.carry)))
if a.state != "fight" or a.mode != "fight" or a.carry:
    bad.append("a stray shot pulled him out of the fight")

for g_, a_ in ((gm, app), (gm2, app2), (gm3, app3), (gm4, app4), (gm5, app5)):
    teardown(g_, a_)
print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
sys.exit(1 if bad else 0)
