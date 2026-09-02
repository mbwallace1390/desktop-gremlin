"""Which way do the joints bow, at every point in the stride?

Reads the rendered limb polylines (hip, knee, foot / shoulder, elbow, hand) and
compares the middle joint's x to the straight chord between the two ends, at
the same height. Positive means the joint sits forward of the chord.

Human reference, facing +x:
  knee  leads  (+) -- the shin trails behind it
  elbow trails (-) -- the forearm swings forward of it
A knee that bows backward is a bird's leg and reads as running the other way.
An average hides a sign flip mid-stride, so this reports every sample.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

gm = harness.load("joints", crowd=1)
app = harness.build(gm)
f = app.fighters[0]


def limbs(phase, face=1, state="walk"):
    f.state, f.st, f.face = state, 1.0, face
    f.walk = phase
    f.vx = 300.0 * face
    f.x, f.y = 900.0, 800.0
    f.squash = f.tumble = 0.0
    f.on_ground = True
    tb, ta = app._ftag[0][0], app._ftag[0][3]
    app._frame_begin()
    app.sx = app.sy = 0.0
    app.draw_fighter(f, 0)
    app._frame_end()
    bx, by = f.x - app.ox, f.y - app.oy
    raw = {"leg L": app._pool[tb]["line"][0],
           "leg R": app._pool[tb]["line"][1],
           "arm L": app._pool[tb]["line"][2],
           "arm R": app._pool[ta]["line"][0]}
    out = {}
    for k, item in raw.items():
        co = app.canvas.coords(item)
        out[k] = [((co[i] - bx) * face, co[i + 1] - by) for i in range(0, 6, 2)]
    return out


def bow(pts):
    """Joint x minus the chord's x at the joint's height. + is forward."""
    (ax, ay), (kx, ky), (bx, by) = pts
    if abs(by - ay) < 1e-6:
        return None                      # limb is horizontal; undefined
    t = (ky - ay) / (by - ay)
    if not (0.0 <= t <= 1.0):
        return None
    return kx - (ax + (bx - ax) * t)


SAMPLES = 24
rows = {}
for i in range(SAMPLES):
    ph = i * 2 * math.pi / SAMPLES
    for name, pts in limbs(ph).items():
        v = bow(pts)
        if v is not None:
            rows.setdefault(name, []).append(v)

print("joint bow across the stride (+ forward of the chord, - behind it):")
ok = True
for name in ("leg L", "leg R", "arm L", "arm R"):
    v = rows.get(name, [])
    if not v:
        print("  %-6s no usable samples" % name)
        continue
    fwd = sum(1 for x in v if x > 0.5)
    back = sum(1 for x in v if x < -0.5)
    want_fwd = name.startswith("leg")
    good = (fwd == 0) if not want_fwd else (back == 0)
    print("  %-6s min %+6.1f  max %+6.1f   %2d samples forward, %2d backward"
          "   want %-8s %s"
          % (name, min(v), max(v), fwd, back,
             "forward" if want_fwd else "backward",
             "ok" if good else "WRONG WAY"))
    if not good:
        ok = False

print()
print("VERDICT: %s" % ("knees lead, elbows trail - correct" if ok
                       else "a joint bows the wrong way somewhere in the stride"))
harness.finish(gm, app, not ok)
