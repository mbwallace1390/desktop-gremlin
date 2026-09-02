"""The bend flip touches every pose, not just walking. Check none of them
produce a broken limb: no NaN, no joint flung away from the body, and the
knee still leads in every pose where he is upright on his feet.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

gm = harness.load("poses", crowd=1)
app = harness.build(gm)
f = app.fighters[0]
bad = []

STATES = ["idle", "walk", "hunt", "fight", "carry", "jump", "fall", "zip",
          "hookfire", "ledge", "wallslide", "grabbed", "thrown", "taunt",
          "cursor", "sleep", "ko", "attack",
          "blink", "float", "pogo", "skate", "surf", "ride", "cannonwind",
          "jet", "climb"]
UPRIGHT = ("idle", "walk", "hunt", "fight", "carry", "taunt", "cursor", "attack")


def draw(state, phase, weapon="sword", mood="bored", face=1):
    f.state, f.st, f.face, f.mood = state, 0.5, face, mood
    f.walk = phase
    f.vx, f.vy = 240.0 * face, 0.0
    f.x, f.y = 900.0, 800.0
    f.squash = f.tumble = f.stun = 0.0
    f.blink = 1.0
    f.weapon, f.atk_dur, f.atk = weapon, gm.ATKDUR[weapon], 0.4 * gm.ATKDUR[weapon]
    f.aim = 0.6
    f.hook = {"x": f.x, "y": f.y - 60, "tx": f.x + 200, "ty": 400.0,
              "t": 0.2, "dur": 0.4}
    f.zip = {"ax": f.x + 200, "ay": 400.0, "t": 0.2, "sx": f.x, "sy": f.y,
             "dur": 0.6}
    app._frame_begin()
    app.sx = app.sy = 0.0
    app.draw_fighter(f, 0)
    app._frame_end()
    tb, ta = app._ftag[0][0], app._ftag[0][3]
    bx, by = f.x - app.ox, f.y - app.oy
    out = []
    for item in app._pool[tb]["line"][:3] + app._pool[ta]["line"][:1]:
        co = app.canvas.coords(item)
        out.append([((co[i] - bx) * face, co[i + 1] - by) for i in range(0, 6, 2)])
    return out


checked = 0
for st in STATES:
    for w in (gm.WEAPONS if st == "attack" else ["sword"]):
        for face in (1, -1):
            for i in range(8):
                ph = i * math.pi / 4
                for limb in draw(st, ph, w, face=face):
                    checked += 1
                    for (x, y) in limb:
                        if not (math.isfinite(x) and math.isfinite(y)):
                            bad.append("%s/%s: non-finite joint" % (st, w))
                        elif abs(x) > 220 or abs(y) > 220:
                            bad.append("%s/%s: joint flung to (%.0f, %.0f)"
                                       % (st, w, x, y))

# knees must still lead wherever he is upright on his feet
wrong = []
for st in UPRIGHT:
    for i in range(12):
        ph = i * math.pi / 6
        legs = draw(st, ph)[:2]
        for pts in legs:
            (ax, ay), (kx, ky), (bx, by) = pts
            if abs(by - ay) < 1e-6:
                continue
            t = (ky - ay) / (by - ay)
            if not (0.0 <= t <= 1.0):
                continue
            if kx - (ax + (bx - ax) * t) < -0.5:
                wrong.append(st)

print("limb samples checked  : %d across %d states, both facings" % (checked, len(STATES)))
print("non-finite or flung   : %d" % len(bad))
print("upright poses with a backward knee: %s"
      % (sorted(set(wrong)) or "none"))

# The body must be one colour for everyone in every mood, and the halo must be
# the thing that moves. Getting that backwards is the whole point of the
# redesign and nothing else in the suite would notice. Its own list, because
# the geometry summary above prints len(bad).
halo_bad = []
halos, bodies = set(), set()
for kind in gm.ROSTER:
    for mood in gm.MOODS:
        f.become(kind)
        # draw() takes the mood as an argument and would otherwise overwrite it
        draw("idle", 0.0, mood=mood)
        tb, th = app._ftag[0][0], app._ftag[0][1]
        bodies.add(app.canvas.itemcget(app._pool[tb]["line"][0], "fill"))
        head = app._pool[th]["oval"][0]
        halos.add((kind, mood, app.canvas.itemcget(head, "outline")))
        if app.canvas.itemcget(head, "fill") != gm.BODY:
            halo_bad.append("%s/%s head is not the body colour" % (kind, mood))
        if float(app.canvas.itemcget(head, "width")) < 3:
            halo_bad.append("%s/%s halo is only %s thick"
                            % (kind, mood, app.canvas.itemcget(head, "width")))
f.become(gm.ROSTER[0])
per_mood = len({h[2] for h in halos if h[1] == "furious"})
per_kind = len({h[2] for h in halos if h[0] == gm.ROSTER[0]})
if len(bodies) != 1:
    halo_bad.append("the body is not one colour: %s" % sorted(bodies))
if per_mood < len(gm.ROSTER):
    halo_bad.append("only %d of %d characters have their own furious halo"
                    % (per_mood, len(gm.ROSTER)))
if per_kind < len(gm.MOODS):
    halo_bad.append("only %d of %d moods change the halo"
                    % (per_kind, len(gm.MOODS)))
print("body colour           : %s for all %d, in every mood"
      % (sorted(bodies)[0], len(gm.ROSTER)))
print("halo                  : %d moods x %d characters, all distinct"
      % (per_kind, per_mood))
bad.extend(halo_bad)
if wrong:
    bad.append("backward knee in: %s" % sorted(set(wrong)))
for b in bad[:5]:
    print("   " + b)

print("\n" + ("FAIL" if bad else "PASS"))
harness.finish(gm, app, bad)
