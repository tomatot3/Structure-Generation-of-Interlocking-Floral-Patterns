"""Summarize explicitly submitted edits for later review; never fit parameters."""
from pathlib import Path
import argparse
import csv
import json
import math

ROOT = Path(__file__).resolve().parents[2]

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def summarize(folder):
    meta = read(folder / 'submission.json')
    if meta.get('consent') is not True:
        return []
    session = read(folder / 'edit_session.json')
    original = read(folder / 'before.json')
    original_ids = {c['curve_id'] for unit in original['selection']['selected_candidates'] for c in unit['curves']}
    rows = []
    for branch in session['branches']:
        before, after = branch['original_cubics'], branch['edited_cubics']
        # Editor coordinates use 1000 units per repeat. Report distances in repeat widths.
        distances = [math.dist(a[key], b[key]) / 1000 for a, b in zip(before, after) for key in ('p0', 'p1', 'p2', 'p3')]
        rows.append({
            'feedback_id': meta['feedback_id'], 'prototype': meta.get('prototype', ''),
            'submitted_at': meta['submitted_at'], 'review_status': meta['review_status'],
            'curve_id': branch['curve_id'], 'parent_id': branch['parent_id'], 'level': branch['level'],
            'change': 'existing' if branch['curve_id'] in original_ids else 'added',
            'status': branch['status'],
            'root_shift_W': math.dist(before[0]['p0'], after[0]['p0']) / 1000 if before else '',
            'tip_shift_W': math.dist(before[-1]['p3'], after[-1]['p3']) / 1000 if before else '',
            'control_point_rms_W': math.sqrt(sum(x*x for x in distances) / len(distances)) if distances else '',
            'mount_fraction_delta': branch['mount_fraction'] - branch['original_mount_fraction'] if branch.get('original_mount_fraction') is not None else '',
            'constraints': json.dumps(branch.get('constraints', {}), ensure_ascii=False),
            'note': meta.get('note', ''),
        })
    remaining = {b['curve_id'] for b in session['branches']}
    for curve_id in sorted(original_ids - remaining):
        rows.append({'feedback_id': meta['feedback_id'], 'prototype': meta.get('prototype', ''),
                     'submitted_at': meta['submitted_at'], 'review_status': meta['review_status'],
                     'curve_id': curve_id, 'change': 'deleted', 'note': meta.get('note', '')})
    return rows

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, default=ROOT/'web/.runtime/editor/feedback')
    parser.add_argument('--output', type=Path, default=ROOT/'web/.runtime/feedback_review.csv')
    args = parser.parse_args()
    rows = [row for path in sorted(args.store.glob('*/submission.json')) for row in summarize(path.parent)]
    columns = ['feedback_id','prototype','submitted_at','review_status','curve_id','parent_id','level','change','status','root_shift_W','tip_shift_W','control_point_rms_W','mount_fraction_delta','constraints','note']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader(); writer.writerows(rows)
    print(f'{len(rows)} branch records from {len(set(row["feedback_id"] for row in rows))} voluntary submissions: {args.output}')

if __name__ == '__main__':
    main()
