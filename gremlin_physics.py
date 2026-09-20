"""Small deterministic contact/force helpers shared by bodies, toys and shots.

Coordinates are desktop pixels, time is seconds. No desktop or drawing I/O.
"""
import math

MATERIALS = {
    "standard": {"friction": 1.0, "restitution": .22},
    "ice": {"friction": .045, "restitution": .12},
    "rubber": {"friction": .85, "restitution": .8},
    "sticky": {"friction": 2.5, "restitution": 0.0},
}
PRESETS = {
    "normal": {"gravity": 1.0, "impulse": 1.0},
    "moon": {"gravity": .38, "impulse": 1.0},
    "bouncy": {"gravity": 1.0, "impulse": 1.1},
    "heavy": {"gravity": 1.3, "impulse": .75},
}


def material(name):
    return MATERIALS.get(name, MATERIALS["standard"])


def preset(name):
    return PRESETS.get(name, PRESETS["normal"])


def squash_axes(squash):
    """Landing squash as (x, y) scale factors, clamped, in one shared place.

    `App.frame` draws the body with these and `gremlin_ragdoll._axes` solves
    passive limbs with them, so the two must agree exactly or limbs detach from
    the torso with every check still green -- the same drift the muzzles once
    paid for. The clamp matters because `_axes` divides by the y factor, which
    reaches zero at a squash of 3.57; nothing assigns beyond the 1.3 cartoon
    flatten today, but the division is here rather than at the assignment sites.
    """
    if not math.isfinite(squash):
        squash = 0.0
    squash = min(2.0, max(-2.0, squash))
    return 1 + squash * .22, 1 - squash * .28


def mass(f):
    """Relative mass grows with body area; optional per-body override is bounded."""
    value = getattr(f, "physics_mass", (f.sc / .68) ** 2)
    return min(8., max(.35, value)) if math.isfinite(value) else 1.


def impulse(f, ix, iy):
    weight = mass(f)
    limit = 2200 * max(.4, f.K())
    f.vx = min(limit, max(-limit, f.vx + ix / weight))
    f.vy = min(limit, max(-limit, f.vy + iy / weight))


def reflect(vx, vy, nx, ny, restitution=.3, friction=.1):
    """Resolve incoming normal velocity, retaining bounded tangential slip."""
    length = math.hypot(nx, ny)
    if length < 1e-12:
        return vx, vy
    nx, ny = nx / length, ny / length
    normal = vx * nx + vy * ny
    if normal >= 0:
        return vx, vy
    slide = 1 - min(1., max(0., friction))
    bounce = -normal * min(.98, max(0., restitution))
    return ((vx - normal * nx) * slide + bounce * nx,
            (vy - normal * ny) * slide + bounce * ny)


def segment_contact(x0, y0, x1, y1, left, top, right, bottom):
    """Slab sweep returning first contact time and outward unit normal.

    Outward travel from a boundary is a separation, not another collision.
    For an embedded start use the nearest face so overlap can be resolved.
    """
    dx, dy = x1 - x0, y1 - y0
    if left > right or top > bottom:
        return None
    enter, leave, normal = -float("inf"), 1., (0., 0.)
    for start, delta, low, high, axis in ((x0, dx, left, right, 0),
                                          (y0, dy, top, bottom, 1)):
        if abs(delta) < 1e-12:
            if start < low or start > high:
                return None
            continue
        a, b = (low - start) / delta, (high - start) / delta
        sign = -1. if delta > 0 else 1.
        if a > b:
            a, b = b, a
        if abs(a - enter) < 1e-10:
            normal = (normal[0] + (sign if axis == 0 else 0.),
                      normal[1] + (sign if axis == 1 else 0.))
        elif a > enter:
            enter = a
            normal = (sign, 0.) if axis == 0 else (0., sign)
        leave = min(leave, b)
        if enter > leave:
            return None
    if leave < 0 or enter > 1:
        return None
    if enter < 0:
        faces = ((abs(x0 - left), -1., 0.), (abs(right - x0), 1., 0.),
                 (abs(y0 - top), 0., -1.), (abs(bottom - y0), 0., 1.))
        distance, nx, ny = min(faces)
        if dx * nx + dy * ny >= 0:
            return None
        return 0., nx, ny
    length = math.hypot(*normal)
    return max(0., enter), normal[0] / max(length, 1.), normal[1] / max(length, 1.)


class CursorHistory:
    """A 100ms velocity fit makes release independent of the last mouse poll."""
    def __init__(self):
        self.samples = []

    def add(self, x, y, when):
        if not all(math.isfinite(v) for v in (x, y, when)):
            return
        if self.samples and when < self.samples[-1][0]:
            self.samples.clear()
        if self.samples and when == self.samples[-1][0]:
            self.samples[-1] = (when, x, y)
        else:
            self.samples.append((when, x, y))
        self.samples = [s for s in self.samples[-16:] if when - s[0] <= .10]

    def velocity(self):
        if len(self.samples) < 2:
            return None
        n = len(self.samples)
        t = sum(s[0] for s in self.samples) / n
        variance = sum((s[0] - t) ** 2 for s in self.samples)
        if variance < 1e-8:
            return None
        return tuple(sum((s[0] - t) * s[axis] for s in self.samples) / variance
                     for axis in (1, 2))
