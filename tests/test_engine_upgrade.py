"""Fixed simulation, bounded desktop writes, live windows, and short navigation."""
import os
import random
import types
import unittest
from unittest.mock import patch

import harness


class EngineUpgrade(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("engine_upgrade", crowd=1)
        self.gm.monitors = lambda: [((0, 0, 1000, 800), (0, 0, 1000, 760))]
        self.gm.virtual_screen = lambda: (0, 0, 1000, 800)
        self.app = harness.build(self.gm)
        harness.fake_terrain(self.app)
        self.app.tray.pump = lambda: None
        self.app.tray.drain = lambda: None
        self.app.check_environment = lambda: None
        self.app.draw = lambda: None
        self.app.record_performance = lambda *args: None

    def tearDown(self):
        harness.teardown(self.gm, self.app)

    def loop(self, app=None):
        app = app or self.app
        clock = types.SimpleNamespace(now=100.0)
        queued = []
        app.root.after = lambda ms, callback: queued.append(callback)
        app.root.mainloop = lambda: None
        app.env_at = clock.now
        samples = []
        app.record_performance = lambda *args: samples.append(args)

        def tick(elapsed):
            clock.now += elapsed
            queued.pop(0)()

        return clock, queued, samples, tick

    def test_fixed_steps_produce_same_physics_at_15_40_60_fps(self):
        gm, app = self.gm, self.app
        results = []
        real_update = gm.App.update.__get__(app)
        app.update_environment = lambda: None
        for fps in (15, 40, 60):
            random.seed(7)
            gm.CFG["fps"] = fps
            f = gm.Fighter(400, 200)
            f.set_state("fall")
            f.vx, f.vy = 90, -150
            f.goal = f.mood_check = 1e9
            app.fighters = [f]
            app.time = 0
            steps = []

            def update(dt):
                steps.append(dt)
                real_update(dt)

            app.update = update
            clock, queued, samples, tick = self.loop()
            with patch.object(gm, "time", types.SimpleNamespace(perf_counter=lambda: clock.now)):
                app.run()
                for _ in range(fps * 2):
                    tick(1 / fps)
            self.assertEqual(len(steps), 120)
            self.assertTrue(all(dt == gm.SIM_STEP for dt in steps))
            self.assertAlmostEqual(app.time, 2.0)
            results.append((f.x, f.y, f.vx, f.vy, f.state, f.on_ground))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_pause_fullscreen_and_stall_have_bounded_catchup(self):
        gm, app = self.gm, self.app
        updates = []
        app.update = lambda dt: updates.append(dt)
        clock, queued, samples, tick = self.loop()
        with patch.object(gm, "time", types.SimpleNamespace(perf_counter=lambda: clock.now)):
            app.run()
            tick(1 / 15)
            self.assertEqual(len(updates), 4)
            for attribute in ("paused", "held"):
                setattr(app, attribute, True)
                tick(5)
                frozen = len(updates)
                setattr(app, attribute, False)
                tick(5)
                self.assertEqual(len(updates), frozen)
                tick(1 / 15)
                self.assertEqual(len(updates), frozen + 4)
            before = len(updates)
            tick(20)
        self.assertEqual(len(updates) - before, gm.MAX_CATCHUP_STEPS)
        self.assertGreater(samples[-1][4], 19)
        self.assertEqual(len(queued), 1)

    def test_catchup_coalesces_desktop_writes_and_rechecks_gates(self):
        gm, app = self.gm, self.app
        icons, windows = [], []
        gm.CFG["move_windows"] = True
        app.can_move_icons = lambda: True
        gm.SHELL.set_item_pos = lambda i, x, y: icons.append((i, x, y)) or True
        gm.place_window = lambda h, x, y: windows.append((h, x, y)) or True
        count = [0]

        def update(dt):
            count[0] += 1
            app.move_icon(0, count[0], 50)
            app.move_window(42, count[0], 60)

        app.update = update
        clock, queued, samples, tick = self.loop()
        with patch.object(gm, "time", types.SimpleNamespace(perf_counter=lambda: clock.now)):
            app.run()
            tick(1 / 15)
        self.assertEqual(icons, [(0, 4, 50)])
        self.assertEqual(windows, [(42, 4, 60)])
        app.begin_frame()
        app.move_icon(0, 99, 50)
        app.move_window(42, 99, 60)
        app.can_move_icons = lambda: False
        gm.foreground_window = lambda: ("Now typing", 42)
        app.flush_frame()
        self.assertEqual(len(icons), 1)
        self.assertEqual(len(windows), 1)

    def test_environment_samples_once_per_render_and_direct_update_still_works(self):
        app = self.app
        calls = []
        app.update_environment = lambda: calls.append(app.time)
        app.update_fighter = lambda f, dt: None
        app.projectiles = app.traps_tick = app.fx_tick = lambda dt: None
        app.begin_frame()
        for _ in range(4):
            app.update(self.gm.SIM_STEP)
        app.flush_frame()
        self.assertEqual(len(calls), 1)
        app.update(.025)
        app.update(.025)
        self.assertEqual(len(calls), 3)

    def test_real_blasts_share_pending_listview_coordinates(self):
        gm, app = self.gm, self.app
        app.can_move_icons = lambda: True
        outcomes = []
        for batched in (False, True):
            shell = harness.FakeShell([(300, 500)])
            gm.SHELL = shell
            harness.fake_terrain(app, icons=harness.shell_icons(shell))
            if batched:
                app.begin_frame()
            for _ in range(2):
                self.assertEqual(app.blast_icons(200, 532, 300, 100), 1)
            if batched:
                # A second consumer sees the pending screen rect and list pos
                # in the same coordinate system before Explorer is updated.
                rect, position = app.icon_rectangle(0), app.icon_position(0)
                self.assertEqual((position[0] - rect[0], position[1] - rect[1]), shell.OFF)
                app.flush_frame()
            outcomes.append(shell.pos[0])
            self.assertEqual(len(shell.writes), 1 if batched else 2)
        self.assertEqual(outcomes[0], outcomes[1])

    def test_deferred_nudge_commits_undo_only_after_actual_success(self):
        gm, app = self.gm, self.app
        gm.CFG["move_windows"] = True
        harness.fake_terrain(app, windows=[("Pad", 300, 300, 500, 500, 42)])
        gm.window_rect = lambda hwnd: (300, 300, 500, 500)
        gm.place_window = lambda *args: False
        for foreground_reject in (False, True):
            gm.foreground_window = lambda: None
            app.begin_frame()
            self.assertTrue(app.nudge_window(42, 10, 0))
            self.assertFalse(app.nudge_window(42, 20, 0))
            self.assertEqual(app.nudged, {})
            if foreground_reject:
                gm.foreground_window = lambda: ("Now typing", 42)
                gm.place_window = lambda *args: self.fail("foreground write must be skipped")
            app.flush_frame()
            self.assertEqual(app.nudged, {})
            self.assertEqual(app.nudged_at, {})
            self.assertEqual(app.nudges, [])
            self.assertEqual(app.terrain.win_rect[42], (300, 300, 500, 500))
        gm.foreground_window = lambda: None
        gm.place_window = lambda *args: True
        app.begin_frame()
        self.assertTrue(app.nudge_window(42, 10, 0))
        app.flush_frame()
        self.assertEqual(app.nudged[42], (300, 300))
        self.assertEqual(len(app.nudges), 1)
        self.assertEqual(app.terrain.win_rect[42], (310, 300, 510, 500))

    def test_occupied_window_tracks_drag_close_and_ignores_stale_full_scan(self):
        gm, app = self.gm, self.app
        gm.CFG["react_to_windows"] = False
        original = ("Pad", 200, 300, 600, 600, 42)
        harness.fake_terrain(app, windows=[original])
        app.terrain.fast_tracking = True
        f = app.fighters[0]
        f.set_state("perch")
        f.x, f.y, f.plat = 350, 300, None
        f.play = {"hwnd": 42, "kind": "perch", "x": 350}
        latest = [220, 330, 620, 630]
        reads = []

        def read(hwnd):
            reads.append(hwnd)
            return tuple(latest) if latest else None

        gm.tracked_window_rect = read
        app.time = .04
        app.update_environment()
        self.assertEqual((f.x, f.y), (370, 330))
        app.time = .05
        app.update_environment()
        self.assertEqual(len(reads), 1)
        latest[:] = [225, 340, 625, 640]
        app.time = .08
        app.update_environment()
        self.assertEqual((f.x, f.y), (375, 340))
        app.terrain.scanner._result = (None, [original])
        app.time = .09
        app.update_environment()
        self.assertEqual((f.x, f.y), (375, 340))
        self.assertEqual(app.terrain.win_rect[42], tuple(latest))
        latest[:] = []
        app.time = .12
        app.update_environment()
        self.assertIsNone(f.play)
        self.assertEqual(f.state, "fall")
        self.assertNotIn(42, app.terrain.win_rect)

    def test_fast_tracking_reconciles_platforms_after_a_confirmed_nudge(self):
        gm, app = self.gm, self.app
        gm.CFG["move_windows"] = True
        harness.fake_terrain(app, windows=[("Pad", 300, 300, 500, 500, 42)])
        app.terrain.fast_tracking = True
        gm.window_rect = lambda hwnd: (300, 300, 500, 500)
        gm.place_window = lambda *args: True
        gm.foreground_window = lambda: None
        f = app.fighters[0]
        f.x, f.y, f.plat = 400, 300, None
        f.play = {"hwnd": 42, "kind": "perch", "x": 400}
        f.set_state("perch")
        app.begin_frame()
        self.assertTrue(app.nudge_window(42, 10, 0))
        app.flush_frame()
        self.assertTrue(app.terrain.track_windows({42}, .04,
                        read_rect=lambda hwnd: (310, 300, 510, 500)))
        app.terrain_changed()
        self.assertEqual(app.terrain.win_pos[42], (310, 300))
        self.assertEqual(app.terrain.targets()[0]["cx"], 410)
        self.assertEqual(app.terrain.platforms[0], (316, 504, 300, "window", 42))
        self.assertEqual((f.x, f.y), (410, 300))

    def stairs(self, alternate=False):
        icons = [("Step", 120, 640, 240, 704, 0),
                 ("Step two", 225, 520, 345, 584, 1),
                 ("Goal", 330, 400, 450, 464, 2)]
        if alternate:
            icons.append(("Alternative", 245, 640, 365, 704, 3))
        harness.fake_terrain(self.app, icons=icons)
        f = self.app.fighters[0]
        f.x, f.y, f.on_ground, f.plat = 80, 760, True, ("floor", None)
        f.vx = f.vy = 0
        f.target = self.app.terrain.targets()[2]
        f.set_state("hunt")
        f.goal = f.mood_check = 1e9
        return f, icons

    def test_route_reaches_high_target_using_existing_climb_states(self):
        gm, app = self.gm, self.app
        f, icons = self.stairs()
        route, origin = app.plan_route(f, f.target)
        self.assertEqual(route, [("icon", 0), ("icon", 1), ("icon", 2)])
        app.update_environment = lambda: None
        app.decide = lambda fighter: None
        seen = set()
        for _ in range(60 * 12):
            app.update(gm.SIM_STEP)
            seen.add(f.state)
            self.assertEqual(f.target["key"], 2)
            if f.on_ground and f.plat == ("icon", 2):
                break
        self.assertEqual(f.plat, ("icon", 2))
        self.assertAlmostEqual(f.y, 400)
        self.assertIn("climb", seen)

    def test_route_replans_moved_surfaces_and_avoids_failed_edge_temporarily(self):
        app = self.app
        f, icons = self.stairs(alternate=True)
        self.assertTrue(app.navigate(f, self.gm.SIM_STEP, f.K()))
        self.assertEqual(f.route[0], ("icon", 0))
        f.route_best = 0
        f.route_since = 0
        app.time = 5
        self.assertFalse(app.navigate(f, self.gm.SIM_STEP, f.K()))
        self.assertTrue(f.route_failed)
        app.time = 5.4
        self.assertTrue(app.navigate(f, self.gm.SIM_STEP, f.K()))
        self.assertEqual(f.route[0], ("icon", 3))
        app.time = 18
        route, origin = app.plan_route(f, f.target)
        self.assertEqual(route[0], ("icon", 0))
        moved = list(icons)
        moved[1] = ("Step two", 800, 520, 920, 584, 1)
        harness.fake_terrain(app, icons=moved)
        app.time = 18.1
        app.navigate(f, self.gm.SIM_STEP, f.K())
        self.assertEqual(f.route, [])

    def test_route_jumps_a_gap_that_cannot_be_climbed(self):
        gm, app = self.gm, self.app
        harness.fake_terrain(app, icons=[
            ("Start", 0, 640, 100, 704, 0),
            ("Across gap", 150, 600, 250, 664, 1),
            ("Upper", 235, 480, 335, 544, 2),
            ("Goal", 320, 360, 420, 424, 3)])
        f = app.fighters[0]
        f.x, f.y, f.on_ground, f.plat = 92, 640, True, ("icon", 0)
        f.target = app.terrain.targets()[3]
        f.set_state("hunt")
        f.goal = f.mood_check = 1e9
        app.update_environment = lambda: None
        self.assertTrue(app.navigate(f, gm.SIM_STEP, f.K()))
        self.assertEqual(f.route[0], ("icon", 1))
        self.assertEqual(f.state, "jump")
        # The normal ledge-grab may finish the jump with a short mantle.
        for _ in range(180):
            app.update(gm.SIM_STEP)
            if f.on_ground:
                break
        self.assertEqual(f.plat, ("icon", 1))
        self.assertAlmostEqual(f.y, 600)

    def test_hunt_fallback_honors_failed_edge_but_keeps_hook_alternative(self):
        gm, app = self.gm, self.app
        harness.fake_terrain(app, windows=[("Pad", 320, 610, 800, 720, 42)])
        f = app.fighters[0]
        f.x, f.y, f.on_ground, f.plat = 200, 760, True, ("floor", None)
        f.target = app.terrain.targets()[0]
        f.play = {"hwnd": 42, "kind": "perch", "x": 450}
        f.plan = "sword"
        f.set_state("hunt")
        self.assertTrue(app.navigate(f, gm.SIM_STEP, f.K()))
        f.x, f.route_best, f.route_since, f.st = 310, 0, 0, 1
        app.time = 5
        # Stalled route fails on this actual hunt call. Even a guaranteed
        # random hop cannot bypass its cooldown through the original fallback.
        with patch.object(gm.random, "random", return_value=0):
            app._st_hunt(f, gm.SIM_STEP, f.K())
            self.assertEqual(f.state, "hunt")
            self.assertTrue(app.route_blocked(f, f.target))
            app.time = 5.4
            app._st_hunt(f, gm.SIM_STEP, f.K())
            self.assertEqual(f.state, "hunt")
        hooks = []
        app.fire_hook = lambda *args: hooks.append(args)
        f.plan, f.atk_cd = "bow", 0
        app._st_hunt(f, gm.SIM_STEP, f.K())
        self.assertEqual(len(hooks), 1)
        app.time = 18
        f.plan = "sword"
        app._st_hunt(f, gm.SIM_STEP, f.K())
        self.assertEqual(f.state, "climb", "the failed edge should be usable after cooldown")


if __name__ == "__main__":
    unittest.main()
