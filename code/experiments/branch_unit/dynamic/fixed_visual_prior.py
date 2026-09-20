#!/usr/bin/env python3
"""Extract a strict, role-conditioned visual prior from the frozen v23 baseline.

The prior records what the fixed generator was visually capable of.  It is not
a five-prototype baseline and it is not a fixed topology prescription.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "dynamic_branch_fixed_visual_prior_v1"
BASELINE_SCHEMA = "frozen_fixed_branchunit_baseline_v1"
CONTRACT_SCHEMA = "dynamic_branch_fixed_visual_prior_contract_v1"
Point = tuple[float, float]


class FixedVisualPriorError(RuntimeError):
    """The frozen baseline or extracted prior violates its declared contract."""


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FixedVisualPriorError(f"JSON root must be an object: {path}")
    return value


def _finite(value: object, path: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise FixedVisualPriorError(f"{path} must be finite")
    return number


def _point(value: object, path: str) -> Point:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise FixedVisualPriorError(f"{path} must be a two-number point")
    return _finite(value[0], f"{path}[0]"), _finite(value[1], f"{path}[1]")


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _angle_delta(a: Point, b: Point) -> float:
    cross = a[0] * b[1] - a[1] * b[0]
    dot = a[0] * b[0] + a[1] * b[1]
    return math.degrees(math.atan2(cross, dot))


def _unit(a: Point, b: Point) -> Point:
    vector = b[0] - a[0], b[1] - a[1]
    length = math.hypot(*vector)
    if length <= 1e-12:
        raise FixedVisualPriorError("curve contains a degenerate direction")
    return vector[0] / length, vector[1] / length


def _polyline_turn(points: Sequence[Sequence[float]]) -> tuple[float, float]:
    if len(points) < 3:
        raise FixedVisualPriorError("curve polyline must contain at least three points")
    converted = [_point(point, "curve.points") for point in points]
    signed = 0.0
    absolute = 0.0
    previous = _unit(converted[0], converted[1])
    for index in range(2, len(converted)):
        current = _unit(converted[index - 1], converted[index])
        delta = _angle_delta(previous, current)
        signed += delta
        absolute += abs(delta)
        previous = current
    return signed, absolute


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise FixedVisualPriorError("cannot summarize an empty sample")
    position = probability * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def summarize(values: Iterable[float]) -> dict[str, Any]:
    rows = sorted(float(value) for value in values)
    if not rows or any(not math.isfinite(value) for value in rows):
        raise FixedVisualPriorError("statistical feature has no finite samples")
    mean = sum(rows) / len(rows)
    variance = sum((value - mean) ** 2 for value in rows) / len(rows)
    return {
        "count": len(rows),
        "min": round(rows[0], 9),
        "q25": round(_quantile(rows, 0.25), 9),
        "median": round(_quantile(rows, 0.50), 9),
        "q75": round(_quantile(rows, 0.75), 9),
        "max": round(rows[-1], 9),
        "mean": round(mean, 9),
        "stddev": round(math.sqrt(variance), 9),
        "samples": [round(value, 9) for value in rows],
    }


def _role_condition(plan_row: Mapping[str, Any]) -> str:
    level = int(plan_row["level"])
    role = str(plan_row.get("growth_role", ""))
    if level == 2 and role == "flower_wrap":
        return "secondary_flower_wrap"
    if level == 2 and plan_row.get("target_boundary"):
        return "secondary_frontier"
    if level == 2:
        return "secondary_lateral"
    if level == 3:
        return "tertiary_lateral"
    raise FixedVisualPriorError(f"unsupported descendant role: level={level}, role={role}")


def _primary_role(plan_row: Mapping[str, Any]) -> str:
    kind = str(plan_row["kind"])
    if kind == "free":
        return "primary_free"
    if kind == "balance":
        return "primary_balance"
    if kind == "flower":
        return "primary_flower"
    raise FixedVisualPriorError(f"unsupported primary kind: {kind}")


def _verify_frozen_baseline(baseline_root: Path) -> dict[str, Any]:
    manifest_path = baseline_root / "freeze_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("schema") != BASELINE_SCHEMA:
        raise FixedVisualPriorError("frozen baseline schema mismatch")
    if manifest.get("baseline_id") != "fixed_depth_7_12_2_v23":
        raise FixedVisualPriorError("unexpected fixed baseline id")
    if manifest.get("prototype_id") != "proto_sw_1_3":
        raise FixedVisualPriorError("fixed baseline prototype mismatch")
    if manifest.get("seeds") != [4101, 4102, 4103]:
        raise FixedVisualPriorError("fixed baseline seed inventory mismatch")
    comparison = manifest.get("comparison_contract")
    if not isinstance(comparison, Mapping):
        raise FixedVisualPriorError("fixed baseline comparison contract is missing")
    if comparison.get("cross_prototype_fixed_baseline_claimed") is not False:
        raise FixedVisualPriorError("fixed baseline incorrectly claims cross-prototype coverage")

    for row in manifest.get("files", []):
        if not isinstance(row, Mapping):
            raise FixedVisualPriorError("freeze manifest file row must be an object")
        path = baseline_root / str(row["frozen_path"])
        if not path.is_file():
            raise FixedVisualPriorError(f"frozen baseline file is missing: {path}")
        if path.stat().st_size != int(row["size_bytes"]):
            raise FixedVisualPriorError(f"frozen baseline size mismatch: {path}")
        if file_sha256(path) != row["sha256"]:
            raise FixedVisualPriorError(f"frozen baseline hash mismatch: {path}")
    return manifest


def build_fixed_visual_prior(
    baseline_root: Path,
    contract_path: Path,
) -> dict[str, Any]:
    """Validate the immutable baseline and extract its visual distributions."""

    contract = read_json(contract_path)
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise FixedVisualPriorError("fixed visual prior contract schema mismatch")
    manifest = _verify_frozen_baseline(baseline_root)

    profile = read_json(baseline_root / "input" / "skeleton_profile.json")
    repeat_x_range = profile.get("repeat_x_range")
    if not isinstance(repeat_x_range, list) or len(repeat_x_range) != 2:
        raise FixedVisualPriorError("baseline repeat_x_range is invalid")
    repeat_width = _finite(repeat_x_range[1], "repeat_x_range[1]") - _finite(
        repeat_x_range[0], "repeat_x_range[0]"
    )
    if repeat_width <= 0.0:
        raise FixedVisualPriorError("baseline repeat width must be positive")

    primary_features: dict[str, list[float]] = defaultdict(list)
    descendant_features: dict[str, list[float]] = defaultdict(list)
    curve_shape_features: dict[str, list[float]] = defaultdict(list)
    role_features: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    categorical: dict[str, Counter[str]] = defaultdict(Counter)
    root_gaps: list[float] = []
    unit_loads: list[float] = []
    raw_rows: list[dict[str, Any]] = []
    paired_primary_templates: dict[str, list[dict[str, Any]]] = {}

    expected_replay = manifest["expected_replay"]
    for seed in manifest["seeds"]:
        record = read_json(baseline_root / "outputs" / f"record_{seed}.json")
        result = record.get("result")
        if not isinstance(result, Mapping):
            raise FixedVisualPriorError(f"record {seed} has no result object")
        if result.get("schema") != "whole_local_hierarchy_result_v1":
            raise FixedVisualPriorError(f"record {seed} result schema mismatch")
        topology = result.get("topology")
        if topology != {
            "level_1": 7,
            "level_2": 12,
            "level_3": 2,
            "maximum_depth": 3,
        }:
            raise FixedVisualPriorError(f"record {seed} topology mismatch")
        if result.get("geometry_hash") != expected_replay[str(seed)]["geometry_hash"]:
            raise FixedVisualPriorError(f"record {seed} geometry hash mismatch")

        plan = result.get("plan")
        curves = result.get("curves")
        if not isinstance(plan, Mapping) or not isinstance(curves, list):
            raise FixedVisualPriorError(f"record {seed} plan/curves are invalid")
        primaries = plan.get("primaries")
        descendants = plan.get("descendants")
        if not isinstance(primaries, list) or len(primaries) != 7:
            raise FixedVisualPriorError(f"record {seed} primary inventory mismatch")
        if not isinstance(descendants, list) or len(descendants) != 14:
            raise FixedVisualPriorError(f"record {seed} descendant inventory mismatch")

        curve_by_id: dict[str, Mapping[str, Any]] = {}
        for curve_row in curves:
            if not isinstance(curve_row, Mapping) or not isinstance(curve_row.get("curve"), Mapping):
                raise FixedVisualPriorError(f"record {seed} contains an invalid curve row")
            curve_id = str(curve_row["curve_id"])
            if curve_id in curve_by_id:
                raise FixedVisualPriorError(f"record {seed} duplicates curve {curve_id}")
            curve_by_id[curve_id] = curve_row

        mounts = sorted(_finite(row["mount_s"], "primary.mount_s") for row in primaries)
        root_gaps.extend(mounts[index] - mounts[index - 1] for index in range(1, len(mounts)))
        child_counts = Counter(str(row["parent_id"]) for row in descendants)
        unit_loads.extend(1.0 + child_counts[str(row["curve_id"])] for row in primaries)
        paired_primary_templates[str(seed)] = []

        for primary in primaries:
            curve_id = str(primary["curve_id"])
            curve = curve_by_id[curve_id]["curve"]
            role = _primary_role(primary)
            chord = _finite(primary["chord_length"], f"{curve_id}.chord_length") / repeat_width
            actual = _finite(curve["actual_length"], f"{curve_id}.actual_length") / repeat_width
            values = {
                "chord_length_repeat": chord,
                "actual_length_repeat": actual,
                "actual_to_chord_ratio": actual / chord,
                "entry_opening_degrees": _finite(
                    primary["entry_opening_degrees"], f"{curve_id}.entry_opening_degrees"
                ),
                "start_arm_ratio": _finite(primary["start_arm_ratio"], f"{curve_id}.start_arm_ratio"),
                "end_arm_ratio": _finite(primary["end_arm_ratio"], f"{curve_id}.end_arm_ratio"),
                "mount_s": _finite(primary["mount_s"], f"{curve_id}.mount_s"),
                "tangent_weight": _finite(primary["tangent_weight"], f"{curve_id}.tangent_weight"),
                "normal_weight": _finite(primary["normal_weight"], f"{curve_id}.normal_weight"),
            }
            signed_turn, absolute_turn = _polyline_turn(curve["points"])
            values["signed_turn_degrees"] = signed_turn
            values["absolute_turn_degrees"] = absolute_turn
            for key, value in values.items():
                primary_features[key].append(value)
                role_features[role][key].append(value)
            categorical[f"{role}.bend_mode"][str(primary["bend_mode"])] += 1
            raw_rows.append(
                {
                    "seed": seed,
                    "curve_id": curve_id,
                    "level": 1,
                    "role_condition": role,
                    **{key: round(value, 9) for key, value in values.items()},
                }
            )
            paired_primary_templates[str(seed)].append(
                {
                    "curve_id": curve_id,
                    "kind": str(primary["kind"]),
                    "role_condition": role,
                    "mount_s": round(values["mount_s"], 9),
                    "target_flower_id": primary.get("target_flower_id"),
                    "cubics": [
                        {
                            key: [
                                round(_finite(cubic[key][0], f"{curve_id}.{key}[0]") / repeat_width, 9),
                                round(_finite(cubic[key][1], f"{curve_id}.{key}[1]") / repeat_width, 9),
                            ]
                            for key in ("p0", "p1", "p2", "p3")
                        }
                        for cubic in curve["cubics"]
                    ],
                    "centerline": [
                        [
                            round(_finite(point[0], f"{curve_id}.points.x") / repeat_width, 9),
                            round(_finite(point[1], f"{curve_id}.points.y") / repeat_width, 9),
                        ]
                        for point in curve["points"][:-1:4]
                    ]
                    + [
                        [
                            round(_finite(curve["points"][-1][0], f"{curve_id}.points[-1].x") / repeat_width, 9),
                            round(_finite(curve["points"][-1][1], f"{curve_id}.points[-1].y") / repeat_width, 9),
                        ]
                    ],
                }
            )

        for descendant in descendants:
            curve_id = str(descendant["curve_id"])
            parent_id = str(descendant["parent_id"])
            curve = curve_by_id[curve_id]["curve"]
            parent_curve = curve_by_id[parent_id]["curve"]
            role = _role_condition(descendant)
            chord = _finite(descendant["chord_length"], f"{curve_id}.chord_length") / repeat_width
            actual = _finite(curve["actual_length"], f"{curve_id}.actual_length") / repeat_width
            parent_actual = _finite(
                parent_curve["actual_length"], f"{parent_id}.actual_length"
            ) / repeat_width
            signed_turn, absolute_turn = _polyline_turn(curve["points"])
            values = {
                "chord_length_repeat": chord,
                "actual_length_repeat": actual,
                "actual_to_chord_ratio": actual / chord,
                "child_to_parent_actual_ratio": actual / parent_actual,
                "entry_opening_degrees": _finite(
                    descendant["entry_opening_degrees"],
                    f"{curve_id}.entry_opening_degrees",
                ),
                "exit_release_degrees": _finite(
                    descendant["exit_release_degrees"],
                    f"{curve_id}.exit_release_degrees",
                ),
                "handle_ratio": _finite(descendant["handle_ratio"], f"{curve_id}.handle_ratio"),
                "mount_fraction": _finite(
                    descendant["mount_fraction"], f"{curve_id}.mount_fraction"
                ),
                "signed_turn_degrees": signed_turn,
                "absolute_turn_degrees": absolute_turn,
            }
            for key, value in values.items():
                descendant_features[key].append(value)
                role_features[role][key].append(value)
            categorical[f"{role}.bend_mode"][str(descendant["bend_mode"])] += 1
            raw_rows.append(
                {
                    "seed": seed,
                    "curve_id": curve_id,
                    "level": int(descendant["level"]),
                    "role_condition": role,
                    **{key: round(value, 9) for key, value in values.items()},
                }
            )

        for curve_row in curves:
            curve = curve_row["curve"]
            points = [_point(point, "curve.points") for point in curve["points"]]
            chord = _distance(points[0], points[-1])
            actual = _finite(curve["actual_length"], "curve.actual_length")
            curve_shape_features["actual_to_endpoint_distance_ratio"].append(actual / chord)
            curve_shape_features["cubic_segment_count"].append(float(len(curve["cubics"])))

    statistical_groups = {
        "primary_geometry": {
            key: summarize(values) for key, values in sorted(primary_features.items())
        },
        "primary_root_rhythm": {
            "consecutive_mount_gap": summarize(root_gaps),
            "unit_load_curves_including_primary": summarize(unit_loads),
        },
        "descendant_geometry": {
            key: summarize(values) for key, values in sorted(descendant_features.items())
        },
        "curve_shape": {
            key: summarize(values) for key, values in sorted(curve_shape_features.items())
        },
        "role_conditioned": {
            role: {key: summarize(values) for key, values in sorted(features.items())}
            for role, features in sorted(role_features.items())
        },
    }
    categorical_groups = {
        key: dict(sorted(counter.items())) for key, counter in sorted(categorical.items())
    }

    prior: dict[str, Any] = {
        "schema": SCHEMA,
        "prior_id": "fixed_visual_prior_proto_sw_1_3_v23_v1",
        "paired_baseline_scope": {
            "baseline_id": manifest["baseline_id"],
            "prototype_id": manifest["prototype_id"],
            "seeds": manifest["seeds"],
            "topology": manifest["topology"],
            "cross_prototype_fixed_baseline_claimed": False,
            "final_pattern_aesthetics_claimed_by_source_gate": False,
        },
        "normalization": {
            "coordinate_system": "repeat_width_isotropic",
            "repeat_width_source_units": round(repeat_width, 9),
            "length_unit": "repeat_width",
            "angles_unit": "degrees",
        },
        "statistics": statistical_groups,
        "categorical_counts": categorical_groups,
        "raw_feature_rows": raw_rows,
        "paired_primary_templates": paired_primary_templates,
        "generation_use": {
            "fixed_topology_required": False,
            "role_conditioning_required": True,
            "independent_uniform_sampling_allowed": False,
            "paired_fixed_derived_candidate_required_for_proto_sw_1_3": True,
            "cross_prototype_use": "visual_distribution_prior_only",
        },
        "provenance": {
            "freeze_manifest_sha256": file_sha256(baseline_root / "freeze_manifest.json"),
            "contract_sha256": file_sha256(contract_path),
            "record_geometry_hashes": {
                seed: manifest["expected_replay"][str(seed)]["geometry_hash"]
                for seed in manifest["seeds"]
            },
        },
    }
    prior["prior_digest"] = canonical_digest(prior)
    return prior


def validate_fixed_visual_prior(prior: Mapping[str, Any]) -> None:
    if prior.get("schema") != SCHEMA:
        raise FixedVisualPriorError("fixed visual prior schema mismatch")
    digest = prior.get("prior_digest")
    if not isinstance(digest, str):
        raise FixedVisualPriorError("fixed visual prior digest is missing")
    payload = dict(prior)
    payload.pop("prior_digest")
    if canonical_digest(payload) != digest:
        raise FixedVisualPriorError("fixed visual prior digest mismatch")
    scope = prior["paired_baseline_scope"]
    if scope["prototype_id"] != "proto_sw_1_3":
        raise FixedVisualPriorError("fixed visual prior paired scope mismatch")
    if scope["cross_prototype_fixed_baseline_claimed"] is not False:
        raise FixedVisualPriorError("fixed visual prior makes an invalid cross-prototype claim")
    roles = set(prior["statistics"]["role_conditioned"])
    expected = {
        "primary_free",
        "primary_balance",
        "primary_flower",
        "secondary_lateral",
        "secondary_frontier",
        "secondary_flower_wrap",
        "tertiary_lateral",
    }
    if roles != expected:
        raise FixedVisualPriorError("fixed visual prior role inventory mismatch")
