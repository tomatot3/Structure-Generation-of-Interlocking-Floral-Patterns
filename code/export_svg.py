"""Export a role-labelled SVG directly from an archived structural asset."""
import argparse,json
from pathlib import Path
from package_paths import ROOT
from export_batch_svgs import render_case_svg
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--asset',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
obj=json.loads((ROOT/'data/structural_assets/assets'/a.asset/'structure.json').read_text('utf-8'))
records=json.loads((ROOT/'data/structural_assets/asset_index.json').read_text('utf-8'))
record=next(r for r in records if r['asset_id']==a.asset)
svg=render_case_svg(obj['analysis'],obj['flower_mount_plan'],obj['selection'],{**record['generation_parameters'],'source_case':a.asset,'backbone_variant_id':record['backbone_variant']},repeat='triple',palette='role')
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(svg,'utf-8');print(a.output)
