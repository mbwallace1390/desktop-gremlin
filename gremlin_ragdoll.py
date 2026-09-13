"""Bounded passive two-link limbs around the existing authored fighter root.

Only grabs, throws and knockouts relinquish animation control. Four damped
angular chains respond to gravity and measured root acceleration; signed hinge
limits prevent inverted knees/elbows. Ground projection works in joint space,
so a contact never stretches a segment. No random stream, desktop I/O, or
render-time simulation is involved.
"""
import math

from gremlin_physics import preset

ACTIVE = frozenset(("grabbed", "thrown", "ko"))
RECOVERY = .32
MAX_STEP = 1 / 120
MAX_SUBSTEPS = 8


def _clamp(value, low, high):
    return max(low, min(high, value))


def _wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


def _axes(f):
    c, s = math.cos(f.tumble), math.sin(f.tumble)
    return (f.face * f.sc * (1 + f.squash * .22),
            f.sc * (1 - f.squash * .28), c, s)


def _local(vector, axes):
    x, y = vector
    fx, fy, c, s = axes
    return ((c * x + s * y) / fx, (-s * x + c * y) / fy)


def _world(vector, axes):
    x, y = vector
    fx, fy, c, s = axes
    return (fx * c * x - fy * s * y, fx * s * x + fy * c * y)


def _rebase(pose, old, new):
    """Retain visible orientation when the state machine resets root tumble."""
    def point(p):
        return _local(_world(p, old), new)
    px, py = point(pose[:2])
    neck = point((math.sin(pose[2]), -math.cos(pose[2])))
    lean = math.atan2(neck[0], -neck[1])
    return (px, py, lean, pose[3]) + tuple(point(p) for p in pose[4:])


class _Limb:
    __slots__ = ("length", "swing", "low", "high", "rest", "a", "b", "va", "vb")

    def __init__(self, anchor, end, leg):
        self.length = 16.0 if leg else 13.0
        self.swing = 1.50 if leg else 2.85
        self.low, self.high = (.04, 2.65) if leg else (-2.75, -.04)
        self.rest = .40 if leg else -.65
        dx, dy = end[0] - anchor[0], end[1] - anchor[1]
        reach = _clamp(math.hypot(dx, dy) / (2 * self.length), .05, .999)
        self.b = _clamp(2 * math.acos(reach) * (1 if leg else -1), self.low, self.high)
        self.a = math.atan2(dy, dx) - self.b / 2
        self.va = self.vb = 0.0

    def limit(self, center):
        offset = _wrap(self.a - center)
        limited = _clamp(offset, -self.swing, self.swing)
        if offset != limited:
            self.va *= -.12
        self.a = center + limited
        limited = _clamp(self.b, self.low, self.high)
        if limited != self.b:
            self.vb *= -.10
        self.b = limited

    def points(self, anchor):
        x, y = anchor
        joint = (x + self.length * math.cos(self.a), y + self.length * math.sin(self.a))
        return joint, (joint[0] + self.length * math.cos(self.a + self.b),
                       joint[1] + self.length * math.sin(self.a + self.b))

    def contact(self, anchor, normal, floor, center):
        """Project to the nearest bounded configuration above the ground plane.

        With equal segments the endpoint lies along a+b/2 at distance
        2*length*cos(b/2). Thus both joint and endpoint contacts have exact
        angle boundaries. A fixed small bend sample is used only on contact;
        choosing an allowed angle keeps both segment lengths exact.
        """
        nx, ny = normal
        joint, end = self.points(anchor)
        if max(nx * joint[0] + ny * joint[1], nx * end[0] + ny * end[1]) <= floor + 1e-7:
            return
        norm = math.hypot(nx, ny)
        height = floor - nx * anchor[0] - ny * anchor[1]
        direction = math.atan2(ny, nx)
        best, cost = None, float("inf")
        bends = (self.b, _clamp(self.b - .18, self.low, self.high),
                 _clamp(self.b + .18, self.low, self.high)) + tuple(
                     self.low + (self.high - self.low) * i / 8 for i in range(9))
        joint_ratio = _clamp(height / (norm * self.length), -1, 1)
        joint_edge = math.acos(joint_ratio)
        for bend_index, bend in enumerate(bends):
            endpoint_ratio = _clamp(height / (norm * 2 * self.length * math.cos(bend / 2)), -1, 1)
            endpoint_edge = math.acos(endpoint_ratio)
            candidates = (self.a, center - self.swing, center + self.swing,
                          direction - joint_edge, direction + joint_edge,
                          direction - bend / 2 - endpoint_edge,
                          direction - bend / 2 + endpoint_edge)
            for angle in candidates:
                angle = center + _wrap(angle - center)
                if abs(angle - center) > self.swing + 1e-8:
                    continue
                jx = anchor[0] + self.length * math.cos(angle)
                jy = anchor[1] + self.length * math.sin(angle)
                ex = jx + self.length * math.cos(angle + bend)
                ey = jy + self.length * math.sin(angle + bend)
                if max(nx * jx + ny * jy, nx * ex + ny * ey) > floor + 1e-6:
                    continue
                distance = _wrap(angle - self.a) ** 2 + .6 * (bend - self.b) ** 2
                if distance < cost:
                    cost, best = distance, (angle, bend)
            # Resting contacts need only a tiny upper-angle correction. Keep
            # their bend and avoid searching impact configurations every tick.
            if bend_index == 0 and cost < .0025:
                break
        if best is not None:
            # Contact dissipates angular energy; the authored root owns the
            # actual fighter collision and cannot receive a second impulse.
            self.a, self.b = best
            self.va *= .30
            self.vb *= .30


class _Body:
    __slots__ = ("limbs", "pose", "joints", "axes", "x", "y", "vx", "vy",
                 "face", "active", "recovery", "torso")

    def __init__(self, f, pose):
        self.pose, self.torso = pose, pose[:4]
        hip = pose[:2]
        shoulder = (hip[0] + 26 * math.sin(pose[2]), hip[1] - 26 * math.cos(pose[2]) - 1)
        self.limbs = [_Limb(hip if i < 2 else shoulder, pose[4 + i], i < 2) for i in range(4)]
        self.joints = None
        self.axes = _axes(f)
        self.x, self.y, self.vx, self.vy = f.x, f.y, f.vx, f.vy
        self.face, self.active, self.recovery = f.face, True, 0.0


class Ragdoll:
    """App integration: update after root physics; pose/joints are pure reads."""

    def __init__(self, app, config=None):
        self.app = app
        self.config = config if config is not None else {}

    def update(self, f, dt):
        if not math.isfinite(dt) or dt <= 0 or f.sc <= 0:
            return
        body = getattr(f, "_ragdoll", None)
        active = f.state in ACTIVE
        axes = _axes(f)
        if not active:
            if body is None:
                return
            if f.state != "idle":
                # Authored actions and exact weapon/grip poses own the next
                # frame immediately, even if a new action interrupts recovery.
                f._ragdoll = None
                return
            if body.active:
                body.pose = _rebase(body.pose, body.axes, axes)
                body.active, body.recovery = False, 0.0
            body.recovery += min(dt, .1)
            if body.recovery >= RECOVERY:
                f._ragdoll = None
            return

        created = body is None or not body.active or body.face != f.face
        if created:
            # Seed from the last authored silhouette so the first passive
            # frame inherits individual limb positions instead of a stock pose.
            initial = f.pose_last if f.pose_last is not None else self.app.raw_pose(f)
            body = f._ragdoll = _Body(f, initial)
        vx, vy = ((f.vx, f.vy) if created else
                  ((f.x - body.x) / dt, (f.y - body.y) / dt))
        # There is no previous measured displacement at activation. Treating
        # that missing sample as zero would fabricate a braking impulse.
        ax = 0.0 if created else _clamp((vx - body.vx) / dt, -12000 * f.sc, 12000 * f.sc)
        ay = 0.0 if created else _clamp((vy - body.vy) / dt, -12000 * f.sc, 12000 * f.sc)
        gravity = 1900 * f.K() * preset(self.config.get("physics_preset", "normal"))["gravity"]
        gx, gy = _local((-ax, gravity - ay), axes)
        gx, gy = _clamp(gx, -7000, 7000), _clamp(gy, -7000, 7000)
        body.x, body.y, body.vx, body.vy = f.x, f.y, vx, vy

        for limb in body.limbs:
            # Keep angular momentum in screen space when the root tumbles.
            upper = _local(_world((math.cos(limb.a), math.sin(limb.a)), body.axes), axes)
            lower = _local(_world((math.cos(limb.a + limb.b), math.sin(limb.a + limb.b)), body.axes), axes)
            limb.a = math.atan2(upper[1], upper[0])
            limb.b = _wrap(math.atan2(lower[1], lower[0]) - limb.a)
        body.axes = axes
        if f.state == "ko":
            target = (0.0, -12.0, -1.35, .2) if f.on_ground else (0.0, -28.0, -.25, .12)
        elif f.state == "grabbed":
            target = (0.0, -28.0, _clamp(gx / 22000, -.25, .25), 0.0)
        else:
            target = (0.0, -30.0, 0.0, 0.0)
        elapsed = min(dt, MAX_STEP * MAX_SUBSTEPS)
        ease = 1 - math.exp(-elapsed * 13)
        body.torso = tuple(a + (b - a) * ease for a, b in zip(body.torso, target))
        px, py, lean, tilt = body.torso
        floor_y = f.y if f.on_ground else self.app.ground_at(f.x, f.y)
        # Ground contacts also protect a rotated torso/head. Translate the
        # display root only; fighter collision, platforms and hit boxes remain
        # owned by the existing physics implementation.
        neck = (px + 26 * math.sin(lean), py - 26 * math.cos(lean))
        head = (neck[0] + 11 * math.sin(lean + tilt), neck[1] - 11 * math.cos(lean + tilt))
        penetration = max(f.y + _world((px, py), axes)[1] + 5 * f.sc - floor_y,
                          f.y + _world(neck, axes)[1] + 4 * f.sc - floor_y,
                          f.y + _world(head, axes)[1] + 13 * f.sc - floor_y, 0.0)
        dx, dy = _local((0, -penetration), axes)
        px, py = px + dx, py + dy
        hip = (px, py)
        shoulder = (px + 26 * math.sin(lean), py - 26 * math.cos(lean) - 1)
        center = math.pi / 2 + lean
        normal = (axes[0] * axes[3] / f.sc, axes[1] * axes[2] / f.sc)
        floor = (floor_y - f.y) / f.sc - 1.0
        steps = max(1, min(MAX_SUBSTEPS, math.ceil(elapsed / MAX_STEP)))
        step = elapsed / steps
        for _ in range(steps):
            for i, limb in enumerate(body.limbs):
                # Gravity and root acceleration create pendulum torque. The
                # lower segment has its own inertia and a weak flexion spring.
                torque = (gy * math.cos(limb.a) - gx * math.sin(limb.a)) / (limb.length * 1.8)
                lower = (gy * math.cos(limb.a + limb.b) - gx * math.sin(limb.a + limb.b)) / limb.length
                limb.va = _clamp((limb.va + torque * step) * math.exp(-2.2 * step), -22, 22)
                limb.vb = _clamp((limb.vb + (.65 * lower - .35 * torque - 9 * (limb.b - limb.rest)) * step)
                                 * math.exp(-3.2 * step), -20, 20)
                limb.a += limb.va * step
                limb.b += limb.vb * step
                limb.limit(center)
                limb.contact(hip if i < 2 else shoulder, normal, floor, center)
        geometry = [limb.points(hip if i < 2 else shoulder) for i, limb in enumerate(body.limbs)]
        body.pose = (px, py, lean, tilt) + tuple(pair[1] for pair in geometry)
        body.joints = tuple(pair[0] for pair in geometry)

    def pose(self, f, authored):
        body = getattr(f, "_ragdoll", None)
        if body is None:
            return authored
        if body.active:
            return body.pose if f.state in ACTIVE else authored
        if f.state != "idle":
            return authored
        u = _clamp(body.recovery / RECOVERY, 0, 1)
        u = u * u * (3 - 2 * u)
        torso = tuple(a + (b - a) * u for a, b in zip(body.pose[:4], authored[:4]))
        ends = tuple(tuple(a + (b - a) * u for a, b in zip(old, new))
                     for old, new in zip(body.pose[4:], authored[4:]))
        return torso + ends

    def joints(self, f, authored):
        body = getattr(f, "_ragdoll", None)
        return body.joints if body is not None and body.active and f.state in ACTIVE else authored
