#!/usr/bin/env python3
"""Independently evaluate formal Paper A cases from saved canonical geometry."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "experiments/branch_unit/dynamic"))
from composition_geometry import CO_TRAVEL_POLICY
DEFAULT_PROTOCOL_DIR = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "protocol"
EPS = 1e-10


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _points(values: Sequence[Sequence[float]], shift_x: float = 0.0) -> np.ndarray:
    result = np.asarray(
        [[float(value[0]) + shift_x, float(value[1])] for value in values],
        dtype=np.float64,
    )
    if result.ndim != 2 or result.shape[0] < 2 or result.shape[1] != 2:
        raise ValueError("polyline must contain at least two 2D points")
    return result


def _cross(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    return first[..., 0] * second[..., 1] - first[..., 1] * second[..., 0]


def _proper_intersection(first: np.ndarray, second: np.ndarray) -> bool:
    if (
        float(first[:, 0].max()) < float(second[:, 0].min())
        or float(first[:, 0].min()) > float(second[:, 0].max())
        or float(first[:, 1].max()) < float(second[:, 1].min())
        or float(first[:, 1].min()) > float(second[:, 1].max())
    ):
        return False
    a0, a1 = first[:-1], first[1:]
    b0, b1 = second[:-1], second[1:]
    av = a1 - a0
    bv = b1 - b0
    o1 = _cross(av[:, None, :], b0[None, :, :] - a0[:, None, :])
    o2 = _cross(av[:, None, :], b1[None, :, :] - a0[:, None, :])
    o3 = _cross(bv[None, :, :], a0[:, None, :] - b0[None, :, :])
    o4 = _cross(bv[None, :, :], a1[:, None, :] - b0[None, :, :])
    proper = ((o1 > EPS) & (o2 < -EPS) | (o1 < -EPS) & (o2 > EPS)) & (
        (o3 > EPS) & (o4 < -EPS) | (o3 < -EPS) & (o4 > EPS)
    )
    return bool(np.any(proper))


def _point_to_segment_distance(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    vector = end - start
    denominator = float(np.dot(vector, vector))
    if denominator <= EPS:
        return float(np.linalg.norm(point - start))
    fraction = float(np.dot(point - start, vector) / denominator)
    fraction = min(1.0, max(0.0, fraction))
    return float(np.linalg.norm(point - (start + fraction * vector)))


def _curve_crosses_with_allowed_junction(
    first: np.ndarray,
    second: np.ndarray,
    junction: np.ndarray | None,
    tolerance: float,
) -> bool:
    for first_index in range(len(first) - 1):
        first_segment = first[first_index : first_index + 2]
        for second_index in range(len(second) - 1):
            second_segment = second[second_index : second_index + 2]
            if not _proper_intersection(first_segment, second_segment):
                continue
            if (
                junction is not None
                and _point_to_segment_distance(junction, first_segment[0], first_segment[1]) <= tolerance
                and _point_to_segment_distance(junction, second_segment[0], second_segment[1]) <= tolerance
            ):
                continue
            return True
    return False


def _point_segment_distances(points: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    vectors = end - start
    denominator = np.sum(vectors * vectors, axis=1)
    delta = points[:, None, :] - start[None, :, :]
    projection = np.sum(delta * vectors[None, :, :], axis=2) / np.maximum(
        denominator[None, :], EPS
    )
    projection = np.clip(projection, 0.0, 1.0)
    nearest = start[None, :, :] + projection[..., None] * vectors[None, :, :]
    return np.linalg.norm(points[:, None, :] - nearest, axis=2)


def _polyline_distance(first: np.ndarray, second: np.ndarray) -> float:
    if _proper_intersection(first, second):
        return 0.0
    first_to_second = _point_segment_distances(first, second[:-1], second[1:]).min()
    second_to_first = _point_segment_distances(second, first[:-1], first[1:]).min()
    return float(min(first_to_second, second_to_first))


def _arc_length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _resample_polyline(points: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray, float]:
    segment_lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    total = float(segment_lengths.sum())
    if total <= EPS:
        raise ValueError("zero-length curve")
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    targets = np.linspace(0.0, total, count)
    output = np.empty((count, 2), dtype=np.float64)
    for index, target in enumerate(targets):
        segment = min(
            int(np.searchsorted(cumulative, target, side="right") - 1),
            len(segment_lengths) - 1,
        )
        local = (target - cumulative[segment]) / max(segment_lengths[segment], EPS)
        output[index] = points[segment] * (1.0 - local) + points[segment + 1] * local
    tangents = np.gradient(output, axis=0)
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1, keepdims=True), EPS)
    return output, tangents, total


def _parallel_score(first: np.ndarray, second: np.ndarray, shifts: Sequence[float], samples: int) -> float:
    """Independent reconstruction from exported geometry, in repeat units.

    Shares the declared parameters, not the production matching/score helper.
    """
    def prepare(p):
        p=np.asarray(p,float)
        p=p[np.r_[True,np.linalg.norm(np.diff(p,axis=0),axis=1)>1e-12]]
        return p,np.r_[0.,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))]
    a,sa=prepare(first);b,sb=prepare(second)
    if sa[-1]>sb[-1] or (sa[-1]==sb[-1] and tuple(map(tuple,a))>tuple(map(tuple,b))):
        a,b,sa,sb=b,a,sb,sa
    h=sa[-1]/(samples-1)
    if h<=0:return 0.
    def spaced(p,s):
        u=np.minimum(np.arange(int(np.floor(s[-1]/h+1e-9))+1)*h,s[-1])
        xy=np.column_stack([np.interp(u,s,p[:,k])for k in (0,1)])
        t=np.gradient(xy,axis=0);t/=np.maximum(np.linalg.norm(t,axis=1)[:,None],1e-12)
        return xy,t
    a,ta=spaced(a,sa);b,tb=spaced(b,sb)
    copies=np.concatenate([b+[float(x),0.]for x in dict.fromkeys(shifts)])
    squared=((a[:,None,:]-copies[None,:,:])**2).sum(axis=2)
    targets=squared.argmin(axis=1)
    chosen=[]
    for target in np.unique(targets):
        eligible=np.flatnonzero(targets==target)
        i=int(eligible[np.argmin(squared[eligible,target])]);d=float(np.sqrt(squared[i,target]))
        if d<=CO_TRAVEL_POLICY['maximum_distance_ratio']:
            copy,j=divmod(int(target),len(b));chosen.append((i,j,copy,d,float(np.dot(ta[i],tb[j]))))
    chosen.sort()
    score=0.;run=[];last=None
    def value(run):return sum(run)if len(run)>=CO_TRAVEL_POLICY['minimum_continuous_intervals']else 0.
    for left,right in zip(chosen,chosen[1:]):
        i,j,c,d,t=left;ni,nj,nc,nd,nt=right
        di,dj=ni-i,nj-j
        allowed=(c==nc and 1<=di<=2 and 1<=abs(dj)<=2 and t*dj>0 and nt*dj>0)
        if not allowed:
            score+=value(run);run=[];last=None;continue
        if last is not None and last!=left:
            score+=value(run);run=[]
        slope=abs(nd-d)/(.5*(di+abs(dj))*h)
        run.append(min(di,abs(dj))*h/sa[-1]*(abs(t)**8+abs(nt)**8)*.5/(1+slope*slope))
        last=right
    return float(score+value(run))


def _metric_parameters(path: Path) -> dict[str, str]:
    return {row["parameter"]: row["value"] for row in _read_csv(path)}


def _curve_points(curve: Mapping[str, Any], shift_x: float = 0.0) -> np.ndarray:
    return _points(curve["centerline"], shift_x)


def _selected_curves(selection: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    rows: list[tuple[str, Mapping[str, Any]]] = []
    for candidate in selection["selected_candidates"]:
        unit_id = str(candidate["candidate_id"])
        for curve in candidate["curves"]:
            rows.append((unit_id, curve))
    return rows


def _support_curves(flower_mount_plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        {
            "curve_id": mount["mount_id"],
            "level": "FLOWER_SUPPORT",
            "centerline": mount["centerline"],
        }
        for mount in flower_mount_plan.get("mounts", [])
    ]


def _pairwise(items: Sequence[Any]) -> Iterable[tuple[Any, Any]]:
    for first_index in range(len(items)):
        for second_index in range(first_index + 1, len(items)):
            yield items[first_index], items[second_index]


def _quantile(values: Sequence[float], q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), q)) if values else 0.0


def _root_features(plan: Mapping[str, Any]) -> dict[str, float]:
    roots = sorted(float(lane["root_s"]) % 1.0 for lane in plan["lanes"])
    histogram = np.histogram(roots, bins=np.linspace(0.0, 1.0, 9))[0].astype(float)
    if roots:
        histogram /= len(roots)
        gaps = [
            (roots[(index + 1) % len(roots)] - roots[index]) % 1.0
            for index in range(len(roots))
        ]
    else:
        gaps = []
    result = {f"root_hist_{index}": float(value) for index, value in enumerate(histogram)}
    result.update(
        root_gap_q25=_quantile(gaps, 0.25),
        root_gap_q50=_quantile(gaps, 0.50),
        root_gap_q75=_quantile(gaps, 0.75),
        root_gap_max=max(gaps, default=0.0),
        root_coverage_qcov=1.0 - max(gaps, default=1.0),
        root_concentration=float(histogram.max()) if len(histogram) else 0.0,
    )
    return result


def _occupied_area_ratio(
    curves: Sequence[Mapping[str, Any]],
    canvas_bounds: Sequence[float],
    radius: float,
    grid_width: int = 384,
) -> float:
    x0, y0, x1, y1 = map(float, canvas_bounds)
    height = max(1, int(round(grid_width * (y1 - y0) / max(x1 - x0, EPS))))
    xs = np.linspace(x0, x1, grid_width, endpoint=False) + (x1 - x0) / (2 * grid_width)
    ys = np.linspace(y0, y1, height, endpoint=False) + (y1 - y0) / (2 * height)
    mask = np.zeros((height, grid_width), dtype=bool)
    for curve in curves:
        points = _curve_points(curve)
        for start, end in zip(points[:-1], points[1:]):
            min_x = max(0, int(math.floor((min(start[0], end[0]) - radius - x0) / (x1 - x0) * grid_width)))
            max_x = min(grid_width, int(math.ceil((max(start[0], end[0]) + radius - x0) / (x1 - x0) * grid_width)))
            min_y = max(0, int(math.floor((min(start[1], end[1]) - radius - y0) / (y1 - y0) * height)))
            max_y = min(height, int(math.ceil((max(start[1], end[1]) + radius - y0) / (y1 - y0) * height)))
            if min_x >= max_x or min_y >= max_y:
                continue
            local_x, local_y = np.meshgrid(xs[min_x:max_x], ys[min_y:max_y])
            query = np.column_stack((local_x.ravel(), local_y.ravel()))
            distance = _point_segment_distances(
                query,
                np.asarray([start], dtype=np.float64),
                np.asarray([end], dtype=np.float64),
            )[:, 0]
            mask[min_y:max_y, min_x:max_x] |= (distance <= radius).reshape(
                max_y - min_y, max_x - min_x
            )
    return float(mask.mean())


def evaluate_case(case_dir: Path, parameters: Mapping[str, str]) -> dict[str, object]:
    strict = _read_json(case_dir / "strict_p0_variant.json")
    analysis = _read_json(case_dir / "prototype_analysis_variant.json")
    flower_mount_plan = _read_json(case_dir / "flower_mount_plan.json")
    plan = _read_json(case_dir / "global_l1_flow_plan.json")
    selection = _read_json(case_dir / "global_unit_selection.json")
    prototype_id = str(analysis["prototype_id"])
    shifts = tuple(float(value) for value in parameters["repeat_shifts_checked"].split(";"))
    nonzero_shifts = tuple(value for value in shifts if abs(value) > EPS)
    clearance_required = float(parameters[f"minimum_full_unit_clearance.{prototype_id}"])
    occupancy_radius = float(parameters["occupancy_radius"])
    parallel_samples = int(float(parameters["parallel_resample_count"]))

    candidates = list(selection["selected_candidates"])
    ordinary = _selected_curves(selection)
    supports = _support_curves(flower_mount_plan)
    backbone_samples = strict["backbone"]["arc_samples"]
    backbone = _points([sample["point"] for sample in backbone_samples])

    internal_crossings = 0
    junction_tolerance = float(parameters["parent_junction_exclusion_tolerance"])
    for candidate in candidates:
        curve_by_id = {str(curve["curve_id"]): curve for curve in candidate["curves"]}
        for first, second in _pairwise(candidate["curves"]):
            junction: np.ndarray | None = None
            if str(first.get("parent_curve_id")) == str(second.get("curve_id")):
                junction = _curve_points(first)[0]
            elif str(second.get("parent_curve_id")) == str(first.get("curve_id")):
                junction = _curve_points(second)[0]
            internal_crossings += int(
                _curve_crosses_with_allowed_junction(
                    _curve_points(first),
                    _curve_points(second),
                    junction,
                    junction_tolerance,
                )
            )

    cross_unit_crossings = 0
    periodic_crossings = 0
    minimum_unit_clearance = float("inf")
    parallel_total = 0.0
    parallel_peak = 0.0
    for first_candidate, second_candidate in _pairwise(candidates):
        pair_peak = 0.0
        for first_curve in first_candidate["curves"]:
            first_points = _curve_points(first_curve)
            for second_curve in second_candidate["curves"]:
                second_points = _curve_points(second_curve)
                for shift_x in shifts:
                    shifted = second_points + np.asarray((shift_x, 0.0))
                    intersects = _proper_intersection(first_points, shifted)
                    if abs(shift_x) <= EPS:
                        cross_unit_crossings += int(intersects)
                    else:
                        periodic_crossings += int(intersects)
                    minimum_unit_clearance = min(
                        minimum_unit_clearance,
                        0.0 if intersects else _polyline_distance(first_points, shifted),
                    )
                if not (
                    str(first_curve.get("level")) == "L1"
                    and str(second_curve.get("level")) == "L1"
                ):
                    pair_peak = max(
                        pair_peak,
                        _parallel_score(first_points, second_points, shifts, parallel_samples),
                    )
        parallel_total += pair_peak
        parallel_peak = max(parallel_peak, pair_peak)

    branch_backbone_crossings = 0
    l1_prefix_min = int(float(parameters["l1_backbone_root_exclusion_min_points"]))
    l1_prefix_fraction = float(parameters["l1_backbone_root_exclusion_fraction"])
    l2_backbone_tolerance = float(parameters["l2_backbone_contact_tolerance"])
    for _, curve in ordinary:
        points = _curve_points(curve)
        if str(curve.get("level")) == "L1":
            start = max(l1_prefix_min, int(len(points) * l1_prefix_fraction))
            trimmed = points[start:]
            if len(trimmed) >= 2:
                branch_backbone_crossings += int(
                    any(
                        _proper_intersection(trimmed, backbone + np.asarray((shift, 0.0)))
                        for shift in shifts
                    )
                )
        else:
            branch_backbone_crossings += int(
                min(
                    _polyline_distance(points, backbone + np.asarray((shift, 0.0)))
                    for shift in shifts
                )
                <= l2_backbone_tolerance
            )
    ordinary_support_crossings = 0
    l1_flower_prefix = int(float(parameters["ordinary_flower_root_exclusion_points"]))
    for _, curve in ordinary:
        all_points_for_curve = _curve_points(curve)
        points = (
            all_points_for_curve[l1_flower_prefix:]
            if str(curve.get("level")) == "L1"
            else all_points_for_curve[1:]
        )
        for support in supports:
            support_points = _curve_points(support)
            ordinary_support_crossings += sum(
                int(_proper_intersection(points, support_points + np.asarray((shift, 0.0))))
                for shift in shifts
            )

    full_nonbackbone = [curve for _, curve in ordinary] + supports
    all_periodic_crossings = periodic_crossings
    for first in full_nonbackbone:
        first_points = _curve_points(first)
        for second in full_nonbackbone:
            second_points = _curve_points(second)
            all_periodic_crossings += sum(
                int(_proper_intersection(first_points, second_points + np.asarray((shift, 0.0))))
                for shift in nonzero_shifts
            )
        all_periodic_crossings += sum(
            int(_proper_intersection(first_points, backbone + np.asarray((shift, 0.0))))
            for shift in nonzero_shifts
        )

    flower_intrusion_curve_count = 0
    flower_epsilon = float(parameters["flower_region_intrusion_epsilon"])
    flowers = analysis.get("flowers", [])
    for _, curve in ordinary:
        all_points_for_curve = _curve_points(curve)
        points = (
            all_points_for_curve[l1_flower_prefix:]
            if str(curve.get("level")) == "L1"
            else all_points_for_curve[1:]
        )
        intrudes = False
        for flower in flowers:
            center = flower["center"]
            rx = float(flower.get("protection_rx", flower["rx"]))
            ry = float(flower.get("protection_ry", flower["ry"]))
            for shift in shifts:
                value = ((points[:, 0] - (float(center[0]) + shift)) / rx) ** 2 + (
                    (points[:, 1] - float(center[1])) / ry
                ) ** 2
                if bool(np.any(value < 1.0 - flower_epsilon)):
                    intrudes = True
                    break
            if intrudes:
                break
        flower_intrusion_curve_count += int(intrudes)

    left = backbone[0]
    right = backbone[-1]
    expected_period = float(analysis["repeat_seam"]["period"])
    seam_gap = float(np.linalg.norm((left + np.asarray((expected_period, 0.0))) - right))
    left_tangent = np.asarray(backbone_samples[0]["tangent"], dtype=np.float64)
    right_tangent = np.asarray(backbone_samples[-1]["tangent"], dtype=np.float64)
    left_tangent /= max(float(np.linalg.norm(left_tangent)), EPS)
    right_tangent /= max(float(np.linalg.norm(right_tangent)), EPS)
    seam_tangent_dot = float(np.dot(left_tangent, right_tangent))
    seam_position_violation = seam_gap > float(parameters["backbone_seam_position_tolerance"])
    seam_tangent_violation = seam_tangent_dot < float(parameters["backbone_seam_tangent_dot_min"])

    curve_values = [curve for _, curve in ordinary]
    l1_curves = [curve for curve in curve_values if str(curve.get("level")) == "L1"]
    l2_curves = [curve for curve in curve_values if str(curve.get("level")) == "L2"]
    lengths = [_arc_length(_curve_points(curve)) for curve in curve_values]
    all_points = np.concatenate([_curve_points(curve) for curve in curve_values], axis=0)
    vertical_span = float(all_points[:, 1].max() - all_points[:, 1].min())
    mean_backbone_excursion = float(
        np.mean(
            [
                _point_segment_distances(_curve_points(curve), backbone[:-1], backbone[1:]).min(axis=1).mean()
                for curve in curve_values
            ]
        )
    )
    upward = sum(float(_curve_points(curve)[-1, 1]) < float(_curve_points(curve)[0, 1]) for curve in l1_curves)
    downward = len(l1_curves) - upward
    hierarchy_l1_only = sum(int(candidate["hierarchy"]["l2_count"]) == 0 for candidate in candidates)
    hierarchy_single = sum(int(candidate["hierarchy"]["l2_count"]) == 1 for candidate in candidates)
    hierarchy_opposed = sum(int(candidate["hierarchy"]["l2_count"]) == 2 for candidate in candidates)

    l1_plan_curves = [
        {
            "curve_id": str(lane["selected_l1_id"]),
            "centerline": lane["centerline"],
            "level": "L1",
        }
        for lane in plan["lanes"]
    ]
    l1_layout_crossings = 0
    l1_layout_periodic_crossings = 0
    l1_layout_minimum_clearance = float("inf")
    l1_parallel_total = 0.0
    l1_parallel_peak = 0.0
    for first, second in _pairwise(l1_plan_curves):
        first_points = _curve_points(first)
        second_points = _curve_points(second)
        for shift in shifts:
            shifted = second_points + np.asarray((shift, 0.0))
            intersects = _proper_intersection(first_points, shifted)
            if abs(shift) <= EPS:
                l1_layout_crossings += int(intersects)
            else:
                l1_layout_periodic_crossings += int(intersects)
            l1_layout_minimum_clearance = min(
                l1_layout_minimum_clearance,
                0.0 if intersects else _polyline_distance(first_points, shifted),
            )
        score = _parallel_score(first_points, second_points, shifts, parallel_samples)
        l1_parallel_total += score
        l1_parallel_peak = max(l1_parallel_peak, score)

    density_objective = plan.get("count_derivation", {}).get("density_objective", {})
    selected_density = density_objective.get("selected", {}) if isinstance(density_objective, Mapping) else {}
    result: dict[str, object] = {
        "prototype_id": prototype_id,
        "mechanical_evaluation_success": 1,
        "internal_unit_crossing_count": internal_crossings,
        "cross_unit_crossing_count": cross_unit_crossings,
        "ordinary_backbone_nonroot_crossing_count": branch_backbone_crossings,
        "ordinary_support_crossing_count": ordinary_support_crossings,
        "periodic_crossing_count": all_periodic_crossings,
        "minimum_cross_unit_clearance": (
            minimum_unit_clearance if math.isfinite(minimum_unit_clearance) else ""
        ),
        "minimum_full_unit_clearance_required": clearance_required,
        "clearance_violation_count": int(
            math.isfinite(minimum_unit_clearance)
            and minimum_unit_clearance < clearance_required - 1e-9
        ),
        "flower_region_intrusion_curve_count": flower_intrusion_curve_count,
        "backbone_seam_position_gap": seam_gap,
        "backbone_seam_tangent_dot": seam_tangent_dot,
        "periodic_seam_violation_count": int(seam_position_violation) + int(seam_tangent_violation),
        "parallel_cotravel_total": parallel_total,
        "parallel_cotravel_peak": parallel_peak,
        "l1_layout_crossing_count": l1_layout_crossings,
        "l1_layout_periodic_crossing_count": l1_layout_periodic_crossings,
        "l1_layout_minimum_clearance": (
            l1_layout_minimum_clearance if math.isfinite(l1_layout_minimum_clearance) else ""
        ),
        "l1_layout_parallel_cotravel_total": l1_parallel_total,
        "l1_layout_parallel_cotravel_peak": l1_parallel_peak,
        "l1_count": len(l1_curves),
        "l2_count": len(l2_curves),
        "branchunit_count_evaluated": len(candidates),
        "ordinary_total_length": sum(lengths),
        "ordinary_mean_length": float(np.mean(lengths)),
        "mean_backbone_excursion": mean_backbone_excursion,
        "vertical_span": vertical_span,
        "occupied_area_ratio": _occupied_area_ratio(
            curve_values,
            analysis["coordinate_system"]["canvas_bounds"],
            occupancy_radius,
        ),
        "upper_allocation_ratio": upward / max(len(l1_curves), 1),
        "lower_allocation_ratio": downward / max(len(l1_curves), 1),
        "hierarchy_l1_only_ratio": hierarchy_l1_only / max(len(candidates), 1),
        "hierarchy_single_l2_ratio": hierarchy_single / max(len(candidates), 1),
        "hierarchy_opposed_l2_ratio": hierarchy_opposed / max(len(candidates), 1),
        "density_resource_D": selected_density.get("resource_score", ""),
    }
    result.update(_root_features(plan))
    return result


def evaluate_run(run_dir: Path, protocol_dir: Path) -> None:
    raw = _read_csv(run_dir / "raw_results.csv")
    parameters = _metric_parameters(protocol_dir / "metric_parameters.csv")
    output: list[dict[str, object]] = []
    for row in raw:
        merged: dict[str, object] = dict(row)
        relative_dir = row.get("case_dir") or row.get("method_dir") or ""
        geometry_available = row["generation_success"] == "1" or (
            row.get("l1_generation_success") == "1" and bool(relative_dir)
        )
        if not geometry_available:
            merged["mechanical_evaluation_success"] = 0
            merged["mechanical_evaluation_error"] = "generation failed; no canonical geometry"
        else:
            try:
                merged.update(evaluate_case(run_dir / relative_dir, parameters))
                merged["mechanical_evaluation_error"] = ""
            except Exception as exc:
                merged["mechanical_evaluation_success"] = 0
                merged["mechanical_evaluation_error"] = f"{type(exc).__name__}: {exc}"
        output.append(merged)
    _write_csv(run_dir / "evaluated_results.csv", output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--protocol-dir", type=Path, default=DEFAULT_PROTOCOL_DIR)
    args = parser.parse_args()
    evaluate_run(args.run_dir.resolve(), args.protocol_dir.resolve())
    print(args.run_dir.resolve() / "evaluated_results.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
