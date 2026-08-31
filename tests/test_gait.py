"""Which way do the legs actually cycle?

Reads the rendered leg lines off the canvas rather than re-deriving the pose
maths, so it tests what is drawn. A correct walk: the foot that is planted
travels BACKWARD relative to the body (that is what pushes it along), and the
lifted foot swings forward. The reverse reads as running backwards.
"""
import importlib.util
import os
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get(
    "GREMLIN_SRC",
    os.path.join(os.path.dirname(_TESTS), "desktop_gremlin.py"))
HERE = os.path.join(_TESTS, ".tmp")          # scratch; never the repo itself
os.makedirs(HERE, exist_ok=True)

spec = importlib.util.spec_from_file_location("gm", SRC)
gm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gm)
gm.MEMORY_PATH = os.path.join(HERE, "gait_memory.json")
gm.MEM = gm.blank_memory()
gm.CFG.update(gm.DEFAULTS)
gm.CFG["crowd"] = 1
gm.CFG["sleep_when_idle"] = False
gm.CFG["all_monitors"] = False
gm.idle_seconds = lambda: 0.0

app = gm.App()
app.poll_cursor = lambda dt: None
f = app.fighters[0]


def feet_at(phase, state="walk", face=1):
    """Both feet in body-local pixels: (x, y) with +x = the way he faces."""
    f.state, f.st, f.face = state, 1.0, face
    f.walk = phase
    f.vx = 160.0 * face
    f.x, f.y = 900.0, 800.0
    f.squash = f.tumble = 0.0
    f.on_ground = True
    app._frame_begin()
    app.sx = app.sy = 0.0
    app.layer(app._ftag[0][0])
    app.draw_fighter(f, 0)
    app._frame_end()
    legs = app._pool[app._ftag[0][0]]["line"][:2]
    out = []
    for it in legs:
        co = app.canvas.coords(it)
        fx, fy = co[-2], co[-1]                     # the foot end of the leg
        bx = f.x - app.ox
        by = f.y - app.oy
        out.append(((fx - bx) * face, fy - by))     # local, flipped to facing
    return out


SAMPLES = 48
planted_moves, lifted_moves = [], []
prev = feet_at(0.0)
for i in range(1, SAMPLES + 1):
    ph = i * (2 * gm.math.pi) / SAMPLES
    now = feet_at(ph)
    for side in (0, 1):
        dx = now[side][0] - prev[side][0]
        ground = now[side][1] > -1.0 and prev[side][1] > -1.0
        if abs(dx) < 0.05:
            continue
        (planted_moves if ground else lifted_moves).append(dx)
    prev = now

planted_fwd = sum(1 for d in planted_moves if d > 0)
planted_back = sum(1 for d in planted_moves if d < 0)
lifted_fwd = sum(1 for d in lifted_moves if d > 0)
lifted_back = sum(1 for d in lifted_moves if d < 0)

print("planted foot steps    : %d forward, %d backward" % (planted_fwd, planted_back))
print("lifted  foot steps    : %d forward, %d backward" % (lifted_fwd, lifted_back))
print()
if planted_back > planted_fwd and lifted_fwd > lifted_back:
    print("VERDICT: correct - planted foot pushes back, lifted foot swings forward")
    ok = True
else:
    print("VERDICT: BACKWARDS - the planted foot is sliding forwards")
    ok = False

try:
    app.tray.remove()
    app.root.destroy()
except Exception:
    pass
if os.path.exists(gm.MEMORY_PATH):
    os.remove(gm.MEMORY_PATH)
sys.exit(0 if ok else 1)
