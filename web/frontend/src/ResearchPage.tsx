import {useEffect,useState} from 'react';
import {ArrowRight,BookOpen,GitBranch,Layers} from 'lucide-react';
import './research.css';

type Point=[number,number];
type Diagram={prototype:string;asset_id:string;pair_id:string;backbone:Point[];flowers:{center:Point;rx:number;ry:number}[];supports:Point[][]};
type Role='all'|'vine'|'flowers'|'supports';
const families=[
  {id:'SW1',name:['Crest–trough','波峰波谷型'],short:['Flower sites relate to peaks and troughs','看花位与峰谷的对应'],
   description:['Flower placement follows the peaks and troughs of the main vine. Flower-bearing paths emerge from a peak, a trough or the corresponding flank. The complete paths explain how each flower is supported.','花位通常与主藤的波峰、波谷相对应。承花路径从峰谷或相应侧翼引出，结合整段路径看花朵怎样被承托。'],
   distinction:['A and B both have two flower sites. Main-vine amplitude, period and phase give them different rhythms. In C, the main vine and flower-bearing paths alternate around the two flower sites.','A、B均为双花配置，通过主藤振幅、周期与相位形成不同节奏；C由主藤与承花路径在两个花位周围交替展开。'],
   prototypes:['SW1-A','SW1-B','SW1-C']},
  {id:'SW2',name:['Axial flower-passing','轴心穿花型'],short:['The main vine continues through flower sites','看主藤是否穿过花位'],
   description:['The flower sits within the region traversed by the main vine. Vine segments continue across the flower site without a separate flower-bearing path.','花位占据主藤连续行进的区域，主藤跨越花位接续，不另设独立的承花路径。'],
   distinction:['SW2-A has one flower site per repeat. Visible vine segments outside the petals provide evidence for continuity; the hidden connection within the flower is recorded as inferred.','SW2-A在一个重复单元中设置一个花位。来源图中花外可见的枝段提供接续依据，花瓣遮挡范围内的连接按推定记录。'],
   prototypes:['SW2-A']},
  {id:'SW3',name:['Tangential flower-bearing','切向承花型'],short:['A path leaves the vine, then turns toward a flower','看承花路径的引出与转向'],
   description:['A flower-bearing path leaves along the local direction of the main vine, then turns toward a flower. Flower sites do not have a fixed correspondence to peaks or troughs.','承花路径沿主藤局部方向切向引出，再转向连接花位。花位不固定对应主藤的波峰或波谷。'],
   distinction:['SW3-A has one flower site per repeat; SW3-B has two. Compare the path origin, its turn and the final flower position together.','SW3-A采用单花配置，SW3-B采用双花配置。识别时将路径起点、转向和末端花位放在一起观察。'],
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
    <p className="eyebrow">{t('CULTURAL KNOWLEDGE · DIGITAL RECORDS','构图知识 · 数字记录')}</p>
    <h2 id="heritage-title">{t('Record how the ornament is composed.','记录纹样如何被组织起来。')}</h2>
    <p>{t('A floral scroll connects flowers and leaves through a continuous vine. Its composition includes the rhythm of the vine, the positions of flowers, the paths that carry them and the way branches attach. These relationships are part of the ornament’s cultural knowledge.','缠枝纹以连续的茎蔓连缀花叶。主藤怎样起伏、花位怎样排列、花朵经由什么路径连接、普通分枝怎样依附，共同构成纹样的组织方式，也是值得保存的文化知识。')}</p>
    <p>{t('Pattern books and compositional studies preserve rich visual material. Editable digital resources are harder to access, and roles and connections still need explicit records. This project links source images to geometry, compositional roles and attachments, so the studied relationships can be compared, edited and reused.','图录与构成研究积累了丰富资料，但可编辑数字资源不易获取，图像中的角色与连接关系也需要显式记录。本项目保留来源图像与结构标注的对应，将几何、构成作用和挂接关系一起记录，使所研究的构图关系能够用于比较、编辑和再利用。')}</p>
   </div>
   <figure className="heritage-pair">
    <div className="heritage-structure-strip"><img src="/media/pairs/structures/sw1-C-01.png" alt={t('Structural reference for sw1-C-01','sw1-C-01结构参照')}/></div>
    <img className="heritage-render" src="/media/pairs/renderings/sw1-C-01.png" alt={t('Appearance generated from the structural reference','基于结构参照生成的外观图')}/>
    <figcaption><span>{t('FROM STRUCTURE TO APPEARANCE','从结构到外观')}</span>{t('Generated example','生成示例')} · sw1-C-01</figcaption>
   </figure>
  </section>

  <section className="sw-section" aria-labelledby="sw-title">
   <div className="research-section-heading"><span className="eyebrow">{t('READING THE STRUCTURE','认识结构')}</span><h2 id="sw-title">{t('What does SW mean?','SW是什么，三类怎样区分？')}</h2>
    <p>{t('SW stands for single-wave floral scroll: one continuous, wave-shaped main vine organizes flower sites and branches into a repeating band. The project groups flower–vine configurations by three related observations.','SW是single-wave的缩写，指由一条连续波状主藤组织花位和分枝、沿一个方向重复的单波形缠枝纹。本项目结合三项关系划分花藤配置。')}</p>
   </div>
   <div className="classification-criteria">
    {[[t('Flower position','花位在哪里'),t('How does the flower site relate to the vine’s peaks, troughs or course?','花位与主藤峰谷、连续行进区域是什么关系？')],[t('Connection origin','连接从哪里引出'),t('Does a separate flower-bearing path leave the vine, and where?','是否存在独立承花路径，它从主藤什么位置引出？')],[t('Complete path','路径怎样到达花位'),t('Does the vine pass through the flower site, or does a path turn toward it?','是主藤穿花接续，还是承花路径转向连接花位？')]].map(([h,p],i)=><div key={h}><span>0{i+1}</span><div><h3>{h}</h3><p>{p}</p></div></div>)}
   </div>
   <div className="family-tabs" role="tablist" aria-label={t('Structural families','结构分类')}>
    {families.map(f=><button key={f.id} role="tab" id={`tab-${f.id}`} aria-controls="family-panel" aria-selected={family===f.id} onClick={()=>{setFamily(f.id);setRole('all')}}><strong>{f.id}</strong><span>{f.name[zh?1:0]}<small>{f.short[zh?1:0]}</small></span></button>)}
   </div>
   <div className="family-panel" id="family-panel" role="tabpanel" aria-labelledby={`tab-${family}`}>
    <div className="family-description"><div><h3>{selected.name[zh?1:0]}</h3><p>{selected.description[zh?1:0]}</p></div><p>{selected.distinction[zh?1:0]}</p></div>
    <div className="relationship-legend" aria-label={t('Highlight relationships','突出显示构成关系')}>
     {(['all','vine','flowers','supports'] as Role[]).map((r,i)=><button key={r} aria-pressed={role===r} onClick={()=>setRole(role===r?'all':r)}>{i>0&&<i style={{background:['','#244880','#b36163','#708166'][i]}}/>}{[t('All relationships','全部关系'),t('Main vine','主藤'),t('Flower sites','花位'),t('Flower-bearing paths','承花路径')][i]}</button>)}
     <span>{t('Select a role to highlight it','点击图例，单独查看一类关系')}</span>
    </div>
    <div className={`family-diagrams family-count-${selected.prototypes.length}`}>
     {selected.prototypes.map(id=>{const diagram=diagrams.find(d=>d.prototype===id);return <article key={id} className="prototype-reading"><div className="prototype-reading-title"><h4>{id}</h4><span>{captions[id][zh?1:0]}</span></div>{diagram?<RelationshipDiagram data={diagram} role={role} zh={zh}/>:<p className="diagram-status">{error?t('Diagram could not load. Please refresh.','图示未能载入，请刷新页面。'):t('Loading diagram…','正在载入图示…')}</p>}<button className="text-button" disabled={busy} onClick={()=>onPrototype(id)}>{t('Try this prototype','用这个原型生成')}<ArrowRight size={15}/></button></article>})}
    </div>
    <p className="classification-caption">{t('Diagrams show the main vine, flower sites and flower-bearing paths from archived structural assets. SW1–SW3 name relationship families; A/B/C identify procedural configurations within each family.','图示取自项目结构资产，展示主藤、花位与承花路径。SW1—SW3表示花藤关系的类型，A/B/C表示该类型下的具体程序配置。')}</p>
   </div>
  </section>

  <section className="heritage-use" aria-labelledby="reuse-title">
   <div className="research-section-heading"><span className="eyebrow">{t('UNDERSTAND · RECORD · REUSE','理解 · 记录 · 再利用')}</span><h2 id="reuse-title">{t('What can these digital records support?','这些数字记录可以用来做什么？')}</h2></div>
   <div className="heritage-values">
    {[[BookOpen,t('Read compositional relationships','比较构图关系'),t('Inspect vine continuity and branch attachment. Compare how similar forms can serve different roles, and how different appearances can share a structure.','查看连续走势与分枝依附，比较外形相近的曲线怎样承担不同作用，以及不同外观怎样共享构图关系。')],[GitBranch,t('Keep a traceable structural record','保存可复核的结构'),t('The 118 annotated examples keep links to their source images. Geometry, roles and attachments form a record that can be revisited as interpretations develop.','118份角色标注材料保留来源对应。几何、角色与挂接一同记录，使后续研究可以回到来源复核、补充与修订。')],[Layers,t('Reuse and redesign','开展结构再设计'),t('Vary branch density and counts, edit local curves, and export the result. Paired appearance images provide references for further image-generation research.','调整分枝疏密和数量，编辑局部曲线并导出结果。配对外观图为后续图像生成研究提供对应参照。')]].map(([Icon,h,p]:any)=><article key={h}><Icon size={23}/><h3>{h}</h3><p>{p}</p></article>)}
   </div>
   <div className="research-resource-row"><div><strong>1,128</strong><span>{t('structural assets','份结构资产')}</span></div><div><strong>500</strong><span>{t('structure–rendering pairs','对结构与渲染图')}</span></div><p>{t('Structural assets include semantic SVGs, geometry and generation parameters. Pair identifiers link 500 appearance images to their structural references.','结构附有语义SVG、几何数据与生成参数；配对编号将500份外观图与对应结构关联起来。')}</p><button className="secondary" onClick={onGallery}>{t('Browse the collection','浏览配对图集')}<ArrowRight size={16}/></button></div>
  </section>
 </div>;
}
