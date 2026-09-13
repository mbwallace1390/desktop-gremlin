"""Surface normals, prop cover and incoming impacts through real toy releases."""
import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

gm = harness.load("physics_arsenal", crowd=2, scale=1.0, play_mode="mischief")
app = harness.build(gm)
app.ox, app.oy, app.W, app.H = 0, 0, 4000, 2400
app.mons = [((0, 0, 4000, 2400), (0, 0, 4000, 2350))]
a, b = app.fighters
real_motion = app.motion
bad = []


def fire(kind="rubber", **trajectory):
    app.motion = real_motion
    app.arsenal.clear()
    real_motion.clear()
    app.W, app.H = 4000, 2400
    app.mons = [((0, 0, 4000, 2400), (0, 0, 4000, 2350))]
    harness.fake_terrain(app)
    gm.CFG.update(play_mode="mischief", physics_preset="normal", surface_material="standard", toy_props=False)
    for f, x in ((a, 100), (b, 3400)):
        f.x, f.y, f.hp = x, 1600, 100
        f.vx = f.vy = f.stun = f.tumble = 0
        f.on_ground = f.grabbed = f.motion_dodging = False
        f.plat, f.target, f.mode, f.face = None, None, "fight", 1
        f.set_state("idle")
    a.per = dict(a.per, weapons=(kind,))
    a.foe, a.plan = b, kind
    app.start_attack(a, foe=True)
    app.release_attack(a)
    shot = app.arsenal.shots[-1]
    shot.update(x=500, y=500, vx=0, vy=0, g=0, pierce=False, tgt=None)
    shot.update(trajectory)
    return shot


def target_normals():
    for trajectory, signs in ((dict(x=950, y=700, vx=100, vy=1000), (1, -1)),
                              (dict(x=700, y=850, vx=1000, vy=100), (-1, 1)),
                              (dict(x=700, y=600, vx=1000, vy=1000), (-1, -1))):
        shot = fire(**trajectory)
        harness.fake_terrain(app, icons=[("Block", 900, 800, 1200, 1100, 7)])
        app.arsenal.update(.25)
        assert shot in app.arsenal.shots, "first target bounce removed rubber shot"
        assert shot["vx"] * signs[0] > 0 and shot["vy"] * signs[1] > 0, \
            "rubber reflected across the wrong target face"
        assert shot["bounces"] == 1, "one surface consumed multiple ricochets"
        for _ in range(5):
            app.arsenal.update(.01)
        assert shot["bounces"] == 1, "inclusive zero-time collision pinned the ricochet"


def materials_and_gravity():
    speeds = {}
    for name in ("ice", "standard", "rubber", "sticky"):
        shot = fire(x=500, y=2300, vx=160, vy=500)
        gm.CFG["surface_material"] = name
        app.arsenal.update(.15)
        speeds[name] = abs(shot["vy"])
        assert all(math.isfinite(shot[k]) for k in ("x", "y", "vx", "vy"))
    assert speeds["rubber"] > speeds["standard"] > speeds["sticky"], \
        "surface materials did not change rubber restitution"
    shot = fire(vy=0, g=160)
    gm.CFG["physics_preset"] = "moon"
    app.arsenal.update(.1)
    moon = shot["vy"]
    shot = fire(vy=0, g=160)
    gm.CFG["physics_preset"] = "heavy"
    app.arsenal.update(.1)
    assert shot["vy"] > moon * 2, "toy gravity ignored the physics preset"


def prop_cover_and_slope():
    shot = fire("glove", x=500, y=1000, vx=2000)
    b.x, b.y = 850, 1034
    hits = []
    prop = {"kind": "crate", "material": "standard"}
    app.motion = SimpleNamespace(projectile_contact=lambda *args: (.2, -1, 0, prop),
                                 hit_prop=lambda *args, **kw: hits.append((args, kw)), clear=lambda *args: None)
    app.arsenal.update(.25)
    assert b.hp == 100 and hits and shot not in app.arsenal.shots, "crate failed to cover victim"
    assert hits[0][0][3:5] == (2000, 0), "prop impulse lost the incoming vector"

    shot = fire(x=500, y=500, vx=600, vy=0)
    normal = -math.sqrt(.5)
    hit_count = [0]
    def slope(*args):
        hit_count[0] += 1
        return (.3, normal, normal, prop) if hit_count[0] == 1 else None
    app.motion = SimpleNamespace(projectile_contact=slope, hit_prop=lambda *args, **kw: None,
                                 clear=lambda *args: None)
    app.arsenal.update(.25)
    assert shot["vy"] < -100 and abs(shot["vx"]) < 100, "slope normal did not redirect rubber flight"


def real_props_receive_shots():
    for kind in ("glove", "bubble", "freeze", "foam", "swap"):
        shot = fire(kind, x=850, y=1070, vx=1000)
        gm.CFG["toy_props"] = True
        prop = real_motion.add_prop("crate", 1000, 1100)
        prop["sleeping"] = True
        b.x, b.y = 1100, 1104
        app.arsenal.update(.3)
        assert shot not in app.arsenal.shots and b.hp == 100 and not app.arsenal.effects.get(b), \
            kind + " passed through real crate cover"
        assert prop["vx"] > 0 and not prop["sleeping"], kind + " failed to wake and push crate"
    shot = fire(x=850, y=1080, vx=1000)
    gm.CFG["toy_props"] = True
    real_motion.add_prop("ramp", 1000, 1100)
    app.arsenal.update(.25)
    assert shot["vy"] < -100 and shot["vx"] > 0, "real ramp failed to bank rubber upward"
    assert shot["bounces"] == 1, "real ramp trapped rubber in duplicate contacts"


def contact_order_and_incoming_impact():
    shot = fire("glove", x=500, y=1000, vx=2000)
    b.x, b.y = 650, 1034
    props = []
    prop = {"kind": "crate"}
    app.motion = SimpleNamespace(projectile_contact=lambda *args: (.8, -1, 0, prop),
                                 hit_prop=lambda *args, **kw: props.append(args), clear=lambda *args: None)
    impacts = []
    original = getattr(app, "impact_fighter", None)
    def record(att, vic, dmg, direction=None, strength=1, point=None):
        impacts.append((direction, point))
        app.hit_fighter(att, vic, dmg)
    app.impact_fighter = record
    try:
        app.arsenal.update(.25)
        assert b.hp < 100 and not props, "later prop took precedence over nearer fighter"
        assert impacts and impacts[0][0] == (2000, 0), "fighter impulse used shooter position instead of flight"
    finally:
        if original is None:
            del app.impact_fighter
        else:
            app.impact_fighter = original


def bounded_arcs_and_return():
    shot = fire(x=1500, y=-100, vx=0, vy=-50, g=160)
    app.arsenal.update(.1)
    assert shot in app.arsenal.shots, "upward rubber arc was deleted above the desktop"
    shot = fire(x=600, y=1800, vx=6000, vy=100, g=160)
    app.W = 1200
    app.mons = [((0, 0, 1200, 2400), (0, 0, 1200, 2350))]
    for _ in range(2000):
        app.arsenal.update(.01)
        if shot not in app.arsenal.shots:
            break
    assert shot not in app.arsenal.shots and shot["bounces"] == 6, "rubber ricochet budget failed"
    shot = fire("boomerang", x=500, y=1000, vx=2000)
    prop = {"kind": "crate"}
    app.motion = SimpleNamespace(projectile_contact=lambda *args: (.1, -1, 0, prop),
                                 hit_prop=lambda *args, **kw: None, clear=lambda *args: None)
    app.arsenal.update(.1)
    assert shot["phase"] == "return", "prop obstruction did not turn boomerang"
    for _ in range(500):
        app.arsenal.update(.01)
        if shot not in app.arsenal.shots:
            break
    assert shot not in app.arsenal.shots, "returning boomerang remained trapped by prop"


for name, body in (("target face and corner normals", target_normals),
                   ("materials and gravity presets", materials_and_gravity),
                   ("prop cover and slope reflection", prop_cover_and_slope),
                   ("real crate cover and ramp bank", real_props_receive_shots),
                   ("earliest contact and incoming impulse", contact_order_and_incoming_impact),
                   ("bounded arcs and boomerang return", bounded_arcs_and_return)):
    try:
        body()
        print("PASS", name)
    except AssertionError as exc:
        bad.append("%s: %s" % (name, exc))
        print("FAIL", bad[-1])
app.motion = real_motion
harness.finish(gm, app, bad)
