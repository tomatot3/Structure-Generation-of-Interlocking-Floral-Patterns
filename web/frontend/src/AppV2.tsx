import StructureView from './StructureView';
import {useEffect,useRef,useState,type ReactNode} from 'react';
import {createRoot} from 'react-dom/client';
import {ArrowRight,ArrowUpRight,BookOpen,ChevronLeft,ChevronRight,Flower2,GitCompareArrows,Grid2X2,ImagePlus,Layers,LoaderCircle,Menu,PenTool,X} from 'lucide-react';
import ResearchPage from './ResearchPage';
import {FeaturedView,Gallery,PairDetail,filterFrom,galleryRoute} from './Gallery';
import {Compare,Studio} from './Workspace';
import {api,assetRoute,DEFAULT,displayCatalogId,parseRoute,post,PROTOTYPES,referenceFor,stored,useGeneration,type Catalog,type Job,type Reference,type Side,type Translate,type View} from './atlas';
import type {Item,Params} from './types';
import './style.css';
import './v2.css';
import './atlas.css';

type Picker='editor'|'appearance'|Side;
type Editor={url:string;item:Item};
type Appearance={pairId?:string;url:string;label:string;project_id:string};
type Saved={params?:Params;current?:Item|null;history?:Item[];comparison?:[Item|null,Item|null];aConfig?:Params;bConfig?:Params;lock?:boolean};
const visibleViews: [View,string,string,typeof Layers][]=[
 ['studio','Studio','工作台',Layers],['compare','Compare','结构对照',GitCompareArrows],['collection','Collection','配对图集',Grid2X2],
 ['editor','Editor','结构编辑',PenTool],['appearance','Appearance','外观设计',ImagePlus],['research','Research','构成研究',BookOpen],
];
const saved=stored<Saved>('papera-studio-v2',{});
const clean=(item:Item|null)=>item?.is_local?null:item;
const frameSrc=(path:string)=>{const u=new URL(path,location.origin);u.searchParams.set('workspace','1');u.searchParams.set('v','atlas-copy-1');return u.pathname+u.search;};

function App(){
 const [zh,setZh]=useState(localStorage.getItem('papera-language')!=='en');
 const t:Translate=(en,cn)=>zh?cn:en;
 const [route,setRoute]=useState(()=>parseRoute(location.hash));
 const [menu,setMenu]=useState(false);
 const [error,setError]=useState('');
 const [catalog,setCatalog]=useState<Catalog|null>(null),[catalogError,setCatalogError]=useState(false),[retryCatalog,setRetryCatalog]=useState(0);
 const [params,setParams]=useState(saved.params||DEFAULT),[current,setCurrent]=useState<Item|null>(saved.current||null);
 const [recent,setRecent]=useState(saved.history||[]);
 const [comparison,setComparison]=useState<[Item|null,Item|null]>(saved.comparison||[null,null]);
 const [aConfig,setAConfig]=useState(saved.aConfig||DEFAULT),[bConfig,setBConfig]=useState(saved.bConfig||{...DEFAULT,seed:20260921,density:'rich'});
 const [lock,setLock]=useState(saved.lock??true),[box,setBox]=useState(''),[activeSide,setActiveSide]=useState<Side>('A');
 const [picker,setPicker]=useState<Picker|null>(null),[detailCache,setDetailCache]=useState<Item>();
 const [editor,setEditor]=useState<Editor|null>(()=>stored('papera-editor',null));
 const [appearance,setAppearance]=useState<Appearance|null>(()=>stored('papera-appearance',null));
 const [pending,setPending]=useState<'editor'|'appearance'|null>(null);
 const pendingRef=useRef(false);
 const editorFrame=useRef<HTMLIFrameElement>(null),appearanceFrame=useRef<HTMLIFrameElement>(null);
 const dirty=useRef({editor:false,appearance:false});
 const [vesselOpen,setVesselOpen]=useState(false);
 const [savedState,setSavedState]=useState({editor:false,appearance:false});
 const routeRef=useRef(route);routeRef.current=route;
 const galleryScroll=useRef<Record<string,number>>({});
 const requested=route.query.get('prototype');
 const workspace=route.view==='editor'||route.view==='appearance';
 const addHistory=(item:Item)=>setRecent(items=>[item,...items.filter(r=>r.case_id!==item.case_id)].slice(0,30));
 const generation=useGeneration((item,target)=>{
  addHistory(item);
  if(target==='main')setCurrent(item);
  else setComparison(old=>target==='A'?[item,old[1]]:[old[0],item]);
 },t);
 const busy=generation.busy||!!pending;

 useEffect(()=>{
  const abort=new AbortController();
  setCatalogError(false);
  api<Catalog>('/catalog',{signal:abort.signal}).then(setCatalog).catch(()=>{if(!abort.signal.aborted)setCatalogError(true);});
  return()=>abort.abort();
 },[retryCatalog]);
 useEffect(()=>{
  document.documentElement.lang=zh?'zh-CN':'en';
  localStorage.setItem('papera-language',zh?'zh':'en');
  sendLanguage(editorFrame.current);sendLanguage(appearanceFrame.current);
 },[zh]);
 useEffect(()=>{
  localStorage.setItem('papera-studio-v2',JSON.stringify({params,current:clean(current),history:recent.filter(r=>!r.is_local),comparison:comparison.map(clean),aConfig,bConfig,lock}));
 },[params,current,recent,comparison,aConfig,bConfig,lock]);
 useEffect(()=>{
  if(route.view==='studio' && requested && PROTOTYPES.includes(requested) && requested!==params.prototype){
   setParams(p=>({...p,prototype:requested}));setCurrent(null);
  }
 },[route.view,requested]);
 useEffect(()=>{
  setBox('');
  if(comparison.some(item=>!item||item.is_local))return;
  const controller=new AbortController();
  Promise.all(comparison.map(async item=>{
   const res=await fetch(item!.view_svg_url||item!.svg_url,{signal:controller.signal});
   const svg=new DOMParser().parseFromString(await res.text(),'image/svg+xml').documentElement;
   return (svg.getAttribute('viewBox')||'').trim().split(/[\s,]+/).map(Number);
  })).then(rects=>{
   if(controller.signal.aborted||rects.some(b=>b.length!==4||b.some(n=>!Number.isFinite(n))))return;
   const x=Math.min(...rects.map(b=>b[0])),y=Math.min(...rects.map(b=>b[1]));
   const end=Math.max(...rects.map(b=>b[0]+b[2])),bottom=Math.max(...rects.map(b=>b[1]+b[3]));
   setBox([x,y,end-x,bottom-y].join(' '));
  }).catch(()=>{});
  return()=>controller.abort();
 },[comparison]);
 useEffect(()=>{
  document.body.classList.toggle('workspace-active',workspace);
  return()=>document.body.classList.remove('workspace-active');
 },[workspace]);
 useEffect(()=>{
  const label=visibleViews.find(([key])=>key===route.view);
  document.title=label?(zh?label[2]:label[1])+' · Floral Scroll Atlas':'Floral Scroll Atlas · 缠枝纹数字图集';
 },[route.view,zh]);
 useEffect(()=>{
  function capture(e:BeforeUnloadEvent){
   if(dirty.current.editor||dirty.current.appearance){e.preventDefault();e.returnValue='';}
  }
  window.addEventListener('beforeunload',capture);
  return()=>window.removeEventListener('beforeunload',capture);
 },[]);
 useEffect(()=>{
  const handle=()=>{
   const next=parseRoute(location.hash), old=routeRef.current;
   if(next.hash===old.hash)return;
   if(!leaveEditor(old.view,next.view)){
    history.pushState(null,'',old.hash||location.pathname+location.search);return;
   }
   updateRoute(next);
  };
  window.addEventListener('hashchange',handle);
  window.addEventListener('popstate',handle);
  return()=>{window.removeEventListener('hashchange',handle);window.removeEventListener('popstate',handle);};
 },[zh]);
 useEffect(()=>{
  const receive=(e:MessageEvent)=>{
   if(e.origin!==location.origin)return;
   const kind=e.source===editorFrame.current?.contentWindow?'editor':e.source===appearanceFrame.current?.contentWindow?'appearance':null;
   if(!kind||!e.data)return;
   if(kind==='appearance'&&e.data.type==='papera-vessel-modal'){setVesselOpen(e.data.open===true);return;}
   if(e.data.type==='papera-ui-ready'){sendLanguage(kind==='editor'?editorFrame.current:appearanceFrame.current);return;}
   if(e.data.type==='papera-'+kind+'-dirty')recordDirty(kind,!!e.data.dirty);
   if(kind==='editor'&&e.data.type==='papera-editor-location'&&typeof e.data.url==='string'){
    const next=stored<Editor|null>('papera-editor',null);
    if(next)localStorage.setItem('papera-editor',JSON.stringify({...next,url:e.data.url}));
   }
   if(kind==='editor'&&e.data.type==='papera-editor-saved'){
    addHistory(e.data.item);
    setEditor(old=>old?{...old,item:e.data.item}:old);
    localStorage.setItem('papera-editor',JSON.stringify({url:e.data.editor_url,item:e.data.item}));
    recordDirty('editor',false);
   }
   if(kind==='editor'&&e.data.type==='papera-open-appearance')void openProject('appearance',e.data.reference);
  };
  window.addEventListener('message',receive);
  return()=>window.removeEventListener('message',receive);
 });
 function sendLanguage(frame:HTMLIFrameElement|null){frame?.contentWindow?.postMessage({type:'papera-ui-language',lang:zh?'zh':'en'},location.origin);}
 function recordDirty(kind:'editor'|'appearance',value:boolean){
  dirty.current[kind]=value;setSavedState(old=>old[kind]===value?old:{...old,[kind]:value});
 }
 function leaveEditor(old:View,next:View){
  return old===next||!(old==='editor'||old==='appearance')||!dirty.current[old]||
   window.confirm(t('There are unsaved edits. Leave this workspace?','当前有未保存的修改。离开工作区？'));
 }
 function updateRoute(next:ReturnType<typeof parseRoute>){
  if(next.view!=='appearance')setVesselOpen(false);
  const from=routeRef.current.view;
  routeRef.current=next;setRoute(next);setPicker(null);setMenu(false);setError('');
  if(next.view!=='collection'||next.pairId||(from!=='collection'&&!galleryScroll.current[galleryRoute(filterFrom(next.query))]))window.scrollTo(0,0);
 }
 function go(hash:string,replace=false,alreadyConfirmed=false){
  const next=parseRoute(hash);
  if(next.hash===routeRef.current.hash)return true;
  if(!alreadyConfirmed&&!leaveEditor(routeRef.current.view,next.view))return false;
  const url=hash||location.pathname+location.search;
  if(replace)history.replaceState(null,'',url);else history.pushState(null,'',url);
  updateRoute(next);return true;
 }
 function openDetail(item:Item){
  if(!item.pair_id)return;
  galleryScroll.current[galleryRoute(filterFrom(route.query))]=window.scrollY;
  setDetailCache(item);
  const previous=galleryRoute(filterFrom(route.query));
  go(assetRoute(item.pair_id)+(previous.includes('?')?previous.slice(previous.indexOf('?')):''));
 }
 function choosePrototype(prototype:string){
  const target='#/studio?prototype='+encodeURIComponent(prototype);
  setParams(p=>({...p,prototype}));setCurrent(null);
  if(route.view==='studio')go(target,true);
 }
 function chooseCompare(side:Side,item:Item){
  if(!go('#/compare'))return;
  setComparison(old=>side==='A'?[item,old[1]]:[old[0],item]);
  if(item.is_local||item.user_edited||side==='B')setLock(false);
  setActiveSide(side);setPicker(null);
 }
 async function generateCompare(side:Side){
  if(side==='A'){await generation.start(aConfig,'A');return;}
  if(!lock){await generation.start(bConfig,'B');return;}
  const source=comparison[0];
  if(!source||source.is_local||source.user_edited)return;
  try{
   if(source.job_id){
    const c=await post<{condition_id:string}>('/conditions',{job_id:source.job_id});
    await generation.start({...bConfig,prototype:source.prototype,variant:source.parameters.variant,condition_id:c.condition_id},'B');
   }else await generation.start({...source.parameters,archive_case:source.case_id},'A',bConfig);
  }catch(e){setError((e as Error).message);}
 }
 async function openProject(kind:'editor'|'appearance',source:Reference|null,item?:Item){
  if(!source||pendingRef.current)return;
  const currentView=routeRef.current.view;
  if(!leaveEditor(currentView,kind))return;
  if((currentView!==kind)&&dirty.current[kind]&&!window.confirm(t('Replace the unsaved work in this workspace?','替换此工作区中未保存的修改？')))return;
  if(currentView===kind&&dirty.current[kind]&&!window.confirm(t('Switch structures and discard unsaved edits?','切换结构并放弃当前未保存的修改？')))return;
  pendingRef.current=true;setPending(kind);setError('');
  try{
   if(kind==='editor'&&item){
    const response=await post<{editor_url:string}>('/editor/sources',source);
    const state={url:response.editor_url,item};
    setEditor(state);localStorage.setItem('papera-editor',JSON.stringify(state));
   }else if(kind==='appearance'){
    const state={...await post<Appearance>('/appearance/projects',source),pairId:item?.pair_id};
    setAppearance(state);localStorage.setItem('papera-appearance',JSON.stringify(state));
   }
   recordDirty(kind,false);setPicker(null);go('#/'+kind,false,true);
  }catch(e){setError((e as Error).message);}
  finally{pendingRef.current=false;setPending(null);}
 }
 function openEditor(item:Item){void openProject('editor',referenceFor(item),item);}
 function openAppearance(item:Item){void openProject('appearance',referenceFor(item),item);}
 function localImage(side:Side,file?:File){
  if(!file)return;
  if(file.size>10*1024*1024||!/\.(png|jpe?g|svg)$/i.test(file.name)){setError(t('Choose a PNG, JPEG or SVG smaller than 10 MB.','请选择小于 10 MB 的 PNG、JPEG 或 SVG。'));return;}
  const reader=new FileReader();
  reader.onload=()=>chooseCompare(side,{case_id:'local-'+Date.now(),prototype:'',parameters:DEFAULT,l1:0,l2:0,flowers:0,structure_url:'',svg_url:'',png_url:'',json_url:'',parameters_url:'',is_local:true,local_url:String(reader.result),local_name:file.name});
  reader.readAsDataURL(file);
 }
 const view=route.view;
 const section=visibleViews.find(([key])=>key===view);
 const title=section?t(section[1],section[2]):'';
 const alert=error||generation.error;
 const pickerChoose=(item:Item)=>picker==='editor'?openEditor(item):picker==='appearance'?openAppearance(item):picker&&chooseCompare(picker,item);
 const selectedFilter=filterFrom(route.query);
 return <div className={'atlas-shell'+(workspace?' atlas-workspace':'')+(view==='appearance'&&vesselOpen?' vessel-modal-open':'')} onClick={e=>{
  const link=(e.target as HTMLElement).closest('a[href^="#/"]') as HTMLAnchorElement|null;
  if(!link||e.defaultPrevented||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
  e.preventDefault();go(link.hash);
 }}>
  <header className="site-header" inert={view==='appearance'&&vesselOpen}><a className="brand" href="/" onClick={e=>{if(!e.metaKey&&!e.ctrlKey){e.preventDefault();go('');}}}><span className="brand-mark"><Flower2 size={23}/></span><span>Floral Scroll Atlas</span></a>
   <nav className={menu?'nav-open':''} aria-label={t('Main navigation','主导航')}>{visibleViews.map(([key,en,cn,Icon])=><a href={'#/'+key} key={key} aria-current={key===view?'page':undefined}><Icon size={15}/>{t(en,cn)}</a>)}</nav>
   <div className="site-tools"><button className="language" onClick={()=>setZh(!zh)}>{zh?'English':'中文'}<ArrowUpRight size={14}/></button><button className="nav-toggle" aria-label={t('Show navigation','打开导航')} aria-expanded={menu} onClick={()=>setMenu(!menu)}>{menu?<X size={22}/>:<Menu size={22}/>}</button></div>
  </header>
  {view==='appearance'&&vesselOpen&&<div className="vessel-host-scrim" aria-hidden="true"/>}
  <main className={workspace?'immersive-main':undefined}>
   {view!=='home'&&!workspace&&!route.pairId&&<div className="page-intro"><h1>{view==='research'?t('The composition of floral scrolls','缠枝纹的构成与变化'):title}</h1></div>}
   {alert&&!picker&&<div className="error" role="alert">{alert}{!error&&generation.canRetry&&<button className="secondary" onClick={generation.retry}>{t('Retry generation','重试生成')}</button>}<button onClick={()=>{setError('');generation.clear();}} aria-label={t('Dismiss','关闭提示')}><X size={17}/></button></div>}
   {(pending||generation.job||generation.submitting)&&<div className="job-status" role="status"><LoaderCircle className="spin" size={17}/>{pending?t('Opening the workspace…','正在打开工作区…'):generation.recovering?t('Connection interrupted. Reconnecting…','连接短暂中断，正在重连…'):generation.job?.state==='queued'?t('Queued · position '+(generation.job.queue_position||1),'排队中 · 第 '+(generation.job.queue_position||1)+' 项'):generation.submitting?t('Submitting…','正在提交…'):t('Generating a composition…','正在生成构图…')}</div>}
   {view==='home'&&<FeaturedView t={t} zh={zh}/>}
   {view==='studio'&&<Studio t={t} zh={zh} catalog={catalog} catalogError={catalogError} retryCatalog={()=>setRetryCatalog(n=>n+1)} params={params} current={current} onPrototype={choosePrototype} onParams={setParams} generate={()=>void generation.start(params,'main')} onCompare={i=>chooseCompare('A',i)} onEditor={openEditor} onAppearance={openAppearance} busy={busy}/>}
   {view==='compare'&&<Compare t={t} zh={zh} items={comparison} a={aConfig} b={bConfig} setA={setAConfig} setB={setBConfig} lock={lock} setLock={setLock} commonBox={box} active={activeSide} setActive={setActiveSide} generate={side=>void generateCompare(side)} choose={setPicker} onLocal={localImage} onEditor={openEditor} onAppearance={openAppearance} busy={busy}/>}
   {view==='collection'&&(route.pairId?<PairDetail id={route.pairId} cached={detailCache} zh={zh} t={t} back={galleryRoute(selectedFilter)} onCompare={chooseCompare} onEditor={openEditor} onAppearance={openAppearance} busy={busy}/>:<Gallery t={t} zh={zh} onSelect={openDetail} filter={selectedFilter} onFilter={(f,replace)=>go(galleryRoute(f),replace)} restoreScroll={galleryScroll.current[galleryRoute(selectedFilter)]}/>)}
   {view==='research'&&<ResearchPage zh={zh} busy={busy} onPrototype={id=>{setParams(p=>({...p,prototype:id}));setCurrent(null);go('#/studio?prototype='+id);}} onGallery={()=>go('#/collection')}/>}
   <section className="editor-workspace" hidden={view!=='editor'}>
    <div className="editor-heading"><div><h1>{t('Structure editor','结构编辑')}</h1>{editor&&<span>{displayCatalogId(editor.item.pair_id||editor.item.prototype)} {savedState.editor?'· '+t('Unsaved edits','未保存'):''}</span>}</div>
     <button className="secondary" disabled={busy} onClick={()=>setPicker('editor')}>{t('Choose structure','选择结构')}</button>
    </div>
    {editor?<iframe className="immersive-frame" ref={editorFrame} title={t('Structure editor','结构编辑器')} src={frameSrc(editor.url)} onLoad={()=>sendLanguage(editorFrame.current)} />:view==='editor'&&<div className="editor-empty"><PenTool size={35}/><h2>{t('Open a floral scroll to refine its branches','载入花藤结构，微调枝蔓走势')}</h2><button className="primary" onClick={()=>current?openEditor(current):setPicker('editor')}>{current?t('Open the studio composition','载入工作台构图'):t('Choose from collection','从图集中选择')}</button></div>}
   </section>
   <section className="editor-workspace appearance-host" hidden={view!=='appearance'}>
    <div className="editor-heading" inert={vesselOpen}><div><h1>{t('Appearance editor','外观设计')}</h1>{appearance&&<span>{appearance.pairId?displayCatalogId(appearance.pairId):displayCatalogId(appearance.label.match(/^SW\d-[A-Z]/i)?.[0]||'')} <small className="case-chip">{appearance.pairId?t('Collection example','图集样例'):t('Current composition','当前构图')}</small> {savedState.appearance?'· '+t('Unsaved edits','未保存'):''}</span>}</div>
     <button className="secondary" disabled={busy} onClick={()=>setPicker('appearance')}>{t('Choose structure','选择结构')}</button>
    </div>
    {appearance?<iframe className="immersive-frame" ref={appearanceFrame} title={t('Appearance editor','外观编辑器')} src={frameSrc(appearance.url)} onLoad={()=>sendLanguage(appearanceFrame.current)} />:view==='appearance'&&<div className="editor-empty"><ImagePlus size={34}/><h2>{t('Start with a paired pattern or a studio composition','从图集纹样或工作台构图开始设计')}</h2><button className="primary" onClick={()=>setPicker('appearance')}>{t('Choose structure','选择结构')}</button></div>}
   </section>
  </main>
  {!workspace&&<footer><span>Floral Scroll Atlas</span><a href="#/research">{t('Floral Scroll Structures and Blue-and-White Patterns','缠枝纹数字构成与青花图集')}</a><span>2026</span></footer>}
  {picker&&<Dialog title={picker==='A'||picker==='B'?t('Choose '+picker,'选择结构 '+picker):t('Choose a starting structure','选择起始结构')} close={()=>setPicker(null)} t={t}>
   {recent.length>0&&<RecentDrafts items={recent} t={t} zh={zh} choose={pickerChoose} disabled={!!pending}/>}
   {pending&&<p role="status">{t('Opening the workspace…','正在打开工作区…')}</p>}{error&&<p role="alert">{error}</p>}<Gallery picker t={t} zh={zh} onSelect={pickerChoose}/>
  </Dialog>}
 </div>;
}
function Dialog({title,close,t,children}:{title:string;close:()=>void;t:Translate;children:ReactNode}){
 const dialog=useRef<HTMLDialogElement>(null);
 useEffect(()=>{
  const el=dialog.current,previous=document.activeElement as HTMLElement|null;
  el?.showModal();
  return()=>{el?.close();previous?.focus();};
 },[]);
 return <dialog className="atlas-dialog" ref={dialog} onCancel={e=>{e.preventDefault();close();}}><div className="modal-head"><h2>{title}</h2><button type="button" aria-label={t('Close','关闭')} onClick={close}><X size={22}/></button></div>{children}</dialog>;
}
createRoot(document.getElementById('root')!).render(<App/>);

function RecentDrafts({items,t,zh,choose,disabled}:{items:Item[];t:Translate;zh:boolean;choose:(item:Item)=>void;disabled:boolean}) {
 const [page,setPage]=useState(0);
 const size=3,count=Math.ceil(items.length/size),safePage=Math.min(page,count-1);
 return <section className="picker-history">
  <header><h3>{t('Recent drafts','最近草稿')}</h3>{count>1&&<div className="draft-paging">
   <button type="button" disabled={safePage<=0} onClick={()=>setPage(safePage-1)} aria-label={t('Previous drafts','上一组草稿')}><ChevronLeft size={16}/></button>
   <span>{safePage+1} / {count}</span>
   <button type="button" disabled={safePage>=count-1} onClick={()=>setPage(safePage+1)} aria-label={t('Next drafts','下一组草稿')}><ChevronRight size={16}/></button>
  </div>}</header>
  <div className="draft-list">{items.slice(safePage*size,(safePage+1)*size).map((item,index)=><button key={item.case_id} onClick={()=>choose(item)} disabled={disabled}>
   <StructureView zh={zh} item={item} preview/><span>{t('Draft','草稿')} {String(safePage*size+index+1).padStart(2,'0')} · {displayCatalogId(item.prototype)}</span><ArrowRight size={15}/>
  </button>)}</div>
 </section>;
}
