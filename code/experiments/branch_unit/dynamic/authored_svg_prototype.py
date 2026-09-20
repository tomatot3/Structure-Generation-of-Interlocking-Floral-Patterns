"""Consume the author-approved SVG in the existing prototype and mounting chain."""
from pathlib import Path
from copy import deepcopy
import re,xml.etree.ElementTree as ET
import numpy as np
from strict_p0_v2 import StrictP0V2,RepeatLocalFrame,BackboneSample,FlowerReserve
from prototype_analysis import analyze_prototype

def _cubics(data):
 tokens=re.findall(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?',data)
 i=0;pos=np.zeros(2);cmd=None;segments=[]
 while i<len(tokens):
  if tokens[i].isalpha():cmd=tokens[i];i+=1
  if cmd not in ('m','M','c','C'):raise ValueError('Unsupported authored SVG command '+str(cmd))
  n=2 if cmd.lower()=='m' else 6
  p=np.array(list(map(float,tokens[i:i+n]))).reshape(-1,2);i+=n
  if cmd.islower():p+=pos
  if n==6:segments.append(np.array([pos,*p]))
  pos=p[-1]
  if n==2:cmd='l' if cmd=='m' else 'L'
 return np.array(segments)

def _sample(segments,n=401):
 t=np.linspace(0,1,n)[:,None];u=1-t
 return np.concatenate([u**3*s[0]+3*u*u*t*s[1]+3*u*t*t*s[2]+t**3*s[3] for s in segments])

def load_authored_svg(path):
 tree=ET.parse(path);root=tree.getroot();els={e.get('id'):e for e in root.iter()}
 layer=els['layer1'];tr=re.fullmatch(r'translate\(([-+\d.eE]+)[ ,]+([-+\d.eE]+)\)',layer.get('transform',''))
 if not tr:raise ValueError('Expected a single translation on author layer')
 offset=np.array([float(tr[1]),float(tr[2])]);blue=_cubics(els['path1'].get('d'))+offset
 x0=blue[0,0,0];width=blue[-1,-1,0]-x0
 origin=np.array([x0,0.]);blue=(blue-origin)/width
 raw=_sample(blue);length=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(raw,axis=0),axis=1))]
 phase=np.linspace(0,1,161);xy=np.column_stack([np.interp(phase*length[-1],length,raw[:,k])for k in (0,1)])
 # A small linear seam correction is explicit; the author SVG stays untouched.
 seam=(xy[0,1]+xy[-1,1])/2;xy[:,1]+=seam-xy[0,1]-(xy[-1,1]-xy[0,1])*xy[:,0]
 xy[0]=[0.,seam];xy[-1]=[1.,seam]
 tangent=np.gradient(xy,axis=0);tangent[0]=tangent[-1]=(xy[1]-xy[-2]+[1,0])/2
 tangent/=np.linalg.norm(tangent,axis=1)[:,None]
 samples=tuple(BackboneSample(float(s),tuple(np.round(p,9)),tuple(t))for s,p,t in zip(phase,xy,tangent))
 flowers=[];carriers=[]
 for i,(fid,pid)in enumerate([('path4','path2'),('path5','path3')],1):
  el=els[fid];center=(np.array([float(el.get('cx')),float(el.get('cy'))])+offset-origin)/width
  flowers.append(FlowerReserve('flower_'+str(i),tuple(np.round(center,9)),round(float(el.get('rx'))/width,9),round(float(el.get('ry'))/width,9)))
  carriers.append((_cubics(els[pid].get('d'))+offset-origin)/width)
 view=list(map(float,root.get('viewBox').split()))
 strict=StrictP0V2('proto_sw_1_c',RepeatLocalFrame(3*width,view[3],(0.,width)),samples,tuple(flowers),())
 return strict,carriers

def add_registered_inputs(inputs,registry):
 for pid,strategy in registry['strategies'].items():
  spec=strategy.get('input_derivation')
  if spec is None:continue
  if spec['geometry_policy']!='author_svg':raise ValueError('Unsupported author input policy')
  strict,_=load_authored_svg(Path(__file__).parent/spec['input_file'])
  base=spec['base_prototype_id'];m=deepcopy(inputs[base]['morphology'])
  m['prototype_id']=pid;m['morphology_digest']=None;m.pop('source_stage2_analysis_digest',None)
  m['evidence']={'author_svg':spec['input_file'],'ordinary_branch_prior_basis':base,'ordinary_branches_in_source':False}
  m['instance_priors']['source_observation_counts_origin']=base
  m['instance_priors']['description_zh']='作者确认的SW1-C双花位及上下交替承花配置；普通分枝先沿用SW1-A先验。'
  m['instance_priors']['flower_relation_emphasis']='authored_alternating_carriers'
  m['family_rule']['flower_binding']='author_main_and_alternating_carriers'
  m['family_rule']['required_relationships']=['author_flower_geometry','author_carrier_shape_and_attachment','alternating_opposite_sides']
  m['review']['status']='author_prototype_adopted_generated_variants_pending'
  inputs[pid]={'strict':strict.as_dict(),'analysis':analyze_prototype(strict),'morphology':m}

def _project(p,points):
 delta=np.diff(points,axis=0);t=np.clip(np.sum((p-points[:-1])*delta,axis=1)/np.sum(delta*delta,axis=1),0,1)
 q=points[:-1]+t[:,None]*delta;i=int(np.argmin(np.linalg.norm(q-p,axis=1)))
 return (i+t[i])/(len(points)-1),q[i]


def _round_lower_carrier(segment):
 # Author-requested shape correction: preserve depth, bring the bottom toward
 # the endpoint midpoint, and minimize bending rather than prescribe handles.
 t=np.linspace(0,1,121)[:,None];u=1-t
 def geometry(ctrl):
  p=u**3*ctrl[0]+3*u*u*t*ctrl[1]+3*u*t*t*ctrl[2]+t**3*ctrl[3]
  v=3*u*u*(ctrl[1]-ctrl[0])+6*u*t*(ctrl[2]-ctrl[1])+3*t*t*(ctrl[3]-ctrl[2])
  a=6*u*(ctrl[2]-2*ctrl[1]+ctrl[0])+6*t*(ctrl[3]-2*ctrl[2]+ctrl[1])
  return p,v,a
 p,_,_=geometry(segment);bottom=p[np.argmax(p[:,1])];mid=(segment[0]+segment[3])/2
 goal_x=(bottom[0]+mid[0])/2;goal_y=bottom[1];scale=np.linalg.norm(segment[3]-segment[0])
 def objective(z,full=False):
  c=segment.copy();c[1:3]=z.reshape(2,2);p,v,a=geometry(c)
  speed=np.linalg.norm(v,axis=1);cross=v[:,0]*a[:,1]-v[:,1]*a[:,0]
  bend=scale*np.trapezoid(cross**2/np.maximum(speed,1e-8)**5,dx=1/120)
  b=p[np.argmax(p[:,1])]
  constraint=((b[0]-goal_x)/scale)**2+((b[1]-goal_y)/scale)**2
  constraint+=np.maximum(0.,-v[:,0]/scale).max()**2
  length=np.linalg.norm(np.diff(p,axis=0),axis=1).sum()/scale
  score=bend+length+100000*constraint
  return c if full else score
 z=segment[1:3].ravel().copy();best=objective(z);step=scale/4
 for _ in range(240):
  options=[]
  for axis in range(4):
   for sign in (-1,1):
    q=z.copy();q[axis]+=sign*step;options.append((objective(q),q))
  value,q=min(options,key=lambda a:a[0])
  if value<best-1e-8:z,best=q,value
  else:
   step*=.5
   if step<scale*1e-5:break
 return objective(z,True)

def build_authored_mounts(analysis,strategy):
 import flower_mounting_v1 as f
 baseline,carriers=load_authored_svg(Path(__file__).parent/strategy['input_derivation']['input_file'])
 base=np.array(baseline.backbone_points);rows=analysis['backbone']['samples'];phase=np.array([p['s']for p in rows]);points=np.array([p['point']for p in rows]);mounts=[]
 for flower,segments in zip(analysis['flowers'],carriers):
  root_s,base_root=_project(segments[0,0],base)
  root=np.array([np.interp(root_s,phase,points[:,k])for k in (0,1)])
  center=np.array(flower['center']);radii=np.array([flower['rx'],flower['ry']]);v=segments[-1,-1]-center
  target=center+v/np.linalg.norm(v/radii)
  dr=root-segments[0,0];dt=target-segments[-1,-1]
  # Blend endpoint translations over the author's two cubic segments; no route search.
  adjusted=segments.copy();count=len(segments)
  for i in range(count):
   for j in range(4):
    # Translate each endpoint and its adjacent handle together.
    # This preserves authored tangents, including zero-length handles.
    t=(i+(0 if j<2 else 1))/count;blend=t*t*(3-2*t)
    adjusted[i,j]+=(1-blend)*dr+blend*dt
  adjusted[0,0]=root;adjusted[-1,-1]=target
  # A collapsed join handle has no first-order tangent and may create a kink.
  # Fit that carrier as one cubic with fixed endpoints and authored endpoint
  # directions, using least squares over the transported source curve.
  degenerate_join=any(np.linalg.norm(adjusted[k+1,1]-adjusted[k+1,0])<1e-10 or np.linalg.norm(adjusted[k,3]-adjusted[k,2])<1e-10 for k in range(count-1))
  if degenerate_join:
   points_source=_sample(adjusted,161)
   distance=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(points_source,axis=0),axis=1))]
   t=np.linspace(0,1,161);u=1-t
   reference=np.column_stack([np.interp(t*distance[-1],distance,points_source[:,j])for j in (0,1)])
   departure=next(p-root for p in adjusted[0,1:]if np.linalg.norm(p-root)>1e-10)
   arrival=next(target-p for p in adjusted[-1,-2::-1]if np.linalg.norm(target-p)>1e-10)
   departure/=np.linalg.norm(departure);arrival/=np.linalg.norm(arrival)
   a=3*u*u*t;b=3*u*t*t
   base=(u**3+a)[:,None]*root+(b+t**3)[:,None]*target
   design=np.column_stack([(a[:,None]*departure).ravel(),(-b[:,None]*arrival).ravel()])
   handles=np.linalg.lstsq(design,(reference-base).ravel(),rcond=None)[0]
   if np.any(handles<=0):raise ValueError('Author carrier smoothing requires nonpositive handles')
   adjusted=np.array([[root,root+handles[0]*departure,target-handles[1]*arrival,target]])
   if target[1]>center[1]:adjusted[0]=_round_lower_carrier(adjusted[0])
  tangent=np.array([np.interp(root_s,phase,[p['tangent'][k]for p in rows])for k in (0,1)])
  record=f._mount_record(analysis,flower,f.FAMILY_SW1,float(root_s),tuple(root),tuple(center),tuple(target),tuple(tangent),[{key:list(map(float,p))for key,p in zip(('p0','p1','p2','p3'),seg)}for seg in adjusted],'author_svg_alternating_carrier',{'origin_kind':'author_svg_root','source_svg':strategy['input_derivation']['input_file'],'carrier_geometry':'author_tangent_constrained_cubic_fit'if degenerate_join else'author_cubics_endpoint_transport','contact_side':'upper'if target[1]<center[1]else'lower'})
  mounts.append(record)
 return mounts
