#!/usr/bin/env python3
"""Coordinate-free composition geometry shared by priors and production solvers."""

from __future__ import annotations

import bisect
import functools
import math
from typing import Sequence

import numpy as np


Point = tuple[float, float]

CO_TRAVEL_POLICY = {
    "metric": "uniform_correspondence_v2",
    "maximum_distance_ratio": 0.065,
    "short_sample_count": 48,
    "maximum_interval_sample_steps": 2,
    "minimum_continuous_intervals": 2,
    "tangent_power": 8,
    "score_use": "continuous_soft_penalty_only",
}


def _point(value: Sequence[float]) -> Point:
    return float(value[0]), float(value[1])


@functools.lru_cache(maxsize=16384)
def _resample_polyline_cached(
    points: tuple[Point, ...],
    count: int = 48,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return arc-length samples, unit tangents, and total length."""

    if len(points) < 2:
        raise ValueError("parallel co-travel requires two-point polylines")
    cumulative = [0.0]
    for index in range(1, len(points)):
        cumulative.append(cumulative[-1] + math.dist(points[index - 1], points[index]))
    length = cumulative[-1]
    if length <= 1e-9:
        raise ValueError("parallel co-travel received a degenerate polyline")

    sampled: list[Point] = []
    for sample_index in range(count):
        distance = length * sample_index / (count - 1)
        upper = min(len(points) - 1, bisect.bisect_left(cumulative, distance))
        lower = max(0, upper - 1)
        span = cumulative[upper] - cumulative[lower]
        weight = 0.0 if span <= 1e-12 else (distance - cumulative[lower]) / span
        sampled.append(
            (
                points[lower][0] * (1.0 - weight) + points[upper][0] * weight,
                points[lower][1] * (1.0 - weight) + points[upper][1] * weight,
            )
        )

    tangents: list[Point] = []
    for index in range(count):
        first = sampled[max(0, index - 1)]
        second = sampled[min(count - 1, index + 1)]
        vector = second[0] - first[0], second[1] - first[1]
        magnitude = math.hypot(*vector)
        if magnitude <= 1e-12:
            tangents.append(tangents[-1] if tangents else (1.0, 0.0))
        else:
            tangents.append((vector[0] / magnitude, vector[1] / magnitude))
    return np.asarray(sampled), np.asarray(tangents), length


def _resample_polyline(
    values: Sequence[Sequence[float]],
    count: int = 48,
) -> tuple[np.ndarray, np.ndarray, float]:
    return _resample_polyline_cached(
        tuple(_point(value) for value in values),
        count,
    )


def parallel_co_travel_score(
    first: Sequence[Sequence[float]],
    second: Sequence[Sequence[float]],
    *,
    repeat_width: float = 1.0,
    repeat_shifts: Sequence[float] | None = None,
    metric: str = "uniform_correspondence_v2",
    maximum_distance_ratio: float | None = None,
) -> float:
    """Evaluate a versioned curve-pair score.

    ``nearest_v1`` preserves the score used by the archived calibration and
    experiments only when explicitly requested. The production default uses
    unique arc-sample correspondences, a repeat-width distance ceiling and
    continuous interval stability. Its score is a soft penalty; old empirical
    quantile hard limits must not be applied to it.
    """

    if metric == "uniform_correspondence_v2":
        shifts = tuple(float(x) for x in repeat_shifts) if repeat_shifts is not None else (-repeat_width, 0., repeat_width)
        cap = CO_TRAVEL_POLICY["maximum_distance_ratio"] if maximum_distance_ratio is None else maximum_distance_ratio
        return _uniform_score_cached(tuple(_point(p) for p in first), tuple(_point(p) for p in second), repeat_width, shifts, cap)
    if metric != "nearest_v1":
        raise ValueError(f"unknown co-travel metric: {metric}")
    if maximum_distance_ratio is not None:
        raise ValueError("distance limit requires uniform_correspondence_v2")
    if repeat_width <= 0.0:
        raise ValueError("repeat_width must be positive")
    points_a, tangents_a, length_a = _resample_polyline(first)
    points_b, tangents_b, length_b = _resample_polyline(second)
    if length_a > length_b:
        points_a, points_b = points_b, points_a
        tangents_a, tangents_b = tangents_b, tangents_a
        length_a, length_b = length_b, length_a

    shifts = (
        tuple(float(value) for value in repeat_shifts)
        if repeat_shifts is not None
        else (-repeat_width, 0.0, repeat_width)
    )
    nearest_distance = np.full(len(points_a), np.inf)
    nearest_alignment = np.zeros(len(points_a))
    for shift_x in shifts:
        shifted = points_b + np.asarray((shift_x, 0.0))
        distances = np.linalg.norm(
            points_a[:, None, :] - shifted[None, :, :],
            axis=2,
        )
        indices = np.argmin(distances, axis=1)
        distances = distances[np.arange(len(points_a)), indices]
        alignments = np.abs(
            np.sum(tangents_a * tangents_b[indices], axis=1)
        )
        closer = distances < nearest_distance
        nearest_distance[closer] = distances[closer]
        nearest_alignment[closer] = alignments[closer]
    normalized_distance = nearest_distance / length_a
    return float(
        np.mean(
            nearest_alignment**8 / (1.0 + normalized_distance**4)
        )
    )


@functools.lru_cache(maxsize=32768)
def _uniform_score_cached(first, second, repeat_width, shifts, cap):
    if not math.isfinite(repeat_width) or repeat_width <= 0 or not math.isfinite(cap) or cap <= 0:
        raise ValueError("repeat width and distance ceiling must be finite and positive")
    a, b = np.asarray(first), np.asarray(second)
    if len(a) >= 2 and len(b) >= 2:
        amin,amax,bmin,bmax=a.min(0),a.max(0),b.min(0),b.max(0)
        lower_bounds=[np.linalg.norm(np.maximum(0.,np.maximum(amin-bmax-[x,0.],bmin+[x,0.]-amax))) for x in shifts]
        if lower_bounds and min(lower_bounds) > cap * repeat_width:
            return 0.0
    return float(uniform_correspondence_details(first, second, repeat_width=repeat_width,
        repeat_shifts=shifts, maximum_distance_ratio=cap)["score"])


def uniform_correspondence_details(
    first: Sequence[Sequence[float]],
    second: Sequence[Sequence[float]],
    *,
    repeat_width: float = 1.0,
    repeat_shifts: Sequence[float] | None = None,
    short_sample_count: int = 48,
    maximum_distance_ratio: float | None = None,
) -> dict:
    """Describe one-to-one correspondences and their distance stability.

    Coordinates share the repeat-width scale; curves are never individually
    translated, rotated, or stretched. Both are sampled at the same physical
    arc step, chosen to give the shorter curve ``short_sample_count`` points.
    Repeated nearest targets are resolved to the closest source sample, so
    every retained sample is used at most once. Adjacent correspondences may
    span one or two sampling steps on either curve; longer gaps do not bridge
    an unsupported segment. This permits unequal arc progression on curved
    offsets without matching many source points to one endpoint. The two-step
    allowance is an experimental discretization setting, not a calibrated
    heritage or perceptual criterion. An optional distance ceiling,
    measured relative to repeat width, excludes far-apart parallel curves.

    At least two connected intervals must survive. This is a geometric metric,
    not an aesthetic acceptance decision. All
    returned coordinates and lengths are in repeat-width units.
    """
    if not math.isfinite(repeat_width) or repeat_width <= 0:
        raise ValueError("repeat_width must be finite and positive")
    if short_sample_count < 3:
        raise ValueError("at least three short-curve samples are required")
    if maximum_distance_ratio is not None and (
        not math.isfinite(maximum_distance_ratio) or maximum_distance_ratio <= 0
    ):
        raise ValueError("maximum distance ratio must be finite and positive")

    def prepare(values):
        points = np.asarray(values, dtype=float) / repeat_width
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2:
            raise ValueError("expected a two-dimensional polyline")
        if not np.all(np.isfinite(points)):
            raise ValueError("curve coordinates must be finite")
        keep = np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-12]
        points = points[keep]
        if len(points) < 2:
            raise ValueError("co-travel received a degenerate polyline")
        arc = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
        return points, arc

    poly_a, arc_a = prepare(first)
    poly_b, arc_b = prepare(second)
    swapped = arc_a[-1] > arc_b[-1] or (arc_a[-1] == arc_b[-1] and tuple(map(tuple,poly_a)) > tuple(map(tuple,poly_b)))
    if swapped:
        poly_a, poly_b, arc_a, arc_b = poly_b, poly_a, arc_b, arc_a
    step = float(arc_a[-1] / (short_sample_count - 1))

    def sample(points, arc):
        count = int(math.floor(float(arc[-1]) / step + 1e-9)) + 1
        positions = np.minimum(np.arange(count) * step, arc[-1])
        xy = np.column_stack([np.interp(positions, arc, points[:,k]) for k in (0,1)])
        delta = np.vstack([xy[1] - xy[0], xy[2:] - xy[:-2], xy[-1] - xy[-2]])
        tangent = delta / np.maximum(np.linalg.norm(delta, axis=1)[:,None], 1e-12)
        return xy, tangent

    a, ta = sample(poly_a, arc_a)
    b, tb = sample(poly_b, arc_b)
    shifts = tuple(float(x)/repeat_width for x in repeat_shifts) if repeat_shifts is not None else (-1., 0., 1.)
    if not shifts or not all(math.isfinite(x) for x in shifts):
        raise ValueError("at least one finite repeat shift is required")
    shifts = tuple(dict.fromkeys(shifts))
    copies = np.concatenate([b + [shift, 0.] for shift in shifts])
    distance = np.linalg.norm(a[:,None,:] - copies[None,:,:], axis=2)
    a_to_b = np.argmin(distance, axis=1)
    matches = []
    # Resolve competition only among source points that actually chose this
    # target. Requiring mutual nearest neighbors instead would retain almost
    # no correspondences on offset curved arcs with different curvatures.
    winners = {}
    for i, target in enumerate(a_to_b):
        previous = winners.get(int(target))
        if previous is None or distance[i,target] < distance[previous,target]:
            winners[int(target)] = i
    unique_count = len(winners)
    for target, i in sorted(winners.items(), key=lambda item: item[1]):
        if maximum_distance_ratio is not None and distance[i,target] > maximum_distance_ratio:
            continue
        copy, j = divmod(int(target), len(b))
        matches.append({
            "a_index": i, "b_index": j, "copy": copy,
            "a_point": a[i].tolist(), "b_point": copies[target].tolist(),
            "distance": float(distance[i,target]),
            "alignment": float(abs(np.dot(ta[i],tb[j]))),
        })

    intervals = []
    for left, right in zip(matches, matches[1:]):
        di = right["a_index"] - left["a_index"]
        dj = right["b_index"] - left["b_index"]
        if left["copy"] != right["copy"] or not (1 <= di <= 2 and 1 <= abs(dj) <= 2):
            continue
        # A direction reversal between matches is not a continued traversal.
        if np.dot(ta[left["a_index"]],tb[left["b_index"]]) * dj <= 0:
            continue
        if np.dot(ta[right["a_index"]],tb[right["b_index"]]) * dj <= 0:
            continue
        span_a, span_b = di * step, abs(dj) * step
        length = min(span_a, span_b)
        mean_distance = .5 * (left["distance"] + right["distance"])
        gradient = abs(right["distance"] - left["distance"]) / (.5 * (span_a + span_b))
        stability = 1. / (1. + gradient ** 2)
        alignment = .5 * (left["alignment"] ** 8 + right["alignment"] ** 8)
        contribution = length / arc_a[-1] * alignment * stability
        intervals.append({
            "a_indices": [left["a_index"], right["a_index"]],
            "b_indices": [left["b_index"], right["b_index"]],
            "copy": left["copy"], "length": float(length),
            "distance_change_per_arc": float(gradient),
            "distance_stability": float(stability),
            "contribution": float(contribution),
        })
    # A single surviving interval does not establish sustained co-travel.
    runs = []
    for interval in intervals:
        if runs and runs[-1][-1]["copy"] == interval["copy"] and runs[-1][-1]["a_indices"][1] == interval["a_indices"][0] and runs[-1][-1]["b_indices"][1] == interval["b_indices"][0]:
            runs[-1].append(interval)
        else:
            runs.append([interval])
    intervals = [seg for run in runs if len(run) >= CO_TRAVEL_POLICY["minimum_continuous_intervals"] for seg in run]
    length = sum(x["length"] for x in intervals)
    return {
        "metric": "uniform_correspondence_v2",
        "score": float(sum(x["contribution"] for x in intervals)),
        "swapped": bool(swapped), "sample_step": step,
        "maximum_distance_ratio": maximum_distance_ratio,
        "unique_match_count_before_distance_limit": unique_count,
        "maximum_interval_sample_steps": 2,
        "short_length": float(arc_a[-1]), "long_length": float(arc_b[-1]),
        "a_samples": a.tolist(), "b_samples": b.tolist(), "repeat_shifts": list(shifts),
        "matches": matches, "intervals": intervals,
        "covered_length": length, "coverage_fraction": float(length / arc_a[-1]),
    }
