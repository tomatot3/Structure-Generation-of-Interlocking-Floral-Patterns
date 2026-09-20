#!/usr/bin/env python3
"""Strict, prototype-independent P0 input contract in repeat-local coordinates."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


SCHEMA = "dynamic_branch_strict_p0_v2"
POLICY_ID = "backbone_flowers_repeat_protection_only_v2"
PROTOTYPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ZONE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
Point = tuple[float, float]

CONSUMED_PROFILE_PATHS = (
    "prototype_id",
    "repeat_x_range",
    "canvas.width",
    "canvas.height",
    "backbone.arc_samples[*].s",
    "backbone.arc_samples[*].point",
    "backbone.arc_samples[*].tangent",
    "flowers[*].flower_id",
    "flowers[*].center",
    "flowers[*].rx",
    "flowers[*].ry",
    "structure_protection_zones[*]",
)

IGNORED_LEGACY_FIELDS = (
    "existing_guides",
    "growth_regions",
    "space_samples",
    "region_graph",
    "nodes",
    "segments",
    "qa",
    "attachments",
    "branch_roles",
    "clearance",
    "branches",
)


class InputContractError(ValueError):
    """Fatal StrictP0 input error; never downgraded to a geometry issue label."""

    def __init__(self, code: str, path: str, message: str):
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")

    def as_dict(self) -> dict[str, str]:
        return {
            "classification": "fatal_contract_error",
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InputContractError("invalid_schema", path, "must be an object")
    return value


def _sequence(value: Any, path: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise InputContractError("invalid_schema", path, "must be an array")
    return value


def _required(mapping: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise InputContractError("missing_required_field", f"{path}.{key}", "field is required")
    return mapping[key]


def _finite(value: Any, path: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InputContractError("invalid_coordinate", path, "must be numeric") from exc
    if not math.isfinite(result):
        raise InputContractError("non_finite_geometry", path, "must be finite")
    return result


def _positive(value: Any, path: str) -> float:
    result = _finite(value, path)
    if result <= 0.0:
        raise InputContractError("invalid_coordinate", path, "must be positive")
    return result


def _point(value: Any, path: str) -> Point:
    row = _sequence(value, path)
    if len(row) != 2:
        raise InputContractError("invalid_coordinate", path, "must contain exactly two coordinates")
    return _finite(row[0], f"{path}[0]"), _finite(row[1], f"{path}[1]")


def _unit(value: Any, path: str) -> Point:
    vector = _point(value, path)
    length = math.hypot(*vector)
    if length <= 1e-12:
        raise InputContractError("invalid_coordinate", path, "direction must be non-degenerate")
    return vector[0] / length, vector[1] / length


def _round_point(point: Point) -> list[float]:
    return [round(point[0], 12), round(point[1], 12)]


def _local_scalar(value: float) -> float:
    """Canonicalize repeat-local values so equivalent scaled inputs compare exactly."""

    # Nine decimals in normalized repeat space is finer than 3e-7 source pixels
    # for the current 256 px repeats, while avoiding binary half-round drift
    # after an equivalent source-space scale/translation.
    rounded = round(value, 9)
    return 0.0 if rounded == -0.0 else rounded


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RepeatLocalFrame:
    source_canvas_width: float
    source_canvas_height: float
    source_repeat_x_range: tuple[float, float]

    @property
    def repeat_width(self) -> float:
        return self.source_repeat_x_range[1] - self.source_repeat_x_range[0]

    @property
    def local_repeat_x_range(self) -> tuple[float, float]:
        return 0.0, 1.0

    @property
    def local_canvas_bounds(self) -> tuple[float, float, float, float]:
        x0, _ = self.source_repeat_x_range
        scale = self.repeat_width
        return (
            -x0 / scale,
            0.0,
            (self.source_canvas_width - x0) / scale,
            self.source_canvas_height / scale,
        )

    def to_local_point(self, point: Point) -> Point:
        x0, _ = self.source_repeat_x_range
        scale = self.repeat_width
        return (
            _local_scalar((point[0] - x0) / scale),
            _local_scalar(point[1] / scale),
        )

    def to_source_point(self, point: Point) -> Point:
        x0, _ = self.source_repeat_x_range
        scale = self.repeat_width
        return x0 + point[0] * scale, point[1] * scale

    def to_local_length(self, value: float) -> float:
        return _local_scalar(value / self.repeat_width)

    def to_source_length(self, value: float) -> float:
        return value * self.repeat_width

    def as_dict(self) -> dict[str, object]:
        return {
            "source": {
                "canvas": {
                    "width": round(self.source_canvas_width, 12),
                    "height": round(self.source_canvas_height, 12),
                },
                "repeat_x_range": [round(value, 12) for value in self.source_repeat_x_range],
            },
            "local": {
                "coordinate_system": "repeat_width_isotropic",
                "repeat_x_range": [0.0, 1.0],
                "canvas_bounds": [round(value, 12) for value in self.local_canvas_bounds],
                "source_units_per_local_unit": round(self.repeat_width, 12),
            },
        }


@dataclass(frozen=True)
class BackboneSample:
    s: float
    point: Point
    tangent: Point

    def as_dict(self) -> dict[str, object]:
        return {
            "s": round(self.s, 12),
            "point": _round_point(self.point),
            "tangent": _round_point(self.tangent),
        }


@dataclass(frozen=True)
class FlowerReserve:
    flower_id: str
    center: Point
    rx: float
    ry: float

    def as_dict(self) -> dict[str, object]:
        return {
            "flower_id": self.flower_id,
            "center": _round_point(self.center),
            "rx": round(self.rx, 12),
            "ry": round(self.ry, 12),
        }


@dataclass(frozen=True)
class ProtectionZone:
    zone_id: str
    role: str
    required: bool
    geometry_type: str
    center: Point | None = None
    rx: float | None = None
    ry: float | None = None
    points: tuple[Point, ...] = ()

    def as_dict(self) -> dict[str, object]:
        geometry: dict[str, object]
        if self.geometry_type == "ellipse":
            geometry = {
                "type": "ellipse",
                "center": _round_point(self.center or (0.0, 0.0)),
                "rx": round(float(self.rx), 12),
                "ry": round(float(self.ry), 12),
            }
        else:
            geometry = {
                "type": "polygon",
                "points": [_round_point(point) for point in self.points],
            }
        return {
            "zone_id": self.zone_id,
            "role": self.role,
            "required": self.required,
            "geometry": geometry,
        }


@dataclass(frozen=True)
class StrictP0V2:
    prototype_id: str
    frame: RepeatLocalFrame
    backbone_samples: tuple[BackboneSample, ...]
    flowers: tuple[FlowerReserve, ...]
    structure_protection_zones: tuple[ProtectionZone, ...]
    policy_id: str = POLICY_ID
    schema: str = SCHEMA

    @property
    def backbone_points(self) -> tuple[Point, ...]:
        return tuple(sample.point for sample in self.backbone_samples)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "policy_id": self.policy_id,
            "prototype_id": self.prototype_id,
            "frame": self.frame.as_dict(),
            "backbone": {
                "arc_samples": [sample.as_dict() for sample in self.backbone_samples],
            },
            "flowers": [flower.as_dict() for flower in self.flowers],
            "structure_protection_zones": [
                zone.as_dict() for zone in self.structure_protection_zones
            ],
            "input_contract": {
                "consumed_profile_paths": list(CONSUMED_PROFILE_PATHS),
                "ignored_legacy_fields": list(IGNORED_LEGACY_FIELDS),
                "fatal_errors_are_diagnostic_labels": False,
                "prototype_specific_topology_consumed": False,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.as_dict())


def _frame_from_profile(profile: Mapping[str, Any]) -> RepeatLocalFrame:
    canvas = _mapping(_required(profile, "canvas", "profile"), "profile.canvas")
    width = _positive(_required(canvas, "width", "profile.canvas"), "profile.canvas.width")
    height = _positive(_required(canvas, "height", "profile.canvas"), "profile.canvas.height")
    repeat = _sequence(
        _required(profile, "repeat_x_range", "profile"),
        "profile.repeat_x_range",
    )
    if len(repeat) != 2:
        raise InputContractError(
            "invalid_coordinate",
            "profile.repeat_x_range",
            "must contain exactly two values",
        )
    x0 = _finite(repeat[0], "profile.repeat_x_range[0]")
    x1 = _finite(repeat[1], "profile.repeat_x_range[1]")
    if not 0.0 <= x0 < x1 <= width:
        raise InputContractError(
            "invalid_coordinate",
            "profile.repeat_x_range",
            "must satisfy 0 <= start < end <= canvas width",
        )
    return RepeatLocalFrame(width, height, (x0, x1))


def _protection_zones(
    profile: Mapping[str, Any],
    frame: RepeatLocalFrame,
) -> tuple[ProtectionZone, ...]:
    raw_zones = profile.get("structure_protection_zones", [])
    rows = _sequence(raw_zones, "profile.structure_protection_zones")
    zones: list[ProtectionZone] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        path = f"profile.structure_protection_zones[{index}]"
        row = _mapping(raw, path)
        zone_id = str(_required(row, "zone_id", path))
        if not ZONE_ID_RE.fullmatch(zone_id):
            raise InputContractError("invalid_schema", f"{path}.zone_id", "invalid stable id")
        if zone_id in seen:
            raise InputContractError("invalid_schema", f"{path}.zone_id", "duplicate zone id")
        seen.add(zone_id)
        role = str(_required(row, "role", path)).strip()
        if not role:
            raise InputContractError("invalid_schema", f"{path}.role", "role must be non-empty")
        required = row.get("required", True)
        if not isinstance(required, bool):
            raise InputContractError("invalid_schema", f"{path}.required", "must be boolean")
        geometry = _mapping(_required(row, "geometry", path), f"{path}.geometry")
        geometry_type = str(_required(geometry, "type", f"{path}.geometry"))
        if geometry_type == "ellipse":
            center = frame.to_local_point(
                _point(_required(geometry, "center", f"{path}.geometry"), f"{path}.geometry.center")
            )
            rx = frame.to_local_length(
                _positive(_required(geometry, "rx", f"{path}.geometry"), f"{path}.geometry.rx")
            )
            ry = frame.to_local_length(
                _positive(_required(geometry, "ry", f"{path}.geometry"), f"{path}.geometry.ry")
            )
            zones.append(
                ProtectionZone(
                    zone_id=zone_id,
                    role=role,
                    required=required,
                    geometry_type="ellipse",
                    center=center,
                    rx=rx,
                    ry=ry,
                )
            )
        elif geometry_type == "polygon":
            raw_points = _sequence(
                _required(geometry, "points", f"{path}.geometry"),
                f"{path}.geometry.points",
            )
            if len(raw_points) < 3:
                raise InputContractError(
                    "invalid_schema",
                    f"{path}.geometry.points",
                    "polygon requires at least three points",
                )
            points = tuple(
                frame.to_local_point(_point(value, f"{path}.geometry.points[{point_index}]"))
                for point_index, value in enumerate(raw_points)
            )
            zones.append(
                ProtectionZone(
                    zone_id=zone_id,
                    role=role,
                    required=required,
                    geometry_type="polygon",
                    points=points,
                )
            )
        else:
            raise InputContractError(
                "invalid_schema",
                f"{path}.geometry.type",
                "must be ellipse or polygon",
            )
    return tuple(zones)


def load_strict_p0_v2(profile: Mapping[str, Any]) -> StrictP0V2:
    """Load only the StrictP0 v2 whitelist and ignore all legacy branch fields."""

    root = _mapping(profile, "profile")
    prototype_id = str(_required(root, "prototype_id", "profile"))
    if not PROTOTYPE_ID_RE.fullmatch(prototype_id):
        raise InputContractError("invalid_schema", "profile.prototype_id", "invalid prototype id")
    frame = _frame_from_profile(root)

    backbone = _mapping(_required(root, "backbone", "profile"), "profile.backbone")
    raw_samples = _sequence(
        _required(backbone, "arc_samples", "profile.backbone"),
        "profile.backbone.arc_samples",
    )
    if len(raw_samples) < 2:
        raise InputContractError(
            "invalid_schema",
            "profile.backbone.arc_samples",
            "requires at least two samples",
        )
    samples: list[BackboneSample] = []
    for index, raw in enumerate(raw_samples):
        path = f"profile.backbone.arc_samples[{index}]"
        row = _mapping(raw, path)
        s = _finite(_required(row, "s", path), f"{path}.s")
        if not 0.0 <= s <= 1.0:
            raise InputContractError("invalid_coordinate", f"{path}.s", "must lie in [0, 1]")
        samples.append(
            BackboneSample(
                s=s,
                point=frame.to_local_point(
                    _point(_required(row, "point", path), f"{path}.point")
                ),
                tangent=_unit(_required(row, "tangent", path), f"{path}.tangent"),
            )
        )
    if any(second.s <= first.s for first, second in zip(samples, samples[1:])):
        raise InputContractError(
            "invalid_schema",
            "profile.backbone.arc_samples[*].s",
            "sample fractions must be strictly increasing",
        )
    if abs(samples[0].s) > 1e-9 or abs(samples[-1].s - 1.0) > 1e-9:
        raise InputContractError(
            "invalid_schema",
            "profile.backbone.arc_samples[*].s",
            "samples must include s=0 and s=1 endpoints",
        )

    raw_flowers = _sequence(_required(root, "flowers", "profile"), "profile.flowers")
    if not raw_flowers:
        raise InputContractError(
            "missing_required_field",
            "profile.flowers",
            "one or more flower reserves are required",
        )
    flowers: list[FlowerReserve] = []
    seen_flowers: set[str] = set()
    for index, raw in enumerate(raw_flowers):
        path = f"profile.flowers[{index}]"
        row = _mapping(raw, path)
        flower_id = str(_required(row, "flower_id", path))
        if not ZONE_ID_RE.fullmatch(flower_id):
            raise InputContractError("invalid_schema", f"{path}.flower_id", "invalid stable id")
        if flower_id in seen_flowers:
            raise InputContractError("invalid_schema", f"{path}.flower_id", "duplicate flower id")
        seen_flowers.add(flower_id)
        flowers.append(
            FlowerReserve(
                flower_id=flower_id,
                center=frame.to_local_point(
                    _point(_required(row, "center", path), f"{path}.center")
                ),
                rx=frame.to_local_length(
                    _positive(_required(row, "rx", path), f"{path}.rx")
                ),
                ry=frame.to_local_length(
                    _positive(_required(row, "ry", path), f"{path}.ry")
                ),
            )
        )

    zones = _protection_zones(root, frame)
    overlap = seen_flowers.intersection(zone.zone_id for zone in zones)
    if overlap:
        raise InputContractError(
            "invalid_schema",
            "profile.structure_protection_zones[*].zone_id",
            f"zone ids collide with flower ids: {sorted(overlap)}",
        )
    return StrictP0V2(
        prototype_id=prototype_id,
        frame=frame,
        backbone_samples=tuple(samples),
        flowers=tuple(flowers),
        structure_protection_zones=zones,
    )


def load_materialized_strict_p0_v2(payload: Mapping[str, Any]) -> StrictP0V2:
    """Validate and load a canonical stage-1 StrictP0 artifact."""

    root = _mapping(payload, "strict_p0")
    if _required(root, "schema", "strict_p0") != SCHEMA:
        raise InputContractError(
            "invalid_schema",
            "strict_p0.schema",
            f"must equal {SCHEMA}",
        )
    if _required(root, "policy_id", "strict_p0") != POLICY_ID:
        raise InputContractError(
            "invalid_schema",
            "strict_p0.policy_id",
            f"must equal {POLICY_ID}",
        )
    frame_payload = _mapping(
        _required(root, "frame", "strict_p0"),
        "strict_p0.frame",
    )
    source = _mapping(
        _required(frame_payload, "source", "strict_p0.frame"),
        "strict_p0.frame.source",
    )
    canvas = _mapping(
        _required(source, "canvas", "strict_p0.frame.source"),
        "strict_p0.frame.source.canvas",
    )
    repeat_values = _sequence(
        _required(source, "repeat_x_range", "strict_p0.frame.source"),
        "strict_p0.frame.source.repeat_x_range",
    )
    if len(repeat_values) != 2:
        raise InputContractError(
            "invalid_coordinate",
            "strict_p0.frame.source.repeat_x_range",
            "must contain exactly two values",
        )
    frame = RepeatLocalFrame(
        source_canvas_width=_positive(
            _required(canvas, "width", "strict_p0.frame.source.canvas"),
            "strict_p0.frame.source.canvas.width",
        ),
        source_canvas_height=_positive(
            _required(canvas, "height", "strict_p0.frame.source.canvas"),
            "strict_p0.frame.source.canvas.height",
        ),
        source_repeat_x_range=(
            _finite(repeat_values[0], "strict_p0.frame.source.repeat_x_range[0]"),
            _finite(repeat_values[1], "strict_p0.frame.source.repeat_x_range[1]"),
        ),
    )
    if not (
        0.0
        <= frame.source_repeat_x_range[0]
        < frame.source_repeat_x_range[1]
        <= frame.source_canvas_width
    ):
        raise InputContractError(
            "invalid_coordinate",
            "strict_p0.frame.source.repeat_x_range",
            "must satisfy 0 <= start < end <= canvas width",
        )
    if frame.as_dict() != dict(frame_payload):
        raise InputContractError(
            "invalid_schema",
            "strict_p0.frame",
            "source and declared local frame do not agree",
        )
    prototype_id = str(_required(root, "prototype_id", "strict_p0"))
    if not PROTOTYPE_ID_RE.fullmatch(prototype_id):
        raise InputContractError(
            "invalid_schema",
            "strict_p0.prototype_id",
            "invalid prototype id",
        )
    backbone = _mapping(
        _required(root, "backbone", "strict_p0"),
        "strict_p0.backbone",
    )
    arc_samples = _sequence(
        _required(backbone, "arc_samples", "strict_p0.backbone"),
        "strict_p0.backbone.arc_samples",
    )
    if len(arc_samples) < 2:
        raise InputContractError(
            "invalid_schema",
            "strict_p0.backbone.arc_samples",
            "requires at least two samples",
        )
    samples: list[BackboneSample] = []
    for index, raw in enumerate(arc_samples):
        path = f"strict_p0.backbone.arc_samples[{index}]"
        row = _mapping(raw, path)
        s = _finite(_required(row, "s", path), f"{path}.s")
        if not 0.0 <= s <= 1.0:
            raise InputContractError(
                "invalid_coordinate",
                f"{path}.s",
                "must lie in [0, 1]",
            )
        point = _point(_required(row, "point", path), f"{path}.point")
        tangent = _point(_required(row, "tangent", path), f"{path}.tangent")
        tangent_length = math.hypot(*tangent)
        if abs(tangent_length - 1.0) > 1e-6:
            raise InputContractError(
                "invalid_coordinate",
                f"{path}.tangent",
                "must be unit length",
            )
        samples.append(
            BackboneSample(
                s=s,
                point=(_local_scalar(point[0]), _local_scalar(point[1])),
                tangent=tangent,
            )
        )
    if any(second.s <= first.s for first, second in zip(samples, samples[1:])):
        raise InputContractError(
            "invalid_schema",
            "strict_p0.backbone.arc_samples[*].s",
            "sample fractions must be strictly increasing",
        )
    if abs(samples[0].s) > 1e-9 or abs(samples[-1].s - 1.0) > 1e-9:
        raise InputContractError(
            "invalid_schema",
            "strict_p0.backbone.arc_samples[*].s",
            "samples must include s=0 and s=1 endpoints",
        )
    raw_flowers = _sequence(
        _required(root, "flowers", "strict_p0"),
        "strict_p0.flowers",
    )
    if not raw_flowers:
        raise InputContractError(
            "missing_required_field",
            "strict_p0.flowers",
            "one or more flower reserves are required",
        )
    flowers: list[FlowerReserve] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_flowers):
        path = f"strict_p0.flowers[{index}]"
        row = _mapping(raw, path)
        flower_id = str(_required(row, "flower_id", path))
        if not ZONE_ID_RE.fullmatch(flower_id) or flower_id in seen_ids:
            raise InputContractError(
                "invalid_schema",
                f"{path}.flower_id",
                "must be a unique stable id",
            )
        seen_ids.add(flower_id)
        center = _point(_required(row, "center", path), f"{path}.center")
        flowers.append(
            FlowerReserve(
                flower_id=flower_id,
                center=(_local_scalar(center[0]), _local_scalar(center[1])),
                rx=_local_scalar(_positive(_required(row, "rx", path), f"{path}.rx")),
                ry=_local_scalar(_positive(_required(row, "ry", path), f"{path}.ry")),
            )
        )
    raw_zones = _sequence(
        root.get("structure_protection_zones", []),
        "strict_p0.structure_protection_zones",
    )
    zones: list[ProtectionZone] = []
    for index, raw in enumerate(raw_zones):
        path = f"strict_p0.structure_protection_zones[{index}]"
        row = _mapping(raw, path)
        zone_id = str(_required(row, "zone_id", path))
        if not ZONE_ID_RE.fullmatch(zone_id) or zone_id in seen_ids:
            raise InputContractError(
                "invalid_schema",
                f"{path}.zone_id",
                "must be a unique stable id",
            )
        seen_ids.add(zone_id)
        role = str(_required(row, "role", path)).strip()
        if not role:
            raise InputContractError(
                "invalid_schema",
                f"{path}.role",
                "role must be non-empty",
            )
        required = row.get("required", True)
        if not isinstance(required, bool):
            raise InputContractError(
                "invalid_schema",
                f"{path}.required",
                "must be boolean",
            )
        geometry = _mapping(
            _required(row, "geometry", path),
            f"{path}.geometry",
        )
        geometry_type = str(
            _required(geometry, "type", f"{path}.geometry")
        )
        if geometry_type == "ellipse":
            center = _point(
                _required(geometry, "center", f"{path}.geometry"),
                f"{path}.geometry.center",
            )
            zones.append(
                ProtectionZone(
                    zone_id=zone_id,
                    role=role,
                    required=required,
                    geometry_type="ellipse",
                    center=(_local_scalar(center[0]), _local_scalar(center[1])),
                    rx=_local_scalar(
                        _positive(
                            _required(geometry, "rx", f"{path}.geometry"),
                            f"{path}.geometry.rx",
                        )
                    ),
                    ry=_local_scalar(
                        _positive(
                            _required(geometry, "ry", f"{path}.geometry"),
                            f"{path}.geometry.ry",
                        )
                    ),
                )
            )
        elif geometry_type == "polygon":
            points = _sequence(
                _required(geometry, "points", f"{path}.geometry"),
                f"{path}.geometry.points",
            )
            if len(points) < 3:
                raise InputContractError(
                    "invalid_schema",
                    f"{path}.geometry.points",
                    "polygon requires at least three points",
                )
            zones.append(
                ProtectionZone(
                    zone_id=zone_id,
                    role=role,
                    required=required,
                    geometry_type="polygon",
                    points=tuple(
                        (
                            _local_scalar(parsed[0]),
                            _local_scalar(parsed[1]),
                        )
                        for parsed in (
                            _point(
                                point,
                                f"{path}.geometry.points[{point_index}]",
                            )
                            for point_index, point in enumerate(points)
                        )
                    ),
                )
            )
        else:
            raise InputContractError(
                "invalid_schema",
                f"{path}.geometry.type",
                "must be ellipse or polygon",
            )
    strict = StrictP0V2(
        prototype_id=prototype_id,
        frame=frame,
        backbone_samples=tuple(samples),
        flowers=tuple(flowers),
        structure_protection_zones=tuple(zones),
    )
    if strict.as_dict() != dict(root):
        raise InputContractError(
            "invalid_schema",
            "strict_p0",
            "materialized artifact is not canonical StrictP0 v2",
        )
    return strict


def poison_ignored_fields(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy with every legacy branch-derived field deliberately corrupted."""

    encoded = json.dumps(profile, ensure_ascii=False)
    poisoned = json.loads(encoded)
    poison = {
        "must_not_be_read": True,
        "coordinates": [999999999.0, -999999999.0],
        "prototype_specific_topology": "forbidden",
    }
    for key in IGNORED_LEGACY_FIELDS:
        poisoned[key] = poison
    poisoned_backbone = dict(poisoned["backbone"])
    poisoned_backbone["source_path_order"] = [999999, -999999]
    poisoned_backbone["legacy_growth_hint"] = poison
    poisoned["backbone"] = poisoned_backbone
    return poisoned
