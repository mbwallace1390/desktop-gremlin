"""Render the real native canvas to a PNG board, without reading the desktop."""
import os
import struct
import zlib
import harness

raise SystemExit("Native preview generation is disabled after the desktop input regression. "
                 "The existing preview is historical and is not a safety check.")

gm = harness.load("upgrade_preview", crowd=10, renderer="auto")
gm.virtual_screen = lambda: (0, 0, 1100, 580)
gm.monitors = lambda: [((0, 0, 1100, 580), (0, 0, 1100, 580))]
app = harness.build(gm)
harness.fake_terrain(app)


def write_png(path, width, height, bgra):
    def chunk(kind, data):
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind + data))
    rgba = bytearray(len(bgra))
    for i in range(0, len(bgra), 4):
        b, g, r, a = bgra[i:i + 4]
        rgba[i:i + 4] = bytes((r, g, b, a))
    rows = b"".join(b"\0" + rgba[y * width * 4:(y + 1) * width * 4] for y in range(height))
    with open(path, "wb") as out:
        out.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0))
                  + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


try:
    if not getattr(app.canvas, "native", None):
        raise RuntimeError("Native preview unavailable: " + getattr(app.canvas, "last_error", ""))
    app.root.withdraw()
    app.canvas.create_rectangle(0, 0, 1100, 290, fill="#ECF0F7", outline="", tags="board")
    app.canvas.create_rectangle(0, 290, 1100, 580, fill="#172131", outline="", tags="board")
    examples = [("walk", "sword", "Walking"), ("attack", "sword", "Sword windup"),
                ("attack", "bow", "Bow draw"), ("attack", "rocket", "Rocket recoil"),
                ("thrown", "pan", "Hit reaction")]
    app.time, app.sx, app.sy = 10., 0., 0.
    app._frame_begin()
    for row, theme in enumerate(("dark", "light")):
        ink = "#172131" if theme == "dark" else "#ECF0F7"
        gm.CFG.update(body_theme=theme, outline=bool(row), halo_strength=1.4 if row else 1.)
        app.canvas.create_text(35, row * 290 + 32, text=theme.title() + " body / " +
                               ("strong halo + outline" if row else "standard halo"),
                               font=("Segoe UI", 15), fill=ink, anchor="w", tags="board")
        for col, (state, weapon, label) in enumerate(examples):
            index = row * 5 + col
            f = app.fighters[index]
            f.x, f.y, f.sc, f.face = 105 + col * 220, 240 + row * 290, 1.65, 1
            f.state, f.st, f.weapon, f.walk, f.vx = state, 1., weapon, 1.2, 250.
            f.squash = f.tumble = f.stun = f.vy = 0.
            f.blink, f.hp, f.on_ground = 1., 100., True
            f.emote = f.play = f.pose_last = f.pose_from = None
            f.atk_dur, f.atk, f.aim = gm.ATKDUR[weapon], gm.ATKDUR[weapon] * (.68 if weapon == "rocket" else .38), -.1
            f.mood = ("bored", "furious", "smug", "hyped", "sulking")[col]
            f.hit_at, f.hit_power = (app.time - .05, .8) if state == "thrown" else (-1000., 0.)
            app.draw_fighter(f, index)
            app.canvas.create_text(f.x, 272 + row * 290, text=label, fill=ink,
                                   font=("Segoe UI", 11), tags="board")
    for tag in app._layers:
        app.canvas.tag_raise(tag)
    native = app.canvas.native
    native.render((app.canvas.items[i] for i in app.canvas.order), present=False)
    path = os.path.join(harness.ROOT, "docs", "upgrades.png")
    write_png(path, 1100, 580, native.capture())
    print(app.canvas.backend_name)
    print(path)
finally:
    harness.teardown(gm, app)
