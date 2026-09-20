#!/usr/bin/env python3
"""Generate the Stage-5E sparse local-L2 review through the formal chain."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from branch_unit_grammar_v1 import (
    _polyline_distance,
    generate_unit_candidate_inventory,
    validate_unit_candidate_inventory,
)
from prototype_strategy_v1 import (
    load_prototype_strategy_registry,
    resolve_prototype_strategy,
)
from render_global_l1_flow import render_png as render_l1_png
from render_stage5_global_selection import render_global_selection
from run_stage3b_l1_flow import _load_inputs, generate_prototype_case
from stage5_global_unit_selection import (
    build_conflict_graph,
    candidate_pair_crossings,
    candidate_pair_minimum_clearance,
    select_global_units,
    validate_global_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage5e_l2_sparse_review_v1"
)
FROZEN_5D_RUN = (
    REPO_ROOT
    / "artifacts"
    / "runs"
    / "dynamic_branch_stage5d_density_review_v1"
)
STAGE4_CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json"
STAGE5E_CONTRACT_PATH = (
    DYNAMIC_DIR / "STAGE5E_L2_SPARSE_SELECTION_CONTRACT_V1.json"
)
EDITOR_L2_PRIOR_PATH = DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json"

PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
UNIT_SEEDS = (49789125, 928347611, 2107448227)
PRODUCTION_SEED = 4101
BACKBONE_SEED = 1658046696
FLOWER_SEED = 0
FLOWER_RHO = 0.0
BRANCH_SEED = 3594281359
L2_ATTACHMENT_TOLERANCE = 1e-4


class Stage5EL2SparseReviewError(RuntimeError):
    """The 5E review cannot be produced through the formal chain."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Stage5EL2SparseReviewError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _canonical(value: object) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    path = Path(
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    )
    if not path.is_file():
        return ImageFont.load_default()
    return ImageFont.truetype(str(path), size)


def _prototype_label(prototype_id: str) -> str:
    return {
        "proto_sw_1_1": "SW1-1",
        "proto_sw_1_3": "SW1-3",
        "proto_sw_2_3": "SW2-3",
        "proto_sw_3_1": "SW3-1",
        "proto_sw_3_2": "SW3-2",
    }[prototype_id]


def _render_seed_sheet(
    image_rows: Mapping[str, Sequence[tuple[Path, Mapping[str, Any]]]],
    output: Path,
    *,
    title: str,
) -> None:
    column_labels = [
        f"unit_seed {UNIT_SEEDS[0]}",
        f"unit_seed {UNIT_SEEDS[1]}",
        f"unit_seed {UNIT_SEEDS[2]}",
    ]
    cell_width = 620
    cell_height = 380
    image_label_height = 30
    left_margin = 112
    top_margin = 96
    canvas = Image.new(
        "RGB",
        (
            left_margin + len(column_labels) * cell_width,
            top_margin + len(PROTOTYPE_IDS) * cell_height,
        ),
        "#f1efe9",
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 10), title, fill="#17242d", font=_font(24, bold=True))
    for column, label in enumerate(column_labels):
        draw.text(
            (left_margin + column * cell_width + 12, 53),
            label,
            fill="#374750",
            font=_font(16, bold=True),
        )
    for row, prototype_id in enumerate(PROTOTYPE_IDS):
        draw.text(
            (15, top_margin + row * cell_height + 18),
            _prototype_label(prototype_id),
            fill="#17242d",
            font=_font(19, bold=True),
        )
        cells = list(image_rows[prototype_id])
        if len(cells) != len(column_labels):
            raise Stage5EL2SparseReviewError(
                f"5E sheet row is incomplete: {prototype_id}"
            )
        for column, (path, summary) in enumerate(cells):
            x0 = left_margin + column * cell_width
            y0 = top_margin + row * cell_height
            draw.rectangle(
                (x0 + 4, y0 + 4, x0 + cell_width - 5, y0 + cell_height - 5),
                outline="#c5cdd2",
                width=2,
            )
            draw.text(
                (x0 + 16, y0 + 9),
                (
                    f"upgraded={summary['upgraded']} "
                    f"L2={summary['l2_count']}"
                ),
                fill="#374750",
                font=_font(16, bold=True),
            )
            with Image.open(path) as source:
                image = source.convert("RGB")
            image.thumbnail(
                (cell_width - 18, cell_height - image_label_height - 18),
                Image.Resampling.LANCZOS,
            )
            x = x0 + (cell_width - image.width) // 2
            image_area_top = y0 + image_label_height
            image_area_height = cell_height - image_label_height
            y = image_area_top + (image_area_height - image.height) // 2
            canvas.paste(image, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def _selected_pair_mechanics(
    selection: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
) -> dict[str, Any]:
    """Independently recompute base and periodic selected-curve mechanics."""

    selected = list(selection["selected_candidates"])
    repeat_shifts = [
        float(value) for value in conflict_graph["repeat_shifts_checked"]
    ]
    base_shifts = [value for value in repeat_shifts if abs(value) <= 1e-12]
    periodic_shifts = [value for value in repeat_shifts if abs(value) > 1e-12]
    if not base_shifts or not periodic_shifts:
        raise Stage5EL2SparseReviewError(
            "5E mechanics require both canonical and periodic repeat shifts"
        )
    required_clearance = float(conflict_graph["minimum_descendant_clearance"])

    base_crossings = 0
    periodic_crossings = 0
    base_clearance_violations = 0
    periodic_clearance_violations = 0
    minimum_base_clearance = float("inf")
    minimum_periodic_clearance = float("inf")
    checked_distinct_pair_count = 0

    for index, first in enumerate(selected):
        for second in selected[index + 1 :]:
            checked_distinct_pair_count += 1
            base_crossings += len(
                candidate_pair_crossings(first, second, base_shifts)
            )
            periodic_crossings += len(
                candidate_pair_crossings(first, second, periodic_shifts)
            )
            base_clearance = candidate_pair_minimum_clearance(
                first,
                second,
                base_shifts,
            )
            periodic_clearance = candidate_pair_minimum_clearance(
                first,
                second,
                periodic_shifts,
            )
            minimum_base_clearance = min(
                minimum_base_clearance,
                base_clearance,
            )
            minimum_periodic_clearance = min(
                minimum_periodic_clearance,
                periodic_clearance,
            )
            if base_clearance < required_clearance - 1e-9:
                base_clearance_violations += 1
            if periodic_clearance < required_clearance - 1e-9:
                periodic_clearance_violations += 1

    for candidate in selected:
        periodic_crossings += len(
            candidate_pair_crossings(candidate, candidate, periodic_shifts)
        )
        periodic_clearance = candidate_pair_minimum_clearance(
            candidate,
            candidate,
            periodic_shifts,
        )
        minimum_periodic_clearance = min(
            minimum_periodic_clearance,
            periodic_clearance,
        )
        if periodic_clearance < required_clearance - 1e-9:
            periodic_clearance_violations += 1

    total_crossings = base_crossings + periodic_crossings
    total_clearance_violations = (
        base_clearance_violations + periodic_clearance_violations
    )
    return {
        "checked_distinct_selected_pair_count": checked_distinct_pair_count,
        "checked_periodic_self_pair_count": len(selected),
        "base_curve_crossing_count": base_crossings,
        "periodic_curve_crossing_count": periodic_crossings,
        "curve_crossing_count": total_crossings,
        "base_near_clearance_violation_count": base_clearance_violations,
        "periodic_near_clearance_violation_count": (
            periodic_clearance_violations
        ),
        "near_clearance_violation_count": total_clearance_violations,
        "minimum_base_selected_clearance": (
            round(minimum_base_clearance, 9)
            if minimum_base_clearance != float("inf")
            else None
        ),
        "minimum_periodic_selected_clearance": (
            round(minimum_periodic_clearance, 9)
            if minimum_periodic_clearance != float("inf")
            else None
        ),
        "required_pair_clearance": round(required_clearance, 9),
    }


def _check_l2_real_attachment(
    candidate: Mapping[str, Any],
    tolerance: float,
) -> None:
    """Independently verify every selected L2 root lies on the actual L1."""

    curves = list(candidate["curves"])
    l1_curve = next(
        (curve for curve in curves if curve.get("level") == "L1"),
        None,
    )
    if l1_curve is None:
        raise Stage5EL2SparseReviewError(
            "selected 5E Unit lacks its L1 curve"
        )
    l1_points = [
        (float(point[0]), float(point[1]))
        for point in l1_curve["centerline"]
    ]
    for curve in curves:
        if curve.get("level") != "L2":
            continue
        root = (
            float(curve["centerline"][0][0]),
            float(curve["centerline"][0][1]),
        )
        distance = _polyline_distance(l1_points, (root, root))
        if distance > tolerance:
            raise Stage5EL2SparseReviewError(
                "selected L2 does not attach to the actual L1 curve: "
                f"{curve['curve_id']} distance={distance:.6g}"
            )


def _check_frozen_l1_invariance(
    plan: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> None:
    lanes = list(plan["lanes"])
    selected = list(selection["selected_candidates"])
    if len(selected) != len(lanes):
        raise Stage5EL2SparseReviewError(
            "formal Stage5 selection does not contain one Unit per ordinary L1"
        )
    lane_by_id = {str(lane["slot_id"]): lane for lane in lanes}
    if {str(row["source_lane_id"]) for row in selected} != set(lane_by_id):
        raise Stage5EL2SparseReviewError(
            "formal Stage5 selection does not preserve the Stage3 lane set"
        )
    for candidate in selected:
        curves = list(candidate["curves"])
        l1_curve = next(
            (curve for curve in curves if curve.get("level") == "L1"),
            None,
        )
        if l1_curve is None:
            raise Stage5EL2SparseReviewError(
                "selected 5E Unit lacks its L1 curve"
            )
        lane = lane_by_id[str(candidate["source_lane_id"])]
        if l1_curve["cubic_segments"] != lane["segments"]:
            raise Stage5EL2SparseReviewError(
                "formal Unit changed the selected Stage3 ordinary L1 curve"
            )


def _assert_frozen_5d_case(
    prototype_id: str,
    density_level: str,
    current_plan: Mapping[str, Any],
    strict_value: Mapping[str, Any],
    flower_mount_plan: Mapping[str, Any],
    flower_layout_plan: Mapping[str, Any],
) -> None:
    case_dir = FROZEN_5D_RUN / prototype_id / density_level
    if not case_dir.is_dir():
        raise Stage5EL2SparseReviewError(
            f"frozen 5D case is missing: {case_dir}"
        )
    frozen_plan = _read_json(case_dir / "global_l1_flow_plan.json")
    if current_plan.get("plan_id") != frozen_plan.get("plan_id"):
        raise Stage5EL2SparseReviewError(
            "5E L1 plan_id differs from the frozen 5D case: "
            f"{prototype_id} {density_level}"
        )
    frozen_roots = [
        round(float(lane["root_s"]), 9) for lane in frozen_plan["lanes"]
    ]
    current_roots = [
        round(float(lane["root_s"]), 9) for lane in current_plan["lanes"]
    ]
    if current_roots != frozen_roots:
        raise Stage5EL2SparseReviewError(
            "5E L1 root set differs from the frozen 5D case: "
            f"{prototype_id} {density_level}"
        )
    frozen_strict = _read_json(case_dir / "strict_p0_variant.json")
    if _canonical(strict_value) != _canonical(frozen_strict):
        raise Stage5EL2SparseReviewError(
            "5E backbone/flower structure differs from the frozen 5D case: "
            f"{prototype_id} {density_level}"
        )
    frozen_mounts = _read_json(case_dir / "flower_mount_plan.json")
    if _canonical(flower_mount_plan) != _canonical(frozen_mounts):
        raise Stage5EL2SparseReviewError(
            "5E flower mounts differ from the frozen 5D case: "
            f"{prototype_id} {density_level}"
        )
    frozen_layout = _read_json(case_dir / "flower_layout_plan.json")
    if _canonical(flower_layout_plan) != _canonical(frozen_layout):
        raise Stage5EL2SparseReviewError(
            "5E flower layout differs from the frozen 5D case: "
            f"{prototype_id} {density_level}"
        )


def run(output_dir: Path) -> None:
    if output_dir.exists():
        raise Stage5EL2SparseReviewError(
            f"output directory already exists: {output_dir}"
        )
    for path in (
        STAGE4_CONTRACT_PATH,
        STAGE5E_CONTRACT_PATH,
        EDITOR_L2_PRIOR_PATH,
    ):
        if not path.is_file():
            raise Stage5EL2SparseReviewError(f"missing 5E input: {path}")
    if not FROZEN_5D_RUN.is_dir():
        raise Stage5EL2SparseReviewError(
            f"missing frozen 5D review directory: {FROZEN_5D_RUN}"
        )

    (
        inputs,
        prior,
        feedback_prior,
        curve_geometry_prior,
        stage3b_contract,
        stage3_plan_contract,
        provenance,
    ) = _load_inputs()
    stage4_contract = _read_json(STAGE4_CONTRACT_PATH)
    stage5e_contract = _read_json(STAGE5E_CONTRACT_PATH)
    editor_l2_prior = _read_json(EDITOR_L2_PRIOR_PATH)
    registry = load_prototype_strategy_registry()
    strategies = {
        prototype_id: resolve_prototype_strategy(
            {"prototype_id": prototype_id},
            registry,
        )
        for prototype_id in PROTOTYPE_IDS
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="stage5e_l2_sparse_",
        dir=output_dir.parent,
    ) as directory:
        temporary = Path(directory)
        structure_rows: dict[str, list[tuple[Path, Mapping[str, Any]]]] = {
            value: [] for value in PROTOTYPE_IDS
        }
        formal_rows: dict[str, list[tuple[Path, Mapping[str, Any]]]] = {
            value: [] for value in PROTOTYPE_IDS
        }
        task_rows: list[dict[str, Any]] = []
        frozen_rows: list[dict[str, Any]] = []
        variation_rows: list[dict[str, Any]] = []
        total_crossings = 0
        total_clearance_violations = 0

        for prototype_id in PROTOTYPE_IDS:
            frozen_density: str | None = None
            selected_id_sets: dict[int, list[str]] = {}
            seed_upgrades: dict[int, list[str]] = {}
            seed_l2_counts: dict[int, int] = {}

            for unit_seed in UNIT_SEEDS:
                result = generate_prototype_case(
                    payload=inputs[prototype_id],
                    prototype_strategy=strategies[prototype_id],
                    production_seed=PRODUCTION_SEED,
                    prior=prior,
                    feedback_prior=feedback_prior,
                    curve_geometry_prior=curve_geometry_prior,
                    contract=stage3b_contract,
                    stage3_plan_contract=stage3_plan_contract,
                    backbone_seed_override=BACKBONE_SEED,
                    flower_seed_override=FLOWER_SEED,
                    branch_seed_override=BRANCH_SEED,
                    unit_seed_override=unit_seed,
                    backbone_rho=None,
                    flower_rho=FLOWER_RHO,
                    ordinary_density_level_override=None,
                )
                analysis = result["variant_analysis"]
                plan = result["plan"]
                flower_mount_plan = result["flower_mount_plan"]
                flower_layout_plan = result["flower_layout_plan"]
                strict_value = result["variant_strict"].as_dict()
                inventory = result["inventory"]
                density_level = str(
                    plan["count_derivation"]["ordinary_density_level"]
                )
                if frozen_density is None:
                    frozen_density = density_level
                elif density_level != frozen_density:
                    raise Stage5EL2SparseReviewError(
                        "production density level changed across unit seeds: "
                        f"{prototype_id}"
                    )
                _assert_frozen_5d_case(
                    prototype_id,
                    density_level,
                    plan,
                    strict_value,
                    flower_mount_plan,
                    flower_layout_plan,
                )
                frozen_rows.append(
                    {
                        "prototype_id": prototype_id,
                        "density_level": density_level,
                        "plan_id": plan["plan_id"],
                        "plan_id_matches_frozen_5d": True,
                        "lane_roots_match_frozen_5d": True,
                        "strict_p0_matches_frozen_5d": True,
                        "flower_mounts_match_frozen_5d": True,
                        "flower_layout_matches_frozen_5d": True,
                    }
                )

                unit_inventory = generate_unit_candidate_inventory(
                    plan,
                    analysis,
                    prior,
                    stage4_contract,
                    editor_l2_prior,
                )
                validate_unit_candidate_inventory(
                    unit_inventory,
                    stage4_contract,
                )
                conflict_graph = build_conflict_graph(
                    unit_inventory,
                    stage5e_contract,
                    editor_l2_prior,
                )
                selection = select_global_units(
                    unit_inventory,
                    conflict_graph,
                    stage5e_contract,
                )
                validate_global_selection(selection, conflict_graph)
                if not selection["feasible"]:
                    raise Stage5EL2SparseReviewError(
                        f"no formal sparse 5E composition: "
                        f"{prototype_id} unit_seed={unit_seed}"
                    )
                _check_frozen_l1_invariance(plan, selection)
                for candidate in selection["selected_candidates"]:
                    _check_l2_real_attachment(
                        candidate,
                        L2_ATTACHMENT_TOLERANCE,
                    )

                mechanics = _selected_pair_mechanics(
                    selection,
                    conflict_graph,
                )
                if (
                    mechanics["curve_crossing_count"] != 0
                    or mechanics["near_clearance_violation_count"] != 0
                ):
                    raise Stage5EL2SparseReviewError(
                        "formal sparse 5E selection failed independent "
                        f"crossing or clearance checks: {prototype_id} "
                        f"unit_seed={unit_seed}"
                    )
                total_crossings += int(mechanics["curve_crossing_count"])
                total_clearance_violations += int(
                    mechanics["near_clearance_violation_count"]
                )
                trace = selection["solver_trace"]
                if int(trace["selected_l3_count"]) != 0:
                    raise Stage5EL2SparseReviewError(
                        "formal sparse 5E selection contains L3 geometry"
                    )
                if any(
                    curve.get("level") not in {"L1", "L2"}
                    for candidate in selection["selected_candidates"]
                    for curve in candidate["curves"]
                ):
                    raise Stage5EL2SparseReviewError(
                        "formal sparse 5E selection contains non-L1/L2 curves"
                    )

                seed_label = f"unit_seed_{unit_seed}"
                case = temporary / prototype_id / seed_label
                case.mkdir(parents=True)
                paths = {
                    "strict_p0_variant.json": case / "strict_p0_variant.json",
                    "prototype_analysis_variant.json": case
                    / "prototype_analysis_variant.json",
                    "flower_layout_plan.json": case
                    / "flower_layout_plan.json",
                    "flower_mount_plan.json": case / "flower_mount_plan.json",
                    "global_l1_flow_plan.json": case
                    / "global_l1_flow_plan.json",
                    "global_l1_candidate_inventory.json": case
                    / "global_l1_candidate_inventory.json",
                    "unit_candidate_inventory.json": case
                    / "unit_candidate_inventory.json",
                    "candidate_conflict_graph.json": case
                    / "candidate_conflict_graph.json",
                    "global_unit_selection.json": case
                    / "global_unit_selection.json",
                    "structure_debug.png": case / "structure_debug.png",
                    "formal_sparse_l2.png": case / "formal_sparse_l2.png",
                }
                _write_json(paths["strict_p0_variant.json"], strict_value)
                _write_json(paths["prototype_analysis_variant.json"], analysis)
                _write_json(
                    paths["flower_layout_plan.json"],
                    flower_layout_plan,
                )
                _write_json(
                    paths["flower_mount_plan.json"],
                    flower_mount_plan,
                )
                _write_json(paths["global_l1_flow_plan.json"], plan)
                _write_json(
                    paths["global_l1_candidate_inventory.json"],
                    inventory,
                )
                _write_json(
                    paths["unit_candidate_inventory.json"],
                    unit_inventory,
                )
                _write_json(
                    paths["candidate_conflict_graph.json"],
                    conflict_graph,
                )
                _write_json(
                    paths["global_unit_selection.json"],
                    selection,
                )
                render_l1_png(
                    analysis,
                    plan,
                    paths["structure_debug.png"],
                    debug=True,
                )
                render_global_selection(
                    analysis,
                    unit_inventory,
                    conflict_graph,
                    selection,
                    paths["formal_sparse_l2.png"],
                    triple_repeat=False,
                    flower_mount_plan=flower_mount_plan,
                )
                summary = {
                    "upgraded": int(trace["achieved_upgrade_count"]),
                    "l2_count": int(trace["selected_l2_count"]),
                }
                structure_rows[prototype_id].append(
                    (paths["structure_debug.png"], summary)
                )
                formal_rows[prototype_id].append(
                    (paths["formal_sparse_l2.png"], summary)
                )
                selected_id_sets[unit_seed] = sorted(
                    selection["selected_candidate_ids"]
                )
                seed_upgrades[unit_seed] = list(trace["upgrade_lane_ids"])
                seed_l2_counts[unit_seed] = int(trace["selected_l2_count"])
                task_rows.append(
                    {
                        "prototype_id": prototype_id,
                        "unit_seed": unit_seed,
                        "density_level": density_level,
                        "production_seed": PRODUCTION_SEED,
                        "backbone_seed": BACKBONE_SEED,
                        "flower_seed": FLOWER_SEED,
                        "flower_rho": FLOWER_RHO,
                        "branch_seed": BRANCH_SEED,
                        "plan_id": plan["plan_id"],
                        "ordinary_l1_count": len(plan["lanes"]),
                        "flower_support_count": len(
                            flower_mount_plan["mounts"]
                        ),
                        "intent_upgrade_budget": int(
                            trace["intent_upgrade_budget"]
                        ),
                        "achieved_upgrade_count": int(
                            trace["achieved_upgrade_count"]
                        ),
                        "upgrade_lane_ids": list(trace["upgrade_lane_ids"]),
                        "selected_l1_only_count": int(
                            trace["selected_l1_only_count"]
                        ),
                        "selected_l2_count": int(trace["selected_l2_count"]),
                        "selected_l3_count": int(trace["selected_l3_count"]),
                        "mechanical_checks": mechanics,
                        "files": {
                            name: str(path.relative_to(temporary)).replace(
                                "\\",
                                "/",
                            )
                            for name, path in paths.items()
                        },
                    }
                )

            if len(set(map(tuple, selected_id_sets.values()))) < 2:
                raise Stage5EL2SparseReviewError(
                    "unit_seed variation did not change the formal 5E "
                    f"selection: {prototype_id}"
                )
            variation_rows.append(
                {
                    "prototype_id": prototype_id,
                    "density_level": frozen_density,
                    "unit_seed_order": list(UNIT_SEEDS),
                    "upgrade_lane_ids_by_seed": {
                        str(seed): seed_upgrades[seed] for seed in UNIT_SEEDS
                    },
                    "selected_l2_count_by_seed": {
                        str(seed): seed_l2_counts[seed]
                        for seed in UNIT_SEEDS
                    },
                    "distinct_formal_selection_count": len(
                        set(map(tuple, selected_id_sets.values()))
                    ),
                    "counterfactual_formal_output_changed": True,
                }
            )

        structure_sheet = (
            temporary / "stage5e_color_structure_contact_sheet.png"
        )
        formal_sheet = (
            temporary / "stage5e_formal_sparse_l2_contact_sheet.png"
        )
        _render_seed_sheet(
            structure_rows,
            structure_sheet,
            title=(
                "Stage 5E: frozen 5D structure, unit_seed-driven sparse "
                "local L2 (structure view)"
            ),
        )
        _render_seed_sheet(
            formal_rows,
            formal_sheet,
            title=(
                "Stage 5E: formal Stage4/Stage5 sparse L2 output "
                "(actual L1-only plus few left/right forks)"
            ),
        )
        manifest = {
            "schema": "dynamic_branch_stage5e_l2_sparse_review_manifest_v1",
            "scope": (
                "all five SW prototypes under the frozen 5D production-"
                "default density, varying unit_seed for sparse local L2"
            ),
            "prototype_order": list(PROTOTYPE_IDS),
            "unit_seed_order": list(UNIT_SEEDS),
            "fixed_seed_domains": {
                "production_seed": PRODUCTION_SEED,
                "backbone_seed": BACKBONE_SEED,
                "flower_seed": FLOWER_SEED,
                "flower_rho": FLOWER_RHO,
                "branch_seed": BRANCH_SEED,
                "ordinary_density_level": "production_default_from_branch_seed",
            },
            "only_changed_input": "unit_seed",
            "stage5_selection_contract": str(STAGE5E_CONTRACT_PATH),
            "production_chain": [
                "frozen_5d_backbone_flower_and_ordinary_l1_set",
                "stage4_unit_candidate_inventory",
                "stage5_sparse_local_l2_global_selection",
                "formal_render",
            ],
            "stage_boundaries": {
                "frozen_5d_l1_set_preserved": True,
                "sparse_local_l2_policy_consumed": True,
                "l3_selected_count_is_zero": True,
                "leaves_or_swollen_rhizomes_generated": False,
                "5f_full_integration_started": False,
            },
            "frozen_5d_verification": frozen_rows,
            "unit_seed_variation": variation_rows,
            "mechanical_summary": {
                "selected_curve_crossing_count": total_crossings,
                "selected_near_clearance_violation_count": (
                    total_clearance_violations
                ),
                "selected_l2_attachment_violation_count": 0,
            },
            "review_gate": {
                "status": "VISUAL_REVIEW_PENDING",
                "numeric_checks_cannot_auto_approve_visual_gate": True,
            },
            "contact_sheets": {
                "color_structure": structure_sheet.name,
                "formal_sparse_l2": formal_sheet.name,
            },
            "provenance": provenance,
            "tasks": task_rows,
        }
        _write_json(temporary / "manifest.json", manifest)
        temporary.replace(output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the Stage-5E sparse local-L2 review."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="review output directory (default: artifacts/runs/"
        "dynamic_branch_stage5e_l2_sparse_review_v1)",
    )
    args = parser.parse_args()
    try:
        run(args.output_dir)
    except Stage5EL2SparseReviewError as exc:
        raise SystemExit(f"stage-5E review error: {exc}") from exc
    print(f"stage-5E sparse L2 review written to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
