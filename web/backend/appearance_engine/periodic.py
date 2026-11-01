"""Recover a repeat window from a multi-repeat appearance image.

The structural viewport supplies a search prior, not a three-equal-parts crop.
Pixels are only cropped and uniformly resized. No seam blending, repainting, or
case-specific geometry is applied. Residual edge disagreement remains measurable.
"""
from __future__ import annotations

import math
from pathlib import Path
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image


def read_viewbox(svg: str | bytes | Path) -> list[float]:
    """Read the actual generation SVG viewport; paths and SVG text are accepted."""
    if isinstance(svg, Path) or (isinstance(svg, str) and not svg.lstrip().startswith('<')):
        element = ET.parse(svg).getroot()
    else:
        element = ET.fromstring(svg)
    values = [float(v) for v in element.attrib['viewBox'].replace(',', ' ').split()]
    if len(values) != 4 or not all(math.isfinite(v) for v in values) or min(values[2:]) <= 0:
        raise ValueError('The generation SVG needs a finite, positive viewBox.')
    return values


def _ink(rgb: np.ndarray) -> np.ndarray:
    # Colored ornament is detectable even where its blue channel is light.
    return 1.0 - rgb.min(axis=2)


def _repeat_error(ink: np.ndarray, period: int) -> float:
    a, b = ink[:, :-period], ink[:, period:]
    return float(np.abs(a - b).sum() / max(float(np.maximum(a, b).sum()), 1e-9))


def edge_diagnostics(image: Image.Image) -> dict:
    """Measure actual adjacent end columns, including foreground color and mass.

    Equal endpoints alone do not establish tangent continuity or visual quality.
    These measurements are observations, never a visual pass/fail decision.
    """
    rgb = np.asarray(image.convert('RGB'), dtype=np.float32) / 255.0
    left, right = rgb[:, 0], rgb[:, -1]
    il, ir = _ink(rgb[:, :1])[:, 0], _ink(rgb[:, -1:])[:, 0]
    mask = np.maximum(il, ir) > .08
    foreground = int(mask.sum())
    color = np.abs(left - right)
    weights = np.maximum(il, ir)
    lmask, rmask = il > .15, ir > .15
    return {
        'edge_rgb_mae_255': float(color.mean() * 255),
        'foreground_rgb_mae_255': float(color[mask].mean() * 255) if foreground else 0.0,
        'foreground_rgb_p95_255': float(np.percentile(color[mask].mean(axis=1), 95) * 255) if foreground else 0.0,
        'foreground_rows': foreground,
        'ink_profile_relative_difference': float(np.abs(il - ir).sum() / max(float(weights.sum()), 1e-9)),
        'left_foreground_rows': int(lmask.sum()),
        'right_foreground_rows': int(rmask.sum()),
        'one_sided_foreground_rows': int(np.count_nonzero(lmask ^ rmask)),
        'foreground_overlap_rows': int(np.count_nonzero(lmask & rmask)),
    }


def extract_periodic_tile(
    image: Image.Image,
    source_viewbox: list[float] | tuple[float, ...] | None = None,
    expected_period: float | None = None,
    output_width: int | None = None,
    structural_period: float = 1.0,
) -> tuple[Image.Image, dict]:
    """Return an unblended repeat tile and explicit registration metadata.

    source_viewbox is the viewBox of the image-generation input SVG, in its
    original coordinates. structural_period is in the same coordinates.
    expected_period, when needed without a viewport, is measured in image pixels.

    Search whole-image repetitions first, then refine width and phase near the
    central structural unit. The finite phase search preserves its object layout;
    a local seam minimum cannot select a different flower or a half-period motif.
    The caller must preserve the input image and consume the returned transform.
    """
    image = image.convert('RGB')
    width, height = image.size
    if min(width, height) < 16 or structural_period <= 0:
        raise ValueError('Repeat extraction needs a nonempty image and a positive structural period.')
    view = None if source_viewbox is None else [float(v) for v in source_viewbox]
    if view is not None:
        if len(view) != 4 or not all(math.isfinite(v) for v in view) or min(view[2:]) <= 0:
            raise ValueError('Invalid source viewBox.')
        nominal_period = width * structural_period / view[2]
        # Choose the full structural unit closest to the center of the source.
        center_source = view[0] + view[2] / 2
        unit_index = round(center_source / structural_period - .5)
        nominal_origin = (unit_index * structural_period - view[0]) * width / view[2]
    else:
        if expected_period is None:
            raise ValueError('Provide the generation SVG viewBox or an expected pixel period.')
        nominal_period = float(expected_period)
        nominal_origin = (width - nominal_period) / 2
        unit_index = 0
    if expected_period is not None:
        nominal_period = float(expected_period)
    if not math.isfinite(nominal_period) or not 12 <= nominal_period <= width / 1.5:
        raise ValueError('The source must contain enough pixels for at least 1.5 repeats.')

    rgb = np.asarray(image, dtype=np.float32) / 255.0
    ink = _ink(rgb)
    if float(ink.mean()) < .001:
        raise ValueError('No foreground was found from which to measure a repeat.')
    # Work at an image-derived scale, keeping more than 200 samples per repeat.
    down = max(1.0, nominal_period / 240.0)
    small_width = max(16, round(width / down))
    small = cv2.resize(ink, (small_width, max(16, round(height / down))), interpolation=cv2.INTER_AREA)
    pixel_scale = width / small_width
    lower = max(4, round(nominal_period * .85 / pixel_scale))
    upper = min(small_width - 4, round(nominal_period * 1.15 / pixel_scale))
    global_scores = [(_repeat_error(small, p), p) for p in range(lower, upper + 1)]
    global_score, coarse_period = min(global_scores)
    global_period = coarse_period * pixel_scale
    # Local drift in generated copies can differ from the full-image optimum.
    # Refine only in its neighboring basin, not arbitrary widths with easy edges.
    radius = max(3, math.ceil(nominal_period * .02))
    periods = range(max(8, round(global_period) - radius), min(width - 2, round(global_period) + radius) + 1)
    phase_radius = nominal_period * .10
    window = max(3, round(nominal_period * .016)) | 1
    smooth = cv2.GaussianBlur(ink, (0, 0), max(.6, nominal_period / 700))
    choices = []
    for period in periods:
        a, b = smooth[:, :-period], smooth[:, period:]
        denominator = np.maximum(a, b).sum(axis=0)
        column = np.abs(a - b).sum(axis=0) / np.maximum(denominator, 1e-8)
        neighborhood = cv2.blur(column[None, :], (window, 1)).ravel()
        lo = max(window, math.ceil(nominal_origin - phase_radius))
        hi = min(width - period - window, math.floor(nominal_origin + phase_radius))
        if hi < lo:
            continue
        x = np.arange(lo, hi + 1)
        # Direct end-column mismatch matters as well as matching neighborhoods.
        # Compare the columns that really become adjacent after the crop.
        l, r = rgb[:, x], rgb[:, x + period - 1]
        active = np.maximum(ink[:, x], ink[:, x + period - 1])
        edge_color = (np.abs(l - r).mean(axis=2) * active).sum(axis=0) / np.maximum(active.sum(axis=0), 1e-8)
        edge_shape = np.abs(ink[:, x] - ink[:, x + period - 1]).sum(axis=0) / np.maximum(active.sum(axis=0), 1e-8)
        # Foreground-normalized neighborhood error avoids choosing blank margins.
        # The small phase prior resolves near-ties toward the structural origin.
        score = neighborhood[x] + .25 * edge_shape + .25 * edge_color + .015 * np.abs(x - nominal_origin) / nominal_period
        index = int(np.argmin(score))
        choices.append((float(score[index]), int(x[index]), period, float(neighborhood[x[index]])))
    if not choices:
        raise ValueError('The source viewport has no complete central repeat window.')
    score, start, period, seam_error = min(choices)
    native = image.crop((start, 0, start + period, height))
    out_width = period if output_width is None else int(output_width)
    if out_width < 1:
        raise ValueError('Output width must be positive.')
    out_height = max(1, round(height * out_width / period))
    tile = native if (out_width, out_height) == native.size else native.resize((out_width, out_height), Image.Resampling.LANCZOS)
    sx, sy = out_width / period, out_height / height
    metadata = {
        'method': 'image-repeat-window-v1',
        'source_size': [width, height],
        'source_viewbox': view,
        'structural_period': structural_period,
        'central_unit_index': unit_index,
        'expected_period_px': nominal_period,
        'global_period_px': global_period,
        'period_px': period,
        'crop_box': [start, 0, start + period, height],
        'nominal_origin_px': nominal_origin,
        'phase_shift_px': start - nominal_origin,
        'phase_in_period': (start - nominal_origin) / period,
        'output_size': [out_width, out_height],
        'image_to_tile': [[sx, 0.0, -start * sx], [0.0, sy, 0.0], [0.0, 0.0, 1.0]],
        'global_repeat_error': global_score,
        'seam_neighborhood_error': seam_error,
        'seam_selection_score': score,
        'native_edge_diagnostics': edge_diagnostics(native),
        'output_edge_diagnostics': edge_diagnostics(tile),
        'resampling': 'crop only' if tile is native else 'crop then aspect-preserving Lanczos resize; height rounded to a pixel',
        'visual_status': 'VISUAL_REVIEW_PENDING',
    }
    if view is not None:
        # X pitch is calibrated to the measured image repeat. Anchor at the
        # viewport-derived central source origin. Y uses the full source viewport,
        # including top padding: it must not reuse import_structure's tight bbox.
        offset = (nominal_origin - start) * sx - unit_index * out_width
        metadata['source_to_tile'] = [
            [out_width / structural_period, 0.0, offset],
            [0.0, out_height / view[3], -view[1] * out_height / view[3]],
            [0.0, 0.0, 1.0],
        ]
        metadata['source_transform_note'] = 'X uses the measured repeat pitch, anchored at the central source origin; Y maps the original generation viewBox.'
    return tile, metadata
