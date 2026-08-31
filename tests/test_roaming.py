"""Do they get stuck near the top row of icons, and can they leave the screen
and come back?

The top row of desktop icons on this machine starts at y=5. Being stuck means
barely moving while in a state that is *trying* to get somewhere -- standing
still mid-duel is not stuck, so attack/fight/idle/taunt/sleep do not count.
"""
import importlib.util
import os
import random
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
gm.MEMORY_PATH = os.path.join(HERE, "stuck_memory.json")
gm.MEM = gm.blank_memory()
gm.CFG.update(gm.DEFAULTS)
gm.CFG["rival"] = True
gm.CFG["sleep_when_idle"] = False
gm.CFG["all_monitors"] = False
gm.CFG["move_icons"] = False
gm.idle_seconds = lambda: 0.0
gm.foreground_window = lambda: ("Notepad", 4242)

ICONS = []
i = 0
for col in range(4):
    for row in range(6):
        ICONS.append(("Icon %d" % i, col * 95, 5 + row * 122,
                      col * 95 + 94, 69 + row * 122, i))
        i += 1

app = gm.App()
app.poll_cursor = lambda dt: None


def refresh(own=0, want_icons=True):
    t = app.terrain
    t.icons, t.windows, t.moved, t.win_pos, t.icons_ok = list(ICONS), [], {}, {}, True
    tg, pl = [], []
    for name, l, tp, r, b, idx in t.icons:
        tg.append({"cx": (l + r) / 2, "cy": (tp + b) / 2, "top": tp, "name": name,
                   "w": r - l, "h": b - tp, "kind": "icon", "key": idx})
        pl.append((l, r, tp, "icon", idx))
    t._targets, t.platforms = tg, pl
    t.bounds = [(x["cx"], x["cy"], x["w"] / 2, max(x["h"], 26) / 2, x) for x in tg]


app.terrain.refresh = refresh
refresh()

random.seed(20260901)
app.fighters[0].x, app.fighters[0].y = 100.0, 40.0
app.fighters[0].set_state("fall")

GOING = ("walk", "fall", "jump", "ledge", "wallslide", "hunt", "carry", "zip")
DT = 1 / 40.0
FRAMES = 40 * 180                      # three minutes
hist = [[] for _ in app.fighters]
states = [{} for _ in app.fighters]
offscreen = [[] for _ in app.fighters]
for n in range(FRAMES):
    app.update(DT)
    for i, f in enumerate(app.fighters):
        hist[i].append((f.x, f.y, f.state))
        states[i][f.state] = states[i].get(f.state, 0) + 1
        out = not (app.ox <= f.x <= app.ox + app.W) or f.y < app.oy
        offscreen[i].append(out)

WIN = 40 * 8
bad = []
for i, h in enumerate(hist):
    for s in range(0, len(h) - WIN, 40):
        seg = h[s:s + WIN]
        if not all(p[2] in GOING for p in seg):
            continue                   # standing still on purpose is fine
        xs = [p[0] for p in seg]
        ys = [p[1] for p in seg]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        if span < 60:
            bad.append((i, s / 40.0, span, seg[0][2], sum(xs) / len(seg),
                        sum(ys) / len(seg)))

for i, f in enumerate(app.fighters):
    top = sum(1 for p in hist[i] if p[1] < app.oy + 200)
    trips, run = 0, False
    longest = cur = 0
    for out in offscreen[i]:
        if out:
            cur += 1
            longest = max(longest, cur)
            if not run:
                trips += 1
                run = True
        else:
            cur = 0
            run = False
    top3 = sorted(states[i].items(), key=lambda kv: -kv[1])[:3]
    print("fighter %d (%-7s): %2.0f%% near the top, %d trips off screen, "
          "longest %.1fs away" % (i, f.kind, 100.0 * top / FRAMES, trips,
                                  longest / 40.0))
    print("    states: %s" % ", ".join("%s %.0fs" % (k, v / 40.0) for k, v in top3))

came_back = all(not offscreen[i][-1] for i in range(len(app.fighters)))
trips_total = sum(1 for i in range(len(app.fighters))
                  for j in range(1, FRAMES)
                  if offscreen[i][j] and not offscreen[i][j - 1])
longest_all = 0
for i in range(len(app.fighters)):
    cur = 0
    for out in offscreen[i]:
        cur = cur + 1 if out else 0
        longest_all = max(longest_all, cur)

# A wrap is the only way x can move most of a screen width in one frame.
wraps = 0
for i in range(len(app.fighters)):
    for j in range(1, FRAMES):
        if abs(hist[i][j][0] - hist[i][j - 1][0]) > app.W * 0.5:
            wraps += 1

print()
print("stuck windows (locomotion states, <60px in 8s): %d" % len(bad))
for b in bad[:3]:
    print("    fighter %d at t=%.0fs in %s, %.0f px, around (%.0f, %.0f)"
          % (b[0], b[1], b[3], b[2], b[4], b[5]))
print("went off screen        : %d times over 3 minutes" % trips_total)
print("wrapped to the far side: %d times" % wraps)
print("longest spell away     : %.1fs (wraps at %.0fpx out or %.1fs out)"
      % (longest_all / 40.0, gm.WRAP, gm.OUT_MAX))
print("all back on screen now : %s" % came_back)
if wraps == 0:
    bad.append("never wrapped to the other side in three minutes")
if longest_all / 40.0 > 3:
    bad.append("spent %.1fs off screen in one go" % (longest_all / 40.0))

ok = not bad and trips_total > 0
print()
print("VERDICT: %s" % ("PASS - roams freely, and comes back on the far side"
                       if ok else "FAIL"))
for b in bad:
    print("   %s" % (b,))
try:
    app.tray.remove()
    app.root.destroy()
except Exception:
    pass
if os.path.exists(gm.MEMORY_PATH):
    os.remove(gm.MEMORY_PATH)
sys.exit(0 if ok else 1)
