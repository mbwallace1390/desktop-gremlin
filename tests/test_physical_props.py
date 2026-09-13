"""Actual toy motion, rendered collision bounds, and moving rope regressions.

The standard harness isolates desktop I/O and every persisted path.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

gm = harness.load("physical_props", crowd=3, scale=1.0, toy_props=True,
                  parkour=False, react_to_windows=False, scenes=False)
from gremlin_motion import MotionEngine

app = harness.build(gm)
app.ox, app.oy, app.W, app.H = 0, 0, 1600, 900
app.mons = [((0, 0, 1600, 900), (0, 0, 1600, 860))]
engine = MotionEngine(app, gm.CFG)
app.motion = engine
f, mate, other = app.fighters
DT = 1.0 / 60
bad = []


def reset():
    engine.clear()
    harness.fake_terrain(app)
    gm.CFG.update(toy_props=True, parkour=False, surface_material="standard",
                  physics_preset="normal", play_mode="mischief")
    app.asleep = False
    for i, actor in enumerate(app.fighters):
        actor.x, actor.y = 1100 + i * 100, 860
        actor.vx = actor.vy = actor.stun = actor.tumble = actor.vr = 0.0
        actor.hp, actor.on_ground, actor.state = 100, True, "idle"
        actor.grabbed, actor.carry, actor.play = False, None, None
        actor.mount = actor.ridden_by = None
        actor.plat, actor.mode = ("floor", None), "roam"
        actor.motion_last_vy = actor.physics_impact_vy = 0.0
        actor.face, actor.goal, actor.ledge_cd = 1, app.time + 999, app.time + 999


def tick(count=1, actors=False):
    for _ in range(count):
        app.time += DT
        engine.update(DT)
        if actors:
            for actor in app.fighters:
                if not engine.control(actor, DT):
                    app.physics(actor, DT, app.ground_at(actor.x, actor.y))


def impact_and_rest():
    p = engine.add_prop("crate", 420, 860)
    engine.hit_prop(p, 397, 823, 950, -120)
    assert p["vx"] > 0 and abs(p["omega"]) > .01, "off-center impact has no torque"
    tick(18)
    assert p["x"] > 430 and abs(p["angle"]) > .03, "crate remains decorative"
    tick(480)
    assert p["sleeping"], "grounded crate never settles to sleep"
    x, y = p["x"], p["y"]
    tick(90)
    assert math.hypot(p["x"] - x, p["y"] - y) < .1, "sleeping crate creeps"
    engine.blast(p["x"] - 20, p["y"] - 30, 120, 350)
    assert not p["sleeping"] and p["vx"] > 0, "blast cannot wake crate"
    p["vx"], p["vy"] = 0.0, 0.0
    engine.blast(p["x"] - 60, p["y"] - 24, 120, -350)
    assert p["vx"] < 0 and abs(p["vy"]) < .01, "negative radial force does not attract"


def stack_and_support():
    lower = engine.add_prop("crate", 600, 860)
    upper = engine.add_prop("crate", 600, 700)
    tick(360)
    assert upper["sleeping"] and lower["sleeping"], "stack does not sleep"
    assert abs(upper["y"] - engine._height(lower, upper["x"])) < 1.5, "crate tunneled through stack"
    engine.hit_prop(lower, 570, 835, 1400, -80)
    tick(90)
    assert upper["y"] > 820, "removed support left floating crate"
    harness.fake_terrain(app, windows=[("shelf", 800, 650, 1100, 720, 17)])
    shelf = engine.add_prop("crate", 920, 480)
    tick(240)
    assert abs(shelf["y"] - 650) < 1.5, "crate misses window support"


def crate_collision():
    first = engine.add_prop("crate", 350, 860)
    second = engine.add_prop("crate", 500, 860)
    tick(60)
    assert second["sleeping"], "receiver crate did not settle"
    first["vx"], first["sleeping"] = 800, False
    tick(18)
    assert first["x"] < second["x"] and second["vx"] > 20, "fast crate skips or fails to wake other crate"


def swept_and_rendered():
    p = engine.add_prop("crate", 500, 700)
    p["angle"] = .55
    app._frame_begin()
    engine.draw()
    app._frame_end()
    points = []
    for item in app.canvas.find_withtag("toys"):
        if app.canvas.itemcget(item, "state") != "hidden" and app.canvas.type(item) != "text":
            points.extend(zip(app.canvas.coords(item)[::2], app.canvas.coords(item)[1::2]))
    left, right = min(x for x, _y in points), max(x for x, _y in points)
    top, bottom = min(y for _x, y in points), max(y for _x, y in points)
    hit = engine.projectile_contact(left - 400, (top + bottom) / 2,
                                    right + 400, (top + bottom) / 2, 2)
    assert hit is not None and hit[3] is p and hit[1] < -.5, "fast shot skips rotated crate"
    assert engine.projectile_contact(left - 10, top - 15, right + 10, top - 15) is None, "invisible box catches clear shot"
    # A diagonal thin ramp must not collide in the empty region above its face.
    ramp = engine.add_prop("ramp", 850, 860)
    assert engine.projectile_contact(790, 822, 810, 822) is None, "ramp collider fills empty triangle"
    assert engine.projectile_contact(850, 760, 850, 900)[3] is ramp
    p["angle"] = 0
    assert engine.projectile_contact(469, 676, 440, 676) is None, "separating shot ricochets twice"


def materials():
    distances = {}
    for name in ("standard", "ice", "sticky"):
        reset()
        gm.CFG["surface_material"] = name
        p = engine.add_prop("crate", 400, 860)
        engine.hit_prop(p, 369, 836, 900, 0)
        tick(90)
        distances[name] = p["x"] - 400
    assert distances["ice"] > distances["standard"] * 1.4, distances
    assert distances["sticky"] < distances["standard"] * .8, distances
    heights = {}
    for name in ("standard", "rubber"):
        reset()
        gm.CFG["surface_material"] = name
        p = engine.add_prop("crate", 600, 560)
        touched = False
        peak = 860
        for _ in range(130):
            tick()
            touched = touched or p["y"] > 854
            if touched:
                peak = min(peak, p["y"])
        heights[name] = peak
    assert heights["rubber"] < heights["standard"] - 35, heights


def physics_presets():
    drops, impulses = {}, {}
    for name in ("normal", "moon", "heavy"):
        reset()
        gm.CFG["physics_preset"] = name
        p = engine.add_prop("crate", 500, 350)
        engine.hit_prop(p, 469, 326, 600, 0)
        impulses[name] = p["vx"]
        tick(30)
        drops[name] = p["y"] - 350
    assert drops["moon"] < drops["normal"] * .5 < drops["heavy"], drops
    assert impulses["heavy"] < impulses["normal"] * .8, impulses
    reset()
    gm.CFG["physics_preset"] = "bouncy"
    p = engine.add_prop("crate", 500, 600)
    saw_bounce = False
    for _ in range(75):
        tick()
        saw_bounce = saw_bounce or p["vy"] < -300
    assert saw_bounce, "bouncy preset does not affect crate contacts"
    gm.CFG["surface_material"] = "ice"
    tick()
    assert p["material"] == "ice", "live surface setting leaves old props unchanged"


def seesaw_torque():
    def launch(speed, lever):
        reset()
        p = engine.add_prop("seesaw", 620, 860)
        mate.x, mate.y, mate.plat = 675, 842, ("toy", p["id"])
        engine.update(DT)  # Register the seated rider before impact.
        f.x, f.y, f.plat = 620 - lever, engine._height(p, 620 - lever), ("toy", p["id"])
        f.motion_last_vy = f.physics_impact_vy = speed
        lowest = 0
        for _ in range(18):
            tick(actors=True)
            lowest = min(lowest, mate.vy)
        return -lowest
    strong, gentle, middle = launch(620, 55), launch(90, 55), launch(620, 12)
    assert strong > gentle + 35 and strong > middle + 35, (strong, gentle, middle)


def continuous_forces():
    fan = engine.add_prop("fan", 500, 860)
    f.x, f.y, f.on_ground, f.state, f.vy = 500, 810, False, "fall", 300
    engine.control(f, DT)
    assert 100 < f.vy < 300, "fan teleports incoming velocity to a preset speed"
    tick(100, actors=True)
    assert f.y < 790, "continuous fan does not lift"
    crate = engine.add_prop("crate", 500, 660)
    tick(80)
    assert crate["y"] < 828, "fan cannot lift physical prop"
    reset()
    p = engine.add_prop("conveyor", 550, 860)
    f.x, f.y, f.plat = 520, 850, ("toy", p["id"])
    engine.control(f, DT)
    assert 0 < f.vx < 90 * f.K(), "belt must accelerate by traction"
    tick(40, actors=True)
    assert f.x > 535, ("belt friction is erased by actor ground damping", f.x, f.vx)


def moving_rope():
    gm.CFG["parkour"] = True
    harness.fake_terrain(app, windows=[("anchor", 450, 250, 650, 310, 21)])
    f.x, f.y, f.on_ground, f.state, f.vx = 710, 610, False, "fall", 130
    assert engine.start(f, "rope", (550, 250))
    action = engine.actions[f]
    assert action["hwnd"] == 21, "rope discards window identity"
    engine.control(f, DT)
    x0, vx0 = f.x, f.vx
    harness.fake_terrain(app, windows=[("anchor", 458, 250, 658, 310, 21)])
    engine.control(f, DT)
    assert action["anchor"] == (558, 250), "anchor stays behind moved window"
    assert f.x > x0 + 2 and f.vx > vx0 + 25, ("window velocity missing from pendulum", f.x - x0, f.vx - vx0)
    release_vx = f.vx
    harness.fake_terrain(app)
    engine.control(f, DT)
    assert f not in engine.actions and f.state != "parkour", "closed anchor does not release"
    assert abs(f.vx - release_vx) < .01, "anchor deletion loses tangent momentum"


def rope_sweep():
    gm.CFG["parkour"] = True
    f.x, f.y, f.on_ground, f.state, f.vx = 430, 650, False, "fall", 900
    assert engine.start(f, "rope", (430, 290))
    harness.fake_terrain(app, windows=[("obstacle", 480, 350, 490, 800, 9)])
    engine.control(f, .12)
    assert f.x < 480 and f not in engine.actions, "rope tunnels through window side"


def rope_window_jump():
    gm.CFG["parkour"] = True
    harness.fake_terrain(app, windows=[("anchor", 450, 250, 650, 310, 21)])
    f.x, f.y, f.on_ground, f.state, f.vx = 710, 610, False, "fall", 130
    assert engine.start(f, "rope", (550, 250))
    engine.control(f, DT)
    x, y, vx, vy = f.x, f.y, f.vx, f.vy
    harness.fake_terrain(app, windows=[("anchor", 1150, 250, 1350, 310, 21)])
    engine.control(f, DT)
    assert f not in engine.actions, "window teleport retains rope ownership"
    assert (f.x, f.y, f.vx, f.vy) == (x, y, vx, vy), "window teleport drags body through desktop"


def lifecycle():
    for i in range(6):
        assert engine.add_prop("crate", 100 + i * 180, 860) is not None
    assert engine.add_prop("crate", 1450, 860) is None
    tick(30)
    engine.update(1000)
    assert not engine.props and not engine.platforms(), "expired dynamic bodies remain"


try:
    for name, test in (("impulse torque and sleep", impact_and_rest),
                       ("stack and terrain support", stack_and_support),
                       ("crate momentum transfer", crate_collision),
                       ("swept drawn geometry", swept_and_rendered),
                       ("material responses", materials), ("physics presets", physics_presets),
                       ("seesaw lever impulse", seesaw_torque),
                       ("continuous fan and belt", continuous_forces),
                       ("moving and deleted anchor", moving_rope),
                       ("rope collision sweep", rope_sweep), ("window jump releases rope", rope_window_jump),
                       ("bounded lifecycle", lifecycle)):
        reset()
        try:
            test()
            print("PASS " + name)
        except Exception as exc:
            bad.append(name + ": " + str(exc))
            print("FAIL " + bad[-1])
finally:
    harness.teardown(gm, app)
print("\n" + ("FAIL\n" + "\n".join(bad) if bad else "PASS physical props"))
sys.exit(1 if bad else 0)
