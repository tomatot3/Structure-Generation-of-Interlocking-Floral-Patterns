"""Recompute the main numerical comparisons from the archived observations."""
import argparse,json,csv,collections
from pathlib import Path
import numpy as np
from package_paths import ROOT

def rows(relative):return list(csv.DictReader((ROOT/'data/evaluation'/relative).open(encoding='utf-8-sig')))
def effect(pairs):
 grouped=collections.defaultdict(list)
 for cid,value in pairs:grouped[cid].append(value)
 values=np.array([np.median(grouped[cid]) for cid in sorted(grouped)])
 boot=np.median(np.random.default_rng(20260825).choice(values,size=(2000,len(values)),replace=True),axis=1)
 return {'contexts':len(values),'median':float(np.median(values)),'CI95':np.quantile(boot,[.025,.975]).tolist()}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 comp=rows('matched/objective_components.csv');groups=collections.defaultdict(dict)
 for r in comp:groups[r['case_id'],r['target']][r['method']]=r
 pairs=[(cid,g['LG+CS'],g['JBC']) for (cid,_),g in groups.items()]
 delta=lambda x,y,k:float(y[k])-float(x[k])
 parent_counts={cid:len(json.loads((ROOT/'data/comparison_contexts'/cid/'methods/Ours/global_l1_flow_plan.json').read_text('utf-8'))['lanes']) for cid in {p[0] for p in pairs}}
 stage2={'requests':len(pairs),'completion':{m:sum(r['attained'].lower() in ['true','1'] for r in comp if r['method']==m) for m in ['LocalGreedy','LG+Count','LG+CS','JBC']},'objective_improved':sum(delta(x,y,'score')>1e-10 for _,x,y in pairs),'objective_tied':sum(abs(delta(x,y,'score'))<=1e-10 for _,x,y in pairs),'objective_difference':effect((cid,delta(x,y,'score')) for cid,x,y in pairs),'cotravel_reduced':sum(delta(x,y,'total') < -1e-10 for _,x,y in pairs),'cotravel_equal':sum(abs(delta(x,y,'total'))<=1e-10 for _,x,y in pairs),'cotravel_increased':sum(delta(x,y,'total')>1e-10 for _,x,y in pairs)}
 stage2['parents_with_children']={m:float(np.mean([float(g[m]['U']) for g in groups.values()])) for m in ['LG+CS','JBC']}
 stage2['parent_coverage_percent']={m:float(np.mean([100*float(g[m]['U'])/parent_counts[cid] for (cid,_),g in groups.items()])) for m in ['LG+CS','JBC']}
 matrix=rows('matrix_c/evaluated_results.csv');hcg=rows('controls/l1/results.csv');common={r['case_id'] for r in hcg if int(r['completed'])}
 stage1={'contexts':len(hcg),'completed':{'IndependentCurve':sum(int(r['l1_generation_success']) for r in matrix if r['method']=='IndependentCurve'),'HardConstraintGreedy':len(common),'GlobalL1':sum(int(r['l1_generation_success']) for r in matrix if r['method']=='Ours')},'common_contexts':len(common)}
 stage1['mean_root_coverage']={'IndependentCurve':float(np.mean([float(r['root_coverage_qcov']) for r in matrix if r['method']=='IndependentCurve' and r['case_id'] in common])),'HardConstraintGreedy':float(np.mean([float(r['root_coverage_qcov']) for r in hcg if r['case_id'] in common])),'GlobalL1':float(np.mean([float(r['root_coverage_qcov']) for r in matrix if r['method']=='Ours' and r['case_id'] in common]))}
 lookup={r['case_id']:float(r['root_coverage_qcov']) for r in hcg}
 stage1['root_coverage_difference']=effect((r['case_id'],float(r['root_coverage_qcov'])-lookup[r['case_id']]) for r in matrix if r['method']=='Ours' and r['case_id'] in common)
 ratings={}
 for name,fields in [('D1_structure_ratings.json',['A1','A2']),('D3_render_ratings.json',['B1','C1'])]:
  obs=json.loads((ROOT/'data/evaluation/human_and_cases'/name).read_text('utf-8'))
  ratings[name]={'records':len(obs),'mean':{k:float(np.mean([r[k] for r in obs])) for k in fields}}
 trips=rows('default/default_triplets.csv')
 summary={'stage_I':stage1,'stage_II':stage2,'soft_density':{'triplets':len(trips),'common_domain':sum(int(r['same_resource_domain']) for r in trips),'resource_changes':dict(collections.Counter(r['D_class'] for r in trips))},'ratings':ratings}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(summary,indent=2),'utf-8');print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
