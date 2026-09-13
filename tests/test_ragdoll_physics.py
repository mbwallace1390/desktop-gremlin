"""Passive limb dynamics, measured through the production Tk drawing when wired.

The harness owns every persistence path and desktop boundary before App exists.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

gm = harness.load("ragdoll_physics", crowd=1, scale=1.0)
from gremlin_ragdoll import Ragdoll

app = harness.build(gm)
harness.fake_terrain(app)
bad = []


def check(condition, message):
    if not condition:
        bad.append(message)


def actor(x=600, y=350):
    f = gm.Fighter(x, y)
    f.sc, f.face = 1.0, 1
    f.state, f.st = "grabbed", 1.0
    f.squash = f.tumble = 0.0
    return f


def tick(engine, f, n=1, dt=1 / 120):
    for _ in range(n):
        app.time += dt
        f.st += dt
        engine.update(f, dt)


def points(engine, f):
    p = engine.pose(f, app.raw_pose(f))
    knees = engine.joints(f, (None,) * 4)
    px, py, lean = p[:3]
    neck = (px + 26 * math.sin(lean), py - 26 * math.cos(lean) - 1)
    return [((px, py), knees[0], p[4]), ((px, py), knees[1], p[5]),
            (neck, knees[2], p[6]), (neck, knees[3], p[7])]


def rendered(f):
    app._frame_begin()
    app.sx = app.sy = 0.0
    app.draw_fighter(f, 0)
    app._frame_end()
    tb, ta = app._ftag[0][0], app._ftag[0][3]
    items = [app._pool[tb]["line"][0], app._pool[tb]["line"][1],
             app._pool[tb]["line"][2], app._pool[ta]["line"][0]]
    return [app.canvas.coords(item) for item in items]


try:
    engine = Ragdoll(app)
    still, dragged = actor(), actor()
    initial = app.raw_pose(still)
    still.pose_last = dragged.pose_last = initial
    for _ in range(60):
        tick(engine, still)
        tick(engine, dragged)
    # Same local pose and clock, different root acceleration. The moving
    # actor's limbs must lag from inertia, without any animation sine driver.
    for _ in range(12):
        dragged.x += 4
        tick(engine, still)
        tick(engine, dragged)
    ps, pd = points(engine, still), points(engine, dragged)
    lag = sum(a[2][0] - b[2][0] for a, b in zip(ps, pd)) / 4
    check(lag > 1.5, "moving grab did not produce visible inertial limb lag")
    frozen = engine.pose(dragged, app.raw_pose(dragged))
    for _ in range(12):
        check(engine.pose(dragged, app.raw_pose(dragged)) == frozen,
              "render-time pose reads advanced physics")

    normal, moon = actor(), actor()
    normal.pose_last = moon.pose_last = (0., -30., 0., 0., (-20., -15.), (20., -15.),
                                         (-20., -60.), (20., -60.))
    normal_engine = Ragdoll(app, {"physics_preset": "normal"})
    moon_engine = Ragdoll(app, {"physics_preset": "moon"})
    tick(normal_engine, normal, 12)
    tick(moon_engine, moon, 12)
    normal_hand = normal_engine.pose(normal, app.raw_pose(normal))[6]
    moon_hand = moon_engine.pose(moon, app.raw_pose(moon))[6]
    check(math.dist(normal_hand, moon_hand) > .3,
          "moon gravity did not affect passive limb motion")

    # Read geometric constraints from segment endpoints, independent of the
    # angular integrator's stored values, across impacts and body rotations.
    f = actor()
    f.state = "thrown"
    for i in range(420):
        f.x += math.sin(i * .13) * 5
        f.y = 360 + math.cos(i * .17) * 50
        f.tumble += .09
        tick(engine, f)
        p = engine.pose(f, app.raw_pose(f))
        for j, (anchor, hinge, end) in enumerate(points(engine, f)):
            vectors = ((hinge[0] - anchor[0], hinge[1] - anchor[1]),
                       (end[0] - hinge[0], end[1] - hinge[1]))
            length = 16 if j < 2 else 13
            check(all(abs(math.hypot(*v) - length) < .001 for v in vectors),
                  "a ragdoll segment stretched or collapsed")
            bend = math.atan2(vectors[0][0] * vectors[1][1] - vectors[0][1] * vectors[1][0],
                              vectors[0][0] * vectors[1][0] + vectors[0][1] * vectors[1][1])
            check(.039 <= bend <= 2.651 if j < 2 else -2.751 <= bend <= -.039,
                  "knee/elbow exceeded its anatomical hinge limits")
            upper = math.atan2(vectors[0][1], vectors[0][0])
            relative = (upper - (math.pi / 2 + p[2]) + math.pi) % (2 * math.pi) - math.pi
            check(abs(relative) <= (1.501 if j < 2 else 2.851),
                  "hip/shoulder exceeded its swing limit")
            check(all(math.isfinite(v) for point in (anchor, hinge, end) for v in point),
                  "non-finite ragdoll coordinate")

    # Grounded knockouts at both facings and arbitrary final body rotations
    # must keep every simulated knee, elbow, foot and hand above the floor.
    floor = app.ground_at(600, 700)
    for scale, squash in ((.6, -.5), (1.0, 0), (1.8, .6)):
        for face in (-1, 1):
            for turn in (0, .7, 1.6, 2.5, -2.2):
                f = actor(600, floor)
                f.face, f.state, f.on_ground, f.tumble = face, "ko", True, turn
                f.sc, f.squash = scale, squash
                for _ in range(90):
                    tick(engine, f)
                    world = app.frame(f)
                    ys = [world(*p)[1] for limb in points(engine, f) for p in limb]
                    check(max(ys) <= floor + .15, "grounded ragdoll limb penetrated the floor")

    f = actor()
    f.state, f.tumble = "thrown", 1.2
    tick(engine, f, 40)
    f.state, f.tumble, f.st = "idle", 0.0, 0.0
    tick(engine, f)
    recovering = engine.pose(f, app.raw_pose(f))
    check(recovering != app.raw_pose(f), "impact recovery snapped immediately to idle")
    tick(engine, f, 60)
    check(engine.pose(f, app.raw_pose(f)) == app.raw_pose(f),
          "recovery did not return full control to the authored pose")
    # Simulation stalls cannot create an unbounded catch-up loop or overflow.
    slow = actor()
    tick(engine, slow)
    for dt in (.3, 10.0, 1e6, float("nan"), 0.0, -.1):
        engine.update(slow, dt)
    check(all(math.isfinite(v) for limb in points(engine, slow) for p in limb for v in p),
          "large or invalid timestep destabilized passive limbs")
    for state in ("walk", "attack", "climb", "zip", "carry"):
        f.state = "thrown"
        tick(engine, f, 3)
        f.state = state
        base = app.raw_pose(f)
        check(engine.pose(f, base) is base, "%s inherited passive limbs" % state)

    # Keep the rendered check strict: integration must expose the same
    # constrained joints on canvas, rather than quietly falling back to IK.
    check(hasattr(app, "ragdoll"), "App has not integrated the ragdoll engine")
    if hasattr(app, "ragdoll"):
        f = app.fighters[0]
        f.x, f.y, f.sc = 600, 350, 1.0
        f.state, f.st, f.tumble, f.squash = "grabbed", 1.0, 0.0, 0.0
        f.on_ground = False
        tick(app.ragdoll, f, 80)
        drawn = rendered(f)
        expected = points(app.ragdoll, f)
        world = app.frame(f)
        for actual, limb in zip(drawn, expected):
            want = [v for point in limb for v in (world(*point)[0] - app.ox,
                                                 world(*point)[1] - app.oy)]
            check(max(abs(a - b) for a, b in zip(actual, want)) < .01,
                  "canvas did not use the simulated joint coordinates")

        # Drive real ownership, spring motion, root collisions and recovery.
        # This catches an omitted/misordered update hook even if direct engine
        # tests and one manually initialized drawing happen to look right.
        f._ragdoll, f.pose_last, f.pose_from = None, None, None
        f.x, f.y, f.gx, f.gy = 600., floor - 150, 600., floor - 150
        f.vx = f.vy = f.vr = f.tumble = f.squash = 0.0
        f.grabbed, f.on_ground = True, False
        f.set_state("grabbed")
        f.mood_check = f.blink = 1000.
        for i in range(50):
            f.gx += 2
            app.time += 1 / 120
            app.update_fighter(f, 1 / 120)
            rendered(f)
        check(f._ragdoll is not None and f._ragdoll.active,
              "real grabbed update did not activate passive limbs")
        f.grabbed = False
        f.vx, f.vy, f.vr = 220., 80., 3.
        f.set_state("thrown")
        recovered, landed = False, False
        previous, previous_state = rendered(f), f.state
        for _ in range(400):
            app.time += 1 / 120
            app.update_fighter(f, 1 / 120)
            current = rendered(f)
            landed = landed or f.on_ground
            check(all(math.isfinite(v) for limb in current for v in limb),
                  "real grab/throw/recovery produced invalid canvas geometry")
            if previous_state == "thrown" and f.state == "idle":
                jump = max(math.dist(old[i:i + 2], new[i:i + 2])
                           for old, new in zip(previous, current) for i in (0, 2, 4))
                check(jump < 12., "resetting tumble caused a visible recovery snap")
            previous, previous_state = current, f.state
            if f.state == "idle" and f._ragdoll is None:
                recovered = True
                break
        check(landed and recovered, "real thrown fighter did not land and finish recovery")
    print("ragdoll: inertial grabs, fixed segments, joint limits, ground contacts, recovery and canvas")
    for message in sorted(set(bad)):
        print("FAIL:", message)
finally:
    harness.teardown(gm, app)

sys.exit(1 if bad else 0)
