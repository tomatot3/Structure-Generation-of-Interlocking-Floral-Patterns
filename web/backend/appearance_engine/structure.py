"""Source geometry for structure references and generation conditions.

Recovered ink guides describe appearance deformation, not the structural model.
This module preserves authored cubics (including flower supports), applies the
case registration, and transfers deliberate editor changes to that baseline.
It neither changes the appearance graph nor rewrites recovered material paths.
"""
from html import escape

import numpy as np


def _fractions(points):
    points = np.asarray(points, float)
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    return distance / max(float(distance[-1]), 1e-12)


def _samples(c, item):
    if item['cubics'] is not None:
        return c.sample_bezier(item['cubics'], 64)
    return item['points']


def _copy(item):
    return {key: value.copy() if value is not None else None
            for key, value in item.items()}


def _set_controls(c, item, points):
    if item['cubics'] is not None:
        item['cubics'] = np.asarray(points).reshape(item['cubics'].shape)
        item['points'] = c.sample_bezier(item['cubics'], 32)
    else:
        item['points'] = np.asarray(points)


def _controls(item):
    if item['cubics'] is not None:
        return item['cubics'].reshape(-1, 2)
    return item['points']


def _apply(c, item, ops):
    points = _controls(item).copy()
    for old, new, mode in ops:
        points = c.apply_motion(points, old, new, mode)
    _set_controls(c, item, points)


def _shift(c, item, delta):
    _set_controls(c, item, _controls(item) + delta)


def _source_cubics(s, o):
    if o.get('source_cubic_segments'):
        return o['source_cubic_segments']
    raw = s.get('source_structure', {})
    source_id = o.get('source_id', o['id'])
    for mount in raw.get('flower_mount_plan', {}).get('mounts', []):
        if mount.get('mount_id') == source_id:
            return mount.get('cubic_segments')
    for unit in raw.get('selection', {}).get('selected_candidates', []):
        for curve in unit.get('curves', []):
            if curve.get('curve_id') == source_id:
                return curve.get('cubic_segments')
    return None


def _parent_changed(s, o, by):
    """Distinguish a deliberate topology correction from source rounding."""
    if o.get('structural_reference') is not None or not o.get('parent'):
        return False
    raw = s.get('source_structure', {})
    source_id = o.get('source_id', o['id'])
    actual = by[o['parent']].get('source_id', o['parent'])
    for unit in raw.get('selection', {}).get('selected_candidates', []):
        for curve in unit.get('curves', []):
            if curve.get('curve_id') == source_id:
                original = curve.get('parent_curve_id') or 'vine'
                return actual != original
    return False


def _baseline(c, s, o):
    frozen = o.get('structural_reference')
    if frozen is not None:
        return {'points': np.asarray(frozen['points'], float),
                'cubics': np.asarray(frozen['cubics'], float)
                if frozen.get('cubics') is not None else None,
                'radii': np.asarray(frozen.get('radii', o.get('radii')), float)
                if o['role'] == 'flower' else None}

    source = np.asarray(o['source_points'], float)
    transform = s.get('source_coordinate_transform', {})
    affine = transform.get('affine') or s.get('periodic_registration', {}).get('source_to_tile')
    if affine is not None:
        matrix = np.asarray(affine, float)
    elif 'scale' in transform:
        scale = float(transform['scale'])
        matrix = np.array([[scale, 0, 0], [0, scale, -float(transform.get('y_offset', 0)) * scale], [0, 0, 1]])
    else:
        offsets = np.asarray(o['registration_offsets'], float)
        anchors = c.resample(source, len(offsets))
        design = np.c_[anchors, np.ones(len(anchors))]
        target = anchors * c.W + offsets
        if np.linalg.matrix_rank(design) == 3:
            matrix = np.vstack([np.linalg.lstsq(design, target, rcond=None)[0].T, [0, 0, 1]])
        else:
            shift = np.mean(offsets, axis=0)
            matrix = np.array([[c.W, 0, shift[0]], [0, c.W, shift[1]], [0, 0, 1]])
    # A declared source-to-tile transform is authoritative. Recovery alignment
    # can overwrite registration_offsets with pixel traces; those offsets must
    # never become structural detail. Legacy scenes without a source transform
    # retain only a single affine calibration, not the individual marker noise.

    def register(points):
        points = np.asarray(points, float)
        return points @ matrix[:2, :2].T + matrix[:2, 2]

    segments = _source_cubics(s, o)
    cubics = None
    if segments:
        raw = np.asarray([[segment[key] for key in ('p0', 'p1', 'p2', 'p3')]
                          for segment in segments], float)
        cubics = register(raw.reshape(-1, 2)).reshape(raw.shape)
    points = c.sample_bezier(cubics, 32) if cubics is not None else register(source)
    return {'points': points, 'cubics': cubics,
            'radii': np.asarray(o['radii'], float) if o['role'] == 'flower' else None}


def _project(c, line, point, periodic):
    shifts = (-c.W, 0., c.W) if periodic else (0.,)
    candidates = []
    for shift in shifts:
        local = np.asarray(point) - [shift, 0.]
        fraction = float(c.nearest([local], line)[0][0])
        root, tangent = c.point_at(line, fraction)
        root = root + [shift, 0.]
        candidates.append((float(np.linalg.norm(root - point)), fraction, shift, root, tangent))
    return min(candidates, key=lambda item: item[0])


def _transfer_delta(c, item, reference, delta):
    """Transfer legacy marker motion without importing its pixel centerline."""
    controls = _controls(item)
    fractions = c.nearest(controls, _samples(c, item))[0]
    reference_fraction = _fractions(reference)
    displacement = np.stack([np.interp(fractions, reference_fraction, delta[:, axis])
                             for axis in range(2)], axis=1)
    _set_controls(c, item, controls + displacement)


def _local_edit(c, o, e, item):
    """Remove the author's parent frame before a structural parent is applied."""
    role = o['role']
    if 'curve' in e and role in ('parent', 'child', 'ornament'):
        target = np.asarray(e['curve'], float)
        author_ops = e.get('parent_ops', [])
        target = c.rebase_parent(target.reshape(-1, 2), author_ops, []).reshape(target.shape)
        if e.get('curve_basis') == 'source-cubic-v1':
            author_guide = c.guide(o).copy()
            for old, new, mode in author_ops:
                author_guide = c.apply_motion(author_guide, np.asarray(old), np.asarray(new), mode)
            reference = c.registered_cubics(o, author_guide)
            # The editor fits displayed handles after parent motion. Undo the
            # author's frame for BOTH target and its corresponding reference;
            # inverse-warping only the target would turn fit error into an edit.
            reference = c.rebase_parent(reference.reshape(-1, 2), author_ops, []).reshape(reference.shape)
            if item['cubics'] is not None and target.shape == item['cubics'].shape == reference.shape:
                _set_controls(c, item, (item['cubics'] + target - reference).reshape(-1, 2))
            else:
                old = c.sample_bezier(reference, 32)
                new = c.sample_bezier(target, 32)
                if len(old) != len(new):
                    new = c.resample(new, len(old))
                _transfer_delta(c, item, old, new - old)
        else:
            old = c.sample_bezier(c.bezier_segments(c.guide(o)), 4)
            new = c.sample_bezier(target, 4)
            if len(new) != len(old):
                raise ValueError('Bezier segment count mismatch')
            new[:5] = old[:5]
            _transfer_delta(c, item, old, new - old)
    elif 'points' in e:
        if role in ('main', 'support', 'flower') and not e.get('unlocked'):
            return
        old = c.guide(o)
        new = np.asarray(e['points'], float).copy()
        if new.shape != old.shape:
            raise ValueError('Control-point count mismatch')
        if role in ('parent', 'child', 'ornament'):
            new[:2] = old[:2]
        _transfer_delta(c, item, old, new - old)
    if role == 'ornament' and e.get('scale', 1) != 1:
        points = _controls(item).copy()
        points[2:] = points[1] + (points[2:] - points[1]) * e['scale']
        _set_controls(c, item, points)
    if role == 'flower':
        item['radii'] *= e.get('scale', 1)


def geometry(c, s, edits=None):
    """Return current source-based geometry in registered tile coordinates.

    Each object has points, optional exact source cubics, and flower radii. A
    structural_reference field is an already registered frozen baseline, used
    by package import and render-input snapshots without repeating registration.
    """
    edits = edits or {}
    by = {o['id']: o for o in s['objects']}
    baseline = {id: _baseline(c, s, o) for id, o in by.items()}
    result, chains = {}, {}
    periodic = bool(s.get('periodic_registration'))

    def visit(id):
        if id in result:
            return result[id]
        o = by[id]
        e = edits.get(id, {})
        parent = o.get('parent')
        ops = []
        if parent:
            visit(parent)
            ops = chains[parent]
        item = _copy(baseline[id])
        _local_edit(c, o, e, item)
        _apply(c, item, ops)

        # Transport the authored root location along the actual structural
        # parent. Roots are not placed on a recovered pixel trace or on a
        # neighbour that happens to be geometrically closer.
        changed = bool(ops) or bool(e.get('curve') is not None or e.get('points') is not None) or _parent_changed(s, o, by)
        if parent and changed and o['role'] != 'flower':
            source_line = _samples(c, baseline[parent])
            _, fraction, shift, _, _ = _project(c, source_line, baseline[id]['points'][0], periodic)
            if 'mount_fraction' in e:
                appearance_line = c.smooth_curve(c.guide(by[parent]))
                for old, new, mode in e.get('parent_ops', []):
                    appearance_line = c.apply_motion(appearance_line, np.asarray(old), np.asarray(new), mode)
                original_root = c.guide(o)[0:1].copy()
                for old, new, mode in e.get('parent_ops', []):
                    original_root = c.apply_motion(original_root, np.asarray(old), np.asarray(new), mode)
                original_fraction = _project(c, appearance_line, original_root[0], periodic)[1]
                fraction = float(np.clip(fraction + float(e['mount_fraction']) - original_fraction, .001, .985))
            root, _ = c.point_at(_samples(c, result[parent]), fraction)
            _shift(c, item, root + [shift, 0.] - item['points'][0])

        if o['role'] == 'support' and o.get('flower') in by:
            flower = o['flower']
            visit(flower)
            center = baseline[flower]['points'][0]
            end = result[flower]['points'][0] + (baseline[id]['points'][-1] - center) * edits.get(flower, {}).get('scale', 1)
            delta = end - item['points'][-1]
            if np.linalg.norm(delta) > 1e-10:
                if item['cubics'] is not None:
                    # Move the distal handle with its endpoint; keep source
                    # joins and the inherited root untouched.
                    item['cubics'][-1, 2:] += delta
                    item['points'] = c.sample_bezier(item['cubics'], 32)
                else:
                    item['points'] += _fractions(item['points'])[:, None] ** 3 * delta

        inherited = _copy(baseline[id])
        _apply(c, inherited, ops)
        before, after = _samples(c, inherited), _samples(c, item)
        if not np.allclose(before, after, atol=1e-9, rtol=0):
            ops = ops + [(before, after, None)]
        chains[id] = ops
        result[id] = item
        return item

    for id in by:
        visit(id)
    return result


def render(c, s, edits=None):
    edits = edits or {}
    shapes = geometry(c, s, edits)
    height = s.get('height', c.H)
    parts = [f'<svg xmlns="{c.NS}" width="{c.W}" height="{height}" viewBox="0 0 {c.W} {height}">',
             '<rect width="100%" height="100%" fill="white"/>']
    for o in s['objects']:
        if c.hidden(o['id'], s, edits) or o['role'] == 'unassigned':
            continue
        item = shapes[o['id']]
        attributes = f'data-object="{escape(o["id"], quote=True)}" data-role="{escape(o["role"], quote=True)}" data-parent="{escape(o.get("parent") or "", quote=True)}"'
        color = c.COLORS[o['role']]
        if o['role'] == 'flower':
            x, y = item['points'][0]
            rx, ry = item['radii']
            element = f'<ellipse {attributes} cx="{x:.6f}" cy="{y:.6f}" rx="{rx:.6f}" ry="{ry:.6f}" stroke="{color}" stroke-width="2" fill="none"/>'
        else:
            if item['cubics'] is not None:
                curves = item['cubics']
                path = f'M{curves[0,0,0]:.6f},{curves[0,0,1]:.6f}'
                path += ''.join(' C' + ' '.join(f'{x:.6f},{y:.6f}' for x, y in curve[1:]) for curve in curves)
            else:
                path = 'M' + ' L'.join(f'{x:.6f},{y:.6f}' for x, y in item['points'])
            element = f'<path {attributes} d="{path}" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
        shifts = (-c.W, 0, c.W) if s.get('periodic_registration') else (0,)
        parts.extend(f'<g transform="translate({shift},0)">{element}</g>' for shift in shifts)
    parts.append('</svg>')
    return ''.join(parts)
