"""Designer workflow: real structure input, correctable objects and portable output."""
import json,copy,base64,time,io,zipfile,math
import numpy as np
from . import core as c

def set_current(edits,settings=None):
 (c.DATA/'design_state.json').write_text(json.dumps({'edits':edits or {},'settings':settings or {'height_mm':50,'repeats':3}},ensure_ascii=False),'utf-8')
def current():
 p=c.DATA/'design_state.json'
 return json.loads(p.read_text('utf-8')) if p.exists() else {'edits':{},'settings':{'height_mm':50,'repeats':3}}

def portable_svg(s,edits=None,settings=None,repeated=False):
 settings=settings or {};doc=c.E.fromstring(c.svg(s,edits).encode());sources={g.get('id'):g for g in doc if g.tag.endswith('g')};by={o['id']:o for o in s['objects']};height_units=s.get('height',c.H)
 # Retain one editable geometry per object. Periodic instances are references,
 # clipped to the same canonical cell used by the browser and cup texture.
 used_ids={n.get('id') for n in doc.iter() if n.get('id')}
 def unique_id(stem):
  result=stem
  while result in used_ids:result+='_' 
  used_ids.add(result);return result
 defs=next((n for n in doc if n.tag=='{'+c.NS+'}defs'),None)
 if defs is None:defs=c.E.Element('{'+c.NS+'}defs');doc.insert(0,defs)
 clip_id=unique_id('period_clip');clip=c.E.SubElement(defs,'{'+c.NS+'}clipPath',id=clip_id,clipPathUnits='userSpaceOnUse');c.E.SubElement(clip,'{'+c.NS+'}rect',x='0',y='0',width=str(c.W),height=str(height_units))
 nodes={}
 for index,(id,source) in enumerate(sources.items()):
  wrapper=c.E.Element('{'+c.NS+'}g',id=unique_id('period_object_'+str(index)));wrapper.set('data-periodic-object',id);wrapper.set('clip-path',f'url(#{clip_id})');source.addprevious(wrapper);wrapper.append(source);nodes[id]=wrapper
  points=[c.prepared_path(p.get('d',''),False)[1] for p in source.iter('{'+c.NS+'}path')];points=[p for p in points if len(p)]
  if not points:continue
  points=np.vstack(points);left=float(points[:,0].min());right=float(points[:,0].max())
  for k in range(math.floor(-right/c.W)+1,math.ceil((c.W-left)/c.W)):
   if k:c.E.SubElement(wrapper,'{'+c.NS+'}use',href='#'+id,x=str(k*c.W),attrib={'data-object':id,'data-periodic-copy':str(k)})
 ink='http://www.inkscape.org/namespaces/inkscape'
 grouped=set()
 def children(id):return [o['id'] for o in s['objects'] if o.get('parent')==id and o['id'] in nodes]
 def unit(id):
  grouped.add(id);o=by[id];g=c.E.Element('{'+c.NS+'}g',id=unique_id('group_'+id));g.set('data-object-group',id);g.set('{'+ink+'}label',o['name']+'（完整组）');g.append(nodes[id])
  for child in children(id):
   if child not in grouped:g.append(unit(child))
  return g
 for o in s['objects']:
  if o['role']=='parent' and o['id'] in nodes and o['id'] not in grouped:
   index=list(doc).index(nodes[o['id']]);group=unit(o['id']);doc.insert(index,group)
 n=max(1,min(24,int(settings.get('repeats',3)))) if repeated else 1
 if repeated:
  content=c.E.Element('{'+c.NS+'}g',id=unique_id('repeat_unit'))
  for g in list(doc):
   if g.tag.endswith('g'):content.append(g)
  defs.append(content)
  for i in range(n):c.E.SubElement(doc,'{'+c.NS+'}use',href='#'+content.get('id'),x=str(i*c.W))
 height=max(5,min(500,float(settings.get('height_mm',50))));width=height*c.W/height_units*n
 doc.set('viewBox',f'0 0 {c.W*n} {height_units}');doc.set('width',f'{width:.4f}mm');doc.set('height',f'{height:.4f}mm')
 metadata=c.E.SubElement(doc,'{'+c.NS+'}metadata');metadata.text=json.dumps({'source':s.get('provenance',{}),'case':s.get('case_id'),'band_height_mm':height,'repeats':n,'unit_width_mm':width/n},ensure_ascii=False)
 return c.E.tostring(doc,encoding='unicode')

def document(s,edits=None,settings=None):
 p=copy.deepcopy(c.project(s,edits));p['appearance_base64']=base64.b64encode((c.DATA/s['image']).read_bytes()).decode();p['settings']=settings or {}
 for record in p['scene'].get('render_records',[]):
  source=record.get('structure_image_url')
  if source and not record.get('structure_image_base64'):
   path=c.ROOT/source
   if path.is_file():record['structure_image_base64']=base64.b64encode(path.read_bytes()).decode()
 p['render_records']=copy.deepcopy(p['scene'].get('render_records',[]));return p

_version_info={}
def versions():
 folder=c.DATA/'named_versions';folder.mkdir(exist_ok=True)
 result=[]
 for p in folder.glob('*.json'):
  key=(str(p),p.stat().st_mtime_ns)
  if key not in _version_info:_version_info[key]=json.loads(p.read_text('utf-8'))['version_info']
  result.append({'id':p.stem,**_version_info[key]})
 return sorted(result,key=lambda p:p['created'],reverse=True)

def save_version(s,edits,settings,name):
 folder=c.DATA/'named_versions';folder.mkdir(exist_ok=True);id=str(time.time_ns());p=document(s,edits,settings);p['version_info']={'name':name.strip() or '设计版本','created':time.strftime('%Y-%m-%d %H:%M:%S'),'case':s.get('case_id')};(folder/(id+'.json')).write_text(json.dumps(p,ensure_ascii=False),'utf-8');(folder/(id+'.svg')).write_text(portable_svg(s,edits,settings),'utf-8');return id

def load_version(id):
 if not str(id).isdigit():raise ValueError('无效版本')
 return json.loads((c.DATA/'named_versions'/(str(id)+'.json')).read_text('utf-8'))

def normalize_legacy(s,edits):
 e=copy.deepcopy(edits)
 # Only old projects without authoring-frame records need this one-time step.
 _,chains=c.motion_graph(s,{k:v for k,v in e.items() if not next((o.get('parent') for o in s['objects'] if o['id']==k),None) or next(o['role'] for o in s['objects'] if o['id']==k)=='parent'})
 for o in s['objects']:
  v=e.get(o['id'],{})
  if 'curve' in v and 'parent_ops' not in v:
   v['parent_ops']=[[a.tolist(),b.tolist(),m] for a,b,m in chains.get(o.get('parent'),[])]
 return e

def retain_design(before,s):
 """Re-author existing curve edits in the recovered parent's current frame.

 Recovery changes material ownership in ORIGINAL image coordinates. It must not
 turn a correction into a design reset. Unedited descendants still inherit their
 parent; explicitly edited curves keep their displayed controls and appearance
 settings. A changed attachment is allowed to move the root to its real parent.
 """
 e=copy.deepcopy(before['edits']);by={o['id']:o for o in s['objects']}
 shown={o['id']:o for o in before['objects']};done=set()
 e={id:v for id,v in e.items() if id in by and not by[id].get('merged_into')}
 def visit(id):
  if id in done:return
  o=by[id];parent=o.get('parent')
  if parent:visit(parent)
  v=e.get(id,{})
  if 'curve' in v and id in shown:
   _,chains=c.motion_graph(s,{k:q for k,q in e.items() if k in done})
   ops=[[a.tolist(),b.tolist(),m] for a,b,m in chains.get(parent,[])]
   old_reference=np.asarray(shown[id]['registered_guide']);new_reference=c.guide(o)
   same_reference=old_reference.shape==new_reference.shape and np.array_equal(old_reference,new_reference)
   if not (same_reference and shown[id].get('parent')==parent and ops==shown[id]['parent_ops']):
    v['curve']=copy.deepcopy(shown[id]['curve']);v['curve_basis']='source-cubic-v1';v['parent_ops']=ops
    if shown[id].get('parent')!=parent:v.pop('mount_fraction',None)
  done.add(id)
 for id in by:visit(id)
 return e

def correct_objects(s,edits,data):
 before=copy.deepcopy(c.project(s,edits));action=data['action']
 history=s.get('correction_history',[])
 if action=='undo_region':
  if not history:raise ValueError('没有可撤销的归属修改')
  s=load_version(history[-1])['scene']
 else:
  version=save_version(s,edits,data.get('settings'),'归属校正前')
  s=change_objects(s,data);s['correction_history']=history+[version]
 c.recover(s);e=retain_design(before,s);set_current(e,data.get('settings'));return s,e

def freeze_structure(s,edits):
 """Capture the actual displayed geometry, independent of subsequent editing."""
 shapes=c.structural_records(s,edits);frozen=copy.deepcopy(s);active=[]
 for original in s['objects']:
  if c.hidden(original['id'],s,edits) or original['role']=='unassigned':continue
  o=copy.deepcopy(original);reference=shapes[o['id']];q=np.asarray(reference['points'])
  o['structural_reference']=copy.deepcopy(reference)
  o['registration_offsets']=(q-c.resample(o['source_points'],len(q))*c.W).tolist()
  for key in ['recovered_guide','appearance_mode','merged_into']:o.pop(key,None)
  if o['role']=='flower':o['radii']=copy.deepcopy(reference['radii'])
  active.append(o)
 for key in ['render_inputs','pending_render_input','render_records','correction_history']:frozen.pop(key,None)
 frozen.update(objects=active,corrections=[],region_edits=[],image='render.png')
 return frozen

def capture_render_input(s,edits,style):
 item={'id':str(time.time_ns()),'created':time.strftime('%Y-%m-%d %H:%M:%S'),'structure_svg':c.conditioning(s,edits),'prompt':c.prompt(s,edits,style),'case':s['case_id'],'structure_scene':freeze_structure(s,edits),'status':'exported; generation not yet confirmed'}
 s.setdefault('render_inputs',[]).append(item);s.pop('pending_render_input',None);c.save_scene(s);return item

def select_render_structure(s,edits,input_id):
 if input_id=='current':
  result=freeze_structure(s,edits);record=None
 else:
  record=next((r for r in s.get('render_inputs',[]) if r['id']==input_id),None)
  if record is None:raise ValueError('请选择这张图实际使用的结构版本；旧导出条件缺少结构快照时，请明确选择当前结构')
  result=copy.deepcopy(record['structure_scene'])
 result['render_inputs']=copy.deepcopy(s.get('render_inputs',[]))
 result['render_records']=copy.deepcopy(s.get('render_records',[]))
 result['appearance_ready']=True
 # Records refer to their exact condition; no duplicate nested scene histories.
 linked={k:copy.deepcopy(v) for k,v in record.items() if k!='structure_scene'} if record else None
 return result,linked

def import_structure(raw):
 if raw.get('schema')=='structvine-design-v2':
  s=copy.deepcopy(raw['scene']);active=[]
  shapes=raw.get('structural_objects') or c.structural_records(s,raw.get('edits',{}))
  # A condition package contains the CURRENT displayed geometry as well as the
  # archived generator output. Import its current geometry, not the old source.
  for obj in raw['objects']:
   if obj.get('hidden') or obj.get('merged_into') or obj['role']=='unassigned':continue
   o=copy.deepcopy(obj);o.pop('guide',None);reference=shapes[o['id']];p=np.asarray(reference['points'],float)
   o['structural_reference']=copy.deepcopy(reference);o['registration_offsets']=(p-c.resample(o['source_points'],len(p))*c.W).tolist()
   if o['role']=='flower':o['radii']=copy.deepcopy(reference['radii'])
   for key in ['recovered_guide','parent_ops','joint_boundary','curve','registered_guide','alignment_guide']:o.pop(key,None)
   active.append(o)
  s.update(objects=active,appearance_ready=False,corrections=[],region_edits=[],render_records=[],render_origin='已导入当前结构；等待外观');s.pop('pending_render_input',None);return s
 if 'analysis' not in raw or 'selection' not in raw:raise ValueError('请选择原生成器导出的结构JSON，或包含它的结构包')
 objs=[]
 def add(id,name,role,points,parent=None,source=None,**kw):
  p=np.asarray(points,float);objs.append(dict(id=id,name=name,role=role,parent=parent,source_id=source or id,source_points=p.tolist(),registration_offsets=np.zeros_like(p).tolist(),**kw))
 add('vine','主藤','main',[p['point'] for p in raw['analysis']['backbone']['samples']])
 for k,m in enumerate(raw.get('flower_mount_plan',{}).get('mounts',[])):
  add(f'support{k+1}',f'承花路径{k+1}','support',m['centerline'],'vine',m['mount_id'],flower=f'flower{k+1}',source_cubic_segments=m.get('cubic_segments'))
 for k,f in enumerate(raw['analysis']['flowers']):
  x,y=f['center'];add(f'flower{k+1}',f'主花{k+1}','flower',[[x,y],[x+.01,y]],None,f['flower_id'],radii=[f['rx']*c.W,f['ry']*c.W])
 curves=[q for unit in raw['selection']['selected_candidates'] for q in unit['curves']]
 ids={q['curve_id']:q['curve_id'] for q in curves};counts={}
 for q in curves:
  level=int(str(q['level']).replace('L',''));counts[level]=counts.get(level,0)+1
  parent=q.get('parent_curve_id') if level>1 else 'vine'
  if level>1 and parent not in ids:raise ValueError('分枝缺少实际父级：'+q['curve_id'])
  add(q['curve_id'],('父枝' if level==1 else '子枝' if level==2 else str(level)+'级枝')+str(counts[level]),'parent' if level==1 else 'child',q['centerline'],parent,q['curve_id'],source_cubic_segments=q.get('cubic_segments'),source_level=level)
 # Retain the period scale and shift only Y; never stretch imported geometry.
 ys=[p[1] for o in objs for p in o['source_points']]
 ys += [f['center'][1]+sign*f['ry'] for f in raw['analysis']['flowers'] for sign in [-1,1]]
 ymin=min(0,min(ys))-.04;height=max(100,int(np.ceil((max(ys)-ymin+.04)*c.W)))
 for o in objs:
  o['registration_offsets']=[[0,-ymin*c.W] for _ in o['source_points']]
 return dict(schema='structvine-case-v2',case_id=raw.get('case_id','imported'),objects=objs,source_structure=raw,width=c.W,height=height,period=c.W,image='render.png',corrections=[],version=1,render_origin='尚未导入外观',appearance_ready=False,provenance={},source_coordinate_transform={'scale':c.W,'y_offset':ymin})

def structure_from_upload(data):
 if 'raw' in data:return import_structure(data['raw'])
 z=zipfile.ZipFile(io.BytesIO(base64.b64decode(data['zip'])))
 candidates=[n for n in z.namelist() if n.lower().endswith('.json')]
 for name in sorted(candidates,key=lambda n:('project' not in n,'structure' not in n,n)):
  try:return import_structure(json.loads(z.read(name)))
  except (ValueError,KeyError,TypeError):pass
 raise ValueError('结构包中没有可识别的生成器结构JSON')

def seed_structure_view(s):
 """A new structural input has no recovered appearance until an image is imported."""
 c.H=s['height'];vectors={}
 for o in s['objects']:
  p=c.guide(o)
  if o['role']=='flower':
   t=np.linspace(0,2*np.pi,96);unit=np.c_[np.cos(t),np.sin(t)];q=p[0]+unit*np.asarray(o['radii']);inner=p[0]+unit*np.maximum(np.asarray(o['radii'])-1.8,1);d='M'+'L'.join(f'{x},{y}' for x,y in q)+'Z'+'M'+'L'.join(f'{x},{y}' for x,y in inner)+'Z'
  else:
   p=c.resample(p,150);v=np.gradient(p,axis=0);v/=np.maximum(np.linalg.norm(v,axis=1)[:,None],1e-9);n=np.c_[-v[:,1],v[:,0]]*1.3;q=np.vstack([p+n,(p-n)[::-1]]);d='M'+'L'.join(f'{x},{y}' for x,y in q)+'Z'
  vectors[o['id']]=[{'fill':c.COLORS[o['role']],'d':d}]
 c.Image.new('RGB',(c.W,c.H),'white').save(c.DATA/'render.png');np.save(c.DATA/'ownership.npy',np.full((c.H,c.W),255,np.uint8));np.save(c.DATA/'protected.npy',np.zeros((c.H,c.W),np.uint8));(c.DATA/'vectors.json').write_text(json.dumps(vectors),'utf-8');c.CACHE.clear();c.save_scene(s)

def change_objects(s,data):
 action=data['action'];by={o['id']:o for o in s['objects']};id=data.get('object');strokes=data.get('strokes',[])
 if action=='assign':
  target=data['target']
 elif action in ['new','unassigned']:
  if not strokes:raise ValueError('请先涂选需要整理的外观片段')
  target='unassigned' if action=='unassigned' else 'detail_'+str(time.time_ns())
  if target not in by:
   pts=np.vstack([b['points'] for b in strokes]);center=pts.mean(axis=0);parent=data.get('parent') if action=='new' else None
   root=c.point_at(c.guide(by[parent]),c.nearest([center],c.guide(by[parent]))[0][0])[0] if parent else center-[1,0]
   p=np.array([root,(root+center)/2,center]);s['objects'].append(dict(id=target,name=data.get('name','').strip() or ('未确定归属' if action=='unassigned' else '新增叶饰'),role='unassigned' if action=='unassigned' else 'ornament',parent=parent,appearance_only=True,manual_object=True,source_id=target,source_points=(p/c.W).tolist(),registration_offsets=np.zeros_like(p).tolist()))
 elif action=='parent':
  parent=data.get('parent') or None
  if parent and by[parent]['role'] not in ['main','support','parent']:
   raise ValueError('请选择主藤、承花路径或普通父枝')
  if parent and by[parent]['role']=='parent' and any(o.get('parent')==id and o['role']=='child' for o in s['objects']):
   raise ValueError('这个父枝已有子枝；当前模型保留两级普通分枝，请选择主藤或承花路径')
  if parent:
   owner=np.load(c.DATA/'ownership.npy');rgb=np.asarray(c.Image.open(c.DATA/s['image']).convert('RGB'));ink=rgb@np.array([.2126,.7152,.0722])<235;ids=list(by)
   own=(owner==ids.index(id))&ink;par=(owner==ids.index(parent))&ink
   if not own.any() or not par.any() or c.cv2.distanceTransform((~par).astype('uint8'),c.cv2.DIST_L2,5)[own].min()>3:
    raise ValueError('这两个外观对象没有实际接触，请选择真正相接的父级')
  p=parent
  while p:
   if p==id:raise ValueError('不能将对象挂到自身或自己的子对象上')
   p=by[p].get('parent')
  by[id]['parent']=parent
  if by[id]['role'] in ['parent','child']:
   by[id]['role']='child' if parent and by[parent]['role']=='parent' else 'parent'
  return s
 elif action=='merge':
  target=data['target']
  if target==id:raise ValueError('请选择另一个对象')
  p=target
  while p:
   if p==id:raise ValueError('不能并入自己的子对象')
   p=by[p].get('parent')
  by[id]['merged_into']=target
  for o in s['objects']:
   if o.get('parent')==id:o['parent']=target
  return s
 elif action=='undo_region':
  if s.get('region_edits'):s['region_edits'].pop()
  return s
 else:raise ValueError('未知对象操作')
 if not strokes:raise ValueError('请先涂选需要整理的外观片段')
 s.setdefault('region_edits',[]).append({'target':target,'strokes':strokes});return s

def apply_regions(s,owner,ink):
 ids=[o['id'] for o in s['objects']]
 for edit in s.get('region_edits',[]):
  if edit['target'] not in ids:continue
  mask=np.zeros(owner.shape,np.uint8)
  for stroke in edit['strokes']:c.cv2.polylines(mask,[np.rint(stroke['points']).astype(np.int32)],False,1,int(stroke.get('size',16)))
  owner[(mask>0)&(ink>0)]=ids.index(edit['target'])
 for i,o in enumerate(s['objects']):
  if o.get('merged_into') in ids:owner[owner==i]=ids.index(o['merged_into'])
 return owner
