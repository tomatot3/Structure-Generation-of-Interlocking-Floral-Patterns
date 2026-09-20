#!/usr/bin/env python3
"""Render complete stage-5 Unit selections and unresolved conflict cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw

from render_stage4_unit_atlas import COLORS, _curve_points, _font


Point = tuple[float, float]


def _mapping(
    analysis: Mapping[str, Any],
    box: tuple[int, int, int, int],
    x_range: tuple[float, float],
) -> tuple[float, float, float, float, float]:
    x_min, x_max = x_range
    y_min = 0.0
    y_max = float(analysis["coordinate_system"]["canvas_bounds"][3])
    left, top, right, bottom = box
    margin = 16
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
    x_range: tuple[float, float],
    shift_x: float = 0.0,
) -> Point:
    origin_x, origin_y, scale, x_min, y_min = _mapping(
        analysis,
        box,
        x_range,
    )
    return (
        origin_x + (float(point[0]) + shift_x - x_min) * scale,
        origin_y + (float(point[1]) - y_min) * scale,
    )


def _draw_structure(
    draw: ImageDraw.ImageDraw,
    analysis: Mapping[str, Any],
    box: tuple[int, int, int, int],
    x_range: tuple[float, float],
    shifts: Sequence[float],
) -> None:
    for boundary_x in range(
        int(min(shifts)),
        int(max(shifts)) + 2,
    ):
        top = _xy(analysis, (boundary_x, 0.0), box, x_range)
        bottom = _xy(
            analysis,
            (
                boundary_x,
                float(analysis["coordinate_system"]["canvas_bounds"][3]),
            ),
            box,
            x_range,
        )
        draw.line((top, bottom), fill=COLORS["grid"], width=1)

    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    for shift_x in shifts:
        points = [
            _xy(analysis, point, box, x_range, shift_x)
            for point in backbone
        ]
        color = COLORS["ink"] if shift_x == 0.0 else COLORS["ghost"]
        width = 4 if shift_x == 0.0 else 2
        draw.line(points, fill=color, width=width, joint="curve")


def _draw_flower_mounts(
    draw: ImageDraw.ImageDraw,
    analysis: Mapping[str, Any],
    flower_mount_plan: Mapping[str, Any],
    box: tuple[int, int, int, int],
    x_range: tuple[float, float],
    shifts: Sequence[float],
) -> None:
    for shift_x in shifts:
        for mount in flower_mount_plan["mounts"]:
            points = [
                _xy(analysis, point, box, x_range, shift_x)
                for point in mount["centerline"]
            ]
            draw.line(
                points,
                fill=COLORS["flower_support"],
                width=4,
                joint="curve",
            )


def _draw_flowers(
    draw: ImageDraw.ImageDraw,
    analysis: Mapping[str, Any],
    box: tuple[int, int, int, int],
    x_range: tuple[float, float],
    shifts: Sequence[float],
) -> None:
    for shift_x in shifts:
        for flower in analysis["flowers"]:
            center = _xy(
                analysis,
                flower["center"],
                box,
                x_range,
                shift_x,
            )
            px = _xy(
                analysis,
                (
                    float(flower["center"][0]) + float(flower["rx"]),
                    float(flower["center"][1]),
                ),
                box,
                x_range,
                shift_x,
            )
            py = _xy(
                analysis,
                (
                    float(flower["center"][0]),
                    float(flower["center"][1]) + float(flower["ry"]),
                ),
                box,
                x_range,
                shift_x,
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


def _draw_candidate(
    draw: ImageDraw.ImageDraw,
    analysis: Mapping[str, Any],
    candidate: Mapping[str, Any],
    box: tuple[int, int, int, int],
    x_range: tuple[float, float],
    shifts: Sequence[float],
    *,
    forced_color: str | None = None,
) -> None:
    for shift_x in shifts:
        for curve in candidate["curves"]:
            points = [
                _xy(analysis, point, box, x_range, shift_x)
                for point in _curve_points(curve)
            ]
            color = forced_color or COLORS[curve["level"].lower()]
            width = 4 if curve["level"] == "L1" else 3
            draw.line(points, fill="#ffffff", width=width + 3, joint="curve")
            draw.line(points, fill=color, width=width, joint="curve")


def render_global_selection(
    analysis: Mapping[str, Any],
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
    selection: Mapping[str, Any],
    output: Path,
    *,
    triple_repeat: bool,
    flower_mount_plan: Mapping[str, Any] | None = None,
) -> None:
    width, height = (1240, 610) if triple_repeat else (940, 610)
    image = Image.new("RGB", (width, height), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    title = (
        f'阶段5全局Unit组合 · {selection["prototype_id"]}'
        f' · seed {selection["seed"]}'
    )
    draw.text(
        (22, 18),
        title,
        fill=COLORS["ink"],
        font=_font(25, bold=True),
    )
    status = (
        f'完整组合：{selection["selected_candidate_count"]}/'
        f'{selection["lane_count"]} 个枝位，无跨Unit交叉'
        if selection["feasible"]
        else "无合法完整组合：下图标出跨repeat的阻断枝组"
    )
    draw.text(
        (22, 53),
        status,
        fill=COLORS["valid"] if selection["feasible"] else COLORS["invalid"],
        font=_font(15, bold=True),
    )
    plot = (18, 88, width - 18, height - 48)
    draw.rectangle(plot, fill=COLORS["panel"], outline=COLORS["grid"], width=2)
    shifts = (-1.0, 0.0, 1.0) if triple_repeat else (0.0,)
    structure_shifts = shifts if triple_repeat else (-1.0, 0.0, 1.0)
    x_range = (-1.08, 2.08) if triple_repeat else (-0.18, 1.18)
    _draw_structure(draw, analysis, plot, x_range, structure_shifts)
    if flower_mount_plan is not None:
        _draw_flower_mounts(
            draw,
            analysis,
            flower_mount_plan,
            plot,
            x_range,
            shifts,
        )
    _draw_flowers(draw, analysis, plot, x_range, shifts)

    if selection["feasible"]:
        for candidate in selection["selected_candidates"]:
            _draw_candidate(
                draw,
                analysis,
                candidate,
                plot,
                x_range,
                shifts,
            )
        strata = " · ".join(
            f'{candidate["source_lane_id"]}:{candidate["parameter_stratum"]}'
            for candidate in selection["selected_candidates"]
        )
        draw.text(
            (22, height - 35),
            strata,
            fill=COLORS["muted"],
            font=_font(11),
        )
    else:
        candidate_by_id = {
            candidate["candidate_id"]: candidate
            for candidate in inventory["candidates"]
        }
        first_by_lane: dict[str, Mapping[str, Any]] = {}
        for candidate in inventory["candidates"]:
            first_by_lane.setdefault(
                str(candidate["source_lane_id"]),
                candidate,
            )
        for candidate in first_by_lane.values():
            l1_only = dict(candidate)
            l1_only["curves"] = [
                curve
                for curve in candidate["curves"]
                if curve["level"] == "L1"
            ]
            _draw_candidate(
                draw,
                analysis,
                l1_only,
                plot,
                x_range,
                shifts,
                forced_color=COLORS["ghost"],
            )
        blocking = selection["blocking_lane_pairs"][0]
        blocking_lanes = {
            blocking["first_lane_id"],
            blocking["second_lane_id"],
        }
        edge = next(
            row
            for row in conflict_graph["edges"]
            if {
                row["first_lane_id"],
                row["second_lane_id"],
            }
            == blocking_lanes
        )
        _draw_candidate(
            draw,
            analysis,
            candidate_by_id[edge["first_candidate_id"]],
            plot,
            x_range,
            shifts,
            forced_color=COLORS["invalid"],
        )
        _draw_candidate(
            draw,
            analysis,
            candidate_by_id[edge["second_candidate_id"]],
            plot,
            x_range,
            shifts,
            forced_color=COLORS["l3"],
        )
        draw.text(
            (22, height - 35),
            (
                f'阻断枝位：{blocking["first_lane_id"]} × '
                f'{blocking["second_lane_id"]}；所有候选组合均交叉'
            ),
            fill=COLORS["invalid"],
            font=_font(12, bold=True),
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
