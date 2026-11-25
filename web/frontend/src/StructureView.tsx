import {useEffect,useRef,useState} from 'react';
import {ZoomIn,ZoomOut,RotateCcw} from 'lucide-react';
import type {Item} from './types';
import {ROLES} from './atlas';

type Selection={label:string;description:string};
type Mark={cid:string|null;parent?:string;role:string;flowerId:string|null};
type Camera={zoom:number;left:number};
type Props={
 item:Item|null;zh:boolean;role?:string;onSelect?:(selection:Selection|null)=>void;
 compact?:boolean;preview?:boolean;resetToken?:number;sharedViewBox?:string;camera?:Camera;onCamera?:(c:Camera)=>void;
};
const widths:Record<string,number>={backbone:2.4,flower_anchor:1.5,flower_support:1.8,L1:1.8,L2:1.3,L3:1.2};
const colors:Record<string,string>=Object.fromEntries(ROLES.map(([key,color])=>[key,color]));
colors.L3='#705c85';
const cachedSvg=new Map<string,string>();
async function svgFor(url:string,signal:AbortSignal){
 const cached=cachedSvg.get(url);if(cached)return cached;
 const r=await fetch(url,{signal});if(!r.ok)throw new Error('SVG '+r.status);
 const text=await r.text();
 if(cachedSvg.size>=64)cachedSvg.delete(cachedSvg.keys().next().value!);
 cachedSvg.set(url,text);
 return text;
}
function displaySvg(raw:string,viewBox:string){
 const root=new DOMParser().parseFromString(raw,'image/svg+xml').documentElement;
 if(root.localName!=='svg')throw new Error('SVG unavailable');
 root.querySelectorAll('metadata,script,foreignObject').forEach(n=>n.remove());
 [root,...root.querySelectorAll('*')].forEach(node=>{
  for(const attr of [...node.attributes]) if(/^on/i.test(attr.name))node.removeAttribute(attr.name);
 });
 root.removeAttribute('width');root.removeAttribute('height');
 root.setAttribute('preserveAspectRatio','xMidYMid meet');
 if(viewBox)root.setAttribute('viewBox',viewBox);
 const bg=root.querySelector('rect');if(bg)bg.setAttribute('fill','transparent');
 if(root.getAttribute('data-repeat-mode')==='triple'&&!root.querySelector('[data-role=unit_boundary]')){
  const group=document.createElementNS(root.namespaceURI,'g');
  group.setAttribute('data-role','unit_boundary');
  const shifts=[...new Set([...root.querySelectorAll('[data-repeat-shift]')].map(node=>Number(node.getAttribute('data-repeat-shift'))))].sort((a,b)=>a-b);
  const [,y,,height]=(root.getAttribute('viewBox')||'').split(/[\s,]+/).map(Number);
  if(shifts.length&&Number.isFinite(y)&&Number.isFinite(height)){
   for(const x of [...shifts,shifts[shifts.length-1]+1]){
    const line=document.createElementNS(root.namespaceURI,'line');
    for(const [attr,value] of Object.entries({x1:x,x2:x,y1:y,y2:y+height}))line.setAttribute(attr,String(value));
    group.append(line);
   }
   root.insertBefore(group,root.querySelector('g'));
  }
 }
 return new XMLSerializer().serializeToString(root);
}
export default function StructureView({item,zh,role='all',onSelect,compact=false,preview=false,sharedViewBox='',resetToken=0,camera,onCamera}:Props){
 const [loaded,setLoaded]=useState<{url:string;box:string;markup:string;failed?:boolean}|null>(null);
 const [data,setData]=useState<any>(null);
 const [localCamera,setLocalCamera]=useState<Camera>({zoom:1,left:0});
 const [pick,setPick]=useState<Mark|null>(null);
 const stage=useRef<HTMLDivElement>(null), scroll=useRef<HTMLDivElement>(null);
 const url=item?.view_svg_url||item?.svg_url||'';
 const t=(en:string,cn:string)=>zh?cn:en;
 const current=camera||localCamera, setCamera=onCamera||setLocalCamera;
 const shown=loaded?.url===url&&loaded.box===sharedViewBox?loaded:null;
 const interaction=!compact&&!preview;
 useEffect(()=>{setPick(null);},[resetToken,role]);
 useEffect(()=>{setLocalCamera({zoom:1,left:0});setPick(null);},[url]);
 useEffect(()=>{
  if(!url)return;
  const controller=new AbortController();
  svgFor(url,controller.signal).then(raw=>{
   if(!controller.signal.aborted)setLoaded({url,box:sharedViewBox,markup:displaySvg(raw,sharedViewBox)});
  }).catch(()=>{if(!controller.signal.aborted)setLoaded({url,box:sharedViewBox,markup:'',failed:true});});
  return()=>controller.abort();
 },[url,sharedViewBox]);
 useEffect(()=>{
  setData(null);
  if(!interaction||!item?.structure_url)return;
  const controller=new AbortController();
  fetch(item.structure_url,{signal:controller.signal}).then(r=>r.ok?r.json():null).then(d=>{if(!controller.signal.aborted)setData(d);}).catch(()=>{});
  return()=>controller.abort();
 },[item?.structure_url,interaction]);
 useEffect(()=>{
  if(scroll.current&&Math.abs(scroll.current.scrollLeft-current.left)>1)scroll.current.scrollLeft=current.left;
 },[current.left,current.zoom,shown?.markup]);
 const names:Record<string,string>=Object.fromEntries(ROLES.map(([key,_,en,cn])=>[key,t(en,cn)]));
 useEffect(()=>{
  for(const el of stage.current?.querySelectorAll<SVGElement>('path,polyline,ellipse')||[]){
   const group=el.closest('[data-role]')?.getAttribute('data-role')||'';
   const key=el.dataset.level||group;
   if(colors[key]){
    el.style.stroke=colors[key];el.style.strokeWidth=String(widths[key]*(preview ? 0.7 : 1));
    el.style.strokeLinecap='round';el.style.strokeLinejoin='round';el.style.vectorEffect='non-scaling-stroke';
    if(key==='flower_anchor')el.style.fill='var(--curve-flower-fill)';
   }
   if(interaction&&colors[key]){
    el.setAttribute('tabindex','0');el.setAttribute('role','button');
    el.setAttribute('aria-label',names[key]||key);el.style.cursor='pointer';
   }
   const id=el.dataset.curveId;
   const related=pick?.cid&&[id,el.dataset.parentCurveId].includes(pick.cid)||pick?.parent&&pick.parent===id;
   const flower=pick?.flowerId&&pick.flowerId===el.dataset.flowerId;
   el.style.opacity=pick?(related||flower||!pick.cid&&!pick.flowerId&&pick.role===key?'1':'.25'):(role==='all'||role===key?'1':'.16');
  }
 },[shown?.markup,pick,role,zh,interaction,preview]);
 function select(target:EventTarget){
  if(!interaction)return;
  const svg=(target as Element).closest('path,polyline,ellipse') as SVGElement|null;
  if(!svg)return;
  const cid=svg.getAttribute('data-curve-id'),flowerId=svg.getAttribute('data-flower-id');
  const curves=(data?.selection?.selected_candidates||[]).flatMap((u:any)=>u.curves||[]);
  const curve=curves.find((c:any)=>c.curve_id===cid);
  const key=curve?.level||svg.dataset.level||svg.closest('[data-role]')?.getAttribute('data-role')||'';
  if(!colors[key])return;
  setPick({cid,parent:curve?.parent_curve_id,role:key,flowerId});
  const childCount=curves.filter((v:any)=>v.parent_curve_id===cid).length;
  const description:Record<string,string>={
   backbone:t('The vine continues through adjacent repeats.','主藤贯穿相邻重复单元。'),
   flower_anchor:t('This marker records the position and extent of a flower site.','此标记记录花位的位置和范围。'),
   flower_support:t('The path links a flower site to the main vine.','承花路径连接花位和主藤。'),
   L1:t('Child branches on this parent: '+childCount,'此父枝带有 '+childCount+' 条子枝。'),
   L2:t('The highlighted parent carries this child branch.','高亮的父枝是这条子枝的挂接对象。'),
  };
  onSelect?.({label:names[key]||key,description:description[key]||t('Branch attachment','分枝挂接')});
 }
 const art=<div className="svg-stage" ref={stage} style={preview?undefined:{width:(current.zoom*100)+'%'}} onClick={e=>select(e.target)} onKeyDown={e=>{if(interaction&&(e.key==='Enter'||e.key===' ')){e.preventDefault();select(e.target);}}} dangerouslySetInnerHTML={{__html:shown?.markup||''}}/>;
 if(preview)return <div className="structure-preview">{shown?.failed&&item?.png_url?<img src={item.png_url} alt={t('Structural drawing','结构线稿')}/>:art}</div>;
 return <div className={'structure-canvas'+(compact?' compact':'')} aria-busy={!!url&&!shown}>
  <div className="canvas-kicker"><span>{t('Three-repeat view','三周期视图')}</span><div>
   <button aria-label={t('Zoom out','缩小')} disabled={!url||current.zoom<=1} onClick={()=>setCamera({...current,zoom:Math.max(1,current.zoom-.25)})}><ZoomOut size={16}/></button>
   <span>{Math.round(current.zoom*100)}%</span>
   <button aria-label={t('Zoom in','放大')} disabled={!url||current.zoom>=2.5} onClick={()=>setCamera({...current,zoom:Math.min(2.5,current.zoom+.25)})}><ZoomIn size={16}/></button>
   <button aria-label={t('Reset view','适应画布')} disabled={!url} onClick={()=>{setCamera({zoom:1,left:0});setPick(null);onSelect?.(null);}}><RotateCcw size={15}/></button>
  </div></div>
  {url&&(!shown||shown.failed)&&<p className="canvas-status" role="status">{shown?.failed?t('The structure could not load.','结构图读取失败。'):t('Loading structure…','正在读取结构…')}</p>}
  <div className="svg-scroll" ref={scroll} onScroll={e=>{if(e.currentTarget.clientWidth&&Math.abs(e.currentTarget.scrollLeft-current.left)>1)setCamera({...current,left:e.currentTarget.scrollLeft});}}>{art}</div>
  <div className="repeat-labels"><span>{t('Previous repeat','前一单元')}</span><span>{t('Central repeat','中央单元')}</span><span>{t('Next repeat','后一单元')}</span></div>
 </div>;
}
