"""Every event the code can yell must exist in EVERY character's bank, and
every line in all of them must survive being formatted and spoken.

A missing key is a KeyError in the middle of a fight, which is exactly the sort
of thing that only shows up on someone's desktop three days later. With ten
banks instead of two, that is ten times the chance of a gap.

This also enforces the thing the cast exists for: no two of them say the same
line. Stock noises ("...", "z z z") are exempt.
"""
import importlib.util
import io
import os
import random
import re
import sys
from itertools import combinations

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
STOCK = {"...", "z z z", "...zzz", "hm", "hm.", "fine.", "MINE"}
bad = []

# 1. the roster and the tables agree
for name in gm.ROSTER:
    for table, label in ((gm.VOICES, "VOICES"), (gm.TRAITS, "TRAITS"),
                         (gm.PALETTES, "PALETTES")):
        if name not in table:
            bad.append("%s is in ROSTER but not %s" % (name, label))
for name in gm.VOICES:
    if name not in gm.ROSTER:
        bad.append("%s is in VOICES but not ROSTER" % name)

# 2. every bank carries the same events
banks = dict((n, set(gm.VOICES[n])) for n in gm.ROSTER if n in gm.VOICES)
if banks:
    first = gm.ROSTER[0]
    for name, keys in banks.items():
        if keys != banks[first]:
            bad.append("%s events differ from %s: missing %s / extra %s"
                       % (name, first, sorted(banks[first] - keys),
                          sorted(keys - banks[first])))

# 3. every event the source yells is a real key, and none is unreachable.
# First argument only, so kwargs like name="..." are not mistaken for events,
# but both halves of yell("revenge" if losing else "fight", ...) are caught.
# chat() is yell() behind a chatty roll, so its events count as spoken too.
yelled = set()
for firstarg in re.findall(r"(?:yell|chat)\(([^,]*)", src):
    yelled.update(re.findall(r'"([a-z_]+)"', firstarg))
# these two are yelled through a variable, so the module declares them
need = yelled | set(gm.MOODS) | set(gm.GREET_EVENTS) | set(gm.CONTEXT_EVENTS)
have = banks.get(gm.ROSTER[0], set())
missing = sorted(need - have)
if missing:
    bad.append("events used but in nobody's bank: %s" % missing)
unused = sorted(have - need - {"generic"})
if unused:
    bad.append("banks nobody ever says: %s" % unused)

# 4. dead references to the tables this replaced
for gone in ("MOODCOL", "RIVALCOL", 'VOICES["gremlin"]', 'CFG["rival"]'):
    if gone in src:
        bad.append("leftover reference to %s" % gone)

# 5. speak every line of every event for every character
gm.CFG.update(gm.DEFAULTS)
spoken = 0
for name in gm.ROSTER:
    f = gm.Fighter(0.0, 0.0, name)
    if f.per is not gm.TRAITS[name]:
        bad.append("%s got the wrong traits" % name)
    if f.pal is not gm.PALETTES[name]:
        bad.append("%s got the wrong palette" % name)
    for event, lines in gm.VOICES[name].items():
        if not lines:
            bad.append("%s/%s is empty" % (name, event))
        for _ in range(len(lines) * 4):
            try:
                f.yell(event, 1.0, name="Recycle Bin", runs=7, throws=41,
                       wins=3, losses=5)
            except Exception as exc:
                bad.append("%s/%s raised %r" % (name, event, exc))
                break
            if not f.emote or "{" in f.emote:
                bad.append("%s/%s produced %r" % (name, event, f.emote))
                break
            spoken += 1

# 6. no two of them say the same thing
shared = []
for a, b in combinations(gm.ROSTER, 2):
    if a not in gm.VOICES or b not in gm.VOICES:
        continue
    for event in gm.VOICES[a]:
        overlap = (set(gm.VOICES[a][event]) & set(gm.VOICES[b].get(event, ()))) - STOCK
        for line in sorted(overlap):
            shared.append("%s and %s both say %r for %s" % (a, b, line, event))

# 7. temperament: same axes everywhere, real weapons, sane ranges
AXES = {"aggro", "chatty", "grudge", "dash", "hops", "thief", "nerve", "weapons"}
for name, t in gm.TRAITS.items():
    if set(t) != AXES:
        bad.append("%s traits: missing %s / extra %s"
                   % (name, sorted(AXES - set(t)), sorted(set(t) - AXES)))
    for w in t.get("weapons", ()):
        if w not in gm.WEAPONS:
            bad.append("%s has an unknown weapon %r" % (name, w))
    for axis in ("aggro", "chatty", "grudge", "dash", "hops"):
        if axis in t and not (0.1 <= t[axis] <= 3.0):
            bad.append("%s %s = %r is out of range" % (name, axis, t[axis]))
    for axis in ("thief", "nerve"):
        if axis in t and not (0.0 <= t[axis] <= 1.0):
            bad.append("%s %s = %r is not a probability" % (name, axis, t[axis]))

# 8. no two characters share a mood colour
seen = {}
for name, pal in gm.PALETTES.items():
    if set(pal) != set(gm.MOODS):
        bad.append("%s palette moods wrong: %s" % (name, sorted(pal)))
    for mood, col in pal.items():
        who = seen.setdefault((mood, col), [])
        who.append(name)
for (mood, col), who in seen.items():
    if len(who) > 1:
        bad.append("%s share the same %s colour %s" % (who, mood, col))

# 9. lines about your own stuff still work, and fall back to the right voice
for name in gm.ROSTER:
    f = gm.Fighter(0.0, 0.0, name)
    for title in ("Holiday - YouTube", "Task Manager", "", None, "Weird App"):
        if not isinstance(gm.line_for_title(f, title), str):
            bad.append("%s: line_for_title(%r) is not a string" % (name, title))
    for icon in ("Recycle Bin", "Steam", "", None):
        if not isinstance(gm.line_for_icon(f, icon), str):
            bad.append("%s: line_for_icon(%r) is not a string" % (name, icon))

# 10. they must actually prefer different weapons
random.seed(1)
melee = {}
for name in gm.ROSTER:
    got = [gm.plan_weapon(gm.TRAITS[name]) for _ in range(3000)]
    melee[name] = sum(1 for w in got if w in gm.MELEE) / float(len(got))
spread = max(melee.values()) - min(melee.values())

print("cast          : %d characters, %d events each"
      % (len(gm.ROSTER), len(have)))
print("lines spoken  : %d" % spoken)
print("shared lines  : %d" % len(shared))
for s in shared[:5]:
    print("   " + s)
print("melee spread  : %.0f%% (%s) to %.0f%% (%s)"
      % (min(melee.values()) * 100, min(melee, key=melee.get),
         max(melee.values()) * 100, max(melee, key=melee.get)))

if shared:
    bad.append("%d lines are shared between characters" % len(shared))
if spread < 0.20:
    bad.append("weapon preferences only span %.0f%% - too alike" % (spread * 100))

print("")
if bad:
    print("FAIL")
    for b in bad[:20]:
        print("  " + b)
    sys.exit(1)
print("PASS")
