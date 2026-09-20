"""Local research website: read-only assets and a durable, single-worker queue."""
from pathlib import Path
import sys,os,json,sqlite3,time,uuid,threading,subprocess,shutil,traceback
from contextlib import asynccontextmanager
ROOT=Path(__file__).resolve().parents[2]
RUNTIME=ROOT/'web/.runtime';RUNTIME.mkdir(exist_ok=True)
sys.path.insert(0,str(RUNTIME/'packages'))
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal

DATA=ROOT/'data';JOBS=RUNTIME/'jobs';JOBS.mkdir(exist_ok=True)
DB=RUNTIME/'jobs.sqlite3';STOP=threading.Event()
read=lambda p:json.loads(p.read_text('utf-8'))
RECORDS={r['case_id']:r for r in read(DATA/'structural_assets/case_records.json')}
ASSETS={r['asset_id']:r for r in read(DATA/'structural_assets/asset_index.json')}
PAIRS=read(DATA/'paired_renderings/pairs.json');PAIR_MAP={r['pair_id']:r for r in PAIRS}
PROTOTYPES=['SW1-A','SW1-B','SW1-C','SW2-A','SW3-A','SW3-B']
sys.path.insert(0,str(ROOT/'code'))
from package_paths import DYNAMIC
from export_batch_svgs import render_case_svg
PROTOTYPE_IDS=dict(zip(PROTOTYPES,['proto_sw_1_1','proto_sw_1_3','proto_sw_1_c','proto_sw_2_3','proto_sw_3_1','proto_sw_3_2']))
PROTOTYPE_INPUTS=read(ROOT/'code/inputs/prototype_inputs.json')

def prototype_preview(p):
 return {'case_id':PROTOTYPE_IDS[p],'prototype':p,'is_prototype':True,'l1':0,'l2':0,'flowers':len(PROTOTYPE_INPUTS[PROTOTYPE_IDS[p]]['analysis']['flowers']),
  'structure_url':f'/api/v1/prototypes/{p}/geometry','view_svg_url':f'/api/v1/prototypes/{p}/svg','svg_url':f'/api/v1/prototypes/{p}/svg','png_url':f'/api/v1/prototypes/{p}/svg','json_url':f'/api/v1/prototypes/{p}/geometry','parameters_url':'','parameters':{'prototype':p,'variant':'expanded','density':'medium','control':'soft','seed':20260920}}

def connect():
 c=sqlite3.connect(DB,timeout=10);c.row_factory=sqlite3.Row;return c
def init_db():
 with connect() as c:
  c.execute('PRAGMA journal_mode=WAL')
  c.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, params TEXT NOT NULL, error TEXT)')
  c.execute('CREATE INDEX IF NOT EXISTS jobs_state_created ON jobs(state,created)')
  for r in c.execute("SELECT id FROM jobs WHERE state='running'").fetchall():
   complete=(JOBS/r['id']/'result.json').exists()
   c.execute('UPDATE jobs SET state=?,updated=?,error=? WHERE id=?',('succeeded' if complete else 'interrupted',time.time(),None if complete else 'The service restarted. Submit this request again.',r['id']))
def update(job,state,error=None):
 with connect() as c:c.execute('UPDATE jobs SET state=?,updated=?,error=? WHERE id=?',(state,time.time(),error,job))
def worker():
 while not STOP.is_set():
  with connect() as c:
   c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
   if r:c.execute("UPDATE jobs SET state='running',updated=? WHERE id=?",(time.time(),r['id']))
  if not r:STOP.wait(.5);continue
  folder=JOBS/r['id']
  try:
   with (folder/'worker.log').open('w',encoding='utf-8') as log:
    proc=subprocess.run([sys.executable,str(Path(__file__).with_name('generate_task.py')),str(folder)],stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
   if proc.returncode:raise RuntimeError('Generation could not complete with these settings. Try another seed.')
   if not (folder/'result.json').exists():raise RuntimeError('Generation returned no complete result.')
   update(r['id'],'succeeded')
  except subprocess.TimeoutExpired:update(r['id'],'failed','This request exceeded the time limit. Try another seed.')
  except Exception as e:update(r['id'],'failed',str(e))

@asynccontextmanager
async def lifespan(app):
 init_db();STOP.clear();thread=threading.Thread(target=worker,daemon=True);thread.start()
 yield
 STOP.set()

app=FastAPI(title='Floral Scroll Atlas',lifespan=lifespan)
from public_access import install_public_access
install_public_access(app,RUNTIME)
class JobRequest(BaseModel):
 model_config=ConfigDict(extra='forbid')
 prototype:Literal['SW1-A','SW1-B','SW1-C','SW2-A','SW3-A','SW3-B']='SW1-A'
 variant:Literal['expanded','compact','swept']='expanded'
 density:Literal['simple','medium','rich']='medium'
 control:Literal['soft','exact']='soft'
 seed:int=Field(default=20260920,ge=0,le=4294967295,strict=True)
 archive_case:str|None=None
 condition_id:str|None=Field(default=None,pattern=r'^[a-f0-9]{32}$')
class ConditionRequest(BaseModel):
 job_id:str=Field(pattern=r'^[a-f0-9]{32}$')

def job_row(job):
 with connect() as c:r=c.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
 if not r:raise HTTPException(404,'Task not found')
 return dict(r)
def asset_info(asset_id,pair=None):
 r=ASSETS[asset_id];params=r['generation_parameters']
 return {'asset_id':asset_id,'case_id':pair['case_id'] if pair else r['case_id'],'prototype':r['prototype'],
  'l1':r['ordinary_L1_count'],'l2':r['L2_count'],'flowers':r['flower_count'],
  'parameters':{'prototype':r['prototype'],'variant':r['backbone_variant'],'density':r['density_level'],'control':'soft' if r['group']=='density' else 'exact','seed':int(params['production_seed']),'archive_case':pair['case_id'] if pair else r['case_id']},
  'structure_url':f'/api/v1/structures/asset/{asset_id}',
  'png_url':f'/media/assets/{asset_id}/render_input.png',
  'svg_url':f'/api/v1/assets/{asset_id}/files/svg','view_svg_url':f'/media/assets/{asset_id}/render_input.svg','json_url':f'/api/v1/assets/{asset_id}/files/geometry','parameters_url':f'/api/v1/assets/{asset_id}/files/parameters',
  **({'pair_id':pair['pair_id'],'render_url':'/media/pairs/'+pair['render_image']} if pair else {})}

@app.get('/api/v1/catalog')
def catalog():
 return {'prototypes':[{'id':p,'family':p[2],'preview':prototype_preview(p),'example':asset_info(next(x for x in PAIRS if x['prototype']==p)['asset_id'],next(x for x in PAIRS if x['prototype']==p))} for p in PROTOTYPES],'asset_count':1128,'pair_count':500,'version':'2026-09-20'}
@app.get('/api/v1/prototypes/{prototype}/{kind}')
def prototype_file(prototype:str,kind:str):
 if prototype not in PROTOTYPE_IDS:raise HTTPException(404)
 pid=PROTOTYPE_IDS[prototype];analysis=PROTOTYPE_INPUTS[pid]['analysis'];selection={'feasible':True,'selected_candidates':[]};mounts={'mounts':[]}
 if kind=='geometry':return {'analysis':{k:analysis[k] for k in ['coordinate_system','backbone','flowers']},'flower_mount_plan':mounts,'selection':selection,'is_prototype':True}
 if kind=='svg':
  from fastapi.responses import Response
  return Response(render_case_svg(analysis,mounts,selection,{'prototype_id':pid,'production_seed':0,'source_case':'prototype'},repeat='triple',palette='role'),media_type='image/svg+xml')
 raise HTTPException(404)
@app.get('/api/v1/assets')
def assets(prototype:str='',q:str='',page:int=1,page_size:int=12,min_children:int=0):
 page=max(1,page);page_size=min(24,max(1,page_size))
 selected=[r for r in PAIRS if (not prototype or r['prototype']==prototype) and (not q or q.lower() in (r['pair_id']+' '+r['case_id']).lower()) and ASSETS[r['asset_id']]['L2_count']>=min_children]
 return {'total':len(selected),'page':page,'items':[asset_info(r['asset_id'],r) for r in selected[(page-1)*page_size:page*page_size]]}
@app.get('/api/v1/structures/asset/{asset_id}')
def structure_asset(asset_id:str):
 if asset_id not in ASSETS:raise HTTPException(404)
 return read(DATA/'structural_assets/assets'/asset_id/'structure.json')
@app.get('/api/v1/assets/{asset_id}/files/{kind}')
def asset_file(asset_id:str,kind:str):
 if asset_id not in ASSETS:raise HTTPException(404)
 if kind=='parameters':return JSONResponse(ASSETS[asset_id]['generation_parameters'],headers={'Content-Disposition':f'attachment; filename="{asset_id}_parameters.json"'})
 names={'svg':'structure.svg','geometry':'structure.json','png':'render_input.png'}
 if kind not in names:raise HTTPException(404)
 return FileResponse(DATA/'structural_assets/assets'/asset_id/names[kind],filename=f'{asset_id}_{names[kind]}')

@app.post('/api/v1/jobs',status_code=202)
def submit(params:JobRequest):
 values=params.model_dump()
 if params.archive_case and params.archive_case not in RECORDS:raise HTTPException(422,'Unknown archived case')
 if params.condition_id:
  base=job_row(params.condition_id)
  if base['state']!='succeeded' or not (JOBS/params.condition_id/'condition.json').exists():raise HTTPException(409,'The fixed floral configuration is not available')
  snapshot=read(JOBS/params.condition_id/'condition.json')
  if snapshot['parameters']['prototype']!=params.prototype or snapshot['parameters']['variant']!=params.variant:raise HTTPException(422,'Prototype and variant must match the fixed floral configuration')
  if params.archive_case:raise HTTPException(422,'Use either an archived case or a fixed condition')
 with connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if c.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]>=20:raise HTTPException(429,'The queue is full. Please try again shortly.')
  job=uuid.uuid4().hex;folder=JOBS/job;folder.mkdir();(folder/'request.json').write_text(json.dumps(values),'utf-8')
  c.execute('INSERT INTO jobs VALUES (?,?,?,?,?,NULL)',(job,'queued',time.time(),time.time(),json.dumps(values)))
 return {'job_id':job,'state':'queued'}
@app.get('/api/v1/jobs/{job}')
def status(job:str):
 r=job_row(job);result=None
 if r['state']=='succeeded':
  result=read(JOBS/job/'result.json');result.update({'structure_url':f'/api/v1/structures/job/{job}','svg_url':f'/api/v1/jobs/{job}/files/svg','view_svg_url':f'/api/v1/jobs/{job}/files/view','png_url':f'/api/v1/jobs/{job}/files/png','json_url':f'/api/v1/jobs/{job}/files/geometry','parameters_url':f'/api/v1/jobs/{job}/files/parameters','job_id':job})
 with connect() as c:position=c.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running') AND created<=?",(r['created'],)).fetchone()[0]
 return {'job_id':job,'state':r['state'],'queue_position':position,'error':r['error'],'parameters':json.loads(r['params']),'result':result}
@app.post('/api/v1/conditions')
def condition(req:ConditionRequest):
 r=job_row(req.job_id)
 if r['state']!='succeeded':raise HTTPException(409,'Generate a complete structure first')
 return {'condition_id':req.job_id,'parameters':read(JOBS/req.job_id/'condition.json')['parameters']}
@app.get('/api/v1/structures/job/{job}')
def structure_job(job:str):
 r=job_row(job)
 if r['state']!='succeeded':raise HTTPException(409)
 return read(JOBS/job/'output/structure.json')
@app.get('/api/v1/jobs/{job}/files/{kind}')
def job_file(job:str,kind:str):
 r=job_row(job)
 if r['state']!='succeeded':raise HTTPException(409)
 names={'svg':'structure.svg','view':'render_input.svg','png':'render_input.png','geometry':'structure.json','parameters':'parameters.json'}
 if kind not in names:raise HTTPException(404)
 path=JOBS/job/'output'/names[kind]
 if not path.exists():raise HTTPException(404,'This format is unavailable')
 return FileResponse(path,filename=f'{job[:8]}_{names[kind]}')
@app.get('/api/v1/healthz')
def health():return {'status':'ok','version':'2026-09-20','generation':'local_cpu','server_pid':os.getpid(),'public_mode':os.environ.get('PAPERA_PUBLIC_MODE')=='1'}

def editor_reference(kind,id):
 if kind=='asset':
  if id not in ASSETS:raise HTTPException(404)
  info=asset_info(id)
  return read(DATA/'structural_assets/assets'/id/'structure.json'),info['parameters'],info['prototype']+' / '+id
 if kind=='job':
  row=job_row(id)
  if row['state']!='succeeded':raise HTTPException(409,'结构还未生成完成')
  result=read(JOBS/id/'result.json')
  return read(JOBS/id/'output/structure.json'),result['parameters'],result['prototype']+' / '+id[:8]
 raise HTTPException(404)
from editor_api import build_router
app.include_router(build_router(ROOT,editor_reference))
app.mount('/editor',StaticFiles(directory=ROOT/'web/editor',html=True),name='direct-editor')

app.mount('/media/assets',StaticFiles(directory=DATA/'structural_assets/assets'),name='asset-files')
app.mount('/media/pairs',StaticFiles(directory=DATA/'paired_renderings'),name='pair-files')
THUMBS=RUNTIME/'thumbnails';THUMBS.mkdir(exist_ok=True)
app.mount('/media/thumbs',StaticFiles(directory=THUMBS),name='thumb-files')
DIST=ROOT/'web/frontend/dist'
if DIST.exists():app.mount('/',StaticFiles(directory=DIST,html=True),name='frontend')

if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('PAPERA_PORT','8976')),log_level='info')
