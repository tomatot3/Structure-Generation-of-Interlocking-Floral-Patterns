"""Check paired IDs, image readability, and links to the archived structures."""
import json,collections
from PIL import Image,ImageChops
from package_paths import ROOT

p=ROOT/'data/paired_renderings';pairs=json.loads((p/'pairs.json').read_text('utf-8'))
records=json.loads((ROOT/'data/structural_assets/case_records.json').read_text('utf-8'));bycase={r['case_id']:r for r in records}
assert len(pairs)==len({r['pair_id'] for r in pairs})==500
ids={r['pair_id'] for r in pairs}
for sub in ['structures','renderings']:assert {x.stem for x in (p/sub).glob('*.png')}==ids
for row in pairs:
 case=bycase[row['case_id']];assert case['asset_id']==row['asset_id'] and case['prototype']==row['prototype']
 original=ROOT/'data/structural_assets'/case['input_image']
 with Image.open(original) as x,Image.open(p/row['structure_image']) as y:
  x=x.convert('RGB');y=y.convert('RGB');assert x.size==y.size and ImageChops.difference(x,y).getbbox() is None,row['pair_id']
 with Image.open(p/row['render_image']) as image:image.load()
assert len({r['asset_id'] for r in pairs})==500
print(json.dumps({'pairs':len(pairs),'matching_archived_inputs':len(pairs),'readable_renderings':len(pairs),'by_prototype':dict(collections.Counter(r['prototype'] for r in pairs))},indent=2))
