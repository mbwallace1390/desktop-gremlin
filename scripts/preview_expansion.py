"""Export actual expansion Canvas frames without starting a desktop overlay.

Run with the project's Python: .venv/Scripts/python.exe -B scripts/preview_expansion.py
The shared harness replaces desktop readers and persistence before App exists.
The one Tk window stays withdrawn; no screenshots or native rendering are used.
"""
import collections
import html
import json
import math
import os
import random
import sys
import tkinter.font
from unittest import mock
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import harness

WIDTH, HEIGHT, FLOOR = 1040, 250, 230
DESTINATION = os.path.join(ROOT, "docs", "expansion-preview.svg")


def escape(value):
    return html.escape(str(value), quote=True)


def number(value):
    if not math.isfinite(float(value)):
        raise AssertionError("Non-finite Canvas coordinate")
    return ("%.2f" % value).rstrip("0").rstrip(".")


def serialize_canvas(app):
    """Preserve the real pooled-item stacking order, coordinates and colours."""
    canvas, output, counts, layers = app.canvas, [], collections.Counter(), collections.Counter()
    for item in canvas.find_all():
        if canvas.itemcget(item, "state") == "hidden":
            continue
        kind, coords = canvas.type(item), canvas.coords(item)
        if not coords:
            continue
        if not all(math.isfinite(c) for c in coords):
            raise AssertionError("Invalid Canvas geometry")
        fill = canvas.itemcget(item, "fill") or "none"
        counts[kind] += 1
        for tag in canvas.gettags(item):
            layers[tag] += 1
        if kind == "line":
            points = " ".join(number(coords[i]) + "," + number(coords[i + 1])
                              for i in range(0, len(coords), 2))
            output.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s" '
                          'stroke-linecap="round" stroke-linejoin="round"/>' %
                          (points, escape(fill), number(float(canvas.itemcget(item, "width")))))
        elif kind in ("oval", "rectangle"):
            x0, y0, x1, y1 = coords
            style = 'fill="%s" stroke="%s" stroke-width="%s"' % (
                escape(fill), escape(canvas.itemcget(item, "outline") or "none"),
                number(float(canvas.itemcget(item, "width"))))
            if kind == "oval":
                output.append('<ellipse cx="%s" cy="%s" rx="%s" ry="%s" %s/>' %
                              (number((x0 + x1) / 2), number((y0 + y1) / 2),
                               number(abs(x1 - x0) / 2), number(abs(y1 - y0) / 2), style))
            else:
                output.append('<rect x="%s" y="%s" width="%s" height="%s" %s/>' %
                              (number(min(x0, x1)), number(min(y0, y1)),
                               number(abs(x1 - x0)), number(abs(y1 - y0)), style))
        elif kind == "polygon":
            # Tk's smooth polygon: quadratic pieces between the midpoints of
            # consecutive points, each point the control of its piece. A point
            # given twice is a sharp corner, which this reproduces exactly.
            pts = [(coords[i], coords[i + 1]) for i in range(0, len(coords), 2)]

            def mid(a, b):
                return number((a[0] + b[0]) / 2) + "," + number((a[1] + b[1]) / 2)
            if canvas.itemcget(item, "smooth") in ("1", "true", "bezier"):
                path = ["M" + mid(pts[-1], pts[0])]
                for i, p in enumerate(pts):
                    path.append("Q%s,%s %s" % (number(p[0]), number(p[1]),
                                               mid(p, pts[(i + 1) % len(pts)])))
            else:
                path = ["M%s,%s" % (number(pts[0][0]), number(pts[0][1]))]
                path += ["L%s,%s" % (number(x), number(y)) for x, y in pts[1:]]
            output.append('<path d="%sZ" fill="%s" stroke="%s" stroke-width="%s" '
                          'stroke-linejoin="round"/>' %
                          (" ".join(path), escape(fill),
                           escape(canvas.itemcget(item, "outline") or "none"),
                           number(float(canvas.itemcget(item, "width")))))
        elif kind == "text":
            font = tkinter.font.Font(root=app.root, font=canvas.itemcget(item, "font")).actual()
            # Match "center" exactly: its letters are not compass points.
            anchor = canvas.itemcget(item, "anchor")
            anchor = "" if anchor == "center" else anchor
            align = "end" if "e" in anchor else "start" if "w" in anchor else "middle"
            baseline = ("text-before-edge" if "n" in anchor else
                        "text-after-edge" if "s" in anchor else "central")
            px = app.root.winfo_fpixels("1i") * abs(font["size"]) / 72
            output.append('<text x="%s" y="%s" fill="%s" font-family="%s" '
                          'font-size="%s" font-weight="%s" text-anchor="%s" '
                          'dominant-baseline="%s">%s</text>' %
                          (number(coords[0]), number(coords[1]), escape(fill),
                           escape(font["family"]), number(px), font["weight"], align,
                           baseline, escape(canvas.itemcget(item, "text"))))
        else:
            raise AssertionError("Unsupported visible Canvas primitive: " + str(kind))
    assert output and counts["line"] > 20 and counts["oval"] > 5
    return "\n".join(output), dict(counts), dict(layers)


def reset(gm, app):
    app.clear_expansion()
    app.shots.clear()
    app.traps.clear()
    app.parts.clear()
    app.booms.clear()
    app.slashes.clear()
    app.stains.clear()
    app.time = app.shake_t = app.sx = app.sy = 0.0
    app.asleep = False
    gm.MEM = gm.blank_memory()
    harness.fake_terrain(app)
    for i, f in enumerate(app.fighters):
        f.x, f.y = 90 + i * 175, FLOOR
        f.vx = f.vy = f.squash = f.stun = f.tumble = f.vr = 0.0
        f.anger = f.boredom = f.emote_t = 0.0
        f.mood_check, f.mood_t = 999.0, 0.0
        f.hp, f.blink, f.mood = 100.0, 20.0, "bored"
        f.state, f.on_ground, f.grabbed = "idle", True, False
        f.foe = f.target = f.plat = f.pose_from = f.emote = None
        f.scene_hat = f.scene_action = None
        f.goal, f.face, f.hat = 999.0, 1, "none"
        f.per = dict(f.per, weapons=gm.WEAPONS)


def advance(app, seconds):
    for _ in range(round(seconds * 120)):
        app.update(1 / 120.0)


def release(gm, app, f, weapon, target):
    f.plan = weapon
    f.per = dict(f.per, weapons=(weapon,))
    app.start_attack(f, at=target)
    assert f.weapon == weapon and f.state == "attack"
    f.atk = gm.RELEASE_AT.get(weapon, .55) * f.atk_dur
    app._st_attack(f, 1 / 120.0, f.K())
    assert app.arsenal.shots[-1]["k"] == weapon


def weapons_panel(gm, app):
    reset(gm, app)
    thrower, protected, floating, player, frozen, stuck = app.fighters
    thrower.x, player.x, floating.x = 80, 255, 445
    frozen.x, stuck.x, protected.x = 665, 825, 965
    release(gm, app, thrower, "boomerang", (370, 150))
    release(gm, app, player, "rubber", (590, 180))
    assert app.arsenal.apply_effect(floating, "bubble", 5, thrower)
    assert app.arsenal.apply_effect(frozen, "freeze", 5, player)
    assert app.arsenal.apply_effect(stuck, "foam", 5, thrower)
    assert app.arsenal.apply_effect(protected, "shield", 5, protected)
    for _ in range(12):
        app.time += 1 / 120.0
        app.arsenal.update(1 / 120.0)
        for f in app.fighters:
            app.arsenal.control(f, 1 / 120.0)
    assert len(app.arsenal.shots) == 2
    assert len(app.arsenal.effects) == 4
    app.draw()
    return ["Returning boomerang + ricocheting ball", "Bubble", "Sliding ice", "Sticky foam", "Shield"]


def motion_panel(gm, app):
    reset(gm, app)
    rope, plane, climber, rider, helper, lifted = app.fighters
    props = [app.motion.add_prop(k, x, FLOOR) for k, x in
             (("crate", 70), ("seesaw", 265), ("ramp", 465), ("fan", 670), ("conveyor", 905))]
    assert all(props)
    rope.x, rope.y, rope.vx = 160, 185, 100
    assert app.motion.start(rope, "rope", (245, 45))
    plane.x, plane.y, plane.on_ground = 800, 112, False
    assert app.motion.start(plane, "plane")
    climber.x, climber.y, climber.plat = 70, FLOOR - props[0]["h"], ("toy", props[0]["id"])
    rider.x, helper.x = 365, 405
    assert app.motion.start(rider, "boost", helper)
    lifted.x, lifted.y = 670, 216
    advance(app, .34)
    assert len(app.motion.props) == 5 and len(app.motion.actions) >= 3
    app.draw()
    return ["Crate", "Pendulum swing / seesaw", "Team boost + ramp", "Fan", "Paper plane / conveyor"]


def social_panel(gm, app):
    reset(gm, app)
    app.fighters = app.fighters[:5]
    thief, victim, lookout, friend, guest = app.fighters
    thief.x, victim.x, lookout.x = 240, 290, 380
    friend.x, guest.x = 745, 825
    victim.hat = "crown"
    assert app.social.start_scene("hat_heist", [thief, victim, lookout])
    assert app.social.start_scene("coffee", [friend, guest])
    advance(app, 2.8)
    assert thief.scene_hat == "crown" and victim.scene_hat == "none"
    assert len(app.social.scenes) == 2
    app.draw()
    return ["Lookout, distraction, stolen hat, escape", "A coffee break builds friendship"]


def main():
    random.seed(912)
    gm = harness.load("expansion_preview", crowd=6, scale=1.0, chaos=.2,
                      play_mode="mischief", group_scenes=True, parkour=True,
                      toy_props=True, blood=False, react_to_windows=False,
                      body_theme="light")
    app = None
    original = gm.tk.Tk

    def withdrawn_root():
        window = original()
        window.withdraw()
        return window

    try:
        with mock.patch.object(gm.tk, "Tk", withdrawn_root), \
                mock.patch.object(gm, "virtual_screen", return_value=(0, 0, WIDTH, HEIGHT)), \
                mock.patch.object(gm, "monitors", return_value=[
                    ((0, 0, WIDTH, HEIGHT), (0, 0, WIDTH, FLOOR))]):
            app = harness.build(gm)
        assert app.root.state() == "withdrawn"
        assert not getattr(app.canvas, "native", None)
        panels, report = [], []
        cases = (("Pocket chaos", "Real projectiles and temporary status effects", weapons_panel),
                 ("A desktop playground", "Momentum, cooperative travel and five physical toys", motion_panel),
                 ("Partners in petty crime", "Two coordinated scenes, with independent actor roles", social_panel))
        for index, (title, caption, render) in enumerate(cases):
            labels = render(gm, app)
            svg, counts, layers = serialize_canvas(app)
            y = 126 + index * 326
            panels.append('<g transform="translate(40 %d)">' % y)
            panels.append('<rect width="1040" height="310" rx="16" fill="#202B40" stroke="#36445D"/>')
            panels.append('<text x="22" y="28" class="panel-title">%02d  %s</text>' % (index + 1, escape(title)))
            panels.append('<text x="22" y="49" class="caption">%s</text>' % escape(caption))
            panels.append('<g transform="translate(0 45)" clip-path="url(#frame)">' + svg + '</g>')
            if index == 0:
                positions = (35, 417, 657, 791, 934)
            elif index == 1:
                positions = (43, 149, 364, 657, 789)
            else:
                positions = (163, 689)
            for x, label in zip(positions, labels):
                panels.append('<text x="%d" y="300" class="label">%s</text>' % (x, escape(label)))
            panels.append('</g>')
            report.append({"panel": title, "canvas_items": sum(counts.values()),
                           "primitive_counts": counts,
                           "expansion_layers": {k: v for k, v in layers.items()
                                                if k in ("arsenal", "social", "toys", "costume")}})
        total = sum(panel["canvas_items"] for panel in report)
        source = '''<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="1150" viewBox="0 0 1120 1150">
<title>Desktop Gremlin expansion: actual app drawing</title>
<desc>Three staged frames exported from the current app's Tk Canvas on fake test terrain. No desktop capture.</desc>
<defs><clipPath id="frame"><rect width="1040" height="250"/></clipPath></defs>
<style>text {font-family: 'Segoe UI',sans-serif} .panel-title {fill:#F2F5FA;font-size:20px;font-weight:700} .caption {fill:#B7C7DD;font-size:13px} .label {fill:#CDD9EA;font-size:12px}</style>
<rect width="1120" height="1150" fill="#111A2A"/>
<text x="40" y="49" fill="#F4D087" font-size="13" font-weight="700" letter-spacing="2">DESKTOP GREMLIN / EXPANSION</text>
<text x="40" y="85" fill="#F3F6FD" font-size="30" font-weight="700">More ways to cause a little trouble.</text>
<text x="40" y="108" fill="#AEBFD6" font-size="14">Actual app drawing. Light bodies, size 1.0; staged on fake terrain in a withdrawn Tk window.</text>
''' + "\n".join(panels) + '''
<text x="40" y="1124" fill="#AEBFD6" font-size="12">%d real Canvas items across 3 frames. Characters, props, projectiles and effects come from production code.</text>
</svg>''' % total
        ET.fromstring(source)
        os.makedirs(os.path.dirname(DESTINATION), exist_ok=True)
        with open(DESTINATION, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(source)
        print(json.dumps({"output": DESTINATION, "panels": report,
                          "total_canvas_items": total, "withdrawn": app.root.state() == "withdrawn"}, indent=2))
    finally:
        if app is not None:
            app.clear_expansion()
        harness.teardown(gm, app)


if __name__ == "__main__":
    main()
