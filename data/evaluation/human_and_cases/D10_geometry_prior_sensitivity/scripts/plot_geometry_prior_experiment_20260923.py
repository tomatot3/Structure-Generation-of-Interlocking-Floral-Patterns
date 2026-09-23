"""All-case paired changes and unmodified structural geometry panels.

Figure contract: show feasibility and the magnitude of output changes under the
two prespecified prior-width perturbations. Quantitative grid; panels a/b show
all paired coverage and length differences, c shows branch-count differences.
Python workflow; 183 mm wide SVG/PDF and 600 dpi PNG, editable vector text.
No population tests or confidence intervals. Bars across dots show median/IQR.
"""
from pathlib import Path
import json,csv,math,html
from collections import Counter
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.path import Path as MPath
from matplotlib.patches import PathPatch,Ellipse

import sys
ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
OUT=ROOT/'figures';OUT.mkdir(exist_ok=True)
SCALES=[.8,1.,1.2];PROTOS=['SW1-A','SW1-B','SW1-C','SW2-A','SW3-A','SW3-B']
COLORS={.8:'#426b9c',1.2:'#ae7735'}
plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],'font.size':7,'axes.titlesize':8,'axes.labelsize':7,'xtick.labelsize':7,'ytick.labelsize':7,'axes.linewidth':.6,'axes.spines.top':False,'axes.spines.right':False,'legend.frameon':False,'svg.fonttype':'none','pdf.fonttype':42,'savefig.facecolor':'white'})
def read(p):return json.loads(p.read_text('utf-8'))
def save(fig,stem):
 fig.savefig(OUT/f'{stem}.svg')
 fig.savefig(OUT/f'{stem}.pdf')
 fig.savefig(OUT/f'{stem}.png',dpi=600)
 if stem=='prior_width_sensitivity':fig.savefig(OUT/f'{stem}.tiff',dpi=600,pil_kwargs={'compression':'tiff_lzw'})
 plt.close(fig)
def paired_plot(ax,pairs,metric,label):
 ax.axhline(0,color='#91999c',linewidth=.65,linestyle='--',zorder=0)
 for x,scale in enumerate([.8,1.2]):
  values=sorted(float(p[metric]) for p in pairs if float(p['scale'])==scale and p['both_generated']=='True')
  xs=np.linspace(x-.11,x+.11,len(values))
  ax.scatter(xs,values,s=11,marker='o' if scale==.8 else 's',facecolor=COLORS[scale],edgecolor='white',linewidth=.3,zorder=2)
  if values:
   q1,med,q3=np.quantile(values,[.25,.5,.75]);ax.plot([x+.21,x+.21],[q1,q3],color='#26343a',lw=2);ax.plot([x+.16,x+.26],[med,med],color='#26343a',lw=1.2)
 ax.set_xticks([0,1],['0.8×','1.2×']);ax.set_xlim(-.45,1.45);ax.set_xlabel('Prior width');ax.set_ylabel(label);ax.margins(y=.18)
def quant(pairs,summary):
 fig,axes=plt.subplots(1,3,figsize=(7.2047244,2.8346457),gridspec_kw={'width_ratios':[1,1,1.16]})
 fig.subplots_adjust(left=.078,right=.992,bottom=.25,top=.79,wspace=.6)
 paired_plot(axes[0],pairs,'root_coverage_qcov_delta','Root coverage difference')
 paired_plot(axes[1],pairs,'length_relative_change_percent','Total branch length change (%)')
 categories=sorted({int(float(p['branch_count_delta'])) for p in pairs if p['both_generated']=='True'})
 for j,scale in enumerate([.8,1.2]):
  counts=Counter(int(float(p['branch_count_delta'])) for p in pairs if float(p['scale'])==scale and p['both_generated']=='True')
  x=np.arange(len(categories))+(j-.5)*.36;y=[counts[c] for c in categories]
  axes[2].bar(x,y,width=.34,color=COLORS[scale],label=f'{scale:.1f}×')
  for xi,yi in zip(x,y):
   if yi:axes[2].text(xi,yi+.2,str(yi),ha='center',va='bottom',fontsize=7)
 axes[2].set_xticks(range(len(categories)),[f'{v:+d}' if v else '0' for v in categories]);axes[2].set_xlabel('Branch count difference');axes[2].set_ylabel('Number of paired inputs');axes[2].set_ylim(0,20);axes[2].set_yticks([0,5,10,15,20]);axes[2].legend(loc='upper right',fontsize=7,handlelength=1)
 for i,(ax,title) in enumerate(zip(axes,['Root coverage','Branch length','Branch count'])):
  ax.set_title(title,loc='left',pad=10);ax.text(-.27,1.10,chr(97+i),transform=ax.transAxes,fontweight='bold',fontsize=9)
 fig.text(.5,.97,f"{summary['geometry_valid_cases']}/54 requests passed geometry checks; 18 matched inputs per perturbation",ha='center',va='top',fontsize=8)
 fig.text(.5,.03,'Changes relative to the default prior (1.0×). Lines beside points: median and interquartile range.',ha='center',fontsize=6.5)
 save(fig,'prior_width_sensitivity')
def all_points(g):
 pts=[s['point'] for s in g['analysis']['backbone']['samples']]
 for f in g['analysis']['flowers']:pts.extend([[f['center'][0]+a*f['rx'],f['center'][1]+b*f['ry']] for a in [-1,1] for b in [-1,1]])
 for u in g['selection']['selected_candidates']:
  for c in u['curves']:pts.extend(p for seg in c['cubic_segments'] for p in seg.values())
 for m in g['flower_mount_plan']['mounts']:pts.extend(m['centerline'])
 return pts
def draw_structure(ax,g,limits):
 colors={'L1':'#b2864c','L2':'#618f9c','L3':'#936c9b'}
 for shift in [-1,0,1]:
  pts=np.asarray([s['point'] for s in g['analysis']['backbone']['samples']]);ax.plot(pts[:,0]+shift,pts[:,1],color='#244880',lw=1.2)
  for m in g['flower_mount_plan']['mounts']:
   pts=np.asarray(m['centerline']);ax.plot(pts[:,0]+shift,pts[:,1],color='#708166',lw=1.0)
  for f in g['analysis']['flowers']:ax.add_patch(Ellipse((f['center'][0]+shift,f['center'][1]),2*f['rx'],2*f['ry'],fill=False,edgecolor='#b36163',linewidth=.7))
  for u in g['selection']['selected_candidates']:
   for c in u['curves']:
    segments=c['cubic_segments'];v=[[segments[0]['p0'][0]+shift,segments[0]['p0'][1]]];codes=[MPath.MOVETO]
    for seg in segments:
     for key in ['p1','p2','p3']:v.append([seg[key][0]+shift,seg[key][1]]);codes.append(MPath.CURVE4)
    ax.add_patch(PathPatch(MPath(v,codes),fill=False,edgecolor=colors.get(c['level'],'#555'),linewidth=.9 if c['level']=='L1' else .65))
 ax.set_xlim(limits[0],limits[2]);ax.set_ylim(limits[3],limits[1]);ax.set_aspect('equal');ax.axis('off')
def structures(results):
 lookup={(r['prototype'],int(r['production_seed']),r['prior_width_scale']):r for r in results};cards=[]
 for proto in PROTOS:
  fig,axes=plt.subplots(3,3,figsize=(12,7.2));fig.subplots_adjust(left=.035,right=.99,bottom=.04,top=.88,wspace=.07,hspace=.25)
  fig.suptitle(f'{proto} — paired prior-width comparison',fontsize=13,y=.985)
  fig.text(.5,.94,'Same flower–vine configuration and seed in each row; all three prespecified seeds shown.',ha='center',fontsize=9)
  for j,seed in enumerate([20260923,20260924,20260925]):
   geometries=[];records=[]
   for scale in SCALES:
    r=lookup[(proto,seed,scale)];records.append(r);geometries.append(read(ROOT/r['case_dir']/'structure.json') if r['generation_success'] and r.get('svg_export_success') else None)
   pts=[p for g in geometries if g is not None for p in all_points(g)]
   box=[min(-1.06,min(p[0] for p in pts)-1-.03),min(0,min(p[1] for p in pts))-.03,max(2.06,max(p[0] for p in pts)+1+.03),max(p[1] for p in pts)+.03] if pts else [-1,0,2,1]
   for i,(g,r) in enumerate(zip(geometries,records)):
    ax=axes[j,i]
    if g is None:ax.text(.5,.5,'Generation/export unavailable',ha='center',transform=ax.transAxes);ax.axis('off')
    else:draw_structure(ax,g,box)
    ax.set_title(f"{'Narrower' if i==0 else 'Default' if i==1 else 'Wider'} ({SCALES[i]:.1f}×) · L1/L2 {r.get('l1_count','–')}/{r.get('l2_count','–')}",fontsize=8,pad=8)
    if i==0:ax.text(0,-.13,f'Seed {seed}',transform=ax.transAxes,fontsize=8)
  save(fig,f'structures_{proto}')
  cards.append(f'<article><h2>{proto}</h2><a href="figures/structures_{proto}.svg" target="_blank"><img src="figures/structures_{proto}.svg" alt="{proto}三个种子的对应结构"></a></article>')
 return cards
def main():
 summary=read(ROOT/'summary.json');results=read(ROOT/'results.json')
 with (ROOT/'paired_changes.csv').open(encoding='utf-8-sig',newline='') as f:pairs=list(csv.DictReader(f))
 assert len(results)==54 and len(pairs)==36
 quant(pairs,summary);cards=structures(results)
 page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>几何先验扰动实验</title><style>body{margin:0;background:#f4f4f0;color:#293d44;font:16px/1.7 'Microsoft YaHei',sans-serif}main{max-width:1440px;padding:30px;margin:auto}article{padding:20px;background:white;border:1px solid #dde1df;border-radius:8px;margin:24px 0}img{width:100%;height:auto}h1{font-size:29px}h2{font-size:20px}p{color:#5e6e72}a{color:#396854}.quant{max-width:1000px;margin:auto}</style><main><h1>父枝几何先验扰动实验</h1><p>六原型 × 三个种子 × 三个分布宽度，共54组。各行从左至右为0.8倍、默认、1.2倍；同一行保持主藤和花位一致，使用共同显示范围。</p>'''
 page+=f'<p><strong>{summary["generated_cases"]}/54生成完成；{summary["geometry_valid_cases"]}/54通过几何检查。</strong></p><p><a href="RESULTS_CN.md">统计说明</a> · <a href="case_metrics.csv">逐例结果</a> · <a href="paired_changes.csv">配对变化</a></p><article class="quant"><img src="figures/prior_width_sensitivity.svg" alt="配对变化统计图"></article>'
 page+=''.join(cards)+'</main></html>'
 (ROOT/'comparison.html').write_text(page,'utf-8')
 (ROOT/'FIGURE_NOTES.md').write_text('''# Figure notes

All 54 planned cases and all 36 perturbation-versus-default pairs are represented. Quantitative points are paired inputs (six prototypes × three seeds), not independent human ratings. No observations are omitted. The short black bars show the median and interquartile range, not confidence intervals. No significance test was conducted.

The quantitative figure is 183 mm wide. SVG retains text, PDF embeds TrueType fonts, and PNG is exported at 600 dpi. Structure sheets are landscape inspection plates, not a single manuscript page. Every seed is shown. Within each row, all conditions use the same coordinate limits and aspect ratio. Curves are plotted directly from saved cubic control points; no curve is smoothed or edited for display. Colors identify structural roles. Source data are case_metrics.csv and paired_changes.csv.
''','utf-8')
 print('Exported quantitative figure, six complete structure-comparison sheets and comparison.html')
if __name__=='__main__':main()
