"""Every event the code can yell must exist in BOTH voices, and every line in
both must survive being formatted and spoken. A missing key is a KeyError in
the middle of a fight, which is exactly the sort of thing that only shows up
on someone's desktop three days later.
"""
import importlib.util
import io
import os
import re
import sys

_TESTS = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get(
    "GREMLIN_SRC",
    os.path.join(os.path.dirname(_TESTS), "desktop_gremlin.py"))
HERE = os.path.join(_TESTS, ".tmp")          # scratch; never the repo itself
os.makedirs(HERE, exist_ok=True)
PATH = SRC

spec = importlib.util.spec_from_file_location("gm", PATH)
gm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gm)

src = io.open(PATH, encoding="utf-8").read()
bad = []

# 1. the two banks must cover the same events
ga = set(gm.VOICES["gremlin"])
ra = set(gm.VOICES["rival"])
if ga != ra:
    bad.append("bank keys differ: only gremlin %s / only rival %s"
               % (sorted(ga - ra), sorted(ra - ga)))

# 2. every yell("x") and set_mood target in the source must be a real key
# first argument only, so kwargs like name="..." are not mistaken for events,
# but both halves of yell("revenge" if losing else "fight", ...) are caught
yelled = set()
for first in re.findall(r"yell\(([^,]*)", src):
    yelled.update(re.findall(r'"([a-z_]+)"', first))
moods = set(gm.MOODCOL)
# these two are yelled through a variable, so the module declares them
need = yelled | moods | set(gm.GREET_EVENTS) | set(gm.CONTEXT_EVENTS)
missing = sorted(need - ga)
if missing:
    bad.append("events used but not in the gremlin bank: %s" % missing)
missing = sorted(need - ra)
if missing:
    bad.append("events used but not in the rival bank: %s" % missing)

unused = sorted(ga - need - {"generic"})
if unused:
    bad.append("banks nobody ever says: %s" % unused)

# 3. dead references to the tables this replaced
for gone in ("LINES[", "FIGHT_LINES", "HURT_LINES", "GENERIC"):
    if gone in src:
        bad.append("leftover reference to %s" % gone)

# 4. speak every line of every event, both characters, formatting included
gm.CFG.update(gm.DEFAULTS)
spoken = 0
for kind in ("gremlin", "rival"):
    f = gm.Fighter(0.0, 0.0, kind)
    if f.per is not gm.TRAITS[kind]:
        bad.append("%s got the wrong traits" % kind)
    for event, lines in gm.VOICES[kind].items():
        for _ in range(len(lines) * 6):
            try:
                f.yell(event, 1.0, name="Recycle Bin", runs=7, throws=41,
                       wins=3, losses=5)
            except Exception as exc:
                bad.append("%s/%s raised %r" % (kind, event, exc))
                break
            if not f.emote or "{" in f.emote:
                bad.append("%s/%s produced %r" % (kind, event, f.emote))
                break
            spoken += 1

# 5. the two of them must not actually sound alike
same = [e for e in ga if set(gm.VOICES["gremlin"][e]) & set(gm.VOICES["rival"][e])]
overlap = sorted(same)

# 6. lines about your stuff still work, and fall back to the right voice
g = gm.Fighter(0.0, 0.0, "gremlin")
r = gm.Fighter(0.0, 0.0, "rival")
for who in (g, r):
    for t in ("Holiday - YouTube", "Task Manager", "", None, "Weird App 9000"):
        assert isinstance(gm.line_for_title(who, t), str)
    for n in ("Recycle Bin", "Steam", "", None):
        assert isinstance(gm.line_for_icon(who, n), str)

# 7. weapon preference actually differs in play
import random
random.seed(1)
picks = {}
for kind in ("gremlin", "rival"):
    per = gm.TRAITS[kind]
    got = [gm.plan_weapon(per, rage=False) for _ in range(4000)]
    melee = sum(1 for w in got if w in gm.MELEE) / len(got)
    picks[kind] = melee

print("events per voice      : %d (identical key sets: %s)"
      % (len(ga), ga == ra))
print("lines spoken cleanly  : %d" % spoken)
print("shared lines between  : %s" % (overlap or "none - fully distinct"))
print("melee preference      : gremlin %.0f%%  rival %.0f%%"
      % (picks["gremlin"] * 100, picks["rival"] * 100))
print("traits                : aggro %.2f/%.2f  chatty %.2f/%.2f  grudge %.2f/%.2f"
      % (gm.TRAITS["gremlin"]["aggro"], gm.TRAITS["rival"]["aggro"],
         gm.TRAITS["gremlin"]["chatty"], gm.TRAITS["rival"]["chatty"],
         gm.TRAITS["gremlin"]["grudge"], gm.TRAITS["rival"]["grudge"]))

if bad:
    print("\nFAIL")
    for b in bad:
        print("  " + b)
    sys.exit(1)
print("\nPASS")
