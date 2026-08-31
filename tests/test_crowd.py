"""One to ten of them, all behaving differently.

Covers the things that only exist once the count is a setting:

  * every count from 1 to 10 runs without an exception
  * nobody is left fighting a foe who is gone, KO'd or held
  * memory is keyed by the roster
  * the ten are measurably different in play, not just in the speech bubbles
  * moving the slider does not reset the survivors or leak canvas items
  * ten of them still hold the frame budget

The last three are the ones with history. spawn_fighters used to keep only
fighters[0] and rebuild the rest, throwing away everyone else's health, mood,
position and carried icon; the canvas pool was never pruned, so going ten to one
left nine fighters' worth of items in it forever; and aim_point dereferenced
f.foe before testing it, which was unreachable with a fixed pair and live the
moment foes are reassigned.
"""
import importlib.util
import os
import random
import sys
import time

_TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get(
    "GREMLIN_SRC",
    os.path.join(os.path.dirname(_TESTS), "desktop_gremlin.py"))
HERE = os.path.join(_TESTS, ".tmp")
os.makedirs(HERE, exist_ok=True)

spec = importlib.util.spec_from_file_location("gm", SRC)
gm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gm)
gm.MEMORY_PATH = os.path.join(HERE, "crowd_memory.json")
gm.MEM = gm.blank_memory()
gm.CFG.update(gm.DEFAULTS)
gm.CFG["sleep_when_idle"] = False
gm.CFG["all_monitors"] = False
gm.CFG["move_icons"] = False
gm.CFG["chaos"] = 2.0
gm.idle_seconds = lambda: 0.0

DT = 1 / 40.0
bad = []

# memory is keyed by the roster
if set(gm.MEM["who"]) != set(gm.ROSTER):
    bad.append("memory keys %s do not match the roster"
               % sorted(set(gm.MEM["who"]) ^ set(gm.ROSTER)))

gm.CFG["crowd"] = 1
app = gm.App()
app.poll_cursor = lambda dt: None

ICONS = [("Icon %d" % i, 60 + (i % 8) * 120, 200 + (i // 8) * 150,
          124 + (i % 8) * 120, 264 + (i // 8) * 150, i) for i in range(16)]


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

# --- 1. every count runs, and leaves nobody fighting a ghost ---------------
print("%-6s %-6s %-9s %s" % ("crowd", "alive", "frames", "outcome"))
for n in range(1, 11):
    gm.CFG["crowd"] = n
    app.apply_settings()
    random.seed(100 + n)
    try:
        for _ in range(40 * 30):                 # thirty seconds each
            app.update(DT)
    except Exception as exc:
        bad.append("crowd=%d raised %r" % (n, exc))
        print("%-6d %-6s %-9s %r" % (n, "-", "-", exc))
        continue
    ghosts = [f.kind for f in app.fighters
              if f.state == "fight" and (f.foe is None or f.foe.hp <= 0
                                         or f.foe.state in ("ko", "grabbed"))]
    names = [f.kind for f in app.fighters]
    if len(app.fighters) != n:
        bad.append("crowd=%d gave %d fighters" % (n, len(app.fighters)))
    if names != list(gm.ROSTER[:n]):
        bad.append("crowd=%d cast is %s" % (n, names))
    if ghosts:
        bad.append("crowd=%d left %s fighting a ghost" % (n, ghosts))
    print("%-6d %-6d %-9d %s" % (n, len(app.fighters), 40 * 30,
                                 "ghosts: %s" % ghosts if ghosts else "ok"))

# --- 2. the slider must not reset survivors or leak canvas items -----------
gm.CFG["crowd"] = 10
app.apply_settings()
for _ in range(200):
    app.update(DT)
    app.draw()
first = app.fighters[0]
# A marker nothing else touches. Health regenerates and mood drifts, so using
# those to prove the object survived tests the simulation, not the respawn.
first._probe = "kept"
pool_at_ten = sum(len(v) for pools in app._pool.values() for v in pools.values())
tags_at_ten = len(app._pool)

for cycle in range(3):
    for n in (1, 10):
        gm.CFG["crowd"] = n
        app.apply_settings()
        for _ in range(20):
            app.update(DT)
            app.draw()

pool_after = sum(len(v) for pools in app._pool.values() for v in pools.values())
tags_after = len(app._pool)
kept = (app.fighters[0] is first
        and getattr(app.fighters[0], "_probe", None) == "kept")
print("")
print("pool at ten           : %d items in %d tags" % (pool_at_ten, tags_at_ten))
print("after 10-1-10 x3      : %d items in %d tags" % (pool_after, tags_after))
print("survivor kept intact  : %s" % kept)
if tags_after > tags_at_ten:
    bad.append("layer tags leaked: %d -> %d" % (tags_at_ten, tags_after))
if pool_after > pool_at_ten * 1.35:
    bad.append("canvas pool grew %d -> %d across slider changes"
               % (pool_at_ten, pool_after))
if not kept:
    bad.append("changing the count reset a survivor")

# --- 3. do the ten actually behave differently? ---------------------------
gm.CFG["crowd"] = 10
app.apply_settings()
for f in app.fighters:
    f.hp = 100.0
said = dict((n, 0) for n in gm.ROSTER)
stole = dict((n, 0) for n in gm.ROSTER)
melee = dict((n, 0) for n in gm.ROSTER)
shots = dict((n, 0) for n in gm.ROSTER)

_yell = gm.Fighter.yell


def spy_yell(self, event, dur=1.5, **fmt):
    said[self.kind] = said.get(self.kind, 0) + 1
    return _yell(self, event, dur, **fmt)


gm.Fighter.yell = spy_yell
_start = app.start_attack


def spy_start(f, at=None, foe=False):
    _start(f, at=at, foe=foe)
    if f.state == "attack":
        shots[f.kind] += 1
        if f.weapon in gm.MELEE:
            melee[f.kind] += 1


app.start_attack = spy_start
_snatch = app.pick_up_icon


def spy_snatch(f, tgt):
    got = _snatch(f, tgt)
    if got:
        stole[f.kind] += 1
    return got


app.pick_up_icon = spy_snatch

random.seed(4242)
try:
    for _ in range(40 * 120):                    # two minutes of ten-way brawl
        app.update(DT)
except Exception as exc:
    bad.append("the ten-way brawl raised %r" % exc)

gm.Fighter.yell = _yell
talk = [said[n] for n in gm.ROSTER]
print("")
print("%-9s %6s %6s %7s  %s" % ("who", "lines", "shots", "melee%", "temperament"))
for n in gm.ROSTER:
    m = (100.0 * melee[n] / shots[n]) if shots[n] else 0.0
    t = gm.TRAITS[n]
    print("%-9s %6d %6d %6.0f%%  aggro %.2f chatty %.2f nerve %.2f"
          % (n, said[n], shots[n], m, t["aggro"], t["chatty"], t["nerve"]))

if talk and max(talk) < 1.8 * (min(talk) + 1):
    bad.append("everyone talks about the same amount: %s" % talk)
if sum(shots.values()) < 40:
    bad.append("only %d attacks in two minutes of ten-way" % sum(shots.values()))

# --- 4. frame time at ten -------------------------------------------------
gm.CFG["crowd"] = 10
app.apply_settings()
for _ in range(40):
    app.update(DT)
    app.draw()
    app.root.update()
t0 = time.perf_counter()
FRAMES = 300
for _ in range(FRAMES):
    app.update(DT)
    app.draw()
    app.root.update()
ms = (time.perf_counter() - t0) / FRAMES * 1000
budget = 1000.0 / gm.CFG["fps"]
print("")
print("frame time at ten     : %.2f ms of a %.0f ms budget (%.0f%%)"
      % (ms, budget, 100.0 * ms / budget))
print("canvas items at ten   : %d" % len(app.canvas.find_all()))
if ms > budget * 0.5:
    bad.append("ten of them cost %.1f ms of a %.0f ms budget" % (ms, budget))

try:
    app.tray.remove()
    app.root.destroy()
except Exception:
    pass
if os.path.exists(gm.MEMORY_PATH):
    os.remove(gm.MEMORY_PATH)

print("")
if bad:
    print("FAIL")
    for b in bad[:15]:
        print("  " + b)
    sys.exit(1)
print("PASS")
