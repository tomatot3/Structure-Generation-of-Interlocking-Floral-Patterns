"""Execute the predeclared 6 x 3 x 3 geometry-prior sensitivity matrix."""
from pathlib import Path
import argparse,sys,json,copy,time,subprocess,os,traceback
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np

REPO=None
DEFAULT_OUT=Path('geometry_prior_sensitivity_run')
PROTOTYPES={'SW1-A':'proto_sw_1_1','SW1-B':'proto_sw_1_3','SW1-C':'proto_sw_1_c','SW2-A':'proto_sw_2_3','SW3-A':'proto_sw_3_1','SW3-B':'proto_sw_3_2'}
SCALES=[1.0,.8,1.2];SEEDS=[20260923,20260924,20260925]
NONNEGATIVE={'start_handle_chord_ratio','end_handle_chord_ratio','start_angle_abs_deg'}
CHECKS=['internal_unit_crossing_count','cross_unit_crossing_count','ordinary_backbone_nonroot_crossing_count','ordinary_support_crossing_count','periodic_crossing_count','clearance_violation_count','flower_region_intrusion_curve_count','periodic_seam_violation_count']
def read(p):return json.loads(p.read_text('utf-8'))
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
def perturb(prior,scale):
    result=copy.deepcopy(prior);audit=[]
    for profile_name,profile in result['profiles'].items():
        for name,dist in profile['descriptor_distributions'].items():
            old=np.asarray(dist['samples'],dtype=float);median=float(np.median(old))
            # A true unmodified baseline, avoiding subtract/add roundoff at a=1.
            new=old.copy() if scale==1.0 else median+scale*(old-median)
            clipped=int(np.sum(new<0)) if name in NONNEGATIVE else 0
            if name in NONNEGATIVE:new=np.maximum(new,0.)
            if scale!=1.0:
                dist['samples']=new.tolist()
                for key,q in [('min',0),('q10',.1),('q25',.25),('median',.5),('q75',.75),('q90',.9),('q95',.95),('max',1)]:
                    if key in dist:dist[key]=float(np.quantile(new,q))
            audit.append({'profile':profile_name,'descriptor':name,'scale':scale,'count':len(new),'clipped_at_zero':clipped,'q03_before':float(np.quantile(old,.03)),'q97_before':float(np.quantile(old,.97)),'q03_after':float(np.quantile(new,.03)),'q97_after':float(np.quantile(new,.97))})
    return result,audit
def case(output,index):
    sys.path.insert(0,str(REPO/'code'))
    import package_paths
    import run_formal_cases as formal
    from evaluate_formal_cases import evaluate_case,_metric_parameters
    from asset_export import export_asset
    row=read(output/'run_matrix.json')[index];start=time.perf_counter();phase='initialization'
    result={**row,'generation_success':0,'mechanical_evaluation_success':0,'svg_export_success':0,'geometry_valid':None}
    try:
        formal._init_worker();formal._WORKER['curve_geometry_prior']=read(output/f"prior_width_{row['prior_width_scale']:.1f}.json")
        phase='generation';generated=formal._run_case(row,output,False);result.update(generated)
        if result['generation_success']:
            folder=output/generated['case_dir'];phase='independent_geometry_check'
            result.update(evaluate_case(folder,_metric_parameters(REPO/'code/inputs/metric_parameters.csv')))
            result['geometry_valid']=all(result[k]==0 for k in CHECKS)
            phase='svg_export';export_asset(folder,read(folder/'prototype_analysis_variant.json'),read(folder/'flower_mount_plan.json'),read(folder/'global_unit_selection.json'),{**row,'source_case':row['case_id'],'backbone_variant_id':row['backbone_variant']},None)
            result['svg_export_success']=1
        else:result['failed_phase']='generation'
    except Exception as e:
        result.update(failed_phase=phase,error_type=type(e).__name__,error_message=str(e),traceback=traceback.format_exc())
    result.update(prior_width_scale=row['prior_width_scale'],prototype=row['prototype'],production_seed=int(row['production_seed']),elapsed_including_check_seconds=time.perf_counter()-start)
    write(output/'case_results'/f"{row['case_id']}.json",result)
    return result
def main():
    global REPO
    p=argparse.ArgumentParser();p.add_argument("--repo",type=Path,required=True);p.add_argument('--output',type=Path,default=DEFAULT_OUT);p.add_argument('--case',type=int);p.add_argument('--workers',type=int,default=4);p.add_argument('--resume',action='store_true');a=p.parse_args();REPO=a.repo.resolve()
    if a.case is not None:case(a.output,a.case);return
    if a.output.exists() and not a.resume:raise RuntimeError('Output exists; use --resume to retain completed cases')
    a.output.mkdir(parents=True,exist_ok=True);(a.output/'logs').mkdir(exist_ok=True)
    sys.path.insert(0,str(REPO/'code'));import package_paths
    import run_formal_cases as formal
    from backbone_variation_v1 import split_generation_seeds
    formal._init_worker();original=copy.deepcopy(formal._WORKER['curve_geometry_prior'])
    rows=[]
    for proto in PROTOTYPES:
        for seed in SEEDS:
            for scale in SCALES:
                rows.append({'case_id':f'{proto}_seed{seed}_width{scale:.1f}','matrix_id':'PRIOR_SENSITIVITY','prototype_id':PROTOTYPES[proto],'prototype':proto,'production_seed':str(seed),'backbone_variant':'expanded','density_level':'medium','replicate':'1','prior_width_scale':scale,**{k:str(v) for k,v in split_generation_seeds(seed).items()}})
    if a.resume:assert read(a.output/'run_matrix.json')==rows
    else:
        write(a.output/'run_matrix.json',rows)
        for scale in SCALES:
            prior,audit=perturb(original,scale);write(a.output/f'prior_width_{scale:.1f}.json',prior);write(a.output/f'perturbations_{scale:.1f}.json',audit)
        git=subprocess.run(['git','rev-parse','HEAD'],cwd=REPO,text=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        write(a.output/'run_settings.json',{'cases':54,'paired_inputs':18,'workers':a.workers,'prototype_ids':PROTOTYPES,'seeds':SEEDS,'scales':SCALES,'main_vine_variant':'expanded','density':'medium','code_repository':str(REPO),'code_commit':git.stdout.strip(),'pilot_policy':'pilot confirms consumption; all 54 cases measured in this run under the same execution mode','failure_policy':'keep every planned input; no replacement seeds or amplitude adjustment','mechanical_checks':CHECKS})
    results={}
    for i,row in enumerate(rows):
        path=a.output/'case_results'/f"{row['case_id']}.json"
        if path.exists():results[i]=read(path)
    write(a.output/'results.json',[results[i] for i in sorted(results)])
    def run_one(i):
        env=os.environ.copy();env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONUTF8='1')
        result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--repo',str(REPO),'--case',str(i),'--output',str(a.output)],env=env,creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True,text=True,encoding='utf-8',errors='replace')
        (a.output/'logs'/f"{rows[i]['case_id']}.log").write_text(result.stdout+result.stderr,'utf-8')
        path=a.output/'case_results'/f"{rows[i]['case_id']}.json"
        if path.exists():return read(path)
        fallback={**rows[i],'generation_success':0,'geometry_valid':None,'failed_phase':'worker_process','error_message':result.stderr[-4000:]};write(path,fallback);return fallback
    started=time.perf_counter();print(f'START 54 planned cases; {len(results)} already recorded; {a.workers} workers',flush=True)
    with ThreadPoolExecutor(max_workers=a.workers) as executor:
        futures={executor.submit(run_one,i):i for i in range(len(rows)) if i not in results}
        for future in as_completed(futures):
            i=futures[future];result=future.result();results[i]=result
            write(a.output/'results.json',[results[i] for i in sorted(results)])
            print(f"{len(results):02d}/54 {result['case_id']} generated={result['generation_success']} geometry={result.get('geometry_valid')} L1={result.get('l1_count')} L2={result.get('l2_count')} error={result.get('error_message','')}",flush=True)
    write(a.output/'completion.json',{'recorded_cases':len(results),'wall_seconds':time.perf_counter()-started,'generated_cases':sum(bool(v['generation_success']) for v in results.values()),'geometry_valid_cases':sum(v.get('geometry_valid') is True for v in results.values())})
    print('COMPLETE',json.dumps(read(a.output/'completion.json')),flush=True)
if __name__=='__main__':main()
