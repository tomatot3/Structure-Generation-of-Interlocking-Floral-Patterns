#!/usr/bin/env python3
"""Global low-frequency periodic backbone variation for stage 5B.

The generator changes a baseline prototype through four interpretable global
controls.  It never perturbs individual samples and never moves one detected
extremum independently of the rest of the periodic waveform.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from prototype_analysis import analyze_prototype
from strict_p0_v2 import BackboneSample, StrictP0V2


Point = tuple[float, float]
CONTRACT_PATH = Path(__file__).with_name("BACKBONE_WAVE_CONTRACT_V4.json")
CONTRACT_SCHEMA = "dynamic_backbone_wave_contract_v4"
VARIANT_LIBRARY_PATH = Path(__file__).with_name("BACKBONE_PROTOTYPE_VARIANTS_V1.json")
VARIANT_LIBRARY_SCHEMA = "dynamic_backbone_prototype_variant_library_v1"
GENERATOR_ID = "global_periodic_wave_v4"


class GlobalBackboneWaveError(RuntimeError):
    """The requested global waveform leaves the declared prototype domain."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _load_contract() -> dict[str, Any]:
    try:
        value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GlobalBackboneWaveError(
            "backbone_wave_contract_invalid",
            f"cannot read {CONTRACT_PATH}",
        ) from exc
    if value.get("schema") != CONTRACT_SCHEMA:
        raise GlobalBackboneWaveError(
            "backbone_wave_contract_invalid",
            "stage-5B global waveform contract schema mismatch",
        )
    return value


def load_prototype_variant_library() -> dict[str, Any]:
    """Load named multi-control directions consumed by the V4 generator."""

    try:
        value = json.loads(VARIANT_LIBRARY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GlobalBackboneWaveError(
            "prototype_variant_library_invalid",
            f"cannot read {VARIANT_LIBRARY_PATH}",
        ) from exc
    if value.get("schema") != VARIANT_LIBRARY_SCHEMA:
        raise GlobalBackboneWaveError(
            "prototype_variant_library_invalid",
            "stage-5B prototype variant library schema mismatch",
        )
    if value.get("generator") != GENERATOR_ID:
        raise GlobalBackboneWaveError(
            "prototype_variant_library_invalid",
            "prototype variant library does not target the active V4 generator",
        )
    return value


def resolve_prototype_variant(
    prototype_id: str,
    variant_id: str,
) -> dict[str, Any]:
    """Resolve one prototype-specific, simultaneous waveform change."""

    library = load_prototype_variant_library()
    variants = library.get("variants_per_prototype", {}).get(prototype_id)
    if not isinstance(variants, list):
        raise GlobalBackboneWaveError(
            "prototype_variant_missing",
            f"no named waveform variants for {prototype_id}",
        )
    for raw_variant in variants:
        if isinstance(raw_variant, Mapping) and raw_variant.get("variant_id") == variant_id:
            controls = raw_variant.get("controls")
            if not isinstance(controls, Mapping) or set(controls) != {
                "amplitude",
                "wavelength",
                "rhythm",
                "roundness",
            }:
                raise GlobalBackboneWaveError(
                    "prototype_variant_invalid",
                    f"{prototype_id}/{variant_id} must set all four waveform controls",
                )
            return dict(raw_variant)
    raise GlobalBackboneWaveError(
        "prototype_variant_missing",
        f"unknown waveform variant {prototype_id}/{variant_id}",
    )


def _canonical(value: float) -> float:
    result = round(float(value), 9)
    return 0.0 if result == -0.0 else result


def _unit(vector: Point, label: str) -> Point:
    length = math.hypot(*vector)
    if length <= 1e-12:
        raise GlobalBackboneWaveError("degenerate_wave", f"{label} is zero")
    return vector[0] / length, vector[1] / length


def _unique_points(strict_p0: StrictP0V2) -> list[Point]:
    samples = strict_p0.backbone_samples
    if len(samples) < 6:
        raise GlobalBackboneWaveError(
            "insufficient_backbone_samples",
            "global waveform requires at least five periodic samples",
        )
    first = samples[0].point
    last = samples[-1].point
    if abs(last[0] - first[0] - 1.0) > 1e-7 or abs(last[1] - first[1]) > 1e-7:
        raise GlobalBackboneWaveError(
            "backbone_seam_position_discontinuous",
            "the last backbone point must equal the first plus one repeat",
        )
    return [sample.point for sample in samples[:-1]]


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
                (following[0] - previous[0], following[1] - previous[1]),
                f"periodic tangent {index}",
            )
        )
    return tangents


def _catmull_rom_periodic(values: Sequence[float], phase: float) -> float:
    count = len(values)
    position = (phase % 1.0) * count
    index = int(math.floor(position)) % count
    fraction = position - math.floor(position)
    p0 = float(values[(index - 1) % count])
    p1 = float(values[index])
    p2 = float(values[(index + 1) % count])
    p3 = float(values[(index + 2) % count])
    return 0.5 * (
        2.0 * p1
        + (-p0 + p2) * fraction
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * fraction**2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * fraction**3
    )


def _seed_unit(seed: int, namespace: str, control: str) -> float:
    payload = hashlib.sha256(
        f"{namespace}:{seed}:{control}:global_wave_v4".encode("utf-8")
    ).digest()
    return int.from_bytes(payload[:8], "big") / float(2**64)


def _normalized_controls(
    seed: int,
    namespace: str,
    overrides: Mapping[str, float] | None,
) -> tuple[dict[str, float], dict[str, float]]:
    aliases = {
        "amplitude": "amplitude",
        "amplitude_scale": "amplitude",
        "wavelength": "wavelength",
        "wavelength_scale": "wavelength",
        "rhythm": "rhythm",
        "rhythm_warp": "rhythm",
        "roundness": "roundness",
    }
    normalized_overrides: dict[str, float] = {}
    for raw_name, raw_value in (overrides or {}).items():
        if raw_name not in aliases:
            raise GlobalBackboneWaveError(
                "unknown_wave_control",
                f"unknown global waveform control: {raw_name}",
            )
        name = aliases[raw_name]
        value = float(raw_value)
        if not math.isfinite(value) or not -1.0 <= value <= 1.0:
            raise GlobalBackboneWaveError(
                "invalid_wave_control",
                f"{raw_name} must lie in [-1, 1]",
            )
        normalized_overrides[name] = value
    units: dict[str, float] = {}
    controls: dict[str, float] = {}
    for name in ("amplitude", "wavelength", "rhythm", "roundness"):
        unit = _seed_unit(seed, namespace, name)
        units[name] = unit
        controls[name] = normalized_overrides.get(name, 2.0 * unit - 1.0)
    return controls, units


def _domain_value(
    normalized: float,
    strength: float,
    bounds: Sequence[float],
    baseline: float,
) -> float:
    lower, upper = float(bounds[0]), float(bounds[1])
    if normalized >= 0.0:
        target = baseline + normalized * (upper - baseline)
    else:
        target = baseline + normalized * (baseline - lower)
    return baseline + strength * (target - baseline)


def _strongest_extremum_phase(analysis: Mapping[str, Any]) -> float:
    rows = list(analysis["backbone"]["extrema"])
    if not rows:
        return 0.0
    row = max(rows, key=lambda value: float(value.get("prominence", 0.0)))
    return float(row["s"])


def _rhythm_phase(phase: float, anchor: float, amount: float) -> float:
    base = math.sin(-2.0 * math.pi * anchor)
    return phase + amount / (2.0 * math.pi) * (
        math.sin(2.0 * math.pi * (phase - anchor)) - base
    )


def _round_wave(value: float, center: float, half_span: float, amount: float) -> float:
    if half_span <= 1e-12:
        return value
    normalized = max(-1.0, min(1.0, (value - center) / half_span))
    shaped = normalized + amount * normalized * (1.0 - normalized**2)
    return center + half_span * shaped


def _cross(first: Point, second: Point) -> float:
    return first[0] * second[1] - first[1] * second[0]


def _proper_intersection(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    ab = a1[0] - a0[0], a1[1] - a0[1]
    ba0 = b0[0] - a0[0], b0[1] - a0[1]
    ba1 = b1[0] - a0[0], b1[1] - a0[1]
    cd = b1[0] - b0[0], b1[1] - b0[1]
    dc0 = a0[0] - b0[0], a0[1] - b0[1]
    dc1 = a1[0] - b0[0], a1[1] - b0[1]
    epsilon = 1e-10
    first = _cross(ab, ba0)
    second = _cross(ab, ba1)
    third = _cross(cd, dc0)
    fourth = _cross(cd, dc1)
    return (
        (first > epsilon and second < -epsilon or first < -epsilon and second > epsilon)
        and (third > epsilon and fourth < -epsilon or third < -epsilon and fourth > epsilon)
    )


def _self_intersections(points: Sequence[Point]) -> int:
    extended = [*points, (points[0][0] + 1.0, points[0][1])]
    segments = list(zip(extended, extended[1:]))
    total = 0
    for first_index, (a0, a1) in enumerate(segments):
        for second_index, (b0, b1) in enumerate(segments):
            if second_index <= first_index + 1:
                continue
            if first_index == 0 and second_index == len(segments) - 1:
                continue
            total += int(_proper_intersection(a0, a1, b0, b1))
    return total


def _extrema_kinds(analysis: Mapping[str, Any]) -> list[str]:
    return [str(row["kind"]) for row in analysis["backbone"]["extrema"]]


def _make_variant(strict_p0: StrictP0V2, points: Sequence[Point]) -> StrictP0V2:
    tangents = _periodic_tangents(points)
    samples = [
        BackboneSample(
            s=index / len(points),
            point=(_canonical(point[0]), _canonical(point[1])),
            tangent=tangents[index],
        )
        for index, point in enumerate(points)
    ]
    samples.append(
        BackboneSample(
            s=1.0,
            point=(_canonical(points[0][0] + 1.0), _canonical(points[0][1])),
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


def generate_global_wave_variant(
    strict_p0: StrictP0V2,
    seed: int,
    strength: float,
    prototype_strategy: Mapping[str, Any],
    controls_override: Mapping[str, float] | None = None,
) -> tuple[StrictP0V2, dict[str, Any]]:
    contract = _load_contract()
    policy = prototype_strategy["backbone_domain"]
    if policy.get("generator") != GENERATOR_ID:
        raise GlobalBackboneWaveError(
            "backbone_generator_mismatch",
            "prototype strategy does not select the global waveform generator",
        )
    if policy.get("variation_contract") != contract["contract_id"]:
        raise GlobalBackboneWaveError(
            "backbone_wave_contract_mismatch",
            "prototype strategy does not name the active global waveform contract",
        )
    family_id = str(prototype_strategy["family_id"])
    family_domain = contract["family_domains"].get(family_id)
    if not isinstance(family_domain, Mapping):
        raise GlobalBackboneWaveError(
            "missing_family_wave_domain",
            f"no global waveform domain for {family_id}",
        )
    baseline_points = _unique_points(strict_p0)
    baseline_analysis = analyze_prototype(strict_p0)
    normalized, random_units = _normalized_controls(
        seed,
        str(prototype_strategy["strategy_id"]),
        controls_override,
    )
    def controls_at(projection_scale: float) -> dict[str, float]:
        projected_strength = strength * projection_scale
        return {
            "amplitude_scale": _domain_value(
                normalized["amplitude"],
                projected_strength,
                family_domain["amplitude_scale"],
                1.0,
            ),
            "wavelength_scale": _domain_value(
                normalized["wavelength"],
                projected_strength,
                family_domain["wavelength_scale"],
                1.0,
            ),
            "rhythm_warp": _domain_value(
                normalized["rhythm"],
                projected_strength,
                family_domain["rhythm_warp"],
                0.0,
            ),
            "roundness": _domain_value(
                normalized["roundness"],
                projected_strength,
                family_domain["roundness"],
                0.0,
            ),
        }

    applied = controls_at(1.0)
    if strength <= 0.0 or all(
        abs(value - baseline) <= 1e-12
        for value, baseline in zip(applied.values(), (1.0, 1.0, 0.0, 0.0))
    ):
        return strict_p0, {
            "schema": "dynamic_backbone_wave_variant_v4",
            "contract_id": contract["contract_id"],
            "prototype_id": strict_p0.prototype_id,
            "prototype_strategy_id": str(prototype_strategy["strategy_id"]),
            "backbone_seed": seed,
            "rho": strength,
            "normalized_controls": normalized,
            "applied_controls": applied,
            "physical_repeat_width": applied["wavelength_scale"],
            "random_domain_units": random_units,
            "flower_geometry_fixed_within_repeat": True,
            "peak_trough_sequence": _extrema_kinds(baseline_analysis),
            "available": True,
            "reason": None,
            "selected_feasibility_scale": 0.0,
            "rejected_projection_scales": [],
        }

    y_values = [point[1] for point in baseline_points]
    center = sum(y_values) / len(y_values)
    half_span = max(max(y_values) - center, center - min(y_values), 1e-12)
    anchor = _strongest_extremum_phase(baseline_analysis)
    constraints = contract["hard_constraints"]
    lower = float(strict_p0.frame.local_canvas_bounds[1]) + float(
        constraints["vertical_canvas_margin"]
    )
    upper = float(strict_p0.frame.local_canvas_bounds[3]) - float(
        constraints["vertical_canvas_margin"]
    )
    rejected: list[dict[str, Any]] = []
    selected: tuple[StrictP0V2, Mapping[str, Any], dict[str, float], float] | None = None
    for raw_scale in contract["projection"]["feasibility_scales"]:
        projection_scale = float(raw_scale)
        trial = controls_at(projection_scale)
        amplitude = trial["amplitude_scale"]
        wavelength = trial["wavelength_scale"]
        rhythm = trial["rhythm_warp"]
        roundness = trial["roundness"]
        varied_points: list[Point] = []
        count = len(baseline_points)
        for index, baseline_point in enumerate(baseline_points):
            phase = index / count
            source_phase = _rhythm_phase(phase, anchor, rhythm)
            value = _catmull_rom_periodic(y_values, source_phase)
            value = center + amplitude * (value - center)
            value = _round_wave(value, center, half_span * amplitude, roundness)
            varied_points.append((baseline_point[0], _canonical(value)))
        issues: list[str] = []
        if any(not lower <= point[1] <= upper for point in varied_points):
            issues.append("backbone_vertical_margin_violation")
        if _self_intersections(varied_points):
            issues.append("backbone_self_intersection")
        extended = [*varied_points, (varied_points[0][0] + 1.0, varied_points[0][1])]
        if any(
            math.dist(first, second)
            < float(constraints["minimum_adjacent_sample_distance"])
            for first, second in zip(extended, extended[1:])
        ):
            issues.append("backbone_adjacent_sample_collapse")
        if not issues:
            variant = strict_p0 if projection_scale <= 0.0 else _make_variant(strict_p0, varied_points)
            variant_analysis = analyze_prototype(variant)
            if _extrema_kinds(variant_analysis) != _extrema_kinds(baseline_analysis):
                issues.append("peak_trough_sequence_changed")
        if not issues:
            selected = variant, variant_analysis, trial, projection_scale
            break
        rejected.append({"scale": projection_scale, "issues": sorted(set(issues))})
    if selected is None:
        raise GlobalBackboneWaveError(
            "backbone_wave_infeasible",
            "no declared projection scale preserves the global waveform domain",
        )
    variant, variant_analysis, applied, selected_scale = selected
    wavelength = applied["wavelength_scale"]
    return variant, {
        "schema": "dynamic_backbone_wave_variant_v4",
        "contract_id": contract["contract_id"],
        "prototype_id": strict_p0.prototype_id,
        "prototype_strategy_id": str(prototype_strategy["strategy_id"]),
        "backbone_seed": seed,
        "rho": strength,
        "normalized_controls": {
            key: round(value, 12) for key, value in normalized.items()
        },
        "applied_controls": {
            key: round(value, 12) for key, value in applied.items()
        },
        "physical_repeat_width": round(wavelength, 12),
        "random_domain_units": random_units,
        "rhythm_anchor_s": round(anchor, 12),
        "flower_geometry_fixed_within_repeat": True,
        "peak_trough_sequence": _extrema_kinds(variant_analysis),
        "available": True,
        "reason": None,
        "selected_feasibility_scale": selected_scale,
        "rejected_projection_scales": rejected,
    }


def generate_named_global_wave_variant(
    strict_p0: StrictP0V2,
    seed: int,
    prototype_strategy: Mapping[str, Any],
    variant_id: str,
    strength: float = 1.0,
) -> tuple[StrictP0V2, dict[str, Any]]:
    """Generate a named prototype variant with all four controls coupled."""

    if prototype_strategy["backbone_domain"].get("variant_library") != (
        "prototype_combined_wave_variants_v1"
    ):
        raise GlobalBackboneWaveError(
            "prototype_variant_library_mismatch",
            "prototype strategy does not name the active combined variant library",
        )
    definition = resolve_prototype_variant(strict_p0.prototype_id, variant_id)
    variant, metadata = generate_global_wave_variant(
        strict_p0,
        seed,
        strength,
        prototype_strategy,
        controls_override=definition["controls"],
    )
    metadata = dict(metadata)
    metadata.update(
        {
            "prototype_variant_library": "prototype_combined_wave_variants_v1",
            "prototype_variant_id": variant_id,
            "prototype_variant_label_zh": str(definition["label_zh"]),
            "combined_controls": True,
        }
    )
    return variant, metadata
