"""Stress the integrated physics presets through real isolated simulation/rendering."""
import math
import random
import unittest

import harness


class MixedPhysics(unittest.TestCase):
    def test_presets_materials_sizes_and_cleanup(self):
        for scale in (.35, .68, 2.5):
            gm = harness.load("physics_mixed", crowd=10, scale=scale, toy_props=True,
                              parkour=True, group_scenes=True, react_to_windows=False)
            gm.monitors = lambda: [((-900, 0, 700, 1000), (-900, 0, 700, 960))]
            gm.virtual_screen = lambda: (-900, 0, 1600, 1000)
            app = harness.build(gm)
            app.root.withdraw()
            try:
                random.seed(9182)
                harness.fake_terrain(app, windows=[("shelf", -650, 540, -150, 780, 41)])
                app.terrain_changed()
                for preset, material in (("normal", "standard"), ("moon", "ice"),
                                         ("bouncy", "rubber"), ("heavy", "sticky")):
                    with self.subTest(scale=scale, preset=preset, material=material):
                        app.set_held(False)
                        gm.CFG.update(physics_preset=preset, surface_material=material)
                        app.apply_settings()
                        for i, actor in enumerate(app.fighters):
                            app.clear_expansion(actor)
                            actor.x, actor.y = -800 + i * 140, 400.
                            actor.vx, actor.vy = (-1 if i % 2 else 1) * 220, -100.
                            actor.hp, actor.grabbed, actor.on_ground = 100., False, False
                            actor.set_state("thrown")
                        app.motion.add_prop("crate", -100, 850)
                        app.motion.add_prop("crate", -100, 650)
                        app.motion.add_prop("seesaw", 350, 960)
                        for frame in range(900):
                            app.update(gm.SIM_STEP)
                            for actor in app.fighters:
                                self.assertTrue(all(math.isfinite(v) for v in
                                    (actor.x, actor.y, actor.vx, actor.vy, actor.vr, actor.tumble)))
                            for prop in app.motion.props:
                                self.assertTrue(all(math.isfinite(prop[k]) for k in
                                    ("x", "y", "vx", "vy", "angle", "omega")))
                            self.assertLessEqual(len(app.motion.props), 6)
                            self.assertLessEqual(len(app.arsenal.shots), 32)
                            if frame % 60 == 0:
                                app.draw()
                                self.assertTrue(all(math.isfinite(v) for item in app.canvas.find_all()
                                                    for v in app.canvas.coords(item)))
                        app.set_held(True)
                        self.assertFalse(app.motion.props or app.motion.actions or app.arsenal.shots)
            finally:
                harness.teardown(gm, app)


if __name__ == "__main__":
    unittest.main()
