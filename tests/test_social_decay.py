"""Do grudges ever wear off?

The saved relationship graph used to be a one-way ratchet. `on_hit` was the
only bond source with no scene gate -- it fired once per landed hit, roughly
once a second in a brawl, while every positive term was gated behind
`_available()`, which needs idle/walk/taunt. Hostility kept everyone in
`fight`, so scenes stopped starting, so the positives stopped firing. Measured
over twenty simulated minutes from a blank memory: 1171 negative deltas
totalling -3521 against 2 positive totalling +16, and fourteen of fifteen pairs
pinned at the -100 floor by minute eight. Nothing decayed, and the score is
saved, so the friendships half of the social system switched itself off for
good and the only cure was "forget everything about me".

What is checked, all read back off the real persisted graph:

  1. ordinary play, swept over several seeds, never floors a pair
  2. the same with "Friendships and group scenes" OFF -- that path calls
     clear() every frame, and the first version of this fix kept its rate-limit
     state in clear(), which handed that configuration the whole bug back
  3. fighting alone cannot push a pair past HIT_BOND_FLOOR, however long it runs
  4. a graph seeded at the floor climbs back out on run time alone
  5. hits spread over time bond once per interval, not once per hit

Every threshold here is a literal. An earlier draft read HIT_BOND_INTERVAL out
of the module under test and advanced the clock by it, which made the check
invariant to that constant: setting it to 0.05 -- a 120x regression that
disables the gate -- left the whole file green. Reading a tuning constant from
the code you are testing measures nothing about that constant.

The graph assertions also require a populated graph. Guarding them with
`if scores` let a build with the decay cranked to a 0.12s half-life -- nothing
ever retained, the social system entirely dead -- report "0 pairs, 0 at the
floor" and exit 0.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

import gremlin_social  # noqa: E402

DT = 1 / 40.0
FLOOR = -95.0          # decay moves a pinned pair off -100 between samples,
                       # so -99.9 was a threshold nothing could ever trip
bad = []


def graph_of(gm):
    return gm.MEM["relationships"]


def play(gm, app, seed, minutes):
    """Run the real app and report (scores, positive pairs, grudge charges)."""
    charges = [0]
    real_bond = app.social._bond

    def spy(a, b, delta):
        if delta < 0:
            charges[0] += 1
        return real_bond(a, b, delta)

    app.social._bond = spy
    random.seed(seed)
    for _ in range(int(40 * 60 * minutes)):
        app.update(DT)
    app.social._bond = real_bond
    scores = list(graph_of(gm).values())
    return scores, [v for v in scores if v > 0], charges[0]


# --- 1 and 2. ordinary play, scenes on and off, several seeds --------------
# Sweeping matters: an earlier draft asserted that a positive bond fired at
# least once in six minutes, which held on seed 31 and failed on 2, 3, 7 and 99.
# Scenes are rare by design -- they need the cast idle -- so that was the check
# being wrong about the system, not the system being broken.
for scenes in (True, False):
    for seed in (2, 7, 31, 99):
        gm = harness.load("social_decay", crowd=6, group_scenes=scenes,
                          play_mode="mischief", chaos=1.0)
        app = harness.build(gm)
        harness.fake_terrain(app, [("Icon %d" % i, 60 + (i % 8) * 120,
                                    200 + (i // 8) * 150, 124 + (i % 8) * 120,
                                    264 + (i // 8) * 150, i) for i in range(16)])
        try:
            scores, positive, charges = play(gm, app, seed, 6)
            label = "scenes %s seed %d" % ("on " if scenes else "off", seed)
            worst = min(scores) if scores else 0.0
            mean = sum(scores) / len(scores) if scores else 0.0
            print("%-22s %2d pairs  worst %7.1f  mean %6.1f  %3d charges  %d positive"
                  % (label, len(scores), worst, mean, charges, len(positive)))
            if charges < 10:
                bad.append("%s: only %d grudge charges -- nothing was measured"
                           % (label, charges))
            if len(scores) < 5:
                bad.append("%s: only %d pairs recorded; an empty graph is not a "
                           "healthy one" % (label, len(scores)))
            if scores and worst <= FLOOR:
                bad.append("%s: worst pair %.1f is at the floor" % (label, worst))
            # The other direction: decay strong enough to hold everyone near
            # zero means a rivalry can never form. _advance reads < -15.
            if scores and worst > -15:
                bad.append("%s: worst pair only %.1f, so no rivalry can form "
                           "(_advance wants < -15)" % (label, worst))
            # Nothing here asserts on a magnitude between those two bounds.
            # `App` reads the real screen -- harness does not pin it -- so how
            # often anyone meets anyone else moves with the desktop size: seed
            # 31 scenes-off measured -41.6 here and -62.8 on a 1280x800 CI
            # runner, against -70.0 for a dead interval gate. A threshold placed
            # between those overlaps the healthy spread. The gate is checked
            # directly instead, in section 6.
        finally:
            harness.teardown(gm, app)

# --- 3, 4, 5. the mechanisms, driven directly -----------------------------
gm = harness.load("social_decay", crowd=6, group_scenes=True,
                  play_mode="mischief")
app = harness.build(gm)
harness.fake_terrain(app, [("Icon %d" % i, 60 + i * 120, 200,
                            124 + i * 120, 264, i) for i in range(8)])
try:
    graph = graph_of(gm)
    social = app.social
    a, b = app.fighters[0], app.fighters[1]
    key = social._key(a, b)

    # 3. fighting alone stops at HIT_BOND_FLOOR, whatever the interval is.
    graph.clear()
    social.alliances.clear()      # a live pact adds -30 friendly fire per hit
    social._hit_bond.clear()
    for _ in range(4000):
        social.time += 1.0        # a literal, not the constant under test
        social.on_hit(a, b, 40)
    fought = graph.get(key, 0.0)
    print("4000 hits spread over 4000s: %.1f" % fought)
    if fought <= FLOOR:
        bad.append("fighting alone reached %.1f: it can still floor a pair" % fought)
    if fought > -15:
        bad.append("4000 hits only reached %.1f, which is not even a rivalry" % fought)

    # 4. a floored graph climbs back out on run time alone. Bonds are blocked
    # for the window so a scene firing cannot be mistaken for decay.
    graph.clear()
    social.alliances.clear()
    pairs = sorted(gm.ROSTER)
    for i, one in enumerate(pairs):
        for two in pairs[i + 1:]:
            graph["|".join(sorted((one, two)))] = -100.0
    seeded = len(graph)
    blocked = [0]

    def refuse(x, y, delta):
        blocked[0] += 1

    real_bond, social._bond = social._bond, refuse
    start = social.time
    while social.time - start < 600:
        social.update(.25)
    social._bond = real_bond
    recovered = min(graph.values()) if graph else 0.0
    print("seeded %d pairs at -100; after ten minutes worst is %.1f, %d left, "
          "%d bond(s) suppressed" % (seeded, recovered, len(graph), blocked[0]))
    if len(graph) != seeded:
        bad.append("decay dropped %d of %d seeded pairs before they neared zero"
                   % (seeded - len(graph), seeded))
    if graph and recovered < -60:
        bad.append("a floored pair only reached %.1f after ten minutes" % recovered)

    # 4b. the fade has to reach disk. Marking dirty on a single pass's drift
    # never fired: one pass can move the largest score by at most 0.21, so any
    # threshold above that left decay living in memory only, and a quiet
    # desktop saved a grudge it had already forgotten.
    graph.clear()
    social.alliances.clear()
    graph["brawler|sniper"] = -100.0
    marks = [0]
    real_mark, social.mark_dirty = social.mark_dirty, lambda: marks.__setitem__(0, marks[0] + 1)
    real_bond, social._bond = social._bond, lambda x, y, d: None
    start = social.time
    while social.time - start < 300:
        social.update(.25)
    social.mark_dirty, social._bond = real_mark, real_bond
    faded = graph.get("brawler|sniper", 0.0)
    print("five quiet minutes: -100.0 faded to %.1f, memory marked dirty %d time(s)"
          % (faded, marks[0]))
    if faded < -80:                # toward zero is recovery, so greater is better
        bad.append("a quiet five minutes only faded -100 to %.1f" % faded)
    if marks[0] == 0:
        bad.append("the fade never marked memory dirty, so quitting would save "
                   "the grudge the run had already let go of")

    # 5. the number of grudge steps follows elapsed time, not hit count. Both
    # spacings are literals: 0.1s is well inside any sane interval and 20s well
    # outside one, so shrinking HIT_BOND_INTERVAL toward zero turns the burst
    # into forty steps and fails here. (An earlier draft used 1s against 30s and
    # got five steps either way -- the same answer for different reasons, which
    # proved nothing.)
    def burst(count, spacing):
        graph.clear()
        social.alliances.clear()
        social._hit_bond.clear()
        social.time += 1000.0          # clear of anything the sections above did
        for _ in range(count):
            social.time += spacing
            social.on_hit(a, b, 20)
        return graph.get(key, 0.0)

    one_step = burst(1, 100.0)
    crammed = burst(40, 0.1)           # 4 seconds: one interval at most
    spread = burst(5, 20.0)            # 100 seconds: one step per hit
    print("one hit: %.1f;  40 hits over 4s: %.1f;  5 hits over 100s: %.1f"
          % (one_step, crammed, spread))
    if one_step == 0:
        bad.append("a landed hit created no grudge at all")
    if crammed < one_step - 0.01:
        bad.append("40 hits crammed into 4s moved the bond %.1f against %.1f for "
                   "a single hit -- still charging per hit" % (crammed, one_step))
    if spread > crammed - 0.01:
        bad.append("5 hits spread over 100s (%.1f) did not out-grudge 40 hits "
                   "crammed into 4s (%.1f): the interval is not gating"
                   % (spread, crammed))

    # 6. the gate survives update()'s own bookkeeping with scenes off. That
    # path calls clear() every frame, and keeping the rate-limit state in
    # clear() reset it before it could expire -- handing the per-hit ratchet
    # back to the one configuration with no positive bond source at all.
    # Driven directly rather than inferred from a six-minute run, so the
    # result does not move with the desktop size.
    graph.clear()
    social.alliances.clear()
    social._hit_bond.clear()
    gm.CFG["group_scenes"] = False
    social.time += 1000.0
    for _ in range(40):
        social.update(.1)                 # runs the clear()-every-frame branch
        social.on_hit(a, b, 20)
    gated = graph.get(key, 0.0)
    gm.CFG["group_scenes"] = True
    print("40 hits over 4s with group scenes OFF: %.1f" % gated)
    if gated < one_step - 0.01:
        bad.append("with group scenes off, 40 hits in 4s moved the bond %.1f "
                   "against %.1f for a single hit: update()'s clear() is wiping "
                   "the rate limit" % (gated, one_step))

    print()
    if bad:
        print("FAILED")
        for line in bad:
            print("  " + line)
finally:
    harness.finish(gm, app, bad)
