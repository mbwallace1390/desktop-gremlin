"""Shots finish visible flight; a cleanup event is never a fake impact.

The older range check only covered the short distance at which the AI fires.
These checks release the real weapons from an elevated platform on a wide
desktop, then follow their shots beyond the old lifetime and through contact.
All terrain and desktop mutation boundaries are isolated by the harness.
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

gm = harness.load("projectile_flight", crowd=2, react_to_windows=False)
gm.monitors = lambda: [((0, 0, 3840, 2160), (0, 0, 3840, 2100))]
gm.virtual_screen = lambda: (0, 0, 3840, 2160)
app = harness.build(gm)
app.root.withdraw()
a, b = app.fighters
bad = []
DT = 1 / 120.0
blasts = []
app.blast_icons = lambda *args: blasts.append(args)


def check(label, ok):
    print("%-65s %s" % (label, "pass" if ok else "FAIL"))
    if not ok:
        bad.append(label)


def alive(shot):
    return any(s is shot for s in app.shots)


def reset_effects():
    app.parts, app.booms, app.bolts, app.slashes = [], [], [], []
    app.traps, app.stains = [], []
    blasts.clear()
    app.shake_t = 0.0


def fire(weapon, scale=.68, x=300., y=180., target=None):
    """Reach the actual release frame while standing on a fake platform."""
    random.seed(812)
    harness.fake_terrain(app, [("Firing ledge", x - 45, y, x + 45, y + 50, 91)])
    app.shots = []
    reset_effects()
    for f in (a, b):
        f.sc = scale
        f.vx = f.vy = f.stun = f.tumble = f.squash = 0.0
        f.foe = f.play = f.carry = f.pose_last = f.pose_from = None
        f.hp, f.on_ground, f.boredom = 100.0, True, 0.0
        f.out, f.hit_at, f.mood_check = 0.0, -1000.0, 1000.0
        f.set_state("idle")
    a.x, a.y, a.plan, a.mode = x, y, weapon, "roam"
    a.per = dict(a.per, weapons=tuple(gm.WEAPONS))
    b.x, b.y, b.hp = -10000.0, 2100.0, 0.0
    tx, ty = target if target is not None else (x + 3000, y - 44 * scale)
    # An aimed point is enough; it is not added as a collision obstacle.
    a.target = {"kind": "window", "key": 92, "cx": tx, "cy": ty,
                "top": ty - 16, "w": 20, "h": 32, "name": "Distant aim"}
    app.start_attack(a)
    for _ in range(240):
        app.time += DT
        app.update_fighter(a, DT)
        if app.shots:
            shot = app.shots[0]
            # The rest of the test follows the ammunition, not the next attack.
            app.shots = [shot]
            harness.fake_terrain(app)
            reset_effects()
            return shot
    raise AssertionError("%s never released a projectile" % weapon)


def advance(seconds):
    for _ in range(int(math.ceil(seconds / DT))):
        app.time += DT
        app.projectiles(DT)
        app.fx_tick(DT)


# Each threshold comes from the released shot, not a copied weapon table.
ordinary = ("bow", "blaster", "minigun", "rocket", "confetti", "harpoon",
            "magnet", "balloon", "peel", "spring")
for scale in (.35, .68):
    for weapon in ordinary:
        shot = fire(weapon, scale)
        old_life = shot["life"]
        advance(old_life + .15)
        check("%s at scale %.2f survives its old timer in clear air" % (weapon, scale),
              alive(shot) and 0 < shot["x"] < app.W
              and 0 < shot["y"] < app.ground_at(shot["x"], shot["y"]))

for weapon in ("anvil", "piano"):
    shot = fire(weapon, .35)
    advance(shot["life"] + .15)
    check("%s falls past its old timer on a tall desktop" % weapon,
          alive(shot) and shot["y"] < app.ground_at(shot["x"], shot["y"]))

# A surviving object must also remain visible and participate in real collision.
shot = fire("blaster")
advance(shot["life"] + .2)
app.draw()
drawn = False
for item in app._pool.get("shot", {}).get("line", []):
    if app.canvas.itemcget(item, "state") == "hidden":
        continue
    coords = app.canvas.coords(item)
    if len(coords) >= 4 and gm.dist(coords[-2] + app.ox, coords[-1] + app.oy,
                                    shot["x"], shot["y"]) < 1:
        drawn = True
check("the drawn laser continues after its old timeout", alive(shot) and drawn)
b.hp, b.x, b.y = 100.0, shot["x"] + 150, shot["y"] + 34 * b.sc
advance(1.0)
check("a laser can hit a fighter after its old timeout", b.hp < 100 and not alive(shot))

for scale in (.35, 1.5):
    shot = fire("blaster", scale)
    advance((app.W - 150 - shot["x"]) / shot["vx"])
    check("a laser at scale %.2f crosses the wide desktop" % scale,
          alive(shot) and shot["x"] >= app.W - 160)

# A deflection is a new journey even when the inbound shot is already older
# than its original cleanup timer. The returning round must still be visible.
shot = fire("blaster")
advance(shot["life"] + .2)
b.hp, b.x, b.y, b.face = 100.0, shot["x"] + 100, shot["y"] + 34 * b.sc, -1
b.state, b.weapon, b.atk, b.atk_dur = "attack", "pan", .2, .4
for _ in range(120):
    if not alive(shot) or shot["owner"] is b:
        break
    advance(DT)
reflected = alive(shot) and shot["owner"] is b and shot["vx"] < 0
a.hp = 0.0
advance(1.0)
check("an old projectile remains live after a pan reflection", reflected and alive(shot))

# Thrown objects must reach their actual landing point, without teleporting a
# ground prop from its two-second timeout several hundred pixels overhead.
for weapon in ("bow", "balloon", "peel", "spring", "anvil", "piano"):
    shot = fire(weapon, .35)
    for _ in range(2400):
        if not alive(shot):
            break
        advance(DT)
    floor = app.ground_at(shot["x"], shot["y"])
    landed = not alive(shot) and abs(shot["y"] - floor) < .001
    if weapon in gm.TRAPS:
        landed = landed and len(app.traps) == 1 and abs(app.traps[0]["x"] - shot["x"]) < .001
    check("%s reaches the physical floor before impact" % weapon, landed)

# These are deliberately timed devices: their fuse remains visible behavior.
for weapon in ("bomb", "blackhole"):
    shot = fire(weapon, .35)
    fuse = shot["life"]
    advance(fuse - .1)
    armed = alive(shot) and not app.booms and not blasts
    advance(.2)
    check("%s retains its intentional fuse" % weapon,
          armed and not alive(shot) and bool(app.booms) and bool(blasts)
          and shot["y"] < app.ground_at(shot["x"], shot["y"]) - 100)

# Gravity-driven arcs may temporarily cross the top and return. Straight fire
# leaves the scene instead of accumulating invisible shots high above it.
for weapon in ("bow", "balloon", "peel", "spring"):
    shot = fire(weapon, 1.5, y=80., target=(300., -1000.))
    above, returned = False, False
    for _ in range(1600):
        if not alive(shot):
            break
        advance(DT)
        above = above or shot["y"] < -60
        returned = returned or (above and alive(shot) and shot["y"] >= 0 and shot["vy"] > 0)
    check("%s can leave the top and fall back into view" % weapon, above and returned)

for weapon in ("blaster", "minigun", "rocket", "confetti", "harpoon", "magnet"):
    shot = fire(weapon, y=180., target=(300., -10000.))
    for _ in range(480):
        if not alive(shot):
            break
        advance(DT)
    check("upward %s retires outside the top without impact" % weapon,
          not alive(shot) and shot["y"] < 0 and not app.booms and not blasts and not app.traps)

for weapon in ("rocket", "bomb", "blackhole", "peel", "spring"):
    shot = fire(weapon, x=app.W - 80, y=400.)
    for _ in range(240):
        if not alive(shot):
            break
        advance(DT)
    check("%s leaving the side causes no blast or ground prop" % weapon,
          not alive(shot) and shot["x"] > app.W
          and not app.booms and not blasts and not app.traps)

# Invalid/stalled fixtures are defensive boundaries, not alternate spawn paths.
# In particular, cleanup must not become an explosion, a floor spark or a trap.
for kind, changes in (
        ("laser", {"vx": 0.0, "vy": 0.0, "g": 0.0, "life": .01}),
        ("rocket", {"vx": float("nan")}),
        ("spring", {"x": float("inf")}),
        ("bomb", {"g": float("nan")}),
        ("peel", {"y": app.H + 100.0})):
    reset_effects()
    shot = {"k": kind, "x": 800.0, "y": 400.0, "vx": 100.0, "vy": 0.0,
            "g": 0.0, "life": 1.0, "owner": a, "trail": [], "spin": 0.0,
            "pierce": True, "tgt": None}
    shot.update(changes)
    app.shots = [shot]
    b.hp = 0.0
    failed = False
    try:
        app.projectiles(.1)
    except (ValueError, OverflowError):
        failed = True
    check("invalid/stalled %s cleans up without any impact" % kind,
          not failed and not app.shots and not app.booms and not blasts
          and not app.traps and not app.parts)

harness.finish(gm, app, bad)
