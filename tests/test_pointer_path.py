"""How the pointer travels: bowed, eased, and exactly on target."""

from __future__ import annotations

import itertools
import math
import random
from typing import Any

import pytest

from human_input_automation.core.actions import MouseClick, MouseMove
from human_input_automation.core.engine import AutomationEngine
from human_input_automation.core.errors import ValidationError
from human_input_automation.core.events import RunStatus
from human_input_automation.core.plan import AutomationPlan, RunOptions
from human_input_automation.core.pointer_path import (
    REFERENCE_DISTANCE_PX,
    PathPoint,
    PointerStyle,
    deviation_px,
    movement_duration_ms,
    plan_pointer_path,
)
from human_input_automation.core.timing import TimingProfile, TimingService

from .fakes import FakeClock, FakeKeyboard, FakeMouse, FakeWindows, make_target

START, END = (100, 100), (900, 500)
DISTANCE = math.dist(START, END)


def path_for(seed: int = 7, duration_ms: float = 400, **style: Any) -> tuple[PathPoint, ...]:
    return plan_pointer_path(
        START, END, duration_ms=duration_ms, style=PointerStyle(**style), rng=random.Random(seed)
    )


def speeds(path: tuple[PathPoint, ...], start: tuple[int, int] = START) -> list[float]:
    points = [PathPoint(start[0], start[1], 0.0), *path]
    return [
        math.dist((a.x, a.y), (b.x, b.y)) / max(b.at_ms - a.at_ms, 1e-9)
        for a, b in itertools.pairwise(points)
    ]


# ---------------------------------------------------------------------------
# The two guarantees
# ---------------------------------------------------------------------------


def test_the_path_always_ends_exactly_on_the_target() -> None:
    """Wandering is for the journey. The destination is not negotiable."""
    for seed in range(200):
        path = path_for(seed)
        assert (path[-1].x, path[-1].y) == END, f"seed {seed}"


def test_time_only_moves_forwards_and_ends_when_it_was_asked_to() -> None:
    for seed in range(100):
        path = path_for(seed, duration_ms=250)
        times = [point.at_ms for point in path]
        assert times == sorted(times), f"seed {seed}"
        assert times[0] >= 0
        assert times[-1] == pytest.approx(250)


def test_the_same_seed_gives_the_same_path() -> None:
    assert path_for(11) == path_for(11)
    assert path_for(11) != path_for(12)


# ---------------------------------------------------------------------------
# What makes it a hand rather than a machine
# ---------------------------------------------------------------------------


def test_the_path_is_not_a_straight_line() -> None:
    """The whole point: an arm pivots, so the pointer arcs."""
    bows = [deviation_px(path_for(seed), START) for seed in range(50)]

    assert min(bows) > 2, "every path should bend at least a little"
    # A hand's arc, not a detour: a few percent of the distance travelled.
    assert max(bows) < DISTANCE * 0.25


def test_the_bow_goes_one_way_for_the_whole_movement() -> None:
    """A hand curves; it does not weave. The deviation keeps its sign."""
    path = path_for(3)
    unit = ((END[0] - START[0]) / DISTANCE, (END[1] - START[1]) / DISTANCE)
    sides = [
        -unit[1] * (point.x - START[0]) + unit[0] * (point.y - START[1]) for point in path
    ]
    significant = [side for side in sides if abs(side) > 2]
    assert significant
    assert all(side > 0 for side in significant) or all(side < 0 for side in significant)


def test_the_speed_is_a_bell_not_a_rectangle() -> None:
    """Almost all the distance is covered in the middle of the movement."""
    measured = speeds(path_for(5))
    middle = measured[len(measured) // 2]

    assert middle > measured[0] * 5
    assert middle > measured[-1] * 5
    # And it is one smooth push, not a series of jerks.
    assert measured.index(max(measured)) == pytest.approx(len(measured) / 2, abs=len(measured) / 4)


def test_a_straight_machine_movement_is_still_available() -> None:
    direct = plan_pointer_path(START, END, duration_ms=400, style=PointerStyle.direct())

    assert deviation_px(direct, START) < 1.5  # rounding only
    measured = speeds(direct)
    assert max(measured) == pytest.approx(min(measured), rel=0.2)  # constant speed
    assert PointerStyle.direct().is_direct
    assert not PointerStyle().is_direct


# ---------------------------------------------------------------------------
# Overshoot
# ---------------------------------------------------------------------------


def test_an_overshoot_goes_past_the_target_and_comes_back() -> None:
    path = plan_pointer_path(
        (0, 0), (500, 0), duration_ms=400, style=PointerStyle(overshoot_rate=1.0),
        rng=random.Random(3),
    )

    assert max(point.x for point in path) > 500, "it should go past"
    assert (path[-1].x, path[-1].y) == (500, 0), "and still land on the target"


def test_nothing_goes_past_the_target_when_overshoot_is_off() -> None:
    for seed in range(50):
        path = plan_pointer_path(
            (0, 0), (500, 0), duration_ms=400,
            style=PointerStyle(overshoot_rate=0.0), rng=random.Random(seed),
        )
        assert max(point.x for point in path) <= 500, f"seed {seed}"


# ---------------------------------------------------------------------------
# How long a reach takes
# ---------------------------------------------------------------------------


def test_a_longer_reach_takes_longer_but_not_proportionally() -> None:
    """Fitts's law: time grows with the logarithm of the distance."""
    style = PointerStyle()
    short = movement_duration_ms(20, 200, style)
    normal = movement_duration_ms(REFERENCE_DISTANCE_PX, 200, style)
    far = movement_duration_ms(2000, 200, style)

    assert short < normal < far
    assert normal == pytest.approx(200)
    assert far < short * 4, "crossing the desktop is not ten times a short hop"


def test_distance_scaling_can_be_switched_off() -> None:
    style = PointerStyle(scale_with_distance=False)
    assert movement_duration_ms(2000, 200, style) == 200


def test_an_explicit_duration_on_the_action_is_used_verbatim() -> None:
    timing = TimingService(TimingProfile(), seed=1)
    assert timing.mouse_move_duration_ms(120, distance_from=(0, 0), to=(2000, 2000)) == 120


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


def test_a_movement_to_where_the_pointer_already_is_is_one_point() -> None:
    path = plan_pointer_path((5, 5), (5, 5), duration_ms=200)
    assert path == (PathPoint(5, 5, 200),)


def test_an_instant_movement_is_a_single_jump() -> None:
    path = plan_pointer_path(START, END, duration_ms=0)
    assert path == (PathPoint(END[0], END[1], 0.0),)


def test_every_coordinate_is_a_whole_pixel() -> None:
    for point in path_for(2):
        assert isinstance(point.x, int) and isinstance(point.y, int)


@pytest.mark.parametrize(
    "changes",
    [
        {"bow": -0.1},
        {"tremor_px": -1.0},
        {"overshoot_rate": 1.5},
        {"correction_share": 1.0},
        {"step_ms": 0},
    ],
)
def test_impossible_settings_are_rejected(changes: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        PointerStyle(**changes)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Through the engine
# ---------------------------------------------------------------------------


def run_with(*actions: object, **plan: object) -> FakeMouse:
    mouse = FakeMouse()
    engine = AutomationEngine(
        keyboard=FakeKeyboard(), mouse=mouse, windows=FakeWindows(), clock=FakeClock()
    )
    report = engine.run(
        AutomationPlan(
            make_target(),
            list(actions),  # type: ignore[arg-type]
            options=RunOptions(seed=5),
            **plan,  # type: ignore[arg-type]
        )
    )
    assert report.status is RunStatus.COMPLETED, report.error
    return mouse


def test_a_run_moves_the_pointer_along_a_curved_path() -> None:
    mouse = run_with(MouseMove(x=900, y=500, duration_ms=300))

    path = mouse.paths[0]
    assert len(path) > 10
    assert path[-1] == (900, 500)
    points = tuple(PathPoint(x, y, 0.0) for x, y in path)
    assert deviation_px(points, (0, 0)) > 2


def test_a_click_at_a_position_travels_there_the_same_way() -> None:
    mouse = run_with(MouseClick(x=400, y=300))

    assert mouse.paths and mouse.paths[0][-1] == (400, 300)
    assert mouse.names[:2] == ["follow_path", "button_down"]


def test_a_plan_can_ask_for_machine_straight_movement() -> None:
    mouse = run_with(MouseMove(x=900, y=500, duration_ms=300), pointer=PointerStyle.direct())

    points = tuple(PathPoint(x, y, 0.0) for x, y in mouse.paths[0])
    assert deviation_px(points, (0, 0)) < 1.5
