import {useEffect,useState} from 'react';
import {ChevronDown,GitCompareArrows,ImagePlus,PenTool,Shuffle} from 'lucide-react';
import StructureView from './StructureView';
import {Downloads} from './Gallery';
import type {Item,Params} from './types';
import {displayCatalogId,PROTOTYPES,ROLES,type Catalog,type Side,type Translate} from './atlas';

type ParamProps={value:Params;onChange:(value:Params)=>void;t:Translate;disabled:boolean;shared?:boolean;hidePrototype?:boolean;advancedOpen?:boolean;};
export function ParamControls({value,onChange,t,disabled,shared=false,hidePrototype=false,advancedOpen=false}:ParamProps){
 const [advanced,setAdvanced]=useState(advancedOpen);
 function change<K extends keyof Params>(key:K,next:Params[K]){onChange({...value,[key]:next});}
 return <div className="parameter-fields">
  {!shared&&!hidePrototype&&<label>{t('Prototype','花藤原型')}<select disabled={disabled} value={value.prototype} onChange={e=>change('prototype',e.target.value)}>{PROTOTYPES.map(p=><option key={p} value={p}>{displayCatalogId(p)}</option>)}</select></label>}
  {!shared&&<label>{t('Main-vine variation','主藤变体')}<select disabled={disabled} value={value.variant} onChange={e=>change('variant',e.target.value)}><option value="expanded">{t('Expanded','舒展')}</option><option value="compact">{t('Compact','紧凑')}</option><option value="swept">{t('Swept','偏转')}</option></select></label>}
  <label>{t('Branch density','分枝疏密')}<select disabled={disabled} value={value.density} onChange={e=>change('density',e.target.value)}><option value="simple">{t('Sparse','疏')}</option><option value="medium">{t('Balanced','中')}</option><option value="rich">{t('Dense','密')}</option></select></label>
  <button className="advanced" aria-expanded={advanced} onClick={()=>setAdvanced(!advanced)}>{t('Variation and branch counts','构图变化与枝数')}<ChevronDown size={15}/></button>
  {advanced&&<><label>{t('Variation number','构图编号')}<div className="seed-row"><input type="number" min="0" max="4294967295" disabled={disabled} value={value.seed} onChange={e=>change('seed',Math.min(4294967295,Math.max(0,Math.trunc(Number(e.target.value)))))} /><button className="secondary" disabled={disabled} aria-label={t('Pick a new variation number','更换构图编号')} onClick={()=>change('seed',Math.floor(Math.random()*4294967295))}><Shuffle size={15}/></button></div></label>
  <label>{t('Branch arrangement','分枝排布')}<select disabled={disabled} value={value.control} onChange={e=>change('control',e.target.value)}><option value="soft">{t('By density','按疏密')}</option><option value="exact">{t('Fixed branch counts','按固定枝数')}</option></select></label>
  {value.control==='exact'&&<p className="small-note count-hint">{t('Per repeat: sparse 5/1, balanced 7/3, dense 9/5. The first number counts parent branches and flower-bearing paths together. The second counts child branches.','每单元疏 5/1 · 中 7/3 · 密 9/5。前一个数合计父枝与承花路径，后一个数为子枝数。')}</p>}</>}
 </div>;
}
export function Counts({item,t}:{item:Item;t:Translate}){
 return <div className="numbers"><div><strong>{item.l1}</strong><span>{t('parent branches','父枝')}</span></div><div><strong>{item.l2}</strong><span>{t('child branches','子枝')}</span></div>{!!item.l3&&<div><strong>{item.l3}</strong><span>{t('third-level','三级枝')}</span></div>}<div><strong>{item.flowers}</strong><span>{t('flower sites','花位')}</span></div></div>;
}
type Actions={onEditor:(item:Item)=>void;onAppearance:(item:Item)=>void;busy:boolean;zh:boolean;t:Translate;};
type StudioProps=Actions&{
 catalog:Catalog|null;catalogError:boolean;retryCatalog:()=>void;params:Params;current:Item|null;
 onParams:(p:Params)=>void;onPrototype:(p:string)=>void;generate:()=>void;onCompare:(item:Item)=>void;
};
export function Studio({t,zh,catalog,catalogError,retryCatalog,params,current,onParams,onPrototype,generate,onCompare,onEditor,onAppearance,busy}:StudioProps){
 const item=current||catalog?.prototypes.find(p=>p.id===params.prototype)?.preview||null;
 const [role,setRole]=useState('all');
 const [selection,select]=useState<{label:string;description:string}|null>(null);
 const [reset,setReset]=useState(0);
 useEffect(()=>{setRole('all');select(null);},[item?.structure_url]);
 return <section className="studio-layout">
  <div className="studio-art">
   <div className="canvas-head"><div><h2>{displayCatalogId(item?.prototype||params.prototype)}</h2><p>{current?t('Current composition','当前构图'):t('Prototype drawing','原型线稿')}</p></div></div>
   {item?<StructureView item={item} zh={zh} role={role} onSelect={select} resetToken={reset}/>:<div className="canvas-placeholder" role="status">{catalogError?t('The catalog could not load.','原型目录读取失败。'):t('Loading prototypes…','正在读取原型…')}{catalogError&&<button className="secondary" onClick={retryCatalog}>{t('Retry','重试')}</button>}</div>}
   {current&&<>
    <div className="role-legend" aria-label={t('Layers of the drawing','线稿层次')}><button className={role==='all'?'active':''} aria-pressed={role==='all'} onClick={()=>{setRole('all');select(null);setReset(n=>n+1);}}>{t('All layers','全部层次')}</button>{ROLES.map(([id,color,en,cn])=><button key={id} aria-pressed={role===id} className={role===id?'active':''} onClick={()=>{setRole(id);select(null);}}><i style={{background:color}}/>{t(en,cn)}</button>)}</div>
    <div className="studio-results"><Counts item={current} t={t}/><div className="result-actions"><button className="primary" onClick={()=>onEditor(current)} disabled={busy}><PenTool size={15}/>{t('Edit structure','编辑结构')}</button><button className="secondary" onClick={()=>onAppearance(current)} disabled={busy}><ImagePlus size={15}/>{t('Edit appearance','编辑外观')}</button><button className="text-button" onClick={()=>onCompare(current)}><GitCompareArrows size={15}/>{t('Use as A','设为对照 A')}</button><Downloads item={current} t={t}/></div></div>
    {selection&&<aside className="relation-note"><strong>{selection.label}</strong><p>{selection.description}</p><button className="text-button" onClick={()=>{select(null);setReset(n=>n+1);}}>{t('Clear selection','清除选择')}</button></aside>}
   </>}
  </div>
  <aside className="studio-controls">
   <h2>{t('Floral prototype','花藤原型')}</h2>
   <div className="prototype-grid">{PROTOTYPES.map(id=><button key={id} aria-pressed={params.prototype===id} disabled={busy||!catalog} className={params.prototype===id?'chosen':''} onClick={()=>onPrototype(id)}>{catalog&&<StructureView zh={zh} preview item={catalog.prototypes.find(p=>p.id===id)?.preview||null}/>}<span>{displayCatalogId(id)}</span></button>)}</div>
   <h2>{t('Branch settings','分枝设置')}</h2>
   <ParamControls value={params} onChange={onParams} t={t} disabled={busy} hidePrototype/>
   <button className="primary generate" disabled={busy||!catalog} onClick={generate}><Shuffle size={16}/>{t('Generate a new composition','生成新构图')}</button>
  </aside>
 </section>;
}
type CompareProps=Actions&{
 items:[Item|null,Item|null];a:Params;b:Params;setA:(v:Params)=>void;setB:(v:Params)=>void;
 lock:boolean;setLock:(v:boolean)=>void;commonBox:string;active:Side;setActive:(v:Side)=>void;
 generate:(side:Side)=>void;choose:(side:Side)=>void;onLocal:(side:Side,file?:File)=>void;
};
export function Compare({t,zh,items,a,b,setA,setB,lock,setLock,commonBox,active,setActive,generate,choose,onLocal,onEditor,onAppearance,busy}:CompareProps){
 const [camera,setCamera]=useState({zoom:1,left:0});
 useEffect(()=>{setCamera({zoom:1,left:0});},[items[0]?.structure_url,items[1]?.structure_url]);
 const [first]=items;
 const fixed=first?.parameters||a;
 const lockedOut=!!first?.is_local||!!first?.user_edited;
 return <section className="comparison">
  <div className="mobile-compare-switch" aria-label={t('Choose comparison side','选择对照侧')}>{(['A','B'] as const).map(side=><button key={side} className={active===side?'active':''} aria-pressed={active===side} onClick={()=>setActive(side)}>{side==='A'?t('Sample A · Reference','样本 A · 基准'):t('Sample B · Comparison','样本 B · 对照')}</button>)}</div>
  <div className="compare-canvases">
   {(['A','B'] as const).map((side,i)=>{
    const item=items[i];
    return <article key={side} className={active===side?'compare-active':''}>
     <div className="canvas-head"><h2>{side==='A'?t('Sample A · Reference','样本 A · 基准'):t('Sample B · Comparison','样本 B · 对照')}</h2>{item&&<span className="case-meta">{item.is_local?item.local_name:displayCatalogId(item.pair_id||item.prototype)}</span>}</div>
     {item?.is_local?<div className="local-compare"><img src={item.local_url} alt={item.local_name}/><p>{t('Local reference image','本地参考图')}</p></div>:item?<StructureView item={item} zh={zh} compact sharedViewBox={commonBox} camera={camera} onCamera={setCamera}/>:<div className="empty-state compare-empty"><GitCompareArrows size={24}/><p>{t('Generate a composition or choose one from the collection to compare here.','在下方生成构图，或从图集选取一组图样来对照。')}</p></div>}
     {item&&!item.is_local&&<div className="compare-result"><Counts item={item} t={t}/><div className="result-actions"><button className="primary" onClick={()=>onEditor(item)} disabled={busy}><PenTool size={15}/>{t('Edit structure','编辑结构')}</button><button className="secondary" onClick={()=>onAppearance(item)} disabled={busy}><ImagePlus size={15}/>{t('Edit appearance','编辑外观')}</button><Downloads item={item} t={t}/></div></div>}
    </article>;
   })}
  </div>
  <div className="comparison-options"><label><input type="checkbox" checked={lock&&!lockedOut} disabled={lockedOut} onChange={e=>setLock(e.target.checked)}/>{t('Lock A’s vine and flower sites','锁定 A 的主藤与花位')}</label>
   {lock&&!lockedOut&&<p>{displayCatalogId(fixed.prototype)} · {({expanded:t('Expanded','舒展'),compact:t('Compact','紧凑'),swept:t('Swept','偏转')} as Record<string,string>)[fixed.variant]} · {t('B shares A’s flower-bearing paths as well. Only branch arrangement varies.','B 同时沿用 A 的承花路径，分枝可单独调整。')}</p>}
   {lockedOut&&<p>{t('Local images and edited structures use independent comparison settings.','本地图像和编辑后的结构采用独立对照设置。')}</p>}
  </div>
  <div className="compare-forms">{(['A','B'] as const).map(side=><section key={side} className={active===side?'compare-active':''}>
   <h2>{side} · {t('Settings','对照设置')}</h2>
   <ParamControls value={side==='A'?a:b} onChange={side==='A'?setA:setB} t={t} disabled={busy} shared={side==='B'&&lock&&!lockedOut}/>
   <div className="comparison-buttons"><button className="primary" disabled={busy||side==='B'&&lock&&!first} onClick={()=>generate(side)}>{t('Generate composition '+side,'生成方案 '+side)}</button><button className="secondary" onClick={()=>choose(side)}>{t('Choose from the collection','从图集选取')}</button><label className="file-button"><ImagePlus size={16}/>{t('Upload a local reference','上传本地参考图')}<input type="file" accept=".png,.jpg,.jpeg,.svg" onChange={e=>{onLocal(side,e.target.files?.[0]);e.target.value='';}}/></label></div>
  </section>)}</div>
 </section>;
}
