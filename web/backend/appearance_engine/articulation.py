"""Match a movable joint to its parent's recovered surface."""
import numpy as np
def parent_socket(c,s,o,requested,width,parent_ops=()):
 ids=[a['id'] for a in s['objects']]
 if o.get('parent') not in ids:return requested
 key=('parent_interior',o['parent'],round(width,2))
 if key not in c.CACHE:
  owner=np.load(c.DATA/'ownership.npy');rgb=np.asarray(c.Image.open(c.DATA/s['image']).convert('RGB'));ink=rgb@np.array([.2126,.7152,.0722])<247
  mask=((owner==ids.index(o['parent']))&ink).astype('uint8')
  if s.get('periodic_registration'):dt=c.cv2.distanceTransform(np.tile(mask,(1,3)),c.cv2.DIST_L2,5)[:,c.W:2*c.W]
  else:dt=c.cv2.distanceTransform(mask,c.cv2.DIST_L2,5)
  y,x=np.where(dt>=max(1,width/2))
  if not len(x):y,x=np.where(mask)
  pts=np.c_[x+.5,y+.5]
  if s.get('periodic_registration') and len(pts):
   line=c.guide(s['objects'][ids.index(o['parent'])]);center=int(round((line[:,0].mean()-pts[:,0].mean())/c.W));variants=[];cost=[]
   for k in range(center-1,center+2):
    q=pts+[k*c.W,0];t,_=c.nearest(q,line);near,_=c.point_at(line,t);variants.append(q);cost.append(np.sum((q-near)**2,axis=1))
   choice=np.argmin(cost,axis=0);pts=np.stack(variants)[choice,np.arange(len(pts))]
  c.CACHE[key]=pts
 pts=c.CACHE[key]
 for a,b,mode in parent_ops:pts=c.apply_motion(pts,a,b,mode)
 if s.get('periodic_registration') and len(pts):pts=pts+np.c_[np.rint((requested[0]-pts[:,0])/c.W)*c.W,np.zeros(len(pts))]
 return pts[np.argmin(np.sum((pts-requested)**2,axis=1))] if len(pts) else requested

