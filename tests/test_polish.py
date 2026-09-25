"""Name tags, bows, speech bubbles, big grabs, toys, sleep, icons, Settings.

Every one of these was wrong on screen while every other check stayed green:
two names drawn over each other under the cursor, a bow drawn as a ring round
the fist, a speech-bubble tail three pixels long, big gremlins that could only
be grabbed by the hips, toy captions printed onto the desktop, a 16 px tray
icon stretched to 20 px at 125% scaling, and a Settings window framed in
native white. Each check reads what was actually drawn or built -- canvas
items, icon bytes, window icons, widget styles -- never the arithmetic that
produced it.
"""
import math
import os
import random
import struct
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

if sys.platform == "linux" and os.environ.get("GREMLIN_ISOLATED_X11") != "1":
    raise SystemExit("Run Linux visual checks on isolated Xvfb with GREMLIN_ISOLATED_X11=1.")

gm = harness.load("polish", crowd=3)
WINDOWS = gm.IS_WINDOWS
gm.monitors = lambda: [((0, 0, 1280, 900), (0, 0, 1280, 860))]
gm.virtual_screen = lambda: (0, 0, 1280, 900)

# The tray asks for its icon while App is built; record the size it wants.
loads = []
_real_load = gm.win32gui.LoadImage if WINDOWS else None


def _spy_load(*args):
    loads.append(args)
    return _real_load(*args)


if WINDOWS:
    gm.win32gui.LoadImage = _spy_load
try:
    app = harness.build(gm)
finally:
    if WINDOWS:
        gm.win32gui.LoadImage = _real_load
harness.fake_terrain(app)
FLOOR = 860
DARK = "#0C1024"
if WINDOWS:
    SM_SMALL = (gm.win32api.GetSystemMetrics(gm.win32con.SM_CXSMICON),
                gm.win32api.GetSystemMetrics(gm.win32con.SM_CYSMICON))
    SM_BIG = gm.win32api.GetSystemMetrics(gm.win32con.SM_CXICON)
bad = []


def check(label, ok):
    print("%-60s %s" % (label, "pass" if ok else "FAIL"))
    if not ok:
        bad.append(label)


def park(f, x, sc=.68, y=FLOOR):
    f.x, f.y, f.face, f.sc = float(x), float(y), 1, sc
    f.state, f.st, f.walk, f.mood = "idle", 1., 0., "bored"
    f.squash = f.tumble = f.stun = f.vx = f.vy = f.vr = 0.
    f.blink, f.hp, f.on_ground, f.grabbed = 1., 100., True, False
    f.emote, f.emote_t = None, 0.
    f.play = f.pose_last = f.pose_from = f.carry = None
    f.hit_at, f.hit_power = -1000., 0.
    f.foe, f.target, f.mode = None, None, "roam"


def park_all():
    app.time, app.shake_t, app.sx, app.sy = 10., 0., 0., 0.
    app.hover = None
    for i, f in enumerate(app.fighters):
        park(f, 150 + i * 420)


def visible(tag=None, kind=None):
    found = []
    for it in (app.canvas.find_withtag(tag) if tag else app.canvas.find_all()):
        if app.canvas.itemcget(it, "state") == "hidden":
            continue
        if kind and app.canvas.type(it) != kind:
            continue
        found.append(it)
    return found


def texts():
    return [app.canvas.itemcget(it, "text") for it in visible(kind="text")]


def points(it):
    co = app.canvas.coords(it)
    return [(co[i], co[i + 1]) for i in range(0, len(co), 2)]


def inside(inner, outer, slack=0.):
    return (outer[0] - slack <= inner[0] and outer[1] - slack <= inner[1] and
            inner[2] <= outer[2] + slack and inner[3] <= outer[3] + slack)


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def head_of(fi):
    """The drawn head oval: centre, radius and top, canvas coordinates."""
    co = app.canvas.coords(visible(app._ftag[fi][1], "oval")[-1])
    return ((co[0] + co[2]) / 2, (co[1] + co[3]) / 2, (co[2] - co[0]) / 2, co[1])


def name_items(f):
    """(his coloured name, its dark outline copies), as drawn."""
    items = [it for it in visible(kind="text")
             if app.canvas.itemcget(it, "text") == f.nickname]
    main = [it for it in items if app.canvas.itemcget(it, "fill") == f.color()]
    outline = [it for it in items if app.canvas.itemcget(it, "fill") == DARK]
    return main, outline


def bubble_of(fi):
    """(outline points, body bottom, tail tip) of one fighter's bubble."""
    if not WINDOWS:
        plates = visible(app._ftag[fi][7], "rectangle")
        tails = visible(app._ftag[fi][7], "line")
        if len(plates) != 1 or len(tails) != 1:
            return None
        x0, y0, x1, y1 = app.canvas.coords(plates[0])
        tip = points(tails[0])[-1]
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), tip], y1, tip
    shape = visible(app._ftag[fi][7], "polygon")
    if len(shape) != 1:
        return None
    pts = points(shape[0])
    tip = max(pts, key=lambda p: p[1])
    body = max(p[1] for p in pts if abs(p[1] - tip[1]) > .5)
    return pts, body, tip


f0, f1, f2 = app.fighters
PHYS = gm.PHYSICS
pick_radius = getattr(PHYS, "pick_radius", None)

# --- 1. one name under the cursor, centred, outlined, on the screen --------
park_all()
app.hover = f0
app.draw()
names = texts()
main, outline = name_items(f0)
check("hover names him once, in his colour", set(names) == {f0.nickname} and len(main) == 1)
check("no second 'the ...' label under the cursor",
      not any(t.startswith("the ") for t in names))
if main:
    bb = app.canvas.bbox(main[0])
    check("name is centred under him", abs((bb[0] + bb[2]) / 2 - (f0.x - app.ox)) <= 2)
    mx, my = app.canvas.coords(main[0])
    offsets = sorted((round(app.canvas.coords(it)[0] - mx), round(app.canvas.coords(it)[1] - my))
                     for it in outline)
    if WINDOWS:
        check("its letters carry a one-pixel dark outline",
              offsets == [(-1, 0), (0, -1), (0, 1), (1, 0)])
if WINDOWS:
    check("no solid plate under his feet to catch clicks",
          not visible(app._ftag[0][7]) and not visible(app._ftag[0][8], "rectangle")
          and not visible(app._ftag[0][8], "polygon"))
else:
    check("Linux name has its intentional contrasting plate",
          len(visible(app._ftag[0][8], "rectangle")) == 1)
f0.grabbed, app.hover = True, None
app.draw()
main, outline = name_items(f0)
check("grabbed shows the same single name", set(texts()) == {f0.nickname} and len(main) == 1)
f0.grabbed = False
edges = []
for x, y in ((0., FLOOR), (2., FLOOR), (1278., FLOOR), (1280., FLOOR), (640., 899.)):
    park_all()
    park(f0, x, y=y)
    app.hover = f0
    app.draw()
    main, _ = name_items(f0)
    bb = app.canvas.bbox(main[0]) if main else (-1, -1, -1, -1)
    edges.append(0 <= bb[0] and bb[2] <= app.W and bb[3] <= app.H)
check("the name stays on the screen at both sides and the bottom", all(edges))

# --- 2. a bow held by its grip ---------------------------------------------
park_all()
f0.sc = 1.0
f0.target = {"kind": "icon", "key": 0, "cx": f0.x + 420., "cy": f0.y - 120.,
             "top": f0.y - 150., "name": "x", "w": 64, "h": 64}
f0.plan = "bow"
f0.per = dict(f0.per, weapons=tuple(gm.WEAPONS))
app.start_attack(f0)
release = gm.RELEASE_AT.get("bow", .55)


def bow_parts(frac):
    f0.atk = frac * release * f0.atk_dur
    app.draw()
    tb, ta, tw, twd = (app._ftag[0][i] for i in (0, 3, 4, 5))
    front = points(visible(tb, "line")[2])[-1]       # left arm, as drawn
    rear = points(visible(ta, "line")[0])[-1]        # right arm, as drawn
    lines = sorted((points(it) for it in visible(tw, "line")), key=len)
    return front, rear, lines, visible(twd, "oval")


front, rear, lines, tips = bow_parts(.6)
arc = lines[-1] if lines else []
check("bow is a nine-point arc", len(arc) == 9)
if len(arc) == 9:
    grip = arc[4]
    check("the grip, mid-arc, is in the front hand", math.dist(grip, front) < .75)
    ax, ay = math.cos(f0.aim), math.sin(f0.aim)
    check("both limb tips sweep back behind the grip",
          all((p[0] - grip[0]) * ax + (p[1] - grip[1]) * ay < -2 for p in (arc[0], arc[-1])))
    string = [ln for ln in lines if len(ln) == 3]
    check("the string is drawn back to the draw hand",
          len(string) == 1 and math.dist(string[0][1], rear) < .75)
    arrow = [ln for ln in lines if len(ln) == 2]
    check("an arrow is nocked while drawing", len(arrow) == 1 and len(tips) == 1
          and math.dist(arrow[0][0], rear) < .75)
    muzzle = app.muzzle(f0)
    check("the arrow leaves from the grip",
          math.dist((muzzle[0] - app.ox, muzzle[1] - app.oy), grip) < .75)
shafts = []
for frac in (.1, .5, .95):
    _front, _rear, drawing, _tips = bow_parts(frac)
    shafts += [math.dist(*ln) for ln in drawing if len(ln) == 2]
check("the nocked arrow keeps its length as he draws",
      len(shafts) == 3 and max(shafts) - min(shafts) < .75)
_front, _rear, lines, tips = bow_parts(1.3)
check("after release the string is straight and the hand empty",
      not [ln for ln in lines if len(ln) == 2] and not tips
      and all(len(ln) != 3 or math.dist(ln[1], ((ln[0][0] + ln[2][0]) / 2,
                                                (ln[0][1] + ln[2][1]) / 2)) < .75
              for ln in lines))

# --- 3. speech bubbles: a body round the words, a tail at the speaker ------
park_all()
f0.say("hm. this place.", 3.)
app.draw()
bubble = bubble_of(0)
words = visible(app._ftag[0][8], "text")
check("a speech bubble has one body and its words", bubble is not None and len(words) == 1)
if bubble is not None and len(words) == 1:
    hx, hy, hr, top = head_of(0)
    shape, body_bottom, tip = bubble
    check("the words sit inside the bubble",
          inside(app.canvas.bbox(words[0]), app.canvas.bbox(visible(app._ftag[0][7])[0])))
    check("the tail is long enough to see", tip[1] - body_bottom >= 4)
    check("the tail points at the speaker's head",
          tip[1] <= top + 1 and abs(tip[0] - hx) <= hr + 6)

aimed = []
for x in (0., 2., 1278., 1280.):
    park_all()
    park(f0, x)
    f0.say("you again? really?", 3.)
    app.draw()
    hx, hy, hr, top = head_of(0)
    bubble = bubble_of(0)
    aimed.append(bubble is not None and bubble[2][1] <= top + 1
                 and abs(bubble[2][0] - hx) <= hr + 6)
check("the tail still finds him at the edges of the screen", all(aimed))

park_all()
f0.foe, f0.hp = f1, 50.
f0.say("properly this time", 3.)
app.draw()
bar = [app.canvas.coords(it) for it in visible(app._ftag[0][6], "rectangle")]
bubble = bubble_of(0)
check("a bubble keeps clear of his health bar", bar and bubble is not None
      and bubble[1] < min(co[1] for co in bar) - 2 and bubble[2][1] <= min(co[1] for co in bar) + 1)

park_all()
f0.state, f0.on_ground = "thrown", False
f0.say("wheeee", 3.)
spots = []
for step in range(8):
    f0.tumble = step * math.pi / 4
    app.draw()
    bubble = bubble_of(0)
    spots.append(app.canvas.bbox(visible(app._ftag[0][7])[0]) if bubble else None)
check("a spinning gremlin's bubble stays where it is",
      None not in spots and max(abs(a - b) for s in spots for a, b in zip(s, spots[0])) <= 1)

park_all()
park(f0, 400)
park(f1, 470)
f1.say("you again? really?", 3.)
app.draw()
before = app.canvas.bbox(visible(app._ftag[1][7])[0])
f0.say("properly this time", 3.)
app.draw()
after = app.canvas.bbox(visible(app._ftag[1][7])[0])
first = visible(app._ftag[0][7])
check("the bubble already showing keeps its place when a neighbour speaks",
      before == after and first and not overlap(app.canvas.bbox(first[0]), after))

rng = random.Random(4242)
lines_said = [ln for kind in gm.ROSTER for ev in ("hello", "revenge", "gangup", "perch")
              for ln in gm.VOICES[kind].get(ev, ())]
clashes = offscreen = 0
for case in range(400):
    park_all()
    sc = rng.choice((.5, .68, 1., 1.6))
    y = FLOOR if case % 2 else rng.uniform(30, FLOOR)   # half of them perched high
    park(f0, rng.uniform(0, 1280), sc, y)
    park(f1, f0.x + rng.uniform(-150, 150), sc, y)
    park(f2, 1500, sc)                     # out of the way
    first, second = (f0, f1) if rng.random() < .5 else (f1, f0)
    for f in (first, second):
        f.say(rng.choice(lines_said).format(runs=3, throws=4, wins=1, losses=2,
                                            name="Steam"), 3.)
    app.draw()
    shape_kind = "polygon" if WINDOWS else "rectangle"
    boxes = [app.canvas.bbox(visible(app._ftag[i][7], shape_kind)[0])
             for i in (0, 1) if visible(app._ftag[i][7], shape_kind)]
    if len(boxes) != 2 or overlap(*boxes):
        clashes += 1
    for i in (0, 1):
        shape = bubble_of(i)
        # the body; a tail may point after a speaker who has walked off it
        body = [p for p in shape[0] if p[1] <= shape[1] + .5] if shape else []
        if body and (min(p[0] for p in body) < 0 or max(p[0] for p in body) > app.W
                     or min(p[1] for p in body) < 0):
            offscreen += 1
check("neighbours' bubbles never overlap, low or high (400 random pairs)", clashes == 0)
check("no bubble pushed off the screen", offscreen == 0)

# --- 4. big gremlins can be grabbed by the head and the feet ---------------
park_all()
check("grab radius is shared through gremlin_physics", callable(pick_radius))
if callable(pick_radius):
    check("default sizes keep the old 62 px grab radius",
          all(pick_radius(s) == 62 for s in (.35, .68, 1., 1.2)))
park(f0, 600, 2.5)
park(f1, 1100)                       # nobody else within reach of the cursor
park(f2, 1240)
app.draw()
hx, hy, hr, top = head_of(0)
check("size 2.5: pointing at his head finds him",
      app.near_fighter(hx + app.ox, hy + app.oy) is f0)
check("size 2.5: pointing at his feet finds him",
      app.near_fighter(f0.x, f0.y - 3) is f0)
app.on_down(SimpleNamespace(x=hx, y=hy))
check("size 2.5: a click on his head grabs him", f0.grabbed)
app.on_up(SimpleNamespace(x=hx, y=hy))
park_all()
park(f0, 600, .68)
park(f1, 1100)
park(f2, 1240)
check("size 0.68: 61 px from the hip grabs, 63 px does not",
      app.near_fighter(f0.x + 61, f0.y - 34 * f0.sc) is f0
      and app.near_fighter(f0.x + 63, f0.y - 34 * f0.sc) is None)


def rings(sc):
    park_all()
    park(f0, 600, sc)
    app.hover = f0
    app.draw()
    return sorted(((app.canvas.coords(it)[2] - app.canvas.coords(it)[0]) / 2,
                   float(app.canvas.itemcget(it, "width"))) for it in visible("hover", "oval"))


small, big = rings(.68), rings(2.5)
check("grab rings keep their size and weight by default",
      [(round(r), w) for r, w in small] == [(18, 5.0), (36, 7.0)])
check("grab rings grow with a big gremlin", big and small and big[-1][0] > small[-1][0] * 1.6)
import gremlin_x11_overlay as overlay  # noqa: E402
if callable(pick_radius):
    regions_ok = True
    for sc in (.35, .68, 1., 1.6, 2.5):
        r = pick_radius(sc)
        got = overlay.fighter_regions([SimpleNamespace(x=500., y=700., sc=sc)], 0, 0, 3000, 3000)
        want = [(int(round(500 - r)), int(round(700 - 34 * sc - r)),
                 int(round(2 * r)), int(round(2 * r)))]
        regions_ok = regions_ok and got == want
    check("Linux input regions use the same grab radius", regions_ok)

# --- 5. toys carry no captions ---------------------------------------------
park_all()
gm.CFG["toy_props"] = True
try:
    made = [app.motion.add_prop(k, x, FLOOR) for k, x in
            (("crate", 200), ("seesaw", 420), ("ramp", 640), ("fan", 860), ("conveyor", 1080))]
    app.draw()
    check("toys are drawn", all(made) and visible("toys"))
    check("toys print no captions on the desktop", not visible("toys", "text"))
finally:
    app.motion.props.clear()
    gm.CFG["toy_props"] = False

# --- 6. a sleeper snores ----------------------------------------------------
park_all()
f0.state, f0.mood = "sleep", "asleep"
app.draw()
hx, hy, hr, top = head_of(0)
zs = [points(it) for it in visible(app._ftag[0][6], "line")]
check("a sleeper has z's drifting over his head",
      len([z for z in zs if len(z) == 4 and max(p[1] for p in z) < top]) >= 2)
park_all()
app.draw()
check("nobody awake snores", not visible(app._ftag[0][6], "line"))

# --- 7. the drawing X11 needs ---------------------------------------------
# Windows additionally exercises the fallback drawing branch. On Linux these
# are real shaped-window frames: do not replace or stub out X11 presentation.
gm.IS_WINDOWS = False
try:
    park_all()
    f0.say("hm. this place.", 3.)
    app.hover = f1
    # A screen shake moves everything drawn, so the tail has to move with it.
    app.fx_random.seed(7)
    app.shake_t, app.shake_m = .4, 20.
    app.draw()
    shaken = abs(app.sx) > 2 or abs(app.sy) > 2
    app.shake_t = app.shake_m = 0.
    hx, hy, hr, top = head_of(0)
    plates = visible(app._ftag[0][7], "rectangle")
    tails = [points(it) for it in visible(app._ftag[0][7], "line")]
    check("Linux: nothing reaches the X11 shape as a polygon", not visible(kind="polygon"))
    check("Linux: the bubble is a plate with a tail at his head, shaken or not",
          shaken and len(plates) == 1 and len(tails) == 1
          and math.dist(tails[0][-1], (hx, top - 1)) < 1.5)
    check("Linux: the name keeps its label plate",
          len(visible(app._ftag[1][8], "rectangle")) == 1 and name_items(f1)[0])
finally:
    gm.IS_WINDOWS = WINDOWS
park_all()
app.draw()
if not WINDOWS:
    check("Linux visual frames reach the real X11 shape presenter",
          app.x11_overlay is not None and
          app.x11_overlay.present(app.fighters, app.ox, app.oy) and
          not app.x11_overlay.failed)


# --- 8. crisp icons at every scaling ----------------------------------------
def ico_images(path):
    with open(path, "rb") as stream:
        data = stream.read()
    _reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    images = {}
    for i in range(count):
        w, h, _c, _r, _planes, _bpp, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        blob = data[offset:offset + size]
        w, h = w or 256, h or 256
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            pw, ph = struct.unpack(">II", blob[16:24])
            images[w] = ("png", pw == w and ph == h, 1, 1)
            continue
        hdr = struct.unpack_from("<IiiHHIIiiII", blob, 0)
        pixels = blob[40:40 + w * h * 4]
        alpha = [pixels[j + 3] for j in range(0, len(pixels), 4)]
        images[w] = ("bmp", hdr[1] == w and hdr[2] == 2 * h and hdr[4] == 32,
                     sum(1 for a in alpha if a > 200), sum(1 for a in alpha if a == 0))
    return kind, images


path = harness.scratch("polish", "check.ico")
gm._write_ico(path, sizes=gm.ICON_SIZES)
kind, images = ico_images(path)
check("every scaling step's small icon is in the full set",
      kind == 1 and all(s in images for s in (16, 20, 24, 28, 32, 36, 40, 48, 56, 64, 72, 80)))
check("every image has the right size and a visible figure",
      all(images[s][1] and images[s][2] > s and images[s][3] > s for s in images))
os.remove(path)
if WINDOWS:
    kind, images = ico_images(gm.ICON_PATH)
    wants = getattr(gm, "tray_icon_sizes", lambda: ())()
    check("the tray's file carries this machine's exact sizes (%d, %d)" % (SM_SMALL[0], SM_BIG),
          set(images) == set(wants) and SM_SMALL[0] in images and SM_BIG in images)
    check("the tray loads the system small-icon size (%dx%d)" % SM_SMALL,
          bool(loads) and tuple(loads[0][3:5]) == SM_SMALL)
app_ico = os.path.join(harness.ROOT, "packaging", "app.ico")
kind, images = ico_images(app_ico)
check("the EXE icon carries 16 to 256 px",
      all(s in images and images[s][1] for s in gm.ICON_SIZES + (256,)))


# --- 9. a Settings window that is dark all the way through -----------------
def icon_px(hwnd, which):
    handle = gm.win32gui.SendMessage(hwnd, gm.win32con.WM_GETICON, which, 0)
    if not handle:
        return 0
    info = gm.win32gui.GetIconInfo(handle)
    try:
        return gm.win32gui.GetObject(info[4]).bmWidth
    finally:
        for bitmap in info[3:5]:
            if bitmap:
                gm.win32gui.DeleteObject(bitmap)


app.open_settings()
sw = app.settings_win
sw.win.update()
style = gm.ttk.Style(app.root)
dark = ("#171b2c", "#0e1120", "#232a45", "#2a3150")
if WINDOWS:
    check("Settings tabs and choices use the dark theme", style.theme_use() == "clam"
          and str(style.lookup("TNotebook", "background")).lower() in dark
          and str(style.lookup("TCombobox", "fieldbackground")).lower() in dark)
    check("the selected tab keeps its width",
          str(style.lookup("TNotebook.Tab", "padding", ("selected",)))
          == str(style.lookup("TNotebook.Tab", "padding")))


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


book = [w for w in descendants(sw.win) if w.winfo_class() == "TNotebook"][0]
cast = [book.nametowidget(t) for t in book.tabs() if book.tab(t, "text") == "Cast"][0]
check("the Cast tab has no light native frame",
      not [w for w in descendants(cast) if w.winfo_class() == "TFrame"])
check("Settings wears the gremlin icon", getattr(sw.win, "gremlin_icon", None) is not None)
if WINDOWS:
    frame = int(sw.win.wm_frame(), 16)
    check("its title bar and taskbar icons are this scaling's exact sizes",
          (icon_px(frame, 0), icon_px(frame, 1)) == (SM_SMALL[0], SM_BIG))
sw.close()
hidden = gm.SettingsWindow(app.root, app)
shown = hidden.win.winfo_ismapped()
hidden.win.withdraw()
hidden.win.update()
check("a Settings window withdrawn at once is never shown",
      not shown and not hidden.win.winfo_ismapped())
hidden.close()
app.open_performance()
app.performance_win.update()
check("Performance wears the gremlin icon",
      getattr(app.performance_win, "gremlin_icon", None) is not None)
app.close_performance()

print("\n" + ("FAIL: " + "; ".join(bad) if bad else "PASS"))
harness.finish(gm, app, bad)
