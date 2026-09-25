"""Crowded speech stays readable, measured from actual Tk canvas items.

The six-speaker top-row case used to bounce the fourth and later bubbles
between two blocked places until a fixed retry count ran out. Pinned monitor
geometry makes that regression independent of the developer's desktop.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

gm = harness.load("speech_layout", crowd=10)
if not gm.IS_WINDOWS and os.environ.get("GREMLIN_ISOLATED_X11") != "1":
    raise RuntimeError("Speech layout checks require an explicitly isolated X11 desktop")
gm.monitors = lambda: [((0, 0, 1280, 900), (0, 0, 1280, 860))]
gm.virtual_screen = lambda: (0, 0, 1280, 900)
app = harness.build(gm)
app.root.withdraw()
harness.fake_terrain(app)
native_platform = gm.IS_WINDOWS
bad = []


def check(label, ok):
    print("%-68s %s" % (label, "pass" if ok else "FAIL"))
    if not ok:
        bad.append(label)


def visible(tag, kind=None):
    return [it for it in app.canvas.find_withtag(tag)
            if app.canvas.itemcget(it, "state") != "hidden"
            and (kind is None or app.canvas.type(it) == kind)]


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def inside(a, b):
    return b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]


def bubble(fi):
    """Read the painted body, text, and complete outline, including its tail."""
    shapes = visible(app._ftag[fi][7])
    words = visible(app._ftag[fi][8], "text")
    kind = "polygon" if gm.IS_WINDOWS else "rectangle"
    plates = [it for it in shapes if app.canvas.type(it) == kind]
    if len(plates) != 1 or len(words) != 1:
        return None
    co = app.canvas.coords(plates[0])
    if kind == "rectangle":
        body = co
    else:
        ys = sorted(set(co[1::2]))
        # The polygon's single lowest vertex is the downward tail tip.
        body_xs = [co[i] for i in range(0, len(co), 2) if co[i + 1] <= ys[-2]]
        body = (min(body_xs), min(ys), max(body_xs), ys[-2])
    bounds = app.canvas.bbox(*shapes)
    return body, app.canvas.bbox(words[0]), bounds


def park(count, x=560., y=100., sc=.68):
    app.time, app.shake_t, app.sx, app.sy = 10., 0., 0., 0.
    app.hover = None
    for i, f in enumerate(app.fighters):
        f.x, f.y, f.face, f.sc = x + i * 20, float(y), 1, sc
        f.state, f.st, f.walk, f.mood = "idle", 1., 0., "bored"
        f.squash = f.tumble = f.stun = f.vx = f.vy = f.vr = 0.
        f.blink, f.hp, f.on_ground, f.grabbed = 1., 100., True, False
        f.emote, f.emote_t = None, 0.
        f.play = f.pose_last = f.pose_from = f.carry = None
        f.hit_at, f.hit_power = -1000., 0.
        f.foe, f.target, f.mode = None, None, "roam"
        if i < count:
            f.say("you again? really?", 3.)


def readable(count):
    drawn = [bubble(i) for i in range(count)]
    return (all(d is not None for d in drawn)
            and all(inside(d[0], (0, 0, app.W, app.H))
                    and inside(d[1], d[0]) for d in drawn)
            and not any(overlap(drawn[i][2], drawn[j][2])
                        for i in range(count) for j in range(i)))


try:
    for windows in ((True, False) if native_platform else (False,)):
        gm.IS_WINDOWS = windows
        label = "Windows" if windows else "Linux"
        park(6)
        app.draw()
        check(label + ": six neighbours near the top have separate bubbles", readable(6))

        failed_cases = []
        for count in (3, 4, 6, 8, 10):
            for sc in (.35, .68, 1., 1.6, 2.5):
                for edge, x, y in (("top", 560., 60.), ("left", 0., 100.),
                                   ("right", 1280. - (count - 1) * 20, 100.),
                                   ("bottom", 560., 860.)):
                    park(count, x, y, sc)
                    app.draw()
                    if not readable(count):
                        failed_cases.append((count, sc, edge))
        if failed_cases:
            print("  crowded failures:", failed_cases)
        check(label + ": 3-10 speakers, screen edges and five sizes", not failed_cases)

        # The last fighter speaks first: age, rather than roster index, owns
        # placement. New arrivals must fit round the already visible message.
        park(0)
        first = app.fighters[-1]
        first.say("I was here first", 3.)
        app.draw()
        before = bubble(9)
        for f in app.fighters[:-1]:
            f.say("you again? really?", 3.)
        app.draw()
        check(label + ": the oldest bubble keeps its place in a crowd",
              before == bubble(9) and readable(10))
        if not windows:
            check("Linux: bubbles use only the shape mask's supported primitives",
                  all(app.canvas.type(it) in ("rectangle", "line")
                      for fi in range(10) for it in visible(app._ftag[fi][7])))
finally:
    gm.IS_WINDOWS = native_platform

print("\n" + ("FAIL: " + "; ".join(bad) if bad else "PASS"))
harness.finish(gm, app, bad)
