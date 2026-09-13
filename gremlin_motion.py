"""Bounded canvas toys and cooperative traversal on the existing physics seam.

World coordinates stay in the simulation. Toys never touch icons, files,
windows, native input or focus. Priority states always supersede traversal.
"""
import math
import random


FREE = frozenset(("idle", "walk", "taunt", "fall", "jump", "wallslide"))
KINDS = ("crate", "seesaw", "ramp", "fan", "conveyor")
ALIASES = {"swing": "rope", "wallkick": "wall_kick", "landing_roll": "roll",
           "dodge": "slide", "paper_plane": "plane", "team_boost": "boost"}
INK, WOOD, PAPER = "#677B92", "#B6A38B", "#EAF4FF"


def clamp(value, low, high):
    return max(low, min(high, value))


class MotionEngine:
    def __init__(self, app, cfg):
        self.app, self.cfg = app, cfg
        self.actions, self.cooldowns = {}, {}
        self.props = []
        self._serial = 0
        self._build_in = 12.0

    def _free(self, f, active=False):
        return (f in self.app.fighters and f.hp > 0 and not f.grabbed
                and not self.app.asleep and f.stun <= 0 and not f.carry
                and not f.play and not f.mount and not f.ridden_by
                and (f.state in FREE or (active and f.state == "parkour")))

    def _finish(self, f, state=None):
        action = self.actions.pop(f, None)
        f.motion_dodging = False
        if action is None:
            return
        if action["kind"] == "roll" and f.state == "parkour":
            f.tumble = f.vr = 0.0
        self.cooldowns[f] = 4.0
        if f.state == "parkour":
            # Release only the state this engine owns; a hit/grab stays intact.
            f.set_state(state or ("idle" if f.on_ground else "fall"))
            f.goal = self.app.time + 1.0
        partner = action.get("partner")
        if partner is not None:
            linked = self.actions.get(partner)
            if linked is not None and linked.get("partner") is f:
                linked.pop("partner", None)
                self._finish(partner)

    def clear(self, f=None):
        if f is not None:
            self._finish(f)
            self.cooldowns.pop(f, None)
            f.motion_last_vy = 0.0
            for prop in self.props:
                prop["occupants"].discard(f)
            return
        for actor in list(self.actions):
            self._finish(actor)
        self.actions.clear()
        self.cooldowns.clear()
        for actor in self.app.fighters:
            actor.motion_dodging = False
            actor.motion_last_vy = 0.0
            if actor.plat and actor.plat[0] == "toy":
                actor.plat, actor.on_ground = None, False
        self.props[:] = []
        self._build_in = 12.0

    def start(self, f, kind, target=None):
        kind = ALIASES.get(kind, kind)
        if (not self.cfg.get("parkour", True) or not self._free(f)
                or f in self.actions or self.cooldowns.get(f, 0) > 0):
            return False
        if kind not in ("rope", "wall_kick", "roll", "vault", "slide", "plane", "boost"):
            return False
        action = {"kind": kind, "t": 0.0, "face": f.face, "duration": 1.5}
        K, S = f.K(), f.sc
        if kind == "rope":
            if target is None:
                ledges = [p for p in self.app.terrain.platforms
                          if p[2] < f.y - 90 * S and abs((p[0] + p[1]) / 2 - f.x) < 320 * S]
                if not ledges:
                    return False
                p = min(ledges, key=lambda p: abs((p[0] + p[1]) / 2 - f.x))
                target = ((p[0] + p[1]) / 2, p[2])
            if not isinstance(target, (tuple, list)) or len(target) < 2:
                return False
            ax, ay = target[:2]
            hand_y = f.y - 62 * S
            dx, dy = f.x - ax, hand_y - ay
            length = math.hypot(dx, dy)
            if dy < 35 * S or length < 65 * S or length > 520 * S:
                return False
            angle = math.atan2(dx, dy)
            # Angular velocity is tangential linear momentum divided by radius.
            omega = (f.vx * math.cos(angle) - f.vy * math.sin(angle)) / length
            if abs(omega) < .18:
                omega = f.face * .45
            action.update(anchor=(ax, ay), length=length, angle=angle,
                          omega=omega, duration=2.2)
            f.on_ground, f.plat = False, None
            # A prior landing squash would move the displayed grip off the
            # fixed-length rope, so the suspended body starts uncompressed.
            f.squash = f.tumble = f.vr = 0.0
        elif kind == "wall_kick":
            wall = self._wall(f) if target is None else target
            if wall is None or f.on_ground:
                return False
            edge, side = wall[:2]
            if abs(f.x - edge) > 28 * S:
                return False
            f.face = -1 if side > 0 else 1
            f.vx, f.vy = f.face * 360 * K, -560 * K
            action.update(face=f.face, duration=.8)
            f.ledge_cd = self.app.time + 1.2
        elif kind in ("roll", "slide"):
            if not f.on_ground:
                return False
            action["speed"] = max(abs(f.vx), (360 if kind == "slide" else 310) * K)
            action["duration"] = .60 if kind == "slide" else .65
            f.motion_dodging = kind == "slide"
        elif kind == "vault":
            if target is None:
                target = self._obstacle(f)
            if target is None or not f.on_ground:
                return False
            if isinstance(target, dict):
                left, right, top = target["x"] - target["w"] / 2, target["x"] + target["w"] / 2, target["y"] - target["h"]
            else:
                left, right, top = target[:3]
            if abs(f.x - (left if f.face > 0 else right)) > 65 * S or not 0 < f.y - top < 100 * S:
                return False
            destination = right + 24 * S if f.face > 0 else left - 24 * S
            action.update(origin=(f.x, f.y), destination=destination,
                          top=top, duration=.85)
            f.on_ground, f.plat = False, None
        elif kind == "plane":
            if f.y > self.app.ground_at(f.x, f.y) - 90 * S:
                return False
            action["duration"] = 8.0
            f.vx, f.vy = f.face * 260 * K, 65 * K
            f.on_ground, f.plat = False, None
        elif kind == "boost":
            if not f.on_ground:
                return False
            helper = target
            if helper is None:
                choices = [o for o in self.app.fighters if o is not f and self._free(o)
                           and o.on_ground and abs(o.x - f.x) < 65 * S
                           and abs(o.y - f.y) < 20 * S]
                social = getattr(self.app, "social", None)
                affinity = getattr(social, "affinity", None)
                helper = max(choices, key=lambda o: affinity(f, o) if affinity else 0) if choices else None
            if (helper is None or helper is f or not self._free(helper)
                    or helper in self.actions or not helper.on_ground
                    or abs(helper.x - f.x) > 75 * S or abs(helper.y - f.y) > 25 * S):
                return False
            action.update(partner=helper, duration=2.0, launched=False)
            self.actions[helper] = {"kind": "boost_helper", "partner": f,
                                    "t": 0.0, "duration": .52, "face": helper.face}
            helper.set_state("parkour")
            helper.vx = 0
            f.face = 1 if helper.x >= f.x else -1
            action["face"] = f.face
        self.actions[f] = action
        f.set_state("parkour")
        f.mode, f.target, f.foe = "roam", None, None
        f.boredom = max(0, f.boredom - .15)
        return True

    def _wall(self, f):
        for _name, left, top, right, bottom, _key in self.app.terrain.windows:
            if top + 15 < f.y < bottom + 40 * f.sc:
                for edge, side in ((left, 1), (right, -1)):
                    if abs(edge - f.x) < 22 * f.sc and f.vx * side > 0:
                        return edge, side
        return None

    def _obstacle(self, f):
        surfaces = list(self.app.terrain.platforms) + self.platforms()
        for left, right, top, _kind, _key in surfaces:
            edge = left if f.face > 0 else right
            if 0 <= (edge - f.x) * f.face < 55 * f.sc and 8 * f.sc < f.y - top < 85 * f.sc:
                return left, right, top
        return None

    def _incoming(self, f):
        shots = list(self.app.shots)
        arsenal = getattr(self.app, "arsenal", None)
        shots += getattr(arsenal, "shots", [])
        for shot in shots:
            if shot.get("owner") is f:
                continue
            dx, dy = shot.get("x", 0) - f.x, shot.get("y", 0) - f.y
            vx = shot.get("vx", 0)
            if (20 * f.sc < abs(dx) < 180 * f.sc and -70 * f.sc < dy < -22 * f.sc
                    and dx * vx < 0):
                return True
        return False

    def consider(self, f):
        if not self.cfg.get("parkour", True) or not self._free(f) or self.cooldowns.get(f, 0) > 0:
            return False
        if f.on_ground and self._incoming(f):
            return self.start(f, "slide")
        chance = .13 if self.cfg.get("play_mode", "mischief") == "battle" else .28
        if random.random() > chance:
            return False
        if not f.on_ground:
            if self._wall(f) is not None:
                return self.start(f, "wall_kick")
            return self.start(f, "rope") or self.start(f, "plane")
        if f.y < self.app.ground_at(f.x, f.y) - 100 * f.sc:
            return self.start(f, "rope") or self.start(f, "plane")
        obstacle = self._obstacle(f)
        if obstacle is not None:
            return self.start(f, "vault", obstacle)
        return self.start(f, "boost")

    def add_prop(self, kind, x, y):
        if not self.cfg.get("toy_props", True) or kind not in KINDS or len(self.props) >= 6:
            return None
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not math.isfinite(x + y):
            return None
        S = self.cfg.get("scale", 1.0)
        width, height = {"crate": (62, 48), "seesaw": (130, 18), "ramp": (130, 46),
                         "fan": (58, 18), "conveyor": (145, 10)}[kind]
        width, height = width * S, height * S
        mon, work = self.app.monitor_at(x, y)
        x = clamp(x, mon[0] + width / 2 + 10, mon[2] - width / 2 - 10)
        y = clamp(y, mon[1] + height + 30, work[3])
        if any(abs(x - p["x"]) < (width + p["w"]) / 2 + 12
               and abs(y - p["y"]) < max(height, p["h"]) for p in self.props):
            return None
        self._serial += 1
        prop = {"id": self._serial, "kind": kind, "x": x, "y": y,
                "w": width, "h": height, "life": 55.0, "angle": 0.0,
                "phase": 0.0, "cooldown": 0.0, "occupants": set(), "direction": 1}
        self.props.append(prop)
        return prop

    def _height(self, prop, x):
        u = clamp((x - prop["x"]) / prop["w"] + .5, 0, 1)
        if prop["kind"] == "ramp":
            return prop["y"] - u * prop["h"]
        if prop["kind"] == "seesaw":
            return prop["y"] - prop["h"] + (x - prop["x"]) * prop["angle"]
        return prop["y"] - prop["h"]

    def platforms(self):
        if not self.cfg.get("toy_props", True):
            return []
        result = []
        for prop in self.props:
            if prop["kind"] == "fan":
                continue
            left, width = prop["x"] - prop["w"] / 2, prop["w"]
            count = 10 if prop["kind"] in ("ramp", "seesaw") else 1
            for i in range(count):
                x0, x1 = left + width * i / count, left + width * (i + 1) / count
                result.append((x0, x1, self._height(prop, (x0 + x1) / 2), "toy", prop["id"]))
        return result

    def update(self, dt):
        for f in list(self.cooldowns):
            self.cooldowns[f] -= dt
            if self.cooldowns[f] <= 0 or f not in self.app.fighters:
                self.cooldowns.pop(f, None)
        for f, action in list(self.actions.items()):
            if (not self.cfg.get("parkour", True) or not self._free(f, True)
                    or f.state != "parkour" or action.get("partner", f) not in self.app.fighters):
                self._finish(f)
        expired = set()
        for prop in list(self.props):
            prop["life"] -= dt
            if prop["life"] <= 0 or not self.cfg.get("toy_props", True):
                expired.add(prop["id"])
                self.props.remove(prop)
                continue
            prop["phase"] = (prop["phase"] + dt * 5) % (math.pi * 2)
            prop["cooldown"] = max(0, prop["cooldown"] - dt)
            occupants = {f for f in self.app.fighters if self._free(f)
                         and f.on_ground and abs(f.x - prop["x"]) < prop["w"] / 2 + 5
                         and abs(f.y - self._height(prop, f.x)) < 12 * f.sc}
            if prop["kind"] == "seesaw":
                newcomers = occupants - prop["occupants"]
                if newcomers and prop["cooldown"] <= 0:
                    landed = max(newcomers, key=lambda f: abs(f.x - prop["x"]))
                    side = -1 if landed.x < prop["x"] else 1
                    riders = [rider for rider in occupants
                              if (rider.x - prop["x"]) * side < -8 * rider.sc]
                    for rider in riders:
                        rider.vy, rider.on_ground, rider.plat = -650 * rider.K(), False, None
                        rider.set_state("jump")
                    prop["angle"] = -side * .23
                    if riders:
                        prop["cooldown"] = .85
                else:
                    prop["angle"] *= max(0, 1 - dt * 2)
            prop["occupants"] = occupants
        if expired:
            for f in self.app.fighters:
                if f.plat and f.plat[0] == "toy" and f.plat[1] in expired:
                    f.plat, f.on_ground = None, False
        # Construction is simulation-only and spreads one small toy every 12s.
        self._build_in -= dt
        if self._build_in <= 0:
            self._build_in = 12.0
            if self.cfg.get("toy_props", True) and not self.app.asleep and len(self.props) < 5 and dt < 2:
                builders = [f for f in self.app.fighters if self._free(f) and f.on_ground]
                if builders:
                    builder = random.choice(builders)
                    kind = KINDS[self._serial % len(KINDS)]
                    x = builder.x + builder.face * 145 * builder.sc
                    if self.add_prop(kind, x, self.app.ground_at(x, builder.y)) is not None:
                        builder.say("Built a " + kind + ".", 1.2)

    def _toys(self, f, dt):
        if not self._free(f):
            return
        for prop in self.props:
            dx = f.x - prop["x"]
            if abs(dx) > prop["w"] / 2 + 4 * f.sc:
                continue
            top = self._height(prop, f.x)
            if prop["kind"] == "fan" and prop["y"] - 185 * f.sc < f.y <= prop["y"] + 2:
                f.vy = min(f.vy, -175 * f.K())
                f.on_ground, f.plat = False, None
                if f.state in ("idle", "walk", "taunt"):
                    f.set_state("jump")
            elif prop["kind"] == "conveyor" and f.on_ground and abs(f.y - top) < 12 * f.sc:
                f.x += prop["direction"] * 90 * f.K() * dt
            elif prop["kind"] in ("ramp", "seesaw") and f.on_ground and abs(f.y - top) < 15 * f.sc:
                # Match the exact next segment (including physics' 6px foot
                # tolerance), so an uphill step cannot create a false fall.
                next_x = f.x + f.vx * dt
                supports = [p[2] for p in self.platforms() if p[4] == prop["id"]
                            and p[0] - 6 <= next_x <= p[1] + 6]
                if supports:
                    f.y, f.vy = min(supports), 0.0
                    f.plat = ("toy", prop["id"])

    def control(self, f, dt):
        action = self.actions.get(f)
        if action is None:
            self._toys(f, dt)
            # These reactions need flight/landing samples, not just AI decisions.
            previous_vy = getattr(f, "motion_last_vy", 0)
            if (self.cfg.get("parkour", True) and self._free(f)
                    and self.cooldowns.get(f, 0) <= 0):
                if f.on_ground and previous_vy > 440 * f.K() and abs(f.vx) > 65 * f.K():
                    self.start(f, "roll")
                elif f.on_ground and self._incoming(f):
                    self.start(f, "slide")
                elif not f.on_ground and self._wall(f) is not None:
                    self.start(f, "wall_kick")
            f.motion_last_vy = f.vy
            action = self.actions.get(f)
            if action is None:
                return False
        if not self._free(f, True) or f.state != "parkour" or not self.cfg.get("parkour", True):
            self._finish(f)
            return False
        kind, K, S = action["kind"], f.K(), f.sc
        action["t"] += dt
        t = action["t"]
        if kind == "rope":
            # Semi-implicit pendulum integration conserves the rope radius and
            # transfers its tangent velocity unchanged when the hand lets go.
            angle, omega, length = action["angle"], action["omega"], action["length"]
            omega += (-1900 * K / length * math.sin(angle) - .045 * omega) * dt
            angle += omega * dt
            action["angle"], action["omega"] = angle, omega
            ax, ay = action["anchor"]
            f.x, f.y = ax + length * math.sin(angle), ay + length * math.cos(angle) + 62 * S
            f.vx, f.vy = length * math.cos(angle) * omega, -length * math.sin(angle) * omega
            f.face = 1 if f.vx >= 0 else -1
            if f.y >= self.app.ground_at(f.x, f.y) - 5:
                self._finish(f)
                self.app.physics(f, dt, self.app.ground_at(f.x, f.y))
            elif (t > .65 and angle * omega > 0 and abs(angle) > .30) or t >= action["duration"]:
                self._finish(f)
            return True
        if kind == "vault":
            u = min(1, t / action["duration"])
            x0, y0 = action["origin"]
            f.x = x0 + (action["destination"] - x0) * u
            height = max(64 * S, y0 - action["top"] + 30 * S)
            f.y = y0 - math.sin(math.pi * u) * height
            f.vx = (action["destination"] - x0) / action["duration"]
            f.vy = -math.cos(math.pi * u) * math.pi * height / action["duration"]
            if u >= 1:
                self._finish(f)
                self.app.physics(f, dt, self.app.ground_at(f.x, f.y))
            return True
        if kind == "boost_helper":
            f.vx = 0
            if t >= action["duration"]:
                # A completed helper lets the already-launched flyer continue.
                partner = action.pop("partner", None)
                if partner in self.actions:
                    self.actions[partner].pop("partner", None)
                self._finish(f)
            return True
        if kind == "boost":
            if not action["launched"] and t < .30:
                f.vx = 0
                return True
            if not action["launched"]:
                action["launched"] = True
                f.on_ground, f.plat = False, None
                f.vx, f.vy = action["face"] * 260 * K, -900 * K
        elif kind == "plane":
            old_x, old_y = f.x, f.y
            f.vx = action["face"] * 260 * K
            # Lift cancels most gravity; existing physics still owns landings,
            # screen wrapping and the first surface crossed.
            f.vy = min(115 * K, max(45 * K, f.vy)) - 1900 * K * dt
            next_x = f.x + f.vx * dt
            for _title, left, top, right, bottom, _key in self.app.terrain.windows:
                crosses = old_x < left <= next_x or next_x <= right < old_x
                if crosses and top < old_y - 12 * S < bottom:
                    self._finish(f, "thrown")
                    f.vx *= -.4
                    f.vy, f.vr, f.stun = -100 * K, action["face"] * 6, .45
                    f.tumble = .5 * action["face"]
                    f.say("Paperwork problem.", 1.1)
                    return True
        elif kind in ("roll", "slide"):
            f.vx = action["face"] * action["speed"] * max(.2, 1 - t / action["duration"] * .6)
            if kind == "roll":
                f.tumble = action["face"] * math.pi * 2 * t / action["duration"]
        self.app.physics(f, dt, self.app.ground_at(f.x, f.y))
        f.walk += dt * abs(f.vx) / max(1, 22 * K)
        if t >= action["duration"] or (kind in ("plane", "wall_kick", "boost") and f.on_ground and t > .35):
            self._finish(f)
        elif f.state in FREE:
            # Physics can select fall on descent; the action continues to own
            # only that ordinary transition, never an external priority state.
            f.set_state("parkour")
        return True

    def pose(self, f):
        action = self.actions.get(f)
        if action is None or f.state != "parkour":
            return None
        kind, t = action["kind"], action["t"]
        if kind == "rope":
            return 0, -30, -.10, 0, (-12, 2), (13, -7), (-2, -62), (2, -62)
        if kind == "slide":
            return -5, -12, -.85, .45, (-19, 0), (23, -1), (-21, -9), (15, -13)
        if kind == "roll":
            return 0, -15, .40, .20, (-7, -3), (8, -3), (-8, -23), (9, -24)
        if kind == "plane":
            return -7, -22, .62, -.35, (-23, -2), (-8, 0), (22, -33), (24, -28)
        if kind == "vault":
            return 0, -22, .35, 0, (-14, -5), (18, -16), (-2, -30), (15, -29)
        if kind == "boost_helper" or (kind == "boost" and t < .30):
            return 0, -19, .1, -.15, (-14, 0), (14, 0), (-8, -41), (9, -43)
        return 0, -30, -.15, 0, (-17, -3), (14, -12), (-20, -58), (17, -61)

    def draw(self):
        app = self.app
        app.layer("toys")
        for prop in self.props:
            x, y, w, h = prop["x"], prop["y"], prop["w"], prop["h"]
            left, right, top = x - w / 2, x + w / 2, y - h
            kind = prop["kind"]
            if kind == "crate":
                app.box(left, top, right, y, "#554B42", WOOD, 2)
                app.line((left + 4, top + 4, right - 4, y - 4), WOOD, 2)
                app.line((left + 4, y - 4, right - 4, top + 4), WOOD, 2)
            elif kind == "seesaw":
                app.line((x - h, y, x, top, x + h, y), INK, 3)
                app.line((left, self._height(prop, left), right, self._height(prop, right)), WOOD, 5)
                app.dot(x, top, 4, PAPER)
            elif kind == "ramp":
                app.line((left, y, right, top, right, y, left, y), WOOD, 4)
                for i in range(1, 5):
                    px = left + w * i / 5
                    app.line((px, y, px, self._height(prop, px)), INK, 1)
            elif kind == "fan":
                app.box(left, top, right, y, "#334655", INK, 2)
                for i in range(3):
                    angle = prop["phase"] + i * math.pi * 2 / 3
                    app.line((x, top + h / 2, x + math.cos(angle) * w * .35,
                              top + h / 2 + math.sin(angle) * h * .32), PAPER, 3)
                    px = x + (i - 1) * w * .28
                    app.line((px, top - 9, px + math.sin(prop["phase"] + i) * 5,
                              top - 40, px, top - 68), "#8CB8C8", 1)
            elif kind == "conveyor":
                app.box(left, top, right, y, "#334655", INK, 2)
                for i in range(6):
                    px = left + ((i / 6 + prop["phase"] / (math.pi * 12)) % 1) * w
                    app.line((px - 3, top + h * .2, px + 3, top + h * .5,
                              px - 3, top + h * .8), PAPER, 1)
            app.text(left - app.ox - app.sx, y + 10 - app.oy - app.sy,
                     kind.upper(), INK, ("Segoe UI", 6))
        for f, action in self.actions.items():
            if f.state != "parkour":
                continue
            S = f.sc
            if action["kind"] == "rope":
                ax, ay = action["anchor"]
                app.line((ax, ay, f.x, f.y - 62 * S), WOOD, max(1, 2 * S))
                app.dot(ax, ay, 3 * S, INK)
            elif action["kind"] == "plane":
                face, x, y = action["face"], f.x, f.y - 4 * S
                app.line((x - face * 37 * S, y - 5 * S, x + face * 51 * S, y - 12 * S,
                          x - face * 19 * S, y + 9 * S, x - face * 37 * S, y - 5 * S), PAPER, 3)
                app.line((x - face * 19 * S, y + 9 * S, x + face * 2 * S, y - 4 * S,
                          x + face * 51 * S, y - 12 * S), INK, 1)
                app.line((x - face * 45 * S, y, x - face * 62 * S, y + 3 * S), INK, 1)
            elif action["kind"] in ("slide", "roll", "wall_kick"):
                for i in range(3):
                    x = f.x - action["face"] * (24 + 7 * i) * S
                    y = f.y - (3 + i * 8) * S
                    app.line((x, y, x - action["face"] * 12 * S, y), INK, 1)
