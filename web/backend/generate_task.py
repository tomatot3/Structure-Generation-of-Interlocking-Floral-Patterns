"""One isolated job; numerical functions are the paper's existing production chain."""
from pathlib import Path
import json,sys,os,time,shutil
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'web/.runtime/packages'),str(ROOT/'code')]
from package_paths import CODE
import run_formal_cases as formal
from backbone_variation_v1 import split_generation_seeds
from run_stage3b_l1_flow import generate_prototype_case
from global_l1_flow import generate_global_l1_flow_plan
from run_batch_generation import _downstream_unit_clearance
from branch_unit_grammar_v1 import generate_unit_candidate_inventory
from stage5_global_unit_selection import build_conflict_graph,select_global_units
from evaluate_formal_cases import evaluate_case,_metric_parameters
from asset_export import export_asset
IDS={'SW1-A':'proto_sw_1_1','SW1-B':'proto_sw_1_3','SW1-C':'proto_sw_1_c','SW2-A':'proto_sw_2_3','SW3-A':'proto_sw_3_1','SW3-B':'proto_sw_3_2'}
read=lambda p:json.loads(p.read_text('utf-8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),'utf-8')
def run(folder):
 started=time.perf_counter();params=read(folder/'request.json');seed=params['seed'];pid=IDS[params['prototype']]
 domain=split_generation_seeds(seed)
 if params.get('archive_case'):
  records=read(ROOT/'data/structural_assets/case_records.json');r=next(r for r in records if r['case_id']==params['archive_case']);row=r['generation_parameters'];pid=r['prototype_id']
  params.update(prototype=r['prototype'],variant=r['backbone_variant'],density=r['density_level'],control='soft' if r['group']=='density' else 'exact',seed=int(row['production_seed']))
  seed=params['seed'];domain={k:int(row[k]) for k in domain}
 profile=str(CODE/'inputs/density_control_profile.json') if params['control']=='exact' else None
 formal._init_worker(profile);w=formal._WORKER;strategy=w['strategies'][pid]
 clearance=_downstream_unit_clearance(strategy,w['editor_l2_prior'],w['stage4_contract'])
 if params.get('condition_id'):
  base=read(folder.parent/params['condition_id']/'condition.json')
  analysis=base['analysis'];mounts=base['mounts'];strict=base['strict'];variation=base['variation'];flower_layout=base['flower_layout']
  domain['backbone_seed']=base['domain']['backbone_seed'];domain['flower_seed']=base['domain']['flower_seed']
  plan,inventory=generate_global_l1_flow_plan(strict,analysis,w['inputs'][pid]['morphology'],w['prior'],w['contract'],domain['branch_seed'],w['feedback_prior'],w['curve_geometry_prior'],mounts,
   backbone_seed=domain['backbone_seed'],flower_seed=domain['flower_seed'],unit_seed=domain['unit_seed'],prototype_strategy=strategy,backbone_variation=variation,flower_layout_plan=flower_layout,
   ordinary_density_level_override=params['density'],downstream_unit_clearance=clearance,density_control_profile=w['density_control_profile'])
 else:
  generated=generate_prototype_case(payload=w['inputs'][pid],prototype_strategy=strategy,production_seed=seed,prior=w['prior'],feedback_prior=w['feedback_prior'],curve_geometry_prior=w['curve_geometry_prior'],contract=w['contract'],stage3_plan_contract=w['stage3_plan_contract'],
   backbone_seed_override=domain['backbone_seed'],flower_seed_override=domain['flower_seed'],branch_seed_override=domain['branch_seed'],unit_seed_override=domain['unit_seed'],backbone_rho=None,prototype_variant_id=params['variant'],flower_rho=None,ordinary_density_level_override=params['density'],downstream_unit_clearance=clearance,density_control_profile=w['density_control_profile'])
  analysis=generated['variant_analysis'];mounts=generated['flower_mount_plan'];strict=generated['variant_strict'].as_dict();variation=generated['variation'];flower_layout=generated['flower_layout_plan'];plan=generated['plan']
 units=generate_unit_candidate_inventory(plan,analysis,w['prior'],w['stage4_contract'],w['editor_l2_prior'])
 graph=build_conflict_graph(units,w['stage5_contract'],w['editor_l2_prior']);selection=select_global_units(units,graph,w['stage5_contract'])
 if not selection.get('feasible'):raise RuntimeError('No feasible complete configuration')
 out=folder/'output';out.mkdir(exist_ok=True)
 for n,x in [('strict_p0_variant.json',strict),('prototype_analysis_variant.json',analysis),('flower_mount_plan.json',mounts),('global_l1_flow_plan.json',plan),('global_unit_selection.json',selection)]:write(out/n,x)
 metrics=evaluate_case(out,_metric_parameters(CODE/'inputs/metric_parameters.csv'))
 violations={k:v for k,v in metrics.items() if ('crossing_count' in k or 'violation_count' in k or 'intrusion_curve_count' in k) and float(v or 0)>0}
 if not metrics.get('mechanical_evaluation_success') or violations:raise RuntimeError('Output geometry did not satisfy the required checks')
 inkscape=os.environ.get('PAPERA_INKSCAPE') or shutil.which('inkscape')
 if not inkscape:raise RuntimeError('Set PAPERA_INKSCAPE to export PNG files')
 export_asset(out,analysis,mounts,selection,{'prototype_id':pid,'production_seed':seed,**domain,'backbone_variant_id':params['variant'],'density_level':params['density'],'source_case':folder.name},inkscape)
 write(out/'parameters.json',{**params,'domain_seeds':domain,'code_version':'2026-09-20'})
 write(folder/'condition.json',{'parameters':params,'domain':domain,'analysis':analysis,'mounts':mounts,'strict':strict,'variation':variation,'flower_layout':flower_layout})
 curves=[c for u in selection['selected_candidates'] for c in u['curves']]
 write(folder/'result.json',{'prototype':params['prototype'],'case_id':folder.name,'parameters':params,'l1':sum(c['level']=='L1' for c in curves),'l2':sum(c['level']=='L2' for c in curves),'flowers':len(analysis['flowers']),'duration':round(time.perf_counter()-started,2),'geometry_checked':True,'condition_id':params.get('condition_id'),'metrics':metrics})
 print('Completed',folder.name,flush=True)
if __name__=='__main__':run(Path(sys.argv[1]).resolve())
