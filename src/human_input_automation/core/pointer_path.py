"""How the pointer travels from one point to another.

A straight line at a constant speed is the one thing a hand never produces. An
arm swinging a mouse bends, because the wrist and elbow rotate about their own
centres rather than along the line to the target; it accelerates hard, coasts,
and brakes into the target; it sometimes goes past and comes back; and it never
holds perfectly still on the way.

Reproducing that is the whole job of this module. It plans a **timed path** -
where the pointer should be and when - as a pure function of the endpoints, a
:class:`PointerStyle` and a seeded generator. The adapter that owns the real
pointer does nothing but replay it, so the interesting part is testable without
a desktop and reproducible from a seed.

Two properties hold whatever the style says, and both are tested:

* **the path ends exactly on the target.** Wandering is for the journey; the
  destination is not negotiable, in the same way a typing mistake is always
  corrected before the text is done;
* **time only moves forwards**, and the last point lands at the requested
  duration, so a movement still takes as long as it was asked to.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from .errors import ValidationError, ValidationIssue

#: Distance, in pixels, at which the distance scaling factor is exactly 1. A
#: movement of about this length is the "normal hop" the timing profile's
#: duration describes.
REFERENCE_DISTANCE_PX = 200.0

#: One position update. Eight milliseconds is ~120 Hz: finer than a 60 Hz
#: screen can show, and the upper bound on how long a stop can be delayed by a
#: movement already in flight.
DEFAULT_STEP_MS = 8.0


@dataclass(frozen=True)
class PathPoint:
    """Where the pointer should be, and how long after the start."""

    x: int
    y: int
    at_ms: float


@dataclass(frozen=True)
class PointerStyle:
    """How much the pointer behaves like a hand rather than a teleport."""

    #: How far the path bows away from the straight line, as a fraction of the
    #: distance travelled. A hand's arc, not a detour: 0.09 of a 600 px move is
    #: about 54 px at its widest.
    bow: float = 0.09
    bow_jitter: float = 0.05
    #: Small deviations along the way, tapering to nothing at both ends so the
    #: start and the target are still exact.
    tremor_px: float = 1.0
    #: How often the hand goes past the target and comes back.
    overshoot_rate: float = 0.2
    #: How far past, as a fraction of the distance.
    overshoot_fraction: float = 0.04
    #: The share of the movement spent correcting an overshoot.
    correction_share: float = 0.25
    #: Whether a longer movement takes longer, as Fitts's law says it does.
    scale_with_distance: bool = True
    #: How often a position is written while moving.
    step_ms: float = DEFAULT_STEP_MS

    def __post_init__(self) -> None:
        issues: list[ValidationIssue] = []
        for name in ("bow", "bow_jitter", "tremor_px", "overshoot_fraction"):
            if float(getattr(self, name)) < 0:
                issues.append(
                    ValidationIssue(
                        "pointer.negative",
                        f"{name} must be >= 0, got {getattr(self, name)}",
                        "pointer",
                    )
                )
        if not 0.0 <= self.overshoot_rate <= 1.0:
            issues.append(
                ValidationIssue(
                    "pointer.rate",
                    f"overshoot_rate must be between 0 and 1, got {self.overshoot_rate}",
                    "pointer",
                )
            )
        if not 0.0 <= self.correction_share < 1.0:
            issues.append(
                ValidationIssue(
                    "pointer.correction_share",
                    f"correction_share must be between 0 and 1, got {self.correction_share}",
                    "pointer",
                )
            )
        if self.step_ms <= 0:
            issues.append(
                ValidationIssue(
                    "pointer.step", f"step_ms must be > 0, got {self.step_ms}", "pointer"
                )
            )
        if issues:
            raise ValidationError(issues)

    @classmethod
    def direct(cls) -> PointerStyle:
        """A straight line at a constant speed - a machine's movement."""
        return cls(
            bow=0.0,
            bow_jitter=0.0,
            tremor_px=0.0,
            overshoot_rate=0.0,
            scale_with_distance=False,
        )

    @property
    def is_direct(self) -> bool:
        """True when nothing here bends, wobbles or overshoots."""
        return (
            self.bow <= 0
            and self.bow_jitter <= 0
            and self.tremor_px <= 0
            and self.overshoot_rate <= 0
        )

    def with_changes(self, **changes: object) -> PointerStyle:
        return replace(self, **changes)  # type: ignore[arg-type]


def movement_duration_ms(distance_px: float, base_ms: float, style: PointerStyle) -> float:
    """How long a movement of ``distance_px`` should take.

    Fitts's law in its usable form: time grows with the logarithm of the
    distance, not linearly, so crossing a whole desktop takes roughly twice as
    long as a short hop rather than ten times. ``base_ms`` describes a hop of
    :data:`REFERENCE_DISTANCE_PX`, and everything is measured against that.
    """
    if not style.scale_with_distance or base_ms <= 0:
        return max(0.0, base_ms)
    difficulty = math.log2(2 + max(0.0, distance_px) / REFERENCE_DISTANCE_PX)
    return base_ms * difficulty / math.log2(3)


def plan_pointer_path(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    duration_ms: float,
    style: PointerStyle | None = None,
    rng: random.Random | None = None,
) -> tuple[PathPoint, ...]:
    """The timed path the pointer should follow from ``start`` to ``end``."""
    style = style or PointerStyle()
    generator = rng or random.Random()
    distance = math.dist(start, end)

    if distance == 0 or duration_ms <= 0:
        return (PathPoint(end[0], end[1], max(0.0, duration_ms)),)
    if style.is_direct:
        return _straight(start, end, duration_ms, style)
    return _natural(start, end, duration_ms, style, generator, distance)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


def _straight(
    start: tuple[int, int], end: tuple[int, int], duration_ms: float, style: PointerStyle
) -> tuple[PathPoint, ...]:
    steps = _step_count(duration_ms, style)
    return tuple(
        PathPoint(
            round(start[0] + (end[0] - start[0]) * step / steps),
            round(start[1] + (end[1] - start[1]) * step / steps),
            duration_ms * step / steps,
        )
        for step in range(1, steps + 1)
    )


def _natural(
    start: tuple[int, int],
    end: tuple[int, int],
    duration_ms: float,
    style: PointerStyle,
    rng: random.Random,
    distance: float,
) -> tuple[PathPoint, ...]:
    """A bowed, eased, occasionally overshooting reach."""
    overshoots = rng.random() < style.overshoot_rate
    aim = end
    if overshoots:
        # Past the target, along the line of travel: the hand was going too
        # fast to stop on it.
        extra = distance * style.overshoot_fraction
        aim = (
            round(end[0] + (end[0] - start[0]) / distance * extra),
            round(end[1] + (end[1] - start[1]) / distance * extra),
        )

    reach_ms = duration_ms * (1 - style.correction_share) if overshoots else duration_ms
    points = list(
        _reach(start, aim, reach_ms, 0.0, style, rng, distance, tremor=True)
    )
    if overshoots:
        # The correction is a small, deliberate move: no bow of its own, and
        # slower, which is what makes an overshoot read as one.
        points.extend(
            _reach(
                aim,
                end,
                duration_ms - reach_ms,
                reach_ms,
                style.with_changes(bow=0.0, bow_jitter=0.0, tremor_px=0.0),
                rng,
                math.dist(aim, end),
                tremor=False,
            )
        )
    return tuple(points)


def _reach(
    start: tuple[int, int],
    end: tuple[int, int],
    duration_ms: float,
    offset_ms: float,
    style: PointerStyle,
    rng: random.Random,
    distance: float,
    *,
    tremor: bool,
) -> list[PathPoint]:
    """One continuous movement: a bezier bow, walked with an eased speed."""
    if duration_ms <= 0 or distance == 0:
        return [PathPoint(end[0], end[1], offset_ms + max(0.0, duration_ms))]

    steps = _step_count(duration_ms, style)
    # Perpendicular to the direction of travel, so the bow is across the line
    # rather than along it. One sign for the whole movement: a hand curves, it
    # does not weave.
    unit_x, unit_y = (end[0] - start[0]) / distance, (end[1] - start[1]) / distance
    normal = (-unit_y, unit_x)
    bow = (style.bow + rng.uniform(-style.bow_jitter, style.bow_jitter)) * distance
    bow *= rng.choice((-1.0, 1.0))
    #: The two control points sit a third and two thirds along, pushed aside by
    #: the bow, which is what gives a cubic bezier its arc.
    controls = [
        (
            start[0] + unit_x * distance * share + normal[0] * bow * weight,
            start[1] + unit_y * distance * share + normal[1] * bow * weight,
        )
        for share, weight in ((1 / 3, 0.9), (2 / 3, 0.6))
    ]
    phase = rng.uniform(0, math.tau)
    wobbles = rng.uniform(1.5, 3.0)

    points: list[PathPoint] = []
    for step in range(1, steps + 1):
        fraction = step / steps
        travelled = _eased(fraction)
        x, y = _bezier(start, controls[0], controls[1], end, travelled)
        if tremor and style.tremor_px > 0:
            # Tapered to nothing at both ends, so the pointer still leaves from
            # and lands on exactly the right pixel.
            taper = math.sin(math.pi * fraction)
            shake = math.sin(phase + fraction * math.tau * wobbles) * style.tremor_px * taper
            x += normal[0] * shake
            y += normal[1] * shake
        points.append(PathPoint(round(x), round(y), offset_ms + duration_ms * fraction))

    points[-1] = PathPoint(end[0], end[1], offset_ms + duration_ms)
    return points


def _eased(fraction: float) -> float:
    """Minimum-jerk easing: still, fast, still.

    The velocity profile of a human reach is a bell, not a rectangle - almost
    all of the distance is covered in the middle of the movement. This is the
    standard smoothstep for it.
    """
    return fraction**3 * (fraction * (fraction * 6 - 15) + 10)


def _bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[int, int],
    t: float,
) -> tuple[float, float]:
    inverse = 1 - t
    a, b, c, d = inverse**3, 3 * inverse**2 * t, 3 * inverse * t**2, t**3
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def _step_count(duration_ms: float, style: PointerStyle) -> int:
    return max(2, int(duration_ms / style.step_ms))


def deviation_px(path: tuple[PathPoint, ...], start: tuple[int, int]) -> float:
    """How far the path strays from the straight line. Used by the tests."""
    if not path:
        return 0.0
    end = (path[-1].x, path[-1].y)
    distance = math.dist(start, end)
    if distance == 0:
        return 0.0
    ux, uy = (end[0] - start[0]) / distance, (end[1] - start[1]) / distance
    return max(
        abs(-uy * (point.x - start[0]) + ux * (point.y - start[1])) for point in path
    )


__all__ = [
    "DEFAULT_STEP_MS",
    "REFERENCE_DISTANCE_PX",
    "PathPoint",
    "PointerStyle",
    "deviation_px",
    "movement_duration_ms",
    "plan_pointer_path",
]
