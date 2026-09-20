#!/usr/bin/env python3
"""PrototypeAnalysis derived only from StrictP0 v2 geometry.

The analyzer is deliberately planner-free. It reports periodic free space,
backbone landmarks, flower relations, crowded/prohibited regions, and possible
L1 attachment intervals without choosing a topology or compiling curves.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from strict_p0_v2 import Point, ProtectionZone, StrictP0V2


SCHEMA = "dynamic_branch_prototype_analysis_v1"
POLICY_ID = "strict_p0_periodic_space_analysis_v1"
REVIEW_STATES = (
    "analysis_pending_review",
    "analysis_approved",
    "analysis_needs_revision",
    "analysis_rejected",
)
PROBE_STEP = 0.00625
MAX_PROBE_CLEARANCE = 0.38
BLANK_CLEARANCE = 0.105
L1_CLEARANCE = 0.14
CROWDED_CLEARANCE = 0.065
BACKBONE_CLEARANCE = 0.022
FLOWER_PADDING = 1.12
MIN_REGION_SPAN = 0.04


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _round(value: float, digits: int = 9) -> float:
    result = round(float(value), digits)
    return 0.0 if result == -0.0 else result


def _round_point(point: Point) -> list[float]:
    return [_round(point[0]), _round(point[1])]


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _sub(a: Point, b: Point) -> Point:
    return a[0] - b[0], a[1] - b[1]


def _mul(a: Point, scale: float) -> Point:
    return a[0] * scale, a[1] * scale


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _length(a: Point) -> float:
    return math.hypot(a[0], a[1])


def _distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(a: Point) -> Point:
    length = _length(a)
    return (1.0, 0.0) if length <= 1e-12 else (a[0] / length, a[1] / length)


def _normal(tangent: Point) -> Point:
    return -tangent[1], tangent[0]


def _angle_degrees(a: Point, b: Point) -> float:
    first = _unit(a)
    second = _unit(b)
    return math.degrees(math.atan2(_cross(first, second), _dot(first, second)))


def _circular_s_distance(a: float, b: float) -> float:
    delta = abs(a - b)
    return min(delta, 1.0 - delta)


def _point_segment_distance(point: Point, start: Point, end: Point) -> float:
    segment = _sub(end, start)
    denominator = _dot(segment, segment)
    if denominator <= 1e-18:
        return _distance(point, start)
    t = max(0.0, min(1.0, _dot(_sub(point, start), segment) / denominator))
    return _distance(point, _add(start, _mul(segment, t)))


def _point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    inside = False
    x, y = point
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        intersects = (y1 > y) != (y2 > y) and x < (
            (x2 - x1) * (y - y1) / (y2 - y1) + x1
        )
        if intersects:
            inside = not inside
        previous = current
    return inside


def _inside_zone(point: Point, zone: ProtectionZone, offset: int) -> bool:
    shifted = (point[0] - offset, point[1])
    if zone.geometry_type == "ellipse":
        assert zone.center is not None and zone.rx is not None and zone.ry is not None
        dx = (shifted[0] - zone.center[0]) / max(zone.rx, 1e-12)
        dy = (shifted[1] - zone.center[1]) / max(zone.ry, 1e-12)
        return dx * dx + dy * dy <= 1.0
    return _point_in_polygon(shifted, zone.points)


def _inside_flower(point: Point, flower: Any, offset: int, padding: float) -> bool:
    cx = flower.center[0] + offset
    cy = flower.center[1]
    dx = (point[0] - cx) / max(flower.rx * padding, 1e-12)
    dy = (point[1] - cy) / max(flower.ry * padding, 1e-12)
    return dx * dx + dy * dy <= 1.0


def _backbone_hit(
    point: Point,
    *,
    root_s: float,
    samples: Sequence[Any],
) -> bool:
    for first, second in zip(samples, samples[1:]):
        mid_s = 0.5 * (float(first.s) + float(second.s))
        if _circular_s_distance(root_s, mid_s) < 0.06:
            continue
        for offset in (-1, 0, 1):
            start = (first.point[0] + offset, first.point[1])
            end = (second.point[0] + offset, second.point[1])
            if _point_segment_distance(point, start, end) < BACKBONE_CLEARANCE:
                return True
    return False


def _nearest_flower(
    point: Point,
    flowers: Sequence[Any],
) -> tuple[str | None, Point | None, float]:
    best: tuple[float, str, Point] | None = None
    for flower in flowers:
        for offset in (-1, 0, 1):
            center = (flower.center[0] + offset, flower.center[1])
            distance = _distance(point, center)
            if best is None or distance < best[0]:
                best = (distance, flower.flower_id, center)
    if best is None:
        return None, None, math.inf
    return best[1], best[2], best[0]


def _ray_clearance(
    p0: StrictP0V2,
    *,
    root_index: int,
    direction: Point,
) -> tuple[float, str, Point]:
    sample = p0.backbone_samples[root_index]
    root = sample.point
    canvas_height = p0.frame.local_canvas_bounds[3]
    distance = 0.025
    while distance <= MAX_PROBE_CLEARANCE + 1e-12:
        point = _add(root, _mul(direction, distance))
        if point[1] <= 0.012 or point[1] >= canvas_height - 0.012:
            return max(0.0, distance - PROBE_STEP), "canvas_vertical_boundary", point
        for flower in p0.flowers:
            if any(
                _inside_flower(point, flower, offset, FLOWER_PADDING)
                for offset in (-1, 0, 1)
            ):
                return max(0.0, distance - PROBE_STEP), "flower_reserve", point
        for zone in p0.structure_protection_zones:
            if any(_inside_zone(point, zone, offset) for offset in (-1, 0, 1)):
                return max(0.0, distance - PROBE_STEP), "structure_protection_zone", point
        if _backbone_hit(
            point,
            root_s=float(sample.s),
            samples=p0.backbone_samples,
        ):
            return max(0.0, distance - PROBE_STEP), "periodic_backbone_return", point
        distance += PROBE_STEP
    target = _add(root, _mul(direction, MAX_PROBE_CLEARANCE))
    return MAX_PROBE_CLEARANCE, "open_until_probe_limit", target


def _space_probes(p0: StrictP0V2) -> list[dict[str, object]]:
    probes: list[dict[str, object]] = []
    for index, sample in enumerate(p0.backbone_samples):
        base_normal = _unit(_normal(sample.tangent))
        for side_id, sign in (("left_normal", 1), ("right_normal", -1)):
            direction = _mul(base_normal, sign)
            clearance, blocked_by, blocked_point = _ray_clearance(
                p0,
                root_index=index,
                direction=direction,
            )
            target = _add(sample.point, _mul(direction, clearance))
            flower_id, flower_center, flower_distance = _nearest_flower(
                sample.point, p0.flowers
            )
            alignment = (
                -1.0
                if flower_center is None
                else _dot(direction, _unit(_sub(flower_center, sample.point)))
            )
            vertical_side = (
                "upper"
                if direction[1] < -0.16
                else "lower"
                if direction[1] > 0.16
                else "lateral"
            )
            probes.append(
                {
                    "probe_id": f"probe_{index:03d}_{side_id}",
                    "sample_index": index,
                    "s": _round(sample.s),
                    "side_id": side_id,
                    "vertical_side": vertical_side,
                    "root": _round_point(sample.point),
                    "direction": _round_point(direction),
                    "clearance": _round(clearance),
                    "target": _round_point(target),
                    "blocked_by": blocked_by,
                    "blocked_point": _round_point(blocked_point),
                    "nearest_flower_id": flower_id,
                    "nearest_flower_center_distance": (
                        None if not math.isfinite(flower_distance) else _round(flower_distance)
                    ),
                    "flower_alignment": _round(alignment),
                    "candidate_for_l1": clearance >= L1_CLEARANCE,
                    "child_space_level": (
                        3
                        if clearance >= 0.23
                        else 2
                        if clearance >= L1_CLEARANCE
                        else 1
                    ),
                }
            )
    return probes


def _smooth(values: Sequence[float], radius: int = 2) -> list[float]:
    result: list[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        result.append(sum(values[start:end]) / (end - start))
    return result


def _select_separated(
    rows: Iterable[dict[str, object]],
    *,
    minimum_s_gap: float,
    limit: int,
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for row in sorted(rows, key=lambda value: float(value["strength"]), reverse=True):
        if all(
            _circular_s_distance(float(row["s"]), float(existing["s"]))
            >= minimum_s_gap
            for existing in selected
        ):
            selected.append(row)
        if len(selected) >= limit:
            break
    return sorted(selected, key=lambda value: float(value["s"]))


def _backbone_landmarks(p0: StrictP0V2) -> dict[str, object]:
    samples = p0.backbone_samples
    ys = _smooth([sample.point[1] for sample in samples], radius=2)
    extrema_candidates: list[dict[str, object]] = []
    window = 7
    for index in range(2, len(samples) - 2):
        before = samples[index - 2].tangent[1]
        after = samples[index + 2].tangent[1]
        kind: str | None = None
        if before < -0.02 and after > 0.02:
            kind = "peak"
        elif before > 0.02 and after < -0.02:
            kind = "trough"
        if kind is None:
            continue
        left = ys[max(0, index - window) : index]
        right = ys[index + 1 : min(len(ys), index + window + 1)]
        if not left or not right:
            continue
        if kind == "peak":
            prominence = min(max(left) - ys[index], max(right) - ys[index])
        else:
            prominence = min(ys[index] - min(left), ys[index] - min(right))
        if prominence < 0.012:
            continue
        extrema_candidates.append(
            {
                "feature_id": "",
                "kind": kind,
                "s": _round(samples[index].s),
                "sample_index": index,
                "point": _round_point(samples[index].point),
                "prominence": _round(prominence),
                "strength": _round(prominence),
            }
        )
    extrema = _select_separated(
        extrema_candidates,
        minimum_s_gap=0.075,
        limit=8,
    )
    if not any(row["kind"] == "peak" for row in extrema):
        index = min(range(1, len(samples) - 1), key=lambda value: ys[value])
        extrema.append(
            {
                "feature_id": "",
                "kind": "peak",
                "s": _round(samples[index].s),
                "sample_index": index,
                "point": _round_point(samples[index].point),
                "prominence": 0.0,
                "strength": 0.0,
                "fallback_global_extremum": True,
            }
        )
    if not any(row["kind"] == "trough" for row in extrema):
        index = max(range(1, len(samples) - 1), key=lambda value: ys[value])
        extrema.append(
            {
                "feature_id": "",
                "kind": "trough",
                "s": _round(samples[index].s),
                "sample_index": index,
                "point": _round_point(samples[index].point),
                "prominence": 0.0,
                "strength": 0.0,
                "fallback_global_extremum": True,
            }
        )
    extrema.sort(key=lambda row: float(row["s"]))
    counters: Counter[str] = Counter()
    for row in extrema:
        counters[str(row["kind"])] += 1
        row["feature_id"] = f"{row['kind']}_{counters[str(row['kind'])]}"
        row.pop("strength", None)

    turn_candidates: list[dict[str, object]] = []
    angle_scores = [0.0] * len(samples)
    for index in range(3, len(samples) - 3):
        angle_scores[index] = abs(
            _angle_degrees(
                samples[index - 3].tangent,
                samples[index + 3].tangent,
            )
        )
    for index in range(4, len(samples) - 4):
        score = angle_scores[index]
        if score < 12.0 or score < max(angle_scores[index - 2 : index + 3]):
            continue
        if any(
            _circular_s_distance(float(samples[index].s), float(row["s"])) < 0.045
            for row in extrema
        ):
            continue
        signed = _angle_degrees(
            samples[index - 3].tangent,
            samples[index + 3].tangent,
        )
        turn_candidates.append(
            {
                "feature_id": "",
                "kind": "turn_left" if signed > 0 else "turn_right",
                "s": _round(samples[index].s),
                "sample_index": index,
                "point": _round_point(samples[index].point),
                "turn_degrees": _round(signed, 6),
                "strength": _round(score, 6),
            }
        )
    turns = _select_separated(turn_candidates, minimum_s_gap=0.075, limit=6)
    for index, row in enumerate(turns, start=1):
        row["feature_id"] = f"turn_{index}"
        row.pop("strength", None)

    break_indices = sorted(
        {
            0,
            len(samples) - 1,
            *(int(row["sample_index"]) for row in extrema),
            *(int(row["sample_index"]) for row in turns),
        }
    )
    slopes: list[dict[str, object]] = []
    for start, end in zip(break_indices, break_indices[1:]):
        span = float(samples[end].s) - float(samples[start].s)
        delta_y = samples[end].point[1] - samples[start].point[1]
        if span < 0.09 or abs(delta_y) < 0.055:
            continue
        local_turns = [
            abs(_angle_degrees(samples[index - 1].tangent, samples[index].tangent))
            for index in range(start + 1, end + 1)
        ]
        mean_turn = sum(local_turns) / max(len(local_turns), 1)
        slopes.append(
            {
                "slope_id": f"slope_{len(slopes) + 1}",
                "start_s": _round(samples[start].s),
                "end_s": _round(samples[end].s),
                "start_point": _round_point(samples[start].point),
                "end_point": _round_point(samples[end].point),
                "trend": "rising" if delta_y < 0.0 else "falling",
                "vertical_change": _round(abs(delta_y)),
                "mean_step_turn_degrees": _round(mean_turn, 6),
                "classification": (
                    "long_gentle_slope" if mean_turn <= 3.5 else "long_turning_slope"
                ),
            }
        )
    return {
        "extrema": extrema,
        "turns": turns,
        "long_slopes": slopes,
    }


def _cyclic_runs(flags: Sequence[bool]) -> list[tuple[list[int], bool]]:
    if not flags or not any(flags):
        return []
    if all(flags):
        return [(list(range(len(flags))), True)]
    runs: list[list[int]] = []
    index = 0
    while index < len(flags):
        if not flags[index]:
            index += 1
            continue
        start = index
        while index < len(flags) and flags[index]:
            index += 1
        runs.append(list(range(start, index)))
    wrapped = False
    if len(runs) >= 2 and flags[0] and flags[-1]:
        merged = runs[-1] + runs[0]
        runs = [merged, *runs[1:-1]]
        wrapped = True
    return [
        (run, wrapped and position == 0)
        for position, run in enumerate(runs)
    ]


def _region_s_ranges(
    indices: Sequence[int],
    samples: Sequence[Any],
    wraps: bool,
) -> list[list[float]]:
    if not wraps:
        return [[_round(samples[indices[0]].s), _round(samples[indices[-1]].s)]]
    split = next(
        (
            position
            for position, (first, second) in enumerate(zip(indices, indices[1:]), start=1)
            if second < first
        ),
        len(indices),
    )
    tail = indices[:split]
    head = indices[split:]
    ranges: list[list[float]] = []
    if tail:
        ranges.append([_round(samples[tail[0]].s), 1.0])
    if head:
        ranges.append([0.0, _round(samples[head[-1]].s)])
    return ranges


def _region_span(ranges: Sequence[Sequence[float]]) -> float:
    return sum(float(end) - float(start) for start, end in ranges)


def _space_regions(
    p0: StrictP0V2,
    probes: Sequence[dict[str, object]],
    *,
    threshold: float,
    mode: str,
) -> list[dict[str, object]]:
    unique_count = len(p0.backbone_samples) - 1
    by_key = {
        (int(row["sample_index"]), str(row["side_id"])): row
        for row in probes
    }
    regions: list[dict[str, object]] = []
    for side_id in ("left_normal", "right_normal"):
        if mode == "above":
            flags = [
                float(by_key[(index, side_id)]["clearance"]) >= threshold
                for index in range(unique_count)
            ]
        else:
            flags = [
                float(by_key[(index, side_id)]["clearance"]) < threshold
                for index in range(unique_count)
            ]
        for indices, wraps in _cyclic_runs(flags):
            ranges = _region_s_ranges(indices, p0.backbone_samples, wraps)
            span = _region_span(ranges)
            if span < MIN_REGION_SPAN:
                continue
            rows = [by_key[(index, side_id)] for index in indices]
            best = max(rows, key=lambda row: float(row["clearance"]))
            clearances = [float(row["clearance"]) for row in rows]
            root_points = [tuple(row["root"]) for row in rows]
            target_points = [tuple(row["target"]) for row in rows]
            polygon = [*root_points, *reversed(target_points)]
            blocked_counts = Counter(str(row["blocked_by"]) for row in rows)
            region_kind = "blank" if mode == "above" else "crowded"
            regions.append(
                {
                    "region_id": f"{region_kind}_{side_id}_{len(regions) + 1}",
                    "kind": (
                        "continuous_blank_region"
                        if mode == "above"
                        else "crowded_backbone_side"
                    ),
                    "side_id": side_id,
                    "wraps_repeat_seam": wraps,
                    "s_ranges": ranges,
                    "s_span": _round(span),
                    "mean_clearance": _round(sum(clearances) / len(clearances)),
                    "max_clearance": _round(max(clearances)),
                    "best_s": best["s"],
                    "best_root": best["root"],
                    "best_direction": best["direction"],
                    "best_target": best["target"],
                    "dominant_blocker": blocked_counts.most_common(1)[0][0],
                    "polygon": [_round_point(point) for point in polygon],
                    "sample_count": len(rows),
                }
            )
    return sorted(
        regions,
        key=lambda row: (
            min(float(value[0]) for value in row["s_ranges"]),
            str(row["side_id"]),
        ),
    )


def _l1_mount_regions(
    p0: StrictP0V2,
    probes: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    raw = _space_regions(
        p0,
        probes,
        threshold=L1_CLEARANCE,
        mode="above",
    )
    regions: list[dict[str, object]] = []
    for row in raw:
        max_clearance = float(row["max_clearance"])
        span = float(row["s_span"])
        max_child_level = 3 if max_clearance >= 0.23 and span >= 0.075 else 2
        regions.append(
            {
                **row,
                "region_id": f"l1_mount_region_{len(regions) + 1}",
                "kind": "candidate_l1_attachment_interval",
                "required": False,
                "maximum_child_level_supported": max_child_level,
                "capacity_class": (
                    "large"
                    if max_clearance >= 0.27 and span >= 0.09
                    else "medium"
                    if max_clearance >= 0.19
                    else "small"
                ),
                "analysis_reason": (
                    "continuous normal-side clearance derived from StrictP0 geometry"
                ),
                "planner_selected": False,
            }
        )
    return regions


def _ellipse_ray_radius(rx: float, ry: float, direction: Point) -> float:
    unit = _unit(direction)
    denominator = math.sqrt(
        (unit[0] / max(rx, 1e-12)) ** 2
        + (unit[1] / max(ry, 1e-12)) ** 2
    )
    return 0.0 if denominator <= 1e-12 else 1.0 / denominator


def _flower_relations(p0: StrictP0V2) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for flower in p0.flowers:
        best: tuple[float, int, int, Point] | None = None
        for index, sample in enumerate(p0.backbone_samples):
            for offset in (-1, 0, 1):
                point = (sample.point[0] + offset, sample.point[1])
                distance = _distance(point, flower.center)
                if best is None or distance < best[0]:
                    best = (distance, index, offset, point)
        assert best is not None
        distance, index, offset, nearest_point = best
        sample = p0.backbone_samples[index]
        to_flower = _sub(flower.center, nearest_point)
        visual_relation = (
            "above_backbone"
            if flower.center[1] < nearest_point[1] - 0.012
            else "below_backbone"
            if flower.center[1] > nearest_point[1] + 0.012
            else "on_backbone_band"
        )
        normal_alignment = _dot(_normal(sample.tangent), _unit(to_flower))
        normal_side = "left_normal" if normal_alignment >= 0.0 else "right_normal"
        edge_gap = max(
            0.0,
            distance
            - _ellipse_ray_radius(
                flower.rx * FLOWER_PADDING,
                flower.ry * FLOWER_PADDING,
                to_flower,
            ),
        )
        start = float(sample.s) - 0.055
        end = float(sample.s) + 0.055
        if start < 0.0:
            support_ranges = [[_round(start + 1.0), 1.0], [0.0, _round(end)]]
        elif end > 1.0:
            support_ranges = [[_round(start), 1.0], [0.0, _round(end - 1.0)]]
        else:
            support_ranges = [[_round(start), _round(end)]]
        rows.append(
            {
                "flower_id": flower.flower_id,
                "center": _round_point(flower.center),
                "rx": _round(flower.rx),
                "ry": _round(flower.ry),
                "protection_padding": FLOWER_PADDING,
                "protection_rx": _round(flower.rx * FLOWER_PADDING),
                "protection_ry": _round(flower.ry * FLOWER_PADDING),
                "nearest_backbone_s": _round(sample.s),
                "nearest_backbone_point": _round_point(nearest_point),
                "nearest_backbone_period_offset": offset,
                "center_distance": _round(distance),
                "edge_gap": _round(edge_gap),
                "vertical_relation": visual_relation,
                "normal_side": normal_side,
                "support_context_s_ranges": support_ranges,
                "support_slot_selected": False,
            }
        )
    return rows


def _prohibited_regions(p0: StrictP0V2) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for flower in p0.flowers:
        rows.append(
            {
                "region_id": f"{flower.flower_id}_reserve",
                "kind": "flower_reserve",
                "source": "strict_p0_flower",
                "geometry": {
                    "type": "ellipse",
                    "center": _round_point(flower.center),
                    "rx": _round(flower.rx * FLOWER_PADDING),
                    "ry": _round(flower.ry * FLOWER_PADDING),
                },
            }
        )
    for zone in p0.structure_protection_zones:
        rows.append(
            {
                "region_id": zone.zone_id,
                "kind": "structure_protection_zone",
                "source": "strict_p0_explicit_zone",
                "geometry": zone.as_dict()["geometry"],
                "required": zone.required,
                "role": zone.role,
            }
        )
    return rows


def _seam_analysis(p0: StrictP0V2) -> dict[str, object]:
    start = p0.backbone_samples[0]
    end = p0.backbone_samples[-1]
    expected_end = (start.point[0] + 1.0, start.point[1])
    tangent_mismatch = abs(_angle_degrees(start.tangent, end.tangent))
    return {
        "periodic_axis": "x",
        "period": 1.0,
        "ghost_offsets": [-1, 1],
        "horizontal_repeat_is_not_a_wall": True,
        "left_endpoint": _round_point(start.point),
        "right_endpoint": _round_point(end.point),
        "left_endpoint_next_period": _round_point(expected_end),
        "position_gap": _round(_distance(end.point, expected_end)),
        "tangent_mismatch_degrees": _round(tangent_mismatch, 6),
        "position_continuous": _distance(end.point, expected_end) <= 0.012,
        "tangent_continuous": tangent_mismatch <= 12.0,
        "space_probes_use_periodic_backbone_copies": True,
    }


def analyze_prototype(p0: StrictP0V2) -> dict[str, object]:
    """Create a deterministic, planner-free PrototypeAnalysis."""

    probes = _space_probes(p0)
    landmarks = _backbone_landmarks(p0)
    blank_regions = _space_regions(
        p0,
        probes,
        threshold=BLANK_CLEARANCE,
        mode="above",
    )
    crowded_regions = _space_regions(
        p0,
        probes,
        threshold=CROWDED_CLEARANCE,
        mode="below",
    )
    l1_regions = _l1_mount_regions(p0, probes)
    flower_relations = _flower_relations(p0)
    prohibited = _prohibited_regions(p0)
    seam = _seam_analysis(p0)
    serialized_local_frame = p0.frame.as_dict()["local"]
    local_frame = {
        "coordinate_system": serialized_local_frame["coordinate_system"],
        "repeat_x_range": serialized_local_frame["repeat_x_range"],
        "canvas_bounds": [
            0.0,
            0.0,
            1.0,
            serialized_local_frame["canvas_bounds"][3],
        ],
        "horizontal_domain": "one_period_with_ghost_neighbors",
    }
    core: dict[str, object] = {
        "schema": SCHEMA,
        "policy_id": POLICY_ID,
        "prototype_id": p0.prototype_id,
        "coordinate_system": local_frame,
        "thresholds": {
            "probe_step": PROBE_STEP,
            "maximum_probe_clearance": MAX_PROBE_CLEARANCE,
            "continuous_blank_clearance": BLANK_CLEARANCE,
            "candidate_l1_clearance": L1_CLEARANCE,
            "crowded_clearance": CROWDED_CLEARANCE,
            "flower_padding": FLOWER_PADDING,
        },
        "backbone": {
            "sample_count": len(p0.backbone_samples),
            "samples": [sample.as_dict() for sample in p0.backbone_samples],
            **landmarks,
        },
        "flowers": flower_relations,
        "space_analysis": {
            "probes": probes,
            "continuous_blank_regions": blank_regions,
            "crowded_regions": crowded_regions,
            "prohibited_regions": prohibited,
        },
        "candidate_l1_attachment_regions": l1_regions,
        "repeat_seam": seam,
        "analysis_contract": {
            "consumes_only_strict_p0_v2": True,
            "old_branches_consumed": False,
            "old_growth_regions_consumed": False,
            "old_region_graph_consumed": False,
            "prototype_id_topology_rules": False,
            "planner_decisions_present": False,
            "curve_geometry_present": False,
            "numeric_results_are_diagnostic_not_visual_approval": True,
        },
        "stage_boundary": {
            "stage_2_prototype_analysis_complete": True,
            "stage_3_candidate_slots_started": False,
            "dynamic_branch_plan_present": False,
            "curve_compilation_present": False,
        },
    }
    core_digest = _canonical_digest(core)
    result = {
        **core,
        "strict_p0_digest": p0.digest,
        "analysis_core_digest": core_digest,
        "analysis_digest": "",
        "review": {
            "status": "analysis_pending_review",
            "allowed_states": list(REVIEW_STATES),
            "visual_gate_required": True,
            "criteria": [
                "backbone_global_flow_understood",
                "flower_side_spaces_identified",
                "candidate_attachment_regions_natural",
                "narrow_spaces_not_overstated",
                "obvious_growth_spaces_not_missed",
                "repeat_seam_space_reasonable",
            ],
        },
    }
    unsigned = dict(result)
    unsigned.pop("analysis_digest", None)
    result["analysis_digest"] = _canonical_digest(unsigned)
    return result


def analysis_summary(analysis: Mapping[str, object]) -> dict[str, object]:
    backbone = analysis["backbone"]
    space = analysis["space_analysis"]
    return {
        "prototype_id": analysis["prototype_id"],
        "analysis_core_digest": analysis["analysis_core_digest"],
        "peak_count": sum(
            row["kind"] == "peak" for row in backbone["extrema"]
        ),
        "trough_count": sum(
            row["kind"] == "trough" for row in backbone["extrema"]
        ),
        "turn_count": len(backbone["turns"]),
        "long_slope_count": len(backbone["long_slopes"]),
        "flower_count": len(analysis["flowers"]),
        "blank_region_count": len(space["continuous_blank_regions"]),
        "crowded_region_count": len(space["crowded_regions"]),
        "prohibited_region_count": len(space["prohibited_regions"]),
        "candidate_l1_region_count": len(
            analysis["candidate_l1_attachment_regions"]
        ),
        "repeat_position_gap": analysis["repeat_seam"]["position_gap"],
        "repeat_tangent_mismatch_degrees": analysis["repeat_seam"][
            "tangent_mismatch_degrees"
        ],
        "review_status": analysis["review"]["status"],
    }
