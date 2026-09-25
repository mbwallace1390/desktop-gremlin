"""Real combat yields safe, bounded opportunities for Mischief group scenes."""
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness
from gremlin_social import QUIET


class SocialPacing(unittest.TestCase):
    def setUp(self):
        random.seed(7)
        self.gm = harness.load("social_pacing", crowd=3, group_scenes=True,
                               play_mode="mischief", react_to_windows=False)
        self.gm.virtual_screen = lambda: (0, 0, 1280, 800)
        self.gm.monitors = lambda: [((0, 0, 1280, 800), (0, 0, 1280, 760))]
        tk_root = self.gm.tk.Tk

        def hidden_root():
            root = tk_root()
            root.withdraw()
            return root

        with mock.patch.object(self.gm.tk, "Tk", hidden_root):
            self.app = harness.build(self.gm)
        harness.fake_terrain(self.app)
        self.a, self.b, self.c = self.app.fighters
        for i, f in enumerate(self.app.fighters):
            f.x, f.y = 500.0 + i * 80, 760.0
            f.vx = f.vy = f.stun = 0.0
            f.state, f.mode = "idle", "roam"
            f.on_ground, f.grabbed, f.hp = True, False, 100.0
            f.foe = f.target = None
            f.goal = self.app.time + 1000
            f.plan = "sword"
        self.social = self.app.social

    def tearDown(self):
        harness.teardown(self.gm, self.app)

    def ticks(self, seconds):
        for _ in range(round(seconds * 60)):
            self.app.update(1 / 60)

    def fight(self, a, b):
        for f, foe in ((a, b), (b, a)):
            f.foe, f.mode = foe, "fight"
            f.set_state("fight")
            f.atk_cd = self.app.time

    def test_real_bout_creates_quiet_scene_and_earned_bond(self):
        # Two neutral actors, actual attacks, no hand-started scene or bond.
        self.app.fighters = [self.a, self.b]
        # One pinned regression scenario proves a completed opportunity; open
        # ended random play may legitimately remain airborne or interrupted.
        for seed in (2,):
            with self.subTest(seed=seed):
                random.seed(seed)
                self.social.clear()
                self.gm.MEM["relationships"].clear()
                self.social._hit_bond.clear()
                self.app.shots.clear()
                self.app.arsenal.clear()
                self.app.fighters = [self.gm.Fighter(500 + i * 80, 760, kind)
                                     for i, kind in enumerate(("brawler", "sniper"))]
                self.a, self.b = self.app.fighters
                for i, f in enumerate(self.app.fighters):
                    f.x, f.y, f.hp = 500.0 + i * 80, 760.0, 100.0
                    f.vx = f.vy = f.stun = 0.0
                    f.on_ground, f.grabbed = True, False
                    f.effects = {}
                self.fight(self.a, self.b)
                quiet, hits, earned = [], [], []
                old_hit, old_bond = self.social.on_hit, self.social._bond

                def hit(a, b, damage):
                    hits.append(damage)
                    return old_hit(a, b, damage)

                def bond(a, b, delta):
                    if delta > 0:
                        earned.append(delta)
                    return old_bond(a, b, delta)

                self.social.on_hit, self.social._bond = hit, bond
                try:
                    for _ in range(60 * 60):
                        self.app.update(1 / 60)
                        quiet += [s["kind"] for s in self.social.scenes
                                  if s["kind"] in QUIET and len(s["actors"]) == 2]
                        if earned:
                            break
                finally:
                    self.social.on_hit, self.social._bond = old_hit, old_bond
                self.assertTrue(hits, "The scenario must actually fight")
                self.assertTrue(quiet, "A fight must leave time for a shared quiet scene")
                self.assertTrue(earned, "The real completed scene must earn the bond")
                print("seed %d: %d hits, shared %s, earned %s" %
                      (seed, len(hits), quiet[0] if quiet else "none", earned))

    def test_bout_clock_survives_attack_state_resets(self):
        self.social.next_scene = 1000
        self.fight(self.a, self.b)
        self.a.atk_cd = 1000
        self.app._st_fight(self.a, .025, self.a.K())
        # A weapon returns to fight with st=0 after every swing.
        self.social.time += 19
        self.a.set_state("fight")
        self.app._st_fight(self.a, .025, self.a.K())
        self.assertEqual("idle", self.a.state)
        self.assertTrue(self.social.recovering(self.a))
        self.assertTrue(self.social.recovering(self.b))
        self.assertEqual({}, self.gm.MEM["relationships"])

    def test_break_is_bounded_and_new_targets_respect_it(self):
        self.social.rest_after_fight(self.a, self.b)
        deadline = self.social._recover_until[self.a.kind]
        self.social.time += 6
        self.social.rest_after_fight(self.a, self.b)
        self.assertEqual(deadline, self.social._recover_until[self.a.kind])
        self.assertIsNone(self.app.nearest_enemy(self.a))
        self.assertIsNone(self.app.nearest_enemy(self.c))
        self.app.decide(self.a)
        self.assertEqual("idle", self.a.state)
        self.social.time += 7
        self.assertFalse(self.social.recovering(self.a))
        self.assertIsNotNone(self.app.nearest_enemy(self.a))
        self.assertLessEqual(len(self.social._recover_until), 10)

    def test_battle_scenes_off_and_peaceful_keep_their_semantics(self):
        for mode, scenes in (("battle", True), ("mischief", False), ("peaceful", True)):
            with self.subTest(mode=mode, scenes=scenes):
                self.gm.CFG.update(play_mode=mode, group_scenes=scenes)
                self.fight(self.a, self.b)
                self.social.rest_after_fight(self.a, self.b)
                self.assertFalse(self.social.recovering(self.a))
                self.assertFalse(self.social.fight_break(self.a, self.b))
                self.assertFalse(self.social.rest_decision(self.a))
                if mode == "peaceful":
                    hp = self.b.hp
                    self.app.hit_fighter(self.a, self.b, 20)
                    self.assertEqual(hp, self.b.hp)
                else:
                    self.assertIsNotNone(self.app.nearest_enemy(self.a))
                    self.app._st_fight(self.a, .025, self.a.K())
                    self.assertIn(self.a.state, ("fight", "attack"))

    def test_recovery_does_not_own_or_cancel_other_activities(self):
        self.social.rest_after_fight(self.a, self.b)
        for state in ("grabbed", "ko", "ride", "float", "thrown", "jump", "attack"):
            with self.subTest(state=state):
                self.a.state = state
                self.a.on_ground = False
                self.a.grabbed = state == "grabbed"
                self.assertFalse(self.social.rest_decision(self.a))
                self.assertFalse(self.social.fight_break(self.a, self.b))
                self.social.update(.1)
                self.assertEqual(state, self.a.state)
        self.a.grabbed, self.a.on_ground, self.a.state = False, True, "idle"
        self.social.clear()
        self.b.state, self.b.on_ground = "idle", True
        self.social.rest_after_fight(self.a, self.b)
        self.assertTrue(self.social.start_scene("coffee", [self.a, self.b]))
        self.assertLessEqual(len(self.social.scenes), self.social.MAX_SCENES)
        self.assertEqual("social", self.a.state)
        self.a.set_state("grabbed")
        self.a.grabbed = True
        self.social.update(.1)
        self.assertEqual("grabbed", self.a.state)
        self.assertNotIn(self.a, self.social.owned)

    def test_recovery_still_takes_damage_and_respects_scene_caps(self):
        self.social.rest_after_fight(self.a, self.b)
        self.app.hit_fighter(self.c, self.a, 5)
        self.assertLess(self.a.hp, 100)
        self.assertEqual("thrown", self.a.state)
        self.a.on_ground = True
        self.a.set_state("idle")
        self.assertTrue(self.social.start_scene("coffee", [self.a]))
        self.assertTrue(self.social.start_scene("juggling", [self.b]))
        self.assertFalse(self.social.start_scene("coffee", [self.c]))
        self.app.fighters.remove(self.c)
        self.social.update(.1)
        self.assertLessEqual(len(self.social.scenes), 2)
        self.social.clear()
        self.assertEqual({}, self.social._recover_until)
        self.assertEqual({}, self.social._fight_started)


if __name__ == "__main__":
    unittest.main()
