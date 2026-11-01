"""Continue Atlas structures in an owner-scoped appearance-editing session."""
from pathlib import Path
from collections import OrderedDict
import base64,copy,io,json,re,time,uuid,shutil
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse,Response,FileResponse
from pydantic import BaseModel,Field
from typing import Literal
from PIL import Image
from appearance_engine import core as c,workflow as w,server as engine
from appearance_engine.periodic import extract_periodic_tile,read_viewbox

class Source(BaseModel):
 kind:Literal['asset','job','edit']
 id:str=Field(pattern=r'^[A-Za-z0-9_-]+$',max_length=100)

class Dispatch:
 """Call the established editor handlers directly; no second HTTP service."""
 def __init__(self,action,payload):
  raw=json.dumps(payload).encode();self.path='/api/'+action;self.rfile=io.BytesIO(raw);self.headers={'Content-Length':str(len(raw))};self.wfile=io.BytesIO();self.status=200;self.response=None
 def send(self,data,type='application/json',filename=None):
  headers={'Cache-Control':'no-store'}
  if filename:headers['Content-Disposition']='attachment; filename="'+filename+'"'
  self.response=JSONResponse(data,headers=headers) if isinstance(data,(dict,list)) else Response(data,media_type=type,headers=headers)
 def send_response(self,status):self.status=status
 def send_header(self,*a):pass
 def end_headers(self):pass
 def send_error(self,status):self.status=status
 def result(self):
  if self.response is not None:return self.response
  return Response(self.wfile.getvalue(),status_code=self.status,media_type='application/json')

def build_router(root,reference_loader,pairs,data_root=None):
 data_root=data_root or root/'data'
 router=APIRouter(prefix='/api/v1/appearance');store=root/'web/.runtime/appearance';store.mkdir(parents=True,exist_ok=True);caches=OrderedDict()
 def who(request):return request.cookies.get('papera_editor_owner','')
 def project(id,request):
  if not re.fullmatch('[a-f0-9]{32}',id):raise HTTPException(404)
  folder=store/id
  if not (folder/'owner.json').exists():raise HTTPException(404)
  record=json.loads((folder/'owner.json').read_text('utf-8'))
  if not who(request) or record['owner']!=who(request):raise HTTPException(404)
  return folder
 def activate(folder):
  c.DATA=folder;c.OUT=folder/'output';c.OUT.mkdir(exist_ok=True)
  if str(folder) not in caches:caches[str(folder)]={}
  caches.move_to_end(str(folder))
  while len(caches)>4:caches.popitem(last=False)
  c.CACHE=caches[str(folder)];c.W=695;c.H=c.load_scene()['height'] if (folder/'scene.json').exists() else 724
 def load_geometry(ref,request):
  if ref.kind!='edit':return reference_loader(ref.kind,ref.id)
  if not re.fullmatch('[a-f0-9]{32}',ref.id):raise HTTPException(404)
  folder=root/'web/.runtime/editor/sessions'/ref.id
  if not (folder/'record.json').exists():raise HTTPException(404)
  record=json.loads((folder/'record.json').read_text('utf-8'))
  if not who(request) or record['owner']!=who(request):raise HTTPException(404)
  return json.loads((folder/'structure.json').read_text('utf-8')),record['parameters'],'已编辑结构'
 def prepare_pair(s,pair,folder):
  image_path=data_root/'paired_renderings'/pair['render_image']
  image=Image.open(image_path).convert('RGB')
  viewport=read_viewbox(data_root/'structural_assets/assets'/pair['asset_id']/'render_input.svg')
  tile,registration=extract_periodic_tile(image,viewport,output_width=c.W)
  image.save(folder/'source_render.png');tile.save(folder/'render.png')
  matrix=c.np.asarray(registration['source_to_tile'],float)
  for o in s['objects']:
   source=c.resample(o['source_points'],len(o['registration_offsets']))
   registered=source@matrix[:2,:2].T+matrix[:2,2]
   o['registration_offsets']=(registered-source*c.W).tolist()
   o.pop('recovered_guide',None)
   if o['role']=='flower':o['radii']=(c.np.asarray(o['radii'])*c.np.diag(matrix)[:2]/c.W).tolist()
  s['height']=tile.height;c.H=tile.height;s['periodic_registration']=registration
  s['source_coordinate_transform']={'affine':registration['source_to_tile']}
  record={'pair_record':pair,'generation_note':'依据结构周期与图像重复位置截取；保留完整原图','structure_image_base64':base64.b64encode((data_root/'paired_renderings'/pair['structure_image']).read_bytes()).decode()}
  prompt=data_root/'paired_renderings'/pair.get('prompt_file','')
  if prompt.is_file():record['prompt']=prompt.read_text('utf-8')
  s['appearance_ready']=True;s['render_records']=[record];c.recover(s)
  return s
 def upgrade_initial_pair(s,folder):
  # Run only when reopening a pristine gallery project. Action requests and
  # authored versions retain their original coordinates and material ownership.
  ref=s.get('atlas_reference',{});saved=w.current()
  if ref.get('kind')!='asset' or s.get('periodic_registration') or saved.get('edits') or s.get('version',1)!=1:return s
  if any(s.get(k) for k in ['corrections','region_edits','correction_history','render_inputs']):return s
  if any(o.get(k) for o in s['objects'] for k in ['manual_object','merged_into']):return s
  pair=next((p for p in pairs if p['asset_id']==ref.get('id')),None)
  records=s.get('render_records',[])
  if not pair or len(records)!=1 or records[0].get('pair_record')!=pair:return s
  backup=folder/'before_periodic_registration'
  if backup.exists():return s
  backup.mkdir()
  names=['scene.json','design_state.json','render.png','vectors.json','ownership.npy','protected.npy']
  for name in names:
   if (folder/name).exists():shutil.copy2(folder/name,backup/name)
  try:
   geometry,_,_=reference_loader('asset',ref['id']);new=w.import_structure(geometry)
   for k in ['case_id','atlas_reference','atlas_parameters','provenance']:new[k]=copy.deepcopy(s.get(k,new.get(k)))
   prepare_pair(new,pair,folder);c.save_scene(new);return new
  except Exception:
   for name in names:
    if (backup/name).exists():shutil.copy2(backup/name,folder/name)
   c.CACHE.clear();c.H=s['height'];raise
 @router.post('/projects')
 def create(ref:Source,request:Request):
  geometry,parameters,label=load_geometry(ref,request);owner=who(request) or uuid.uuid4().hex;id=uuid.uuid4().hex;folder=store/id;folder.mkdir()
  with c.LOCK:
   activate(folder)
   (folder/'owner.json').write_text(json.dumps({'owner':owner,'reference':ref.model_dump(),'created':time.time()}),'utf-8')
   if ref.kind=='asset' and ref.id=='A452':
    example=json.loads((root/'web/appearance_examples/ceramic_border.json').read_text('utf-8'));s=example['scene'];s['height']=724;c.H=724
    Image.open(io.BytesIO(base64.b64decode(example['appearance_base64']))).convert('RGB').save(folder/'render.png');c.recover(s);w.set_current(example.get('edits',{}),example.get('settings'))
   else:
    s=w.import_structure(geometry);s['case_id']=parameters.get('prototype','')+' / '+ref.id;s['atlas_reference']=ref.model_dump();w.seed_structure_view(s)
    pair=next((p for p in pairs if ref.kind=='asset' and p['asset_id']==ref.id),None)
    if pair:
     prepare_pair(s,pair,folder)
    w.set_current({}, {'height_mm':50,'repeats':3})
   s['atlas_reference']=ref.model_dump();s['atlas_parameters']=parameters;c.save_scene(s)
  label=parameters.get('prototype','')+' · '+{'asset':'配对外观','job':'生成结构','edit':'已编辑结构'}[ref.kind]
  response=JSONResponse({'project_id':id,'url':'/appearance/?project='+id,'label':label})
  if not who(request):response.set_cookie('papera_editor_owner',owner,httponly=True,secure=request.url.scheme=='https',samesite='strict',max_age=15552000,path='/')
  return response
 @router.post('/cup-example')
 def cup_example(request:Request):
  owner=who(request) or uuid.uuid4().hex;id=uuid.uuid4().hex;folder=store/id;folder.mkdir()
  with c.LOCK:
   activate(folder)
   (folder/'owner.json').write_text(json.dumps({'owner':owner,'reference':{'kind':'example','id':'ceramic-border-final'},'created':time.time()}),'utf-8')
   example=json.loads((root/'web/appearance_examples/ceramic_border_final.json').read_text('utf-8'));s=example['scene'];c.H=s['height']
   Image.open(io.BytesIO(base64.b64decode(example['appearance_base64']))).convert('RGB').save(folder/'render.png')
   c.recover(s);w.set_current(example.get('edits',{}),example.get('settings'));c.save_scene(s)
  response=JSONResponse({'project_id':id})
  if not who(request):response.set_cookie('papera_editor_owner',owner,httponly=True,secure=request.url.scheme=='https',samesite='strict',max_age=15552000,path='/')
  return response
 @router.get('/projects/{id}/state')
 def state(id:str,request:Request):
  folder=project(id,request)
  with c.LOCK:
   activate(folder);s=upgrade_initial_pair(c.load_scene(),folder);state=w.current();return engine.preview(s,state['edits'])|{'scene':s,**state}
 @router.get('/projects/{id}/data/{name:path}')
 def data(id:str,name:str,request:Request):
  folder=project(id,request)
  if name not in {'render.png','output/cup_preview.png','output/cup.glb','output/cup_texture.png'} and not re.fullmatch(r'named_versions/[0-9]+\.svg',name):raise HTTPException(404)
  path=folder/name
  if not path.is_file():raise HTTPException(404)
  return FileResponse(path,headers={'Cache-Control':'no-store'})
 @router.post('/projects/{id}/{action}')
 async def action(id:str,action:str,request:Request):
  folder=project(id,request)
  if action not in {'preview-3d','preview','svg','repeat','condition','render-inputs','export','save','version-save','version-open','structure','provenance','objects','recover','import','restore'}:raise HTTPException(404)
  if int(request.headers.get('content-length','0'))>25000000:raise HTTPException(413)
  payload=await request.json()
  if action=='preview-3d':
   try:
    model=base64.b64decode(payload['glb'],validate=True)
    if model[:4]!=b'glTF':raise ValueError('Expected GLB')
    output=folder/'output';output.mkdir(exist_ok=True)
    for key,name in [('png','cup_preview.png'),('texture','cup_texture.png')]:
     raw=base64.b64decode(payload[key].split(',',1)[1],validate=True)
     if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Expected PNG')
     (output/name).write_bytes(raw)
    (output/'cup.glb').write_bytes(model)
    (output/'cup_settings.json').write_text(json.dumps({k:payload.get(k) for k in ['settings','edits','design_settings']},ensure_ascii=False,indent=2),'utf-8')
   except (ValueError,KeyError,IndexError) as exc:raise HTTPException(400,str(exc))
   prefix=f'/api/v1/appearance/projects/{id}/data/output/'
   return {'png':prefix+'cup_preview.png','glb':prefix+'cup.glb','texture':prefix+'cup_texture.png'}
  with c.LOCK:
   activate(folder);handler=Dispatch(action,payload);engine.Handler.do_POST(handler);return handler.result()
 return router
