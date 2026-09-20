"""Create browsing thumbnails; original image files remain unchanged."""
from pathlib import Path
from PIL import Image
import json
ROOT=Path(__file__).resolve().parents[2]
output=ROOT/'web/.runtime/thumbnails';output.mkdir(parents=True,exist_ok=True)
rows=json.loads((ROOT/'data/paired_renderings/pairs.json').read_text('utf-8'))
for row in rows:
 dst=output/(row['pair_id']+'.webp')
 if dst.exists():continue
 with Image.open(ROOT/'data/paired_renderings'/row['render_image']) as im:
  im=im.convert('RGB');im.thumbnail((960,360));im.save(dst,'WEBP',quality=84)
print('Thumbnails:',len(list(output.glob('*.webp'))))
