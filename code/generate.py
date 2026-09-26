"""Generate new structures or regenerate recorded cases using their seeds and controls."""
import argparse,json
from pathlib import Path
from package_paths import ROOT,CODE
import run_formal_cases as formal
from asset_export import export_asset
from backbone_variation_v1 import split_generation_seeds,validate_seed
from evaluate_formal_cases import evaluate_case,_metric_parameters

def geometry_difference(current,archived):
 """Compare coordinates and parent geometry; tolerate float64 round-off."""
 def canonical(obj):
  curves=[c for u in obj['selection']['selected_candidates'] for c in u['curves']]
  parents={c['curve_id']:c['cubic_segments'] for c in curves}
  cc=[{'level':c['level'],'segments':c['cubic_segments'],'centerline':c['centerline'],'parent_segments':parents.get(c.get('parent_curve_id'))} for c in curves]
  cc.sort(key=lambda c:json.dumps(c,sort_keys=True))
  mounts=[{k:m[k] for k in ['flower_id','centerline','cubic_segments'] if k in m} for m in obj['flower_mount_plan']['mounts']]
  return {'curves':cc,'backbone':obj['analysis']['backbone']['samples'],'flowers':obj['analysis']['flowers'],'mounts':mounts}
 errors=[]
 def walk(x,y):
  if isinstance(x,(int,float)) and not isinstance(x,bool) and isinstance(y,(int,float)):
   errors.append(abs(x-y));return True
  if isinstance(x,dict) and isinstance(y,dict):return x.keys()==y.keys() and all(walk(x[k],y[k]) for k in x)
  if isinstance(x,list) and isinstance(y,list):return len(x)==len(y) and all(walk(u,v) for u,v in zip(x,y))
  return x==y
 identities_equal=walk(canonical(current),canonical(archived))
 maximum=max(errors,default=0.)
 return identities_equal and maximum<=1e-12,maximum

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--case',action='append',help='Original case ID; repeat this option for several cases.')
 p.add_argument('--group',choices=['density','exact','seed'],help='Run every recorded case in a group.')
 p.add_argument('--prototype',choices=['SW1-A','SW1-B','SW1-C','SW2-A','SW3-A','SW3-B'],help='Generate new cases from a procedural prototype.')
 p.add_argument('--seed',type=int,action='append',help='New production seed; repeat for a batch.')
 p.add_argument('--variant',choices=['expanded','compact','swept'],default='expanded')
 p.add_argument('--density',choices=['simple','medium','rich'],default='medium')
 p.add_argument('--control',choices=['soft','exact'],default='soft')
 p.add_argument('--inkscape',help='Optional Inkscape executable, or inkscape if available on PATH; exports the conditioning PNG.')
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--compare-archive',action='store_true',help='Compare regenerated coordinates and parent links with the archived asset.')
 a=p.parse_args()
 if sum(bool(v) for v in [a.case,a.group,a.prototype])!=1:p.error('Choose --case, --group, or --prototype.')
 if a.prototype:
  if not a.seed:p.error('--prototype requires one or more --seed values.')
  if a.compare_archive:p.error('New seeds have no archived case to compare.')
  ids={'SW1-A':'proto_sw_1_1','SW1-B':'proto_sw_1_3','SW1-C':'proto_sw_1_c','SW2-A':'proto_sw_2_3','SW3-A':'proto_sw_3_1','SW3-B':'proto_sw_3_2'}
  selected=[]
  for seed in dict.fromkeys(a.seed):
   validate_seed(seed,'production_seed')
   cid=f'{a.prototype}_{a.variant}_{a.density}_{a.control}_{seed}'
   row={'case_id':cid,'matrix_id':'CUSTOM','prototype_id':ids[a.prototype],
        'production_seed':str(seed),'backbone_variant':a.variant,'density_level':a.density,
        'replicate':'1',**{k:str(v) for k,v in split_generation_seeds(seed).items()}}
   selected.append({'case_id':cid,'group':'density' if a.control=='soft' else 'exact',
                    'prototype_id':ids[a.prototype],'backbone_variant':a.variant,'generation_parameters':row})
 else:
  if a.seed:p.error('--seed is used with --prototype.')
  records=json.loads((ROOT/'data/structural_assets/case_records.json').read_text('utf-8'))
  selected=[r for r in records if r['case_id'] in a.case] if a.case else [r for r in records if r['group']==a.group]
  if a.case and set(a.case)!={r['case_id'] for r in selected}:p.error('Unknown case ID.')
 a.output.mkdir(parents=True,exist_ok=False)
 metrics=_metric_parameters(CODE/'inputs/metric_parameters.csv');profile=None;results=[]
 for r in selected:
  wanted=None if r['group']=='density' else str(CODE/'inputs/density_control_profile.json')
  if not formal._WORKER or wanted!=profile:formal._init_worker(wanted);profile=wanted
  row=r['generation_parameters'];result=formal._run_case(row,a.output,False)
  folder=a.output/result['case_dir']
  read=lambda n:json.loads((folder/n).read_text('utf-8'))
  analysis=read('prototype_analysis_variant.json');mount=read('flower_mount_plan.json');selection=read('global_unit_selection.json')
  export_asset(folder,analysis,mount,selection,{**row,'source_case':r['case_id'],'backbone_variant_id':r['backbone_variant']},a.inkscape)
  result['geometry_metrics']=evaluate_case(folder,metrics)
  if a.compare_archive:
   archive=json.loads((ROOT/'data/structural_assets'/r['asset_directory']/'structure.json').read_text('utf-8'))
   same,error=geometry_difference({'analysis':analysis,'flower_mount_plan':mount,'selection':selection},archive)
   result['archived_geometry_equal']=same;result['maximum_coordinate_difference']=error
   if not same:raise RuntimeError(f"Regenerated geometry differs from archived case {r['case_id']}")
  results.append(result);print(r['case_id'],json.dumps({'L1':result['ordinary_l1_count'],'L2':result['selected_l2_count'],'archive_equal':result.get('archived_geometry_equal')}),flush=True)
 (a.output/'results.json').write_text(json.dumps(results,indent=2),'utf-8')

if __name__=='__main__':main()
