#!/usr/bin/env python3
"""Stage-4 complete BranchUnit grammar and deterministic candidate generator.

The approved stage-3B L1 geometry is immutable.  This module enumerates the
declared grammar/role/parameter strata exactly once, materializes L2/L3 cubic
Bezier descendants, and preserves every valid or invalid candidate.  It never
repairs, retries, resamples, deletes, or globally selects candidates.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np

from geometry_batch import (
    point_segment_distance_matrix_batch,
    polyline_pair_intersects,
    polyline_pair_minimum_distance,
    segments_intersect_batch,
)
from prototype_strategy_v1 import validate_strategy_projection


SCHEMA = "dynamic_branch_stage4_unit_candidate_inventory_v1"
SCHEMA_V2 = "dynamic_branch_stage4_unit_candidate_inventory_v2"
CANDIDATE_SCHEMA = "dynamic_branch_unit_candidate_v1"
CANDIDATE_SCHEMA_V2 = "dynamic_branch_unit_candidate_v2"
CONTRACT_SCHEMA = "dynamic_branch_stage4_unit_grammar_contract_v1"
CONTRACT_SCHEMA_V2 = "dynamic_branch_stage4_unit_grammar_contract_v2"
EDITOR_L2_PRIOR_SCHEMA = "dynamic_branch_editor_l2_placement_prior_v1"
Point = tuple[float, float]


class UnitGrammarError(RuntimeError):
    """The stage-4 grammar input or complete candidate pool is invalid."""


def _editor_l2_profile(
    editor_l2_prior: Mapping[str, Any],
    prototype_id: str,
    profile_key: str | None = None,
) -> Mapping[str, Any]:
    if editor_l2_prior.get("schema") != EDITOR_L2_PRIOR_SCHEMA:
        raise UnitGrammarError("editor L2 placement prior schema mismatch")
    profiles = editor_l2_prior.get("profiles")
    if not isinstance(profiles, Mapping):
        raise UnitGrammarError("editor L2 placement prior has no profiles")
    profile = profiles.get(profile_key or prototype_id) or profiles.get("global")
    if not isinstance(profile, Mapping):
        raise UnitGrammarError(
            f"editor L2 placement prior has no profile for {prototype_id}"
        )
    if int(profile.get("active_l2_count", 0)) < 5:
        raise UnitGrammarError("editor L2 placement profile is too small")
    return profile


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _finite(value: object, path: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise UnitGrammarError(f"{path} must be finite")
    return number


def _point(value: object, path: str = "point") -> Point:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
    ):
        raise UnitGrammarError(f"{path} must be a two-number point")
    return _finite(value[0], f"{path}[0]"), _finite(value[1], f"{path}[1]")


def _round(value: float) -> float:
    return round(float(value), 9)


def _round_point(point: Point) -> list[float]:
    return [_round(point[0]), _round(point[1])]


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scalar: float) -> Point:
    return a[0] * scalar, a[1] * scalar


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _length(vector: Point) -> float:
    return math.hypot(vector[0], vector[1])


def _distance(a: Point, b: Point) -> float:
    return _length(_sub(a, b))


def _unit(vector: Point, path: str = "vector") -> Point:
    length = _length(vector)
    if length <= 1e-12:
        raise UnitGrammarError(f"{path} must be non-degenerate")
    return vector[0] / length, vector[1] / length


def _rotate(vector: Point, degrees: float) -> Point:
    angle = math.radians(degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return (
        vector[0] * cosine - vector[1] * sine,
        vector[0] * sine + vector[1] * cosine,
    )


def _lerp(a: Point, b: Point, fraction: float) -> Point:
    return (
        a[0] + (b[0] - a[0]) * fraction,
        a[1] + (b[1] - a[1]) * fraction,
    )


def _cubic(
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


def _circular_arc_cubics(
    root: Point,
    entry: Point,
    signed_turn_degrees: float,
    arc_length: float,
    segment_count: int = 2,
) -> list[dict[str, list[float]]]:
    """Approximate a constant-curvature arc with tangent-matched cubics."""

    total_radians = math.radians(signed_turn_degrees)
    radius = arc_length / abs(total_radians)
    turn_sign = 1.0 if total_radians > 0.0 else -1.0
    normal = (-entry[1], entry[0])
    center = _add(root, _mul(normal, turn_sign * radius))
    root_radius = _sub(root, center)
    segment_degrees = signed_turn_degrees / segment_count
    segment_radians = total_radians / segment_count
    handle_length = (
        4.0
        / 3.0
        * radius
        * math.tan(abs(segment_radians) / 4.0)
    )
    segments: list[dict[str, list[float]]] = []
    for index in range(segment_count):
        start_degrees = segment_degrees * index
        end_degrees = segment_degrees * (index + 1)
        p0 = _add(center, _rotate(root_radius, start_degrees))
        p3 = _add(center, _rotate(root_radius, end_degrees))
        start_tangent = _rotate(entry, start_degrees)
        end_tangent = _rotate(entry, end_degrees)
        segments.append(
            _cubic(
                p0,
                _add(p0, _mul(start_tangent, handle_length)),
                _sub(p3, _mul(end_tangent, handle_length)),
                p3,
            )
        )
    return segments


def _cubic_point(segment: Mapping[str, Sequence[float]], t: float) -> Point:
    p0 = _point(segment["p0"], "segment.p0")
    p1 = _point(segment["p1"], "segment.p1")
    p2 = _point(segment["p2"], "segment.p2")
    p3 = _point(segment["p3"], "segment.p3")
    u = 1.0 - t
    return (
        u**3 * p0[0]
        + 3.0 * u * u * t * p1[0]
        + 3.0 * u * t * t * p2[0]
        + t**3 * p3[0],
        u**3 * p0[1]
        + 3.0 * u * u * t * p1[1]
        + 3.0 * u * t * t * p2[1]
        + t**3 * p3[1],
    )


def _sample_segments(
    segments: Sequence[Mapping[str, Sequence[float]]],
    count: int = 36,
) -> list[Point]:
    points: list[Point] = []
    for segment_index, segment in enumerate(segments):
        start = 0 if segment_index == 0 else 1
        points.extend(
            _cubic_point(segment, index / count)
            for index in range(start, count + 1)
        )
    return points


def _polyline_length(points: Sequence[Point]) -> float:
    return sum(
        _distance(points[index - 1], points[index])
        for index in range(1, len(points))
    )


def _sample_polyline(
    points: Sequence[Point],
    fraction: float,
) -> tuple[Point, Point]:
    if len(points) < 2:
        raise UnitGrammarError("polyline needs at least two points")
    lengths = [
        _distance(points[index - 1], points[index])
        for index in range(1, len(points))
    ]
    total = sum(lengths)
    if total <= 1e-12:
        raise UnitGrammarError("polyline must be non-degenerate")
    target = max(0.0, min(1.0, fraction)) * total
    traversed = 0.0
    for index, segment_length in enumerate(lengths, start=1):
        if traversed + segment_length >= target or index == len(lengths):
            local = (target - traversed) / segment_length
            return (
                _lerp(points[index - 1], points[index], local),
                _unit(_sub(points[index], points[index - 1]), "polyline tangent"),
            )
        traversed += segment_length
    raise AssertionError("unreachable polyline sample")


def _angle_degrees(a: Point, b: Point) -> float:
    cosine = max(-1.0, min(1.0, _dot(_unit(a), _unit(b))))
    return math.degrees(math.acos(cosine))


def _halton(index: int, base: int, scramble: int) -> float:
    if index <= 0:
        raise UnitGrammarError("Halton index must be positive")
    result = 0.0
    factor = 1.0 / base
    value = index
    while value:
        digit = value % base
        digit = (digit + scramble) % base
        result += digit * factor
        value //= base
        factor /= base
    return result


def _seed_scramble(seed: int, lane_id: str, dimension: int, base: int) -> int:
    digest = hashlib.sha256(
        f"{seed}|{lane_id}|{dimension}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:4], "big") % base


def _quantile(statistic: Mapping[str, Any], quantile: float) -> float:
    samples = [float(value) for value in statistic["samples"]]
    if not samples:
        raise UnitGrammarError("empirical statistic has no samples")
    position = max(0.0, min(1.0, quantile)) * (len(samples) - 1)
    lower = int(math.floor(position))
    upper = min(len(samples) - 1, lower + 1)
    return samples[lower] + (samples[upper] - samples[lower]) * (
        position - lower
    )


def _stat(
    prior: Mapping[str, Any],
    role_condition: str,
    name: str,
) -> Mapping[str, Any]:
    role_stats = prior["statistics"]["role_conditioned"].get(role_condition)
    if not isinstance(role_stats, Mapping) or name not in role_stats:
        raise UnitGrammarError(
            f"fixed visual prior lacks {role_condition}.{name}"
        )
    statistic = role_stats[name]
    if not isinstance(statistic, Mapping):
        raise UnitGrammarError(
            f"fixed visual prior statistic is invalid: {role_condition}.{name}"
        )
    return statistic


def _candidate_strata(
    lane: Mapping[str, Any],
    contract: Mapping[str, Any],
    editor_l2_profile: Mapping[str, Any] | None = None,
) -> list[tuple[str, str, bool, str]]:
    if contract.get("schema") == CONTRACT_SCHEMA_V2:
        coverage = contract["candidate_coverage"]["weak_role_grammar_strata"]
        paired_histogram = (
            editor_l2_profile.get(
                "paired_child_departure_turn_pattern_histogram",
                {},
            )
            if editor_l2_profile
            else {}
        )
        paired_variants = [
            str(variant)
            for variant in contract["candidate_coverage"][
                "paired_child_turn_sign_variants"
            ]
            if variant != "context_swapped"
            or (
                isinstance(paired_histogram, Mapping)
                and int(paired_histogram.get("negative+positive", 0)) > 0
                and int(paired_histogram.get("positive+negative", 0)) > 0
            )
            if variant != "editor_same_sign"
            or (
                isinstance(paired_histogram, Mapping)
                and (
                    int(paired_histogram.get("negative+negative", 0)) > 0
                    or int(paired_histogram.get("positive+positive", 0)) > 0
                )
            )
        ]
        return [
            (grammar_id, str(stratum), False, str(turn_sign_variant))
            for grammar_id in ("L1-Only", "Y-C", "Y-2C")
            for sample_index in range(3 if grammar_id == "Y-2C" else 1)
            for stratum in coverage[grammar_id]
            for turn_sign_variant in (
                contract["candidate_coverage"][
                    "single_child_turn_sign_variants"
                ]
                if grammar_id == "Y-C"
                else paired_variants
                if grammar_id == "Y-2C"
                else ("context_preferred",)
            )
        ]
    role = str(lane["role"])
    coverage = contract["candidate_coverage"]
    if role in {"primary_sweep", "balance"}:
        rows: list[tuple[str, str, bool, str]] = []
        for grammar_id in ("Y-C", "Y-2C"):
            for stratum in coverage["ordinary_grammar_strata"][grammar_id]:
                rows.append(
                    (
                        grammar_id,
                        str(stratum),
                        stratum in {"open_c", "open_asymmetric"},
                        "context_preferred",
                    )
                )
        return rows
    if role == "frontier":
        return [
            (
                "Frontier-Y-C",
                str(stratum),
                stratum == "outer_hook",
                "context_preferred",
            )
            for stratum in coverage["frontier_strata"]
        ]
    if role == "flower_support":
        return [
            ("FlowerSupport-C", str(stratum), False, "context_preferred")
            for stratum in coverage["flower_support_strata"]
        ]
    if role == "terminal_flower_support":
        return [
            (
                "TerminalSupport-C",
                str(stratum),
                False,
                "context_preferred",
            )
            for stratum in coverage["terminal_support_strata"]
        ]
    raise UnitGrammarError(f"unsupported stage-3B lane role: {role}")


def _role_condition(role: str, level: int) -> str:
    if level == 3:
        return "tertiary_lateral"
    if role == "frontier":
        return "secondary_frontier"
    if role == "flower_support":
        return "secondary_flower_wrap"
    return "secondary_lateral"


def _local_density_scale(
    lane: Mapping[str, Any],
    all_lanes: Sequence[Mapping[str, Any]],
) -> float:
    root_s = float(lane["root_s"])
    gaps = sorted(
        min(abs(root_s - float(other["root_s"])), 1.0 - abs(root_s - float(other["root_s"])))
        for other in all_lanes
        if other["slot_id"] != lane["slot_id"]
    )
    if not gaps:
        return 1.0
    nearest = gaps[0]
    return max(0.72, min(1.05, 0.72 + nearest / 0.22 * 0.33))


def _nearest_backbone_vector(
    analysis: Mapping[str, Any],
    point: Point,
) -> Point:
    backbone_points = [
        _point(row["point"], "backbone.point")
        for row in analysis["backbone"]["samples"]
    ]
    nearest = min(backbone_points, key=lambda value: _distance(point, value))
    vector = _sub(point, nearest)
    if _length(vector) <= 1e-8:
        tangent = _unit(
            _sub(backbone_points[-1], backbone_points[0]),
            "backbone endpoint tangent",
        )
        return -tangent[1], tangent[0]
    return _unit(vector, "outward vector")


def _child_signs(
    parent_points: Sequence[Point],
    mounts: Sequence[float],
    analysis: Mapping[str, Any],
    lane: Mapping[str, Any],
    asymmetry: float,
    turn_sign_variant: str,
    editor_l2_profile: Mapping[str, Any] | None,
) -> list[int]:
    signs: list[int] = []
    for index, mount in enumerate(mounts):
        root, tangent = _sample_polyline(parent_points, mount)
        outward = _nearest_backbone_vector(analysis, root)
        flower_avoidance = (0.0, 0.0)
        for flower in analysis["flowers"]:
            center = _point(flower["center"], "flower.center")
            near_center = min(
                (
                    (center[0] - 1.0, center[1]),
                    center,
                    (center[0] + 1.0, center[1]),
                ),
                key=lambda value: _distance(root, value),
            )
            away = _sub(root, near_center)
            distance = max(0.04, _length(away))
            weight = (
                2.2
                if lane["role"] == "flower_support"
                and flower["flower_id"] == lane["flower_id"]
                else 0.8
            )
            flower_avoidance = _add(
                flower_avoidance,
                _mul(_unit(away, "flower avoidance"), weight / distance),
            )
        positive_direction = _rotate(tangent, 55.0)
        negative_direction = _rotate(tangent, -55.0)
        positive = _dot(positive_direction, outward) + 0.55 * _dot(
            positive_direction,
            flower_avoidance,
        ) + 0.08 * asymmetry
        negative = _dot(negative_direction, outward) + 0.55 * _dot(
            negative_direction,
            flower_avoidance,
        ) - 0.08 * asymmetry
        preferred = 1 if positive >= negative else -1
        if len(mounts) == 2 and index == 1:
            preferred *= -1
        signs.append(preferred)
    if len(signs) == 1 and turn_sign_variant == "context_opposed":
        if editor_l2_profile is None:
            raise UnitGrammarError(
                "opposed child turn candidate lacks editor evidence"
            )
        histogram = editor_l2_profile.get(
            "single_child_departure_turn_sign_histogram",
            {},
        )
        if not (
            isinstance(histogram, Mapping)
            and int(histogram.get("positive", 0)) > 0
            and int(histogram.get("negative", 0)) > 0
        ):
            raise UnitGrammarError(
                "editor profile does not demonstrate both child turn signs"
            )
        signs[0] *= -1
    elif len(signs) == 2 and turn_sign_variant == "context_swapped":
        if editor_l2_profile is None:
            raise UnitGrammarError(
                "swapped paired-child candidate lacks editor evidence"
            )
        histogram = editor_l2_profile.get(
            "paired_child_departure_turn_pattern_histogram",
            {},
        )
        if not (
            isinstance(histogram, Mapping)
            and int(histogram.get("negative+positive", 0)) > 0
            and int(histogram.get("positive+negative", 0)) > 0
        ):
            raise UnitGrammarError(
                "editor profile does not demonstrate both paired turn orders"
            )
        signs = [-sign for sign in signs]
    elif len(signs) == 2 and turn_sign_variant == "editor_same_sign":
        if editor_l2_profile is None:
            raise UnitGrammarError(
                "same-sign paired-child candidate lacks editor evidence"
            )
        histogram = editor_l2_profile.get(
            "paired_child_departure_turn_pattern_histogram",
            {},
        )
        negative_count = (
            int(histogram.get("negative+negative", 0))
            if isinstance(histogram, Mapping)
            else 0
        )
        positive_count = (
            int(histogram.get("positive+positive", 0))
            if isinstance(histogram, Mapping)
            else 0
        )
        if max(negative_count, positive_count) <= 0:
            raise UnitGrammarError(
                "editor profile does not demonstrate same-sign paired turns"
            )
        editor_sign = -1 if negative_count >= positive_count else 1
        signs = [editor_sign, editor_sign]
    elif turn_sign_variant != "context_preferred":
        raise UnitGrammarError(
            f"unsupported child turn sign variant: {turn_sign_variant}"
        )
    return signs


def _mounts(
    prior: Mapping[str, Any],
    role_condition: str,
    count: int,
    quantiles: Sequence[float],
    contract: Mapping[str, Any],
    editor_l2_profile: Mapping[str, Any] | None = None,
) -> list[float]:
    if count == 0:
        return []
    low, high = [
        float(value) for value in contract["geometry"]["mount_fraction_range"]
    ]
    if editor_l2_profile is not None:
        if count == 1:
            mount = _quantile(
                editor_l2_profile["single_child_mount_fraction"],
                quantiles[0],
            )
            return [max(low, min(high, mount))]
        center = _quantile(
            editor_l2_profile["paired_child_mount_center"],
            quantiles[0],
        )
        separation = _quantile(
            editor_l2_profile["paired_child_mount_separation"],
            quantiles[1],
        )
        minimum_gap = float(
            contract["geometry"]["minimum_sibling_mount_separation"]
        )
        separation = max(minimum_gap, min(high - low, separation))
        lower = max(low, min(high - separation, center - separation * 0.5))
        return [lower, lower + separation]
    statistic = _stat(prior, role_condition, "mount_fraction")
    if count == 1:
        return [max(low, min(high, _quantile(statistic, quantiles[0])))]
    center = _quantile(statistic, quantiles[0])
    minimum_gap = float(
        contract["geometry"]["minimum_sibling_mount_separation"]
    )
    expansion = minimum_gap + 0.04 * quantiles[1]
    lower = max(low, min(high - expansion, center - expansion * 0.5))
    upper = lower + expansion
    return [lower, upper]


def _contextual_mounts(
    parent_points: Sequence[Point],
    preferred_mounts: Sequence[float],
    lane: Mapping[str, Any],
    analysis: Mapping[str, Any],
    contract: Mapping[str, Any],
    phase: float,
) -> list[float]:
    """Solve prior fidelity and flower-clearance before geometry materialization."""

    low, high = [
        float(value) for value in contract["geometry"]["mount_fraction_range"]
    ]
    minimum_gap = float(
        contract["geometry"]["minimum_sibling_mount_separation"]
    )
    samples = [
        low + (high - low) * index / 48.0
        for index in range(49)
    ]

    def clearance(fraction: float) -> float:
        point, _ = _sample_polyline(parent_points, fraction)
        values: list[float] = []
        for flower in analysis["flowers"]:
            is_sw1_target = (
                lane["role"] == "flower_support"
                and flower["flower_id"] == lane["flower_id"]
            )
            values.append(
                _ellipse_value(
                    point,
                    flower,
                    protection=not is_sw1_target,
                )
            )
        return min(values, default=4.0)

    selected: list[float] = []
    for index, preferred in enumerate(preferred_mounts):
        eligible = [
            fraction
            for fraction in samples
            if all(abs(fraction - other) >= minimum_gap for other in selected)
        ]
        if not eligible:
            raise UnitGrammarError(
                f"{lane['slot_id']} has no legal sibling mount interval"
            )
        chosen = max(
            eligible,
            key=lambda fraction: (
                min(4.0, clearance(fraction))
                - 1.45 * abs(fraction - preferred)
                + 0.035
                * math.cos(
                    2.0
                    * math.pi
                    * (fraction + phase + index * 0.31)
                ),
                -abs(fraction - preferred),
                -fraction,
            ),
        )
        selected.append(chosen)
    return sorted(selected)


def _child_length_ratio(
    prior: Mapping[str, Any],
    role: str,
    level: int,
    quantile: float,
    parent_length: float,
    density_scale: float,
    contract: Mapping[str, Any],
) -> float:
    role_condition = _role_condition(role, level)
    empirical = _quantile(
        _stat(prior, role_condition, "child_to_parent_actual_ratio"),
        quantile,
    )
    if level == 3:
        bounds = contract["geometry"]["tertiary_parent_length_ratio_range"]
    elif role == "frontier":
        bounds = contract["geometry"]["frontier_child_parent_length_ratio_range"]
    elif role == "flower_support":
        bounds = contract["geometry"][
            "flower_support_child_parent_length_ratio_range"
        ]
    elif role == "terminal_flower_support":
        bounds = contract["geometry"][
            "terminal_support_child_parent_length_ratio_range"
        ]
    else:
        bounds = contract["geometry"]["ordinary_child_parent_length_ratio_range"]
    long_parent_scale = max(0.68, min(1.08, 1.08 - 0.42 * max(0.0, parent_length - 0.24)))
    value = empirical * density_scale * long_parent_scale
    return max(float(bounds[0]), min(float(bounds[1]), value))


def _compile_child_curve(
    *,
    curve_id: str,
    branch_unit_id: str,
    parent_curve: Mapping[str, Any],
    mount_fraction: float,
    sign: int,
    role: str,
    semantic_role: str,
    level: int,
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    quantiles: Sequence[float],
    density_scale: float,
    shape_signature: str,
    target_flower: Mapping[str, Any] | None,
) -> dict[str, Any]:
    parent_points = [
        _point(value, f"{parent_curve['curve_id']}.centerline")
        for value in parent_curve["centerline"]
    ]
    root, parent_tangent = _sample_polyline(parent_points, mount_fraction)
    parent_length = _polyline_length(parent_points)
    role_condition = _role_condition(role, level)
    empirical_opening = _quantile(
        _stat(prior, role_condition, "entry_opening_degrees"),
        quantiles[0],
    )
    if shape_signature == "S":
        opening_key = "s_entry_opening_degrees_range"
    elif role == "flower_support":
        opening_key = "flower_wrap_c_entry_opening_degrees_range"
    else:
        opening_key = "c_entry_opening_degrees_range"
    opening_low, opening_high = [
        float(value) for value in contract["geometry"][opening_key]
    ]
    opening = opening_low + (opening_high - opening_low) * quantiles[0]
    entry = _unit(_rotate(parent_tangent, sign * opening), "child entry")
    ratio = _child_length_ratio(
        prior,
        role,
        level,
        quantiles[1],
        parent_length,
        density_scale,
        contract,
    )
    intended_length = parent_length * ratio
    release = _quantile(
        _stat(prior, role_condition, "exit_release_degrees"),
        quantiles[2],
    )
    handle_ratio = _quantile(
        _stat(prior, role_condition, "handle_ratio"),
        quantiles[3],
    )
    curl_energy = 0.92 + 0.18 * quantiles[4]
    transverse = (-entry[1], entry[0])

    if shape_signature == "S":
        s_turn_low, s_turn_high = [
            float(value)
            for value in contract["geometry"]["s_internal_turn_degrees_range"]
        ]
        s_internal_turn = s_turn_low + (
            s_turn_high - s_turn_low
        ) * quantiles[2]
        first_turn = -sign * s_internal_turn * (
            0.52 + 0.16 * quantiles[3]
        )
        first_length = intended_length * (
            0.46 + 0.10 * quantiles[4]
        )
        first_segment = _circular_arc_cubics(
            root,
            entry,
            first_turn,
            first_length,
            segment_count=1,
        )[0]
        inflection = _point(first_segment["p3"])
        inflection_tangent = _unit(
            _sub(
                _point(first_segment["p3"]),
                _point(first_segment["p2"]),
            ),
            "child S inflection tangent",
        )
        second_turn = sign * (
            8.0 + (s_internal_turn - 8.0) * (0.16 + 0.16 * quantiles[0])
        )
        second_segment = _circular_arc_cubics(
            inflection,
            inflection_tangent,
            second_turn,
            intended_length - first_length,
            segment_count=1,
        )[0]
        segments = [first_segment, second_segment]
    else:
        c_turn_low, c_turn_high = [
            float(value)
            for value in contract["geometry"]["c_internal_turn_degrees_range"]
        ]
        c_internal_turn = c_turn_low + (
            c_turn_high - c_turn_low
        ) * quantiles[2]
        c_handle_low, c_handle_high = [
            float(value)
            for value in contract["geometry"]["c_handle_ratio_range"]
        ]
        handle_ratio = c_handle_low + (
            c_handle_high - c_handle_low
        ) * quantiles[3]
        if role == "flower_support":
            if target_flower is None:
                raise UnitGrammarError(
                    f"{curve_id} flower wrap lacks its target flower"
                )
            center = _point(target_flower["center"], "target_flower.center")
            near_center = min(
                (
                    (center[0] - 1.0, center[1]),
                    center,
                    (center[0] + 1.0, center[1]),
                ),
                key=lambda value: _distance(root, value),
            )
            rx = float(target_flower["rx"])
            ry = float(target_flower["ry"])
            delta = _sub(root, near_center)
            outward = _unit(
                (delta[0] / (rx * rx), delta[1] / (ry * ry)),
                "flower ellipse outward gradient",
            )
            tangent_a = (-outward[1], outward[0])
            tangent_b = (outward[1], -outward[0])
            wrap_tangent = (
                tangent_a
                if _dot(tangent_a, entry) >= _dot(tangent_b, entry)
                else tangent_b
            )
            end_direction = _unit(
                _add(
                    _add(_mul(entry, 0.78), _mul(wrap_tangent, 0.22)),
                    _mul(outward, 0.10),
                ),
                "flower wrap exit",
            )
            tip_direction = _unit(
                _add(_mul(entry, 0.58), _mul(end_direction, 0.42)),
                "flower wrap tip direction",
            )
            tip = _add(
                root,
                _add(
                    _mul(tip_direction, intended_length * 0.88),
                    _mul(outward, intended_length * 0.20),
                ),
            )
        else:
            end_direction = _unit(
                _rotate(entry, -sign * c_internal_turn),
                "child C exit",
            )
            tip_direction = _unit(
                _add(_mul(entry, 0.48), _mul(end_direction, 0.52)),
                "child tip direction",
            )
            tip = _add(
                root,
                _add(
                    _mul(tip_direction, intended_length * 0.92),
                    _mul(
                        transverse,
                        sign * intended_length * 0.05 * curl_energy,
                    ),
                ),
            )
        segments = [
            _cubic(
                root,
                _add(root, _mul(entry, intended_length * handle_ratio)),
                _sub(tip, _mul(end_direction, intended_length * handle_ratio)),
                tip,
            )
        ]

    centerline = _sample_segments(segments, 32)
    actual_length = _polyline_length(centerline)
    return {
        "curve_id": curve_id,
        "branch_unit_id": branch_unit_id,
        "level": f"L{level}",
        "hierarchy_level": level,
        "parent_curve_id": parent_curve["curve_id"],
        "mount_fraction": _round(mount_fraction),
        "semantic_role": semantic_role,
        "shape_signature": shape_signature,
        "turn_sign": sign,
        "entry_opening_degrees": _round(opening),
        "intended_parent_length_ratio": _round(ratio),
        "actual_length": _round(actual_length),
        "cubic_segments": segments,
        "centerline": [_round_point(point) for point in centerline],
        "sampling_trace": {
            "role_condition": role_condition,
            "quantiles": [_round(value) for value in quantiles],
            "empirical_entry_opening_degrees": _round(
                empirical_opening
            ),
            "empirical_exit_release_degrees": _round(release),
            "density_scale": _round(density_scale),
            "generated_once": True,
        },
    }


def _l1_curve(lane: Mapping[str, Any], branch_unit_id: str) -> dict[str, Any]:
    segments = [dict(segment) for segment in lane["segments"]]
    centerline = _sample_segments(segments, 36)
    return {
        "curve_id": f"{branch_unit_id}.L1",
        "branch_unit_id": branch_unit_id,
        "level": "L1",
        "hierarchy_level": 1,
        "parent_curve_id": None,
        "mount_fraction": None,
        "semantic_role": str(lane["role"]),
        "shape_signature": str(lane["curvature_signature"]),
        "turn_sign": 0,
        "entry_opening_degrees": None,
        "intended_parent_length_ratio": None,
        "actual_length": _round(_polyline_length(centerline)),
        "cubic_segments": segments,
        "centerline": [_round_point(point) for point in centerline],
        "sampling_trace": {
            "source": "approved_stage3b_immutable_l1",
            "source_candidate_id": lane["candidate_id"],
        },
    }


def _candidate_quantiles(
    seed: int,
    lane_id: str,
    candidate_index: int,
) -> list[float]:
    bases = (2, 3, 5, 7, 11, 13, 17, 19)
    return [
        _halton(
            candidate_index + 1,
            base,
            _seed_scramble(seed, lane_id, dimension, base),
        )
        for dimension, base in enumerate(bases)
    ]


def _shape_from_stratum(stratum: str, index: int) -> str:
    if "_s" in stratum or stratum in {"nested_s", "subordinate_s"}:
        return "S"
    if "hook" in stratum:
        return "S"
    if stratum == "open_asymmetric" and index == 1:
        return "S"
    return "C"


def _length_quantile_for_stratum(stratum: str, value: float) -> float:
    """Map a low-discrepancy value into the declared empirical length band."""

    if "compact" in stratum:
        low, high = 0.34, 0.54
    elif stratum in {"open_c", "open_asymmetric", "long_c", "long_s"}:
        low, high = 0.72, 0.97
    elif stratum in {
        "outer_hook",
        "nested_s",
        "lower_wrap_s",
        "subordinate_s",
    }:
        low, high = 0.64, 0.88
    else:
        low, high = 0.50, 0.78
    return low + (high - low) * value


def _occupancy_tubes(
    curves: Sequence[Mapping[str, Any]],
    radius: float,
) -> list[dict[str, Any]]:
    tubes: list[dict[str, Any]] = []
    for curve in curves:
        points = [_point(row) for row in curve["centerline"]]
        tubes.append(
            {
                "curve_id": curve["curve_id"],
                "radius": _round(radius),
                "bounds": [
                    _round(min(point[0] for point in points) - radius),
                    _round(min(point[1] for point in points) - radius),
                    _round(max(point[0] for point in points) + radius),
                    _round(max(point[1] for point in points) + radius),
                ],
            }
        )
    return tubes


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


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    vector = _sub(end, start)
    denominator = _dot(vector, vector)
    if denominator <= 1e-18:
        return _distance(point, start)
    fraction = max(
        0.0,
        min(1.0, _dot(_sub(point, start), vector) / denominator),
    )
    return _distance(point, _add(start, _mul(vector, fraction)))


def _polyline_distance(
    a: Sequence[Point],
    b: Sequence[Point],
) -> float:
    minimum = float("inf")
    for index in range(1, len(a)):
        for other_index in range(1, len(b)):
            a0, a1 = a[index - 1], a[index]
            b0, b1 = b[other_index - 1], b[other_index]
            if _segments_intersect(a0, a1, b0, b1):
                return 0.0
            minimum = min(
                minimum,
                _point_segment_distance(a0, b0, b1),
                _point_segment_distance(a1, b0, b1),
                _point_segment_distance(b0, a0, a1),
                _point_segment_distance(b1, a0, a1),
            )
    return minimum


def _curve_crosses(
    a: Mapping[str, Any],
    b: Mapping[str, Any],
    allowed_junction: Point | None,
) -> bool:
    a_points = [_point(value) for value in a["centerline"]]
    b_points = [_point(value) for value in b["centerline"]]
    for index in range(1, len(a_points)):
        for other_index in range(1, len(b_points)):
            a0, a1 = a_points[index - 1], a_points[index]
            b0, b1 = b_points[other_index - 1], b_points[other_index]
            if not _segments_intersect(a0, a1, b0, b1):
                continue
            if (
                allowed_junction is not None
                and _point_segment_distance(allowed_junction, a0, a1) <= 1e-7
                and _point_segment_distance(allowed_junction, b0, b1) <= 1e-7
            ):
                continue
            return True
    return False


def _ellipse_value(
    point: Point,
    flower: Mapping[str, Any],
    *,
    protection: bool = True,
) -> float:
    center = _point(flower["center"], "flower.center")
    rx = float(flower["protection_rx"] if protection else flower["rx"])
    ry = float(flower["protection_ry"] if protection else flower["ry"])
    near_x = min(
        (point[0] - 1.0, point[0], point[0] + 1.0),
        key=lambda value: abs(value - center[0]),
    )
    return ((near_x - center[0]) / rx) ** 2 + ((point[1] - center[1]) / ry) ** 2


def _diagnose_candidate(
    candidate: Mapping[str, Any],
    analysis: Mapping[str, Any],
    contract: Mapping[str, Any],
    editor_l2_profile: Mapping[str, Any] | None = None,
    flower_mount_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    curves = candidate["curves"]
    curve_by_id = {curve["curve_id"]: curve for curve in curves}
    if len(curve_by_id) != len(curves):
        issues.append({"code": "duplicate_curve_id"})
    l1_curves = [curve for curve in curves if curve["level"] == "L1"]
    if len(l1_curves) != 1:
        issues.append({"code": "invalid_l1_count", "actual": len(l1_curves)})

    bounds_by_role = {
        "frontier": contract["geometry"]["frontier_child_parent_length_ratio_range"],
        "flower_support": contract["geometry"][
            "flower_support_child_parent_length_ratio_range"
        ],
        "terminal_flower_support": contract["geometry"][
            "terminal_support_child_parent_length_ratio_range"
        ],
        "ordinary": contract["geometry"]["ordinary_child_parent_length_ratio_range"],
        "tertiary": contract["geometry"]["tertiary_parent_length_ratio_range"],
    }
    openings: list[float] = []
    root_errors: list[float] = []
    departure_distances: list[float] = []
    parent_clearance_onset_fractions: list[float] = []
    post_departure_parent_clearances: list[float] = []
    parent_occupancy_reentry_count = 0
    parent_occupancy_clearance = 2.0 * float(
        contract["geometry"]["occupancy_radius"]
    )
    for curve in curves:
        for segment in curve["cubic_segments"]:
            for key in ("p0", "p1", "p2", "p3"):
                _point(segment[key], f"{curve['curve_id']}.{key}")
        if curve["level"] == "L1":
            continue
        parent_id = curve["parent_curve_id"]
        parent = curve_by_id.get(parent_id)
        if parent is None or parent["hierarchy_level"] + 1 != curve["hierarchy_level"]:
            issues.append(
                {"code": "invalid_parent_graph", "curve_id": curve["curve_id"]}
            )
            continue
        parent_points = [_point(value) for value in parent["centerline"]]
        expected_root, parent_tangent = _sample_polyline(
            parent_points,
            float(curve["mount_fraction"]),
        )
        root = _point(curve["cubic_segments"][0]["p0"])
        root_error = _distance(root, expected_root)
        root_errors.append(root_error)
        if root_error > 2e-6:
            issues.append(
                {
                    "code": "attachment_error",
                    "curve_id": curve["curve_id"],
                    "value": _round(root_error),
                }
            )
        entry = _unit(
            _sub(
                _point(curve["cubic_segments"][0]["p1"]),
                root,
            ),
            "child entry derivative",
        )
        opening = _angle_degrees(parent_tangent, entry)
        openings.append(opening)
        opening_bounds = contract["geometry"]["entry_opening_degrees_range"]
        if not float(opening_bounds[0]) - 0.5 <= opening <= float(opening_bounds[1]) + 0.5:
            issues.append(
                {
                    "code": "entry_opening_out_of_range",
                    "curve_id": curve["curve_id"],
                    "value": _round(opening),
                }
            )
        child_points = [_point(value) for value in curve["centerline"]]
        probe_index = max(2, int(len(child_points) * 0.30))
        parent_matrix = point_segment_distance_matrix_batch(
            np.asarray(child_points, dtype=np.float64),
            np.asarray(parent_points[:-1], dtype=np.float64),
            np.asarray(parent_points[1:], dtype=np.float64),
        )
        parent_distances = [
            float(value) for value in parent_matrix.min(axis=1)
        ]
        departure = parent_distances[probe_index]
        departure_distances.append(departure)
        minimum_departure = min(
            float(contract["geometry"]["minimum_immediate_departure_distance"]),
            float(curve["actual_length"]) * 0.14,
        )
        if departure < minimum_departure:
            issues.append(
                {
                    "code": "child_does_not_depart_immediately",
                    "curve_id": curve["curve_id"],
                    "value": _round(departure),
                }
            )
        first_clear_index = next(
            (
                index
                for index, distance in enumerate(parent_distances[1:], start=1)
                if distance >= parent_occupancy_clearance
            ),
            None,
        )
        if first_clear_index is None:
            issues.append(
                {
                    "code": "child_does_not_clear_parent_occupancy",
                    "curve_id": curve["curve_id"],
                    "required_clearance": _round(parent_occupancy_clearance),
                    "maximum_parent_clearance": _round(
                        max(parent_distances, default=0.0)
                    ),
                }
            )
        else:
            cumulative = [0.0]
            for index in range(1, len(child_points)):
                cumulative.append(
                    cumulative[-1]
                    + _distance(child_points[index - 1], child_points[index])
                )
            total_child_length = cumulative[-1]
            parent_clearance_onset_fractions.append(
                cumulative[first_clear_index] / max(total_child_length, 1e-12)
            )
            post_clearance = parent_distances[first_clear_index:]
            post_departure_parent_clearances.append(min(post_clearance))
            reentry_indices = [
                index
                for index in range(first_clear_index + 1, len(parent_distances))
                if (
                    parent_distances[index] < parent_occupancy_clearance
                    and parent_distances[index - 1]
                    >= parent_occupancy_clearance
                )
            ]
            if reentry_indices:
                parent_occupancy_reentry_count += len(reentry_indices)
                issues.append(
                    {
                        "code": "child_reenters_parent_occupancy",
                        "curve_id": curve["curve_id"],
                        "required_clearance": _round(parent_occupancy_clearance),
                        "reentry_count": len(reentry_indices),
                        "minimum_post_departure_clearance": _round(
                            min(post_clearance)
                        ),
                    }
                )
        parent_length = float(parent["actual_length"])
        ratio = float(curve["actual_length"]) / parent_length
        if curve["level"] == "L3":
            bounds = bounds_by_role["tertiary"]
        else:
            bounds = bounds_by_role.get(
                str(candidate["role"]),
                bounds_by_role["ordinary"],
            )
        if not float(bounds[0]) * 0.84 <= ratio <= float(bounds[1]) * 1.18:
            issues.append(
                {
                    "code": "hierarchy_length_ratio_out_of_range",
                    "curve_id": curve["curve_id"],
                    "value": _round(ratio),
                }
            )

    l2_mounts = sorted(
        float(curve["mount_fraction"])
        for curve in curves
        if curve["level"] == "L2"
    )
    minimum_mount_gap = min(
        (
            l2_mounts[index] - l2_mounts[index - 1]
            for index in range(1, len(l2_mounts))
        ),
        default=1.0,
    )
    if minimum_mount_gap < (
        float(contract["geometry"]["minimum_sibling_mount_separation"])
        - 1e-9
    ):
        issues.append(
            {
                "code": "sibling_mounts_too_close",
                "value": _round(minimum_mount_gap),
            }
        )

    l2_curves = [curve for curve in curves if curve["level"] == "L2"]
    sibling_curve_clearance = min(
        (
            polyline_pair_minimum_distance(
                np.asarray(
                    [
                        [float(point[0]), float(point[1])]
                        for point in first["centerline"]
                    ],
                    dtype=np.float64,
                ),
                np.asarray(
                    [
                        [float(point[0]), float(point[1])]
                        for point in second["centerline"]
                    ],
                    dtype=np.float64,
                ),
            )
            for index, first in enumerate(l2_curves)
            for second in l2_curves[index + 1 :]
        ),
        default=1.0,
    )
    required_sibling_clearance = 0.0
    if len(l2_curves) > 1:
        required_sibling_clearance = parent_occupancy_clearance
        if editor_l2_profile is not None:
            required_sibling_clearance = max(
                required_sibling_clearance,
                float(
                    editor_l2_profile[
                        "paired_child_curve_clearance_unit_ratio"
                    ]["q10"]
                ),
            )
        if sibling_curve_clearance < required_sibling_clearance:
            issues.append(
                {
                    "code": "sibling_curves_below_occupancy_clearance",
                    "value": _round(sibling_curve_clearance),
                    "required": _round(required_sibling_clearance),
                }
            )

    crossing_count = 0
    for index, curve in enumerate(curves):
        points = [_point(value) for value in curve["centerline"]]
        if len(points) >= 3:
            first_indexes: list[int] = []
            second_indexes: list[int] = []
            for first in range(1, len(points)):
                for second in range(first + 2, len(points)):
                    first_indexes.append(first)
                    second_indexes.append(second)
            if first_indexes:
                self_a0 = np.asarray(
                    [points[first - 1] for first in first_indexes],
                    dtype=np.float64,
                )
                self_a1 = np.asarray(
                    [points[first] for first in first_indexes],
                    dtype=np.float64,
                )
                self_b0 = np.asarray(
                    [points[second - 1] for second in second_indexes],
                    dtype=np.float64,
                )
                self_b1 = np.asarray(
                    [points[second] for second in second_indexes],
                    dtype=np.float64,
                )
                if bool(
                    np.any(
                        segments_intersect_batch(
                            self_a0[:, 0],
                            self_a0[:, 1],
                            self_a1[:, 0],
                            self_a1[:, 1],
                            self_b0[:, 0],
                            self_b0[:, 1],
                            self_b1[:, 0],
                            self_b1[:, 1],
                        )
                    )
                ):
                    crossing_count += 1
        for other in curves[index + 1 :]:
            allowed: Point | None = None
            if other["parent_curve_id"] == curve["curve_id"]:
                allowed = _point(other["cubic_segments"][0]["p0"])
            elif curve["parent_curve_id"] == other["curve_id"]:
                allowed = _point(curve["cubic_segments"][0]["p0"])
            curve_points = np.asarray(
                [
                    [float(point[0]), float(point[1])]
                    for point in curve["centerline"]
                ],
                dtype=np.float64,
            )
            other_points = np.asarray(
                [
                    [float(point[0]), float(point[1])]
                    for point in other["centerline"]
                ],
                dtype=np.float64,
            )
            if polyline_pair_intersects(
                curve_points,
                other_points,
                junction=allowed,
            ):
                crossing_count += 1
    if crossing_count:
        issues.append({"code": "unit_self_crossing", "count": crossing_count})

    backbone = [
        _point(row["point"], "backbone.point")
        for row in analysis["backbone"]["samples"]
    ]
    backbone_crossing_count = 0
    for curve in curves:
        if curve["level"] == "L1":
            continue
        points = [_point(value) for value in curve["centerline"]]
        if (
            min(
                polyline_pair_minimum_distance(
                    np.asarray(points, dtype=np.float64),
                    np.asarray(backbone, dtype=np.float64)
                    + np.asarray([shift, 0.0], dtype=np.float64),
                )
                for shift in (-1.0, 0.0, 1.0)
            )
            <= 0.001
        ):
            backbone_crossing_count += 1
    if backbone_crossing_count:
        issues.append(
            {
                "code": "non_root_backbone_crossing",
                "count": backbone_crossing_count,
            }
        )

    reserve_entry_count = 0
    target_flower_id = candidate["flower_relation"]["flower_id"]
    for curve in curves:
        if curve["level"] == "L1":
            continue
        for point in [_point(value) for value in curve["centerline"]][1:]:
            enters = False
            for flower in analysis["flowers"]:
                is_sw1_wrap_target = (
                    candidate["role"] == "flower_support"
                    and flower["flower_id"] == target_flower_id
                )
                if _ellipse_value(
                    point,
                    flower,
                    protection=not is_sw1_wrap_target,
                ) < 1.0:
                    enters = True
                    break
            if enters:
                reserve_entry_count += 1
                break
    if reserve_entry_count:
        issues.append(
            {
                "code": "descendant_enters_flower_reserve",
                "count": reserve_entry_count,
            }
        )

    support_contact_error = 0.0
    if candidate["role"] in {"flower_support", "terminal_flower_support"}:
        target_id = candidate["flower_relation"]["flower_id"]
        flower = next(
            (row for row in analysis["flowers"] if row["flower_id"] == target_id),
            None,
        )
        if flower is None:
            issues.append({"code": "support_flower_missing"})
        else:
            endpoint = _point(l1_curves[0]["cubic_segments"][-1]["p3"])
            center = _point(flower["center"])
            rx = float(flower["rx"])
            ry = float(flower["ry"])
            near_x = min(
                (endpoint[0] - 1.0, endpoint[0], endpoint[0] + 1.0),
                key=lambda value: abs(value - center[0]),
            )
            support_contact_error = abs(
                ((near_x - center[0]) / rx) ** 2
                + ((endpoint[1] - center[1]) / ry) ** 2
                - 1.0
            )
            if support_contact_error > 0.035:
                issues.append(
                    {
                        "code": "support_terminal_contact_not_preserved",
                        "value": _round(support_contact_error),
                    }
                )

    periodic_crossing_count = 0
    for curve in curves:
        for other in curves:
            shifted = dict(other)
            shifted["centerline"] = [
                [_round(float(point[0]) + 1.0), _round(float(point[1]))]
                for point in other["centerline"]
            ]
            shifted_points = np.asarray(
                [
                    [float(point[0]), float(point[1])]
                    for point in shifted["centerline"]
                ],
                dtype=np.float64,
            )
            if polyline_pair_intersects(
                np.asarray(
                    [
                        [float(point[0]), float(point[1])]
                        for point in curve["centerline"]
                    ],
                    dtype=np.float64,
                ),
                shifted_points,
            ):
                periodic_crossing_count += 1
    if periodic_crossing_count:
        issues.append(
            {
                "code": "periodic_self_crossing",
                "count": periodic_crossing_count,
            }
        )

    flower_support_clearance = float("inf")
    flower_support_conflict_count = 0
    if flower_mount_plan is not None:
        required_clearance = 2.0 * float(
            contract["geometry"]["occupancy_radius"]
        )
        for curve in curves:
            curve_points = [_point(value) for value in curve["centerline"]]
            for mount in flower_mount_plan.get("mounts", []):
                mount_points = [
                    _point(value) for value in mount["centerline"]
                ]
                curve_array = np.asarray(
                    curve_points,
                    dtype=np.float64,
                )
                mount_array = np.asarray(
                    mount_points,
                    dtype=np.float64,
                )
                minimum = min(
                    polyline_pair_minimum_distance(
                        curve_array,
                        mount_array
                        + np.asarray([offset, 0.0], dtype=np.float64),
                    )
                    for offset in (-1.0, 0.0, 1.0)
                )
                flower_support_clearance = min(
                    flower_support_clearance,
                    minimum,
                )
                if minimum < required_clearance:
                    flower_support_conflict_count += 1
                    break
        if flower_support_conflict_count:
            issues.append(
                {
                    "code": "unit_conflicts_with_frozen_flower_support",
                    "count": flower_support_conflict_count,
                    "required_clearance": _round(required_clearance),
                }
            )

    metrics = {
        "maximum_attachment_error": _round(max(root_errors, default=0.0)),
        "minimum_entry_opening_degrees": _round(min(openings, default=0.0)),
        "minimum_immediate_departure": _round(
            min(departure_distances, default=0.0)
        ),
        "parent_occupancy_clearance": _round(parent_occupancy_clearance),
        "maximum_parent_clearance_onset_fraction": _round(
            max(parent_clearance_onset_fractions, default=0.0)
        ),
        "minimum_post_departure_parent_clearance": _round(
            min(post_departure_parent_clearances, default=1.0)
        ),
        "parent_occupancy_reentry_count": parent_occupancy_reentry_count,
        "minimum_sibling_mount_separation": _round(minimum_mount_gap),
        "unit_self_crossing_count": crossing_count,
        "backbone_crossing_count": backbone_crossing_count,
        "flower_reserve_entry_count": reserve_entry_count,
        "support_contact_error": _round(support_contact_error),
        "periodic_self_crossing_count": periodic_crossing_count,
        "minimum_frozen_flower_support_clearance": _round(
            flower_support_clearance
            if math.isfinite(flower_support_clearance)
            else 1.0
        ),
        "frozen_flower_support_conflict_count": (
            flower_support_conflict_count
        ),
    }
    if editor_l2_profile is not None:
        metrics.update(
            {
                "minimum_sibling_curve_clearance": _round(
                    sibling_curve_clearance
                ),
                "required_sibling_curve_clearance": _round(
                    required_sibling_clearance
                ),
            }
        )
    return {
        "valid": not issues,
        "issue_count": len(issues),
        "issues": issues,
        "metrics": metrics,
    }


def _build_candidate(
    *,
    plan: Mapping[str, Any],
    lane: Mapping[str, Any],
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    grammar_id: str,
    stratum: str,
    include_l3: bool,
    turn_sign_variant: str,
    candidate_index: int,
    editor_l2_profile: Mapping[str, Any] | None,
    flower_mount_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    seed = int(
        plan["unit_seed"]
        if plan.get("unit_seed") is not None
        else plan["seed"]
    )
    lane_id = str(lane["slot_id"])
    quantiles = _candidate_quantiles(seed, lane_id, candidate_index)
    branch_unit_id = f"{plan['plan_id']}__{lane_id}"
    candidate_id = (
        f"{branch_unit_id}__{grammar_id}__{stratum}"
        f"__{turn_sign_variant}__sample_{candidate_index:04d}"
    )
    l1 = _l1_curve(lane, branch_unit_id)
    curves: list[dict[str, Any]] = [l1]
    grammar = contract["grammar"][grammar_id]
    l2_count = int(grammar["l2_count"])
    role = str(lane["role"])
    weak_roles = contract.get("schema") == CONTRACT_SCHEMA_V2
    generation_role = "primary_sweep" if weak_roles else role
    role_condition = _role_condition(generation_role, 2)
    preferred_mounts = _mounts(
        prior,
        role_condition,
        l2_count,
        quantiles,
        contract,
        editor_l2_profile,
    )
    l1_points = [_point(value) for value in l1["centerline"]]
    mounts = _contextual_mounts(
        l1_points,
        preferred_mounts,
        lane,
        analysis,
        contract,
        quantiles[7],
    )
    if l2_count == 2:
        low, high = [
            float(value)
            for value in contract["geometry"]["mount_fraction_range"]
        ]
        separation = max(
            float(contract["geometry"]["minimum_sibling_mount_separation"]),
            mounts[1] - mounts[0],
        )
        extra_separation = min(
            0.10,
            max(0.0, high - low - separation) * quantiles[6],
        )
        center = 0.5 * (mounts[0] + mounts[1])
        half_gap = 0.5 * (separation + extra_separation)
        lower_mount = max(low, min(high - 2.0 * half_gap, center - half_gap))
        mounts = [lower_mount, lower_mount + 2.0 * half_gap]
    signs = _child_signs(
        l1_points,
        mounts,
        analysis,
        lane,
        float(plan["global_latents"]["asymmetry"]),
        turn_sign_variant,
        editor_l2_profile,
    )
    target_flower = next(
        (
            flower
            for flower in analysis["flowers"]
            if flower["flower_id"] == lane["flower_id"]
        ),
        None,
    )
    density_scale = _local_density_scale(lane, plan["lanes"])
    for child_index, (mount, sign) in enumerate(zip(mounts, signs), start=1):
        child_quantiles = [
            quantiles[(child_index + offset) % len(quantiles)]
            for offset in range(5)
        ]
        child_quantiles[1] = _length_quantile_for_stratum(
            stratum,
            child_quantiles[1],
        )
        shape = _shape_from_stratum(stratum, child_index - 1)
        child = _compile_child_curve(
            curve_id=f"{branch_unit_id}.L2.{child_index}",
            branch_unit_id=branch_unit_id,
            parent_curve=l1,
            mount_fraction=mount,
            sign=sign,
            role=generation_role,
            semantic_role=(
                "lateral_subordinate"
                if weak_roles
                else "flower_wrap"
                if role == "flower_support"
                else "terminal_subordinate"
                if role == "terminal_flower_support"
                else "frontier_extension"
                if role == "frontier"
                else "lateral_subordinate"
            ),
            level=2,
            prior=prior,
            contract=contract,
            quantiles=child_quantiles,
            density_scale=density_scale,
            shape_signature=shape,
            target_flower=target_flower,
        )
        curves.append(child)

    if include_l3:
        l2_parent = curves[-1]
        tertiary_quantiles = [
            quantiles[(5 + offset) % len(quantiles)] for offset in range(5)
        ]
        tertiary_mount = _mounts(
            prior,
            "tertiary_lateral",
            1,
            tertiary_quantiles,
            contract,
            None,
        )[0]
        tertiary = _compile_child_curve(
            curve_id=f"{branch_unit_id}.L3.1",
            branch_unit_id=branch_unit_id,
            parent_curve=l2_parent,
            mount_fraction=tertiary_mount,
            sign=-int(l2_parent["turn_sign"]),
            role=role,
            semantic_role="tertiary_echo",
            level=3,
            prior=prior,
            contract=contract,
            quantiles=tertiary_quantiles,
            density_scale=density_scale,
            shape_signature="C",
            target_flower=None,
        )
        curves.append(tertiary)

    flower_relation = {
        "flower_id": lane["flower_id"],
        "policy": (
            "soft_spatial_anchor_without_mandatory_service"
            if weak_roles
            else "sw1_trough_support_with_single_wrap"
            if role == "flower_support"
            else "sw3_remote_below_flower_underside_support"
            if role == "terminal_flower_support"
            else "ordinary_descendants_exclude_all_flower_reserves"
        ),
        "l1_contact_point": lane["target"] if lane["flower_id"] else None,
    }
    candidate: dict[str, Any] = {
        "schema": CANDIDATE_SCHEMA_V2 if weak_roles else CANDIDATE_SCHEMA,
        "candidate_id": candidate_id,
        "branch_unit_id": branch_unit_id,
        "source_plan_id": plan["plan_id"],
        "source_plan_digest": plan["plan_digest"],
        "source_lane_id": lane_id,
        "source_lane_candidate_id": lane["candidate_id"],
        "prototype_id": plan["prototype_id"],
        "seed": seed,
        "role": role,
        "grammar_id": grammar_id,
        "parameter_stratum": stratum,
        "turn_sign_variant": turn_sign_variant,
        "hierarchy": {
            "l1_count": 1,
            "l2_count": l2_count,
            "l3_count": 1 if include_l3 else 0,
            "maximum_level": 3 if include_l3 else 2 if l2_count else 1,
        },
        "curves": curves,
        "parent_graph": [
            {
                "curve_id": curve["curve_id"],
                "parent_curve_id": curve["parent_curve_id"],
                "mount_fraction": curve["mount_fraction"],
            }
            for curve in curves
        ],
        "occupancy_tubes": _occupancy_tubes(
            curves,
            float(contract["geometry"]["occupancy_radius"]),
        ),
        "flower_relation": flower_relation,
        "visual_features": {
            "l1_signature": lane["curvature_signature"],
            "l2_sign_sequence": [
                curve["turn_sign"] for curve in curves if curve["level"] == "L2"
            ],
            "l2_turn_sign_candidate_coverage": (
                "editor_bidirectional_single_child"
                if l2_count == 1
                and editor_l2_profile
                and int(
                    editor_l2_profile.get(
                        "single_child_departure_turn_sign_histogram",
                        {},
                    ).get("positive", 0)
                )
                > 0
                and int(
                    editor_l2_profile.get(
                        "single_child_departure_turn_sign_histogram",
                        {},
                    ).get("negative", 0)
                )
                > 0
                else "context_preferred"
            ),
            "l2_shape_sequence": [
                curve["shape_signature"]
                for curve in curves
                if curve["level"] == "L2"
            ],
            "mount_sequence": [
                curve["mount_fraction"]
                for curve in curves
                if curve["level"] == "L2"
            ],
            "length_sequence": [
                curve["actual_length"] for curve in curves
            ],
            "hierarchy_density_class": (
                "l1_only"
                if l2_count == 0
                else "single_child"
                if l2_count == 1
                else "paired_child"
            ),
        },
        "random_provenance": {
            "method": contract["sampling"]["method"],
            "seed": seed,
            "candidate_index": candidate_index,
            "halton_quantiles": [_round(value) for value in quantiles],
            "validation_guided_retry_count": 0,
            "validation_guided_resample_count": 0,
            "automatic_repair_count": 0,
            "automatic_deletion_count": 0,
            "silent_fallback_count": 0,
        },
    }
    candidate["intrinsic_diagnostics"] = _diagnose_candidate(
        candidate,
        analysis,
        contract,
        editor_l2_profile,
        flower_mount_plan,
    )
    digest_source = dict(candidate)
    candidate["candidate_digest"] = canonical_digest(digest_source)
    return candidate


def generate_unit_candidate_inventory(
    plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
    prior: Mapping[str, Any],
    contract: Mapping[str, Any],
    editor_l2_prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract_schema = contract.get("schema")
    expected_plan_schemas = (
        {
            "dynamic_branch_global_l1_flow_plan_v2",
            "dynamic_branch_global_l1_flow_plan_v3",
        }
        if contract_schema == CONTRACT_SCHEMA_V2
        else {"dynamic_branch_global_l1_flow_plan_v1"}
    )
    if plan.get("schema") not in expected_plan_schemas:
        raise UnitGrammarError("stage-3B plan schema mismatch")
    if analysis.get("schema") != "dynamic_branch_prototype_analysis_v1":
        raise UnitGrammarError("stage-2 analysis schema mismatch")
    if prior.get("schema") != "dynamic_branch_fixed_visual_prior_v1":
        raise UnitGrammarError("stage-3A prior schema mismatch")
    if contract_schema not in {CONTRACT_SCHEMA, CONTRACT_SCHEMA_V2}:
        raise UnitGrammarError("stage-4 contract schema mismatch")
    if analysis.get("prototype_id") != plan.get("prototype_id"):
        raise UnitGrammarError("analysis/plan prototype mismatch")
    if plan.get("review", {}).get("status") != "l1_flow_pending_visual_review":
        raise UnitGrammarError("approved source plan content was unexpectedly mutated")
    prototype_strategy = plan.get("prototype_strategy")
    if contract_schema == CONTRACT_SCHEMA_V2 and not isinstance(
        prototype_strategy, Mapping
    ):
        raise UnitGrammarError("stage-3B plan lacks frozen prototype strategy")
    if isinstance(prototype_strategy, Mapping):
        validate_strategy_projection(
            prototype_strategy,
            prototype_id=str(plan["prototype_id"]),
            family_id=str(plan["family_id"]),
            flower_count=len(analysis["flowers"]),
        )
        branchunit_policy = prototype_strategy["branchunit_profile"]
        if branchunit_policy["candidate_coverage_policy"] != (
            "contract_weak_role_grammar_strata"
        ):
            raise UnitGrammarError("unsupported BranchUnit candidate coverage strategy")
    flower_mount_plan = plan.get("flower_mount_plan")
    if not isinstance(flower_mount_plan, Mapping):
        raise UnitGrammarError("stage-3B plan lacks frozen flower mounting")
    if flower_mount_plan.get("mount_policy", {}).get(
        "mounts_frozen_before_ordinary_l1"
    ) is not True:
        raise UnitGrammarError("flower mounting is not an upstream constraint")
    editor_l2_profile: Mapping[str, Any] | None = None
    if contract_schema == CONTRACT_SCHEMA_V2:
        if editor_l2_prior is None:
            raise UnitGrammarError(
                "stage-4 V2 requires the editor L2 placement prior"
            )
        editor_l2_profile = _editor_l2_profile(
            editor_l2_prior,
            str(plan["prototype_id"]),
            str(
                prototype_strategy["branchunit_profile"][
                    "editor_l2_profile_key"
                ]
            ),
        )

    candidates: list[dict[str, Any]] = []
    lane_rows: list[dict[str, Any]] = []
    candidate_index = 0
    for lane in plan["lanes"]:
        lane_candidates: list[dict[str, Any]] = []
        for (
            grammar_id,
            stratum,
            include_l3,
            turn_sign_variant,
        ) in _candidate_strata(lane, contract, editor_l2_profile):
            candidate = _build_candidate(
                plan=plan,
                lane=lane,
                analysis=analysis,
                prior=prior,
                contract=contract,
                grammar_id=grammar_id,
                stratum=stratum,
                include_l3=include_l3,
                turn_sign_variant=turn_sign_variant,
                candidate_index=candidate_index,
                editor_l2_profile=editor_l2_profile,
                flower_mount_plan=flower_mount_plan,
            )
            candidate_index += 1
            candidates.append(candidate)
            lane_candidates.append(candidate)
        feasible = [
            candidate
            for candidate in lane_candidates
            if candidate["intrinsic_diagnostics"]["valid"]
        ]
        lane_rows.append(
            {
                "source_lane_id": lane["slot_id"],
                "role": lane["role"],
                "candidate_count": len(lane_candidates),
                "feasible_candidate_count": len(feasible),
                "candidate_ids": [
                    candidate["candidate_id"] for candidate in lane_candidates
                ],
                "feasible_candidate_ids": [
                    candidate["candidate_id"] for candidate in feasible
                ],
                "coverage_complete": True,
            }
        )

    empty_lanes = [
        row["source_lane_id"]
        for row in lane_rows
        if row["feasible_candidate_count"] == 0
    ]
    weak_roles = contract_schema == CONTRACT_SCHEMA_V2
    inventory: dict[str, Any] = {
        "schema": SCHEMA_V2 if weak_roles else SCHEMA,
        "contract_id": contract["contract_id"],
        "inventory_id": (
            f"{plan['plan_id']}__unit_candidates_v2"
            if weak_roles
            else f"{plan['plan_id']}__unit_candidates_v1"
        ),
        "prototype_id": plan["prototype_id"],
        "family_id": plan["family_id"],
        "prototype_strategy": (
            dict(prototype_strategy)
            if isinstance(prototype_strategy, Mapping)
            else None
        ),
        "seed": (
            plan["unit_seed"]
            if plan.get("unit_seed") is not None
            else plan["seed"]
        ),
        "branch_seed": plan["seed"],
        "unit_seed": (
            plan["unit_seed"]
            if plan.get("unit_seed") is not None
            else plan["seed"]
        ),
        "source_plan_id": plan["plan_id"],
        "source_plan_digest": plan["plan_digest"],
        "ordinary_density_level": plan.get("count_derivation", {}).get(
            "ordinary_density_level"
        ),
        "density_control_profile": plan.get("density_control_profile"),
        "source_l1_geometry_policy": "approved_stage3b_l1_is_immutable",
        "role_policy": (
            "weak_compatibility_metadata_only"
            if weak_roles
            else "role_conditioned_v1"
        ),
        "global_latents": plan["global_latents"],
        "flower_mount_plan_id": str(flower_mount_plan["plan_id"]),
        "lane_count": len(plan["lanes"]),
        "candidate_count": len(candidates),
        "feasible_candidate_count": sum(
            candidate["intrinsic_diagnostics"]["valid"]
            for candidate in candidates
        ),
        "invalid_candidate_count": sum(
            not candidate["intrinsic_diagnostics"]["valid"]
            for candidate in candidates
        ),
        "lanes": lane_rows,
        "candidates": candidates,
        "coverage": {
            "declared_grammar_role_strata_complete": True,
            "lanes_without_feasible_candidate": empty_lanes,
            "global_selection_performed": False,
            "experimental_variants_created": False,
        },
        "generation_policy": {
            "generated_once": True,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
            "silent_fallback_used": False,
            "best_of_n_selection_used": False,
            "frozen_flower_support_geometry_consumed": True,
        },
        "review": {
            "status": contract["output"]["review_state"],
            "numeric_checks_cannot_auto_approve_visual_gate": True,
            "criteria": [
                "visible_l1_curvature",
                "visible_c_and_s_flow",
                "sparse_l1_only_single_and_paired_hierarchy",
                "coordinated_sibling_rhythm",
                "editor_demonstrated_l2_mount_spacing",
                "immediate_child_departure",
                "flower_relation_is_soft_not_mandatory",
            ],
        },
    }
    if weak_roles and editor_l2_prior is not None:
        inventory["editor_l2_placement_prior"] = {
            "consumed": True,
            "prior_id": str(editor_l2_prior["prior_id"]),
            "profile_id": str(plan["prototype_id"]),
            "mount_source": "saved_editor_active_l2_parent_grouping",
        }
    digest_source = dict(inventory)
    inventory["inventory_digest"] = canonical_digest(digest_source)
    validate_unit_candidate_inventory(inventory, contract)
    if empty_lanes:
        raise UnitGrammarError(
            "stage-4 candidate coverage is infeasible for lanes: "
            + ", ".join(str(value) for value in empty_lanes)
        )
    return inventory


def validate_unit_candidate_inventory(
    inventory: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> None:
    weak_roles = contract.get("schema") == CONTRACT_SCHEMA_V2
    expected_schema = SCHEMA_V2 if weak_roles else SCHEMA
    expected_candidate_schema = (
        CANDIDATE_SCHEMA_V2 if weak_roles else CANDIDATE_SCHEMA
    )
    if inventory.get("schema") != expected_schema:
        raise UnitGrammarError("candidate inventory schema mismatch")
    if inventory.get("contract_id") != contract.get("contract_id"):
        raise UnitGrammarError("candidate inventory contract mismatch")
    lanes = inventory.get("lanes")
    candidates = inventory.get("candidates")
    if not isinstance(lanes, list) or not isinstance(candidates, list):
        raise UnitGrammarError("candidate inventory arrays are missing")
    if inventory.get("candidate_count") != len(candidates):
        raise UnitGrammarError("candidate inventory count mismatch")
    if any(
        candidate.get("schema") != expected_candidate_schema
        for candidate in candidates
    ):
        raise UnitGrammarError("candidate schema mismatch")
    if any(
        candidate.get("source_plan_digest") != inventory.get("source_plan_digest")
        for candidate in candidates
    ):
        raise UnitGrammarError("candidate source plan binding mismatch")
    policy = inventory.get("generation_policy", {})
    forbidden = (
        "validation_guided_retry_used",
        "validation_guided_resample_used",
        "automatic_repair_used",
        "automatic_deletion_used",
        "silent_fallback_used",
        "best_of_n_selection_used",
    )
    if any(policy.get(key) is not False for key in forbidden):
        raise UnitGrammarError("forbidden stage-4 generation behavior detected")
    if inventory.get("review", {}).get("status") != contract["output"]["review_state"]:
        raise UnitGrammarError("candidate review state mismatch")
    if inventory.get("coverage", {}).get("global_selection_performed") is not False:
        raise UnitGrammarError("stage-5 global selection leaked into stage 4")
    if weak_roles:
        l2_policy = inventory.get("editor_l2_placement_prior", {})
        if l2_policy.get("consumed") is not True:
            raise UnitGrammarError(
                "stage-4 V2 did not consume editor L2 placement evidence"
            )
        if l2_policy.get("mount_source") != (
            "saved_editor_active_l2_parent_grouping"
        ):
            raise UnitGrammarError("stage-4 V2 L2 mount source mismatch")
    role_counts = Counter(candidate["role"] for candidate in candidates)
    if not role_counts:
        raise UnitGrammarError("candidate inventory is empty")
