#!/usr/bin/env python3
"""Run frozen Matrix-A/B cases through the formal V3 + H2-B chain."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
PROTOCOL_DIR = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "protocol"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1"
STAGE4_CONTRACT_PATH = DYNAMIC_DIR / "STAGE4_UNIT_GRAMMAR_CONTRACT_V2.json"
STAGE5_CONTRACT_PATH = DYNAMIC_DIR / "STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json"
EDITOR_L2_PRIOR_PATH = DYNAMIC_DIR / "EDITOR_L2_PLACEMENT_PRIOR_V1.json"

if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

_WORKER: dict[str, Any] = {}

RESULT_FIELDS = (
    "case_id",
    "matrix_id",
    "method",
    "prototype_id",
    "backbone_variant",
    "density_level",
    "replicate",
    "production_seed",
    "generation_success",
    "error_type",
    "error_message",
    "ordinary_l1_count",
    "selected_l1_only_count",
    "selected_l2_count",
    "branchunit_count",
    "stage3_runtime_seconds",
    "stage4_runtime_seconds",
    "conflict_graph_runtime_seconds",
    "selection_runtime_seconds",
    "render_runtime_seconds",
    "total_runtime_seconds",
    "l1_candidate_count",
    "branchunit_candidate_count",
    "conflict_edge_count",
    "pair_penalty_count",
    "search_node_count",
    "search_node_limit",
    "search_node_limit_reached",
    "case_dir",
)


class FormalRunError(RuntimeError):
    """One frozen formal case cannot be executed as specified."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FormalRunError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_cases(path: Path, matrices: Sequence[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    allowed = set(matrices)
    selected = [row for row in rows if row["matrix_id"] in allowed]
    if not selected:
        raise FormalRunError(f"no frozen cases for matrices {sorted(allowed)}")
    return selected


def _write_results(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _init_worker(density_control_profile_path: str | None = None) -> None:
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
        stage5_contract=_read_json(STAGE5_CONTRACT_PATH),
        editor_l2_prior=_read_json(EDITOR_L2_PRIOR_PATH),
        density_control_profile=(
            _read_json(Path(density_control_profile_path))
            if density_control_profile_path is not None
            else None
        ),
    )


def _run_case(row: Mapping[str, str], output_dir: Path, render: bool) -> dict[str, object]:
    from branch_unit_grammar_v1 import generate_unit_candidate_inventory
    from export_batch_svgs import render_case_svg
    from render_stage5_global_selection import render_global_selection
    from run_batch_generation import _downstream_unit_clearance
    from run_stage3b_l1_flow import generate_prototype_case
    from stage5_global_unit_selection import build_conflict_graph, select_global_units

    if not _WORKER:
        _init_worker()
    started_total = time.perf_counter()
    case_id = str(row["case_id"])
    prototype_id = str(row["prototype_id"])
    strategy = _WORKER["strategies"][prototype_id]
    downstream_clearance = _downstream_unit_clearance(
        strategy,
        _WORKER["editor_l2_prior"],
        _WORKER["stage4_contract"],
    )

    started = time.perf_counter()
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
        prototype_variant_id=str(row["backbone_variant"]),
        flower_rho=None,
        ordinary_density_level_override=str(row["density_level"]),
        downstream_unit_clearance=downstream_clearance,
        density_control_profile=_WORKER.get("density_control_profile"),
    )
    stage3_runtime = time.perf_counter() - started
    analysis = generated["variant_analysis"]
    plan = generated["plan"]
    flower_mount_plan = generated["flower_mount_plan"]
    actual_variant = str(generated["variation"].get("prototype_variant_id"))
    actual_density = str(plan["count_derivation"]["ordinary_density_level"])
    if actual_variant != row["backbone_variant"] or actual_density != row["density_level"]:
        raise FormalRunError(
            f"override mismatch: expected {row['backbone_variant']}/{row['density_level']}, "
            f"got {actual_variant}/{actual_density}"
        )

    started = time.perf_counter()
    unit_inventory = generate_unit_candidate_inventory(
        plan,
        analysis,
        _WORKER["prior"],
        _WORKER["stage4_contract"],
        _WORKER["editor_l2_prior"],
    )
    stage4_runtime = time.perf_counter() - started
    started = time.perf_counter()
    conflict_graph = build_conflict_graph(
        unit_inventory,
        _WORKER["stage5_contract"],
        _WORKER["editor_l2_prior"],
    )
    conflict_runtime = time.perf_counter() - started
    started = time.perf_counter()
    selection = select_global_units(
        unit_inventory,
        conflict_graph,
        _WORKER["stage5_contract"],
    )
    selection_runtime = time.perf_counter() - started
    if not bool(selection.get("feasible")):
        raise FormalRunError("formal H2-B selector returned infeasible")

    case_dir = output_dir / "raw_cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=False)
    _write_json(case_dir / "case_input.json", dict(row))
    _write_json(case_dir / "strict_p0_variant.json", generated["variant_strict"].as_dict())
    _write_json(case_dir / "prototype_analysis_variant.json", analysis)
    _write_json(case_dir / "flower_mount_plan.json", flower_mount_plan)
    _write_json(case_dir / "global_l1_flow_plan.json", plan)
    _write_json(case_dir / "global_unit_selection.json", selection)

    render_runtime = 0.0
    if render:
        started = time.perf_counter()
        render_global_selection(
            analysis,
            unit_inventory,
            conflict_graph,
            selection,
            case_dir / "formal_triple.png",
            triple_repeat=True,
            flower_mount_plan=flower_mount_plan,
        )
        provenance = {
            "prototype_id": prototype_id,
            "production_seed": int(row["production_seed"]),
            "backbone_seed": int(row["backbone_seed"]),
            "flower_seed": int(row["flower_seed"]),
            "branch_seed": int(row["branch_seed"]),
            "unit_seed": int(row["unit_seed"]),
            "backbone_variant_id": row["backbone_variant"],
            "density_level": row["density_level"],
            "source_case": case_id,
            "source_contract_id": _WORKER["stage5_contract"]["contract_id"],
            "source_plan_id": plan["plan_id"],
            "source_selection_id": selection["selection_id"],
        }
        (case_dir / "formal_triple.svg").write_text(
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
        render_runtime = time.perf_counter() - started

    trace = selection.get("solver_trace", {})
    result: dict[str, object] = {
        "case_id": case_id,
        "matrix_id": row["matrix_id"],
        "method": "Ours",
        "prototype_id": prototype_id,
        "backbone_variant": row["backbone_variant"],
        "density_level": row["density_level"],
        "replicate": int(row["replicate"]),
        "production_seed": int(row["production_seed"]),
        "generation_success": 1,
        "error_type": "",
        "error_message": "",
        "ordinary_l1_count": len(plan["lanes"]),
        "selected_l1_only_count": int(trace.get("selected_l1_only_count", 0)),
        "selected_l2_count": int(trace.get("selected_l2_count", 0)),
        "branchunit_count": len(selection["selected_candidates"]),
        "stage3_runtime_seconds": stage3_runtime,
        "stage4_runtime_seconds": stage4_runtime,
        "conflict_graph_runtime_seconds": conflict_runtime,
        "selection_runtime_seconds": selection_runtime,
        "render_runtime_seconds": render_runtime,
        "total_runtime_seconds": time.perf_counter() - started_total,
        "l1_candidate_count": len(generated.get("inventory", {}).get("candidates", [])),
        "branchunit_candidate_count": int(conflict_graph["node_count"]),
        "conflict_edge_count": int(conflict_graph["edge_count"]),
        "pair_penalty_count": int(conflict_graph["pair_penalty_count"]),
        "search_node_count": int(trace.get("search_node_count", 0)),
        "search_node_limit": int(trace.get("search_node_limit", 0)),
        "search_node_limit_reached": int(bool(trace.get("search_node_limit_reached"))),
        "case_dir": str(case_dir.relative_to(output_dir)).replace("\\", "/"),
    }
    _write_json(case_dir / "case_result.json", result)
    return result


def _safe_run(row: Mapping[str, str], output_dir_str: str, render: bool) -> dict[str, object]:
    try:
        return _run_case(row, Path(output_dir_str), render)
    except Exception as exc:
        return {
            "case_id": row["case_id"],
            "matrix_id": row["matrix_id"],
            "method": "Ours",
            "prototype_id": row["prototype_id"],
            "backbone_variant": row["backbone_variant"],
            "density_level": row["density_level"],
            "replicate": row["replicate"],
            "production_seed": row["production_seed"],
            "generation_success": 0,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "case_dir": "",
        }


def run(
    *,
    frozen_cases: Path,
    output_dir: Path,
    matrices: Sequence[str],
    workers: int,
    limit: int | None,
    render: bool,
) -> None:
    if output_dir.exists():
        raise FormalRunError(f"output already exists: {output_dir}")
    rows = _read_cases(frozen_cases, matrices)
    if limit is not None:
        rows = rows[:limit]
    output_dir.mkdir(parents=True)
    results: list[dict[str, object]] = []
    if workers == 1:
        _init_worker()
        for row in rows:
            results.append(_safe_run(row, str(output_dir), render))
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as executor:
            futures = {
                executor.submit(_safe_run, row, str(output_dir), render): row
                for row in rows
            }
            for future in as_completed(futures):
                results.append(future.result())
    by_id = {str(result["case_id"]): result for result in results}
    ordered = [by_id[row["case_id"]] for row in rows]
    _write_results(output_dir / "raw_results.csv", ordered)
    failures = [result for result in ordered if not int(result["generation_success"])]
    _write_json(output_dir / "failures.json", failures)
    _write_json(
        output_dir / "run_manifest.json",
        {
            "schema": "paper_a_formal_case_run_v1",
            "method": "Ours",
            "matrices": list(matrices),
            "planned_case_count": len(rows),
            "generation_success_count": len(rows) - len(failures),
            "generation_failure_count": len(failures),
            "render_enabled": render,
            "failure_cases_not_replaced": True,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--frozen-cases",
        type=Path,
        default=PROTOCOL_DIR / "frozen_cases.csv",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--matrix", action="append", choices=("A", "B"), required=True)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()
    if args.workers <= 0:
        raise SystemExit("workers must be positive")
    run(
        frozen_cases=args.frozen_cases.resolve(),
        output_dir=args.output_dir.resolve(),
        matrices=args.matrix,
        workers=args.workers,
        limit=args.limit,
        render=not args.no_render,
    )
    print(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
