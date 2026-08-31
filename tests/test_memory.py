"""Continuity has to survive a restart, a corrupt file, and a hostile one.

Runs against a memory file in the scratchpad, never the real one.
"""
import importlib.util
import io
import json
import os
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get(
    "GREMLIN_SRC",
    os.path.join(os.path.dirname(_TESTS), "desktop_gremlin.py"))
HERE = os.path.join(_TESTS, ".tmp")          # scratch; never the repo itself
os.makedirs(HERE, exist_ok=True)
STORE = os.path.join(HERE, "gremlin_memory.json")
bad = []


def fresh():
    """A brand new process's view of the world, pointed at our own file."""
    spec = importlib.util.spec_from_file_location("gm", SRC)
    gm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gm)
    gm.MEMORY_PATH = STORE
    gm.MEM = gm.load_memory()
    return gm


if os.path.exists(STORE):
    os.remove(STORE)

# --- run one: they meet you -------------------------------------------------
gm = fresh()
gm.MEM["runs"] += 1
print("run 1 greeting        : %s" % gm.greeting_event(gm.ROSTER[0]))
if gm.greeting_event(gm.ROSTER[0]) != "hello":
    bad.append("first run should be a hello")
for _ in range(9):
    gm.bump(gm.ROSTER[0], "thrown")
for _ in range(4):
    gm.bump(gm.ROSTER[1], "wins")
    gm.bump(gm.ROSTER[0], "losses")
for _ in range(5):
    gm.bump_icon("Steam")
for _ in range(2):
    gm.bump_icon("Recycle Bin")
gm.MEM["who"][gm.ROSTER[0]]["streak"] = -3
gm.save_memory()

# --- run two: they remember -------------------------------------------------
gm = fresh()
gm.MEM["runs"] += 1
m = gm.MEM["who"][gm.ROSTER[0]]
print("run 2 carried over    : runs=%d thrown=%d losses=%d streak=%d fav=%r"
      % (gm.MEM["runs"], m["thrown"], m["losses"], m["streak"],
         gm.favourite_icon()))
if gm.MEM["runs"] != 2 or m["thrown"] != 9 or m["losses"] != 4:
    bad.append("counters did not survive the restart")
if gm.favourite_icon() != "Steam":
    bad.append("favourite icon wrong: %r" % gm.favourite_icon())
ev = gm.greeting_event(gm.ROSTER[0])
print("run 2 greeting        : %s -> %r" % (ev, gm.VOICES[gm.ROSTER[0]][ev][0]))
if ev != "remember_throws":
    bad.append("9 throws should be worth mentioning, got %s" % ev)
if m["streak"] > -2:
    bad.append("losing streak lost")

# --- the icon dict must not grow without bound ------------------------------
for i in range(60):
    gm.bump_icon("Junk %d" % i)
print("icon dict capped at   : %d entries" % len(gm.MEM["icons"]))
if len(gm.MEM["icons"]) > 24:
    bad.append("icon dict unbounded: %d" % len(gm.MEM["icons"]))

# --- nothing about which apps you use may ever be written -------------------
gm.save_memory()
raw = io.open(STORE, encoding="utf-8").read()
keys = set(json.loads(raw))
print("keys on disk          : %s" % sorted(keys))
if keys - {"version", "runs", "icons", "who"}:
    bad.append("unexpected keys persisted: %s" % sorted(keys))
for word in ("YouTube", "Chrome", "title", "window", "foreground", "hour"):
    if word.lower() in raw.lower():
        bad.append("a window/app trace reached the file: %r" % word)

# --- a corrupt or hostile file must not take the app down -------------------
for junk in ('not json at all', '[]', 'null',
             '{"runs": "lots", "who": {"brawler": {"thrown": "many"}}}',
             '{"runs": -5, "icons": {"x": -3}, "who": {"sniper": {"wins": 1e309}}}',
             '{"who": {"brawler": {"thrown": 99999999999999}}}'):
    io.open(STORE, "w", encoding="utf-8").write(junk)
    try:
        g2 = fresh()
        assert isinstance(g2.MEM["runs"], int)
        assert all(isinstance(v, int) for v in g2.MEM["who"][gm.ROSTER[0]].values())
        assert g2.greeting_event(gm.ROSTER[1]) in g2.GREET_EVENTS
    except Exception as exc:
        bad.append("junk %r broke it: %r" % (junk[:30], exc))
print("survived junk files   : 6 variants")

# --- forget really forgets --------------------------------------------------
gm = fresh()
gm.bump(gm.ROSTER[0], "thrown", 50)
gm.bump_icon("Steam")
gm.save_memory()
gm.forget_memory()
after = fresh()
print("after forget          : thrown=%d icons=%d runs=%d"
      % (after.MEM["who"][gm.ROSTER[0]]["thrown"], len(after.MEM["icons"]),
         after.MEM["runs"]))
if after.MEM["who"][gm.ROSTER[0]]["thrown"] or after.MEM["icons"] or after.MEM["runs"]:
    bad.append("forget left something behind")

os.remove(STORE)
print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
sys.exit(1 if bad else 0)
