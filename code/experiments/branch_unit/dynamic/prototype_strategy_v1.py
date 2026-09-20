#!/usr/bin/env python3
"""Compile and route immutable prototype-domain generation strategies."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


REGISTRY_SCHEMA = "dynamic_branch_prototype_strategy_registry_v1"
PROJECTION_SCHEMA = "dynamic_branch_prototype_strategy_projection_v1"
DEFAULT_REGISTRY_PATH = Path(__file__).with_name(
    "PROTOTYPE_STRATEGY_REGISTRY_V1.json"
)
REQUIRED_POLICY_KEYS = (
    "backbone_domain",
    "flower_layout",
    "flower_mount",
    "l1_profile",
    "branchunit_profile",
    "global_selection_profile",
)


class PrototypeStrategyError(RuntimeError):
    """A prototype request or frozen domain strategy is invalid."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            f"cannot read prototype strategy registry: {path}",
        ) from exc
    if not isinstance(value, dict):
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            "prototype strategy registry root must be an object",
        )
    return value


def load_prototype_strategy_registry(
    path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    registry = _read_json(path)
    if registry.get("schema") != REGISTRY_SCHEMA:
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            "prototype strategy registry schema mismatch",
        )
    order = registry.get("prototype_order")
    strategies = registry.get("strategies")
    if (
        not isinstance(order, list)
        or not isinstance(strategies, Mapping)
        or list(strategies) != order
        or len(set(order)) != len(order)
    ):
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            "prototype order and strategy inventory do not match",
        )
    strategy_ids: set[str] = set()
    signatures: set[tuple[str, int, str]] = set()
    for prototype_id in order:
        row = strategies.get(prototype_id)
        if not isinstance(row, Mapping):
            raise PrototypeStrategyError(
                "strategy_registry_invalid",
                f"strategy is missing for {prototype_id}",
            )
        _validate_registry_strategy(row, prototype_id)
        strategy_id = str(row["strategy_id"])
        signature = row["route_signature"]
        route_key = (
            str(signature["flower_relation"]),
            int(signature["flower_count"]),
            str(signature["style_intent"]),
        )
        if strategy_id in strategy_ids or route_key in signatures:
            raise PrototypeStrategyError(
                "strategy_registry_invalid",
                "strategy ids and complete route signatures must be unique",
            )
        strategy_ids.add(strategy_id)
        signatures.add(route_key)
    return registry


def _validate_registry_strategy(
    strategy: Mapping[str, Any],
    registry_key: str,
) -> None:
    if str(strategy.get("prototype_id")) != registry_key:
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            f"strategy key/identity mismatch for {registry_key}",
        )
    if not str(strategy.get("strategy_id", "")):
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            f"strategy id is missing for {registry_key}",
        )
    if not str(strategy.get("family_id", "")):
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            f"family id is missing for {registry_key}",
        )
    signature = strategy.get("route_signature")
    invariants = strategy.get("invariants")
    if not isinstance(signature, Mapping) or not isinstance(invariants, Mapping):
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            f"route signature or invariants are missing for {registry_key}",
        )
    flower_count = signature.get("flower_count")
    if (
        isinstance(flower_count, bool)
        or not isinstance(flower_count, int)
        or flower_count < 0
        or invariants.get("flower_count") != flower_count
    ):
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            f"flower-count invariant is invalid for {registry_key}",
        )
    if not all(isinstance(strategy.get(key), Mapping) for key in REQUIRED_POLICY_KEYS):
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            f"one or more policy blocks are missing for {registry_key}",
        )
    flower_layout = strategy["flower_layout"]
    mode = str(flower_layout.get("mode", ""))
    family_id = str(strategy["family_id"])
    if family_id == "SW-3_tangent_terminal":
        expected_mode = (
            "sw3_single_joint_domain"
            if flower_count == 1
            else "sw3_pair_joint_domain"
        )
        if mode != expected_mode:
            raise PrototypeStrategyError(
                "strategy_registry_invalid",
                f"SW-3 flower layout mode mismatch for {registry_key}",
            )
    elif mode != "fixed_prototype_relation":
        raise PrototypeStrategyError(
            "strategy_registry_invalid",
            f"non-SW-3 flower layout must remain fixed for {registry_key}",
        )


def prototype_ids(registry: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(value) for value in registry["prototype_order"])


def compile_prototype_strategy(
    registry: Mapping[str, Any],
    prototype_id: str,
) -> dict[str, Any]:
    rows = registry.get("strategies")
    row = rows.get(prototype_id) if isinstance(rows, Mapping) else None
    if not isinstance(row, Mapping):
        raise PrototypeStrategyError(
            "unknown_prototype",
            f"prototype has no registered strategy: {prototype_id}",
        )
    projection = copy.deepcopy(dict(row))
    projection["schema"] = PROJECTION_SCHEMA
    projection["registry_id"] = str(registry["registry_id"])
    validate_strategy_projection(projection)
    return projection


def resolve_prototype_strategy(
    request: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise PrototypeStrategyError(
            "route_no_match",
            "prototype route request must be an object",
        )
    explicit = request.get("prototype_id")
    if explicit is not None:
        strategy = compile_prototype_strategy(registry, str(explicit))
        signature = strategy["route_signature"]
        contradictions = [
            key
            for key in ("flower_relation", "flower_count", "style_intent")
            if key in request and request[key] != signature[key]
        ]
        if contradictions:
            raise PrototypeStrategyError(
                "explicit_prototype_conflict",
                f"explicit prototype contradicts route fields: {', '.join(contradictions)}",
            )
        return strategy

    if not request.get("flower_relation"):
        raise PrototypeStrategyError(
            "route_relation_missing",
            "semantic routing requires flower_relation",
        )
    count = request.get("flower_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise PrototypeStrategyError(
            "route_flower_count_missing",
            "semantic routing requires a non-negative integer flower_count",
        )
    candidates: list[str] = []
    for prototype_id in prototype_ids(registry):
        signature = registry["strategies"][prototype_id]["route_signature"]
        if signature["flower_relation"] != request["flower_relation"]:
            continue
        if signature["flower_count"] != count:
            continue
        if (
            request.get("style_intent") is not None
            and signature["style_intent"] != request["style_intent"]
        ):
            continue
        candidates.append(prototype_id)
    if not candidates:
        raise PrototypeStrategyError(
            "route_no_match",
            "no prototype strategy matches the semantic route request",
        )
    if len(candidates) > 1:
        raise PrototypeStrategyError(
            "route_ambiguous",
            "semantic route matches multiple prototypes; provide style_intent: "
            + ", ".join(candidates),
        )
    return compile_prototype_strategy(registry, candidates[0])


def validate_route_request_against_strategy(
    request: Mapping[str, Any],
    strategy: Mapping[str, Any],
) -> None:
    """Recheck a route request against the frozen strategy at a stage boundary."""

    validate_strategy_projection(strategy)
    if request.get("prototype_id") is not None and request["prototype_id"] != strategy[
        "prototype_id"
    ]:
        raise PrototypeStrategyError(
            "explicit_prototype_conflict",
            "route request does not name the frozen prototype strategy",
        )
    signature = strategy["route_signature"]
    contradictions = [
        key
        for key in ("flower_relation", "flower_count", "style_intent")
        if key in request and request[key] != signature[key]
    ]
    if contradictions:
        raise PrototypeStrategyError(
            "explicit_prototype_conflict",
            "route request contradicts frozen strategy fields: "
            + ", ".join(contradictions),
        )


def parse_route_request(value: str) -> dict[str, Any]:
    candidate = Path(value)
    if candidate.is_file():
        return _read_json(candidate)
    try:
        request = json.loads(value)
    except json.JSONDecodeError as exc:
        raise PrototypeStrategyError(
            "route_request_invalid_json",
            "route request must be a JSON object or a JSON file path",
        ) from exc
    if not isinstance(request, dict):
        raise PrototypeStrategyError(
            "route_request_invalid_json",
            "route request JSON root must be an object",
        )
    return request


def validate_strategy_projection(
    strategy: Mapping[str, Any],
    *,
    prototype_id: str | None = None,
    family_id: str | None = None,
    flower_count: int | None = None,
) -> None:
    if not isinstance(strategy, Mapping) or strategy.get("schema") != PROJECTION_SCHEMA:
        raise PrototypeStrategyError(
            "strategy_morphology_mismatch",
            "frozen prototype strategy projection is missing or malformed",
        )
    _validate_registry_strategy(strategy, str(strategy.get("prototype_id")))
    if prototype_id is not None and strategy.get("prototype_id") != prototype_id:
        raise PrototypeStrategyError(
            "strategy_morphology_mismatch",
            "strategy/prototype identity mismatch",
        )
    if family_id is not None and strategy.get("family_id") != family_id:
        raise PrototypeStrategyError(
            "strategy_morphology_mismatch",
            "strategy/morphology family mismatch",
        )
    if flower_count is not None and strategy["invariants"]["flower_count"] != flower_count:
        raise PrototypeStrategyError(
            "strategy_input_flower_count_mismatch",
            "strategy flower-count invariant does not match the active input",
        )


def validate_strategy_against_inputs(
    strategy: Mapping[str, Any],
    strict_p0: Mapping[str, Any] | Any,
    analysis: Mapping[str, Any],
    morphology: Mapping[str, Any],
) -> None:
    prototype_id = str(
        strict_p0.get("prototype_id")
        if isinstance(strict_p0, Mapping)
        else strict_p0.prototype_id
    )
    strict_flowers: Sequence[Any] = (
        strict_p0.get("flowers", ())
        if isinstance(strict_p0, Mapping)
        else strict_p0.flowers
    )
    analysis_flowers = analysis.get("flowers")
    family_id = morphology.get("classification", {}).get(
        "flower_branch_relation", {}
    ).get("family_id")
    validate_strategy_projection(
        strategy,
        prototype_id=prototype_id,
        family_id=str(family_id),
        flower_count=len(strict_flowers),
    )
    if analysis.get("prototype_id") != prototype_id:
        raise PrototypeStrategyError(
            "strategy_morphology_mismatch",
            "strategy input analysis has a different prototype identity",
        )
    if not isinstance(analysis_flowers, Sequence) or len(analysis_flowers) != len(strict_flowers):
        raise PrototypeStrategyError(
            "strategy_input_flower_count_mismatch",
            "strategy input analysis has a different flower inventory",
        )
    instance = morphology.get("instance_priors", {})
    signature = strategy["route_signature"]
    if instance.get("density_class") != signature["style_intent"]:
        raise PrototypeStrategyError(
            "strategy_morphology_mismatch",
            "strategy style intent does not match the morphology profile",
        )


DEFAULT_REGISTRY = load_prototype_strategy_registry()
PROTOTYPE_IDS = prototype_ids(DEFAULT_REGISTRY)

MATERIALIZED_PROTOTYPE_IDS = tuple(p for p in PROTOTYPE_IDS if "input_derivation" not in DEFAULT_REGISTRY["strategies"][p])
