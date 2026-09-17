"""Collision broad-phase regressions on an isolated desktop, without timing noise."""
import random
import unittest

import harness


class CollisionPerformance(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("collision_performance", crowd=1, react_to_windows=False)
        self.gm.monitors = lambda: [((-1200, -800, 3600, 2200), (-1200, -800, 3600, 2160))]
        self.gm.virtual_screen = lambda: (-1200, -800, 4800, 3000)
        self.app = harness.build(self.gm)
        self.app.root.withdraw()
        harness.fake_terrain(self.app)
        self.owner = self.app.fighters[0]
        self.owner.x, self.owner.y = -1000., 1800.
        self.owner.aim = 0.
        self.owner.shot_pierce, self.owner.shot_tgt = False, None

    def tearDown(self):
        harness.teardown(self.gm, self.app)

    @staticmethod
    def bound(key, cx, cy, hw=12., hh=16., kind="icon"):
        target = {"kind": kind, "key": key, "cx": cx, "cy": cy,
                  "w": hw * 2, "h": hh * 2, "top": cy - hh, "name": "fixture"}
        return cx, cy, hw, hh, target

    def test_sweeps_match_exhaustive_geometry_and_order(self):
        rng = random.Random(907)
        terrain = self.app.terrain
        rows = [self.bound(i, rng.uniform(-1000, 3000), rng.uniform(-600, 1800),
                           rng.uniform(0, 100), rng.uniform(0, 80)) for i in range(400)]
        # Wide windows, coincident faces and a point box exercise overflow cells
        # and the list-order tiebreaker used by both projectile engines.
        rows += [self.bound(900, 300., 300., 100000., 100000., "window"),
                 self.bound(901, -128., -128., 0., 0.),
                 self.bound(902, -128., -128., 0., 0.)]
        terrain.bounds = rows
        paths = [(-200000., -200000., 200000., 200000., 0.),
                 (-128., -128., -128., -128., 0.),
                 (-256., -128., 0., -128., 7.)]
        paths += [(rng.uniform(-1200, 3600), rng.uniform(-800, 2200),
                   rng.uniform(-1200, 3600), rng.uniform(-800, 2200),
                   rng.choice((0., 3., 17., 150.))) for _ in range(120)]
        for x0, y0, x1, y1, radius in paths:
            def hits(candidates):
                return [(target["key"], at) for cx, cy, hw, hh, target in candidates
                        if (at := self.app.segment_box(x0, y0, x1, y1,
                            cx - hw - radius, cy - hh - radius,
                            cx + hw + radius, cy + hh + radius)) is not None]
            self.assertEqual(hits(terrain.projectile_candidates(x0, y0, x1, y1, radius)),
                             hits(rows))

    def test_replacement_and_in_place_list_changes_invalidate(self):
        terrain = self.app.terrain
        terrain.bounds = [self.bound(i, i * 80., 100.) for i in range(100)]
        terrain.projectile_candidates(0., 100., 20., 100.)
        terrain.bounds[0] = self.bound(0, 2500., 900.)
        terrain.bounds.append(self.bound(200, 5., 100.))
        candidates = terrain.projectile_candidates(0., 100., 20., 100.)
        self.assertEqual([row[-1]["key"] for row in candidates], [200])
        terrain.bounds.insert(0, self.bound(201, 5., 100.))
        terrain.bounds.reverse()
        candidates = terrain.projectile_candidates(0., 100., 20., 100.)
        self.assertEqual([row[-1]["key"] for row in candidates], [200, 201])
        terrain.bounds[:] = [self.bound(301, -100., -100.)]
        self.assertEqual(terrain.projectile_candidates(0., 100., 20., 100.), [])
        terrain.bounds = [self.bound(302, 5., 100.)]
        self.assertEqual(terrain.projectile_candidates(0., 100., 20., 100.), terrain.bounds)

    def test_identity_lookup_follows_moved_and_removed_targets(self):
        terrain = self.app.terrain
        icons = [("Icon %d" % i, i * 80, 80, i * 80 + 32, 112, i) for i in range(80)]
        terrain.apply(icons, [("Window", 100, -120, 500, 300, 77)])
        old = terrain.projectile_candidates(0., 0., 0., 0., target=("icon", 5))
        self.assertEqual(old[0][0], 416.)
        icons[5] = ("Moved", -100, -200, -68, -168, 5)
        terrain.apply(icons, [("Window", -700, -600, -300, 300, 77)])
        self.assertEqual(terrain.projectile_candidates(0., 0., 0., 0., target=("icon", 5))[0][0], -84.)
        self.assertEqual(terrain.projectile_candidates(0., 0., 0., 0., target=("window", 77))[0][1], -584.)
        terrain.fast_tracking = True
        terrain.track_windows([77], 1., lambda hwnd: (-900, -700, -500, 200))
        self.assertEqual(terrain.projectile_candidates(0., 0., 0., 0., target=("window", 77))[0][1], -684.)
        terrain.bounds.append(self.bound(5, 300., 300.))
        self.assertEqual(len(terrain.projectile_candidates(0., 0., 0., 0., target=("icon", 5))), 2)
        terrain.apply([], [])
        self.assertEqual(terrain.projectile_candidates(0., 0., 0., 0., target=("icon", 5)), [])

    def test_arsenal_contacts_equal_exhaustive_candidates(self):
        rng = random.Random(91)
        terrain = self.app.terrain
        terrain.bounds = [self.bound(i, rng.uniform(-1000, 3000), rng.uniform(-600, 1800))
                          for i in range(400)]
        indexed = terrain.projectile_candidates
        def exhaustive(x0, y0, x1, y1, radius=0., target=None):
            return [row for row in terrain.bounds
                    if target is None or (row[-1]["kind"], row[-1]["key"]) == target]
        for i in range(90):
            shot = {"owner": self.owner, "hit": set(), "k": "rubber", "phase": "out",
                    "pierce": i % 3 == 0, "tgt": ("icon", i) if i % 2 else None}
            path = (rng.uniform(-1200, 3600), rng.uniform(-800, 1800),
                    rng.uniform(-1200, 3600), rng.uniform(-800, 1800), rng.uniform(0, 25))
            terrain.projectile_candidates = indexed
            actual = self.app.arsenal._contact(shot, *path)
            terrain.projectile_candidates = exhaustive
            expected = self.app.arsenal._contact(shot, *path)
            self.assertEqual(actual, expected)
        terrain.projectile_candidates = indexed

    def test_main_projectiles_keep_ties_and_targeted_range(self):
        terrain = self.app.terrain
        terrain.bounds = [self.bound(i, 2500. + i * 60., 1500.) for i in range(80)]
        terrain.bounds += [self.bound(901, -200., -100.), self.bound(902, -200., -100.)]
        contact = self.app.arsenal._contact(
            {"owner": self.owner, "hit": set(), "k": "rubber", "phase": "out",
             "pierce": False, "tgt": None}, -800., -100., 1200., -100., 7.)
        self.assertEqual(contact[0], "target")
        self.assertEqual(contact[-1]["key"], 901, "arsenal keeps its first tied terrain row")
        hits = []
        self.app.hit_target = lambda owner, target, x, y: hits.append((target["key"], x, y))
        self.app.shoot(self.owner, "pellet", 30000., 0., .001, at=(-800., -100.))
        self.app.projectiles(1 / 15.)
        self.assertEqual(hits, [(902, -212., -100.)], "last tied terrain row still wins")
        hits.clear()
        self.owner.shot_pierce, self.owner.shot_tgt = True, ("icon", 901)
        self.app.shoot(self.owner, "pellet", 30000., 0., .001, at=(-800., -100.))
        self.app.projectiles(1 / 15.)
        self.assertEqual(hits, [(901, -212., -100.)], "expired timer cannot shorten aimed flight")

    def test_dense_desktop_reduces_narrow_phase_work(self):
        terrain = self.app.terrain
        identity_reads = [0]
        class CountedTarget(dict):
            def __getitem__(self, key):
                if key in ("kind", "key"):
                    identity_reads[0] += 1
                return super().__getitem__(key)
        terrain.bounds = [self.bound(i, 200. + (i % 20) * 80., 200. + (i // 20) * 80.)
                          for i in range(400)]
        terrain.bounds[:] = [(*row[:-1], CountedTarget(row[-1])) for row in terrain.bounds]
        self.assertLessEqual(len(terrain.projectile_candidates(180., 200., 210., 200.)), 2)
        identity_reads[0] = 0
        count = [0]
        real_segment = self.app.segment_box
        def counted(*args):
            count[0] += 1
            return real_segment(*args)
        self.app.segment_box = counted
        self.owner.shot_pierce, self.owner.shot_tgt = True, ("icon", 399)
        for _ in range(24):
            self.app.shoot(self.owner, "pellet", 600., 0., 1., at=(-800., -100.))
        self.app.projectiles(1 / 60.)
        self.assertEqual(len(self.app.shots), 24)
        self.assertLessEqual(count[0], 24, "aimed shots must not test every desktop object")
        self.assertLessEqual(identity_reads[0], 2, "aimed shots must not scan every target identity")
        self.app.shots = []
        self.owner.shot_pierce, self.owner.shot_tgt = False, None
        count[0] = 0
        for _ in range(24):
            self.app.shoot(self.owner, "pellet", 600., 0., 1., at=(-800., -100.))
        self.app.projectiles(1 / 60.)
        self.assertEqual(len(self.app.shots), 24)
        self.assertLessEqual(count[0], 24, "clear local paths must not test distant boxes")


if __name__ == "__main__":
    unittest.main()
