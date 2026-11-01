#!/usr/bin/env python3
"""Run the frozen 90-context RQ2-B exact-L2 matched-budget diagnostic."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
DYNAMIC_DIR = REPO_ROOT / "experiments" / "branch_unit" / "dynamic"
DEFAULT_SOURCE_RUN = (
    REPO_ROOT
    / "artifacts"
    / "paper_a_chapter4_v1"
    / "rq2"
    / "matrix_c_four_methods"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "rq2_matched_budget"
)
PROTOCOL_DIR = REPO_ROOT / "artifacts" / "paper_a_chapter4_v1" / "protocol"
OURS_CONTRACT_PATH = DYNAMIC_DIR / "STAGE5E_L2_JOINT_SELECTION_CONTRACT_V2.json"
LOCAL_CONTRACT_PATH = DYNAMIC_DIR / "STAGE5E_L2_SPARSE_SELECTION_CONTRACT_V1.json"
BOOTSTRAP_SEED = 20260825
BOOTSTRAP_REPLICATES = 2000
SMOKE_CASE_ID = "C083"
METHODS = ("LocalGreedy@B", "Ours@B")

if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))


RAW_FIELDS = (
    "case_id",
    "prototype_id",
    "backbone_variant",
    "density_level",
    "replicate",
    "production_seed",
    "diagnostic_id",
    "method",
    "target_l2_count",
    "target_upgraded_parent_count",
    "achieved_l2_count",
    "achieved_upgraded_parent_count",
    "budget_attained",
    "selection_status",
    "failure_reason",
    "selected_candidate_ids",
    "selected_parent_states",
    "search_node_count",
    "search_node_limit_reached",
    "bounded_space_exhausted",
    "runtime_seconds",
    "source_stage3_plan_id",
    "source_inventory_id",
    "source_conflict_graph_id",
)

HARD_METRICS = (
    "internal_unit_crossing_count",
    "cross_unit_crossing_count",
    "ordinary_backbone_nonroot_crossing_count",
    "ordinary_support_crossing_count",
    "periodic_crossing_count",
    "clearance_violation_count",
    "flower_region_intrusion_curve_count",
    "periodic_seam_violation_count",
)

METRIC_FIELDS = (
    "case_id",
    "prototype_id",
    "backbone_variant",
    "density_level",
    "replicate",
    "diagnostic_id",
    "method",
    "target_l2_count",
    "target_upgraded_parent_count",
    "achieved_l2_count",
    "achieved_upgraded_parent_count",
    "mechanically_legal",
    *HARD_METRICS,
    "minimum_cross_unit_clearance",
    "minimum_full_unit_clearance_required",
    "parallel_cotravel_total",
    "parallel_cotravel_peak",
    "hierarchy_l1_only_ratio",
    "hierarchy_single_l2_ratio",
    "hierarchy_opposed_l2_ratio",
)


class MatchedBudgetError(RuntimeError):
    """The frozen matched-budget diagnostic cannot run as specified."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MatchedBudgetError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str],
) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _actual_l2_count(candidate: Mapping[str, Any]) -> int:
    return sum(
        1
        for curve in candidate.get("curves", [])
        if isinstance(curve, Mapping) and curve.get("level") == "L2"
    )


def _selection_budget(selection: Mapping[str, Any]) -> tuple[int, int]:
    candidates = selection.get("selected_candidates", [])
    l2_count = sum(_actual_l2_count(candidate) for candidate in candidates)
    upgraded = sum(_actual_l2_count(candidate) > 0 for candidate in candidates)
    return int(l2_count), int(upgraded)


def _eligible_geometry_state(candidate: Mapping[str, Any]) -> str | None:
    from stage5_global_unit_selection import _candidate_5e_state

    return _candidate_5e_state(candidate)


def _geometry_state(candidate: Mapping[str, Any]) -> str:
    state = _eligible_geometry_state(candidate)
    if state is None:
        raise MatchedBudgetError(
            f"candidate has no eligible geometry state: {candidate.get('candidate_id')}"
        )
    return state


def _intent_upgrade_budget(inventory: Mapping[str, Any]) -> int:
    lane_count = len(inventory["lanes"])
    return min(
        1 + (int(inventory["unit_seed"]) % 3),
        max(1, (lane_count - 1) // 2),
    )


def _prepare_selector_inputs(
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
) -> dict[str, Any]:
    eligible_by_lane: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for candidate in inventory["candidates"]:
        if (
            bool(candidate["intrinsic_diagnostics"]["valid"])
            and _eligible_geometry_state(candidate) is not None
        ):
            eligible_by_lane[str(candidate["source_lane_id"])].append(candidate)

    lane_ids = [str(row["source_lane_id"]) for row in inventory["lanes"]]
    if set(lane_ids) != set(eligible_by_lane):
        raise MatchedBudgetError("one or more frozen lanes have no eligible BranchUnit")
    lane_order = sorted(
        lane_ids,
        key=lambda lane_id: (len(eligible_by_lane[lane_id]), lane_id),
    )

    conflict_ids: dict[str, set[str]] = defaultdict(set)
    for edge in conflict_graph["edges"]:
        first_id = str(edge["first_candidate_id"])
        second_id = str(edge["second_candidate_id"])
        conflict_ids[first_id].add(second_id)
        conflict_ids[second_id].add(first_id)

    pair_penalties: dict[str, dict[str, float]] = defaultdict(dict)
    for row in conflict_graph.get("pair_penalties", []):
        first_id = str(row["first_candidate_id"])
        second_id = str(row["second_candidate_id"])
        penalty = float(row["normalized_penalty"])
        pair_penalties[first_id][second_id] = penalty
        pair_penalties[second_id][first_id] = penalty

    return {
        "lane_ids": lane_ids,
        "lane_order": lane_order,
        "eligible_by_lane": eligible_by_lane,
        "conflict_ids": conflict_ids,
        "pair_penalties": pair_penalties,
        "prototype_strategy": inventory.get("prototype_strategy"),
    }


def _select_unconstrained_adapter(
    method: str,
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    from stage5_global_unit_selection import (
        _select_joint_sparse_l2,
        _select_sparse_l2,
    )

    prepared = _prepare_selector_inputs(inventory, conflict_graph)
    function = _select_sparse_l2 if method == "LocalGreedy" else _select_joint_sparse_l2
    return function(
        inventory=inventory,
        conflict_graph=conflict_graph,
        contract=contract,
        **prepared,
    )


def _all_l1_baseline(
    *,
    lane_order: Sequence[str],
    eligible_by_lane: Mapping[str, Sequence[Mapping[str, Any]]],
    conflict_ids: Mapping[str, set[str]],
    pair_penalties: Mapping[str, Mapping[str, float]],
) -> tuple[list[Mapping[str, Any]], int, int]:
    by_lane: dict[str, list[Mapping[str, Any]]] = {}
    for lane_id in lane_order:
        by_lane[lane_id] = sorted(
            (
                candidate
                for candidate in eligible_by_lane[lane_id]
                if _actual_l2_count(candidate) == 0
            ),
            key=lambda candidate: (
                len(conflict_ids[str(candidate["candidate_id"])]),
                str(candidate["candidate_id"]),
            ),
        )

    best: list[Mapping[str, Any]] = []
    best_peak = float("inf")
    best_total = float("inf")
    selected: list[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    nodes = 0
    backtracks = 0

    def search(index: int, total: float, peak: float) -> None:
        nonlocal best, best_peak, best_total, nodes, backtracks
        if index == len(lane_order):
            if (peak, total) < (best_peak, best_total):
                best_peak = peak
                best_total = total
                best = list(selected)
            return
        lane_id = lane_order[index]
        for candidate in by_lane[lane_id]:
            nodes += 1
            candidate_id = str(candidate["candidate_id"])
            if selected_ids & conflict_ids[candidate_id]:
                continue
            added = [
                pair_penalties[candidate_id].get(existing_id, 0.0)
                for existing_id in selected_ids
            ]
            next_total = total + sum(added)
            next_peak = max(peak, max(added, default=0.0))
            if next_peak > best_peak + 1e-12 or (
                abs(next_peak - best_peak) <= 1e-12
                and next_total >= best_total - 1e-12
            ):
                continue
            selected.append(candidate)
            selected_ids.add(candidate_id)
            search(index + 1, next_total, next_peak)
            selected.pop()
            selected_ids.remove(candidate_id)
            backtracks += 1

    search(0, 0.0, 0.0)
    if not best:
        raise MatchedBudgetError("no feasible all-L1 baseline in frozen inventory")
    return best, nodes, backtracks


def _select_localgreedy_at_b(
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
    target_l2_count: int,
) -> dict[str, Any]:
    prepared = _prepare_selector_inputs(inventory, conflict_graph)
    lane_order = prepared["lane_order"]
    eligible_by_lane = prepared["eligible_by_lane"]
    conflict_ids = prepared["conflict_ids"]
    pair_penalties = prepared["pair_penalties"]
    baseline, phase_a_nodes, phase_a_backtracks = _all_l1_baseline(
        lane_order=lane_order,
        eligible_by_lane=eligible_by_lane,
        conflict_ids=conflict_ids,
        pair_penalties=pair_penalties,
    )

    by_state: dict[str, dict[str, list[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for lane_id in prepared["lane_ids"]:
        for candidate in eligible_by_lane[lane_id]:
            by_state[_geometry_state(candidate)][lane_id].append(candidate)

    unit_seed = int(inventory["unit_seed"])
    upgrade_priority = list(lane_order)
    random.Random(unit_seed).shuffle(upgrade_priority)
    intent_budget = _intent_upgrade_budget(inventory)
    state_cycle = ["SINGLE_L2_LEFT", "SINGLE_L2_RIGHT", "OPPOSED_L2_PAIR"]
    final_by_lane = {
        str(candidate["source_lane_id"]): candidate for candidate in baseline
    }
    final_ids = {str(candidate["candidate_id"]) for candidate in baseline}
    upgraded_lanes: list[str] = []
    achieved_l2 = 0

    for priority_index, lane_id in enumerate(upgrade_priority):
        if len(upgraded_lanes) >= intent_budget:
            break
        phase = (unit_seed + priority_index) % len(state_cycle)
        preferred = state_cycle[phase:] + state_cycle[:phase]
        candidates: list[Mapping[str, Any]] = []
        for state in preferred:
            candidates.extend(by_state[state][lane_id])
        candidates.sort(
            key=lambda candidate: (
                len(conflict_ids[str(candidate["candidate_id"])]),
                str(candidate["candidate_id"]),
            )
        )
        for candidate in candidates:
            candidate_l2 = _actual_l2_count(candidate)
            if achieved_l2 + candidate_l2 > target_l2_count:
                continue
            candidate_id = str(candidate["candidate_id"])
            if final_ids & conflict_ids[candidate_id]:
                continue
            replaced = final_by_lane[lane_id]
            final_ids.remove(str(replaced["candidate_id"]))
            final_by_lane[lane_id] = candidate
            final_ids.add(candidate_id)
            upgraded_lanes.append(lane_id)
            achieved_l2 += candidate_l2
            break

    selected_candidates = [final_by_lane[str(lane_id)] for lane_id in lane_order]
    achieved_l2, achieved_upgraded = _selection_budget(
        {"selected_candidates": selected_candidates}
    )
    attained = achieved_l2 == target_l2_count
    return {
        "schema": "paper_a_rq2_mb_l2_selection_v1",
        "diagnostic_id": "MB-L2",
        "method": "LocalGreedy@B",
        "selection_id": (
            f"{inventory['inventory_id']}__localgreedy_mb_l2_B{target_l2_count}"
        ),
        "seed": inventory["unit_seed"],
        "source_inventory_id": inventory["inventory_id"],
        "source_conflict_graph_id": conflict_graph.get("conflict_graph_digest", ""),
        "target_l2_count": target_l2_count,
        "budget_attained": attained,
        "selection_status": "success" if attained else "budget_not_attained",
        "failure_reason": "" if attained else "sequential irreversible pass ended below target B",
        "selected_candidate_ids": [
            str(candidate["candidate_id"]) for candidate in selected_candidates
        ],
        "selected_candidates": selected_candidates,
        "solver_trace": {
            "intent_upgrade_budget": intent_budget,
            "achieved_upgrade_count": achieved_upgraded,
            "selected_l2_count": achieved_l2,
            "phase_a_search_node_count": phase_a_nodes,
            "phase_a_backtrack_count": phase_a_backtracks,
            "upgrade_priority": upgrade_priority,
            "upgrade_lane_ids": upgraded_lanes,
            "search_node_count": phase_a_nodes,
            "search_node_limit_reached": False,
            "bounded_space_exhausted": True,
            "silent_fallback_used": False,
        },
    }


def _select_ours_at_b(
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
    contract: Mapping[str, Any],
    target_l2_count: int,
    *,
    node_limit_override: int | None = None,
) -> dict[str, Any]:
    from stage5_global_unit_selection import (
        _joint_local_quality_by_candidate,
        _seeded_tie_value,
    )

    prepared = _prepare_selector_inputs(inventory, conflict_graph)
    lane_order = prepared["lane_order"]
    eligible_by_lane = prepared["eligible_by_lane"]
    conflict_ids = prepared["conflict_ids"]
    pair_penalties = prepared["pair_penalties"]
    unit_seed = int(inventory["unit_seed"])
    intent_budget = _intent_upgrade_budget(inventory)
    objective_contract = contract["joint_objective"]
    weights = objective_contract["weights"]
    local_weight = float(weights["local_quality"])
    upgrade_reward = float(weights["upgraded_lane_reward"])
    total_pair_weight = float(weights["total_parallel_penalty"])
    peak_pair_weight = float(weights["peak_parallel_penalty"])
    extra_child_weight = float(weights["extra_l2_child_penalty"])
    node_limit = (
        int(node_limit_override)
        if node_limit_override is not None
        else int(contract["bounded_search"]["node_limit"])
    )
    local_quality = _joint_local_quality_by_candidate(eligible_by_lane)

    def candidate_gain(candidate: Mapping[str, Any]) -> float:
        candidate_id = str(candidate["candidate_id"])
        l2_count = _actual_l2_count(candidate)
        if l2_count == 0:
            return 0.0
        return (
            local_weight * local_quality[candidate_id]["score"]
            + upgrade_reward
            - extra_child_weight * max(0, l2_count - 1)
        )

    ordered_by_lane: dict[str, list[Mapping[str, Any]]] = {}
    best_gain_by_lane: dict[str, float] = {}
    max_l2_by_lane: dict[str, int] = {}
    for lane_id in lane_order:
        ordered = sorted(
            eligible_by_lane[lane_id],
            key=lambda candidate: (
                -candidate_gain(candidate),
                len(conflict_ids[str(candidate["candidate_id"])]),
                _seeded_tie_value(unit_seed, str(candidate["candidate_id"])),
            ),
        )
        ordered_by_lane[lane_id] = ordered
        best_gain_by_lane[lane_id] = max(
            (candidate_gain(candidate) for candidate in ordered), default=0.0
        )
        max_l2_by_lane[lane_id] = max(
            (_actual_l2_count(candidate) for candidate in ordered), default=0
        )

    maximum_reachable = sum(
        sorted(max_l2_by_lane.values(), reverse=True)[:intent_budget]
    )
    selected: list[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    best_selected: list[Mapping[str, Any]] = []
    best_components: dict[str, float | int] | None = None
    best_score = float("-inf")
    best_tie_value: str | None = None
    search_node_count = 0
    exact_composition_count = 0
    backtrack_count = 0
    conflict_prune_count = 0
    upgrade_budget_prune_count = 0
    exact_budget_prune_count = 0
    bound_prune_count = 0
    node_limit_reached = False

    def score_components(
        local_sum: float,
        upgraded_count: int,
        total_l2_count: int,
        pair_total: float,
        pair_peak: float,
    ) -> dict[str, float | int]:
        extra_l2_children = max(0, total_l2_count - upgraded_count)
        score = (
            local_weight * local_sum
            + upgrade_reward * upgraded_count
            - total_pair_weight * pair_total
            - peak_pair_weight * pair_peak
            - extra_child_weight * extra_l2_children
        )
        return {
            "score": float(score),
            "local_quality_sum": float(local_sum),
            "upgraded_lane_count": int(upgraded_count),
            "total_l2_count": int(total_l2_count),
            "extra_l2_child_count": int(extra_l2_children),
            "total_parallel_penalty": float(pair_total),
            "peak_parallel_penalty": float(pair_peak),
        }

    def search(
        lane_index: int,
        local_sum: float,
        upgraded_count: int,
        total_l2_count: int,
        pair_total: float,
        pair_peak: float,
    ) -> None:
        nonlocal best_selected, best_components, best_score, best_tie_value
        nonlocal search_node_count, exact_composition_count, backtrack_count
        nonlocal conflict_prune_count, upgrade_budget_prune_count
        nonlocal exact_budget_prune_count, bound_prune_count, node_limit_reached
        if search_node_count >= node_limit:
            node_limit_reached = True
            return
        if total_l2_count > target_l2_count:
            exact_budget_prune_count += 1
            return
        remaining_upgrade_count = max(0, intent_budget - upgraded_count)
        remaining_lanes = lane_order[lane_index:]
        max_additional_l2 = sum(
            sorted(
                (max_l2_by_lane[lane_id] for lane_id in remaining_lanes),
                reverse=True,
            )[:remaining_upgrade_count]
        )
        if total_l2_count + max_additional_l2 < target_l2_count:
            exact_budget_prune_count += 1
            return
        if lane_index == len(lane_order):
            if total_l2_count != target_l2_count:
                return
            exact_composition_count += 1
            components = score_components(
                local_sum,
                upgraded_count,
                total_l2_count,
                pair_total,
                pair_peak,
            )
            score = float(components["score"])
            tie_value = _seeded_tie_value(
                unit_seed,
                "|".join(
                    sorted(str(candidate["candidate_id"]) for candidate in selected)
                ),
            )
            if score > best_score + 1e-12 or (
                abs(score - best_score) <= 1e-12
                and (best_tie_value is None or tie_value < best_tie_value)
            ):
                best_score = score
                best_tie_value = tie_value
                best_selected = list(selected)
                best_components = components
            return

        current = score_components(
            local_sum,
            upgraded_count,
            total_l2_count,
            pair_total,
            pair_peak,
        )
        remaining_gains = sorted(
            (
                max(0.0, best_gain_by_lane[lane_id])
                for lane_id in remaining_lanes
            ),
            reverse=True,
        )[:remaining_upgrade_count]
        optimistic_score = float(current["score"]) + sum(remaining_gains)
        if optimistic_score < best_score - 1e-12:
            bound_prune_count += 1
            return

        lane_id = lane_order[lane_index]
        for candidate in ordered_by_lane[lane_id]:
            if search_node_count >= node_limit:
                node_limit_reached = True
                return
            search_node_count += 1
            candidate_id = str(candidate["candidate_id"])
            if selected_ids & conflict_ids[candidate_id]:
                conflict_prune_count += 1
                continue
            l2_count = _actual_l2_count(candidate)
            is_upgrade = int(l2_count > 0)
            next_upgraded_count = upgraded_count + is_upgrade
            if next_upgraded_count > intent_budget:
                upgrade_budget_prune_count += 1
                continue
            if total_l2_count + l2_count > target_l2_count:
                exact_budget_prune_count += 1
                continue
            added_pair_penalties = [
                pair_penalties[candidate_id].get(existing_id, 0.0)
                for existing_id in selected_ids
            ]
            selected.append(candidate)
            selected_ids.add(candidate_id)
            search(
                lane_index + 1,
                local_sum + local_quality[candidate_id]["score"] * is_upgrade,
                next_upgraded_count,
                total_l2_count + l2_count,
                pair_total + sum(added_pair_penalties),
                max(pair_peak, max(added_pair_penalties, default=0.0)),
            )
            selected.pop()
            selected_ids.remove(candidate_id)
            backtrack_count += 1

    if target_l2_count <= maximum_reachable and node_limit > 0:
        search(0, 0.0, 0, 0, 0.0, 0.0)

    if best_selected and best_components is not None:
        status = "success"
        failure_reason = ""
        budget_attained = True
    elif node_limit_reached:
        status = "budget_indeterminate_node_limit"
        failure_reason = "node limit reached before any exact-B composition was found"
        budget_attained = False
    else:
        status = "budget_infeasible"
        failure_reason = "bounded candidate space exhausted without an exact-B composition"
        budget_attained = False

    achieved_l2, achieved_upgraded = (
        _selection_budget({"selected_candidates": best_selected})
        if best_selected
        else (0, 0)
    )
    return {
        "schema": "paper_a_rq2_mb_l2_selection_v1",
        "diagnostic_id": "MB-L2",
        "method": "Ours@B",
        "selection_id": f"{inventory['inventory_id']}__ours_mb_l2_B{target_l2_count}",
        "seed": inventory["unit_seed"],
        "source_inventory_id": inventory["inventory_id"],
        "source_conflict_graph_id": conflict_graph.get("conflict_graph_digest", ""),
        "target_l2_count": target_l2_count,
        "budget_attained": budget_attained,
        "selection_status": status,
        "failure_reason": failure_reason,
        "selected_candidate_ids": [
            str(candidate["candidate_id"]) for candidate in best_selected
        ],
        "selected_candidates": list(best_selected),
        "solver_trace": {
            "intent_upgrade_budget": intent_budget,
            "achieved_upgrade_count": achieved_upgraded,
            "selected_l2_count": achieved_l2,
            "search_node_limit": node_limit,
            "search_node_count": search_node_count,
            "search_node_limit_reached": node_limit_reached,
            "bounded_space_exhausted": not node_limit_reached,
            "exact_composition_count": exact_composition_count,
            "backtrack_count": backtrack_count,
            "hard_conflict_prune_count": conflict_prune_count,
            "sparse_budget_prune_count": upgrade_budget_prune_count,
            "exact_l2_budget_prune_count": exact_budget_prune_count,
            "objective_bound_prune_count": bound_prune_count,
            "maximum_reachable_l2_count": maximum_reachable,
            "selected_objective": best_components or {},
            "silent_fallback_used": False,
        },
    }


def _write_metric_context_inputs(source_case_dir: Path, target_dir: Path) -> None:
    source = source_case_dir / "methods" / "Ours"
    for name in (
        "strict_p0_variant.json",
        "prototype_analysis_variant.json",
        "flower_mount_plan.json",
        "global_l1_flow_plan.json",
    ):
        _write_json(target_dir / name, _read_json(source / name))


def _independent_metrics(
    metric_dir: Path,
    selection: Mapping[str, Any],
    parameters: Mapping[str, str],
) -> dict[str, object]:
    from evaluate_formal_cases import evaluate_case

    _write_json(metric_dir / "global_unit_selection.json", selection)
    metrics = evaluate_case(metric_dir, parameters)
    metrics["mechanically_legal"] = int(
        int(metrics["mechanical_evaluation_success"]) == 1
        and all(int(metrics[field]) == 0 for field in HARD_METRICS)
    )
    return metrics


def _metric_row(
    case_input: Mapping[str, Any],
    method: str,
    target: int,
    selection: Mapping[str, Any],
    metrics: Mapping[str, object],
) -> dict[str, object]:
    achieved_l2, achieved_upgraded = _selection_budget(selection)
    if int(metrics["l2_count"]) != achieved_l2:
        raise MatchedBudgetError(
            f"independent geometry L2 count mismatch for {case_input['case_id']} {method} B={target}"
        )
    return {
        "case_id": case_input["case_id"],
        "prototype_id": case_input["prototype_id"],
        "backbone_variant": case_input["backbone_variant"],
        "density_level": case_input["density_level"],
        "replicate": case_input["replicate"],
        "diagnostic_id": "MB-L2",
        "method": method,
        "target_l2_count": target,
        "target_upgraded_parent_count": "",
        "achieved_l2_count": achieved_l2,
        "achieved_upgraded_parent_count": achieved_upgraded,
        **{field: metrics[field] for field in METRIC_FIELDS if field in metrics},
    }


def _raw_row(
    case_input: Mapping[str, Any],
    method: str,
    target: int,
    selection: Mapping[str, Any],
    runtime_seconds: float,
    plan_id: str,
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
) -> dict[str, object]:
    achieved_l2, achieved_upgraded = _selection_budget(selection)
    states = {
        str(candidate["source_lane_id"]): _geometry_state(candidate)
        for candidate in selection.get("selected_candidates", [])
    }
    trace = selection.get("solver_trace", {})
    return {
        "case_id": case_input["case_id"],
        "prototype_id": case_input["prototype_id"],
        "backbone_variant": case_input["backbone_variant"],
        "density_level": case_input["density_level"],
        "replicate": case_input["replicate"],
        "production_seed": case_input["production_seed"],
        "diagnostic_id": "MB-L2",
        "method": method,
        "target_l2_count": target,
        "target_upgraded_parent_count": "",
        "achieved_l2_count": achieved_l2,
        "achieved_upgraded_parent_count": achieved_upgraded,
        "budget_attained": int(bool(selection.get("budget_attained"))),
        "selection_status": selection.get("selection_status", "selection_error"),
        "failure_reason": selection.get("failure_reason", ""),
        "selected_candidate_ids": json.dumps(
            selection.get("selected_candidate_ids", []), ensure_ascii=False
        ),
        "selected_parent_states": json.dumps(states, ensure_ascii=False, sort_keys=True),
        "search_node_count": trace.get("search_node_count", ""),
        "search_node_limit_reached": int(
            bool(trace.get("search_node_limit_reached", False))
        ),
        "bounded_space_exhausted": int(
            bool(trace.get("bounded_space_exhausted", False))
        ),
        "runtime_seconds": runtime_seconds,
        "source_stage3_plan_id": plan_id,
        "source_inventory_id": inventory["inventory_id"],
        "source_conflict_graph_id": conflict_graph.get("conflict_graph_digest", ""),
    }


def _run_context(source_case_dir: Path) -> dict[str, Any]:
    from evaluate_formal_cases import _metric_parameters

    case_input = _read_json(source_case_dir / "case_input.json")
    inventory = _read_json(source_case_dir / "shared_stage4_inventory.json")
    conflict_graph = _read_json(source_case_dir / "shared_conflict_graph.json")
    ours_contract = _read_json(OURS_CONTRACT_PATH)
    plan = _read_json(source_case_dir / "methods" / "Ours" / "global_l1_flow_plan.json")
    parameters = _metric_parameters(PROTOCOL_DIR / "metric_parameters.csv")
    intent_budget = _intent_upgrade_budget(inventory)
    raw_rows: list[dict[str, object]] = []
    metric_rows: list[dict[str, object]] = []

    with tempfile.TemporaryDirectory(prefix=f"paper_a_mb_{case_input['case_id']}_") as tmp:
        metric_dir = Path(tmp)
        _write_metric_context_inputs(source_case_dir, metric_dir)
        for target in range(1, 2 * intent_budget + 1):
            for method in METHODS:
                started = time.perf_counter()
                if method == "LocalGreedy@B":
                    selection = _select_localgreedy_at_b(
                        inventory, conflict_graph, target
                    )
                else:
                    selection = _select_ours_at_b(
                        inventory, conflict_graph, ours_contract, target
                    )
                runtime = time.perf_counter() - started
                raw_rows.append(
                    _raw_row(
                        case_input,
                        method,
                        target,
                        selection,
                        runtime,
                        str(plan["plan_id"]),
                        inventory,
                        conflict_graph,
                    )
                )
                if bool(selection.get("budget_attained")):
                    metrics = _independent_metrics(metric_dir, selection, parameters)
                    metric_rows.append(
                        _metric_row(case_input, method, target, selection, metrics)
                    )
    return {
        "case_id": case_input["case_id"],
        "raw_rows": raw_rows,
        "metric_rows": metric_rows,
        "error": "",
    }


def _safe_run_context(source_case_dir_str: str) -> dict[str, Any]:
    source_case_dir = Path(source_case_dir_str)
    try:
        return _run_context(source_case_dir)
    except Exception as exc:
        case_input = _read_json(source_case_dir / "case_input.json")
        inventory = _read_json(source_case_dir / "shared_stage4_inventory.json")
        conflict_graph = _read_json(source_case_dir / "shared_conflict_graph.json")
        plan = _read_json(
            source_case_dir / "methods" / "Ours" / "global_l1_flow_plan.json"
        )
        raw_rows: list[dict[str, object]] = []
        for target in range(1, 2 * _intent_upgrade_budget(inventory) + 1):
            for method in METHODS:
                selection = {
                    "selected_candidates": [],
                    "selected_candidate_ids": [],
                    "budget_attained": False,
                    "selection_status": "context_error",
                    "failure_reason": f"{type(exc).__name__}: {exc}",
                    "solver_trace": {},
                }
                raw_rows.append(
                    _raw_row(
                        case_input,
                        method,
                        target,
                        selection,
                        0.0,
                        str(plan["plan_id"]),
                        inventory,
                        conflict_graph,
                    )
                )
        return {
            "case_id": case_input["case_id"],
            "raw_rows": raw_rows,
            "metric_rows": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _smoke_checks(source_run: Path, output_dir: Path) -> None:
    from evaluate_formal_cases import _metric_parameters

    case_dir = source_run / "raw_cases" / SMOKE_CASE_ID
    inventory = _read_json(case_dir / "shared_stage4_inventory.json")
    conflict_graph = _read_json(case_dir / "shared_conflict_graph.json")
    ours_contract = _read_json(OURS_CONTRACT_PATH)
    local_contract = _read_json(LOCAL_CONTRACT_PATH)
    checks: list[dict[str, object]] = []

    try:
        parity_details: dict[str, object] = {}
        for method, contract in (
            ("LocalGreedy", local_contract),
            ("Ours", ours_contract),
        ):
            adapted = _select_unconstrained_adapter(
                method, inventory, conflict_graph, contract
            )
            formal = _read_json(
                case_dir / "methods" / method / "global_unit_selection.json"
            )
            matched = adapted["selected_candidate_ids"] == formal["selected_candidate_ids"]
            parity_details[method] = {
                "matched": matched,
                "selected_candidate_count": len(adapted["selected_candidate_ids"]),
            }
            if not matched:
                raise MatchedBudgetError(f"{method} parity mismatch")
        checks.append(
            {
                "check_id": "formal_parity_one_context",
                "passed": 1,
                "details": json.dumps(parity_details, ensure_ascii=False),
            }
        )
    except Exception as exc:
        checks.append(
            {
                "check_id": "formal_parity_one_context",
                "passed": 0,
                "details": f"{type(exc).__name__}: {exc}",
            }
        )

    try:
        single = next(
            candidate
            for candidate in inventory["candidates"]
            if bool(candidate["intrinsic_diagnostics"]["valid"])
            and str(_eligible_geometry_state(candidate)).startswith("SINGLE_L2")
        )
        opposed = next(
            candidate
            for candidate in inventory["candidates"]
            if bool(candidate["intrinsic_diagnostics"]["valid"])
            and _eligible_geometry_state(candidate) == "OPPOSED_L2_PAIR"
        )
        single_budget = _selection_budget({"selected_candidates": [single]})
        opposed_budget = _selection_budget({"selected_candidates": [opposed]})
        if single_budget != (1, 1) or opposed_budget != (2, 1):
            raise MatchedBudgetError(
                f"unexpected geometry budgets: single={single_budget}, opposed={opposed_budget}"
            )
        checks.append(
            {
                "check_id": "mb_l2_geometry_semantics",
                "passed": 1,
                "details": json.dumps(
                    {
                        "single": {"B": 1, "U": 1},
                        "opposed": {"B": 2, "U": 1},
                    },
                    ensure_ascii=False,
                ),
            }
        )
    except Exception as exc:
        checks.append(
            {
                "check_id": "mb_l2_geometry_semantics",
                "passed": 0,
                "details": f"{type(exc).__name__}: {exc}",
            }
        )

    try:
        intent_budget = _intent_upgrade_budget(inventory)
        unreachable_target = 2 * intent_budget + 1
        local_unreachable = _select_localgreedy_at_b(
            inventory, conflict_graph, unreachable_target
        )
        ours_unreachable = _select_ours_at_b(
            inventory, conflict_graph, ours_contract, unreachable_target
        )
        ours_limited = _select_ours_at_b(
            inventory,
            conflict_graph,
            ours_contract,
            2 * intent_budget,
            node_limit_override=1,
        )
        source_ids = {str(row["candidate_id"]) for row in inventory["candidates"]}
        selected_ids = set(local_unreachable["selected_candidate_ids"])
        valid = (
            local_unreachable["selection_status"] == "budget_not_attained"
            and ours_unreachable["selection_status"] == "budget_infeasible"
            and ours_limited["selection_status"]
            == "budget_indeterminate_node_limit"
            and not bool(local_unreachable["solver_trace"]["silent_fallback_used"])
            and not bool(ours_unreachable["solver_trace"]["silent_fallback_used"])
            and selected_ids <= source_ids
            and int(local_unreachable["seed"]) == int(inventory["unit_seed"])
            and int(ours_unreachable["seed"]) == int(inventory["unit_seed"])
        )
        if not valid:
            raise MatchedBudgetError("unreachable-budget status separation failed")
        checks.append(
            {
                "check_id": "unreachable_budget_no_fallback",
                "passed": 1,
                "details": json.dumps(
                    {
                        "target": unreachable_target,
                        "LocalGreedy@B": local_unreachable["selection_status"],
                        "Ours@B": ours_unreachable["selection_status"],
                        "node_limited_Ours@B": ours_limited["selection_status"],
                    },
                    ensure_ascii=False,
                ),
            }
        )
    except Exception as exc:
        checks.append(
            {
                "check_id": "unreachable_budget_no_fallback",
                "passed": 0,
                "details": f"{type(exc).__name__}: {exc}",
            }
        )

    try:
        parameters = _metric_parameters(PROTOCOL_DIR / "metric_parameters.csv")
        selection = _select_ours_at_b(inventory, conflict_graph, ours_contract, 2)
        if not bool(selection["budget_attained"]):
            raise MatchedBudgetError("smoke exact-B selection was not attained")
        with tempfile.TemporaryDirectory(prefix="paper_a_mb_smoke_") as tmp:
            metric_dir = Path(tmp)
            _write_metric_context_inputs(case_dir, metric_dir)
            original = _independent_metrics(metric_dir, selection, parameters)
            sentinel = copy.deepcopy(selection)
            sentinel["feasible"] = False
            sentinel["status"] = "SENTINEL_DO_NOT_READ"
            for candidate in sentinel["selected_candidates"]:
                candidate["intrinsic_diagnostics"]["valid"] = False
            altered = _independent_metrics(metric_dir, sentinel, parameters)
        fields = (
            "l2_count",
            "mechanically_legal",
            "parallel_cotravel_total",
            "parallel_cotravel_peak",
        )
        if any(original[field] != altered[field] for field in fields):
            raise MatchedBudgetError("independent metrics changed with selector sentinels")
        if int(original["l2_count"]) != _selection_budget(selection)[0]:
            raise MatchedBudgetError("independent L2 count differs from canonical curves")
        checks.append(
            {
                "check_id": "independent_canonical_geometry_metrics",
                "passed": 1,
                "details": json.dumps(
                    {field: original[field] for field in fields},
                    ensure_ascii=False,
                ),
            }
        )
    except Exception as exc:
        checks.append(
            {
                "check_id": "independent_canonical_geometry_metrics",
                "passed": 0,
                "details": f"{type(exc).__name__}: {exc}",
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "smoke_checks.csv",
        checks,
        ("check_id", "passed", "details"),
    )
    _write_json(
        output_dir / "smoke_checks.json",
        {
            "schema": "paper_a_rq2_mb_l2_minimal_smoke_v1",
            "case_id": SMOKE_CASE_ID,
            "check_count": len(checks),
            "all_passed": all(int(row["passed"]) == 1 for row in checks),
            "checks": checks,
            "visual_status": "VISUAL_REVIEW_PENDING",
        },
    )
    if len(checks) != 4 or not all(int(row["passed"]) == 1 for row in checks):
        raise MatchedBudgetError("one or more of the four frozen smoke checks failed")


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
        ).strip()
    except Exception:
        return ""


def _run_formal(source_run: Path, output_dir: Path, workers: int) -> None:
    smoke_path = output_dir / "smoke_checks.json"
    if not smoke_path.exists() or not bool(_read_json(smoke_path).get("all_passed")):
        raise MatchedBudgetError("the four frozen smoke checks must pass before formal run")
    for name in ("raw_results.csv", "independent_metrics.csv", "run_manifest.json"):
        if (output_dir / name).exists():
            raise MatchedBudgetError(f"formal output already exists: {output_dir / name}")

    case_dirs = sorted((source_run / "raw_cases").glob("C[0-9][0-9][0-9]"))
    if len(case_dirs) != 90:
        raise MatchedBudgetError(f"expected 90 frozen contexts, got {len(case_dirs)}")

    outcomes: list[dict[str, Any]] = []
    if workers == 1:
        outcomes = [_safe_run_context(str(case_dir)) for case_dir in case_dirs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_safe_run_context, str(case_dir)): case_dir.name
                for case_dir in case_dirs
            }
            for future in as_completed(futures):
                outcomes.append(future.result())

    raw_rows = [row for outcome in outcomes for row in outcome["raw_rows"]]
    metric_rows = [row for outcome in outcomes for row in outcome["metric_rows"]]
    raw_rows.sort(
        key=lambda row: (
            str(row["case_id"]),
            int(row["target_l2_count"]),
            str(row["method"]),
        )
    )
    metric_rows.sort(
        key=lambda row: (
            str(row["case_id"]),
            int(row["target_l2_count"]),
            str(row["method"]),
        )
    )
    _write_csv(output_dir / "raw_results.csv", raw_rows, RAW_FIELDS)
    _write_csv(output_dir / "independent_metrics.csv", metric_rows, METRIC_FIELDS)
    _write_csv(
        output_dir / "protocol.csv",
        [
            {
                "protocol_id": "paper_a_rq2_mb_l2_v1",
                "freeze_date": "2026-08-25",
                "matrix_c_source": str(source_run),
                "primary_budget": "exact total L2 curve count B",
                "secondary_budget": "upgraded-parent count U audit only",
                "budget_grid_rule": "B_target=1..2*formal_H2B_intent_upgrade_budget",
                "localgreedy_semantics": "seeded sequential irreversible; skip upgrades exceeding B",
                "ours_semantics": "H2-B bounded joint search with exact terminal B",
                "node_limit": int(
                    _read_json(OURS_CONTRACT_PATH)["bounded_search"]["node_limit"]
                ),
                "bootstrap_seed": BOOTSTRAP_SEED,
                "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            }
        ],
        (
            "protocol_id",
            "freeze_date",
            "matrix_c_source",
            "primary_budget",
            "secondary_budget",
            "budget_grid_rule",
            "localgreedy_semantics",
            "ours_semantics",
            "node_limit",
            "bootstrap_seed",
            "bootstrap_replicates",
        ),
    )
    errors = [
        {"case_id": outcome["case_id"], "error": outcome["error"]}
        for outcome in outcomes
        if outcome["error"]
    ]
    status_counts = Counter(str(row["selection_status"]) for row in raw_rows)
    _write_json(
        output_dir / "run_manifest.json",
        {
            "schema": "paper_a_rq2_mb_l2_run_v1",
            "code_commit": _git_commit(),
            "source_run": str(source_run),
            "context_count": len(case_dirs),
            "raw_result_count": len(raw_rows),
            "independent_metric_count": len(metric_rows),
            "status_counts": dict(sorted(status_counts.items())),
            "context_errors": errors,
            "failure_records_retained": True,
            "silent_fallback_enabled": False,
            "production_code_modified_by_adapter": False,
            "visual_status": "VISUAL_REVIEW_PENDING",
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "formal"), required=True)
    parser.add_argument("--source-run", type=Path, default=DEFAULT_SOURCE_RUN)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    args = parser.parse_args()
    if args.workers <= 0:
        raise SystemExit("workers must be positive")
    source_run = args.source_run.resolve()
    output_dir = args.output_dir.resolve()
    if args.mode == "smoke":
        _smoke_checks(source_run, output_dir)
    else:
        _run_formal(source_run, output_dir, args.workers)
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
