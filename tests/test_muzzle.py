"""Does every round leave the END of the weapon, as drawn?

For each weapon that fires, both facings, a spread of aims, and a squashed
and a tumbling body: draw him at the moment of release, read every weapon
point back off the canvas, take the one furthest along the aim -- that is the
tip -- and fire through the real path (_st_attack -> release_attack -> shoot).
The round's first position has to sit within 4px of that tip.

Three earlier muzzles each modelled the pose instead of sharing it: from the
shoulder, from the hand, along an idealised aim ray. Each sat a few pixels
off every barrel, and read as the round appearing beside the gun.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

gm = harness.load("muzzle", crowd=2)
app = harness.build(gm)
harness.fake_terrain(app, [])
# Keep the fixture smaller than the release position below: physics moves the
# fighter after emission, so reading the tip afterward must not pass by chance
# just because the developer's monitor happens to be tall enough.
app.mons = [((0, 0, 1280, 720), (0, 0, 1280, 720))]
app.ox = app.oy = 0
app.W, app.H = 1280, 720
f = app.fighters[0]
S = f.sc
DT = 1 / 40.0
TOL = 4.0
bad = []

# everything that puts something in the air from the weapon in his hand;
# the droppers call it down from the sky and the melee weapons fire nothing
SHOOTERS = [w for w in gm.WEAPONS if w not in gm.MELEE and w not in gm.DROPPERS]


THROWN = ("bomb", "balloon", "blackhole", "peel")   # drawn as a blob in the hand


def drawn_tip(w, aim):
    """Where the drawn weapon ends, read off the canvas, in screen pixels.

    A gun's tip is its furthest point along the aim. A thrown blob leaves
    from the blob itself -- the biggest oval, not the fuse spark. The spring
    leaves from the middle of its zigzag, and the bow's arrow from the middle
    of the bow's curve, the fifth vertex of its nine-point arc."""
    app._frame_begin()
    app.sx = app.sy = 0.0
    app.draw_fighter(f, 0)
    app._frame_end()
    lines, ovals = [], []                          # [(vertices)], [(cx, cy, r)]
    for tag in app._ftag[0][4:6]:                  # weapon, weapon dots
        for kind, items in app._pool.get(tag, {}).items():
            for it in items[:app._used[tag].get(kind, 0)]:
                co = app.canvas.coords(it)
                if kind == "line":
                    lines.append([(co[i] + app.ox, co[i + 1] + app.oy)
                                  for i in range(0, len(co), 2)])
                else:
                    ovals.append(((co[0] + co[2]) / 2 + app.ox,
                                  (co[1] + co[3]) / 2 + app.oy, co[2] - co[0]))
    if not lines and not ovals:
        return None
    if w in THROWN:
        cx, cy, _r = max(ovals, key=lambda o: o[2])
        return (cx, cy)
    if w == "bow":
        arc = max(lines, key=len)
        return arc[len(arc) // 2]
    if w == "spring":
        zig = max(lines, key=len)
        return (sum(p[0] for p in zig) / len(zig), sum(p[1] for p in zig) / len(zig))
    pts = [p for ln in lines for p in ln] + [(cx, cy) for cx, cy, _r in ovals]
    dx, dy = math.cos(aim), math.sin(aim)
    return max(pts, key=lambda p: p[0] * dx + p[1] * dy)


def fire(w, face, dx, dy, squash=0.0, tumble=0.0):
    """Aim at a target dx, dy from his chest, through start_attack, then run
    the frame in which the round is released. Returns (tip, spawn, aim)."""
    f.x, f.y = 900.0, 800.0
    f.on_ground, f.plat = True, ("floor", None)
    f.vx = f.vy = 0.0
    f.squash, f.tumble, f.stun = squash, tumble, 0.0
    f.face = face
    f.foe, f.mode = None, "roam"
    f.hp = 100.0
    cx, cy = f.x + face * dx, f.y - 44 * S + dy
    f.target = {"kind": "icon", "key": 0, "cx": cx, "cy": cy, "top": cy - 32,
                "name": "x", "w": 64, "h": 64}
    f.plan = w
    f.per = dict(f.per, weapons=tuple(gm.WEAPONS))
    f.snatch = False
    f.hits = 0                # a third lightning hit wrecks the target and idles him
    app.start_attack(f)
    if f.state != "attack" or f.weapon != w:
        return None, None, None
    # to the frame before the release; _st_attack advances atk by dt first
    f.atk = (.30 if w == "minigun" else gm.RELEASE_AT.get(w, .55)) * f.atk_dur
    app.shots.clear()
    if hasattr(app, "arsenal"):
        app.arsenal.shots.clear()
    app.bolts.clear()
    released_tip = []
    original_release = app.release_attack
    original_shoot = app.shoot

    def observe_release(fighter):
        original_release(fighter)
        # Read the actual weapon at emission, before recoil moves the body.
        # The glove visibly launches him backwards within this same frame.
        released_tip.append(drawn_tip(w, fighter.aim))

    def observe_shoot(fighter, *args, **kwargs):
        original_shoot(fighter, *args, **kwargs)
        if w == "minigun":
            # Continuous bursts bypass release_attack. Observe their barrel
            # here, before this update's physics can move the fighter.
            released_tip.append(drawn_tip(w, fighter.aim))

    app.release_attack = observe_release
    app.shoot = observe_shoot
    try:
        app.update_fighter(f, DT)
    finally:
        app.release_attack = original_release
        app.shoot = original_shoot
    if w == "lightning":
        spawn = tuple(app.bolts[-1]["pts"][:2]) if app.bolts else None
    else:
        rounds = app.shots or (app.arsenal.shots if hasattr(app, "arsenal") else [])
        spawn = (rounds[-1]["x"], rounds[-1]["y"]) if rounds else None
    return (released_tip[-1] if released_tip else drawn_tip(w, f.aim)), spawn, f.aim


# An attack never tumbles (the tumble belongs to thrown and ko), but it can
# start squashed from a landing, so squash is in and tumble is not.
CASES = [(face, dx, dy, sq, 0.0)
         for face in (1, -1)
         for dx, dy in ((300, -250), (300, -60), (300, 0), (300, 90),
                        (120, 200), (80, -20))
         for sq in (0.0,)]
CASES += [(1, 300, -60, .5, 0.0), (-1, 300, 0, .3, 0.0), (1, 200, 100, .3, 0.0)]

print("%-10s %7s %7s  %s" % ("weapon", "worst", "mean", "cases"))
for w in SHOOTERS:
    errs = []
    for face, dx, dy, sq, tb in CASES:
        tip, spawn, aim = fire(w, face, dx, dy, sq, tb)
        if tip is None or spawn is None:
            bad.append("%s: no round or no drawing (face %d, aim %s)" % (w, face, aim))
            continue
        errs.append(math.hypot(spawn[0] - tip[0], spawn[1] - tip[1]))
    if not errs:
        continue
    worst, mean = max(errs), sum(errs) / len(errs)
    print("%-10s %6.1fpx %6.1fpx  %d" % (w, worst, mean, len(errs)))
    if worst > TOL:
        bad.append("%s leaves %.1fpx from the end of the weapon" % (w, worst))

print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
harness.finish(gm, app, bad)
