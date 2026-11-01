"""One object graph drives conditioning, guided recovery and appearance editing.
Registration is an explicit, editable case alignment, not semantic ownership masks.
"""
from pathlib import Path
import sys,os,json,copy,math,re,threading,io,base64,zipfile,subprocess
if os.environ.get('CASE_DEPS'):sys.path.insert(0,os.environ['CASE_DEPS'])
import cv2,numpy as np
from PIL import Image
from lxml import etree as E
from . import articulation
ROOT=Path(__file__).resolve().parent;CASE=ROOT.parent;NS='http://www.w3.org/2000/svg'
DATA=ROOT/'data';OUT=ROOT/'output'
LOCK=threading.RLock();CACHE={};W=695;H=724;ORIGIN=695
COLORS={'main':'#0000ff','support':'#008000','flower':'#ff0000','parent':'#ff9900','child':'#00ffff','ornament':'#9a70b2'}
def resample(points,n=100):
 p=np.asarray(points,float);ds=np.linalg.norm(np.diff(p,axis=0),axis=1);t=np.r_[0,np.cumsum(ds)];t/=max(t[-1],1e-9)
 return np.stack([np.interp(np.linspace(0,1,n),t,p[:,j]) for j in range(2)],axis=1)
def nearest(points,line):
 p=np.asarray(points,float);line=np.asarray(line,float);a=line[:-1];v=np.diff(line,axis=0);lens=np.linalg.norm(v,axis=1);acc=np.r_[0,np.cumsum(lens)];total=max(acc[-1],1e-9)
 # Batch to bound memory for large compound paths.
 ts=[];ns=[]
 for block in np.array_split(p,max(1,len(p)//1800+1)):
  delta=block[:,None,:]-a[None,:,:];u=np.clip(np.sum(delta*v[None,:,:],axis=2)/(lens**2+1e-9),0,1);q=a[None,:,:]+u[:,:,None]*v[None,:,:];d=np.sum((block[:,None,:]-q)**2,axis=2);idx=np.argmin(d,axis=1);row=np.arange(len(block));tan=v[idx]/np.maximum(lens[idx,None],1e-9);normal=np.stack([-tan[:,1],tan[:,0]],axis=1)
  ts.append((acc[idx]+u[row,idx]*lens[idx])/total);ns.append(np.sum((block-q[row,idx])*normal,axis=1))
 return np.concatenate(ts),np.concatenate(ns)
def point_at(line,t):
 p=np.asarray(line,float);v=np.diff(p,axis=0);ds=np.linalg.norm(v,axis=1);acc=np.r_[0,np.cumsum(ds)];acc/=max(acc[-1],1e-9);idx=np.clip(np.searchsorted(acc,t,side='right')-1,0,len(v)-1);u=(np.asarray(t)-acc[idx])/np.maximum(acc[idx+1]-acc[idx],1e-9);q=p[idx]+u[...,None]*v[idx];tan=v[idx]/np.maximum(ds[idx,None],1e-9);return q,tan
def map_curve(points,old,new):
 # Rigid moving least squares: interpolate control motion with local rotation,
 # without TPS's unbounded affine/shear extrapolation over broad leaf silhouettes.
 pts=np.asarray(points,float);old=np.asarray(old,float);new=np.asarray(new,float)
 if np.array_equal(old,new):return pts
 out=[]
 for block in np.array_split(pts,max(1,len(pts)//1800+1)):
  delta=block[:,None,:]-old[None,:,:];w=1/np.maximum(np.sum(delta*delta,axis=2),1e-8)**2;w/=w.sum(axis=1)[:,None]
  p=w@old;q=w@new;X=old[None,:,:]-p[:,None,:];Y=new[None,:,:]-q[:,None,:]
  a=np.sum(w*np.sum(X*Y,axis=2),axis=1);b=np.sum(w*(X[:,:,0]*Y[:,:,1]-X[:,:,1]*Y[:,:,0]),axis=1)
  angle=np.arctan2(b,a);co=np.cos(angle);si=np.sin(angle);v=block-p
  out.append(q+np.c_[co*v[:,0]-si*v[:,1],si*v[:,0]+co*v[:,1]])
 return np.vstack(out)
def apply_motion(points,old,new,mode=None):return map_curve(points,old,new)
def rebase_parent(points,previous_ops,current_ops):
 """Carry edits from the parent state in which they were authored to its new state."""
 p=np.asarray(points,float).copy()
 if json.dumps(previous_ops,separators=(',',':'))==json.dumps([[a.tolist(),b.tolist(),m] for a,b,m in current_ops],separators=(',',':')):return p
 for old,new,mode in reversed(previous_ops):
  old=np.asarray(old);new=np.asarray(new);target=p.copy();q=map_curve(target,new,old)
  # Invert the actual parent deformation, not a second fitted child transform.
  for _ in range(12):
   f=map_curve(q,old,new);err=target-f
   if np.max(np.linalg.norm(err,axis=1),initial=0)<1e-5:break
   dx=(map_curve(q+[.01,0],old,new)-f)/.01;dy=(map_curve(q+[0,.01],old,new)-f)/.01
   J=np.stack([dx,dy],axis=2);step=np.linalg.pinv(J)@err[:,:,None];step=step[:,:,0];length=np.linalg.norm(step,axis=1);q+=step*np.minimum(1,20/np.maximum(length,1e-9))[:,None]
  p=q
 for a,b,m in current_ops:p=apply_motion(p,a,b,m)
 return p
def registration_guide(o):
 return resample(o['source_points'],len(o['registration_offsets']))*W+np.asarray(o['registration_offsets'])
def guide(o):return np.asarray(o['recovered_guide']) if 'recovered_guide' in o else registration_guide(o)
def smooth_curve(points):
 p=np.asarray(points,float)
 if len(p)<3:return p
 tangent=np.empty_like(p);tangent[1:-1]=(p[2:]-p[:-2])*.5;tangent[0]=p[1]-p[0];tangent[-1]=p[-1]-p[-2]
 sampled=[]
 for i in range(len(p)-1):
  t=np.linspace(0,1,max(4,int(np.linalg.norm(p[i+1]-p[i])/2)),endpoint=False)[:,None]
  sampled.append((2*t**3-3*t**2+1)*p[i]+(t**3-2*t**2+t)*tangent[i]+(-2*t**3+3*t**2)*p[i+1]+(t**3-t**2)*tangent[i+1])
 return np.vstack(sampled+[p[-1:]])
def bezier_segments(points):
 p=np.asarray(points,float);t=np.empty_like(p);t[1:-1]=(p[2:]-p[:-2])*.5;t[0]=p[1]-p[0];t[-1]=p[-1]-p[-2]
 return np.array([[p[i],p[i]+t[i]/3,p[i+1]-t[i+1]/3,p[i+1]] for i in range(len(p)-1)])
def sample_bezier(segments,steps=4):
 curves=np.asarray(segments,float);t=np.linspace(0,1,steps,endpoint=False)[:,None];out=[]
 for p in curves:out.append((1-t)**3*p[0]+3*(1-t)**2*t*p[1]+3*(1-t)*t*t*p[2]+t**3*p[3])
 return np.vstack(out+[curves[-1,3:4]])
def reference_guide(o,edits):
 p=guide(o)
 if edits.get(o['id'],{}).get('curve_basis')=='source-cubic-v1':return sample_bezier(registered_cubics(o),12)
 return sample_bezier(bezier_segments(p)) if 'curve' in edits.get(o['id'],{}) else p
def source_cubics(o):
 if o.get('source_cubic_segments'):return o['source_cubic_segments']
 return None

def registered_cubics(o,points=None):
 # Retain the source representation and segment count. Registration calibrates
 # its control points to the appearance; it does not add a segment at each marker.
 source=source_cubics(o);count=len(source) if source else 1
 p=np.asarray(points if points is not None else guide(o),float)
 if source:
  original=np.array([[c[k] for k in ['p0','p1','p2','p3']] for c in source])*W
  src=sample_bezier(original,32);lengths=np.r_[0,np.cumsum(np.linalg.norm(np.diff(src,axis=0),axis=1))];fractions=lengths/max(lengths[-1],1e-9)
  dense,_=point_at(smooth_curve(p),fractions)
 else:dense=resample(smooth_curve(p),65)
 result=[]
 for i in range(count):
  lo=round(i*(len(dense)-1)/count);hi=round((i+1)*(len(dense)-1)/count);q=dense[lo:hi+1];t=np.linspace(0,1,len(q))[:,None]
  a=np.c_[3*(1-t)**2*t,3*(1-t)*t*t];rhs=q-(1-t)**3*q[0]-t**3*q[-1]
  controls=np.linalg.lstsq(a,rhs,rcond=None)[0]
  result.append([q[0],controls[0],controls[1],q[-1]])
 return np.asarray(result)
def load_scene():return json.loads((DATA/'scene.json').read_text('utf-8'))
def save_scene(s):
 (DATA/'scene.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),'utf-8')
def conditioning(s,edits=None):
 from . import structure
 return structure.render(sys.modules[__name__],s,edits)

def structural_geometry(s,edits=None):
 from . import structure
 return structure.geometry(sys.modules[__name__],s,edits)

def structural_records(s,edits=None):
 return {id:{key:value.tolist() if value is not None else None for key,value in item.items()} for id,item in structural_geometry(s,edits).items()}
def prompt(s,edits=None,style='青花花叶，白底，清晰的装饰轮廓'):
 active=[o for o in s['objects'] if not hidden(o['id'],s,edits or {})]
 branches=[o for o in active if o['role']=='parent'];children=[o for o in active if o['role']=='child']
 relations='；'.join(f'{o["name"]}依附{next(p["name"] for p in active if p["id"]==o["parent"])}' for o in children)
 return f'以所附结构为构图参照，生成一个可水平重复的完整植物装饰纹样。\n蓝线为主藤，绿线为承花路径，红色轮廓为花位，橙线为父枝，青线为子枝。保留主藤连续走势、花位及承花关系，不将不同枝条合并或创造新的连接。\n本方案有{len(branches)}条普通父枝、{len(children)}条子枝。{relations}。紫色线是外观附属叶饰参照，不计作结构子枝。\n在对应路径周围补充花瓣、叶片和枝条厚度。两侧边界按同一周期连续，不增加文字或边框。\n外观要求：{style}\n这是生成提示，输出仍须与输入结构核对。'
def hidden(id,s,edits):
 o=next(x for x in s['objects'] if x['id']==id)
 return bool(o.get('merged_into')) or bool(edits.get(id,{}).get('hidden')) or bool(o['parent'] and hidden(o['parent'],s,edits))
def motion_graph(s,edits):
 result={};chains={};by={o['id']:o for o in s['objects']}
 def visit(id):
  if id in result:return result[id]
  o=by[id];p=reference_guide(o,edits).copy();e=edits.get(id,{});ops=[]
  if o['parent']:
   parent=by[o['parent']];visit(parent['id']);ops=chains[parent['id']]
   for a,b,mode in ops:p=apply_motion(p,a,b,mode)
  inherited=p.copy()
  if 'points' in e:
   target=np.asarray(e['points'],float)
   if target.shape!=p.shape:raise ValueError('Control-point count mismatch')
   # Curve roots are inherited. Parent/child editing cannot rewrite the attachment point.
   if o['role'] in ['parent','child','ornament']:target[:2]=p[:2]
   if o['role'] in ['main','support'] and not e.get('unlocked'):target=p
   if o['role']=='flower' and not e.get('unlocked'):target=p
   p=target
  if 'curve' in e and o['role'] in ['parent','child','ornament']:
   structural=e.get('curve_basis')=='source-cubic-v1'
   target=sample_bezier(e['curve'],12 if structural else 4)
   if o['parent']:target=rebase_parent(target,e.get('parent_ops',[]),ops)
   if target.shape!=p.shape:raise ValueError('Bezier segment count mismatch')
   if structural:
    if 'mount_fraction' in e and o['parent']:
     # A movable root remains on its actual parent, as in the structural editor.
     parentline=smooth_curve(visit(o['parent']));root,_=point_at(parentline,float(np.clip(e['mount_fraction'],.001,.985)))
     target+=root-target[0]
    else:target[0]=p[0]
   else:target[:5]=p[:5] # Legacy segmented sessions remain readable.
   p=target
  if o['role']=='support':
   f=by[o['flower']];fe=edits.get(f['id'],{});fc=guide(f)[0];newc=np.asarray(fe.get('points',guide(f)),float)[0] if fe.get('unlocked') else fc
   end=newc+(guide(o)[-1]-fc)*fe.get('scale',1);delta=end-p[-1]
   weights=np.linspace(0,1,len(p))**3;p=p+weights[:,None]*delta
  if o['role']=='ornament' and e.get('scale',1)!=1:
   p[2:]=p[1]+(p[2:]-p[1])*e['scale']
  if not np.allclose(inherited,p):
   a,b=inherited,p
   if o['role'] in ['parent','child','ornament']:
    pins=attachment_pins(s,o)
    for pa,pb,mode in ops:pins=apply_motion(pins,pa,pb,mode)
    if len(pins):
     angle=0.
     if np.linalg.norm(p[0]-inherited[0])>1e-7 and o['parent']:
      parentline=smooth_curve(result[o['parent']]);t0=nearest([inherited[0]],parentline)[0][0];t1=nearest([p[0]],parentline)[0][0]
      u=point_at(parentline,t0)[1];v=point_at(parentline,t1)[1];angle=np.arctan2(u[0]*v[1]-u[1]*v[0],u@v)
     co,si=np.cos(angle),np.sin(angle);rotation=np.array([[co,-si],[si,co]])
     target=(pins-inherited[0])@rotation.T+p[0]
     if np.linalg.norm(p[0]-inherited[0])>1e-7:
      center=target.mean(axis=0)
      surface=articulation.parent_socket(sys.modules[__name__],s,o,center,2,ops)
      target+=surface-center
     a=np.vstack([a,pins]);b=np.vstack([b,target])
   ops=ops+[(a,b,None)]
  chains[id]=ops;result[id]=p;return p
 for o in s['objects']:visit(o['id'])
 return result,chains
def effective_guides(s,edits):return motion_graph(s,edits)[0]
def recover(s):
 from . import ownership
 from . import workflow
 # Remove the former case-specific material override, including saved projects.
 for o in s['objects']:
  if o.get('appearance_mode')=='rigid_foliage':o.pop('appearance_mode')
 rgb=np.asarray(Image.open(DATA/s['image']).convert('RGB').resize((W,H)));lum=rgb@np.array([.2126,.7152,.0722]);ink=(lum<247).astype('uint8');objs=s['objects']
 owner,protected=ownership.partition(sys.modules[__name__],s,rgb)
 owner=workflow.apply_regions(s,owner,ink)
 np.save(DATA/'ownership.npy',owner);np.save(DATA/'protected.npy',protected)
 layers=[]
 for top in range(252,8,-4):
  pix=rgb[(lum<top)&(lum>=top-4)]
  if len(pix):layers.append((top,'#'+''.join(f'{int(v):02x}' for v in np.median(pix,axis=0))))
 groups={};stats={}
 for i,o in enumerate(objs):
  owned=(owner==i)&(ink>0)
  ps=[]
  for top,color in layers:
   # Exact pixel-cell unions give adjacent roles a shared boundary without overlapping
   # ownership. The old dilated masks left detached one-pixel remnants after deletion.
   mask=(lum<top)&owned;d=cell_contours(mask)
   if d:
    if s.get('periodic_registration'):d=unwrap_contours(d,guide(o))
    ps.append({'fill':color,'d':d})
  groups[o['id']]=ps;stats[o['id']]=int(np.sum((owner==i)&(ink>0)))
 (DATA/'vectors.json').write_text(json.dumps(groups,separators=(',',':')),'utf-8');CACHE.clear()
 s['recovery_revision']=4;save_scene(s)
 return {'objects':len(groups),'paths':sum(map(len,groups.values())),'areas':stats}

def unwrap_contours(d,line):
 """Keep each cut material piece in its object's unfolded coordinate frame.

 The exported period clips/wraps these paths. Motion must see the nearby parent,
 rather than treat the left half of a right-edge leaf as a distant object.
 """
 line=resample(line,min(160,max(2,len(line))));result=[]
 for contour in d.split('Z'):
  if not contour:continue
  points=np.array([[float(x),float(y)] for x,y in re.findall(r'[ML](-?[\d.]+),(-?[\d.]+)',contour)])
  if not len(points):continue
  samples=points[np.linspace(0,len(points)-1,min(32,len(points))).astype(int)]
  center=int(round((float(line[:,0].mean())-float(samples[:,0].mean()))/W))
  shifts=list(range(center-1,center+2))
  score=[float(np.min(np.sum((samples[:,None,:]+[k*W,0]-line[None,:,:])**2,axis=2),axis=1).mean()) for k in shifts]
  shift=shifts[int(np.argmin(score))]*W
  if shift:
   it=iter(points+[shift,0]);contour=re.sub(r'([ML])(-?[\d.]+),(-?[\d.]+)',lambda m:m[1]+','.join(f'{v:g}' for v in next(it)),contour)
  result.append(contour+'Z')
 return ''.join(result)
def cell_contours(mask):
 # Trace the exterior of the exact pixel-cell union, including holes. Unlike tiled
 # rectangles, this has no internal T junctions that can split during deformation.
 p=np.pad(mask,1);edges={}
 def add(a,b):edges.setdefault(a,[]).append(b)
 for y,x in zip(*np.where(mask&~p[:-2,1:-1])):add((int(x),int(y)),(int(x+1),int(y)))
 for y,x in zip(*np.where(mask&~p[1:-1,2:])):add((int(x+1),int(y)),(int(x+1),int(y+1)))
 for y,x in zip(*np.where(mask&~p[2:,1:-1])):add((int(x+1),int(y+1)),(int(x),int(y+1)))
 for y,x in zip(*np.where(mask&~p[1:-1,:-2])):add((int(x),int(y+1)),(int(x),int(y)))
 paths=[]
 while edges:
  start=next(iter(edges));cur=start;last=None;poly=[]
  while True:
   poly.append(cur);options=edges[cur]
   if len(options)>1 and last is not None:
    dx,dy=cur[0]-last[0],cur[1]-last[1]
    nxt=max(options,key=lambda q:dx*(q[1]-cur[1])-dy*(q[0]-cur[0]))
   else:nxt=options[0]
   options.remove(nxt)
   if not options:del edges[cur]
   last,cur=cur,nxt
   if cur==start:break
  reduced=[]
  for k,q in enumerate(poly):
   a=poly[k-1];b=poly[(k+1)%len(poly)]
   if (q[0]-a[0])*(b[1]-q[1])!=(q[1]-a[1])*(b[0]-q[0]):reduced.append(q)
  paths.append('M'+'L'.join(f'{x},{y}' for x,y in reduced)+'Z')
 return ''.join(paths)
def vectors():
 if 'vectors' not in CACHE:CACHE['vectors']=json.loads((DATA/'vectors.json').read_text('utf-8'))
 return CACHE['vectors']
def prepared_path(d,dense):
 cache=CACHE.setdefault('prepared_paths',{})
 key=(d,dense)
 if key in cache:return cache[key]
 if dense:
  paths=[]
  for path in d.split('Z'):
   vertices=np.array([[float(a),float(b)] for a,b in re.findall(r'[ML](-?[\d.]+),(-?[\d.]+)',path)])
   if not len(vertices):continue
   samples=[]
   for a,b in zip(vertices,np.roll(vertices,-1,axis=0)):
    n=max(1,int(np.ceil(np.linalg.norm(b-a)/2)));samples.extend(a+(b-a)*t/n for t in range(n))
   paths.append('M'+'L'.join(f'{x:g},{y:g}' for x,y in samples)+'Z')
  d=''.join(paths)
 pts=np.array([[float(a),float(b)] for a,b in re.findall(r'[ML](-?[\d.]+),(-?[\d.]+)',d)])
 cache[key]=(d,pts)
 return d,pts
def transform_path(d,old,new,affine=None):
 if affine is None and np.array_equal(old,new):return d
 d,pts=prepared_path(d,affine is None)
 if not len(pts):return d
 if affine is not None:pts=pts@affine[:2,:2].T+affine[:2,2]
 elif not np.array_equal(old,new):pts=map_curve(pts,old,new)
 else:return d
 it=iter(pts);return re.sub(r'([ML])(-?[\d.]+),(-?[\d.]+)',lambda m:m[1]+','.join(f'{v:.2f}' for v in next(it)),d)
def attachment_pins(s,o):
 key=('attachment_pins',o['id'])
 if key in CACHE:return CACHE[key]
 ids=[v['id'] for v in s['objects']]
 if not o['parent'] or o['parent'] not in ids:return np.empty((0,2))
 from . import ownership
 owner=np.load(DATA/'ownership.npy');rgb=np.asarray(Image.open(DATA/s['image']).convert('RGB'));ink=rgb@np.array([.2126,.7152,.0722])<235
 pts=ownership.joint_pixels(sys.modules[__name__],owner,ink,ids.index(o['id']),ids.index(o['parent']),periodic=bool(s.get('periodic_registration')),reference_x=float(guide(o)[0,0]))
 if len(pts):
  pts=pts[np.lexsort((pts[:,1],pts[:,0]))];pts=pts[np.unique(np.linspace(0,len(pts)-1,min(12,len(pts))).astype(int))]
 CACHE[key]=pts;return pts
def svg(s,edits=None,repeats=1,selected=None,as_groups=False):
 edits=edits or {};V=vectors();guides,chains=motion_graph(s,edits);by={o['id']:o for o in s['objects']};groups=[]
 def chain(id):return chains[id]
 for o in s['objects']:
  if hidden(o['id'],s,edits):continue
  e=edits.get(o['id'],{});asset=by.get(e.get('replacement'),o);paths=V[asset['id']];old=guide(asset);new=guides[o['id']];affine=None
  if o['role']=='flower':
   oldc=old[0];newc=new[0];rx=np.array(o['radii'])/np.array(asset['radii'])*e.get('scale',1);affine=np.array([[rx[0],0,newc[0]-rx[0]*oldc[0]],[0,rx[1],newc[1]-rx[1]*oldc[1]],[0,0,1]])
   if asset['id']==o['id'] and e.get('scale',1)==1 and np.array_equal(oldc,newc):affine=None
  elif asset['id']!=o['id']:
   # Material replacement is fitted to the target's actual attachment curve.
   pass
  ops=chain(o['id'])
  key=(o['id'],asset['id'],tuple(old.ravel()),tuple(new.ravel()),tuple(affine.ravel()) if affine is not None else None,tuple((tuple(a.ravel()),tuple(b.ravel()),mode) for a,b,mode in ops))
  group_cache=CACHE.setdefault('rendered_groups',{})
  if key in group_cache:
   groups.append(group_cache[key]);continue
  parts=[f'<g id="{o["id"]}" data-role="{o["role"]}" data-parent="{o["parent"] or ""}" data-source="{o["source_id"]}"><title>{o["name"]}</title>']
  parts.append('<g data-material="body">')
  for p in paths:
   if o['role']=='flower':d=transform_path(p['d'],old,new,affine)
   else:
    d=p['d']
    if asset['id']!=o['id']:d=transform_path(d,old,guide(o))
    # Child appearance receives exactly its parent's spatial mapping, not a second
    # independently fitted approximation. Shared attachment boundaries stay shared.
    for a,b,mode in ops:
     d=transform_path(d,a,b)
   parts.append(f'<path fill="{p["fill"]}" fill-rule="evenodd" d="{d}"/>')
  parts.append('</g></g>');group=''.join(parts);groups.append(group)
  if len(group_cache)>56:group_cache.pop(next(iter(group_cache)))
  group_cache[key]=group
 if as_groups:return {E.fromstring(g.encode()).get('id'):g for g in groups}
 content=''.join(groups)
 if repeats==1:return f'<svg xmlns="{NS}" viewBox="0 0 {W} {H}" width="{W}" height="{H}"><rect width="100%" height="100%" fill="white"/>{content}</svg>'
 return f'<svg xmlns="{NS}" viewBox="0 0 {W*repeats} {H}" width="{W*repeats}" height="{H}"><defs><g id="unit">{content}</g></defs><rect width="100%" height="100%" fill="white"/>'+''.join(f'<use href="#unit" x="{i*W}"/>' for i in range(repeats))+'</svg>'
def project(s,edits=None):
 edits=edits or {};G,chains=motion_graph(s,edits)
 objects=[]
 for o in s['objects']:
  e=edits.get(o['id'],{});curves=e.get('curve');parentops=chains[o['parent']] if o['parent'] else []
  if curves is not None:
   shape=np.asarray(curves).shape;curves=rebase_parent(np.asarray(curves).reshape(-1,2),e.get('parent_ops',[]),parentops).reshape(shape)
   curves+=G[o['id']][0]-curves[0,0];curves=curves.tolist()
  if e.get('curve_basis')!='source-cubic-v1':curves=registered_cubics(o,G[o['id']]).tolist()
  parentline=smooth_curve(G[o['parent']]).tolist() if o['parent'] else []
  joint=attachment_pins(s,o)
  for a,b,mode in chains[o['id']]:joint=apply_motion(joint,a,b,mode)
  objects.append({**o,'parent_ops':[[a.tolist(),b.tolist(),m] for a,b,m in parentops],'joint_boundary':joint.tolist(),'guide':G[o['id']].tolist(),'curve':curves,'curve_basis':'source-cubic-v1','parent_guide':parentline,'source_cubic_segments':source_cubics(o),'alignment_guide':resample(guide(o),min(8,len(guide(o)))).tolist(),'registered_guide':guide(o).tolist(),'hidden':hidden(o['id'],s,edits)})
 return {'schema':'structvine-design-v2','source_case':s['case_id'],'coordinate_system':'registered appearance pixels; one horizontal period','period':W,'height':H,'objects':objects,'structural_objects':structural_records(s,edits),'edits':edits,'scene':s,'provenance':s.get('provenance',{}),'render_records':s.get('render_records',[])}
def geometry_warnings(s,edits):
 G=effective_guides(s,edits);issues=[]
 for o in s['objects']:
  if o['role'] not in ['parent','child'] or o['id'] not in edits or hidden(o['id'],s,edits):continue
  new=resample(G[o['id']],60);old=resample(guide(o),60)
  for f in s['objects']:
   if f['role']!='flower':continue
   c=G[f['id']][0];r=np.array(f['radii'])*edits.get(f['id'],{}).get('scale',1)
   if np.any(np.sum(((new-c)/r)**2,axis=1)<.85) and not np.any(np.sum(((old-guide(f)[0])/np.array(f['radii']))**2,axis=1)<.85):issues.append(o['name']+'进入'+f['name']+'范围')
 if 'vine' in edits:
  p=G['vine']
  if np.linalg.norm((p[-1]-p[0])-np.array([W,0]))>1e-4:issues.append('主藤两端未按周期对齐')
 return issues
def package(s,edits=None,style='',kind='design',settings=None):
 from . import workflow
 b=io.BytesIO()
 structure=conditioning(s,edits);(OUT/'condition.svg').write_text(structure,'utf-8')
 inkscape=os.environ.get('PAPERA_INKSCAPE') or os.environ.get('INKSCAPE_EXE') or 'D:/inkspace/bin/inkscape.exe'
 subprocess.run([inkscape,str(OUT/'condition.svg'),'--export-type=png','--export-width=1390',f'--export-filename={OUT}/condition.png'],creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0,check=True,capture_output=True)
 p=workflow.document(s,edits,settings)
 with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('structure.svg',structure);z.write(OUT/'condition.png','structure.png');z.writestr('render_prompt.txt',prompt(s,edits,style));z.writestr('project.json',json.dumps(p,ensure_ascii=False,indent=2));z.writestr('original_source_structure.json',json.dumps(s.get('source_structure',{}),ensure_ascii=False,indent=2))
  for i,record in enumerate(p.get('render_records',[]),1):
   if record.get('structure_image_base64'):z.writestr(f'generation_records/input_{i}.png',base64.b64decode(record['structure_image_base64']))
   if record.get('prompt'):z.writestr(f'generation_records/prompt_{i}.txt',record['prompt'])
   if record.get('pair_record'):z.writestr(f'generation_records/pair_{i}.json',json.dumps(record['pair_record'],ensure_ascii=False,indent=2))
   if record.get('input',{}):
    z.writestr(f'generation_records/input_{i}.svg',record['input']['structure_svg']);z.writestr(f'generation_records/prompt_{i}.txt',record['input']['prompt'])
  if kind=='design':z.writestr('editable.svg',workflow.portable_svg(s,edits,settings));z.writestr('repeat.svg',workflow.portable_svg(s,edits,settings,True));z.writestr('design_notes.json',json.dumps({'provenance':s.get('provenance',{}),'render_records':s.get('render_records',[]),'settings':settings or {}},ensure_ascii=False,indent=2))
 return b.getvalue()
