#!/usr/bin/env python3
"""Prototype-family-conditioned flower binding before ordinary L1 planning.

The active morphology family decides whether flowers are supported from a
detected trough (SW-1), already belong to the main axis and need no support
curve (SW-2), or terminate a long remote tangent branch routed below the
flower (SW-3).  The resulting geometry is frozen before ordinary L1 candidate
generation so later branches consume, rather than constrain, the flower
relationship.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from prototype_strategy_v1 import validate_strategy_projection


Point = tuple[float, float]
SCHEMA = "dynamic_branch_flower_mount_plan_v2"
FAMILY_SW1 = "SW-1_valley_filling"
FAMILY_SW2 = "SW-2_axis_penetrating"
FAMILY_SW3 = "SW-3_tangent_terminal"
FAMILY_IDS = {FAMILY_SW1, FAMILY_SW2, FAMILY_SW3}

# Normalized carrier reaches measured from the two flower-primary curves kept
# in all saved proto_sw_1_3 editor sessions.  They are length evidence, not
# root coordinates or reusable curve templates.
EDITOR_SW1_CARRIER_REACH_PRIOR = (0.126, 0.219)
EDITOR_SW1_ROOT_TANGENT_ALIGNMENT = 0.682
# The saved SW1 editor examples use a single, one-sided bow for a long lateral
# carrier.  Scale its sag by the flower rather than storing prototype points.
EDITOR_SW1_LATERAL_ARC_SAG_SHARE = 0.35
SW1_SHARED_ROOT_MINIMUM_S_GAP = 0.06


class FlowerMountingError(RuntimeError):
    """The family-conditioned flower binding cannot be constructed safely."""


def _point(value: Sequence[float]) -> Point:
    return float(value[0]), float(value[1])


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(point: Point, scale: float) -> Point:
    return point[0] * scale, point[1] * scale


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _length(point: Point) -> float:
    return math.hypot(point[0], point[1])


def _distance(a: Point, b: Point) -> float:
    return _length(_sub(a, b))


def _unit(point: Point, label: str) -> Point:
    length = _length(point)
    if length <= 1e-12:
        raise FlowerMountingError(f"degenerate vector: {label}")
    return point[0] / length, point[1] / length


def _round_point(point: Point) -> list[float]:
    return [round(point[0], 9), round(point[1], 9)]


def _circular_distance(a: float, b: float) -> float:
    delta = abs((a - b) % 1.0)
    return min(delta, 1.0 - delta)


def _signed_circular_delta(value: float, origin: float) -> float:
    return (value - origin + 0.5) % 1.0 - 0.5


def _periodic_point_near(value: Sequence[float], reference_x: float) -> Point:
    point = _point(value)
    return point[0] + round(reference_x - point[0]), point[1]


def _cubic_point(segment: Mapping[str, Sequence[float]], t: float) -> Point:
    p0, p1, p2, p3 = (_point(segment[key]) for key in ("p0", "p1", "p2", "p3"))
    u = 1.0 - t
    return (
        u**3 * p0[0] + 3.0 * u * u * t * p1[0] + 3.0 * u * t * t * p2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3.0 * u * u * t * p1[1] + 3.0 * u * t * t * p2[1] + t**3 * p3[1],
    )


def _sample_segments(
    segments: Sequence[Mapping[str, Sequence[float]]],
    count: int = 40,
) -> list[Point]:
    points: list[Point] = []
    for segment_index, segment in enumerate(segments):
        sampled = [_cubic_point(segment, index / count) for index in range(count + 1)]
        points.extend(sampled if segment_index == 0 else sampled[1:])
    return points


def _polyline_length(points: Sequence[Point]) -> float:
    return sum(_distance(a, b) for a, b in zip(points, points[1:]))


def _nearest_sample(analysis: Mapping[str, Any], s: float) -> Mapping[str, Any]:
    return min(
        analysis["backbone"]["samples"],
        key=lambda row: _circular_distance(float(row["s"]), s),
    )


def _flower_center_near(flower: Mapping[str, Any], reference_x: float) -> Point:
    center = _point(flower["center"])
    return center[0] + round(reference_x - center[0]), center[1]


def _flower_boundary_toward(
    flower: Mapping[str, Any],
    root: Point,
) -> tuple[Point, Point]:
    center = _flower_center_near(flower, root[0])
    rx = float(flower["rx"])
    ry = float(flower["ry"])
    vector = _sub(root, center)
    denominator = math.sqrt((vector[0] / rx) ** 2 + (vector[1] / ry) ** 2)
    if denominator <= 1.0:
        raise FlowerMountingError("flower reserve overlaps a candidate support root")
    return _add(center, _mul(vector, 1.0 / denominator)), center


def _flower_lower_contact(
    flower: Mapping[str, Any],
    reference_x: float,
) -> tuple[Point, Point]:
    """Return the flower-bottom contact used by SW-1 support stems.

    Saved editor examples place the visible support at the lower flower pole;
    the carrier may travel sideways from a valley flank, but it must finish by
    rising into the flower rather than sticking into a lateral boundary.
    """
    center = _flower_center_near(flower, reference_x)
    return (center[0], center[1] + float(flower["ry"])), center


def _hermite_segment(
    start: Point,
    end: Point,
    start_direction: Point,
    end_direction: Point,
    start_arm: float,
    end_arm: float,
) -> dict[str, list[float]]:
    return {
        "p0": _round_point(start),
        "p1": _round_point(_add(start, _mul(_unit(start_direction, "start tangent"), start_arm))),
        "p2": _round_point(_sub(end, _mul(_unit(end_direction, "end tangent"), end_arm))),
        "p3": _round_point(end),
    }


def _family_id(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
) -> str:
    prototype_id = str(analysis["prototype_id"])
    classification = morphology.get("classification")
    if isinstance(classification, Mapping):
        relation = classification.get("flower_branch_relation")
        family_id = (
            str(relation.get("family_id"))
            if isinstance(relation, Mapping)
            else ""
        )
    else:
        instance = morphology.get("instances", {}).get(prototype_id)
        family_id = (
            str(instance.get("family_id"))
            if isinstance(instance, Mapping)
            else ""
        )
    if family_id not in FAMILY_IDS:
        raise FlowerMountingError(
            f"morphology family is missing or unsupported: {prototype_id}"
        )
    return family_id


def _target_reaches(count: int) -> list[float]:
    if count <= 0:
        return []
    if count == 1:
        return [sum(EDITOR_SW1_CARRIER_REACH_PRIOR) * 0.5]
    lower, upper = EDITOR_SW1_CARRIER_REACH_PRIOR
    return [lower + (upper - lower) * index / (count - 1) for index in range(count)]


def _sw1_root_rows(
    analysis: Mapping[str, Any],
) -> list[
    tuple[
        Mapping[str, Any],
        list[tuple[float, Mapping[str, Any], float]],
        float,
        float,
    ]
]:
    troughs = [row for row in analysis["backbone"]["extrema"] if row["kind"] == "trough"]
    peaks = [row for row in analysis["backbone"]["extrema"] if row["kind"] == "peak"]
    if not troughs:
        raise FlowerMountingError("SW-1 requires a detected trough")

    assignments: list[tuple[Mapping[str, Any], Mapping[str, Any], Point, float]] = []
    for flower in analysis["flowers"]:
        center = _point(flower["center"])
        candidates: list[tuple[float, Mapping[str, Any], Point]] = []
        for trough in troughs:
            # SW-1 is a within-repeat valley composition.  Do not replace the
            # registered valley with a spatially nearer neighboring copy.
            point = _point(trough["point"])
            candidates.append((_distance(point, center), trough, point))
        _, trough, trough_point = min(candidates, key=lambda row: row[0])
        assignments.append((flower, trough, trough_point, abs(center[0] - trough_point[0])))

    rows: list[
        tuple[
            Mapping[str, Any],
            list[tuple[float, Mapping[str, Any], float]],
            float,
            float,
        ]
    ] = []
    by_trough: dict[float, list[tuple[Mapping[str, Any], Mapping[str, Any], Point, float]]] = {}
    for assignment in assignments:
        by_trough.setdefault(float(assignment[1]["s"]), []).append(assignment)
    for trough_s, group in by_trough.items():
        group.sort(key=lambda row: row[3])
        reaches = _target_reaches(len(group))
        for (flower, trough, trough_point, _), target_reach in zip(group, reaches):
            center = _point(flower["center"])
            horizontal_delta = center[0] - trough_point[0]
            direction_sign = 1.0 if horizontal_delta >= 0.0 else -1.0
            peak_distances = [
                direction_sign * _signed_circular_delta(float(peak["s"]), trough_s)
                for peak in peaks
                if direction_sign * _signed_circular_delta(float(peak["s"]), trough_s) > 0.0
            ]
            flank_extent = min(peak_distances, default=0.5)
            candidates: list[tuple[float, Mapping[str, Any], float]] = []
            for sample in analysis["backbone"]["samples"]:
                signed = direction_sign * _signed_circular_delta(float(sample["s"]), trough_s)
                if signed < -1e-9 or signed > flank_extent + 1e-9:
                    continue
                root = _periodic_point_near(sample["point"], center[0])
                contact, _ = _flower_lower_contact(flower, root[0])
                # A valley support must approach the flower from below.  The
                # old center-only check admitted roots beside the flower and
                # produced the pinched lateral V visible in proto_sw_1_1.
                if root[1] + 1e-9 < contact[1]:
                    continue
                reach = _distance(root, contact)
                under_flower_offset = abs(root[0] - contact[0])
                cost = (
                    abs(reach - target_reach)
                    + under_flower_offset * 0.08
                    + signed * 0.015
                )
                candidates.append((cost, sample, reach))
            if not candidates:
                raise FlowerMountingError(f"no trough/flank support root: {flower['flower_id']}")
            candidates.sort(key=lambda row: (row[0], float(row[1]["s"])))
            rows.append((flower, candidates, target_reach, trough_s))
    return rows


def _mount_record(
    analysis: Mapping[str, Any],
    flower: Mapping[str, Any],
    family_id: str,
    root_s: float,
    root: Point,
    center: Point,
    target: Point,
    tangent: Point,
    segments: Sequence[Mapping[str, Sequence[float]]],
    source_relation: str,
    route: Mapping[str, Any],
) -> dict[str, Any]:
    centerline = _sample_segments(segments)
    rx = float(flower["rx"])
    ry = float(flower["ry"])
    terminal_direction = _unit(_sub(center, target), "flower terminal normal")
    ellipse_values = [
        ((point[0] - center[0]) / rx) ** 2 + ((point[1] - center[1]) / ry) ** 2
        for point in centerline[:-1]
    ]
    flower_id = str(flower["flower_id"])
    return {
        "mount_id": f'{analysis["prototype_id"]}__{flower_id}__flower_support',
        "flower_id": flower_id,
        "morphology_family": family_id,
        "semantic_role": "flower_support_stem",
        "source_relation": source_relation,
        "root_s": round(root_s, 9),
        "root": _round_point(root),
        "root_tangent": _round_point(tangent),
        "flower_center_periodic": _round_point(center),
        "flower_rx": round(rx, 9),
        "flower_ry": round(ry, 9),
        "contact_point": _round_point(target),
        "contact_normal": _round_point(terminal_direction),
        "cubic_segments": list(segments),
        "centerline": [_round_point(point) for point in centerline],
        "route": dict(route),
        "geometry": {
            "root_to_contact_chord": round(_distance(root, target), 9),
            "curve_length": round(_polyline_length(centerline), 9),
            "minimum_precontact_ellipse_value": round(min(ellipse_values), 9),
        },
    }


def _sw1_departure_direction(tangent: Point, chord_direction: Point) -> Point:
    if _dot(tangent, chord_direction) < 0.0:
        tangent = _mul(tangent, -1.0)
    perpendicular = _sub(chord_direction, _mul(tangent, _dot(tangent, chord_direction)))
    perpendicular = _unit(perpendicular, "SW-1 departure side")
    normal_weight = math.sqrt(1.0 - EDITOR_SW1_ROOT_TANGENT_ALIGNMENT**2)
    return _unit(
        _add(
            _mul(tangent, EDITOR_SW1_ROOT_TANGENT_ALIGNMENT),
            _mul(perpendicular, normal_weight),
        ),
        "SW-1 editor-conditioned departure",
    )


def _build_sw1_mount_candidate(
    analysis: Mapping[str, Any],
    flower: Mapping[str, Any],
    sample: Mapping[str, Any],
    target_reach: float,
    trough_s: float,
    candidate_rank: int,
) -> dict[str, Any]:
    center = _point(flower["center"])
    root = _periodic_point_near(sample["point"], center[0])
    target, center = _flower_lower_contact(flower, root[0])
    chord = _sub(target, root)
    chord_length = _length(chord)
    chord_direction = _unit(chord, "SW-1 carrier chord")
    parent_tangent = _unit(_point(sample["tangent"]), "SW-1 backbone tangent")
    departure = _sw1_departure_direction(parent_tangent, chord_direction)
    terminal = _unit(_sub(center, target), "SW-1 flower normal")
    horizontal_run = abs(chord[0])
    lateral_carrier = horizontal_run > max(abs(chord[1]), float(flower["rx"]))
    if lateral_carrier:
        # Keep both controls on the lower side of the root-to-flower chord.
        # This produces one continuous bow with no intermediate inflection or
        # waypoint kink, while retaining an upward terminal at the flower.
        arc_normal = (-chord_direction[1], chord_direction[0])
        if arc_normal[1] < 0.0:
            arc_normal = _mul(arc_normal, -1.0)
        sag = min(horizontal_run, float(flower["ry"])) * EDITOR_SW1_LATERAL_ARC_SAG_SHARE
        first_control = _add(
            _add(root, _mul(chord, 0.38)),
            _mul(arc_normal, sag),
        )
        second_control = _sub(target, _mul(terminal, sag))
        segments = [
            {
                "p0": _round_point(root),
                "p1": _round_point(first_control),
                "p2": _round_point(second_control),
                "p3": _round_point(target),
            }
        ]
        carrier_geometry = "single_one_sided_lateral_arc"
    else:
        segments = [
            _hermite_segment(
                root,
                target,
                departure,
                terminal,
                chord_length * 0.47,
                chord_length * 0.26,
            )
        ]
        carrier_geometry = "direct_terminal_rise"
    return _mount_record(
        analysis,
        flower,
        FAMILY_SW1,
        float(sample["s"]),
        root,
        center,
        target,
        parent_tangent,
        segments,
        "detected_trough_or_flank_to_lower_flower_contact",
        {
            "origin_kind": "wave_trough_support",
            "detected_trough_s": round(trough_s, 9),
            "editor_reach_target": round(target_reach, 9),
            "editor_root_tangent_alignment": EDITOR_SW1_ROOT_TANGENT_ALIGNMENT,
            "carrier_geometry": carrier_geometry,
            "feasible_candidate_rank": candidate_rank,
            "contact_side": "lower_flower_pole_from_below",
        },
    )


def _mount_conflicts(
    mount: Mapping[str, Any],
    analysis: Mapping[str, Any],
    accepted: Sequence[Mapping[str, Any]],
) -> bool:
    points = [_point(value) for value in mount["centerline"]]
    backbone = [_point(row["point"]) for row in analysis["backbone"]["samples"]]
    if any(
        _proper_polyline_crossings(points, _shift(backbone, offset))
        for offset in (-1.0, 0.0, 1.0)
    ):
        return True
    return any(
        _proper_polyline_crossings(
            points,
            _shift([_point(value) for value in other["centerline"]], offset),
        )
        for other in accepted
        for offset in (-1.0, 0.0, 1.0)
    )


def _build_sw1_mounts(
    analysis: Mapping[str, Any],
) -> list[dict[str, Any]]:
    mounts: list[dict[str, Any]] = []
    for flower, candidates, target_reach, trough_s in _sw1_root_rows(analysis):
        selected_mount: dict[str, Any] | None = None
        for candidate_rank, (_, sample, _) in enumerate(candidates, start=1):
            if any(
                _circular_distance(float(sample["s"]), float(accepted["root_s"]))
                < SW1_SHARED_ROOT_MINIMUM_S_GAP
                for accepted in mounts
            ):
                continue
            candidate = _build_sw1_mount_candidate(
                analysis,
                flower,
                sample,
                target_reach,
                trough_s,
                candidate_rank,
            )
            if not _mount_conflicts(candidate, analysis, mounts):
                selected_mount = candidate
                break
        if selected_mount is None:
            raise FlowerMountingError(
                f"no conflict-free trough support: {flower['flower_id']}"
            )
        mounts.append(selected_mount)
    return mounts


def _build_sw3_mounts(
    analysis: Mapping[str, Any],
    stage3_contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    policy = stage3_contract["initial_layout_constraints"]["sw3_remote_terminal_support"]
    minimum_arc = float(policy["minimum_arc_distance_from_nearest_flower_mount"])
    maximum_arc = float(policy["maximum_arc_distance_from_nearest_flower_mount"])
    preferred_arc = float(policy["preferred_arc_distance"])
    below_margin = float(policy["minimum_below_flower_corridor_margin"])
    mounts: list[dict[str, Any]] = []
    for flower in analysis["flowers"]:
        center_base = _point(flower["center"])
        nearest_s = float(flower["nearest_backbone_s"])
        candidates: list[tuple[float, Mapping[str, Any], Point, Point, Point]] = []
        for sample in analysis["backbone"]["samples"]:
            root_s = float(sample["s"])
            arc_distance = _circular_distance(root_s, nearest_s)
            if not minimum_arc <= arc_distance <= maximum_arc:
                continue
            root = _periodic_point_near(sample["point"], center_base[0])
            center = _flower_center_near(flower, root[0])
            if root[1] <= center[1]:
                continue
            contact = center[0], center[1] + float(flower["ry"])
            side = -1.0 if root[0] <= contact[0] else 1.0
            horizontal_offset = float(flower["protection_rx"]) * 0.35
            waypoint = (
                contact[0] + side * horizontal_offset,
                center[1] + float(flower["protection_ry"]) + below_margin,
            )
            tangent = _unit(_point(sample["tangent"]), "SW-3 parent tangent")
            toward_waypoint = _unit(_sub(waypoint, root), "SW-3 tangent reach")
            if _dot(tangent, toward_waypoint) < 0.0:
                tangent = _mul(tangent, -1.0)
            tangent_alignment = _dot(tangent, toward_waypoint)
            cost = abs(arc_distance - preferred_arc) - tangent_alignment * 0.08
            candidates.append((cost, sample, root, center, waypoint))
        if not candidates:
            raise FlowerMountingError(f"no remote tangent support root: {flower['flower_id']}")
        candidates.sort(key=lambda row: (row[0], float(row[1]["s"])))
        selected_mount: dict[str, Any] | None = None
        for candidate_rank, (_, sample, root, center, waypoint) in enumerate(
            candidates,
            start=1,
        ):
            contact = center[0], center[1] + float(flower["ry"])
            tangent = _unit(_point(sample["tangent"]), "SW-3 parent tangent")
            toward_waypoint = _unit(_sub(waypoint, root), "SW-3 first reach")
            if _dot(tangent, toward_waypoint) < 0.0:
                tangent = _mul(tangent, -1.0)
            join_direction = _unit(_sub(contact, waypoint), "SW-3 fold direction")
            terminal = _unit(_sub(center, contact), "SW-3 flower underside normal")
            first_chord = _distance(root, waypoint)
            second_chord = _distance(waypoint, contact)
            segments = [
                _hermite_segment(
                    root,
                    waypoint,
                    tangent,
                    join_direction,
                    first_chord * 0.34,
                    first_chord * 0.20,
                ),
                _hermite_segment(
                    waypoint,
                    contact,
                    join_direction,
                    terminal,
                    second_chord * 0.34,
                    second_chord * 0.28,
                ),
            ]
            candidate = _mount_record(
                analysis,
                flower,
                FAMILY_SW3,
                float(sample["s"]),
                root,
                center,
                contact,
                tangent,
                segments,
                "remote_long_slope_tangent_corridor_to_flower_underside",
                {
                    "origin_kind": "remote_tangent_extension",
                    "nearest_flower_s": round(float(flower["nearest_backbone_s"]), 9),
                    "arc_distance": round(
                        _circular_distance(float(sample["s"]), float(flower["nearest_backbone_s"])),
                        9,
                    ),
                    "under_flower_waypoint": _round_point(waypoint),
                    "contact_side": "underside",
                    "near_flower_stub_allowed": False,
                    "feasible_candidate_rank": candidate_rank,
                },
            )
            if not _mount_conflicts(candidate, analysis, mounts):
                selected_mount = candidate
                break
        if selected_mount is None:
            raise FlowerMountingError(
                f"no conflict-free remote tangent support: {flower['flower_id']}"
            )
        mounts.append(selected_mount)
    return mounts


def _proper_segment_intersection(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    ab0 = _cross(_sub(a1, a0), _sub(b0, a0))
    ab1 = _cross(_sub(a1, a0), _sub(b1, a0))
    ba0 = _cross(_sub(b1, b0), _sub(a0, b0))
    ba1 = _cross(_sub(b1, b0), _sub(a1, b0))
    epsilon = 1e-10
    return (
        ((ab0 > epsilon and ab1 < -epsilon) or (ab0 < -epsilon and ab1 > epsilon))
        and ((ba0 > epsilon and ba1 < -epsilon) or (ba0 < -epsilon and ba1 > epsilon))
    )


def _proper_polyline_crossings(a: Sequence[Point], b: Sequence[Point]) -> int:
    return sum(
        1
        for a0, a1 in zip(a, a[1:])
        for b0, b1 in zip(b, b[1:])
        if _proper_segment_intersection(a0, a1, b0, b1)
    )


def _shift(points: Sequence[Point], offset: float) -> list[Point]:
    return [(point[0] + offset, point[1]) for point in points]


def _axis_flower_integration(
    analysis: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Measure whether the periodic backbone actually passes through each flower."""

    backbone = [_point(row["point"]) for row in analysis["backbone"]["samples"]]
    extended = [
        _shift(backbone, offset)
        for offset in (-1.0, 0.0, 1.0)
    ]
    rows: list[dict[str, Any]] = []
    for flower in analysis["flowers"]:
        center = _point(flower["center"])
        rx = float(flower["rx"])
        ry = float(flower["ry"])
        minimum_radius = math.inf
        crossings: list[Point] = []
        for polyline in extended:
            for first, second in zip(polyline, polyline[1:]):
                p0 = ((first[0] - center[0]) / rx, (first[1] - center[1]) / ry)
                p1 = ((second[0] - center[0]) / rx, (second[1] - center[1]) / ry)
                direction = _sub(p1, p0)
                length_squared = _dot(direction, direction)
                if length_squared <= 1e-16:
                    projection = 0.0
                else:
                    projection = max(
                        0.0,
                        min(1.0, -_dot(p0, direction) / length_squared),
                    )
                nearest = _add(p0, _mul(direction, projection))
                minimum_radius = min(minimum_radius, _length(nearest))

                quadratic_b = 2.0 * _dot(p0, direction)
                quadratic_c = _dot(p0, p0) - 1.0
                discriminant = quadratic_b * quadratic_b - 4.0 * length_squared * quadratic_c
                if length_squared <= 1e-16 or discriminant < -1e-12:
                    continue
                root = math.sqrt(max(0.0, discriminant))
                for value in (
                    (-quadratic_b - root) / (2.0 * length_squared),
                    (-quadratic_b + root) / (2.0 * length_squared),
                ):
                    if -1e-9 <= value <= 1.0 + 1e-9:
                        point = _add(first, _mul(_sub(second, first), max(0.0, min(1.0, value))))
                        if all(_distance(point, prior) > 1e-7 for prior in crossings):
                            crossings.append(point)
        rows.append(
            {
                "flower_id": str(flower["flower_id"]),
                "minimum_normalized_axis_distance": round(minimum_radius, 12),
                "axis_boundary_crossing_count": len(crossings),
                "axis_penetrates_flower": minimum_radius < 1.0 - 1e-7 and len(crossings) >= 2,
            }
        )
    return rows


def _mechanical_checks(
    plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    backbone = [_point(row["point"]) for row in analysis["backbone"]["samples"]]
    mounts = [[_point(point) for point in row["centerline"]] for row in plan["mounts"]]
    backbone_crossings = 0
    mount_crossings = 0
    for mount in mounts:
        for mount_offset in (-1.0, 0.0, 1.0):
            shifted_mount = _shift(mount, mount_offset)
            for structure_offset in (-2.0, -1.0, 0.0, 1.0, 2.0):
                backbone_crossings += _proper_polyline_crossings(shifted_mount, _shift(backbone, structure_offset))
    for first_index, first in enumerate(mounts):
        for second_index, second in enumerate(mounts):
            for offset in (-1.0, 0.0, 1.0):
                if second_index < first_index or (second_index == first_index and offset <= 0.0):
                    continue
                mount_crossings += _proper_polyline_crossings(first, _shift(second, offset))

    endpoint_errors: list[float] = []
    reserve_intrusions = 0
    for mount in plan["mounts"]:
        center = _point(mount["flower_center_periodic"])
        rx = float(mount["flower_rx"])
        ry = float(mount["flower_ry"])
        contact = _point(mount["contact_point"])
        ellipse_value = ((contact[0] - center[0]) / rx) ** 2 + ((contact[1] - center[1]) / ry) ** 2
        endpoint_errors.append(abs(ellipse_value - 1.0))
        for point in [_point(value) for value in mount["centerline"][:-1]]:
            value = ((point[0] - center[0]) / rx) ** 2 + ((point[1] - center[1]) / ry) ** 2
            if value < 1.0 - 2e-6:
                reserve_intrusions += 1
    axis_integration = (
        _axis_flower_integration(analysis)
        if plan["flower_mount_mechanism"] == "axis_integration"
        else []
    )
    return {
        "flower_count": len(analysis["flowers"]),
        "expected_mount_count": int(plan["expected_mount_count"]),
        "mount_count": len(mounts),
        "backbone_proper_crossing_count": backbone_crossings,
        "periodic_mount_proper_crossing_count": mount_crossings,
        "flower_reserve_precontact_intrusion_count": reserve_intrusions,
        "maximum_contact_ellipse_error": round(max(endpoint_errors, default=0.0), 12),
        "axis_flower_integration": axis_integration,
    }


def build_flower_mount_plan(
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    stage3_contract: Mapping[str, Any],
    *,
    seed: int,
    prototype_strategy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the family-specific flower relation before ordinary L1 planning."""

    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**32 - 1:
        raise FlowerMountingError("flower mounting seed must be a non-negative 32-bit integer")
    morphology_family = _family_id(analysis, morphology)
    if prototype_strategy is None:
        family_id = morphology_family
        mount_mechanism = {
            FAMILY_SW1: "valley_flank_support",
            FAMILY_SW2: "axis_integration",
            FAMILY_SW3: "remote_tangent_underside",
        }[family_id]
        binding = {
            FAMILY_SW1: "trough_or_valley_flank_support",
            FAMILY_SW2: "flower_is_part_of_continuous_main_axis",
            FAMILY_SW3: "remote_tangent_extension_to_flower_underside",
        }[family_id]
    else:
        validate_strategy_projection(
            prototype_strategy,
            prototype_id=str(analysis["prototype_id"]),
            family_id=morphology_family,
            flower_count=len(analysis["flowers"]),
        )
        family_id = str(prototype_strategy["family_id"])
        mount_policy = prototype_strategy["flower_mount"]
        mount_mechanism = str(mount_policy["mechanism"])
        binding = str(mount_policy["binding"])

    if mount_mechanism == "valley_flank_support":
        mounts = _build_sw1_mounts(analysis)
        expected_mount_count = len(analysis["flowers"])
    elif mount_mechanism == "authored_svg_carriers":
        from authored_svg_prototype import build_authored_mounts
        mounts = build_authored_mounts(analysis, prototype_strategy)
        expected_mount_count = len(analysis["flowers"])
    elif mount_mechanism == "axis_integration":
        mounts = []
        expected_mount_count = 0
    elif mount_mechanism == "remote_tangent_underside":
        mounts = _build_sw3_mounts(analysis, stage3_contract)
        expected_mount_count = len(analysis["flowers"])
    else:
        raise FlowerMountingError(
            f"unsupported flower mount strategy: {mount_mechanism}"
        )

    plan: dict[str, Any] = {
        "schema": SCHEMA,
        "plan_id": f'{analysis["prototype_id"]}__seed_{seed}__flower_mount_first_v1',
        "prototype_id": str(analysis["prototype_id"]),
        "seed": seed,
        "morphology_family": family_id,
        "prototype_strategy": (
            dict(prototype_strategy) if prototype_strategy is not None else None
        ),
        "flower_mount_mechanism": mount_mechanism,
        "flower_binding": binding,
        "expected_mount_count": expected_mount_count,
        "source_stage": "variant_analysis_before_ordinary_l1",
        "source_stage3_contract_schema": str(stage3_contract["schema"]),
        "mount_policy": {
            "nearest_backbone_short_stub_used": False,
            "prototype_family_and_flower_position_control_root": True,
            "sw1_root_source": ("author_svg_attachment" if mount_mechanism == "authored_svg_carriers" else "detected_trough_and_flower_conditioned_valley_flank"),
            "sw1_distinct_flower_growth_roots": mount_mechanism != "authored_svg_carriers",
            "sw1_minimum_flower_root_s_gap": (None if mount_mechanism == "authored_svg_carriers" else SW1_SHARED_ROOT_MINIMUM_S_GAP),
            "sw2_support_curve_policy": "none_axis_integration",
            "sw3_root_source": "remote_long_slope_or_tangent_corridor",
            "ordinary_l1_present_during_mount_selection": False,
            "mounts_frozen_before_ordinary_l1": True,
            "best_of_n_visual_ranking_used": False,
        },
        "mounts": mounts,
        "review_gate": {
            "status": "family_conditioned_flower_binding_pending_visual_review",
            "numeric_checks_cannot_auto_approve_visual_gate": True,
        },
    }
    plan["mechanical_checks"] = _mechanical_checks(plan, analysis)
    validate_flower_mount_plan(
        plan,
        analysis,
        morphology,
        prototype_strategy=prototype_strategy,
    )
    return plan


def validate_flower_mount_plan(
    plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
    *,
    prototype_strategy: Mapping[str, Any] | None = None,
) -> None:
    """Recompute active-path constraints without trusting stored status fields."""

    if plan.get("schema") != SCHEMA:
        raise FlowerMountingError("flower mount plan schema mismatch")
    if plan.get("prototype_id") != analysis.get("prototype_id"):
        raise FlowerMountingError("flower mount plan/analysis mismatch")
    morphology_family = _family_id(analysis, morphology)
    if plan.get("morphology_family") != morphology_family:
        raise FlowerMountingError("flower mount morphology family mismatch")
    frozen_strategy = plan.get("prototype_strategy")
    if prototype_strategy is not None:
        validate_strategy_projection(
            prototype_strategy,
            prototype_id=str(analysis["prototype_id"]),
            family_id=morphology_family,
            flower_count=len(analysis["flowers"]),
        )
        if frozen_strategy != prototype_strategy:
            raise FlowerMountingError("flower mount strategy projection mismatch")
        if plan.get("flower_mount_mechanism") != prototype_strategy[
            "flower_mount"
        ]["mechanism"]:
            raise FlowerMountingError("flower mount mechanism mismatch")
    elif frozen_strategy is not None:
        validate_strategy_projection(
            frozen_strategy,
            prototype_id=str(analysis["prototype_id"]),
            family_id=morphology_family,
            flower_count=len(analysis["flowers"]),
        )
    if plan.get("mount_policy", {}).get("mounts_frozen_before_ordinary_l1") is not True:
        raise FlowerMountingError("flower mounts were not frozen before ordinary L1")
    recomputed = _mechanical_checks(plan, analysis)
    if recomputed != plan.get("mechanical_checks"):
        raise FlowerMountingError("stored flower mount checks do not match geometry")
    if recomputed["mount_count"] != recomputed["expected_mount_count"]:
        raise FlowerMountingError("family-specific flower mount count mismatch")
    for key in (
        "backbone_proper_crossing_count",
        "periodic_mount_proper_crossing_count",
        "flower_reserve_precontact_intrusion_count",
    ):
        if int(recomputed[key]) != 0:
            raise FlowerMountingError(f"flower mount validation failed: {key}")
    if float(recomputed["maximum_contact_ellipse_error"]) > 2e-7:
        raise FlowerMountingError("flower mount endpoint misses ellipse")
    if plan["flower_mount_mechanism"] == "valley_flank_support":
        root_values = [float(row["root_s"]) for row in plan["mounts"]]
        if any(
            _circular_distance(first, second) < SW1_SHARED_ROOT_MINIMUM_S_GAP
            for first_index, first in enumerate(root_values)
            for second_index, second in enumerate(root_values)
            if second_index > first_index
        ):
            raise FlowerMountingError(
                "SW-1 flower carriers share an over-concentrated growth root"
            )
    if plan["flower_mount_mechanism"] == "axis_integration":
        failed = [
            row["flower_id"]
            for row in recomputed["axis_flower_integration"]
            if not row["axis_penetrates_flower"]
        ]
        if failed:
            raise FlowerMountingError(
                "SW-2 flowers are not integrated into the continuous main axis: "
                + ", ".join(failed)
            )
