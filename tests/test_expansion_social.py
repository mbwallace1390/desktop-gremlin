"""Scene outcomes and rendered props through the shared safe desktop harness."""
import importlib.util
import json
import math
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness


class SocialScenes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gm = harness.load("expansion_social", crowd=6, react_to_windows=False,
                              group_scenes=False, parkour=False, toy_props=False)
        original = cls.gm.tk.Tk

        def root():
            window = original()
            window.withdraw()
            return window

        with mock.patch.object(cls.gm.tk, "Tk", root), \
                mock.patch.object(cls.gm, "virtual_screen", return_value=(0, 0, 1000, 760)), \
                mock.patch.object(cls.gm, "monitors", return_value=[
                    ((0, 0, 1000, 760), (0, 0, 1000, 720))]):
            cls.app = harness.build(cls.gm)
        harness.fake_terrain(cls.app)

    @classmethod
    def tearDownClass(cls):
        harness.teardown(cls.gm, cls.app)

    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("gremlin_social"),
                             "The social director and scene behavior are missing")
        from gremlin_social import SocialDirector
        random.seed(912)
        self.memory = {"relationships": {}}
        self.dirty = 0
        self.cfg = dict(self.gm.CFG, group_scenes=True, play_mode="mischief")
        self.director = SocialDirector(self.app, self.cfg, lambda: self.memory,
                                       self.mark_dirty)
        from gremlin_arsenal import Arsenal
        self.app.arsenal = Arsenal(self.app, self.cfg)
        self.app.social = self.director
        self.app.fighters = self.app.fighters[:6]
        for i, f in enumerate(self.app.fighters):
            f.x = 400.0 + i * 45
            f.y = self.app.ground_at(f.x)
            f.vx = f.vy = f.stun = f.tumble = f.anger = 0.0
            f.hp = 100.0
            f.on_ground, f.grabbed = True, False
            f.state, f.mode = "idle", "roam"
            f.foe = f.target = f.plat = f.play = None
            f.hat, f.scene_hat, f.scene_action = "cap", None, None
            f.effects, f.social_rescue = {}, False
            f.goal, f.boredom = self.app.time + 999, 0
        self.actors = self.app.fighters
        self.a, self.b, self.c = self.actors[:3]

    def tearDown(self):
        if hasattr(self, "director"):
            self.director.clear()
            self.app.arsenal.clear()
            self.app.fighters = self.actors

    def mark_dirty(self):
        self.dirty += 1

    def tick(self, seconds):
        for _ in range(int(seconds * 40)):
            self.director.update(.025)
            for f in self.actors:
                self.director.control(f, .025)

    def drawing(self):
        self.app._frame_begin()
        self.director.draw()
        self.app._frame_end()
        return [(self.app.canvas.type(i), self.app.canvas.coords(i),
                 self.app.canvas.itemcget(i, "text") if self.app.canvas.type(i) == "text" else "")
                for i in self.app.canvas.find_withtag("social")
                if self.app.canvas.itemcget(i, "state") != "hidden"]

    def test_01_relationships_persist_under_stable_keys_and_forget_rebinds(self):
        self.a.nickname, self.b.nickname = "Private nickname", "Another nickname"
        # The clock has to move. on_hit bonds once per HIT_BOND_INTERVAL, so a
        # hundred hits at one instant are one grudge: this used to reach about
        # -100 and now reaches -5.3, which is above both rivalry thresholds
        # _consider() reads. assertLess(score, 0) stayed green either way, so
        # the test kept its name while no longer proving a rivalry forms.
        for _ in range(100):
            self.director.time += 4.0
            self.director.on_hit(self.a, self.b, 30)
        score = self.director.affinity(self.a, self.b)
        self.assertLess(score, -15, "Repeated hits must create a real rivalry")
        self.assertGreaterEqual(score, -100)
        self.assertEqual(score, self.director.affinity(self.b, self.a))
        raw = json.dumps(self.memory)
        self.assertNotIn("nickname", raw)
        self.assertIn(self.a.kind, raw)
        from gremlin_social import SocialDirector
        self.memory = json.loads(raw)
        reloaded = SocialDirector(self.app, self.cfg, lambda: self.memory, self.mark_dirty)
        self.assertEqual(score, reloaded.affinity(self.a, self.b))
        self.assertGreater(self.dirty, 0)
        self.memory = {"relationships": {}}
        self.assertEqual(0, self.director.affinity(self.a, self.b), "Forget must use new memory")

    def test_02_alliance_targets_strongest_and_friendly_fire_breaks_it(self):
        self.a.hp, self.b.hp, self.c.hp = 45, 50, 100
        self.assertTrue(self.director.start_scene("alliance", [self.a, self.b, self.c]))
        self.tick(7)
        self.assertIs(self.a.foe, self.c)
        self.assertIs(self.b.foe, self.c)
        self.assertGreater(self.director.affinity(self.a, self.b), 75)
        self.director.on_hit(self.a, self.b, 2)
        self.assertLess(self.director.affinity(self.a, self.b), 0,
                        "Friendly fire must end the pact and create a grudge")

    def test_03_rescue_moves_and_recovers_a_knocked_out_friend(self):
        self.b.hp, self.b.state = 0, "ko"
        self.a.x = self.b.x - 120
        start = self.a.x
        self.assertTrue(self.director.start_scene("rescue", [self.a, self.b]))
        self.tick(1.2)
        self.assertGreater(self.a.x, start + 15, "Rescuer must approach the friend")
        self.assertTrue(any(t != "text" for t, _, _ in self.drawing()))
        self.tick(5)
        self.assertGreater(self.b.hp, 0)
        self.assertNotEqual(self.b.state, "ko")
        self.assertGreater(self.director.affinity(self.a, self.b), 0)

    def test_04_falling_and_ledge_rescue_return_friend_to_a_surface(self):
        for state in ("fall", "ledge"):
            self.director.clear()
            self.a.state, self.b.state = "idle", state
            self.a.on_ground, self.b.on_ground = True, False
            self.b.y -= 100
            self.b.vy = 150
            self.assertTrue(self.director.start_scene("rescue", [self.a, self.b]))
            self.tick(6)
            self.assertTrue(self.b.on_ground)
            self.assertAlmostEqual(self.b.y, self.app.ground_at(self.b.x), delta=2)

    def test_05_hat_heist_has_lookout_theft_escape_and_restoration(self):
        self.b.hat = "crown"
        self.assertTrue(self.director.start_scene("hat_heist", [self.a, self.b, self.c]))
        self.tick(2.8)
        self.assertEqual(self.a.scene_hat, "crown")
        self.assertEqual(self.b.scene_hat, "none")
        stolen_at = self.a.x
        self.assertNotEqual(self.c.scene_action, self.a.scene_action)
        self.tick(2)
        self.assertGreater(abs(self.a.x - stolen_at), 10, "Thief must run with the hat")
        self.director.clear(self.a)
        self.assertIsNone(self.a.scene_hat)
        self.assertIsNone(self.b.scene_hat)
        self.assertEqual("crown", self.b.hat, "Heist must never overwrite the saved profile")

    def test_06_surrender_lures_rival_onto_a_real_temporary_trap(self):
        self.assertTrue(self.director.start_scene("surrender", [self.a, self.b]))
        self.tick(1.8)
        props = self.drawing()
        self.assertTrue(any(t == "line" for t, _, _ in props))
        start_x = self.b.x
        self.tick(2.3)
        self.assertGreater(abs(self.b.x - start_x), 5, "The target must approach the dropped trap")
        self.assertTrue(self.b.stun > 0 or self.b.state == "thrown" or "foam" in self.b.effects,
                        "A fake surrender needs a trap consequence")
        self.assertLess(self.director.affinity(self.a, self.b), 0)

    def test_07_spectators_watch_live_fighters_and_score_impacts(self):
        self.a.state, self.b.state = "fight", "fight"
        self.a.foe, self.b.foe = self.b, self.a
        self.assertTrue(self.director.start_scene("spectators", [self.c, self.a, self.b]))
        self.tick(2)
        before = self.drawing()
        self.director.on_hit(self.a, self.b, 22)
        after = self.drawing()
        self.assertEqual("fight", self.a.state, "Spectators cannot take ownership of a fight")
        self.assertTrue(any(t == "rectangle" for t, _, _ in before), "A scorecard must be drawn")
        self.assertNotEqual(before, after, "The card must respond to an actual hit")

    def test_08_court_mediates_a_grudge_with_bench_gavel_and_restitution(self):
        self.director.on_hit(self.a, self.b, 20)
        score = self.director.affinity(self.a, self.b)
        self.assertTrue(self.director.start_scene("court", [self.a, self.b, self.c]))
        self.tick(2.5)
        props = self.drawing()
        self.assertTrue(any(t == "rectangle" for t, _, _ in props))
        self.assertTrue(any(t == "line" for t, _, _ in props))
        self.tick(6)
        self.assertGreater(self.director.affinity(self.a, self.b), score)

    def test_09_quiet_games_draw_distinct_moving_props_and_build_friendships(self):
        signatures = []
        for kind in ("cards", "football", "juggling", "blanket_nap", "coffee"):
            self.director.clear()
            for f in self.actors:
                f.state, f.on_ground, f.boredom = "idle", True, .6
                f.x, f.y = 400 + self.actors.index(f) * 45, self.app.ground_at(f.x)
            before = self.director.affinity(self.a, self.b)
            self.assertTrue(self.director.start_scene(kind, [self.a, self.b]), kind)
            self.tick(2)
            first = self.drawing()
            self.tick(.7)
            second = self.drawing()
            geometry = [(t, p) for t, p, _ in first if t != "text"]
            self.assertTrue(geometry, kind + " needs props")
            self.assertNotEqual(first, second, kind + " must visibly animate")
            signatures.append(geometry)
            self.tick(10)
            self.assertGreater(self.director.affinity(self.a, self.b), before, kind)
            self.assertLess(self.a.boredom, .6, kind)
            self.assertNotEqual("social", self.a.state)
        self.assertEqual(5, len({repr(s) for s in signatures}), "Games cannot share one generic prop")

    def test_10_inspectors_measure_resized_window_and_leave_temporary_sticker(self):
        old = {91: (300, 350, 800, 650)}
        new = {91: (300, 350, 900, 650)}
        self.app.terrain.win_rect = dict(new)
        self.director.on_windows_changed(old, new)
        self.tick(2)
        self.assertTrue(any(self.director.control(f, 0) for f in self.actors))
        props = self.drawing()
        self.assertTrue(any(t == "line" and len(p) >= 4 for t, p, _ in props))
        self.tick(4)
        self.assertTrue(any(t == "rectangle" for t, _, _ in self.drawing()), "Inspection sticker must remain briefly")
        self.assertNotIn("91", json.dumps(self.memory), "Window handles must stay out of memory")
        self.director.on_windows_changed(new, {})
        self.assertFalse(self.drawing(), "A closed window must take its sticker and tape with it")

    def test_11_interruption_removal_and_cooldowns_do_not_leave_owned_actors(self):
        self.assertTrue(self.director.start_scene("cards", [self.a, self.b]))
        self.assertFalse(self.director.start_scene("coffee", [self.a, self.c]))
        self.a.grabbed, self.a.state = True, "grabbed"
        self.director.update(.025)
        self.assertFalse(self.director.control(self.b, 0))
        self.assertEqual("grabbed", self.a.state)
        self.assertIsNone(self.b.scene_action)
        self.a.grabbed, self.a.state = False, "idle"
        self.assertFalse(self.director.start_scene("cards", [self.a, self.b]),
                         "Interrupted actors need a cooldown")
        self.director.clear()
        self.assertTrue(self.director.start_scene("coffee", [self.a, self.b]))
        self.app.fighters = self.actors[1:]
        self.director.update(.025)
        self.assertFalse(self.director.control(self.b, 0))
        self.app.fighters = self.actors

    def test_12_peaceful_mode_and_solo_cast_have_working_quiet_play(self):
        self.cfg["play_mode"] = "peaceful"
        for kind in ("surrender", "hat_heist", "alliance", "court"):
            self.assertFalse(self.director.start_scene(kind, [self.a, self.b, self.c]))
        self.assertTrue(self.director.start_scene("coffee", [self.a]))
        self.tick(3)
        self.assertTrue(self.drawing())
        self.cfg["group_scenes"] = False
        self.director.update(.025)
        self.assertFalse(self.director.control(self.a, 0))
        self.assertFalse(self.drawing())

    def test_13_invalid_relationship_values_cannot_poison_rival_selection(self):
        self.memory = {"relationships": {
            "|".join(sorted((self.a.kind, self.b.kind))): float("nan"),
            "private-window-title|unknown": 80}}
        self.assertTrue(math.isfinite(self.director.affinity(self.a, self.b)))
        self.director.on_hit(self.a, self.b, float("inf"))
        self.assertTrue(math.isfinite(self.director.affinity(self.a, self.b)))

    def test_14_rescue_retains_visible_bindings_until_haul_and_preserves_shield(self):
        for effect in ("foam", "bubble", "freeze"):
            self.director.clear()
            self.app.arsenal.clear()
            self.a.state, self.a.on_ground = "idle", True
            self.b.state, self.b.on_ground = "idle", True
            self.assertTrue(self.app.arsenal.apply_effect(self.b, effect, 8, self.c))
            self.assertTrue(self.app.arsenal.apply_effect(self.b, "shield", 10, self.b))
            self.assertTrue(self.director.start_scene("rescue", [self.a, self.b]))
            for _ in range(80):
                self.director.update(.025)
                self.app.arsenal.update(.025)
            self.assertIn(effect, self.b.effects, "Binding must remain visible during the approach")
            self.app._frame_begin()
            self.app.arsenal.draw()
            self.app._frame_end()
            self.assertTrue([i for i in self.app.canvas.find_withtag("arsenal")
                             if self.app.canvas.itemcget(i, "state") != "hidden"])
            self.tick(3)
            self.assertNotIn(effect, self.b.effects)
            self.assertIn("shield", self.b.effects)
            self.assertFalse(self.b.social_rescue)

    def test_15_rescue_interruption_releases_ownership_without_deleting_status(self):
        self.assertTrue(self.app.arsenal.apply_effect(self.b, "foam", 8, self.c))
        self.assertTrue(self.director.start_scene("rescue", [self.a, self.b]))
        self.tick(1)
        self.a.set_state("sleep")
        self.director.update(.025)
        self.assertFalse(self.director.control(self.b, 0))
        self.assertFalse(self.b.social_rescue)
        self.assertEqual("sleep", self.a.state)
        self.assertEqual("effect", self.b.state,
                         "Aborted rescue hands the victim back to the remaining foam")

    def test_16_scene_cap_and_temporary_hats_work_with_default_bare_heads(self):
        self.b.hat = "none"
        self.assertTrue(self.director.start_scene("hat_heist", [self.a, self.b, self.c]))
        self.tick(.5)
        self.assertNotIn(self.b.scene_hat, (None, "none"), "The prop hat must be visible before its theft")
        self.tick(2.3)
        self.assertNotIn(self.a.scene_hat, (None, "none"))
        self.assertTrue(self.director.start_scene("coffee", [self.actors[3]]))
        self.assertFalse(self.director.start_scene("juggling", [self.actors[4]]))
        self.director.clear()
        self.assertEqual("none", self.b.hat)
        self.assertFalse(any(self.director.control(f, 0) for f in self.actors))
        self.assertFalse(self.drawing())

    def test_17_damage_from_the_common_target_does_not_break_an_alliance(self):
        self.assertTrue(self.director.start_scene("alliance", [self.a, self.b, self.c]))
        self.tick(5)
        self.director.on_hit(self.c, self.a, 5)
        self.director.clear(self.a)  # same hit-interruption hook used by App
        self.a.set_state("thrown")
        self.director.update(.025)
        self.assertGreater(self.director.affinity(self.a, self.b), 75)
        self.a.grabbed = True
        self.director.clear(self.a)
        self.director.update(.025)
        self.assertLess(self.director.affinity(self.a, self.b), 75)

    def test_18_spectator_card_survives_the_real_hit_cleanup_hook(self):
        self.a.state, self.b.state = "fight", "fight"
        self.a.foe, self.b.foe = self.b, self.a
        self.assertTrue(self.director.start_scene("spectators", [self.c, self.a, self.b]))
        self.tick(2)
        self.app.hit_fighter(self.a, self.b, 18)
        self.assertTrue(self.director.control(self.c, 0),
                        "A watched hit must raise the scorecard, not cancel its spectator")
        self.assertTrue(any(text == "6" for _, _, text in self.drawing()))

    def test_19_successful_rescue_grants_a_short_protective_shield(self):
        self.b.state, self.b.hp = "ko", 0
        self.assertTrue(self.director.start_scene("rescue", [self.a, self.b]))
        self.tick(4.3)
        self.assertIn("shield", self.b.effects)
        for _ in range(160):
            self.app.arsenal.update(.025)
        self.assertNotIn("shield", self.b.effects, "Rescue protection must expire")

    def test_20_scene_poses_reach_the_drawn_fighter_limbs(self):
        arm_shapes = []
        for scene in ("juggling", "blanket_nap"):
            self.director.clear()
            self.a.state, self.a.on_ground = "idle", True
            self.assertTrue(self.director.start_scene(scene, [self.a]))
            self.tick(2)
            self.a.pose_from = None
            self.a.emote, self.a.emote_t = None, 0
            self.app.draw()
            arm_shapes.append([self.app.canvas.coords(i)
                               for i in self.app.canvas.find_withtag(self.app._ftag[0][3])
                               if self.app.canvas.type(i) == "line" and
                               self.app.canvas.itemcget(i, "state") != "hidden"])
        self.assertTrue(all(arm_shapes))
        self.assertNotEqual(arm_shapes[0], arm_shapes[1],
                            "Juggling and a nap must draw different real arm poses")

    def test_21_falling_friend_gets_help_before_the_ambient_scene_timer(self):
        self.memory["relationships"]["|".join(sorted((self.a.kind, self.b.kind)))] = 20
        self.b.state, self.b.on_ground, self.b.vy = "fall", False, 200
        self.b.y -= 85
        self.tick(.5)
        self.assertTrue(self.director.control(self.b, 0),
                        "A short fall cannot wait eight seconds for the next coffee break")

    def test_22_alliance_keeps_its_strongest_target_when_an_unrelated_foe_is_closer(self):
        self.assertTrue(self.director.start_scene("alliance", [self.a, self.b, self.c]))
        self.tick(5)
        self.actors[3].x = self.a.x + 3
        self.assertIs(self.app.nearest_enemy(self.a), self.c,
                      "Combat must honor the live pact target, even with a nearer fourth actor")

    def test_23_every_scene_completes_through_the_production_update_loop(self):
        for kind in ("alliance", "rescue", "hat_heist", "surrender", "spectators",
                     "court", "cards", "football", "juggling", "blanket_nap", "coffee"):
            self.director.clear()
            self.app.arsenal.clear()
            self.app.shots.clear()
            self.app.traps.clear()
            self.memory["relationships"] = {}
            for i, f in enumerate(self.actors):
                f.x, f.y = 400 + i * 45, self.app.ground_at(400 + i * 45)
                f.vx = f.vy = f.tumble = f.stun = f.boredom = f.anger = 0
                f.state, f.hp, f.on_ground = "idle", 100, True
                f.goal = self.app.time + 999
                f.foe = f.target = f.plat = None
            if kind == "rescue":
                self.b.hp, self.b.state = 0, "ko"
            if kind == "spectators":
                self.b.state, self.c.state = "fight", "fight"
                self.b.foe, self.c.foe = self.c, self.b
            self.assertTrue(self.director.start_scene(kind, self.actors[:3]), kind)
            for step in range(400):
                self.app.update(.025)
                if step % 10 == 0:
                    self.app.draw()
                self.assertTrue(all(math.isfinite(f.x) and math.isfinite(f.y) for f in self.actors))
                if not self.director.control(self.a, 0):
                    break
            self.assertFalse(self.director.control(self.a, 0), kind + " stranded an actor")
            self.assertIsNone(self.a.scene_action)


if __name__ == "__main__":
    unittest.main()
