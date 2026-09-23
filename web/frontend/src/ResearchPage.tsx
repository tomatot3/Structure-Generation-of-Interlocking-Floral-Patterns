import {useEffect,useState} from 'react';
import {ArrowRight} from 'lucide-react';
import './research.css';

type Point=[number,number];
type Diagram={prototype:string;asset_id:string;pair_id:string;backbone:Point[];flowers:{center:Point;rx:number;ry:number}[];supports:Point[][]};
type Role='all'|'vine'|'flowers'|'supports';
const families=[
  {id:'SW1',name:['Crest–trough','波峰波谷型'],short:['Flowers at peaks and troughs','花位与峰谷对应'],
   description:['Flower sites follow the peaks and troughs of the main vine. Flower-bearing paths extend from these points or their flanks.','花位通常与主藤的波峰、波谷相对应，承花路径从峰谷或相应侧翼引出。'],
   distinction:['A and B both have two flower sites. Main-vine amplitude, period and phase give them different rhythms. In C, the main vine and flower-bearing paths alternate around the two flower sites.','A、B均为双花配置，通过主藤振幅、周期与相位形成不同节奏；C由主藤与承花路径在两个花位周围交替展开。'],
   prototypes:['SW1-A','SW1-B','SW1-C']},
  {id:'SW2',name:['Axial flower-passing','轴心穿花型'],short:['The vine passes through flower sites','主藤穿花接续'],
   description:['The flower sits within the region traversed by the main vine. Vine segments continue across the flower site without a separate flower-bearing path.','花位占据主藤连续行进的区域，主藤跨越花位接续，不另设独立的承花路径。'],
   distinction:['SW2-A has one flower site per repeat. Visible vine segments outside the petals provide evidence for continuity; the hidden connection within the flower is recorded as inferred.','SW2-A在一个重复单元中设置一个花位。来源图中花外可见的枝段提供接续依据，花瓣遮挡范围内的连接按推定记录。'],
   prototypes:['SW2-A']},
  {id:'SW3',name:['Tangential flower-bearing','切向承花型'],short:['Flowers on tangential paths','切向引枝承花'],
   description:['A flower-bearing path leaves along the local direction of the main vine, then turns toward a flower. Flower sites do not have a fixed correspondence to peaks or troughs.','承花路径沿主藤局部方向切向引出，再转向连接花位。花位不固定对应主藤的波峰或波谷。'],
   distinction:['SW3-A has one flower site per repeat; SW3-B has two.','SW3-A采用单花配置，SW3-B采用双花配置。'],
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
   <polyline points={line(data.backbone)} fill="none" stroke="#244880" strokeWidth="3" vectorEffect="non-scaling-stroke" opacity={opacity('vine')}/>
   <g opacity={opacity('supports')} stroke="#708166" fill="none" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
    {data.supports.map((p,i)=><polyline key={i} points={line(p)} vectorEffect="non-scaling-stroke"/>)}</g>
   <g opacity={opacity('flowers')} fill="#b3616310" stroke="#b36163" strokeWidth="1.8">
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
 return <div className="heritage-page">
  <section className="heritage-lead" aria-labelledby="heritage-title">
   <div className="heritage-story">
    
    <h2 id="heritage-title">{t('Flowers along a continuous vine','连续花藤中的构图关系')}</h2>
    <p>{t('In floral scroll ornament, a continuous vine links flowers and leaves into a repeating composition. Flower shapes may differ while their arrangement remains similar. Curves that look alike may also serve different purposes: one carries a flower, while another forms a side branch.','缠枝纹以绵延的茎蔓连缀花叶，在反复延伸中形成连续的构图。花叶造型不同的纹样，可能有相近的花藤安排；外形相似的曲线，也可能分别承担承花和分枝的作用。理解这些关系，有助于比较传统纹样的构成。')}</p>
    <p>{t('Pattern books and compositional studies preserve these designs mainly as plates and text. Editable files are harder to obtain, and images alone do not explicitly record each branch’s role or connection. This project records those relationships alongside the curves, making them available for structural study and new designs.','图录与构成研究多以图版和文字保存这些资料，可编辑文件不易获取，枝条的作用与连接也没有在图像中被单独记录。本项目将这些关系与曲线一同整理，让来源纹样中的构成线索得以保留，并成为结构分析与再设计的材料。')}</p>
   </div>
   <figure className="heritage-pair">
    <div className="heritage-structure-strip"><img src="/media/pairs/structures/sw1-C-01.png" alt={t('Structural reference for sw1-C-01','sw1-C-01结构参照')}/></div>
    <img className="heritage-render" src="/media/pairs/renderings/sw1-C-01.png" alt={t('Appearance generated from the structural reference','基于结构参照生成的外观图')}/>
    <figcaption><span>{t('FROM STRUCTURE TO APPEARANCE','从结构到外观')}</span>{t('Generated example','生成示例')} · sw1-C-01</figcaption>
   </figure>
  </section>

  <section className="sw-section" aria-labelledby="sw-title">
   <div className="research-section-heading"><h2 id="sw-title">{t('Three flower–vine configurations','三类花藤配置')}</h2>
    <p>{t('The study focuses on single-wave floral scrolls (SW), in which flowers and branches follow one undulating main vine. Three configurations are distinguished by flower position and the paths connecting flowers to the vine.','本研究关注单波形缠枝纹（single-wave，简称SW）：花位与分枝围绕一条波状主藤展开，沿一个方向连续重复。依据花位分布和花藤连接方式，分为以下三类。')}</p>
   </div>
   <div className="classification-criteria">
    {[[t('Flower position','花位分布'),t('The flower’s position relative to the course of the main vine.','花位相对主藤峰谷与行进区域的位置。')],[t('Connection origin','连接起点'),t('The presence and origin of a separate flower-bearing path.','独立承花路径的有无及其引出位置。')],[t('Path to the flower','路径走向'),t('A vine passing through the flower, or a path turning toward it.','主藤穿花接续，或由承花路径转向连接。')]].map(([h,p],i)=><div key={h}><span>0{i+1}</span><div><h3>{h}</h3><p>{p}</p></div></div>)}
   </div>
   <div className="family-tabs" role="tablist" aria-label={t('Structural families','结构分类')}>
    {families.map(f=><button key={f.id} role="tab" id={`tab-${f.id}`} aria-controls="family-panel" aria-selected={family===f.id} onClick={()=>{setFamily(f.id);setRole('all')}}><strong>{f.id}</strong><span>{f.name[zh?1:0]}<small>{f.short[zh?1:0]}</small></span></button>)}
   </div>
   <div className="family-panel" id="family-panel" role="tabpanel" aria-labelledby={`tab-${family}`}>
    <div className="family-description"><div><h3>{selected.name[zh?1:0]}</h3><p>{selected.description[zh?1:0]}</p></div><p>{selected.distinction[zh?1:0]}</p></div>
    <div className="relationship-legend" aria-label={t('Highlight relationships','突出显示构成关系')}>
     {(['all','vine','flowers','supports'] as Role[]).map((r,i)=><button key={r} aria-pressed={role===r} onClick={()=>setRole(role===r?'all':r)}>{i>0&&<i style={{background:['','#244880','#b36163','#708166'][i]}}/>}{[t('All relationships','全部关系'),t('Main vine','主藤'),t('Flower sites','花位'),t('Flower-bearing paths','承花路径')][i]}</button>)}
     
    </div>
    <div className={`family-diagrams family-count-${selected.prototypes.length}`}>
     {selected.prototypes.map(id=>{const diagram=diagrams.find(d=>d.prototype===id);return <article key={id} className="prototype-reading"><div className="prototype-reading-title"><h4>{id}</h4><span>{captions[id][zh?1:0]}</span></div>{diagram?<RelationshipDiagram data={diagram} role={role} zh={zh}/>:<p className="diagram-status">{error?t('Diagram could not load. Please refresh.','图示未能载入，请刷新页面。'):t('Loading diagram…','正在载入图示…')}</p>}<button className="text-button" disabled={busy} onClick={()=>onPrototype(id)}>{t('Open in studio','在工作台打开')}<ArrowRight size={15}/></button></article>})}
    </div>
    <p className="classification-caption">{t('SW1–SW3 denote the three configurations. A/B/C identify the six prototypes used in this project. Diagrams show the main vine, flower sites and flower-bearing paths.','SW1—SW3为三类配置，A/B/C区分本项目的六个原型。图中保留主藤、花位与承花路径。')}</p>
   </div>
  </section>

  <section className="heritage-use" aria-labelledby="reuse-title">
   <div className="research-section-heading"><h2 id="reuse-title">{t('Research materials and digital collection','研究资料与数字图集')}</h2>
    <p>{t('The research draws on 118 role-annotated examples, each linked to its source image. The annotations distinguish vine paths, flower connections and branch attachments. They provide the basis for the six prototypes and their generated variations.','研究整理了118份角色标注材料，逐一保留与来源图像的对应。标注区分主藤、承花连接与分枝依附，作为六个原型及其生成变化的构成依据。')}</p>
    <p>{t('The collection contains 1,128 generated structures, including 500 paired with appearance renderings. Each structure includes editable curves and connection records. These files can be used to compare compositions, develop new designs or provide references for image generation.','数字图集收录1,128份生成结构，其中500份配有渲染图。结构文件保留可编辑曲线与连接记录，可用于构图比较、纹样再设计，也可作为图像生成的结构参照。')}</p>
   </div>
   <div className="research-resource-row"><div><strong>1,128</strong><span>{t('structural assets','份结构资产')}</span></div><div><strong>500</strong><span>{t('structure–rendering pairs','对结构与渲染图')}</span></div><p>{t('Includes semantic SVGs, geometry data and generation parameters.','附语义SVG、几何数据与生成参数。')}</p><button className="secondary" onClick={onGallery}>{t('Browse the collection','浏览配对图集')}<ArrowRight size={16}/></button></div>
  </section>
 </div>;
}
