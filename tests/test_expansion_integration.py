"""Public settings, stable cast identities and mode boundaries for the expansion."""
import json
import unittest
from unittest import mock

import harness


class ExpansionIntegration(unittest.TestCase):
    def setUp(self):
        self.gm = harness.load("expansion_integration", group_scenes=False,
                               parkour=False, toy_props=False)
        self.app = None

    def tearDown(self):
        harness.teardown(self.gm, self.app)

    def build(self):
        gm = self.gm
        original = gm.tk.Tk

        def root():
            window = original()
            window.withdraw()
            return window

        with mock.patch.object(gm.tk, "Tk", root), \
                mock.patch.object(gm, "virtual_screen", return_value=(0, 0, 900, 700)), \
                mock.patch.object(gm, "monitors", return_value=[
                    ((0, 0, 900, 700), (0, 0, 900, 660))]):
            self.app = harness.build(gm)
        harness.fake_terrain(self.app)
        return self.app

    def test_custom_cast_preserves_survivors_by_identity(self):
        gm = self.gm
        self.assertIn("cast", gm.DEFAULTS)
        gm.CFG["cast"] = "veteran,magpie"
        app = self.build()
        self.assertEqual([f.kind for f in app.fighters], ["veteran", "magpie"])
        survivor = app.fighters[1]
        survivor.hp = 61
        gm.CFG["cast"] = "magpie,coward"
        app.apply_settings()
        self.assertIs(app.fighters[0], survivor)
        self.assertEqual(survivor.hp, 61)
        self.assertEqual([f.kind for f in app.fighters], ["magpie", "coward"])

    def test_profiles_round_trip_and_render_without_mutating_personality(self):
        gm = self.gm
        self.assertIn("profiles", gm.DEFAULTS)
        gm.CFG.update(cast="tinkerer", profiles=json.dumps({"tinkerer": {
            "nickname": "Wrench", "color": "#12ABEF", "hat": "crown",
            "weapons": ["bow"]}}))
        app = self.build()
        f = app.fighters[0]
        self.assertEqual((f.nickname, f.custom_color, f.hat), ("Wrench", "#12ABEF", "crown"))
        self.assertEqual(f.per["weapons"], ("bow",))
        self.assertNotEqual(gm.TRAITS["tinkerer"]["weapons"], ("bow",))
        self.assertEqual({gm.plan_weapon(f.per) for _ in range(20)}, {"bow"})
        app.draw()
        items = app.canvas.find_withtag("costume")
        self.assertTrue(items, "a selected accessory must be drawn on the real canvas")
        app.hover = f
        app.draw()
        self.assertTrue(any(app.canvas.type(i) == "text" and app.canvas.itemcget(i, "text") == "Wrench"
                            for i in app.canvas.find_all()))
        self.assertTrue(gm.save_settings(gm.CFG))
        self.assertEqual(json.loads(gm.load_settings()["profiles"])["tinkerer"]["nickname"], "Wrench")

    def test_invalid_profiles_and_cast_are_normalized_independently(self):
        gm = self.gm
        self.assertIn("profiles", gm.DEFAULTS)
        with open(gm.SETTINGS_PATH, "w", encoding="utf-8") as out:
            json.dump({"cast": "veteran,veteran,missing,coward", "crowd": 7,
                       "profiles": json.dumps({"veteran": {"nickname": "A\nB",
                           "color": "not-a-color", "hat": "missing"}}),
                       "play_mode": "invalid", "fps": 30}, out)
        cfg = gm.load_settings()
        self.assertEqual(cfg["cast"], "veteran,coward")
        self.assertEqual(cfg["fps"], 30)
        self.assertEqual(cfg["play_mode"], "mischief")
        profile = json.loads(cfg["profiles"])["veteran"]
        self.assertEqual(profile["nickname"], "A B")
        self.assertEqual(profile["color"], "")
        self.assertEqual(profile["hat"], "none")

    def test_peaceful_and_empty_loadout_block_damage_and_firing(self):
        gm = self.gm
        self.assertIn("play_mode", gm.DEFAULTS)
        app = self.build()
        a, b = app.fighters
        a.foe, a.plan = b, "blaster"
        gm.CFG["play_mode"] = "peaceful"
        app.apply_settings()
        hp = b.hp
        app.hit_fighter(a, b, 30)
        app.start_attack(a, foe=True)
        self.assertEqual(b.hp, hp)
        self.assertNotEqual(a.state, "attack")
        self.assertFalse(app.shots)
        gm.CFG["play_mode"] = "battle"
        gm.CFG["profiles"] = json.dumps({a.kind: {"weapons": []}})
        app.apply_settings()
        a.foe = b
        app.start_attack(a, foe=True)
        self.assertNotEqual(a.state, "attack")
        self.assertFalse(app.combat_allowed(a))

    def test_settings_expose_all_features_and_apply_cast_and_profiles(self):
        gm = self.gm
        self.assertIn("cast", gm.DEFAULTS)
        app = self.build()
        app.open_settings()
        win = app.settings_win
        win.win.withdraw()
        self.assertEqual(set(win.vars), set(gm.DEFAULTS))
        win.vars["cast"].set("drama,veteran")
        win.vars["profiles"].set(json.dumps({"drama": {"nickname": "Ham", "hat": "cap"}}))
        win.vars["play_mode"].set("peaceful")
        win.apply()
        self.assertEqual([f.kind for f in app.fighters], ["drama", "veteran"])
        self.assertEqual(app.fighters[0].nickname, "Ham")
        self.assertEqual(gm.load_settings()["play_mode"], "peaceful")

    def test_toys_survive_independent_parkour_setting(self):
        gm = self.gm
        gm.CFG["toy_props"] = True
        app = self.build()
        toy = app.motion.add_prop("crate", 500, 650)
        self.assertIsNotNone(toy)
        app.apply_settings()
        self.assertIn(toy, app.motion.props)
        self.assertIn(("toy", toy["id"]), app.navigation_targets())
        gm.CFG["toy_props"] = False
        app.apply_settings()
        self.assertFalse(app.motion.props)

    def test_relationship_loader_clamps_huge_integers_and_rejects_nonfinite_scores(self):
        gm = self.gm
        with open(gm.MEMORY_PATH, "w", encoding="utf-8") as output:
            json.dump({"runs": 7, "relationships": {
                "veteran|tinkerer": 10 ** 400, "brawler|sniper": float("nan"),
                "coward|magpie": -25, "unknown|grump": 20}}, output)
        memory = gm.load_memory()
        self.assertEqual(memory["runs"], 7)
        self.assertEqual(memory["relationships"], {"tinkerer|veteran": 100, "coward|magpie": -25})

    def test_rope_hands_keep_contact_during_entry_blend(self):
        self.gm.CFG["parkour"] = True
        app = self.build()
        f = app.fighters[0]
        f.x, f.y, f.on_ground, f.vx = 400, 400, False, 150
        f.set_state("idle")
        app.draw()
        self.assertTrue(app.motion.start(f, "rope", (430, 220)))
        app.update(.01)
        app.draw()
        rope = next(app.canvas.coords(i) for i in app.canvas.find_withtag("toys")
                    if app.canvas.type(i) == "line" and len(app.canvas.coords(i)) == 4)
        hand = app.canvas.coords(app._pool[app._ftag[0][3]]["line"][0])[-2:]
        self.assertAlmostEqual(hand[0], rope[2], delta=2)
        self.assertAlmostEqual(hand[1], rope[3], delta=2)


if __name__ == "__main__":
    unittest.main()
