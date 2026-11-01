from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
import json,sys,time,base64,io,traceback,subprocess,gzip
from PIL import Image,ImageOps
from . import core
from . import workflow
ROOT=core.CASE
def preview(scene,edits,previous=None):
 result={'guide':core.conditioning(scene,edits),'project':core.project(scene,edits),'prompt':core.prompt(scene,edits),'warnings':core.geometry_warnings(scene,edits),'versions':workflow.versions()}
 if previous is None:result['art']=core.svg(scene,edits)
 else:
  before=core.svg(scene,previous,as_groups=True);after=core.svg(scene,edits,as_groups=True)
  result['patch']={id:g for id,g in after.items() if before.get(id)!=g};result['removed']=[id for id in before if id not in after]
 return result
def snapshot(scene):
 p=core.DATA/'versions';p.mkdir(exist_ok=True);(p/f'{time.time_ns()}.json').write_text(json.dumps(scene,ensure_ascii=False),'utf-8')
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT),**kw)
 def send(self,data,type='application/json',filename=None):
  if isinstance(data,(dict,list)):data=json.dumps(data,ensure_ascii=False).encode()
  elif isinstance(data,str):data=data.encode()
  compress='gzip' in self.headers.get('Accept-Encoding','') and len(data)>4096 and type=='application/json'
  if compress:data=gzip.compress(data,compresslevel=1)
  self.send_response(200);self.send_header('Content-Type',type);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
  if compress:self.send_header('Content-Encoding','gzip')
  if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
  self.end_headers();self.wfile.write(data)
 def do_GET(self):
  if self.path=='/api/health':return self.send({'service':'structvine-v2','port':8989})
  if self.path=='/api/state':
   with core.LOCK:
    s=core.load_scene();state=workflow.current();return self.send(preview(s,state['edits'])|{'scene':s,**state})
  if self.path=='/':self.path='/v2/index.html'
  super().do_GET()
 def do_POST(self):
  try:
   length=int(self.headers.get('Content-Length','0'))
   if length>25000000:raise ValueError('File too large')
   data=json.loads(self.rfile.read(length));edits=data.get('edits',{})
   with core.LOCK:
    s=core.load_scene()
    if self.path=='/api/preview':return self.send(preview(s,edits,data.get('previous')))
    if self.path=='/api/svg':return self.send(workflow.portable_svg(s,edits,data.get('settings')),'image/svg+xml','design.svg')
    if self.path=='/api/repeat':return self.send(workflow.portable_svg(s,edits,data.get('settings'),True),'image/svg+xml','repeat.svg')
    if self.path=='/api/condition':
     style=data.get('style','青花花叶，白底，保持连接与连续构图')
     workflow.capture_render_input(s,edits,style)
     return self.send(core.package(s,edits,style,'condition'),'application/zip','render-input.zip')
    if self.path=='/api/render-inputs':
     return self.send({'inputs':[{k:r[k] for k in ['id','created','case','structure_svg']} for r in s.get('render_inputs',[])]})
    if self.path=='/api/export':return self.send(core.package(s,edits,kind='design',settings=data.get('settings')),'application/zip','editable-design.zip')
    if self.path=='/api/save':
     workflow.set_current(edits,data.get('settings'));return self.send(workflow.document(s,edits,data.get('settings')),'application/json','design-project.json')
    if self.path=='/api/version-save':
     workflow.save_version(s,edits,data.get('settings'),data.get('name',''));workflow.set_current(edits,data.get('settings'));return self.send({'versions':workflow.versions()})
    if self.path=='/api/version-open':
     p=workflow.load_version(data['id']);snapshot(s);s=p['scene'];core.H=s['height'];core.Image.open(io.BytesIO(base64.b64decode(p['appearance_base64']))).convert('RGB').save(core.DATA/'render.png');core.CACHE.clear()
     if s.get('appearance_ready',True):core.recover(s)
     else:workflow.seed_structure_view(s)
     workflow.set_current(p['edits'],p.get('settings'));return self.send(preview(s,p['edits'])|{'scene':s,'edits':p['edits'],'settings':p.get('settings',{})})
    if self.path=='/api/structure':
     workflow.save_version(s,edits,data.get('settings'),'导入结构前');s=workflow.structure_from_upload(data);workflow.seed_structure_view(s);workflow.set_current({},data.get('settings'));return self.send(preview(s,{})|{'scene':s,'edits':{}})
    if self.path=='/api/provenance':
     s['provenance']={k:str(data.get(k,'')) for k in ['source','interpretation','task']};core.save_scene(s);return self.send({'provenance':s['provenance']})
    if self.path=='/api/objects':
     if not s.get('appearance_ready',True):raise ValueError('请先导入外观图')
     s,edits=workflow.correct_objects(s,edits,data);return self.send(preview(s,{} if data.get('view')=='recover' else edits)|{'scene':s,'edits':edits})
    if self.path=='/api/recover':
     before=core.copy.deepcopy(core.project(s,edits));version=workflow.save_version(s,edits,data.get('settings'),'重新分组前');s.setdefault('correction_history',[]).append(version)
     for id,points in data.get('guides',{}).items():
      o=next(o for o in s['objects'] if o['id']==id);p=core.np.asarray(points,float)
      if p.ndim!=2 or p.shape[1]!=2 or len(p)<2:raise ValueError('Invalid guide points')
      o['registration_offsets']=(p-core.resample(o['source_points'],len(p))*core.W).tolist()
      o.pop('recovered_guide',None)
     s['corrections']=data.get('corrections',s.get('corrections',[]));s['version']+=1;core.save_scene(s);stats=core.recover(s);edits=workflow.retain_design(before,s);workflow.set_current(edits,data.get('settings'));return self.send(preview(s,{})|{'scene':s,'edits':edits,'recovery':stats})
    if self.path=='/api/import':
     im=Image.open(io.BytesIO(base64.b64decode(data['image']))).convert('RGB')
     imported,linked=workflow.select_render_structure(s,edits,data.get('render_input_id'))
     workflow.save_version(s,edits,data.get('settings'),'导入外观前');s=imported;core.H=s['height']
     im=ImageOps.contain(im,(core.W,core.H));canvas=Image.new('RGB',(core.W,core.H),'white');canvas.paste(im,((core.W-im.width)//2,(core.H-im.height)//2));canvas.save(core.DATA/'render.png');s['version']+=1;s['render_origin']='designer-imported appearance; alignment must be checked';s.setdefault('render_records',[]).append({'imported':time.strftime('%Y-%m-%d %H:%M:%S'),'filename':data.get('filename',''),'generation_note':data.get('generation_note',''),'input':linked,'structure_basis':'exported snapshot' if linked else 'operator-selected current structure; original generation input unconfirmed','status':'imported; generation provenance supplied by operator'});core.save_scene(s);core.recover(s);workflow.set_current({},data.get('settings'));return self.send(preview(s,{})|{'scene':s,'edits':{}})
    if self.path=='/api/restore':
     p=data['project']
     if p.get('schema')!='structvine-design-v2':raise ValueError('Not a v2 design project')
     snapshot(s);s=p['scene'];s['image']='render.png';core.H=s['height']
     if 'appearance_base64' not in p:raise ValueError('The project does not include its appearance image')
     Image.open(io.BytesIO(base64.b64decode(p['appearance_base64']))).convert('RGB').resize((core.W,core.H)).save(core.DATA/'render.png')
     core.save_scene(s);core.CACHE.clear()
     if s.get('appearance_ready',True):core.recover(s)
     else:workflow.seed_structure_view(s)
     restored=workflow.normalize_legacy(s,p.get('edits',{}));workflow.set_current(restored,p.get('settings'));return self.send(preview(s,restored)|{'scene':s,'edits':restored,'settings':p.get('settings',{})})
    self.send_error(404)
  except Exception as e:
   traceback.print_exc();raw=json.dumps({'error':str(e)},ensure_ascii=False).encode();self.send_response(400);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
 def log_message(self,fmt,*args):print(fmt%args,flush=True)
