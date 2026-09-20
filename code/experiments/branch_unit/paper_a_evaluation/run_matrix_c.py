#!/usr/bin/env python3
"""Run the frozen four-method Matrix-C ablation on shared upstream contexts."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
PROTOCOL_DIR = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "protocol"
STAGE4_CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json"
OURS_CONTRACT_PATH = DYNAMIC_DIR / "STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json"
LOCAL_CONTRACT_PATH = DYNAMIC_DIR / "STAGE5E_L2_SPARSE_SELECTION_CONTRACT_V1.json"
EDITOR_L2_PRIOR_PATH = DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json"
METHODS = ("IndependentCurve", "FixedSlot", "LocalGreedy", "Ours")

if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

_WORKER: dict[str, Any] = {}

RESULT_FIELDS = (
    "case_id",
    "method",
    "prototype_id",
    "backbone_variant",
    "density_level",
    "replicate",
    "production_seed",
    "generation_success",
    "l1_generation_success",
    "unit_generation_applicable",
    "unit_generation_success",
    "error_type",
    "error_message",
    "ordinary_l1_count",
    "selected_l2_count",
    "branchunit_count",
    "shared_stage3_plan_id",
    "shared_stage4_inventory_id",
    "shared_conflict_graph_id",
    "method_plan_id",
    "method_selection_id",
    "runtime_seconds",
    "method_dir",
)


class MatrixCError(RuntimeError):
    """One frozen ablation context cannot be executed as specified."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MatrixCError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_matrix_c(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["matrix_id"] == "C"]
    if len(rows) != 90:
        raise MatrixCError(f"Matrix-C must contain 90 frozen contexts, got {len(rows)}")
    return rows


def _write_results(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _init_worker() -> None:
    from prototype_strategy_v1 import (
        load_prototype_strategy_registry,
        resolve_prototype_strategy,
    )
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
    registry = load_prototype_strategy_registry()
    strategies = {
        prototype_id: resolve_prototype_strategy({"prototype_id": prototype_id}, registry)
        for prototype_id in inputs
    }
    _WORKER.update(
        inputs=inputs,
        prior=prior,
        feedback_prior=feedback_prior,
        curve_geometry_prior=curve_geometry_prior,
        contract=contract,
        stage3_plan_contract=stage3_plan_contract,
        provenance=provenance,
        strategies=strategies,
        stage4_contract=_read_json(STAGE4_CONTRACT_PATH),
        ours_contract=_read_json(OURS_CONTRACT_PATH),
        local_contract=_read_json(LOCAL_CONTRACT_PATH),
        editor_l2_prior=_read_json(EDITOR_L2_PRIOR_PATH),
    )


def _assign_current_lane_ids(candidates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for index, candidate in enumerate(
        sorted(candidates, key=lambda row: (float(row["root_s"]), str(row["candidate_id"]))),
        start=1,
    ):
        row = dict(candidate)
        lane_id = f"selected_l1_{index:03d}"
        row["selected_l1_id"] = lane_id
        row["slot_id"] = lane_id
        row["legacy_identity_alias"] = "slot_id_equals_selected_l1_id"
        row["role"] = "primary_sweep"
        selected.append(row)
    return selected


def _root_rhythm(lanes: Sequence[Mapping[str, Any]], source: str) -> dict[str, Any]:
    roots = sorted(float(lane["root_s"]) % 1.0 for lane in lanes)
    gaps = [
        (roots[(index + 1) % len(roots)] - roots[index]) % 1.0
        for index in range(len(roots))
    ]
    return {
        "source": source,
        "selected_root_s": [round(value, 9) for value in roots],
        "gaps": [round(value, 9) for value in gaps],
        "preassigned_preferred_roots_used": source == "legacy_fixed_slots",
    }


def _adapt_plan(
    ours_plan: Mapping[str, Any],
    lanes: Sequence[Mapping[str, Any]],
    *,
    method: str,
    solver: Mapping[str, Any],
    preassigned_slots: bool,
) -> dict[str, Any]:
    from global_l1_flow import canonical_digest

    plan = copy.deepcopy(dict(ours_plan))
    plan.pop("plan_digest", None)
    plan["plan_id"] = f"{ours_plan['plan_id']}__baseline_{method.lower()}"
    plan["lanes"] = list(lanes)
    support_count = int(plan["count_derivation"].get("required_support_count", 0))
    plan["count_derivation"].update(
        ordinary_lane_count=len(lanes),
        selected_ordinary_l1_count=len(lanes),
        selected_l1_count=len(lanes) + support_count,
        total_l1_with_flower_support_count=len(lanes) + support_count,
    )
    plan["role_counts"] = dict(Counter(str(lane["role"]) for lane in lanes))
    plan["root_rhythm"] = _root_rhythm(
        lanes,
        "legacy_fixed_slots" if preassigned_slots else "individual_score_only",
    )
    plan["preassigned_selection_slots_used"] = preassigned_slots
    plan["selection_semantics"] = method
    plan["solver"] = dict(solver)
    plan["diagnostics"] = {
        **plan["diagnostics"],
        "lane_count": len(lanes),
        "hard_issue_count": 0,
        "automatic_repair_used": False,
        "automatic_deletion_used": False,
        "validation_guided_retry_used": False,
        "validation_guided_resample_used": False,
    }
    plan["plan_digest"] = canonical_digest(plan)
    return plan


def _independent_plan(
    ours_plan: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    target_count = len(ours_plan["lanes"])
    feasible = [
        candidate
        for candidate in inventory["candidates"]
        if not candidate.get("hard_rejections")
    ]
    ranked = sorted(
        feasible,
        key=lambda row: (-float(row["individual_score"]), str(row["candidate_id"])),
    )
    if len(ranked) < target_count:
        raise MatrixCError(
            f"IndependentCurve has {len(ranked)} feasible candidates for K={target_count}"
        )
    selected = _assign_current_lane_ids(ranked[:target_count])
    plan = _adapt_plan(
        ours_plan,
        selected,
        method="IndependentCurve",
        solver={
            "method": "independent_individual_score_ranking",
            "requested_count": target_count,
            "candidate_count": len(feasible),
            "pair_conflict_graph_used": False,
            "root_deduplication_used": False,
            "posthoc_repair_used": False,
        },
        preassigned_slots=False,
    )
    return plan, {
        "candidate_count": len(feasible),
        "selected_candidate_ids": [lane["candidate_id"] for lane in selected],
    }


def _fixed_slot_plan(
    ours_plan: Mapping[str, Any],
    analysis: Mapping[str, Any],
    flower_mount_plan: Mapping[str, Any],
    strategy: Mapping[str, Any],
    prior: Mapping[str, Any],
    branch_seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from global_l1_flow import (
        Slot,
        _candidate_rejections,
        _global_latents,
        _ordinary_candidates,
        _slot_roles,
        _solve,
        _vertical_preferences,
    )

    target_count = len(ours_plan["lanes"])
    latents = _global_latents(str(analysis["prototype_id"]), branch_seed)
    l1_policy = strategy["l1_profile"]
    vertical = _vertical_preferences(
        str(l1_policy["side_rhythm"]), target_count, branch_seed
    )
    roles = _slot_roles(
        str(strategy["family_id"]), target_count, l1_policy["ordinary_role_cycle"]
    )
    slots = [
        Slot(
            slot_id=f"ordinary_{index + 1}",
            role=roles[index],
            index=index,
            flower_id=None,
            preferred_s=((index + 0.5) / target_count + float(latents["flow_phase"])) % 1.0,
            preferred_vertical_side=vertical[index],
        )
        for index in range(target_count)
    ]
    pools: dict[str, list[dict[str, Any]]] = {}
    inventory_rows: list[dict[str, Any]] = []
    mechanism = str(strategy["flower_mount"]["mechanism"])
    for slot in slots:
        candidates = _ordinary_candidates(
            slot,
            analysis,
            prior,
            latents,
            lane_count=target_count,
            branch_seed=branch_seed,
        )
        feasible: list[dict[str, Any]] = []
        for candidate in candidates:
            reasons = _candidate_rejections(
                candidate,
                analysis,
                str(strategy["family_id"]),
                prior,
                None,
                flower_mount_plan,
                None,
                mechanism,
            )
            row = dict(candidate)
            row["hard_rejections"] = list(reasons)
            inventory_rows.append(row)
            if not reasons:
                feasible.append(candidate)
        if not feasible:
            raise MatrixCError(f"FixedSlot slot {slot.slot_id} has no feasible candidates")
        pools[slot.slot_id] = feasible
    selected, legacy_solver = _solve(slots, pools, prior, None, None)
    lanes = _assign_current_lane_ids(selected)
    plan = _adapt_plan(
        ours_plan,
        lanes,
        method="FixedSlot",
        solver={
            "method": "legacy_preassigned_slot_global_beam",
            "requested_count": target_count,
            "legacy_solver": legacy_solver,
            "support_slots_generated": False,
            "posthoc_repair_used": False,
        },
        preassigned_slots=True,
    )
    return plan, {
        "schema": "paper_a_fixed_slot_candidate_inventory_v1",
        "candidate_count": len(inventory_rows),
        "candidates": inventory_rows,
        "selected_candidate_ids": [lane["candidate_id"] for lane in lanes],
    }


def _l1_selection(plan: Mapping[str, Any], method: str) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for lane in plan["lanes"]:
        lane_id = str(lane["selected_l1_id"])
        curve_id = f"{lane_id}.L1"
        candidates.append(
            {
                "candidate_id": f"{method}__{lane_id}",
                "source_lane_id": lane_id,
                "parameter_stratum": method,
                "hierarchy": {"l1_count": 1, "l2_count": 0, "l3_count": 0, "maximum_level": 1},
                "curves": [
                    {
                        "curve_id": curve_id,
                        "parent_curve_id": None,
                        "level": "L1",
                        "hierarchy_level": 1,
                        "centerline": lane["centerline"],
                        "cubic_segments": lane["segments"],
                        "actual_length": lane["planning_length"],
                        "semantic_role": lane.get("role", "primary_sweep"),
                    }
                ],
            }
        )
    return {
        "schema": "paper_a_l1_baseline_selection_v1",
        "selection_id": f"{plan['plan_id']}__selection",
        "prototype_id": plan["prototype_id"],
        "seed": plan["unit_seed"],
        "feasible": True,
        "lane_count": len(candidates),
        "selected_candidate_count": len(candidates),
        "selected_candidates": candidates,
        "solver_trace": {
            "method": method,
            "selected_l1_only_count": len(candidates),
            "selected_l2_count": 0,
            "selected_l3_count": 0,
        },
    }


def _render_and_save_method(
    *,
    method_dir: Path,
    method: str,
    row: Mapping[str, str],
    strict: Mapping[str, Any],
    analysis: Mapping[str, Any],
    flower_mount_plan: Mapping[str, Any],
    plan: Mapping[str, Any],
    selection: Mapping[str, Any],
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
) -> None:
    from export_batch_svgs import render_case_svg
    from render_stage5_global_selection import render_global_selection

    method_dir.mkdir(parents=True, exist_ok=False)
    _write_json(method_dir / "strict_p0_variant.json", strict)
    _write_json(method_dir / "prototype_analysis_variant.json", analysis)
    _write_json(method_dir / "flower_mount_plan.json", flower_mount_plan)
    _write_json(method_dir / "global_l1_flow_plan.json", plan)
    _write_json(method_dir / "global_unit_selection.json", selection)
    render_global_selection(
        analysis,
        inventory,
        conflict_graph,
        selection,
        method_dir / "formal_triple.png",
        triple_repeat=True,
        flower_mount_plan=flower_mount_plan,
    )
    provenance = {
        "prototype_id": row["prototype_id"],
        "production_seed": int(row["production_seed"]),
        "backbone_seed": int(row["backbone_seed"]),
        "flower_seed": int(row["flower_seed"]),
        "branch_seed": int(row["branch_seed"]),
        "unit_seed": int(row["unit_seed"]),
        "backbone_variant_id": row["backbone_variant"],
        "density_level": row["density_level"],
        "source_case": row["case_id"],
        "source_contract_id": method,
        "source_plan_id": plan["plan_id"],
        "source_selection_id": selection["selection_id"],
    }
    (method_dir / "formal_triple.svg").write_text(
        render_case_svg(
            analysis,
            flower_mount_plan,
            selection,
            provenance,
            repeat="triple",
            palette="role",
        ),
        encoding="utf-8",
        newline="\n",
    )


def _method_result(
    row: Mapping[str, str],
    method: str,
    *,
    success: bool,
    l1_success: bool,
    unit_applicable: bool,
    unit_success: bool,
    started: float,
    plan: Mapping[str, Any] | None = None,
    selection: Mapping[str, Any] | None = None,
    shared_inventory_id: str = "",
    shared_graph_id: str = "",
    method_dir: str = "",
    error: Exception | None = None,
) -> dict[str, object]:
    trace = selection.get("solver_trace", {}) if selection else {}
    return {
        "case_id": row["case_id"],
        "method": method,
        "prototype_id": row["prototype_id"],
        "backbone_variant": row["backbone_variant"],
        "density_level": row["density_level"],
        "replicate": int(row["replicate"]),
        "production_seed": int(row["production_seed"]),
        "generation_success": int(success),
        "l1_generation_success": int(l1_success),
        "unit_generation_applicable": int(unit_applicable),
        "unit_generation_success": int(unit_success),
        "error_type": type(error).__name__ if error else "",
        "error_message": str(error) if error else "",
        "ordinary_l1_count": len(plan["lanes"]) if plan else "",
        "selected_l2_count": int(trace.get("selected_l2_count", 0)) if selection else "",
        "branchunit_count": len(selection["selected_candidates"]) if selection else "",
        "shared_stage3_plan_id": "" if plan is None else str(plan.get("source_ours_plan_id", "")),
        "shared_stage4_inventory_id": shared_inventory_id,
        "shared_conflict_graph_id": shared_graph_id,
        "method_plan_id": str(plan["plan_id"]) if plan else "",
        "method_selection_id": str(selection["selection_id"]) if selection else "",
        "runtime_seconds": time.perf_counter() - started,
        "method_dir": method_dir,
    }


def _run_context(row: Mapping[str, str], output_dir: Path) -> dict[str, Any]:
    from branch_unit_grammar_v1 import generate_unit_candidate_inventory
    from run_batch_generation import _downstream_unit_clearance
    from run_stage3b_l1_flow import generate_prototype_case
    from stage5_global_unit_selection import build_conflict_graph, select_global_units

    if not _WORKER:
        _init_worker()
    case_dir = output_dir / "raw_cases" / row["case_id"]
    case_dir.mkdir(parents=True, exist_ok=False)
    _write_json(case_dir / "case_input.json", dict(row))
    prototype_id = row["prototype_id"]
    strategy = _WORKER["strategies"][prototype_id]
    clearance = _downstream_unit_clearance(
        strategy, _WORKER["editor_l2_prior"], _WORKER["stage4_contract"]
    )
    generated = generate_prototype_case(
        payload=_WORKER["inputs"][prototype_id],
        prototype_strategy=strategy,
        production_seed=int(row["production_seed"]),
        prior=_WORKER["prior"],
        feedback_prior=_WORKER["feedback_prior"],
        curve_geometry_prior=_WORKER["curve_geometry_prior"],
        contract=_WORKER["contract"],
        stage3_plan_contract=_WORKER["stage3_plan_contract"],
        backbone_seed_override=int(row["backbone_seed"]),
        flower_seed_override=int(row["flower_seed"]),
        branch_seed_override=int(row["branch_seed"]),
        unit_seed_override=int(row["unit_seed"]),
        backbone_rho=None,
        prototype_variant_id=row["backbone_variant"],
        flower_rho=None,
        ordinary_density_level_override=row["density_level"],
        downstream_unit_clearance=clearance,
    )
    strict = generated["variant_strict"].as_dict()
    analysis = generated["variant_analysis"]
    flower_mount_plan = generated["flower_mount_plan"]
    ours_plan = generated["plan"]
    ours_plan["source_ours_plan_id"] = ours_plan["plan_id"]
    shared_inventory = generate_unit_candidate_inventory(
        ours_plan,
        analysis,
        _WORKER["prior"],
        _WORKER["stage4_contract"],
        _WORKER["editor_l2_prior"],
    )
    shared_graph = build_conflict_graph(
        shared_inventory,
        _WORKER["ours_contract"],
        _WORKER["editor_l2_prior"],
    )
    _write_json(case_dir / "shared_stage4_inventory.json", shared_inventory)
    _write_json(case_dir / "shared_conflict_graph.json", shared_graph)

    results: list[dict[str, object]] = []
    method_root = case_dir / "methods"
    for method in METHODS:
        started = time.perf_counter()
        plan: dict[str, Any] | None = None
        selection: dict[str, Any] | None = None
        inventory: Mapping[str, Any] = {}
        graph: Mapping[str, Any] = {}
        try:
            if method == "Ours":
                plan = ours_plan
                inventory = shared_inventory
                graph = shared_graph
                selection = select_global_units(inventory, graph, _WORKER["ours_contract"])
            elif method == "LocalGreedy":
                plan = ours_plan
                inventory = shared_inventory
                graph = shared_graph
                selection = select_global_units(inventory, graph, _WORKER["local_contract"])
            elif method == "IndependentCurve":
                plan, baseline_inventory = _independent_plan(ours_plan, generated["inventory"])
                plan["source_ours_plan_id"] = ours_plan["plan_id"]
                selection = _l1_selection(plan, method)
                inventory = {"candidates": selection["selected_candidates"]}
                graph = {}
                _write_json(case_dir / "independent_curve_inventory.json", baseline_inventory)
            else:
                plan, fixed_inventory = _fixed_slot_plan(
                    ours_plan,
                    analysis,
                    flower_mount_plan,
                    strategy,
                    _WORKER["prior"],
                    int(row["branch_seed"]),
                )
                plan["source_ours_plan_id"] = ours_plan["plan_id"]
                inventory = generate_unit_candidate_inventory(
                    plan,
                    analysis,
                    _WORKER["prior"],
                    _WORKER["stage4_contract"],
                    _WORKER["editor_l2_prior"],
                )
                graph = build_conflict_graph(
                    inventory,
                    _WORKER["ours_contract"],
                    _WORKER["editor_l2_prior"],
                )
                selection = select_global_units(inventory, graph, _WORKER["ours_contract"])
                _write_json(case_dir / "fixed_slot_l1_inventory.json", fixed_inventory)
            if not bool(selection.get("feasible")):
                raise MatrixCError(f"{method} selection returned infeasible")
            method_dir = method_root / method
            _render_and_save_method(
                method_dir=method_dir,
                method=method,
                row=row,
                strict=strict,
                analysis=analysis,
                flower_mount_plan=flower_mount_plan,
                plan=plan,
                selection=selection,
                inventory=inventory,
                conflict_graph=graph,
            )
            results.append(
                _method_result(
                    row,
                    method,
                    success=True,
                    l1_success=True,
                    unit_applicable=method != "IndependentCurve",
                    unit_success=method != "IndependentCurve",
                    started=started,
                    plan=plan,
                    selection=selection,
                    shared_inventory_id=(
                        str(shared_inventory["inventory_id"])
                        if method in {"Ours", "LocalGreedy"}
                        else ""
                    ),
                    shared_graph_id=(
                        str(shared_graph.get("conflict_graph_digest", ""))
                        if method in {"Ours", "LocalGreedy"}
                        else ""
                    ),
                    method_dir=str(method_dir.relative_to(output_dir)).replace("\\", "/"),
                )
            )
        except Exception as exc:
            fallback_dir = ""
            if plan is not None:
                try:
                    fallback_selection = _l1_selection(plan, method)
                    fallback_method_dir = method_root / method
                    _render_and_save_method(
                        method_dir=fallback_method_dir,
                        method=method,
                        row=row,
                        strict=strict,
                        analysis=analysis,
                        flower_mount_plan=flower_mount_plan,
                        plan=plan,
                        selection=fallback_selection,
                        inventory={"candidates": fallback_selection["selected_candidates"]},
                        conflict_graph={},
                    )
                    fallback_dir = str(fallback_method_dir.relative_to(output_dir)).replace("\\", "/")
                except Exception:
                    fallback_dir = ""
            results.append(
                _method_result(
                    row,
                    method,
                    success=False,
                    l1_success=plan is not None,
                    unit_applicable=method != "IndependentCurve",
                    unit_success=False,
                    started=started,
                    plan=plan,
                    selection=selection,
                    shared_inventory_id=(
                        str(shared_inventory["inventory_id"])
                        if method in {"Ours", "LocalGreedy"}
                        else ""
                    ),
                    shared_graph_id=(
                        str(shared_graph.get("conflict_graph_digest", ""))
                        if method in {"Ours", "LocalGreedy"}
                        else ""
                    ),
                    error=exc,
                    method_dir=fallback_dir,
                )
            )
    return {"ok": True, "case_id": row["case_id"], "results": results}


def _safe_context(row: Mapping[str, str], output_dir_str: str) -> dict[str, Any]:
    try:
        return _run_context(row, Path(output_dir_str))
    except Exception as exc:
        return {
            "ok": False,
            "case_id": row["case_id"],
            "row": dict(row),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
        }


def run(
    *,
    frozen_cases: Path,
    output_dir: Path,
    workers: int,
    limit: int | None,
) -> None:
    if output_dir.exists():
        raise MatrixCError(f"output already exists: {output_dir}")
    rows = _read_matrix_c(frozen_cases)
    if limit is not None:
        rows = rows[:limit]
    output_dir.mkdir(parents=True)
    outcomes: list[dict[str, Any]] = []
    if workers == 1:
        _init_worker()
        outcomes = [_safe_context(row, str(output_dir)) for row in rows]
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as executor:
            futures = {
                executor.submit(_safe_context, row, str(output_dir)): row for row in rows
            }
            for future in as_completed(futures):
                outcomes.append(future.result())
    outcome_by_id = {outcome["case_id"]: outcome for outcome in outcomes}
    ordered_results: list[dict[str, object]] = []
    failures: list[dict[str, Any]] = []
    for row in rows:
        outcome = outcome_by_id[row["case_id"]]
        if outcome["ok"]:
            by_method = {result["method"]: result for result in outcome["results"]}
            ordered_results.extend(by_method[method] for method in METHODS)
        else:
            failures.append(outcome)
            for method in METHODS:
                ordered_results.append(
                    {
                        "case_id": row["case_id"],
                        "method": method,
                        "prototype_id": row["prototype_id"],
                        "backbone_variant": row["backbone_variant"],
                        "density_level": row["density_level"],
                        "replicate": row["replicate"],
                        "production_seed": row["production_seed"],
                        "generation_success": 0,
                        "l1_generation_success": 0,
                        "unit_generation_applicable": int(method != "IndependentCurve"),
                        "unit_generation_success": 0,
                        "error_type": outcome["error_type"],
                        "error_message": outcome["error_message"],
                    }
                )
    _write_results(output_dir / "raw_results.csv", ordered_results)
    _write_json(output_dir / "context_failures.json", failures)
    _write_json(
        output_dir / "run_manifest.json",
        {
            "schema": "paper_a_matrix_c_ablation_v1",
            "context_count": len(rows),
            "method_count": len(METHODS),
            "planned_result_count": len(rows) * len(METHODS),
            "result_row_count": len(ordered_results),
            "methods": list(METHODS),
            "ours_and_localgreedy_share_same_stage4_objects": True,
            "independent_curve_is_l1_only": True,
            "failure_cases_not_replaced": True,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--frozen-cases", type=Path, default=PROTOCOL_DIR / "frozen_cases.csv"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.workers <= 0:
        raise SystemExit("workers must be positive")
    run(
        frozen_cases=args.frozen_cases.resolve(),
        output_dir=args.output_dir.resolve(),
        workers=args.workers,
        limit=args.limit,
    )
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
