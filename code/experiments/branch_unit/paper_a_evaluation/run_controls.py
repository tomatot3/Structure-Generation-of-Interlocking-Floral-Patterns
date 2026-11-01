"""Frozen Batch4 selection-only controls; original archives remain read-only."""
from pathlib import Path
from collections import defaultdict
from itertools import combinations
import csv,json,sys,random,time,argparse,copy
from concurrent.futures import ProcessPoolExecutor,as_completed
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
R=ROOT/'crossing_fix_20260907/results'
E=Path(__file__).resolve().parent
D=E.parent/'dynamic'
sys.path[:0]=[str(E),str(D)]
import run_rq2_matched_budget as mb
from stage5_global_unit_selection import _joint_local_quality_by_candidate

METHODS=('LocalGreedy + Count','LocalGreedy + Count + Score')
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def csvout(p,rr):
    p.parent.mkdir(parents=True,exist_ok=True)
    fields=list(dict.fromkeys(k for r in rr for k in r))
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rr)

def components(config,q,pairs,w):
    b,u=mb._selection_budget({'selected_candidates':config})
    qq=sum(q[c['candidate_id']]['score'] for c in config if mb._actual_l2_count(c))
    pp=[pairs[a['candidate_id']].get(b['candidate_id'],0.) for a,b in combinations(config,2)]
    total=sum(pp);peak=max(pp,default=0.)
    score=w['local_quality']*qq+w['upgraded_lane_reward']*u-w['total_parallel_penalty']*total-w['peak_parallel_penalty']*peak-w['extra_l2_child_penalty']*max(0,b-u)
    return dict(score=score,quality=qq,B=b,U=u,total=total,peak=peak)

def replacement_delta(config,old,new,q,pairs,w):
    # Recompute peak on retained pairs plus new pairs, so an old peak can disappear.
    rest=[c for c in config if c['source_lane_id']!=old['source_lane_id']]
    oldp=[pairs[old['candidate_id']].get(c['candidate_id'],0.) for c in rest]
    newp=[pairs[new['candidate_id']].get(c['candidate_id'],0.) for c in rest]
    retained=[pairs[a['candidate_id']].get(b['candidate_id'],0.) for a,b in combinations(rest,2)]
    b,u=mb._selection_budget({'selected_candidates':config})
    ob,nb=mb._actual_l2_count(old),mb._actual_l2_count(new)
    du=int(nb>0)-int(ob>0);db=nb-ob
    dq=(q[new['candidate_id']]['score'] if nb else 0.)-(q[old['candidate_id']]['score'] if ob else 0.)
    return (w['local_quality']*dq+w['upgraded_lane_reward']*du
            -w['total_parallel_penalty']*(sum(newp)-sum(oldp))
            -w['peak_parallel_penalty']*(max(retained+newp,default=0.)-max(retained+oldp,default=0.))
            -w['extra_l2_child_penalty']*(max(0,b+db-u-du)-max(0,b-u)))

def count_suffix(order,eligible):
    suffix=[None]*(len(order)+1);suffix[-1]={(0,0)}
    for i in range(len(order)-1,-1,-1):
        counts={0}|{mb._actual_l2_count(c) for c in eligible[order[i]]}
        suffix[i]={(b+n,u+int(n>0)) for b,u in suffix[i+1] for n in counts}
    return suffix

def prepare(inv,graph):
    p=mb._prepare_selector_inputs(inv,graph)
    base,nodes,back=mb._all_l1_baseline(**{k:p[k] for k in ['lane_order','eligible_by_lane','conflict_ids','pair_penalties']})
    order=list(p['lane_order']);random.Random(int(inv['unit_seed'])).shuffle(order)
    p.update(baseline=base,upgrade_order=order,suffix=count_suffix(order,p['eligible_by_lane']),q=_joint_local_quality_by_candidate(p['eligible_by_lane']),phase_a_nodes=nodes,phase_a_backtracks=back)
    return p

def select(inv,graph,target,p,w,use_score):
    config={c['source_lane_id']:c for c in p['baseline']};ids={c['candidate_id'] for c in p['baseline']}
    b=u=0;umax=mb._intent_upgrade_budget(inv);trace=[]
    for i,lane in enumerate(p['upgrade_order']):
        if b==target or u>=umax:break
        ranked=sorted((c for c in p['eligible_by_lane'][lane] if mb._actual_l2_count(c)>0),key=lambda c:(len(p['conflict_ids'][c['candidate_id']]),c['candidate_id']))
        accepted=None;best=-float('inf');count_reject=conflict_reject=0
        for c in ranked:
            nb=b+mb._actual_l2_count(c)
            if nb>target:continue
            if not any(n==target-nb and v<=umax-u-1 for n,v in p['suffix'][i+1]):count_reject+=1;continue
            # Same-parent graph edges do not exist; explicitly remove the replaced instance.
            if (ids-{config[lane]['candidate_id']}) & p['conflict_ids'][c['candidate_id']]:conflict_reject+=1;continue
            delta=replacement_delta(list(config.values()),config[lane],c,p['q'],p['pair_penalties'],w) if use_score else 0.
            if accepted is None or delta>best+1e-12:accepted=c;best=delta
            if not use_score:break
        trace.append(dict(parent=lane,accepted=accepted['candidate_id'] if accepted else None,delta=best if accepted and use_score else None,count_rejections=count_reject,conflict_rejections=conflict_reject))
        if accepted:
            ids.remove(config[lane]['candidate_id']);config[lane]=accepted;ids.add(accepted['candidate_id']);b+=mb._actual_l2_count(accepted);u+=1
    selected=[config[l] for l in p['lane_order']];attained=b==target
    return dict(schema='paper_a_batch4_local_control_v1',method=METHODS[int(use_score)],selection_id=f"{inv['inventory_id']}__batch4_{int(use_score)}_B{target}",seed=inv['unit_seed'],target_l2_count=target,budget_attained=attained,selection_status='success' if attained else 'budget_not_attained',failure_reason='' if attained else 'single irreversible pass ended below target B',selected_candidates=selected,selected_candidate_ids=[c['candidate_id'] for c in selected],solver_trace=dict(intent_upgrade_budget=umax,achieved_upgrade_count=u,selected_l2_count=b,upgrade_priority=p['upgrade_order'],search_node_count=p['phase_a_nodes'],search_node_limit_reached=False,bounded_space_exhausted=True),upgrade_trace=trace,objective=components(selected,p['q'],p['pair_penalties'],w))

def interface_check():
    # A genuine compatible replacement in the frozen inventory whose removed edge was the peak.
    w=read(mb.OURS_CONTRACT_PATH)['joint_objective']['weights']
    for path in sorted((R/'matrix_c/raw_cases').glob('C*')):
        inv=read(path/'shared_stage4_inventory.json');graph=read(path/'shared_conflict_graph.json');p=prepare(inv,graph)
        config=read(path/'methods/LocalGreedy/global_unit_selection.json')['selected_candidates'];before=components(config,p['q'],p['pair_penalties'],w)
        for old in config:
            for new in p['eligible_by_lane'][old['source_lane_id']]:
                if not mb._actual_l2_count(new):continue
                rest=[c for c in config if c is not old]
                if {c['candidate_id'] for c in rest}&p['conflict_ids'][new['candidate_id']]:continue
                after=components(rest+[new],p['q'],p['pair_penalties'],w)
                if after['peak']>=before['peak']-1e-12:continue
                delta=replacement_delta(config,old,new,p['q'],p['pair_penalties'],w)
                assert abs(delta-(after['score']-before['score']))<1e-12
                # Discrete count hole: one remaining parent with only {0,2} cannot provide one.
                toy=count_suffix(['p'],{'p':[{'curves':[{'level':'L2'},{'level':'L2'}]}]})[0]
                assert (1,1) not in toy and (2,1) in toy
                out=dict(case_id=path.name,old_id=old['candidate_id'],new_id=new['candidate_id'],before=before,after=after,incremental_delta=delta,full_difference=after['score']-before['score'],count_states=sorted(toy))
                save(HERE/'interface_check.json',out);print(json.dumps(out),flush=True);return
    raise RuntimeError('No peak-removal witness found')

def matched_case(caseid):
    source=R/'matrix_c/raw_cases'/caseid;dest=HERE/'matched/raw_cases'/caseid;dest.mkdir(parents=True,exist_ok=True)
    inv=read(source/'shared_stage4_inventory.json');graph=read(source/'shared_conflict_graph.json');inp=read(source/'case_input.json');plan=read(source/'methods/Ours/global_l1_flow_plan.json')
    p=prepare(inv,graph);w=read(mb.OURS_CONTRACT_PATH)['joint_objective']['weights'];params=__import__('evaluate_formal_cases')._metric_parameters(mb.PROTOCOL_DIR/'metric_parameters.csv')
    metricdir=dest/'evaluation_context';metricdir.mkdir(exist_ok=True);mb._write_metric_context_inputs(source,metricdir)
    raw=[];metrics=[]
    for target in range(1,2*mb._intent_upgrade_budget(inv)+1):
        for use_score in (False,True):
            start=time.perf_counter();sel=select(inv,graph,target,p,w,use_score);elapsed=time.perf_counter()-start;method=METHODS[int(use_score)]
            save(dest/f'B{target}_variant{int(use_score)}.json',sel)
            raw.append(mb._raw_row(inp,method,target,sel,elapsed,plan['plan_id'],inv,graph))
            if sel['budget_attained']:
                m=mb._independent_metrics(metricdir,sel,params);metrics.append(mb._metric_row(inp,method,target,sel,m))
    save(dest/'outcome.json',dict(raw=raw,metrics=metrics));return caseid,len(raw),len(metrics)

def matched(workers):
    assert (HERE/'interface_check.json').exists(),'Run the one interface check before grid'
    cases=[p.name for p in sorted((R/'matrix_c/raw_cases').glob('C*'))]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(matched_case,c) for c in cases]
        for n,f in enumerate(as_completed(futures),1):print(n,f.result(),flush=True)
    outputs=[read(HERE/'matched/raw_cases'/c/'outcome.json') for c in cases]
    csvout(HERE/'matched/raw_results.csv',[r for o in outputs for r in o['raw']]);csvout(HERE/'matched/independent_metrics.csv',[r for o in outputs for r in o['metrics']])

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['check','matched']);ap.add_argument('--workers',type=int,default=6);args=ap.parse_args()
    interface_check() if args.mode=='check' else matched(args.workers)
