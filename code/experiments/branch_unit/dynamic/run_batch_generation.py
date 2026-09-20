#!/usr/bin/env python3
"""Large-scale batch generation through the frozen 5A-5F production chain."""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "artifacts" / "runs" / "dynamic_branch_batch_v3"
)
EXPECTED_STAGE3B_PLAN_SCHEMA = "dynamic_branch_global_l1_flow_plan_v3"
EXPECTED_STAGE3B_CONTRACT_ID = "soft_density_global_l1_flow_v3"
EXPECTED_STAGE5_CONTRACT_ID = "stage5e_joint_sparse_local_l2_selection_v2"
STAGE4_CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json"
STAGE5E_CONTRACT_PATH = (
    DYNAMIC_DIR / "STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json"
)
EDITOR_L2_PRIOR_PATH = DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json"

PROTOTYPE_IDS = (
    "proto_sw_1_1",
    "proto_sw_1_3",
    "proto_sw_2_3",
    "proto_sw_3_1",
    "proto_sw_3_2",
)
VARIANT_IDS = ("expanded", "compact", "swept")
DENSITY_LEVELS = ("simple", "medium", "rich")

_G: dict[str, Any] = {}


class BatchGenerationError(RuntimeError):
    """One case cannot be produced through the frozen chain."""


def _init() -> None:
    sys.path.insert(0, str(DYNAMIC_DIR))
    from run_stage3b_l1_flow import _load_inputs

    (
        inputs,
        prior,
        feedback_prior,
        curve_geometry_prior,
        contract,
        stage3_plan_contract,
        provenance,
    ) = _load_inputs()
    _G.update(
        inputs=inputs,
        prior=prior,
        feedback_prior=feedback_prior,
        curve_geometry_prior=curve_geometry_prior,
        contract=contract,
        stage3_plan_contract=stage3_plan_contract,
        provenance=provenance,
        stage4_contract=_read_json(STAGE4_CONTRACT_PATH),
        stage5e_contract=_read_json(STAGE5E_CONTRACT_PATH),
        editor_l2_prior=_read_json(EDITOR_L2_PRIOR_PATH),
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BatchGenerationError(f"JSON root must be an object: {path}")
    return value


def _downstream_unit_clearance(
    strategy: Mapping[str, Any],
    editor_l2_prior: Mapping[str, Any],
    stage4_contract: Mapping[str, Any],
) -> float:
    """The full-Unit clearance Stage5 will require for this prototype."""

    profile_key = str(strategy["branchunit_profile"]["editor_l2_profile_key"])
    profile = editor_l2_prior["profiles"][profile_key]
    editor_q10 = float(
        profile["nonparent_curve_clearance_unit_ratio"]["q10"]
    )
    occupancy_diameter = 2.0 * float(
        stage4_contract["geometry"]["occupancy_radius"]
    )
    return max(occupancy_diameter, editor_q10)


def production_cell(prototype_id: str, production_seed: int) -> tuple[str, str]:
    """Resolve the discrete backbone-variant and density cell without geometry."""

    from backbone_variation_v1 import (
        production_prototype_variant_id,
        split_generation_seeds,
    )
    from global_l1_flow import _seed_unit

    domains = split_generation_seeds(production_seed)
    variant = production_prototype_variant_id(
        domains["backbone_seed"],
        prototype_id,
    )
    density_unit = _seed_unit(
        str(prototype_id),
        domains["branch_seed"],
        "ordinary_l1_density_level_v1",
    )
    density = DENSITY_LEVELS[
        min(len(DENSITY_LEVELS) - 1, int(density_unit * len(DENSITY_LEVELS)))
    ]
    return str(variant), str(density)


def allocate_stratified(
    prototype_id: str,
    count: int,
    seed_candidates: Sequence[int],
) -> list[int]:
    """Spread the requested case count evenly over the 3x3 discrete cells."""

    # Distribute the remainder across variants first so small batches do not
    # collapse onto a single backbone direction.
    cells = [
        (variant, density)
        for density in DENSITY_LEVELS
        for variant in VARIANT_IDS
    ]
    base, remainder = divmod(count, len(cells))
    targets = {
        cell: base + (1 if index < remainder else 0)
        for index, cell in enumerate(cells)
    }
    chosen: dict[tuple[str, str], list[int]] = {cell: [] for cell in cells}
    for seed in seed_candidates:
        cell = production_cell(prototype_id, seed)
        if len(chosen[cell]) < targets[cell]:
            chosen[cell].append(seed)
        if sum(len(value) for value in chosen.values()) >= count:
            break
    ordered = [
        seed
        for cell in cells
        for seed in chosen[cell]
    ]
    if len(ordered) < count:
        used = set(ordered)
        for seed in seed_candidates:
            if seed not in used:
                ordered.append(seed)
                used.add(seed)
            if len(ordered) >= count:
                break
    return ordered[:count]


def _generate_case(
    item: tuple[str, int, bool, str, str],
) -> dict[str, Any]:
    prototype_id, production_seed, slim, render_mode, output_dir_str = item
    output_dir = Path(output_dir_str)
    from backbone_variation_v1 import split_generation_seeds
    from branch_unit_grammar_v1 import (
        generate_unit_candidate_inventory,
        validate_unit_candidate_inventory,
    )
    from render_global_l1_flow import render_png as render_l1_png
    from render_stage5_global_selection import render_global_selection
    from run_stage3b_l1_flow import generate_prototype_case
    from run_stage5e_l2_sparse_review import (
        L2_ATTACHMENT_TOLERANCE,
        _check_frozen_l1_invariance,
        _check_l2_real_attachment,
        _selected_pair_mechanics,
    )
    from stage5_global_unit_selection import (
        build_conflict_graph,
        select_global_units,
        validate_global_selection,
    )

    strategy_registry = _load_registry()
    strategy = strategy_registry[prototype_id]
    downstream_clearance = _downstream_unit_clearance(
        strategy,
        _G["editor_l2_prior"],
        _G["stage4_contract"],
    )
    result = generate_prototype_case(
        payload=_G["inputs"][prototype_id],
        prototype_strategy=strategy,
        production_seed=production_seed,
        prior=_G["prior"],
        feedback_prior=_G["feedback_prior"],
        curve_geometry_prior=_G["curve_geometry_prior"],
        contract=_G["contract"],
        stage3_plan_contract=_G["stage3_plan_contract"],
        backbone_seed_override=None,
        flower_seed_override=None,
        branch_seed_override=None,
        unit_seed_override=None,
        backbone_rho=None,
        flower_rho=None,
        ordinary_density_level_override=None,
        downstream_unit_clearance=downstream_clearance,
    )
    analysis = result["variant_analysis"]
    plan = result["plan"]
    flower_mount_plan = result["flower_mount_plan"]
    flower_layout_plan = result["flower_layout_plan"]
    strict_value = result["variant_strict"].as_dict()
    inventory = result["inventory"]
    stage4_contract = _G["stage4_contract"]
    stage5e_contract = _G["stage5e_contract"]
    editor_l2_prior = _G["editor_l2_prior"]

    unit_inventory = generate_unit_candidate_inventory(
        plan,
        analysis,
        _G["prior"],
        stage4_contract,
        editor_l2_prior,
    )
    validate_unit_candidate_inventory(unit_inventory, stage4_contract)
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
        raise BatchGenerationError("formal selection infeasible")
    _check_frozen_l1_invariance(plan, selection)
    for candidate in selection["selected_candidates"]:
        _check_l2_real_attachment(candidate, L2_ATTACHMENT_TOLERANCE)
    mechanics = _selected_pair_mechanics(selection, conflict_graph)
    if (
        mechanics["curve_crossing_count"] != 0
        or mechanics["near_clearance_violation_count"] != 0
    ):
        raise BatchGenerationError(
            "independent crossing or clearance check failed"
        )
    trace = selection["solver_trace"]
    if int(trace["selected_l3_count"]) != 0:
        raise BatchGenerationError("formal selection contains L3 geometry")

    case_dir = (
        output_dir
        / prototype_id
        / f"seed_{production_seed}"
    )
    case_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {
        "derived_seeds.json": case_dir / "derived_seeds.json",
        "backbone_variation.json": case_dir / "backbone_variation.json",
        "strict_p0_variant.json": case_dir / "strict_p0_variant.json",
        "prototype_analysis_variant.json": case_dir
        / "prototype_analysis_variant.json",
        "flower_layout_plan.json": case_dir / "flower_layout_plan.json",
        "flower_mount_plan.json": case_dir / "flower_mount_plan.json",
        "global_l1_flow_plan.json": case_dir / "global_l1_flow_plan.json",
        "global_unit_selection.json": case_dir
        / "global_unit_selection.json",
    }
    if not slim:
        paths.update(
            {
                "global_l1_candidate_inventory.json": case_dir
                / "global_l1_candidate_inventory.json",
                "unit_candidate_inventory.json": case_dir
                / "unit_candidate_inventory.json",
                "candidate_conflict_graph.json": case_dir
                / "candidate_conflict_graph.json",
                "structure_debug.png": case_dir / "structure_debug.png",
            }
        )
    if render_mode in {"single", "both"}:
        paths["formal_single.png"] = case_dir / "formal_single.png"
    if render_mode in {"triple", "both"}:
        paths["formal_triple.png"] = case_dir / "formal_triple.png"

    _write_json(
        paths["derived_seeds.json"],
        {
            "production_seed": production_seed,
            **split_generation_seeds(production_seed),
        },
    )
    _write_json(paths["backbone_variation.json"], result["variation"])
    _write_json(paths["strict_p0_variant.json"], strict_value)
    _write_json(paths["prototype_analysis_variant.json"], analysis)
    _write_json(paths["flower_layout_plan.json"], flower_layout_plan)
    _write_json(paths["flower_mount_plan.json"], flower_mount_plan)
    _write_json(paths["global_l1_flow_plan.json"], plan)
    _write_json(paths["global_unit_selection.json"], selection)
    if not slim:
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
        render_l1_png(
            analysis,
            plan,
            paths["structure_debug.png"],
            debug=True,
        )
    if render_mode in {"single", "both"}:
        render_global_selection(
            analysis,
            unit_inventory,
            conflict_graph,
            selection,
            paths["formal_single.png"],
            triple_repeat=False,
            flower_mount_plan=flower_mount_plan,
        )
    if render_mode in {"triple", "both"}:
        render_global_selection(
            analysis,
            unit_inventory,
            conflict_graph,
            selection,
            paths["formal_triple.png"],
            triple_repeat=True,
            flower_mount_plan=flower_mount_plan,
        )

    cell = production_cell(prototype_id, production_seed)
    summary = {
        "stage3b_plan_schema": str(plan["schema"]),
        "stage3b_contract_id": str(_G["contract"]["contract_id"]),
        "stage5_contract_id": str(stage5e_contract["contract_id"]),
        "density_objective_version": str(
            plan["solver"]["density_objective"]["version"]
        ),
        "prototype_id": prototype_id,
        "production_seed": production_seed,
        "backbone_variant_id": cell[0],
        "density_level": cell[1],
        "plan_id": plan["plan_id"],
        "ordinary_l1_count": len(plan["lanes"]),
        "flower_support_count": len(flower_mount_plan["mounts"]),
        "achieved_upgrade_count": int(trace["achieved_upgrade_count"]),
        "selected_l2_count": int(trace["selected_l2_count"]),
        "selected_l3_count": int(trace["selected_l3_count"]),
        "downstream_mount_projection_used": bool(
            result["downstream_mount_projection"]["used"]
        ),
        "downstream_unit_clearance": round(downstream_clearance, 9),
        "mechanical_checks": mechanics,
        "slim": slim,
        "render_mode": render_mode,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "files": {
            name: str(path.relative_to(output_dir)).replace("\\", "/")
            for name, path in paths.items()
        },
    }
    _write_json(case_dir / "case_manifest.json", summary)
    return summary


def _load_registry() -> dict[str, Any]:
    from prototype_strategy_v1 import (
        load_prototype_strategy_registry,
        resolve_prototype_strategy,
    )

    registry = load_prototype_strategy_registry()
    return {
        prototype_id: resolve_prototype_strategy(
            {"prototype_id": prototype_id},
            registry,
        )
        for prototype_id in PROTOTYPE_IDS
    }


def _safe_generate(
    item: tuple[str, int, bool, str, str],
) -> dict[str, Any]:
    try:
        return {"ok": True, "summary": _generate_case(item)}
    except Exception as exc:  # noqa: BLE001 - batch must record per-case failures
        prototype_id, production_seed, _, _, _ = item
        return {
            "ok": False,
            "prototype_id": prototype_id,
            "production_seed": production_seed,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a stratified batch through the frozen chain."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cases-per-prototype", type=int, default=20)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--seed-start", type=int, default=100000)
    parser.add_argument("--allocation", choices=("stratified", "sequential"), default="stratified")
    parser.add_argument("--render", choices=("single", "triple", "both"), default="both")
    parser.add_argument("--slim", action="store_true")
    args = parser.parse_args()
    if args.cases_per_prototype <= 0 or args.workers <= 0:
        raise SystemExit("cases-per-prototype and workers must be positive")

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in (STAGE4_CONTRACT_PATH, STAGE5E_CONTRACT_PATH, EDITOR_L2_PRIOR_PATH):
        if not path.is_file():
            raise SystemExit(f"missing batch input: {path}")

    seed_window = max(args.cases_per_prototype * 60, 60)
    seed_candidates = list(
        range(args.seed_start, args.seed_start + seed_window)
    )
    tasks: list[tuple[str, int, bool, str, str]] = []
    for prototype_id in PROTOTYPE_IDS:
        if args.allocation == "stratified":
            seeds = allocate_stratified(
                prototype_id,
                args.cases_per_prototype,
                seed_candidates,
            )
        else:
            seeds = seed_candidates[: args.cases_per_prototype]
        for seed in seeds:
            case_dir = output_dir / prototype_id / f"seed_{seed}"
            case_manifest_path = case_dir / "case_manifest.json"
            if case_manifest_path.is_file():
                existing_case = _read_json(case_manifest_path)
                if (
                    existing_case.get("stage3b_plan_schema")
                    == EXPECTED_STAGE3B_PLAN_SCHEMA
                    and existing_case.get("stage3b_contract_id")
                    == EXPECTED_STAGE3B_CONTRACT_ID
                    and existing_case.get("stage5_contract_id")
                    == EXPECTED_STAGE5_CONTRACT_ID
                ):
                    continue
                raise SystemExit(
                    "existing batch case belongs to an incompatible Stage3B "
                    f"chain: {case_manifest_path}"
                )
            tasks.append(
                (
                    prototype_id,
                    seed,
                    args.slim,
                    args.render,
                    str(output_dir),
                )
            )

    print(
        f"batch: {len(tasks)} pending cases, {args.workers} workers, "
        f"slim={args.slim}, render={args.render}, output={output_dir}"
    )
    if not tasks:
        print("nothing to do")
        return 0

    summaries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    start = time.perf_counter()
    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=_init,
    ) as pool:
        futures = [pool.submit(_safe_generate, task) for task in tasks]
        done = 0
        for future in as_completed(futures):
            done += 1
            payload = future.result()
            if payload["ok"]:
                summaries.append(payload["summary"])
            else:
                failures.append(payload)
            if done % 5 == 0 or done == len(tasks):
                elapsed = time.perf_counter() - start
                print(
                    f"progress: {done}/{len(tasks)} cases, "
                    f"{len(failures)} failures, {elapsed:.0f}s"
                )

    sys.path.insert(0, str(DYNAMIC_DIR))
    from run_stage3b_l1_flow import _load_inputs

    provenance = _load_inputs()[6]
    total_crossings = sum(
        int(row["mechanical_checks"]["curve_crossing_count"])
        for row in summaries
    )
    total_clearance = sum(
        int(row["mechanical_checks"]["near_clearance_violation_count"])
        for row in summaries
    )
    coverage: dict[str, dict[str, int]] = {}
    for row in summaries:
        key = f"{row['backbone_variant_id']}__{row['density_level']}"
        coverage.setdefault(row["prototype_id"], {})
        coverage[row["prototype_id"]][key] = (
            coverage[row["prototype_id"]].get(key, 0) + 1
        )
    manifest = {
        "schema": "dynamic_branch_batch_generation_manifest_v3",
        "stage3b_plan_schema": EXPECTED_STAGE3B_PLAN_SCHEMA,
        "stage3b_contract_id": EXPECTED_STAGE3B_CONTRACT_ID,
        "stage5_contract_id": EXPECTED_STAGE5_CONTRACT_ID,
        "output_dir": str(output_dir),
        "cases_per_prototype_requested": args.cases_per_prototype,
        "allocation": args.allocation,
        "slim": args.slim,
        "render_mode": args.render,
        "workers": args.workers,
        "successful_case_count": len(summaries),
        "failed_case_count": len(failures),
        "prototype_order": list(PROTOTYPE_IDS),
        "coverage_by_cell": coverage,
        "mechanical_summary": {
            "selected_curve_crossing_count": total_crossings,
            "selected_near_clearance_violation_count": total_clearance,
        },
        "provenance": provenance,
        "tasks": summaries,
    }
    _write_json(output_dir / "manifest.json", manifest)
    _write_json(output_dir / "failures.json", failures)
    elapsed = time.perf_counter() - start
    print(
        f"batch complete: {len(summaries)} ok, {len(failures)} failed, "
        f"{elapsed:.0f}s"
    )
    return 0 if summaries else 1


if __name__ == "__main__":
    raise SystemExit(main())
