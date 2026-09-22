"""Rerun the packaged selectors on frozen candidate geometry with prespecified weights."""
from pathlib import Path
import sys,json,csv,copy,time,math,argparse
from itertools import combinations
W=Path(__file__).parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--package',type=Path,default=Path('D:/sdxl/PaperA_Data_Code_20260920'))
parser.add_argument('--output',type=Path,default=W/'results')
ARGS=parser.parse_args()
PACKAGE=ARGS.package.resolve()
sys.path.insert(0,str(PACKAGE/'code'))
import package_paths
import run_controls as control
import run_rq2_matched_budget as matched
import stage5_global_unit_selection as solver

BASE_LOCAL={'clearance_quality':.55,'length_typicality':.25,'opening_typicality':.20}
CONTRACT=control.read(matched.OURS_CONTRACT_PATH)
BASE_GLOBAL=CONTRACT['joint_objective']['weights'].copy()
SETTINGS=[dict(setting='baseline',parameter='baseline',factor=1.,local=BASE_LOCAL,global_weights=BASE_GLOBAL)]
for param in ['clearance_quality','length_typicality','opening_typicality','upgraded_lane_reward','total_parallel_penalty','peak_parallel_penalty']:
 for factor in [.8,1.2]:
  local=BASE_LOCAL.copy();weights=BASE_GLOBAL.copy()
  if param in local:
   local[param]*=factor;s=sum(local.values());local={k:v/s for k,v in local.items()}
  else:weights[param]*=factor
  SETTINGS.append(dict(setting=param+('_minus20' if factor<1 else '_plus20'),parameter=param,factor=factor,local=local,global_weights=weights))

def raw_count(c):return sum(x['level']=='L2' for x in c['curves'])
def sig(c):
 # Compare child geometry and mounts, not candidate labels; the parent is fixed.
 return tuple((x['parent_curve_id'],float(x['mount_fraction']),tuple(tuple(p) for p in x['centerline'])) for x in c['curves'] if x['level']=='L2')
def evaluate(config,q,pair,w):
 b=sum(raw_count(c) for c in config);u=sum(raw_count(c)>0 for c in config)
 quality=sum(q[c['candidate_id']]['score'] for c in config if raw_count(c))
 penalties=[pair.get(a['candidate_id'],{}).get(b['candidate_id'],0.) for a,b in combinations(config,2)]
 total=sum(penalties);peak=max(penalties,default=0.)
 score=w['local_quality']*quality+w['upgraded_lane_reward']*u-w['total_parallel_penalty']*total-w['peak_parallel_penalty']*peak-w['extra_l2_child_penalty']*max(0,b-u)
 return dict(score=score,quality=quality,B=b,U=u,total=total,peak=peak)

def main():
 out=ARGS.output.resolve();out.mkdir(parents=True,exist_ok=False)
 (out/'settings.json').write_text(json.dumps(SETTINGS,indent=2),'utf-8')
 archived=control.rows(PACKAGE/'data/evaluation/matched/objective_components.csv')
 targets={}
 for r in archived:targets.setdefault(r['case_id'],set()).add(int(r['target']))
 archive={(r['case_id'],int(r['target']),r['method']):r for r in archived}
 original=solver._joint_local_quality_by_candidate
 rows=[];start=time.perf_counter()
 # C019 first is a run-path check, retained as part of the full experiment.
 cases=['C019']+[c for c in sorted(targets) if c!='C019']
 with (out/'selections.jsonl').open('w',encoding='utf-8') as sf:
  for index,cid in enumerate(cases):
   src=PACKAGE/'data/comparison_contexts'/cid
   inv=control.read(src/'shared_stage4_inventory.json');graph=control.read(src/'shared_conflict_graph.json');meta=control.read(src/'case_input.json')
   prepared=control.prepare(inv,graph);q0=original(prepared['eligible_by_lane'])
   original_selections={};n=len(prepared['lane_ids']);umax=matched._intent_upgrade_budget(inv)
   candidate_sigs={c['candidate_id']:sig(c) for candidates in prepared['eligible_by_lane'].values() for c in candidates}
   frozen_parents={}
   for lane,cs in prepared['eligible_by_lane'].items():
    shapes=[tuple(tuple(p) for p in next(x for x in c['curves'] if x['level']=='L1')['centerline']) for c in cs]
    assert all(x==shapes[0] for x in shapes),('parent not fixed',cid,lane)
    frozen_parents[lane]=shapes[0]
   for setting in SETTINGS:
    q=copy.deepcopy(q0)
    if setting['setting']!='baseline':
     for row in q.values():row['score']=sum(setting['local'][k]*row[k] for k in BASE_LOCAL)
    # This is the helper actually imported inside the archived JBC selector.
    def experiment_quality(eligible):
     assert {c['candidate_id'] for cs in eligible.values() for c in cs}==set(q)
     return q
    solver._joint_local_quality_by_candidate=experiment_quality
    prepared['q']=q
    contract=copy.deepcopy(CONTRACT);contract['joint_objective']['weights']=setting['global_weights'].copy()
    for target in sorted(targets[cid]):
     for method in ['LG+CS','JBC']:
      t=time.perf_counter()
      if method=='JBC':selected=matched._select_ours_at_b(inv,graph,contract,target)
      else:selected=control.select(inv,graph,target,prepared,setting['global_weights'],True)
      duration=time.perf_counter()-t;config=selected['selected_candidates']
      values=evaluate(config,q,prepared['pair_penalties'],setting['global_weights'])
      base_values=evaluate(config,q0,prepared['pair_penalties'],BASE_GLOBAL)
      ids=[c['candidate_id'] for c in config];bylane={c['source_lane_id']:c for c in config}
      complete=(len(bylane)==n and len(config)==n and values['B']==target and values['U']<=umax)
      assert bool(selected['budget_attained'])==complete,('count discrepancy',cid,setting['setting'],target,method)
      conflicts=sum(b['candidate_id'] in prepared['conflict_ids'][a['candidate_id']] for a,b in combinations(config,2))
      assert conflicts==0,('conflict',cid,setting['setting'],target,method)
      assert all(c['candidate_id'] in q for c in config)
      if complete:
       reported=selected['solver_trace'].get('selected_objective',selected.get('objective',{}))
       assert abs(values['score']-reported['score'])<1e-9,('objective not consumed',cid,setting['setting'],method)
      if setting['setting']=='baseline':
       old=archive[cid,target,method]
       assert complete==(old['attained'].lower() in ['true','1'])
       assert all(abs(values[k]-float(old[k]))<1e-9 for k in ['score','quality','B','U','total','peak']),(cid,target,method,values,old)
       original_selections[target,method]={'ids':bylane,'score':base_values['score']}
      baseline=original_selections[target,method]
      changed=sum(lane not in bylane or candidate_sigs[bylane[lane]['candidate_id']]!=candidate_sigs[c['candidate_id']] for lane,c in baseline['ids'].items())
      features={k:sum(q0[c['candidate_id']][k] for c in config if raw_count(c)) for k in BASE_LOCAL}
      row=dict(setting=setting['setting'],parameter=setting['parameter'],factor=setting['factor'],case_id=cid,prototype=meta['prototype_id'],target=target,method=method,complete=complete,**values,reference_score=base_values['score'],reference_quality=base_values['quality'],reference_score_change=base_values['score']-baseline['score'],**features,parent_count=n,parent_coverage=values['U']/n,changed_parents=changed,configuration_same=changed==0,conflict_edges=conflicts,node_limit_reached=selected['solver_trace'].get('search_node_limit_reached',False),search_nodes=selected['solver_trace'].get('search_node_count',0),runtime_seconds=duration)
      rows.append(row)
      sf.write(json.dumps(dict(setting=setting['setting'],case_id=cid,target=target,method=method,selected_ids=ids),ensure_ascii=False)+'\n')
   solver._joint_local_quality_by_candidate=original
   print(f'{index+1}/108 {cid}: all 13 settings finished; {len(rows)} method-request results; elapsed {time.perf_counter()-start:.1f}s',flush=True)
   if index%12==0:control.csvout(out/'request_results.csv',rows)
 control.csvout(out/'request_results.csv',rows)
 print('FINISHED',len(rows),'rows',time.perf_counter()-start,flush=True)

if __name__=='__main__':
 try:main()
 finally:pass
