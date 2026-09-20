"""Adapt the original direct editor to generated assets and opt-in research data."""
from pathlib import Path
import copy,json,uuid,time,math,html,os,subprocess,shutil
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import JSONResponse,FileResponse
from pydantic import BaseModel,Field,ConfigDict
from typing import Literal
import legacy_editor_core as core

def read(p):return json.loads(p.read_text('utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False),'utf-8')
def points(cubics):return core.sample_cubics(cubics,64)

def bootstrap(geometry,parameters,base_id,label):
    scale=1000.0
    cs=[c for u in geometry['selection']['selected_candidates'] for c in u['curves']]
    ys=[q[1] for c in cs for seg in c['cubic_segments'] for q in seg.values()]
    ys += [v['point'][1] for v in geometry['analysis']['backbone']['samples']]
    ys += [f['center'][1]+s*f['ry'] for f in geometry['analysis']['flowers'] for s in [-1,1]]
    offset=min(0,min(ys))-.04
    convert=lambda p:[p[0]*scale,(p[1]-offset)*scale]
    def cubics(v):return [{k:convert(q) for k,q in seg.items()} for seg in v]
    backbone=[convert(v['point']) for v in geometry['analysis']['backbone']['samples']]
    converted={c['curve_id']:cubics(c['cubic_segments']) for c in cs};branches=[];counts={}
    for c in cs:
        level=int(c['level'][1:]);parent=c.get('parent_curve_id') or 'backbone';curve=converted[c['curve_id']]
        parent_points=backbone if parent=='backbone' else points(converted[parent])
        mount=core.project_point_to_polyline(curve[0]['p0'],parent_points)['fraction'];counts[level]=counts.get(level,0)+1
        branches.append({'curve_id':c['curve_id'],'parent_id':parent,'level':level,'role':c.get('semantic_role','ordinary_branch'),'kind':'generated','source':'paper_a','target_flower_id':None,'label':f'{"父枝" if level==1 else "子枝" if level==2 else "三级枝"} {counts[level]}','mount_fraction':mount,'original_mount_fraction':mount,'width':5 if level==1 else 3,'status':c.get('status','required'),'original_cubics':copy.deepcopy(curve),'edited_cubics':copy.deepcopy(curve),'constraints':{'root_mount_range':None,'endpoint_region':None,'curve_envelope':None}})
    return {'schema':core.SCHEMA,'source':{'seed':int(parameters.get('seed',0)),'base_id':base_id,'prototype':parameters.get('prototype',''),'label':label},
        'canvas':{'width':1000,'height':math.ceil((max(ys)-offset+.04)*scale),'active_repeat_x':[0.,1000.],'strict_edges':['top','bottom']},
        'backbone':{'points':backbone,'locked':True},'flowers':[{'flower_id':f.get('flower_id',f'flower_{i+1}'),'center':convert(f['center']),'rx':f['rx']*scale,'ry':f['ry']*scale} for i,f in enumerate(geometry['analysis']['flowers'])],
        'supports':[{'flower_id':m.get('flower_id'),'points':[convert(p) for p in m['centerline']]} for m in geometry['flower_mount_plan']['mounts']],
        'branches':branches,'topology':{},'forbidden_regions':[],'warnings':[],'edit_summary':{},'coordinate_transform':{'scale':scale,'y_offset':offset}}

def normalized_structure(session,record):
    scale=record['bootstrap']['coordinate_transform']['scale'];offset=record['bootstrap']['coordinate_transform']['y_offset']
    base=copy.deepcopy(record['geometry']);curves=[]
    for b in session['branches']:
        if b['status']=='forbidden':continue
        segs=[{k:[p[0]/scale,p[1]/scale+offset] for k,p in seg.items()} for seg in b['edited_cubics']]
        curves.append({'curve_id':b['curve_id'],'parent_curve_id':None if b['parent_id']=='backbone' else b['parent_id'],'level':'L'+str(b['level']),'semantic_role':b['role'],'status':b['status'],'cubic_segments':segs,'centerline':points(segs)})
    # A forbidden parent removes its dependent subtree from the visible export.
    while True:
        ids={c['curve_id'] for c in curves};kept=[c for c in curves if c['parent_curve_id'] is None or c['parent_curve_id'] in ids]
        if len(kept)==len(curves):break
        curves=kept
    base['schema']='papera-edited-structural-asset-v1';base['selection']={'selected_candidates':[{'candidate_id':'edited_configuration','curves':curves}]}
    base['manual_edit']={'source_id':record['bootstrap']['source']['base_id'],'geometry_status':'user_edited','edit_summary':session['edit_summary']}
    return base

def render_structure(geometry):
    ns='http://www.w3.org/2000/svg';analysis=geometry['analysis'];curves=[c for u in geometry['selection']['selected_candidates'] for c in u['curves']]
    ys=[v['point'][1] for v in analysis['backbone']['samples']]+[f['center'][1]+s*f['ry'] for f in analysis['flowers'] for s in [-1,1]]
    ys += [q[1] for c in curves for seg in c['cubic_segments'] for q in seg.values()]
    ymin=min(0,min(ys))-.04;ymax=max(ys)+.04
    chunks=[f'<svg xmlns="{ns}" viewBox="-1.08 {ymin} 3.16 {ymax-ymin}" width="2048" height="{round(2048*(ymax-ymin)/3.16)}"><rect x="-1.08" y="{ymin}" width="3.16" height="{ymax-ymin}" fill="white"/>']
    colors={'L1':'#b2864c','L2':'#618f9c','L3':'#936c9b'}
    def line(ps):return ' '.join(f'{p[0]},{p[1]}' for p in ps)
    for shift in [-1,0,1]:
        chunks.append(f'<g transform="translate({shift} 0)" fill="none" stroke-linecap="round" stroke-linejoin="round">')
        chunks.append(f'<g data-role="backbone"><polyline data-repeat-shift="{shift}" points="{line([v["point"] for v in analysis["backbone"]["samples"]])}" stroke="#244880" stroke-width=".007"/></g>')
        chunks.append('<g data-role="flower_support">')
        for m in geometry['flower_mount_plan']['mounts']:chunks.append(f'<polyline data-flower-id="{html.escape(str(m.get("flower_id","")))}" points="{line(m["centerline"])}" stroke="#708166" stroke-width=".007"/>')
        chunks.append('</g><g data-role="flower_anchor">')
        for i,f in enumerate(analysis['flowers']):chunks.append(f'<ellipse data-flower-id="{html.escape(str(f.get("flower_id",f"flower_{i+1}")))}" cx="{f["center"][0]}" cy="{f["center"][1]}" rx="{f["rx"]}" ry="{f["ry"]}" stroke="#b36163" stroke-width=".004"/>')
        chunks.append('</g><g data-role="branches">')
        for c in curves:chunks.append(f'<path data-curve-id="{html.escape(c["curve_id"])}" data-parent-curve-id="{html.escape(c.get("parent_curve_id") or "")}" data-level="{c["level"]}" d="{core._svg_path(c["cubic_segments"])}" stroke="{colors.get(c["level"],"#333")}" stroke-width=".005"/>')
        chunks.append('</g></g>')
    chunks.append('</svg>');return ''.join(chunks)

class Reference(BaseModel):
    model_config=ConfigDict(extra='forbid')
    kind:Literal['asset','job','edit']
    id:str=Field(min_length=1,max_length=100,pattern=r'^[A-Za-z0-9_-]+$')
class FeedbackRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    session_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    consent:Literal[True]
    policy_version:Literal['2026-09-20']
    note:str=Field(default='',max_length=2000)

def build_router(root,reference_loader):
    router=APIRouter(prefix='/api/v1/editor');store=root/'web/.runtime/editor'
    for n in ['sources','sessions','feedback']:(store/n).mkdir(parents=True,exist_ok=True)
    def owner(request):return request.cookies.get('papera_editor_owner','')
    def owned(kind,id,request):
        if not core.re.fullmatch('[a-f0-9]{32}',id):raise HTTPException(404)
        path=store/kind/id
        file=path/'record.json' if kind=='sessions' else path.with_suffix('.json')
        if not file.exists():raise HTTPException(404)
        value=read(file)
        if not owner(request) or value.get('owner')!=owner(request):raise HTTPException(404)
        return value,path
    def item(id,record,geometry):
        curves=[c for u in geometry['selection']['selected_candidates'] for c in u['curves']]
        prefix=f'/api/v1/editor/sessions/{id}/files/'
        return {'edit_id':id,'case_id':f'edit-{id[:8]}','prototype':record['parameters'].get('prototype',''),'parameters':record['parameters'],'l1':sum(c['level']=='L1' for c in curves),'l2':sum(c['level']=='L2' for c in curves),'l3':sum(c['level']=='L3' for c in curves),'flowers':len(geometry['analysis']['flowers']),'structure_url':prefix+'structure','view_svg_url':prefix+'svg','svg_url':prefix+'svg','png_url':prefix+'png','json_url':prefix+'structure','parameters_url':prefix+'parameters','user_edited':True}
    @router.post('/sources')
    def source(ref:Reference,request:Request):
        who=owner(request) or uuid.uuid4().hex
        if ref.kind=='edit':
            saved,_=owned('sessions',ref.id,request)
            owned('sources',saved['source_id'],request)
            return {'source_id':saved['source_id'],'editor_url':f'/editor/?source={saved["source_id"]}&session={ref.id}'}
        else:geometry,parameters,label=reference_loader(ref.kind,ref.id)
        id=uuid.uuid4().hex;boot=bootstrap(geometry,parameters,id,label)
        write(store/'sources'/f'{id}.json',{'owner':who,'reference':ref.model_dump(),'parameters':parameters,'geometry':geometry,'bootstrap':boot,'created_at':time.time()})
        response=JSONResponse({'source_id':id,'editor_url':f'/editor/?source={id}'})
        if not owner(request):response.set_cookie('papera_editor_owner',who,httponly=True,secure=request.url.scheme=='https',samesite='strict',max_age=15552000,path='/')
        return response
    @router.get('/sources/{id}')
    def load_source(id:str,request:Request):return owned('sources',id,request)[0]['bootstrap']
    @router.post('/sessions',status_code=201)
    async def save(request:Request):
        if int(request.headers.get('content-length','0') or 0)>3000000:raise HTTPException(413,'结构文件过大')
        payload=await request.json();source_id=payload.get('source',{}).get('base_id','');record,_=owned('sources',source_id,request)
        try:session=core.validate_session(payload,record['bootstrap'])
        except (core.EditorError,ValueError,TypeError,KeyError) as e:raise HTTPException(422,str(e))
        id=uuid.uuid4().hex;path=store/'sessions'/id;path.mkdir()
        structure=normalized_structure(session,record);svg=render_structure(structure)
        write(path/'session.json',session);write(path/'structure.json',structure);(path/'edited.svg').write_text(svg,'utf-8')
        write(path/'parameters.json',record['parameters'])
        saved={'owner':owner(request),'source_id':source_id,'parameters':record['parameters'],'created_at':time.time(),'geometry_status':'user_edited','feedback_submitted':False}
        write(path/'record.json',saved)
        return {'session_id':id,'item':item(id,saved,structure),'warnings':session['warnings']}
    @router.get('/sessions')
    def sessions(request:Request,source:str):
        owned('sources',source,request);found=[]
        for p in (store/'sessions').glob('*/record.json'):
            v=read(p)
            if v['source_id']==source and v['owner']==owner(request):found.append({'session_id':p.parent.name,'created_at':v['created_at'],'label':time.strftime('%m-%d %H:%M:%S',time.localtime(v['created_at']))})
        found.sort(key=lambda row:row['created_at'],reverse=True)
        return {'targets':found,'aggregate':{'target_count':len(found)}}
    @router.get('/sessions/{id}')
    def load_session(id:str,request:Request):_,path=owned('sessions',id,request);return read(path/'session.json')
    @router.get('/sessions/{id}/files/{kind}')
    def file(id:str,kind:str,request:Request):
        _,path=owned('sessions',id,request);names={'svg':'edited.svg','png':'edited.png','geometry':'session.json','structure':'structure.json','parameters':'parameters.json'}
        if kind not in names:raise HTTPException(404)
        target=path/names[kind]
        if kind=='png' and not target.exists():
            executable=os.environ.get('PAPERA_INKSCAPE') or shutil.which('inkscape')
            if not executable:raise HTTPException(503,'PNG导出尚未配置')
            subprocess.run([executable,str(path/'edited.svg'),'--export-type=png','--export-width=2048',f'--export-filename={target}'],check=True,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        return FileResponse(target,filename=f'edited_{id[:8]}_{target.name}')
    @router.post('/feedback')
    def feedback(body:FeedbackRequest,request:Request):
        saved,path=owned('sessions',body.session_id,request)
        if saved.get('feedback_submitted'):return {'feedback_id':saved['feedback_id'],'already_submitted':True}
        source,_=owned('sources',saved['source_id'],request);after=read(path/'session.json');id=uuid.uuid4().hex;target=store/'feedback'/id;target.mkdir()
        write(target/'before.json',source['geometry']);write(target/'after.json',read(path/'structure.json'));write(target/'edit_session.json',after);write(target/'parameters.json',saved['parameters'])
        write(target/'submission.json',{'feedback_id':id,'consent':True,'policy_version':body.policy_version,'submitted_at':time.time(),'reference':source['reference'],'prototype':saved['parameters'].get('prototype'),'note':body.note,'review_status':'pending','applied_to_generator':False})
        saved.update(feedback_submitted=True,feedback_id=id);write(path/'record.json',saved)
        return {'feedback_id':id,'already_submitted':False}
    return router
