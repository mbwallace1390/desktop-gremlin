"""Real new-weapon releases, swept impacts, status ownership and canvas output.

Removing a release hook, collision branch, recoil, catch, status cleanup or
draw path must fail its corresponding scenario. The desktop is harness-owned.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness

gm = harness.load("expansion_arsenal", crowd=3, scale=1.0, play_mode="mischief")
app = harness.build(gm)
harness.fake_terrain(app)
app.ox, app.oy, app.W, app.H = 0, 0, 8000, 2400
app.mons = [((0, 0, 8000, 2400), (0, 0, 8000, 2350))]
a, b, c = app.fighters
NAMES = ("boomerang", "bubble", "freeze", "swap", "glove", "rubber", "foam")
bad = []


def check(name, body):
    try:
        body()
        print("PASS", name)
    except AssertionError as exc:
        bad.append("%s: %s" % (name, exc))
        print("FAIL", bad[-1])


def engine():
    assert all(w in gm.WEAPONS for w in NAMES), "seven weapons missing from real combat"
    if not hasattr(app, "arsenal"):
        # Module-only focused run before the root's lifecycle integration lands.
        from gremlin_arsenal import Arsenal
        app.arsenal = Arsenal(app, gm.CFG)
    return app.arsenal


def reset():
    e = engine()
    e.clear()
    gm.CFG["play_mode"] = "mischief"
    gm.MEM["relationships"] = {}
    for i, f in enumerate((a, b, c)):
        f.x, f.y = 600.0 + i * 190, 1600.0
        f.vx = f.vy = f.squash = f.tumble = f.stun = 0.0
        f.hp, f.blink = 100.0, 10.0
        f.on_ground, f.grabbed, f.plat = False, False, None
        f.motion_dodging = False
        f.set_state("idle")
        f.foe, f.mode, f.target, f.face = None, "roam", None, 1
        f.per = dict(f.per, weapons=NAMES)
    c.x = 6500
    a.foe, b.foe, a.mode, b.mode = b, a, "fight", "fight"
    return e


def fire(name, face=1):
    e = reset()
    a.plan = name
    if face < 0:
        a.x, b.x = 1000, 810
    app.start_attack(a, foe=True)
    assert a.state == "attack" and a.weapon == name, "planned weapon did not start"
    a.atk = gm.RELEASE_AT.get(name, .55) * a.atk_dur
    app._st_attack(a, 1 / 120.0, a.K())
    assert e.shots, "real attack produced no projectile"
    return e, e.shots[-1]


def advance(e, seconds, control=False):
    for _ in range(round(seconds * 120)):
        app.time += 1 / 120.0
        e.update(1 / 120.0)
        if control:
            for f in app.fighters:
                e.control(f, 1 / 120.0)


def releases_and_drawing():
    for name in NAMES:
        for face in (1, -1):
            e, shot = fire(name, face)
            mx, my = app.muzzle(a)
            assert math.hypot(shot["x"] - mx, shot["y"] - my) < 4, name + " muzzle drift"
            app._frame_begin()
            app.sx = app.sy = 0.0
            app.draw_fighter(a, 0)
            e.draw()
            app._frame_end()
            visible = [it for it in app.canvas.find_withtag("arsenal")
                       if app.canvas.itemcget(it, "state") != "hidden"]
            assert visible, name + " has no visible flight"
            for it in visible:
                assert all(math.isfinite(v) for v in app.canvas.coords(it)), "invalid canvas position"


def impacts():
    for name, status in (("bubble", "bubble"), ("freeze", "freeze"), ("foam", "foam")):
        e, _shot = fire(name)
        advance(e, .8)
        assert status in b.effects and b.state == "effect", name + " did not capture victim"
        old_y, old_x = b.y, b.x
        advance(e, .25, True)
        if status == "bubble":
            assert b.y < old_y - 1, "bubble victim did not float"
        elif status == "freeze":
            assert b.x > old_x + 1, "frozen cube did not slide"
        else:
            assert abs(b.x - old_x) < .01, "sticky victim escaped sideways"
        app.draw()
        assert any(app.canvas.itemcget(it, "state") != "hidden"
                   for it in app.canvas.find_withtag("arsenal")), "status is invisible"


def shields_pop_rescue_expiration():
    e = reset()
    assert e.apply_effect(b, "shield", 5)
    app.hit_fighter(a, b, 13)
    assert b.hp == 100 and b.state == "idle", "shield leaked hit/knockback"
    app.hit_fighter(a, b, 10)
    assert b.hp == 97 and "shield" not in b.effects, "shield budget not consumed"
    e.apply_effect(b, "bubble", 4, a)
    app.hit_fighter(c, b, 3)
    assert "bubble" not in b.effects and b.state == "thrown", "hit did not pop bubble"
    e.apply_effect(b, "foam", 4, a)
    b.set_state("grabbed")
    e.update(.05)
    assert not b.effects and b.state == "grabbed", "effect overrode user grab"
    b.set_state("idle")
    e.apply_effect(b, "freeze", .15, a)
    advance(e, .2, True)
    assert not b.effects and b.state != "effect", "timed effect stranded control"
    e.apply_effect(b, "foam", 4, a)
    e.clear(b)
    assert not b.effects and b.state != "effect", "rescue clear stranded friend"
    assert not e.apply_effect(b, "bubble", float("nan"), a), "nonfinite duration accepted"


def swap_and_glove():
    e, _shot = fire("swap")
    ax, bx = a.x, b.x
    advance(e, .8)
    assert abs(a.x - bx) < 1 and abs(b.x - ax) < 1, "swap did not exchange positions"
    assert a.state == b.state == "fall", "swap left obsolete attack/platform ownership"
    e, _shot = fire("glove")
    assert a.vx < -100 * a.K() and a.vy < 0, "glove has no heavy recoil"
    advance(e, .8)
    assert b.hp < 90 and b.vx > 0, "glove did not punch victim"


def allowed_loadouts():
    e = reset()
    a.per = dict(a.per, weapons=("foam",))
    a.plan = "sword"
    app.start_attack(a, foe=True)
    assert a.weapon == "foam", "stale plan escaped custom weapon list"
    a.set_state("idle")
    app.start_attack(a, at=(a.x + 20, a.y - 30))
    assert a.weapon == "foam", "cursor attack escaped custom weapon list"
    a.weapon = "bubble"
    app.release_attack(a)
    assert not e.shots, "release bypassed changed loadout"
    a.per = dict(a.per, weapons=())
    assert gm.plan_weapon(a.per) is not None, "empty loadout crashed planning"


def allies_shields_dodge_and_caps():
    e = reset()
    key = "|".join(sorted((b.kind, c.kind)))
    gm.MEM["relationships"][key] = 30
    e.apply_effect(b, "bubble", 4, a)
    before = b.hp
    app.hit_fighter(c, b, 10)
    assert b.hp == before and "bubble" not in b.effects, "friend pop hurt its occupant"
    e.apply_effect(b, "foam", 4, a)
    b.y, c.y, c.x = 2350, 2350, b.x + 20
    advance(e, .7, True)
    assert "foam" not in b.effects, "nearby friend did not free sticky victim"
    e, _shot = fire("freeze")
    e.apply_effect(b, "shield", 5)
    advance(e, .8)
    assert b.hp == 100 and "freeze" not in b.effects, "shield allowed capture"
    e, _shot = fire("glove")
    b.motion_dodging = True
    advance(e, .8)
    assert b.hp == 100, "projectile hit a sliding dodge"
    e, _shot = fire("rubber")
    for _ in range(60):
        app.release_attack(a)
    assert len(e.shots) <= 32, "projectile count is unbounded"
    e.clear()
    assert not e.shots and not e.effects, "full cleanup retained ownership"


def boomerang_return_and_bonk():
    e, shot = fire("boomerang")
    b.x = 7000
    a.set_state("idle")
    advance(e, 5)
    assert not e.shots and a.hp == 100, "facing owner failed to catch return"
    e, shot = fire("boomerang")
    b.x = 7000
    a.set_state("idle")
    a.face = -1
    advance(e, 5)
    assert not e.shots and a.hp < 100, "turned-away owner cannot be bonked"
    e, shot = fire("boomerang")
    b.x = 7000
    a.set_state("idle")
    shot["x"], shot["y"], shot["vx"], shot["vy"] = 700, 2340, 50, 500
    advance(e, 6)
    assert not e.shots, "floor contact trapped returning boomerang forever"


def in_frame_interruption_order():
    e = reset()
    # Real releases ordered victim, attacker, unrelated owner. The middle hit
    # interrupts the first owner while both earlier/later rounds are pending.
    for owner, target, weapon in ((b, c, "bubble"), (a, b, "glove"), (c, a, "rubber")):
        owner.foe, owner.mode, owner.plan = target, "fight", weapon
        app.start_attack(owner, foe=True)
        app.release_attack(owner)
    victim_round, attack_round, third_round = e.shots
    attack_round.update(x=b.x - 40, y=b.y - 34 * b.sc, vx=10000, vy=0)
    old_x = third_round["x"]
    e.update(.01)
    assert b.hp < 100, "middle projectile did not reach victim"
    assert victim_round not in e.shots, "hit resurrected victim's cancelled round"
    assert third_round in e.shots and third_round["x"] != old_x, "cleanup skipped trailing owner's flight"


def collision_bounds_and_cleanup():
    e, shot = fire("rubber")
    # A narrow real monitor rectangle forces repeated visible wall/floor bounces.
    app.W, app.H = 1200, 1800
    app.mons = [((0, 0, 1200, 1800), (0, 0, 1200, 1750))]
    b.x, c.x = 6000, 7000
    advance(e, 12)
    assert not e.shots, "ricochets never terminate"
    app.W, app.H = 8000, 2400
    app.mons = [((0, 0, 8000, 2400), (0, 0, 8000, 2350))]
    e, shot = fire("bubble")
    b.x = 7000
    advance(e, 2.5)
    assert shot in e.shots and shot["x"] > 1200, "wide-desktop shot disappeared early"
    shot["vx"] = 900000
    b.x, b.y = shot["x"] + 1500, shot["y"] + 34 * b.sc
    e.update(.01)
    assert "bubble" in b.effects, "fast shot tunneled through victim"
    e.clear(a)
    assert not e.shots and not b.effects, "removed source retained shots/statuses"
    e.apply_effect(b, "freeze", 5, a)
    b.x, b.y, b.vx = 700, 2349, 900
    harness.fake_terrain(app, windows=[("Obstacle", 820, 2270, 920, 2390, 7)])
    e.control(b, .2)
    assert b.x < 820 or not b.effects, "sliding cube tunneled through a window"
    e.apply_effect(b, "freeze", 5, a)
    b.x, b.y, b.vx = 700, 2349, 900
    harness.fake_terrain(app, windows=[("Far wall", 950, 2250, 1050, 3100, 8),
                                     ("Near wall", 820, 2250, 920, 3100, 7)])
    e.control(b, .4)
    assert b.x < 820, "cube used terrain order instead of first crossed wall"
    harness.fake_terrain(app)
    e, _shot = fire("foam")
    gm.CFG["play_mode"] = "peaceful"
    e.update(.05)
    assert not e.shots, "peaceful change left ammunition live"
    before = b.hp
    app.hit_fighter(a, b, 10)
    assert b.hp == before, "peaceful mode allowed damage"


for name, body in (("real releases and canvas", releases_and_drawing),
                   ("capture and movement", impacts),
                   ("shield, pop, rescue and expiry", shields_pop_rescue_expiration),
                   ("swap and glove recoil", swap_and_glove),
                   ("profile weapon boundaries", allowed_loadouts),
                   ("allies, shields, dodges and caps", allies_shields_dodge_and_caps),
                   ("boomerang catch and owner bonk", boomerang_return_and_bonk),
                   ("same-frame interruption ordering", in_frame_interruption_order),
                   ("sweeps, wide flights and lifecycle", collision_bounds_and_cleanup)):
    check(name, body)
harness.finish(gm, app, bad)
