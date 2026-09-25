"""Bounded, local-only friendships and short scenes on the existing Tk canvas.

Actors remain ordinary Fighters. A scene owns them only while their state is
``social``; an outside state change always wins. Props belong to the scene,
and only finite scores between stable roster identities reach saved memory.
"""
import math
import random


ROSTER = frozenset(("brawler", "sniper", "coward", "showoff", "grump",
                    "magpie", "zealot", "tinkerer", "drama", "veteran"))
QUIET = ("cards", "football", "juggling", "blanket_nap", "coffee")
HOSTILE = frozenset(("alliance", "hat_heist", "surrender", "court", "spectators"))
DURATIONS = {"alliance": 4.5, "rescue": 4.2, "hat_heist": 7.5,
             "surrender": 4.0, "spectators": 8.0, "court": 7.5,
             "cards": 8.0, "football": 8.0, "juggling": 7.0,
             "blanket_nap": 9.0, "coffee": 7.0, "inspect": 5.0}
MIN_ACTORS = {"alliance": 3, "rescue": 2, "hat_heist": 3,
              "surrender": 2, "spectators": 3, "court": 3,
              "cards": 2, "football": 2, "juggling": 1,
              "blanket_nap": 1, "coffee": 1, "inspect": 1}
# A landed hit is a grudge, not an integral. `on_hit` is the only bond source
# with no scene gate behind it, so without an interval it charged once per hit
# -- about once a second in a brawl -- and floored every pair within minutes.
# Once floored, nobody was ever idle enough for `_available()` to start a scene,
# so the positive terms stopped firing and the ratchet sustained itself.
HIT_BOND_INTERVAL = 6.0
# Ordinary fighting makes rivals, never permanent enemies, and it says so by
# construction rather than by tuning: the hit channel simply stops here. Relying
# on decay to counterbalance it instead meant the equilibrium depended on how
# many pairs the hits were spread across -- fine at a crowd of six, still a slow
# ratchet to the floor at a crowd of two. Betrayal and the scene penalties are
# rare and scene-gated, and may still take a pair below this.
HIT_BOND_FLOOR = -70.0
# Scores fade on run time. Grudges fade far faster than friendships: they are
# generated continuously by the thing the cast does most, while a friendship
# needs a whole scene to complete. Decaying both at one rate made every
# friendship expire below the `affinity >= 15` ally gate about two minutes after
# the scene that earned it.
GRUDGE_HALF_LIFE = 420.0
BOND_HALF_LIFE = 1800.0
BOND_EPSILON = 0.5            # below this a pair is forgotten, not stored
# Decay accumulates this much before it is worth a save. It is CUMULATIVE, not
# per pass: one pass can only ever move the largest possible score by 0.21
# (|100| at the 420s half-life over the 1.25s of run time update() can hand it),
# so comparing a single tick against any threshold above that never fires at
# all -- decay then lives in memory only and a quiet desktop saves a grudge it
# has already forgotten.
BOND_STEP = 1.0
FREE_STATES = frozenset(("idle", "walk", "taunt"))
# Mischief alternates short bouts with breathing room for ordinary scenes.
# These clocks govern new decisions, never damage, flight or scene ownership.
FIGHT_BOUT = 18.0
FIGHT_RECOVERY = 12.0
RESCUABLE = frozenset(("ko", "fall", "thrown", "ledge", "cling", "foam",
                      "bubble", "frozen", "stuck"))
INK, PAPER, GOLD, WOOD = "#38415b", "#fff5d9", "#efc55e", "#a9754d"
GREEN, RED, BLUE = "#73c99a", "#ef7d8a", "#70b9df"

# Each personality supplies its own delivery, including quiet grumbling and
# nervous/boastful body timing. No additions to the existing combat voice keys.
VOICE = {"brawler": ("Right. Together!", "Got you, mate.", "Fair's fair."),
         "sniper": ("Positions checked.", "Hold still. I've got this.", "Evidence accepted."),
         "coward": ("This is safe... right?", "Don't look down!", "Can we shake on it?"),
         "showoff": ("Watch a professional.", "Another flawless save!", "A standing ovation?"),
         "grump": ("Fine. Five minutes.", "Stop dangling about.", "Pay up. Then hush."),
         "magpie": ("Ooh. Shiny opportunity.", "You owe me a shiny.", "I'll hold the evidence."),
         "zealot": ("For the cause!", "No gremlin left behind!", "Justice is served!"),
         "tinkerer": ("I have a small plan.", "Emergency repair underway.", "The facts line up."),
         "drama": ("A scene worthy of me!", "Rescued from certain doom!", "I demand a retrial!"),
         "veteran": ("Steady. We know the drill.", "Easy. One hand at a time.", "Call it even." )}


def _clamp(value, low, high):
    return max(low, min(high, value))


def _number(value, default=0.0):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return default


class SocialDirector:
    MAX_SCENES = 2

    def __init__(self, app, cfg, memory_getter, mark_dirty):
        self.app, self.cfg = app, cfg
        self.memory_getter, self.mark_dirty = memory_getter, mark_dirty
        self.scenes, self.alliances, self.stickers = [], [], []
        self.owned, self.cooldowns = {}, {}
        self._hit_bond = {}       # pair key -> when a hit last deepened it
        self._fight_started, self._recover_until = {}, {}
        self._decay_due = 0.0     # decay runs about once a second, not per frame
        self._decay_drift = 0.0   # fade not yet persisted, in score units
        self.time, self.next_scene, self.window_cooldown = 0.0, 8.0, 0.0
        self.next_rescue = 0.0
        self.last_hit = None

    @staticmethod
    def _key(a, b):
        ak, bk = getattr(a, "kind", ""), getattr(b, "kind", "")
        if ak == bk or ak not in ROSTER or bk not in ROSTER:
            return None
        return "|".join(sorted((ak, bk)))

    def _relations(self):
        memory = self.memory_getter()
        records = memory.get("relationships")
        if not isinstance(records, dict):
            records = memory["relationships"] = {}
        return records

    def affinity(self, a, b):
        key = self._key(a, b)
        if key is None:
            return 0.0
        for pact in self.alliances:
            if a in pact["members"] and b in pact["members"] and pact["until"] > self.time:
                return 100.0
        return _clamp(_number(self._relations().get(key)), -100.0, 100.0)

    def alliance_target(self, f):
        """Combat honors the pact's common target until betrayal or expiry."""
        if self.cfg.get("play_mode") == "peaceful":
            return None
        for pact in self.alliances:
            if f not in pact["members"] or pact["until"] <= self.time:
                continue
            target = pact["target"]
            if all(actor in self.app.fighters and not actor.grabbed and actor.hp > 0
                   and actor.state not in ("sleep", "ko")
                   for actor in pact["members"] + (target,)):
                return target
        return None

    def _pacing_enabled(self):
        return (self.cfg.get("group_scenes", True) and
                self.cfg.get("play_mode") == "mischief")

    def recovering(self, f):
        return (self._pacing_enabled() and f is not None and
                self._recover_until.get(f.kind, 0) > self.time)

    def can_engage(self, a, b):
        """Recovery affects target choice; existing projectiles still hit."""
        return not (self.recovering(a) or self.recovering(b))

    def rest_after_fight(self, *actors):
        if not self._pacing_enabled():
            return
        for f in actors:
            if f is not None and f in self.app.fighters:
                # A late hit cannot keep extending somebody's break forever.
                if not self.recovering(f):
                    self._recover_until[f.kind] = self.time + FIGHT_RECOVERY
                self._fight_started.pop(f.kind, None)
        # Nominate soon, after the fighters have actually landed and yielded.
        self.next_scene = min(self.next_scene, self.time + .5)

    def fight_break(self, f, foe):
        """Called between attacks, only when normal grounded combat can yield."""
        if (not self._pacing_enabled() or not f.on_ground or f.grabbed or
                f.carry or f.mount or f.ridden_by):
            return False
        started = self._fight_started.setdefault(f.kind, self.time)
        if (self.recovering(f) or self.recovering(foe) or
                self.time - started >= FIGHT_BOUT):
            self.rest_after_fight(f, foe)
            return True
        return False

    def rest_decision(self, f):
        if not self.recovering(f) or not self._available(f):
            return False
        f.foe = f.target = None
        f.mode = "roam"
        f.set_state("idle")
        f.goal = getattr(self.app, "time", 0) + 1.0
        return True

    def _bond(self, a, b, delta):
        key = self._key(a, b)
        if key is None:
            return
        relations = self._relations()
        # Bound the saved graph to the 45 possible stable pairs. Invalid data
        # is discarded at this write boundary as well as by the loader.
        for bad in list(relations):
            parts = bad.split("|") if isinstance(bad, str) else []
            if (len(parts) != 2 or parts[0] == parts[1] or
                    not all(p in ROSTER for p in parts) or parts != sorted(parts)):
                del relations[bad]
        score = _clamp(_number(relations.get(key)) + _number(delta), -100.0, 100.0)
        if relations.get(key) != score:
            relations[key] = score
            self.mark_dirty()

    def _decay(self, elapsed):
        """Pull every saved score toward zero, so grudges and friendships fade.

        This runs before the group_scenes gate on purpose: hits still lower
        bonds with scenes switched off, and that direction has no counterpart
        at all there, so skipping decay would leave the worst ratchet of the lot.

        Only a drift worth persisting marks memory dirty. Marking on every pass
        instead turned an event-driven flag into a permanently set one, and
        `save_memory` then rewrote the file every sixty seconds for the life of
        the process -- on a desktop where nothing had happened.
        """
        relations = self._relations()
        if not relations:
            return
        elapsed = _clamp(_number(elapsed), 0, 60)
        fade = .5 ** (elapsed / GRUDGE_HALF_LIFE)
        warm = .5 ** (elapsed / BOND_HALF_LIFE)
        changed, drift = False, 0.0
        for key in list(relations):
            was = _number(relations.get(key))
            score = was * (fade if was < 0 else warm)
            if abs(score) < BOND_EPSILON:
                del relations[key]        # forgotten entirely, not stored as ~0
                changed = True
            else:
                relations[key] = score
                drift = max(drift, abs(score - was))
        self._decay_drift += drift
        if changed or self._decay_drift >= BOND_STEP:
            self._decay_drift = 0.0
            self.mark_dirty()

    def on_hit(self, att, vic, dmg):
        damage = _number(dmg)
        if att is vic or damage <= 0 or self.cfg.get("play_mode") == "peaceful":
            return
        if damage >= vic.hp:
            # Schedule a break, but let hit_fighter own the knockout and let
            # the winner finish any unrelated activity already in progress.
            self.rest_after_fight(att, vic)
        # One fight is one grudge per interval, and fighting alone stops at
        # HIT_BOND_FLOOR. Charging per landed hit with no bound drove every pair
        # to the -100 floor inside three minutes; see HIT_BOND_INTERVAL.
        key = self._key(att, vic)
        if key is not None and self.time - self._hit_bond.get(key, -1e9) >= HIT_BOND_INTERVAL:
            self._hit_bond[key] = self.time
            # The stored score, not affinity(): that reports 100 for a live
            # pact, which would hand a fighting pair the full step every time.
            room = _number(self._relations().get(key)) - HIT_BOND_FLOOR
            if room > 0:
                self._bond(att, vic, -min(6.0, .8 + damage * .15, room))
        self.last_hit = (att, vic, self.time)
        for pact in list(self.alliances):
            if att in pact["members"] and vic in pact["members"]:
                # Friendly fire breaks the temporary team immediately.
                self.alliances.remove(pact)
                self._bond(att, vic, -30)
                vic.foe = att
                vic.say("You were on MY side!", 2.0)
        for scene in self.scenes:
            if scene["kind"] == "spectators" and att in scene["actors"][1:]:
                scene["score"] = min(10, max(1, round(damage / 3)))
                scene["scored_at"] = scene["t"]
                scene["actors"][0].scene_action = "cheer"

    def _available(self, f):
        return (f in self.app.fighters and f not in self.owned and
                not getattr(f, "grabbed", False) and f.hp > 0 and
                f.state in FREE_STATES and f.on_ground and
                not getattr(f, "carry", None) and not getattr(f, "mount", None) and
                not getattr(f, "ridden_by", None) and
                self.cooldowns.get(f.kind, 0) <= self.time)

    def _rescuable(self, f):
        effects = getattr(f, "effects", {})
        return (f.state in RESCUABLE or (isinstance(effects, dict) and
                any(name in effects for name in ("foam", "bubble", "freeze"))))

    def start_scene(self, kind, actors=None):
        if (kind not in DURATIONS or not self.cfg.get("group_scenes", True) or
                len(self.scenes) >= self.MAX_SCENES or
                (self.cfg.get("play_mode") == "peaceful" and kind in HOSTILE)):
            return False
        candidates = [f for f in self.app.fighters if self._available(f)]
        if actors is None:
            if kind == "rescue":
                victim = next((f for f in self.app.fighters if self._rescuable(f)
                               and f not in self.owned and not f.grabbed), None)
                if victim is None:
                    return False
                helpers = sorted(candidates, key=lambda f: self.affinity(f, victim), reverse=True)
                actors = helpers[:1] + [victim]
            elif kind == "alliance" and len(candidates) >= 3:
                strongest = max(candidates, key=lambda f: f.hp + f.per.get("aggro", 1) * 15)
                actors = [f for f in candidates if f is not strongest][:2] + [strongest]
            else:
                actors = candidates[:max(MIN_ACTORS[kind], min(2, len(candidates)))]
        actors = list(actors)[:4]
        if len(actors) < MIN_ACTORS[kind] or len(set(actors)) != len(actors):
            return False
        owned = actors[:1] if kind == "spectators" else actors
        for i, f in enumerate(actors):
            if kind == "spectators" and i > 0:
                if f not in self.app.fighters or f.grabbed or f.hp <= 0:
                    return False
                continue
            if kind == "rescue" and i == 1:
                if f not in self.app.fighters or f in self.owned or f.grabbed or not self._rescuable(f):
                    return False
            elif not self._available(f):
                return False
        center = sum(f.x for f in actors) / len(actors)
        center = _clamp(center, self.app.ox + 95, self.app.ox + self.app.W - 95)
        scene = {"kind": kind, "actors": actors, "owned": owned, "t": 0.0,
                 "x": center, "y": self.app.ground_at(center), "stage": -1,
                 "orig": {f: (f.x, f.y, f.state, f.hp, f.on_ground) for f in owned},
                 "score": 0, "scored_at": -10, "stolen": False, "done": False}
        if kind == "rescue":
            scene["x"] = _clamp(actors[1].x, self.app.ox + 35, self.app.ox + self.app.W - 35)
            scene["y"] = self.app.ground_at(scene["x"])
        self.scenes.append(scene)
        for f in owned:
            self.owned[f] = scene
            f.set_state("social")
            f.scene_action = "walk"
            f.vx = f.vy = 0.0
            f.foe = f.target = None
            f.goal = getattr(self.app, "time", 0) + DURATIONS[kind]
        if kind == "rescue":
            # Arsenal keeps the victim's bindings drawn while the rescuer
            # approaches; only the successful haul removes those effects.
            actors[1].social_rescue = True
        elif kind == "hat_heist":
            hat = getattr(actors[1], "hat", "none")
            scene["heist_hat"] = hat if hat != "none" else "tophat"
            if hat == "none":
                # A borrowed stage hat makes the scene available to the
                # default bare-headed cast without changing saved appearance.
                actors[1].scene_hat = scene["heist_hat"]
        actors[0].say(VOICE[actors[0].kind][1 if kind == "rescue" else 0], 1.8)
        # One ambient nomination at a time. Explicit menu starts still obey
        # actor cooldowns and the coordinator's simultaneous-scene cap.
        self.next_scene = max(self.next_scene, self.time + 10)
        return True

    def _move(self, f, x, y, dt, speed=95):
        dx, dy = x - f.x, y - f.y
        distance = math.hypot(dx, dy)
        if distance > .1:
            step = min(distance, dt * speed * (.5 + f.sc))
            f.x += dx / distance * step
            f.y += dy / distance * step
            f.face = 1 if dx >= 0 else -1
            f.walk += step / max(8, 15 * f.sc)
        f.vx = f.vy = 0.0

    def _stage(self, scene, stage):
        changed = scene["stage"] != stage
        scene["stage"] = stage
        return changed

    def _advance(self, s, dt):
        t, kind, actors = s["t"], s["kind"], s["actors"]
        a, x, y = actors[0], s["x"], s["y"]
        if kind == "rescue":
            b = actors[1]
            self._move(a, x - 28 * a.sc, y, dt, 130)
            a.scene_action = "walk" if t < 1.2 else "reach" if t < 2.2 else "kneel"
            b.scene_action = "hanging" if s["orig"][b][2] in ("fall", "ledge", "cling", "bubble") else "nap"
            if t >= 1.5:
                # The visible rope goes taut before the friend is hauled in.
                self._move(b, x + 12, y, dt, 115)
            if t >= 3 and self._stage(s, 1):
                arsenal = getattr(self.app, "arsenal", None)
                if arsenal is not None:
                    release = getattr(arsenal, "release_bindings", None)
                    if release:
                        release(b)
                    else:
                        arsenal.clear(b)
                b.hp, b.stun, b.tumble = max(30.0, b.hp), 0.0, 0.0
                b.on_ground = True
                b.scene_action = "sit"
                self._bond(a, b, 18)
                b.say(VOICE[b.kind][2], 1.7)
        elif kind == "alliance":
            b, strongest = actors[1:3]
            self._move(a, x - 30, y, dt)
            self._move(b, x + 5, y, dt)
            self._move(strongest, x + 100, y, dt)
            a.scene_action = b.scene_action = "reach" if t > 1.3 else "walk"
            strongest.scene_action = "lookout"
            a.face, b.face = 1, -1
            if t > 2 and self._stage(s, 1):
                strongest.say("Two against one?", 1.8)
        elif kind == "hat_heist":
            victim, lookout = actors[1:3]
            self._move(victim, x + 28, y, dt)
            self._move(lookout, x + 90, y, dt)
            lookout.scene_action = "lookout" if t < 1.5 else "cheer"
            lookout.face, victim.face = -1, 1
            victim.scene_action = "lookout" if t < 2.3 else "surrender"
            if t < 2.4:
                self._move(a, victim.x - 15, y, dt, 125)
                a.scene_action = "walk" if t < 1.5 else "reach"
            else:
                if not s["stolen"]:
                    # Hats are temporary overrides; saved profiles never move.
                    s["stolen"] = True
                    a.scene_hat, victim.scene_hat = s["heist_hat"], "none"
                    self._bond(a, victim, -16)
                    self._bond(a, lookout, 7)
                    victim.say("My hat!", 1.8)
                a.scene_action = "walk"
                self._move(a, x - 115, y, dt, 130)
                if t > 4.5:
                    victim.scene_action = "walk"
                    self._move(victim, a.x + 30, y, dt, 70)
        elif kind == "surrender":
            victim = actors[1]
            a.scene_action = "surrender" if t < 1.8 else "walk"
            if t < 1.8:
                self._move(a, x - 22, y, dt)
            else:
                # Leave a spring under the white flag, then invite the rival
                # into its small contact radius while backing away.
                self._move(a, x - 95, y, dt)
                victim.scene_action = "walk"
                self._move(victim, x - 22, y, dt, 65)
            if t > 3.3 and abs(victim.x - (x - 22)) < 18:
                s["trap_hit"] = True
                self._bond(a, victim, -18)
                s["done"] = True
        elif kind == "spectators":
            left, right = actors[1:3]
            self._move(a, _clamp(min(left.x, right.x) - 70, self.app.ox + 35,
                                 self.app.ox + self.app.W - 35), y, dt)
            a.face = 1 if (left.x + right.x) / 2 >= a.x else -1
            a.scene_action = "cheer" if t - s["scored_at"] < 1 else "sit"
        elif kind == "court":
            defendant, judge = actors[1:3]
            self._move(a, x - 65, y, dt)
            self._move(defendant, x + 65, y, dt)
            self._move(judge, x, y, dt)
            a.face, defendant.face = 1, -1
            a.scene_action = "reach" if t < 3 else "sit"
            defendant.scene_action = "surrender" if t < 3 else "reach"
            judge.scene_action = "throw" if 2 < t < 4.5 else "sit"
            if t > 4.5 and self._stage(s, 1):
                self._bond(a, defendant, 20)
                a.anger = defendant.anger = 0.0
                judge.say(VOICE[judge.kind][2], 2)
        elif kind == "inspect":
            rect = self.app.terrain.win_rect.get(s.get("window"))
            if rect is None:
                s["done"] = True
                return
            l, top, r, bottom = rect
            for i, f in enumerate(actors):
                self._move(f, l + 15 if i == 0 else r - 15, top, dt, 180)
                f.scene_action = "inspect" if t > 1 else "walk"
                f.face = 1 if i == 0 else -1
            if t > 3.5 and self._stage(s, 1):
                self.stickers.append({"window": s["window"], "until": self.time + 8})
                del self.stickers[:-3]
                a.say("Measured. Approved.", 1.4)
        else:
            for i, f in enumerate(actors):
                px = x + (i - (len(actors) - 1) / 2) * 66
                self._move(f, px, y, dt)
                f.face = 1 if i == 0 else -1
                if t < 1:
                    f.scene_action = "walk"
                elif kind == "football":
                    f.scene_action = "kick" if int(t * 1.4) % len(actors) == i else "lookout"
                    # Players shuffle with the pass so it is a game of catch
                    # and kicks rather than a ball orbiting stationary actors.
                    self._move(f, px + math.sin(t * 1.4 + i * math.pi) * 16, y, dt)
                elif kind == "juggling":
                    f.scene_action = "juggle" if i == 0 else "cheer"
                elif kind == "blanket_nap":
                    f.scene_action = "nap"
                elif kind == "coffee":
                    f.scene_action = "sip" if math.sin(t * 2 + i) > 0 else "sit"
                else:
                    f.scene_action = "deal" if int(t * 1.5) % len(actors) == i else "sit"

    def _finish(self, scene, completed=False):
        if scene not in self.scenes:
            return
        self.scenes.remove(scene)
        kind, actors = scene["kind"], scene["actors"]
        for f in scene["owned"]:
            self.owned.pop(f, None)
            self.cooldowns[f.kind] = self.time + 9.0
            f.scene_hat = f.scene_action = None
            f.social_rescue = False
            if f.state == "social":
                # Cancellation preserves a pre-existing KO; external grabs,
                # hits and sleep already changed state and are never reset.
                bound = any(k in getattr(f, "effects", {}) for k in ("foam", "bubble", "freeze"))
                state = "ko" if f.hp <= 0 else "effect" if bound else "idle" if f.on_ground else "fall"
                f.set_state(state)
                f.goal = getattr(self.app, "time", 0) + 1.2
        if not completed:
            return
        if kind in QUIET:
            for f in actors:
                f.boredom, f.anger = max(0, f.boredom - .35), max(0, f.anger - .12)
                if kind in ("coffee", "blanket_nap"):
                    f.hp = min(100, f.hp + 8)
            for i, f in enumerate(actors):
                for other in actors[i + 1:]:
                    self._bond(f, other, 8)
        elif kind == "alliance":
            a, b, target = actors[:3]
            self._bond(a, b, 6)
            self.alliances.append({"members": (a, b), "target": target,
                                  "until": self.time + 18})
            del self.alliances[:-3]
            for f in (a, b):
                f.foe, f.mode = target, "roam"
                f.set_state("fight")
        elif kind == "rescue":
            victim = actors[1]
            arsenal = getattr(self.app, "arsenal", None)
            if arsenal is not None and "shield" not in getattr(victim, "effects", {}):
                arsenal.apply_effect(victim, "shield", 3.0, source=actors[0])
        elif kind == "surrender" and scene.get("trap_hit"):
            attacker, victim = actors[:2]
            arsenal = getattr(self.app, "arsenal", None)
            if arsenal is not None:
                arsenal.apply_effect(victim, "foam", 1.6, source=attacker)
            else:
                victim.stun = max(victim.stun, 1.6)
                victim.vy, victim.on_ground = -100 * victim.sc, False
                victim.set_state("thrown")
            victim.say("That was NOT a surrender!", 1.8)

    def control(self, f, dt):
        scene = self.owned.get(f)
        if scene is None:
            return False
        if f.state != "social" or f.grabbed or f not in self.app.fighters:
            self._finish(scene)
            return False
        return True

    def update(self, dt):
        dt = _clamp(_number(dt), 0, .25)
        self.time += dt
        if self._pacing_enabled():
            kinds = {f.kind for f in self.app.fighters}
            fighting = {f.kind for f in self.app.fighters
                        if f.mode == "fight" or f.state == "fight"}
            self._fight_started = {k: t for k, t in self._fight_started.items()
                                   if k in fighting}
            self._recover_until = {k: t for k, t in self._recover_until.items()
                                   if k in kinds and t > self.time}
            for f in self.app.fighters:
                started = self._fight_started.get(f.kind)
                if started is not None and self.time - started >= FIGHT_BOUT:
                    self.rest_after_fight(f, f.foe)
        else:
            self._fight_started.clear()
            self._recover_until.clear()
        self._decay_due += dt
        if self._decay_due >= 1.0:
            self._decay(self._decay_due)
            self._decay_due = 0.0
        if not self.cfg.get("group_scenes", True):
            self.clear()
            return
        peace = self.cfg.get("play_mode") == "peaceful"
        self.alliances[:] = [p for p in self.alliances if not peace and p["until"] > self.time
                            and all(f in self.app.fighters and not f.grabbed and f.hp > 0
                                    and f.state not in ("sleep", "ko")
                                    for f in p["members"] + (p["target"],))]
        self.stickers[:] = [p for p in self.stickers if p["until"] > self.time
                            and p["window"] in self.app.terrain.win_rect]
        for s in list(self.scenes):
            valid = all(f in self.app.fighters and not f.grabbed for f in s["actors"])
            valid = valid and all(f.state == "social" for f in s["owned"])
            if not valid or (peace and s["kind"] in HOSTILE):
                self._finish(s)
                continue
            s["t"] += dt
            self._advance(s, dt)
            if s["done"] or s["t"] >= DURATIONS[s["kind"]]:
                self._finish(s, completed=True)
        if self.time >= self.next_rescue:
            # A fall or ledge hang lasts less than an ambient scene interval.
            # This bounded ten-actor check lets friends catch it in time.
            self.next_rescue = self.time + .4
            self._try_rescue()
        if self.time >= self.next_scene:
            self.next_scene = self.time + (8 if self.cfg.get("play_mode") == "battle" else 5)
            self._consider()

    def _try_rescue(self):
        available = [f for f in self.app.fighters if self._available(f)]
        if not available or len(self.scenes) >= self.MAX_SCENES:
            return False
        # Friends are first responders. The threshold admits a new friendship
        # after a shared coffee but prevents rescuing the rival who just hit us.
        for victim in self.app.fighters:
            if self._rescuable(victim) and victim not in self.owned and not victim.grabbed:
                helpers = [f for f in available if f is not victim and self.affinity(f, victim) > 0
                           and abs(f.x - victim.x) < 350]
                if helpers and self.start_scene("rescue", [max(helpers, key=lambda f: self.affinity(f, victim)), victim]):
                    return True
        return False

    def _consider(self):
        available = [f for f in self.app.fighters if self._available(f)]
        if not available or len(self.scenes) >= self.MAX_SCENES:
            return
        resting = [f for f in available if self.recovering(f)]
        first = random.choice(resting or available)
        near = [f for f in available if f is not first and abs(f.x - first.x) < 400
                and abs(f.y - first.y) < 45]
        if resting and not near and any(
                f is not first and self.recovering(f) and f.hp > 0 and
                not f.grabbed and abs(f.x - first.x) < 400 and
                self._recover_until[f.kind] - self.time > FIGHT_RECOVERY - 3
                for f in self.app.fighters):
            # Let a nearby partner finish the swing or landing before giving
            # the first actor a solo scene that would occupy the whole break.
            self.next_scene = self.time + .5
            return
        random.shuffle(near)
        actors = [first] + near[:2]
        if self.cfg.get("play_mode") != "peaceful" and not resting:
            fighters = [f for f in self.app.fighters if f.state in ("fight", "attack") and f.hp > 0]
            if len(fighters) >= 2 and random.random() < .45:
                if self.start_scene("spectators", [first] + fighters[:2]):
                    return
            if len(actors) >= 3 and random.random() < .48:
                rivalry = self.affinity(actors[0], actors[1]) < -15
                kind = "court" if rivalry else "hat_heist" if first.per.get("thief", 1) > 1 else "alliance"
                if kind == "alliance":
                    actors.sort(key=lambda f: f.hp + f.per.get("aggro", 1) * 15)
                if self.start_scene(kind, actors):
                    return
            if len(actors) >= 2 and self.affinity(actors[0], actors[1]) < -10 and random.random() < .35:
                if self.start_scene("surrender", actors[:2]):
                    return
        options = QUIET if len(actors) > 1 else ("juggling", "blanket_nap", "coffee")
        kind = random.choice(options)
        self.start_scene(kind, actors[:2])

    def on_windows_changed(self, old, new):
        # Only anonymous handles and geometry live here, and only in RAM.
        if not isinstance(old, dict) or not isinstance(new, dict):
            return
        for s in list(self.scenes):
            if s["kind"] == "inspect" and s.get("window") not in new:
                self._finish(s)
        self.stickers[:] = [p for p in self.stickers if p["window"] in new]
        if not self.cfg.get("group_scenes", True) or self.time < self.window_cooldown:
            return
        for handle, rect in new.items():
            before = old.get(handle)
            if before is None or len(rect) != 4 or len(before) != 4:
                continue
            resized = abs((rect[2] - rect[0]) - (before[2] - before[0])) > 20 or abs((rect[3] - rect[1]) - (before[3] - before[1])) > 20
            if not resized:
                continue
            available = sorted((f for f in self.app.fighters if self._available(f)),
                               key=lambda f: abs(f.x - rect[0]))[:2]
            if available and self.start_scene("inspect", available):
                self.scenes[-1]["window"] = handle
                self.window_cooldown = self.time + 18
                return

    def clear(self, f=None):
        for scene in list(self.scenes):
            # Watched fighters are not owned by the scorecard scene. Their
            # normal hit cleanup must leave the spectator free to score it.
            if f is None or f in scene["owned"]:
                self._finish(scene)
        if f is None:
            self.alliances.clear()
            self.stickers.clear()
            self.cooldowns.clear()
            self._fight_started.clear()
            self._recover_until.clear()
            # _hit_bond deliberately survives: it is rate-limit state keyed by
            # character pair, not scene state keyed by actor. update() calls
            # clear() every frame when group_scenes is off, so wiping it here
            # reset the gate before it could ever expire and handed that
            # configuration the original per-hit ratchet back, with no positive
            # bond source at all to offset it. Measured at 119 hits: 20 grudge
            # steps with scenes on, 119 with them off.
            self.last_hit = None
            self.next_scene = self.time + 8

    def pose(self, f):
        if f not in self.owned or f.state != "social":
            return None
        action, t = getattr(f, "scene_action", "sit"), self.time
        px, py, lean, tilt = 0.0, -30.0, 0.0, 0.0
        feet, hands = ((-6, 0), (7, 0)), ((-10, -38), (10, -38))
        if action == "walk":
            stride = math.sin(f.walk) * 14
            feet = ((-stride, -max(0, math.cos(f.walk)) * 6),
                    (stride, -max(0, -math.cos(f.walk)) * 6))
            hands, lean = ((-stride * .6, -37), (stride * .6, -37)), .12
        elif action in ("sit", "deal", "sip", "kneel"):
            py, feet = -16, ((-18, 0), (18, 0))
            hands = ((-14, -23), (20, -25 if action == "deal" else -47 if action == "sip" else -23))
            lean = .18 if action == "kneel" else 0
        elif action == "nap":
            py, lean, tilt = -13 + math.sin(t * 2) * .6, -.5, .55
            feet, hands = ((-17, -1), (-4, 2)), ((-22, -19), (-6, -15))
        elif action in ("surrender", "cheer", "hanging"):
            wave = math.sin(t * 7) * 3 if action == "cheer" else 0
            hands = ((-22, -70 + wave), (22, -70 - wave))
        elif action in ("reach", "inspect"):
            lean, hands = .25, ((10, -43), (34, -49))
        elif action == "lookout":
            hands = ((-10, -37), (11, -67))
            tilt = .15 * math.sin(t * 2)
        elif action == "throw":
            hands = ((-10, -38), (20 + math.sin(t * 7) * 9, -54 - max(0, math.cos(t * 7)) * 15))
        elif action == "juggle":
            hands = ((-23, -39 - math.sin(t * 6) * 8), (23, -39 + math.sin(t * 6) * 8))
        elif action == "kick":
            lean, feet = -.18, ((-9, 0), (27, -15 - 8 * math.sin(t * 6)))
        if f.kind == "coward":
            tilt += math.sin(t * 14) * .035
        elif f.kind in ("showoff", "drama"):
            lean += math.sin(t * 3) * .06
        return px, py, lean, tilt, feet[0], feet[1], hands[0], hands[1]

    def _text(self, x, y, text, color=INK, size=9):
        self.app.text(x - self.app.ox - self.app.sx, y - self.app.oy - self.app.sy,
                      text, color, ("Segoe UI", size, "bold"))

    def draw(self):
        app = self.app
        app.layer("social")
        for pact in self.alliances:
            for f in pact["members"]:
                app.box(f.x - 15 * f.sc, f.y - 47 * f.sc, f.x - 8 * f.sc,
                        f.y - 42 * f.sc, GREEN, INK)
        for s in self.scenes:
            self._draw_scene(s)
        for sticker in self.stickers:
            rect = app.terrain.win_rect.get(sticker["window"])
            if rect:
                x, y = rect[2] - 44, rect[1] + 9
                app.box(x, y, x + 36, y + 22, GREEN, INK)
                app.line((x + 8, y + 11, x + 14, y + 17, x + 28, y + 5), PAPER, 3)

    def _draw_scene(self, s):
        app, actors, kind, t = self.app, s["actors"], s["kind"], s["t"]
        a, x, y = actors[0], s["x"], s["y"]
        scale = sum(f.sc for f in actors) / len(actors)
        if kind == "rescue":
            b = actors[1]
            hand = (a.x + 20 * a.sc, a.y - 43 * a.sc)
            app.line((*hand, (a.x + b.x) / 2, min(a.y, b.y) - 50 * scale,
                      b.x, b.y - 38 * b.sc), GOLD, max(2, 3 * scale))
            app.box(a.x - 20, y - 9, a.x - 3, y, PAPER, INK)
            app.line((a.x - 15, y - 5, a.x - 8, y - 5), RED, 2)
            app.line((a.x - 11, y - 8, a.x - 11, y - 2), RED, 2)
        elif kind == "alliance":
            for f in actors[:2]:
                app.box(f.x - 13, f.y - 35, f.x - 7, f.y - 29, GREEN, INK)
            if t > 2:
                target = actors[2]
                app.line((x, y - 65, target.x, target.y - 50), GREEN, 2)
                app.line((target.x - 8, target.y - 56, target.x, target.y - 50,
                          target.x - 9, target.y - 46), GREEN, 2)
        elif kind == "hat_heist":
            lookout = actors[2]
            # A little whistle supplies the distraction while the thief reaches.
            app.dot(lookout.x - 12, lookout.y - 40, 4, GOLD, INK)
            if 1.4 < t < 3.5:
                for i in range(3):
                    xx = lookout.x - 24 - i * 9
                    app.line((xx, lookout.y - 50 - i * 4, xx - 4, lookout.y - 43 - i * 4), GOLD, 2)
        elif kind == "surrender":
            pole_x = a.x + 16 if t < 1.8 else x - 22
            app.line((pole_x, y, pole_x, y - 61), WOOD, 2)
            app.box(pole_x, y - 61, pole_x + 23, y - 46, PAPER, INK)
            if t > 1.3:
                app.line((x - 36, y - 1, x - 30, y - 7, x - 24, y - 1,
                          x - 18, y - 7, x - 12, y - 1), GREEN, 3)
        elif kind == "spectators":
            card_x, card_y = a.x + a.face * 23, a.y - 56 - (5 if t - s["scored_at"] < 1 else 0)
            app.line((card_x, card_y + 15, card_x, card_y + 30), WOOD, 2)
            app.box(card_x - 14, card_y - 12, card_x + 16, card_y + 15, PAPER, INK)
            self._text(card_x - 7, card_y + 1, str(s["score"]) if s["score"] else "?", RED, 12)
        elif kind == "court":
            app.box(x - 26, y - 25, x + 26, y - 4, WOOD, INK)
            for side in (-1, 1):
                app.box(x + side * 65 - 21, y - 12, x + side * 65 + 21, y - 5, WOOD, INK)
            gy = y - 34 - abs(math.sin(t * 7)) * 16 if 2 < t < 4.5 else y - 34
            app.line((x + 8, y - 30, x + 18, gy), WOOD, 3)
            app.box(x + 12, gy - 5, x + 28, gy + 2, INK)
            if t > 4.5:
                u = _clamp((t - 4.5) / 1.8, 0, 1)
                app.dot(x + 58 - 116 * u, y - 27 - math.sin(u * math.pi) * 18, 5, GOLD, INK)
        elif kind == "inspect":
            rect = app.terrain.win_rect.get(s.get("window"))
            if rect:
                left, top, right, _ = rect
                u = min(1, t / 2.5)
                end = left + 10 + (right - left - 20) * u
                app.line((left + 10, top - 5, end, top - 5), GOLD, 5)
                for i in range(11):
                    tick = left + 10 + (end - left - 10) * i / 10
                    app.line((tick, top - 8, tick, top - 2), INK, 1)
                app.box(end - 8, top - 10, end + 8, top + 5, GOLD, INK)
                self._text(left + 17, top - 22, "%d px" % (right - left), INK)
        elif kind == "cards":
            app.box(x - 32, y - 27, x + 32, y - 20, GREEN, INK)
            app.line((x - 25, y - 20, x - 25, y, x + 25, y, x + 25, y - 20), WOOD, 3)
            for i in range(5):
                xx = x - 20 + i * 9
                lift = max(0, math.sin(t * 4 - i)) * 4
                app.box(xx, y - 33 - lift, xx + 7, y - 23 - lift, PAPER, INK)
                app.dot(xx + 3.5, y - 28 - lift, 1.2, RED if i % 2 else INK)
            dealer = actors[int(t * 1.5) % len(actors)]
            u = (t * 1.5) % 1
            cx = dealer.x + (x - dealer.x) * u
            app.box(cx - 4, y - 33 - 12 * math.sin(math.pi * u), cx + 4,
                    y - 23 - 12 * math.sin(math.pi * u), PAPER, RED)
        elif kind == "football":
            left, right = actors[0].x, actors[-1].x
            u = (math.sin(t * 2.2) + 1) / 2
            bx, by = left + (right - left) * u, y - 7 - math.sin(u * math.pi) * 28
            app.dot(bx, by, 7, PAPER, INK, 2)
            app.line((bx - 3, by - 2, bx + 3, by + 2), INK, 2)
            for gx in (x - 90, x + 90):
                app.line((gx - 13, y, gx - 13, y - 24, gx + 13, y - 24, gx + 13, y), PAPER, 2)
                app.line((gx - 13, y - 24, gx + 13, y, gx + 13, y - 24, gx - 13, y), BLUE, 1)
        elif kind == "juggling":
            for i, color in enumerate((RED, GOLD, BLUE)):
                phase = (t * .85 + i / 3) % 1
                bx = a.x + (phase * 2 - 1) * 24 * scale
                by = a.y - (42 + math.sin(phase * math.pi) * 58) * scale
                app.dot(bx, by, 4.5 * scale, color, INK)
        elif kind == "blanket_nap":
            for f in actors:
                rise = math.sin(t * 2) * scale
                app.box(f.x - 23 * scale, y - 17 * scale + rise,
                        f.x + 19 * scale, y + 2, BLUE, INK)
                for i in range(3):
                    app.line((f.x - 17 * scale + i * 12 * scale, y - 15 * scale + rise,
                              f.x - 17 * scale + i * 12 * scale, y + 1), PAPER, 1)
                app.box(f.x - 28 * scale, y - 22 * scale, f.x - 13 * scale, y - 14 * scale, PAPER, INK)
                self._text(f.x - 5, y - 42 - (t * 4) % 14, "z", BLUE, 8)
        elif kind == "coffee":
            for i, f in enumerate(actors):
                sip = max(0, math.sin(t * 2 + i))
                cx, cy = f.x + f.face * 16 * scale, f.y - (25 + sip * 22) * scale
                app.box(cx - 6, cy - 7, cx + 6, cy + 5, PAPER, INK)
                app.line((cx + 6, cy - 4, cx + 10, cy - 4, cx + 10, cy + 2, cx + 6, cy + 2), INK, 2)
                for j in range(2):
                    sway = math.sin(t * 4 + j) * 3
                    app.line((cx - 2 + j * 5, cy - 11, cx + sway + j * 5, cy - 17,
                              cx - sway + j * 5, cy - 23), PAPER, 1)
