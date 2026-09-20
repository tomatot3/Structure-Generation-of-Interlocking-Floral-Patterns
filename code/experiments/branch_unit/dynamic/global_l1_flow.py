#!/usr/bin/env python3
"""Stage-3B global L1 flow-lane planner.

This module performs one seeded, forward global solve.  It does not consume the
selected layouts from the rejected stage-3/stage-4 chain, and it does not
repair, delete, retry, or resample a failed result.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from statistics import NormalDist
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from fixed_visual_prior import canonical_digest, validate_fixed_visual_prior
from composition_geometry import parallel_co_travel_score
from geometry_batch import (
    global_l1_polyline_distance_batch,
    point_segment_distance_matrix_batch,
    polyline_pair_intersects,
)
from prototype_strategy_v1 import (
    PROTOTYPE_IDS,
    validate_strategy_against_inputs,
)


SCHEMA = "dynamic_branch_global_l1_flow_plan_v1"
SCHEMA_V2 = "dynamic_branch_global_l1_flow_plan_v2"
SCHEMA_V3 = "dynamic_branch_global_l1_flow_plan_v3"
CONTRACT_SCHEMA = "dynamic_branch_stage3b_l1_flow_contract_v1"
CONTRACT_SCHEMA_V2 = "dynamic_branch_stage3b_l1_flow_contract_v2"
CONTRACT_SCHEMA_V3 = "dynamic_branch_stage3b_l1_flow_contract_v3"
FEEDBACK_SCHEMA = "dynamic_branch_edit_feedback_prior_v1"
CURVE_GEOMETRY_PRIOR_SCHEMA = "dynamic_branch_editor_curve_geometry_prior_v4"
SEEDS = (4101, 4102, 4103)
ORDINARY_DENSITY_LEVELS = ("simple", "medium", "rich")
DENSITY_CONTROL_PROFILE_SCHEMA = "visual_density_control_profile_v2"
Point = tuple[float, float]


class GlobalL1FlowError(RuntimeError):
    """The formal L1 global solve is infeasible or violates its contract."""


@dataclass(frozen=True)
class Slot:
    slot_id: str
    role: str
    index: int
    flower_id: str | None
    preferred_s: float
    preferred_vertical_side: str


@dataclass
class BeamState:
    lanes: list[dict[str, Any]]
    score: float


def _feedback_mode(contract: Mapping[str, Any]) -> bool:
    return contract.get("schema") in {CONTRACT_SCHEMA_V2, CONTRACT_SCHEMA_V3}


def _soft_density_mode(contract: Mapping[str, Any]) -> bool:
    return contract.get("schema") == CONTRACT_SCHEMA_V3


def _feedback_profile(
    feedback_prior: Mapping[str, Any],
    prototype_id: str,
    profile_key: str | None = None,
) -> dict[str, Any]:
    if feedback_prior.get("schema") != FEEDBACK_SCHEMA:
        raise GlobalL1FlowError("edit feedback prior schema mismatch")
    policy = feedback_prior.get("stage3b_policy")
    profiles = feedback_prior.get("prototype_profiles")
    if not isinstance(policy, Mapping) or not isinstance(profiles, Mapping):
        raise GlobalL1FlowError("edit feedback prior is incomplete")
    prototype = profiles.get(profile_key or prototype_id)
    if not isinstance(prototype, Mapping):
        raise GlobalL1FlowError(
            f"edit feedback prior has no profile for {prototype_id}"
        )
    return {**dict(policy), **dict(prototype)}


def _curve_geometry_profile(
    curve_geometry_prior: Mapping[str, Any],
    prototype_id: str,
    profile_key: str | None = None,
) -> Mapping[str, Any]:
    if curve_geometry_prior.get("schema") != CURVE_GEOMETRY_PRIOR_SCHEMA:
        raise GlobalL1FlowError("editor curve geometry prior schema mismatch")
    profiles = curve_geometry_prior.get("profiles")
    if not isinstance(profiles, Mapping):
        raise GlobalL1FlowError("editor curve geometry prior has no profiles")
    profile = profiles.get(profile_key or prototype_id) or profiles.get("global")
    if not isinstance(profile, Mapping):
        raise GlobalL1FlowError(
            f"editor curve geometry prior has no profile for {prototype_id}"
        )
    if int(profile.get("single_cubic_l1_count", 0)) < 5:
        raise GlobalL1FlowError("editor curve geometry profile is too small")
    if int(profile.get("paired_original_edited_cubic_count", 0)) < 5:
        raise GlobalL1FlowError(
            "editor curve geometry profile lacks paired corrections"
        )
    if int(profile.get("paired_edited_descriptor_unique_count", 0)) != int(
        profile["paired_original_edited_cubic_count"]
    ):
        raise GlobalL1FlowError(
            "editor profile does not support non-repeating corrections"
        )
    if int(profile.get("edited_exemplar_count", 0)) < 5:
        raise GlobalL1FlowError("editor curve geometry profile lacks exemplars")
    if int(profile.get("edited_exemplar_unique_descriptor_count", 0)) < 5:
        raise GlobalL1FlowError(
            "editor curve geometry profile lacks distinct edited exemplars"
        )
    pair_geometry = profile.get("composition_pair_geometry")
    if (
        int(profile.get("composition_pair_count", 0)) < 10
        or not isinstance(pair_geometry, Mapping)
        or not isinstance(
            pair_geometry.get("parallel_co_travel_score"), Mapping
        )
    ):
        raise GlobalL1FlowError(
            "editor curve geometry profile lacks composition pair evidence"
        )
    return profile


def _finite(value: object, path: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise GlobalL1FlowError(f"{path} must be finite")
    return number


def _point(value: object, path: str) -> Point:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise GlobalL1FlowError(f"{path} must be a two-number point")
    return _finite(value[0], f"{path}[0]"), _finite(value[1], f"{path}[1]")


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scalar: float) -> Point:
    return a[0] * scalar, a[1] * scalar


def _rotate(vector: Point, radians: float) -> Point:
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (
        vector[0] * cosine - vector[1] * sine,
        vector[0] * sine + vector[1] * cosine,
    )


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _length(a: Point) -> float:
    return math.hypot(a[0], a[1])


def _distance(a: Point, b: Point) -> float:
    return _length(_sub(a, b))


def _unit(vector: Point, path: str = "vector") -> Point:
    length = _length(vector)
    if length <= 1e-12:
        raise GlobalL1FlowError(f"{path} must be non-degenerate")
    return vector[0] / length, vector[1] / length


def _lerp(a: Point, b: Point, fraction: float) -> Point:
    return a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction


def _round_point(point: Point) -> list[float]:
    return [round(point[0], 9), round(point[1], 9)]


def _periodic_delta(a: float, b: float) -> float:
    delta = abs(a - b) % 1.0
    return min(delta, 1.0 - delta)


def _periodic_near_x(x: float, reference_x: float) -> float:
    return min((x - 1.0, x, x + 1.0), key=lambda candidate: abs(candidate - reference_x))


def _cubic_point(segment: Mapping[str, Sequence[float]], t: float) -> Point:
    p0 = _point(segment["p0"], "segment.p0")
    p1 = _point(segment["p1"], "segment.p1")
    p2 = _point(segment["p2"], "segment.p2")
    p3 = _point(segment["p3"], "segment.p3")
    u = 1.0 - t
    return (
        u**3 * p0[0] + 3.0 * u * u * t * p1[0] + 3.0 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3.0 * u * u * t * p1[1] + 3.0 * u * t * t * p2[1] + t**3 * p3[1],
    )


def _sample_segments(
    segments: Sequence[Mapping[str, Sequence[float]]],
    samples_per_segment: int = 18,
) -> list[Point]:
    points: list[Point] = []
    for segment_index, segment in enumerate(segments):
        start = 0 if segment_index == 0 else 1
        points.extend(
            _cubic_point(segment, index / samples_per_segment)
            for index in range(start, samples_per_segment + 1)
        )
    return points


def _segment(
    p0: Point,
    p1: Point,
    p2: Point,
    p3: Point,
) -> dict[str, list[float]]:
    return {
        "p0": _round_point(p0),
        "p1": _round_point(p1),
        "p2": _round_point(p2),
        "p3": _round_point(p3),
    }


def _hermite_segment(
    start: Point,
    end: Point,
    start_direction: Point,
    end_direction: Point,
    start_arm: float,
    end_arm: float,
) -> dict[str, list[float]]:
    d0 = _unit(start_direction, "start_direction")
    d1 = _unit(end_direction, "end_direction")
    return _segment(
        start,
        _add(start, _mul(d0, start_arm)),
        _sub(end, _mul(d1, end_arm)),
        end,
    )


def _polyline_length(points: Sequence[Point]) -> float:
    return sum(_distance(points[index - 1], points[index]) for index in range(1, len(points)))


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    vector = _sub(end, start)
    denominator = _dot(vector, vector)
    if denominator <= 1e-18:
        return _distance(point, start)
    t = max(0.0, min(1.0, _dot(_sub(point, start), vector) / denominator))
    return _distance(point, _add(start, _mul(vector, t)))


def _orientation(a: Point, b: Point, c: Point) -> float:
    return _cross(_sub(b, a), _sub(c, a))


def _segments_intersect(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    tolerance = 1e-10
    o1 = _orientation(a0, a1, b0)
    o2 = _orientation(a0, a1, b1)
    o3 = _orientation(b0, b1, a0)
    o4 = _orientation(b0, b1, a1)
    if (
        (o1 > tolerance and o2 < -tolerance or o1 < -tolerance and o2 > tolerance)
        and (o3 > tolerance and o4 < -tolerance or o3 < -tolerance and o4 > tolerance)
    ):
        return True

    def on_segment(point: Point, start: Point, end: Point) -> bool:
        return (
            min(start[0], end[0]) - tolerance
            <= point[0]
            <= max(start[0], end[0]) + tolerance
            and min(start[1], end[1]) - tolerance
            <= point[1]
            <= max(start[1], end[1]) + tolerance
        )

    return (
        (abs(o1) <= tolerance and on_segment(b0, a0, a1))
        or (abs(o2) <= tolerance and on_segment(b1, a0, a1))
        or (abs(o3) <= tolerance and on_segment(a0, b0, b1))
        or (abs(o4) <= tolerance and on_segment(a1, b0, b1))
    )


def _segment_distance(a0: Point, a1: Point, b0: Point, b1: Point) -> float:
    if _segments_intersect(a0, a1, b0, b1):
        return 0.0
    return min(
        _point_segment_distance(a0, b0, b1),
        _point_segment_distance(a1, b0, b1),
        _point_segment_distance(b0, a0, a1),
        _point_segment_distance(b1, a0, a1),
    )


def _polyline_distance(a: Sequence[Point], b: Sequence[Point], offset_b: float = 0.0) -> float:
    a_min_x = min(point[0] for point in a)
    a_max_x = max(point[0] for point in a)
    a_min_y = min(point[1] for point in a)
    a_max_y = max(point[1] for point in a)
    b_min_x = min(point[0] + offset_b for point in b)
    b_max_x = max(point[0] + offset_b for point in b)
    b_min_y = min(point[1] for point in b)
    b_max_y = max(point[1] for point in b)
    gap_x = max(0.0, a_min_x - b_max_x, b_min_x - a_max_x)
    gap_y = max(0.0, a_min_y - b_max_y, b_min_y - a_max_y)
    box_gap = math.hypot(gap_x, gap_y)
    if box_gap > 0.18:
        return box_gap
    minimum = float("inf")
    for index in range(1, len(a)):
        a0, a1 = a[index - 1], a[index]
        for other_index in range(1, len(b)):
            b0 = b[other_index - 1][0] + offset_b, b[other_index - 1][1]
            b1 = b[other_index][0] + offset_b, b[other_index][1]
            minimum = min(minimum, _segment_distance(a0, a1, b0, b1))
            if minimum <= 0.0:
                return 0.0
    return minimum


def _sample_at_s(analysis: Mapping[str, Any], s: float) -> tuple[Point, Point]:
    samples = analysis["backbone"]["samples"]
    position = (s % 1.0) * (len(samples) - 1)
    lower = int(math.floor(position))
    upper = min(len(samples) - 1, lower + 1)
    fraction = position - lower
    point = _lerp(
        _point(samples[lower]["point"], "backbone.point"),
        _point(samples[upper]["point"], "backbone.point"),
        fraction,
    )
    tangent = _unit(
        _lerp(
            _point(samples[lower]["tangent"], "backbone.tangent"),
            _point(samples[upper]["tangent"], "backbone.tangent"),
            fraction,
        ),
        "backbone.tangent",
    )
    return point, tangent


def _normal(tangent: Point, side_id: str) -> Point:
    left = -tangent[1], tangent[0]
    if side_id == "left_normal":
        return left
    if side_id == "right_normal":
        return -left[0], -left[1]
    raise GlobalL1FlowError(f"unknown side id: {side_id}")


def _closest_side(tangent: Point, direction: Point) -> tuple[str, Point]:
    left = _normal(tangent, "left_normal")
    right = _normal(tangent, "right_normal")
    return (
        ("left_normal", left)
        if _dot(left, direction) >= _dot(right, direction)
        else ("right_normal", right)
    )


def _ellipse_value(point: Point, center: Point, rx: float, ry: float) -> float:
    return ((point[0] - center[0]) / rx) ** 2 + ((point[1] - center[1]) / ry) ** 2


def _flower_center_near(flower: Mapping[str, Any], reference_x: float) -> Point:
    center = _point(flower["center"], "flower.center")
    return _periodic_near_x(center[0], reference_x), center[1]


def _flower_boundary_toward(
    flower: Mapping[str, Any],
    source: Point,
    *,
    underside: bool = False,
) -> Point:
    center = _flower_center_near(flower, source[0])
    rx = _finite(flower["rx"], "flower.rx")
    ry = _finite(flower["ry"], "flower.ry")
    if underside:
        return center[0], center[1] + ry
    vector = _sub(source, center)
    denominator = math.sqrt((vector[0] / rx) ** 2 + (vector[1] / ry) ** 2)
    if denominator <= 1e-12:
        raise GlobalL1FlowError("flower/source direction is degenerate")
    return center[0] + vector[0] / denominator, center[1] + vector[1] / denominator


def _flower_by_id(analysis: Mapping[str, Any], flower_id: str) -> Mapping[str, Any]:
    matches = [flower for flower in analysis["flowers"] if flower["flower_id"] == flower_id]
    if len(matches) != 1:
        raise GlobalL1FlowError(f"flower id is not unique: {flower_id}")
    return matches[0]


def _candidate_regions(analysis: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = analysis.get("candidate_l1_attachment_regions")
    if not isinstance(rows, list) or not rows:
        raise GlobalL1FlowError("analysis has no L1 attachment regions")
    return rows


def _region_s_values(
    region: Mapping[str, Any],
    phase: float,
    total_target_count: int = 10,
    total_region_span: float | None = None,
) -> list[float]:
    ranges = [
        (float(start), float(end))
        for start, end in region["s_ranges"]
        if float(end) > float(start)
    ]
    if not ranges:
        return []
    region_span = sum(end - start for start, end in ranges)
    denominator = region_span if total_region_span is None else total_region_span
    region_budget = max(
        2 * len(ranges),
        int(math.ceil(total_target_count * region_span / max(denominator, 1e-12))),
    )
    counts = [2 for _ in ranges]
    remaining = region_budget - sum(counts)
    if remaining > 0:
        raw = [remaining * (end - start) / region_span for start, end in ranges]
        whole = [int(value) for value in raw]
        counts = [count + extra for count, extra in zip(counts, whole)]
        remainder = remaining - sum(whole)
        ranked = sorted(
            range(len(ranges)),
            key=lambda index: (-(raw[index] - whole[index]), index),
        )
        for index in ranked[:remainder]:
            counts[index] += 1
    values: list[float] = []
    for (start_value, end_value), count in zip(ranges, counts):
        span = end_value - start_value
        for index in range(count):
            fraction = (index + 1) / (count + 1)
            shifted = min(0.97, max(0.03, fraction + phase))
            values.append((start_value + span * shifted) % 1.0)
    return values


def _global_latents(prototype_id: str, seed: int) -> dict[str, float]:
    digest = hashlib.sha256(f"{prototype_id}:{seed}:global_l1_flow_v1".encode("utf-8")).digest()
    generator = random.Random(int.from_bytes(digest[:8], "big"))
    return {
        "openness": round(generator.triangular(0.88, 1.14, 1.0), 9),
        "sweep_amplitude": round(generator.triangular(0.88, 1.16, 1.02), 9),
        "asymmetry": round(generator.triangular(-0.16, 0.16, 0.0), 9),
        "flow_phase": round(generator.uniform(-0.035, 0.035), 9),
        "curl_energy": round(generator.triangular(0.86, 1.15, 1.0), 9),
    }


def _required_support_count(
    family_id: str,
    flower_count: int,
    prototype_strategy: Mapping[str, Any] | None = None,
) -> int:
    if prototype_strategy is not None:
        policy = prototype_strategy["flower_mount"]["support_count_policy"]
        if policy == "one_per_flower":
            return flower_count
        if policy == "zero":
            return 0
        raise GlobalL1FlowError(f"unsupported support-count strategy: {policy}")
    if family_id in {"SW-1_valley_filling", "SW-3_tangent_terminal"}:
        return flower_count
    if family_id == "SW-2_axis_penetrating":
        return 0
    raise GlobalL1FlowError(f"unsupported morphology family: {family_id}")


def _derive_lane_count(
    prototype_id: str,
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    prior: Mapping[str, Any],
    branch_seed: int,
    feedback_profile: Mapping[str, Any] | None = None,
    flower_mount_plan: Mapping[str, Any] | None = None,
    prototype_strategy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    family_id = (
        str(prototype_strategy["family_id"])
        if prototype_strategy is not None
        else morphology["classification"]["flower_branch_relation"]["family_id"]
    )
    if feedback_profile is not None:
        preferred = int(feedback_profile["preferred_l1_count"])
        root_spacing = _minimum_root_spacing(prior)
        merged_ranges = _merged_attachment_ranges(analysis)
        root_capacity_before_support = periodic_max_separated_point_count(
            merged_ranges,
            root_spacing,
        )
        if flower_mount_plan is None:
            raise GlobalL1FlowError(
                "feedback L1 planning requires flower mounting first"
            )
        required_support_count = _required_support_count(
            str(family_id),
            len(analysis["flowers"]),
            prototype_strategy,
        )
        mounts = flower_mount_plan.get("mounts")
        if not isinstance(mounts, Sequence) or len(mounts) != required_support_count:
            raise GlobalL1FlowError("flower-first support count mismatch")
        reserved_roots = [float(row["root_s"]) for row in mounts]
        residual_ranges = _subtract_periodic_root_exclusions(
            merged_ranges,
            reserved_roots,
            root_spacing,
        )
        root_capacity = periodic_max_separated_point_count(
            residual_ranges,
            root_spacing,
        )
        raw_counts = sorted({preferred - 1, preferred, preferred + 1})
        feasible_counts = [
            count
            for count in raw_counts
            if (
                5 <= count <= 9
                and count > required_support_count
                and count - required_support_count <= root_capacity
            )
        ]
        if not feasible_counts:
            raise GlobalL1FlowError("dynamic_l1_count_infeasible")
        density_u = _seed_unit(
            prototype_id,
            branch_seed,
            "dynamic_l1_count_v2",
        )
        selected_total = feasible_counts[
            min(len(feasible_counts) - 1, int(density_u * len(feasible_counts)))
        ]
        ordinary_count = selected_total - required_support_count
        return {
            "selected_l1_count": selected_total,
            "required_support_count": required_support_count,
            "ordinary_lane_count": ordinary_count,
            "total_l1_with_flower_support_count": selected_total,
            "count_semantics": (
                "selected_l1_count_is_total; flower supports are allocated "
                "first; ordinary_lane_count is the residual"
            ),
            "primary_branch_evidence": int(
                morphology["instance_priors"]["source_observation_counts"][
                    "primary_branch_count"
                ]
            ),
            "branch_guide_equivalent_l1": None,
            "blank_region_plus_support_evidence": len(
                analysis["space_analysis"]["continuous_blank_regions"]
            ),
            "fixed_visual_capacity": int(
                prior["paired_baseline_scope"]["topology"]["L1"]
            ),
            "preferred_l1_count": preferred,
            "raw_count_candidates": raw_counts,
            "feasible_count_candidates": feasible_counts,
            "root_capacity_before_flower_support": root_capacity_before_support,
            "ordinary_root_capacity_after_flower_support": root_capacity,
            "flower_support_reserved_root_s": [
                round(value, 9) for value in reserved_roots
            ],
            "minimum_root_spacing": round(root_spacing, 9),
            "density_u": round(density_u, 9),
            "governing_evidence": (
                "editor_total_l1_center_count_then_flower_support_first_and_"
                "variant_residual_attachment_capacity"
            ),
            "fixed_count_copied": False,
            "mandatory_flower_service_count": required_support_count,
        }
    support_count = _required_support_count(
        family_id,
        len(analysis["flowers"]),
        prototype_strategy,
    )
    evidence = morphology["instance_priors"]["source_observation_counts"]
    primary_evidence = int(evidence["primary_branch_count"])
    guide_evidence = int(evidence["branch_guide_count"])
    median_unit_load = float(
        prior["statistics"]["primary_root_rhythm"]["unit_load_curves_including_primary"]["median"]
    )
    guide_equivalent = int(round(guide_evidence / median_unit_load))
    space_evidence = support_count + len(analysis["space_analysis"]["continuous_blank_regions"])
    fixed_visual_capacity = int(prior["paired_baseline_scope"]["topology"]["L1"])
    if prototype_id == "proto_sw_1_3":
        selected = fixed_visual_capacity
        governing_evidence = "strict_paired_fixed_visual_capacity"
    else:
        selected = min(
            fixed_visual_capacity,
            max(support_count, primary_evidence, guide_equivalent, space_evidence),
        )
        governing_evidence = "morphology_and_blank_space_capacity"
    if selected <= support_count:
        raise GlobalL1FlowError(f"{prototype_id} has no capacity for ordinary L1 lanes")
    return {
        "selected_l1_count": selected,
        "required_support_count": support_count,
        "ordinary_lane_count": selected - support_count,
        "primary_branch_evidence": primary_evidence,
        "branch_guide_equivalent_l1": guide_equivalent,
        "blank_region_plus_support_evidence": space_evidence,
        "fixed_visual_capacity": fixed_visual_capacity,
        "governing_evidence": governing_evidence,
        "fixed_count_copied": False,
    }


def _derive_common_count_domain(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    prior: Mapping[str, Any],
    feedback_profile: Mapping[str, Any],
    flower_mount_plan: Mapping[str, Any],
    branch_seed: int,
    prototype_strategy: Mapping[str, Any] | None = None,
    ordinary_density_level_override: str | None = None,
    soft_density_mode: bool = False,
    density_control_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive the admissible ordinary-L1 count band before set search."""

    family_id = (
        str(prototype_strategy["family_id"])
        if prototype_strategy is not None
        else morphology["classification"]["flower_branch_relation"]["family_id"]
    )
    preferred = int(feedback_profile["preferred_l1_count"])
    root_spacing = _minimum_root_spacing(prior)
    merged_ranges = _merged_attachment_ranges(analysis)
    root_capacity_before_support = periodic_max_separated_point_count(
        merged_ranges,
        root_spacing,
    )
    required_support_count = _required_support_count(
        family_id,
        len(analysis["flowers"]),
        prototype_strategy,
    )
    mounts = flower_mount_plan.get("mounts")
    if not isinstance(mounts, Sequence) or len(mounts) != required_support_count:
        raise GlobalL1FlowError("flower-first support count mismatch")
    reserved_roots = [float(row["root_s"]) for row in mounts]
    residual_ranges = _subtract_periodic_root_exclusions(
        merged_ranges,
        reserved_roots,
        root_spacing,
    )
    ordinary_root_capacity = periodic_max_separated_point_count(
        residual_ranges,
        root_spacing,
    )
    ordinary_center = preferred - required_support_count
    if ordinary_center <= 0:
        raise GlobalL1FlowError("ordinary L1 center must remain positive")
    if (
        ordinary_density_level_override is not None
        and ordinary_density_level_override not in ORDINARY_DENSITY_LEVELS
    ):
        raise GlobalL1FlowError(
            "ordinary density override must be simple, medium, or rich"
        )
    density_u = _seed_unit(
        str(analysis["prototype_id"]),
        branch_seed,
        "ordinary_l1_density_level_v1",
    )
    density_level = (
        ordinary_density_level_override
        if ordinary_density_level_override is not None
        else ORDINARY_DENSITY_LEVELS[
            min(
                len(ORDINARY_DENSITY_LEVELS) - 1,
                int(density_u * len(ORDINARY_DENSITY_LEVELS)),
            )
        ]
    )
    density_targets: Mapping[str, Any] | None = None
    if density_control_profile is not None:
        if density_control_profile.get("schema") != DENSITY_CONTROL_PROFILE_SCHEMA:
            raise GlobalL1FlowError("density control profile schema mismatch")
        density_targets = density_control_profile.get(
            "target_total_l1_count_by_level"
        )
        if (
            not isinstance(density_targets, Mapping)
            or set(density_targets) != set(ORDINARY_DENSITY_LEVELS)
            or any(
                isinstance(density_targets[level], bool)
                or not isinstance(density_targets[level], int)
                or not 5 <= int(density_targets[level]) <= 9
                for level in ORDINARY_DENSITY_LEVELS
            )
        ):
            raise GlobalL1FlowError("density control total-L1 targets are invalid")
        if not (
            int(density_targets["simple"])
            < int(density_targets["medium"])
            < int(density_targets["rich"])
        ):
            raise GlobalL1FlowError("density control total-L1 targets must increase")
        raw_total_counts = [int(density_targets[density_level])]
    else:
        raw_total_counts = sorted({preferred - 1, preferred, preferred + 1})
    allowed_total_counts = [
        count
        for count in raw_total_counts
        if (
            5 <= count <= 9
            and count > required_support_count
            and count - required_support_count <= ordinary_root_capacity
        )
    ]
    if not allowed_total_counts:
        raise GlobalL1FlowError("dynamic_l1_count_infeasible")
    allowed_ordinary_counts = [
        count - required_support_count for count in allowed_total_counts
    ]
    result = {
        "preferred_l1_count": preferred,
        "raw_total_l1_count_candidates": raw_total_counts,
        "allowed_total_l1_counts": allowed_total_counts,
        "allowed_ordinary_l1_counts": allowed_ordinary_counts,
        "ordinary_density_level": density_level,
        "ordinary_density_source": (
            "explicit_visual_density_control_v2"
            if density_control_profile is not None
            else "explicit_review_override"
            if ordinary_density_level_override is not None
            else "branch_seed"
        ),
        "ordinary_density_u": (
            None if ordinary_density_level_override is not None else round(density_u, 9)
        ),
        "required_support_count": required_support_count,
        "root_capacity_before_flower_support": root_capacity_before_support,
        "ordinary_root_capacity_after_flower_support": ordinary_root_capacity,
        "flower_support_reserved_root_s": [
            round(value, 9) for value in reserved_roots
        ],
        "minimum_root_spacing": round(root_spacing, 9),
        "count_selected_before_candidate_search": False,
        "count_semantics": (
            (
                "the requested density level fixes a preregistered total-L1 target; "
                "the common-pool solver still selects the compatible L1 geometry; "
                "frozen flower supports count toward the total but are not regenerated"
            )
            if density_control_profile is not None
            else (
                (
                    "preferred total count defines only the admissible search band; "
                    "all geometry-witnessed ordinary-L1 cardinalities compete in one "
                    "soft resource ranking; simple/medium/rich does not preselect N; "
                    "frozen flower supports do not participate in the density resource"
                )
                if soft_density_mode
                else (
                    "preferred total count is converted once to an ordinary-L1 "
                    "center; the requested simple/medium/rich level selects among "
                    "geometry-feasible ordinary cardinalities inside the common-"
                    "pool solver; frozen flower supports do not participate in the "
                    "density level"
                )
            )
        ),
        "primary_branch_evidence": int(
            morphology["instance_priors"]["source_observation_counts"][
                "primary_branch_count"
            ]
        ),
        "fixed_visual_capacity": int(
            prior["paired_baseline_scope"]["topology"]["L1"]
        ),
        "fixed_count_copied": False,
        "mandatory_flower_service_count": required_support_count,
    }
    if density_control_profile is not None and density_targets is not None:
        result.update(
            {
                "density_control_profile": dict(density_control_profile),
                "target_total_l1_count": int(density_targets[density_level]),
            }
        )
    if soft_density_mode:
        result.update(
            {
                "density_count_mapping_used": density_control_profile is not None,
                "selected_set_and_count_jointly_ranked": (
                    density_control_profile is None
                ),
            }
        )
    else:
        result.update(
            {
                "ordinary_l1_count_center": ordinary_center,
                "ordinary_l1_count_capacity_domain": {
                    "simple": min(allowed_ordinary_counts),
                    "medium": min(
                        allowed_ordinary_counts,
                        key=lambda value: (abs(value - ordinary_center), value),
                    ),
                    "rich": max(allowed_ordinary_counts),
                },
            }
        )
    return result


def _vertical_preferences(
    rhythm: str,
    count: int,
    seed: int,
) -> list[str]:
    if rhythm == "upper_side_emphasis":
        base = ["upper", "upper", "lower"]
    elif rhythm == "sparse_asymmetric_alternation":
        base = ["upper", "lower", "upper", "lower", "lower"]
    else:
        base = ["upper", "lower"]
    offset = seed % len(base)
    return [base[(index + offset) % len(base)] for index in range(count)]


def _slot_roles(
    family_id: str,
    count: int,
    role_cycle: Sequence[str] | None = None,
) -> list[str]:
    if role_cycle is not None:
        cycle = tuple(str(value) for value in role_cycle)
        if not cycle:
            raise GlobalL1FlowError("prototype strategy has an empty role cycle")
        return [cycle[index % len(cycle)] for index in range(count)]
    if family_id == "SW-1_valley_filling":
        cycle = ("frontier", "primary_sweep", "balance", "primary_sweep")
    elif family_id == "SW-2_axis_penetrating":
        cycle = ("primary_sweep", "frontier", "primary_sweep", "balance")
    elif family_id == "SW-3_tangent_terminal":
        cycle = ("primary_sweep", "balance", "frontier")
    else:
        raise GlobalL1FlowError(f"unsupported morphology family: {family_id}")
    return [cycle[index % len(cycle)] for index in range(count)]


def _make_slots(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    count_derivation: Mapping[str, Any],
    latents: Mapping[str, float],
    seed: int,
    prior: Mapping[str, Any],
    feedback_profile: Mapping[str, Any] | None = None,
    prototype_strategy: Mapping[str, Any] | None = None,
) -> tuple[list[Slot], dict[str, Any]]:
    family_id = (
        str(prototype_strategy["family_id"])
        if prototype_strategy is not None
        else morphology["classification"]["flower_branch_relation"]["family_id"]
    )
    l1_policy = (
        prototype_strategy["l1_profile"]
        if prototype_strategy is not None
        else None
    )
    side_rhythm = str(
        l1_policy["side_rhythm"]
        if l1_policy is not None
        else morphology["instance_priors"]["side_rhythm"]
    )
    role_cycle = (
        l1_policy["ordinary_role_cycle"]
        if l1_policy is not None
        else None
    )
    if feedback_profile is not None:
        ordinary_count = int(count_derivation["ordinary_lane_count"])
        vertical = _vertical_preferences(side_rhythm, ordinary_count, seed)
        roles = _slot_roles(family_id, ordinary_count, role_cycle)
        preferred_values, rhythm = _dynamic_root_rhythm(
            str(
                l1_policy["random_namespace"]
                if l1_policy is not None
                else analysis["prototype_id"]
            ),
            seed,
            ordinary_count,
            feedback_profile,
            prior,
        )
        return (
            [
                Slot(
                    slot_id=f"ordinary_{index + 1}",
                    role=roles[index],
                    index=index,
                    flower_id=None,
                    preferred_s=preferred_values[index],
                    preferred_vertical_side=vertical[index],
                )
                for index in range(ordinary_count)
            ],
            rhythm,
        )
    support_role = (
        "flower_support"
        if family_id == "SW-1_valley_filling"
        else "terminal_flower_support"
    )
    slots: list[Slot] = []
    for index, flower in enumerate(analysis["flowers"][: count_derivation["required_support_count"]]):
        slots.append(
            Slot(
                slot_id=f"support_{index + 1}",
                role=support_role,
                index=index,
                flower_id=str(flower["flower_id"]),
                preferred_s=float(flower["nearest_backbone_s"]),
                preferred_vertical_side="lower",
            )
        )

    ordinary_count = int(count_derivation["ordinary_lane_count"])
    vertical = _vertical_preferences(side_rhythm, ordinary_count, seed)
    roles = _slot_roles(family_id, ordinary_count, role_cycle)
    for index in range(ordinary_count):
        preferred_s = (
            (index + 0.5) / ordinary_count + float(latents["flow_phase"])
        ) % 1.0
        slots.append(
            Slot(
                slot_id=f"ordinary_{index + 1}",
                role=roles[index],
                index=index,
                flower_id=None,
                preferred_s=preferred_s,
                preferred_vertical_side=vertical[index],
            )
        )
    return slots, {
        "source": "legacy_stage3b_spacing",
        "preferred_s": [round(slot.preferred_s, 9) for slot in slots],
    }


def _candidate_base(
    *,
    candidate_id: str,
    slot: Slot,
    source_channel: str,
    side_id: str,
    root_s: float,
    root: Point,
    target: Point,
    segments: Sequence[Mapping[str, Sequence[float]]],
    flower_id: str | None,
    curvature_signature: str,
    features: Mapping[str, float],
    individual_score: float,
) -> dict[str, Any]:
    centerline = _sample_segments(segments)
    return {
        "candidate_id": candidate_id,
        "slot_id": slot.slot_id,
        "source_channel": source_channel,
        "role": slot.role,
        "flower_id": flower_id,
        "side_id": side_id,
        "root_s": round(root_s % 1.0, 9),
        "root": _round_point(root),
        "target": _round_point(target),
        "curvature_signature": curvature_signature,
        "segments": list(segments),
        "centerline": [_round_point(point) for point in centerline],
        "planning_length": round(_polyline_length(centerline), 9),
        "occupancy_radius": 0.018,
        "features": {key: round(float(value), 9) for key, value in features.items()},
        "individual_score": round(individual_score, 9),
    }


def _common_candidate_base(
    *,
    candidate_id: str,
    source_channel: str,
    side_id: str,
    root_s: float,
    root: Point,
    target: Point,
    segments: Sequence[Mapping[str, Sequence[float]]],
    curvature_signature: str,
    features: Mapping[str, float],
    individual_score: float,
) -> dict[str, Any]:
    """Build a pre-selection ordinary L1 candidate with no lane identity."""

    centerline = _sample_segments(segments)
    return {
        "candidate_id": candidate_id,
        "source_channel": source_channel,
        "role": "primary_sweep",
        "flower_id": None,
        "side_id": side_id,
        "root_s": round(root_s % 1.0, 9),
        "root": _round_point(root),
        "target": _round_point(target),
        "curvature_signature": curvature_signature,
        "segments": list(segments),
        "centerline": [_round_point(point) for point in centerline],
        "planning_length": round(_polyline_length(centerline), 9),
        "occupancy_radius": 0.018,
        "features": {
            key: round(float(value), 9) for key, value in features.items()
        },
        "individual_score": round(individual_score, 9),
    }


def _seed_unit(prototype_id: str, seed: int, domain: str) -> float:
    digest = hashlib.sha256(
        f"{prototype_id}:{seed}:{domain}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64)


def _minimum_root_spacing(prior: Mapping[str, Any]) -> float:
    root_stats = prior["statistics"]["primary_root_rhythm"][
        "consecutive_mount_gap"
    ]
    return max(0.05, float(root_stats["min"]) * 0.78)


def _minimum_lane_clearance(
    prior: Mapping[str, Any],
    curve_geometry_profile: Mapping[str, Any] | None,
) -> float:
    if curve_geometry_profile is not None:
        stroke_width = curve_geometry_profile["observed_geometry"].get(
            "stroke_width_unit_ratio"
        )
        if not isinstance(stroke_width, Mapping):
            raise GlobalL1FlowError(
                "editor curve geometry lacks normalized stroke width"
            )
        # The observed stroke-width distribution is evidence for the occupied
        # radius of one lane, not for the distance between two centerlines.
        # Two occupied strokes need the sum of their diameters plus a visible
        # white gap; using one stroke width made near-touching legal.
        stroke_diameter = float(stroke_width["q90"])
        return 2.0 * stroke_diameter
    root_spacing = _minimum_root_spacing(prior)
    return max(0.032, root_spacing * 0.58)


def _merged_attachment_ranges(
    analysis: Mapping[str, Any],
) -> list[tuple[float, float]]:
    ranges = sorted(
        (
            max(0.0, float(start)),
            min(1.0, float(end)),
        )
        for region in _candidate_regions(analysis)
        for start, end in region["s_ranges"]
        if float(end) > float(start)
    )
    merged: list[tuple[float, float]] = []
    for start, end in ranges:
        if not merged or start > merged[-1][1] + 1e-12:
            merged.append((start, end))
        else:
            merged[-1] = merged[-1][0], max(merged[-1][1], end)
    return merged


def periodic_max_separated_point_count(
    ranges: Sequence[Sequence[float]],
    minimum_spacing: float,
) -> int:
    """Compute continuous periodic root capacity from merged one-dimensional ranges."""

    spacing = float(minimum_spacing)
    if not 0.0 < spacing <= 1.0:
        raise GlobalL1FlowError("minimum root spacing must lie in (0, 1]")
    normalized = sorted(
        (max(0.0, float(row[0])), min(1.0, float(row[1])))
        for row in ranges
        if len(row) == 2 and float(row[1]) > float(row[0])
    )
    if not normalized:
        return 0
    maximum_possible = int(math.floor(1.0 / spacing + 1e-10))
    anchors: set[float] = set()
    for start, _ in normalized:
        for index in range(maximum_possible + 1):
            anchors.add(round((start - index * spacing) % 1.0, 12))
    repeated = sorted(
        (start + offset, end + offset)
        for offset in (-1.0, 0.0, 1.0, 2.0)
        for start, end in normalized
    )

    def contains(value: float) -> bool:
        wrapped = value % 1.0
        return any(
            start - 1e-10 <= wrapped <= end + 1e-10
            for start, end in normalized
        )

    def next_allowed(target: float, limit: float) -> float | None:
        for start, end in repeated:
            if end < target - 1e-10:
                continue
            candidate = max(target, start)
            if candidate <= end + 1e-10 and candidate <= limit + 1e-10:
                return candidate
        return None

    maximum = 0
    for anchor in sorted(value for value in anchors if contains(value)):
        last = anchor
        count = 1
        limit = anchor + 1.0 - spacing
        while count < maximum_possible:
            value = next_allowed(last + spacing, limit)
            if value is None:
                break
            count += 1
            last = value
        maximum = max(maximum, count)
    return maximum


def _subtract_periodic_root_exclusions(
    ranges: Sequence[Sequence[float]],
    fixed_roots: Sequence[float],
    minimum_spacing: float,
) -> list[tuple[float, float]]:
    """Remove only root positions that conflict with already-frozen supports."""

    fragments = [
        (max(0.0, float(row[0])), min(1.0, float(row[1])))
        for row in ranges
        if len(row) == 2 and float(row[1]) > float(row[0])
    ]
    spacing = float(minimum_spacing)
    for root in fixed_roots:
        exclusions = [
            (float(root) + offset - spacing, float(root) + offset + spacing)
            for offset in (-1.0, 0.0, 1.0)
        ]
        for lower, upper in exclusions:
            next_fragments: list[tuple[float, float]] = []
            for start, end in fragments:
                if upper <= start or lower >= end:
                    next_fragments.append((start, end))
                    continue
                if start < lower:
                    next_fragments.append((start, min(end, lower)))
                if upper < end:
                    next_fragments.append((max(start, upper), end))
            fragments = [
                (start, end)
                for start, end in next_fragments
                if end - start > 1e-10
            ]
    return fragments


def _prototype_gap_samples(
    feedback_profile: Mapping[str, Any],
    prior: Mapping[str, Any],
) -> tuple[list[float], str]:
    rhythm = feedback_profile.get("root_rhythm_quantiles")
    if isinstance(rhythm, Sequence) and not isinstance(rhythm, (str, bytes)):
        positions = sorted(float(value) % 1.0 for value in rhythm)
        if len(positions) >= 2:
            gaps = [
                positions[index + 1] - positions[index]
                for index in range(len(positions) - 1)
            ]
            gaps.append(positions[0] + 1.0 - positions[-1])
            return sorted(gap for gap in gaps if gap > 0.0), "prototype_editor_gap_samples"
    samples = prior["statistics"]["primary_root_rhythm"][
        "consecutive_mount_gap"
    ]["samples"]
    values = sorted(float(value) for value in samples if float(value) > 0.0)
    if not values:
        raise GlobalL1FlowError("fixed visual prior has no root-gap samples")
    return values, "fixed_visual_prior_gap_samples"


def _empirical_quantile(samples: Sequence[float], quantile: float) -> float:
    if len(samples) == 1:
        return float(samples[0])
    position = min(1.0, max(0.0, quantile)) * (len(samples) - 1)
    lower = int(math.floor(position))
    upper = min(len(samples) - 1, lower + 1)
    return float(samples[lower]) + (
        float(samples[upper]) - float(samples[lower])
    ) * (position - lower)


def _dynamic_root_rhythm(
    prototype_id: str,
    branch_seed: int,
    count: int,
    feedback_profile: Mapping[str, Any],
    prior: Mapping[str, Any],
) -> tuple[list[float], dict[str, Any]]:
    samples, source = _prototype_gap_samples(feedback_profile, prior)
    spacing = _minimum_root_spacing(prior)
    if count * spacing >= 1.0:
        raise GlobalL1FlowError("dynamic_l1_count_infeasible")
    quantile_phase = _seed_unit(
        prototype_id,
        branch_seed,
        "root_gap_quantile_phase_v2",
    )
    rotation = _seed_unit(
        prototype_id,
        branch_seed,
        "root_rhythm_rotation_v2",
    )
    golden_step = (math.sqrt(5.0) - 1.0) / 2.0
    sampled = [
        _empirical_quantile(
            samples,
            (quantile_phase + index * golden_step) % 1.0,
        )
        for index in range(count)
    ]
    residual = 1.0 - count * spacing
    total_weight = sum(sampled)
    gaps = [
        spacing + residual * value / total_weight
        for value in sampled
    ]
    preferred: list[float] = []
    cursor = rotation
    for gap in gaps:
        preferred.append(cursor % 1.0)
        cursor += gap
    return preferred, {
        "source": source,
        "minimum_root_spacing": round(spacing, 9),
        "gap_quantile_phase": round(quantile_phase, 9),
        "rotation": round(rotation, 9),
        "gaps": [round(value, 9) for value in gaps],
        "preferred_s": [round(value, 9) for value in preferred],
        "completely_equidistant": max(gaps) - min(gaps) <= 1e-9,
    }


def _bow_ratio(points: Sequence[Point]) -> float:
    if len(points) < 3:
        return 0.0
    start = points[0]
    end = points[-1]
    chord = _distance(start, end)
    actual = _polyline_length(points)
    if chord <= 1e-9 or actual <= 1e-9:
        return 0.0
    maximum = max(
        abs(_cross(_sub(end, start), _sub(point, start))) / chord
        for point in points[1:-1]
    )
    return maximum / actual


def _direction_turn_degrees(first: Point, second: Point) -> float:
    first_unit = _unit(first, "first_direction")
    second_unit = _unit(second, "second_direction")
    cosine = max(-1.0, min(1.0, _dot(first_unit, second_unit)))
    return math.degrees(math.acos(cosine))


def _polyline_inflection_count(points: Sequence[Point]) -> int:
    signs: list[int] = []
    for index in range(1, len(points) - 1):
        incoming = _sub(points[index], points[index - 1])
        outgoing = _sub(points[index + 1], points[index])
        turn = _cross(incoming, outgoing)
        if abs(turn) <= 1e-8:
            continue
        sign = 1 if turn > 0.0 else -1
        if not signs or signs[-1] != sign:
            signs.append(sign)
    return max(0, len(signs) - 1)


def _empirical_cdf(
    distribution: Mapping[str, Any],
    value: float,
) -> float:
    samples = [float(sample) for sample in distribution["samples"]]
    if not samples:
        raise GlobalL1FlowError("editor geometry distribution is empty")
    return bisect_right(samples, float(value)) / len(samples)


def _continuous_editor_descriptors(
    profile: Mapping[str, Any],
    prototype_id: str,
    branch_seed: int,
    candidate_index: int,
) -> tuple[dict[str, float], dict[str, float], str, float]:
    """Draw one continuous descriptor vector from the editor distribution.

    The editor cases are used to estimate marginal distributions and their
    Gaussian-copula dependence.  No individual editor curve is selected or
    transferred into a production candidate.
    """

    names = (
        "start_handle_chord_ratio",
        "end_handle_chord_ratio",
        "start_angle_abs_deg",
        "end_angle_chord_deg",
        "end_angle_normalized_deg",
        "parent_tangent_departure_deg",
    )
    edited_distributions = profile.get("descriptor_distributions")
    if not isinstance(edited_distributions, Mapping):
        raise GlobalL1FlowError("editor descriptor distributions are missing")
    cholesky = profile.get("descriptor_gaussian_copula_cholesky")
    if (
        not isinstance(cholesky, Sequence)
        or len(cholesky) != len(names)
        or any(not isinstance(row, Sequence) or len(row) != len(names) for row in cholesky)
    ):
        raise GlobalL1FlowError("editor descriptor copula is missing")

    generator = random.Random(
        int.from_bytes(
            hashlib.sha256(
                f"{prototype_id}:{branch_seed}:continuous_l1:{candidate_index}".encode(
                    "utf-8"
                )
            ).digest()[:8],
            "big",
        )
    )
    independent = [generator.gauss(0.0, 1.0) for _ in names]
    correlated = [
        sum(float(cholesky[row][column]) * independent[column] for column in range(row + 1))
        for row in range(len(names))
    ]
    normal = NormalDist()
    quantiles = {
        name: min(0.97, max(0.03, normal.cdf(value)))
        for name, value in zip(names, correlated)
    }
    descriptors = {
        name: _empirical_quantile(
            [float(value) for value in edited_distributions[name]["samples"]],
            quantiles[name],
        )
        for name in names
    }
    length_quantile = min(
        0.97,
        max(
            0.03,
            0.62 * quantiles["start_handle_chord_ratio"]
            + 0.38 * quantiles["end_handle_chord_ratio"],
        ),
    )
    learned_length = _empirical_quantile(
        [
            float(value)
            for value in profile["observed_geometry"][
                "actual_length_unit_ratio"
            ]["samples"]
        ],
        length_quantile,
    )
    return (
        descriptors,
        quantiles,
        f"continuous_copula_{candidate_index:05d}",
        learned_length,
    )


def _maximum_backbone_excursion(
    points: Sequence[Point],
    backbone: Sequence[Point],
) -> float:
    maximum = 0.0
    point_array = np.asarray(points, dtype=np.float64)
    backbone_array = np.asarray(backbone, dtype=np.float64)
    if point_array.shape[0] and backbone_array.shape[0] >= 2:
        per_point_minimum = np.full(point_array.shape[0], np.inf)
        for offset in (-1.0, 0.0, 1.0):
            shifted = backbone_array + np.asarray(
                [offset, 0.0],
                dtype=np.float64,
            )
            matrix = point_segment_distance_matrix_batch(
                point_array,
                shifted[:-1],
                shifted[1:],
            )
            per_point_minimum = np.minimum(
                per_point_minimum,
                matrix.min(axis=1),
            )
        maximum = max(maximum, float(per_point_minimum.max()))
    return maximum


def _nearest_flower_gap(
    points: Sequence[Point],
    analysis: Mapping[str, Any],
) -> float:
    if not analysis["flowers"]:
        return 1.0
    minimum = float("inf")
    for flower in analysis["flowers"]:
        rx = float(flower["protection_rx"])
        ry = float(flower["protection_ry"])
        for point in points:
            center = _flower_center_near(flower, point[0])
            normalized = math.sqrt(max(0.0, _ellipse_value(point, center, rx, ry)))
            minimum = min(minimum, max(0.0, normalized - 1.0))
    return minimum


def _polylines_cross(
    a: Sequence[Point],
    b: Sequence[Point],
    offset_b: float = 0.0,
) -> bool:
    a_array = np.asarray(a, dtype=np.float64)
    b_array = np.asarray(b, dtype=np.float64)
    b_array = b_array + np.asarray([offset_b, 0.0], dtype=np.float64)
    return polyline_pair_intersects(a_array, b_array)


def _feedback_ordinary_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    latents: Mapping[str, float],
    feedback_profile: Mapping[str, Any],
    curve_geometry_profile: Mapping[str, Any],
    lane_count: int,
    branch_seed: int,
) -> list[dict[str, Any]]:
    """Generate L1 curves from the continuous editor-learned descriptor field."""

    base_length = float(
        prior["statistics"]["primary_geometry"]["chord_length_repeat"]["median"]
    )
    length_strata = tuple(float(value) for value in feedback_profile["length_strata"])
    length_multiplier = float(feedback_profile["length_multiplier"])
    root_gap_median = float(
        prior["statistics"]["primary_root_rhythm"]["consecutive_mount_gap"]["median"]
    )
    canvas_height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    backbone = _backbone_points(analysis)
    candidates: list[dict[str, Any]] = []
    candidate_index = 0
    phase = float(latents["flow_phase"]) * (1.0 if slot.index % 2 == 0 else -1.0)
    bow_distribution = curve_geometry_profile["observed_geometry"]["bow_ratio"]
    bow_lower = float(bow_distribution["q10"])
    bow_upper = float(bow_distribution["q90"])
    regions = _candidate_regions(analysis)
    total_region_span = sum(
        sum(float(end) - float(start) for start, end in region["s_ranges"])
        for region in regions
    )
    root_sample_count = max(10, 2 * lane_count)
    # Twelve continuous draws per root/length stratum retain a broad shape
    # domain without turning the exact global solve into an exemplar-sized
    # combinatorial search.
    descriptor_sample_count = 12

    for region in regions:
        side_id = str(region["side_id"])
        for root_s in _region_s_values(
            region,
            phase,
            root_sample_count,
            total_region_span,
        ):
            root, tangent = _sample_at_s(analysis, root_s)
            outward = _normal(tangent, side_id)
            for along_sign in (-1.0, 1.0):
                along = _mul(tangent, along_sign)
                for stratum_index, length_scale in enumerate(length_strata):
                    for _ in range(descriptor_sample_count):
                        candidate_index += 1
                        planned = (
                            base_length
                            * length_scale
                            * length_multiplier
                            * (0.94 + 0.06 * float(latents["openness"]))
                        )
                        (
                            descriptors,
                            descriptor_quantiles,
                            geometry_sample_id,
                            learned_actual_length,
                        ) = _continuous_editor_descriptors(
                            curve_geometry_profile,
                            str(analysis["prototype_id"]),
                            branch_seed,
                            candidate_index,
                        )
                        if stratum_index == 0:
                            planned = min(
                                planned,
                                learned_actual_length,
                                float(
                                    prior["statistics"][
                                        "primary_geometry"
                                    ]["actual_length_repeat"]["min"]
                                ),
                            )
                        longitudinal = planned * (
                            0.72 + 0.10 * stratum_index
                        )
                        outward_reach = planned * (
                            0.56 + 0.035 * stratum_index
                        )
                        parent_departure = math.radians(
                            float(descriptors["parent_tangent_departure_deg"])
                        )
                        start_direction = _unit(
                            _add(
                                _mul(along, math.cos(parent_departure)),
                                _mul(outward, math.sin(parent_departure)),
                            ),
                            "feedback_editor_parent_local_start",
                        )
                        end_angle = float(
                            descriptors["end_angle_chord_deg"]
                        )
                        normalized_end_angle = float(
                            descriptors["end_angle_normalized_deg"]
                        )
                        start_angle_abs = float(
                            descriptors["start_angle_abs_deg"]
                        )
                        if abs(end_angle) > 1e-7:
                            orientation_sign = (
                                1.0
                                if normalized_end_angle / end_angle >= 0.0
                                else -1.0
                            )
                            signed_start_angle = (
                                orientation_sign * start_angle_abs
                            )
                            chord_direction = _unit(
                                _rotate(
                                    start_direction,
                                    -math.radians(signed_start_angle),
                                ),
                                "feedback_editor_exemplar_chord",
                            )
                        else:
                            chord_options = [
                                _unit(
                                    _rotate(
                                        start_direction,
                                        -math.radians(sign * start_angle_abs),
                                    ),
                                    "feedback_editor_exemplar_chord",
                                )
                                for sign in (-1.0, 1.0)
                            ]
                            chord_direction = max(
                                chord_options,
                                key=lambda direction: _dot(direction, outward),
                            )
                        chord_length = math.hypot(
                            longitudinal,
                            outward_reach,
                        )
                        target = _add(
                            root,
                            _mul(chord_direction, chord_length),
                        )
                        terminal_direction = _unit(
                            _rotate(
                                chord_direction,
                                math.radians(
                                    float(descriptors["end_angle_chord_deg"])
                                ),
                            ),
                            "feedback_editor_exemplar_terminal",
                        )
                        start_arm = chord_length * float(
                            descriptors["start_handle_chord_ratio"]
                        )
                        end_arm = chord_length * float(
                            descriptors["end_handle_chord_ratio"]
                        )
                        segments = [
                            _segment(
                                root,
                                _add(root, _mul(start_direction, start_arm)),
                                _sub(target, _mul(terminal_direction, end_arm)),
                                target,
                            )
                        ]
                        points = _sample_segments(segments)
                        if any(
                            point[1] < 0.025 or point[1] > canvas_height - 0.025
                            for point in points
                        ):
                            continue
                        if any(point[0] < -0.30 or point[0] > 1.30 for point in points):
                            continue
                        actual_length = _polyline_length(points)
                        bow_ratio = _bow_ratio(points)
                        bow_empirical_quantile = _empirical_cdf(
                            bow_distribution,
                            bow_ratio,
                        )
                        terminal_turn_degrees = _direction_turn_degrees(
                            start_direction,
                            terminal_direction,
                        )
                        start_chord_angle_error = abs(
                            _direction_turn_degrees(
                                start_direction,
                                chord_direction,
                            )
                            - start_angle_abs
                        )
                        inflection_count = _polyline_inflection_count(points)
                        vertical_span = max(point[1] for point in points) - min(
                            point[1] for point in points
                        )
                        excursion = _maximum_backbone_excursion(points, backbone)
                        flower_gap = _nearest_flower_gap(points, analysis)
                        root_preference = 1.0 - min(
                            1.0,
                            _periodic_delta(root_s, slot.preferred_s)
                            / max(root_gap_median * 2.2, 0.18),
                        )
                        vertical_side = "upper" if target[1] < root[1] else "lower"
                        vertical_match = (
                            1.0 if vertical_side == slot.preferred_vertical_side else 0.0
                        )
                        if bow_lower <= bow_ratio <= bow_upper:
                            bow_score = 1.0
                        else:
                            bow_score = 1.0 - min(
                                1.0,
                                min(
                                    abs(bow_ratio - bow_lower),
                                    abs(bow_ratio - bow_upper),
                                )
                                / max(bow_upper - bow_lower, 0.03),
                            )
                        compact_score = 1.0 - min(
                            1.0,
                            abs(actual_length - planned) / max(planned * 0.45, 1e-9),
                        )
                        individual_score = (
                            2.6 * root_preference
                            + 0.45 * vertical_match
                            + 0.75 * min(1.0, float(region["mean_clearance"]) / 0.30)
                            + 1.25 * abs(_dot(start_direction, tangent))
                            + 1.35 * bow_score
                            + 1.10 * compact_score
                            + (1.0 if stratum_index == 1 else 0.45 if stratum_index == 2 else 0.0)
                            - 0.35
                            * max(
                                0.0,
                                vertical_span
                                / float(feedback_profile["maximum_vertical_span"])
                                - 0.78,
                            )
                        )
                        candidate_payload = _candidate_base(
                                candidate_id=(
                                    f"{slot.slot_id}_feedback_{candidate_index:04d}"
                                ),
                                slot=slot,
                                source_channel=(
                                    "editor_descriptor_distribution_sample"
                                ),
                                side_id=side_id,
                                root_s=root_s,
                                root=root,
                                target=target,
                                segments=segments,
                                flower_id=None,
                                curvature_signature=(
                                    "learned_reverse_end"
                                    if float(
                                        descriptors["end_angle_chord_deg"]
                                    )
                                    < 0.0
                                    else "learned_same_side_end"
                                ),
                                features={
                                    "root_preference": root_preference,
                                    "vertical_match": vertical_match,
                                    "initial_tangent_alignment": abs(
                                        _dot(start_direction, tangent)
                                    ),
                                    "initial_outward_alignment": _dot(
                                        start_direction, outward
                                    ),
                                    "bow_ratio": bow_ratio,
                                    "bow_empirical_quantile": (
                                        bow_empirical_quantile
                                    ),
                                    "vertical_span": vertical_span,
                                    "maximum_backbone_excursion": excursion,
                                    "nearest_flower_gap": flower_gap,
                                    "length_stratum": float(stratum_index),
                                    "learned_actual_length_unit_ratio": (
                                        learned_actual_length
                                    ),
                                    "editor_geometry_sample_index": candidate_index,
                                    "descriptor_mean_quantile": sum(
                                        descriptor_quantiles.values()
                                    )
                                    / len(descriptor_quantiles),
                                    **{
                                        f"editor_{name}": value
                                        for name, value in descriptors.items()
                                    },
                                    **{
                                        f"editor_{name}_quantile": value
                                        for name, value in descriptor_quantiles.items()
                                    },
                                    "terminal_turn_degrees": terminal_turn_degrees,
                                    "editor_start_chord_angle_error_deg": (
                                        start_chord_angle_error
                                    ),
                                    "inflection_count": float(inflection_count),
                                    "planned_chord": _distance(root, target),
                                },
                                individual_score=individual_score,
                            )
                        candidate_payload["editor_geometry_sample_id"] = (
                            geometry_sample_id
                        )
                        candidate_payload["editor_geometry_source"] = (
                            "continuous_gaussian_copula_over_editor_descriptors"
                        )
                        candidates.append(candidate_payload)
    return candidates


def _common_root_samples(
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    latents: Mapping[str, float],
) -> tuple[list[tuple[int, str, float, Mapping[str, Any]]], int]:
    """Sample one stable periodic grid, independent of the selected L1 count."""

    minimum_spacing = _minimum_root_spacing(prior)
    grid_count = max(24, min(40, int(math.ceil(1.7 / minimum_spacing))))
    phase = float(latents["flow_phase"])
    regions = _candidate_regions(analysis)
    rows: list[tuple[int, str, float, Mapping[str, Any]]] = []
    for grid_index in range(grid_count):
        root_s = ((grid_index + 0.5) / grid_count + phase) % 1.0
        by_side: dict[str, list[Mapping[str, Any]]] = {}
        for region in regions:
            if any(
                float(start) - 1e-12 <= root_s <= float(end) + 1e-12
                for start, end in region["s_ranges"]
            ):
                by_side.setdefault(str(region["side_id"]), []).append(region)
        for side_id in sorted(by_side):
            region = max(
                by_side[side_id],
                key=lambda row: (
                    float(row["mean_clearance"]),
                    str(row["region_id"]),
                ),
            )
            rows.append((grid_index, side_id, root_s, region))
    return rows, grid_count


def _feedback_common_ordinary_candidates(
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    latents: Mapping[str, float],
    feedback_profile: Mapping[str, Any],
    curve_geometry_profile: Mapping[str, Any],
    branch_seed: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Generate one broad ordinary-L1 pool before cardinality selection."""

    base_length = float(
        prior["statistics"]["primary_geometry"]["chord_length_repeat"]["median"]
    )
    length_strata = tuple(
        float(value) for value in feedback_profile["length_strata"]
    )
    length_multiplier = float(feedback_profile["length_multiplier"])
    canvas_height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    backbone = _backbone_points(analysis)
    bow_distribution = curve_geometry_profile["observed_geometry"]["bow_ratio"]
    bow_lower = float(bow_distribution["q10"])
    bow_upper = float(bow_distribution["q90"])
    root_rows, grid_count = _common_root_samples(analysis, prior, latents)
    descriptor_sample_count = 6
    candidates: list[dict[str, Any]] = []
    side_indices = {"left_normal": 0, "right_normal": 1}

    for grid_index, side_id, root_s, region in root_rows:
        if side_id not in side_indices:
            raise GlobalL1FlowError(f"unknown attachment side: {side_id}")
        root, tangent = _sample_at_s(analysis, root_s)
        outward = _normal(tangent, side_id)
        for along_index, along_sign in enumerate((-1.0, 1.0)):
            along = _mul(tangent, along_sign)
            for stratum_index, length_scale in enumerate(length_strata):
                for sample_index in range(descriptor_sample_count):
                    stable_index = (
                        (
                            (
                                (
                                    grid_index * len(side_indices)
                                    + side_indices[side_id]
                                )
                                * 2
                                + along_index
                            )
                            * len(length_strata)
                            + stratum_index
                        )
                        * descriptor_sample_count
                        + sample_index
                        + 1
                    )
                    planned = (
                        base_length
                        * length_scale
                        * length_multiplier
                        * (0.94 + 0.06 * float(latents["openness"]))
                    )
                    (
                        descriptors,
                        descriptor_quantiles,
                        geometry_sample_id,
                        learned_actual_length,
                    ) = _continuous_editor_descriptors(
                        curve_geometry_profile,
                        str(analysis["prototype_id"]),
                        branch_seed,
                        stable_index,
                    )
                    if stratum_index == 0:
                        planned = min(
                            planned,
                            learned_actual_length,
                            float(
                                prior["statistics"]["primary_geometry"][
                                    "actual_length_repeat"
                                ]["min"]
                            ),
                        )
                    longitudinal = planned * (0.72 + 0.10 * stratum_index)
                    outward_reach = planned * (0.56 + 0.035 * stratum_index)
                    parent_departure = math.radians(
                        float(descriptors["parent_tangent_departure_deg"])
                    )
                    start_direction = _unit(
                        _add(
                            _mul(along, math.cos(parent_departure)),
                            _mul(outward, math.sin(parent_departure)),
                        ),
                        "common_editor_parent_local_start",
                    )
                    end_angle = float(descriptors["end_angle_chord_deg"])
                    normalized_end_angle = float(
                        descriptors["end_angle_normalized_deg"]
                    )
                    start_angle_abs = float(descriptors["start_angle_abs_deg"])
                    if abs(end_angle) > 1e-7:
                        orientation_sign = (
                            1.0 if normalized_end_angle / end_angle >= 0.0 else -1.0
                        )
                        chord_direction = _unit(
                            _rotate(
                                start_direction,
                                -math.radians(orientation_sign * start_angle_abs),
                            ),
                            "common_editor_chord",
                        )
                    else:
                        chord_options = [
                            _unit(
                                _rotate(
                                    start_direction,
                                    -math.radians(sign * start_angle_abs),
                                ),
                                "common_editor_chord",
                            )
                            for sign in (-1.0, 1.0)
                        ]
                        chord_direction = max(
                            chord_options,
                            key=lambda direction: _dot(direction, outward),
                        )
                    chord_length = math.hypot(longitudinal, outward_reach)
                    target = _add(root, _mul(chord_direction, chord_length))
                    terminal_direction = _unit(
                        _rotate(chord_direction, math.radians(end_angle)),
                        "common_editor_terminal",
                    )
                    start_arm = chord_length * float(
                        descriptors["start_handle_chord_ratio"]
                    )
                    end_arm = chord_length * float(
                        descriptors["end_handle_chord_ratio"]
                    )
                    segments = [
                        _segment(
                            root,
                            _add(root, _mul(start_direction, start_arm)),
                            _sub(target, _mul(terminal_direction, end_arm)),
                            target,
                        )
                    ]
                    points = _sample_segments(segments)
                    if any(
                        point[1] < 0.025 or point[1] > canvas_height - 0.025
                        for point in points
                    ):
                        continue
                    if any(
                        point[0] < -0.30 or point[0] > 1.30 for point in points
                    ):
                        continue
                    actual_length = _polyline_length(points)
                    bow_ratio = _bow_ratio(points)
                    bow_empirical_quantile = _empirical_cdf(
                        bow_distribution,
                        bow_ratio,
                    )
                    terminal_turn_degrees = _direction_turn_degrees(
                        start_direction,
                        terminal_direction,
                    )
                    start_chord_angle_error = abs(
                        _direction_turn_degrees(
                            start_direction,
                            chord_direction,
                        )
                        - start_angle_abs
                    )
                    inflection_count = _polyline_inflection_count(points)
                    vertical_span = max(point[1] for point in points) - min(
                        point[1] for point in points
                    )
                    excursion = _maximum_backbone_excursion(points, backbone)
                    flower_gap = _nearest_flower_gap(points, analysis)
                    if bow_lower <= bow_ratio <= bow_upper:
                        bow_score = 1.0
                    else:
                        bow_score = 1.0 - min(
                            1.0,
                            min(
                                abs(bow_ratio - bow_lower),
                                abs(bow_ratio - bow_upper),
                            )
                            / max(bow_upper - bow_lower, 0.03),
                        )
                    compact_score = 1.0 - min(
                        1.0,
                        abs(actual_length - planned) / max(planned * 0.45, 1e-9),
                    )
                    individual_score = (
                        0.75 * min(1.0, float(region["mean_clearance"]) / 0.30)
                        + 1.25 * abs(_dot(start_direction, tangent))
                        + 1.35 * bow_score
                        + 1.10 * compact_score
                        + (
                            1.0
                            if stratum_index == 1
                            else 0.45 if stratum_index == 2 else 0.0
                        )
                        - 0.35
                        * max(
                            0.0,
                            vertical_span
                            / float(feedback_profile["maximum_vertical_span"])
                            - 0.78,
                        )
                    )
                    side_code = "l" if side_id == "left_normal" else "r"
                    along_code = "f" if along_sign > 0.0 else "b"
                    candidate_id = (
                        f"l1_pool_r{grid_index:03d}_{side_code}_{along_code}_"
                        f"k{stratum_index}_q{sample_index:02d}"
                    )
                    candidate = _common_candidate_base(
                        candidate_id=candidate_id,
                        source_channel="editor_descriptor_distribution_sample",
                        side_id=side_id,
                        root_s=root_s,
                        root=root,
                        target=target,
                        segments=segments,
                        curvature_signature=(
                            "learned_reverse_end"
                            if end_angle < 0.0
                            else "learned_same_side_end"
                        ),
                        features={
                            "initial_tangent_alignment": abs(
                                _dot(start_direction, tangent)
                            ),
                            "initial_outward_alignment": _dot(
                                start_direction,
                                outward,
                            ),
                            "bow_ratio": bow_ratio,
                            "bow_empirical_quantile": bow_empirical_quantile,
                            "vertical_span": vertical_span,
                            "maximum_backbone_excursion": excursion,
                            "nearest_flower_gap": flower_gap,
                            "length_stratum": float(stratum_index),
                            "learned_actual_length_unit_ratio": (
                                learned_actual_length
                            ),
                            "editor_geometry_sample_index": stable_index,
                            "descriptor_mean_quantile": sum(
                                descriptor_quantiles.values()
                            )
                            / len(descriptor_quantiles),
                            **{
                                f"editor_{name}": value
                                for name, value in descriptors.items()
                            },
                            **{
                                f"editor_{name}_quantile": value
                                for name, value in descriptor_quantiles.items()
                            },
                            "terminal_turn_degrees": terminal_turn_degrees,
                            "editor_start_chord_angle_error_deg": (
                                start_chord_angle_error
                            ),
                            "inflection_count": float(inflection_count),
                            "planned_chord": _distance(root, target),
                        },
                        individual_score=individual_score,
                    )
                    candidate["pool_root_id"] = f"l1_pool_root_{grid_index:03d}"
                    candidate["editor_geometry_sample_id"] = geometry_sample_id
                    candidate["editor_geometry_source"] = (
                        "continuous_gaussian_copula_over_editor_descriptors"
                    )
                    candidates.append(candidate)
    return candidates, {
        "source": "count_independent_periodic_root_grid",
        "grid_count": grid_count,
        "eligible_root_side_count": len(root_rows),
        "descriptor_samples_per_root_side_direction_stratum": (
            descriptor_sample_count
        ),
        "depends_on_selected_l1_count": False,
    }


def _ordinary_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    latents: Mapping[str, float],
    feedback_profile: Mapping[str, Any] | None = None,
    curve_geometry_profile: Mapping[str, Any] | None = None,
    lane_count: int = 5,
    branch_seed: int = 0,
) -> list[dict[str, Any]]:
    if feedback_profile is not None:
        if curve_geometry_profile is None:
            raise GlobalL1FlowError(
                "editor-demonstrated curve geometry profile is required"
            )
        return _feedback_ordinary_candidates(
            slot,
            analysis,
            prior,
            latents,
            feedback_profile,
            curve_geometry_profile,
            lane_count,
            branch_seed,
        )
    primary_stats = prior["statistics"]["primary_geometry"]["chord_length_repeat"]
    if slot.role == "frontier":
        base_length = float(primary_stats["q75"])
    elif slot.role == "balance":
        base_length = 0.5 * (
            float(primary_stats["median"]) + float(primary_stats["q75"])
        )
    else:
        base_length = float(primary_stats["median"])
    length_scales = (0.90, 1.08)
    phase = float(latents["flow_phase"]) * (1.0 if slot.index % 2 == 0 else -1.0)
    canvas_height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    root_gap_median = float(
        prior["statistics"]["primary_root_rhythm"]["consecutive_mount_gap"]["median"]
    )
    candidates: list[dict[str, Any]] = []
    index = 0
    regions = _candidate_regions(analysis)
    total_region_span = sum(
        sum(float(end) - float(start) for start, end in region["s_ranges"])
        for region in regions
    )
    root_sample_count = max(10, 2 * lane_count)
    for region in regions:
        side_id = str(region["side_id"])
        for root_s in _region_s_values(
            region,
            phase,
            root_sample_count,
            total_region_span,
        ):
            root, tangent = _sample_at_s(analysis, root_s)
            outward = _normal(tangent, side_id)
            for along_sign in (-1.0, 1.0):
                for length_scale in length_scales:
                    index += 1
                    planned = (
                        base_length
                        * length_scale
                        * float(latents["openness"])
                        * (1.08 if slot.role == "frontier" else 1.0)
                    )
                    radial = min(0.36, max(0.20, planned * 0.68))
                    longitudinal = math.sqrt(max(planned * planned - radial * radial, 0.0144))
                    longitudinal *= along_sign * float(latents["sweep_amplitude"])
                    target = _add(
                        root,
                        _add(_mul(outward, radial), _mul(tangent, longitudinal)),
                    )
                    if not (0.035 <= target[1] <= canvas_height - 0.035):
                        continue
                    if not (-0.32 <= target[0] <= 1.32):
                        continue
                    start_direction = _unit(
                        _add(_mul(outward, 0.91), _mul(tangent, 0.18 * along_sign)),
                        "ordinary_start_direction",
                    )
                    terminal_direction = _unit(
                        _add(_mul(tangent, 0.78 * along_sign), _mul(outward, 0.34)),
                        "ordinary_terminal_direction",
                    )
                    chord = _distance(root, target)
                    entry_arm = chord * (0.28 + 0.05 * float(latents["curl_energy"]))
                    exit_arm = chord * (0.34 + 0.06 * float(latents["curl_energy"]))
                    if (slot.index + (1 if along_sign > 0 else 0)) % 2 == 0:
                        terminal_direction = _unit(
                            _add(_mul(terminal_direction, 0.72), _mul(outward, -0.46)),
                            "ordinary_s_terminal",
                        )
                        signature = "S"
                    else:
                        signature = "C"
                    segments = [
                        _hermite_segment(
                            root,
                            target,
                            start_direction,
                            terminal_direction,
                            entry_arm,
                            exit_arm,
                        )
                    ]
                    root_preference = 1.0 - min(
                        1.0, _periodic_delta(root_s, slot.preferred_s) / max(root_gap_median * 2.5, 0.20)
                    )
                    vertical_side = "upper" if target[1] < root[1] else "lower"
                    vertical_match = 1.0 if vertical_side == slot.preferred_vertical_side else 0.0
                    individual_score = (
                        3.0 * root_preference
                        + 1.4 * vertical_match
                        + 1.0 * float(region["mean_clearance"]) / 0.38
                        + (0.7 if signature == "S" else 0.45)
                    )
                    candidates.append(
                        _candidate_base(
                            candidate_id=f"{slot.slot_id}_dynamic_{index:03d}",
                            slot=slot,
                            source_channel="dynamic_prior_conditioned",
                            side_id=side_id,
                            root_s=root_s,
                            root=root,
                            target=target,
                            segments=segments,
                            flower_id=None,
                            curvature_signature=signature,
                            features={
                                "outward_alignment": _dot(start_direction, outward),
                                "root_preference": root_preference,
                                "vertical_match": vertical_match,
                                "planned_chord": chord,
                            },
                            individual_score=individual_score,
                        )
                    )
    return candidates


def _trough_s_values(analysis: Mapping[str, Any]) -> list[float]:
    troughs = [
        float(row["s"])
        for row in analysis["backbone"]["extrema"]
        if row["kind"] == "trough"
    ]
    if not troughs:
        raise GlobalL1FlowError("SW-1 support planning requires a detected trough")
    return troughs


def _sw1_support_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    latents: Mapping[str, float],
) -> list[dict[str, Any]]:
    if slot.flower_id is None:
        raise GlobalL1FlowError("SW-1 support slot has no flower id")
    flower = _flower_by_id(analysis, slot.flower_id)
    troughs = _trough_s_values(analysis)
    base_trough = min(
        troughs,
        key=lambda value: _periodic_delta(value, float(flower["nearest_backbone_s"])),
    )
    offsets = (-0.105, -0.075, -0.045, 0.045, 0.075, 0.105)
    candidates: list[dict[str, Any]] = []
    for index, offset in enumerate(offsets, start=1):
        signed_offset = offset + float(latents["flow_phase"]) * 0.35
        root_s = (base_trough + signed_offset) % 1.0
        root, tangent = _sample_at_s(analysis, root_s)
        target = _flower_boundary_toward(flower, root)
        direction = _unit(_sub(target, root), "sw1_support_direction")
        side_id, outward = _closest_side(tangent, direction)
        start_direction = _unit(
            _add(_mul(outward, 0.86), _mul(direction, 0.40)),
            "sw1_support_start",
        )
        center = _flower_center_near(flower, root[0])
        radial = _unit(_sub(target, center), "sw1_flower_radial")
        terminal_direction = _mul(radial, -1.0)
        chord = _distance(root, target)
        segments = [
            _hermite_segment(
                root,
                target,
                start_direction,
                terminal_direction,
                chord * 0.31,
                chord * 0.24,
            )
        ]
        trough_distance = _periodic_delta(root_s, base_trough)
        candidates.append(
            _candidate_base(
                candidate_id=f"{slot.slot_id}_sw1_{index:02d}",
                slot=slot,
                source_channel="prototype_morphology_rule",
                side_id=side_id,
                root_s=root_s,
                root=root,
                target=target,
                segments=segments,
                flower_id=slot.flower_id,
                curvature_signature="C",
                features={
                    "outward_alignment": _dot(start_direction, outward),
                    "trough_arc_distance": trough_distance,
                    "flower_contact_ellipse_value": _ellipse_value(
                        target,
                        center,
                        float(flower["rx"]),
                        float(flower["ry"]),
                    ),
                },
                individual_score=6.0 - 7.0 * trough_distance,
            )
        )
    return candidates


def _sw3_support_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    latents: Mapping[str, float],
) -> list[dict[str, Any]]:
    if slot.flower_id is None:
        raise GlobalL1FlowError("SW-3 support slot has no flower id")
    flower = _flower_by_id(analysis, slot.flower_id)
    nearest_s = float(flower["nearest_backbone_s"])
    distances = (0.335, 0.375, 0.415, 0.455)
    candidates: list[dict[str, Any]] = []
    index = 0
    for arc_direction in (-1.0, 1.0):
        for distance in distances:
            index += 1
            remote_distance = distance + float(latents["flow_phase"]) * 0.20
            root_s = (nearest_s + arc_direction * remote_distance) % 1.0
            root, tangent = _sample_at_s(analysis, root_s)
            center = _flower_center_near(flower, root[0])
            rx = float(flower["rx"])
            ry = float(flower["ry"])
            target = center[0], center[1] + ry
            horizontal_sign = -1.0 if root[0] <= center[0] else 1.0
            waypoint = (
                center[0] + horizontal_sign * (0.62 * rx + 0.035),
                center[1] + ry + 0.055,
            )
            toward_waypoint = _unit(_sub(waypoint, root), "sw3_waypoint_direction")
            side_id, outward = _closest_side(tangent, toward_waypoint)
            start_direction = _unit(
                _add(_mul(toward_waypoint, 0.92), _mul(outward, 0.16)),
                "sw3_support_start",
            )
            first_chord = _distance(root, waypoint)
            second_chord = _distance(waypoint, target)
            first = _hermite_segment(
                root,
                waypoint,
                start_direction,
                _unit(_sub(target, waypoint), "sw3_waypoint_exit"),
                first_chord * 0.33,
                first_chord * 0.12,
            )
            tangent_at_waypoint = _unit(_sub(target, waypoint), "sw3_second_start")
            second = _hermite_segment(
                waypoint,
                target,
                tangent_at_waypoint,
                (0.0, -1.0),
                max(0.035, second_chord * 0.42),
                max(0.025, second_chord * 0.28),
            )
            candidates.append(
                _candidate_base(
                    candidate_id=f"{slot.slot_id}_sw3_{index:02d}",
                    slot=slot,
                    source_channel="prototype_morphology_rule",
                    side_id=side_id,
                    root_s=root_s,
                    root=root,
                    target=target,
                    segments=[first, second],
                    flower_id=slot.flower_id,
                    curvature_signature="SC" if arc_direction < 0 else "CS",
                    features={
                        "outward_alignment": _dot(start_direction, outward),
                        "remote_mount_arc_distance": _periodic_delta(root_s, nearest_s),
                        "below_flower_waypoint_margin": waypoint[1] - (center[1] + ry),
                        "underside_contact_dx": abs(target[0] - center[0]),
                        "underside_contact_dy": abs(target[1] - (center[1] + ry)),
                    },
                    individual_score=8.0
                    - abs(_periodic_delta(root_s, nearest_s) - 0.395) * 8.0,
                )
            )
    return candidates


def _fixed_warp_candidates(
    slot: Slot,
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    seed: int,
    enabled: bool | None = None,
) -> list[dict[str, Any]]:
    if enabled is None:
        enabled = analysis["prototype_id"] == "proto_sw_1_3"
    if not enabled:
        return []
    templates = prior["paired_primary_templates"][str(seed)]
    if slot.flower_id is None:
        applicable = [
            row for row in templates if row["kind"] != "flower"
        ]
        applicable.sort(key=lambda row: float(row["mount_s"]))
        ordinary_index = int(slot.slot_id.split("_")[-1]) - 1
        if ordinary_index >= len(applicable):
            return []
        applicable = [applicable[ordinary_index]]
    else:
        applicable = [
            row
            for row in templates
            if row["kind"] == "flower" and row["target_flower_id"] == slot.flower_id
        ]
    candidates: list[dict[str, Any]] = []
    for template in applicable:
        source_segments = template["cubics"]
        root = _point(source_segments[0]["p0"], "fixed_template.p0")
        target = _point(source_segments[-1]["p3"], "fixed_template.p3")
        root_s = float(template["mount_s"])
        _, tangent = _sample_at_s(analysis, root_s)
        direction = _unit(_sub(target, root), "fixed_warp_direction")
        side_id, outward = _closest_side(tangent, direction)
        source_p1 = _point(source_segments[0]["p1"], "fixed_template.p1")
        source_arm = max(0.065, _distance(root, source_p1))
        corrected_start = _unit(
            _add(_mul(outward, 0.90), _mul(direction, 0.24)),
            "fixed_warp_corrected_start",
        )
        segments = [
            {
                key: list(values)
                for key, values in source_segment.items()
            }
            for source_segment in source_segments
        ]
        segments[0]["p1"] = _round_point(_add(root, _mul(corrected_start, source_arm)))
        candidates.append(
            _candidate_base(
                candidate_id=f'{slot.slot_id}_fixed_warp_{template["curve_id"]}',
                slot=slot,
                source_channel="fixed_warp_visual_prior",
                side_id=side_id,
                root_s=root_s,
                root=root,
                target=target,
                segments=segments,
                flower_id=slot.flower_id,
                curvature_signature="fixed_derived",
                features={
                    "outward_alignment": _dot(corrected_start, outward),
                    "source_template_mount_s": root_s,
                    "initial_handle_changed_only": 1.0,
                },
                individual_score=7.0,
            )
        )
    return candidates


def _backbone_points(analysis: Mapping[str, Any]) -> list[Point]:
    return [_point(row["point"], "backbone.point") for row in analysis["backbone"]["samples"]]


def _ordinary_flower_intrusion(
    centerline: Sequence[Point],
    analysis: Mapping[str, Any],
) -> bool:
    for flower in analysis["flowers"]:
        rx = float(flower["protection_rx"])
        ry = float(flower["protection_ry"])
        for point in centerline[3:]:
            center = _flower_center_near(flower, point[0])
            if _ellipse_value(point, center, rx, ry) < 1.0:
                return True
    return False


def _support_flower_intrusion(
    centerline: Sequence[Point],
    analysis: Mapping[str, Any],
    target_flower_id: str,
) -> bool:
    for flower in analysis["flowers"]:
        rx = float(flower["protection_rx"])
        ry = float(flower["protection_ry"])
        limit = int(len(centerline) * 0.72) if flower["flower_id"] == target_flower_id else len(centerline)
        for point in centerline[:limit]:
            center = _flower_center_near(flower, point[0])
            if _ellipse_value(point, center, rx, ry) < 1.0:
                return True
    return False


def _backbone_non_root_clearance(
    centerline: Sequence[Point],
    backbone: Sequence[Point],
) -> float:
    start = max(4, int(len(centerline) * 0.16))
    minimum = float("inf")
    point_array = np.asarray(centerline[start:], dtype=np.float64)
    backbone_array = np.asarray(backbone, dtype=np.float64)
    for offset in (-1.0, 0.0, 1.0):
        shifted = backbone_array + np.asarray([offset, 0.0], dtype=np.float64)
        matrix = point_segment_distance_matrix_batch(
            point_array,
            shifted[:-1],
            shifted[1:],
        )
        if matrix.size:
            minimum = min(minimum, float(matrix.min()))
    return minimum


def _flower_mount_rejections(
    candidate: Mapping[str, Any],
    flower_mount_plan: Mapping[str, Any],
    prior: Mapping[str, Any],
    curve_geometry_profile: Mapping[str, Any] | None = None,
) -> list[str]:
    """Test an ordinary candidate against flower geometry frozen upstream."""

    reasons: list[str] = []
    root_spacing = _minimum_root_spacing(prior)
    lane_clearance = _minimum_lane_clearance(
        prior,
        curve_geometry_profile,
    )
    candidate_points = [
        _point(point, "candidate.centerline")
        for point in candidate["centerline"]
    ]
    for mount in flower_mount_plan.get("mounts", []):
        if _periodic_delta(
            float(candidate["root_s"]),
            float(mount["root_s"]),
        ) < root_spacing:
            reasons.append("ordinary_root_conflicts_with_frozen_flower_support")
            break
    for mount in flower_mount_plan.get("mounts", []):
        mount_points = [
            _point(point, "flower_mount.centerline")
            for point in mount["centerline"]
        ]
        minimum = min(
            global_l1_polyline_distance_batch(
                candidate_points,
                mount_points,
                offset,
            )
            for offset in (-1.0, 0.0, 1.0)
        )
        if minimum < lane_clearance:
            reasons.append("ordinary_curve_conflicts_with_frozen_flower_support")
            break
    return reasons


def _output_geometry_rejections(
    segments: Sequence[Mapping[str, Sequence[float]]],
    analysis: Mapping[str, Any],
) -> list[str]:
    """Check the Stage-4 output polyline before selecting an ordinary L1.

    Keep the original planning samples and scores. Safety uses the 36-step
    output samples and their root-prefix semantics, so resampling cannot
    enlarge the exempt region or hide crossings between sample points.
    """
    points = [tuple(round(v, 9) for v in p) for p in _sample_segments(segments, 36)]
    start = max(4, int(len(points) * 0.16))
    backbone = _backbone_points(analysis)
    reasons: list[str] = []
    if any(_polylines_cross(points[start:], backbone, shift) for shift in (-1.0, 0.0, 1.0)):
        reasons.append("output_l1_non_root_backbone_crossing")
    if _ordinary_flower_intrusion(points, analysis):
        reasons.append("output_l1_enters_flower_reserve")
    return reasons


def _candidate_rejections(
    candidate: Mapping[str, Any],
    analysis: Mapping[str, Any],
    family_id: str,
    prior: Mapping[str, Any],
    feedback_profile: Mapping[str, Any] | None = None,
    flower_mount_plan: Mapping[str, Any] | None = None,
    curve_geometry_profile: Mapping[str, Any] | None = None,
    flower_mount_mechanism: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    centerline = [_point(point, "candidate.centerline") for point in candidate["centerline"]]
    root = _point(candidate["root"], "candidate.root")
    target = _point(candidate["target"], "candidate.target")
    _, tangent = _sample_at_s(analysis, float(candidate["root_s"]))
    outward = _normal(tangent, str(candidate["side_id"]))
    initial = _unit(_sub(centerline[1], centerline[0]), "candidate.initial")
    if feedback_profile is None:
        if _dot(initial, outward) < 0.72:
            reasons.append("ordinary_or_support_initial_departure_not_outward")
    else:
        tangent_alignment = abs(_dot(initial, tangent))
        outward_alignment = _dot(initial, outward)
        if tangent_alignment < float(
            feedback_profile["minimum_initial_tangent_alignment"]
        ):
            reasons.append("feedback_lane_does_not_start_tangentially")
        if outward_alignment < float(
            feedback_profile["minimum_initial_outward_alignment"]
        ):
            reasons.append("feedback_lane_initially_turns_inward")

    canvas_height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    if not (0.0 <= target[1] <= canvas_height):
        reasons.append("target_outside_vertical_canvas")
    if not (-0.34 <= target[0] <= 1.34):
        reasons.append("target_outside_periodic_review_window")

    backbone_clearance = _backbone_non_root_clearance(
        centerline,
        _backbone_points(analysis),
    )
    if backbone_clearance < 0.012:
        reasons.append("non_root_backbone_crossing_or_contact")

    role = str(candidate["role"])
    flower_id = candidate.get("flower_id")
    if flower_id is None:
        reasons.extend(_output_geometry_rejections(candidate["segments"], analysis))
        if _ordinary_flower_intrusion(centerline, analysis):
            reasons.append("ordinary_lane_enters_flower_reserve")
    else:
        if _support_flower_intrusion(centerline, analysis, str(flower_id)):
            reasons.append("support_lane_enters_flower_reserve_before_terminal_approach")
    if flower_id is None and flower_mount_plan is not None:
        reasons.extend(
            _flower_mount_rejections(
                candidate,
                flower_mount_plan,
                prior,
                curve_geometry_profile,
            )
        )

    if feedback_profile is not None and candidate.get(
        "editor_geometry_source"
    ) != "continuous_gaussian_copula_over_editor_descriptors":
        reasons.append("continuous_editor_geometry_source_missing")

    self_clearance = min(
        global_l1_polyline_distance_batch(centerline, centerline, -1.0),
        global_l1_polyline_distance_batch(centerline, centerline, 1.0),
    )
    if self_clearance < 0.032:
        reasons.append("periodic_self_conflict")

    if (
        feedback_profile is None
        and (
            flower_mount_mechanism == "valley_flank_support"
            if flower_mount_mechanism is not None
            else family_id == "SW-1_valley_filling"
        )
        and role == "flower_support"
    ):
        trough_distance = float(candidate["features"].get("trough_arc_distance", 1.0))
        if trough_distance > 0.14:
            reasons.append("sw1_support_not_from_trough_flank")
    if (
        feedback_profile is None
        and (
            flower_mount_mechanism == "remote_tangent_underside"
            if flower_mount_mechanism is not None
            else family_id == "SW-3_tangent_terminal"
        )
        and role == "terminal_flower_support"
    ):
        remote = float(candidate["features"].get("remote_mount_arc_distance", -1.0))
        if not 0.30 <= remote <= 0.48:
            reasons.append("sw3_support_mount_not_remote")
        if float(candidate["features"].get("below_flower_waypoint_margin", -1.0)) < 0.035:
            reasons.append("sw3_support_does_not_route_below_flower")
        if float(candidate["features"].get("underside_contact_dx", 1.0)) > 0.01:
            reasons.append("sw3_support_wrong_horizontal_contact")
        if float(candidate["features"].get("underside_contact_dy", 1.0)) > 0.01:
            reasons.append("sw3_support_wrong_vertical_contact")

    minimum_length = float(
        prior["statistics"]["primary_geometry"]["actual_length_repeat"]["min"]
    ) * 0.72
    if float(candidate["planning_length"]) < minimum_length:
        reasons.append("lane_shorter_than_visual_prior_floor")
    return reasons


def _pair_metrics(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    root_spacing: float,
    lane_clearance: float,
    curve_geometry_profile: Mapping[str, Any] | None = None,
    known_separated_clearance: float | None = None,
) -> tuple[bool, float, dict[str, float]]:
    root_gap = _periodic_delta(float(a["root_s"]), float(b["root_s"]))
    if root_gap < root_spacing:
        return False, 0.0, {"root_gap": root_gap, "minimum_clearance": 0.0}
    points_a = [_point(point, "lane_a.centerline") for point in a["centerline"]]
    points_b = [_point(point, "lane_b.centerline") for point in b["centerline"]]
    minimum = (
        float(known_separated_clearance)
        if known_separated_clearance is not None
        else min(
            global_l1_polyline_distance_batch(points_a, points_b, offset)
            for offset in (-1.0, 0.0, 1.0)
        )
    )
    # _polyline_distance delegates to _segment_distance, which returns zero
    # for every crossing/contact.  A second all-segment crossing pass would
    # repeat the same hard test for every conflict-graph edge.
    if minimum < lane_clearance:
        return False, 0.0, {"root_gap": root_gap, "minimum_clearance": minimum}

    direction_a = _unit(_sub(points_a[-1], points_a[-4]), "lane_a_terminal")
    direction_b = _unit(_sub(points_b[-1], points_b[-4]), "lane_b_terminal")
    alignment = abs(_dot(direction_a, direction_b))
    co_travel = parallel_co_travel_score(points_a, points_b)
    co_travel_soft_limit = 1.0
    co_travel_hard_limit = 1.0
    co_travel_penalty = 0.0
    clearance_penalty = 0.0
    if curve_geometry_profile is not None:
        # Co-travel is a continuous composition cost. Safety still comes from
        # the crossing/clearance predicate above, not sparse score quantiles.
        co_travel_soft_limit = 0.0
        co_travel_hard_limit = 1.0
        co_travel_penalty = co_travel
        clearance_penalty = max(
            0.0,
            (lane_clearance - minimum) / max(lane_clearance, 1e-9),
        )
    glide = 0.0
    if lane_clearance <= minimum <= 0.16 and alignment >= 0.72:
        glide = alignment * (1.0 - abs(minimum - 0.085) / 0.075)
    spacing_score = 1.0 - min(1.0, abs(root_gap - 0.13) / 0.13)
    glide_reward = 0.9 * glide if curve_geometry_profile is None else 0.0
    pair_score = (
        glide_reward
        + 0.35 * spacing_score
        - 0.9 * co_travel_penalty
        - 0.45 * clearance_penalty
    )
    return True, pair_score, {
        "root_gap": root_gap,
        "minimum_clearance": minimum,
        "terminal_alignment": alignment,
        "parallel_glide": glide,
        "parallel_glide_reward_applied": glide_reward,
        "parallel_co_travel_score": co_travel,
        "parallel_co_travel_soft_limit": co_travel_soft_limit,
        "parallel_co_travel_hard_limit": co_travel_hard_limit,
        "parallel_co_travel_penalty": co_travel_penalty,
        "editor_stroke_clearance_soft_limit": lane_clearance,
        "editor_stroke_clearance_penalty": clearance_penalty,
        "curve_crossing_count": 0.0,
    }


def _global_score(
    lanes: Sequence[Mapping[str, Any]],
    feedback_profile: Mapping[str, Any] | None = None,
    curve_geometry_profile: Mapping[str, Any] | None = None,
) -> tuple[float, dict[str, float]]:
    roots = sorted(float(lane["root_s"]) for lane in lanes)
    root_gaps = [
        roots[index] - roots[index - 1]
        for index in range(1, len(roots))
    ] + [1.0 - roots[-1] + roots[0]]
    root_gap_mean = sum(root_gaps) / len(root_gaps)
    root_gap_variance = sum((gap - root_gap_mean) ** 2 for gap in root_gaps) / len(root_gaps)
    root_coverage = 1.0 - max(root_gaps)

    target_bins = {
        (
            int(math.floor((_point(lane["target"], "lane.target")[0] % 1.0) * 4.0)),
            0 if _point(lane["target"], "lane.target")[1] < _point(lane["root"], "lane.root")[1] else 1,
        )
        for lane in lanes
    }
    target_coverage = len(target_bins) / min(len(lanes), 8)
    lengths = [float(lane["planning_length"]) for lane in lanes]
    length_mean = sum(lengths) / len(lengths)
    length_variance = sum((value - length_mean) ** 2 for value in lengths) / len(lengths)
    length_rhythm = min(1.0, math.sqrt(length_variance) / max(length_mean * 0.32, 1e-9))
    source_channels = Counter(str(lane["source_channel"]) for lane in lanes)
    fixed_prior_presence = 1.0 if source_channels["fixed_warp_visual_prior"] else 0.0
    if feedback_profile is not None:
        if curve_geometry_profile is None:
            raise GlobalL1FlowError(
                "global feedback scoring lacks editor curve geometry"
            )
        bow_distribution = curve_geometry_profile["observed_geometry"][
            "bow_ratio"
        ]
        bow_lower = float(bow_distribution["q10"])
        bow_upper = float(bow_distribution["q90"])
        bow_scores = [
            (
                1.0
                if bow_lower <= float(lane["features"]["bow_ratio"]) <= bow_upper
                else 1.0
                - min(
                    1.0,
                    min(
                        abs(float(lane["features"]["bow_ratio"]) - bow_lower),
                        abs(float(lane["features"]["bow_ratio"]) - bow_upper),
                    )
                    / max(bow_upper - bow_lower, 0.03),
                )
            )
            for lane in lanes
        ]
        tangent_alignment = sum(
            float(lane["features"]["initial_tangent_alignment"])
            for lane in lanes
        ) / len(lanes)
        root_rhythm_fidelity = sum(
            float(lane["features"]["root_preference"]) for lane in lanes
        ) / len(lanes)
        vertical_compactness = 1.0 - min(
            1.0,
            sum(float(lane["features"]["vertical_span"]) for lane in lanes)
            / len(lanes)
            / float(feedback_profile["maximum_vertical_span"]),
        )
        excursion_compactness = 1.0 - min(
            1.0,
            sum(
                float(lane["features"]["maximum_backbone_excursion"])
                for lane in lanes
            )
            / len(lanes)
            / float(feedback_profile["maximum_backbone_excursion"]),
        )
        length_strata_coverage = len(
            {
                int(round(float(lane["features"]["length_stratum"])))
                for lane in lanes
            }
        ) / 3.0
        target_fractions = [
            float(value)
            for value in feedback_profile["length_stratum_target_fractions"]
        ]
        actual_fractions = [
            sum(
                int(round(float(lane["features"]["length_stratum"]))) == index
                for lane in lanes
            )
            / len(lanes)
            for index in range(3)
        ]
        length_strata_mix = 1.0 - 0.5 * sum(
            abs(actual - target)
            for actual, target in zip(actual_fractions, target_fractions)
        )
        motion_signature_coverage = min(
            1.0,
            len({str(lane["curvature_signature"]) for lane in lanes}) / 2.0,
        )
        geometry_sample_coverage = len(
            {
                int(lane["features"]["editor_geometry_sample_index"])
                for lane in lanes
            }
        ) / len(lanes)
        uniform_targets = [
            (index + 0.5) / len(lanes) for index in range(len(lanes))
        ]

        def distribution_match(feature_name: str) -> float:
            observed = sorted(
                float(lane["features"][feature_name]) for lane in lanes
            )
            return max(
                0.0,
                1.0
                - 2.0
                * sum(
                    abs(value - target)
                    for value, target in zip(observed, uniform_targets)
                )
                / len(observed),
            )

        control_descriptor_distribution_match = sum(
            distribution_match(feature_name)
            for feature_name in (
                "editor_start_handle_chord_ratio_quantile",
                "editor_end_handle_chord_ratio_quantile",
                "editor_start_angle_abs_deg_quantile",
                "editor_end_angle_normalized_deg_quantile",
            )
        ) / 4.0
        bow_distribution_match = distribution_match(
            "bow_empirical_quantile"
        )
        bow_mean = sum(
            float(lane["features"]["bow_ratio"]) for lane in lanes
        ) / len(lanes)
        bow_spread = min(
            1.0,
            math.sqrt(
                sum(
                    (float(lane["features"]["bow_ratio"]) - bow_mean) ** 2
                    for lane in lanes
                )
                / len(lanes)
            )
            / max(
                float(bow_distribution["q75"])
                - float(bow_distribution["q25"]),
                0.03,
            ),
        )
        flower_proximity = sum(
            1.0 / (1.0 + 2.0 * float(lane["features"]["nearest_flower_gap"]))
            for lane in lanes
        ) / len(lanes)
        bow_fidelity = sum(bow_scores) / len(bow_scores)
        score = (
            2.5 * root_coverage
            + 2.0 * root_rhythm_fidelity
            + 1.2 * target_coverage
            + 1.0 * length_rhythm
            + 0.7 * length_strata_coverage
            + 1.8 * length_strata_mix
            + 1.5 * bow_fidelity
            + 0.7 * bow_spread
            + 0.8 * motion_signature_coverage
            + 2.5 * geometry_sample_coverage
            + 1.4 * control_descriptor_distribution_match
            + 2.4 * bow_distribution_match
            + 1.4 * tangent_alignment
            + 1.15 * vertical_compactness
            + 1.15 * excursion_compactness
            + 0.45 * flower_proximity
        )
        return score, {
            "root_coverage": root_coverage,
            "root_rhythm_fidelity": root_rhythm_fidelity,
            "target_zone_coverage": target_coverage,
            "length_rhythm": length_rhythm,
            "length_strata_coverage": length_strata_coverage,
            "length_strata_mix": length_strata_mix,
            "bow_fidelity": bow_fidelity,
            "bow_spread": bow_spread,
            "motion_signature_coverage": motion_signature_coverage,
            "geometry_sample_coverage": geometry_sample_coverage,
            "control_descriptor_distribution_match": (
                control_descriptor_distribution_match
            ),
            "bow_distribution_match": bow_distribution_match,
            "initial_tangent_alignment": tangent_alignment,
            "vertical_compactness": vertical_compactness,
            "backbone_excursion_compactness": excursion_compactness,
            "soft_flower_proximity": flower_proximity,
            "fixed_prior_channel_present": 0.0,
        }
    score = (
        4.0 * root_coverage
        + 3.0 * target_coverage
        + 1.6 * length_rhythm
        + 0.8 * fixed_prior_presence
        + min(1.0, math.sqrt(root_gap_variance) / 0.055)
    )
    return score, {
        "root_coverage": root_coverage,
        "target_zone_coverage": target_coverage,
        "length_rhythm": length_rhythm,
        "root_gap_variation": math.sqrt(root_gap_variance),
        "fixed_prior_channel_present": fixed_prior_presence,
    }


def _balanced_feedback_solver_pool(
    ranked_pool: Sequence[Mapping[str, Any]],
    expansion_cap: int,
    slot_index: int,
) -> list[Mapping[str, Any]]:
    """Admit root-, continuous-shape-, and length-diverse rows to the beam."""

    by_root: dict[
        float,
        dict[tuple[int, int], list[Mapping[str, Any]]],
    ] = {}
    for candidate in ranked_pool:
        root_key = round(float(candidate["root_s"]), 9)
        geometry_sample_index = int(
            candidate["features"]["editor_geometry_sample_index"]
        )
        length_stratum = int(
            round(float(candidate["features"]["length_stratum"]))
        )
        by_root.setdefault(root_key, {}).setdefault(
            (geometry_sample_index, length_stratum),
            [],
        ).append(candidate)
    root_order = sorted(
        by_root,
        key=lambda root: (
            -max(
                float(candidate["individual_score"])
                for rows in by_root[root].values()
                for candidate in rows
            ),
            root,
        ),
    )
    pool: list[Mapping[str, Any]] = []
    round_index = 0
    while len(pool) < expansion_cap:
        added = False
        for root_position, root in enumerate(root_order):
            groups = by_root[root]
            group_keys = sorted(groups)
            if not group_keys:
                continue
            start = (
                root_position + slot_index + round_index
            ) % len(group_keys)
            for offset in range(len(group_keys)):
                group_key = group_keys[(start + offset) % len(group_keys)]
                rows = groups[group_key]
                if rows:
                    pool.append(rows.pop(0))
                    added = True
                    break
            if len(pool) >= expansion_cap:
                break
        if not added:
            break
        round_index += 1
    return pool


def _solve(
    slots: Sequence[Slot],
    candidate_pools: Mapping[str, Sequence[Mapping[str, Any]]],
    prior: Mapping[str, Any],
    feedback_profile: Mapping[str, Any] | None = None,
    curve_geometry_profile: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root_spacing = _minimum_root_spacing(prior)
    lane_clearance = _minimum_lane_clearance(
        prior,
        curve_geometry_profile,
    )
    beam_capacity = 36 * len(slots) ** 2
    expansion_cap = 4 * len(slots) + 4
    pair_cache: dict[tuple[str, str], tuple[bool, float, dict[str, float]]] = {}
    solver_pools: dict[str, list[Mapping[str, Any]]] = {}
    feasibility_pools: dict[str, list[Mapping[str, Any]]] = {}
    for slot in slots:
        ranked_pool = sorted(
            candidate_pools[slot.slot_id],
            key=lambda row: (-float(row["individual_score"]), str(row["candidate_id"])),
        )
        if feedback_profile is not None:
            pool = _balanced_feedback_solver_pool(
                ranked_pool,
                expansion_cap,
                slot.index,
            )
        else:
            pool = ranked_pool[:expansion_cap]
        if not pool:
            raise GlobalL1FlowError(f"slot {slot.slot_id} has no feasible candidates")
        solver_pools[slot.slot_id] = pool
        feasibility_pools[slot.slot_id] = (
            _balanced_feedback_solver_pool(
                ranked_pool,
                len(ranked_pool),
                slot.index,
            )
            if feedback_profile is not None
            else ranked_pool
        )

    def pair_result(
        candidate: Mapping[str, Any],
        existing: Mapping[str, Any],
    ) -> tuple[bool, float, dict[str, float]]:
        key = tuple(
            sorted(
                (
                    str(candidate["candidate_id"]),
                    str(existing["candidate_id"]),
                )
            )
        )
        if key not in pair_cache:
            pair_cache[key] = _pair_metrics(
                candidate,
                existing,
                root_spacing,
                lane_clearance,
                curve_geometry_profile,
            )
        return pair_cache[key]

    root_feasibility_nodes = 0
    curve_feasibility_nodes = 0
    root_groups: dict[
        str,
        list[tuple[float, list[Mapping[str, Any]]]],
    ] = {}
    for slot in slots:
        grouped: dict[float, list[Mapping[str, Any]]] = {}
        for candidate in feasibility_pools[slot.slot_id]:
            root_key = round(float(candidate["root_s"]), 9)
            grouped.setdefault(root_key, []).append(candidate)
        root_groups[slot.slot_id] = list(grouped.items())

    selected_roots: dict[str, float] = {}
    selected_root_domains: dict[str, list[Mapping[str, Any]]] = {}

    def find_curve_assignment() -> list[Mapping[str, Any]] | None:
        nonlocal curve_feasibility_nodes
        selected: dict[str, Mapping[str, Any]] = {}

        def search_curves(
            remaining_slots: tuple[Slot, ...],
        ) -> list[Mapping[str, Any]] | None:
            nonlocal curve_feasibility_nodes
            if not remaining_slots:
                return [selected[slot.slot_id] for slot in slots]
            selected_values = tuple(selected.values())
            viable_by_slot: dict[str, list[Mapping[str, Any]]] = {}
            for slot in remaining_slots:
                viable: list[Mapping[str, Any]] = []
                for candidate in selected_root_domains[slot.slot_id]:
                    curve_feasibility_nodes += 1
                    if all(
                        pair_result(candidate, existing)[0]
                        for existing in selected_values
                    ):
                        viable.append(candidate)
                if not viable:
                    return None
                viable_by_slot[slot.slot_id] = viable
            slot = min(
                remaining_slots,
                key=lambda row: (
                    len(viable_by_slot[row.slot_id]),
                    row.index,
                ),
            )
            next_remaining = tuple(
                row
                for row in remaining_slots
                if row.slot_id != slot.slot_id
            )
            for candidate in viable_by_slot[slot.slot_id]:
                selected[slot.slot_id] = candidate
                result = search_curves(next_remaining)
                if result is not None:
                    return result
                del selected[slot.slot_id]
            return None

        return search_curves(tuple(slots))

    def find_root_assignment(
        remaining_slots: tuple[Slot, ...],
    ) -> list[Mapping[str, Any]] | None:
        nonlocal root_feasibility_nodes
        if not remaining_slots:
            return find_curve_assignment()
        viable_by_slot: dict[
            str,
            list[tuple[float, list[Mapping[str, Any]]]],
        ] = {}
        for slot in remaining_slots:
            viable = []
            for root_s, candidates in root_groups[slot.slot_id]:
                root_feasibility_nodes += 1
                if all(
                    _periodic_delta(root_s, other) >= root_spacing
                    for other in selected_roots.values()
                ):
                    viable.append((root_s, candidates))
            if not viable:
                return None
            viable_by_slot[slot.slot_id] = viable
        slot = min(
            remaining_slots,
            key=lambda row: (
                len(viable_by_slot[row.slot_id]),
                row.index,
            ),
        )
        next_remaining = tuple(
            row for row in remaining_slots if row.slot_id != slot.slot_id
        )
        for root_s, candidates in viable_by_slot[slot.slot_id]:
            selected_roots[slot.slot_id] = root_s
            selected_root_domains[slot.slot_id] = candidates
            result = find_root_assignment(next_remaining)
            if result is not None:
                return result
            del selected_roots[slot.slot_id]
            del selected_root_domains[slot.slot_id]
        return None

    feasibility_witness = find_root_assignment(tuple(slots))
    if feasibility_witness is None:
        raise GlobalL1FlowError(
            "global candidate pool has no complete compatible assignment"
        )
    for slot, witness_candidate in zip(slots, feasibility_witness):
        pool = solver_pools[slot.slot_id]
        witness_id = str(witness_candidate["candidate_id"])
        if not any(
            str(candidate["candidate_id"]) == witness_id
            for candidate in pool
        ):
            if len(pool) >= expansion_cap:
                pool[-1] = witness_candidate
            else:
                pool.append(witness_candidate)

    states = [BeamState(lanes=[], score=0.0)]
    witness_prefix_preservation_count = 0
    for slot_index, slot in enumerate(slots):
        pool = solver_pools[slot.slot_id]
        expanded: list[BeamState] = []
        for state in states:
            for candidate in pool:
                pair_score = 0.0
                compatible = True
                for existing in state.lanes:
                    valid, score, _ = pair_result(candidate, existing)
                    if not valid:
                        compatible = False
                        break
                    pair_score += score
                if compatible:
                    expanded.append(
                        BeamState(
                            lanes=state.lanes + [dict(candidate)],
                            score=state.score
                            + float(candidate["individual_score"])
                            + pair_score,
                        )
                    )
        if not expanded:
            raise GlobalL1FlowError(
                f"single forward global solve became infeasible at slot {slot.slot_id}"
            )
        expanded.sort(
            key=lambda state: (
                -state.score,
                tuple(str(row["candidate_id"]) for row in state.lanes),
            )
        )
        states = expanded[:beam_capacity]
        witness_signature = tuple(
            str(candidate["candidate_id"])
            for candidate in feasibility_witness[: slot_index + 1]
        )
        if not any(
            tuple(str(row["candidate_id"]) for row in state.lanes)
            == witness_signature
            for state in states
        ):
            witness_state = next(
                state
                for state in expanded
                if tuple(
                    str(row["candidate_id"]) for row in state.lanes
                )
                == witness_signature
            )
            if len(states) < beam_capacity:
                states.append(witness_state)
            else:
                states[-1] = witness_state
            witness_prefix_preservation_count += 1

    ranked: list[tuple[float, BeamState, dict[str, float]]] = []
    for state in states:
        global_value, global_features = _global_score(
            state.lanes,
            feedback_profile,
            curve_geometry_profile,
        )
        ranked.append((state.score + global_value, state, global_features))
    ranked.sort(
        key=lambda row: (
            -row[0],
            tuple(str(lane["candidate_id"]) for lane in row[1].lanes),
        )
    )
    total_score, selected_state, global_features = ranked[0]
    selected = sorted(selected_state.lanes, key=lambda row: float(row["root_s"]))

    pair_rows: list[dict[str, Any]] = []
    for index, lane in enumerate(selected):
        for other in selected[index + 1 :]:
            key = tuple(sorted((str(lane["candidate_id"]), str(other["candidate_id"]))))
            valid, score, metrics = pair_cache.get(
                key,
                _pair_metrics(
                    lane,
                    other,
                    root_spacing,
                    lane_clearance,
                    curve_geometry_profile,
                ),
            )
            if not valid:
                raise GlobalL1FlowError("selected global state contains a hard pair conflict")
            pair_rows.append(
                {
                    "candidate_ids": list(key),
                    "pair_score": round(score, 9),
                    **{name: round(value, 9) for name, value in metrics.items()},
                }
            )
    solver: dict[str, Any] = {
        "solver": "deterministic_seeded_global_beam_set_solver",
        "beam_capacity": beam_capacity,
        "expansion_cap_per_slot": expansion_cap,
        "root_spacing_hard": round(root_spacing, 9),
        "lane_clearance_hard": round(lane_clearance, 9),
        "terminal_state_count": len(states),
        "exact_feasibility_node_count": (
            root_feasibility_nodes + curve_feasibility_nodes
        ),
        "root_feasibility_node_count": root_feasibility_nodes,
        "curve_feasibility_node_count": curve_feasibility_nodes,
        "witness_prefix_preservation_count": (
            witness_prefix_preservation_count
        ),
        "selected_total_score": round(total_score, 9),
        "global_features": {key: round(value, 9) for key, value in global_features.items()},
        "selected_pair_metrics": pair_rows,
        "exact_editor_geometry_exemplar_reuse": False,
    }
    return selected, solver


def _common_set_score(
    lanes: Sequence[Mapping[str, Any]],
    *,
    analysis: Mapping[str, Any],
    preferred_total_count: int | None,
    support_count: int | None,
    support_roots: Sequence[float],
    root_spacing: float,
    prototype_strategy: Mapping[str, Any] | None = None,
) -> tuple[float, dict[str, float]]:
    """Score only the low-dimensional structural baseline owned by R4."""

    if not lanes:
        raise GlobalL1FlowError("cannot score an empty ordinary L1 set")
    ordinary_roots = sorted(float(lane["root_s"]) % 1.0 for lane in lanes)
    flower_markers = [
        float(flower["nearest_backbone_s"]) % 1.0
        for flower in analysis["flowers"]
    ]
    coverage_markers = sorted(
        {
            round(value % 1.0, 9)
            for value in (*ordinary_roots, *support_roots, *flower_markers)
        }
    )
    coverage_gaps = [
        coverage_markers[index] - coverage_markers[index - 1]
        for index in range(1, len(coverage_markers))
    ] + [1.0 - coverage_markers[-1] + coverage_markers[0]]
    root_coverage = 1.0 - max(coverage_gaps)

    selected_markers = sorted(
        {round(value % 1.0, 9) for value in (*ordinary_roots, *support_roots)}
    )
    selected_gaps = [
        selected_markers[index] - selected_markers[index - 1]
        for index in range(1, len(selected_markers))
    ] + [1.0 - selected_markers[-1] + selected_markers[0]]
    minimum_gap = min(selected_gaps)
    cluster_relief = min(
        1.0,
        max(0.0, minimum_gap - root_spacing)
        / max(root_spacing * 0.60, 1e-9),
    )

    lengths = [float(lane["planning_length"]) for lane in lanes]
    length_mean = sum(lengths) / len(lengths)
    length_variance = sum(
        (value - length_mean) ** 2 for value in lengths
    ) / len(lengths)
    length_variation = min(
        1.0,
        math.sqrt(length_variance) / max(length_mean * 0.28, 1e-9),
    )
    upper_count = sum(
        _point(lane["target"], "lane.target")[1]
        < _point(lane["root"], "lane.root")[1]
        for lane in lanes
    )
    lower_count = len(lanes) - upper_count
    vertical_balance = 1.0 - abs(upper_count - lower_count) / len(lanes)
    side_rhythm = (
        str(prototype_strategy["l1_profile"]["side_rhythm"])
        if prototype_strategy is not None
        else "near_balanced"
    )
    if side_rhythm == "upper_side_emphasis":
        # SW3-2 asks for a small upper-side majority.  The target follows the
        # selected set cardinality, so this does not introduce fixed roots,
        # fixed slots, or a 5D density/count policy.
        target_upper_count = len(lanes) // 2 + 1
        vertical_rhythm_fit = 1.0 / (
            1.0 + abs(upper_count - target_upper_count)
        )
    else:
        target_upper_count = len(lanes) / 2.0
        vertical_rhythm_fit = vertical_balance
    candidate_quality = sum(
        float(lane["individual_score"]) for lane in lanes
    ) / len(lanes)
    total_planning_length = sum(lengths)
    mean_backbone_excursion = sum(
        float(lane["features"]["maximum_backbone_excursion"])
        for lane in lanes
    ) / len(lanes)
    mean_vertical_span = sum(
        float(lane["features"]["vertical_span"])
        for lane in lanes
    ) / len(lanes)
    score = (
        0.34 * candidate_quality
        + 1.65 * root_coverage
        + 0.62 * cluster_relief
        + 0.58 * length_variation
        + 0.42 * vertical_rhythm_fit
    )
    features = {
        "mean_candidate_quality": candidate_quality,
        "root_arc_coverage": root_coverage,
        "minimum_selected_root_gap": minimum_gap,
        "severe_root_cluster_relief": cluster_relief,
        "length_variation": length_variation,
        "upper_lane_count": float(upper_count),
        "lower_lane_count": float(lower_count),
        "upper_lane_fraction": upper_count / len(lanes),
        "vertical_side_balance": vertical_balance,
        "target_upper_lane_count": float(target_upper_count),
        "vertical_rhythm_fit": vertical_rhythm_fit,
        "ordinary_l1_count": float(len(lanes)),
        "total_planning_length": total_planning_length,
        "mean_backbone_excursion": mean_backbone_excursion,
        "mean_vertical_span": mean_vertical_span,
    }
    if preferred_total_count is not None and support_count is not None:
        selected_total_count = len(lanes) + support_count
        count_closeness = 1.0 / (
            1.0 + abs(selected_total_count - preferred_total_count)
        )
        score += 0.55 * count_closeness
        features.update(
            {
                "selected_total_l1_count": float(selected_total_count),
                "preferred_total_l1_count": float(preferred_total_count),
                "count_center_closeness": count_closeness,
            }
        )
    return score, features


def _minmax_value(value: float, lower: float, upper: float) -> float:
    if upper - lower < 1e-9:
        return 0.5
    return min(1.0, max(0.0, (value - lower) / (upper - lower)))


def _linear_quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise GlobalL1FlowError("cannot derive a density target from no terminal sets")
    if not 0.0 <= quantile <= 1.0:
        raise GlobalL1FlowError("soft density target quantile must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    position = quantile * (len(ordered) - 1)
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return (
        ordered[lower_index] * (1.0 - fraction)
        + ordered[upper_index] * fraction
    )


def _rank_soft_density_sets(
    terminal_sets: Mapping[
        tuple[str, ...],
        tuple[float, Mapping[str, float]],
    ],
    density_level: str,
    policy: Mapping[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    """Jointly rank every witnessed set and cardinality with one soft target."""

    if density_level not in ORDINARY_DENSITY_LEVELS:
        raise GlobalL1FlowError("soft density selector received an invalid level")
    target_quantiles = policy.get("target_quantiles")
    component_weights = policy.get("resource_component_weights")
    if not isinstance(target_quantiles, Mapping) or not isinstance(
        component_weights,
        Mapping,
    ):
        raise GlobalL1FlowError("V3 contract lacks the soft density objective")
    resource_names = (
        "ordinary_l1_count",
        "total_planning_length",
        "mean_backbone_excursion",
        "mean_vertical_span",
    )
    if set(component_weights) != set(resource_names):
        raise GlobalL1FlowError("soft density resource components mismatch")
    weights = {name: float(component_weights[name]) for name in resource_names}
    structural_weight = float(policy.get("structural_weight", -1.0))
    density_fit_weight = float(policy.get("density_fit_weight", -1.0))
    if (
        any(value < 0.0 for value in weights.values())
        or abs(sum(weights.values()) - 1.0) > 1e-9
        or structural_weight < 0.0
        or density_fit_weight < 0.0
        or abs(structural_weight + density_fit_weight - 1.0) > 1e-9
    ):
        raise GlobalL1FlowError("soft density objective weights are invalid")

    structural_values = [float(value[0]) for value in terminal_sets.values()]
    structural_bounds = (min(structural_values), max(structural_values))
    resource_bounds = {
        name: (
            min(float(features[name]) for _, features in terminal_sets.values()),
            max(float(features[name]) for _, features in terminal_sets.values()),
        )
        for name in resource_names
    }
    rows: list[dict[str, Any]] = []
    for signature, (structural_raw, features) in terminal_sets.items():
        resource_raw = {
            name: float(features[name]) for name in resource_names
        }
        resource_normalized = {
            name: _minmax_value(
                resource_raw[name],
                resource_bounds[name][0],
                resource_bounds[name][1],
            )
            for name in resource_names
        }
        resource_score = sum(
            weights[name] * resource_normalized[name]
            for name in resource_names
        )
        rows.append(
            {
                "signature": signature,
                "structural_raw": float(structural_raw),
                "structural_normalized": _minmax_value(
                    float(structural_raw),
                    structural_bounds[0],
                    structural_bounds[1],
                ),
                "features": dict(features),
                "resource_raw": resource_raw,
                "resource_normalized": resource_normalized,
                "resource_score": resource_score,
            }
        )

    resource_scores = [float(row["resource_score"]) for row in rows]
    density_targets = {
        level: _linear_quantile(
            resource_scores,
            float(target_quantiles[level]),
        )
        for level in ORDINARY_DENSITY_LEVELS
    }
    target_quantile = float(target_quantiles[density_level])
    target_resource_score = density_targets[density_level]
    bandwidth_fraction = float(policy.get("fit_bandwidth_fraction", -1.0))
    minimum_bandwidth = float(policy.get("minimum_fit_bandwidth", -1.0))
    if (
        policy.get("fit_kernel") != "gaussian"
        or bandwidth_fraction <= 0.0
        or minimum_bandwidth <= 0.0
    ):
        raise GlobalL1FlowError("soft density fit bandwidth is invalid")
    resource_bandwidth = max(
        minimum_bandwidth,
        bandwidth_fraction
        * (density_targets["rich"] - density_targets["simple"]),
    )
    for row in rows:
        target_distance = (
            float(row["resource_score"]) - target_resource_score
        )
        density_fit = math.exp(
            -0.5 * (target_distance / resource_bandwidth) ** 2
        )
        row["density_fit"] = density_fit
        row["total_objective"] = (
            structural_weight * float(row["structural_normalized"])
            + density_fit_weight * density_fit
        )
    rows.sort(
        key=lambda row: (
            -float(row["total_objective"]),
            -float(row["structural_raw"]),
            abs(float(row["resource_score"]) - target_resource_score),
            row["signature"],
        )
    )

    best_by_cardinality: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(len(row["signature"]))
        if key not in best_by_cardinality:
            best_by_cardinality[key] = {
                "structural_raw": round(float(row["structural_raw"]), 9),
                "resource_score": round(float(row["resource_score"]), 9),
                "density_fit": round(float(row["density_fit"]), 9),
                "total_objective": round(float(row["total_objective"]), 9),
            }

    selected_row = rows[0]
    density_objective = {
        "version": str(policy.get("version", "soft_resource_v3")),
        "density_level": density_level,
        "target_quantile": round(target_quantile, 9),
        "target_resource_score": round(target_resource_score, 9),
        "target_resource_scores": {
            level: round(density_targets[level], 9)
            for level in ORDINARY_DENSITY_LEVELS
        },
        "fit_kernel": "gaussian",
        "fit_bandwidth": round(resource_bandwidth, 9),
        "structural_weight": round(structural_weight, 9),
        "density_fit_weight": round(density_fit_weight, 9),
        "component_weights": {
            name: round(weights[name], 9) for name in resource_names
        },
        "normalization_bounds": {
            "structural_raw": {
                "minimum": round(structural_bounds[0], 9),
                "maximum": round(structural_bounds[1], 9),
            },
            **{
                name: {
                    "minimum": round(resource_bounds[name][0], 9),
                    "maximum": round(resource_bounds[name][1], 9),
                }
                for name in resource_names
            },
        },
        "selected": {
            "structural_raw": round(float(selected_row["structural_raw"]), 9),
            "structural_normalized": round(
                float(selected_row["structural_normalized"]), 9
            ),
            "resource_raw": {
                name: round(float(selected_row["resource_raw"][name]), 9)
                for name in resource_names
            },
            "resource_normalized": {
                name: round(
                    float(selected_row["resource_normalized"][name]), 9
                )
                for name in resource_names
            },
            "resource_score": round(float(selected_row["resource_score"]), 9),
            "density_fit": round(float(selected_row["density_fit"]), 9),
            "total_objective": round(float(selected_row["total_objective"]), 9),
        },
    }
    return rows, density_objective, best_by_cardinality


def _build_common_conflict_graph(
    candidates: Sequence[Mapping[str, Any]],
    prior: Mapping[str, Any],
    curve_geometry_profile: Mapping[str, Any],
    lane_clearance_override: float | None = None,
) -> tuple[
    dict[str, set[str]],
    dict[tuple[str, str], tuple[bool, float, dict[str, float]]],
    float,
    float,
]:
    """Build the R3 graph over every mechanically valid pool candidate."""

    candidate_ids = [str(row["candidate_id"]) for row in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise GlobalL1FlowError("common L1 pool contains duplicate candidate ids")
    root_spacing = _minimum_root_spacing(prior)
    lane_clearance = (
        float(lane_clearance_override)
        if lane_clearance_override is not None
        else _minimum_lane_clearance(prior, curve_geometry_profile)
    )
    adjacency = {candidate_id: set() for candidate_id in candidate_ids}
    pair_cache: dict[
        tuple[str, str], tuple[bool, float, dict[str, float]]
    ] = {}
    geometry = {
        candidate_id: [
            _point(value, "common_candidate.centerline")
            for value in rows_by_id["centerline"]
        ]
        for candidate_id, rows_by_id in (
            (str(row["candidate_id"]), row) for row in candidates
        )
    }
    bounds = {
        candidate_id: (
            min(point[0] for point in points),
            max(point[0] for point in points),
            min(point[1] for point in points),
            max(point[1] for point in points),
        )
        for candidate_id, points in geometry.items()
    }

    def periodic_box_gap(first_id: str, second_id: str) -> float:
        first_min_x, first_max_x, first_min_y, first_max_y = bounds[first_id]
        second_min_x, second_max_x, second_min_y, second_max_y = bounds[
            second_id
        ]
        minimum = float("inf")
        for offset in (-1.0, 0.0, 1.0):
            gap_x = max(
                0.0,
                first_min_x - (second_max_x + offset),
                second_min_x + offset - first_max_x,
            )
            gap_y = max(
                0.0,
                first_min_y - second_max_y,
                second_min_y - first_max_y,
            )
            minimum = min(minimum, math.hypot(gap_x, gap_y))
        return minimum

    evaluated_geometry_pair_count = 0
    root_only_conflict_count = 0
    distant_compatible_pair_count = 0
    for index, candidate in enumerate(candidates):
        candidate_id = str(candidate["candidate_id"])
        for other in candidates[index + 1 :]:
            other_id = str(other["candidate_id"])
            key = tuple(sorted((candidate_id, other_id)))
            root_gap = _periodic_delta(
                float(candidate["root_s"]),
                float(other["root_s"]),
            )
            if root_gap < root_spacing:
                result = (
                    False,
                    0.0,
                    {"root_gap": root_gap, "minimum_clearance": 0.0},
                )
                root_only_conflict_count += 1
            else:
                box_gap = periodic_box_gap(candidate_id, other_id)
                if box_gap > 0.18:
                    result = _pair_metrics(
                        candidate,
                        other,
                        root_spacing,
                        lane_clearance,
                        curve_geometry_profile,
                        known_separated_clearance=box_gap,
                    )
                    result[2]["broad_phase_distant"] = 1.0
                    distant_compatible_pair_count += 1
                else:
                    result = _pair_metrics(
                        candidate,
                        other,
                        root_spacing,
                        lane_clearance,
                        curve_geometry_profile,
                    )
                    evaluated_geometry_pair_count += 1
            pair_cache[key] = result
            if not result[0]:
                adjacency[candidate_id].add(other_id)
                adjacency[other_id].add(candidate_id)
    pair_cache[("__graph_stats__", "__graph_stats__")] = (
        True,
        0.0,
        {
            "evaluated_geometry_pair_count": float(
                evaluated_geometry_pair_count
            ),
            "root_only_conflict_count": float(root_only_conflict_count),
            "distant_compatible_pair_count": float(
                distant_compatible_pair_count
            ),
        },
    )
    return adjacency, pair_cache, root_spacing, lane_clearance


def _seeded_rescue_witness(
    rows_by_id: Mapping[str, Mapping[str, Any]],
    ordered_ids: Sequence[str],
    adjacency: Mapping[str, set[str]],
    target_count: int,
    rescue_seed: int | None,
    add_terminal,
) -> bool:
    """Deterministic seeded greedy fallback for the common-set search.

    The ranked greedy can miss an existing independent set on dense graphs.
    This fallback only runs after the greedy found no witness for one target
    cardinality, uses the case branch seed for its shuffle order, and never
    re-rolls the generation seed.
    """

    base = 0 if rescue_seed is None else int(rescue_seed)
    sequence = (base * 1103515245 + target_count * 12345 + 12345) % (2**32)
    rng = random.Random(sequence)
    for _ in range(4000):
        nodes = list(ordered_ids)
        rng.shuffle(nodes)
        chosen: list[str] = []
        banned: set[str] = set()
        for node in nodes:
            if node in banned:
                continue
            chosen.append(node)
            banned.update(adjacency[node])
            if len(chosen) >= target_count:
                add_terminal(chosen)
                return True
    return False


def _solve_common_set(
    candidates: Sequence[Mapping[str, Any]],
    count_derivation: Mapping[str, Any],
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    curve_geometry_profile: Mapping[str, Any],
    prototype_strategy: Mapping[str, Any] | None = None,
    rescue_seed: int | None = None,
    lane_clearance_override: float | None = None,
    soft_density_policy: Mapping[str, Any] | None = None,
    shared_density_clearance: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select one compatible variable-cardinality set from a shared pool."""

    if not candidates:
        raise GlobalL1FlowError("dynamic_l1_layout_infeasible: empty common pool")
    (
        adjacency,
        pair_cache,
        root_spacing,
        lane_clearance,
    ) = _build_common_conflict_graph(
        candidates,
        prior,
        curve_geometry_profile,
        lane_clearance_override,
    )
    graph_stats = pair_cache.pop(("__graph_stats__", "__graph_stats__"))[2]
    rows_by_id = {str(row["candidate_id"]): row for row in candidates}
    ordered_ids = sorted(
        rows_by_id,
        key=lambda candidate_id: (
            len(adjacency[candidate_id]),
            -float(rows_by_id[candidate_id]["individual_score"]),
            candidate_id,
        ),
    )
    support_count = int(count_derivation["required_support_count"])
    support_roots = [
        float(value)
        for value in count_derivation["flower_support_reserved_root_s"]
    ]
    preferred_total = int(count_derivation["preferred_l1_count"])
    soft_density_enabled = soft_density_policy is not None
    allowed_counts = sorted(
        {
            int(value)
            for value in count_derivation["allowed_ordinary_l1_counts"]
        },
        key=(
            (lambda value: value)
            if soft_density_enabled
            else (
                lambda value: (
                    abs(value + support_count - preferred_total),
                    value,
                )
            )
        ),
    )
    terminal_sets: dict[tuple[str, ...], tuple[float, dict[str, float]]] = {}
    cardinality_status: dict[str, str] = {}
    greedy_attempt_count = 0
    exact_search_node_count = 0
    exact_search_node_limit = 250_000

    def score_ids(ids: Sequence[str]) -> tuple[float, dict[str, float]]:
        return _common_set_score(
            [rows_by_id[candidate_id] for candidate_id in ids],
            analysis=analysis,
            preferred_total_count=(
                None if soft_density_enabled else preferred_total
            ),
            support_count=None if soft_density_enabled else support_count,
            support_roots=support_roots,
            root_spacing=root_spacing,
            prototype_strategy=prototype_strategy,
        )

    def add_terminal(ids: Sequence[str]) -> None:
        signature = tuple(sorted(ids))
        score, features = score_ids(signature)
        previous = terminal_sets.get(signature)
        if previous is None or score > previous[0]:
            terminal_sets[signature] = score, features

    for target_count in allowed_counts:
        before_count = len(terminal_sets)
        for first_id in ordered_ids:
            greedy_attempt_count += 1
            selected_ids = [first_id]
            selected_set = {first_id}
            while len(selected_ids) < target_count:
                compatible_ids = [
                    candidate_id
                    for candidate_id in ordered_ids
                    if candidate_id not in selected_set
                    and all(
                        candidate_id not in adjacency[existing_id]
                        for existing_id in selected_ids
                    )
                ]
                if not compatible_ids:
                    break
                ranked_additions: list[tuple[float, int, float, str]] = []
                for candidate_id in compatible_ids:
                    tentative = selected_ids + [candidate_id]
                    structural_score, _ = score_ids(tentative)
                    ranked_additions.append(
                        (
                            structural_score,
                            -len(adjacency[candidate_id]),
                            float(rows_by_id[candidate_id]["individual_score"]),
                            candidate_id,
                        )
                    )
                ranked_additions.sort(
                    key=lambda row: (-row[0], -row[1], -row[2], row[3])
                )
                selected_id = ranked_additions[0][3]
                selected_ids.append(selected_id)
                selected_set.add(selected_id)
            if len(selected_ids) == target_count:
                add_terminal(selected_ids)

        if len(terminal_sets) > before_count:
            cardinality_status[str(target_count)] = "greedy_witness_found"
            continue

        if _seeded_rescue_witness(
            rows_by_id,
            ordered_ids,
            adjacency,
            target_count,
            rescue_seed,
            add_terminal,
        ):
            cardinality_status[str(target_count)] = "seeded_rescue_witness_found"
            continue

        exhausted = False
        witness: list[str] | None = None

        def exact_search(start_index: int, selected_ids: list[str]) -> None:
            nonlocal exact_search_node_count, exhausted, witness
            if witness is not None or exhausted:
                return
            exact_search_node_count += 1
            if exact_search_node_count > exact_search_node_limit:
                exhausted = True
                return
            if len(selected_ids) == target_count:
                witness = list(selected_ids)
                return
            remaining_needed = target_count - len(selected_ids)
            if len(ordered_ids) - start_index < remaining_needed:
                return
            for index in range(start_index, len(ordered_ids)):
                candidate_id = ordered_ids[index]
                if all(
                    candidate_id not in adjacency[existing_id]
                    for existing_id in selected_ids
                ):
                    selected_ids.append(candidate_id)
                    exact_search(index + 1, selected_ids)
                    selected_ids.pop()
                    if witness is not None or exhausted:
                        return

        exact_search(0, [])
        if exhausted:
            cardinality_status[str(target_count)] = (
                "exact_search_exhausted_no_witness"
            )
            continue
        if witness is None:
            cardinality_status[str(target_count)] = "geometrically_infeasible"
        else:
            add_terminal(witness)
            cardinality_status[str(target_count)] = "exact_witness_found"

    if not terminal_sets:
        raise GlobalL1FlowError(
            "dynamic_l1_layout_infeasible: no compatible cardinality"
        )
    geometry_witnessed_counts = sorted(
        {len(signature) for signature in terminal_sets}
    )
    density_level = str(count_derivation["ordinary_density_level"])
    if density_level not in ORDINARY_DENSITY_LEVELS:
        raise GlobalL1FlowError("common set selector received an invalid density level")
    density_objective: dict[str, Any] | None = None
    best_objective_by_cardinality: dict[str, dict[str, Any]] | None = None
    resolved_density_domain: dict[str, int] | None = None
    ordinary_center: int | None = None
    density_initial_clearances: dict[str, float] = {}
    if soft_density_enabled:
        soft_ranked_sets, density_objective, best_objective_by_cardinality = (
            _rank_soft_density_sets(
                terminal_sets,
                density_level,
                soft_density_policy,
            )
        )
        selected_row = soft_ranked_sets[0]
        selected_signature = tuple(selected_row["signature"])
        selected_score = float(selected_row["total_objective"])
        selected_features = dict(selected_row["features"])
        selected_ordinary_count = len(selected_signature)
        if shared_density_clearance is not None:
            # A density target must not decide which normalization domain is used.
            # Inspect all three target choices from this same terminal set first.
            for level in ORDINARY_DENSITY_LEVELS:
                ranked = (
                    soft_ranked_sets
                    if level == density_level
                    else _rank_soft_density_sets(terminal_sets, level, soft_density_policy)[0]
                )
                lines = [rows_by_id[cid]["centerline"] for cid in ranked[0]["signature"]]
                density_initial_clearances[level] = min(
                    (
                        global_l1_polyline_distance_batch(first, second, offset)
                        for index, first in enumerate(lines)
                        for second in lines[index + 1 :]
                        for offset in (-1.0, 0.0, 1.0)
                    ),
                    default=float("inf"),
                )
    else:
        ordinary_center = int(count_derivation["ordinary_l1_count_center"])
        resolved_density_domain = {
            "simple": min(geometry_witnessed_counts),
            "medium": min(
                geometry_witnessed_counts,
                key=lambda value: (abs(value - ordinary_center), value),
            ),
            "rich": max(geometry_witnessed_counts),
        }
        selected_ordinary_count = resolved_density_domain[density_level]
        ranked_sets = sorted(
            (
                (score, signature, features)
                for signature, (score, features) in terminal_sets.items()
                if len(signature) == selected_ordinary_count
            ),
            key=lambda row: (-row[0], row[1]),
        )
        if not ranked_sets:
            raise GlobalL1FlowError(
                "dynamic_l1_layout_infeasible: density cardinality has no witness"
            )
        selected_score, selected_signature, selected_features = ranked_sets[0]
    selected_pool_rows = sorted(
        (dict(rows_by_id[candidate_id]) for candidate_id in selected_signature),
        key=lambda row: (float(row["root_s"]), str(row["candidate_id"])),
    )
    selected: list[dict[str, Any]] = []
    for index, row in enumerate(selected_pool_rows, start=1):
        selected_l1_id = f"selected_l1_{index:03d}"
        row["selected_l1_id"] = selected_l1_id
        row["slot_id"] = selected_l1_id
        row["legacy_identity_alias"] = "slot_id_equals_selected_l1_id"
        row["role"] = "primary_sweep"
        selected.append(row)

    pair_rows: list[dict[str, Any]] = []
    for index, lane in enumerate(selected):
        for other in selected[index + 1 :]:
            key = tuple(
                sorted(
                    (
                        str(lane["candidate_id"]),
                        str(other["candidate_id"]),
                    )
                )
            )
            valid, pair_score, metrics = pair_cache[key]
            if not valid:
                raise GlobalL1FlowError(
                    "selected common L1 set contains a hard pair conflict"
                )
            pair_rows.append(
                {
                    "candidate_ids": list(key),
                    "pair_score": round(pair_score, 9),
                    **{
                        name: round(value, 9)
                        for name, value in metrics.items()
                    },
                }
            )
    edge_count = sum(len(values) for values in adjacency.values()) // 2
    solver: dict[str, Any] = {
        "solver": (
            "bounded_deterministic_common_pool_variable_cardinality_set_selector"
        ),
        "global_optimality_claimed": False,
        "selection_slots_used": False,
        "ordinary_density_level": density_level,
        "ordinary_density_source": str(
            count_derivation["ordinary_density_source"]
        ),
        "selected_ordinary_l1_count": selected_ordinary_count,
        "static_side_rhythm_policy": (
            str(prototype_strategy["l1_profile"]["side_rhythm"])
            if prototype_strategy is not None
            else "near_balanced"
        ),
        "root_spacing_hard": round(root_spacing, 9),
        "lane_clearance_hard": round(lane_clearance, 9),
        "common_pool_node_count": len(candidates),
        "common_pool_conflict_edge_count": edge_count,
        "pair_relation_count": len(pair_cache),
        "evaluated_geometry_pair_count": int(
            graph_stats["evaluated_geometry_pair_count"]
        ),
        "root_only_conflict_count": int(
            graph_stats["root_only_conflict_count"]
        ),
        "distant_compatible_pair_count": int(
            graph_stats["distant_compatible_pair_count"]
        ),
        "allowed_ordinary_l1_counts": allowed_counts,
        "cardinality_status": cardinality_status,
        "greedy_start_count": greedy_attempt_count,
        "exact_search_node_count": exact_search_node_count,
        "exact_search_node_limit": exact_search_node_limit,
        "terminal_compatible_set_count": len(terminal_sets),
        "terminal_set_count_by_cardinality": {
            str(count): sum(
                len(signature) == count for signature in terminal_sets
            )
            for count in geometry_witnessed_counts
        },
        "selected_total_score": round(selected_score, 9),
        "global_features": {
            key: round(value, 9) for key, value in selected_features.items()
        },
        "selected_pair_metrics": pair_rows,
        "exact_editor_geometry_exemplar_reuse": False,
    }
    if density_initial_clearances:
        solver["density_initial_pair_clearances"] = density_initial_clearances
    if soft_density_enabled:
        solver.update(
            {
                "count_selected_during_set_search": False,
                "count_selected_after_terminal_search": True,
                "density_count_mapping_used": False,
                "selected_count_as_result": True,
                "selected_set_and_count_jointly_ranked": True,
                "geometry_witnessed_ordinary_l1_counts": (
                    geometry_witnessed_counts
                ),
                "density_objective": density_objective,
                "best_objective_by_cardinality": (
                    best_objective_by_cardinality
                ),
            }
        )
    else:
        if ordinary_center is None or resolved_density_domain is None:
            raise GlobalL1FlowError("legacy density cardinality state is incomplete")
        solver.update(
            {
                "count_selected_during_set_search": True,
                "count_selected_by_ordinary_density_policy": True,
                "ordinary_l1_count_center": ordinary_center,
                "geometry_feasible_ordinary_l1_counts": (
                    geometry_witnessed_counts
                ),
                "resolved_ordinary_l1_count_domain": resolved_density_domain,
                "density_levels_have_distinct_counts": (
                    len(set(resolved_density_domain.values()))
                    == len(ORDINARY_DENSITY_LEVELS)
                ),
            }
        )
    if lane_clearance_override is not None:
        solver["lane_clearance_override_applied"] = True
    if any(
        status == "seeded_rescue_witness_found"
        for status in cardinality_status.values()
    ):
        solver["seeded_rescue_used"] = True
    return selected, solver


def _validate_inputs(
    strict_p0: Mapping[str, Any],
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    seed: int,
    prototype_strategy: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    if contract.get("schema") not in {
        CONTRACT_SCHEMA,
        CONTRACT_SCHEMA_V2,
        CONTRACT_SCHEMA_V3,
    }:
        raise GlobalL1FlowError("stage-3B contract schema mismatch")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise GlobalL1FlowError("branch_seed must be a non-negative 32-bit integer")
    prototype_id = str(strict_p0.get("prototype_id"))
    if prototype_id not in PROTOTYPE_IDS:
        raise GlobalL1FlowError(f"unknown prototype id: {prototype_id}")
    if strict_p0.get("schema") != "dynamic_branch_strict_p0_v2":
        raise GlobalL1FlowError(f"{prototype_id} StrictP0 schema mismatch")
    if analysis.get("schema") != "dynamic_branch_prototype_analysis_v1":
        raise GlobalL1FlowError(f"{prototype_id} analysis schema mismatch")
    if morphology.get("schema") != "dynamic_branch_morphology_profile_v1":
        raise GlobalL1FlowError(f"{prototype_id} morphology schema mismatch")
    if analysis.get("prototype_id") != prototype_id or morphology.get("prototype_id") != prototype_id:
        raise GlobalL1FlowError(f"{prototype_id} input identity mismatch")
    strict_flower_ids = [row["flower_id"] for row in strict_p0["flowers"]]
    analysis_flower_ids = [row["flower_id"] for row in analysis["flowers"]]
    if strict_flower_ids != analysis_flower_ids:
        raise GlobalL1FlowError(f"{prototype_id} flower inventory mismatch")
    validate_fixed_visual_prior(prior)
    family_id = str(morphology["classification"]["flower_branch_relation"]["family_id"])
    if prototype_strategy is not None:
        validate_strategy_against_inputs(
            prototype_strategy,
            strict_p0,
            analysis,
            morphology,
        )
        family_id = str(prototype_strategy["family_id"])
    return prototype_id, family_id


def generate_global_l1_flow_plan(
    strict_p0: Mapping[str, Any],
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    seed: int,
    feedback_prior: Mapping[str, Any] | None = None,
    curve_geometry_prior: Mapping[str, Any] | None = None,
    flower_mount_plan: Mapping[str, Any] | None = None,
    *,
    backbone_seed: int | None = None,
    flower_seed: int | None = None,
    unit_seed: int | None = None,
    prototype_strategy: Mapping[str, Any] | None = None,
    backbone_variation: Mapping[str, Any] | None = None,
    flower_layout_plan: Mapping[str, Any] | None = None,
    ordinary_density_level_override: str | None = None,
    downstream_unit_clearance: float | None = None,
    density_control_profile: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate one formal L1-only layout and its complete candidate inventory."""

    prototype_id, family_id = _validate_inputs(
        strict_p0,
        analysis,
        morphology,
        prior,
        contract,
        seed,
        prototype_strategy,
    )
    if flower_seed is not None and (
        isinstance(flower_seed, bool)
        or not isinstance(flower_seed, int)
        or not 0 <= flower_seed <= 2**32 - 1
    ):
        raise GlobalL1FlowError("flower_seed must be a non-negative 32-bit integer")
    if unit_seed is not None and (
        isinstance(unit_seed, bool)
        or not isinstance(unit_seed, int)
        or not 0 <= unit_seed <= 2**32 - 1
    ):
        raise GlobalL1FlowError("unit_seed must be a non-negative 32-bit integer")
    if flower_layout_plan is not None:
        if flower_layout_plan.get("prototype_id") != prototype_id:
            raise GlobalL1FlowError("flower layout plan prototype mismatch")
        if flower_seed is None or int(flower_layout_plan.get("flower_seed", -1)) != flower_seed:
            raise GlobalL1FlowError("flower layout plan seed mismatch")
    repeat_width_scale = 1.0
    prototype_variant_id: str | None = None
    if backbone_variation is not None:
        if backbone_variation.get("prototype_id") != prototype_id:
            raise GlobalL1FlowError("backbone variation prototype mismatch")
        repeat_width_scale = float(
            backbone_variation.get("physical_repeat_width", 1.0)
        )
        if not math.isfinite(repeat_width_scale) or repeat_width_scale <= 0.0:
            raise GlobalL1FlowError("invalid physical repeat width scale")
        raw_variant_id = backbone_variation.get("prototype_variant_id")
        prototype_variant_id = (
            str(raw_variant_id) if raw_variant_id is not None else None
        )
    feedback_profile: Mapping[str, Any] | None = None
    curve_geometry_profile: Mapping[str, Any] | None = None
    if _feedback_mode(contract):
        if (
            feedback_prior is None
            or curve_geometry_prior is None
            or flower_mount_plan is None
        ):
            raise GlobalL1FlowError(
                "feedback Stage3B requires both editor priors and flower mounting first"
            )
        if flower_mount_plan.get("prototype_id") != prototype_id:
            raise GlobalL1FlowError("flower mount plan prototype mismatch")
        if flower_mount_plan.get("morphology_family") != family_id:
            raise GlobalL1FlowError("flower mount plan morphology mismatch")
        if (
            prototype_strategy is not None
            and flower_mount_plan.get("prototype_strategy") != prototype_strategy
        ):
            raise GlobalL1FlowError("flower mount plan strategy mismatch")
        if flower_mount_plan.get("mount_policy", {}).get(
            "mounts_frozen_before_ordinary_l1"
        ) is not True:
            raise GlobalL1FlowError("flower mount plan is not an upstream constraint")
        l1_policy = (
            prototype_strategy["l1_profile"]
            if prototype_strategy is not None
            else {}
        )
        feedback_profile = _feedback_profile(
            feedback_prior,
            prototype_id,
            str(l1_policy.get("feedback_profile_key", prototype_id)),
        )
        curve_geometry_profile = _curve_geometry_profile(
            curve_geometry_prior,
            prototype_id,
            str(l1_policy.get("curve_geometry_profile_key", prototype_id)),
        )
    latents = _global_latents(prototype_id, seed)
    slots: list[Slot] = []
    pools: dict[str, list[dict[str, Any]]] = {}
    inventory_rows: list[dict[str, Any]] = []
    rejection_counts: Counter[str] = Counter()
    pool_sampling: dict[str, Any] | None = None
    if feedback_profile is not None:
        if curve_geometry_profile is None or flower_mount_plan is None:
            raise GlobalL1FlowError("feedback common-pool inputs are incomplete")
        soft_density_policy: Mapping[str, Any] | None = None
        if _soft_density_mode(contract):
            candidate_policy = contract.get("planning_policy", {}).get(
                "soft_density_objective"
            )
            if not isinstance(candidate_policy, Mapping):
                raise GlobalL1FlowError(
                    "V3 contract lacks a soft density objective policy"
                )
            soft_density_policy = candidate_policy
        count_derivation = _derive_common_count_domain(
            analysis,
            morphology,
            prior,
            feedback_profile,
            flower_mount_plan,
            seed,
            prototype_strategy,
            ordinary_density_level_override,
            soft_density_mode=soft_density_policy is not None,
            density_control_profile=density_control_profile,
        )
        candidates, pool_sampling = _feedback_common_ordinary_candidates(
            analysis,
            prior,
            latents,
            feedback_profile,
            curve_geometry_profile,
            seed,
        )
        feasible: list[dict[str, Any]] = []
        for candidate in candidates:
            reasons = _candidate_rejections(
                candidate,
                analysis,
                family_id,
                prior,
                feedback_profile,
                flower_mount_plan,
                curve_geometry_profile,
                (
                    str(prototype_strategy["flower_mount"]["mechanism"])
                    if prototype_strategy is not None
                    else None
                ),
            )
            inventory_row = dict(candidate)
            inventory_row["hard_rejections"] = reasons
            inventory_rows.append(inventory_row)
            rejection_counts.update(reasons)
            if not reasons:
                feasible.append(candidate)
        if not feasible:
            raise GlobalL1FlowError("dynamic_l1_layout_infeasible: empty common pool")
        selected, solver = _solve_common_set(
            feasible,
            count_derivation,
            analysis,
            prior,
            curve_geometry_profile,
            prototype_strategy,
            rescue_seed=seed,
            soft_density_policy=soft_density_policy,
            shared_density_clearance=(
                downstream_unit_clearance
                if soft_density_policy is not None and density_control_profile is None
                else None
            ),
        )
        if downstream_unit_clearance is not None:
            required_clearance = float(downstream_unit_clearance)
            selected_centerlines = [
                [_point(point, "lane.centerline") for point in row["centerline"]]
                for row in selected
            ]
            minimum_pair_clearance = min(
                (
                    global_l1_polyline_distance_batch(first, second, offset)
                    for index, first in enumerate(selected_centerlines)
                    for second in selected_centerlines[index + 1 :]
                    for offset in (-1.0, 0.0, 1.0)
                ),
                default=float("inf"),
            )
            density_initial_clearances = solver.get("density_initial_pair_clearances", {})
            domain_minimum_clearance = min(
                density_initial_clearances.values(), default=minimum_pair_clearance
            )
            if domain_minimum_clearance < required_clearance - 1e-9:
                rescue_feasible: list[dict[str, Any]] = []
                mount_point_lists = [
                    [
                        _point(point, "flower_mount.centerline")
                        for point in mount["centerline"]
                    ]
                    for mount in flower_mount_plan.get("mounts", [])
                ]
                for candidate in feasible:
                    candidate_points = [
                        _point(point, "candidate.centerline")
                        for point in candidate["centerline"]
                    ]
                    minimum_mount_clearance = min(
                        (
                            global_l1_polyline_distance_batch(
                                candidate_points,
                                mount_points,
                                offset,
                            )
                            for mount_points in mount_point_lists
                            for offset in (-1.0, 0.0, 1.0)
                        ),
                        default=float("inf"),
                    )
                    if minimum_mount_clearance >= required_clearance - 1e-9:
                        rescue_feasible.append(candidate)
                selected, solver = _solve_common_set(
                    rescue_feasible,
                    count_derivation,
                    analysis,
                    prior,
                    curve_geometry_profile,
                    prototype_strategy,
                    rescue_seed=seed,
                    lane_clearance_override=required_clearance,
                    soft_density_policy=soft_density_policy,
                )
                solver["downstream_clearance_resolve"] = {
                    "initial_min_pair_clearance": round(
                        minimum_pair_clearance,
                        9,
                    ),
                    "required": round(required_clearance, 9),
                    "re_solved": True,
                    "density_initial_pair_clearances": density_initial_clearances,
                }
            else:
                solver["downstream_clearance_resolve"] = {
                    "initial_min_pair_clearance": round(
                        minimum_pair_clearance,
                        9,
                    ),
                    "required": round(required_clearance, 9),
                    "re_solved": False,
                    "density_initial_pair_clearances": density_initial_clearances,
                }
        selected_ordinary_count = len(selected)
        selected_total_count = selected_ordinary_count + int(
            count_derivation["required_support_count"]
        )
        if selected_ordinary_count not in {
            int(value)
            for value in count_derivation["allowed_ordinary_l1_counts"]
        }:
            raise GlobalL1FlowError(
                "set selector returned a cardinality outside the allowed domain"
            )
        count_derivation = {
            **count_derivation,
            "ordinary_lane_count": selected_ordinary_count,
            "selected_ordinary_l1_count": selected_ordinary_count,
            "selected_l1_count": selected_total_count,
            "total_l1_with_flower_support_count": selected_total_count,
        }
        if soft_density_policy is not None:
            count_derivation.update(
                {
                    "geometry_witnessed_ordinary_l1_counts": solver[
                        "geometry_witnessed_ordinary_l1_counts"
                    ],
                    "selected_count_as_result": True,
                    "selected_set_and_count_jointly_ranked": True,
                    "density_objective": solver["density_objective"],
                }
            )
            if density_control_profile is not None:
                solver.update(
                    {
                        "selected_count_as_result": False,
                        "selected_set_and_count_jointly_ranked": False,
                        "density_count_mapping_used": True,
                        "target_total_l1_count": int(
                            count_derivation["target_total_l1_count"]
                        ),
                    }
                )
                count_derivation.update(
                    {
                        "selected_count_as_result": False,
                        "selected_set_and_count_jointly_ranked": False,
                        "density_count_mapping_used": True,
                    }
                )
        else:
            count_derivation.update(
                {
                    "geometry_feasible_ordinary_l1_counts": solver[
                        "geometry_feasible_ordinary_l1_counts"
                    ],
                    "resolved_ordinary_l1_count_domain": solver[
                        "resolved_ordinary_l1_count_domain"
                    ],
                    "density_levels_have_distinct_counts": solver[
                        "density_levels_have_distinct_counts"
                    ],
                }
            )
        selected_roots = sorted(float(row["root_s"]) for row in selected)
        root_gaps = [
            selected_roots[index] - selected_roots[index - 1]
            for index in range(1, len(selected_roots))
        ] + [1.0 - selected_roots[-1] + selected_roots[0]]
        root_rhythm = {
            "source": "selected_common_pool_set",
            "selected_root_s": [round(value, 9) for value in selected_roots],
            "gaps": [round(value, 9) for value in root_gaps],
            "minimum_root_spacing": round(_minimum_root_spacing(prior), 9),
            "residual_ranges": [
                [round(start, 9), round(end, 9)]
                for start, end in _subtract_periodic_root_exclusions(
                    _merged_attachment_ranges(analysis),
                    [
                        float(row["root_s"])
                        for row in flower_mount_plan["mounts"]
                    ],
                    _minimum_root_spacing(prior),
                )
            ],
            "preassigned_preferred_roots_used": False,
        }
        feasible_candidate_count = len(feasible)
    else:
        count_derivation = _derive_lane_count(
            prototype_id,
            analysis,
            morphology,
            prior,
            seed,
            None,
            flower_mount_plan,
            prototype_strategy,
        )
        slots, root_rhythm = _make_slots(
            analysis,
            morphology,
            count_derivation,
            latents,
            seed,
            prior,
            None,
            prototype_strategy,
        )
        for slot in slots:
            candidates = []
            if slot.role == "flower_support":
                candidates.extend(_sw1_support_candidates(slot, analysis, latents))
            elif slot.role == "terminal_flower_support":
                candidates.extend(_sw3_support_candidates(slot, analysis, latents))
            else:
                candidates.extend(
                    _ordinary_candidates(
                        slot,
                        analysis,
                        prior,
                        latents,
                        lane_count=int(count_derivation["selected_l1_count"]),
                    )
                )
            candidates.extend(
                _fixed_warp_candidates(
                    slot,
                    analysis,
                    prior,
                    seed,
                    (
                        bool(
                            prototype_strategy["l1_profile"][
                                "legacy_fixed_warp_visual_prior"
                            ]
                        )
                        if prototype_strategy is not None
                        else None
                    ),
                )
            )
            feasible = []
            for candidate in candidates:
                reasons = _candidate_rejections(
                    candidate,
                    analysis,
                    family_id,
                    prior,
                    None,
                    flower_mount_plan,
                    None,
                    (
                        str(prototype_strategy["flower_mount"]["mechanism"])
                        if prototype_strategy is not None
                        else None
                    ),
                )
                inventory_row = dict(candidate)
                inventory_row["hard_rejections"] = reasons
                inventory_rows.append(inventory_row)
                rejection_counts.update(reasons)
                if not reasons:
                    feasible.append(candidate)
            if not feasible:
                raise GlobalL1FlowError(
                    f"{prototype_id} seed {seed} slot {slot.slot_id} has no feasible candidates"
                )
            pools[slot.slot_id] = feasible
        selected, solver = _solve(slots, pools, prior, None, None)
        feasible_candidate_count = sum(len(rows) for rows in pools.values())

    selected_ids = {str(row["candidate_id"]) for row in selected}
    selected_lane_ids = {
        str(row["candidate_id"]): str(row["selected_l1_id"])
        for row in selected
        if row.get("selected_l1_id") is not None
    }
    for row in inventory_rows:
        candidate_id = str(row["candidate_id"])
        row["selected"] = candidate_id in selected_ids
        if candidate_id in selected_lane_ids:
            row["selected_l1_id"] = selected_lane_ids[candidate_id]

    role_counts = Counter(str(row["role"]) for row in selected)
    expected_selected_count = (
        int(count_derivation["ordinary_lane_count"])
        if feedback_profile is not None
        else int(count_derivation["selected_l1_count"])
    )
    if sum(role_counts.values()) != expected_selected_count:
        raise GlobalL1FlowError(
            "selected L1 count does not match count derivation"
        )
    if feedback_profile is None and (
        role_counts["flower_support"] + role_counts["terminal_flower_support"]
        != count_derivation["required_support_count"]
    ):
        raise GlobalL1FlowError("selected support count does not match morphology requirement")

    if _soft_density_mode(contract):
        plan_schema = SCHEMA_V3
        plan_version = "v3"
    elif feedback_profile is not None:
        plan_schema = SCHEMA_V2
        plan_version = "v2"
    else:
        plan_schema = SCHEMA
        plan_version = "v1"
    density_identity_suffix = (
        f"__density_{count_derivation['ordinary_density_level']}"
        if feedback_profile is not None
        else ""
    )
    plan: dict[str, Any] = {
        "schema": plan_schema,
        "plan_id": (
            f"{prototype_id}__seed_{seed}__global_l1_flow_{plan_version}"
            f"{density_identity_suffix}"
        ),
        "prototype_id": prototype_id,
        "family_id": family_id,
        "seed": seed,
        "branch_seed": seed,
        "backbone_seed": backbone_seed,
        "flower_seed": flower_seed,
        "unit_seed": unit_seed,
        "prototype_variant_id": prototype_variant_id,
        "repeat_layout": {
            "coordinate_space": "prototype_repeat_local",
            "normalized_repeat_width": 1.0,
            "physical_repeat_width_scale": round(repeat_width_scale, 12),
            "canonical_output_x_transform": "multiply_all_repeat_local_x_by_physical_repeat_width_scale",
        },
        "prototype_strategy": (
            dict(prototype_strategy) if prototype_strategy is not None else None
        ),
        "geometry_semantics": "planning_flow_lane_not_final_branch_curve",
        "stage_scope": {
            "l1_only": True,
            "l2_present": False,
            "l3_present": False,
            "terminal_content_present": False,
            "old_stage3_layout_consumed": False,
            "old_stage4_geometry_consumed": False,
        },
        "global_latents": latents,
        "edit_feedback_policy": (
            {
                "consumed": True,
                "prior_id": str(feedback_prior["prior_id"]),
                "role_semantics": str(feedback_profile["role_semantics"]),
                "mandatory_flower_service_lanes": bool(
                    feedback_profile["mandatory_flower_service_lanes"]
                ),
                "curve_geometry_source": str(
                    feedback_profile["curve_geometry_source"]
                ),
                "curve_geometry_prior_id": str(
                    curve_geometry_prior["prior_id"]
                ),
                "fixed_curve_shape_quota": False,
                "exact_editor_geometry_exemplar_reuse": False,
                "fixed_svg_templates_consumed": False,
            }
            if feedback_profile is not None and feedback_prior is not None
            else {"consumed": False}
        ),
        "flower_layout_plan": flower_layout_plan,
        "flower_mount_plan": flower_mount_plan,
        "count_derivation": count_derivation,
        "density_control_profile": (
            dict(density_control_profile)
            if density_control_profile is not None
            else None
        ),
        "root_rhythm": root_rhythm,
        **(
            {
                "selection_semantics": (
                    (
                        (
                            "common_pool_then_preregistered_density_count_then_"
                            "compatible_set_ranking; lane identities are assigned "
                            "only after selection"
                        )
                        if density_control_profile is not None
                        else (
                            "common_pool_then_soft_density_joint_set_and_count_"
                            "ranking; lane identities are assigned only after selection"
                        )
                    )
                    if _soft_density_mode(contract)
                    else (
                        "common_pool_then_density_conditioned_feasible_"
                        "cardinality_selection; lane identities are assigned "
                        "only after selection"
                    )
                ),
                "preassigned_selection_slots_used": False,
                "common_pool_sampling": pool_sampling,
            }
            if feedback_profile is not None
            else {
                "slots": [
                    {
                        "slot_id": slot.slot_id,
                        "role": slot.role,
                        "flower_id": slot.flower_id,
                        "preferred_s": round(slot.preferred_s, 9),
                        "preferred_vertical_side": (
                            slot.preferred_vertical_side
                        ),
                    }
                    for slot in slots
                ]
            }
        ),
        "lanes": selected,
        "role_counts": dict(sorted(role_counts.items())),
        "solver": solver,
        "diagnostics": {
            "hard_issue_count": 0,
            "lane_count": len(selected),
            "candidate_count": len(inventory_rows),
            "feasible_candidate_count": feasible_candidate_count,
            "rejected_candidate_count": sum(
                1 for row in inventory_rows if row["hard_rejections"]
            ),
            "rejection_counts": dict(sorted(rejection_counts.items())),
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "silent_fallback_used": False,
        },
        "review": {
            "status": "l1_flow_pending_visual_review",
            "numeric_checks_cannot_auto_approve_visual_gate": True,
            "criteria": [
                "flower_support_is_frozen_before_ordinary_l1",
                "global_direction_position_and_distance",
                "compact_medium_long_hierarchy",
                "tangent_run_outward_turn_and_settle",
                "ordinary_l1_preserves_flower_support_corridors",
                "root_and_target_spacing",
                "white_space_distribution",
                "non_crossing_periodic_flow",
            ],
        },
        "input_digests": {
            "strict_p0_digest": analysis["strict_p0_digest"],
            "analysis_digest": analysis["analysis_digest"],
            "morphology_digest": morphology["morphology_digest"],
            "fixed_visual_prior_digest": prior["prior_digest"],
            **(
                {"edit_feedback_prior_digest": canonical_digest(feedback_prior)}
                if feedback_prior is not None
                else {}
            ),
            **(
                {
                    "editor_curve_geometry_prior_digest": canonical_digest(
                        curve_geometry_prior
                    )
                }
                if curve_geometry_prior is not None
                else {}
            ),
        },
    }
    plan["plan_digest"] = canonical_digest(plan)
    inventory: dict[str, Any] = {
        "schema": (
            "dynamic_branch_global_l1_candidate_inventory_v3"
            if _soft_density_mode(contract)
            else (
                "dynamic_branch_global_l1_candidate_inventory_v2"
                if feedback_profile is not None
                else "dynamic_branch_global_l1_candidate_inventory_v1"
            )
        ),
        "prototype_id": prototype_id,
        "seed": seed,
        "branch_seed": seed,
        "backbone_seed": backbone_seed,
        "flower_seed": flower_seed,
        "unit_seed": unit_seed,
        "prototype_variant_id": prototype_variant_id,
        "repeat_layout": dict(plan["repeat_layout"]),
        "prototype_strategy": (
            dict(prototype_strategy) if prototype_strategy is not None else None
        ),
        "ordinary_density_level": (
            str(count_derivation["ordinary_density_level"])
            if feedback_profile is not None
            else None
        ),
        "ordinary_density_source": (
            str(count_derivation["ordinary_density_source"])
            if feedback_profile is not None
            else None
        ),
        "single_forward_global_solve": True,
        "flower_mount_plan_id": (
            str(flower_mount_plan["plan_id"])
            if flower_mount_plan is not None
            else None
        ),
        "experimental_variants": False,
        "candidate_pool_semantics": (
            "count_independent_common_ordinary_l1_pool"
            if feedback_profile is not None
            else "legacy_per_slot_candidate_pools"
        ),
        "preassigned_selection_slots_used": feedback_profile is None,
        "common_pool_sampling": pool_sampling,
        "candidate_count": len(inventory_rows),
        "selected_candidate_ids": sorted(selected_ids),
        "candidates": inventory_rows,
    }
    inventory["inventory_digest"] = canonical_digest(inventory)
    return plan, inventory


def validate_global_l1_flow_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema") not in {SCHEMA, SCHEMA_V2, SCHEMA_V3}:
        raise GlobalL1FlowError("global L1 flow plan schema mismatch")
    digest = plan.get("plan_digest")
    if not isinstance(digest, str):
        raise GlobalL1FlowError("global L1 flow plan digest is missing")
    payload = dict(plan)
    payload.pop("plan_digest")
    if canonical_digest(payload) != digest:
        raise GlobalL1FlowError("global L1 flow plan digest mismatch")
    if plan["stage_scope"] != {
        "l1_only": True,
        "l2_present": False,
        "l3_present": False,
        "terminal_content_present": False,
        "old_stage3_layout_consumed": False,
        "old_stage4_geometry_consumed": False,
    }:
        raise GlobalL1FlowError("global L1 flow stage scope mismatch")
    if plan["diagnostics"]["hard_issue_count"] != 0:
        raise GlobalL1FlowError("global L1 flow plan contains hard issues")
    if plan["review"]["status"] != "l1_flow_pending_visual_review":
        raise GlobalL1FlowError("global L1 flow plan has an invalid review state")
    if plan.get("schema") in {SCHEMA_V2, SCHEMA_V3}:
        policy = plan.get("edit_feedback_policy", {})
        if policy.get("curve_geometry_source") != (
            "continuous_editor_descriptor_distribution"
        ):
            raise GlobalL1FlowError(
                "V2 plan lacks continuous editor-learned geometry evidence"
            )
        if policy.get("fixed_curve_shape_quota") is not False:
            raise GlobalL1FlowError("V2 plan reintroduced a fixed shape quota")
        if policy.get("exact_editor_geometry_exemplar_reuse") is not False:
            raise GlobalL1FlowError(
                "V2 plan reintroduced exact editor geometry exemplars"
            )
        flower_mount_plan = plan.get("flower_mount_plan")
        if not isinstance(flower_mount_plan, Mapping):
            raise GlobalL1FlowError("V2 plan lacks upstream flower mounting")
        if flower_mount_plan.get("mount_policy", {}).get(
            "mounts_frozen_before_ordinary_l1"
        ) is not True:
            raise GlobalL1FlowError(
                "V2 flower mounting was not frozen before ordinary L1"
            )
        mounts = flower_mount_plan.get("mounts")
        if not isinstance(mounts, Sequence):
            raise GlobalL1FlowError("V2 flower mount inventory is invalid")
        if len(mounts) != int(
            plan["count_derivation"]["required_support_count"]
        ):
            raise GlobalL1FlowError("V2 flower support count mismatch")
        if (
            len(plan["lanes"]) + len(mounts)
            != int(plan["count_derivation"]["selected_l1_count"])
        ):
            raise GlobalL1FlowError(
                "V2 total L1 count does not include frozen flower supports"
            )
        if len(plan["lanes"]) != int(
            plan["count_derivation"]["selected_ordinary_l1_count"]
        ):
            raise GlobalL1FlowError(
                "V2 selected ordinary L1 count mismatch"
            )
        density_level = plan["count_derivation"].get(
            "ordinary_density_level"
        )
        if density_level not in ORDINARY_DENSITY_LEVELS:
            raise GlobalL1FlowError("V2 ordinary density level is invalid")
        if int(plan["solver"].get("selected_ordinary_l1_count", -1)) != len(
            plan["lanes"]
        ):
            raise GlobalL1FlowError(
                "solver selected count does not match the actual lane set"
            )
        if plan.get("schema") == SCHEMA_V2:
            if (
                plan["count_derivation"].get("ordinary_density_source")
                == "explicit_review_override"
                and plan["count_derivation"].get(
                    "density_levels_have_distinct_counts"
                )
                is not True
            ):
                raise GlobalL1FlowError(
                    "V2 controlled density review domain collapsed"
                )
            resolved_density_domain = plan["count_derivation"].get(
                "resolved_ordinary_l1_count_domain"
            )
            if (
                not isinstance(resolved_density_domain, Mapping)
                or set(resolved_density_domain) != set(ORDINARY_DENSITY_LEVELS)
                or len(plan["lanes"])
                != int(resolved_density_domain[density_level])
            ):
                raise GlobalL1FlowError(
                    "V2 density level did not determine the actual ordinary L1 count"
                )
        else:
            solver = plan["solver"]
            count_derivation = plan["count_derivation"]
            witnessed_counts = solver.get(
                "geometry_witnessed_ordinary_l1_counts"
            )
            if (
                not isinstance(witnessed_counts, Sequence)
                or isinstance(witnessed_counts, (str, bytes))
                or len(plan["lanes"])
                not in {int(value) for value in witnessed_counts}
            ):
                raise GlobalL1FlowError(
                    "V3 selected count is not geometry-witnessed"
                )
            density_control_profile = plan.get("density_control_profile")
            if density_control_profile is None:
                if (
                    solver.get("selected_count_as_result") is not True
                    or count_derivation.get("selected_count_as_result") is not True
                    or solver.get("selected_set_and_count_jointly_ranked") is not True
                    or count_derivation.get(
                        "selected_set_and_count_jointly_ranked"
                    )
                    is not True
                    or solver.get("density_count_mapping_used") is not False
                    or count_derivation.get("density_count_mapping_used") is not False
                ):
                    raise GlobalL1FlowError(
                        "V3 density did not jointly rank set and count as a result"
                    )
                if any(
                    key in solver or key in count_derivation
                    for key in (
                        "resolved_ordinary_l1_count_domain",
                        "density_levels_have_distinct_counts",
                        "count_selected_by_ordinary_density_policy",
                    )
                ):
                    raise GlobalL1FlowError(
                        "V3 plan reintroduced an exact density-count mapping"
                    )
            else:
                targets = density_control_profile.get(
                    "target_total_l1_count_by_level"
                )
                if (
                    density_control_profile.get("schema")
                    != DENSITY_CONTROL_PROFILE_SCHEMA
                    or not isinstance(targets, Mapping)
                    or int(count_derivation.get("target_total_l1_count", -1))
                    != int(targets[density_level])
                    or int(count_derivation.get("selected_l1_count", -1))
                    != int(targets[density_level])
                    or solver.get("selected_count_as_result") is not False
                    or count_derivation.get("selected_count_as_result") is not False
                    or solver.get("selected_set_and_count_jointly_ranked") is not False
                    or count_derivation.get(
                        "selected_set_and_count_jointly_ranked"
                    )
                    is not False
                    or solver.get("density_count_mapping_used") is not True
                    or count_derivation.get("density_count_mapping_used") is not True
                ):
                    raise GlobalL1FlowError(
                        "V3 visual density control was not consumed exactly"
                    )
            density_objective = solver.get("density_objective")
            if (
                not isinstance(density_objective, Mapping)
                or density_objective.get("density_level") != density_level
                or not isinstance(density_objective.get("selected"), Mapping)
                or count_derivation.get("density_objective")
                != density_objective
            ):
                raise GlobalL1FlowError(
                    "V3 plan lacks the consumed soft density objective"
                )
            best_by_cardinality = solver.get("best_objective_by_cardinality")
            if (
                not isinstance(best_by_cardinality, Mapping)
                or set(best_by_cardinality)
                != {str(int(value)) for value in witnessed_counts}
            ):
                raise GlobalL1FlowError(
                    "V3 soft objective did not compare every witnessed cardinality"
                )
        if plan.get("preassigned_selection_slots_used") is not False:
            raise GlobalL1FlowError(
                "V2 plan reintroduced preassigned selection slots"
            )
        if "slots" in plan:
            raise GlobalL1FlowError(
                "V2 plan exports obsolete preassigned slots"
            )
        selected_lane_ids = [
            str(lane.get("selected_l1_id")) for lane in plan["lanes"]
        ]
        if (
            any(value == "None" for value in selected_lane_ids)
            or len(selected_lane_ids) != len(set(selected_lane_ids))
            or any(
                lane.get("slot_id") != lane.get("selected_l1_id")
                for lane in plan["lanes"]
            )
        ):
            raise GlobalL1FlowError(
                "V2 post-selection lane identities are invalid"
            )
        root_spacing = float(plan["solver"]["root_spacing_hard"])
        lane_clearance = float(plan["solver"]["lane_clearance_hard"])
        for lane in plan["lanes"]:
            lane_points = [
                _point(value, "lane.centerline")
                for value in lane["centerline"]
            ]
            for mount in mounts:
                if _periodic_delta(
                    float(lane["root_s"]),
                    float(mount["root_s"]),
                ) < root_spacing - 1e-9:
                    raise GlobalL1FlowError(
                        "ordinary root conflicts with upstream flower support"
                    )
                mount_points = [
                    _point(value, "flower_mount.centerline")
                    for value in mount["centerline"]
                ]
                if min(
                    global_l1_polyline_distance_batch(
                        lane_points,
                        mount_points,
                        offset,
                    )
                    for offset in (-1.0, 0.0, 1.0)
                ) < lane_clearance - 1e-9:
                    raise GlobalL1FlowError(
                        "ordinary lane conflicts with upstream flower support"
                    )
        sample_indices = [
            int(lane["features"]["editor_geometry_sample_index"])
            for lane in plan["lanes"]
        ]
        if len(sample_indices) != len(set(sample_indices)):
            raise GlobalL1FlowError(
                "V2 plan repeats a continuous geometry draw"
            )
        for lane in plan["lanes"]:
            features = lane.get("features", {})
            if not all(
                key in features
                for key in (
                    "editor_start_handle_chord_ratio",
                    "editor_end_handle_chord_ratio",
                    "editor_start_angle_abs_deg",
                    "editor_end_angle_chord_deg",
                    "editor_end_angle_normalized_deg",
                    "editor_parent_tangent_departure_deg",
                    "descriptor_mean_quantile",
                    "editor_geometry_sample_index",
                    "editor_start_chord_angle_error_deg",
                )
            ):
                raise GlobalL1FlowError(
                    "V2 lane lacks learned continuous descriptors"
                )
            if float(
                features["editor_start_chord_angle_error_deg"]
            ) > 1e-5:
                raise GlobalL1FlowError(
                    "V2 lane does not preserve its sampled internal geometry"
                )
            if not isinstance(lane.get("editor_geometry_sample_id"), str):
                raise GlobalL1FlowError("V2 lane lacks a geometry sample id")
            if lane.get("editor_geometry_source") != (
                "continuous_gaussian_copula_over_editor_descriptors"
            ):
                raise GlobalL1FlowError(
                    "V2 lane did not consume the continuous descriptor field"
                )
