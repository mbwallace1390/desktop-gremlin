"""Read the rendered animation, theme contrast and contact poses off Tk."""
import html
import math
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

gm = harness.load("visual_upgrade", crowd=2)
gm.monitors = lambda: [((0, 0, 1280, 900), (0, 0, 1280, 860))]
gm.virtual_screen = lambda: (0, 0, 1280, 900)
app = harness.build(gm)
harness.fake_terrain(app)
f, other = app.fighters
bad = []


def check(label, ok):
    print("%-48s %s" % (label, "pass" if ok else "FAIL"))
    if not ok:
        bad.append(label)


def park():
    f.x, f.y, f.face, f.sc = 450., 600., 1, .68
    f.state, f.st, f.walk, f.mood = "idle", 1., 0., "bored"
    f.squash = f.tumble = f.stun = f.vx = f.vy = 0.
    f.blink, f.hp, f.on_ground = 1., 100., True
    f.emote = f.play = f.pose_last = f.pose_from = None
    f.hit_at = -1000.
    f.foe, f.target, f.mode = None, None, "roam"
    app.time = 10.


def draw():
    app._frame_begin()
    app.sx = app.sy = 0.
    app.draw_fighter(f, 0)
    app._frame_end()


def skeleton():
    tb, ta = app._ftag[0][0], app._ftag[0][3]
    lines = app._pool[tb]["line"]
    return {"torso": app.canvas.coords(lines[3]),
            "hands": app.canvas.coords(lines[2])[-2:] + app.canvas.coords(app._pool[ta]["line"][0])[-2:],
            "feet": app.canvas.coords(lines[0])[-2:] + app.canvas.coords(lines[1])[-2:]}


park()
draw()
before = skeleton()
f.set_state("walk")
f.vx = 300 * f.K()
draw()
begin = skeleton()
app.time += .08
f.st = .08
draw()
middle = skeleton()
app.time += .10
f.st = .18
draw()
end = skeleton()
check("state entry preserves displayed upper body", begin["torso"] == before["torso"]
      and begin["hands"] == before["hands"])
check("transition reaches a distinct middle and end", middle["torso"] != begin["torso"]
      and middle["torso"] != end["torso"] and f.pose_from is None)
check("state blend keeps planted feet exact", begin["feet"] == middle["feet"] == end["feet"])

# Exact grips win over the incoming arm pose, even on the first frame.
park()
draw()
f.play = {"kind": "hang", "hwnd": 77, "x": 450., "phase": 0}
f.set_state("hang")
f.y = 500 + 82 * f.sc
draw()
hands = skeleton()["hands"]
check("new hang grips stay on the window edge", abs(hands[1] - 500) < .001
      and abs(hands[3] - 500) < .001)

# Read the barrel tip from its drawn cap while a transition is active.
# Muzzle-only raw poses would disagree until the animation settled.
park()
draw()
f.target = {"kind": "icon", "key": 0, "cx": 800., "cy": 560., "top": 530.,
            "w": 64, "h": 64, "name": "fixture"}
f.plan = "blaster"
f.per = dict(f.per, weapons=tuple(gm.WEAPONS))
app.start_attack(f)
for elapsed in (0., .04, .09, .15):
    app.time = 10. + elapsed
    f.st = f.atk = elapsed
    draw()
    cap = app._pool[app._ftag[0][5]]["oval"][0]
    co = app.canvas.coords(cap)
    tip = ((co[0] + co[2]) / 2, (co[1] + co[3]) / 2)
    muzzle = app.muzzle(f)
    check("blended muzzle stays on barrel at %.2fs" % elapsed,
          math.hypot(tip[0] - muzzle[0], tip[1] - muzzle[1]) < .001)

# The former step recoil had a 7-unit discontinuity at the release boundary.
park()
f.state, f.weapon, f.atk_dur, f.aim = "attack", "blaster", gm.ATKDUR["blaster"], 0.
f.atk = (.55 - .0001) * f.atk_dur
before = app.attack_pose(f)[-1]
f.atk = (.55 + .0001) * f.atk_dur
after = app.attack_pose(f)[-1]
check("gun recoil has no release-frame jump", math.dist(before, after) < .05)

# Both body themes retain contrasting faces and the existing identity color.
for theme, body, face in (("dark", gm.BODY, gm.FACE), ("light", "#F3F5FB", "#171923")):
    park()
    gm.CFG["body_theme"], gm.CFG["outline"], gm.CFG["halo_strength"] = theme, False, 1.
    draw()
    tb, th, tf = app._ftag[0][:3]
    head = app._pool[th]["oval"][0]
    colors = {app.canvas.itemcget(item, "fill") for kind, items in app._pool[tf].items()
              for item in items[:app._used[tf].get(kind, 0)]}
    check("%s theme has readable face and mood halo" % theme,
          app.canvas.itemcget(head, "fill") == body and colors == {face}
          and app.canvas.itemcget(head, "outline") == f.color())
    widths = []
    for strength in (.5, 2.):
        gm.CFG["halo_strength"] = strength
        draw()
        widths.append(float(app.canvas.itemcget(app._pool[th]["oval"][0], "width")))
    check("%s halo strength changes rendered width" % theme, widths[1] > widths[0])
    gm.CFG["outline"] = True
    draw()
    used = app._used[tb]["line"]
    contrast = gm.FACE if theme == "dark" else gm.BODY
    check("%s outline adds a contrasting silhouette" % theme, used == 9
          and app.canvas.itemcget(app._pool[tb]["line"][0], "fill") == contrast)
    gm.CFG["outline"] = False
    draw()
    check("%s outline turns off without stale strokes" % theme, app._used[tb]["line"] == 4
          and all(app.canvas.itemcget(it, "state") == "hidden" for it in app._pool[tb]["line"][4:]))
gm.CFG.update(body_theme="dark", outline=False, halo_strength=1.)

# Contact feedback changes by weapon and only uses the decorative RNG.
park()
other.weapon = "sword"
random.seed(999)
state = random.getstate()
colors = []
for weapon in ("pan", "blaster", "balloon", "confetti"):
    other.weapon = weapon
    app.parts.clear()
    app.impact_visual(other, f, 10)
    colors.append({p["col"] for p in app.parts})
check("weapon families produce distinct impact colors", len({tuple(sorted(c)) for c in colors}) == 4)
check("contact decoration leaves AI randomness alone", random.getstate() == state)
park()
other.x, other.weapon = f.x - 100, "pan"
app.hit_fighter(other, f, 12)
draw()
hit = skeleton()["torso"]
app.time += .3
f.st = .3
draw()
check("damage has a brief visual recoil silhouette", hit != skeleton()["torso"]
      and f.hp == 88 and f.state == "thrown")


def preview(path):
    """Export the actual tested canvas primitives, not a second pose model."""
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="580" viewBox="0 0 1100 580">']
    examples = [("walk", "sword", "Walking"), ("attack", "sword", "Sword windup"),
                ("attack", "bow", "Bow draw"), ("attack", "rocket", "Rocket recoil"),
                ("thrown", "pan", "Hit reaction")]
    for row, theme in enumerate(("dark", "light")):
        fill, ink = ("#ECF0F7", "#172131") if theme == "dark" else ("#172131", "#ECF0F7")
        svg += ['<rect x="0" y="%d" width="1100" height="290" fill="%s"/>' % (row * 290, fill),
                '<text x="35" y="%d" fill="%s" font-family="Segoe UI,sans-serif" font-size="22">%s body / %s</text>'
                % (row * 290 + 38, ink, theme.title(), "standard halo" if not row else "strong halo + outline")]
        gm.CFG.update(body_theme=theme, outline=bool(row), halo_strength=1.4 if row else 1.)
        for col, (st, weapon, label) in enumerate(examples):
            park()
            f.x, f.y, f.sc = 105 + col * 220, 240 + row * 290, 1.65
            f.state, f.weapon, f.walk, f.vx = st, weapon, 1.2, 250.
            f.atk_dur, f.atk, f.aim = gm.ATKDUR[weapon], gm.ATKDUR[weapon] * (.68 if weapon == "rocket" else .38), -.1
            f.mood = ("bored", "furious", "smug", "hyped", "sulking")[col]
            if st == "thrown":
                f.hit_at, f.hit_power = app.time - .05, .8
            draw()
            for item in app.canvas.find_all():
                if app.canvas.itemcget(item, "state") == "hidden":
                    continue
                kind, co = app.canvas.type(item), app.canvas.coords(item)
                color = html.escape(app.canvas.itemcget(item, "fill") or "none")
                if kind == "line":
                    pts = " ".join("%.2f,%.2f" % (co[i], co[i + 1]) for i in range(0, len(co), 2))
                    svg.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s" stroke-linecap="round" stroke-linejoin="round"/>' % (pts, color, app.canvas.itemcget(item, "width")))
                elif kind == "oval":
                    stroke = html.escape(app.canvas.itemcget(item, "outline") or "none")
                    svg.append('<ellipse cx="%.2f" cy="%.2f" rx="%.2f" ry="%.2f" fill="%s" stroke="%s" stroke-width="%s"/>' % ((co[0]+co[2])/2, (co[1]+co[3])/2, (co[2]-co[0])/2, (co[3]-co[1])/2, color, stroke, app.canvas.itemcget(item, "width")))
            svg.append('<text x="%d" y="%d" text-anchor="middle" fill="%s" font-family="Segoe UI,sans-serif" font-size="16">%s</text>' % (f.x, 275 + row * 290, ink, label))
    svg.append('</svg>')
    Path(path).write_text("\n".join(svg), encoding="utf-8")
    print("Preview:", path)


if "--preview" in sys.argv:
    preview(harness.scratch("visual_upgrade", "preview.svg"))
print("\n" + ("FAIL: " + "; ".join(bad) if bad else "PASS"))
harness.finish(gm, app, bad)
