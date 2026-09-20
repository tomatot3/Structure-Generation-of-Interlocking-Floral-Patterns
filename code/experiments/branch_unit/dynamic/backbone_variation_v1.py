#!/usr/bin/env python3
"""Prototype-domain joint backbone variation for stage 5B.

The active V2 path converts a seeded four-dimensional shape intent into one
coupled low-dimensional deformation, projects infeasible targets toward the
baseline, freezes flower geometry, and immediately regenerates analysis.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from bisect import bisect_right
from pathlib import Path
from typing import Any, Mapping, Sequence

from prototype_analysis import analyze_prototype
from prototype_strategy_v1 import validate_strategy_projection
from strict_p0_v2 import BackboneSample, FlowerReserve, StrictP0V2


Point = tuple[float, float]
UINT32_MAX = 2**32 - 1
VISUAL_SAFETY_MARGIN = 0.035
MAXIMUM_DISPLACEMENT = 0.025
CONTRACT_SCHEMA_V2 = "dynamic_backbone_variation_contract_v2"
CONTRACT_PATH = Path(__file__).with_name("BACKBONE_VARIATION_CONTRACT_V2.json")
CONTRACT_SCHEMA_V3 = "dynamic_backbone_variation_contract_v3"
CONTRACT_PATH_V3 = Path(__file__).with_name("BACKBONE_VARIATION_CONTRACT_V3.json")
STAGE3_PLAN_CONTRACT_PATH = Path(__file__).with_name("STAGE3_PLAN_CONTRACT.json")


class BackboneVariationError(RuntimeError):
    """The requested variation violates the periodic geometry contract."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def validate_seed(seed: int, label: str = "seed") -> int:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise BackboneVariationError("invalid_seed", f"{label} must be an integer")
    if not 0 <= seed <= UINT32_MAX:
        raise BackboneVariationError(
            "invalid_seed",
            f"{label} must lie in [0, {UINT32_MAX}]",
        )
    return seed


def split_seed(seed: int) -> tuple[int, int]:
    """Split one production seed into independent backbone and branch domains."""

    master = validate_seed(seed)
    backbone = hashlib.sha256(f"{master}:backbone_seed:v1".encode("utf-8")).digest()
    branch = hashlib.sha256(f"{master}:branch_seed:v1".encode("utf-8")).digest()
    return int.from_bytes(backbone[:4], "big"), int.from_bytes(branch[:4], "big")


def split_generation_seeds(seed: int) -> dict[str, int]:
    """Split one production seed into the four formal generation domains.

    The original backbone/branch hashes stay byte-for-byte compatible with
    ``split_seed``.  Flower placement and BranchUnit detail receive independent
    namespaces so 5C can be varied without changing the other three domains.
    """

    backbone_seed, branch_seed = split_seed(seed)
    master = validate_seed(seed)
    flower = hashlib.sha256(f"{master}:flower_seed:v1".encode("utf-8")).digest()
    unit = hashlib.sha256(f"{master}:unit_seed:v1".encode("utf-8")).digest()
    return {
        "backbone_seed": backbone_seed,
        "flower_seed": int.from_bytes(flower[:4], "big"),
        "branch_seed": branch_seed,
        "unit_seed": int.from_bytes(unit[:4], "big"),
    }


def production_rho(backbone_seed: int) -> float:
    seed = validate_seed(backbone_seed, "backbone_seed")
    payload = hashlib.sha256(f"{seed}:backbone_rho:v1".encode("utf-8")).digest()
    unit = int.from_bytes(payload[:8], "big") / float(2**64)
    return 0.35 + 0.65 * unit


def production_prototype_variant_id(
    backbone_seed: int,
    prototype_id: str,
) -> str:
    """Choose one accepted combined variant direction for the production chain."""

    seed = validate_seed(backbone_seed, "backbone_seed")
    from global_backbone_wave_v4 import load_prototype_variant_library

    library = load_prototype_variant_library()
    rows = library.get("variants_per_prototype", {}).get(prototype_id)
    if not isinstance(rows, list) or not rows:
        raise BackboneVariationError(
            "prototype_variant_missing",
            f"no production prototype variants for {prototype_id}",
        )
    variant_ids = [str(row["variant_id"]) for row in rows]
    payload = hashlib.sha256(
        f"{seed}:{prototype_id}:prototype_variant:v1".encode("utf-8")
    ).digest()
    return variant_ids[int.from_bytes(payload[:8], "big") % len(variant_ids)]


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


def _unit(point: Point, label: str) -> Point:
    length = _length(point)
    if length <= 1e-12:
        raise BackboneVariationError(
            "degenerate_periodic_frame",
            f"{label} has zero length",
        )
    return point[0] / length, point[1] / length


def _lerp(first: Point, second: Point, fraction: float) -> Point:
    return (
        first[0] + (second[0] - first[0]) * fraction,
        first[1] + (second[1] - first[1]) * fraction,
    )


def _canonical_point(point: Point) -> Point:
    x_value = round(float(point[0]), 9)
    y_value = round(float(point[1]), 9)
    return (
        0.0 if x_value == -0.0 else x_value,
        0.0 if y_value == -0.0 else y_value,
    )


def _load_variation_contract() -> dict[str, Any]:
    try:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackboneVariationError(
            "backbone_variation_contract_invalid",
            f"cannot read {CONTRACT_PATH}",
        ) from exc
    if contract.get("schema") != CONTRACT_SCHEMA_V2:
        raise BackboneVariationError(
            "backbone_variation_contract_invalid",
            "stage-5B backbone variation contract schema mismatch",
        )
    return contract


def _load_variation_contract_v3() -> dict[str, Any]:
    try:
        contract = json.loads(CONTRACT_PATH_V3.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackboneVariationError(
            "backbone_variation_contract_invalid",
            f"cannot read {CONTRACT_PATH_V3}",
        ) from exc
    if contract.get("schema") != CONTRACT_SCHEMA_V3:
        raise BackboneVariationError(
            "backbone_variation_contract_invalid",
            "stage-5B retry backbone variation contract schema mismatch",
        )
    return contract


def _circular_distance(first: float, second: float) -> float:
    delta = abs((first - second) % 1.0)
    return min(delta, 1.0 - delta)


def _angle_between(first: Point, second: Point) -> float:
    return math.acos(max(-1.0, min(1.0, _dot(first, second))))


def backbone_shape_descriptors(points: Sequence[Point]) -> dict[str, float]:
    """Independently measure the four shape dimensions from periodic geometry."""

    if len(points) < 5:
        raise BackboneVariationError(
            "insufficient_backbone_samples",
            "shape descriptors require at least four periodic samples",
        )
    tangents = _periodic_tangents(points)
    amplitude = max(point[1] for point in points) - min(point[1] for point in points)
    extended = [*points, (points[0][0] + 1.0, points[0][1])]
    arc_length = sum(
        _length(_sub(second, first))
        for first, second in zip(extended, extended[1:])
    )
    turns = [
        _angle_between(tangents[index - 1], tangents[index])
        for index in range(len(tangents))
    ]
    total_turn = sum(turns)
    if total_turn <= 1e-12:
        concentration = 0.0
    else:
        mean = total_turn / len(turns)
        concentration = math.sqrt(
            sum((value - mean) ** 2 for value in turns) / len(turns)
        ) / mean
    midline = sum(point[1] for point in points) / len(points)
    anchor = max(
        range(len(points)),
        key=lambda index: abs(points[index][1] - midline),
    )
    half = len(points) // 2
    forward_turn = sum(turns[(anchor + offset) % len(points)] for offset in range(half))
    backward_turn = sum(
        turns[(anchor - offset - 1) % len(points)] for offset in range(half)
    )
    asymmetry = (forward_turn - backward_turn) / max(
        forward_turn + backward_turn,
        1e-12,
    )
    return {
        "amplitude": amplitude,
        "arc_length": arc_length,
        "curvature_concentration": concentration,
        "asymmetry": asymmetry,
    }


def _seed_domain_unit(seed: int, namespace: str, domain: str) -> float:
    payload = hashlib.sha256(
        f"{namespace}:{seed}:{domain}:backbone_v2".encode("utf-8")
    ).digest()
    return int.from_bytes(payload[:8], "big") / float(2**64)


def _target_descriptor_deltas(
    seed: int,
    namespace: str,
    rho: float,
    baseline: Mapping[str, float],
    contract: Mapping[str, Any],
    overrides: Mapping[str, float] | None,
) -> tuple[dict[str, float], dict[str, float]]:
    dimensions = contract["shape_dimensions"]
    random_units: dict[str, float] = {}
    deltas: dict[str, float] = {}
    domains = {
        "amplitude": "amplitude_domain",
        "arc_length": "arc_length_domain",
        "curvature_concentration": "curvature_domain",
        "asymmetry": "asymmetry_domain",
    }
    for name, domain in domains.items():
        unit = _seed_domain_unit(seed, namespace, domain)
        random_units[name] = unit
        normalized = 2.0 * unit - 1.0
        if overrides is not None and name in overrides:
            normalized = float(overrides[name])
        if not math.isfinite(normalized) or not -1.0 <= normalized <= 1.0:
            raise BackboneVariationError(
                "invalid_backbone_shape_target",
                f"{name} target must lie in [-1, 1]",
            )
        if name == "asymmetry":
            maximum = float(dimensions[name]["maximum_absolute_delta"])
        else:
            maximum = (
                float(baseline[name])
                * float(dimensions[name]["maximum_relative_delta"])
            )
        deltas[name] = normalized * rho * maximum
    return deltas, random_units


def _descriptor_vector(descriptors: Mapping[str, float]) -> list[float]:
    return [
        float(descriptors[name])
        for name in (
            "amplitude",
            "arc_length",
            "curvature_concentration",
            "asymmetry",
        )
    ]


def _solve_linear_system(matrix: Sequence[Sequence[float]], rhs: Sequence[float]) -> list[float]:
    size = len(rhs)
    augmented = [list(matrix[row]) + [float(rhs[row])] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-12:
            raise BackboneVariationError(
                "backbone_shape_basis_degenerate",
                "joint shape basis is numerically singular",
            )
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(size)]


def _least_squares_coefficients(
    response: Sequence[Sequence[float]],
    target: Sequence[float],
    ridge: float,
) -> list[float]:
    size = len(target)
    normal = [
        [
            sum(response[row][i] * response[row][j] for row in range(size))
            + (ridge if i == j else 0.0)
            for j in range(size)
        ]
        for i in range(size)
    ]
    rhs = [
        sum(response[row][i] * target[row] for row in range(size))
        for i in range(size)
    ]
    return _solve_linear_system(normal, rhs)


def _unique_samples(strict_p0: StrictP0V2) -> tuple[BackboneSample, ...]:
    samples = strict_p0.backbone_samples
    if len(samples) < 5:
        raise BackboneVariationError(
            "insufficient_backbone_samples",
            "at least four unique periodic samples are required",
        )
    first = samples[0].point
    last = samples[-1].point
    if (
        abs(last[0] - first[0] - 1.0) > 1e-7
        or abs(last[1] - first[1]) > 1e-7
    ):
        raise BackboneVariationError(
            "backbone_seam_position_discontinuous",
            "the final sample must equal the first sample plus (1, 0)",
        )
    return samples[:-1]


def _periodic_tangents(points: Sequence[Point]) -> list[Point]:
    tangents: list[Point] = []
    for index in range(len(points)):
        previous = points[index - 1]
        following = points[(index + 1) % len(points)]
        if index == 0:
            previous = previous[0] - 1.0, previous[1]
        if index == len(points) - 1:
            following = following[0] + 1.0, following[1]
        tangents.append(
            _unit(
                _sub(following, previous),
                f"periodic tangent {index}",
            )
        )
    return tangents


def _normals(tangents: Sequence[Point]) -> list[Point]:
    return [(-tangent[1], tangent[0]) for tangent in tangents]


def _available_margin(strict_p0: StrictP0V2) -> float:
    bounds = strict_p0.frame.local_canvas_bounds
    lower = float(bounds[1])
    upper = float(bounds[3])
    margins = [
        min(sample.point[1] - lower, upper - sample.point[1])
        for sample in _unique_samples(strict_p0)
    ]
    margins.extend(
        min(
            flower.center[1] - flower.ry - lower,
            upper - flower.center[1] - flower.ry,
        )
        for flower in strict_p0.flowers
    )
    for zone in strict_p0.structure_protection_zones:
        if zone.geometry_type == "ellipse" and zone.center is not None:
            margins.append(
                min(
                    zone.center[1] - float(zone.ry) - lower,
                    upper - zone.center[1] - float(zone.ry),
                )
            )
        else:
            raise BackboneVariationError(
                "protection_zone_anchor_required",
                "polygon protection zones require an explicit variation anchor",
            )
    return min(margins) - VISUAL_SAFETY_MARGIN


def displacement_budget(strict_p0: StrictP0V2) -> tuple[float, float]:
    available = _available_margin(strict_p0)
    maximum = max(0.0, min(MAXIMUM_DISPLACEMENT, 0.45 * available))
    return available, maximum


def _mode_parameters(backbone_seed: int) -> dict[str, float]:
    seed = validate_seed(backbone_seed, "backbone_seed")
    payload = hashlib.sha256(f"{seed}:backbone_modes:v1".encode("utf-8")).digest()
    generator = random.Random(int.from_bytes(payload[:8], "big"))
    amplitude_weight = generator.uniform(-1.0, 1.0)
    bend_weight = generator.uniform(-1.0, 1.0)
    if abs(bend_weight) < 0.18:
        bend_weight = math.copysign(0.18, bend_weight or 1.0)
    asymmetry_weight = generator.uniform(-0.72, 0.72)
    if abs(asymmetry_weight) > abs(bend_weight):
        asymmetry_weight = math.copysign(abs(bend_weight), asymmetry_weight)
    energy = math.sqrt(
        amplitude_weight * amplitude_weight
        + bend_weight * bend_weight
        + asymmetry_weight * asymmetry_weight
    )
    if energy <= 1e-12:
        amplitude_weight, bend_weight, asymmetry_weight, energy = 0.0, 1.0, 0.0, 1.0
    return {
        "wa": amplitude_weight / energy,
        "wb": bend_weight / energy,
        "wc": asymmetry_weight / energy,
        "phi": generator.uniform(0.0, 2.0 * math.pi),
        "delta": generator.uniform(-math.pi, math.pi),
    }


def _normalize_signal(values: Sequence[float]) -> list[float]:
    energy = math.sqrt(sum(value * value for value in values) / len(values))
    if energy <= 1e-12:
        return [0.0 for _ in values]
    return [value / energy for value in values]


def _raw_displacements(
    samples: Sequence[BackboneSample],
    normals: Sequence[Point],
    parameters: Mapping[str, float],
) -> list[Point]:
    midline = sum(sample.point[1] for sample in samples) / len(samples)
    amplitude = _normalize_signal(
        [sample.point[1] - midline for sample in samples]
    )
    bend = _normalize_signal(
        [
            math.sin(2.0 * math.pi * sample.s + float(parameters["phi"]))
            for sample in samples
        ]
    )
    asymmetry = _normalize_signal(
        [
            0.35
            * math.sin(
                4.0 * math.pi * sample.s
                + 2.0 * float(parameters["phi"])
                + float(parameters["delta"])
            )
            for sample in samples
        ]
    )
    raw: list[Point] = []
    for index, normal in enumerate(normals):
        scalar = (
            float(parameters["wa"]) * amplitude[index]
            + float(parameters["wb"]) * bend[index]
            + float(parameters["wc"]) * asymmetry[index]
        )
        raw.append(_mul(normal, scalar))
    return raw


def _smooth_periodic(values: Sequence[float], radius: int = 2) -> list[float]:
    size = len(values)
    weights = [radius + 1 - abs(offset) for offset in range(-radius, radius + 1)]
    total = float(sum(weights))
    return [
        sum(
            values[(index + offset) % size] * weight
            for offset, weight in zip(range(-radius, radius + 1), weights)
        )
        / total
        for index in range(size)
    ]


def _joint_shape_bases(
    points: Sequence[Point],
    tangents: Sequence[Point],
) -> list[list[Point]]:
    """Build four smooth geometry-derived bases without prototype coordinates."""

    count = len(points)
    normals = _normals(tangents)
    midline = sum(point[1] for point in points) / count
    amplitude_signal = _normalize_signal([point[1] - midline for point in points])
    signed_turn = [
        math.atan2(
            tangents[index - 1][0] * tangents[index][1]
            - tangents[index - 1][1] * tangents[index][0],
            _dot(tangents[index - 1], tangents[index]),
        )
        for index in range(count)
    ]
    step_turn = [abs(value) for value in signed_turn]
    mean_turn = sum(step_turn) / count
    curvature_signal = _normalize_signal(
        _smooth_periodic([value - mean_turn for value in step_turn], radius=3)
    )
    length_signal = _normalize_signal(_smooth_periodic(signed_turn, radius=3))
    anchor = max(
        range(count),
        key=lambda index: abs(points[index][1] - midline),
    )
    asymmetry_signal = _normalize_signal(
        [
            amplitude_signal[index]
            * math.sin(2.0 * math.pi * (index - anchor) / count)
            for index in range(count)
        ]
    )
    amplitude_basis = [
        _mul(normal, amplitude_signal[index])
        for index, normal in enumerate(normals)
    ]
    length_basis = [
        _mul(normal, length_signal[index])
        for index, normal in enumerate(normals)
    ]
    curvature_basis = [
        _mul(normal, curvature_signal[index])
        for index, normal in enumerate(normals)
    ]
    asymmetry_basis = [
        _mul(normal, asymmetry_signal[index])
        for index, normal in enumerate(normals)
    ]
    return [amplitude_basis, length_basis, curvature_basis, asymmetry_basis]


def _apply_joint_bases(
    points: Sequence[Point],
    bases: Sequence[Sequence[Point]],
    coefficients: Sequence[float],
    budget: float,
) -> list[Point]:
    displacement = [
        (
            sum(coefficients[basis_index] * bases[basis_index][index][0] for basis_index in range(len(bases))),
            sum(coefficients[basis_index] * bases[basis_index][index][1] for basis_index in range(len(bases))),
        )
        for index in range(len(points))
    ]
    maximum = max((_length(value) for value in displacement), default=0.0)
    scale = 0.0 if maximum <= 1e-12 else min(1.0, budget / maximum)
    return [
        _canonical_point(_add(point, _mul(displacement[index], scale)))
        for index, point in enumerate(points)
    ]


def _basis_response(
    points: Sequence[Point],
    bases: Sequence[Sequence[Point]],
    step: float,
) -> list[list[float]]:
    baseline = _descriptor_vector(backbone_shape_descriptors(points))
    columns: list[list[float]] = []
    for index in range(len(bases)):
        coefficients = [0.0] * len(bases)
        coefficients[index] = step
        varied = _apply_joint_bases(points, bases, coefficients, float("inf"))
        varied = [
            _canonical_point(point)
            for point in _resample_periodic(varied, len(points))
        ]
        descriptor = _descriptor_vector(backbone_shape_descriptors(varied))
        columns.append(
            [(descriptor[row] - baseline[row]) / step for row in range(len(baseline))]
        )
    return [
        [columns[column][row] for column in range(len(columns))]
        for row in range(len(baseline))
    ]


def _materialize_joint_points(
    base_points: Sequence[Point],
    bases: Sequence[Sequence[Point]],
    coefficients: Sequence[float],
    budget: float,
) -> list[Point]:
    if max((abs(value) for value in coefficients), default=0.0) <= 1e-12:
        return list(base_points)
    displaced = _apply_joint_bases(
        base_points,
        bases,
        coefficients,
        budget,
    )
    return [
        _canonical_point(point)
        for point in _resample_periodic(displaced, len(base_points))
    ]


def _iterative_joint_coefficients(
    base_points: Sequence[Point],
    bases: Sequence[Sequence[Point]],
    target_descriptors: Sequence[float],
    row_scales: Sequence[float],
    budget: float,
    solver: Mapping[str, Any],
) -> tuple[list[float], list[dict[str, Any]]]:
    coefficients = [0.0] * len(bases)
    step = max(0.025, float(solver["finite_difference_step"]))
    maximum_norm = float(solver["maximum_coefficient_norm"])
    decay = float(solver["joint_step_decay"])
    trace: list[dict[str, Any]] = []

    def objective(values: Sequence[float]) -> float:
        points = _materialize_joint_points(
            base_points,
            bases,
            values,
            budget,
        )
        current = _descriptor_vector(backbone_shape_descriptors(points))
        return math.sqrt(
            sum(
                (
                    (target_descriptors[index] - current[index])
                    / row_scales[index]
                )
                ** 2
                for index in range(len(current))
            )
        )

    best_error = objective(coefficients)
    for iteration in range(int(solver["maximum_joint_iterations"])):
        selected = list(coefficients)
        selected_error = best_error
        selected_move = "none"
        for basis_index in range(len(bases)):
            for direction in (-1.0, 1.0):
                candidate = list(coefficients)
                candidate[basis_index] += direction * step
                norm = math.sqrt(sum(value * value for value in candidate))
                if norm > maximum_norm:
                    candidate = [value * maximum_norm / norm for value in candidate]
                candidate_error = objective(candidate)
                if candidate_error < selected_error - 1e-10:
                    selected = candidate
                    selected_error = candidate_error
                    selected_move = f"basis_{basis_index}:{int(direction):+d}"
        coefficients = selected
        best_error = selected_error
        trace.append(
            {
                "iteration": iteration,
                "normalized_error": round(best_error, 9),
                "coefficients": [round(value, 9) for value in coefficients],
                "step": round(step, 9),
                "selected_move": selected_move,
            }
        )
        step *= decay
    return coefficients, trace


def _extrema_sequence(analysis: Mapping[str, Any]) -> list[str]:
    return [str(row["kind"]) for row in analysis["backbone"]["extrema"]]


def _family_guard_issues(
    variant: StrictP0V2,
    baseline_analysis: Mapping[str, Any],
    variant_analysis: Mapping[str, Any],
    prototype_strategy: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> list[str]:
    issues: list[str] = []
    constraints = contract["hard_constraints"]
    if _extrema_sequence(variant_analysis) != _extrema_sequence(baseline_analysis):
        issues.append("peak_trough_sequence_changed")
    guard = str(prototype_strategy["backbone_domain"]["family_guard"])
    if guard == "sw1_fixed_flower_valley_relation":
        from flower_mounting_v1 import FlowerMountingError, _sw1_root_rows

        try:
            rows = _sw1_root_rows(variant_analysis)
        except FlowerMountingError:
            rows = []
        if len(rows) != len(variant_analysis["flowers"]):
            issues.append("sw1_flower_lost_valley_relation")
    elif guard == "sw2_fixed_flower_axis_integration":
        from flower_mounting_v1 import _axis_flower_integration

        if any(
            not row["axis_penetrates_flower"]
            for row in _axis_flower_integration(variant_analysis)
        ):
            issues.append("sw2_axis_no_longer_penetrates_flower")
    elif guard == "sw3_fixed_flower_remote_tangent_corridor":
        if len(variant_analysis["backbone"]["long_slopes"]) < int(
            constraints["sw3_minimum_long_slope_count"]
        ):
            issues.append("sw3_remote_tangent_corridor_missing")
        minimum_arc = float(constraints["sw3_remote_root_minimum_arc_distance"])
        maximum_arc = float(constraints["sw3_remote_root_maximum_arc_distance"])
        for flower in variant_analysis["flowers"]:
            nearest = float(flower["nearest_backbone_s"])
            center = flower["center"]
            if not any(
                minimum_arc <= _circular_distance(float(sample["s"]), nearest) <= maximum_arc
                and float(sample["point"][1]) > float(center[1])
                for sample in variant_analysis["backbone"]["samples"]
            ):
                issues.append("sw3_remote_tangent_root_unavailable")
                break
        if not issues:
            from flower_mounting_v1 import FlowerMountingError, _build_sw3_mounts

            try:
                stage3_contract = json.loads(
                    STAGE3_PLAN_CONTRACT_PATH.read_text(encoding="utf-8")
                )
                mounts = _build_sw3_mounts(variant_analysis, stage3_contract)
            except (OSError, json.JSONDecodeError, FlowerMountingError):
                mounts = []
            if len(mounts) != len(variant_analysis["flowers"]):
                issues.append("sw3_formal_mount_route_infeasible")
    else:
        issues.append("unsupported_family_guard")
    return issues


def _fixed_flower_metadata(strict_p0: StrictP0V2) -> list[dict[str, Any]]:
    return [
        {
            "flower_id": flower.flower_id,
            "base_center": [round(value, 12) for value in flower.center],
            "variant_center": [round(value, 12) for value in flower.center],
            "rx": round(flower.rx, 12),
            "ry": round(flower.ry, 12),
            "transport_policy": "fixed_geometry_in_5b",
        }
        for flower in strict_p0.flowers
    ]


def _make_variant(
    strict_p0: StrictP0V2,
    points: Sequence[Point],
) -> StrictP0V2:
    tangents = _periodic_tangents(points)
    samples = [
        BackboneSample(
            s=index / len(points),
            point=point,
            tangent=tangents[index],
        )
        for index, point in enumerate(points)
    ]
    samples.append(
        BackboneSample(
            s=1.0,
            point=(points[0][0] + 1.0, points[0][1]),
            tangent=tangents[0],
        )
    )
    return StrictP0V2(
        prototype_id=strict_p0.prototype_id,
        frame=strict_p0.frame,
        backbone_samples=tuple(samples),
        flowers=strict_p0.flowers,
        structure_protection_zones=strict_p0.structure_protection_zones,
    )


def _shape_controls_v3(
    seed: int,
    namespace: str,
    contract: Mapping[str, Any],
    overrides: Mapping[str, float] | None,
) -> tuple[dict[str, float], dict[str, float]]:
    domains = {
        "amplitude": "amplitude_domain",
        "arc_length": "arc_length_domain",
        "curvature_concentration": "curvature_domain",
        "asymmetry": "asymmetry_domain",
    }
    minimum = float(contract["seed_policy"]["minimum_random_control_magnitude"])
    controls: dict[str, float] = {}
    random_units: dict[str, float] = {}
    for name, domain in domains.items():
        unit = _seed_domain_unit(seed, namespace, domain)
        random_units[name] = unit
        raw = 2.0 * unit - 1.0
        if overrides is not None and name in overrides:
            control = float(overrides[name])
        elif abs(raw) <= 1e-12:
            control = minimum
        else:
            control = math.copysign(
                minimum + (1.0 - minimum) * abs(raw),
                raw,
            )
        if not math.isfinite(control) or not -1.0 <= control <= 1.0:
            raise BackboneVariationError(
                "invalid_backbone_shape_target",
                f"{name} target must lie in [-1, 1]",
            )
        controls[name] = control
    return controls, random_units


def _circular_signed_distance(first: float, second: float) -> float:
    return (first - second + 0.5) % 1.0 - 0.5


def _extremum_support_radius(
    extremum_s: float,
    all_extrema_s: Sequence[float],
    shape: Mapping[str, Any],
) -> float:
    neighbors = [
        _circular_distance(extremum_s, other)
        for other in all_extrema_s
        if _circular_distance(extremum_s, other) > 1e-8
    ]
    nearest = min(neighbors, default=0.5)
    return max(
        float(shape["minimum_support_radius"]),
        min(
            float(shape["maximum_support_radius"]),
            nearest * float(shape["support_radius_as_neighbor_fraction"]),
        ),
    )


def _cosine_bump(distance: float, radius: float) -> float:
    if distance >= radius:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * distance / radius))


def _periodic_scalar_at(
    sample_s: Sequence[float],
    values: Sequence[float],
    query: float,
) -> float:
    wrapped = query % 1.0
    lower = max(0, min(len(sample_s) - 1, bisect_right(sample_s, wrapped) - 1))
    upper = (lower + 1) % len(sample_s)
    lower_s = sample_s[lower]
    upper_s = sample_s[upper] if upper > 0 else 1.0
    denominator = max(upper_s - lower_s, 1e-12)
    fraction = (wrapped - lower_s) / denominator
    return values[lower] + (values[upper] - values[lower]) * fraction


def _extremum_skeleton_points_v3(
    strict_p0: StrictP0V2,
    baseline_analysis: Mapping[str, Any],
    controls: Mapping[str, float],
    strength: float,
    contract: Mapping[str, Any],
) -> tuple[list[Point], dict[str, Any]]:
    """Move the detected peak/trough skeleton, then rebuild one smooth period.

    The correspondence and sample fractions stay fixed.  Unlike V2, this does
    not erase the deformation with equal-arc resampling and does not optimize
    proxy descriptors.
    """

    unique = _unique_samples(strict_p0)
    points = [sample.point for sample in unique]
    sample_s = [sample.s for sample in unique]
    extrema = list(baseline_analysis["backbone"]["extrema"])
    extrema_s = [float(row["s"]) for row in extrema]
    if not extrema_s:
        raise BackboneVariationError(
            "missing_extremum_skeleton",
            "stage-5B extremum deformation requires detected extrema",
        )
    shape = contract["shape_controls"]
    amplitude_control = float(controls["amplitude"])
    amplitude_magnitude = (
        float(shape["amplitude"]["minimum_extremum_shift"])
        + (
            float(shape["amplitude"]["maximum_extremum_shift"])
            - float(shape["amplitude"]["minimum_extremum_shift"])
        )
        * abs(amplitude_control)
    )
    baseline_amplitude = max(point[1] for point in points) - min(point[1] for point in points)
    amplitude_magnitude = min(
        amplitude_magnitude,
        baseline_amplitude
        * float(shape["amplitude"]["maximum_shift_as_baseline_amplitude_fraction"]),
    )
    amplitude_magnitude *= strength
    amplitude_sign = -1.0 if amplitude_control < 0.0 else 1.0

    y_displacements = [0.0] * len(points)
    extremum_targets: list[dict[str, Any]] = []
    for row in extrema:
        kind = str(row["kind"])
        target_shift = amplitude_sign * amplitude_magnitude * (
            -1.0 if kind == "peak" else 1.0
        )
        center_s = float(row["s"])
        radius = _extremum_support_radius(
            center_s,
            extrema_s,
            shape["amplitude"],
        )
        for index, value in enumerate(sample_s):
            y_displacements[index] += target_shift * _cosine_bump(
                _circular_distance(value, center_s),
                radius,
            )
        extremum_targets.append(
            {
                "kind": kind,
                "baseline_s": round(center_s, 9),
                "support_radius": round(radius, 9),
                "requested_vertical_shift": round(target_shift, 9),
            }
        )

    anchor = max(
        extrema,
        key=lambda row: abs(float(row["point"][1]) - sum(p[1] for p in points) / len(points)),
    )
    anchor_s = float(anchor["s"])
    asymmetry_amount = (
        float(controls["asymmetry"])
        * strength
        * float(shape["asymmetry"]["maximum_slope_bias"])
    )
    varied_y = [
        point[1]
        + y_displacements[index]
        + asymmetry_amount * math.sin(2.0 * math.pi * (sample_s[index] - anchor_s))
        for index, point in enumerate(points)
    ]

    low = min(varied_y)
    high = max(varied_y)
    center = 0.5 * (low + high)
    half_span = max(0.5 * (high - low), 1e-9)
    shoulder_warp = (
        float(controls["curvature_concentration"])
        * strength
        * float(shape["curvature_concentration"]["maximum_shoulder_warp"])
    )
    rebuilt_y: list[float] = []
    for value in varied_y:
        normalized = max(-1.0, min(1.0, (value - center) / half_span))
        shaped = normalized + shoulder_warp * normalized * (1.0 - normalized**2)
        rebuilt_y.append(center + half_span * shaped)

    spacing_amount = (
        float(controls["arc_length"])
        * strength
        * float(shape["arc_length"]["maximum_horizontal_spacing_warp"])
    )
    seam_value = math.cos(-2.0 * math.pi * anchor_s)
    varied_points = []
    for index, point in enumerate(points):
        phase_offset = spacing_amount * (
            math.cos(2.0 * math.pi * (sample_s[index] - anchor_s)) - seam_value
        )
        varied_points.append(
            _canonical_point(
                (
                    point[0],
                    _periodic_scalar_at(sample_s, rebuilt_y, sample_s[index] + phase_offset),
                )
            )
        )
    corresponding = [
        _length(_sub(variant, baseline))
        for baseline, variant in zip(points, varied_points)
    ]
    return varied_points, {
        "primary_geometry": "extremum_skeleton_smooth_rebuild",
        "anchor_s": round(anchor_s, 9),
        "curvature_shoulder_warp": round(shoulder_warp, 9),
        "slope_bias": round(asymmetry_amount, 9),
        "horizontal_spacing_warp": round(spacing_amount, 9),
        "extremum_targets": extremum_targets,
        "maximum_corresponding_displacement": round(max(corresponding), 9),
        "rms_corresponding_displacement": round(
            math.sqrt(sum(value * value for value in corresponding) / len(corresponding)),
            9,
        ),
    }


def _generate_extremum_skeleton_variant_v3(
    strict_p0: StrictP0V2,
    seed: int,
    strength: float,
    prototype_strategy: Mapping[str, Any],
    shape_targets: Mapping[str, float] | None,
) -> tuple[StrictP0V2, dict[str, Any]]:
    contract = _load_variation_contract_v3()
    policy = prototype_strategy["backbone_domain"]
    if policy.get("variation_contract") != contract["contract_id"]:
        raise BackboneVariationError(
            "backbone_variation_contract_mismatch",
            "prototype strategy does not name the active stage-5B retry contract",
        )
    if policy.get("flower_transport_policy") != "fixed_geometry_in_5b":
        raise BackboneVariationError(
            "unsupported_flower_transport_strategy",
            "stage 5B requires fixed flower geometry",
        )
    base_points = [sample.point for sample in _unique_samples(strict_p0)]
    baseline_analysis = analyze_prototype(strict_p0)
    baseline_descriptors = backbone_shape_descriptors(base_points)
    controls, random_units = _shape_controls_v3(
        seed,
        str(prototype_strategy["strategy_id"]),
        contract,
        shape_targets,
    )
    common_metadata = {
        "schema": "dynamic_backbone_variation_v3",
        "contract_id": contract["contract_id"],
        "prototype_id": strict_p0.prototype_id,
        "prototype_strategy_id": str(prototype_strategy["strategy_id"]),
        "backbone_seed": seed,
        "rho": strength,
        "shape_controls": {key: round(value, 12) for key, value in controls.items()},
        "random_domain_units": random_units,
        "baseline_descriptors": {
            key: round(value, 12) for key, value in baseline_descriptors.items()
        },
        "flower_geometry_fixed": True,
        "flower_anchors": _fixed_flower_metadata(strict_p0),
        "family_guard": str(policy["family_guard"]),
    }
    if strength <= 0.0:
        return strict_p0, {
            **common_metadata,
            "selected_feasibility_scale": 0.0,
            "skeleton_deformation": {
                "primary_geometry": "extremum_skeleton_smooth_rebuild",
                "maximum_corresponding_displacement": 0.0,
                "rms_corresponding_displacement": 0.0,
                "extremum_targets": [],
            },
            "achieved_descriptors": {
                key: round(value, 12) for key, value in baseline_descriptors.items()
            },
            "rejected_projection_scales": [],
            "family_guard_issues": [],
            "available": True,
            "reason": None,
        }

    constraints = contract["hard_constraints"]
    projection = contract["projection"]
    lower = float(strict_p0.frame.local_canvas_bounds[1]) + float(
        constraints["vertical_canvas_margin"]
    )
    upper = float(strict_p0.frame.local_canvas_bounds[3]) - float(
        constraints["vertical_canvas_margin"]
    )
    rejected: list[dict[str, Any]] = []
    selected: tuple[StrictP0V2, Mapping[str, Any], float, dict[str, Any]] | None = None
    for declared_scale in projection["feasibility_scales"]:
        scale = float(declared_scale)
        trial_points, deformation = _extremum_skeleton_points_v3(
            strict_p0,
            baseline_analysis,
            controls,
            strength * scale,
            contract,
        )
        issues: list[str] = []
        if backbone_self_intersections(trial_points):
            issues.append("backbone_self_intersection")
        if any(not lower <= point[1] <= upper for point in trial_points):
            issues.append("backbone_vertical_margin_violation")
        extended = [*trial_points, (trial_points[0][0] + 1.0, trial_points[0][1])]
        if any(
            _length(_sub(second, first))
            < float(constraints["minimum_adjacent_sample_distance"])
            for first, second in zip(extended, extended[1:])
        ):
            issues.append("backbone_adjacent_sample_collapse")
        minimum_maximum = (
            float(projection["minimum_maximum_corresponding_displacement_per_strength"])
            * strength
            * scale
        )
        minimum_rms = (
            float(projection["minimum_rms_corresponding_displacement_per_strength"])
            * strength
            * scale
        )
        if float(deformation["maximum_corresponding_displacement"]) + 1e-9 < minimum_maximum:
            issues.append("backbone_deformation_below_visible_maximum_floor")
        if float(deformation["rms_corresponding_displacement"]) + 1e-9 < minimum_rms:
            issues.append("backbone_deformation_below_visible_rms_floor")
        if not issues:
            trial_variant = _make_variant(strict_p0, trial_points)
            trial_analysis = analyze_prototype(trial_variant)
            issues.extend(
                _family_guard_issues(
                    trial_variant,
                    baseline_analysis,
                    trial_analysis,
                    prototype_strategy,
                    contract,
                )
            )
        if not issues:
            selected = trial_variant, trial_analysis, scale, deformation
            break
        rejected.append({"scale": scale, "issues": sorted(set(issues))})
    if selected is None:
        raise BackboneVariationError(
            "backbone_variation_infeasible",
            "no declared skeleton projection preserves the prototype domain",
        )
    selected_variant, _, selected_scale, deformation = selected
    achieved = backbone_shape_descriptors(
        [sample.point for sample in selected_variant.backbone_samples[:-1]]
    )
    return selected_variant, {
        **common_metadata,
        "selected_feasibility_scale": selected_scale,
        "skeleton_deformation": deformation,
        "achieved_descriptors": {
            key: round(value, 12) for key, value in achieved.items()
        },
        "rejected_projection_scales": rejected,
        "family_guard_issues": [],
        "available": True,
        "reason": None,
    }


def _generate_joint_backbone_variant_v2(
    strict_p0: StrictP0V2,
    seed: int,
    strength: float,
    prototype_strategy: Mapping[str, Any],
    shape_targets: Mapping[str, float] | None,
) -> tuple[StrictP0V2, dict[str, Any]]:
    contract = _load_variation_contract()
    backbone_policy = prototype_strategy["backbone_domain"]
    if backbone_policy.get("variation_contract") != contract["contract_id"]:
        raise BackboneVariationError(
            "backbone_variation_contract_mismatch",
            "prototype strategy does not name the active stage-5B contract",
        )
    if backbone_policy.get("flower_transport_policy") != "fixed_geometry_in_5b":
        raise BackboneVariationError(
            "unsupported_flower_transport_strategy",
            "stage 5B requires fixed flower geometry",
        )
    unique = _unique_samples(strict_p0)
    base_points = [sample.point for sample in unique]
    base_flowers = tuple(strict_p0.flowers)
    baseline_analysis = analyze_prototype(strict_p0)
    baseline_descriptors = backbone_shape_descriptors(base_points)
    target_deltas, random_units = _target_descriptor_deltas(
        seed,
        str(prototype_strategy["strategy_id"]),
        strength,
        baseline_descriptors,
        contract,
        shape_targets,
    )
    available_margin, maximum_budget = displacement_budget(strict_p0)
    if strength <= 0.0:
        return strict_p0, {
            "schema": "dynamic_backbone_variation_v2",
            "contract_id": contract["contract_id"],
            "prototype_id": strict_p0.prototype_id,
            "prototype_strategy_id": str(prototype_strategy["strategy_id"]),
            "backbone_seed": seed,
            "rho": 0.0,
            "available_margin": available_margin,
            "maximum_displacement_budget": maximum_budget,
            "selected_feasibility_scale": 0.0,
            "random_domain_units": random_units,
            "baseline_descriptors": {
                key: round(value, 12) for key, value in baseline_descriptors.items()
            },
            "requested_descriptor_deltas": {
                key: 0.0 for key in baseline_descriptors
            },
            "achieved_descriptors": {
                key: round(value, 12) for key, value in baseline_descriptors.items()
            },
            "basis_coefficients": [0.0, 0.0, 0.0, 0.0],
            "joint_solver_trace": [],
            "rejected_projection_scales": [],
            "flower_geometry_fixed": True,
            "flower_anchors": _fixed_flower_metadata(strict_p0),
            "family_guard": str(backbone_policy["family_guard"]),
            "family_guard_issues": [],
            "available": True,
            "reason": None,
        }
    bases = _joint_shape_bases(base_points, _periodic_tangents(base_points))
    solver = contract["joint_solver"]
    names = (
        "amplitude",
        "arc_length",
        "curvature_concentration",
        "asymmetry",
    )
    row_scales = []
    for name in names:
        if name == "asymmetry":
            scale = float(
                contract["shape_dimensions"][name]["maximum_absolute_delta"]
            )
        else:
            scale = baseline_descriptors[name] * float(
                contract["shape_dimensions"][name]["maximum_relative_delta"]
            )
        row_scales.append(max(scale, 1e-8))
    target_descriptors = [
        baseline_descriptors[name] + target_deltas[name]
        for name in names
    ]
    coefficients, joint_solver_trace = _iterative_joint_coefficients(
        base_points,
        bases,
        target_descriptors,
        row_scales,
        maximum_budget,
        solver,
    )

    selected_variant: StrictP0V2 | None = None
    selected_analysis: Mapping[str, Any] | None = None
    selected_scale = 0.0
    rejected_scales: list[dict[str, Any]] = []
    constraints = contract["hard_constraints"]
    lower = float(strict_p0.frame.local_canvas_bounds[1]) + float(
        constraints["vertical_canvas_margin"]
    )
    upper = float(strict_p0.frame.local_canvas_bounds[3]) - float(
        constraints["vertical_canvas_margin"]
    )
    for feasibility_scale in solver["feasibility_scales"]:
        scale = float(feasibility_scale)
        trial_coefficients = [value * scale for value in coefficients]
        if scale <= 0.0:
            trial_points = list(base_points)
        else:
            trial_points = _materialize_joint_points(
                base_points,
                bases,
                trial_coefficients,
                maximum_budget,
            )
        issues: list[str] = []
        if backbone_self_intersections(trial_points):
            issues.append("backbone_self_intersection")
        if any(not lower <= point[1] <= upper for point in trial_points):
            issues.append("backbone_vertical_margin_violation")
        extended = [*trial_points, (trial_points[0][0] + 1.0, trial_points[0][1])]
        if any(
            _length(_sub(second, first))
            < float(constraints["minimum_adjacent_sample_distance"])
            for first, second in zip(extended, extended[1:])
        ):
            issues.append("backbone_adjacent_sample_collapse")
        if not issues:
            trial_variant = (
                strict_p0
                if scale <= 0.0
                else _make_variant(strict_p0, trial_points)
            )
            if tuple(trial_variant.flowers) != base_flowers:
                issues.append("flower_geometry_changed_in_5b")
            trial_analysis = analyze_prototype(trial_variant)
            issues.extend(
                _family_guard_issues(
                    trial_variant,
                    baseline_analysis,
                    trial_analysis,
                    prototype_strategy,
                    contract,
                )
            )
        if not issues:
            selected_variant = trial_variant
            selected_analysis = trial_analysis
            selected_scale = scale
            break
        rejected_scales.append({"scale": scale, "issues": sorted(set(issues))})
    if selected_variant is None or selected_analysis is None:
        raise BackboneVariationError(
            "backbone_variation_infeasible",
            "no declared projection scale preserves the prototype domain",
        )
    achieved = backbone_shape_descriptors(
        [sample.point for sample in selected_variant.backbone_samples[:-1]]
    )
    metadata = {
        "schema": "dynamic_backbone_variation_v2",
        "contract_id": contract["contract_id"],
        "prototype_id": strict_p0.prototype_id,
        "prototype_strategy_id": str(prototype_strategy["strategy_id"]),
        "backbone_seed": seed,
        "rho": strength,
        "available_margin": available_margin,
        "maximum_displacement_budget": maximum_budget,
        "selected_feasibility_scale": selected_scale,
        "random_domain_units": random_units,
        "baseline_descriptors": {
            key: round(value, 12) for key, value in baseline_descriptors.items()
        },
        "requested_descriptor_deltas": {
            key: round(value, 12) for key, value in target_deltas.items()
        },
        "achieved_descriptors": {
            key: round(value, 12) for key, value in achieved.items()
        },
        "basis_coefficients": [round(value * selected_scale, 12) for value in coefficients],
        "joint_solver_trace": joint_solver_trace,
        "rejected_projection_scales": rejected_scales,
        "flower_geometry_fixed": True,
        "flower_anchors": _fixed_flower_metadata(strict_p0),
        "family_guard": str(backbone_policy["family_guard"]),
        "family_guard_issues": [],
        "available": True,
        "reason": None,
    }
    return selected_variant, metadata


def _resample_periodic(points: Sequence[Point], count: int) -> list[Point]:
    extended = [*points, (points[0][0] + 1.0, points[0][1])]
    lengths = [0.0]
    for first, second in zip(extended, extended[1:]):
        lengths.append(lengths[-1] + _length(_sub(second, first)))
    total = lengths[-1]
    if total <= 1e-12:
        raise BackboneVariationError(
            "degenerate_backbone",
            "the varied periodic backbone has zero length",
        )
    result: list[Point] = []
    for index in range(count):
        target = total * index / count
        segment = max(0, min(len(points) - 1, bisect_right(lengths, target) - 1))
        span = lengths[segment + 1] - lengths[segment]
        fraction = 0.0 if span <= 1e-12 else (target - lengths[segment]) / span
        result.append(_lerp(extended[segment], extended[segment + 1], fraction))
    return result


def _orientation(first: Point, second: Point, third: Point) -> float:
    return (
        (second[0] - first[0]) * (third[1] - first[1])
        - (second[1] - first[1]) * (third[0] - first[0])
    )


def _proper_segment_intersection(
    first_start: Point,
    first_end: Point,
    second_start: Point,
    second_end: Point,
) -> bool:
    first_a = _orientation(first_start, first_end, second_start)
    first_b = _orientation(first_start, first_end, second_end)
    second_a = _orientation(second_start, second_end, first_start)
    second_b = _orientation(second_start, second_end, first_end)
    epsilon = 1e-11
    return (
        first_a * first_b < -epsilon
        and second_a * second_b < -epsilon
    )


def backbone_self_intersections(points: Sequence[Point]) -> list[tuple[int, int, int]]:
    """Return proper intersections within the period and against adjacent copies."""

    extended = [*points, (points[0][0] + 1.0, points[0][1])]
    segments = list(zip(extended, extended[1:]))
    intersections: list[tuple[int, int, int]] = []
    for first_index, (first_start, first_end) in enumerate(segments):
        for second_index, (second_start, second_end) in enumerate(segments):
            if first_index >= second_index or abs(first_index - second_index) <= 1:
                continue
            if _proper_segment_intersection(
                first_start,
                first_end,
                second_start,
                second_end,
            ):
                intersections.append((first_index, second_index, 0))
        for shift in (-1, 1):
            for second_index, (second_start, second_end) in enumerate(segments):
                shifted_start = second_start[0] + shift, second_start[1]
                shifted_end = second_end[0] + shift, second_end[1]
                if _proper_segment_intersection(
                    first_start,
                    first_end,
                    shifted_start,
                    shifted_end,
                ):
                    intersections.append((first_index, second_index, shift))
    return sorted(set(intersections))


def _sample_frame(
    points: Sequence[Point],
    tangents: Sequence[Point],
    s: float,
) -> tuple[Point, Point]:
    position = (s % 1.0) * len(points)
    lower = int(math.floor(position)) % len(points)
    fraction = position - math.floor(position)
    upper = (lower + 1) % len(points)
    upper_point = points[upper]
    if upper == 0:
        upper_point = upper_point[0] + 1.0, upper_point[1]
    point = _lerp(points[lower], upper_point, fraction)
    tangent = _unit(
        _lerp(tangents[lower], tangents[upper], fraction),
        "interpolated periodic tangent",
    )
    return point, tangent


def _flower_anchor(
    flower: FlowerReserve,
    points: Sequence[Point],
    sample_s: Sequence[float],
) -> dict[str, Any]:
    extended_points = [*points, (points[0][0] + 1.0, points[0][1])]
    extended_s = [*sample_s, 1.0]
    best: tuple[float, int, float, int, Point, Point] | None = None
    for period_offset in (-1, 0, 1):
        shifted_center = flower.center[0] + period_offset, flower.center[1]
        for index, (start, end) in enumerate(
            zip(extended_points, extended_points[1:])
        ):
            vector = _sub(end, start)
            denominator = _dot(vector, vector)
            fraction = 0.0 if denominator <= 1e-12 else max(
                0.0,
                min(1.0, _dot(_sub(shifted_center, start), vector) / denominator),
            )
            projection = _lerp(start, end, fraction)
            distance = _length(_sub(shifted_center, projection))
            tangent = _unit(vector, "flower anchor segment")
            candidate = (
                distance,
                index,
                fraction,
                period_offset,
                projection,
                tangent,
            )
            if best is None or candidate[:4] < best[:4]:
                best = candidate
    if best is None:
        raise BackboneVariationError(
            "flower_anchor_unavailable",
            f"no continuous backbone anchor for {flower.flower_id}",
        )
    _, index, fraction, period_offset, projection, tangent = best
    anchor_s = extended_s[index] + (
        extended_s[index + 1] - extended_s[index]
    ) * fraction
    shifted_center = flower.center[0] + period_offset, flower.center[1]
    offset = _sub(shifted_center, projection)
    normal = -tangent[1], tangent[0]
    offset_n = _dot(offset, normal)
    return {
        "flower_id": flower.flower_id,
        "anchor_s": anchor_s % 1.0,
        "period_offset": period_offset,
        "offset_t": _dot(offset, tangent),
        "offset_n": offset_n,
        "normal_side": "left_normal" if offset_n >= 0.0 else "right_normal",
    }


def _move_flowers(
    strict_p0: StrictP0V2,
    base_points: Sequence[Point],
    base_s: Sequence[float],
    variant_points: Sequence[Point],
    variant_tangents: Sequence[Point],
) -> tuple[tuple[FlowerReserve, ...], list[dict[str, Any]]]:
    anchors = [
        _flower_anchor(flower, base_points, base_s)
        for flower in strict_p0.flowers
    ]
    moved: list[FlowerReserve] = []
    metadata: list[dict[str, Any]] = []
    for flower, anchor in zip(strict_p0.flowers, anchors):
        point, tangent = _sample_frame(
            variant_points,
            variant_tangents,
            float(anchor["anchor_s"]),
        )
        normal = -tangent[1], tangent[0]
        unwrapped_center = _add(
            point,
            _add(
                _mul(tangent, float(anchor["offset_t"])),
                _mul(normal, float(anchor["offset_n"])),
            ),
        )
        center = (
            unwrapped_center[0] - int(anchor["period_offset"]),
            unwrapped_center[1],
        )
        center = _canonical_point(center)
        moved.append(
            FlowerReserve(
                flower_id=flower.flower_id,
                center=center,
                rx=flower.rx,
                ry=flower.ry,
            )
        )
        metadata.append(
            {
                **anchor,
                "base_center": [round(value, 12) for value in flower.center],
                "variant_center": [round(value, 12) for value in center],
            }
        )
    return tuple(moved), metadata


def generate_backbone_variant(
    strict_p0: StrictP0V2,
    backbone_seed: int,
    rho: float | None = None,
    *,
    prototype_strategy: Mapping[str, Any] | None = None,
    shape_targets: Mapping[str, float] | None = None,
    prototype_variant_id: str | None = None,
) -> tuple[StrictP0V2, dict[str, Any]]:
    seed = validate_seed(backbone_seed, "backbone_seed")
    strength = production_rho(seed) if rho is None else float(rho)
    if not math.isfinite(strength) or not 0.0 <= strength <= 1.0:
        raise BackboneVariationError(
            "invalid_backbone_strength",
            "rho must lie in [0, 1]",
        )
    if prototype_strategy is not None:
        validate_strategy_projection(
            prototype_strategy,
            prototype_id=strict_p0.prototype_id,
            flower_count=len(strict_p0.flowers),
        )
        backbone_policy = prototype_strategy["backbone_domain"]
        if backbone_policy.get("generator") == "global_periodic_wave_v4":
            from global_backbone_wave_v4 import (
                generate_global_wave_variant,
                generate_named_global_wave_variant,
            )

            if shape_targets is not None and prototype_variant_id is not None:
                raise BackboneVariationError(
                    "conflicting_backbone_variant_request",
                    "shape targets and a named prototype variant are mutually exclusive",
                )
            selected_variant_id = (
                prototype_variant_id
                if prototype_variant_id is not None
                else production_prototype_variant_id(seed, strict_p0.prototype_id)
            )
            if shape_targets is None:
                variant, metadata = generate_named_global_wave_variant(
                    strict_p0,
                    seed,
                    prototype_strategy,
                    selected_variant_id,
                    1.0 if rho is None else strength,
                )
                metadata = dict(metadata)
                metadata["production_variant_selection"] = (
                    "explicit" if prototype_variant_id is not None else "seeded"
                )
                return variant, metadata

            return generate_global_wave_variant(
                strict_p0,
                seed,
                strength,
                prototype_strategy,
                shape_targets,
            )
        if backbone_policy.get("generator") == "extremum_skeleton_backbone_v3":
            return _generate_extremum_skeleton_variant_v3(
                strict_p0,
                seed,
                strength,
                prototype_strategy,
                shape_targets,
            )
        if backbone_policy.get("generator") == "joint_descriptor_backbone_v2":
            return _generate_joint_backbone_variant_v2(
                strict_p0,
                seed,
                strength,
                prototype_strategy,
                shape_targets,
            )
        if backbone_policy.get("generator") != "controlled_periodic_backbone_v1":
            raise BackboneVariationError(
                "unsupported_backbone_strategy",
                "5A only supports the existing controlled periodic backbone generator",
            )
        if backbone_policy.get("flower_transport_policy") != (
            "continuous_local_anchor_v1"
        ):
            raise BackboneVariationError(
                "unsupported_flower_transport_strategy",
                "5A requires continuous local flower-anchor transport",
            )
    if shape_targets:
        raise BackboneVariationError(
            "unsupported_backbone_shape_target",
            "shape targets require the stage-5B joint descriptor generator",
        )
    unique = _unique_samples(strict_p0)
    base_points = [sample.point for sample in unique]
    base_s = [sample.s for sample in unique]
    available_margin, maximum_budget = displacement_budget(strict_p0)
    parameters = _mode_parameters(seed)
    requested_budget = strength * maximum_budget
    if requested_budget <= 0.0:
        reason = (
            "backbone_variation_unavailable_for_margin"
            if maximum_budget <= 0.0 and strength > 0.0
            else None
        )
        metadata = {
            "schema": "dynamic_backbone_variation_v1",
            "prototype_id": strict_p0.prototype_id,
            "backbone_seed": seed,
            "rho": strength,
            "available_margin": available_margin,
            "maximum_displacement_budget": maximum_budget,
            "applied_displacement_budget": 0.0,
            "available": reason is None,
            "reason": reason,
            "mode_parameters": parameters,
            "flower_anchors": [],
            "prototype_strategy_id": (
                str(prototype_strategy["strategy_id"])
                if prototype_strategy is not None
                else None
            ),
        }
        return strict_p0, metadata

    base_tangents = _periodic_tangents(base_points)
    raw = _raw_displacements(unique, _normals(base_tangents), parameters)
    maximum_raw = max(_length(value) for value in raw)
    if maximum_raw <= 1e-12:
        raise BackboneVariationError(
            "degenerate_variation_field",
            "the combined low-dimensional displacement field is zero",
        )
    scale = requested_budget / maximum_raw
    displaced = [
        _add(point, _mul(raw_value, scale))
        for point, raw_value in zip(base_points, raw)
    ]
    variant_points = [
        _canonical_point(point)
        for point in _resample_periodic(displaced, len(base_points))
    ]
    intersections = backbone_self_intersections(variant_points)
    if intersections:
        raise BackboneVariationError(
            "backbone_self_intersection",
            f"the varied backbone has {len(intersections)} proper intersections",
        )
    variant_tangents = _periodic_tangents(variant_points)
    moved_flowers, flower_anchors = _move_flowers(
        strict_p0,
        base_points,
        base_s,
        variant_points,
        variant_tangents,
    )
    samples = [
        BackboneSample(
            s=index / len(variant_points),
            point=point,
            tangent=variant_tangents[index],
        )
        for index, point in enumerate(variant_points)
    ]
    samples.append(
        BackboneSample(
            s=1.0,
            point=(variant_points[0][0] + 1.0, variant_points[0][1]),
            tangent=variant_tangents[0],
        )
    )
    variant = StrictP0V2(
        prototype_id=strict_p0.prototype_id,
        frame=strict_p0.frame,
        backbone_samples=tuple(samples),
        flowers=moved_flowers,
        structure_protection_zones=strict_p0.structure_protection_zones,
    )
    metadata = {
        "schema": "dynamic_backbone_variation_v1",
        "prototype_id": strict_p0.prototype_id,
        "backbone_seed": seed,
        "rho": strength,
        "available_margin": available_margin,
        "maximum_displacement_budget": maximum_budget,
        "applied_displacement_budget": requested_budget,
        "available": True,
        "reason": None,
        "mode_parameters": parameters,
        "flower_anchors": flower_anchors,
        "prototype_strategy_id": (
            str(prototype_strategy["strategy_id"])
            if prototype_strategy is not None
            else None
        ),
    }
    return variant, metadata


def generate_and_analyze_variant(
    strict_p0: StrictP0V2,
    backbone_seed: int,
    rho: float | None = None,
    *,
    prototype_strategy: Mapping[str, Any] | None = None,
    shape_targets: Mapping[str, float] | None = None,
    prototype_variant_id: str | None = None,
) -> tuple[StrictP0V2, dict[str, Any], dict[str, Any]]:
    variant, metadata = generate_backbone_variant(
        strict_p0,
        backbone_seed,
        rho,
        prototype_strategy=prototype_strategy,
        shape_targets=shape_targets,
        prototype_variant_id=prototype_variant_id,
    )
    analysis = analyze_prototype(variant)
    return variant, analysis, metadata
