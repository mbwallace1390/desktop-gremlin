"""Real impact, body-contact, drag and settings regressions on an isolated desktop."""
import math
import types
import unittest

import harness


class PhysicsUpgrade(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("physics_upgrade", crowd=3, react_to_windows=False)
        self.gm.monitors = lambda: [((0, 0, 1600, 1000), (0, 0, 1600, 960))]
        self.gm.virtual_screen = lambda: (0, 0, 1600, 1000)
        self.app = harness.build(self.gm)
        self.app.root.withdraw()
        harness.fake_terrain(self.app)
        self.app.decide = lambda f: None
        self.a, self.b, self.c = self.app.fighters
        for i, f in enumerate(self.app.fighters):
            f.x, f.y = 100. + i * 450, 400.
            f.vx = f.vy = 0.
            f.hp, f.on_ground = 100., False
            f.goal = f.blink = f.mood_check = 1000.
            f.set_state("idle")

    def tearDown(self):
        harness.teardown(self.gm, self.app)

    def test_hits_preserve_existing_momentum(self):
        self.b.vx = 100.
        self.app.hit_fighter(self.a, self.b, 10)
        first = self.b.vx
        self.b.vx = 300.
        self.b.hp = 100.
        self.app.hit_fighter(self.a, self.b, 10)
        self.assertAlmostEqual(self.b.vx - first, 200.)

    def test_impacts_follow_incoming_direction_and_weight(self):
        self.app.impact_fighter(self.a, self.b, 10, direction=(-1, .1))
        self.assertLess(self.b.vx, 0, "a returning shot must push toward its shooter")
        light = abs(self.b.vx)
        self.b.vx = self.b.vy = 0.
        self.b.physics_mass = 2.
        self.app.impact_fighter(self.a, self.b, 10, direction=(-1, .1))
        self.assertLess(abs(self.b.vx), light)

    def test_blast_direction_and_falloff(self):
        self.b.x, self.c.x = 560., 660.
        self.b.y = self.c.y = 400.
        self.app.blast_fighters(self.a, 540., 400. - 30 * self.b.sc, 160., 26)
        self.assertGreater(self.b.vx, self.c.vx)
        self.assertLess(self.b.hp, self.c.hp)
        self.b.hp, self.b.x, self.b.vx, self.b.vy = 100., 520., 0., 0.
        self.app.blast_fighters(self.a, 540., 400. - 30 * self.b.sc, 160., 26)
        self.assertLess(self.b.vx, 0, "blast center, not owner, determines force direction")

    def test_swept_feet_catch_narrow_platform(self):
        harness.fake_terrain(self.app, icons=[("Narrow", 253, 520, 267, 570, 8)])
        f = self.b
        f.x, f.y, f.vx, f.vy = 200., 490., 6000., 3000.
        f.set_state("fall")
        self.app.physics(f, 1 / 60., 960.)
        self.assertEqual(f.plat, ("icon", 8))
        self.assertEqual(f.y, 520.)
        self.assertLess(f.x, 280.)

    def test_thrown_body_hits_window_side(self):
        harness.fake_terrain(self.app, windows=[("Wall", 500, 200, 750, 800, 42)])
        f = self.b
        f.x, f.y, f.vx, f.vy = 470., 430., 3000., 0.
        f.set_state("thrown")
        self.app.physics(f, 1 / 60., 960.)
        self.assertLess(f.x, 500.)
        self.assertLess(f.vx, 0.)

    def test_wrap_cannot_sweep_through_unrelated_platform(self):
        harness.fake_terrain(self.app, icons=[("Across screen", 875, 510, 930, 570, 8)])
        f = self.b
        f.x, f.y, f.vx, f.vy = 1600. + self.gm.WRAP + 1, 500., 0., 1000.
        f.set_state("fall")
        self.app.physics(f, .02, 960.)
        self.assertEqual(f.x, 24.)
        self.assertIsNone(f.plat)

    def test_walking_can_leave_platform_edge(self):
        harness.fake_terrain(self.app, icons=[("Edge", 500, 520, 600, 570, 8)])
        f = self.b
        f.x, f.y, f.vx, f.vy = 604., 520., 200., 0.
        f.on_ground, f.plat = True, ("icon", 8)
        f.set_state("walk")
        self.app.physics(f, .02, 960.)
        self.assertGreater(f.x, 606.)
        self.assertFalse(f.on_ground)

    def test_surface_material_changes_sliding(self):
        f = self.b
        speeds = []
        for material in ("sticky", "standard", "ice"):
            self.gm.CFG["surface_material"] = material
            f.x, f.y, f.vx, f.vy = 600., 960., 200., 0.
            f.on_ground = True
            f.set_state("idle")
            self.app.physics(f, 1 / 60., 960.)
            speeds.append(f.vx)
        self.assertLess(speeds[0], speeds[1])
        self.assertLess(speeds[1], speeds[2])

    def test_grab_point_and_spring_have_inertia(self):
        f = self.b
        self.app.on_down(types.SimpleNamespace(x=f.x + 6, y=f.y - 25 * f.sc))
        self.assertAlmostEqual(f.gy, f.y, msg="grabbing the torso must not snap to the head")
        self.app.on_drag(types.SimpleNamespace(x=f.x + 120, y=f.y - 25 * f.sc))
        self.app.update_fighter(f, 1 / 60.)
        self.assertGreater(f.vx, 0.)
        self.assertLess(f.x, f.gx)

    def test_throw_uses_recent_motion_not_last_zero_sample(self):
        f = self.b
        self.app.on_down(types.SimpleNamespace(x=f.x, y=f.y - 30 * f.sc))
        for t, x in ((0., 550.), (.04, 580.), (.08, 610.), (.09, 610.)):
            self.app.record_cursor_sample(x, 380., t)
        self.app.mouse["vx"] = self.app.mouse["vy"] = 0.
        self.app.on_up(None)
        self.assertGreater(f.vx, 150.)
        self.assertTrue(math.isfinite(f.vr))

    def test_presets_are_real_and_settings_round_trip(self):
        f = self.b
        velocities = []
        for name in ("moon", "normal", "heavy"):
            self.gm.CFG["physics_preset"] = name
            f.x, f.y, f.vx, f.vy = 600., 400., 0., 0.
            f.set_state("fall")
            self.app.physics(f, 1 / 60., 960.)
            velocities.append(f.vy)
        self.assertLess(velocities[0], velocities[1])
        self.assertLess(velocities[1], velocities[2])
        self.gm.CFG.update(surface_material="rubber", physics_preset="moon")
        self.assertTrue(self.gm.save_settings(self.gm.CFG))
        loaded = self.gm.load_settings()
        self.assertEqual((loaded["surface_material"], loaded["physics_preset"]), ("rubber", "moon"))


if __name__ == "__main__":
    unittest.main()
