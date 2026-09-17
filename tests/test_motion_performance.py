"""Geometry reuse and sleeping support invalidation on an isolated desktop."""
import math
import unittest
from unittest.mock import patch

import harness


class MotionPerformance(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("motion_performance", crowd=1, scale=1.0,
                               toy_props=True, react_to_windows=False)
        self.gm.monitors = lambda: [((0, 0, 1600, 1000), (0, 0, 1600, 960))]
        self.gm.virtual_screen = lambda: (0, 0, 1600, 1000)
        self.app = harness.build(self.gm)
        self.app.root.withdraw()
        harness.fake_terrain(self.app)
        self.engine = self.app.motion
        self.app.fighters[0].hp = 0

    def tearDown(self):
        harness.teardown(self.gm, self.app)

    def crate(self, x=400., y=500.):
        prop = self.engine.add_prop("crate", x, y)
        self.assertIsNotNone(prop)
        return prop

    def sleeping_platform_crate(self):
        harness.fake_terrain(self.app, windows=[("Support", 320, 500, 480, 600, 42)])
        prop = self.crate()
        prop.update(sleeping=True, support=("window", 42))
        self.engine._crate_step(prop, 1 / 120)
        self.assertTrue(prop["sleeping"])
        return prop

    def test_platforms_reuse_heights_and_preserve_public_list_ownership(self):
        prop = self.crate()
        with patch.object(self.engine, "_height", wraps=self.engine._height) as height:
            expected = self.engine.platforms()
            initial = height.call_count
            self.assertGreater(initial, 0)
            for _ in range(20):
                self.assertEqual(self.engine.platforms(), expected)
            self.assertEqual(height.call_count, initial)
            public = self.engine.platforms()
            public.clear()
            self.assertEqual(self.engine.platforms(), expected)
        vertices = self.engine._vertices(prop)
        bounds = self.engine._bounds(prop)
        self.assertIs(self.engine._vertices(prop), vertices)
        self.assertIs(self.engine._bounds(prop), bounds)

    def test_every_geometry_mutation_invalidates_immediately(self):
        prop = self.crate()
        self.engine.platforms()
        for field, value in (("x", 430.), ("y", 520.), ("w", 90.), ("h", 60.),
                             ("angle", .37), ("id", 91), ("kind", "seesaw"),
                             ("kind", "ramp"), ("kind", "fan")):
            with self.subTest(field=field, value=value):
                prop[field] = value
                uncached = {k: v for k, v in prop.items() if not k.startswith("_")}
                self.assertEqual(self.engine._bounds(prop), self.engine._bounds(uncached))
                self.assertEqual(self.engine._vertices(prop), self.engine._vertices(uncached))
                self.assertEqual(self.engine._prop_platforms(prop),
                                 self.engine._prop_platforms(uncached))

    def test_rotating_crate_changes_real_projectile_contact_same_frame(self):
        prop = self.crate()
        self.engine.platforms()
        self.assertIsNone(self.engine.projectile_contact(350, 447, 450, 447))
        prop["angle"] = math.pi / 2
        hit = self.engine.projectile_contact(350, 447, 450, 447)
        self.assertIsNotNone(hit)
        self.assertIs(hit[3], prop)
        prop["x"] += 300
        self.assertIsNone(self.engine.projectile_contact(350, 447, 450, 447))

    def test_sleeping_crate_skips_unchanged_support_scans(self):
        prop = self.sleeping_platform_crate()
        before = (prop["x"], prop["y"], prop["angle"])
        with patch.object(self.engine, "_support", wraps=self.engine._support) as support:
            for _ in range(30):
                self.engine.update(1 / 60)
            self.assertEqual(support.call_count, 0)
        self.assertEqual((prop["x"], prop["y"], prop["angle"]), before)

    def test_moving_or_removed_desktop_support_wakes_crate(self):
        for surface in ([(326, 474, 540, "window", 42)], [],
                        [(700, 800, 500, "window", 42)]):
            with self.subTest(surface=surface):
                self.engine.clear()
                prop = self.sleeping_platform_crate()
                # The real scanner replaces its list; also cover in-place edits
                # used by desktop fixtures and immediate movement corrections.
                self.app.terrain.platforms[:] = surface
                self.engine.update(1 / 60)
                self.assertFalse(prop["sleeping"])
                self.assertGreater(prop["y"], 500)

    def test_floor_work_area_change_wakes_crate(self):
        prop = self.crate(y=960.)
        prop.update(sleeping=True, support=("floor", None))
        self.engine._crate_step(prop, 1 / 120)
        self.app.mons = [((0, 0, 1600, 1000), (0, 0, 1600, 980))]
        self.engine.update(1 / 60)
        self.assertFalse(prop["sleeping"])
        self.assertGreater(prop["y"], 960.)

    def test_moved_rotated_and_removed_toy_support_wakes_crate(self):
        for change in ("move", "rotate", "remove", "velocity"):
            with self.subTest(change=change):
                self.engine.clear()
                base = self.crate(y=800.)
                upper = self.crate(y=752.)
                upper.update(sleeping=True, support=("toy", base["id"]))
                self.engine._crate_step(upper, 1 / 120)
                self.assertTrue(upper["sleeping"])
                if change == "move":
                    base["x"] += 300
                elif change == "rotate":
                    base["angle"] = .4
                elif change == "remove":
                    self.engine.props.remove(base)
                else:
                    base["vx"] = 100
                self.engine._crate_step(upper, 1 / 120)
                self.assertFalse(upper["sleeping"])

    def test_new_fan_force_wakes_previously_cached_sleep(self):
        prop = self.sleeping_platform_crate()
        fan = self.engine.add_prop("fan", 800., 600.)
        self.engine._crate_step(prop, 1 / 120)
        self.assertTrue(prop["sleeping"])
        fan["x"] = prop["x"]
        self.engine._crate_step(prop, 1 / 120)
        self.assertFalse(prop["sleeping"])
        self.assertLess(prop["vy"], 0.)

    def test_conveyor_start_and_direct_impulse_wake_sleep(self):
        belt = self.engine.add_prop("conveyor", 400., 700.)
        prop = self.crate(x=800., y=690.)
        prop.update(x=400., sleeping=True, support=("toy", belt["id"]))
        belt["direction"] = 0
        self.engine._crate_step(prop, 1 / 120)
        self.assertTrue(prop["sleeping"])
        belt["direction"] = 1
        self.engine._crate_step(prop, 1 / 120)
        self.assertFalse(prop["sleeping"])
        self.assertGreater(prop["vx"], 0.)
        self.engine.clear()
        prop = self.sleeping_platform_crate()
        self.engine.hit_prop(prop, prop["x"], prop["y"] - 24, 400, 0)
        self.engine._crate_step(prop, 1 / 120)
        self.assertFalse(prop["sleeping"])
        self.assertGreater(prop["x"], 400.)


if __name__ == "__main__":
    unittest.main()
