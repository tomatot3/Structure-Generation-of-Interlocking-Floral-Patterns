"""Run Stage II selectors on the archived shared candidate spaces."""
import argparse,json,csv,time
from pathlib import Path
from package_paths import ROOT
import run_controls as control
import run_rq2_matched_budget as matched

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',default='C019');p.add_argument('--all',action='store_true');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False)
 rows=list(csv.DictReader((ROOT/'data/evaluation/matched/objective_components.csv').open(encoding='utf-8')))
 targets={}
 for r in rows:targets.setdefault(r['case_id'],set()).add(int(r['target']))
 cids=sorted(targets) if a.all else [a.case]
 contract=control.read(matched.OURS_CONTRACT_PATH);w=contract['joint_objective']['weights'];out=[]
 archived={(r['case_id'],int(r['target']),r['method']):r for r in rows}
 for cid in cids:
  src=ROOT/'data/comparison_contexts'/cid
  inv=control.read(src/'shared_stage4_inventory.json');graph=control.read(src/'shared_conflict_graph.json');prepared=control.prepare(inv,graph)
  for target in sorted(targets[cid]):
   for method in ['LocalGreedy','LG+Count','LG+CS','JBC']:
    start=time.perf_counter()
    if method=='LocalGreedy':sel=matched._select_localgreedy_at_b(inv,graph,target)
    elif method=='JBC':sel=matched._select_ours_at_b(inv,graph,contract,target)
    else:sel=control.select(inv,graph,target,prepared,w,method=='LG+CS')
    elapsed=time.perf_counter()-start
    values=control.components(sel['selected_candidates'],prepared['q'],prepared['pair_penalties'],w)
    old=archived[cid,target,method]
    equal=all(abs(float(values[k])-float(old[k]))<1e-10 for k in ['score','quality','B','U','total','peak']) and bool(sel['budget_attained'])==(old['attained'].lower() in ['true','1'])
    if not equal:raise RuntimeError(f'Archived comparison differs: {cid} B={target} {method}')
    record={'case_id':cid,'target':target,'method':method,'attained':sel['budget_attained'],**values,'runtime_seconds':elapsed,'archive_equal':equal};out.append(record)
    folder=a.output/cid;folder.mkdir(exist_ok=True);control.save(folder/f'B{target}_{method}.json',sel)
  print(cid,'reproduced',len(targets[cid])*4,'method-request results',flush=True)
 control.csvout(a.output/'objective_components.csv',out)

if __name__=='__main__':main()
