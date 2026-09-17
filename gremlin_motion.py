"""Bounded canvas toys and cooperative traversal on the existing physics seam.

World coordinates stay in the simulation. Toys never touch icons, files,
windows, native input or focus. Priority states always supersede traversal.
"""
import math
import random

from gremlin_physics import material, preset, segment_contact


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
        self._support_terrain = None

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
            anchor_window = None
            if target is None:
                ledges = [p for p in self.app.terrain.platforms
                          if p[2] < f.y - 90 * S and abs((p[0] + p[1]) / 2 - f.x) < 320 * S]
                if not ledges:
                    return False
                p = min(ledges, key=lambda p: abs((p[0] + p[1]) / 2 - f.x))
                target = ((p[0] + p[1]) / 2, p[2])
                if p[3] == "window":
                    anchor_window = p[4]
            if not isinstance(target, (tuple, list)) or len(target) < 2:
                return False
            ax, ay = target[:2]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (ax, ay)):
                return False
            if anchor_window is None:
                for hwnd, rect in self.app.terrain.win_rect.items():
                    if rect[0] <= ax <= rect[2] and abs(ay - rect[1]) < 6:
                        anchor_window = hwnd
                        break
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
                          omega=omega, duration=2.2, hwnd=anchor_window,
                          anchor_velocity=(0.0, 0.0))
            if anchor_window is not None:
                rect = self.app.terrain.win_rect[anchor_window]
                action["local_anchor"] = (ax - rect[0], ay - rect[1])
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
                "phase": 0.0, "cooldown": 0.0, "occupants": set(), "direction": 1,
                "vx": 0.0, "vy": 0.0, "omega": 0.0, "mass": 3.0,
                "sleeping": False, "rest": 0.0, "support": None,
                "material": self.cfg.get("surface_material", "standard")}
        self.props.append(prop)
        return prop

    def _height(self, prop, x):
        if prop["kind"] == "crate":
            vertices = self._vertices(prop)
            crossings = []
            for a, b in zip(vertices, vertices[1:] + vertices[:1]):
                if min(a[0], b[0]) - .001 <= x <= max(a[0], b[0]) + .001:
                    if abs(b[0] - a[0]) < .001:
                        crossings.append(min(a[1], b[1]))
                    else:
                        crossings.append(a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))
            return min(crossings) if crossings else min(y for _x, y in vertices)
        u = clamp((x - prop["x"]) / prop["w"] + .5, 0, 1)
        if prop["kind"] == "ramp":
            return prop["y"] - u * prop["h"]
        if prop["kind"] == "seesaw":
            return prop["y"] - prop["h"] + (x - prop["x"]) * math.tan(prop["angle"])
        return prop["y"] - prop["h"]

    @staticmethod
    def _geometry_key(prop):
        # Props are ordinary mutable dictionaries. Check values at every read so
        # impulses, contact correction and external placement cannot leave stale
        # geometry behind between physics, projectile collision and drawing.
        return (prop["kind"], prop["id"], prop["x"], prop["y"],
                prop["w"], prop["h"], prop["angle"])

    def _geometry(self, prop):
        key = self._geometry_key(prop)
        cached = prop.get("_geometry")
        if cached is None or cached["key"] != key:
            cached = prop["_geometry"] = {"key": key}
        return cached

    def _prop_platforms(self, prop):
        cached = self._geometry(prop)
        if "platforms" not in cached:
            result = []
            if prop["kind"] != "fan":
                left, _top, right, _bottom = self._bounds(prop)
                width = right - left
                count = 10 if prop["kind"] in ("crate", "ramp", "seesaw") else 1
                for i in range(count):
                    x0, x1 = left + width * i / count, left + width * (i + 1) / count
                    result.append((x0, x1, self._height(prop, (x0 + x1) / 2), "toy", prop["id"]))
            cached["platforms"] = tuple(result)
        return cached["platforms"]

    def platforms(self):
        if not self.cfg.get("toy_props", True):
            return []
        # Return a fresh outer list: callers may extend it without changing the
        # cached surfaces shared by the remaining fighters in this frame.
        return [surface for prop in self.props for surface in self._prop_platforms(prop)]

    def _vertices(self, prop):
        """Drawing and swept collisions use the same rigid crate corners."""
        cached = self._geometry(prop)
        if "vertices" in cached:
            return cached["vertices"]
        cx, cy = prop["x"], prop["y"] - prop["h"] / 2
        c, s = math.cos(prop["angle"]), math.sin(prop["angle"])
        w, h = prop["w"] / 2, prop["h"] / 2
        cached["vertices"] = tuple((cx + dx * c - dy * s, cy + dx * s + dy * c)
                                   for dx, dy in ((-w, -h), (w, -h), (w, h), (-w, h)))
        return cached["vertices"]

    def _bounds(self, prop):
        cached = self._geometry(prop)
        if "bounds" in cached:
            return cached["bounds"]
        if prop["kind"] == "crate":
            corners = self._vertices(prop)
            cached["bounds"] = (min(x for x, _y in corners), min(y for _x, y in corners),
                                max(x for x, _y in corners), max(y for _x, y in corners))
        else:
            left, right = prop["x"] - prop["w"] / 2, prop["x"] + prop["w"] / 2
            cached["bounds"] = (left, min(self._height(prop, left), self._height(prop, right)),
                                right, prop["y"])
        return cached["bounds"]

    def _polygon_contact(self, x0, y0, x1, y1, vertices, radius):
        """Clip a swept point against a convex polygon's outward half planes."""
        enter, leave, nx, ny = 0.0, 1.0, 0.0, 0.0
        dx, dy = x1 - x0, y1 - y0
        nearest_face = (-float("inf"), 0.0, 0.0)
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            ex, ey = b[0] - a[0], b[1] - a[1]
            length = max(.001, math.hypot(ex, ey))
            ox, oy = ey / length, -ex / length
            distance = (x0 - a[0]) * ox + (y0 - a[1]) * oy - radius
            if distance > nearest_face[0]:
                nearest_face = distance, ox, oy
            speed = dx * ox + dy * oy
            if abs(speed) < 1e-9:
                if distance > 0:
                    return None
                continue
            t = -distance / speed
            if speed < 0:
                if t >= enter:
                    enter, nx, ny = t, ox, oy
            else:
                leave = min(leave, t)
            if enter > leave:
                return None
        if 0 <= enter <= 1 and leave >= 0:
            if nearest_face[0] <= 1e-7:
                # Separation from a just-hit face is not another ricochet.
                _distance, nx, ny = nearest_face
                return (0.0, nx, ny) if dx * nx + dy * ny < 0 else None
            if nx == ny == 0:
                length = max(.001, math.hypot(dx, dy))
                nx, ny = -dx / length, -dy / length
            return enter, nx, ny
        return None

    def projectile_contact(self, x0, y0, x1, y1, radius=0):
        if not self.cfg.get("toy_props", True):
            return None
        nearest = None
        for prop in self.props:
            left, top, right, bottom = self._bounds(prop)
            if prop["kind"] == "crate":
                vertices = self._vertices(prop)
            elif prop["kind"] == "ramp":
                vertices = [(left, bottom), (right, top), (right, bottom)]
            elif prop["kind"] == "seesaw":
                # The thin beam is the contact surface, not its empty bounding box.
                ly, ry = self._height(prop, left), self._height(prop, right)
                vertices = [(left, ly - 2.5), (right, ry - 2.5),
                            (right, ry + 2.5), (left, ly + 2.5)]
            else:
                vertices = [(left, top), (right, top), (right, bottom), (left, bottom)]
            hit = self._polygon_contact(x0, y0, x1, y1, vertices, max(0, radius))
            if hit is not None and (nearest is None or hit[0] < nearest[0]):
                nearest = hit + (prop,)
        return nearest

    def hit_prop(self, prop, x, y, vx, vy, strength=1.0):
        if prop not in self.props or not all(math.isfinite(v) for v in (x, y, vx, vy, strength)):
            return
        power = clamp(strength, 0, 8) * preset(self.cfg.get("physics_preset", "normal"))["impulse"]
        jx, jy = clamp(vx, -4000, 4000) * .32 * power, clamp(vy, -4000, 4000) * .32 * power
        mass = prop["mass"]
        inertia = mass * (prop["w"] ** 2 + prop["h"] ** 2) / 12
        # The cross product converts an off-center impulse into angular momentum.
        torque = (x - prop["x"]) * jy - (y - prop["y"] + prop["h"] / 2) * jx
        if prop["kind"] == "crate":
            prop["vx"] = clamp(prop["vx"] + jx / mass, -900, 900)
            prop["vy"] = clamp(prop["vy"] + jy / mass, -900, 900)
            prop["omega"] = clamp(prop["omega"] + torque / max(1, inertia), -10, 10)
            prop["sleeping"], prop["rest"] = False, 0.0
        elif prop["kind"] == "seesaw":
            prop["omega"] = clamp(prop["omega"] + torque / max(1, inertia), -9, 9)

    def blast(self, x, y, radius, strength):
        if radius <= 0:
            return
        for prop in self.props:
            dx, dy = prop["x"] - x, prop["y"] - prop["h"] / 2 - y
            distance = math.hypot(dx, dy)
            if distance < radius:
                # Negative radial strength is attraction; only explosions lift.
                force = strength * (1 - distance / radius)
                self.hit_prop(prop, x, y, dx / max(1, distance) * force,
                              dy / max(1, distance) * force - max(0, force) * .65, 2.0)

    def surface_velocity(self, f):
        if f.plat and f.plat[0] == "toy":
            for prop in self.props:
                if prop["id"] == f.plat[1]:
                    return prop["direction"] * 90 * f.K() if prop["kind"] == "conveyor" else 0.0
        return 0.0

    def _support(self, prop, previous_bottom):
        left, _top, right, bottom = self._bounds(prop)
        floor = self.app.ground_at(prop["x"], previous_bottom)
        best = (floor, ("floor", None), 0.0) if bottom >= floor - .5 else None
        for a, b, y, kind, key in self.app.terrain.platforms:
            if (a <= prop["x"] <= b and min(right, b) - max(left, a) > 5 and bottom >= y - .5
                    and previous_bottom <= y + 4
                    and (best is None or y < best[0])):
                best = y, (kind, key), 0.0
        for other in self.props:
            if other is prop or other["kind"] == "fan":
                continue
            a, _t, b, _d = self._bounds(other)
            if not (a <= prop["x"] <= b and min(right, b) - max(left, a) > 5):
                continue
            sample = clamp(prop["x"], a + .01, b - .01)
            y = self._height(other, sample)
            if (bottom >= y - .5 and previous_bottom <= y + 4
                    and (best is None or y < best[0])):
                best = y, ("toy", other["id"]), other["vx"]
        return best

    def _sleep_key(self, prop):
        # Snapshot desktop surfaces once per update, but inspect the small prop
        # list on every substep: a lower crate may have just moved or expired.
        terrain = self._support_terrain
        if terrain is None:
            terrain = tuple(self.app.terrain.platforms)
        neighbors = tuple((self._geometry_key(other), other["vx"], other["vy"],
                           other["omega"], other["direction"])
                          for other in self.props if other is not prop)
        return (self._geometry_key(prop), prop["vx"], prop["vy"], prop["omega"],
                prop["support"], terrain, neighbors,
                self.app.ground_at(prop["x"], self._bounds(prop)[3]),
                self.cfg.get("scale", 1.0), self.cfg.get("physics_preset", "normal"),
                prop["material"])

    def _sleep_driven(self, prop, support):
        if abs(prop["vx"]) >= .8 or abs(prop["vy"]) >= 1 or abs(prop["omega"]) >= .02:
            return True
        for other in self.props:
            if (other["kind"] == "fan" and abs(prop["x"] - other["x"]) < other["w"] / 2
                    and other["y"] - 185 * self.cfg.get("scale", 1.0) < prop["y"] < other["y"]):
                return True
            if support is not None and support[1] == ("toy", other["id"]):
                if ((other["kind"] == "conveyor" and other["direction"])
                        or other["vx"] or other["vy"] or other["omega"]):
                    return True
        return False

    def _crate_step(self, prop, dt):
        K = self.cfg.get("scale", 1.0) / 1.75
        old_x, old_y = prop["x"], prop["y"]
        before = self._bounds(prop)
        if prop["sleeping"]:
            sleep_key = self._sleep_key(prop)
            if prop.get("_sleep_key") == sleep_key:
                return
            support = self._support(prop, before[3])
            if (support is not None and abs(before[3] - support[0]) < 1
                    and not self._sleep_driven(prop, support)):
                prop["support"] = support[1]
                prop["_sleep_key"] = self._sleep_key(prop)
                return
            # Moved supports and newly active fans/belts wake a stable stack.
            prop["sleeping"], prop["rest"] = False, 0.0
        prop.pop("_sleep_key", None)
        response = material(prop["material"])
        bounce = max(response["restitution"], .7 if self.cfg.get("physics_preset") == "bouncy" else 0)
        gravity = 1900 * K * preset(self.cfg.get("physics_preset", "normal"))["gravity"]
        prop["vy"] += gravity * dt
        for fan in self.props:
            if (fan["kind"] == "fan" and abs(prop["x"] - fan["x"]) < fan["w"] / 2
                    and fan["y"] - 185 * self.cfg.get("scale", 1.0) < prop["y"] < fan["y"]):
                prop["vy"] -= gravity * 1.8 * dt
        prop["vy"] = clamp(prop["vy"], -1000, 1200)
        prop["x"] += prop["vx"] * dt
        prop["y"] += prop["vy"] * dt
        prop["angle"] = (prop["angle"] + prop["omega"] * dt + math.pi) % (2 * math.pi) - math.pi
        bounds = self._bounds(prop)
        # Window sides are swept using the crate's conservative rotated extent.
        ex, ey = (bounds[2] - bounds[0]) / 2, (bounds[3] - bounds[1]) / 2
        for _name, left, top, right, bottom, _key in self.app.terrain.windows:
            hit = segment_contact(old_x, old_y - prop["h"] / 2,
                                  prop["x"], prop["y"] - prop["h"] / 2,
                                  left - ex, top - ey, right + ex, bottom + ey)
            if hit is not None and hit[1] and not (left - ex < old_x < right + ex
                    and top - ey < old_y - prop["h"] / 2 < bottom + ey):
                prop["x"] = old_x + (prop["x"] - old_x) * hit[0] + hit[1] * .1
                prop["vx"] *= -bounce
        support = self._support(prop, before[3])
        previous_support, prop["support"] = prop["support"], None
        if support is not None and prop["vy"] >= 0:
            level, key, belt = support
            prop["y"] -= self._bounds(prop)[3] - level
            prop["support"] = key
            if key[0] == "toy":
                base = next((p for p in self.props if p["id"] == key[1]), None)
                if base is not None and base["kind"] == "conveyor":
                    belt = base["direction"] * 90 * K
                elif base is not None and base["kind"] == "seesaw" and previous_support != key:
                    inertia = base["mass"] * base["w"] ** 2 / 12
                    base["omega"] += prop["mass"] * prop["vy"] * (prop["x"] - base["x"]) / inertia
            # Tiny contact velocities settle, while energetic impacts rebound.
            prop["vy"] = -prop["vy"] * bounce if prop["vy"] > 90 * K else 0.0
            drag = 260 * K * response["friction"] * dt
            prop["vx"] += clamp(belt - prop["vx"], -drag, drag)
            # Contact torque lets a tilted box fall onto its nearest broad face.
            error = (prop["angle"] + math.pi / 2) % math.pi - math.pi / 2
            prop["omega"] -= error * 22 * dt
            prop["omega"] *= math.exp(-7 * max(.25, response["friction"]) * dt)
            if abs(error) < .035 and abs(prop["omega"]) < .2:
                prop["angle"] -= error
                prop["omega"] = 0.0
                prop["y"] -= self._bounds(prop)[3] - level
            if abs(prop["vx"]) < .8 and abs(prop["vy"]) < 1 and abs(prop["omega"]) < .02:
                prop["rest"] += dt
                if prop["rest"] > .6:
                    prop["sleeping"], prop["vx"], prop["vy"] = True, 0.0, 0.0
            else:
                prop["rest"] = 0.0
        else:
            prop["rest"] = 0.0
        mon, work = self.app.monitor_at(prop["x"], prop["y"])
        bounds = self._bounds(prop)
        if bounds[0] < mon[0] or bounds[2] > mon[2]:
            prop["x"] += mon[0] - bounds[0] if bounds[0] < mon[0] else mon[2] - bounds[2]
            prop["vx"] *= -bounce
        # Carry only existing physical riders; priority activities remain owners.
        for actor in prop["occupants"]:
            if self._free(actor) and actor.plat == ("toy", prop["id"]):
                actor.x += prop["x"] - old_x
                actor.y = self._height(prop, actor.x)

    def _crate_pairs(self):
        crates = [p for p in self.props if p["kind"] == "crate"]
        for i, first in enumerate(crates):
            for second in crates[i + 1:]:
                a, b = self._bounds(first), self._bounds(second)
                ox, oy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
                if ox <= 0 or oy <= .5:
                    continue
                upper, lower = (first, second) if a[1] < b[1] else (second, first)
                lower_bounds = b if upper is first else a
                unstable = not lower_bounds[0] <= upper["x"] <= lower_bounds[2]
                if ox < oy or unstable:
                    sign = -1 if first["x"] < second["x"] else 1
                    first["x"] += sign * (ox / 2 + .01)
                    second["x"] -= sign * (ox / 2 + .01)
                    relative = (first["vx"] - second["vx"]) * sign
                    if relative < 0:
                        bounce = min(material(p["material"])["restitution"] for p in (first, second))
                        impulse = -(1 + bounce) * relative / 2
                        first["vx"] += impulse * sign
                        second["vx"] -= impulse * sign
                    for p in (first, second):
                        p["sleeping"], p["rest"] = False, 0.0
                else:
                    upper["y"] -= oy
                    upper["vy"] = min(upper["vy"], lower["vy"])

    def _seesaw_step(self, prop, occupants, dt):
        inertia = prop["mass"] * prop["w"] ** 2 / 12
        gravity = 1900 / 1.75 * self.cfg.get("scale", 1.0) * preset(self.cfg.get("physics_preset", "normal"))["gravity"]
        for actor in occupants:
            lever = actor.x - prop["x"]
            weight = clamp(getattr(actor, "physics_mass", actor.sc ** 2), .35, 8)
            prop["omega"] += weight * gravity * lever / inertia * dt
            if actor not in prop["occupants"]:
                speed = max(0, getattr(actor, "physics_impact_vy", 0), getattr(actor, "motion_last_vy", 0))
                prop["omega"] += weight * min(speed, 1500) * lever / inertia
                actor.physics_impact_vy = actor.motion_last_vy = 0.0
        for other in self.props:
            if other["kind"] == "crate" and other["support"] == ("toy", prop["id"]):
                prop["omega"] += other["mass"] * gravity * (other["x"] - prop["x"]) / inertia * dt
        prop["omega"] = clamp((prop["omega"] - prop["angle"] * 5 * dt) * math.exp(-1.3 * dt), -9, 9)
        prop["angle"] += prop["omega"] * dt
        limit = math.atan2(prop["h"] - 2, prop["w"] / 2)
        if abs(prop["angle"]) > limit:
            prop["angle"] = clamp(prop["angle"], -limit, limit)
            prop["omega"] *= -.12
        for actor in occupants:
            # The derivative of beam height is the launch velocity at this lever.
            surface_vy = (actor.x - prop["x"]) * prop["omega"] / math.cos(prop["angle"]) ** 2
            actor.y = self._height(prop, actor.x)
            if surface_vy < -60 * actor.K():
                actor.y -= 1
                actor.vy, actor.on_ground, actor.plat = surface_vy, False, None
                actor.set_state("jump")

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
            prop["material"] = self.cfg.get("surface_material", "standard")
            occupants = {f for f in self.app.fighters if self._free(f)
                         and f.on_ground and abs(f.x - prop["x"]) < prop["w"] / 2 + 5
                         and abs(f.y - self._height(prop, f.x)) < 12 * f.sc}
            if prop["kind"] == "seesaw":
                self._seesaw_step(prop, occupants, min(dt, .12))
            prop["occupants"] = occupants
        # A fixed upper bound prevents a delayed render from multiplying work.
        steps = max(1, min(8, int(math.ceil(max(0, dt) / (1 / 120)))))
        step = min(max(0, dt), .12) / steps
        self._support_terrain = tuple(self.app.terrain.platforms)
        try:
            for _ in range(steps):
                for prop in sorted(self.props, key=lambda p: p["y"], reverse=True):
                    if prop["kind"] == "crate":
                        self._crate_step(prop, step)
                self._crate_pairs()
        finally:
            self._support_terrain = None
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
                gravity = 1900 * f.K() * preset(self.cfg.get("physics_preset", "normal"))["gravity"]
                f.vy -= gravity * 1.8 * dt
                f.on_ground, f.plat = False, None
                if f.state in ("idle", "walk", "taunt"):
                    f.set_state("jump")
            elif prop["kind"] == "conveyor" and f.on_ground and abs(f.y - top) < 12 * f.sc:
                traction = 900 * f.K() * material(prop["material"])["friction"] * dt
                f.vx += clamp(prop["direction"] * 90 * f.K() - f.vx, -traction, traction)
            elif prop["kind"] in ("crate", "ramp", "seesaw") and f.on_ground and abs(f.y - top) < 15 * f.sc:
                # Match the exact next segment (including physics' 6px foot
                # tolerance), so an uphill step cannot create a false fall.
                next_x = f.x + f.vx * dt
                surfaces = self._prop_platforms(prop) if self.cfg.get("toy_props", True) else ()
                supports = [p[2] for p in surfaces
                            if p[0] - 6 <= next_x <= p[1] + 6]
                if supports:
                    f.y, f.vy = min(supports), 0.0
                    f.plat = ("toy", prop["id"])
            elif prop["kind"] == "crate" and top + 4 < f.y < prop["y"] + 50 * f.sc:
                left, _top, right, _bottom = self._bounds(prop)
                side = -1 if f.x < prop["x"] else 1
                if f.vx * side < 0:
                    # Walking bodies push with a per-step impulse, never teleport the box.
                    self.hit_prop(prop, f.x, f.y - 25 * f.sc, f.vx, 0, dt * 8)
                    f.x = (left - 5 * f.sc) if side < 0 else (right + 5 * f.sc)
                    f.vx = prop["vx"]

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
            if dt <= 0:
                return True
            old_anchor = action["anchor"]
            hwnd = action.get("hwnd")
            if hwnd is not None:
                rect = self.app.terrain.win_rect.get(hwnd)
                if rect is None:
                    self._finish(f)
                    return True
                local = action["local_anchor"]
                action["anchor"] = rect[0] + local[0], rect[1] + local[1]
            ax, ay = action["anchor"]
            if math.hypot(ax - old_anchor[0], ay - old_anchor[1]) > max(80 * S, action["length"] * .75):
                # A maximize/monitor jump cannot drag the body through an entire
                # desktop in one sample; let go with the last valid momentum.
                self._finish(f)
                return True
            avx, avy = (ax - old_anchor[0]) / dt, (ay - old_anchor[1]) / dt
            last_vx, last_vy = action["anchor_velocity"]
            angle, omega, length = action["angle"], action["omega"], action["length"]
            # Anchor acceleration contributes an opposite tangential impulse in
            # the moving reference frame. World release adds anchor velocity.
            omega -= ((avx - last_vx) * math.cos(angle)
                      - (avy - last_vy) * math.sin(angle)) / length
            action["anchor_velocity"] = avx, avy
            steps = max(1, min(8, int(math.ceil(dt / (1 / 120)))))
            step = min(dt, .12) / steps
            gravity = 1900 * K * preset(self.cfg.get("physics_preset", "normal"))["gravity"]
            for index in range(steps):
                omega += (-gravity / length * math.sin(angle) - .045 * omega) * step
                angle += omega * step
                u = (index + 1) / steps
                anchor_x, anchor_y = old_anchor[0] + (ax - old_anchor[0]) * u, old_anchor[1] + (ay - old_anchor[1]) * u
                next_x = anchor_x + length * math.sin(angle)
                next_y = anchor_y + length * math.cos(angle) + 62 * S
                hit = self._rope_contact(f, next_x, next_y, hwnd)
                f.vx = avx + length * math.cos(angle) * omega
                f.vy = avy - length * math.sin(angle) * omega
                if hit is not None:
                    fraction, nx, ny = hit
                    f.x += (next_x - f.x) * fraction + nx * .2
                    f.y += (next_y - f.y) * fraction + ny * .2
                    inward = min(0, f.vx * nx + f.vy * ny)
                    f.vx -= inward * nx
                    f.vy -= inward * ny
                    self._finish(f)
                    return True
                f.x, f.y = next_x, next_y
            action["angle"], action["omega"] = angle, omega
            f.face = 1 if f.vx >= 0 else -1
            if (t > .65 and angle * omega > 0 and abs(angle) > .30) or t >= action["duration"]:
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

    def _rope_contact(self, f, next_x, next_y, anchor_window):
        nearest = None
        obstacles = [(rect, True) for rect in self.app.terrain.windows]
        obstacles += [(rect, False) for rect in self.app.terrain.icons]
        for (_name, left, top, right, bottom, key), is_window in obstacles:
            for height in (4, 32, 60):
                x0, y0, x1, y1 = f.x, f.y - height * f.sc, next_x, next_y - height * f.sc
                radius = 9 * f.sc
                if (is_window and key == anchor_window and left - radius < x0 < right + radius
                        and top - radius < y0 < bottom + radius):
                    continue
                hit = segment_contact(x0, y0, x1, y1, left - radius, top - radius,
                                      right + radius, bottom + radius)
                if hit is not None and (nearest is None or hit[0] < nearest[0]):
                    nearest = hit
        for height in (4, 32, 60):
            hit = self.projectile_contact(f.x, f.y - height * f.sc,
                                          next_x, next_y - height * f.sc, 9 * f.sc)
            if hit is not None and (nearest is None or hit[0] < nearest[0]):
                nearest = hit[:3]
        floor = self.app.ground_at(next_x, f.y)
        if next_y >= floor and next_y > f.y:
            hit = (clamp((floor - f.y) / (next_y - f.y), 0, 1), 0.0, -1.0)
            if nearest is None or hit[0] < nearest[0]:
                nearest = hit
        return nearest

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
                corners = self._vertices(prop)
                if abs(prop["angle"]) < .001:
                    app.box(left, top, right, y, "#554B42", WOOD, 2)
                else:
                    app.line(tuple(v for point in corners + corners[:1] for v in point), WOOD, 2)
                app.line(corners[0] + corners[2], WOOD, 2)
                app.line(corners[1] + corners[3], WOOD, 2)
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
