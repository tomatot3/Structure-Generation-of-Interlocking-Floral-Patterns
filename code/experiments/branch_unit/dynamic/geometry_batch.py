"""Batched float64 geometry primitives for the frozen programmatic chain.

The formulas replicate `branch_unit_grammar_v1._orientation`,
`_segments_intersect`, and `_point_segment_distance` exactly, so batched
results must agree with the scalar results to float64 rounding precision.
This module is additive; it does not change the formal chain by itself.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

Backend = Literal["numpy", "torch_cuda"]

INTERSECTION_TOLERANCE = 1e-10
DEGENERATE_DENOMINATOR_EPSILON = 1e-18


def _lib(backend: Backend):
    if backend == "numpy":
        return np
    import torch

    return torch


def orientation_batch(
    ax,
    ay,
    bx,
    by,
    cx,
    cy,
    *,
    backend: Backend = "numpy",
):
    """Cross((b - a), (c - a)) for batched point triples."""

    lib = _lib(backend)
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def point_segment_distance_batch(
    px,
    py,
    sx,
    sy,
    ex,
    ey,
    *,
    backend: Backend = "numpy",
):
    """Batched point-to-segment distance with the scalar clip semantics."""

    lib = _lib(backend)
    vx = ex - sx
    vy = ey - sy
    denominator = vx * vx + vy * vy
    fraction = (px - sx) * vx + (py - sy) * vy
    if backend == "numpy":
        safe_denominator = np.where(
            denominator <= DEGENERATE_DENOMINATOR_EPSILON,
            1.0,
            denominator,
        )
        fraction = np.clip(fraction / safe_denominator, 0.0, 1.0)
        fraction = np.where(denominator <= DEGENERATE_DENOMINATOR_EPSILON, 0.0, fraction)
    else:
        safe_denominator = lib.where(
            denominator <= DEGENERATE_DENOMINATOR_EPSILON,
            lib.ones_like(denominator),
            denominator,
        )
        fraction = lib.clip(fraction / safe_denominator, 0.0, 1.0)
        fraction = lib.where(
            denominator <= DEGENERATE_DENOMINATOR_EPSILON,
            lib.zeros_like(fraction),
            fraction,
        )
    projection_x = sx + vx * fraction
    projection_y = sy + vy * fraction
    return lib.hypot(px - projection_x, py - projection_y)


def segments_intersect_batch(
    a0x,
    a0y,
    a1x,
    a1y,
    b0x,
    b0y,
    b1x,
    b1y,
    *,
    backend: Backend = "numpy",
):
    """Batched segment intersection with the scalar orientation semantics."""

    lib = _lib(backend)
    tolerance = INTERSECTION_TOLERANCE
    o1 = orientation_batch(a0x, a0y, a1x, a1y, b0x, b0y, backend=backend)
    o2 = orientation_batch(a0x, a0y, a1x, a1y, b1x, b1y, backend=backend)
    o3 = orientation_batch(b0x, b0y, b1x, b1y, a0x, a0y, backend=backend)
    o4 = orientation_batch(b0x, b0y, b1x, b1y, a1x, a1y, backend=backend)
    # Apply the area tolerance to each orientation, not their product.
    # Multiplying small, nonzero areas otherwise hides genuine crossings.
    proper_crossing = (
        ((o1 > tolerance) & (o2 < -tolerance))
        | ((o1 < -tolerance) & (o2 > tolerance))
    ) & (
        ((o3 > tolerance) & (o4 < -tolerance))
        | ((o3 < -tolerance) & (o4 > tolerance))
    )

    def on_segment(px, py, sx, sy, ex, ey):
        return (
            (lib.minimum(sx, ex) - tolerance <= px)
            & (px <= lib.maximum(sx, ex) + tolerance)
            & (lib.minimum(sy, ey) - tolerance <= py)
            & (py <= lib.maximum(sy, ey) + tolerance)
        )

    touching = (
        ((lib.abs(o1) <= tolerance) & on_segment(b0x, b0y, a0x, a0y, a1x, a1y))
        | ((lib.abs(o2) <= tolerance) & on_segment(b1x, b1y, a0x, a0y, a1x, a1y))
        | ((lib.abs(o3) <= tolerance) & on_segment(a0x, a0y, b0x, b0y, b1x, b1y))
        | ((lib.abs(o4) <= tolerance) & on_segment(a1x, a1y, b0x, b0y, b1x, b1y))
    )
    return proper_crossing | touching


def _segment_pair_arrays(pa, pb):
    """Flatten all segment pairs between two polylines into coordinate arrays."""

    a0 = pa[:-1]
    a1 = pa[1:]
    b0 = pb[:-1]
    b1 = pb[1:]
    repeat_count = b0.shape[0]
    tile_count = a0.shape[0]
    return (
        np.repeat(a0[:, 0], repeat_count),
        np.repeat(a0[:, 1], repeat_count),
        np.repeat(a1[:, 0], repeat_count),
        np.repeat(a1[:, 1], repeat_count),
        np.tile(b0[:, 0], tile_count),
        np.tile(b0[:, 1], tile_count),
        np.tile(b1[:, 0], tile_count),
        np.tile(b1[:, 1], tile_count),
    )


def polyline_pair_intersects(pa, pb, junction=None) -> bool:
    """Return True when any segment pair between two polylines intersects.

    Mirrors `branch_unit_grammar_v1._curve_crosses`: an optional junction
    point within 1e-7 of both segments is excluded from the crossing test.
    """

    if pa.shape[0] < 2 or pb.shape[0] < 2:
        return False
    arrays = _segment_pair_arrays(pa, pb)
    intersects = segments_intersect_batch(
        arrays[0],
        arrays[1],
        arrays[2],
        arrays[3],
        arrays[4],
        arrays[5],
        arrays[6],
        arrays[7],
    )
    if junction is None:
        return bool(np.any(intersects))
    junction_x = float(junction[0])
    junction_y = float(junction[1])
    junction_on_a = (
        point_segment_distance_batch(
            junction_x,
            junction_y,
            arrays[0],
            arrays[1],
            arrays[2],
            arrays[3],
        )
        <= 1e-7
    )
    junction_on_b = (
        point_segment_distance_batch(
            junction_x,
            junction_y,
            arrays[4],
            arrays[5],
            arrays[6],
            arrays[7],
        )
        <= 1e-7
    )
    excluded = junction_on_a & junction_on_b
    return bool(np.any(intersects & ~excluded))


def point_segment_distance_matrix_batch(
    points,
    segment_starts,
    segment_ends,
):
    """Distances from each point to every segment, shaped (points, segments)."""

    point_count = points.shape[0]
    segment_count = segment_starts.shape[0]
    px = np.repeat(points[:, 0], segment_count)
    py = np.repeat(points[:, 1], segment_count)
    sx = np.tile(segment_starts[:, 0], point_count)
    sy = np.tile(segment_starts[:, 1], point_count)
    ex = np.tile(segment_ends[:, 0], point_count)
    ey = np.tile(segment_ends[:, 1], point_count)
    return point_segment_distance_batch(
        px,
        py,
        sx,
        sy,
        ex,
        ey,
    ).reshape(point_count, segment_count)


def polyline_pair_minimum_distance(pa, pb) -> float:
    """Minimum distance between two polylines, zero on any intersection.

    Mirrors `branch_unit_grammar_v1._polyline_distance`: the minimum over the
    four point-to-segment distances of every segment pair, or zero when any
    pair intersects. An empty polyline yields infinity.
    """

    if pa.shape[0] < 2 or pb.shape[0] < 2:
        return float("inf")
    arrays = _segment_pair_arrays(pa, pb)
    intersects = segments_intersect_batch(
        arrays[0],
        arrays[1],
        arrays[2],
        arrays[3],
        arrays[4],
        arrays[5],
        arrays[6],
        arrays[7],
    )
    if bool(np.any(intersects)):
        return 0.0
    distances = np.minimum.reduce(
        [
            point_segment_distance_batch(
                arrays[0],
                arrays[1],
                arrays[4],
                arrays[5],
                arrays[6],
                arrays[7],
            ),
            point_segment_distance_batch(
                arrays[2],
                arrays[3],
                arrays[4],
                arrays[5],
                arrays[6],
                arrays[7],
            ),
            point_segment_distance_batch(
                arrays[4],
                arrays[5],
                arrays[0],
                arrays[1],
                arrays[2],
                arrays[3],
            ),
            point_segment_distance_batch(
                arrays[6],
                arrays[7],
                arrays[0],
                arrays[1],
                arrays[2],
                arrays[3],
            ),
        ]
    )
    return float(np.min(distances))


def global_l1_polyline_distance_batch(pa, pb, offset=0.0) -> float:
    """Mirror `global_l1_flow._polyline_distance` including the box shortcut.

    When the axis-aligned bounding boxes (with the x offset applied) are more
    than 0.18 apart, the scalar function returns that box gap instead of the
    true distance, so the batched path must preserve the same value.
    """

    a = np.asarray(pa, dtype=np.float64)
    b = np.asarray(pb, dtype=np.float64)
    a_min_x = float(a[:, 0].min())
    a_max_x = float(a[:, 0].max())
    a_min_y = float(a[:, 1].min())
    a_max_y = float(a[:, 1].max())
    b_min_x = float(b[:, 0].min()) + offset
    b_max_x = float(b[:, 0].max()) + offset
    b_min_y = float(b[:, 1].min())
    b_max_y = float(b[:, 1].max())
    gap_x = max(0.0, a_min_x - b_max_x, b_min_x - a_max_x)
    gap_y = max(0.0, a_min_y - b_max_y, b_min_y - a_max_y)
    box_gap = math.hypot(gap_x, gap_y)
    if box_gap > 0.18:
        return box_gap
    shifted = b + np.asarray([offset, 0.0], dtype=np.float64)
    return polyline_pair_minimum_distance(a, shifted)
