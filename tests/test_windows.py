"""Hanging, sitting, knocking on your window.

A window is a climbing frame: sit on the title bar, hang from the bottom edge,
cling to a side, bang on it. Every one of those is a state that skips physics
and pins him to a rectangle that can move or vanish under him, and the cursor
has to be able to shoo him off it. So:

  1. left to themselves, with the window you are using in front of them, they
     get there on their own -- and mostly to that window
  2. every play is drawn on the window: read off the canvas, not the maths
  3. the window is dragged: they ride along; it is closed: they let go
  4. a cursor coming at one scares him off; a cursor resting on one does not
  5. nothing nudges a window unless the setting says so, and even then not
     the one you are typing in, not off its monitor; the tray puts it back
  6. a grab, sleep and the crowd slider all end a play with nothing dangling

Runs against fake windows; nothing real is touched.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

gm = harness.load("windows", crowd=5, chaos=2.0, react_to_windows=True)
gm.foreground_window = lambda: ("Notepad", 4242)
app = harness.build(gm)
DT = 1 / 40.0
bad = []

OX, OY, W = app.ox, app.oy, app.W
S = app.fighters[0].sc
GY = app.ground_at(OX + W / 2)
# Notepad floats: a title bar to sit on, a bottom edge to hang from within a
# jump of the floor. Other stands on the floor: a side to cling to and knock on.
NOTE = ["Notepad", OX + int(W * .30), int(GY - 560), OX + int(W * .75),
        int(GY - 150)]
OTHER = ["Other", OX + int(W * .04), int(GY - 420), OX + int(W * .27), int(GY - 10)]
WINS = {4242: list(NOTE), 4343: list(OTHER)}
ICONS = [("Icon %d" % i, OX + int(W * .82) + i * 70, int(GY - 64),
          OX + int(W * .82) + i * 70 + 64, int(GY), i) for i in range(2)]


def windows():
    return [(t, l, tp, r, b, h) for h, (t, l, tp, r, b) in WINS.items()]


refresh = harness.fake_terrain(app, ICONS, windows)


# --- 1. they get there on their own -----------------------------------------
random.seed(2026)
visits = {}                     # (kind, hwnd) -> entries
prev = {f: None for f in app.fighters}
for _ in range(40 * 90):
    app.update(DT)
    for f in app.fighters:
        now = (f.play["kind"], f.play["hwnd"]) if f.state in gm.PLAY_STATES else None
        if now and now != prev[f]:
            visits[now] = visits.get(now, 0) + 1
        prev[f] = now
kinds = {k for k, h in visits}
fg = sum(n for (k, h), n in visits.items() if h == 4242)
other = sum(n for (k, h), n in visits.items() if h == 4343)
print("plays in 90s          : %s" % ", ".join(
    "%s@%s x%d" % (k, "notepad" if h == 4242 else "other", n)
    for (k, h), n in sorted(visits.items())))
print("kinds reached         : %s   foreground %d, other %d"
      % (sorted(kinds), fg, other))
if len(kinds) < 3:
    bad.append("only %s reached on their own in 90s" % sorted(kinds))
if fg <= other:
    bad.append("the window in use got %d visits against %d" % (fg, other))


# --- 2. every play is drawn on the window -----------------------------------
def park_everyone():
    # props left over from the brawl spring and shoot the next scenario:
    # a banana peel on the floor threw a perch attempt mid-hunt
    app.traps.clear()
    app.shots.clear()
    app.parts.clear()
    app.booms.clear()
    for i, g in enumerate(app.fighters):
        g.play = None
        g.foe = g.target = None
        g.carry = None
        g.mode = "roam"
        g.hp, g.stun, g.vx, g.vy = 100.0, 0.0, 0.0, 0.0
        # a parked fighter's boredom still climbs, and at the top it resets
        # his goal and he starts a fight with the scenario
        g.boredom, g.anger, g.mood = 0.0, 0.0, "bored"
        g.x, g.y = OX + W * .9 + i * 12, GY
        g.on_ground, g.plat = True, ("floor", None)
        g.state, g.st, g.goal = "idle", 0.0, 1e9      # never decides
    refresh()


def limbs(f, fi=0):
    """World-space end points: feet L/R, hands L/R, read off the canvas."""
    app._frame_begin()
    app.sx = app.sy = 0.0
    app.draw_fighter(f, fi)
    app._frame_end()
    tb, ta = app._ftag[fi][0], app._ftag[fi][3]
    items = app._pool[tb]["line"][:3] + app._pool[ta]["line"][:1]
    out = []
    for it in items:
        co = app.canvas.coords(it)
        out.append((co[-2] + OX, co[-1] + OY))
    return out                                   # footL, footR, handL, handR


def reach(f, kind, hwnd, seconds):
    """go_play through the real entry, then let him walk, hook or climb."""
    if not app.go_play(f, kind, hwnd):
        return False
    for _ in range(int(40 * seconds)):
        app.update(DT)
        if f.state == kind and app.time - f.play["t0"] > .5:
            return True
    return False


park_everyone()
f0 = app.fighters[0]
# from here the scenarios steer: nobody improvises, and the window in use
# draws no visitors of its own
app.decide = lambda ff: None
app.window_magnet = lambda: None
random.seed(7)
for kind, hwnd, start_x in (("hang", 4242, OX + W * .5), ("perch", 4242, OX + W * .5),
                            ("cling", 4343, OX + W * .3), ("knock", 4343, OX + W * .3)):
    park_everyone()
    f0.x = start_x
    got = reach(f0, kind, hwnd, 24)
    if not got:
        bad.append("%s on %s never happened (ended in %s)" % (kind, hwnd, f0.state))
        print("%-6s reached %s" % (kind, got))
        continue
    l, t, r, b = WINS[hwnd][1:]
    fl, fr, hl, hr = limbs(f0)
    if kind == "perch":
        ok = all(t < y < t + 40 * max(1, S) for _, y in (fl, fr)) and l < f0.x < r
        detail = "feet %.0f/%.0f below the edge at %d" % (fl[1] - t, fr[1] - t, t)
    elif kind == "hang":
        ok = all(abs(y - b) <= 4 for _, y in (hl, hr)) and fl[1] > b + 30
        detail = "hands %.1f/%.1f from the bottom edge, feet %.0f below" % (
            hl[1] - b, hr[1] - b, fl[1] - b)
    elif kind == "cling":
        edge = l if f0.play["side"] == 1 else r
        ok = all(abs(x - edge) <= 4 for x, _ in (hl, hr)) and t < f0.y < b + 40
        detail = "hands %.1f/%.1f from the side edge" % (hl[0] - edge, hr[0] - edge)
    else:
        edge = l if f0.play["side"] == 1 else r
        ok = abs(hr[0] - edge) <= 14 and abs(f0.y - GY) < 1
        detail = "knuckles %.1f from the edge, phase %d" % (hr[0] - edge, f0.play["phase"])
    print("%-6s reached %s   %s" % (kind, got, detail))
    if not ok:
        bad.append("%s is not drawn on the window: %s" % (kind, detail))

# --- 3. dragged, they ride along; closed, they let go ----------------------
park_everyone()
f0, f1 = app.fighters[0], app.fighters[1]
random.seed(8)
f0.x = OX + W * .5
hung = reach(f0, "hang", 4242, 12)
if hung:
    f0.play["until"] = 1e9          # a hang lasts 5-14s; the perch trip can take longer
f1.x = OX + W * .55
sat = reach(f1, "perch", 4242, 24)
if sat:
    f1.play["until"] = 1e9
x0, x1 = f0.x, f1.x
WINS[4242][1] += 40
WINS[4242][3] += 40
app.terrain.apply(list(ICONS), windows())     # the real apply computes `moved`
app.terrain_changed()
rode = (hung and sat and abs(f0.x - x0 - 40) < .5 and abs(f1.x - x1 - 40) < .5
        and f0.state == "hang" and f1.state == "perch")
print("window dragged 40px   : hanger moved %.0f, sitter moved %.0f"
      % (f0.x - x0, f1.x - x1))
if not rode:
    bad.append("dragging the window did not carry them (%s %s)" % (f0.state, f1.state))
del WINS[4242]
app.terrain.apply(list(ICONS), windows())
app.terrain_changed()
letgo = (f0.play is None and f1.play is None
         and f0.state not in gm.PLAY_STATES and f1.state not in gm.PLAY_STATES)
print("window closed         : states %s / %s, plans %s / %s"
      % (f0.state, f1.state, f0.play, f1.play))
if not letgo:
    bad.append("closing the window left someone attached to it")
WINS[4242] = list(NOTE)
refresh()

# --- 4. the cursor: coming at him scares him; resting on him does not -------
park_everyone()
random.seed(9)
f0.x = OX + W * .5
hung = reach(f0, "hang", 4242, 12)
app.mouse = {"x": f0.x - 100, "y": f0.y - 40 * S, "t": app.time, "vx": 400.0, "vy": 0.0}
app.scare(DT)
fled = f0.state not in gm.PLAY_STATES and f0.play is None and f0.window_shy == 4242
print("cursor coming at him  : was hanging %s, now %s, shy of the window %s"
      % (hung, f0.state, f0.window_shy == 4242))
if not hung or not fled:
    bad.append("a cursor coming at him did not scare him off")
for _ in range(40 * 3):
    app.update(DT)                       # land, and let the cooldown matter
park_everyone()
f0.x = OX + W * .5
hung = reach(f0, "hang", 4242, 12)
app.mouse = {"x": f0.x - 40, "y": f0.y - 40 * S, "t": app.time, "vx": 0.0, "vy": 0.0}
app.hover = app.near_fighter(app.mouse["x"], app.mouse["y"])
app.scare(DT)
stayed = f0.state == "hang" and app.hover is f0
print("cursor resting on him : still hanging %s, grab rings on him %s"
      % (f0.state == "hang", app.hover is f0))
if not hung or not stayed:
    bad.append("a resting cursor scared him off, or lost the grab")

# --- 5. nudging a window: only with the setting, never yours right now -------
placed = []
rects = {h: tuple(v[1:]) for h, v in WINS.items()}
gm.place_window = lambda h, x, y: placed.append((h, int(x), int(y))) or True
gm.window_rect = lambda h: rects[h]
gm.window_alive = lambda h: True
app.fg = ("Notepad", 4242)
park_everyone()
gm.CFG["move_windows"] = False
off_direct = app.nudge_window(4343, 20, 0)
# a knock's shove phase, and a window finished by gunfire, both go through it
random.seed(10)
f0.x = OX + W * .3
knocked = reach(f0, "knock", 4343, 12)
f0.st = 9.05
for _ in range(4):
    app.update(DT)
tgt = [t for t in app.terrain.targets() if t["kind"] == "window" and t["key"] == 4343][0]
f0.hits = 0
for _ in range(4):
    app.hit_target(f0, tgt, tgt["cx"], tgt["cy"])
calls_off = len(placed)
print("setting off           : direct %s, after a shove and a wrecking: %d calls"
      % (off_direct, calls_off))
if off_direct or calls_off:
    bad.append("a window was moved with move_windows off")

gm.CFG["move_windows"] = True
app.nudged.clear()
app.nudged_at.clear()
app.nudges = []
on_direct = app.nudge_window(4343, 20, 0)
again = app.nudge_window(4343, 20, 0)               # inside the per-window limit
l0, t0 = rects[4343][0], rects[4343][1]
first = placed[-1] if placed else None
work = app.work_area_at(*( (rects[4343][0] + rects[4343][2]) / 2, (rects[4343][1] + rects[4343][3]) / 2 ))
print("setting on            : moved %s to %s, repeat inside 4s refused %s"
      % (on_direct, first, not again))
if not on_direct or first != (4343, l0 + 20, t0) or again:
    bad.append("nudge with the setting on went wrong: %s again=%s" % (first, again))
# clamped to the monitor: a shove far left stops at the work area
app.nudged_at.clear()
app.nudge_window(4343, -5000, 0)
nl = app.terrain.win_rect[4343][0]
print("shoved off the edge   : window left edge now %d, work area starts %d" % (nl, work[0]))
if nl < work[0]:
    bad.append("a nudge pushed the window off its monitor")
# the one you are typing in is left alone
gm.idle_seconds = lambda: 0.5
busy = app.nudge_window(4242, 20, 0)
gm.idle_seconds = lambda: 5.0
app.nudged_at.clear()
free = app.nudge_window(4242, 20, 0)
gm.idle_seconds = lambda: 0.0
print("foreground window     : while typing %s, idle %s" % (busy, free))
if busy or not free:
    bad.append("the foreground rule is wrong: typing=%s idle=%s" % (busy, free))
placed.clear()
n = app.restore_windows()
back = sorted(placed)
want = sorted((h, x, y) for h, (x, y) in
              {4343: (l0, t0), 4242: (rects[4242][0], rects[4242][1])}.items())
print("put my windows back   : %d restored, to their first positions %s" % (n, back == want))
if n != 2 or back != want or app.nudged:
    bad.append("restore_windows did not put both back: %s" % back)
gm.CFG["move_windows"] = False

# --- 6. a grab, sleep and the crowd slider end a play cleanly ----------------
park_everyone()
random.seed(11)
f0.x = OX + W * .5
hung = reach(f0, "hang", 4242, 12)
app.on_down(type("E", (), {"x": f0.x - OX, "y": f0.y - 40 * S - OY})())
grabbed = f0.state == "grabbed" and f0.play is None
print("grabbed mid-hang      : state %s, plan %s" % (f0.state, f0.play))
app.on_up(None)
for _ in range(40 * 2):
    app.update(DT)
park_everyone()
f0.x = OX + W * .5
hung2 = reach(f0, "hang", 4242, 12)
gm.CFG["sleep_when_idle"] = True
gm.idle_seconds = lambda: 1e9
app.update(DT)
slept = f0.state == "sleep" and f0.play is None
print("sleep mid-hang        : state %s, plan %s" % (f0.state, f0.play))
gm.CFG["sleep_when_idle"] = False
gm.idle_seconds = lambda: 0.0
gm.CFG["crowd"] = 1
app.apply_settings()
print("crowd slider          : %d left, no exception" % len(app.fighters))
if not (hung and grabbed):
    bad.append("a grab did not end the play cleanly")
if not (hung2 and slept):
    bad.append("sleep did not end the play cleanly")
if len(app.fighters) != 1:
    bad.append("the crowd slider broke with someone on a window")

print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
harness.finish(gm, app, bad)
