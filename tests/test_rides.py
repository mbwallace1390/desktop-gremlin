"""Every joyride starts, travels, ends, and leaves nothing dangling.

The ride states skip physics, hold references to other fighters, and one of
them drags a real desktop icon -- three different ways to strand someone
off-screen, sit him on a ghost, or scribble on the desktop with the switch
off. Runs against a fake shell; the real desktop is never touched.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

bad = []
GRID = [(300 + i * 140, 700) for i in range(6)]

# react_to_windows off, or the REAL foreground window drafts the mount into a
# hunt mid-ride
gm = harness.load("rides", crowd=3, react_to_windows=False)
gm.foreground_window = lambda: None
shell = harness.FakeShell(GRID)
app = harness.build(gm, shell)
refresh = harness.fake_terrain(app, harness.shell_icons(shell))
f = app.fighters[0]
DT = 1 / 40.0
SETTLED = ("idle", "walk", "taunt", "fall", "jump", "thrown")


def park(g):
    g.x, g.y = 900.0, app.ground_at(900)
    g.vx = g.vy = 0.0
    g.on_ground, g.hp, g.stun = True, 100.0, 0.0
    g.state, g.mode, g.foe, g.target = "idle", "roam", None, None
    g.goal = app.time + 999
    # saturated boredom fires the tantrum, and the tantrum sets goal=0,
    # which every timed ride reads as "ride over" -- keep the fixture calm
    g.boredom = g.anger = 0.0
    g.mood, g.emote_t = "bored", 0.0


# --- every ride starts, runs without an exception, and puts him back -------
print("%-10s %-8s %7s  %s" % ("ride", "started", "frames", "ends"))
for kind in ("pogo", "skate", "float", "cannon", "jet"):
    random.seed(31)
    for g in app.fighters:
        park(g)
    ok = app.start_ride(f, kind)
    frames = 0
    if ok:
        for frames in range(1, 40 * 16):
            app.update(DT)
            if f.state in SETTLED and f.on_ground:
                break
    settled = f.state in SETTLED and f.on_ground
    onscreen = app.ox - 60 < f.x < app.ox + app.W + 60 and f.y >= app.oy
    print("%-10s %-8s %7d  %s" % (kind, ok, frames,
                                  f.state if settled else "STUCK in %s" % f.state))
    if not ok:
        bad.append("%s refused to start on flat ground" % kind)
    elif not settled:
        bad.append("%s never ended: state %s after %d frames"
                   % (kind, f.state, frames))
    elif not onscreen:
        bad.append("%s ended off screen at (%.0f, %.0f)" % (kind, f.x, f.y))

# --- the float never rises out of sight ------------------------------------
# The climb is ~17px/s, so from the ground a broken ceiling looks identical
# for the whole window -- the first version of this check proved nothing.
# Start him just above the cap line instead: capped he hovers, uncapped he
# climbs straight off the top of the screen.
random.seed(32)
park(f)
app.start_ride(f, "float")
f.y = app.oy + 160
f.goal = app.time + 1e9                # no popping out of the scenario
peak = f.y
for _ in range(40 * 10):
    app.update(DT)
    peak = min(peak, f.y)
    if f.state != "float":
        break
print("\nballoon peak height   : y=%.0f (cap line %d, screen top %d)"
      % (peak, app.oy + 120, app.oy))
if peak < app.oy + 100:
    bad.append("the balloon carried him out of sight (y=%.0f)" % peak)
f.goal = app.time                       # pop it; back to normal
for _ in range(40 * 3):
    app.update(DT)
    if f.on_ground:
        break

# --- shoulders: rides whoever is nearest, detaches the moment he goes down --
random.seed(33)
for g in app.fighters:
    park(g)
app.fighters[1].x = f.x + 40
app.fighters[2].x = f.x - 300          # out of mounting range
ok = app.start_ride(f, "shoulders")
m = f.mount                             # whoever he actually picked
for _ in range(20):
    app.update(DT)
riding = f.state == "ride" and m is not None and f.mount is m \
    and m.ridden_by is f
if m is not None:
    m.hp = 0.0
    m.set_state("ko")
for _ in range(30):
    app.update(DT)
detached = f.mount is None and (m is None or m.ridden_by is None) \
    and f.state != "ride"
print("shoulder ride         : started=%s riding=%s detached on ko=%s"
      % (ok, riding, detached))
if not (ok and riding):
    bad.append("shoulder ride never got going")
if not detached:
    bad.append("rider still holds a reference to a KO'd mount")

# --- surf: tied to move_icons, and really moves the (fake) icon -------------
random.seed(34)
for g in app.fighters:
    park(g)
f.x = shell.pos[2][0] + 32.0
gm.CFG["move_icons"] = False
refused = not app.start_ride(f, "surf")
gm.CFG["move_icons"] = True
refresh()
shell.writes.clear()
started = app.start_ride(f, "surf")
idx = f.surf_idx[0] if f.surf_idx else None
x0 = shell.pos.get(idx, (0, 0))[0] if idx is not None else 0
for _ in range(40 * 12):
    app.update(DT)
    if f.state in SETTLED and f.on_ground:
        break
moved = idx is not None and abs(shell.pos[idx][0] - x0) > 60
print("icon surf             : refused w/o setting=%s, started=%s, "
      "icon moved %.0fpx, %d writes"
      % (refused, started, abs(shell.pos[idx][0] - x0) if idx is not None else 0,
         len(shell.writes)))
if not refused:
    bad.append("surf ran with move_icons off")
if not started:
    bad.append("surf refused with move_icons on and an icon underfoot")
elif not moved:
    bad.append("surf ended but the icon never travelled")
if f.surf_idx is not None:
    bad.append("surf left a claim on icon %r" % (f.surf_idx,))

# --- mid-surf, flipping the setting off bails out cleanly -------------------
random.seed(35)
for g in app.fighters:
    park(g)
f.x = shell.pos[3][0] + 32.0
app.start_ride(f, "surf")
for _ in range(10):
    app.update(DT)
shell.writes.clear()
gm.CFG["move_icons"] = False
for _ in range(40 * 3):
    app.update(DT)
print("setting off mid-surf  : state %r, %d writes after the flip"
      % (f.state, len(shell.writes)))
if f.state == "surf" or shell.writes:
    bad.append("surf kept going after move_icons was switched off")
gm.CFG["move_icons"] = True

# --- sleep collapses a ride and leaves no props ----------------------------
random.seed(36)
for g in app.fighters:
    park(g)
app.start_ride(f, "float")
app.asleep = True
gm.CFG["sleep_when_idle"] = True
gm.idle_seconds = lambda: 1e9
for _ in range(40 * 3):
    app.update(DT)
clean = (f.state == "sleep" and f.mount is None and f.surf_idx is None
         and not f.chute)
print("sleep mid-ride        : state %r, fields clean=%s" % (f.state, clean))
if not clean:
    bad.append("sleep left ride fields dangling (state %s)" % f.state)

# --- an interrupted grapple leaves no rope ---------------------------------
# The zip rope was drawn for as long as f.zip was set, and only the zip's own
# end cleared it: hit or grabbed mid-swing, he ran and jumped about with the
# line still tied to him. Read off the canvas: rope items in use after a draw.


def rope_items():
    app.draw()
    return sum(app._used.get(tag, {}).get(kind, 0)
               for tag in app._rtag[0] for kind in app._used.get(tag, {}))


gm.CFG["sleep_when_idle"] = False
gm.idle_seconds = lambda: 0.0
app.asleep = False
other = app.fighters[1]
print("")
for how in ("hit while zipping", "grabbed while zipping",
            "hit while the hook flies", "sleep while zipping"):
    random.seed(37)
    for g in app.fighters:
        park(g)
    app.fire_hook(f, 1300.0, app.ground_at(1300) - 260)
    if "hook flies" in how:
        app.update(DT)
        app.update(DT)
    else:
        for _ in range(40):
            app.update(DT)
            if f.state == "zip":
                break
    flying = f.state in ("hookfire", "zip") and rope_items() > 0
    if how.startswith("hit"):
        app.hit_fighter(other, f, 10)
    elif how.startswith("grabbed"):
        app.on_down(type("E", (), {"x": f.x - app.ox, "y": f.y - 40 * f.sc - app.oy})())
    else:
        gm.CFG["sleep_when_idle"] = True
        gm.idle_seconds = lambda: 1e9
        app.update(DT)
        gm.CFG["sleep_when_idle"] = False
        gm.idle_seconds = lambda: 0.0
        app.asleep = False
    for _ in range(20):
        app.update(DT)
    rope = rope_items()
    print("%-26s: rope while flying %s, after %d items, fields %s/%s, state %s"
          % (how, flying, rope, f.hook, f.zip, f.state))
    if not flying:
        bad.append("%s: the grapple never flew, so nothing was tested" % how)
    if rope or f.hook is not None or f.zip is not None:
        bad.append("%s: the rope stayed tied to him" % how)
    if how.startswith("grabbed"):
        app.on_up(None)

print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
harness.finish(gm, app, bad)
