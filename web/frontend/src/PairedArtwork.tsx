import {useEffect,useState,type CSSProperties,type PointerEvent} from 'react';
import {Blend,MoveHorizontal} from 'lucide-react';
import StructureView from './StructureView';
import {api,FEATURED,featuredMedia,type Assets,type Translate} from './atlas';
import type {Item} from './types';

export function useFeaturedPair() {
 const [item,setItem]=useState<Item|null>(null);
 useEffect(()=>{
  const controller=new AbortController();
  api<Assets>('/assets?q='+encodeURIComponent(FEATURED),{signal:controller.signal})
   .then(data=>setItem(data.items.find(entry=>entry.pair_id===FEATURED)||null))
   .catch(()=>{});
  return()=>controller.abort();
 },[]);
 return item;
}

export function PorcelainImage({src,fallback,alt='',priority=false}:{src:string;fallback?:string;alt?:string;priority?:boolean}) {
 const [source,setSource]=useState(src),[ready,setReady]=useState(false),[failed,setFailed]=useState(false);
 const selected=source===fallback?source:src;
 return <div className={'specimen-image'+(ready?' is-ready':failed?' is-unavailable':' is-loading')}>
  <img className="qinghua-artwork" src={selected} alt={alt} loading={priority?'eager':'lazy'} fetchPriority={priority?'high':undefined}
    onLoad={()=>{setReady(true);setFailed(false);}} onError={()=>{if(fallback&&selected!==fallback){setSource(fallback);}else setFailed(true);}}/>
 </div>;
}

export default function PairedArtwork({item,t,zh,mode}:{item:Item|null;t:Translate;zh:boolean;mode:'hero'|'detail'|'research'}) {
 const [reveal,setReveal]=useState(0);
 const rendering=item?.render_url||(mode!=='detail'?featuredMedia.rendering:'');
 const overlay=!!item&&reveal>0;
 const label=t('Overlay structure','透视叠合');
 function dragReveal(e:PointerEvent<HTMLSpanElement>){
  const bounds=e.currentTarget.parentElement!.getBoundingClientRect();
  setReveal(Math.max(0,Math.min(100,Math.round((e.clientX-bounds.left)/bounds.width*100))));
 }
 const skeleton=<StructureView item={item} zh={zh} preview/>;
 return <div className={'paired-artwork paired-'+mode}>
  <figure className="paired-panel">
   <div className={'paired-media'+(overlay?' has-overlay':'')} style={{'--reveal':reveal+'%'} as CSSProperties}>
    <PorcelainImage key={rendering} src={rendering} alt={t('Blue-and-white floral scroll','缠枝纹青花纹样')} priority/>
    {overlay&&<div className="paired-overlay" aria-hidden="true"><div className="paired-overlay-lines">{skeleton}</div></div>}
    {item&&mode==='hero'&&<span aria-hidden="true" className={'paired-reveal-edge'+(reveal>0?' is-active':'')}
     onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);dragReveal(e);}}
     onPointerMove={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId))dragReveal(e);}}><MoveHorizontal size={18}/></span>}
   </div>
   {mode==='detail'&&<figcaption>{t('Blue-and-white pattern','青花纹样')}<button type="button" className="secondary overlay-toggle" aria-pressed={!!reveal} onClick={()=>setReveal(reveal?0:100)}><Blend size={16}/>{label}</button></figcaption>}
  </figure>
  <figure className="paired-panel paired-structure">
   <div className="paired-media" role="img" aria-label={t('Structural drawing of the same floral scroll','同一组缠枝纹的结构线稿')}>{item?skeleton:null}</div>
   {mode==='detail'&&<figcaption>{t('Structural drawing','结构线稿')}</figcaption>}
  </figure>
  {mode==='hero'&&item&&<label className="paired-reveal"><Blend size={15}/><span>{label}</span><input type="range" min="0" max="100" value={reveal} onChange={e=>setReveal(Number(e.target.value))}/></label>}
 </div>;
}
