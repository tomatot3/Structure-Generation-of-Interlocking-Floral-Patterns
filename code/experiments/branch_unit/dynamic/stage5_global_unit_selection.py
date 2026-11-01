#!/usr/bin/env python3
"""Build cross-Unit conflicts and select one immutable Unit per approved lane."""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from functools import lru_cache
from typing import Any, Mapping, Sequence

import numpy as np

from composition_geometry import parallel_co_travel_score, CO_TRAVEL_POLICY
from geometry_batch import (
    polyline_pair_intersects,
    polyline_pair_minimum_distance,
)
from prototype_strategy_v1 import validate_strategy_projection


SCHEMA_V1 = "dynamic_branch_stage5_global_unit_selection_v1"
SCHEMA_V2 = "dynamic_branch_stage5_global_unit_selection_v2"
CONFLICT_SCHEMA_V1 = "dynamic_branch_stage5_candidate_conflict_graph_v1"
CONFLICT_SCHEMA_V2 = "dynamic_branch_stage5_candidate_conflict_graph_v2"
CONTRACT_SCHEMA_V1 = "dynamic_branch_stage5_global_selection_contract_v1"
CONTRACT_SCHEMA_V2 = "dynamic_branch_stage5_global_selection_contract_v2"
EDITOR_L2_PRIOR_SCHEMA = "dynamic_branch_editor_l2_placement_prior_v1"
FIXED_L1_ONLY_POLICY = "fixed_l1_only_for_5c_r6"
FIXED_L1_ONLY_5D_POLICY = "fixed_l1_only_for_5d_density_review"
SPARSE_L2_5E_POLICY = "sparse_local_l2_for_5e"
JOINT_SPARSE_L2_H2B_POLICY = "joint_sparse_local_l2_for_h2b"
SPARSE_L2_POLICIES = {
    SPARSE_L2_5E_POLICY,
    JOINT_SPARSE_L2_H2B_POLICY,
}
FIXED_L1_ONLY_POLICIES = {
    FIXED_L1_ONLY_POLICY,
    FIXED_L1_ONLY_5D_POLICY,
}
SCHEMA = SCHEMA_V1
CONFLICT_SCHEMA = CONFLICT_SCHEMA_V1
CONTRACT_SCHEMA = CONTRACT_SCHEMA_V1


class Stage5SelectionError(RuntimeError):
    """The immutable candidate pool cannot be processed under the contract."""


def _candidate_is_actual_l1_only(candidate: Mapping[str, Any]) -> bool:
    hierarchy = candidate.get("hierarchy")
    curves = candidate.get("curves")
    return bool(
        isinstance(hierarchy, Mapping)
        and hierarchy.get("l2_count") == 0
        and hierarchy.get("l3_count") == 0
        and isinstance(curves, Sequence)
        and curves
        and all(
            isinstance(curve, Mapping) and curve.get("level") == "L1"
            for curve in curves
        )
    )


def _candidate_5e_state(candidate: Mapping[str, Any]) -> str | None:
    """Derive the allowed 5E Unit state from actual geometry.

    Allowed states are L1_ONLY, SINGLE_L2_LEFT, SINGLE_L2_RIGHT, and
    OPPOSED_L2_PAIR. The state is recomputed from hierarchy counts and the
    real L2 turn signs instead of reading a self-reported class label.
    Returns None when the Unit must not be selectable under 5E: any L3,
    paired children with identical turn signs (same-side barbs), or an
    unexpected L2 count.
    """

    hierarchy = candidate.get("hierarchy")
    curves = candidate.get("curves")
    if not (isinstance(hierarchy, Mapping) and isinstance(curves, Sequence)):
        return None
    if hierarchy.get("l3_count") != 0:
        return None
    l2_curves = [
        curve
        for curve in curves
        if isinstance(curve, Mapping) and curve.get("level") == "L2"
    ]
    l2_count = len(l2_curves)
    if l2_count == 0:
        return "L1_ONLY"
    if l2_count == 1:
        sign = int(l2_curves[0].get("turn_sign", 0))
        if sign > 0:
            return "SINGLE_L2_RIGHT"
        if sign < 0:
            return "SINGLE_L2_LEFT"
        return None
    if l2_count == 2:
        signs = [int(curve.get("turn_sign", 0)) for curve in l2_curves]
        if signs[0] and signs[1] and signs[0] != signs[1]:
            return "OPPOSED_L2_PAIR"
        return None
    return None


def _select_sparse_l2(
    *,
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
    contract: Mapping[str, Any],
    lane_ids: Sequence[str],
    lane_order: Sequence[str],
    eligible_by_lane: Mapping[str, Sequence[Mapping[str, Any]]],
    conflict_ids: Mapping[str, set[str]],
    pair_penalties: Mapping[str, Mapping[str, float]],
    prototype_strategy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Select a sparse 5E composition: L1-only baseline plus seeded upgrades.

    Phase A re-solves the deterministic best all-L1-only composition with the
    same lexicographic parallel-co-travel objective as 5C/5D. Phase B derives
    an upgrade priority, state phase, and intent budget from unit_seed, then
    upgrades lanes one by one only when the hard conflict graph allows it.
    Landing zero L2 units is a legal result; no fixed class fractions are
    consumed.
    """

    by_state: dict[
        str, dict[str, list[Mapping[str, Any]]]
    ] = defaultdict(lambda: defaultdict(list))
    for lane_id in lane_ids:
        for candidate in eligible_by_lane[lane_id]:
            state = _candidate_5e_state(candidate)
            by_state[state][lane_id].append(candidate)

    baseline_eligible: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for lane_id in lane_order:
        baseline_eligible[lane_id] = sorted(
            by_state["L1_ONLY"][lane_id],
            key=lambda candidate: (
                len(conflict_ids[str(candidate["candidate_id"])]),
                str(candidate["candidate_id"]),
            ),
        )

    best_baseline: list[Mapping[str, Any]] = []
    best_peak = float("inf")
    best_total = float("inf")
    selected: list[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    phase_a_node_count = 0
    phase_a_backtrack_count = 0

    def search(index: int, total: float, peak: float) -> None:
        nonlocal best_baseline, best_peak, best_total
        nonlocal phase_a_node_count, phase_a_backtrack_count
        if index == len(lane_order):
            if (peak, total) < (best_peak, best_total):
                best_peak = peak
                best_total = total
                best_baseline = list(selected)
            return
        lane_id = lane_order[index]
        for candidate in baseline_eligible[lane_id]:
            phase_a_node_count += 1
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
            phase_a_backtrack_count += 1

    search(0, 0.0, 0.0)
    if not best_baseline:
        raise Stage5SelectionError(
            "sparse 5E baseline has no feasible all-L1-only composition"
        )

    unit_seed = int(inventory["unit_seed"])
    upgrade_priority = list(lane_order)
    random.Random(unit_seed).shuffle(upgrade_priority)
    intent_budget = min(
        1 + (unit_seed % 3),
        max(1, (len(lane_ids) - 1) // 2),
    )
    state_cycle = [
        "SINGLE_L2_LEFT",
        "SINGLE_L2_RIGHT",
        "OPPOSED_L2_PAIR",
    ]
    final_by_lane = {
        str(candidate["source_lane_id"]): candidate
        for candidate in best_baseline
    }
    final_ids = {str(candidate["candidate_id"]) for candidate in best_baseline}
    upgrade_lane_ids: list[str] = []
    for priority_index, lane_id in enumerate(upgrade_priority):
        if len(upgrade_lane_ids) >= intent_budget:
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
            candidate_id = str(candidate["candidate_id"])
            if final_ids & conflict_ids[candidate_id]:
                continue
            replaced = final_by_lane[lane_id]
            final_ids.remove(str(replaced["candidate_id"]))
            final_by_lane[lane_id] = candidate
            final_ids.add(candidate_id)
            upgrade_lane_ids.append(lane_id)
            break

    selected_candidates = [
        final_by_lane[str(lane_id)] for lane_id in lane_order
    ]
    selected_l2_count = sum(
        int(candidate["hierarchy"]["l2_count"])
        for candidate in selected_candidates
    )
    selected_l3_count = sum(
        int(candidate["hierarchy"]["l3_count"])
        for candidate in selected_candidates
    )
    result: dict[str, Any] = {
        "schema": SCHEMA_V2,
        "contract_id": contract["contract_id"],
        "selection_id": (
            f"{inventory['inventory_id']}__global_unit_selection_sparse5e"
        ),
        "prototype_id": inventory["prototype_id"],
        "family_id": inventory["family_id"],
        "prototype_strategy": (
            dict(prototype_strategy)
            if isinstance(prototype_strategy, Mapping)
            else None
        ),
        "seed": inventory["seed"],
        "source_inventory_id": inventory["inventory_id"],
        "source_inventory_digest": inventory["inventory_digest"],
        "source_conflict_graph_digest": conflict_graph[
            "conflict_graph_digest"
        ],
        "status": contract["output"]["review_state"],
        "feasible": True,
        "lane_count": len(lane_ids),
        "selected_candidate_count": len(selected_candidates),
        "selected_candidate_ids": [
            candidate["candidate_id"] for candidate in selected_candidates
        ],
        "selected_candidates": selected_candidates,
        "blocking_lane_pairs": [],
        "solver_trace": {
            "method": contract["selection"]["solver"],
            "hierarchy_policy": SPARSE_L2_5E_POLICY,
            "lane_order": list(lane_order),
            "upgrade_priority": upgrade_priority,
            "candidate_order": contract["deterministic_order"][
                "candidate_order"
            ],
            "phase_a_search_node_count": phase_a_node_count,
            "phase_a_backtrack_count": phase_a_backtrack_count,
            "intent_upgrade_budget": intent_budget,
            "achieved_upgrade_count": len(upgrade_lane_ids),
            "upgrade_lane_ids": upgrade_lane_ids,
            "selected_l1_only_count": sum(
                1
                for candidate in selected_candidates
                if _candidate_5e_state(candidate) == "L1_ONLY"
            ),
            "selected_l2_count": selected_l2_count,
            "selected_l3_count": selected_l3_count,
            "zero_l2_landed_is_legal": True,
            "best_of_n_visual_ranking_used": False,
            "composite_visual_score_used": False,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
            "silent_fallback_used": False,
        },
        "review": {
            "numeric_checks_cannot_auto_approve_visual_gate": True,
            "criteria": [
                "l2_forks_are_sparse",
                "forks_are_readable_not_same_side_barbs",
                "local_complexity_emphasis_formed",
                "backbone_flower_l1_rhythm_preserved",
            ],
        },
    }
    result["selection_digest"] = canonical_digest(result)
    validate_global_selection(result, conflict_graph)
    return result


def _candidate_l2_count(candidate: Mapping[str, Any]) -> int:
    return sum(
        1
        for curve in candidate.get("curves", [])
        if isinstance(curve, Mapping) and curve.get("level") == "L2"
    )


def _joint_local_quality_by_candidate(
    eligible_by_lane: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, dict[str, float]]:
    """Score local L2 geometry against the active Stage4 inventory.

    Stage4 has already enforced the hard local geometry constraints.  H2-B
    therefore uses only continuous margins here.  Length and entry opening
    are compared with the median of candidates in the same real Unit state,
    so the selector does not introduce a new fixed L2 template.
    """

    raw: dict[str, dict[str, float | str]] = {}
    by_state: dict[str, list[dict[str, float | str]]] = defaultdict(list)
    for candidates in eligible_by_lane.values():
        for candidate in candidates:
            candidate_id = str(candidate["candidate_id"])
            state = _candidate_5e_state(candidate)
            if state in {None, "L1_ONLY"}:
                raw[candidate_id] = {
                    "state": "L1_ONLY",
                    "clearance_margin": 0.0,
                    "child_parent_length_ratio": 0.0,
                    "entry_opening_degrees": 0.0,
                }
                continue
            curves = list(candidate.get("curves", []))
            l1_length = sum(
                float(curve.get("actual_length", 0.0))
                for curve in curves
                if isinstance(curve, Mapping) and curve.get("level") == "L1"
            )
            l2_length = sum(
                float(curve.get("actual_length", 0.0))
                for curve in curves
                if isinstance(curve, Mapping) and curve.get("level") == "L2"
            )
            metrics = candidate["intrinsic_diagnostics"]["metrics"]
            parent_required = max(
                float(metrics.get("parent_occupancy_clearance", 0.0)),
                1e-9,
            )
            clearance_ratios = [
                float(
                    metrics.get(
                        "minimum_post_departure_parent_clearance",
                        parent_required,
                    )
                )
                / parent_required
            ]
            sibling_required = float(
                metrics.get("required_sibling_curve_clearance", 0.0)
            )
            if sibling_required > 1e-9:
                clearance_ratios.append(
                    float(
                        metrics.get(
                            "minimum_sibling_curve_clearance",
                            sibling_required,
                        )
                    )
                    / sibling_required
                )
            row: dict[str, float | str] = {
                "state": state,
                "clearance_margin": min(clearance_ratios),
                "child_parent_length_ratio": (
                    l2_length / max(l1_length, 1e-9)
                ),
                "entry_opening_degrees": float(
                    metrics.get("minimum_entry_opening_degrees", 0.0)
                ),
            }
            raw[candidate_id] = row
            by_state[state].append(row)

    state_reference: dict[str, dict[str, float]] = {}
    for state, rows in by_state.items():
        state_reference[state] = {
            "length_median": float(
                np.median(
                    [float(row["child_parent_length_ratio"]) for row in rows]
                )
            ),
            "opening_median": float(
                np.median(
                    [float(row["entry_opening_degrees"]) for row in rows]
                )
            ),
        }

    result: dict[str, dict[str, float]] = {}
    for candidate_id, row in raw.items():
        state = str(row["state"])
        if state == "L1_ONLY":
            result[candidate_id] = {
                "score": 0.0,
                "clearance_quality": 0.0,
                "length_typicality": 0.0,
                "opening_typicality": 0.0,
            }
            continue
        reference = state_reference[state]
        clearance_margin = max(0.0, float(row["clearance_margin"]))
        clearance_quality = clearance_margin / (1.0 + clearance_margin)
        length_median = max(reference["length_median"], 1e-9)
        length_typicality = 1.0 / (
            1.0
            + abs(
                np.log(
                    max(
                        float(row["child_parent_length_ratio"]),
                        1e-9,
                    )
                    / length_median
                )
            )
        )
        opening_scale = max(reference["opening_median"], 1.0)
        opening_typicality = 1.0 / (
            1.0
            + abs(
                float(row["entry_opening_degrees"])
                - reference["opening_median"]
            )
            / opening_scale
        )
        score = (
            0.55 * clearance_quality
            + 0.25 * length_typicality
            + 0.20 * opening_typicality
        )
        result[candidate_id] = {
            "score": float(score),
            "clearance_quality": float(clearance_quality),
            "length_typicality": float(length_typicality),
            "opening_typicality": float(opening_typicality),
        }
    return result


def _seeded_tie_value(unit_seed: int, value: str) -> str:
    return hashlib.sha256(f"{unit_seed}:{value}".encode("utf-8")).hexdigest()


def _select_joint_sparse_l2(
    *,
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
    contract: Mapping[str, Any],
    lane_ids: Sequence[str],
    lane_order: Sequence[str],
    eligible_by_lane: Mapping[str, Sequence[Mapping[str, Any]]],
    conflict_ids: Mapping[str, set[str]],
    pair_penalties: Mapping[str, Mapping[str, float]],
    prototype_strategy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Jointly choose one complete Unit per lane under a sparse L2 budget."""

    unit_seed = int(inventory["unit_seed"])
    density_control_profile = inventory.get("density_control_profile")
    target_l2_count: int | None = None
    if density_control_profile is not None:
        if density_control_profile.get("schema") != "visual_density_control_profile_v2":
            raise Stage5SelectionError("density control profile schema mismatch")
        density_level = inventory.get("ordinary_density_level")
        targets = density_control_profile.get("target_selected_l2_count_by_level")
        if (
            density_level not in {"simple", "medium", "rich"}
            or not isinstance(targets, Mapping)
            or set(targets) != {"simple", "medium", "rich"}
        ):
            raise Stage5SelectionError("density control L2 targets are incomplete")
        target_l2_count = int(targets[str(density_level)])
        if target_l2_count < 0 or target_l2_count > 2 * len(lane_ids):
            raise Stage5SelectionError("density control L2 target is out of range")
        intent_budget = min(target_l2_count, len(lane_ids))
    else:
        intent_budget = min(
            1 + (unit_seed % 3),
            max(1, (len(lane_ids) - 1) // 2),
        )
    objective_contract = contract["joint_objective"]
    weights = objective_contract["weights"]
    local_weight = float(weights["local_quality"])
    upgrade_reward = float(weights["upgraded_lane_reward"])
    total_pair_weight = float(weights["total_parallel_penalty"])
    peak_pair_weight = float(weights["peak_parallel_penalty"])
    extra_child_weight = float(weights["extra_l2_child_penalty"])
    node_limit = int(contract["bounded_search"]["node_limit"])
    local_quality = _joint_local_quality_by_candidate(eligible_by_lane)

    ordered_by_lane: dict[str, list[Mapping[str, Any]]] = {}
    best_gain_by_lane: dict[str, float] = {}
    for lane_id in lane_order:
        def candidate_gain(candidate: Mapping[str, Any]) -> float:
            candidate_id = str(candidate["candidate_id"])
            l2_count = _candidate_l2_count(candidate)
            if l2_count == 0:
                return 0.0
            return (
                local_weight * local_quality[candidate_id]["score"]
                + upgrade_reward
                - extra_child_weight * max(0, l2_count - 1)
            )

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
            (candidate_gain(candidate) for candidate in ordered),
            default=0.0,
        )

    selected: list[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    best_selected: list[Mapping[str, Any]] = []
    best_components: dict[str, float | int] | None = None
    best_score = float("-inf")
    best_tie_value: str | None = None
    search_node_count = 0
    feasible_composition_count = 0
    backtrack_count = 0
    conflict_prune_count = 0
    budget_prune_count = 0
    bound_prune_count = 0
    node_limit_reached = False

    def score_components(
        *,
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
        *,
        local_sum: float,
        upgraded_count: int,
        total_l2_count: int,
        pair_total: float,
        pair_peak: float,
    ) -> None:
        nonlocal best_selected, best_components, best_score, best_tie_value
        nonlocal search_node_count, feasible_composition_count
        nonlocal backtrack_count, conflict_prune_count, budget_prune_count
        nonlocal bound_prune_count, node_limit_reached
        if search_node_count >= node_limit:
            node_limit_reached = True
            return
        if lane_index == len(lane_order):
            if target_l2_count is not None and total_l2_count != target_l2_count:
                return
            feasible_composition_count += 1
            components = score_components(
                local_sum=local_sum,
                upgraded_count=upgraded_count,
                total_l2_count=total_l2_count,
                pair_total=pair_total,
                pair_peak=pair_peak,
            )
            score = float(components["score"])
            tie_value = _seeded_tie_value(
                unit_seed,
                "|".join(
                    sorted(str(candidate["candidate_id"]) for candidate in selected)
                ),
            )
            if (
                score > best_score + 1e-12
                or (
                    abs(score - best_score) <= 1e-12
                    and (best_tie_value is None or tie_value < best_tie_value)
                )
            ):
                best_score = score
                best_tie_value = tie_value
                best_selected = list(selected)
                best_components = components
            return

        current_components = score_components(
            local_sum=local_sum,
            upgraded_count=upgraded_count,
            total_l2_count=total_l2_count,
            pair_total=pair_total,
            pair_peak=pair_peak,
        )
        remaining_budget = max(0, intent_budget - upgraded_count)
        remaining_gains = sorted(
            (
                max(0.0, best_gain_by_lane[lane_id])
                for lane_id in lane_order[lane_index:]
            ),
            reverse=True,
        )[:remaining_budget]
        optimistic_score = float(current_components["score"]) + sum(
            remaining_gains
        )
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
            l2_count = _candidate_l2_count(candidate)
            if (
                target_l2_count is not None
                and total_l2_count + l2_count > target_l2_count
            ):
                budget_prune_count += 1
                continue
            is_upgrade = int(l2_count > 0)
            next_upgraded_count = upgraded_count + is_upgrade
            if next_upgraded_count > intent_budget:
                budget_prune_count += 1
                continue
            added_pair_penalties = [
                pair_penalties[candidate_id].get(existing_id, 0.0)
                for existing_id in selected_ids
            ]
            selected.append(candidate)
            selected_ids.add(candidate_id)
            search(
                lane_index + 1,
                local_sum=(
                    local_sum
                    + local_quality[candidate_id]["score"] * is_upgrade
                ),
                upgraded_count=next_upgraded_count,
                total_l2_count=total_l2_count + l2_count,
                pair_total=pair_total + sum(added_pair_penalties),
                pair_peak=max(
                    pair_peak,
                    max(added_pair_penalties, default=0.0),
                ),
            )
            selected.pop()
            selected_ids.remove(candidate_id)
            backtrack_count += 1

    search(
        0,
        local_sum=0.0,
        upgraded_count=0,
        total_l2_count=0,
        pair_total=0.0,
        pair_peak=0.0,
    )
    if not best_selected or best_components is None:
        raise Stage5SelectionError(
            "joint H2-B search found no complete legal composition"
            + (
                f" at selected L2 target {target_l2_count}"
                if target_l2_count is not None
                else ""
            )
        )

    selected_candidates = list(best_selected)
    selected_l2_count = sum(
        _candidate_l2_count(candidate) for candidate in selected_candidates
    )
    upgrade_lane_ids = [
        str(candidate["source_lane_id"])
        for candidate in selected_candidates
        if _candidate_l2_count(candidate) > 0
    ]
    result: dict[str, Any] = {
        "schema": SCHEMA_V2,
        "contract_id": contract["contract_id"],
        "selection_id": (
            f"{inventory['inventory_id']}__global_unit_selection_joint_h2b"
        ),
        "prototype_id": inventory["prototype_id"],
        "family_id": inventory["family_id"],
        "prototype_strategy": (
            dict(prototype_strategy)
            if isinstance(prototype_strategy, Mapping)
            else None
        ),
        "seed": inventory["seed"],
        "source_inventory_id": inventory["inventory_id"],
        "source_inventory_digest": inventory["inventory_digest"],
        "source_conflict_graph_digest": conflict_graph[
            "conflict_graph_digest"
        ],
        "status": contract["output"]["review_state"],
        "feasible": True,
        "lane_count": len(lane_ids),
        "selected_candidate_count": len(selected_candidates),
        "selected_candidate_ids": [
            candidate["candidate_id"] for candidate in selected_candidates
        ],
        "selected_candidates": selected_candidates,
        "blocking_lane_pairs": [],
        "solver_trace": {
            "method": contract["selection"]["solver"],
            "hierarchy_policy": JOINT_SPARSE_L2_H2B_POLICY,
            "lane_order": list(lane_order),
            "candidate_order": contract["deterministic_order"][
                "candidate_order"
            ],
            "intent_upgrade_budget": intent_budget,
            "maximum_upgrade_lane_count": intent_budget,
            "target_selected_l2_count": target_l2_count,
            "target_selected_l2_count_type": (
                "density_control_exact"
                if target_l2_count is not None
                else "not_requested"
            ),
            "achieved_upgrade_count": len(upgrade_lane_ids),
            "upgrade_lane_ids": upgrade_lane_ids,
            "selected_l1_only_count": sum(
                1
                for candidate in selected_candidates
                if _candidate_5e_state(candidate) == "L1_ONLY"
            ),
            "selected_l2_count": selected_l2_count,
            "selected_l3_count": 0,
            "search_node_limit": node_limit,
            "search_node_count": search_node_count,
            "backtrack_count": backtrack_count,
            "feasible_composition_count": feasible_composition_count,
            "hard_conflict_prune_count": conflict_prune_count,
            "sparse_budget_prune_count": budget_prune_count,
            "objective_bound_prune_count": bound_prune_count,
            "search_node_limit_reached": node_limit_reached,
            "bounded_space_exhausted": not node_limit_reached,
            "global_optimum_claimed": False,
            "selection_basis": "best_feasible_composition_seen",
            "objective_weights": dict(weights),
            "selected_objective": {
                key: round(float(value), 9)
                if isinstance(value, float)
                else value
                for key, value in best_components.items()
            },
            "selected_local_quality": {
                str(candidate["candidate_id"]): {
                    key: round(float(value), 9)
                    for key, value in local_quality[
                        str(candidate["candidate_id"])
                    ].items()
                }
                for candidate in selected_candidates
                if _candidate_l2_count(candidate) > 0
            },
            "zero_l2_landed_is_legal": True,
            "irreversible_lane_upgrade_order_used": False,
            "best_of_n_visual_ranking_used": False,
            "composite_visual_score_used": False,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
            "silent_fallback_used": False,
        },
        "review": {
            "numeric_checks_cannot_auto_approve_visual_gate": True,
            "criteria": [
                "l2_forks_are_sparse",
                "joint_selection_avoids_cross_unit_crowding",
                "local_forks_remain_readable",
                "backbone_flower_l1_rhythm_preserved",
            ],
        },
    }
    result["selection_digest"] = canonical_digest(result)
    validate_global_selection(result, conflict_graph)
    return result


def _editor_l2_profile(
    editor_l2_prior: Mapping[str, Any],
    prototype_id: str,
    profile_key: str | None = None,
) -> Mapping[str, Any]:
    if editor_l2_prior.get("schema") != EDITOR_L2_PRIOR_SCHEMA:
        raise Stage5SelectionError("editor L2 placement prior schema mismatch")
    profiles = editor_l2_prior.get("profiles")
    if not isinstance(profiles, Mapping):
        raise Stage5SelectionError("editor L2 placement prior has no profiles")
    profile = profiles.get(profile_key or prototype_id) or profiles.get("global")
    if not isinstance(profile, Mapping):
        raise Stage5SelectionError(
            f"editor L2 placement prior has no profile for {prototype_id}"
        )
    return profile


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _curve_bounds(
    curve: Mapping[str, Any],
    shift_x: float = 0.0,
) -> tuple[float, float, float, float]:
    points = curve["centerline"]
    return (
        min(float(point[0]) for point in points) + shift_x,
        min(float(point[1]) for point in points),
        max(float(point[0]) for point in points) + shift_x,
        max(float(point[1]) for point in points),
    )


def _bounds_overlap(
    first: Sequence[float],
    second: Sequence[float],
) -> bool:
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


@lru_cache(maxsize=4096)
def _cached_polyline_distance(
    first_points: tuple[tuple[float, float], ...],
    second_points: tuple[tuple[float, float], ...],
) -> float:
    first_array = np.asarray(first_points, dtype=np.float64)
    second_array = np.asarray(second_points, dtype=np.float64)
    return polyline_pair_minimum_distance(first_array, second_array)


def _bounds_distance(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    gap_x = max(0.0, first[0] - second[2], second[0] - first[2])
    gap_y = max(0.0, first[1] - second[3], second[1] - first[3])
    return (gap_x * gap_x + gap_y * gap_y) ** 0.5


def candidate_pair_crossings(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    repeat_shifts: Sequence[float],
) -> list[dict[str, Any]]:
    crossings: list[dict[str, Any]] = []
    for first_curve in first["curves"]:
        for second_curve in second["curves"]:
            first_bounds = _curve_bounds(first_curve)
            for shift_x in repeat_shifts:
                second_bounds = _curve_bounds(second_curve, float(shift_x))
                if not _bounds_overlap(first_bounds, second_bounds):
                    continue
                first_points_array = np.asarray(
                    [
                        [float(point[0]), float(point[1])]
                        for point in first_curve["centerline"]
                    ],
                    dtype=np.float64,
                )
                second_points_array = np.asarray(
                    [
                        [float(point[0]) + float(shift_x), float(point[1])]
                        for point in second_curve["centerline"]
                    ],
                    dtype=np.float64,
                )
                if polyline_pair_intersects(
                    first_points_array,
                    second_points_array,
                ):
                    crossings.append(
                        {
                            "first_curve_id": first_curve["curve_id"],
                            "first_level": first_curve["level"],
                            "second_curve_id": second_curve["curve_id"],
                            "second_level": second_curve["level"],
                            "second_repeat_shift_x": float(shift_x),
                        }
                    )
    return crossings


def candidate_pair_minimum_clearance(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    repeat_shifts: Sequence[float],
) -> float:
    """Measure the full curve-to-curve clearance between two BranchUnits."""

    minimum = float("inf")
    for first_curve in first["curves"]:
        for second_curve in second["curves"]:
            first_points = tuple(
                (float(point[0]), float(point[1]))
                for point in first_curve["centerline"]
            )
            first_bounds = _curve_bounds(first_curve)
            for shift_x in repeat_shifts:
                second_points = tuple(
                    (float(point[0]) + float(shift_x), float(point[1]))
                    for point in second_curve["centerline"]
                )
                second_bounds = _curve_bounds(second_curve, float(shift_x))
                if _bounds_distance(first_bounds, second_bounds) >= minimum:
                    continue
                minimum = min(
                    minimum,
                    _cached_polyline_distance(first_points, second_points),
                )
    return minimum


def candidate_pair_parallel_co_travel(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    repeat_shifts: Sequence[float],
) -> dict[str, Any]:
    """Find the strongest cross-Unit co-travel pair involving a descendant."""

    maximum = 0.0
    maximum_pair: dict[str, Any] | None = None
    for first_curve in first["curves"]:
        for second_curve in second["curves"]:
            if (
                first_curve["level"] == "L1"
                and second_curve["level"] == "L1"
            ):
                continue
            score = parallel_co_travel_score(
                first_curve["centerline"],
                second_curve["centerline"],
                repeat_shifts=repeat_shifts,
            )
            if score > maximum:
                maximum = score
                maximum_pair = {
                    "first_curve_id": first_curve["curve_id"],
                    "first_level": first_curve["level"],
                    "second_curve_id": second_curve["curve_id"],
                    "second_level": second_curve["level"],
                }
    return {
        "score": maximum,
        "curve_pair": maximum_pair,
    }


def build_conflict_graph(
    inventory: Mapping[str, Any],
    contract: Mapping[str, Any],
    editor_l2_prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract_schema = str(contract.get("schema"))
    fixed_l1_only = (
        contract_schema == CONTRACT_SCHEMA_V2
        and contract.get("selection", {}).get("hierarchy_policy")
        in FIXED_L1_ONLY_POLICIES
    )
    sparse_l2 = (
        contract_schema == CONTRACT_SCHEMA_V2
        and contract.get("selection", {}).get("hierarchy_policy")
        in SPARSE_L2_POLICIES
    )

    def graph_eligible(candidate: Mapping[str, Any]) -> bool:
        if not candidate["intrinsic_diagnostics"]["valid"]:
            return False
        if fixed_l1_only and not _candidate_is_actual_l1_only(candidate):
            return False
        if sparse_l2 and _candidate_5e_state(candidate) is None:
            return False
        return True

    prototype_strategy = inventory.get("prototype_strategy")
    if contract_schema == CONTRACT_SCHEMA_V2 and not isinstance(
        prototype_strategy, Mapping
    ):
        raise Stage5SelectionError("stage-4 inventory lacks frozen prototype strategy")
    if isinstance(prototype_strategy, Mapping):
        validate_strategy_projection(
            prototype_strategy,
            prototype_id=str(inventory["prototype_id"]),
            family_id=str(inventory["family_id"]),
        )
    repeat_shifts = [
        float(value)
        for value in contract["hard_constraints"]["repeat_shifts_checked"]
    ]
    minimum_clearance: float | None = None
    parallel_co_travel_soft_limit: float | None = None
    parallel_co_travel_upper_tail: float | None = None
    maximum_parallel_co_travel: float | None = None
    editor_l2_prior_id: str | None = None
    if contract_schema == CONTRACT_SCHEMA_V2:
        if editor_l2_prior is None:
            raise Stage5SelectionError(
                "stage-5 V2 requires the editor L2 placement prior"
            )
        profile = _editor_l2_profile(
            editor_l2_prior,
            str(inventory["prototype_id"]),
            str(
                prototype_strategy["branchunit_profile"][
                    "editor_l2_profile_key"
                ]
            ),
        )
        occupancy_radii = [
            float(tube["radius"])
            for candidate in inventory["candidates"]
            if graph_eligible(candidate)
            for tube in candidate["occupancy_tubes"]
        ]
        if not occupancy_radii:
            raise Stage5SelectionError("stage-4 inventory lacks occupancy tubes")
        occupancy_diameter = 2.0 * max(occupancy_radii)
        minimum_clearance = max(
            occupancy_diameter,
            float(profile["nonparent_curve_clearance_unit_ratio"]["q10"]),
        )
        parallel_distribution = profile[
            "cross_unit_parallel_co_travel_score"
        ]
        parallel_co_travel_soft_limit = 0.0
        parallel_co_travel_upper_tail = float(
            parallel_distribution["q95"]
        )
        maximum_parallel_co_travel = 1.0  # score domain, not a hard threshold
        editor_l2_prior_id = str(editor_l2_prior["prior_id"])
    candidates = inventory["candidates"]
    nodes = [
        {
            "candidate_id": candidate["candidate_id"],
            "source_lane_id": candidate["source_lane_id"],
            "role": candidate["role"],
            "grammar_id": candidate["grammar_id"],
            "parameter_stratum": candidate["parameter_stratum"],
            "eligible": graph_eligible(candidate),
            "intrinsic_issue_codes": [
                issue["code"]
                for issue in candidate["intrinsic_diagnostics"]["issues"]
            ],
        }
        for candidate in candidates
    ]
    eligible = [
        candidate
        for candidate in candidates
        if graph_eligible(candidate)
    ]
    edges: list[dict[str, Any]] = []
    pair_penalties: list[dict[str, Any]] = []
    for index, first in enumerate(eligible):
        for second in eligible[index + 1 :]:
            if first["source_lane_id"] == second["source_lane_id"]:
                continue
            crossings = candidate_pair_crossings(
                first,
                second,
                repeat_shifts,
            )
            pair_clearance = candidate_pair_minimum_clearance(
                first,
                second,
                repeat_shifts,
            )
            crowded = (
                minimum_clearance is not None
                and pair_clearance < minimum_clearance
            )
            parallel = candidate_pair_parallel_co_travel(
                first,
                second,
                repeat_shifts,
            )
            if (
                parallel_co_travel_soft_limit is not None
                and maximum_parallel_co_travel is not None
                and float(parallel["score"])
                > parallel_co_travel_soft_limit + 1e-9
            ):
                pair_penalties.append(
                    {
                        "first_candidate_id": first["candidate_id"],
                        "first_lane_id": first["source_lane_id"],
                        "second_candidate_id": second["candidate_id"],
                        "second_lane_id": second["source_lane_id"],
                        "parallel_co_travel_score": round(
                            float(parallel["score"]), 9
                        ),
                        "normalized_penalty": round(
                            max(
                                0.0,
                                float(parallel["score"])
                                - parallel_co_travel_soft_limit,
                            )
                            / max(
                                maximum_parallel_co_travel
                                - parallel_co_travel_soft_limit,
                                0.01,
                            ),
                            9,
                        ),
                        "curve_pair": parallel["curve_pair"],
                    }
                )
            if crossings or crowded:
                conflict_kinds = [
                    name
                    for active, name in (
                        (bool(crossings), "cross_unit_curve_crossing"),
                        (crowded, "editor_l2_clearance_violation"),
                    )
                    if active
                ]
                edge = {
                    "first_candidate_id": first["candidate_id"],
                    "first_lane_id": first["source_lane_id"],
                    "second_candidate_id": second["candidate_id"],
                    "second_lane_id": second["source_lane_id"],
                    "reason": (
                        conflict_kinds[0]
                        if len(conflict_kinds) == 1
                        else "multiple_cross_unit_geometry_conflicts"
                    ),
                    "conflict_kinds": conflict_kinds,
                    "crossings": crossings,
                }
                if contract_schema == CONTRACT_SCHEMA_V2:
                    edge.update(
                        {
                            "minimum_descendant_clearance": round(
                                pair_clearance, 9
                            ),
                            "required_descendant_clearance": round(
                                float(minimum_clearance), 9
                            ),
                            "parallel_co_travel_score": round(
                                float(parallel["score"]), 9
                            ),
                            "maximum_parallel_co_travel_score": round(
                                float(maximum_parallel_co_travel), 9
                            ),
                            "parallel_co_travel_curve_pair": parallel[
                                "curve_pair"
                            ],
                        }
                    )
                edges.append(edge)
    graph_schema = (
        CONFLICT_SCHEMA_V2
        if contract_schema == CONTRACT_SCHEMA_V2
        else CONFLICT_SCHEMA_V1
    )
    graph: dict[str, Any] = {
        "schema": graph_schema,
        "contract_id": contract["contract_id"],
        "prototype_id": inventory["prototype_id"],
        "prototype_strategy": (
            dict(prototype_strategy)
            if isinstance(prototype_strategy, Mapping)
            else None
        ),
        "seed": inventory["seed"],
        "source_inventory_id": inventory["inventory_id"],
        "source_inventory_digest": inventory["inventory_digest"],
        "node_count": len(nodes),
        "eligible_node_count": len(eligible),
        "ineligible_node_count": len(nodes) - len(eligible),
        "edge_count": len(edges),
        "repeat_shifts_checked": repeat_shifts,
        "nodes": nodes,
        "edges": edges,
        "pair_penalty_count": len(pair_penalties),
        "pair_penalties": pair_penalties,
        "co_travel_policy": dict(CO_TRAVEL_POLICY),
    }
    if contract_schema == CONTRACT_SCHEMA_V2:
        graph.update(
            {
                "editor_l2_placement_prior_id": editor_l2_prior_id,
                "minimum_descendant_clearance": round(
                    float(minimum_clearance), 9
                ),
                "maximum_parallel_co_travel_score": round(
                    float(maximum_parallel_co_travel), 9
                ),
                "parallel_co_travel_soft_limit": round(
                    float(parallel_co_travel_soft_limit), 9
                ),
                "parallel_co_travel_editor_q95": round(
                    float(parallel_co_travel_upper_tail), 9
                ),
            }
        )
    graph["conflict_graph_digest"] = canonical_digest(graph)
    return graph


def _blocking_lane_pairs(
    eligible_by_lane: Mapping[str, Sequence[Mapping[str, Any]]],
    conflict_ids: Mapping[str, set[str]],
) -> list[dict[str, Any]]:
    lanes = sorted(eligible_by_lane)
    rows: list[dict[str, Any]] = []
    for index, first_lane in enumerate(lanes):
        for second_lane in lanes[index + 1 :]:
            first_candidates = eligible_by_lane[first_lane]
            second_candidates = eligible_by_lane[second_lane]
            if all(
                second["candidate_id"]
                in conflict_ids[first["candidate_id"]]
                for first in first_candidates
                for second in second_candidates
            ):
                rows.append(
                    {
                        "first_lane_id": first_lane,
                        "second_lane_id": second_lane,
                        "first_candidate_count": len(first_candidates),
                        "second_candidate_count": len(second_candidates),
                        "reason": "every_candidate_pair_conflicts",
                    }
                )
    return rows


def _derive_hierarchy_mix_counts(
    lane_count: int,
    fractions: Mapping[str, Any],
) -> dict[str, int]:
    """Convert edit-derived fractions to exact per-composition counts."""

    class_order = ("l1_only", "single_child", "paired_child")
    if set(fractions) != set(class_order):
        raise Stage5SelectionError("hierarchy mix classes are incomplete")
    total = sum(float(fractions[name]) for name in class_order)
    if total <= 0.0:
        raise Stage5SelectionError("hierarchy mix fractions must be positive")
    raw = {
        name: lane_count * float(fractions[name]) / total
        for name in class_order
    }
    counts = {name: int(raw[name]) for name in class_order}
    remainder = lane_count - sum(counts.values())
    ranked = sorted(
        class_order,
        key=lambda name: (-(raw[name] - counts[name]), class_order.index(name)),
    )
    for name in ranked[:remainder]:
        counts[name] += 1
    return counts


def select_global_units(
    inventory: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    contract_schema = str(contract.get("schema"))
    is_v2 = contract_schema == CONTRACT_SCHEMA_V2
    prototype_strategy = inventory.get("prototype_strategy")
    if is_v2 and not isinstance(prototype_strategy, Mapping):
        raise Stage5SelectionError("stage-4 inventory lacks frozen prototype strategy")
    if isinstance(prototype_strategy, Mapping):
        validate_strategy_projection(
            prototype_strategy,
            prototype_id=str(inventory["prototype_id"]),
            family_id=str(inventory["family_id"]),
        )
    if (
        isinstance(prototype_strategy, Mapping)
        and conflict_graph.get("prototype_strategy") != prototype_strategy
    ):
        raise Stage5SelectionError("conflict graph strategy projection mismatch")
    fixed_l1_only_policy = contract.get("selection", {}).get(
        "hierarchy_policy"
    )
    fixed_l1_only = (
        is_v2 and fixed_l1_only_policy in FIXED_L1_ONLY_POLICIES
    )
    sparse_l2 = is_v2 and fixed_l1_only_policy in SPARSE_L2_POLICIES
    joint_sparse_l2 = (
        is_v2 and fixed_l1_only_policy == JOINT_SPARSE_L2_H2B_POLICY
    )

    eligible_by_lane: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for candidate in inventory["candidates"]:
        if candidate["intrinsic_diagnostics"]["valid"] and (
            not fixed_l1_only or _candidate_is_actual_l1_only(candidate)
        ) and (not sparse_l2 or _candidate_5e_state(candidate) is not None):
            eligible_by_lane[str(candidate["source_lane_id"])].append(candidate)

    lane_ids = [str(row["source_lane_id"]) for row in inventory["lanes"]]
    if set(lane_ids) != set(eligible_by_lane):
        raise Stage5SelectionError("one or more lanes have no eligible Unit")
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

    if contract_schema not in {CONTRACT_SCHEMA_V1, CONTRACT_SCHEMA_V2}:
        raise Stage5SelectionError("stage-5 contract schema mismatch")

    if joint_sparse_l2:
        return _select_joint_sparse_l2(
            inventory=inventory,
            conflict_graph=conflict_graph,
            contract=contract,
            lane_ids=lane_ids,
            lane_order=lane_order,
            eligible_by_lane=eligible_by_lane,
            conflict_ids=conflict_ids,
            pair_penalties=pair_penalties,
            prototype_strategy=prototype_strategy,
        )

    if sparse_l2:
        return _select_sparse_l2(
            inventory=inventory,
            conflict_graph=conflict_graph,
            contract=contract,
            lane_ids=lane_ids,
            lane_order=lane_order,
            eligible_by_lane=eligible_by_lane,
            conflict_ids=conflict_ids,
            pair_penalties=pair_penalties,
            prototype_strategy=prototype_strategy,
        )

    hierarchy_targets: dict[str, int] | None = None
    seed_class_offset: int | None = None
    if fixed_l1_only:
        for lane_id in lane_order:
            eligible_by_lane[lane_id].sort(
                key=lambda candidate: (
                    len(conflict_ids[str(candidate["candidate_id"])]),
                    str(candidate["candidate_id"]),
                )
            )
    elif is_v2:
        selection_policy = prototype_strategy["global_selection_profile"]
        if selection_policy["hierarchy_mix_policy"] != "contract_fraction_targets":
            raise Stage5SelectionError("unsupported hierarchy-mix strategy")
        if selection_policy["candidate_order_policy"] != (
            "contract_class_cycle_seed_phase"
        ):
            raise Stage5SelectionError("unsupported candidate-order strategy")
        hierarchy_targets = _derive_hierarchy_mix_counts(
            len(lane_ids),
            contract["hierarchy_mix"]["class_fraction_targets"],
        )
        class_cycle = list(contract["deterministic_order"]["class_cycle"])
        seed_class_offset = (
            int(inventory["seed"])
            + int(selection_policy["class_cycle_phase_offset"])
        ) % len(class_cycle)
        stratum_priorities = contract["deterministic_order"][
            "within_class_stratum_priority"
        ]

        def v2_candidate_order(
            candidate: Mapping[str, Any],
            lane_index: int,
        ) -> tuple[int, int, int, str]:
            density_class = str(
                candidate["visual_features"]["hierarchy_density_class"]
            )
            class_offset = (lane_index + seed_class_offset) % len(class_cycle)
            desired_class_order = (
                class_cycle[class_offset:]
                + class_cycle[:class_offset]
            )
            strata = list(stratum_priorities[density_class])
            # Repeated visits to the same hierarchy class rotate through its
            # strata.  The branch seed rotates the first visited stratum while
            # leaving crossing and clearance constraints unchanged.
            offset = (
                lane_index // len(class_cycle) + int(inventory["seed"])
            ) % len(strata)
            rotated_strata = strata[offset:] + strata[:offset]
            return (
                desired_class_order.index(density_class),
                rotated_strata.index(str(candidate["parameter_stratum"])),
                len(conflict_ids[str(candidate["candidate_id"])]),
                str(candidate["candidate_id"]),
            )

        for lane_index, lane_id in enumerate(lane_order):
            eligible_by_lane[lane_id].sort(
                key=lambda candidate, index=lane_index: v2_candidate_order(
                    candidate,
                    index,
                )
            )
    else:
        priorities = contract["deterministic_order"]["role_stratum_priority"]

        def v1_candidate_order(
            candidate: Mapping[str, Any],
        ) -> tuple[int, int, str]:
            role_priority = priorities[str(candidate["role"])]
            return (
                role_priority.index(str(candidate["parameter_stratum"])),
                len(conflict_ids[str(candidate["candidate_id"])]),
                str(candidate["candidate_id"]),
            )

        for lane_id in lane_order:
            eligible_by_lane[lane_id].sort(key=v1_candidate_order)

    selected: list[Mapping[str, Any]] = []
    selected_ids: set[str] = set()
    selected_hierarchy_counts: dict[str, int] = defaultdict(int)
    search_node_count = 0
    backtrack_count = 0
    best_selected: list[Mapping[str, Any]] = []
    best_parallel_penalty = float("inf")
    best_parallel_peak_penalty = float("inf")

    def search(
        lane_index: int,
        parallel_penalty: float = 0.0,
        parallel_peak_penalty: float = 0.0,
    ) -> bool:
        nonlocal search_node_count, backtrack_count
        nonlocal best_parallel_penalty, best_parallel_peak_penalty
        if lane_index == len(lane_order):
            if (
                is_v2
                and not fixed_l1_only
                and dict(selected_hierarchy_counts) != hierarchy_targets
            ):
                return False
            if is_v2:
                objective = (parallel_peak_penalty, parallel_penalty)
                best_objective = (
                    best_parallel_peak_penalty,
                    best_parallel_penalty,
                )
                if objective < best_objective:
                    best_parallel_peak_penalty = parallel_peak_penalty
                    best_parallel_penalty = parallel_penalty
                    best_selected[:] = selected
                return False
            return True
        if is_v2 and hierarchy_targets is not None:
            remaining_lanes = lane_order[lane_index:]
            for density_class, target in hierarchy_targets.items():
                deficit = target - selected_hierarchy_counts[density_class]
                if deficit < 0:
                    return False
                available_lane_count = sum(
                    any(
                        str(
                            candidate["visual_features"][
                                "hierarchy_density_class"
                            ]
                        )
                        == density_class
                        for candidate in eligible_by_lane[remaining_lane]
                    )
                    for remaining_lane in remaining_lanes
                )
                if deficit > available_lane_count:
                    return False
        lane_id = lane_order[lane_index]
        for candidate in eligible_by_lane[lane_id]:
            search_node_count += 1
            candidate_id = str(candidate["candidate_id"])
            if selected_ids & conflict_ids[candidate_id]:
                continue
            added_pair_penalties = [
                pair_penalties[candidate_id].get(existing_id, 0.0)
                for existing_id in selected_ids
            ]
            added_parallel_penalty = sum(added_pair_penalties)
            next_parallel_penalty = (
                parallel_penalty + added_parallel_penalty
            )
            next_parallel_peak_penalty = max(
                parallel_peak_penalty,
                max(added_pair_penalties, default=0.0),
            )
            if (
                is_v2
                and (
                    next_parallel_peak_penalty
                    > best_parallel_peak_penalty + 1e-12
                    or (
                        abs(
                            next_parallel_peak_penalty
                            - best_parallel_peak_penalty
                        )
                        <= 1e-12
                        and next_parallel_penalty
                        >= best_parallel_penalty - 1e-12
                    )
                )
            ):
                continue
            density_class = None
            if is_v2 and hierarchy_targets is not None:
                density_class = str(
                    candidate["visual_features"]["hierarchy_density_class"]
                )
                if (
                    selected_hierarchy_counts[density_class]
                    >= hierarchy_targets[density_class]
                ):
                    continue
            selected.append(candidate)
            selected_ids.add(candidate_id)
            if density_class is not None:
                selected_hierarchy_counts[density_class] += 1
            if search(
                lane_index + 1,
                next_parallel_penalty,
                next_parallel_peak_penalty,
            ):
                return True
            selected.pop()
            selected_ids.remove(candidate_id)
            if density_class is not None:
                selected_hierarchy_counts[density_class] -= 1
            backtrack_count += 1
        return False

    first_assignment_feasible = search(0)
    if is_v2:
        feasible = bool(best_selected)
        selected = list(best_selected)
        selected_ids = {
            str(candidate["candidate_id"]) for candidate in selected
        }
        selected_hierarchy_counts = defaultdict(int)
        for candidate in selected:
            selected_hierarchy_counts[
                str(
                    candidate["visual_features"][
                        "hierarchy_density_class"
                    ]
                )
            ] += 1
    else:
        feasible = first_assignment_feasible
    selected_candidates = list(selected) if feasible else []
    result: dict[str, Any] = {
        "schema": SCHEMA_V2 if is_v2 else SCHEMA_V1,
        "contract_id": contract["contract_id"],
        "selection_id": (
            f"{inventory['inventory_id']}__global_unit_selection_"
            f"{'v2' if is_v2 else 'v1'}"
        ),
        "prototype_id": inventory["prototype_id"],
        "family_id": inventory["family_id"],
        "prototype_strategy": (
            dict(prototype_strategy)
            if isinstance(prototype_strategy, Mapping)
            else None
        ),
        "seed": inventory["seed"],
        "source_inventory_id": inventory["inventory_id"],
        "source_inventory_digest": inventory["inventory_digest"],
        "source_conflict_graph_digest": conflict_graph[
            "conflict_graph_digest"
        ],
        "status": (
            contract["output"]["review_state"]
            if feasible
            else "global_unit_selection_infeasible"
        ),
        "feasible": feasible,
        "lane_count": len(lane_ids),
        "selected_candidate_count": len(selected_candidates),
        "selected_candidate_ids": [
            candidate["candidate_id"] for candidate in selected_candidates
        ],
        "selected_candidates": selected_candidates,
        "blocking_lane_pairs": (
            []
            if feasible
            else _blocking_lane_pairs(eligible_by_lane, conflict_ids)
        ),
        "solver_trace": {
            "method": contract["selection"]["solver"],
            "hierarchy_policy": (
                str(fixed_l1_only_policy)
                if fixed_l1_only
                else "contract_fraction_targets"
                if is_v2
                else "role_conditioned_v1"
            ),
            "lane_order": lane_order,
            "candidate_order": contract["deterministic_order"][
                "candidate_order"
            ],
            "search_node_count": search_node_count,
            "backtrack_count": backtrack_count,
            "stopped_at_first_complete_legal_assignment": (
                feasible and not is_v2
            ),
            "best_of_n_visual_ranking_used": False,
            "composite_visual_score_used": False,
            "validation_guided_retry_used": False,
            "validation_guided_resample_used": False,
            "automatic_repair_used": False,
            "automatic_deletion_used": False,
            "silent_fallback_used": False,
        },
        "review": {
            "numeric_checks_cannot_auto_approve_visual_gate": True,
            "criteria": [
                "whole_composition_vine_flow",
                "cross_unit_non_crossing",
                "hierarchy_and_density_rhythm",
                "flower_support_relation",
                "repeat_continuity",
            ],
        },
    }
    if fixed_l1_only:
        result["solver_trace"].update(
            {
                "selected_l1_only_count": len(selected_candidates),
                "selected_l2_count": sum(
                    int(candidate["hierarchy"]["l2_count"])
                    for candidate in selected_candidates
                ),
                "selected_l3_count": sum(
                    int(candidate["hierarchy"]["l3_count"])
                    for candidate in selected_candidates
                ),
                "stage_scope_overrides_prototype_hierarchy_mix": True,
                "global_pair_penalty_optimized": True,
                "selected_parallel_co_travel_penalty": (
                    round(best_parallel_penalty, 9)
                    if feasible
                    else None
                ),
                "selected_parallel_co_travel_peak_penalty": (
                    round(best_parallel_peak_penalty, 9)
                    if feasible
                    else None
                ),
            }
        )
    elif is_v2:
        result["solver_trace"].update(
            {
                "edit_feedback_structural_mix_enforced": True,
                "hierarchy_mix_target_counts": hierarchy_targets,
                "hierarchy_mix_selected_counts": dict(
                    selected_hierarchy_counts
                ),
                "branch_seed_class_phase": seed_class_offset,
                "global_pair_penalty_optimized": True,
                "selected_parallel_co_travel_penalty": (
                    round(best_parallel_penalty, 9)
                    if feasible
                    else None
                ),
                "selected_parallel_co_travel_peak_penalty": (
                    round(best_parallel_peak_penalty, 9)
                    if feasible
                    else None
                ),
            }
        )
    result["selection_digest"] = canonical_digest(result)
    validate_global_selection(result, conflict_graph)
    return result


def validate_global_selection(
    selection: Mapping[str, Any],
    conflict_graph: Mapping[str, Any],
) -> None:
    if selection.get("schema") not in {SCHEMA_V1, SCHEMA_V2}:
        raise Stage5SelectionError("selection schema mismatch")
    if selection.get("source_conflict_graph_digest") != conflict_graph.get(
        "conflict_graph_digest"
    ):
        raise Stage5SelectionError("selection/conflict graph mismatch")
    selected = selection.get("selected_candidates")
    if not isinstance(selected, list):
        raise Stage5SelectionError("selected candidate array is missing")
    if selection.get("feasible"):
        if len(selected) != selection.get("lane_count"):
            raise Stage5SelectionError(
                "feasible composition does not cover every lane"
            )
        lane_ids = [candidate["source_lane_id"] for candidate in selected]
        if len(set(lane_ids)) != len(lane_ids):
            raise Stage5SelectionError(
                "feasible composition selects a lane more than once"
            )
        if any(
            not candidate["intrinsic_diagnostics"]["valid"]
            for candidate in selected
        ):
            raise Stage5SelectionError(
                "feasible composition contains an invalid Unit"
            )
        selected_ids = {
            candidate["candidate_id"] for candidate in selected
        }
        for edge in conflict_graph["edges"]:
            if {
                edge["first_candidate_id"],
                edge["second_candidate_id"],
            } <= selected_ids:
                raise Stage5SelectionError(
                    "feasible composition contains a conflict edge"
                )
        if selection.get("schema") == SCHEMA_V2 and selection.get(
            "solver_trace", {}
        ).get("hierarchy_policy") in FIXED_L1_ONLY_POLICIES:
            for candidate in selected:
                hierarchy = candidate.get("hierarchy")
                curves = candidate.get("curves")
                if (
                    not isinstance(hierarchy, Mapping)
                    or hierarchy.get("l2_count") != 0
                    or hierarchy.get("l3_count") != 0
                    or not isinstance(curves, Sequence)
                    or not curves
                    or any(
                        not isinstance(curve, Mapping)
                        or curve.get("level") != "L1"
                        for curve in curves
                    )
                ):
                    raise Stage5SelectionError(
                        "fixed L1-only selection contains non-L1 hierarchy geometry"
                    )
        elif selection.get("schema") == SCHEMA_V2 and selection.get(
            "solver_trace", {}
        ).get("hierarchy_policy") in SPARSE_L2_POLICIES:
            for candidate in selected:
                if _candidate_5e_state(candidate) is None:
                    raise Stage5SelectionError(
                        "sparse 5E selection contains a non-eligible Unit"
                    )
                if candidate.get("hierarchy", {}).get("l3_count") != 0:
                    raise Stage5SelectionError(
                        "sparse 5E selection contains an L3 hierarchy"
                    )
            trace = selection.get("solver_trace", {})
            if int(trace.get("selected_l3_count", -1)) != 0:
                raise Stage5SelectionError(
                    "sparse 5E solver trace reports a non-zero L3 count"
                )
            if trace.get("hierarchy_policy") == JOINT_SPARSE_L2_H2B_POLICY:
                if int(trace.get("achieved_upgrade_count", -1)) > int(
                    trace.get("maximum_upgrade_lane_count", -1)
                ):
                    raise Stage5SelectionError(
                        "joint H2-B selection exceeds its sparse L2 budget"
                    )
                if trace.get("irreversible_lane_upgrade_order_used") is not False:
                    raise Stage5SelectionError(
                        "joint H2-B selection reports an irreversible upgrade order"
                    )
        elif selection.get("schema") == SCHEMA_V2:
            target_counts = selection.get("solver_trace", {}).get(
                "hierarchy_mix_target_counts"
            )
            actual_counts: dict[str, int] = defaultdict(int)
            for candidate in selected:
                actual_counts[
                    str(
                        candidate["visual_features"][
                            "hierarchy_density_class"
                        ]
                    )
                ] += 1
            if dict(actual_counts) != target_counts:
                raise Stage5SelectionError(
                    "V2 composition does not match its frozen hierarchy mix"
                )
    elif selected:
        raise Stage5SelectionError(
            "infeasible result must not publish a partial selection"
        )
