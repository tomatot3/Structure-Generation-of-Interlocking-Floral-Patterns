"""Extract flower-vine relationships from six archived structures for the Research page."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[2]
pairs=json.loads((ROOT/'data/paired_renderings/pairs.json').read_text('utf-8'))
diagrams=[]
for prototype in ['SW1-A','SW1-B','SW1-C','SW2-A','SW3-A','SW3-B']:
    pair=next(row for row in pairs if row['prototype']==prototype)
    geometry=json.loads((ROOT/'data/structural_assets/assets'/pair['asset_id']/'structure.json').read_text('utf-8'))
    diagrams.append({'prototype':prototype,'asset_id':pair['asset_id'],'pair_id':pair['pair_id'],
                     'backbone':[row['point'] for row in geometry['analysis']['backbone']['samples']],
                     'flowers':[{key:flower[key] for key in ['center','rx','ry']} for flower in geometry['analysis']['flowers']],
                     'supports':[mount['centerline'] for mount in geometry['flower_mount_plan']['mounts']]})
target=ROOT/'web/frontend/public/research/configurations.json'
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(diagrams,ensure_ascii=False,separators=(',',':')),'utf-8')
print('Six relationship diagrams extracted from archived geometry:',target)
