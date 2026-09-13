"""First-contact landings and late shots preserve the fighter's current activity.

The regressions fail if landings trust terrain enumeration order, or an old
projectile completes a target by taking its owner out of a later activity.
All shots pass through the real attack release and projectile collision paths.
"""
import types
import unittest

import harness


class BehaviorRecovery(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("behavior_recovery", crowd=2, react_to_windows=False)
        self.gm.monitors = lambda: [((0, 0, 1600, 1000), (0, 0, 1600, 960))]
        self.gm.virtual_screen = lambda: (0, 0, 1600, 1000)
        self.app = harness.build(self.gm)
        self.app.root.withdraw()
        self.app.update_environment = lambda: None
        self.app.decide = lambda fighter: None
        self.a, self.b = self.app.fighters
        self.park()

    def tearDown(self):
        harness.teardown(self.gm, self.app)

    def park(self):
        app = self.app
        for index, fighter in enumerate(app.fighters):
            app.end_ride(fighter)
            fighter.x, fighter.y = 200. + index * 1000, 400. if index == 0 else 960.
            fighter.vx = fighter.vy = fighter.stun = fighter.tumble = 0.
            fighter.squash = fighter.boredom = fighter.anger = 0.
            fighter.foe = fighter.target = fighter.carry = fighter.play = None
            fighter.hp, fighter.on_ground, fighter.grabbed = 100., True, False
            fighter.goal = fighter.mood_check = fighter.blink = 1000.
            fighter.mode, fighter.hits, fighter.snatch = "roam", 0, False
            fighter.set_state("idle")
        app.shots, app.traps = [], []
        app.asleep = False

    def fire_at_window(self):
        app, fighter = self.app, self.a
        harness.fake_terrain(app,
            icons=[("Firing ledge", 150, 400, 250, 460, 99)],
            windows=[("Target", 490, 355, 510, 600, 42),
                     ("Next target", 700, 355, 750, 600, 43)])
        fighter.target = app.terrain.targets()[1]
        fighter.plan, fighter.hits = "blaster", 3
        fighter.per = dict(fighter.per, weapons=tuple(self.gm.WEAPONS))
        app.start_attack(fighter)
        for _ in range(60):
            app.time += self.gm.SIM_STEP
            app.update_fighter(fighter, self.gm.SIM_STEP)
            if app.shots:
                break
        self.assertEqual(len(app.shots), 1, "the real attack must release its shot")

    def finish_shot(self, completed=True):
        app = self.app
        impacts = len(app.booms)
        for _ in range(120):
            app.time += self.gm.SIM_STEP
            app.projectiles(self.gm.SIM_STEP)
            if not app.shots:
                break
        self.assertFalse(app.shots, "the round must reach its actual window")
        if completed:
            self.assertGreater(len(app.booms), impacts, "target completion still has its impact")
            self.assertEqual(self.a.hits, 0, "target completion still records the fourth hit")
        else:
            self.assertEqual(len(app.booms), impacts, "an old target cannot borrow new target progress")

    def test_fall_lands_on_first_surface_independent_of_terrain_order(self):
        app, fighter = self.app, self.a
        icons = [("Lower icon", 200, 510, 280, 570, 0)]
        windows = [("Upper window", 150, 500, 400, 700, 42)]
        harness.fake_terrain(app, icons=icons, windows=windows)
        app.terrain.apply(icons, windows)
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                if reverse:
                    app.terrain.platforms.reverse()
                fighter.x, fighter.y = 240., 494.
                fighter.vx, fighter.vy, fighter.on_ground = 0., 1000., False
                fighter.set_state("fall")
                app.update_fighter(fighter, self.gm.SIM_STEP)
                self.assertEqual((fighter.y, fighter.plat), (500, ("window", 42)))

    def test_floor_precedes_platform_below_the_work_area(self):
        app, fighter = self.app, self.a
        harness.fake_terrain(app, icons=[("Below floor", 200, 970, 280, 1030, 0)])
        fighter.x, fighter.y = 240., 954.
        fighter.vx, fighter.vy, fighter.on_ground = 0., 1000., False
        fighter.set_state("fall")
        app.update_fighter(fighter, self.gm.SIM_STEP)
        self.assertEqual((fighter.y, fighter.plat), (960, ("floor", None)))

    def test_late_shot_cannot_cancel_knockout_grab_sleep_or_ride(self):
        app, fighter = self.app, self.a
        for activity in ("ko", "grabbed", "sleep", "float", "ride"):
            with self.subTest(activity=activity):
                self.park()
                self.fire_at_window()
                if activity == "ko":
                    app.hit_fighter(self.b, fighter, 200)
                elif activity == "grabbed":
                    app.on_down(types.SimpleNamespace(
                        x=fighter.x, y=fighter.y - 40 * fighter.sc))
                elif activity == "sleep":
                    app.asleep = True
                    app.update_fighter(fighter, self.gm.SIM_STEP)
                elif activity == "ride":
                    self.b.x = fighter.x + 40
                    self.assertTrue(app.start_ride(fighter, "shoulders"))
                else:
                    self.assertTrue(app.start_ride(fighter, activity))
                self.assertEqual(fighter.state, activity)
                before = (fighter.state, fighter.hp, fighter.target, fighter.goal,
                          fighter.grabbed, fighter.mount, self.b.ridden_by)
                self.finish_shot()
                self.assertEqual((fighter.state, fighter.hp, fighter.target, fighter.goal,
                                  fighter.grabbed, fighter.mount, self.b.ridden_by), before)

    def test_late_shot_cannot_cancel_a_new_hunt_target(self):
        self.fire_at_window()
        fighter = self.a
        fighter.target = self.app.terrain.targets()[2]
        fighter.hits = 2
        fighter.set_state("hunt")
        self.finish_shot(completed=False)
        self.assertEqual(fighter.hits, 2, "old contact must not count toward the new target")
        self.app.hit_target(fighter, fighter.target, 700, 371)
        self.assertEqual(fighter.hits, 3, "new target still needs its fourth own hit")
        self.assertEqual(fighter.state, "hunt")
        self.assertIsNotNone(fighter.target)
        self.assertEqual(fighter.target["key"], 43)

    def test_late_shot_cannot_cancel_a_window_visit_to_the_same_target(self):
        self.fire_at_window()
        fighter = self.a
        fighter.play = {"kind": "perch", "hwnd": 42, "x": 500}
        fighter.set_state("hunt")
        self.finish_shot()
        self.assertEqual(fighter.state, "hunt")
        self.assertIsNotNone(fighter.play)
        self.assertEqual(fighter.play["hwnd"], 42)

    def test_current_target_still_completes_after_a_terrain_refresh(self):
        for state in ("attack", "hunt", "idle"):
            with self.subTest(state=state):
                self.park()
                self.fire_at_window()
                self.a.target = dict(self.a.target)  # scan replaced the dict, same target
                self.a.set_state(state)
                self.finish_shot()
                self.assertEqual(self.a.state, "idle")
                self.assertIsNone(self.a.target)


if __name__ == "__main__":
    unittest.main()
