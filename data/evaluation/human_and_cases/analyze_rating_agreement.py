"""Reproduce ordinal agreement from D1/D3 ratings.
Krippendorff (2013), Computing Krippendorff's Alpha-Reliability, pp. 5–6.
Bootstrap complete items, retaining the five fixed evaluators per item.
"""
from pathlib import Path
import json, numpy as np, csv
from itertools import combinations
W=Path(__file__).parent
D=W

def ordinal_alpha(x):
    x=np.asarray(x,int)-1
    counts=np.eye(5)[x].sum(axis=1)
    m=x.shape[1]
    o=(counts.T@counts-np.diag(counts.sum(axis=0)))/(m-1)
    n=o.sum(axis=0); total=n.sum()
    mid=np.cumsum(n)-n/2
    distance=(mid[:,None]-mid[None,:])**2
    expected=np.outer(n,n)/(total-1)
    de=(expected*distance).sum()
    return float(1-(o*distance).sum()/de) if de else float('nan')

def direct_alpha(x):
    # Direct unordered-pair expression: a separate check of coincidence accounting.
    n=np.bincount(x.ravel(),minlength=6)[1:]
    mid=np.cumsum(n)-n/2
    d=(mid[:,None]-mid[None,:])**2
    observed=np.mean([d[a-1,b-1] for row in x for a,b in combinations(row,2)])
    expected=sum(n[a]*n[b]*d[a,b] for a in range(5) for b in range(a+1,5))/(x.size*(x.size-1)/2)
    return float(1-observed/expected)

def main():
    out={'method':'ordinal Krippendorff alpha; item bootstrap with fixed evaluators',
         'bootstrap_replicates':5000,'random_seed':20260922,'metrics':{},'items':{},'render_models':{}}
    rng=np.random.default_rng(20260922)
    for filename,idkey,dims in [('D1_structure_ratings.json','sample_id',['A1','A2']),('D3_render_ratings.json','render_id',['B1','C1'])]:
        rows=json.loads((D/filename).read_text('utf-8-sig')); ids=sorted({r[idkey] for r in rows}); raters=sorted({r['evaluator'] for r in rows})
        assert len(raters)==5 and len(rows)==len(ids)*5
        lookup={(r[idkey],r['evaluator']):r for r in rows};assert len(lookup)==len(rows)
        for dim in dims:
            x=np.array([[lookup[i,r][dim] for r in raters] for i in ids],int)
            assert np.all((x>=1)&(x<=5))
            alpha=ordinal_alpha(x);assert abs(alpha-direct_alpha(x))<1e-12
            rng=np.random.default_rng(20260922)
            boot=np.array([ordinal_alpha(x[rng.integers(0,len(x),len(x))]) for _ in range(5000)])
            diff=np.array([abs(a-b) for row in x for a,b in combinations(row,2)])
            ranges=np.ptp(x,axis=1)
            out['metrics'][dim]={'items':len(x),'ratings':x.size,'alpha':alpha,'ci95':np.nanquantile(boot,[.025,.975]).tolist(),
                'undefined_bootstrap':int(np.isnan(boot).sum()),'exact_pair_agreement':float(np.mean(diff==0)),
                'within_one_pair_agreement':float(np.mean(diff<=1)),'unanimous_items':int((ranges==0).sum()),
                'items_range_at_most_one':int((ranges<=1).sum()),'score_counts':{str(i):int((x==i).sum()) for i in range(1,6)},
                'rater_means':dict(zip(raters,x.mean(axis=0).tolist()))}
            out['items'][dim]=[{idkey:i,'scores':dict(zip(raters,row.tolist())),'mean':float(row.mean()),'median':float(np.median(row)),
                               'range':int(row.max()-row.min())} for i,row in zip(ids,x)]
        if idkey=='render_id':
            for model in sorted({r['model'] for r in rows}):
                group=[r for r in rows if r['model']==model]
                out['render_models'][model]={'images':len({r[idkey] for r in group}),**{d:float(np.mean([r[d] for r in group])) for d in dims}}
            b=np.array([np.mean([r['B1'] for r in rows if r[idkey]==i]) for i in ids])
            c=np.array([np.mean([r['C1'] for r in rows if r[idkey]==i]) for i in ids])
            out['render_discrepancy']={'appearance_higher':int((b>c).sum()),'equal':int((b==c).sum()),'preservation_higher':int((b<c).sum()),
               'image_scores':[{idkey:i,'B1':float(bv),'C1':float(cv)} for i,bv,cv in zip(ids,b,c)]}
    (W/'D7_rating_agreement.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({k:v for k,v in out.items() if k!='items'},ensure_ascii=False,indent=2))
    print('LARGE_DISAGREEMENTS',json.dumps({d:[r for r in rr if r['range']>1] for d,rr in out['items'].items()},ensure_ascii=False))

if __name__=='__main__': main()
