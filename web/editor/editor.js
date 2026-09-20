(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const POINT_NAMES = ["p0", "p1", "p2", "p3"];
  const ALLOWED_SEEDS = [0];
  const SAMPLE_COUNT = 96;
  const ROOT_MIN_FRACTION = 0.001;
  const ROOT_MAX_FRACTION = 0.985;
  const MODE_HINTS = {
    select: "选择分支后直接拖动根点、枝尖或 Bézier 控制柄",
    add: "在主干或 L1/L2 父枝上按下，向空白处拖出一条新枝",
    "root-range": "选择分支后，在它的父枝上拖出允许挂载的弧长区间",
    "endpoint-region": "选择分支后，在画布上按住并自由圈出枝尖允许区域",
    envelope: "选择分支，拖动橙色边界控制点定义曲线允许包络",
    forbidden: "选择禁区范围后，在画布上按住并自由圈出禁区",
  };

  const ui = {
    svg: document.getElementById("editor-canvas"),
    seedTitle: document.getElementById("seed-title"),
    seedSelect: document.getElementById("seed-select"),
    selectionStatus: document.getElementById("selection-status"),
    geometryStatus: document.getElementById("geometry-status"),
    saveStatus: document.getElementById("save-status"),
    modeHint: document.getElementById("mode-hint"),
    undo: document.getElementById("undo-button"),
    redo: document.getElementById("redo-button"),
    save: document.getElementById("save-button"),
    delete: document.getElementById("delete-button"),
    forbiddenScope: document.getElementById("forbidden-scope"),
    unitStats: document.getElementById("unit-stats"),
    constraintStats: document.getElementById("constraint-stats"),
    targetSelect: document.getElementById("target-select"),
    compare: document.getElementById("compare-button"),
    targetStats: document.getElementById("target-stats"),
  };

  const state = {
    seed: 0,
    bootstrap: null,
    bootstraps: new Map(),
    seedSlots: new Map(),
    branches: [],
    forbiddenRegions: [],
    selectedId: null,
    mode: "select",
    viewMode: "context",
    undo: [],
    redo: [],
    drag: null,
    sessionId: null,
    dirty: false,
    targetIndex: null,
    targetComparison: null,
    idCounter: 0,
  };

  const deepClone = (value) => JSON.parse(JSON.stringify(value));
  const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const add = (a, b) => [a[0] + b[0], a[1] + b[1]];
  const subtract = (a, b) => [a[0] - b[0], a[1] - b[1]];
  const scale = (value, amount) => [value[0] * amount, value[1] * amount];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
  const normalize = (value) => {
    const length = Math.hypot(value[0], value[1]);
    return length < 1e-12 ? [1, 0] : [value[0] / length, value[1] / length];
  };
  const branchMap = (branches = state.branches) => new Map(branches.map((branch) => [branch.curve_id, branch]));
  const selectedBranch = () => state.selectedId ? branchMap().get(state.selectedId) || null : null;

  function svgNode(name, attributes = {}) {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }

  function pathData(cubics) {
    const chunks = [`M ${cubics[0].p0[0]} ${cubics[0].p0[1]}`];
    cubics.forEach((cubic) => chunks.push(
      `C ${cubic.p1[0]} ${cubic.p1[1]} ${cubic.p2[0]} ${cubic.p2[1]} ${cubic.p3[0]} ${cubic.p3[1]}`,
    ));
    return chunks.join(" ");
  }

  function polylinePath(points) {
    return points.map((point, index) => `${index ? "L" : "M"} ${point[0]} ${point[1]}`).join(" ");
  }

  function polygonPoints(points) {
    return points.map((point) => `${point[0]},${point[1]}`).join(" ");
  }

  function cubicPoint(cubic, t) {
    const one = 1 - t;
    const weights = [one ** 3, 3 * one * one * t, 3 * one * t * t, t ** 3];
    return [0, 1].map((axis) => POINT_NAMES.reduce(
      (total, name, index) => total + weights[index] * cubic[name][axis], 0,
    ));
  }

  function sampleCubics(cubics, samples = SAMPLE_COUNT) {
    const points = [];
    cubics.forEach((cubic, cubicIndex) => {
      for (let index = 0; index <= samples; index += 1) {
        if (cubicIndex && index === 0) continue;
        points.push(cubicPoint(cubic, index / samples));
      }
    });
    return points;
  }

  function polylineLengths(points) {
    const lengths = [];
    let total = 0;
    for (let index = 0; index < points.length - 1; index += 1) {
      const length = distance(points[index], points[index + 1]);
      lengths.push(length);
      total += length;
    }
    return { lengths, total };
  }

  function frameAtFraction(points, fraction) {
    const { lengths, total } = polylineLengths(points);
    if (total <= 1e-12) throw new Error("父枝长度为零");
    const safe = Math.max(0, Math.min(1, fraction));
    const target = safe * total;
    let traversed = 0;
    for (let index = 0; index < lengths.length; index += 1) {
      const length = lengths[index];
      if (length <= 1e-12) continue;
      if (traversed + length >= target || index === lengths.length - 1) {
        const local = Math.max(0, Math.min(1, (target - traversed) / length));
        const tangent = normalize(subtract(points[index + 1], points[index]));
        return {
          point: add(points[index], scale(subtract(points[index + 1], points[index]), local)),
          tangent,
          normal: [-tangent[1], tangent[0]],
          fraction: safe,
        };
      }
      traversed += length;
    }
    throw new Error("无法计算父枝局部框架");
  }

  function projectPoint(point, points) {
    const { lengths, total } = polylineLengths(points);
    if (total <= 1e-12) throw new Error("父枝长度为零");
    let traversed = 0;
    let best = null;
    for (let index = 0; index < lengths.length; index += 1) {
      const length = lengths[index];
      if (length <= 1e-12) continue;
      const start = points[index];
      const vector = subtract(points[index + 1], start);
      const local = Math.max(0, Math.min(1, dot(subtract(point, start), vector) / (length * length)));
      const candidate = add(start, scale(vector, local));
      const gap = distance(point, candidate);
      if (!best || gap < best.distance) {
        best = { fraction: (traversed + local * length) / total, distance: gap };
      }
      traversed += length;
    }
    if (!best) throw new Error("父枝没有有效线段");
    return frameAtFraction(points, Math.max(ROOT_MIN_FRACTION, Math.min(ROOT_MAX_FRACTION, best.fraction)));
  }

  function toLocal(point, frame) {
    const offset = subtract(point, frame.point);
    return [dot(offset, frame.tangent), dot(offset, frame.normal)];
  }

  function fromLocal(local, frame) {
    return add(frame.point, add(scale(frame.tangent, local[0]), scale(frame.normal, local[1])));
  }

  function transformCubics(cubics, oldFrame, newFrame) {
    return cubics.map((cubic) => Object.fromEntries(
      POINT_NAMES.map((name) => [name, fromLocal(toLocal(cubic[name], oldFrame), newFrame)]),
    ));
  }

  function transformSpatialConstraints(branch, oldFrame, newFrame) {
    const constraints = branch.constraints || {};
    if (constraints.endpoint_region) {
      constraints.endpoint_region.points = constraints.endpoint_region.points.map(
        (point) => fromLocal(toLocal(point, oldFrame), newFrame),
      );
    }
    if (constraints.curve_envelope) {
      constraints.curve_envelope.boundary_a = transformCubics(
        constraints.curve_envelope.boundary_a, oldFrame, newFrame,
      );
      constraints.curve_envelope.boundary_b = transformCubics(
        constraints.curve_envelope.boundary_b, oldFrame, newFrame,
      );
      updateEnvelopeAnalysis(branch);
    }
  }

  function childrenOf(parentId, branches = state.branches) {
    return branches.filter((branch) => branch.parent_id === parentId)
      .sort((a, b) => a.level - b.level || a.curve_id.localeCompare(b.curve_id));
  }

  function descendantsOf(parentId, branches = state.branches) {
    const result = [];
    const visit = (id) => childrenOf(id, branches).forEach((child) => {
      result.push(child);
      visit(child.curve_id);
    });
    visit(parentId);
    return result;
  }

  function propagateDescendants(branches, parentId, oldParentPoints, newParentPoints) {
    const byId = branchMap(branches);
    childrenOf(parentId, branches).forEach((childRef) => {
      const child = byId.get(childRef.curve_id);
      const oldFrame = frameAtFraction(oldParentPoints, child.mount_fraction);
      const newFrame = frameAtFraction(newParentPoints, child.mount_fraction);
      const oldCubics = deepClone(child.edited_cubics);
      child.edited_cubics = transformCubics(oldCubics, oldFrame, newFrame);
      transformSpatialConstraints(child, oldFrame, newFrame);
      propagateDescendants(
        branches,
        child.curve_id,
        sampleCubics(oldCubics),
        sampleCubics(child.edited_cubics),
      );
    });
  }

  function parentPoints(branch, branches = state.branches) {
    if (branch.parent_id === "backbone") return state.bootstrap.backbone.points;
    const parent = branchMap(branches).get(branch.parent_id);
    if (!parent) throw new Error(`找不到父枝 ${branch.parent_id}`);
    return sampleCubics(parent.edited_cubics, 128);
  }

  function parentGeometry(parentId, branches = state.branches) {
    if (parentId === "backbone") return state.bootstrap.backbone.points;
    const parent = branchMap(branches).get(parentId);
    if (!parent) throw new Error(`找不到父枝 ${parentId}`);
    return sampleCubics(parent.edited_cubics, 128);
  }

  function topUnitId(curveId, branches = state.branches) {
    const byId = branchMap(branches);
    let current = byId.get(curveId);
    if (!current) return null;
    while (current.level > 1) current = byId.get(current.parent_id);
    return current ? current.curve_id : null;
  }

  function unitMembers(curveId, branches = state.branches) {
    const unitId = topUnitId(curveId, branches);
    if (!unitId) return [];
    return [branchMap(branches).get(unitId), ...descendantsOf(unitId, branches)].filter(Boolean);
  }

  function canvasPoint(event) {
    const point = ui.svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const transformed = point.matrixTransform(ui.svg.getScreenCTM().inverse());
    return [transformed.x, transformed.y];
  }

  function currentSnapshot() {
    return { branches: deepClone(state.branches), forbiddenRegions: deepClone(state.forbiddenRegions) };
  }

  function restoreSnapshot(snapshot) {
    state.branches = deepClone(snapshot.branches);
    state.forbiddenRegions = deepClone(snapshot.forbiddenRegions);
  }

  function commitSnapshot(before) {
    const after = currentSnapshot();
    if (JSON.stringify(before) === JSON.stringify(after)) return false;
    state.undo.push(before);
    state.redo = [];
    state.dirty = true; window.parent.postMessage({type:"papera-editor-dirty",dirty:true},window.location.origin);
    return true;
  }

  function setMessage(text, kind = "") {
    ui.saveStatus.className = kind;
    ui.saveStatus.textContent = text;
  }

  function lineSegmentsIntersect(a, b, c, d) {
    const orientation = (p, q, r) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
    const values = [orientation(a, b, c), orientation(a, b, d), orientation(c, d, a), orientation(c, d, b)];
    const epsilon = 1e-8;
    if (((values[0] > epsilon && values[1] < -epsilon) || (values[0] < -epsilon && values[1] > epsilon))
      && ((values[2] > epsilon && values[3] < -epsilon) || (values[2] < -epsilon && values[3] > epsilon))) return true;
    const onSegment = (start, point, end) => point[0] >= Math.min(start[0], end[0]) - epsilon
      && point[0] <= Math.max(start[0], end[0]) + epsilon
      && point[1] >= Math.min(start[1], end[1]) - epsilon
      && point[1] <= Math.max(start[1], end[1]) + epsilon;
    return (Math.abs(values[0]) <= epsilon && onSegment(a, c, b))
      || (Math.abs(values[1]) <= epsilon && onSegment(a, d, b))
      || (Math.abs(values[2]) <= epsilon && onSegment(c, a, d))
      || (Math.abs(values[3]) <= epsilon && onSegment(c, b, d));
  }

  function polylinesIntersect(first, second) {
    for (let firstIndex = 0; firstIndex < first.length - 1; firstIndex += 1) {
      for (let secondIndex = 0; secondIndex < second.length - 1; secondIndex += 1) {
        if (lineSegmentsIntersect(first[firstIndex], first[firstIndex + 1], second[secondIndex], second[secondIndex + 1])) return true;
      }
    }
    return false;
  }

  function normalizedSagitta(points) {
    const start = points[0];
    const end = points[points.length - 1];
    const chord = Math.max(distance(start, end), 1e-9);
    const vector = subtract(end, start);
    const maximum = Math.max(...points.map(
      (point) => Math.abs(vector[0] * (start[1] - point[1]) - (start[0] - point[0]) * vector[1]) / chord,
    ));
    return maximum / chord;
  }

  function updateEnvelopeAnalysis(branch) {
    const envelope = branch.constraints?.curve_envelope;
    if (!envelope) return;
    const preferred = sampleCubics(branch.edited_cubics, 64);
    const first = sampleCubics(envelope.boundary_a, 64);
    const second = sampleCubics(envelope.boundary_b, 64);
    const length = (points) => polylineLengths(points).total;
    const angle = (points) => Math.atan2(
      points.at(-1)[1] - points[0][1], points.at(-1)[0] - points[0][0],
    ) * 180 / Math.PI;
    const paths = [preferred, first, second];
    const lengths = paths.map(length);
    const angles = paths.map(angle);
    const sagittas = paths.map(normalizedSagitta);
    envelope.polygon = [...first, ...deepClone(second).reverse()];
    envelope.intersects = polylinesIntersect(first, second);
    envelope.inferred = {
      length_range: [Math.min(...lengths), Math.max(...lengths)],
      direction_degrees_range: [Math.min(...angles), Math.max(...angles)],
      normalized_sagitta_range: [Math.min(...sagittas), Math.max(...sagittas)],
      maximum_offset: Math.max(...preferred.map((point, index) => Math.max(
        distance(point, first[index]), distance(point, second[index]),
      ))),
    };
  }

  function ensureEnvelope(branch) {
    branch.constraints ||= { root_mount_range: null, endpoint_region: null, curve_envelope: null };
    if (branch.constraints.curve_envelope) return false;
    const firstPoint = branch.edited_cubics[0].p0;
    const lastPoint = branch.edited_cubics.at(-1).p3;
    const tangent = normalize(subtract(lastPoint, firstPoint));
    const normal = [-tangent[1], tangent[0]];
    const offset = Math.max(5, Math.min(10, distance(firstPoint, lastPoint) * 0.075));
    const shifted = (amount) => branch.edited_cubics.map((cubic) => Object.fromEntries(
      POINT_NAMES.map((name) => [name, add(cubic[name], scale(normal, amount))]),
    ));
    branch.constraints.curve_envelope = { boundary_a: shifted(offset), boundary_b: shifted(-offset) };
    updateEnvelopeAnalysis(branch);
    return true;
  }

  function rangePolyline(points, start, end) {
    const steps = Math.max(8, Math.round(Math.abs(end - start) * 160));
    return Array.from({ length: steps + 1 }, (_, index) => frameAtFraction(
      points, start + (end - start) * index / steps,
    ).point);
  }

  function viewBoxForState() {
    const [start, end] = state.bootstrap.canvas.active_repeat_x;
    const period = end - start;
    const height = state.bootstrap.canvas.height;
    if (state.viewMode === "whole") return [start, 0, period, height];
    if (state.viewMode === "double") return [start, 0, period * 2, height];
    if (state.viewMode === "unit" && state.selectedId) {
      const members = unitMembers(state.selectedId);
      if (members.length) {
        const points = members.flatMap((branch) => sampleCubics(branch.edited_cubics, 48));
        const xs = points.map((point) => point[0]);
        const ys = points.map((point) => point[1]);
        const padding = 18;
        const x = Math.min(...xs) - padding;
        const y = Math.min(...ys) - padding;
        return [x, y, Math.max(48, Math.max(...xs) - Math.min(...xs) + 2 * padding), Math.max(48, Math.max(...ys) - Math.min(...ys) + 2 * padding)];
      }
    }
    return [start - period, 0, period * 3, height];
  }

  function drawLockedScene(group, offset = 0, interactiveBackbone = false) {
    const locked = svgNode("g", offset ? { transform: `translate(${offset} 0)` } : {});
    if (interactiveBackbone) {
      const hit = svgNode("path", { d: polylinePath(state.bootstrap.backbone.points), class: "backbone-hit", "data-parent-id": "backbone" });
      hit.addEventListener("pointerdown", (event) => startNewBranch("backbone", event));
      locked.appendChild(hit);
    }
    locked.appendChild(svgNode("path", { d: polylinePath(state.bootstrap.backbone.points), class: "backbone", "data-locked": "backbone" }));
    (state.bootstrap.supports || []).forEach(support => locked.appendChild(svgNode("path", {d: polylinePath(support.points), class:"flower-support", "data-locked":support.flower_id})));
    state.bootstrap.flowers.forEach((flower) => {
      locked.appendChild(svgNode("ellipse", { cx: flower.center[0], cy: flower.center[1], rx: flower.rx, ry: flower.ry, class: "flower", "data-locked": flower.flower_id }));
      locked.appendChild(svgNode("circle", { cx: flower.center[0], cy: flower.center[1], r: 2.2, class: "flower-center", "data-locked": flower.flower_id }));
    });
    group.appendChild(locked);
  }

  function drawBranchSet(group, { copy = false, offset = 0, ghost = false } = {}) {
    const branchGroup = svgNode("g", offset ? { transform: `translate(${offset} 0)` } : {});
    const visibleUnit = state.viewMode === "unit" && state.selectedId ? topUnitId(state.selectedId) : null;
    state.branches.forEach((branch) => {
      const d = pathData(branch.edited_cubics);
      if (!copy && !ghost) {
        const hit = svgNode("path", { d, class: "branch-hit", "data-curve-id": branch.curve_id, "data-level": branch.level });
        hit.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          event.stopPropagation();
          if (state.mode === "add") startNewBranch(branch.curve_id, event);
          else selectBranch(branch.curve_id);
        });
        branchGroup.appendChild(hit);
      }
      const classes = ["branch-display"];
      if (!copy && !ghost && branch.curve_id === state.selectedId) classes.push("branch-selected");
      if (state.mode === "add" && !copy && !ghost && branch.level < 3) classes.push("branch-parent-candidate");
      const path = svgNode("path", {
        "data-level": branch.level,
        d,
        class: classes.join(" "),
        "stroke-width": branch.width,
        "data-display-id": branch.curve_id,
        "data-status": branch.status,
      });
      if (visibleUnit && topUnitId(branch.curve_id) !== visibleUnit) path.setAttribute("opacity", ".09");
      branchGroup.appendChild(path);
    });
    group.appendChild(branchGroup);
  }

  function screenRadius(pixels) {
    const matrix = ui.svg.getScreenCTM();
    return pixels / Math.max(0.001, matrix ? Math.hypot(matrix.a, matrix.b) : 1);
  }

  function handleCircle(point, className, type, details = {}, radius = 5.5) {
    const node = svgNode("circle", {
      cx: point[0], cy: point[1], r: screenRadius(radius), class: `handle ${className}`, "data-handle-type": type,
      "vector-effect": "non-scaling-stroke",
      ...Object.fromEntries(Object.entries(details).map(([key, value]) => [`data-${key}`, value])),
    });
    node.addEventListener("pointerdown", (event) => startDrag(type, details, event));
    return node;
  }

  function drawDirectControls(group, branch) {
    const cubics = branch.edited_cubics;
    cubics.forEach((cubic, segment) => {
      group.appendChild(svgNode("path", { d: `M ${cubic.p0[0]} ${cubic.p0[1]} L ${cubic.p1[0]} ${cubic.p1[1]}`, class: "control-line" }));
      group.appendChild(svgNode("path", { d: `M ${cubic.p3[0]} ${cubic.p3[1]} L ${cubic.p2[0]} ${cubic.p2[1]}`, class: "control-line" }));
      group.appendChild(handleCircle(cubic.p1, "bezier-handle", "control", { segment, point: "p1" }));
      group.appendChild(handleCircle(cubic.p2, "bezier-handle", "control", { segment, point: "p2" }));
    });
    group.appendChild(handleCircle(cubics[0].p0, "root-handle", "root"));
    group.appendChild(handleCircle(cubics.at(-1).p3, "tip-handle", "tip"));
    for (let segment = 0; segment < cubics.length - 1; segment += 1) {
      const join = cubics[segment].p3;
      const size = screenRadius(6);
      const diamond = svgNode("polygon", {
        points: `${join[0]},${join[1] - size} ${join[0] + size},${join[1]} ${join[0]},${join[1] + size} ${join[0] - size},${join[1]}`,
        "vector-effect": "non-scaling-stroke",
        class: "handle join-handle", "data-handle-type": "join", "data-segment": segment,
      });
      diamond.addEventListener("pointerdown", (event) => startDrag("join", { segment }, event));
      group.appendChild(diamond);
    }
    childrenOf(branch.curve_id).forEach((child) => {
      const root = child.edited_cubics[0].p0;
      group.appendChild(svgNode("circle", { cx: root[0], cy: root[1], r: 2.7, class: "child-root", "data-child-root": child.curve_id }));
    });
  }

  function drawConstraints(group) {
    state.branches.forEach((branch) => {
      const constraints = branch.constraints || {};
      if (constraints.root_mount_range) {
        const points = parentPoints(branch);
        const highlighted = rangePolyline(points, ...constraints.root_mount_range);
        group.appendChild(svgNode("path", { d: polylinePath(highlighted), class: "root-range", "data-owner": branch.curve_id }));
        highlighted.filter((_, index) => index === 0 || index === highlighted.length - 1).forEach((point) => {
          group.appendChild(svgNode("circle", { cx: point[0], cy: point[1], r: 3.2, class: "range-end" }));
        });
      }
      if (constraints.endpoint_region) {
        group.appendChild(svgNode("polygon", { points: polygonPoints(constraints.endpoint_region.points), class: "allowed-region", "data-owner": branch.curve_id }));
      }
      const envelope = constraints.curve_envelope;
      if (envelope) {
        group.appendChild(svgNode("polygon", {
          points: polygonPoints(envelope.polygon),
          class: `envelope-fill${envelope.intersects ? " intersects" : ""}`,
          "data-owner": branch.curve_id,
        }));
        ["boundary_a", "boundary_b"].forEach((boundary) => group.appendChild(svgNode("path", {
          d: pathData(envelope[boundary]),
          class: `envelope-boundary${envelope.intersects ? " intersects" : ""}`,
          "data-envelope-boundary": boundary,
          "data-owner": branch.curve_id,
        })));
      }
    });
    state.forbiddenRegions.forEach((region) => group.appendChild(svgNode("polygon", {
      points: polygonPoints(region.points), class: "forbidden-region", "data-region-id": region.region_id, "data-scope": region.scope,
    })));
  }

  function drawModeControls(group, branch) {
    if (branch) group.appendChild(svgNode("path", { d: pathData(branch.edited_cubics), class: "preferred-emphasis" }));
    if (branch && state.mode === "select") drawDirectControls(group, branch);
    if (branch && state.mode === "root-range") {
      const points = parentPoints(branch);
      const hit = svgNode("path", { d: polylinePath(points), class: "range-parent-hit", "data-range-parent": branch.parent_id });
      hit.addEventListener("pointerdown", startRootRange);
      group.appendChild(hit);
    }
    if (branch && state.mode === "endpoint-region" && branch.constraints.endpoint_region) {
      branch.constraints.endpoint_region.points.forEach((point, index) => group.appendChild(
        handleCircle(point, "region-vertex allowed", "region-vertex", { region: "endpoint", index }, 3.5),
      ));
    }
    if (branch && state.mode === "envelope" && branch.constraints.curve_envelope) {
      const envelope = branch.constraints.curve_envelope;
      ["boundary_a", "boundary_b"].forEach((boundary) => envelope[boundary].forEach((cubic, segment) => {
        group.appendChild(svgNode("path", { d: `M ${cubic.p0[0]} ${cubic.p0[1]} L ${cubic.p1[0]} ${cubic.p1[1]}`, class: "envelope-line" }));
        group.appendChild(svgNode("path", { d: `M ${cubic.p3[0]} ${cubic.p3[1]} L ${cubic.p2[0]} ${cubic.p2[1]}`, class: "envelope-line" }));
        POINT_NAMES.forEach((point) => group.appendChild(handleCircle(
          cubic[point], `envelope-handle${envelope.intersects ? " intersects" : ""}`, "envelope-handle", { boundary, segment, point }, point === "p0" || point === "p3" ? 3.8 : 3.3,
        )));
      }));
    }
    if (state.mode === "forbidden") {
      state.forbiddenRegions.forEach((region) => region.points.forEach((point, index) => group.appendChild(
        handleCircle(point, "region-vertex forbidden", "region-vertex", { region: region.region_id, index }, 3.4),
      )));
    }
  }

  function drawTransient(group) {
    if (!state.drag) return;
    if (state.drag.type === "lasso" && state.drag.points.length > 1) {
      group.appendChild(svgNode("polygon", { points: polygonPoints(state.drag.points), class: "lasso-preview" }));
    } else if (state.drag.type === "new" && state.drag.previewCubics) {
      group.appendChild(svgNode("path", { d: pathData(state.drag.previewCubics), class: "new-preview" }));
    }
  }

  function render() {
    if (!state.bootstrap) return;
    const [viewX, viewY, viewWidth, viewHeight] = viewBoxForState();
    const [start, end] = state.bootstrap.canvas.active_repeat_x;
    const period = end - start;
    const height = state.bootstrap.canvas.height;
    ui.svg.setAttribute("viewBox", `${viewX} ${viewY} ${viewWidth} ${viewHeight}`);
    ui.svg.replaceChildren();

    ui.svg.appendChild(svgNode("rect", { x: start, y: 0, width: period, height, class: "repeat-zone" }));
    ui.svg.appendChild(svgNode("rect", { x: viewX, y: 0, width: viewWidth, height: 8, class: "edge-band" }));
    ui.svg.appendChild(svgNode("rect", { x: viewX, y: height - 8, width: viewWidth, height: 8, class: "edge-band" }));

    if (state.viewMode === "context") {
      [-period, period].forEach((offset) => {
        const ghost = svgNode("g", { class: "ghost", "data-repeat-offset": offset });
        drawLockedScene(ghost, offset);
        drawBranchSet(ghost, { copy: true, offset, ghost: true });
        ui.svg.appendChild(ghost);
      });
    }
    if (state.viewMode === "double") {
      const copy = svgNode("g", { class: "ghost", "data-repeat-offset": period });
      drawLockedScene(copy, period);
      drawBranchSet(copy, { copy: true, offset: period, ghost: true });
      ui.svg.appendChild(copy);
    }

    const locked = svgNode("g", { "data-layer": "locked-structure" });
    drawLockedScene(locked, 0, state.mode === "add");
    ui.svg.appendChild(locked);
    const branches = svgNode("g", { "data-layer": "editable-branches" });
    drawBranchSet(branches);
    ui.svg.appendChild(branches);
    const constraints = svgNode("g", { "data-layer": "constraints" });
    drawConstraints(constraints);
    ui.svg.appendChild(constraints);

    if (["endpoint-region", "forbidden"].includes(state.mode)) {
      const interaction = svgNode("rect", { x: viewX, y: viewY, width: viewWidth, height: viewHeight, fill: "transparent", "data-layer": "lasso-interaction" });
      interaction.addEventListener("pointerdown", startLasso);
      ui.svg.appendChild(interaction);
    }

    const controls = svgNode("g", { "data-layer": "controls" });
    drawModeControls(controls, selectedBranch());
    drawTransient(controls);
    ui.svg.appendChild(controls);
    updateStatus();
  }

  function selectBranch(curveId) {
    state.selectedId = curveId;
    if (state.viewMode === "unit") render();
    else render();
  }

  function setMode(mode) {
    if (state.drag) return;
    state.mode = mode;
    document.body.dataset.mode = mode;
    document.querySelectorAll("[data-mode]").forEach((button) => button.classList.toggle("active", button.dataset.mode === mode));
    ui.modeHint.textContent = MODE_HINTS[mode];
    if (mode === "envelope") {
      const branch = selectedBranch();
      if (!branch) setMessage("请先选择一条分支，再创建曲线包络。", "error");
      else {
        const before = currentSnapshot();
        if (ensureEnvelope(branch)) commitSnapshot(before);
      }
    }
    render();
  }

  function startPointerDrag(type, details, event) {
    event.preventDefault();
    event.stopPropagation();
    state.drag = { pointerId: event.pointerId, type, details, base: currentSnapshot(), changed: false };
    ui.svg.setPointerCapture(event.pointerId);
  }

  function startDrag(type, details, event) {
    if (!state.selectedId && type !== "region-vertex") return;
    startPointerDrag(type, details, event);
    applyDrag(canvasPoint(event));
  }

  function setControlPointWithG1(branch, baseBranch, segmentIndex, pointName, position) {
    branch.edited_cubics[segmentIndex][pointName] = position;
    if (branch.edited_cubics.length !== 2) return;
    const first = branch.edited_cubics[0];
    const second = branch.edited_cubics[1];
    const baseFirst = baseBranch.edited_cubics[0];
    const baseSecond = baseBranch.edited_cubics[1];
    const join = first.p3;
    if (segmentIndex === 0 && pointName === "p2") {
      second.p1 = add(join, scale(normalize(subtract(join, position)), distance(baseSecond.p1, baseSecond.p0)));
    } else if (segmentIndex === 1 && pointName === "p1") {
      first.p2 = add(join, scale(normalize(subtract(position, join)), -distance(baseFirst.p3, baseFirst.p2)));
    }
  }

  function applyDrag(position) {
    const drag = state.drag;
    if (!drag || ["lasso", "new", "root-range"].includes(drag.type)) return;
    restoreSnapshot(drag.base);
    const nextById = branchMap();

    if (drag.type === "region-vertex") {
      const index = Number(drag.details.index);
      if (drag.details.region === "endpoint") {
        const branch = nextById.get(state.selectedId);
        branch.constraints.endpoint_region.points[index] = position;
      } else {
        const region = state.forbiddenRegions.find((item) => item.region_id === drag.details.region);
        if (region) region.points[index] = position;
      }
    } else if (drag.type === "envelope-handle") {
      const branch = nextById.get(state.selectedId);
      const envelope = branch.constraints.curve_envelope;
      const boundary = envelope[drag.details.boundary];
      const segment = Number(drag.details.segment);
      const pointName = drag.details.point;
      boundary[segment][pointName] = position;
      if (pointName === "p3" && segment < boundary.length - 1) boundary[segment + 1].p0 = position;
      if (pointName === "p0" && segment > 0) boundary[segment - 1].p3 = position;
      updateEnvelopeAnalysis(branch);
    } else {
      const branch = nextById.get(state.selectedId);
      const baseBranch = branchMap(drag.base.branches).get(state.selectedId);
      const oldPoints = sampleCubics(baseBranch.edited_cubics);
      if (drag.type === "root") {
        const parent = parentPoints(baseBranch, drag.base.branches);
        const oldFrame = frameAtFraction(parent, baseBranch.mount_fraction);
        const newFrame = projectPoint(position, parent);
        branch.edited_cubics = transformCubics(baseBranch.edited_cubics, oldFrame, newFrame);
        branch.mount_fraction = newFrame.fraction;
        transformSpatialConstraints(branch, oldFrame, newFrame);
      } else if (drag.type === "tip") {
        const lastIndex = branch.edited_cubics.length - 1;
        const baseLast = baseBranch.edited_cubics[lastIndex];
        const delta = subtract(position, baseLast.p3);
        branch.edited_cubics[lastIndex].p3 = position;
        branch.edited_cubics[lastIndex].p2 = add(baseLast.p2, delta);
      } else if (drag.type === "control") {
        setControlPointWithG1(branch, baseBranch, Number(drag.details.segment), drag.details.point, position);
      } else if (drag.type === "join") {
        const segment = Number(drag.details.segment);
        const oldJoin = baseBranch.edited_cubics[segment].p3;
        const delta = subtract(position, oldJoin);
        branch.edited_cubics[segment].p3 = position;
        branch.edited_cubics[segment].p2 = add(baseBranch.edited_cubics[segment].p2, delta);
        branch.edited_cubics[segment + 1].p0 = position;
        branch.edited_cubics[segment + 1].p1 = add(baseBranch.edited_cubics[segment + 1].p1, delta);
      }
      propagateDescendants(state.branches, branch.curve_id, oldPoints, sampleCubics(branch.edited_cubics));
    }
    drag.changed = JSON.stringify(drag.base) !== JSON.stringify(currentSnapshot());
    render();
  }

  function startRootRange(event) {
    const branch = selectedBranch();
    if (!branch) return;
    startPointerDrag("root-range", {}, event);
    const frame = projectPoint(canvasPoint(event), parentPoints(branch));
    state.drag.startFraction = frame.fraction;
    applyRootRange(canvasPoint(event));
  }

  function applyRootRange(position) {
    const drag = state.drag;
    restoreSnapshot(drag.base);
    const branch = branchMap().get(state.selectedId);
    const frame = projectPoint(position, parentPoints(branch));
    branch.constraints.root_mount_range = [drag.startFraction, frame.fraction].sort((a, b) => a - b);
    drag.changed = true;
    render();
  }

  function lassoScope() {
    const scope = ui.forbiddenScope.value;
    const branch = selectedBranch();
    if (scope === "global") return { scope, target: null };
    if (!branch) throw new Error("当前禁区范围需要先选择一条分支");
    if (scope === "unit") return { scope, target: topUnitId(branch.curve_id) };
    if (scope === "parent") return { scope, target: branch.curve_id };
    return { scope: "level", target: branch.level };
  }

  function startLasso(event) {
    if (state.mode === "endpoint-region" && !selectedBranch()) {
      setMessage("请先选择一条分支，再圈出枝尖允许区域。", "error");
      return;
    }
    try {
      if (state.mode === "forbidden") lassoScope();
    } catch (error) {
      setMessage(error.message, "error");
      return;
    }
    startPointerDrag("lasso", { classification: state.mode === "forbidden" ? "forbidden" : "allowed" }, event);
    state.drag.points = [canvasPoint(event)];
    render();
  }

  function applyLasso(position) {
    const points = state.drag.points;
    if (!points.length || distance(points.at(-1), position) >= 1.8) points.push(position);
    render();
  }

  function newBranchCubics(frame, endpoint) {
    const vector = subtract(endpoint, frame.point);
    const length = Math.max(1, Math.hypot(vector[0], vector[1]));
    return [{
      p0: deepClone(frame.point),
      p1: add(frame.point, scale(frame.tangent, Math.min(34, length * 0.3))),
      p2: subtract(endpoint, scale(normalize(vector), Math.min(30, length * 0.26))),
      p3: deepClone(endpoint),
    }];
  }

  function startNewBranch(parentId, event) {
    if (state.mode !== "add") return;
    const parent = parentId === "backbone" ? null : branchMap().get(parentId);
    if (parent && parent.level >= 3) {
      setMessage("当前固定深度编辑器只允许新增到 L3。", "error");
      return;
    }
    startPointerDrag("new", { parentId }, event);
    const parentLine = parentGeometry(parentId, state.drag.base.branches);
    state.drag.rootFrame = projectPoint(canvasPoint(event), parentLine);
    state.drag.previewCubics = newBranchCubics(state.drag.rootFrame, canvasPoint(event));
    render();
  }

  function applyNewBranch(position) {
    state.drag.previewCubics = newBranchCubics(state.drag.rootFrame, position);
    state.drag.changed = distance(state.drag.rootFrame.point, position) >= 8;
    render();
  }

  function finishDrag(event) {
    const drag = state.drag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (ui.svg.hasPointerCapture(event.pointerId)) ui.svg.releasePointerCapture(event.pointerId);
    if (drag.type === "lasso") {
      if (drag.points.length >= 3) {
        if (drag.details.classification === "allowed") {
          const branch = selectedBranch();
          branch.constraints.endpoint_region = { type: "polygon", classification: "allowed", points: deepClone(drag.points) };
        } else {
          const binding = lassoScope();
          state.idCounter += 1;
          state.forbiddenRegions.push({
            region_id: `forbidden_${state.seed}_${Date.now()}_${state.idCounter}`,
            classification: "forbidden",
            ...binding,
            points: deepClone(drag.points),
          });
        }
        drag.changed = true;
      }
    } else if (drag.type === "new" && drag.changed) {
      const parent = drag.details.parentId === "backbone" ? null : branchMap().get(drag.details.parentId);
      const level = parent ? parent.level + 1 : 1;
      state.idCounter += 1;
      const curveId = `user_branch_${state.seed}_${Date.now()}_${state.idCounter}`;
      state.branches.push({
        curve_id: curveId,
        parent_id: drag.details.parentId,
        level,
        role: `user_level_${level}`,
        kind: "user",
        source: "user_drawn",
        target_flower_id: null,
        mount_fraction: drag.rootFrame.fraction,
        original_mount_fraction: null,
        width: [0, 3, 2.1, 1.45][level],
        status: "required",
        original_cubics: [],
        edited_cubics: deepClone(drag.previewCubics),
        constraints: { root_mount_range: null, endpoint_region: null, curve_envelope: null },
      });
      state.selectedId = curveId;
    }
    if (drag.changed) commitSnapshot(drag.base);
    state.drag = null;
    render();
  }

  function undo() {
    if (!state.undo.length || state.drag) return;
    state.redo.push(currentSnapshot());
    restoreSnapshot(state.undo.pop());
    if (state.selectedId && !branchMap().has(state.selectedId)) state.selectedId = null;
    state.dirty = true; window.parent.postMessage({type:"papera-editor-dirty",dirty:true},window.location.origin);
    render();
  }

  function redo() {
    if (!state.redo.length || state.drag) return;
    state.undo.push(currentSnapshot());
    restoreSnapshot(state.redo.pop());
    if (state.selectedId && !branchMap().has(state.selectedId)) state.selectedId = null;
    state.dirty = true; window.parent.postMessage({type:"papera-editor-dirty",dirty:true},window.location.origin);
    render();
  }

  function setBranchStatus(status) {
    const branch = selectedBranch();
    if (!branch) return;
    const before = currentSnapshot();
    branch.status = status;
    commitSnapshot(before);
    render();
  }

  function deleteSelected() {
    const branch = selectedBranch();
    if (!branch) return;
    const descendants = descendantsOf(branch.curve_id);
    if (descendants.length && !window.confirm(`该分支有 ${descendants.length} 条后代。确定删除整棵子树；取消则保留。`)) return;
    const before = currentSnapshot();
    const ids = new Set([branch.curve_id, ...descendants.map((item) => item.curve_id)]);
    state.branches = state.branches.filter((item) => !ids.has(item.curve_id));
    state.forbiddenRegions = state.forbiddenRegions.filter((region) => !ids.has(region.target));
    state.selectedId = null;
    commitSnapshot(before);
    render();
  }

  function geometryMetrics(branch) {
    const points = sampleCubics(branch.edited_cubics, 48);
    let priorSign = 0;
    let changes = 0;
    for (let index = 1; index < points.length - 1; index += 1) {
      const first = subtract(points[index], points[index - 1]);
      const second = subtract(points[index + 1], points[index]);
      const cross = first[0] * second[1] - first[1] * second[0];
      const threshold = Math.max(1e-5, Math.hypot(...first) * Math.hypot(...second) * .002);
      const sign = Math.abs(cross) < threshold ? 0 : Math.sign(cross);
      if (sign && priorSign && sign !== priorSign) changes += 1;
      if (sign) priorSign = sign;
    }
    return { sagitta: normalizedSagitta(points), changes };
  }

  function updateStatus() {
    const branch = selectedBranch();
    if (branch) {
      ui.selectionStatus.textContent = `${branch.label || "新增分枝"} · L${branch.level} · 挂接位置 ${(branch.mount_fraction*100).toFixed(1)}%`;
      const metrics = geometryMetrics(branch);
      const envelope = branch.constraints?.curve_envelope;
      ui.geometryStatus.textContent = `弓高 ${metrics.sagitta.toFixed(3)} · 曲率符号变化 ${metrics.changes}${envelope?.intersects ? " · 警告：包络边界相交" : ""}`;
    } else {
      const counts = [1, 2, 3].map((level) => state.branches.filter((item) => item.level === level).length);
      ui.selectionStatus.textContent = `${state.branches.length} 条分枝：父枝 ${counts[0]}，子枝 ${counts[1]}${counts[2] ? `，三级枝 ${counts[2]}` : ""}`;
      ui.geometryStatus.textContent = "主藤、花位与承花路径保持固定；拖动分枝进行编辑";
    }
    ui.undo.disabled = !state.undo.length;
    ui.redo.disabled = !state.redo.length;
    ui.delete.disabled = !branch;
    document.querySelectorAll("[data-status]").forEach((button) => {
      if (button.tagName === "BUTTON") button.classList.toggle("active", Boolean(branch && button.dataset.status === branch.status));
    });
    updateUnitStats();
    updateConstraintStats();
  }

  function updateUnitStats() {
    const branch = selectedBranch();
    if (!branch) {
      ui.unitStats.textContent = "选择分枝查看所属枝组";
      return;
    }
    const members = unitMembers(branch.curve_id);
    const required = members.filter((item) => item.status === "required").length;
    const optional = members.filter((item) => item.status === "optional").length;
    const forbidden = members.filter((item) => item.status === "forbidden").length;
    ui.unitStats.textContent = `当前枝组：必需 ${required} 条，可选 ${optional} 条，禁用 ${forbidden} 条。`;
  }

  function updateConstraintStats() {
    const rootRanges = state.branches.filter((branch) => branch.constraints?.root_mount_range).length;
    const endpoints = state.branches.filter((branch) => branch.constraints?.endpoint_region).length;
    const envelopes = state.branches.filter((branch) => branch.constraints?.curve_envelope).length;
    const intersections = state.branches.filter((branch) => branch.constraints?.curve_envelope?.intersects).length;
    ui.constraintStats.textContent = `根点区间 ${rootRanges} · 枝尖区 ${endpoints} · 曲线包络 ${envelopes} · 禁区 ${state.forbiddenRegions.length}${intersections ? ` · ${intersections} 个包络相交` : ""}`;
  }

  function buildPayload() {
    return {
      schema: state.bootstrap.schema,
      source: deepClone(state.bootstrap.source),
      canvas: deepClone(state.bootstrap.canvas),
      branches: deepClone(state.branches),
      forbidden_regions: deepClone(state.forbiddenRegions),
      warnings: [],
      edit_summary: {},
    };
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, {...options, credentials:"same-origin"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || result.error || `请求失败 (${response.status})`);
    return result;
  }

  async function save() {
    ui.save.disabled = true;
    setMessage("正在保存结构…");
    try {
      const result = await fetchJson("/api/v1/editor/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPayload()),
      });
      state.sessionId = result.session_id; window.parent.postMessage({type:"papera-editor-saved",item:result.item,editor_url:`/editor/?source=${window.EDITOR_SOURCE}&session=${result.session_id}`},window.location.origin);
      state.dirty = false; window.parent.postMessage({type:"papera-editor-dirty",dirty:false},window.location.origin);
      const url = new URL(window.location.href);
      url.searchParams.set("source", window.EDITOR_SOURCE);
      url.searchParams.set("session", result.session_id);
      window.history.replaceState({}, "", url);
      setMessage(`已保存，可继续编辑或下载。`, "success");
      await refreshTargets();
    } catch (error) {
      setMessage(error.message, "error");
    } finally {
      ui.save.disabled = false;
    }
  }

  function slotCurrentSeed() {
    if (!state.bootstrap) return;
    state.seedSlots.set(state.seed, {
      snapshot: currentSnapshot(), selectedId: state.selectedId, undo: deepClone(state.undo), redo: deepClone(state.redo),
      sessionId: state.sessionId, dirty: state.dirty,
    });
  }

  async function bootstrapForSeed(seed) {
    if (!state.bootstraps.has(seed)) state.bootstraps.set(seed, await fetchJson(`/api/v1/editor/sources/${encodeURIComponent(window.EDITOR_SOURCE)}`));
    return state.bootstraps.get(seed);
  }

  async function switchSeed(seed) {
    if (!ALLOWED_SEEDS.includes(seed) || seed === state.seed) return;
    slotCurrentSeed();
    const bootstrap = await bootstrapForSeed(seed);
    state.seed = seed;
    state.bootstrap = bootstrap;
    const slot = state.seedSlots.get(seed);
    if (slot) {
      restoreSnapshot(slot.snapshot);
      state.selectedId = slot.selectedId;
      state.undo = slot.undo;
      state.redo = slot.redo;
      state.sessionId = slot.sessionId;
      state.dirty = slot.dirty;
    } else {
      state.branches = deepClone(bootstrap.branches);
      state.forbiddenRegions = [];
      state.selectedId = null;
      state.undo = [];
      state.redo = [];
      state.sessionId = null;
      state.dirty = false; window.parent.postMessage({type:"papera-editor-dirty",dirty:false},window.location.origin);
    }
    state.targetComparison = null;
    ui.seedSelect.value = String(seed);
    ui.seedTitle.textContent = state.bootstrap.source.label;
    const url = new URL(window.location.href);
    url.searchParams.set("source", window.EDITOR_SOURCE);
    url.searchParams.set("seed", String(seed));
    window.history.replaceState({}, "", url);
    setMessage(`已切换到真实 record_${seed}.json`, "success");
    await refreshTargets();
    render();
  }

  async function refreshTargets() {
    try {
      state.targetIndex = await fetchJson(`/api/v1/editor/sessions?source=${encodeURIComponent(window.EDITOR_SOURCE)}`);
      ui.targetSelect.replaceChildren();
      if (!state.targetIndex.targets.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "暂无保存版本";
        ui.targetSelect.appendChild(option);
        ui.compare.disabled = true;
      } else {
        state.targetIndex.targets.forEach((target) => {
          const option = document.createElement("option");
          option.value = target.session_id;
          option.textContent = target.label;
          ui.targetSelect.appendChild(option);
        });
        if (state.sessionId) ui.targetSelect.value = state.sessionId;
        ui.compare.disabled = false;
      }
      const aggregate = state.targetIndex.aggregate;
      ui.targetStats.textContent = `此结构已保存 ${aggregate.target_count} 个版本。`;
    } catch (error) {
      ui.targetStats.textContent = error.message;
      ui.compare.disabled = true;
    }
  }

  function compareBranches(current, target) {
    const targetById = new Map(target.map((branch) => [branch.curve_id, branch]));
    const currentById = new Map(current.map((branch) => [branch.curve_id, branch]));
    const shared = [...currentById.keys()].filter((id) => targetById.has(id));
    const squared = [];
    const mounts = [];
    let statusDifferences = 0;
    shared.forEach((id) => {
      const first = currentById.get(id);
      const second = targetById.get(id);
      mounts.push(Math.abs(first.mount_fraction - second.mount_fraction));
      if (first.status !== second.status) statusDifferences += 1;
      first.edited_cubics.forEach((cubic, segment) => {
        if (!second.edited_cubics[segment]) return;
        POINT_NAMES.forEach((name) => [0, 1].forEach((axis) => squared.push(
          (cubic[name][axis] - second.edited_cubics[segment][name][axis]) ** 2,
        )));
      });
    });
    return {
      shared: shared.length,
      currentOnly: current.length - shared.length,
      targetOnly: target.length - shared.length,
      rms: squared.length ? Math.sqrt(squared.reduce((sum, value) => sum + value, 0) / squared.length) : 0,
      mountMae: mounts.length ? mounts.reduce((sum, value) => sum + value, 0) / mounts.length : 0,
      statusDifferences,
    };
  }

  async function compareTarget() {
    const sessionId = ui.targetSelect.value;
    if (!sessionId) return;
    try {
      const target = await fetchJson(`/api/v1/editor/sessions/${encodeURIComponent(sessionId)}`);
      state.targetComparison = compareBranches(state.branches, target.branches);
      const result = state.targetComparison;
      ui.targetStats.textContent = `与所选版本比较：共同分枝 ${result.shared} 条，当前新增 ${result.currentOnly} 条，当前删除 ${result.targetOnly} 条；平均挂接位置差 ${(result.mountMae*100).toFixed(1)}%，状态变化 ${result.statusDifferences} 条。`;
    } catch (error) {
      ui.targetStats.textContent = error.message;
    }
  }

  function setViewMode(mode) {
    state.viewMode = mode;
    document.querySelectorAll("[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === mode));
    if (mode === "unit" && !state.selectedId) setMessage("枝组视图需要先选择一条分枝。", "error");
    render();
  }

  function fatal(error) {
    const template = document.getElementById("error-template");
    const node = template.content.firstElementChild.cloneNode(true);
    node.textContent = `编辑器载入失败：${error.message}`;
    document.querySelector("main").replaceChildren(node);
  }

  async function initialize() {
    const query = new URLSearchParams(window.location.search);
    const requestedSession = query.get("session");
    let session = null;
    let seed = 0;
    if (requestedSession) {
      session = await fetchJson(`/api/v1/editor/sessions/${encodeURIComponent(requestedSession)}`);
      seed = Number(session.source.seed);
    }
    state.seed = seed;
    state.bootstrap = await bootstrapForSeed(seed);
    state.seed=Number(state.bootstrap.source.seed);
    state.branches = deepClone(session ? session.branches : state.bootstrap.branches);
    state.forbiddenRegions = deepClone(session ? session.forbidden_regions : []);
    state.sessionId = requestedSession;
    state.dirty = false; window.parent.postMessage({type:"papera-editor-dirty",dirty:false},window.location.origin);
    state.seedSelect = seed;
    ui.seedSelect.value = String(seed);
    ui.seedTitle.textContent = state.bootstrap.source.label;
    document.body.dataset.mode = state.mode;
    if (session) setMessage(`已载入保存的结构。`, "success");
    window.parent.postMessage({type:"papera-editor-location",url:location.pathname+location.search},location.origin);
    await refreshTargets();
    render();
  }

  ui.svg.addEventListener("pointerdown", (event) => {
    if (event.target === ui.svg || event.target.classList.contains("repeat-zone")) {
      if (state.mode === "select") state.selectedId = null;
      render();
    }
  });
  ui.svg.addEventListener("pointermove", (event) => {
    if (!state.drag || event.pointerId !== state.drag.pointerId) return;
    const point = canvasPoint(event);
    if (state.drag.type === "lasso") applyLasso(point);
    else if (state.drag.type === "new") applyNewBranch(point);
    else if (state.drag.type === "root-range") applyRootRange(point);
    else applyDrag(point);
  });
  ui.svg.addEventListener("pointerup", finishDrag);
  ui.svg.addEventListener("pointercancel", finishDrag);
  document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => setMode(button.dataset.mode)));
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => setViewMode(button.dataset.view)));
  document.querySelectorAll("button[data-status]").forEach((button) => button.addEventListener("click", () => setBranchStatus(button.dataset.status)));
  ui.undo.addEventListener("click", undo);
  ui.redo.addEventListener("click", redo);
  ui.save.addEventListener("click", save);
  ui.delete.addEventListener("click", deleteSelected);
  ui.seedSelect.addEventListener("change", () => switchSeed(Number(ui.seedSelect.value)).catch((error) => setMessage(error.message, "error")));
  ui.compare.addEventListener("click", compareTarget);
  document.getElementById("load-version").addEventListener("click", () => {
    if (!ui.targetSelect.value) return;
    if (state.dirty && !window.confirm("载入所选版本会放弃当前未保存的修改，是否载入？")) return;
    state.dirty = false;
    const url = new URL(window.location.href);
    url.searchParams.set("session", ui.targetSelect.value);
    window.location.href = url.href;
  });
  window.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key.toLowerCase() === "z") {
      event.preventDefault();
      event.shiftKey ? redo() : undo();
    } else if (event.key.toLowerCase() === "y") {
      event.preventDefault();
      redo();
    }
  });

  window.__DIRECT_EDITOR_TEST__ = {
    getState: () => deepClone({
      seed: state.seed, branches: state.branches, forbiddenRegions: state.forbiddenRegions,
      selectedId: state.selectedId, mode: state.mode, viewMode: state.viewMode, sessionId: state.sessionId,
    }),
    selectBranch,
    setMode,
    buildPayload,
  };


  async function downloadSaved(kind) {
    if (state.dirty || !state.sessionId) await save();
    if (state.dirty || !state.sessionId) return;
    const response=await fetch(`/api/v1/editor/sessions/${state.sessionId}/files/${kind}`);
    if(!response.ok){setMessage("下载失败，请重试。","error");return;}
    const blob=await response.blob();const url=URL.createObjectURL(blob);const link=document.createElement("a");link.href=url;link.download=`edited_${state.sessionId.slice(0,8)}.${kind==='geometry'?'json':kind}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function contribute() {
    const consent=document.getElementById("feedback-consent");
    if(!consent.checked){setMessage("请先勾选自愿提交说明。","error");return;}
    if(state.dirty || !state.sessionId) await save();
    if(state.dirty || !state.sessionId)return;
    try {const response=await fetchJson("/api/v1/editor/feedback",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session_id:state.sessionId,consent:true,policy_version:"2026-09-20",note:document.getElementById("feedback-note").value})});setMessage("已提交，用于后续参数分析。当前生成参数保持不变。","success");document.getElementById("feedback-status").textContent=`已提交：${response.feedback_id.slice(0,8)}`;}catch(e){setMessage(e.message,"error")}
  }
  document.querySelectorAll("[data-download]").forEach(b=>b.addEventListener("click",()=>downloadSaved(b.dataset.download)));
  document.getElementById("feedback-submit").addEventListener("click",contribute);
  window.addEventListener("beforeunload",event=>{if(state.dirty){event.preventDefault();event.returnValue=""}});

  new ResizeObserver(()=>window.parent.postMessage({type:"papera-editor-height",height:document.body.scrollHeight},window.location.origin)).observe(document.body);
  initialize().catch(fatal);
})();
