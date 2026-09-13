"""Bounded cartoon projectiles and interruptible effects on the existing canvas.

No desktop APIs or persistence live here. App owns the frame/lifecycle hooks;
ordinary shots finish at a swept collision or a desktop edge, never a timer.
"""
import math

from gremlin_physics import material, preset, reflect, segment_contact


WEAPONS = ("boomerang", "bubble", "freeze", "swap", "glove", "rubber", "foam")
CONTROL = ("bubble", "freeze", "foam")
COLORS = {"boomerang": "#EDB16C", "bubble": "#A9EEFF", "freeze": "#7ADFFF",
          "swap": "#D49CFF", "glove": "#FF6375", "rubber": "#FFD65B",
          "foam": "#CEFFB8", "shield": "#F5DB78"}
SPEEDS = {"boomerang": 820, "bubble": 730, "freeze": 880, "swap": 1050,
          "glove": 980, "rubber": 1050, "foam": 700}
MAX_SHOTS = 32


def _clamp(value, low, high):
    return max(low, min(high, value))


class Arsenal:
    def __init__(self, app, cfg):
        self.app, self.cfg = app, cfg
        self.shots = []
        self.effects = {}

    def _allowed(self, f=None):
        allowed = getattr(self.app, "combat_allowed", None)
        return allowed(f) if allowed else self.cfg.get("play_mode", "mischief") != "peaceful"

    def _eligible(self, f):
        return f in self.app.fighters and f.hp > 0 and not f.grabbed and \
            f.state not in ("ko", "grabbed", "sleep")

    def _interrupt(self, f):
        self.app.drop_icon(f)
        self.app.end_ride(f)
        motion = getattr(self.app, "motion", None)
        if motion:
            motion.clear(f)
        # A controlled effect owns no target route, surface or old attack.
        f.route = []
        f.plat = None
        f.on_ground = False
        f.target = None

    def _remove(self, f, kind):
        effects = self.effects.get(f, {})
        effects.pop(kind, None)
        if not effects:
            self.effects.pop(f, None)
        if kind in CONTROL and f.state == "effect" and not any(k in effects for k in CONTROL):
            f.set_state("fall")
            f.on_ground = False
            f.vy = max(0.0, f.vy)

    def clear(self, f=None):
        if f is None:
            self.shots.clear()
            for fighter, effects in list(self.effects.items()):
                for kind in list(effects):
                    self._remove(fighter, kind)

            return
        self.shots[:] = [s for s in self.shots if s["owner"] is not f]
        # Removal also releases victims whose effect source no longer exists.
        for fighter, effects in list(self.effects.items()):
            for kind, status in list(effects.items()):
                if fighter is f or status["source"] is f:
                    self._remove(fighter, kind)

    def release_bindings(self, f):
        """A rescue removes immobilization while preserving protective shields."""
        for kind in CONTROL:
            self._remove(f, kind)

    def apply_effect(self, f, kind, duration, source=None):
        if kind not in CONTROL + ("shield",) or not self._eligible(f):
            return False
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            return False
        if kind != "shield" and not self._allowed():
            return False
        existing = self.effects.get(f, {})
        if kind != "shield" and "shield" in existing:
            return False
        if kind in CONTROL:
            for old in CONTROL:
                self._remove(f, old)
            self._interrupt(f)
            # The engine, rather than an AI activity, owns this temporary state.
            f.set_state("effect")
            f.vy = 0.0
            f.vx = (1 if source and f.x >= source.x else -1) * 300 * f.K() \
                if kind == "freeze" else 0.0
        effects = self.effects.setdefault(f, {})
        f.effects = effects
        effects[kind] = {"left": min(20.0, duration), "source": source,
                         "power": 20.0 if kind == "shield" else 0.0, "rescue": 0.0}
        return True

    def _friends(self, a, b):
        social = getattr(self.app, "social", None)
        return a is not b and social is not None and social.affinity(a, b) >= 15

    def filter_damage(self, att, vic, dmg):
        if not self._allowed() or not isinstance(dmg, (int, float)) or not math.isfinite(dmg):
            return 0.0
        dmg = _clamp(dmg, 0.0, 200.0)
        effects = self.effects.get(vic, {})
        shield = effects.get("shield")
        if shield:
            absorbed = min(dmg, shield["power"])
            shield["power"] -= absorbed
            dmg -= absorbed
            if shield["power"] <= 0:
                self._remove(vic, "shield")
            if not dmg:
                return 0.0
        captured = any(k in effects for k in CONTROL)
        if captured:
            for kind in CONTROL:
                self._remove(vic, kind)
            # A friend can break the bubble/ice/foam without hurting its occupant.
            if self._friends(att, vic):
                vic.say("Thanks!", 1.0)
                return 0.0
        return dmg

    def release(self, f):
        kind = f.weapon
        if kind not in WEAPONS:
            return False
        if not self._allowed(f) or not self._eligible(f) or kind not in f.per.get("weapons", ()):
            return True
        if len(self.shots) >= MAX_SHOTS:
            return True
        x, y = self.app.muzzle(f)
        tx, ty = self.app.aim_point(f)
        angle = math.atan2(ty - y, tx - x)
        speed = SPEEDS[kind] * f.K()
        self.shots.append({"k": kind, "x": x, "y": y, "owner": f,
                           "vx": math.cos(angle) * speed, "vy": math.sin(angle) * speed,
                           "speed": speed, "g": 160 * f.K() if kind == "rubber" else 0.0,
                           "sc": f.sc, "spin": 0.0, "distance": 0.0, "phase": "out",
                           "age": 0.0, "bounces": 0, "hit": set(),
                           "pierce": f.shot_pierce, "tgt": f.shot_tgt})
        if kind == "glove":
            # The spring launches the shooter backwards too; ordinary physics
            # carries the recoil after the release frame.
            impulse = preset(self.cfg.get("physics_preset", "normal"))["impulse"]
            f.vx = -math.cos(angle) * 620 * f.K() * impulse
            f.vy = -210 * f.K() * impulse
            f.on_ground = False
        return True

    def _impact(self, shot, victim):
        owner, kind = shot["owner"], shot["k"]
        direction, point = (shot["vx"], shot["vy"]), (shot["x"], shot["y"])
        shielded = "shield" in self.effects.get(victim, {})
        if kind in ("bubble", "freeze", "foam"):
            self.app.impact_fighter(owner, victim, 2, direction=direction, point=point)
            if not shielded:
                applied = self.apply_effect(victim, kind, 5 if kind == "bubble" else 4, owner)
                if applied and kind == "freeze" and abs(shot["vx"]) > .01:
                    # A banked freeze shot pushes its cube along the incoming path.
                    victim.vx = math.copysign(abs(victim.vx), shot["vx"])
        elif kind == "swap":
            if shielded:
                self.app.impact_fighter(owner, victim, 2, direction=direction, point=point)
            elif self._eligible(owner) and self._eligible(victim):
                ax, ay, bx, by = owner.x, owner.y, victim.x, victim.y
                for f, x, y in ((owner, bx, by), (victim, ax, ay)):
                    for status in CONTROL:
                        self._remove(f, status)
                    self._interrupt(f)
                    # Clamp transferred feet to real desktop/floor coordinates.
                    f.x = _clamp(x, self.app.ox + 20, self.app.ox + self.app.W - 20)
                    f.y = _clamp(y, self.app.oy + 90 * f.sc, self.app.ground_at(f.x, y))
                    f.vx = f.vy = 0.0
                    f.set_state("fall")
                    f.say("Your turn!", .8)
        else:
            self.app.impact_fighter(owner, victim, 18 if kind == "glove" else 8,
                                    direction=direction, point=point)

    def _turn(self, s):
        # A boomerang returns after its outbound leg or the first obstruction.
        s["phase"], s["age"] = "return", 0.0

    def _contact(self, s, x0, y0, x1, y1, radius):
        """Pick the first crossed solid regardless of fighter/terrain list order."""
        app, owner = self.app, s["owner"]
        result = None

        def consider(kind, hit, obj):
            nonlocal result
            if hit is None:
                return
            at, nx, ny = hit[:3]
            # Inclusive boxes must not reflect a shot already departing a face.
            if at <= 1e-8 and (x1 - x0) * nx + (y1 - y0) * ny >= 0:
                return
            if result is None or at < result[1]:
                result = kind, at, nx, ny, obj

        for f in app.fighters:
            if f is owner or f in s["hit"] or not self._eligible(f) or getattr(f, "motion_dodging", False):
                continue
            consider("fighter", segment_contact(x0, y0, x1, y1,
                     f.x - 14 * f.sc - radius, f.y - 76 * f.sc - radius,
                     f.x + 14 * f.sc + radius, f.y + radius), f)
        returning = s["k"] == "boomerang" and s["phase"] == "return"
        if not returning:
            for cx, cy, hw, hh, target in app.terrain.bounds:
                if s["pierce"] and s["tgt"] != (target["kind"], target["key"]):
                    continue
                consider("target", segment_contact(x0, y0, x1, y1,
                         cx - hw - radius, cy - hh - radius,
                         cx + hw + radius, cy + hh + radius), target)
            floor = app.floor_contact(x0, y0 + radius, x1, y1 + radius)
            if floor:
                consider("floor", (floor[0], 0.0, -1.0), floor[1])
            motion = getattr(app, "motion", None)
            if motion:
                hit = motion.projectile_contact(x0, y0, x1, y1, radius)
                if hit:
                    consider("prop", hit, hit[3])
            left, right = app.ox + radius, app.ox + app.W - radius
            dx = x1 - x0
            if dx < 0 and x1 < left:
                consider("edge", (max(0.0, (left - x0) / dx), 1.0, 0.0), left)
            elif dx > 0 and x1 > right:
                consider("edge", (max(0.0, (right - x0) / dx), -1.0, 0.0), right)
        return result

    def _bounce(self, s, nx, ny, surface):
        properties = material(surface)
        # Rubber ammunition stays lively on ordinary ground, while sticky
        # surfaces absorb it and ice preserves the tangential part of its speed.
        restitution = .1 if surface == "sticky" else min(.98, .61 + 1.1 * properties["restitution"])
        restitution = min(.98, restitution * preset(self.cfg.get("physics_preset", "normal"))["impulse"])
        s["vx"], s["vy"] = reflect(s["vx"], s["vy"], nx, ny, restitution,
                                     min(.9, .1 * properties["friction"]))
        # A tiny outward separation avoids hitting the same inclusive face at t=0.
        separation = max(.05, .08 * s["sc"])
        s["x"] += nx * separation
        s["y"] += ny * separation
        s["bounces"] += 1
        return s["bounces"] < 6

    def _flight(self, s, dt):
        app, owner, kind = self.app, s["owner"], s["k"]
        s["age"] += dt
        s["spin"] += dt * 16
        x0, y0 = s["x"], s["y"]
        if kind == "boomerang" and s["phase"] == "return":
            dx, dy = owner.x - x0, owner.y - 38 * owner.sc - y0
            distance = math.hypot(dx, dy)
            speed = s["speed"] * 1.25
            if distance < max(14 * owner.sc, speed * dt):
                catching = self._eligible(owner) and owner.state in ("idle", "walk", "fight", "attack") \
                    and (x0 - owner.x) * owner.face >= 0
                if catching:
                    owner.say("Caught it!", .8)
                else:
                    self.app.impact_fighter(owner, owner, 7,
                                            direction=(s["vx"], s["vy"]), point=(x0, y0))
                    owner.say("...ow.", 1)
                return False
            s["vx"], s["vy"] = dx / distance * speed, dy / distance * speed
            # Only a return leg has a deadline: an owner continuously fleeing
            # faster than the return speed must not retain a shot forever.
            if s["age"] > max(5.0, math.hypot(app.W, app.H) / max(1, speed) * 3):
                return False
        s["vy"] += s["g"] * preset(self.cfg.get("physics_preset", "normal"))["gravity"] * dt
        radius = max(3.0, 7 * s["sc"])
        remaining = dt
        # Each pass either completes this step or consumes a ricochet, so even
        # a very large step through a cramped corner has at most six contacts.
        while remaining > 1e-8:
            x0, y0 = s["x"], s["y"]
            x1, y1 = x0 + s["vx"] * remaining, y0 + s["vy"] * remaining
            hit = self._contact(s, x0, y0, x1, y1, radius)
            if hit is None:
                s["x"], s["y"] = x1, y1
                s["distance"] += math.hypot(x1 - x0, y1 - y0)
                break
            event, contact, nx, ny, obj = hit
            s["x"], s["y"] = x0 + (x1 - x0) * contact, y0 + (y1 - y0) * contact
            s["distance"] += math.hypot(s["x"] - x0, s["y"] - y0)
            remaining *= 1.0 - contact
            if event == "fighter":
                s["hit"].add(obj)
                self._impact(s, obj)
            elif event == "target":
                app.hit_target(owner, obj, s["x"], s["y"])
            elif event == "prop":
                # Soft control rounds still hit cover, with a gentle physical nudge.
                strength = .25 if kind == "freeze" else .1 if kind in ("bubble", "foam") else 1.0
                app.motion.hit_prop(obj, s["x"], s["y"], s["vx"], s["vy"], strength=strength)
            if kind == "boomerang":
                # Returning rounds pass scenery so the first obstruction cannot
                # strand their owner with an unreachable projectile.
                self._turn(s)
                return True
            if kind != "rubber":
                return False
            surface = self.cfg.get("surface_material", "standard")
            if event == "prop":
                surface = obj.get("material", surface)
            if not self._bounce(s, nx, ny, surface):
                return False
        # Gravity-bearing arcs can leave the top and descend into the desktop.
        # Straight shots still finish once their path leaves the visible world.
        if (s["y"] < app.oy - 60 and s["g"] <= 0) or s["y"] > app.oy + app.H + 60:
            if kind == "boomerang":
                if s["phase"] == "out":
                    self._turn(s)
            else:
                return False
        if kind == "boomerang" and s["phase"] == "out" and s["distance"] > 390 * (.4 + .6 * owner.K()):
            self._turn(s)
        return True

    def update(self, dt):
        if not math.isfinite(dt) or dt <= 0:
            return
        if not self._allowed():
            self.clear()
            return
        for f, effects in list(self.effects.items()):
            for kind, effect in list(effects.items()):
                effect["left"] -= dt
                source = effect["source"]
                rescued = f.state == "social" and getattr(f, "social_rescue", False)
                if not self._eligible(f) or (source is not None and source not in self.app.fighters) \
                        or effect["left"] <= 0 or (kind in CONTROL and f.state != "effect" and not rescued):
                    self._remove(f, kind)
        live = []
        pending = tuple(self.shots)
        for s in pending:
            # An impact can synchronously clear another owner's ammunition.
            # Iterate a snapshot, but never revive a round that cleanup removed.
            if not any(current is s for current in self.shots):
                continue
            if s["owner"] not in self.app.fighters or not all(math.isfinite(s[k]) for k in ("x", "y", "vx", "vy", "g")):
                continue
            if self._flight(s, dt):
                live.append(s)
        active_ids = {id(s) for s in self.shots}
        pending_ids = {id(s) for s in pending}
        self.shots = [s for s in live if id(s) in active_ids] + \
            [s for s in self.shots if id(s) not in pending_ids]

    def control(self, f, dt):
        effects = self.effects.get(f, {})
        kind = next((k for k in CONTROL if k in effects), None)
        if not kind:
            return False
        if f.state == "social" and getattr(f, "social_rescue", False):
            return False  # Rope/haul owns movement until it releases bindings.
        if not self._eligible(f) or f.state != "effect":
            self._remove(f, kind)
            return False
        app, k = self.app, f.K()
        if kind == "bubble":
            f.vx = math.sin(app.time * 2 + f.seedp) * 18 * k
            f.vy = -75 * k
            f.x = _clamp(f.x + f.vx * dt, app.ox + 24, app.ox + app.W - 24)
            f.y = max(app.oy + 100 * f.sc, f.y + f.vy * dt)
            f.on_ground = False
        else:
            x0, y0 = f.x, f.y
            f.vx = f.vx * max(0, 1 - dt * .35) if kind == "freeze" else 0.0
            f.vy += 1400 * k * preset(self.cfg.get("physics_preset", "normal"))["gravity"] * dt
            x1, y1 = x0 + f.vx * dt, y0 + f.vy * dt
            if kind == "freeze":
                # Swept cube versus the actual window body, not only its top.
                first_wall = 2.0
                for _title, l, t, r, b, _key in app.terrain.windows:
                    at = app.segment_box(x0, y0 - 32 * f.sc, x1, y1 - 32 * f.sc,
                                         l - 18 * f.sc, t - 30 * f.sc, r + 18 * f.sc, b)
                    if at is not None:
                        first_wall = min(first_wall, at)
                if first_wall <= 1:
                    x1 = x0 + (x1 - x0) * max(0, first_wall - .01)
                    f.vx *= -.65
                for other in app.fighters:
                    if other is f or not self._eligible(other):
                        continue
                    at = app.segment_box(x0, y0 - 30 * f.sc, x1, y1 - 30 * f.sc,
                                         other.x - 24 * f.sc, other.y - 75 * other.sc,
                                         other.x + 24 * f.sc, other.y + 5)
                    if at is not None:
                        self.app.hit_fighter(f, other, 5)
                        self._remove(f, kind)
                        return False
            floor = app.floor_contact(x0, y0, x1, y1)
            best, top = (floor if floor else (2.0, y1))
            if y1 > y0:
                for l, r, py, _type, _key in app.terrain.platforms:
                    at = (py - y0) / (y1 - y0)
                    if 0 <= at <= 1 and at < best and l <= x0 + (x1 - x0) * at <= r:
                        best, top = at, py
            f.x = _clamp(x1, app.ox + 20, app.ox + app.W - 20)
            if f.x != x1:
                f.vx *= -.7
            f.y, f.on_ground = (top if best <= 1 else y1), best <= 1
            if f.on_ground:
                f.vy = 0.0
            if kind == "foam":
                nearby_friend = any(self._eligible(o) and self._friends(o, f)
                                    and math.hypot(o.x - f.x, o.y - f.y) < 70 * max(o.sc, f.sc)
                                    for o in app.fighters if o is not f)
                effects[kind]["rescue"] = effects[kind]["rescue"] + dt if nearby_friend else 0.0
                if effects[kind]["rescue"] > .6:
                    self._remove(f, kind)
                    f.say("Free! Thanks!", 1)
        return True

    def draw(self):
        app = self.app
        app.layer("arsenal")
        for shot in self.shots:
            x, y, sc = shot["x"], shot["y"], shot["sc"]
            kind, color = shot["k"], COLORS[shot["k"]]
            if kind == "boomerang":
                angle = shot["spin"]
                pts = []
                for lx, ly in ((-13, -8), (0, 0), (13, -8)):
                    pts.extend((x + (lx * math.cos(angle) - ly * math.sin(angle)) * sc,
                                y + (lx * math.sin(angle) + ly * math.cos(angle)) * sc))
                app.line(pts, color, max(2, 4 * sc))
            elif kind == "bubble":
                app.ring(x, y, 12 * sc, color, max(1, 2 * sc))
                app.dot(x - 4 * sc, y - 5 * sc, 2 * sc, "#FFFFFF")
            elif kind == "freeze":
                for angle in (0, math.pi / 3, math.pi * 2 / 3):
                    dx, dy = math.cos(angle) * 10 * sc, math.sin(angle) * 10 * sc
                    app.line((x - dx, y - dy, x + dx, y + dy), color, max(1, 2 * sc))
            elif kind == "swap":
                app.line((x - 12 * sc, y, x + 12 * sc, y), color, max(2, 3 * sc))
                app.line((x + 7 * sc, y - 5 * sc, x + 12 * sc, y, x + 7 * sc, y + 5 * sc), color, 2)
                app.line((x - 7 * sc, y - 5 * sc, x - 12 * sc, y, x - 7 * sc, y + 5 * sc), color, 2)
            elif kind == "glove":
                app.dot(x, y, 10 * sc, color, "#FFFFFF", 1)
                app.dot(x - 5 * sc, y + 6 * sc, 5 * sc, color)
                app.line((x - 22 * sc, y, x - 16 * sc, y - 4 * sc, x - 10 * sc, y + 4 * sc, x - 4 * sc, y), "#D5D9E8", 2)
            elif kind == "foam":
                for dx, dy, radius in ((-6, 1, 7), (3, -4, 8), (7, 5, 6)):
                    app.dot(x + dx * sc, y + dy * sc, radius * sc, color, "#8DCE82", 1)
            else:
                app.dot(x, y, 8 * sc, color, "#E28255", 2)
                app.line((x - 6 * sc, y, x + 6 * sc, y), "#FFFFFF", 1)
        for f, effects in self.effects.items():
            sc, x, y = f.sc, f.x, f.y
            if "shield" in effects:
                app.ring(x, y - 37 * sc, 49 * sc, COLORS["shield"], max(1, 2 * sc))
            if "bubble" in effects:
                app.ring(x, y - 35 * sc, 47 * sc, COLORS["bubble"], max(2, 3 * sc))
                app.ring(x - 17 * sc, y - 58 * sc, 8 * sc, "#FFFFFF", 1)
            if "freeze" in effects:
                app.box(x - 22 * sc, y - 79 * sc, x + 22 * sc, y + 3 * sc, "", COLORS["freeze"], max(2, 3 * sc))
                app.line((x - 19 * sc, y - 4 * sc, x + 19 * sc, y - 69 * sc), "#BDEFFF", 1)
            if "foam" in effects:
                for dx, dy, radius in ((-16, -4, 12), (0, -8, 15), (17, -3, 11), (0, -25, 9)):
                    app.dot(x + dx * sc, y + dy * sc, radius * sc, COLORS["foam"], "#8DCE82", 1)
