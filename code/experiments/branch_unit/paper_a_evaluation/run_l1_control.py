"""Recover the frozen ordinary pool, then perform one score-ordered greedy pass."""
from run_controls import *
import global_l1_flow as g
import run_matrix_c as mc
from run_stage3b_l1_flow import _load_inputs
from evaluate_formal_cases import _metric_parameters,evaluate_case

CONTEXT=None
def setup():
    global CONTEXT
    if CONTEXT is None:CONTEXT=_load_inputs()
    return CONTEXT

def case(caseid):
    source=R/'matrix_c/raw_cases'/caseid;ours=source/'methods/Ours';dest=HERE/'l1/raw_cases'/caseid
    dest.mkdir(parents=True,exist_ok=True)
    inp=read(source/'case_input.json');plan=read(ours/'global_l1_flow_plan.json');analysis=read(ours/'prototype_analysis_variant.json');mount=read(ours/'flower_mount_plan.json')
    inputs,prior,fp,gp,contract,_,_=setup();strategy=plan['prototype_strategy'];policy=strategy['l1_profile'];pid=inp['prototype_id']
    feedback=g._feedback_profile(fp,pid,policy.get('feedback_profile_key',pid));geometry=g._curve_geometry_profile(gp,pid,policy.get('curve_geometry_profile_key',pid))
    seed=int(inp['branch_seed']);latents=g._global_latents(pid,seed)
    stock,sampling=g._feedback_common_ordinary_candidates(analysis,prior,latents,feedback,geometry,seed)
    feasible=[]
    for c in stock:
        reasons=g._candidate_rejections(c,analysis,plan['family_id'],prior,feedback,mount,geometry,strategy['flower_mount']['mechanism'])
        if not reasons:feasible.append(c)
    archived_ic=read(source/'independent_curve_inventory.json')
    ranked=sorted(feasible,key=lambda c:(-c['individual_score'],c['candidate_id']))
    k=len(plan['lanes'])
    # This is source recovery, not a new geometry run: compare actual selected controls and IDs.
    assert len(feasible)==archived_ic['candidate_count'],(caseid,'pool size drift')
    assert [c['candidate_id'] for c in mc._assign_current_lane_ids(ranked[:k])]==archived_ic['selected_candidate_ids'],(caseid,'independent selection drift')
    byid={c['candidate_id']:c for c in feasible};maxerr=0.
    for lane in plan['lanes']:
        c=byid[lane['candidate_id']]
        maxerr=max(maxerr,float(np.max(np.abs(np.asarray(c['centerline'])-np.asarray(lane['centerline'])))))
        assert c['segments']==lane['segments'],(caseid,'control points drift')
    assert maxerr<1e-8,(caseid,maxerr)
    # When the archived final Global-L1 call used the downstream-clearance re-solve,
    # apply precisely the same prefilter and clearance override to this control.
    override=None
    if plan['solver']['downstream_clearance_resolve']['re_solved']:
        from run_batch_generation import _downstream_unit_clearance
        override=_downstream_unit_clearance(strategy,read(mc.EDITOR_L2_PRIOR_PATH),read(mc.STAGE4_CONTRACT_PATH))
        mountpoints=[[g._point(p,'mount') for p in m['centerline']] for m in mount['mounts']]
        feasible=[c for c in feasible if min((g.global_l1_polyline_distance_batch(c['centerline'],m,s) for m in mountpoints for s in (-1.,0.,1.)),default=float('inf'))>=override-1e-9]
    assert len(feasible)==plan['solver']['common_pool_node_count'],(caseid,'final pool size drift')
    rootspace=g._minimum_root_spacing(prior);clearance=override if override is not None else g._minimum_lane_clearance(prior,geometry)
    # The original graph is computed by this exact pair predicate. Evaluate only queried edges.
    chosen=[];queries=0;started=time.perf_counter()
    for c in sorted(feasible,key=lambda c:(-c['individual_score'],c['candidate_id'])):
        compatible=True
        for prev in chosen:
            queries+=1
            if not g._pair_metrics(c,prev,rootspace,clearance,geometry)[0]:compatible=False;break
        if compatible:chosen.append(c)
        if len(chosen)==k:break
    lanes=mc._assign_current_lane_ids(chosen)
    newplan=copy.deepcopy(plan);newplan.pop('plan_digest',None);newplan['lanes']=lanes;newplan['plan_id']=plan['plan_id']+'__HardConstraintGreedy'
    newplan['count_derivation'].update(ordinary_lane_count=len(lanes),selected_ordinary_l1_count=len(lanes))
    newplan['solver']=dict(method='HardConstraintGreedy',target_count=k,selected_count=len(lanes),candidate_count=len(feasible),pair_queries=queries)
    selection=mc._l1_selection(newplan,'HardConstraintGreedy')
    for name in ['strict_p0_variant.json','prototype_analysis_variant.json','flower_mount_plan.json']:save(dest/name,read(ours/name))
    save(dest/'global_l1_flow_plan.json',newplan);save(dest/'global_unit_selection.json',selection)
    save(dest/'recovered_candidates.json',dict(candidates=feasible,sampling=sampling,source='frozen upstream analysis, priors and branch seed'))
    params=_metric_parameters(mb.PROTOCOL_DIR/'metric_parameters.csv');metrics=evaluate_case(dest,params)
    legal=int(metrics['mechanical_evaluation_success'])==1 and all(int(metrics[h])==0 for h in mb.HARD_METRICS)
    out={k:inp[k] for k in ['case_id','prototype_id','backbone_variant','density_level','replicate']}
    out.update(method='HardConstraintGreedy',target_count=k,achieved_count=len(lanes),completed=int(len(lanes)==k),mechanically_legal=int(legal),completed_and_legal=int(legal and len(lanes)==k),candidate_count=len(feasible),recovered_geometry_max_error=maxerr,runtime_seconds=time.perf_counter()-started,selected_candidate_ids=json.dumps([c['candidate_id'] for c in lanes]))
    out.update(metrics)
    save(dest/'outcome.json',out);return caseid,len(lanes),k,legal

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--case');ap.add_argument('--workers',type=int,default=4);args=ap.parse_args()
    if args.case:print(case(args.case),flush=True)
    else:
        cases=[p.name for p in sorted((R/'matrix_c/raw_cases').glob('C*'))]
        pending=[c for c in cases if not (HERE/'l1/raw_cases'/c/'outcome.json').exists()]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for i,f in enumerate(as_completed([pool.submit(case,c) for c in pending]),1):print(i,f.result(),flush=True)
        csvout(HERE/'l1/results.csv',[read(HERE/'l1/raw_cases'/c/'outcome.json') for c in cases])
