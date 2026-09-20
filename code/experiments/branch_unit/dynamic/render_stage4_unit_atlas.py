#!/usr/bin/env python3
"""Render complete stage-4 Unit candidates without globally selecting them."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont


COLORS = {
    "background": "#f1efe9",
    "panel": "#ffffff",
    "ink": "#17242d",
    "muted": "#68757d",
    "grid": "#cbd3d8",
    "ghost": "#c2c9ce",
    "flower": "#b53372",
    "flower_fill": "#fff7fb",
    "flower_support": "#4f7d35",
    "l1": "#087c94",
    "l2": "#188566",
    "l3": "#d27918",
    "valid": "#23945f",
    "invalid": "#c34a42",
}
Point = tuple[float, float]


class UnitAtlasRenderError(RuntimeError):
    """The stage-4 candidate atlas cannot be rendered."""


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    path = Path(
        "DejaVuSans-Bold.ttf"
        if bold
        else "DejaVuSans.ttf"
    )
    if not path.is_file():
        raise UnitAtlasRenderError(f"required font is missing: {path}")
    return ImageFont.truetype(str(path), size)


def _point(value: Sequence[float]) -> Point:
    return float(value[0]), float(value[1])


def _sample_cubic(
    segment: Mapping[str, Sequence[float]],
    count: int = 28,
) -> list[Point]:
    p0, p1, p2, p3 = (
        _point(segment[key]) for key in ("p0", "p1", "p2", "p3")
    )
    points: list[Point] = []
    for index in range(count + 1):
        t = index / count
        u = 1.0 - t
        points.append(
            (
                u**3 * p0[0]
                + 3 * u * u * t * p1[0]
                + 3 * u * t * t * p2[0]
                + t**3 * p3[0],
                u**3 * p0[1]
                + 3 * u * u * t * p1[1]
                + 3 * u * t * t * p2[1]
                + t**3 * p3[1],
            )
        )
    return points


def _curve_points(curve: Mapping[str, Any]) -> list[Point]:
    points: list[Point] = []
    for segment_index, segment in enumerate(curve["cubic_segments"]):
        sampled = _sample_cubic(segment)
        if segment_index:
            sampled = sampled[1:]
        points.extend(sampled)
    return points


def _mapping(
    analysis: Mapping[str, Any],
    box: tuple[int, int, int, int],
) -> tuple[float, float, float, float, float]:
    x_min, x_max = -0.18, 1.18
    y_min = 0.0
    y_max = float(analysis["coordinate_system"]["canvas_bounds"][3])
    left, top, right, bottom = box
    margin = 14
    scale = min(
        (right - left - 2 * margin) / (x_max - x_min),
        (bottom - top - 2 * margin) / (y_max - y_min),
    )
    used_width = (x_max - x_min) * scale
    used_height = (y_max - y_min) * scale
    origin_x = left + (right - left - used_width) * 0.5
    origin_y = top + (bottom - top - used_height) * 0.5
    return origin_x, origin_y, scale, x_min, y_min


def _xy(
    analysis: Mapping[str, Any],
    point: Sequence[float],
    box: tuple[int, int, int, int],
) -> Point:
    origin_x, origin_y, scale, x_min, y_min = _mapping(analysis, box)
    return (
        origin_x + (float(point[0]) - x_min) * scale,
        origin_y + (float(point[1]) - y_min) * scale,
    )


def _draw_context(
    draw: ImageDraw.ImageDraw,
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    box: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = box
    draw.rectangle(box, fill=COLORS["panel"])
    x0 = _xy(analysis, (0.0, 0.0), box)
    x1 = _xy(
        analysis,
        (0.0, float(analysis["coordinate_system"]["canvas_bounds"][3])),
        box,
    )
    y0 = _xy(analysis, (1.0, 0.0), box)
    y1 = _xy(
        analysis,
        (1.0, float(analysis["coordinate_system"]["canvas_bounds"][3])),
        box,
    )
    draw.line((x0, x1), fill=COLORS["grid"], width=1)
    draw.line((y0, y1), fill=COLORS["grid"], width=1)

    backbone = [
        _xy(analysis, row["point"], box)
        for row in analysis["backbone"]["samples"]
    ]
    draw.line(backbone, fill=COLORS["ink"], width=3, joint="curve")
    for flower in analysis["flowers"]:
        center = _xy(analysis, flower["center"], box)
        px = _xy(
            analysis,
            (
                float(flower["center"][0]) + float(flower["rx"]),
                float(flower["center"][1]),
            ),
            box,
        )
        py = _xy(
            analysis,
            (
                float(flower["center"][0]),
                float(flower["center"][1]) + float(flower["ry"]),
            ),
            box,
        )
        rx = abs(px[0] - center[0])
        ry = abs(py[1] - center[1])
        draw.ellipse(
            (
                center[0] - rx,
                center[1] - ry,
                center[0] + rx,
                center[1] + ry,
            ),
            fill=COLORS["flower_fill"],
            outline=COLORS["flower"],
            width=2,
        )

    for lane in plan["lanes"]:
        if lane["slot_id"] == candidate["source_lane_id"]:
            continue
        points: list[Point] = []
        for segment_index, segment in enumerate(lane["segments"]):
            sampled = _sample_cubic(segment, 20)
            if segment_index:
                sampled = sampled[1:]
            points.extend(_xy(analysis, point, box) for point in sampled)
        draw.line(points, fill=COLORS["ghost"], width=2, joint="curve")

    for curve in candidate["curves"]:
        color = COLORS[curve["level"].lower()]
        points = [
            _xy(analysis, point, box)
            for point in _curve_points(curve)
        ]
        draw.line(points, fill="#ffffff", width=6, joint="curve")
        draw.line(points, fill=color, width=3, joint="curve")
        root = points[0]
        if curve["level"] != "L1":
            draw.ellipse(
                (
                    root[0] - 3,
                    root[1] - 3,
                    root[0] + 3,
                    root[1] + 3,
                ),
                fill="#ffffff",
                outline=color,
                width=2,
            )

    status_color = (
        COLORS["valid"]
        if candidate["intrinsic_diagnostics"]["valid"]
        else COLORS["invalid"]
    )
    draw.rectangle(box, outline=status_color, width=3)
    title = (
        f'{candidate["grammar_id"]} · {candidate["parameter_stratum"]}'
        f' · L2={candidate["hierarchy"]["l2_count"]}'
        f' L3={candidate["hierarchy"]["l3_count"]}'
    )
    draw.text(
        (left + 8, top + 6),
        title,
        fill=COLORS["ink"],
        font=_font(13, bold=True),
    )
    status = (
        "合法候选"
        if candidate["intrinsic_diagnostics"]["valid"]
        else "保留的非法候选："
        + ",".join(
            issue["code"]
            for issue in candidate["intrinsic_diagnostics"]["issues"]
        )
    )
    draw.text(
        (left + 8, bottom - 25),
        status,
        fill=status_color,
        font=_font(11),
    )


def render_lane_context_atlas(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    inventory: Mapping[str, Any],
    output: Path,
) -> None:
    candidates_by_lane: dict[str, list[Mapping[str, Any]]] = {}
    for candidate in inventory["candidates"]:
        candidates_by_lane.setdefault(
            str(candidate["source_lane_id"]),
            [],
        ).append(candidate)
    columns = 6
    tile_width = 300
    tile_height = 245
    left_label = 185
    header = 92
    row_count = len(inventory["lanes"])
    width = left_label + columns * tile_width + 24
    height = header + row_count * tile_height + 42
    image = Image.new("RGB", (width, height), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text(
        (24, 18),
        (
            f'阶段4完整Unit候选图谱 · {inventory["prototype_id"]}'
            f' · seed {inventory["seed"]}'
        ),
        fill=COLORS["ink"],
        font=_font(25, bold=True),
    )
    draw.text(
        (24, 55),
        "每格独立显示一个候选；其他L1仅作灰色上下文，不代表全局组合。",
        fill=COLORS["muted"],
        font=_font(15),
    )
    for row_index, lane_row in enumerate(inventory["lanes"]):
        y = header + row_index * tile_height
        draw.text(
            (18, y + 22),
            str(lane_row["source_lane_id"]),
            fill=COLORS["ink"],
            font=_font(18, bold=True),
        )
        draw.text(
            (18, y + 52),
            str(lane_row["role"]),
            fill=COLORS["muted"],
            font=_font(13),
        )
        draw.text(
            (18, y + 78),
            (
                f'候选 {lane_row["candidate_count"]}\n'
                f'合法 {lane_row["feasible_candidate_count"]}'
            ),
            fill=COLORS["valid"],
            font=_font(13, bold=True),
            spacing=5,
        )
        lane_candidates = candidates_by_lane[lane_row["source_lane_id"]]
        for column_index, candidate in enumerate(lane_candidates):
            box = (
                left_label + column_index * tile_width,
                y,
                left_label + (column_index + 1) * tile_width - 8,
                y + tile_height - 8,
            )
            _draw_context(draw, analysis, plan, candidate, box)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def render_role_grammar_atlas(
    candidates: Sequence[Mapping[str, Any]],
    output: Path,
) -> None:
    """Show every deterministic grammar/stratum row in a neutral Unit frame."""

    representatives: dict[tuple[str, str], Mapping[str, Any]] = {}
    for candidate in candidates:
        key = (
            str(candidate["grammar_id"]),
            str(candidate["parameter_stratum"]),
        )
        representatives.setdefault(key, candidate)
    ordered = [representatives[key] for key in sorted(representatives)]
    columns = 4
    tile_width = 390
    tile_height = 300
    rows = math.ceil(len(ordered) / columns)
    image = Image.new(
        "RGB",
        (columns * tile_width + 30, rows * tile_height + 110),
        COLORS["background"],
    )
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text(
        (24, 18),
        "阶段4 Unit语法图谱",
        fill=COLORS["ink"],
        font=_font(27, bold=True),
    )
    draw.text(
        (24, 58),
        "每个语法/参数层只取确定性枚举中的首个实例作结构说明；完整候选见各任务上下文图谱。",
        fill=COLORS["muted"],
        font=_font(14),
    )
    for item_index, candidate in enumerate(ordered):
        column = item_index % columns
        row = item_index // columns
        box = (
            15 + column * tile_width,
            95 + row * tile_height,
            15 + (column + 1) * tile_width - 10,
            95 + (row + 1) * tile_height - 10,
        )
        left, top, right, bottom = box
        draw.rectangle(box, fill=COLORS["panel"], outline=COLORS["grid"], width=2)
        all_points = [
            point
            for curve in candidate["curves"]
            for point in _curve_points(curve)
        ]
        min_x = min(point[0] for point in all_points)
        max_x = max(point[0] for point in all_points)
        min_y = min(point[1] for point in all_points)
        max_y = max(point[1] for point in all_points)
        span_x = max(0.05, max_x - min_x)
        span_y = max(0.05, max_y - min_y)
        scale = min((right - left - 44) / span_x, (bottom - top - 88) / span_y)

        def normalized(point: Point) -> Point:
            return (
                left + 22 + (point[0] - min_x) * scale,
                top + 48 + (point[1] - min_y) * scale,
            )

        for curve in candidate["curves"]:
            color = COLORS[curve["level"].lower()]
            points = [normalized(point) for point in _curve_points(curve)]
            draw.line(points, fill="#ffffff", width=8, joint="curve")
            draw.line(points, fill=color, width=4, joint="curve")
        draw.text(
            (left + 12, top + 10),
            f'{candidate["grammar_id"]} · {candidate["parameter_stratum"]}',
            fill=COLORS["ink"],
            font=_font(16, bold=True),
        )
        draw.text(
            (left + 12, bottom - 30),
            (
                f'{candidate["role"]} · '
                f'L2={candidate["hierarchy"]["l2_count"]} '
                f'L3={candidate["hierarchy"]["l3_count"]}'
            ),
            fill=COLORS["muted"],
            font=_font(12),
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def render_fixed_baseline_pair(
    fixed_image: Path,
    stage4_atlas: Path,
    output: Path,
    *,
    seed: int,
) -> None:
    with Image.open(fixed_image) as source:
        fixed = source.convert("RGB")
    with Image.open(stage4_atlas) as source:
        atlas = source.convert("RGB")
    canvas = Image.new("RGB", (2000, 1040), COLORS["background"])
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (30, 18),
        f"proto_sw_1_3固定视觉能力与阶段4候选对照 · seed {seed}",
        fill=COLORS["ink"],
        font=_font(26, bold=True),
    )
    draw.text(
        (30, 58),
        "左：冻结固定版完整枝组；右：同种子的全部动态Unit候选图谱。此图不执行优选。",
        fill=COLORS["muted"],
        font=_font(15),
    )
    fixed.thumbnail((950, 900), Image.Resampling.LANCZOS)
    atlas.thumbnail((950, 900), Image.Resampling.LANCZOS)
    canvas.paste(fixed, (25, 110))
    canvas.paste(atlas, (1025, 110))
    draw.rectangle((25, 110, 975, 1015), outline=COLORS["grid"], width=2)
    draw.rectangle((1025, 110, 1975, 1015), outline=COLORS["grid"], width=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def render_contact_sheet(
    paths: Sequence[Path],
    output: Path,
    *,
    columns: int = 3,
    cell_size: tuple[int, int] = (620, 480),
) -> None:
    if not paths:
        raise UnitAtlasRenderError("contact sheet path list is empty")
    rows = math.ceil(len(paths) / columns)
    width = columns * cell_size[0]
    height = rows * cell_size[1]
    sheet = Image.new("RGB", (width, height), COLORS["background"])
    for index, path in enumerate(paths):
        with Image.open(path) as source:
            image = source.convert("RGB")
        image.thumbnail(
            (cell_size[0] - 18, cell_size[1] - 18),
            Image.Resampling.LANCZOS,
        )
        x = (index % columns) * cell_size[0] + (cell_size[0] - image.width) // 2
        y = (index // columns) * cell_size[1] + (cell_size[1] - image.height) // 2
        sheet.paste(image, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
