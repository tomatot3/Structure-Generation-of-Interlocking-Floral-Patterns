#!/usr/bin/env python3
"""Export saved batch results as vector SVG (triple repeat by default)."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from render_stage4_unit_atlas import COLORS


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_DIR = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_batch_v1"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "dynamic_branch_batch_500_svg"

ROLE_COLORS = {
    "backbone": "#0000ff",
    "primary_branch": "#ff9900",
    "secondary_branch": "#00ffff",
    "flower_support": "#007800",
    "flower_anchor": "#ff0000",
    "unit_boundary": "#000000",
}

ROLE_METADATA = (
    "role_color_identity_v2: "
    "backbone=#0000ff; primary_branch=#ff9900; "
    "secondary_branch=#00ffff; flower_support=#007800; "
    "flower_anchor=#ff0000; unit_boundary=#000000(dashed). "
    "data-role is authoritative; stroke color is a visual fallback."
)


def _round(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def _xml_attr(value: object) -> str:
    return html.escape(str(value), quote=True)


def _dom_token(value: object) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-.")
    return token or "unknown"


def _repeat_instances(repeat: str) -> tuple[tuple[str, float], ...]:
    if repeat == "triple":
        return (
            ("repeat_m1", -1.0),
            ("repeat_0", 0.0),
            ("repeat_p1", 1.0),
        )
    return (("repeat_0", 0.0),)


def _point(point: Sequence[float], shift_x: float) -> str:
    return f"{_round(float(point[0]) + shift_x)},{_round(float(point[1]))}"


def _polyline(
    points: Sequence[Sequence[float]],
    shift_x: float,
) -> str:
    if len(points) < 2:
        return ""
    coordinates = " ".join(_point(point, shift_x) for point in points)
    return f'<polyline points="{coordinates}" fill="none" '


def _curve_path(curve: Mapping[str, Any], shift_x: float) -> str:
    parts: list[str] = []
    for segment in curve["cubic_segments"]:
        p0 = (float(segment["p0"][0]) + shift_x, float(segment["p0"][1]))
        p1 = (float(segment["p1"][0]) + shift_x, float(segment["p1"][1]))
        p2 = (float(segment["p2"][0]) + shift_x, float(segment["p2"][1]))
        p3 = (float(segment["p3"][0]) + shift_x, float(segment["p3"][1]))
        if not parts:
            parts.append(f"M {_point(p0, 0.0)}")
        parts.append(
            f"C {_point(p1, 0.0)} {_point(p2, 0.0)} {_point(p3, 0.0)}"
        )
    return " ".join(parts)


def render_case_svg(
    analysis: Mapping[str, Any],
    flower_mount_plan: Mapping[str, Any],
    selection: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    repeat: str,
    palette: str,
) -> str:
    canvas_height = float(analysis["coordinate_system"]["canvas_bounds"][3])
    repeat_instances = _repeat_instances(repeat)
    shifts = tuple(shift for _, shift in repeat_instances)
    x_min = -1.08 if repeat == "triple" else -0.18
    x_max = 2.08 if repeat == "triple" else 1.18
    view_width = x_max - x_min
    used_dom_ids: set[str] = set()

    def dom_id(*parts: object) -> str:
        value = "--".join(_dom_token(part) for part in parts)
        if value in used_dom_ids:
            raise ValueError(f"duplicate SVG DOM id: {value}")
        used_dom_ids.add(value)
        return value

    root_id = dom_id(
        "structural-svg",
        provenance["prototype_id"],
        f"production-seed-{provenance['production_seed']}",
    )
    root_metadata = {
        "prototype-id": provenance.get("prototype_id"),
        "production-seed": provenance.get("production_seed"),
        "backbone-seed": provenance.get("backbone_seed"),
        "flower-seed": provenance.get("flower_seed"),
        "branch-seed": provenance.get("branch_seed"),
        "unit-seed": provenance.get("unit_seed"),
        "backbone-variant-id": provenance.get("backbone_variant_id"),
        "density-level": provenance.get("density_level"),
        "source-case": provenance.get("source_case"),
        "source-contract-id": provenance.get("source_contract_id"),
        "source-plan-id": provenance.get("source_plan_id"),
        "source-selection-id": provenance.get("source_selection_id"),
        "repeat-mode": repeat,
    }
    root_attributes = "".join(
        f' data-{name}="{_xml_attr(value)}"'
        for name, value in root_metadata.items()
        if value is not None
    )
    parts = [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'id="{_xml_attr(root_id)}"{root_attributes} '
            f'viewBox="{_round(x_min)} 0 {_round(view_width)} '
            f'{_round(canvas_height)}" '
            f'width="{int(round(view_width * 1000))}" '
            f'height="{int(round(canvas_height * 1000))}">'
        ),
        (
            f'<rect x="{_round(x_min)}" y="0" width="{_round(view_width)}" '
            f'height="{_round(canvas_height)}" fill="{COLORS["background"]}"/>'
        ),
        f"<metadata>{ROLE_METADATA}</metadata>",
    ]

    def stroke_style(role: str, dashed: bool = False) -> str:
        color = (
            ROLE_COLORS[role]
            if palette == "role"
            else {
                "backbone": COLORS["ink"],
                "primary_branch": COLORS["l1"],
                "secondary_branch": COLORS["l2"],
                "flower_support": COLORS["flower_support"],
                "flower_anchor": COLORS["flower"],
                "unit_boundary": COLORS["grid"],
            }[role]
        )
        dash = ' stroke-dasharray="0.012 0.008"' if dashed else ""
        return f'stroke="{color}"{dash}'

    boundary_group_id = dom_id("unit-boundaries")
    parts.append(
        f'<g id="{_xml_attr(boundary_group_id)}" '
        f'data-instance-id="{_xml_attr(boundary_group_id)}" '
        'data-role="unit_boundary">'
    )
    for boundary_index, boundary_x in enumerate(
        range(int(min(shifts)), int(max(shifts)) + 2)
    ):
        boundary_id = dom_id("unit-boundary", f"{boundary_index:02d}")
        parts.append(
            '<line '
            f'id="{_xml_attr(boundary_id)}" '
            f'data-instance-id="{_xml_attr(boundary_id)}" '
            f'data-boundary-x="{_round(boundary_x)}" '
            f'x1="{_round(boundary_x)}" y1="0" '
            f'x2="{_round(boundary_x)}" y2="{_round(canvas_height)}" '
            + stroke_style("unit_boundary", dashed=True)
            + ' stroke-width="0.004"/>'
        )
    parts.append("</g>")

    backbone_layer_id = dom_id("backbone-layer")
    parts.append(
        f'<g id="{_xml_attr(backbone_layer_id)}" '
        f'data-instance-id="{_xml_attr(backbone_layer_id)}" '
        'data-role="backbone">'
    )
    backbone = [row["point"] for row in analysis["backbone"]["samples"]]
    for repeat_id, shift_x in repeat_instances:
        repeat_group_id = dom_id("backbone", repeat_id)
        backbone_id = dom_id(repeat_id, "backbone")
        parts.append(
            f'<g id="{_xml_attr(repeat_group_id)}" '
            f'data-instance-id="{_xml_attr(repeat_group_id)}" '
            f'data-repeat-id="{_xml_attr(repeat_id)}" '
            f'data-repeat-shift="{_round(shift_x)}">'
        )
        color = (
            ROLE_COLORS["backbone"]
            if palette == "role"
            else (COLORS["ink"] if shift_x == 0.0 else COLORS["ghost"])
        )
        width = 0.014 if shift_x == 0.0 else 0.007
        polyline = _polyline(backbone, shift_x)
        parts.append(
            polyline
            + f'id="{_xml_attr(backbone_id)}" '
            + f'data-instance-id="{_xml_attr(backbone_id)}" '
            + f'data-repeat-id="{_xml_attr(repeat_id)}" '
            + f'data-repeat-shift="{_round(shift_x)}" '
            + f'stroke="{color}" stroke-width="{_round(width)}" '
            'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        parts.append("</g>")
    parts.append("</g>")

    support_layer_id = dom_id("flower-support-layer")
    parts.append(
        f'<g id="{_xml_attr(support_layer_id)}" '
        f'data-instance-id="{_xml_attr(support_layer_id)}" '
        'data-role="flower_support">'
    )
    for repeat_id, shift_x in repeat_instances:
        repeat_group_id = dom_id("flower-support", repeat_id)
        parts.append(
            f'<g id="{_xml_attr(repeat_group_id)}" '
            f'data-instance-id="{_xml_attr(repeat_group_id)}" '
            f'data-repeat-id="{_xml_attr(repeat_id)}" '
            f'data-repeat-shift="{_round(shift_x)}">'
        )
        for mount in flower_mount_plan.get("mounts", []):
            mount_id = str(mount.get("mount_id", mount.get("flower_id", "mount")))
            instance_id = dom_id(repeat_id, "flower-support", mount_id)
            polyline = _polyline(mount["centerline"], shift_x)
            parts.append(
                polyline
                + f'id="{_xml_attr(instance_id)}" '
                + f'data-instance-id="{_xml_attr(instance_id)}" '
                + f'data-repeat-id="{_xml_attr(repeat_id)}" '
                + f'data-repeat-shift="{_round(shift_x)}" '
                + f'data-mount-id="{_xml_attr(mount_id)}" '
                + stroke_style("flower_support")
                + ' '
                'stroke-width="0.010" stroke-linejoin="round" '
                'stroke-linecap="round" '
                f'data-flower-id="{_xml_attr(mount.get("flower_id", ""))}"/>'
            )
        parts.append("</g>")
    parts.append("</g>")

    flower_layer_id = dom_id("flower-anchor-layer")
    parts.append(
        f'<g id="{_xml_attr(flower_layer_id)}" '
        f'data-instance-id="{_xml_attr(flower_layer_id)}" '
        'data-role="flower_anchor">'
    )
    for repeat_id, shift_x in repeat_instances:
        repeat_group_id = dom_id("flower-anchor", repeat_id)
        parts.append(
            f'<g id="{_xml_attr(repeat_group_id)}" '
            f'data-instance-id="{_xml_attr(repeat_group_id)}" '
            f'data-repeat-id="{_xml_attr(repeat_id)}" '
            f'data-repeat-shift="{_round(shift_x)}">'
        )
        for flower in analysis["flowers"]:
            flower_id = str(flower.get("flower_id", "flower"))
            instance_id = dom_id(repeat_id, "flower-anchor", flower_id)
            center_x = float(flower["center"][0]) + shift_x
            center_y = float(flower["center"][1])
            rx = float(flower["rx"])
            ry = float(flower["ry"])
            parts.append(
                '<ellipse '
                f'id="{_xml_attr(instance_id)}" '
                f'data-instance-id="{_xml_attr(instance_id)}" '
                f'data-repeat-id="{_xml_attr(repeat_id)}" '
                f'data-repeat-shift="{_round(shift_x)}" '
                f'cx="{_round(center_x)}" cy="{_round(center_y)}" '
                f'rx="{_round(rx)}" ry="{_round(ry)}" '
                f'fill="{COLORS["flower_fill"]}" '
                + stroke_style("flower_anchor")
                + ' stroke-width="0.006" '
                f'data-flower-id="{_xml_attr(flower_id)}"/>'
            )
        parts.append("</g>")
    parts.append("</g>")

    if selection["feasible"]:
        branch_layer_id = dom_id("branches-layer")
        parts.append(
            f'<g id="{_xml_attr(branch_layer_id)}" '
            f'data-instance-id="{_xml_attr(branch_layer_id)}" '
            'data-role="branches">'
        )
        for repeat_id, shift_x in repeat_instances:
            repeat_group_id = dom_id("branches", repeat_id)
            parts.append(
                f'<g id="{_xml_attr(repeat_group_id)}" '
                f'data-instance-id="{_xml_attr(repeat_group_id)}" '
                f'data-repeat-id="{_xml_attr(repeat_id)}" '
                f'data-repeat-shift="{_round(shift_x)}">'
            )
            for candidate in selection["selected_candidates"]:
                for curve in candidate["curves"]:
                    canonical_curve_id = str(curve.get("curve_id", "curve"))
                    curve_instance_id = dom_id(
                        repeat_id,
                        "curve",
                        canonical_curve_id,
                    )
                    role = (
                        "primary_branch"
                        if curve["level"] == "L1"
                        else "secondary_branch"
                    )
                    color = (
                        ROLE_COLORS[role]
                        if palette == "role"
                        else COLORS[str(curve["level"]).lower()]
                    )
                    width = 0.010 if curve["level"] == "L1" else 0.007
                    path = _curve_path(curve, shift_x)
                    if palette == "presentation":
                        halo_id = dom_id(
                            repeat_id,
                            "curve-halo",
                            canonical_curve_id,
                        )
                        parts.append(
                            f'<path id="{_xml_attr(halo_id)}" '
                            f'data-instance-id="{_xml_attr(halo_id)}" '
                            f'data-repeat-id="{_xml_attr(repeat_id)}" '
                            f'data-repeat-shift="{_round(shift_x)}" '
                            f'data-source-curve-id="{_xml_attr(canonical_curve_id)}" '
                            f'd="{path}" fill="none" '
                            'stroke="#ffffff" '
                            f'stroke-width="{_round(width + 0.007)}" '
                            'stroke-linejoin="round" stroke-linecap="round"/>'
                        )
                    parts.append(
                        f'<path id="{_xml_attr(curve_instance_id)}" '
                        f'data-instance-id="{_xml_attr(curve_instance_id)}" '
                        f'data-repeat-id="{_xml_attr(repeat_id)}" '
                        f'data-repeat-shift="{_round(shift_x)}" '
                        f'd="{path}" fill="none" '
                        + f'stroke="{color}" '
                        + f'stroke-width="{_round(width)}" '
                        'stroke-linejoin="round" stroke-linecap="round" '
                        f'data-role="{_xml_attr(role)}" '
                        f'data-level="{_xml_attr(curve.get("level", ""))}" '
                        f'data-curve-id="{_xml_attr(canonical_curve_id)}" '
                        f'data-parent-curve-id="{_xml_attr(curve.get("parent_curve_id", ""))}" '
                        f'data-lane-id="{_xml_attr(candidate.get("source_lane_id", ""))}" '
                        f'data-unit-id="{_xml_attr(candidate.get("candidate_id", ""))}"/>'
                    )
            parts.append("</g>")
        parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


def run(source_dir: Path, output_dir: Path, repeat: str, palette: str) -> int:
    if repeat not in {"single", "triple"}:
        raise SystemExit("--repeat must be single or triple")
    if palette not in {"role", "presentation"}:
        raise SystemExit("--palette must be role or presentation")
    output_dir.mkdir(parents=True, exist_ok=True)
    exported = 0
    skipped = 0
    for case_manifest in sorted(source_dir.glob("*/seed_*/case_manifest.json")):
        case_dir = case_manifest.parent
        derived_seeds_path = case_dir / "derived_seeds.json"
        variation_path = case_dir / "backbone_variation.json"
        analysis_path = case_dir / "prototype_analysis_variant.json"
        mounts_path = case_dir / "flower_mount_plan.json"
        selection_path = case_dir / "global_unit_selection.json"
        if not (
            analysis_path.is_file()
            and mounts_path.is_file()
            and selection_path.is_file()
        ):
            skipped += 1
            continue
        manifest = json.loads(case_manifest.read_text(encoding="utf-8"))
        derived_seeds = (
            json.loads(derived_seeds_path.read_text(encoding="utf-8"))
            if derived_seeds_path.is_file()
            else {}
        )
        variation = (
            json.loads(variation_path.read_text(encoding="utf-8"))
            if variation_path.is_file()
            else {}
        )
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        mounts = json.loads(mounts_path.read_text(encoding="utf-8"))
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        prototype_id = str(selection["prototype_id"])
        seed = str(case_manifest.parent.name).replace("seed_", "")
        provenance = {
            "prototype_id": prototype_id,
            "production_seed": manifest.get("production_seed", seed),
            "backbone_seed": derived_seeds.get("backbone_seed"),
            "flower_seed": derived_seeds.get("flower_seed"),
            "branch_seed": derived_seeds.get("branch_seed"),
            "unit_seed": derived_seeds.get("unit_seed"),
            "backbone_variant_id": manifest.get(
                "backbone_variant_id",
                variation.get("prototype_variant_id"),
            ),
            "density_level": manifest.get("density_level"),
            "source_case": case_dir.relative_to(source_dir).as_posix(),
            "source_contract_id": selection.get("contract_id"),
            "source_plan_id": manifest.get("plan_id"),
            "source_selection_id": selection.get("selection_id"),
        }
        svg = render_case_svg(
            analysis,
            mounts,
            selection,
            provenance,
            repeat=repeat,
            palette=palette,
        )
        (output_dir / f"{prototype_id}__seed_{seed}.svg").write_text(
            svg,
            encoding="utf-8",
            newline="\n",
        )
        exported += 1
    print(f"exported={exported} skipped={skipped} output={output_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export saved batch results as SVG."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--repeat", choices=("single", "triple"), default="triple")
    parser.add_argument(
        "--palette",
        choices=("role", "presentation"),
        default="role",
    )
    args = parser.parse_args()
    return run(args.source_dir, args.output_dir, args.repeat, args.palette)


if __name__ == "__main__":
    raise SystemExit(main())
