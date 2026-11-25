import {useEffect,useRef,useState} from 'react';
import {ArrowRight,ArrowUpRight,ChevronDown,ChevronLeft,ChevronRight,Download,GitCompareArrows,ImagePlus,PenTool,Search} from 'lucide-react';
import StructureView from './StructureView';
import PairedArtwork,{PorcelainImage,useFeaturedPair} from './PairedArtwork';
import type {Item} from './types';
import {api,assetRoute,catalogSearch,displayCatalogId,FEATURED,PROTOTYPES,type Assets,type Side,type Translate} from './atlas';

export type GalleryFilter={prototype:string;q:string;page:number;children:number};
const initial:GalleryFilter={prototype:'',q:'',page:1,children:0};
export function filterFrom(query:URLSearchParams):GalleryFilter{
 const page=Number(query.get('page'));
 const minimum=Number(query.get('min_children'));
 const prototype=query.get('prototype')||'';
 return {prototype:PROTOTYPES.includes(prototype)?prototype:'',q:query.get('q')||'',page:Number.isSafeInteger(page)&&page>0?page:1,children:[1,3,5].includes(minimum)?minimum:0};
}
export function galleryRoute(f:GalleryFilter){
 const query=new URLSearchParams();
 if(f.prototype)query.set('prototype',f.prototype);
 if(f.q)query.set('q',f.q);
 if(f.page>1)query.set('page',String(f.page));
 if(f.children)query.set('min_children',String(f.children));
 return '#/collection'+(query.size?'?'+query:'');
}
type GalleryProps={
 t:Translate;zh:boolean;onSelect:(item:Item)=>void;
 filter?:GalleryFilter;onFilter?:(filter:GalleryFilter,replace?:boolean)=>void;picker?:boolean;restoreScroll?:number;
};
export function Gallery({t,zh,onSelect,filter,onFilter,picker=false,restoreScroll}:GalleryProps){
 const [local,setLocal]=useState(initial);
 const {prototype,q,page,children}=filter||local;
 const [data,setData]=useState<Assets|null>(null);
 const [phase,setPhase]=useState<'loading'|'ready'|'error'>('loading');
 const [retry,setRetry]=useState(0);
 const [search,setSearch]=useState(q);
 const grid=useRef<HTMLElement>(null);
 const restored=useRef(false);
 const size=picker?6:12;
 useEffect(()=>{setSearch(q);},[q]);
 useEffect(()=>{
  if(search===q)return;
  const timer=window.setTimeout(()=>change({q:search,page:1},true),180);
  return()=>window.clearTimeout(timer);
 },[search,q,prototype,children]);
 useEffect(()=>{
  const abort=new AbortController();
  setPhase('loading');
  const args=new URLSearchParams({prototype,q:catalogSearch(q),page:String(page),page_size:String(size),min_children:String(children)});
  api<Assets>('/assets?'+args,{signal:abort.signal})
   .then(next=>{if(!abort.signal.aborted){setData(next);setPhase('ready');}})
   .catch(()=>{if(!abort.signal.aborted)setPhase('error');});
  return()=>abort.abort();
 },[prototype,q,page,size,children,retry]);
 useEffect(()=>{
  if(phase==='ready'&&!restored.current){
   restored.current=true;
   if(restoreScroll)window.scrollTo(0,restoreScroll);
  }
 },[phase,restoreScroll]);
 function change(fields:Partial<GalleryFilter>,replace=false){
  const next={prototype,q,page,children,...fields};
  if(onFilter)onFilter(next,replace);
  else setLocal(next);
 }
 return <section className="collection" ref={grid} aria-busy={phase==='loading'}>
  {!picker&&<p className="collection-lead">{t('Explore 500 structural drawings paired with blue-and-white patterns. Browse by prototype or number of child branches.','图集收录 500 组结构线稿与青花纹样，可按原型和子枝数量查找。')}</p>}
  <div className="gallery-toolbar">
   <div className="filter-pills" aria-label={t('Filter by prototype','按原型筛选')}>
    {['',...PROTOTYPES].map(p=><button key={p} className={p===prototype?'active':''} aria-pressed={p===prototype} onClick={()=>change({prototype:p,page:1})}>{p?displayCatalogId(p):t('All prototypes','全部原型')}</button>)}
   </div>
   <label className="search"><Search size={16}/><input aria-label={t('Search collection','搜索图集')} placeholder={t('Search by number, e.g. SW1–A · 01','搜索编号，如 SW1–A · 01')} value={search} onChange={e=>setSearch(e.target.value)}/></label>
  </div>
  <div className="gallery-count">
   <span role="status">{phase==='loading'?t(data?'Updating results…':'Loading collection…',data?'正在更新结果…':'正在读取图集…'):phase==='error'?t('Collection could not load.','图集读取失败。'):t((data?.total??0)+' matching '+(data?.total===1?'pair':'pairs'),'共 '+(data?.total??0)+' 组图样')}</span>
   <label>{t('Child branches','子枝繁简')}<select value={children} onChange={e=>change({children:Number(e.target.value),page:1})}><option value={0}>{t('All','全部')}</option>{[1,3,5].map(n=><option key={n} value={n}>{t(n+' or more','至少 '+n+' 枝')}</option>)}</select></label>
  </div>
  {phase==='error'&&<p className="status-error" role="alert">{t('Check the connection and try again.','请检查连接后重试。')} <button className="secondary" onClick={()=>setRetry(n=>n+1)}>{t('Retry','重试')}</button></p>}
  <div className="gallery-grid">
   {phase==='loading'&&!data&&Array.from({length:size/2},(_,i)=><div key={i} className="skeleton-card" aria-hidden="true"/>)}
   {data?.items.map(item=>{
    const card=<><div className="card-render"><PorcelainImage src={'/media/thumbs/'+item.pair_id+'.webp'} fallback={item.render_url}/></div>
     <div className="card-structure"><StructureView item={item} zh={zh} preview/></div><div className="card-caption"><div><strong className="catalog-id">{displayCatalogId(item.pair_id!)}</strong><span>{item.l1} {t('parents','父枝')} · {item.l2} {t('children','子枝')}</span></div><ArrowUpRight size={16}/></div></>;
    return picker?<button className="gallery-card" key={item.pair_id} onClick={()=>onSelect(item)}>{card}</button>:<a className="gallery-card" aria-label={displayCatalogId(item.pair_id!)} href={assetRoute(item.pair_id!)} key={item.pair_id} onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onSelect(item);}}>{card}</a>;
   })}
  </div>
  {phase==='ready'&&!data?.items.length&&<div className="empty-state"><p>{t('No matching structures.','没有匹配的结构。')}</p><button className="secondary" onClick={()=>{setSearch('');change(initial);}}>{t('Clear filters','清除筛选')}</button></div>}
  {!!data?.total&&<div className="pagination"><button disabled={page===1||phase!=='ready'} onClick={()=>{change({page:page-1});grid.current?.scrollIntoView({block:'start'});}}><ChevronLeft size={15}/>{t('Previous','上一页')}</button><span>{page} / {Math.max(1,Math.ceil(data.total/size))}</span><button disabled={page*size>=data.total||phase!=='ready'} onClick={()=>{change({page:page+1});grid.current?.scrollIntoView({block:'start'});}}>{t('Next','下一页')}<ChevronRight size={15}/></button></div>}
 </section>;
}

export function Downloads({item,t,rendering=false}:{item:Item;t:Translate;rendering?:boolean}){
 const options=[[t('Vector structure (SVG)','矢量结构（SVG）'),item.svg_url],[t('Structural drawing (PNG)','结构线稿（PNG）'),item.png_url],[t('Geometry (JSON)','几何数据（JSON）'),item.json_url],[t('Composition parameters','构图参数'),item.parameters_url],...(rendering?[[t('Blue-and-white pattern (PNG)','青花纹样（PNG）'),item.render_url]]:[])];
 return <details className="download-menu"><summary className="secondary"><Download size={16}/>{t('Download','下载')}<ChevronDown size={14}/></summary><div className="download-list">{options.map(([label,url])=>url&&<a href={url} download key={label}>{label}<Download size={13}/></a>)}</div></details>;
}

export function FeaturedView({t,zh}:{t:Translate;zh:boolean}){
 const item=useFeaturedPair();
 return <div className="landing"><section className="landing-hero">
 <div className="landing-copy"><h1>{t('Floral Scroll Atlas','缠枝纹数字图集')}</h1><p>{t('A single vine links flowers and leaves in a repeating blue-and-white border. The structural drawing traces those connections and gives new branch arrangements a starting point in the original composition.','一条主藤串起花叶，反复延伸成青花边饰。结构线稿保留花位与分枝的连接，重新安排枝叶时，原有构成仍有迹可循。')}</p></div>
 <section className="hero-pair specimen-surface" aria-label={t('Blue-and-white pattern and structural drawing','青花纹样与结构线稿')}>
  <PairedArtwork item={item} t={t} zh={zh} mode="hero"/>
  <p className="specimen-caption"><span>{t('Blue-and-white pattern and structural drawing','青花纹样与结构线稿')}</span><span className="catalog-id">{displayCatalogId(FEATURED)}</span></p>
 </section>
 <div className="landing-actions"><a className="primary" href={assetRoute(FEATURED)}>{t('View this pair','查看此组图样')}<ArrowRight size={17}/></a><a className="secondary" href="#/studio?prototype=SW1-C">{t('Open the pattern studio','进入纹样工作台')}</a></div>
 </section><div className="landing-index"><a href="#/collection">{t('Browse 500 paired patterns','浏览 500 组配对图样')}<ArrowUpRight size={16}/></a><a href="#/research">{t('Explore the structure of single-wave floral scrolls','阅读单波形缠枝构成研究')}<ArrowUpRight size={16}/></a></div></div>;
}

export function PairDetail({id,cached,t,zh,back,onCompare,onEditor,onAppearance,busy}:{id:string;cached?:Item;t:Translate;zh:boolean;back:string;onCompare:(side:Side,item:Item)=>void;onEditor:(item:Item)=>void;onAppearance:(item:Item)=>void;busy:boolean}){
 const [loaded,setLoaded]=useState<{id:string;item?:Item;error?:true}|null>(null);
 const [retry,setRetry]=useState(0);
 const known=cached?.pair_id===id?cached:undefined;
 useEffect(()=>{
  if(known)return;
  const abort=new AbortController();
  api<Assets>('/assets?'+new URLSearchParams({q:id,page_size:'12'}),{signal:abort.signal})
   .then(data=>{if(!abort.signal.aborted)setLoaded({id,item:data.items.find(item=>item.pair_id===id)});})
   .catch(()=>{if(!abort.signal.aborted)setLoaded({id,error:true});});
  return()=>abort.abort();
 },[id,known,retry]);
 const shown=loaded?.id===id?loaded:undefined;
 const item=known||shown?.item;
 return <section className="pair-detail">
  <a className="text-button back-link" href={back}><ChevronLeft size={16}/>{t('Back to collection','返回配对图集')}</a>
  <header className="pair-heading"><h1 className="catalog-id" aria-label={displayCatalogId(id)}>{displayCatalogId(id)}</h1></header>
  {item?<><div className="detail-art specimen-surface"><PairedArtwork key={id} item={item} t={t} zh={zh} mode="detail"/></div>
   <div className="pair-actions"><button className="primary" disabled={busy} onClick={()=>onAppearance(item)}><ImagePlus size={15}/>{t('Edit appearance','编辑外观')}</button><button className="secondary" disabled={busy} onClick={()=>onEditor(item)}><PenTool size={15}/>{t('Edit structure','编辑结构')}</button><button className="text-button" onClick={()=>onCompare('A',item)}><GitCompareArrows size={15}/>{t('Use as A','设为对照 A')}</button><button className="text-button" onClick={()=>onCompare('B',item)}><GitCompareArrows size={15}/>{t('Use as B','设为对照 B')}</button><Downloads item={item} t={t} rendering/></div></>:shown?<div className="empty-state">{shown.error?<><p>{t('Could not load this pair.','无法读取这组图样。')}</p><button className="secondary" onClick={()=>{setLoaded(null);setRetry(n=>n+1);}}>{t('Retry','重试')}</button></>:<p>{t('This pair was not found in the collection.','图集中未找到这组图样。')}</p>}</div>:<div className="skeleton-card detail-loading" role="status">{t('Loading this pair…','正在读取配对图样…')}</div>}
 </section>;
}
