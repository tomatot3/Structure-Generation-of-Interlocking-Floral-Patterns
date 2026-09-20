#!/usr/bin/env python3
"""Stage 5C flower placement on the active dynamic BranchUnit chain.

Only SW-3 owns a variable flower-placement domain.  A seeded low-dimensional
composition intent is expressed in backbone-local coordinates, then projected
along one continuous ray until the *formal* flower-mount solver can construct
the complete joint tuple (flower reserves, support roots, support paths).
SW-1 and SW-2 pass through unchanged.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from flower_mounting_v1 import (
    FlowerMountingError,
    build_flower_mount_plan,
    validate_flower_mount_plan,
)
from prototype_analysis import analyze_prototype
from prototype_strategy_v1 import validate_strategy_projection
from strict_p0_v2 import FlowerReserve, StrictP0V2


Point = tuple[float, float]
UINT32_MAX = 2**32 - 1
SCHEMA = "dynamic_branch_flower_placement_plan_v1"
SW3_FAMILY = "SW-3_tangent_terminal"


class FlowerPlacementError(RuntimeError):
    """No feasible placement exists on the requested structural intent ray."""


@dataclass(frozen=True)
class _Anchor:
    flower: FlowerReserve
    s: float
    point: Point
    tangent: Point
    normal: Point
    tangent_offset: float
    normal_offset: float
    center_distance: float


def _validate_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise FlowerPlacementError("flower_seed must be an integer")
    if not 0 <= seed <= UINT32_MAX:
        raise FlowerPlacementError(
            f"flower_seed must lie in [0, {UINT32_MAX}]"
        )
    return seed


def production_flower_rho(flower_seed: int) -> float:
    seed = _validate_seed(flower_seed)
    digest = hashlib.sha256(f"{seed}:flower_rho:v1".encode("utf-8")).digest()
    unit = int.from_bytes(digest[:8], "big") / float(2**64)
    # Production stays inside the portion of the SW-3 domain that retained
    # enough residual capacity in the complete L1/BranchUnit review.  Explicit
    # rho=1 remains available for domain-boundary experiments.
    return 0.45 + 0.25 * unit


def _add(first: Point, second: Point) -> Point:
    return first[0] + second[0], first[1] + second[1]


def _sub(first: Point, second: Point) -> Point:
    return first[0] - second[0], first[1] - second[1]


def _mul(point: Point, scalar: float) -> Point:
    return point[0] * scalar, point[1] * scalar


def _dot(first: Point, second: Point) -> float:
    return first[0] * second[0] + first[1] * second[1]


def _length(point: Point) -> float:
    return math.hypot(point[0], point[1])


def _unit(point: Point) -> Point:
    length = _length(point)
    if length <= 1e-12:
        return 1.0, 0.0
    return point[0] / length, point[1] / length


def _canonical_x(x: float) -> float:
    result = x % 1.0
    return 0.0 if abs(result - 1.0) <= 1e-12 else result


def _periodic_near(point: Point, reference_x: float) -> Point:
    return min(
        ((point[0] + offset, point[1]) for offset in (-1.0, 0.0, 1.0)),
        key=lambda candidate: abs(candidate[0] - reference_x),
    )


def _periodic_delta(value: float) -> float:
    return (value + 0.5) % 1.0 - 0.5


def _unique_samples(strict_p0: StrictP0V2) -> list[Any]:
    rows = list(strict_p0.backbone_samples)
    if len(rows) >= 2 and abs(rows[-1].s - 1.0) <= 1e-9:
        rows = rows[:-1]
    if len(rows) < 3:
        raise FlowerPlacementError("flower placement requires a periodic backbone")
    return rows


def _arc_length(strict_p0: StrictP0V2) -> float:
    rows = _unique_samples(strict_p0)
    total = 0.0
    for index, row in enumerate(rows):
        next_row = rows[(index + 1) % len(rows)]
        next_point = next_row.point
        if index == len(rows) - 1:
            next_point = (next_point[0] + 1.0, next_point[1])
        total += _length(_sub(next_point, row.point))
    return max(total, 1e-9)


def _frame_at_s(strict_p0: StrictP0V2, s: float) -> tuple[Point, Point, Point]:
    rows = _unique_samples(strict_p0)
    normalized = s % 1.0
    position = normalized * len(rows)
    index = int(math.floor(position)) % len(rows)
    fraction = position - math.floor(position)
    first = rows[index]
    second = rows[(index + 1) % len(rows)]
    second_point = second.point
    if index == len(rows) - 1:
        second_point = (second_point[0] + 1.0, second_point[1])
    point = _add(first.point, _mul(_sub(second_point, first.point), fraction))
    tangent = _unit(
        _add(first.tangent, _mul(_sub(second.tangent, first.tangent), fraction))
    )
    normal = (-tangent[1], tangent[0])
    return point, tangent, normal


def _anchor(strict_p0: StrictP0V2, flower: FlowerReserve) -> _Anchor:
    best: tuple[float, float, Point] | None = None
    for sample in _unique_samples(strict_p0):
        point = _periodic_near(sample.point, flower.center[0])
        distance = _length(_sub(flower.center, point))
        if best is None or distance < best[0]:
            best = distance, float(sample.s), point
    if best is None:
        raise FlowerPlacementError(f"cannot anchor flower {flower.flower_id}")
    point, tangent, normal = _frame_at_s(strict_p0, best[1])
    point = _periodic_near(point, flower.center[0])
    offset = _sub(flower.center, point)
    return _Anchor(
        flower=flower,
        s=best[1],
        point=point,
        tangent=tangent,
        normal=normal,
        tangent_offset=_dot(offset, tangent),
        normal_offset=_dot(offset, normal),
        center_distance=_length(offset),
    )


def _state(seed: int, prototype_id: str, names: Sequence[str]) -> dict[str, float]:
    digest = hashlib.sha256(
        f"{seed}:{prototype_id}:flower_layout_state:v1".encode("utf-8")
    ).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    values = [rng.uniform(-1.0, 1.0) for _ in names]
    maximum = max((abs(value) for value in values), default=1.0)
    if maximum <= 1e-12:
        values[0] = 1.0
        maximum = 1.0
    return {
        name: value / maximum
        for name, value in zip(names, values)
    }


def _single_centers(
    strict_p0: StrictP0V2,
    anchors: Sequence[_Anchor],
    state: Mapping[str, float],
    scale: float,
) -> list[Point]:
    anchor = anchors[0]
    anchor_budget = 0.18 * max(anchor.flower.rx, anchor.flower.ry)
    normal_budget = 0.12 * max(anchor.center_distance, anchor.flower.ry)
    tangent_budget = 0.14 * anchor.flower.rx
    base_point = _periodic_near(anchor.point, anchor.flower.center[0])
    away = _unit(_sub(anchor.flower.center, base_point))
    lateral = _unit((-away[1], away[0]))
    if _dot(lateral, anchor.tangent) < 0.0:
        lateral = _mul(lateral, -1.0)
    center = _add(
        anchor.flower.center,
        _add(
            _mul(
                anchor.tangent,
                scale * state["anchor_shift"] * anchor_budget,
            ),
            _add(
                _mul(
                    lateral,
                    scale * state["tangent_bias"] * tangent_budget,
                ),
                _mul(
                    away,
                    scale * state["normal_standoff"] * normal_budget,
                ),
            ),
        ),
    )
    return [(_canonical_x(center[0]), center[1])]


def _pair_centers(
    strict_p0: StrictP0V2,
    anchors: Sequence[_Anchor],
    state: Mapping[str, float],
    scale: float,
) -> list[Point]:
    if len(anchors) != 2:
        raise FlowerPlacementError("the paired SW-3 domain requires two flowers")
    mean_radius = sum(max(row.flower.rx, row.flower.ry) for row in anchors) / 2.0
    mean_rx = sum(row.flower.rx for row in anchors) / 2.0
    mean_ry = sum(row.flower.ry for row in anchors) / 2.0
    first_center = anchors[0].flower.center
    second_center = _periodic_near(anchors[1].flower.center, first_center[0])
    pair_vector = _sub(second_center, first_center)
    pair_distance = _length(pair_vector)
    pair_axis = _unit(pair_vector)
    stagger_axis = _unit((-pair_axis[1], pair_axis[0]))
    if stagger_axis[1] < 0.0:
        stagger_axis = _mul(stagger_axis, -1.0)
    group_axis = _unit(_add(anchors[0].tangent, anchors[1].tangent))
    group_budget = 0.16 * mean_radius
    spread_budget = 0.09 * pair_distance
    vertical_order = sorted(
        range(2),
        key=lambda index: anchors[index].flower.center[1],
    )
    stagger_sign = [0.0, 0.0]
    stagger_sign[vertical_order[0]] = -1.0
    stagger_sign[vertical_order[1]] = 1.0
    centers: list[Point] = []
    for index, anchor in enumerate(anchors):
        pair_sign = -0.5 if index == 0 else 0.5
        base_point = _periodic_near(anchor.point, anchor.flower.center[0])
        away = _unit(_sub(anchor.flower.center, base_point))
        center = _add(
            anchor.flower.center,
            _add(
                _add(
                    _mul(
                        group_axis,
                        scale * state["group_shift"] * group_budget,
                    ),
                    _mul(
                        pair_axis,
                        scale
                        * pair_sign
                        * state["pair_spread"]
                        * spread_budget,
                    ),
                ),
                _add(
                    _mul(
                        away,
                        scale
                        * (
                            state["group_standoff"]
                            * 0.10
                            * max(anchor.center_distance, mean_ry)
                        ),
                    ),
                    _add(
                        _mul(
                            stagger_axis,
                            scale
                            * stagger_sign[index]
                            * state["height_stagger"]
                            * 0.12
                            * mean_ry,
                        ),
                        _mul(
                            anchor.tangent,
                            scale
                            * pair_sign
                            * state["asymmetry"]
                            * 0.16
                            * mean_rx,
                        ),
                    ),
                ),
            ),
        )
        centers.append((_canonical_x(center[0]), center[1]))
    return centers


def _strict_with_centers(
    strict_p0: StrictP0V2,
    centers: Sequence[Point],
) -> StrictP0V2:
    if len(centers) != len(strict_p0.flowers):
        raise FlowerPlacementError("flower center count mismatch")
    flowers = tuple(
        FlowerReserve(
            flower_id=flower.flower_id,
            center=(float(center[0]), float(center[1])),
            rx=flower.rx,
            ry=flower.ry,
        )
        for flower, center in zip(strict_p0.flowers, centers)
    )
    return StrictP0V2(
        prototype_id=strict_p0.prototype_id,
        frame=strict_p0.frame,
        backbone_samples=strict_p0.backbone_samples,
        flowers=flowers,
        structure_protection_zones=strict_p0.structure_protection_zones,
    )


def _pair_clearance(flowers: Sequence[FlowerReserve]) -> float:
    if len(flowers) < 2:
        return math.inf
    minimum = math.inf
    for first_index, first in enumerate(flowers):
        for second in flowers[first_index + 1 :]:
            dx = _periodic_delta(second.center[0] - first.center[0])
            dy = second.center[1] - first.center[1]
            value = math.hypot(
                dx / max(first.rx + second.rx, 1e-9),
                dy / max(first.ry + second.ry, 1e-9),
            )
            minimum = min(minimum, value)
    return minimum


def _center_shift(base: Point, final: Point) -> float:
    return math.hypot(_periodic_delta(final[0] - base[0]), final[1] - base[1])


def _candidate(
    strict_p0: StrictP0V2,
    centers: Sequence[Point],
    baseline_anchors: Sequence[_Anchor],
    morphology: Mapping[str, Any],
    stage3_contract: Mapping[str, Any],
    flower_seed: int,
    prototype_strategy: Mapping[str, Any],
) -> tuple[StrictP0V2, dict[str, Any], dict[str, Any]]:
    trial = _strict_with_centers(strict_p0, centers)
    lower = float(trial.frame.local_canvas_bounds[1])
    upper = float(trial.frame.local_canvas_bounds[3])
    for flower in trial.flowers:
        if flower.center[1] - flower.ry < lower or flower.center[1] + flower.ry > upper:
            raise FlowerPlacementError(
                f"flower reserve leaves canvas: {flower.flower_id}"
            )
    if _pair_clearance(trial.flowers) < 1.05:
        raise FlowerPlacementError("paired flower reserves lose breathing space")
    analysis = analyze_prototype(trial)
    for relation, anchor in zip(analysis["flowers"], baseline_anchors):
        if float(relation["center_distance"]) < 0.70 * anchor.center_distance:
            raise FlowerPlacementError(
                f"flower collapses toward backbone: {anchor.flower.flower_id}"
            )
    mount_plan = build_flower_mount_plan(
        analysis,
        morphology,
        stage3_contract,
        seed=flower_seed,
        prototype_strategy=prototype_strategy,
    )
    validate_flower_mount_plan(
        mount_plan,
        analysis,
        morphology,
        prototype_strategy=prototype_strategy,
    )
    minimum_reach = float(
        stage3_contract["initial_layout_constraints"]
        ["sw3_remote_terminal_support"]
        ["minimum_root_to_flower_boundary_reach"]
    )
    if any(
        float(mount["geometry"]["root_to_contact_chord"]) < minimum_reach
        for mount in mount_plan["mounts"]
    ):
        raise FlowerPlacementError("flower support reach falls below the contract")
    return trial, analysis, mount_plan


def generate_flower_layout_and_mount(
    backbone_strict: StrictP0V2,
    morphology: Mapping[str, Any],
    stage3_contract: Mapping[str, Any],
    *,
    flower_seed: int,
    prototype_strategy: Mapping[str, Any],
    rho: float | None = None,
    projection_ceiling: float = 1.0,
) -> tuple[StrictP0V2, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Generate the formal post-backbone flower state and its frozen mounts."""

    seed = _validate_seed(flower_seed)
    validate_strategy_projection(
        prototype_strategy,
        prototype_id=backbone_strict.prototype_id,
        flower_count=len(backbone_strict.flowers),
    )
    policy = prototype_strategy["flower_layout"]
    mode = str(policy["mode"])
    baseline_centers = [flower.center for flower in backbone_strict.flowers]
    if mode == "fixed_prototype_relation":
        analysis = analyze_prototype(backbone_strict)
        mounts = build_flower_mount_plan(
            analysis,
            morphology,
            stage3_contract,
            seed=seed,
            prototype_strategy=prototype_strategy,
        )
        validate_flower_mount_plan(
            mounts,
            analysis,
            morphology,
            prototype_strategy=prototype_strategy,
        )
        plan = {
            "schema": SCHEMA,
            "prototype_id": backbone_strict.prototype_id,
            "flower_seed": seed,
            "mode": mode,
            "state_names": [],
            "intent_state": {},
            "requested_rho": 0.0,
            "selected_projection_scale": 0.0,
            "projection_retention": 1.0,
            "baseline_centers": [list(value) for value in baseline_centers],
            "final_centers": [list(value) for value in baseline_centers],
            "center_shift_distances": [0.0 for _ in baseline_centers],
            "joint_domain": {
                "coordinate_system": "fixed_prototype_relation",
                "formal_feasibility_consumers": [
                    "prototype_analysis",
                    "flower_mount_plan",
                ],
            },
        }
        return backbone_strict, analysis, plan, mounts
    if mode not in {"sw3_single_joint_domain", "sw3_pair_joint_domain"}:
        raise FlowerPlacementError(f"unsupported flower layout mode: {mode}")
    if str(prototype_strategy["family_id"]) != SW3_FAMILY:
        raise FlowerPlacementError("only SW-3 may use a variable flower domain")

    strength = production_flower_rho(seed) if rho is None else float(rho)
    if not math.isfinite(strength) or not 0.0 <= strength <= 1.0:
        raise FlowerPlacementError("flower rho must lie in [0, 1]")
    ceiling = float(projection_ceiling)
    if not math.isfinite(ceiling) or not 0.0 <= ceiling <= 1.0:
        raise FlowerPlacementError("projection ceiling must lie in [0, 1]")
    anchors = [_anchor(backbone_strict, flower) for flower in backbone_strict.flowers]
    if mode == "sw3_single_joint_domain":
        names = ("anchor_shift", "normal_standoff", "tangent_bias")
        if len(anchors) != 1:
            raise FlowerPlacementError("single SW-3 layout requires one flower")
        center_fn = _single_centers
    else:
        names = (
            "group_shift",
            "pair_spread",
            "height_stagger",
            "group_standoff",
            "asymmetry",
        )
        if len(anchors) != 2:
            raise FlowerPlacementError("paired SW-3 layout requires two flowers")
        center_fn = _pair_centers
    intent = _state(seed, backbone_strict.prototype_id, names)
    requested_state = {name: strength * value for name, value in intent.items()}

    # This is projection of one seeded continuous intent, not best-of-N sampling.
    projection_scales = [
        round(ceiling - index / 10.0, 10)
        for index in range(int(math.floor(ceiling * 10.0 + 1e-9)) + 1)
    ]
    if not projection_scales or projection_scales[-1] > 0.0:
        projection_scales.append(0.0)
    rejection_rows: list[dict[str, Any]] = []
    selected: tuple[StrictP0V2, dict[str, Any], dict[str, Any]] | None = None
    selected_scale = 0.0
    raw_centers = center_fn(backbone_strict, anchors, requested_state, 1.0)
    for projection_scale in projection_scales:
        centers = center_fn(
            backbone_strict,
            anchors,
            requested_state,
            projection_scale,
        )
        try:
            selected = _candidate(
                backbone_strict,
                centers,
                anchors,
                morphology,
                stage3_contract,
                seed,
                prototype_strategy,
            )
        except (FlowerPlacementError, FlowerMountingError) as exc:
            rejection_rows.append(
                {
                    "projection_scale": round(projection_scale, 3),
                    "reason": str(exc),
                }
            )
            continue
        selected_scale = projection_scale
        break
    if selected is None:
        raise FlowerPlacementError(
            f"no feasible projection for {backbone_strict.prototype_id}"
        )
    final_strict, final_analysis, mount_plan = selected
    final_centers = [flower.center for flower in final_strict.flowers]
    raw_shift = sum(
        _center_shift(base, raw)
        for base, raw in zip(baseline_centers, raw_centers)
    )
    final_shift = sum(
        _center_shift(base, final)
        for base, final in zip(baseline_centers, final_centers)
    )
    retention = 1.0 if raw_shift <= 1e-12 else final_shift / raw_shift
    plan = {
        "schema": SCHEMA,
        "prototype_id": backbone_strict.prototype_id,
        "flower_seed": seed,
        "mode": mode,
        "state_names": list(names),
        "intent_state": {name: round(value, 9) for name, value in requested_state.items()},
        "requested_rho": round(strength, 9),
        "selected_projection_scale": round(selected_scale, 3),
        "projection_retention": round(retention, 9),
        "baseline_centers": [
            [round(value[0], 12), round(value[1], 12)]
            for value in baseline_centers
        ],
        "raw_intent_centers": [
            [round(value[0], 12), round(value[1], 12)]
            for value in raw_centers
        ],
        "final_centers": [
            [round(value[0], 12), round(value[1], 12)]
            for value in final_centers
        ],
        "center_shift_distances": [
            round(_center_shift(base, final), 12)
            for base, final in zip(baseline_centers, final_centers)
        ],
        "joint_domain": {
            "coordinate_system": "current_backbone_local_frame",
            "candidate_tuple": [
                "flower_centers",
                "formal_support_roots",
                "formal_support_paths",
            ],
            "formal_feasibility_consumers": [
                "prototype_analysis",
                "flower_mount_plan",
            ],
            "projection_policy": "single_seeded_intent_ray_toward_baseline",
            "clearance_is_constraint_not_objective": True,
        },
        "rejected_projections": rejection_rows,
    }
    return final_strict, final_analysis, plan, mount_plan
