#!/usr/bin/env python3
"""Render clean and diagnostic stage-3B L1 flow-lane review images."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1500
HEIGHT = 900
PANEL = (34, 78, 1466, 846)
COLORS = {
    "background": "#f2f0ea",
    "panel": "#ffffff",
    "ink": "#18242d",
    "muted": "#66737c",
    "grid": "#cbd3d8",
    "backbone": "#17242d",
    "ghost": "#b7c0c6",
    "flower": "#b53372",
    "flower_fill": "#fff7fb",
    "reserve": "#e8a8ca",
    "primary_sweep": "#17856f",
    "balance": "#2f6fb2",
    "frontier": "#7953aa",
    "flower_support": "#dc7b08",
    "terminal_flower_support": "#c44b45",
    "fixed_warp": "#087c94",
}


class L1FlowRenderError(RuntimeError):
    """The formal review image cannot be rendered."""


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    path = Path(
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    )
    if not path.is_file():
        raise L1FlowRenderError(f"required review font is missing: {path}")
    return ImageFont.truetype(str(path), size)


def _color(lane: Mapping[str, Any]) -> str:
    if lane["source_channel"] == "fixed_warp_visual_prior":
        return COLORS["fixed_warp"]
    return COLORS[str(lane["role"])]


def _repeat_width(plan: Mapping[str, Any]) -> float:
    return float(plan.get("repeat_layout", {}).get("physical_repeat_width_scale", 1.0))


def _world_point(point: Sequence[float], repeat_width: float, offset: float = 0.0) -> tuple[float, float]:
    return (float(point[0]) + offset) * repeat_width, float(point[1])


def _bounds(
    analysis: Mapping[str, Any],
    repeat_count: int,
    repeat_width: float = 1.0,
) -> tuple[float, float, float, float]:
    height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    if repeat_count == 1:
        return -0.34 * repeat_width, 1.34 * repeat_width, 0.0, height
    return -1.08 * repeat_width, 2.08 * repeat_width, 0.0, height


def _xy(
    analysis: Mapping[str, Any],
    point: Sequence[float],
    repeat_count: int,
    repeat_width: float = 1.0,
) -> tuple[float, float]:
    x_min, x_max, y_min, y_max = _bounds(analysis, repeat_count, repeat_width)
    left, top, right, bottom = PANEL
    margin_x = 34
    margin_y = 34
    scale = min(
        (right - left - 2 * margin_x) / (x_max - x_min),
        (bottom - top - 2 * margin_y) / (y_max - y_min),
    )
    used_width = (x_max - x_min) * scale
    used_height = (y_max - y_min) * scale
    origin_x = left + (right - left - used_width) * 0.5
    origin_y = top + (bottom - top - used_height) * 0.5
    return (
        origin_x + (float(point[0]) - x_min) * scale,
        origin_y + (float(point[1]) - y_min) * scale,
    )


def _sample_cubic(segment: Mapping[str, Sequence[float]], count: int = 42) -> list[tuple[float, float]]:
    p0 = tuple(float(value) for value in segment["p0"])
    p1 = tuple(float(value) for value in segment["p1"])
    p2 = tuple(float(value) for value in segment["p2"])
    p3 = tuple(float(value) for value in segment["p3"])
    points: list[tuple[float, float]] = []
    for index in range(count + 1):
        t = index / count
        u = 1.0 - t
        points.append(
            (
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return points


def _lane_points(
    lane: Mapping[str, Any],
    offset: float,
    repeat_width: float = 1.0,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for segment_index, segment in enumerate(lane["segments"]):
        sampled = _sample_cubic(segment)
        if segment_index:
            sampled = sampled[1:]
        points.extend(_world_point(point, repeat_width, offset) for point in sampled)
    return points


def _flower_mount_lanes(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    flower_plan = plan.get("flower_mount_plan")
    if not isinstance(flower_plan, Mapping):
        return []
    role = (
        "flower_support"
        if flower_plan.get("morphology_family") == "SW-1_valley_filling"
        else "terminal_flower_support"
    )
    return [
        {
            "segments": mount["cubic_segments"],
            "role": role,
            "source_channel": "flower_mount_first",
            "root_s": mount["root_s"],
            "slot_id": mount["mount_id"],
        }
        for mount in flower_plan.get("mounts", [])
    ]


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    points: Sequence[tuple[float, float]],
    color: str,
) -> None:
    if len(points) < 4:
        raise L1FlowRenderError("lane arrow needs at least four sampled points")
    end = points[-1]
    previous = points[-4]
    angle = math.atan2(end[1] - previous[1], end[0] - previous[0])
    size = 12
    draw.polygon(
        [
            end,
            (
                end[0] - size * math.cos(angle - 0.48),
                end[1] - size * math.sin(angle - 0.48),
            ),
            (
                end[0] - size * math.cos(angle + 0.48),
                end[1] - size * math.sin(angle + 0.48),
            ),
        ],
        fill=color,
    )


def _offsets(repeat_count: int) -> tuple[float, ...]:
    return (0.0,) if repeat_count == 1 else (-1.0, 0.0, 1.0)


def render_png(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    output: Path,
    *,
    repeat_count: int = 1,
    debug: bool = False,
) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["background"])
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(PANEL, radius=18, fill=COLORS["panel"], outline=COLORS["grid"], width=2)
    mode = "三周期" if repeat_count == 3 else "单周期"
    suffix = " · 诊断" if debug else ""
    draw.text(
        (42, 23),
        f'阶段3B · 全局L1流线 · {plan["prototype_id"]} · seed {plan["seed"]} · {mode}{suffix}',
        font=_font(25, bold=True),
        fill=COLORS["ink"],
    )
    draw.text(
        (1130, 30),
        "先挂接花枝，再规划普通L1",
        font=_font(16, bold=True),
        fill="#a33a35",
    )

    height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    repeat_width = _repeat_width(plan)
    boundary_values = (0.0, 1.0) if repeat_count == 1 else (-1.0, 0.0, 1.0, 2.0)
    for x_value in boundary_values:
        draw.line(
            [
                _xy(analysis, (x_value * repeat_width, 0.0), repeat_count, repeat_width),
                _xy(analysis, (x_value * repeat_width, height), repeat_count, repeat_width),
            ],
            fill=COLORS["grid"],
            width=2,
        )

    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    flower_mount_lanes = _flower_mount_lanes(plan)
    for offset in _offsets(repeat_count):
        backbone_points = [
            _xy(
                analysis,
                _world_point(point, repeat_width, offset),
                repeat_count,
                repeat_width,
            )
            for point in backbone
        ]
        draw.line(backbone_points, fill=COLORS["backbone"], width=5, joint="curve")

        for mount_lane in flower_mount_lanes:
            color = COLORS[str(mount_lane["role"])]
            world = _lane_points(mount_lane, offset, repeat_width)
            screen = [_xy(analysis, point, repeat_count, repeat_width) for point in world]
            draw.line(screen, fill=color + "30", width=20, joint="curve")
            draw.line(screen, fill=color, width=6, joint="curve")
            root = screen[0]
            draw.ellipse(
                (root[0] - 6, root[1] - 6, root[0] + 6, root[1] + 6),
                fill="#ffffff",
                outline=color,
                width=3,
            )

        for flower in analysis["flowers"]:
            center = _world_point(flower["center"], repeat_width, offset)
            center_px = _xy(analysis, center, repeat_count, repeat_width)
            rx_px = abs(
                _xy(
                    analysis,
                    (center[0] + float(flower["rx"]) * repeat_width, center[1]),
                    repeat_count,
                    repeat_width,
                )[0]
                - center_px[0]
            )
            ry_px = abs(
                _xy(
                    analysis,
                    (center[0], center[1] + float(flower["ry"])),
                    repeat_count,
                    repeat_width,
                )[1]
                - center_px[1]
            )
            draw.ellipse(
                (
                    center_px[0] - rx_px,
                    center_px[1] - ry_px,
                    center_px[0] + rx_px,
                    center_px[1] + ry_px,
                ),
                fill=COLORS["flower_fill"],
                outline=COLORS["flower"],
                width=3,
            )
            if debug:
                reserve_rx = rx_px * float(flower["protection_rx"]) / float(flower["rx"])
                reserve_ry = ry_px * float(flower["protection_ry"]) / float(flower["ry"])
                draw.ellipse(
                    (
                        center_px[0] - reserve_rx,
                        center_px[1] - reserve_ry,
                        center_px[0] + reserve_rx,
                        center_px[1] + reserve_ry,
                    ),
                    outline=COLORS["reserve"],
                    width=2,
                )

    for lane in plan["lanes"]:
        color = _color(lane)
        for offset in _offsets(repeat_count):
            world = _lane_points(lane, offset, repeat_width)
            screen = [_xy(analysis, point, repeat_count, repeat_width) for point in world]
            draw.line(screen, fill=color + "30", width=20, joint="curve")
            draw.line(screen, fill=color, width=5, joint="curve")
            root = screen[0]
            draw.ellipse((root[0] - 6, root[1] - 6, root[0] + 6, root[1] + 6), fill="#ffffff", outline=color, width=3)
            _draw_arrow(draw, screen, color)
            if debug and offset == 0.0:
                draw.text(
                    (root[0] + 8, root[1] - 22),
                    f'{lane["slot_id"]} · s={float(lane["root_s"]):.3f}',
                    font=_font(13, bold=True),
                    fill=color,
                )

    role_counts = "  ".join(
        f"{role}:{count}" for role, count in plan["role_counts"].items()
    )
    draw.text(
        (48, 858),
        (
            f'挂接枝={len(flower_mount_lanes)}  普通L1={len(plan["lanes"])}  '
            f'{role_counts}  ·  状态：待人工视觉验收'
        ),
        font=_font(15),
        fill=COLORS["muted"],
    )
    image.save(output)


def _svg_path(
    lane: Mapping[str, Any],
    analysis: Mapping[str, Any],
    repeat_count: int,
    offset: float,
    repeat_width: float = 1.0,
) -> str:
    commands: list[str] = []
    for segment_index, segment in enumerate(lane["segments"]):
        points = {
            key: _xy(
                analysis,
                _world_point(value, repeat_width, offset),
                repeat_count,
                repeat_width,
            )
            for key, value in segment.items()
        }
        if segment_index == 0:
            commands.append(f'M {points["p0"][0]:.2f} {points["p0"][1]:.2f}')
        commands.append(
            f'C {points["p1"][0]:.2f} {points["p1"][1]:.2f} '
            f'{points["p2"][0]:.2f} {points["p2"][1]:.2f} '
            f'{points["p3"][0]:.2f} {points["p3"][1]:.2f}'
        )
    return " ".join(commands)


def render_svg(
    analysis: Mapping[str, Any],
    plan: Mapping[str, Any],
    output: Path,
    *,
    repeat_count: int = 1,
) -> None:
    title = html.escape(
        f'阶段3B 全局L1流线 {plan["prototype_id"]} seed {plan["seed"]}'
    )
    rows = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="1500" height="900" fill="#f2f0ea"/>',
        '<rect x="34" y="78" width="1432" height="768" rx="18" fill="#fff" stroke="#cbd3d8" stroke-width="2"/>',
        f'<text x="42" y="50" font-family="Microsoft YaHei" font-size="25" font-weight="700" fill="#18242d">{title}</text>',
    ]
    height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    repeat_width = _repeat_width(plan)
    boundaries = (0.0, 1.0) if repeat_count == 1 else (-1.0, 0.0, 1.0, 2.0)
    for x_value in boundaries:
        p0 = _xy(analysis, (x_value * repeat_width, 0.0), repeat_count, repeat_width)
        p1 = _xy(analysis, (x_value * repeat_width, height), repeat_count, repeat_width)
        rows.append(
            f'<line x1="{p0[0]:.2f}" y1="{p0[1]:.2f}" x2="{p1[0]:.2f}" y2="{p1[1]:.2f}" stroke="#cbd3d8" stroke-width="2"/>'
        )
    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    flower_mount_lanes = _flower_mount_lanes(plan)
    for offset in _offsets(repeat_count):
        points = " ".join(
            f"{x:.2f},{y:.2f}"
            for x, y in (
                _xy(
                    analysis,
                    _world_point(point, repeat_width, offset),
                    repeat_count,
                    repeat_width,
                )
                for point in backbone
            )
        )
        rows.append(
            f'<polyline points="{points}" fill="none" stroke="#17242d" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
        )
        for mount_lane in flower_mount_lanes:
            color = COLORS[str(mount_lane["role"])]
            path = _svg_path(mount_lane, analysis, repeat_count, offset, repeat_width)
            rows.append(
                f'<path d="{path}" fill="none" stroke="{color}" stroke-opacity="0.18" stroke-width="20" stroke-linecap="round" stroke-linejoin="round"/>'
            )
            rows.append(
                f'<path d="{path}" fill="none" stroke="{color}" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
            )
        for flower in analysis["flowers"]:
            center = _xy(
                analysis,
                _world_point(flower["center"], repeat_width, offset),
                repeat_count,
                repeat_width,
            )
            rx = abs(
                _xy(
                    analysis,
                    (
                        (float(flower["center"][0]) + offset + float(flower["rx"])) * repeat_width,
                        float(flower["center"][1]),
                    ),
                    repeat_count,
                    repeat_width,
                )[0]
                - center[0]
            )
            ry = abs(
                _xy(
                    analysis,
                    (
                        (float(flower["center"][0]) + offset) * repeat_width,
                        float(flower["center"][1]) + float(flower["ry"]),
                    ),
                    repeat_count,
                    repeat_width,
                )[1]
                - center[1]
            )
            rows.append(
                f'<ellipse cx="{center[0]:.2f}" cy="{center[1]:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" fill="#fff7fb" stroke="#b53372" stroke-width="3"/>'
            )
    for lane in plan["lanes"]:
        color = _color(lane)
        for offset in _offsets(repeat_count):
            path = _svg_path(lane, analysis, repeat_count, offset, repeat_width)
            rows.append(
                f'<path d="{path}" fill="none" stroke="{color}" stroke-opacity="0.18" stroke-width="20" stroke-linecap="round" stroke-linejoin="round"/>'
            )
            rows.append(
                f'<path d="{path}" fill="none" stroke="{color}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
            )
    rows.append("</svg>")
    output.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")


def render_contact_sheet(
    image_paths: Iterable[Path],
    output: Path,
    *,
    columns: int,
    max_cell_width: int = 640,
) -> None:
    paths = list(image_paths)
    if not paths:
        raise L1FlowRenderError("contact sheet input is empty")
    images = [Image.open(path).convert("RGB") for path in paths]
    ratio = max_cell_width / images[0].width
    cell_width = max_cell_width
    cell_height = round(images[0].height * ratio)
    rows = math.ceil(len(images) / columns)
    sheet = Image.new(
        "RGB",
        (columns * cell_width, rows * cell_height),
        COLORS["background"],
    )
    for index, image in enumerate(images):
        resized = image.resize((cell_width, cell_height), Image.Resampling.LANCZOS)
        sheet.paste(
            resized,
            ((index % columns) * cell_width, (index // columns) * cell_height),
        )
    sheet.save(output)

