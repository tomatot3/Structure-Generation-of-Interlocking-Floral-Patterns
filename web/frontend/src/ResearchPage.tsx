import {useEffect,useState} from 'react';
import {ArrowRight} from 'lucide-react';
import PairedArtwork,{useFeaturedPair} from './PairedArtwork';
import {assetRoute,displayCatalogId,FEATURED} from './atlas';
import './research.css';

type Point=[number,number];
type Diagram={prototype:string;asset_id:string;pair_id:string;backbone:Point[];flowers:{center:Point;rx:number;ry:number}[];supports:Point[][]};
type Role='all'|'vine'|'flowers'|'supports';
const families=[
  {id:'SW1',name:['Crest–trough','波峰波谷型'],short:['Flowers at peaks and troughs','花位与峰谷对应'],
   description:['Flowers usually sit near the peaks and troughs. Their bearing paths start at those points or on the flanks.','花位通常与主藤的波峰、波谷对应，承花路径从峰谷或侧翼引出。'],
   distinction:['A and B both place two flowers in each repeat, with different wave heights, repeat widths and alignments. In C, the vine and its flower-bearing paths wind around the two flower sites in turn.','A、B 每单元各有两个花位，波幅、周期与相位的变化使两者各有节奏。C 的主藤与承花路径在两个花位周围交替回环。'],
   prototypes:['SW1-A','SW1-B','SW1-C']},
  {id:'SW2',name:['Axial flower-passing','轴心穿花型'],short:['The vine passes through flower sites','主藤穿花接续'],
   description:['The flower sits in the course of the main vine, which continues through the flower site without a separate bearing path.','花位落在主藤经过的区域，主藤穿过花位接续，花朵由主藤承接。'],
   distinction:['SW2–A has one flower site per repeat. The visible vine on either side of the flower guides the inferred connection behind the petals.','SW2–A 每单元一个花位。图中花瓣遮住的部分，依据花外可见枝段推定接续。'],
   prototypes:['SW2-A']},
  {id:'SW3',name:['Tangential flower-bearing','切向承花型'],short:['Flowers on tangential paths','切向引枝承花'],
   description:['The bearing path follows the direction of the vine where it leaves, then turns toward the flower. The flower sites have no fixed alignment with the peaks and troughs.','承花路径沿主藤在引出点的切向伸展，再转向花位。花位与主藤的峰谷没有固定对应。'],
   distinction:['SW3–A places one flower in each repeat, and SW3–B places two.','SW3–A 为单花构成，SW3–B 为双花构成。'],
   prototypes:['SW3-A','SW3-B']}
];
const captions:Record<string,[string,string]>={
 'SW1-A':['Two flowers · configuration A','双花 · 配置A'],
 'SW1-B':['Two flowers · configuration B','双花 · 配置B'],
 'SW1-C':['Two flowers · alternating paths','双花 · 交替绕花'],
 'SW2-A':['One flower · vine passing through','单花 · 主藤穿花'],
 'SW3-A':['One flower · tangential connection','单花 · 切向承花'],
 'SW3-B':['Two flowers · tangential connections','双花 · 切向承花']
};

function RelationshipDiagram({data,role,zh}:{data:Diagram;role:Role;zh:boolean}){
 const points=[...data.backbone,...data.supports.flat(),...data.flowers.flatMap(f=>[[f.center[0]-f.rx,f.center[1]-f.ry],[f.center[0]+f.rx,f.center[1]+f.ry]] as Point[])];
 const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
 const x=Math.min(...xs)-.065,y=Math.min(...ys)-.065,w=Math.max(...xs)-x+.065,h=Math.max(...ys)-y+.065;
 const line=(ps:Point[])=>ps.map(p=>p.join(',')).join(' ');
 const opacity=(r:Role)=>role==='all'||role===r?1:.12;
 return <svg viewBox={`${x} ${y} ${w} ${h}`} role="img" aria-label={`${data.prototype} ${zh?'花藤关系图':'flower–vine relationships'}`}>
   <polyline points={line(data.backbone)} fill="none" stroke="var(--curve-vine)" strokeWidth="3" vectorEffect="non-scaling-stroke" opacity={opacity('vine')}/>
   <g opacity={opacity('supports')} stroke="var(--curve-support)" fill="none" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
    {data.supports.map((p,i)=><polyline key={i} points={line(p)} vectorEffect="non-scaling-stroke"/>)}</g>
   <g opacity={opacity('flowers')} fill="var(--curve-flower-fill)" stroke="var(--curve-flower)" strokeWidth="1.8">
    {data.flowers.map((f,i)=><ellipse key={i} cx={f.center[0]} cy={f.center[1]} rx={f.rx} ry={f.ry} vectorEffect="non-scaling-stroke"/>)}</g>
 </svg>;
}

export default function ResearchPage({zh,onPrototype,onGallery,busy}:{zh:boolean;onPrototype:(id:string)=>void;onGallery:()=>void;busy:boolean}){
 const t=(en:string,cn:string)=>zh?cn:en;
 const [family,setFamily]=useState('SW1');
 const [role,setRole]=useState<Role>('all');
 const [diagrams,setDiagrams]=useState<Diagram[]>([]);
 const [error,setError]=useState(false);
 useEffect(()=>{let active=true;fetch('/research/configurations.json').then(r=>{if(!r.ok)throw Error();return r.json()}).then(d=>{if(active)setDiagrams(d)}).catch(()=>{if(active)setError(true)});return()=>{active=false}},[]);
 const selected=families.find(f=>f.id===family)!;
 const featured=useFeaturedPair();
 return <div className="heritage-page">
  <section className="heritage-lead" aria-labelledby="heritage-title">
   <div className="heritage-story">
    
    <h2 id="heritage-title">{t('The rhythm of a continuous vine','一条主藤的构图秩序')}</h2>
    <p>{t('A winding vine links flowers and leaves in a repeating pattern. Different flowers can follow a similar arrangement. Two curves may also look alike while serving different purposes. One carries a flower, while the other is a side branch.','缠枝纹沿一条起伏的主藤连缀花叶。花叶的形态虽有变化，花位与主藤的安排仍可能相近。看起来相似的两条曲线，一条可能托起花朵，另一条可能只是旁枝。')}</p>
    <p>{t('Pattern books preserve the appearance of floral scrolls in images and text. The Atlas also records where each branch joins and its role in the design. Those records help us compare patterns and carry their composition into new designs.','图录用图版和文字保存纹样的外貌。图集则把枝条的作用与连接关系一同记录下来，便于对照不同图样，也让再设计有原来的构图可参照。')}</p>
   </div>
   <div className="heritage-pair specimen-surface">
    <PairedArtwork item={featured} zh={zh} t={t} mode="research"/>
    <p className="specimen-caption"><a href={assetRoute(FEATURED)}>{t('View the paired example','查看配对案例')} <ArrowRight size={15}/></a></p>
   </div>
  </section>

  <section className="sw-section" aria-labelledby="sw-title">
   <div className="research-section-heading"><h2 id="sw-title">{t('Three flower–vine configurations','三类花藤配置')}</h2>
    <p>{t('In a single-wave floral scroll (SW), flowers and branches repeat along one undulating vine. The Atlas groups these scrolls into three types by flower placement and the way each flower connects to the vine.','单波形缠枝纹（SW）的花叶沿一条波状主藤连续重复。顺着主藤看花位，再看花朵如何与主藤相连，可以辨认出三类构成。')}</p>
   </div>
   <div className="classification-criteria">
    {[[t('Flower position','花位分布'),t('Where the flower sits along or beside the main vine.','看花位落在主藤的峰谷、走向线上，还是偏在一侧。')],[t('Branch origin','引枝起点'),t('Whether a separate path carries the flower and where that path starts.','有独立承花路径时，留意它与主藤相接的位置。')],[t('Path through the flower site','接续走势'),t('The main vine can run through the flower site, or a separate path can turn toward it.','主藤可穿过花位接续，花位也可由承花路径转向连接。')]].map(([h,p],i)=><div key={h}><span>0{i+1}</span><div><h3>{h}</h3><p>{p}</p></div></div>)}
   </div>
   <div className="family-tabs" role="tablist" aria-label={t('Structural families','结构分类')}>
    {families.map(f=><button key={f.id} role="tab" id={`tab-${f.id}`} aria-controls="family-panel" aria-selected={family===f.id} onClick={()=>{setFamily(f.id);setRole('all')}}><strong>{f.id}</strong><span>{f.name[zh?1:0]}<small>{f.short[zh?1:0]}</small></span></button>)}
   </div>
   <div className="family-panel" id="family-panel" role="tabpanel" aria-labelledby={`tab-${family}`}>
    <div className="family-description"><div><h3>{selected.name[zh?1:0]}</h3><p>{selected.description[zh?1:0]}</p></div><p>{selected.distinction[zh?1:0]}</p></div>
    <div className="relationship-legend" aria-label={t('Highlight relationships','突出显示构成关系')}>
     {(['all','vine','flowers','supports'] as Role[]).map((r,i)=><button key={r} aria-pressed={role===r} onClick={()=>setRole(role===r?'all':r)}>{i>0&&<i style={{background:['','var(--curve-vine)','var(--curve-flower)','var(--curve-support)'][i]}}/>}{[t('All relationships','全部关系'),t('Main vine','主藤'),t('Flower sites','花位'),t('Flower-bearing paths','承花路径')][i]}</button>)}
     
    </div>
    <div className={`family-diagrams family-count-${selected.prototypes.length}`}>
     {selected.prototypes.map(id=>{const diagram=diagrams.find(d=>d.prototype===id);return <article key={id} className="prototype-reading"><div className="prototype-reading-title"><h4>{displayCatalogId(id)}</h4><span>{captions[id][zh?1:0]}</span></div>{diagram?<RelationshipDiagram data={diagram} role={role} zh={zh}/>:<p className="diagram-status">{error?t('Diagram could not load. Please refresh.','图示未能载入，请刷新页面。'):t('Loading diagram…','正在载入图示…')}</p>}<button className="text-button" disabled={busy} onClick={()=>onPrototype(id)}>{t('Open in studio','在工作台打开')}<ArrowRight size={15}/></button></article>})}
    </div>
    <p className="classification-caption">{t('SW1 through SW3 mark the three types. The letters distinguish the six prototypes. The drawings trace the vine, flower sites and flower-bearing paths.','SW1 至 SW3 对应三类构成，字母区分六个原型。线稿标出主藤、花位和承花路径。')}</p>
   </div>
  </section>

  <section className="heritage-use" aria-labelledby="reuse-title">
   <div className="research-section-heading"><h2 id="reuse-title">{t('Research materials and digital collection','研究资料与数字图集')}</h2>
    <p>{t('The six prototypes draw on 121 annotated patterns, each linked to its source image. The annotations record the main vine, the flower connections and the attachment of each branch.','六个原型以 121 份纹样标注为依据，每份均保留与来源图像的对应记录。标注记下主藤、花位的连接方式和分枝的挂接关系。')}</p>
    <p>{t('The Atlas contains 1,128 generated compositions, 500 of them paired with blue-and-white patterns. Each structure retains editable curves and their connections, so the same drawing can support comparison, redesign or image generation.','图集收录 1,128 份生成结构，其中 500 份配有青花纹样。结构线稿保留可编辑的曲线与连接关系，供比较构图、调整纹样或生成新外观时参照。')}</p>
   </div>
   <div className="research-resource-row"><div><strong>1,128</strong><span>{t('generated structures','份生成结构')}</span></div><div><strong>500</strong><span>{t('paired patterns','组青花纹样与结构线稿')}</span></div><p>{t('Download editable SVGs, geometry data and composition parameters.','可下载矢量结构、几何数据和构图参数。')}</p><button className="secondary" onClick={onGallery}>{t('Browse the paired collection','浏览配对图集')}<ArrowRight size={16}/></button></div>
  </section>
 </div>;
}
