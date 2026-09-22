from pathlib import Path
import csv,json,argparse
from collections import defaultdict
import numpy as np
W=Path(__file__).parent
parser=argparse.ArgumentParser();parser.add_argument('--results',type=Path,default=W/'results');out=parser.parse_args().results
with (out/'request_results.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
numeric=['score','quality','B','U','total','peak','reference_score','reference_quality','reference_score_change','clearance_quality','length_typicality','opening_typicality','parent_count','parent_coverage','changed_parents','runtime_seconds','search_nodes']
for r in rows:
 for k in numeric:r[k]=float(r[k])
 for k in ['complete','configuration_same','node_limit_reached']:r[k]=r[k]=='True'
groups=defaultdict(dict)
for r in rows:groups[r['setting']][r['case_id'],r['target'],r['method']]=r
settings=json.loads((out/'settings.json').read_text('utf-8'));summ=[];details=[]
rng=np.random.default_rng(20260922);resamples=rng.integers(0,108,(2000,108))
def effect(pairs,key):
 by=defaultdict(list)
 for a,b in pairs:by[a['case_id']].append(b[key]-a[key])
 vals=np.array([np.median(by[k]) for k in sorted(by)])
 ci=np.quantile(np.median(vals[resamples],axis=1),[.025,.975])
 return float(np.median(vals)),float(ci[0]),float(ci[1])
for setting in settings:
 name=setting['setting'];g=groups[name]
 keys=sorted({(c,b) for c,b,m in g});pairs=[(g[c,b,'LG+CS'],g[c,b,'JBC']) for c,b in keys if g[c,b,'LG+CS']['complete'] and g[c,b,'JBC']['complete']]
 delta=np.array([b['score']-a['score'] for a,b in pairs]);fixed=np.array([b['reference_score']-a['reference_score'] for a,b in pairs])
 median,lo,hi=effect(pairs,'score');med0,lo0,hi0=effect(pairs,'reference_score')
 s=dict(setting=name,parameter=setting['parameter'],factor=setting['factor'],pairs=len(pairs),wins=int(sum(delta>1e-10)),ties=int(sum(abs(delta)<=1e-10)),losses=int(sum(delta < -1e-10)),paired_median=median,ci_low=lo,ci_high=hi,mean_gain=float(np.mean(delta)),reference_wins=int(sum(fixed>1e-10)),reference_ties=int(sum(abs(fixed)<=1e-10)),reference_losses=int(sum(fixed < -1e-10)),reference_median=med0,reference_ci_low=lo0,reference_ci_high=hi0,reference_mean_gain=float(np.mean(fixed)))
 for m,label in [('LG+CS','LGCS'),('JBC','JBC')]:
  rr=[r for r in g.values() if r['method']==m]
  s[label+'_complete']=sum(r['complete'] for r in rr)
  s[label+'_same_count']=sum(r['configuration_same'] for r in rr)
  s[label+'_same_percent']=100*s[label+'_same_count']/len(rr)
  s[label+'_changed_parent_percent']=100*sum(r['changed_parents']/r['parent_count'] for r in rr)/len(rr)
  s[label+'_reference_change_mean']=float(np.mean([r['reference_score_change'] for r in rr]))
  s[label+'_reference_change_min']=min(r['reference_score_change'] for r in rr)
  s[label+'_node_limit_count']=sum(r['node_limit_reached'] for r in rr)
  for k in ['score','quality','total','peak','parent_coverage','clearance_quality','length_typicality','opening_typicality']:
   s[label+'_'+k+'_mean']=float(np.mean([r[k] for r in rr]))
 summ.append(s)
 for a,b in pairs:
  details.append(dict(setting=name,case_id=a['case_id'],target=a['target'],delta=float(b['score']-a['score']),reference_delta=float(b['reference_score']-a['reference_score']),jbc_same=b['configuration_same'],lgcs_same=a['configuration_same'],jbc_reference_change=b['reference_score_change']))
 print(name,'win/tie/loss',s['wins'],s['ties'],s['losses'],'median',round(median,6),'CI',round(lo,6),round(hi,6),'JBC same',round(s['JBC_same_percent'],2),'reference w/t/l',s['reference_wins'],s['reference_ties'],s['reference_losses'],'JBC J0 change mean/min',round(s['JBC_reference_change_mean'],6),round(s['JBC_reference_change_min'],6))
for filename,rr in [('summary.csv',summ),('paired_differences.csv',details)]:
 with (out/filename).open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rr[0]));w.writeheader();w.writerows(rr)
(out/'summary.json').write_text(json.dumps(summ,indent=2),'utf-8')
bad=sorted([r for r in rows if r['method']=='JBC' and r['setting']!='baseline'],key=lambda r:r['reference_score_change'])
print('MOST_REFERENCE_LOSS',[(r['case_id'],r['target'],r['setting'],r['reference_score_change'],r['changed_parents']) for r in bad[:8]])
print('REFERENCE_REVERSALS',[(r['setting'],r['case_id'],r['target'],r['reference_delta']) for r in details if r['reference_delta']< -1e-10][:25])
print('ALL_complete',sum(r['complete'] for r in rows),'node_limits',sum(r['node_limit_reached'] for r in rows))
