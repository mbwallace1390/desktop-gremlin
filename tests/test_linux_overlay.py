"""Portable shape checks plus real cross-process X11 mouse delivery.

Linux integration requires an isolated X server (the release workflow uses
Xvfb). It never sends synthetic input to the user's normal desktop.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import gremlin_x11_overlay as overlay
except ImportError:
    overlay = None


class FakeCanvas:
    def __init__(self, items):
        self.items = items

    def find_all(self):
        return tuple(self.items)

    def type(self, item):
        return self.items[item][0]

    def coords(self, item):
        return self.items[item][1]

    def itemcget(self, item, name):
        return self.items[item][2].get(name, "")

    def bbox(self, item):
        return self.items[item][2].get("bbox")


class ShapeGeometry(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(overlay, "X11 desktop overlay has not been implemented")

    def test_snapshot_excludes_hidden_and_unpainted_items(self):
        canvas = FakeCanvas({
            1: ("line", [1, 2, 10, 20], {"fill": "red", "width": "4"}),
            2: ("rectangle", [0, 0, 500, 500], {"state": "hidden", "fill": "red"}),
            3: ("oval", [20, 20, 40, 40], {}),
            4: ("text", [50, 50], {"fill": "white", "text": "Hi", "bbox": (45, 40, 60, 55)}),
        })
        commands = overlay.canvas_commands(canvas, 500, 500)
        self.assertEqual([c[0] for c in commands], ["line", "text"])
        self.assertEqual(commands[1][1], (45, 40, 60, 55))

    def test_hostile_nonfinite_or_excessive_geometry_fails_closed(self):
        canvas = FakeCanvas({1: ("line", [float("nan"), 1, 2, 3], {"fill": "red"})})
        with self.assertRaises(ValueError):
            overlay.canvas_commands(canvas, 300, 200)
        with self.assertRaises(ValueError):
            overlay.canvas_commands(FakeCanvas({}), 40000, 200)

    def test_clipping_preserves_long_cross_screen_projectile_lines(self):
        self.assertEqual(overlay.clip_line(-100000, 50, 100000, 50, 300, 200),
                         (0, 50, 300, 50))
        self.assertIsNone(overlay.clip_line(-20, -30, -5, -8, 300, 200))

    def test_fighter_input_regions_match_shared_picker_and_are_bounded(self):
        rects = overlay.fighter_regions([SimpleNamespace(x=110, y=154, sc=1)], 10, 20, 300, 200)
        self.assertEqual(rects, [(38, 38, 124, 124)])
        self.assertEqual(overlay.fighter_regions([SimpleNamespace(x=-9000, y=154, sc=1)],
                                               0, 0, 300, 200), [])

    def test_probe_refuses_normal_desktop_before_spawning_or_injecting(self):
        from gremlin_x11_probe import run_input_probe
        with patch.dict(os.environ, {"DISPLAY": ":0", "GREMLIN_ISOLATED_X11": ""}), \
                patch("gremlin_x11_probe.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(RuntimeError, "explicitly isolated"):
                run_input_probe(SimpleNamespace())
            spawn.assert_not_called()


@unittest.skipUnless(sys.platform.startswith("linux") and
                     os.environ.get("GREMLIN_ISOLATED_X11") == "1" and os.environ.get("DISPLAY"),
                     "requires explicitly isolated GREMLIN_ISOLATED_X11=1")
class X11Delivery(unittest.TestCase):
    def test_actual_cross_process_delivery(self):
        self.assertIsNotNone(overlay)
        _exercise_x11_delivery(self)


def _exercise_x11_delivery(case):
    import tkinter as tk
    from gremlin_x11_probe import run_input_probe
    from gremlin_x11 import X11Desktop
    # Production establishes Xlib threading/error dispatch before Tk starts.
    desktop = X11Desktop()
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry("480x360+0+0")
    canvas = tk.Canvas(root, width=480, height=360, bg="magenta", highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)
    fighter = SimpleNamespace(x=160, y=184, sc=1, grabbed=False)
    app = SimpleNamespace(root=root, canvas=canvas, fighters=[fighter], ox=0, oy=0, running=True)

    def down(event):
        if abs(event.x - fighter.x) < 62 and abs(event.y - (fighter.y - 34)) < 62:
            fighter.grabbed = True

    def drag(event):
        if fighter.grabbed:
            fighter.gx, fighter.gy = event.x, event.y

    def up(event):
        fighter.grabbed = False

    app.on_up = up
    canvas.bind("<ButtonPress-1>", down)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<ButtonRelease-1>", up)
    app.x11_overlay = overlay.X11Overlay(root, canvas, lambda: setattr(app, "running", False))
    try:
        case.assertFalse(root.winfo_ismapped(), "constructor must not map any overlay")
        checks = run_input_probe(app, emergency=False)
        case.assertTrue(all(checks.values()), checks)
        pixmaps = tuple(app.x11_overlay._pixmaps)
        for _ in range(20):
            case.assertTrue(app.x11_overlay.present(app.fighters, 0, 0))
        case.assertEqual(tuple(app.x11_overlay._pixmaps), pixmaps)
        case.assertEqual(len(app.x11_overlay._gcs), 2)
        # A real server-side BadDrawable must route to this connection's
        # handler even though Tk installed its own handler after the service.
        renderer = app.x11_overlay
        renderer.x.XFillRectangle(renderer.display, 0, renderer._gcs[0], 0, 0, 1, 1)
        case.assertFalse(renderer.present(app.fighters, 0, 0))
        root.update()
        case.assertFalse(root.winfo_ismapped())
        case.assertFalse(renderer.show())
        case.assertFalse(app.running)
        case.assertIn("X11 overlay request failed", renderer.error)
    finally:
        app.x11_overlay.close()
        root.destroy()
        desktop.close()


if __name__ == "__main__":
    unittest.main()
