"""Audit regressions at the real movement and combat entry points, on fakes."""
import os
import random
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

gm = harness.load("audit_behaviour", crowd=2, react_to_windows=False)
gm.monitors = lambda: [((0, 0, 1600, 1000), (0, 0, 1600, 960))]
gm.virtual_screen = lambda: (0, 0, 1600, 1000)
shell = harness.FakeShell([(300, 500), (600, 500)])
app = harness.build(gm, shell)
refresh = harness.fake_terrain(app, harness.shell_icons(shell))
a, b = app.fighters
bad = []
random.seed(1234)


def check(label, ok):
    print("%-45s %s" % (label, "pass" if ok else "FAIL"))
    if not ok:
        bad.append(label)


def park():
    app.shots.clear()
    app.cancel_icon_moves()
    for i, f in enumerate(app.fighters):
        app.end_ride(f)
        f.x, f.y = 200.0 + 500 * i, 960.0
        f.vx = f.vy = f.anger = f.boredom = 0.0
        f.hp, f.on_ground = 100.0, True
        f.mode, f.foe, f.target = "roam", None, None
        f.set_state("idle")
        f.goal = app.time + 1000


def carry():
    park()
    gm.CFG["move_icons"] = True
    refresh()
    assert app.pick_up_icon(a, app.terrain.targets()[0])
    app.carry_tick(a, .13)
    shell.writes.clear()


carry()
gm.CFG["move_icons"] = False
app._st_carry(a, .2, a.K())
check("disable stops ongoing carry writes", not shell.writes and a.carry is None
      and a.state != "carry")

carry()
gm.CFG["move_icons"] = False
app.drop_icon(a)
check("drop obeys disabled movement gate", not shell.writes and a.carry is None)

carry()
b.surf_idx = (1, *shell.OFF, 64, 64)
b.set_state("surf")
gm.CFG["move_icons"] = False
app.apply_settings()
check("settings cancel carry and surf together", not shell.writes
      and a.carry is None and b.surf_idx is None
      and a.state != "carry" and b.state != "surf")

for fatal in (False, True):
    carry()
    a.hp = 5 if fatal else 100
    app.hit_fighter(b, a, 10)
    check("damage releases icon (%s)" % ("KO" if fatal else "survived"),
          a.carry is None and a.state == ("ko" if fatal else "thrown")
          and len(shell.writes) == 1)

carry()
b.surf_idx = (1, *shell.OFF, 64, 64)
b.set_state("surf")
app.summon()
check("summon releases cargo and surfing claims", a.carry is None
      and b.surf_idx is None and a.state == b.state == "walk"
      and len(shell.writes) == 1)

carry()
a.set_state("jump")
app.update_fighter(a, .025)
check("other interrupted states release stale cargo", a.carry is None
      and len(shell.writes) == 1)

carry()
refresh()
t = app.terrain.targets()[1]
a.hits = 2
app.hit_target(a, t, t["cx"], t["cy"])
check("background projectile preserves icon delivery", a.carry is not None
      and a.state == "carry" and not shell.writes)


def restore_fake():
    # If undo is entered with a live claim, the next carry/surf tick can
    # overwrite it. Observe that ordering at the actual restore boundary.
    check("restore cancels claims before shell call", all(
        f.carry is None and f.surf_idx is None for f in app.fighters))
    shell.pos = {0: (300, 500), 1: (600, 500)}
    return 2


gm.restore_layout = restore_fake
gm.LAYOUT_DIRTY = False
for settings in (False, True):
    carry()
    b.surf_idx = (1, *shell.OFF, 64, 64)
    b.set_state("surf")
    if settings:
        window = SimpleNamespace(app=app, status=SimpleNamespace(config=lambda **kw: None))
        gm.SettingsWindow.restore(window)
    else:
        app.restore_icons()
    for f in app.fighters:
        app.update_fighter(f, .025)
    check("%s restore stays restored" % ("settings" if settings else "tray"),
          not shell.writes and shell.pos == {0: (300, 500), 1: (600, 500)})

gm.restore_layout = lambda: 1
gm.LAYOUT_DIRTY = True
status = {}
window = SimpleNamespace(app=app, status=SimpleNamespace(config=lambda **kw: status.update(kw)))
gm.SettingsWindow.restore(window)
messages = []
app.tray.notify = lambda title, text: messages.append(text)
app.restore_icons()
check("partial restore reported by both controls", "incomplete" in status["text"]
      and "incomplete" in messages[-1] and status["fg"] == "#FF5B47")
gm.LAYOUT_DIRTY = False

# Failed shell position reads must not manufacture offsets or acquire icons.
park()
gm.CFG["move_icons"] = True
refresh()
position = shell.item_pos
shell.item_pos = lambda idx: None
check("failed probe refuses icon blast", app.blast_icons(330, 530, 200, 80) == 0)
check("failed probe refuses icon yank", not app.yank_icon(app.terrain.targets()[0], 700))
check("failed probe refuses icon carry", not app.pick_up_icon(a, app.terrain.targets()[0]))
a.x = 330
check("failed probe refuses icon surf", not app.start_ride(a, "surf"))
shell.item_pos = position

# Foreground safety does not depend on window-reaction state/cache.
park()
gm.CFG["move_windows"] = True
gm.CFG["react_to_windows"] = False
app.terrain.win_rect = {4242: (300, 300, 800, 800)}
app.fg = ("stale", 1111)
gm.foreground_window = lambda: ("typing here", 4242)
gm.idle_seconds = lambda: .5
placed = []
gm.window_rect = lambda hwnd: app.terrain.win_rect[hwnd]
gm.place_window = lambda *args: placed.append(args) or True
check("actual foreground protected with reactions off",
      not app.nudge_window(4242, 10, 0) and not placed)
gm.idle_seconds = lambda: 5.0
check("idle foreground can still be nudged", app.nudge_window(4242, 10, 0)
      and len(placed) == 1)
gm.monitors = lambda: [((0, 0, 1600, 1000), (0, 0, 1600, 960)),
                       ((1600, 0, 3200, 1000), (1600, 0, 3200, 960))]
app.terrain.win_rect[4343] = (2000, 300, 2500, 800)
check("primary-only overlay keeps secondary nudge local", app.nudge_window(4343, 10, 0)
      and placed[-1] == (4343, 2010, 300))
gm.CFG["move_windows"] = gm.CFG["move_icons"] = False

# Fire through the real attack entry point, then put the opponent across
# exactly one frame of travel. Endpoint-only collision misses these shots.
for fps in (15, 20):
    park()
    harness.fake_terrain(app)
    a.foe, a.plan, a.mode = b, "minigun", "fight"
    a.per = dict(a.per, weapons=tuple(gm.WEAPONS))
    app.start_attack(a, foe=True)
    for _ in range(30):
        app._st_attack(a, .025, a.K())
        if app.shots:
            break
    assert app.shots
    shot = app.shots[0]
    dt = 1.0 / fps
    b.x = shot["x"] + shot["vx"] * dt / 2
    b.y = shot["y"] + (shot["vy"] + shot["g"] * dt) * dt / 2 + 40 * b.sc
    app.projectiles(dt)
    check("minigun hits between frames at %dfps" % fps, b.hp < 100 and not app.shots)


def round_at(x=200, y=600, vx=1350):
    a.aim = 0
    a.shot_pierce, a.shot_tgt = False, None
    app.shoot(a, "pellet", vx, 0, 1.15, at=(x, y))
    return app.shots[-1]


def target(kind, key, x):
    return {"kind": kind, "key": key, "cx": x, "cy": 600., "w": 2., "h": 30.,
            "top": 585., "name": "fixture"}


real_target_hit = app.hit_target
terrain_hits = []
app.hit_target = lambda f, t, x, y: terrain_hits.append((t["key"], x))
for near_kind, far_kind in (("icon", "window"), ("window", "icon")):
    park()
    terrain_hits.clear()
    near, far = target(near_kind, 1, 207), target(far_kind, 2, 226)
    app.terrain.bounds = [(t["cx"], t["cy"], 1., 15., t) for t in (far, near)]
    round_at()
    app.projectiles(1 / 15)
    check("nearest %s wins despite terrain order" % near_kind,
          terrain_hits == [(1, 206.)])

park()
terrain_hits.clear()
near, far = target("icon", 1, 207), target("window", 2, 226)
app.terrain.bounds = [(t["cx"], t["cy"], 1., 15., t) for t in (near, far)]
shot = round_at()
shot["pierce"], shot["tgt"] = True, ("window", 2)
app.projectiles(1 / 15)
check("aimed piercing hits only selected terrain", terrain_hits == [(2, 225.)])

for fighter_first in (False, True):
    park()
    terrain_hits.clear()
    b.x, b.y = (208 if fighter_first else 230), 625
    t = target("window", 1, 220 if fighter_first else 202)
    app.terrain.bounds = [(t["cx"], t["cy"], 1., 15., t)]
    round_at()
    app.projectiles(1 / 15)
    check("first collision across fighter/terrain (%s)" % fighter_first,
          (b.hp < 100 and not terrain_hits) if fighter_first
          else (b.hp == 100 and terrain_hits == [(1, 201.)]))
app.hit_target = real_target_hit

# Reflection at the swept contact point keeps the round alive and assigns
# it to the pan; its return trip must hurt the original shooter.
park()
harness.fake_terrain(app)
a.x, a.y = 180, 625
b.x, b.y, b.face = 218, 625, -1
b.weapon, b.atk, b.atk_dur = "pan", .2, .5
b.set_state("attack")
shot = round_at()
shot["pierce"] = True
app.projectiles(1 / 15)
reflected = (len(app.shots) == 1 and shot["owner"] is b and shot["vx"] < 0
             and b.hp == 100 and abs(shot["x"] - (b.x - 18 * b.sc)) < .001)
app.projectiles(1 / 15)
check("swept pan reflection returns damage to shooter", reflected and a.hp < 100)

# The higher floor on the far side of a seam cannot consume a shot before
# a victim on the source display, or trigger an explosion at the muzzle.
park()
app.mons = [((0, 0, 1000, 800), (0, 0, 1000, 760)),
            ((1000, 0, 2000, 1200), (1000, 0, 2000, 1160))]
a.x, a.y, b.x, b.y = 1500, 925, 1300, 925
shot = round_at(1500, 900)
shot["vx"] = -10000.
app.projectiles(.1)
check("nearer victim wins before higher-floor seam", b.hp < 100
      and 1300 < shot["x"] < 1320)
b.x = 1800
shot = round_at(1500, 900)
shot["vx"] = -10000.
app.projectiles(.1)
check("higher-floor collision occurs at seam", not app.shots and shot["x"] == 1000)

# A fast falling shot must hit the source monitor's floor even when its
# uncorrected endpoint crosses into a second monitor stacked underneath.
park()
app.mons = [((0, 0, 1600, 1000), (0, 0, 1600, 960)),
            ((0, 1000, 1600, 2000), (0, 1000, 1600, 1960))]
shot = round_at(900, 950)
shot["vx"], shot["vy"] = 0., 1200.
app.projectiles(.1)
check("projectile lands on source stacked monitor", not app.shots
      and shot["y"] == 960)

print("\n" + ("FAIL: " + "; ".join(bad) if bad else "PASS"))
harness.finish(gm, app, bad)
