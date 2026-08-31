"""Do their shots actually reach each other, and what stops them?

For each ranged weapon: stand the two of them apart at the distance the AI is
willing to open fire from (REACH scaled the way decide() scales it), fire, and
follow the projectile. Reports whether it reached the foe, fell short, or was
eaten by a desktop icon on the way.
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
a.foe, b.foe = b, a


def set_terrain(with_icons):
    """A column of icons standing between them, at their own height."""
    t = app.terrain
    icons = []
    if with_icons:
        for i in range(6):
            x = 700 + i * 120
            icons.append(("Icon %d" % i, x, 940, x + 64, 1004, i))
    t.icons, t.windows, t.moved, t.win_pos = icons, [], {}, {}
    t.icons_ok = bool(icons)
    tg, pl = [], []
    for name, l, tp, r, bo, idx in t.icons:
        tg.append({"cx": (l + r) / 2, "cy": (tp + bo) / 2, "top": tp,
                   "name": name, "w": r - l, "h": bo - tp,
                   "kind": "icon", "key": idx})
        pl.append((l, r, tp, "icon", idx))
    t._targets, t.platforms = tg, pl
    t.bounds = [(x["cx"], x["cy"], x["w"] / 2, max(x["h"], 26) / 2, x)
                for x in tg]


hits = {"foe": 0, "icon": 0}
_hf, _ht = app.hit_fighter, app.hit_target
app.hit_fighter = lambda att, vic, d: (hits.__setitem__("foe", hits["foe"] + 1),
                                       _hf(att, vic, d))[1]
app.hit_target = lambda f, t, x, y: (hits.__setitem__("icon", hits["icon"] + 1),
                                     _ht(f, t, x, y))[1]

GROUND = app.ground_at(900)
RANGED = ("bow", "blaster", "rocket", "minigun", "bomb")


def trial(weapon, with_icons):
    set_terrain(with_icons)
    hits["foe"] = hits["icon"] = 0
    app.parts, app.shots, app.booms, app.bolts, app.slashes = [], [], [], [], []
    K = a.K()
    # exactly how far decide()/the fight state let him open fire from
    reach = gm.REACH[weapon] * (.4 + .6 * K)
    a.x, a.y = 640.0, GROUND
    b.x, b.y = 640.0 + reach * 0.92, GROUND
    for f in (a, b):
        f.vx = f.vy = 0.0
        f.on_ground = True
        f.hp = 100.0
        f.state = "fight"
        f.hits = 0
    a.face = 1
    cx, cy = b.x, b.y - 34 * b.sc
    # go through start_attack, which is where the aim and the foe-bound flag
    # are decided; random() pinned to 0 makes it keep the weapon we asked for
    import random as _r
    real = _r.random
    _r.random = lambda: 0.0
    a.plan = weapon
    app.start_attack(a, foe=True)
    _r.random = real
    assert a.weapon == weapon, "wanted %s, got %s" % (weapon, a.weapon)
    a.atk, a.fired, a.burst = 0.0, False, 0.0
    app.release_attack(a)
    if weapon == "minigun":                 # fires in a burst, not one shot
        for _ in range(6):
            app.shoot(a, "pellet", 1050, 60, .9)
    launched = len(app.shots)
    best = 1e9
    travelled = 0.0
    x0 = a.x
    for _ in range(400):
        for s in app.shots:
            best = min(best, gm.dist(s["x"], s["y"], cx, cy))
            travelled = max(travelled, s["x"] - x0)
        if not app.shots:
            break
        app.projectiles(1 / 40.0)
        if hits["foe"] or hits["icon"]:
            break
    gap = b.x - a.x
    return {"reach": reach, "gap": gap, "launched": launched,
            "closest": best, "travelled": travelled,
            "foe": hits["foe"], "icon": hits["icon"]}


print("scale %.2f, so K=%.2f: speeds scale by K, reaches by (.4+.6K)=%.2f"
      % (gm.CFG["scale"], a.K(), .4 + .6 * a.K()))
print()
print("%-9s %6s %6s %8s %9s   %s" %
      ("weapon", "gap", "flew", "closest", "outcome", "with icons between them"))
bad = []
for w in RANGED:
    clean = trial(w, False)
    dirty = trial(w, True)
    if clean["foe"]:
        out = "HIT"
    elif clean["closest"] < 40:
        out = "near"
    else:
        out = "SHORT"
    if dirty["foe"] and dirty["icon"]:
        d = "hit foe, blast also caught an icon"
    elif dirty["foe"]:
        d = "hit foe"
    elif dirty["icon"]:
        d = "BLOCKED by an icon"
    else:
        d = "still short"
    print("%-9s %6.0f %6.0f %8.0f %9s   %s"
          % (w, clean["gap"], clean["travelled"], clean["closest"], out, d))
    if out == "SHORT":
        bad.append("%s falls short by %.0fpx" % (w, clean["closest"]))
    if dirty["icon"] and not dirty["foe"]:
        bad.append("%s is eaten by a desktop icon" % w)

print()
if bad:
    print("PROBLEMS:")
    for x in bad:
        print("  " + x)
else:
    print("all weapons reach, and icons do not intercept")

try:
    app.tray.remove()
    app.root.destroy()
except Exception:
    pass
if os.path.exists(gm.MEMORY_PATH):
    os.remove(gm.MEMORY_PATH)
sys.exit(1 if bad else 0)
