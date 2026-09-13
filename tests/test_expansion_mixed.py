"""All production feature flags together, with the real loop and owned Canvas."""
import json
import math
import random
import unittest
from unittest import mock

import harness


class MixedExpansion(unittest.TestCase):
    def test_long_sessions_modes_and_removal(self):
        observed = set()
        for crowd, scale, fps in ((1, .35, 15), (4, .68, 40), (10, 2.5, 60)):
            with self.subTest(crowd=crowd, scale=scale, fps=fps):
                gm = harness.load("expansion_mixed", crowd=crowd, scale=scale,
                                  fps=fps, group_scenes=True, parkour=True,
                                  toy_props=True, react_to_windows=False)
                app = None
                original = gm.tk.Tk

                def owned_root():
                    root = original()
                    root.withdraw()
                    return root

                try:
                    random.seed(900 + crowd)
                    with mock.patch.object(gm.tk, "Tk", owned_root), \
                            mock.patch.object(gm, "virtual_screen", return_value=(0, 0, 1600, 1000)), \
                            mock.patch.object(gm, "monitors", return_value=[
                                ((0, 0, 1600, 1000), (0, 0, 1600, 960))]):
                        app = harness.build(gm)
                    harness.fake_terrain(app, windows=[
                        ("Test ledge", 200, 560, 650, 820, 101),
                        ("Test high ledge", 900, 300, 1450, 700, 102)])
                    app.terrain_changed()
                    for frame in range(7200):
                        if frame in (2400, 4800):
                            gm.CFG["play_mode"] = "peaceful" if frame == 2400 else "battle"
                            app.apply_settings()
                        app.update(1 / 60)
                        observed.update(s["kind"] for s in app.social.scenes)
                        observed.update(a["kind"] for a in app.motion.actions.values())
                        observed.update(p["kind"] for p in app.motion.props)
                        observed.update(s["k"] for s in app.arsenal.shots)
                        self.assertLessEqual(len(app.arsenal.shots), 32)
                        self.assertLessEqual(len(app.motion.props), 6)
                        self.assertLessEqual(len(app.social.scenes), 2)
                        self.assertLessEqual(len(gm.MEM["relationships"]), 45)
                        for f in app.fighters:
                            self.assertTrue(all(math.isfinite(v) for v in
                                                (f.x, f.y, f.vx, f.vy, f.hp)))
                            self.assertFalse(f.state == "effect" and not app.arsenal.effects.get(f))
                            self.assertFalse(f.state == "social" and f not in app.social.owned)
                            self.assertFalse(f.state == "parkour" and f not in app.motion.actions)
                        if gm.CFG["play_mode"] == "peaceful":
                            self.assertFalse(app.shots or app.arsenal.shots)
                            self.assertFalse(any(f.state in ("attack", "fight") or
                                                 (f.state == "hunt" and not f.play) for f in app.fighters),
                                             [(frame, f.kind, f.state, f.mode, f.play) for f in app.fighters])
                        if frame % 60 == 0:
                            app.draw()
                    gm.CFG["cast"] = app.fighters[-1].kind
                    app.apply_settings()
                    app.update(1 / 60)
                    self.assertEqual(len(app.fighters), 1)
                    self.assertTrue(all(f in app.fighters for f in app.arsenal.effects))
                    self.assertTrue(all(f in app.fighters for f in app.motion.actions))
                    self.assertTrue(all(f in app.fighters for f in app.social.owned))
                    app.set_held(True)
                    self.assertFalse(app.arsenal.shots or app.arsenal.effects or app.motion.actions
                                     or app.motion.props or app.social.scenes)
                    self.assertEqual(app.renderer_mode, "tk" if gm.IS_WINDOWS else "x11")
                finally:
                    harness.teardown(gm, app)
        self.assertTrue(observed.intersection(("cards", "coffee", "juggling", "blanket_nap")))
        self.assertIn("crate", observed)
        with open(harness.scratch("expansion", "observed.json"), "w", encoding="utf-8") as out:
            json.dump(sorted(observed), out, indent=2)


if __name__ == "__main__":
    unittest.main()
