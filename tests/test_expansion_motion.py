"""Controlled travel and real Tk prop rendering; all desktop I/O is sandboxed.

Missing pendulum acceleration, landing/crash branches, cooperative launch,
passive toy forces, lifetime cleanup or priority guards each break a check.
"""
import importlib.util
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

assert importlib.util.find_spec("gremlin_motion") is not None, "motion engine is missing"
from gremlin_motion import MotionEngine

gm = harness.load("expansion_motion", crowd=3, scale=1.0, parkour=True,
                  toy_props=True, react_to_windows=False, scenes=False)
app = harness.build(gm)
app.ox, app.oy, app.W, app.H = 0, 0, 1600, 900
app.mons = [((0, 0, 1600, 900), (0, 0, 1600, 860))]
harness.fake_terrain(app)
engine = MotionEngine(app, gm.CFG)
app.motion = engine
f, mate, other = app.fighters
DT = 1.0 / 60
bad = []


def reset():
    engine.clear()
    app.shots[:] = []
    app.asleep = False
    gm.CFG.update(parkour=True, toy_props=True, play_mode="mischief")
    harness.fake_terrain(app)
    for i, actor in enumerate(app.fighters):
        actor.x, actor.y = 420.0 + i * 240, 860.0
        actor.vx = actor.vy = actor.tumble = actor.vr = actor.stun = 0.0
        actor.hp, actor.on_ground = 100, True
        actor.face = 1
        actor.grabbed, actor.carry, actor.play = False, None, None
        actor.mount = actor.ridden_by = None
        actor.plat = ("floor", None)
        actor.state, actor.mode = "idle", "roam"
        actor.pose_from = None
        actor.foe = actor.target = None
        actor.goal = app.time + 999
        actor.ledge_cd = app.time + 999


def tick(count=1):
    for _ in range(count):
        app.time += DT
        engine.update(DT)
        for actor in app.fighters:
            actor.st += DT
            if not engine.control(actor, DT):
                app.physics(actor, DT, app.ground_at(actor.x, actor.y))


def draw_toys():
    app._frame_begin()
    engine.draw()
    app._frame_end()
    return [item for item in app.canvas.find_withtag("toys")
            if app.canvas.itemcget(item, "state") != "hidden"]


def check(name, test):
    reset()
    try:
        test()
        print("PASS " + name)
    except Exception as exc:
        bad.append(name + ": " + str(exc))
        print("FAIL " + bad[-1])


def rope():
    f.x, f.y, f.on_ground = 450, 580, False
    assert engine.start(f, "rope", (610, 290))
    before = (f.x, f.y)
    speeds, lengths = [], []
    for _ in range(35):
        tick()
        if f.state != "parkour":
            break
        speeds.append(math.hypot(f.vx, f.vy))
        lines = [app.canvas.coords(i) for i in draw_toys()
                 if app.canvas.type(i) == "line"]
        rope_line = next(p for p in lines if abs(p[0] - 610) < 1 and abs(p[1] - 290) < 1)
        lengths.append(math.hypot(rope_line[2] - 610, rope_line[3] - 290))
    assert len(lengths) > 12 and max(lengths) - min(lengths) < 1.5, "rope stretches"
    assert max(speeds) > min(speeds) + 20, "rope lacks pendulum acceleration"
    assert math.hypot(f.x - before[0], f.y - before[1]) > 35, "swing did not travel"
    for _ in range(180):
        tick()
        if f.state != "parkour":
            break
    assert f.state != "parkour" and abs(f.vx) > 40 and not f.on_ground, "release lost momentum"
    assert not draw_toys(), "released rope still drawn"


def wall_kick():
    harness.fake_terrain(app, windows=[("fake", 600, 280, 950, 740, 17)])
    f.x, f.y, f.on_ground, f.vx = 593, 520, False, 170
    assert engine.start(f, "wall_kick", (600, 1))
    tick(8)
    assert f.x < 580 and f.vx < 0 and f.vy < -80, "wall failed to reverse and lift"


def roll():
    f.vx = 240
    assert engine.start(f, "roll")
    x0 = f.x
    tick(12)
    assert f.x > x0 + 12 and abs(f.tumble) > .3, "landing roll neither travels nor rotates"
    tick(80)
    assert f.state != "parkour" and f.tumble == 0, "roll never recovers"


def vault():
    crate = engine.add_prop("crate", 485, 860)
    f.x, f.face = 433, 1
    assert engine.start(f, "vault", crate)
    tick(20)
    assert f.y < 810, "vault did not clear crate"
    tick(100)
    assert f.x > 510 and f.on_ground and f.state != "parkour", "vault did not land beyond obstacle"


def slide():
    app.shots.append({"owner": mate, "x": f.x + 95, "y": f.y - 45,
                      "vx": -350, "vy": 0, "k": "pistol"})
    x0 = f.x
    assert engine.start(f, "slide")
    tick(8)
    pose = engine.pose(f)
    assert f.x != x0 and pose[1] > -20, "dodge did not lower moving body"
    assert getattr(f, "motion_dodging", False), "slide does not signal projectile evasion"
    tick(60)
    assert not getattr(f, "motion_dodging", False), "slide protection outlives slide"


def plane_landing():
    f.x, f.y, f.on_ground = 300, 490, False
    assert engine.start(f, "plane")
    x0 = f.x
    tick(60)
    assert f.x > x0 + 70 and f.y < 660, "paper plane fails to glide"
    assert len(draw_toys()) >= 3, "paper plane not drawn"
    for _ in range(600):
        tick()
        if f.state != "parkour" and f.on_ground:
            break
    assert f.on_ground and f.state != "parkour", "paper plane did not land"
    assert not draw_toys(), "landed plane remains attached"


def plane_crash():
    harness.fake_terrain(app, windows=[("fake", 450, 330, 650, 710, 9)])
    f.x, f.y, f.on_ground, f.face = 380, 510, False, 1
    assert engine.start(f, "plane")
    tick(70)
    assert f.state != "parkour", "plane flew through window side"
    assert f.stun > 0 or f.tumble != 0 or f.state == "thrown", "plane crash has no visible consequence"


def boost():
    mate.x = f.x + 32
    assert engine.start(f, "boost", mate)
    tick(30)
    assert f.y < 785 and f.vy < -120, "teammate did not launch flyer"
    assert mate.on_ground, "helper flew with flyer"
    tick(190)
    assert f.state != "parkour" and mate.state != "parkour", "boost did not release both actors"


def crate_support():
    p = engine.add_prop("crate", 500, 860)
    f.x, f.y, f.on_ground = 500, 720, False
    tick(90)
    assert f.on_ground and f.y < 840 and f.plat == ("toy", p["id"]), "crate has no physical top"


def seesaw():
    p = engine.add_prop("seesaw", 620, 860)
    f.x, f.y, f.vy, f.on_ground = 580, 720, 250, False
    mate.x, mate.y, mate.on_ground = 660, 842, True
    mate.plat = ("toy", p["id"])
    launched = False
    for _ in range(100):
        tick()
        launched = launched or mate.vy < -120
    assert launched, "seesaw does not launch opposite rider"


def ramp():
    engine.add_prop("ramp", 550, 860)
    f.x, f.y, f.vx, f.face, f.state = 491, 860, 95, 1, "walk"
    lowest = f.y
    for _ in range(50):
        tick()
        lowest = min(lowest, f.y)
    assert lowest < 835 and f.x > 540, "ramp does not carry feet uphill"


def fan():
    engine.add_prop("fan", 500, 860)
    f.x = 500
    tick(60)
    assert f.y < 785 and not f.on_ground, "fan does not lift nearby actor"


def conveyor():
    p = engine.add_prop("conveyor", 550, 860)
    f.x, f.y, f.plat = 520, 850, ("toy", p["id"])
    x0 = f.x
    tick(40)
    assert f.x > x0 + 15, "conveyor fails to transport idle actor"


def protection():
    for state in ("grabbed", "ko", "sleep", "carry", "perch", "hang", "cling", "knock"):
        f.state = state
        assert not engine.start(f, "plane"), "stole " + state
    f.state, f.y, f.on_ground = "fall", 500, False
    assert engine.start(f, "rope", (550, 220))
    f.set_state("grabbed")
    x0, y0 = f.x, f.y
    engine.update(DT)
    assert not engine.control(f, DT) and f.state == "grabbed", "stole interruption"
    assert (f.x, f.y) == (x0, y0) and not draw_toys(), "interrupted rope owns position or drawing"
    engine.clear()
    f.state, f.y, f.on_ground = "idle", 860, True
    assert engine.start(f, "roll")
    tick(5)
    f.set_state("thrown")
    f.vr, f.tumble = 7.0, .7
    engine.update(DT)
    assert (f.vr, f.tumble) == (7.0, .7), "roll cleanup erased new hit rotation"


def cleanup():
    for kind in ("crate", "seesaw", "ramp", "fan", "conveyor"):
        engine.add_prop(kind, 160 + 230 * len(engine.props), 860)
    assert len(draw_toys()) > 18, "props have no distinct visible geometry"
    for i in range(20):
        engine.add_prop("crate", 160 + 50 * i, 860)
    assert len(engine.props) <= 6, "unbounded prop construction"
    engine.update(1000)
    assert not engine.props and not engine.platforms(), "expired props retain support"
    engine.add_prop("crate", 500, 860)
    engine.clear()
    assert not draw_toys(), "clear leaves visible toys"
    mate.x = f.x + 20
    assert engine.start(f, "boost", mate)
    app.fighters.remove(mate)
    engine.update(DT)
    assert not engine.actions and f.state != "parkour", "removed teammate remains referenced"
    app.fighters.append(mate)


def automatic():
    f.x, f.y, f.on_ground = 300, 500, False
    # Force only the feature's probability gate; its selected path is real.
    import gremlin_motion
    old = gremlin_motion.random.random
    gremlin_motion.random.random = lambda: 0.0
    try:
        assert engine.consider(f), "travel never considered during ordinary AI"
    finally:
        gremlin_motion.random.random = old
    engine.clear()
    f.x, f.y, f.on_ground, f.state = 300, 500, True, "idle"
    old = gremlin_motion.random.random
    gremlin_motion.random.random = lambda: 0.0
    try:
        assert engine.consider(f), "elevated platform cannot begin automatic travel"
    finally:
        gremlin_motion.random.random = old
    engine.clear()
    f.state, f.on_ground = "idle", True
    gm.CFG["parkour"] = False
    assert not engine.consider(f) and not engine.start(f, "roll"), "parkour toggle ignored"
    gm.CFG["toy_props"] = False
    assert engine.add_prop("crate", 500, 860) is None, "toy toggle ignored"


def construction():
    for _ in range(13):
        engine.update(1.0)
    assert engine.props and draw_toys(), "normal idle simulation never constructs a toy"


def drawing_coordinates():
    app.ox, app.oy = -200, -100
    app.mons = [((-200, -100, 1400, 800), (-200, -100, 1400, 760))]
    try:
        p = engine.add_prop("crate", 320, 700)
        drawn = draw_toys()
        box = next(i for i in drawn if app.canvas.type(i) == "rectangle")
        coords = app.canvas.coords(box)
        assert 480 < coords[0] < 500 and 750 < coords[1] < 765, "prop world offset is wrong"
        # Toys used to carry a 6pt caption ("CRATE"), which this checked for
        # world coordinates; the caption is gone, and must stay gone.
        assert not any(app.canvas.type(i) == "text" for i in drawn), "toy printed a caption"
    finally:
        app.ox, app.oy = 0, 0
        app.mons = [((0, 0, 1600, 900), (0, 0, 1600, 860))]


def drawn_body():
    def head_top():
        app._frame_begin()
        app.sx = app.sy = 0.0
        app.draw_fighter(f, 0)
        engine.draw()
        app._frame_end()
        head = app._pool[app._ftag[0][1]]["oval"][0]
        return app.canvas.coords(head)[1]
    standing_top = head_top()
    assert engine.start(f, "slide")
    tick(14)
    assert head_top() > standing_top + 18, "actual drawn head does not duck during slide"
    engine.clear()
    f.x, f.y, f.on_ground, f.state = 450, 580, False, "fall"
    head_top()
    assert engine.start(f, "rope", (610, 290))
    tick(1)
    head_top()
    rope_line = next(app.canvas.coords(i) for i in app.canvas.find_withtag("toys")
                     if app.canvas.type(i) == "line" and app.canvas.itemcget(i, "state") != "hidden"
                     and abs(app.canvas.coords(i)[0] - 610) < 1)
    hand_item = app._pool[app._ftag[0][3]]["line"][0]
    hand = app.canvas.coords(hand_item)[-2:]
    assert math.hypot(hand[0] - rope_line[2], hand[1] - rope_line[3]) < 6, "drawn hand misses rope"


try:
    for name, test in (("pendulum and release", rope), ("wall kick", wall_kick),
                       ("landing roll", roll), ("crate vault", vault),
                       ("projectile slide", slide), ("paper plane landing", plane_landing),
                       ("paper plane crash", plane_crash), ("team boost", boost),
                       ("crate support", crate_support), ("seesaw impulse", seesaw),
                       ("ramp ascent", ramp), ("fan lift", fan),
                       ("conveyor transport", conveyor), ("state priorities", protection),
                       ("bounded cleanup and drawing", cleanup), ("automatic travel", automatic),
                       ("automatic construction", construction), ("world-coordinate drawing", drawing_coordinates),
                       ("rendered duck and rope grip", drawn_body)):
        check(name, test)
finally:
    harness.teardown(gm, app)
print("\n" + ("FAIL\n" + "\n".join(bad) if bad else "PASS expansion motion"))
sys.exit(1 if bad else 0)
