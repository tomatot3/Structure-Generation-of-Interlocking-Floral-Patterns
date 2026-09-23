"""Descriptive paired analysis of the predeclared prior-width experiment."""
from pathlib import Path
import json,csv,statistics,copy,math,html
from collections import Counter
import numpy as np

import sys
ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
SCALES=[.8,1.,1.2];PROTOS=['SW1-A','SW1-B','SW1-C','SW2-A','SW3-A','SW3-B']
METRICS=['l1_count','l2_count','ordinary_total_length','root_coverage_qcov','total_runtime_seconds']
def read(p):return json.loads(p.read_text('utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
def csv_write(p,rows):
 if not rows:return
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def stats(values):
 values=np.asarray(values,dtype=float)
 if not len(values):return {'n':0,'mean':None,'median':None,'min':None,'max':None,'q25':None,'q75':None}
 return {'n':len(values),'mean':float(np.mean(values)),'median':float(np.median(values)),'min':float(np.min(values)),'max':float(np.max(values)),'q25':float(np.quantile(values,.25)),'q75':float(np.quantile(values,.75))}
def geometry_signature(v):
 return sorted((c['level'],str(c.get('parent_curve_id')),json.dumps(c['cubic_segments'],sort_keys=True)) for u in v['selection']['selected_candidates'] for c in u['curves'])
def main():
 results=read(ROOT/'results.json');matrix=read(ROOT/'run_matrix.json')
 assert len(results)==len(matrix)==54,'Wait for every planned case'
 assert {r['case_id'] for r in results}=={r['case_id'] for r in matrix}
 lookup={(r['prototype'],int(r['production_seed']),r['prior_width_scale']):r for r in results}
 flat=[];prototype_summary=[];overall=[];summary=[]
 for r in results:
  flat.append({k:r.get(k) for k in ['case_id','prototype','production_seed','prior_width_scale','generation_success','geometry_valid',*METRICS,'failed_phase','error_message']})
 csv_write(ROOT/'case_metrics.csv',flat)
 for proto in [None,*PROTOS]:
  for scale in SCALES:
   selected=[r for r in results if r['prior_width_scale']==scale and (proto is None or r['prototype']==proto)]
   generated=[r for r in selected if r['generation_success']]
   row={'prototype':proto or 'All','scale':scale,'planned':len(selected),'generated':len(generated),'geometry_valid':sum(r.get('geometry_valid') is True for r in selected)}
   for metric in METRICS:
    for k,v in stats([r[metric] for r in generated if r.get(metric) is not None]).items():row[metric+'_'+k]=v
   (overall if proto is None else prototype_summary).append(row)
 csv_write(ROOT/'summary_by_condition.csv',overall);csv_write(ROOT/'summary_by_prototype.csv',prototype_summary)
 pairs=[];input_comparisons=[]
 for proto in PROTOS:
  for seed in [20260923,20260924,20260925]:
   base=lookup[(proto,seed,1.)]
   for scale in [.8,1.2]:
    other=lookup[(proto,seed,scale)];paired=bool(base['generation_success'] and other['generation_success'])
    pair={'prototype':proto,'seed':seed,'scale':scale,'baseline_case_id':base['case_id'],'case_id':other['case_id'],'both_generated':paired}
    for metric in ['l1_count','l2_count','ordinary_total_length','root_coverage_qcov']:
     pair[metric+'_baseline']=base.get(metric);pair[metric+'_perturbed']=other.get(metric)
     pair[metric+'_delta']=other[metric]-base[metric] if paired and metric in base and metric in other else None
    pair['length_relative_change_percent']=100*(other['ordinary_total_length']/base['ordinary_total_length']-1) if paired and base.get('ordinary_total_length',0)>0 else None
    pair['branch_count_delta']=pair['l1_count_delta']+pair['l2_count_delta'] if paired else None
    if paired:
     a=read(ROOT/base['case_dir']/'structure.json');b=read(ROOT/other['case_dir']/'structure.json')
     same_inputs=a['analysis']['backbone']['samples']==b['analysis']['backbone']['samples'] and a['analysis']['flowers']==b['analysis']['flowers'] and a['flower_mount_plan']==b['flower_mount_plan']
     pair['flower_vine_inputs_unchanged']=same_inputs
     pair['selected_geometry_changed']=geometry_signature(a)!=geometry_signature(b)
     assert same_inputs,(proto,seed,scale)
    else:pair.update(flower_vine_inputs_unchanged=None,selected_geometry_changed=None)
    pairs.append(pair)
 csv_write(ROOT/'paired_changes.csv',pairs)
 for scale in [.8,1.2]:
  values=[p for p in pairs if p['scale']==scale];valid=[p for p in values if p['both_generated']]
  row={'scale':scale,'planned_pairs':len(values),'completed_pairs':len(valid),'changed_geometry_pairs':sum(p['selected_geometry_changed'] is True for p in valid),'unchanged_branch_count_pairs':sum(p['branch_count_delta']==0 for p in valid)}
  for name in ['l1_count_delta','l2_count_delta','branch_count_delta','ordinary_total_length_delta','root_coverage_qcov_delta','length_relative_change_percent']:
   row[name]=stats([p[name] for p in valid])
  row['branch_count_change_distribution']=dict(sorted(Counter(p['branch_count_delta'] for p in valid).items()))
  summary.append(row)
 clipping={str(scale):sum(v['clipped_at_zero'] for v in read(ROOT/f'perturbations_{scale:.1f}.json')) for scale in SCALES}
 failures=[{k:r.get(k) for k in ['case_id','failed_phase','error_type','error_message']} for r in results if not r['generation_success'] or r.get('geometry_valid') is not True]
 out={'planned_cases':54,'generated_cases':sum(bool(r['generation_success']) for r in results),'geometry_valid_cases':sum(r.get('geometry_valid') is True for r in results),'descriptive_paired_changes':summary,'condition_means':overall,'negative_samples_clipped_at_zero':clipping,'failures':failures,'statistical_inference':'descriptive analysis of all 18 prespecified paired inputs; no population significance test','visual_review':'pending user review'}
 write(ROOT/'summary.json',out)
 lines=['# 父枝几何先验扰动实验','',f"完成情况：54个预定请求中，{out['generated_cases']}个生成完成，{out['geometry_valid_cases']}个通过独立几何检查。",'',
 '六个原型各取3个固定种子；主藤形态 expanded，疏密 medium。以边际中位数为中心，将六个父枝形态描述子的分布宽度设为默认的0.8、1.0、1.2倍。保留相关结构、长度先验、子枝先验、评分、约束及搜索预算。默认条件使用原先验原值。', '',
 '本实验使用既有正式先验。25例人工修正补充数据未重新拟合，也未用于替换生成输入。已有论文实验保持不变。','',
 '| 分布宽度 | 生成完成 | 几何通过 | 平均L1 | 平均L2 | 平均总枝长/W | 平均根位覆盖量 |','|---|---:|---:|---:|---:|---:|---:|']
 for r in overall:lines.append(f"| {r['scale']:.1f} | {r['generated']}/{r['planned']} | {r['geometry_valid']}/{r['planned']} | {r['l1_count_mean']:.2f} | {r['l2_count_mean']:.2f} | {r['ordinary_total_length_mean']:.4f} | {r['root_coverage_qcov_mean']:.4f} |")
 lines+=['','与相同原型、相同种子的默认条件配对：','']
 for r in summary:
  length=r['length_relative_change_percent'];cov=r['root_coverage_qcov_delta'];count=r['branch_count_delta']
  lines.append(f"- {r['scale']:.1f}倍：总枝长相对变化中位数 {length['median']:+.2f}%（范围 {length['min']:+.2f}% 至 {length['max']:+.2f}%）；根位覆盖量差中位数 {cov['median']:+.4f}（范围 {cov['min']:+.4f} 至 {cov['max']:+.4f}）；总分枝数差范围 {count['min']:+.0f} 至 {count['max']:+.0f}，{r['unchanged_branch_count_pairs']}/{r['completed_pairs']}例数量不变。")
 lines+=['','几何检查覆盖内部和枝组间相交、与主藤及承花路径相交、周期间相交、间距、花位侵入和周期接缝。所有预定请求均保留；结果不按视觉优劣筛选。图中每个点对应一个固定原型和种子，配对变化取扰动条件减默认条件。','',
 '零截断数（六个先验配置的样本条目总计，包含全局及各原型配置；不是独立案例数）：'+str(clipping)+'。','',
 '解释：这项实验检验的是现有先验分布宽度变化时生成流程的可行性与输出变化，不是25例人工校准样本的重采样检验。约束通过与视觉质量分别判断；本实验也未重新比较JBC和对照方法的相对增益。','',
 '运行时间在4个并行CPU进程下记录，仅作本次运行记录，不与正文单任务耗时比较。','',
 '候选池与最终结构由各扰动先验重新生成。所有配对的主藤、花位和承花路径均保持一致。完整结果见 case_metrics.csv、paired_changes.csv 和 raw_cases；横向结构对照见 comparison.html。']
 if failures:lines+=['','未通过案例：',json.dumps(failures,ensure_ascii=False,indent=2)]
 (ROOT/'RESULTS_CN.md').write_text('\n'.join(lines),'utf-8')
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
