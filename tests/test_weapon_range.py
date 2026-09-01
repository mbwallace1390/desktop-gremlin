"""Does every weapon cover the distance it is fired from?

Three questions, because the weapons are three different kinds:

  flat-fired (blaster, minigun, rocket)  does the round OUTRUN the gap?
  lobbed     (bow, bomb)                 does it LAND on him?
  instant    (sword, chainsaw, lightning) does the swing or bolt connect?

Judging a lob by distance is meaningless: a good lob lands exactly on the
target, so its margin is 1.0 by construction. Judging a flat weapon by whether
it hits a stationary target is just as useless -- at the firing distance they
all do. The target moves, so what matters is how much road is left.

Two shipped without any. Aimed three degrees down at the other one's chest from
a muzzle 39px up, the minigun buried its pellets after 498px and the rocket
after 353px, both with most of their life still to run, against firing
distances of 272 and 329. Both were stopped by the FLOOR, so raising the
lifetime -- the obvious move -- did nothing for either.

Nothing here carries its own copy of a projectile constant. An earlier version
did, and reported the old numbers after they had been changed.
"""
import importlib.util
import os
import random
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get(
    "GREMLIN_SRC",
    os.path.join(os.path.dirname(_TESTS), "desktop_gremlin.py"))
HERE = os.path.join(_TESTS, ".tmp")          # scratch; never the repo itself
os.makedirs(HERE, exist_ok=True)

spec = importlib.util.spec_from_file_location("gm", SRC)
gm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gm)
gm.MEMORY_PATH = os.path.join(HERE, "range_memory.json")
gm.MEM = gm.blank_memory()
gm.CFG.update(gm.DEFAULTS)
gm.CFG["crowd"] = 2
gm.CFG["sleep_when_idle"] = False
gm.CFG["all_monitors"] = False
gm.CFG["move_icons"] = False
gm.idle_seconds = lambda: 0.0

app = gm.App()
app.poll_cursor = lambda dt: None
a, b = app.fighters
GROUND = app.ground_at(900)
SCALE = .4 + .6 * a.K()

FLAT = ("blaster", "minigun", "rocket")
LOBBED = ("bow", "bomb")
INSTANT = ("sword", "chainsaw", "lightning")
MARGIN = 1.5                    # a flat round must outrun the gap by this much
SAMPLES = 5                     # the minigun sprays; one sample is noise
bad = []


def set_terrain(with_icons, window=None):
    """Optionally a row of icons standing between them, at their own height.

    The shooter stands at x=200 and no firing distance here puts the target
    past x=560, so the wall runs 260..560: genuinely in the corridor. The
    first version of this wall stood at x=700 -- behind every target -- and
    its 'with icons between' column passed green while intercepting nothing.
    """
    t = app.terrain
    icons = []
    if with_icons:
        x, i = 260, 0
        while x < 560:
            icons.append(("Icon %d" % i, x, int(GROUND) - 80, x + 64,
                          int(GROUND) - 16, i))
            x += 80
            i += 1
    t.icons, t.windows, t.moved, t.win_pos = icons, [], {}, {}
    t.icons_ok = bool(icons)
    tg, pl = [], []
    for name, l, tp, r, bo, idx in t.icons:
        tg.append({"cx": (l + r) / 2, "cy": (tp + bo) / 2, "top": tp,
                   "name": name, "w": r - l, "h": bo - tp,
                   "kind": "icon", "key": idx})
        pl.append((l, r, tp, "icon", idx))
    if window:
        wl, wt, wr, wb, hwnd = window
        t.windows = [("Probe", wl, wt, wr, wb, hwnd)]
        tg.append({"cx": (wl + wr) / 2, "cy": wt + 16, "top": wt,
                   "name": "Probe", "w": wr - wl, "h": 32,
                   "kind": "window", "key": hwnd})
        pl.append((wl + 6, wr - 6, wt, "window", hwnd))
    t._targets, t.platforms = tg, pl
    t.bounds = [(x["cx"], x["cy"], x["w"] / 2, max(x["h"], 26) / 2, x)
                for x in tg]


def square_up(weapon, gap):
    """Both on the floor, gap apart, mid-attack with the weapon we asked for."""
    a.x, a.y = 200.0, GROUND
    b.x, b.y = 200.0 + gap, GROUND
    for f in (a, b):
        f.vx = f.vy = 0.0
        f.on_ground, f.hp, f.stun = True, 100.0, 0.0
        f.tumble = f.squash = 0.0
        f.carry = None
    a.foe, b.foe = b, a
    a.face, a.plan, a.mode = 1, weapon, "fight"
    app.shots = []
    app.parts, app.booms, app.bolts, app.slashes = [], [], [], []
    real = random.random
    random.random = lambda: 0.0            # start_attack keeps the plan
    app.start_attack(a, foe=True)
    random.random = real
    assert a.weapon == weapon, "wanted %s, got %s" % (weapon, a.weapon)


def fire(weapon, gap, seed):
    """Let the real attack state release a round. Returns it, or None."""
    random.seed(seed)
    square_up(weapon, gap)
    hits = []
    real_hit = app.hit_fighter
    app.hit_fighter = lambda att, vic, d: (hits.append(1), real_hit(att, vic, d))[1]
    for _ in range(240):
        if app.shots or hits:
            break
        app.update_fighter(a, 1 / 40.0)
    app.hit_fighter = real_hit
    return (app.shots[0] if app.shots else None), bool(hits)


def follow(shot):
    """With the target taken away, how far does it get and what stops it?"""
    x0 = shot["x"]
    b.x = 99999.0
    for _ in range(1200):
        if shot not in app.shots:
            break
        px, py, plife = shot["x"], shot["y"], shot["life"]
        app.projectiles(1 / 40.0)
        if shot not in app.shots:
            # life first: at the boundary a round satisfies both conditions,
            # and calling that "the floor" sent me hunting a fault that was
            # not there
            return abs(px - x0), ("ran out of life" if plife <= 1 / 20.0
                                  else "hit the floor"
                                  if py >= app.ground_at(px) - 12
                                  else "left the screen")
    return 0.0, "still flying"


def connects(weapon, gap, with_icons=False, seed=1):
    """Fire at a target standing at gap, and see if it is hit."""
    set_terrain(with_icons)
    random.seed(seed)
    square_up(weapon, gap)
    hits, iconed = [], []
    real_hit, real_t = app.hit_fighter, app.hit_target
    app.hit_fighter = lambda att, vic, d: (hits.append(1), real_hit(att, vic, d))[1]
    app.hit_target = lambda f, t, x, y: (iconed.append(1), real_t(f, t, x, y))[1]
    for _ in range(400):
        if hits:
            break
        app.update_fighter(a, 1 / 40.0)
        app.projectiles(1 / 40.0)
    app.hit_fighter, app.hit_target = real_hit, real_t
    return bool(hits), bool(iconed)


# --- 1. does each weapon connect at the range it fires from, icons or not ---
print("scale %.2f, so the AI opens fire at REACH x %.2f"
      % (gm.CFG["scale"], SCALE))
print("")
print("%-10s %7s  %-22s %s" % ("weapon", "fires@", "against a standing target",
                               "with icons between"))
for w in INSTANT + LOBBED + FLAT:
    reach = gm.REACH[w] * SCALE
    clean, _ = connects(w, reach, False)
    dirty, ic = connects(w, reach, True)
    note = "hit" if clean else "MISSED"
    dnote = ("hit" if dirty else "BLOCKED" if ic else "missed")
    if not clean:
        bad.append("%s misses a standing target at its own firing distance" % w)
    if not dirty and ic:
        bad.append("%s is stopped by a desktop icon" % w)
    print("%-10s %7.0f  %-22s %s" % (w, reach, note, dnote))

# --- 1b. stray fire: cursor shots and window shots against the same wall ----
# Both used to be soaked by whatever icon stood first in the corridor -- only
# fighter-vs-fighter fire carried pierce. shots_over_icons (default on) lets
# them over too; an aimed round still hits the one thing it was fired at, and
# turning the setting off must bring the old cover behaviour back.


def stray(kind, over, seed=5):
    """Fire a blaster at the cursor, or at a window, through the wall."""
    gm.CFG["shots_over_icons"] = over
    window = (700, int(GROUND) - 60, 1100, int(GROUND), 4242) \
        if kind == "window" else None
    set_terrain(True, window=window)
    random.seed(seed)
    a.x, a.y = 200.0, GROUND
    a.vx = a.vy = 0.0
    a.on_ground, a.hp, a.stun = True, 100.0, 0.0
    a.tumble = a.squash = 0.0
    a.carry, a.foe, a.mode = None, None, "roam"
    a.face = 1
    b.x = 99999.0
    app.shots = []
    hits = []
    real_t = app.hit_target
    app.hit_target = lambda f, t, x, y: (hits.append(t.get("kind")),
                                         real_t(f, t, x, y))[1]
    if kind == "window":
        a.target = [t for t in app.terrain.targets() if t["kind"] == "window"][0]
        a.plan = "blaster"
        real_r = random.random
        random.random = lambda: 0.0            # start_attack keeps the plan
        app.start_attack(a)
        random.random = real_r
    else:
        a.target = None
        real_c = random.choice
        random.choice = lambda seq: "blaster" if "blaster" in seq else real_c(seq)
        app.start_attack(a, at=(830.0, GROUND - 40))
        random.choice = real_c
    assert a.weapon == "blaster", a.weapon
    for _ in range(400):
        app.update_fighter(a, 1 / 40.0)
        app.projectiles(1 / 40.0)
        if hits or (a.state != "attack" and not app.shots):
            break
    app.hit_target = real_t
    return hits


print("")
print("%-24s %-14s %s" % ("stray fire", "setting on", "setting off"))
for kind in ("cursor", "window"):
    on, off = stray(kind, True), stray(kind, False)
    if kind == "cursor":
        good_on, good_off = not on, "icon" in off
        want_on = "flies over" if good_on else "EATEN: %s" % on
        want_off = "blocked" if good_off else "NOT BLOCKED: %s" % off
    else:
        good_on = bool(on) and on[0] == "window"
        good_off = bool(off) and off[0] == "icon"
        want_on = "hits the window" if good_on else "WRONG: %s" % on
        want_off = "icon takes it" if good_off else "WRONG: %s" % off
    print("%-24s %-14s %s" % (kind, want_on, want_off))
    if not good_on:
        bad.append("%s shot with shots_over_icons on: %s" % (kind, on or "none"))
    if not good_off:
        bad.append("%s shot with shots_over_icons off: %s" % (kind, off or "none"))
gm.CFG["shots_over_icons"] = True

# --- 2. how much road a flat round has left past that distance -------------
set_terrain(False)
print("")
print("%-10s %7s %8s %7s  %s"
      % ("weapon", "fires@", "can fly", "margin", "stopped by"))
for w in LOBBED + FLAT:
    reach = gm.REACH[w] * SCALE
    runs = []
    for i in range(SAMPLES):
        shot, hit = fire(w, reach, 1000 + i)
        if shot is None:
            continue
        runs.append(follow(shot))
    if not runs:
        bad.append("%s never released a round" % w)
        continue
    runs.sort()
    flown, cause = runs[len(runs) // 2]          # median of the samples
    ratio = flown / reach if reach else 0.0
    print("%-10s %7.0f %8.0f %7.2f  %s" % (w, reach, flown, ratio, cause))
    if w in FLAT and ratio < MARGIN:
        bad.append("%s only outruns its firing distance by %.2fx "
                   "(%s)" % (w, ratio, cause))

print("")
if bad:
    print("PROBLEMS:")
    for x in bad:
        print("  " + x)
else:
    print("every weapon reaches, and the flat ones have road to spare")

try:
    app.tray.remove()
    app.root.destroy()
except Exception:
    pass
if os.path.exists(gm.MEMORY_PATH):
    os.remove(gm.MEMORY_PATH)
sys.exit(1 if bad else 0)
