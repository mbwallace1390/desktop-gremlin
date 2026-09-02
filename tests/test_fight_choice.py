"""In a real fight, does the shot he fires match the distance he closed?

The weapon-range check builds its own shot and proves the mechanism works.
This one lets the AI decide everything -- when to close, which weapon, when to
fire -- with a wall of icons between them, and checks two things that only show
up when the decision path runs for itself:

  * every shot meant for the other fighter is flagged to pass over the desktop
  * nobody fires from beyond the reach of the weapon actually in his hands

The second one shipped broken. The fight state walks him to REACH[f.plan], and
start_attack used to swap in a different weapon half the time, so he would
stand at lightning range and swing a sword. Measured over four minutes before
the fix: every chainsaw swing and 9 in 10 sword swings thrown from outside
their own reach, and only lightning -- which is instant, and only ever fired
when it was also the plan -- reliably connected.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

gm = harness.load("fight", crowd=2, chaos=2.0)     # chaos: more fights per minute
app = harness.build(gm)
a, b = app.fighters
GROUND = app.ground_at(900)

# a wall of icons at fighter height, directly between them
ICONS = []
for i in range(10):
    x = 500 + i * 100
    ICONS.append(("Icon %d" % i, x, int(GROUND) - 120, x + 64, int(GROUND) - 56, i))
harness.fake_terrain(app, ICONS)

fired = []
_start = app.start_attack


def start_attack(f, at=None, foe=False):
    _start(f, at=at, foe=foe)
    if foe and f.foe and f.state == "attack":
        k = .4 + .6 * f.K()
        fired.append({"plan": f.plan, "weapon": f.weapon,
                      "gap": abs(f.foe.x - f.x),
                      "reach_used": gm.REACH[f.weapon] * k,
                      "at_foe": f.at_foe, "f": f, "hit": False})


app.start_attack = start_attack
_hf = app.hit_fighter


def hit_fighter(att, vic, dmg):
    for r in reversed(fired):
        if r["f"] is att:
            r["hit"] = True
            break
    return _hf(att, vic, dmg)


app.hit_fighter = hit_fighter

random.seed(7)
DT = 1 / 40.0
for n in range(40 * 240):                    # four minutes
    if n % 200 == 0:                         # keep them interested
        for f in (a, b):
            f.hp = 100.0
            f.foe = b if f is a else a
            f.mode = "fight"
            f.set_state("fight")
    app.update(DT)

bad = []
if len(fired) < 40:
    bad.append("only %d attacks in four minutes - too few to judge" % len(fired))

no_pierce = [r for r in fired if not r["at_foe"]]
mismatch = [r for r in fired if r["plan"] != r["weapon"]]
whiff = [r for r in fired if r["gap"] > r["reach_used"]]

print("attacks started in a fight   : %d" % len(fired))
print("not flagged to pass icons    : %d" % len(no_pierce))
print("fired a weapon he did not close for: %d" % len(mismatch))
print("fired from beyond its reach  : %d" % len(whiff))
print()
print("%-10s %5s %7s  %s" % ("weapon", "n", "hit foe", "closed for"))
by = {}
for r in fired:
    by.setdefault(r["weapon"], []).append(r)
for w in sorted(by):
    rows = by[w]
    print("%-10s %5d %7d  %s"
          % (w, len(rows), sum(1 for r in rows if r["hit"]),
             ",".join(sorted({r["plan"] for r in rows}))[:34]))

# Every ranged weapon that got used has to land something. A weapon that never
# connects across a whole fight is the shape of the bug this file exists for.
for w, rows in by.items():
    if len(rows) >= 8 and not any(r["hit"] for r in rows):
        bad.append("%s fired %d times and never hit" % (w, len(rows)))

if no_pierce:
    bad.append("%d fight shots were not flagged to pass over icons" % len(no_pierce))
if mismatch:
    bad.append("%d attacks used a weapon he had not closed for" % len(mismatch))
if whiff:
    bad.append("%d attacks were thrown from outside their own reach" % len(whiff))

print("\n" + ("FAIL\n  " + "\n  ".join(bad) if bad else "PASS"))
harness.finish(gm, app, bad)
