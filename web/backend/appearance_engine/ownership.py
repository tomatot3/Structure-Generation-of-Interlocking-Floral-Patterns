"""Topology-aware ink partition, with junctions cut at the parent's visible envelope.

Paint highlights are not semantic boundaries. Seeded foreground propagation owns
whole connected material; robust cross sections reserve only the continuing stem,
not the entire foreground run where a side branch joins it.
"""
import heapq
from types import SimpleNamespace
import numpy as np

def _components(c,mask,periodic=False):
 """Connected material on the plane, or on a horizontally periodic canvas."""
 count,labels=c.cv2.connectedComponents(mask.astype('uint8'),8)
 if not periodic or count<2:return count,labels
 roots=list(range(count))
 def find(k):
  while roots[k]!=k:roots[k]=roots[roots[k]];k=roots[k]
  return k
 for y in range(mask.shape[0]):
  left=int(labels[y,0])
  if not left:continue
  for yy in range(max(0,y-1),min(mask.shape[0],y+2)):
   right=int(labels[yy,-1])
   if right:
    a,b=find(left),find(right)
    if a!=b:roots[b]=a
 roots=np.array([find(k) for k in range(count)]);unique=np.unique(roots)
 return len(unique),np.searchsorted(unique,roots)[labels]

def _distance(c,mask,periodic=False):
 if not periodic:return c.cv2.distanceTransform(mask.astype('uint8'),c.cv2.DIST_L2,5)
 width=mask.shape[1]
 return c.cv2.distanceTransform(np.tile(mask.astype('uint8'),(1,3)),c.cv2.DIST_L2,5)[:,width:2*width]

def _line(c,mask,points,thickness,periodic=False):
 for shift in (-c.W,0,c.W) if periodic else (0,):
  c.cv2.polylines(mask,[np.rint(np.asarray(points)+[shift,0]).astype(np.int32)],False,1,thickness)

def joint_pixels(c,owner,ink,index,parent,periodic=False,reference_x=None):
 """Contact of the principal physical body, excluding detached paint specks."""
 n,cc=_components(c,(owner==index)&ink,periodic)
 if n<2:return np.empty((0,2))
 sizes=np.bincount(cc.ravel());own=cc==(1+int(np.argmax(sizes[1:])))
 par=(owner==parent)&ink
 extended=np.tile(par,(1,3)) if periodic else par
 dilated=c.cv2.dilate(extended.astype('uint8'),np.ones((3,3),np.uint8))>0
 if periodic:dilated=dilated[:,c.W:2*c.W]
 contact=own&dilated
 n,cc=_components(c,contact,periodic)
 if n<2:
  dist=_distance(c,~par,periodic)
  contact=own&(dist<=dist[own].min()+1)
 else:
  sizes=np.bincount(cc.ravel());contact=cc==(1+int(np.argmax(sizes[1:])))
 y,x=np.where(contact);x=x.astype(float)+.5
 if periodic and len(x):
  anchor=float(reference_x) if reference_x is not None else float(x[0])
  x+=np.rint((anchor-x)/c.W)*c.W
 return np.c_[x,y+.5]

def trace_ink(c,lum,points):
 """Shortest foreground route guided by the supplied structural path.

 Centre-distance favours the stem interior. Guide distance disambiguates routes
 at crossings; it does not prescribe the stem boundary or its thickness.
 """
 # Near-white JPEG/antialias halos are retained later for appearance, but cannot
 # serve as a bridge through empty space when tracing the physical stem.
 ink=lum<235;dt=c.cv2.distanceTransform(ink.astype('uint8'),c.cv2.DIST_L2,5)
 seed=np.zeros(ink.shape,np.uint8);c.cv2.polylines(seed,[np.rint(c.smooth_curve(points)).astype(np.int32)],False,1,1)
 gd=c.cv2.distanceTransform(1-seed,c.cv2.DIST_L2,5);yy,xx=np.where(ink);coords=np.c_[xx,yy]
 if not len(coords):return np.asarray(points)
 endpoints=[]
 for q in [points[0],points[-1]]:
  endpoints.append(tuple(coords[np.argmin(np.sum((coords-q)**2,axis=1))][::-1]))
 start,end=endpoints;near=gd[ink&(gd<min(getattr(c,'unit_width',c.W),c.H)*.05)]
 radius=max(8,float(np.quantile(near,.6))) if len(near) else 8
 cost=1+(gd/max(radius,1))**2+6/(dt+1)
 dist=np.full(ink.shape,np.inf);previous=np.full(ink.shape,-1,np.int32);dist[start]=0;heap=[(0,*start)]
 steps=[(-1,0,1),(1,0,1),(0,-1,1),(0,1,1),(-1,-1,1.414),(1,-1,1.414),(-1,1,1.414),(1,1,1.414)]
 while heap:
  d,y,x=heapq.heappop(heap)
  if d>dist[y,x]:continue
  if (y,x)==end:break
  for dy,dx,w in steps:
   a=y+dy;b=x+dx
   if 0<=a<c.H and 0<=b<c.W and ink[a,b]:
    nd=d+w*(cost[y,x]+cost[a,b])*.5
    if nd<dist[a,b]:dist[a,b]=nd;previous[a,b]=y*c.W+x;heapq.heappush(heap,(nd,a,b))
 if not np.isfinite(dist[end]):return np.asarray(points)
 line=[];p=end
 while p!=start:
  line.append([p[1]+.5,p[0]+.5]);k=previous[p];p=divmod(int(k),c.W)
 line.append([start[1]+.5,start[0]+.5]);line=np.array(line[::-1])
 # Smooth pixel staircase without drifting across a different foreground component.
 window=5;pad=np.pad(line,((window,window),(0,0)),mode='edge');line=np.array([pad[j:j+2*window+1].mean(axis=0) for j in range(len(line))])
 return c.resample(line,max(8,int(len(line)/5)))

def stem_envelope(c,lum,points):
 p=c.resample(c.smooth_curve(points),max(30,int(np.linalg.norm(np.diff(points,axis=0),axis=1).sum())))
 tangent=np.gradient(p,axis=0);tangent/=np.maximum(np.linalg.norm(tangent,axis=1)[:,None],1e-9)
 normal=np.c_[-tangent[:,1],tangent[:,0]]
 # Search width only limits the image profile query, not the recovered stem width.
 reach=int(np.ceil(min(getattr(c,'unit_width',c.W),c.H)*.08));off=np.arange(-reach,reach+1)
 bounds=np.full((len(p),2),np.nan)
 for j,(q,n) in enumerate(zip(p,normal)):
  xy=np.rint(q+off[:,None]*n).astype(int);valid=(xy[:,0]>=0)&(xy[:,0]<c.W)&(xy[:,1]>=0)&(xy[:,1]<c.H)
  ink=np.zeros(len(off),bool);ink[valid]=lum[xy[valid,1],xy[valid,0]]<247
  hits=np.flatnonzero(ink)
  if not len(hits):continue
  k=hits[np.argmin(abs(off[hits]))]
  # Off-image/poorly registered samples cannot create a broad protected area.
  if abs(off[k])>reach/4:continue
  a=b=k
  while a>0 and ink[a-1]:a-=1
  while b+1<len(off) and ink[b+1]:b+=1
  bounds[j]=[off[a]-.5,off[b]+.5]
 widths=np.diff(bounds,axis=1)[:,0];typical=np.nanmedian(widths)
 if not np.isfinite(typical):return np.zeros(lum.shape,np.uint8)
 # A junction widens a cross section on one side. Estimate continuation from
 # nearby narrower sections, independently on the two sides of the centreline.
 window=max(3,int(np.ceil(typical*2)))
 smooth=bounds.copy()
 for j in range(len(p)):
  b=bounds[max(0,j-window):min(len(p),j+window+1)]
  b=b[np.isfinite(b).all(axis=1)]
  if len(b):smooth[j]=[np.quantile(b[:,0],.7),np.quantile(b[:,1],.3)]
 mask=np.zeros(lum.shape,np.uint8)
 for j in range(len(p)-1):
  if not np.isfinite(smooth[j:j+2]).all():continue
  a=p[j]+normal[j]*smooth[j,0];b=p[j]+normal[j]*smooth[j,1]
  d=p[j+1]+normal[j+1]*smooth[j+1,0];e=p[j+1]+normal[j+1]*smooth[j+1,1]
  c.cv2.fillConvexPoly(mask,np.rint([a,b,e,d]).astype(np.int32),1)
 return mask

def partition(c,s,rgb):
 lum=rgb@np.array([.2126,.7152,.0722]);ink=lum<247;objs=s['objects'];ids=[o['id'] for o in objs]
 periodic=bool(s.get('periodic_registration'))
 if periodic:
  # Trace the unwrapped path through neighboring copies. Taking endpoints modulo
  # W would collapse the main vine's complete period to a zero-length route.
  expanded=SimpleNamespace(W=3*c.W,H=c.H,unit_width=c.W,cv2=c.cv2,smooth_curve=c.smooth_curve,resample=c.resample)
  tiled=np.tile(lum,(1,3));traces={};envelopes={}
  for o in objs:
   if o['role']=='flower':continue
   reference=c.registration_guide(o)
   p=reference if o.get('manual_object') else trace_ink(expanded,tiled,reference+[c.W,0])-[c.W,0]
   traces[o['id']]=p
   if o['role'] in ['main','support','parent']:
    full=stem_envelope(expanded,tiled,p+[c.W,0])
    envelopes[o['id']]=full.reshape(c.H,3,c.W).max(axis=1)
 else:
  traces={o['id']:(c.registration_guide(o) if o.get('manual_object') else trace_ink(c,lum,c.registration_guide(o))) for o in objs if o['role']!='flower'}
  envelopes={o['id']:stem_envelope(c,lum,traces[o['id']]) for o in objs if o['role'] in ['main','support','parent']}
 reserved=np.full(ink.shape,-1,np.int16)
 # Parent-before-child traversal is structural, never tied to case or object IDs.
 depth={}
 def level(o):
  if o['id'] not in depth:depth[o['id']]=level(objs[ids.index(o['parent'])])+1 if o.get('parent') else 0
  return depth[o['id']]
 for o in sorted(objs,key=level):
  if o['id'] in envelopes:
   m=envelopes[o['id']].astype(bool)&ink&(reserved<0);reserved[m]=ids.index(o['id'])
 seeds=[];D=[]
 for i,o in enumerate(objs):
  mask=np.zeros(ink.shape,np.uint8);p=traces[o['id']] if o['role']!='flower' else c.guide(o)
  if o.get('manual_object'):
   D.append(np.full(ink.shape,1e6));seeds.append(mask);continue
  if o['role']=='flower':
   for shift in (-c.W,0,c.W) if periodic else (0,):
    c.cv2.ellipse(mask,tuple(np.rint(p[0]+[shift,0]).astype(int)),tuple(np.rint(np.array(o['radii'])*.65).astype(int)),0,0,360,1,-1)
  else:_line(c,mask,p,3,periodic)
  D.append(_distance(c,1-mask,periodic));mask&=ink.astype('uint8');mask[(reserved>=0)&(reserved!=i)]=0;mask[reserved==i]=1;seeds.append(mask)
 distance=np.full(ink.shape,np.inf);owner=np.full(ink.shape,-1,np.int16);heap=[]
 closest=np.argmin(D,axis=0)
 for i,seed in enumerate(seeds):
  yy,xx=np.where((seed>0)&((closest==i)|(reserved==i)))
  for y,x in zip(yy,xx):distance[y,x]=0;owner[y,x]=i;heapq.heappush(heap,(0,int(y),int(x),i))
 for stroke in s.get('corrections',[]):
  i=ids.index(stroke['object']);mask=np.zeros(ink.shape,np.uint8);_line(c,mask,stroke['points'],int(stroke.get('size',18)),periodic)
  # Existing broad correction brushes may cross a parent stem. Reserve its
  # measured continuing envelope; the editable cut is at that envelope's edge.
  yy,xx=np.where((mask>0)&ink&((reserved<0)|(reserved==i)))
  for y,x in zip(yy,xx):distance[y,x]=0;owner[y,x]=i;heapq.heappush(heap,(0,int(y),int(x),i))
 steps=[(-1,0,1),(1,0,1),(0,-1,1),(0,1,1),(-1,-1,1.414),(1,-1,1.414),(-1,1,1.414),(1,1,1.414)]
 while heap:
  d,y,x,i=heapq.heappop(heap)
  if d>distance[y,x] or owner[y,x]!=i:continue
  for dy,dx,w in steps:
   yy=y+dy;xx=x+dx
   if periodic:xx%=c.W
   if 0<=yy<c.H and 0<=xx<c.W and ink[yy,xx] and d+w<distance[yy,xx]:
    distance[yy,xx]=d+w;owner[yy,xx]=i;heapq.heappush(heap,(d+w,yy,xx,i))
 # A disconnected antialiased fragment follows its nearest established body as
 # a whole component, instead of being split pixel-by-pixel between guide lines.
 n,cc=_components(c,ink&(owner<0),periodic)
 bodydist=[_distance(c,owner!=i,periodic) if np.any(owner==i) else np.full(ink.shape,1e6) for i in range(len(objs))]
 for k in range(1,n):
  m=cc==k;owner[m]=int(np.argmin([d[m].mean() for d in bodydist]))
 # Classify detached paint/antialias fragments against actual object bodies.
 # A coarse guide crossing one fragment is insufficient to reserve it forever.
 detached=[];bodydist=[]
 for i in range(len(objs)):
  count,cc=_components(c,ink&(owner==i),periodic)
  sizes=np.bincount(cc.ravel());principal=1+int(np.argmax(sizes[1:])) if count>1 else -1
  body=cc==principal
  bodydist.append(_distance(c,~body,periodic) if body.any() else np.full(ink.shape,1e6))
  for k in range(1,count):
   if k!=principal:detached.append(cc==k)
 for m in detached:
  owner[m]=int(np.argmin([d[m].mean() for d in bodydist]))
 owner[~ink]=closest[~ink]
 # Editing consumes the same image-registered paths as recovery. A coarse
 # structural root inside a shared stem is not the visible material's joint.
 for o in sorted(objs,key=level):
  if o['role']=='flower':continue
  p=traces[o['id']]
  if o['role'] in ['parent','child','ornament'] and o.get('parent') in ids:
   i=ids.index(o['id']);pi=ids.index(o['parent']);part=joint_pixels(c,owner,lum<235,i,pi,periodic,float(p[0,0]))
   if len(part):
    joint=part.mean(axis=0);parent=objs[pi];parentline=np.asarray(parent.get('recovered_guide',traces[parent['id']]))
    candidates=[]
    for shift in (-c.W,0,c.W) if periodic else (0,):
     line=parentline+[shift,0];t=c.nearest([joint],line)[0][0];root=c.point_at(line,t)[0];candidates.append(root)
    root=min(candidates,key=lambda q:np.linalg.norm(q-joint))
    j=int(np.argmin(np.linalg.norm(p-joint,axis=1)));p=np.vstack([root,joint,p[j+1:]])
  o['recovered_guide']=p.tolist()
 return owner.astype('uint8'),np.where(reserved>=0,reserved+1,0).astype('uint8')
