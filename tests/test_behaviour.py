"""Drive the new behaviour for real: greeting, context remarks, revenge after a
losing streak, ganging up, and the grudge against one icon.

None of these fire reliably in a short random run, so each is forced and the
spoken events are recorded.
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
gm.MEMORY_PATH = os.path.join(HERE, "rt_memory.json")   # never the real one
gm.MEM = gm.blank_memory()

gm.CFG.update(gm.DEFAULTS)
gm.CFG["crowd"] = 2
gm.CFG["move_icons"] = False
gm.CFG["sleep_when_idle"] = False
gm.CFG["all_monitors"] = False
gm.BACKUP_OK = False
gm.idle_seconds = lambda: 0.0
gm.foreground_window = lambda: ("* notes.txt - Notepad", 4242)

ICONS = [("Steam", 40, 60, 144, 124, 0), ("Recycle Bin", 200, 60, 304, 124, 1),
         ("Firefox", 360, 60, 464, 124, 2)]
WINS = [("* notes.txt - Notepad", 300, 400, 1100, 900, 4242)]

app = gm.App()
app.poll_cursor = lambda dt: None


def fake_refresh(own=0, want_icons=True):
    t = app.terrain
    t.icons, t.windows, t.moved = list(ICONS), list(WINS), {}
    t.win_pos = {4242: (300, 400)}
    t.icons_ok = True
    tg, pl = [], []
    for name, l, tp, r, b, idx in t.icons:
        tg.append({"cx": (l + r) / 2, "cy": (tp + b) / 2, "top": tp, "name": name,
                   "w": r - l, "h": b - tp, "kind": "icon", "key": idx})
        pl.append((l, r, tp, "icon", idx))
    for title, l, tp, r, b, h in t.windows:
        tg.append({"cx": (l + r) / 2, "cy": tp + 16, "top": tp, "name": title,
                   "w": r - l, "h": 32, "kind": "window", "key": h})
        pl.append((l + 6, r - 6, tp, "window", h))
    t._targets, t.platforms = tg, pl
    t.bounds = [(x["cx"], x["cy"], x["w"] / 2, max(x["h"], 26) / 2, x) for x in tg]


app.terrain.refresh = fake_refresh
fake_refresh()

heard = []
_real_yell = gm.Fighter.yell


def spy(self, event, dur=1.5, **fmt):
    heard.append((self.kind, event))
    return _real_yell(self, event, dur, **fmt)


gm.Fighter.yell = spy
g, r2 = app.fighters
bad = []


def ran(tag):
    return sorted({e for k, e in heard if e.startswith(tag)})


# --- 1. the greeting on a first ever run ------------------------------------
heard.clear()
random.seed(3)
for _ in range(260):                       # past the 5s greeting mark
    app.update(1 / 40.0)
print("greeting              : %s" % [e for k, e in heard if e in gm.GREET_EVENTS])
if not any(e in gm.GREET_EVENTS for k, e in heard):
    bad.append("no greeting inside the first 6.5s")

# --- 2. a context remark ----------------------------------------------------
heard.clear()
app.watch.quiet_until = 0.0
app.watch.next_check = 0.0
app.watch.since = app.time - 1200          # been in one window a long while
for _ in range(320):                       # pick() is throttled to 1 Hz
    app.update(1 / 40.0)
print("context remark        : %s" % ran("ctx_"))
if not ran("ctx_"):
    bad.append("no context remark after 20 minutes in one window")

# --- 3. it must then go quiet -----------------------------------------------
heard.clear()
for _ in range(400):                       # 10s later: still inside the cooldown
    app.update(1 / 40.0)
if ran("ctx_"):
    bad.append("context remarks are not respecting the cooldown: %s" % ran("ctx_"))
print("cooldown holds        : yes (nothing in the next 10s)")

# --- 4. revenge after losing repeatedly -------------------------------------
heard.clear()
gm.MEM["who"][gm.ROSTER[0]]["streak"] = -4
random.seed(11)
for _ in range(400):
    g.foe, r2.foe = r2, g
    g.hp = r2.hp = 100.0
    r2.state = "idle"
    g.stun = 0.0
    app.decide(g)
print("revenge / fight       : %s" % sorted({e for k, e in heard
                                             if e in ("revenge", "fight")}))
if "revenge" not in [e for k, e in heard]:
    bad.append("a 4-loss streak never produced a revenge line")
if "fight" in [e for k, e in heard]:
    bad.append("still using the plain fight line while on a losing streak")

# --- 5. ganging up ----------------------------------------------------------
heard.clear()
gm.MEM["who"][gm.ROSTER[0]]["streak"] = 0
random.seed(5)
for _ in range(600):
    g.foe, r2.foe = r2, g
    g.hp = r2.hp = 100.0
    r2.state = "hunt"
    r2.target = app.terrain.targets()[0]
    g.stun = 0.0
    app.decide(g)
print("gang up               : %d times" % sum(1 for k, e in heard if e == "gangup"))
if not any(e == "gangup" for k, e in heard):
    bad.append("never ganged up on the other one's target")

# --- 6. a grudge against one icon -------------------------------------------
for _ in range(8):
    gm.bump_icon("Steam")
print("favourite icon        : %r" % gm.favourite_icon())
heard.clear()
random.seed(9)
for _ in range(900):
    r2.state = "idle"
    r2.target = None
    g.foe = r2
    g.stun = 0.0
    g.anger = 0.0
    g.mood = "bored"
    g.said = -99
    app.decide(g)
print("named its old enemy   : %d times" % sum(1 for k, e in heard if e == "fav_icon"))
if not any(e == "fav_icon" for k, e in heard):
    bad.append("never used the fav_icon line despite a clear favourite")

# --- 7. and none of that broke the frame loop -------------------------------
random.seed(2)
for _ in range(600):
    app.update(1 / 40.0)
    app.draw()
    app.root.update()
print("600 more frames drawn : no exceptions")

try:
    app.tray.remove()
    app.root.destroy()
except Exception:
    pass
if os.path.exists(gm.MEMORY_PATH):
    os.remove(gm.MEMORY_PATH)
print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
sys.exit(1 if bad else 0)
