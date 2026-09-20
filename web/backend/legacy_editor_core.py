"""Geometry and validation adapted from the original direct_branch editor.

The curve, attachment, propagation and constraint operations are retained.
Web sessions use an explicit source snapshot and direct geometry comparisons.
"""
from __future__ import annotations
import copy,html,json,math,re
from typing import Any,Iterable,Mapping,MutableMapping,Sequence
SCHEMA="direct_branch_rule_editor_session_v1"
POINT_NAMES=("p0","p1","p2","p3")
ROOT_DISTANCE_TOLERANCE=1.0
MOUNT_FRACTION_TOLERANCE=0.006
MAX_MOUNT_FRACTION=0.995
MAX_BRANCHES=200
MAX_REGION_POINTS=1024
def load_source(seed):
    raise EditorValidationError("Provide the stored source snapshot.")
class EditorError(RuntimeError):
    """Base editor error."""

class EditorValidationError(EditorError):
    """Raised when browser or stored session data is invalid."""

def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EditorError(f"无法读取固定输入 {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EditorError(f"固定输入不是 JSON 对象: {path}")
    return value

def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )

def _point(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise EditorValidationError(f"{label} 必须是二维坐标")
    try:
        point = [float(value[0]), float(value[1])]
    except (TypeError, ValueError) as exc:
        raise EditorValidationError(f"{label} 含有非数值坐标") from exc
    if not all(math.isfinite(item) for item in point):
        raise EditorValidationError(f"{label} 含有非有限坐标")
    return point

def _cubics(value: Any, label: str) -> list[dict[str, list[float]]]:
    if not isinstance(value, list) or len(value) not in (1, 2):
        raise EditorValidationError(f"{label} 必须包含一段或两段 cubic")
    result: list[dict[str, list[float]]] = []
    for segment_index, segment in enumerate(value):
        if not isinstance(segment, dict) or set(segment) != set(POINT_NAMES):
            raise EditorValidationError(f"{label}[{segment_index}] 字段必须为 p0/p1/p2/p3")
        result.append(
            {
                name: _point(segment[name], f"{label}[{segment_index}].{name}")
                for name in POINT_NAMES
            }
        )
    for index in range(len(result) - 1):
        if _distance(result[index]["p3"], result[index + 1]["p0"]) > 1e-6:
            raise EditorValidationError(f"{label} 的两段 cubic 连接点不一致")
    return result

def cubic_point(cubic: Mapping[str, Sequence[float]], t: float) -> list[float]:
    t = min(1.0, max(0.0, float(t)))
    one = 1.0 - t
    weights = (one**3, 3.0 * one * one * t, 3.0 * one * t * t, t**3)
    return [
        sum(weights[index] * float(cubic[name][axis]) for index, name in enumerate(POINT_NAMES))
        for axis in (0, 1)
    ]

def sample_cubic(cubic: Mapping[str, Sequence[float]], samples: int = 64) -> list[list[float]]:
    if samples < 2:
        raise ValueError("samples 必须至少为 2")
    return [cubic_point(cubic, index / samples) for index in range(samples + 1)]

def sample_cubics(cubics: Sequence[Mapping[str, Sequence[float]]], samples: int = 64) -> list[list[float]]:
    points: list[list[float]] = []
    for cubic in cubics:
        sampled = sample_cubic(cubic, samples)
        points.extend(sampled if not points else sampled[1:])
    return points

def _distance(first: Sequence[float], second: Sequence[float]) -> float:
    return math.hypot(float(first[0]) - float(second[0]), float(first[1]) - float(second[1]))

def _normalize(vector: Sequence[float]) -> list[float]:
    length = math.hypot(float(vector[0]), float(vector[1]))
    if length <= 1e-12:
        return [1.0, 0.0]
    return [float(vector[0]) / length, float(vector[1]) / length]

def project_point_to_polyline(
    point: Sequence[float], polyline: Sequence[Sequence[float]]
) -> dict[str, Any]:
    """Return the closest point, arc fraction, tangent, normal, and distance."""

    if len(polyline) < 2:
        raise EditorValidationError("父枝采样点不足")
    target = _point(point, "projection.point")
    lengths = [_distance(polyline[index], polyline[index + 1]) for index in range(len(polyline) - 1)]
    total = sum(lengths)
    if total <= 1e-12:
        raise EditorValidationError("父枝长度为零")

    best: dict[str, Any] | None = None
    traversed = 0.0
    for index, segment_length in enumerate(lengths):
        start = polyline[index]
        end = polyline[index + 1]
        dx = float(end[0]) - float(start[0])
        dy = float(end[1]) - float(start[1])
        if segment_length <= 1e-12:
            traversed += segment_length
            continue
        raw = ((target[0] - float(start[0])) * dx + (target[1] - float(start[1])) * dy) / (
            segment_length * segment_length
        )
        local = min(1.0, max(0.0, raw))
        closest = [float(start[0]) + local * dx, float(start[1]) + local * dy]
        distance = _distance(target, closest)
        if best is None or distance < best["distance"]:
            tangent = [dx / segment_length, dy / segment_length]
            best = {
                "point": closest,
                "arc_length": traversed + local * segment_length,
                "fraction": (traversed + local * segment_length) / total,
                "tangent": tangent,
                "normal": [-tangent[1], tangent[0]],
                "distance": distance,
            }
        traversed += segment_length
    if best is None:
        raise EditorValidationError("父枝没有有效线段")
    return best

def frame_at_fraction(polyline: Sequence[Sequence[float]], fraction: float) -> dict[str, Any]:
    if len(polyline) < 2:
        raise EditorValidationError("父枝采样点不足")
    fraction = min(1.0, max(0.0, float(fraction)))
    lengths = [_distance(polyline[index], polyline[index + 1]) for index in range(len(polyline) - 1)]
    total = sum(lengths)
    if total <= 1e-12:
        raise EditorValidationError("父枝长度为零")
    target = fraction * total
    traversed = 0.0
    for index, segment_length in enumerate(lengths):
        if segment_length <= 1e-12:
            continue
        if traversed + segment_length >= target or index == len(lengths) - 1:
            local = min(1.0, max(0.0, (target - traversed) / segment_length))
            start = polyline[index]
            end = polyline[index + 1]
            tangent = _normalize([float(end[0]) - float(start[0]), float(end[1]) - float(start[1])])
            return {
                "point": [
                    float(start[0]) + local * (float(end[0]) - float(start[0])),
                    float(start[1]) + local * (float(end[1]) - float(start[1])),
                ],
                "tangent": tangent,
                "normal": [-tangent[1], tangent[0]],
                "fraction": fraction,
            }
        traversed += segment_length
    raise EditorValidationError("无法计算父枝局部框架")

def local_coordinates(point: Sequence[float], frame: Mapping[str, Sequence[float]]) -> list[float]:
    dx = float(point[0]) - float(frame["point"][0])
    dy = float(point[1]) - float(frame["point"][1])
    return [
        dx * float(frame["tangent"][0]) + dy * float(frame["tangent"][1]),
        dx * float(frame["normal"][0]) + dy * float(frame["normal"][1]),
    ]

def from_local_coordinates(local: Sequence[float], frame: Mapping[str, Sequence[float]]) -> list[float]:
    return [
        float(frame["point"][0])
        + float(local[0]) * float(frame["tangent"][0])
        + float(local[1]) * float(frame["normal"][0]),
        float(frame["point"][1])
        + float(local[0]) * float(frame["tangent"][1])
        + float(local[1]) * float(frame["normal"][1]),
    ]

def transform_cubics_between_frames(
    cubics: Sequence[Mapping[str, Sequence[float]]],
    old_frame: Mapping[str, Sequence[float]],
    new_frame: Mapping[str, Sequence[float]],
) -> list[dict[str, list[float]]]:
    return [
        {
            name: from_local_coordinates(local_coordinates(cubic[name], old_frame), new_frame)
            for name in POINT_NAMES
        }
        for cubic in cubics
    ]

def propagate_descendants(
    branches: MutableMapping[str, dict[str, Any]],
    changed_parent_id: str,
    old_parent_points: Sequence[Sequence[float]],
    new_parent_points: Sequence[Sequence[float]],
) -> None:
    """Rigidly remap every descendant through its parent's old/new local frame."""

    children = sorted(
        (branch for branch in branches.values() if branch["parent_id"] == changed_parent_id),
        key=lambda branch: (int(branch["level"]), str(branch["curve_id"])),
    )
    for child in children:
        fraction = float(child["mount_fraction"])
        old_frame = frame_at_fraction(old_parent_points, fraction)
        new_frame = frame_at_fraction(new_parent_points, fraction)
        old_cubics = copy.deepcopy(child["edited_cubics"])
        new_cubics = transform_cubics_between_frames(old_cubics, old_frame, new_frame)
        child["edited_cubics"] = new_cubics
        propagate_descendants(
            branches,
            str(child["curve_id"]),
            sample_cubics(old_cubics, 96),
            sample_cubics(new_cubics, 96),
        )

def _validate_parent_graph(branches: Sequence[Mapping[str, Any]]) -> None:
    by_id = {str(branch["curve_id"]): branch for branch in branches}
    if len(by_id) != len(branches):
        raise EditorValidationError("分支 ID 不唯一")
    for branch in branches:
        curve_id = str(branch["curve_id"])
        parent_id = str(branch["parent_id"])
        level = int(branch["level"])
        if parent_id == "backbone":
            if level != 1:
                raise EditorValidationError(f"{curve_id} 挂载主干但层级不是 L1")
        else:
            parent = by_id.get(parent_id)
            if parent is None:
                raise EditorValidationError(f"{curve_id} 引用不存在父枝 {parent_id}")
            if int(parent["level"]) + 1 != level:
                raise EditorValidationError(f"{curve_id} 与父枝层级不连续")

    for curve_id in by_id:
        visited: set[str] = set()
        current = curve_id
        while current != "backbone":
            if current in visited:
                raise EditorValidationError(f"父子拓扑存在环: {curve_id}")
            visited.add(current)
            current = str(by_id[current]["parent_id"])

def _polygon(value: Any, label: str) -> list[list[float]]:
    if not isinstance(value, list) or not 3 <= len(value) <= MAX_REGION_POINTS:
        raise EditorValidationError(f"{label} 必须包含 3 到 {MAX_REGION_POINTS} 个点")
    return [_point(point, f"{label}[{index}]") for index, point in enumerate(value)]

def _orientation(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> float:
    return (float(b[0]) - float(a[0])) * (float(c[1]) - float(a[1])) - (
        float(b[1]) - float(a[1])
    ) * (float(c[0]) - float(a[0]))

def _segments_intersect(
    a: Sequence[float], b: Sequence[float], c: Sequence[float], d: Sequence[float]
) -> bool:
    first = _orientation(a, b, c)
    second = _orientation(a, b, d)
    third = _orientation(c, d, a)
    fourth = _orientation(c, d, b)
    epsilon = 1e-8
    if (
        (first > epsilon and second < -epsilon or first < -epsilon and second > epsilon)
        and (third > epsilon and fourth < -epsilon or third < -epsilon and fourth > epsilon)
    ):
        return True
    def on_segment(start: Sequence[float], point: Sequence[float], end: Sequence[float]) -> bool:
        return (
            min(float(start[0]), float(end[0])) - epsilon <= float(point[0]) <= max(float(start[0]), float(end[0])) + epsilon
            and min(float(start[1]), float(end[1])) - epsilon <= float(point[1]) <= max(float(start[1]), float(end[1])) + epsilon
        )
    return (
        abs(first) <= epsilon and on_segment(a, c, b)
        or abs(second) <= epsilon and on_segment(a, d, b)
        or abs(third) <= epsilon and on_segment(c, a, d)
        or abs(fourth) <= epsilon and on_segment(c, b, d)
    )

def _polylines_intersect(
    first: Sequence[Sequence[float]], second: Sequence[Sequence[float]]
) -> bool:
    for first_index in range(len(first) - 1):
        for second_index in range(len(second) - 1):
            if _segments_intersect(
                first[first_index],
                first[first_index + 1],
                second[second_index],
                second[second_index + 1],
            ):
                return True
    return False

def _polyline_length(points: Sequence[Sequence[float]]) -> float:
    return sum(_distance(points[index], points[index + 1]) for index in range(len(points) - 1))

def _normalized_sagitta(points: Sequence[Sequence[float]]) -> float:
    if len(points) < 2:
        return 0.0
    start, end = points[0], points[-1]
    chord = _distance(start, end)
    if chord <= 1e-9:
        return 0.0
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    maximum = max(
        abs(dx * (float(start[1]) - float(point[1])) - (float(start[0]) - float(point[0])) * dy)
        / chord
        for point in points
    )
    return maximum / chord

def _angle_degrees(start: Sequence[float], end: Sequence[float]) -> float:
    return math.degrees(math.atan2(float(end[1]) - float(start[1]), float(end[0]) - float(start[0])))

def _envelope_analysis(
    preferred: Sequence[Mapping[str, Sequence[float]]],
    boundary_a: Sequence[Mapping[str, Sequence[float]]],
    boundary_b: Sequence[Mapping[str, Sequence[float]]],
) -> dict[str, Any]:
    preferred_points = sample_cubics(preferred, 64)
    first_points = sample_cubics(boundary_a, 64)
    second_points = sample_cubics(boundary_b, 64)
    polygon = first_points + list(reversed(second_points))
    paths = (preferred_points, first_points, second_points)
    lengths = [_polyline_length(points) for points in paths]
    angles = [_angle_degrees(points[0], points[-1]) for points in paths]
    sagittas = [_normalized_sagitta(points) for points in paths]
    pair_count = min(len(preferred_points), len(first_points), len(second_points))
    maximum_offset = max(
        max(
            _distance(preferred_points[index], first_points[index]),
            _distance(preferred_points[index], second_points[index]),
        )
        for index in range(pair_count)
    )
    return {
        "polygon": [[round(float(value), 9) for value in point] for point in polygon],
        "intersects": _polylines_intersect(first_points, second_points),
        "inferred": {
            "length_range": [round(min(lengths), 9), round(max(lengths), 9)],
            "direction_degrees_range": [round(min(angles), 9), round(max(angles), 9)],
            "normalized_sagitta_range": [round(min(sagittas), 9), round(max(sagittas), 9)],
            "maximum_offset": round(maximum_offset, 9),
        },
    }

def _point_in_polygon(point: Sequence[float], polygon: Sequence[Sequence[float]]) -> bool:
    inside = False
    x, y = float(point[0]), float(point[1])
    prior = len(polygon) - 1
    for index, current in enumerate(polygon):
        xi, yi = float(current[0]), float(current[1])
        xj, yj = float(polygon[prior][0]), float(polygon[prior][1])
        if (yi > y) != (yj > y):
            crossing = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < crossing:
                inside = not inside
        prior = index
    return inside

def _normalize_constraints(value: Any, branch: Mapping[str, Any]) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise EditorValidationError(f"{branch['curve_id']}.constraints 必须是对象")
    allowed_keys = {"root_mount_range", "endpoint_region", "curve_envelope"}
    if set(value) - allowed_keys:
        raise EditorValidationError(f"{branch['curve_id']}.constraints 含未知字段")

    root_range = value.get("root_mount_range")
    if root_range is not None:
        if not isinstance(root_range, list) or len(root_range) != 2:
            raise EditorValidationError(f"{branch['curve_id']}.root_mount_range 必须有两个端点")
        try:
            root_range = sorted(float(item) for item in root_range)
        except (TypeError, ValueError) as exc:
            raise EditorValidationError(f"{branch['curve_id']}.root_mount_range 无效") from exc
        if not all(math.isfinite(item) for item in root_range) or not (
            0.0 <= root_range[0] <= root_range[1] < MAX_MOUNT_FRACTION
        ):
            raise EditorValidationError(f"{branch['curve_id']}.root_mount_range 越界")
        root_range = [round(item, 12) for item in root_range]

    endpoint_region = value.get("endpoint_region")
    if endpoint_region is not None:
        if not isinstance(endpoint_region, dict) or endpoint_region.get("type") != "polygon":
            raise EditorValidationError(f"{branch['curve_id']}.endpoint_region 必须是 polygon")
        endpoint_region = {
            "type": "polygon",
            "classification": "allowed",
            "points": _polygon(
                endpoint_region.get("points"), f"{branch['curve_id']}.endpoint_region.points"
            ),
        }

    envelope = value.get("curve_envelope")
    if envelope is not None:
        if not isinstance(envelope, dict):
            raise EditorValidationError(f"{branch['curve_id']}.curve_envelope 必须是对象")
        boundary_a = _cubics(
            envelope.get("boundary_a"), f"{branch['curve_id']}.curve_envelope.boundary_a"
        )
        boundary_b = _cubics(
            envelope.get("boundary_b"), f"{branch['curve_id']}.curve_envelope.boundary_b"
        )
        if len(boundary_a) != len(branch["edited_cubics"]) or len(boundary_b) != len(
            branch["edited_cubics"]
        ):
            raise EditorValidationError(f"{branch['curve_id']}.curve_envelope 段数必须与 preferred 一致")
        analysis = _envelope_analysis(branch["edited_cubics"], boundary_a, boundary_b)
        envelope = {
            "boundary_a": boundary_a,
            "boundary_b": boundary_b,
            **analysis,
        }

    return {
        "root_mount_range": root_range,
        "endpoint_region": endpoint_region,
        "curve_envelope": envelope,
    }

def _normalize_forbidden_regions(
    value: Any, branches: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 256:
        raise EditorValidationError("forbidden_regions 必须是最多 256 项的列表")
    by_id = {str(branch["curve_id"]): branch for branch in branches}
    level_one = {curve_id for curve_id, branch in by_id.items() if int(branch["level"]) == 1}
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, region in enumerate(value):
        if not isinstance(region, dict):
            raise EditorValidationError(f"forbidden_regions[{index}] 必须是对象")
        region_id = str(region.get("region_id", ""))
        if not SESSION_ID_RE.fullmatch(region_id) or region_id in seen:
            raise EditorValidationError(f"forbidden_regions[{index}].region_id 无效或重复")
        seen.add(region_id)
        scope = str(region.get("scope", ""))
        target = region.get("target")
        if scope == "global":
            target = None
        elif scope == "unit":
            if target not in level_one:
                raise EditorValidationError(f"{region_id} 的 Unit 目标无效")
        elif scope == "parent":
            if target != "backbone" and target not in by_id:
                raise EditorValidationError(f"{region_id} 的父枝目标无效")
        elif scope == "level":
            try:
                target = int(target)
            except (TypeError, ValueError) as exc:
                raise EditorValidationError(f"{region_id} 的层级目标无效") from exc
            if not 1 <= target <= 12:
                raise EditorValidationError(f"{region_id} 的层级目标越界")
        else:
            raise EditorValidationError(f"{region_id} 的 scope 无效")
        result.append(
            {
                "region_id": region_id,
                "classification": "forbidden",
                "scope": scope,
                "target": target,
                "points": _polygon(region.get("points"), f"{region_id}.points"),
            }
        )
    return result

def _geometry_warnings(
    branches: Sequence[Mapping[str, Any]], forbidden_regions: Sequence[Mapping[str, Any]] = ()
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for branch in branches:
        curve_id = str(branch["curve_id"])
        cubics = branch["edited_cubics"]
        first = cubics[0]
        last = cubics[-1]
        chord = _distance(first["p0"], last["p3"])
        if chord < 2.0:
            warnings.append({"curve_id": curve_id, "code": "very_short_chord"})
        for segment_index, cubic in enumerate(cubics):
            if _distance(cubic["p0"], cubic["p1"]) < 0.5 or _distance(cubic["p2"], cubic["p3"]) < 0.5:
                warnings.append(
                    {"curve_id": curve_id, "segment": segment_index, "code": "very_short_handle"}
                )
        if len(cubics) == 2:
            incoming = _normalize(
                [
                    cubics[0]["p3"][0] - cubics[0]["p2"][0],
                    cubics[0]["p3"][1] - cubics[0]["p2"][1],
                ]
            )
            outgoing = _normalize(
                [
                    cubics[1]["p1"][0] - cubics[1]["p0"][0],
                    cubics[1]["p1"][1] - cubics[1]["p0"][1],
                ]
            )
            dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
            if dot < 0.97:
                warnings.append({"curve_id": curve_id, "code": "g1_discontinuity", "dot": round(dot, 8)})
        constraints = branch.get("constraints") or {}
        root_range = constraints.get("root_mount_range")
        if root_range is not None and not root_range[0] <= float(branch["mount_fraction"]) <= root_range[1]:
            warnings.append({"curve_id": curve_id, "code": "preferred_root_outside_allowed_range"})
        endpoint_region = constraints.get("endpoint_region")
        if endpoint_region is not None and not _point_in_polygon(
            cubics[-1]["p3"], endpoint_region["points"]
        ):
            warnings.append({"curve_id": curve_id, "code": "preferred_endpoint_outside_allowed_region"})
        envelope = constraints.get("curve_envelope")
        if envelope is not None and envelope.get("intersects"):
            warnings.append({"curve_id": curve_id, "code": "curve_envelope_boundaries_intersect"})
    for region in forbidden_regions:
        for branch in branches:
            if any(_point_in_polygon(point, region["points"]) for point in sample_cubics(branch["edited_cubics"], 32)):
                warnings.append(
                    {
                        "curve_id": branch["curve_id"],
                        "region_id": region["region_id"],
                        "code": "preferred_curve_enters_forbidden_region",
                    }
                )
    return warnings

def _curve_deltas(
    branches: Sequence[Mapping[str, Any]], source_branches: Sequence[Mapping[str, Any]] = ()
) -> dict[str, Any]:
    deltas: dict[str, Any] = {}
    modified: list[str] = []
    source_ids = {str(branch["curve_id"]) for branch in source_branches}
    current_ids = {str(branch["curve_id"]) for branch in branches}
    added = sorted(current_ids - source_ids)
    deleted = sorted(source_ids - current_ids)
    for branch in branches:
        curve_id = str(branch["curve_id"])
        original = branch["original_cubics"]
        edited = branch["edited_cubics"]
        if curve_id in added:
            point_deltas: list[dict[str, list[float]]] = []
            mount_delta: float | None = None
            changed = True
        else:
            point_deltas = [
                {
                    name: [
                        round(float(new_segment[name][axis]) - float(old_segment[name][axis]), 12)
                        for axis in (0, 1)
                    ]
                    for name in POINT_NAMES
                }
                for old_segment, new_segment in zip(original, edited)
            ]
            raw_mount_delta = float(branch["mount_fraction"]) - float(
                branch["original_mount_fraction"]
            )
            mount_delta = 0.0 if abs(raw_mount_delta) <= 1e-5 else round(raw_mount_delta, 12)
            changed = mount_delta != 0.0 or any(
                abs(coordinate) > 1e-9
                for segment in point_deltas
                for point in segment.values()
                for coordinate in point
            )
        constraints_changed = branch.get("constraints") != {
            "root_mount_range": None,
            "endpoint_region": None,
            "curve_envelope": None,
        }
        status_changed = branch.get("status") != "required"
        changed = changed or constraints_changed or status_changed
        if changed:
            modified.append(curve_id)
        deltas[curve_id] = {
            "mount_fraction_delta": mount_delta,
            "cubic_point_deltas": point_deltas,
            "constraints_changed": constraints_changed,
            "status_changed": status_changed,
            "changed": changed,
        }
    return {
        "added_curve_ids": added,
        "deleted_curve_ids": deleted,
        "modified_curve_ids": modified,
        "modified_count": len(modified),
        "curve_deltas": deltas,
    }

def validate_session(payload: Any, source: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise EditorValidationError("session payload 必须是 JSON 对象")
    session = copy.deepcopy(payload)
    if session.get("schema") != SCHEMA:
        raise EditorValidationError(f"session schema 必须是 {SCHEMA}")
    received_source = session.get("source")
    if not isinstance(received_source, dict):
        raise EditorValidationError("session.source 缺失")
    try:
        seed = int(received_source.get("seed"))
    except (TypeError, ValueError) as exc:
        raise EditorValidationError("session.source.seed 无效") from exc
    source_data = copy.deepcopy(dict(source or load_source(seed)))

    expected_source = source_data["source"]
    protected_source_fields = ("seed", "base_id", "prototype")
    for field in protected_source_fields:
        if received_source.get(field) != expected_source.get(field):
            raise EditorValidationError(f"session.source.{field} 与固定输入不一致")
    if session.get("canvas") != source_data["canvas"]:
        raise EditorValidationError("session.canvas 与固定 profile 不一致")

    received_branches = session.get("branches")
    if not isinstance(received_branches, list) or not 0 <= len(received_branches) <= MAX_BRANCHES:
        raise EditorValidationError(f"session.branches 必须包含 0 到 {MAX_BRANCHES} 条分支")
    expected_by_id = {branch["curve_id"]: branch for branch in source_data["branches"]}
    received_by_id: dict[str, dict[str, Any]] = {}
    for row in received_branches:
        if not isinstance(row, dict) or not isinstance(row.get("curve_id"), str):
            raise EditorValidationError("session.branches 含无效分支")
        curve_id = row["curve_id"]
        if curve_id in received_by_id:
            raise EditorValidationError(f"重复 curve_id: {curve_id}")
        if curve_id not in expected_by_id and not re.fullmatch(r"user_branch_[A-Za-z0-9_-]{1,64}", curve_id):
            raise EditorValidationError(f"新增分支 ID 无效: {curve_id}")
        received_by_id[curve_id] = row

    normalized: list[dict[str, Any]] = []
    for row in received_branches:
        curve_id = row["curve_id"]
        expected = expected_by_id.get(curve_id)
        status = str(row.get("status", ""))
        if status not in {"required", "optional", "forbidden"}:
            raise EditorValidationError(f"{curve_id}.status 无效")
        edited = _cubics(row.get("edited_cubics"), f"{curve_id}.edited_cubics")
        try:
            mount_fraction = float(row.get("mount_fraction"))
        except (TypeError, ValueError) as exc:
            raise EditorValidationError(f"{curve_id}.mount_fraction 无效") from exc
        if not math.isfinite(mount_fraction) or not 0.0 <= mount_fraction < MAX_MOUNT_FRACTION:
            raise EditorValidationError(f"{curve_id}.mount_fraction 必须位于 [0, {MAX_MOUNT_FRACTION})")

        if expected is not None:
            for field in (
                "parent_id",
                "level",
                "role",
                "kind",
                "source",
                "target_flower_id",
                "width",
            ):
                if row.get(field) != expected.get(field):
                    raise EditorValidationError(f"{curve_id}.{field} 与 source record 不一致")
            original = _cubics(row.get("original_cubics"), f"{curve_id}.original_cubics")
            if original != expected["original_cubics"]:
                raise EditorValidationError(f"{curve_id}.original_cubics 不可修改")
            original_mount = float(row.get("original_mount_fraction", math.nan))
            if not math.isfinite(original_mount) or abs(
                original_mount - expected["original_mount_fraction"]
            ) > 1e-12:
                raise EditorValidationError(f"{curve_id}.original_mount_fraction 不可修改")
            branch = {
                **{key: copy.deepcopy(expected[key]) for key in expected},
                "mount_fraction": mount_fraction,
                "status": status,
                "edited_cubics": edited,
            }
        else:
            try:
                level = int(row.get("level"))
                width = float(row.get("width"))
            except (TypeError, ValueError) as exc:
                raise EditorValidationError(f"{curve_id} 的 level/width 无效") from exc
            if not 1 <= level <= 3:
                raise EditorValidationError(f"{curve_id}.level 必须位于 L1-L3")
            if not math.isfinite(width) or not 0.25 <= width <= 12.0:
                raise EditorValidationError(f"{curve_id}.width 越界")
            if row.get("original_cubics") not in ([], None):
                raise EditorValidationError(f"{curve_id}.original_cubics 对新增枝必须为空")
            if row.get("original_mount_fraction") is not None:
                raise EditorValidationError(f"{curve_id}.original_mount_fraction 对新增枝必须为空")
            if row.get("kind") != "user" or row.get("source") != "user_drawn":
                raise EditorValidationError(f"{curve_id} 必须标记为 user/user_drawn")
            branch = {
                "curve_id": curve_id,
                "parent_id": str(row.get("parent_id")),
                "level": level,
                "role": str(row.get("role", f"user_level_{level}")),
                "kind": "user",
                "source": "user_drawn",
                "target_flower_id": row.get("target_flower_id"),
                "mount_fraction": mount_fraction,
                "original_mount_fraction": None,
                "width": width,
                "status": status,
                "original_cubics": [],
                "edited_cubics": edited,
            }
        branch["constraints"] = _normalize_constraints(row.get("constraints"), branch)
        normalized.append(branch)

    _validate_parent_graph(normalized)
    normalized_by_id = {branch["curve_id"]: branch for branch in normalized}
    for branch in sorted(normalized, key=lambda item: (item["level"], item["curve_id"])):
        if branch["parent_id"] == "backbone":
            parent_points = source_data["backbone"]["points"]
        else:
            parent_points = sample_cubics(
                normalized_by_id[branch["parent_id"]]["edited_cubics"], 128
            )
        projection = project_point_to_polyline(branch["edited_cubics"][0]["p0"], parent_points)
        if projection["distance"] > ROOT_DISTANCE_TOLERANCE:
            raise EditorValidationError(
                f"{branch['curve_id']} 根点离开父枝 {projection['distance']:.4f}px"
            )
        if projection["fraction"] >= MAX_MOUNT_FRACTION:
            raise EditorValidationError(f"{branch['curve_id']} 根点不能停在父枝尖端")
        if abs(projection["fraction"] - branch["mount_fraction"]) > MOUNT_FRACTION_TOLERANCE:
            raise EditorValidationError(
                f"{branch['curve_id']}.mount_fraction 与根点投影不一致"
            )
        branch["mount_fraction"] = round(float(projection["fraction"]), 12)

    forbidden_regions = _normalize_forbidden_regions(
        session.get("forbidden_regions", []), normalized
    )
    result = {
        "schema": SCHEMA,
        "source": copy.deepcopy(source_data["source"]),
        "canvas": copy.deepcopy(source_data["canvas"]),
        "branches": normalized,
        "forbidden_regions": forbidden_regions,
        "warnings": _geometry_warnings(normalized, forbidden_regions),
        "edit_summary": _curve_deltas(normalized, source_data["branches"]),
    }
    return result

def _svg_path(cubics: Sequence[Mapping[str, Sequence[float]]]) -> str:
    first = cubics[0]
    parts = [f"M {first['p0'][0]:.9f} {first['p0'][1]:.9f}"]
    for cubic in cubics:
        parts.append(
            "C "
            f"{cubic['p1'][0]:.9f} {cubic['p1'][1]:.9f} "
            f"{cubic['p2'][0]:.9f} {cubic['p2'][1]:.9f} "
            f"{cubic['p3'][0]:.9f} {cubic['p3'][1]:.9f}"
        )
    return " ".join(parts)

def _polyline_path(points: Sequence[Sequence[float]]) -> str:
    return "M " + " L ".join(f"{point[0]:.9f} {point[1]:.9f}" for point in points)

def _polygon_attribute(points: Sequence[Sequence[float]]) -> str:
    return " ".join(f"{point[0]:.9f},{point[1]:.9f}" for point in points)

def _range_polyline(points: Sequence[Sequence[float]], start: float, end: float) -> list[list[float]]:
    steps = max(8, int(abs(end - start) * 160))
    return [
        frame_at_fraction(points, start + (end - start) * index / steps)["point"]
        for index in range(steps + 1)
    ]

def render_edited_svg(session: Mapping[str, Any], source: Mapping[str, Any] | None = None) -> str:
    seed = int(session["source"]["seed"])
    source_data = dict(source or load_source(seed))
    active = session["canvas"]["active_repeat_x"]
    period = float(active[1]) - float(active[0])
    height = float(session["canvas"]["height"])
    view_x = float(active[0]) - period
    view_width = period * 3.0
    branch_markup = []
    for branch in session["branches"]:
        branch_markup.append(
            f'<path data-curve-id="{html.escape(str(branch["curve_id"]))}" '
            f'data-status="{html.escape(str(branch["status"]))}" '
            f'd="{_svg_path(branch["edited_cubics"])}" '
            f'stroke-width="{float(branch["width"]):.6f}" />'
        )
    branch_svg = "\n      ".join(branch_markup)
    flowers = "\n      ".join(
        f'<ellipse cx="{flower["center"][0]:.9f}" cy="{flower["center"][1]:.9f}" '
        f'rx="{flower["rx"]:.9f}" ry="{flower["ry"]:.9f}" />'
        for flower in source_data["flowers"]
    )
    content = (
        f'<path class="backbone" d="{_polyline_path(source_data["backbone"]["points"])}" />\n'
        f'      <g class="flowers">{flowers}</g>\n'
        f'      <g class="branches">{branch_svg}</g>'
    )
    current_by_id = {branch["curve_id"]: branch for branch in session["branches"]}
    overlay_markup: list[str] = []
    for branch in session["branches"]:
        constraints = branch.get("constraints") or {}
        root_range = constraints.get("root_mount_range")
        if root_range is not None:
            if branch["parent_id"] == "backbone":
                parent_points = source_data["backbone"]["points"]
            else:
                parent_points = sample_cubics(current_by_id[branch["parent_id"]]["edited_cubics"], 96)
            highlighted = _range_polyline(parent_points, root_range[0], root_range[1])
            overlay_markup.append(
                f'<path class="root-range" data-owner="{html.escape(branch["curve_id"])}" '
                f'd="{_polyline_path(highlighted)}" />'
            )
        endpoint = constraints.get("endpoint_region")
        if endpoint is not None:
            overlay_markup.append(
                f'<polygon class="allowed-region" data-owner="{html.escape(branch["curve_id"])}" '
                f'points="{_polygon_attribute(endpoint["points"])}" />'
            )
        envelope = constraints.get("curve_envelope")
        if envelope is not None:
            overlay_markup.append(
                f'<polygon class="curve-envelope" data-owner="{html.escape(branch["curve_id"])}" '
                f'points="{_polygon_attribute(envelope["polygon"])}" />'
            )
            overlay_markup.append(f'<path class="envelope-boundary" d="{_svg_path(envelope["boundary_a"])}" />')
            overlay_markup.append(f'<path class="envelope-boundary" d="{_svg_path(envelope["boundary_b"])}" />')
    for region in session.get("forbidden_regions", []):
        overlay_markup.append(
            f'<polygon class="forbidden-region" data-region-id="{html.escape(region["region_id"])}" '
            f'data-scope="{html.escape(region["scope"])}" '
            f'points="{_polygon_attribute(region["points"])}" />'
        )
    overlays = "\n  ".join(overlay_markup)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view_x:.6f} 0 {view_width:.6f} {height:.6f}">
  <metadata>{html.escape(_canonical_json({"schema": SCHEMA, "source": session["source"]["base_id"]}))}</metadata>
  <style>
    .edge {{ fill: #a33a2b; opacity: .16; }}
    .scene {{ fill: none; stroke: #172025; stroke-linecap: round; stroke-linejoin: round; }}
    .backbone {{ stroke: #8a6544; stroke-width: 5; }}
    .flowers ellipse {{ fill: #eeeafd; stroke: #5546df; stroke-width: 1; }}
    .branches path {{ fill: none; stroke: #172025; }}
    .branches path[data-status="optional"] {{ stroke-dasharray: 4 3; }}
    .branches path[data-status="forbidden"] {{ stroke: #b33a2e; opacity: .55; }}
    .ghost {{ opacity: .16; }}
    .root-range {{ fill: none; stroke: #1b8a70; stroke-width: 7; opacity: .5; }}
    .allowed-region {{ fill: #3aaa7b; fill-opacity: .14; stroke: #238665; stroke-width: 1; }}
    .curve-envelope {{ fill: #d99b31; fill-opacity: .13; stroke: none; }}
    .envelope-boundary {{ fill: none; stroke: #bf791a; stroke-width: 1; stroke-dasharray: 3 2; }}
    .forbidden-region {{ fill: #c74638; fill-opacity: .16; stroke: #ad3027; stroke-width: 1; }}
  </style>
  <rect width="{view_width:.6f}" height="9" x="{view_x:.6f}" y="0" class="edge" />
  <rect width="{view_width:.6f}" height="9" x="{view_x:.6f}" y="{height - 9:.6f}" class="edge" />
  <g class="scene ghost" transform="translate({-period:.6f} 0)">{content}</g>
  <g class="scene">{content}</g>
  <g class="constraint-overlays">{overlays}</g>
  <g class="scene ghost" transform="translate({period:.6f} 0)">{content}</g>
</svg>
'''

def _session_metrics(session: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    source_by_id = {branch["curve_id"]: branch for branch in source["branches"]}
    squared: list[float] = []
    mount_deltas: list[float] = []
    for branch in session["branches"]:
        original = source_by_id.get(branch["curve_id"])
        if original is None:
            continue
        mount_deltas.append(abs(float(branch["mount_fraction"]) - float(original["mount_fraction"])))
        for old_segment, new_segment in zip(original["original_cubics"], branch["edited_cubics"]):
            for name in POINT_NAMES:
                squared.extend(
                    (float(new_segment[name][axis]) - float(old_segment[name][axis])) ** 2
                    for axis in (0, 1)
                )
    statuses = {name: 0 for name in ("required", "optional", "forbidden")}
    for branch in session["branches"]:
        statuses[str(branch["status"])] += 1
    constraints = {
        "root_ranges": sum(bool(branch["constraints"]["root_mount_range"]) for branch in session["branches"]),
        "endpoint_regions": sum(bool(branch["constraints"]["endpoint_region"]) for branch in session["branches"]),
        "curve_envelopes": sum(bool(branch["constraints"]["curve_envelope"]) for branch in session["branches"]),
        "forbidden_regions": len(session.get("forbidden_regions", [])),
    }
    return {
        "branch_count": len(session["branches"]),
        "modified_count": int(session["edit_summary"]["modified_count"]),
        "control_point_rms_delta": round(math.sqrt(sum(squared) / len(squared)), 9) if squared else 0.0,
        "mount_mean_absolute_delta": round(sum(mount_deltas) / len(mount_deltas), 12)
        if mount_deltas
        else 0.0,
        "statuses": statuses,
        "constraints": constraints,
        "warning_count": len(session.get("warnings", [])),
    }

def branch_map(branches: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(branch["curve_id"]): branch for branch in branches}