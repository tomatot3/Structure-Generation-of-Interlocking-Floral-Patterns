const projectId=new URLSearchParams(location.search).get('project'),API='/api/v1/appearance/projects/'+encodeURIComponent(projectId),dataFile=p=>API+'/data/'+p;let canvasHeight=724;
const $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';let scene,project,edits={},selected='branch2',mode='edit',history=[],future=[],draftGuides={},brushes=[],payload,drag=null,stroke=null,request=0,previewTimer=0,previewController=null,lastShown={};
async function api(path,data){$('status').textContent='处理中…';const r=await fetch(API+'/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});if(!r.ok){let e=await r.json();throw Error(e.error||e.detail||'操作失败');}return r;}
function toast(t){$('toast').textContent=t;$('toast').style.display='block';setTimeout(()=>$('toast').style.display='none',2500);}
function fail(e){$('status').textContent='操作未完成';toast(e.message);}
function remember(){history.push(JSON.stringify(edits));future=[];updateHistory();}
function updateHistory(){$('undo').disabled=!history.length;$('redo').disabled=!future.length;}
function cancelCurrentPreview(){request++;clearTimeout(previewTimer);if(previewController)previewController.abort();}
async function refresh(override){cancelCurrentPreview();const id=request,sent=structuredClone(override||(mode==='recover'?{}:edits));$('status').textContent='更新矢量…';previewTimer=setTimeout(async()=>{try{previewController=new AbortController();const r=await fetch(API+'/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({edits:sent,previous:lastShown}),signal:previewController.signal});if(!r.ok)throw Error((await r.json()).error);const p=await r.json();if(id===request){display(p);lastShown=sent;}}catch(e){if(e.name!=='AbortError')fail(e);}},60);}
// The editable sources keep their IDs and their full, uncut geometry. Every
// consumer shows the same clipped periodic instances of those sources.
const PeriodicSvg=(()=>{
 const width=695;let serial=0;
 function shifts(left,right){const result=[];for(let k=Math.floor(-right/width)+1;k<=Math.ceil((width-left)/width)-1;k++)if(k)result.push(k);return result;}
 function mount(svg){
  const sources=[...svg.querySelectorAll('g[data-role]')],by=new Map(sources.map(g=>[g.id,g]));
  const ordered=(project?.objects||[]).map(o=>by.get(o.id)).filter(Boolean);for(const g of sources)if(!ordered.includes(g))ordered.push(g);
  // Detach only material groups; retain all original definitions and backgrounds.
  for(const g of sources)g.remove();svg.querySelector('[data-periodic-unit]')?.remove();
  let defs=[...svg.children].find(n=>n.localName==='defs');if(!defs){defs=el('defs',{});svg.prepend(defs);}
  let clip=defs.querySelector('[data-periodic-clip]');if(!clip){clip=el('clipPath',{id:'appearance-period-clip','data-periodic-clip':'',clipPathUnits:'userSpaceOnUse'});defs.appendChild(clip);}
  clip.replaceChildren(el('rect',{x:0,y:0,width,height:canvasHeight}));
  const unit=el('g',{'data-periodic-unit':''});svg.appendChild(unit);
  const wrappers=new Map();ordered.forEach((g,i)=>{
   g.dataset.object=g.id;
   const wrapper=el('g',{id:'appearance-period-object-'+i,'data-periodic-object':g.id,'clip-path':'url(#'+clip.id+')'});
   wrapper.appendChild(g);unit.appendChild(wrapper);wrappers.set(g.id,wrapper);
   const b=g.getBBox();for(const k of shifts(b.x,b.x+b.width))wrapper.appendChild(el('use',{href:'#'+g.id,x:k*width,'data-object':g.id,'data-periodic-copy':k}));
   wrapper.onclick=e=>{e.stopPropagation();select(g.id);};
  });
  // Match the portable SVG's editable parent groups and their painting order.
  const grouped=new Set();function bundle(id,group){grouped.add(id);group.appendChild(wrappers.get(id));for(const child of project?.objects||[])if(child.parent===id&&wrappers.has(child.id)&&!grouped.has(child.id)){const nested=el('g',{'data-object-group':child.id});group.appendChild(nested);bundle(child.id,nested);}}
  for(const o of project?.objects||[])if(o.role==='parent'&&wrappers.has(o.id)&&!grouped.has(o.id)){const group=el('g',{'data-object-group':o.id});wrappers.get(o.id).before(group);bundle(o.id,group);}
  return unit;
 }
 function objects(svg){return [...svg.querySelectorAll('[data-periodic-object]')];}
 function instances(svg,count){
  const groups=[];for(let i=0;i<count;i++){const group=el('g',{transform:'translate('+(i*width)+',0)'});for(const source of objects(svg))group.appendChild(el('use',{href:'#'+source.id,'data-object':source.dataset.periodicObject}));groups.push(group);}return groups;
 }
 function namespace(svg,prefix){
  const names=new Map([...svg.querySelectorAll('[id]')].map(n=>[n.id,prefix+n.id]));
  for(const n of [svg,...svg.querySelectorAll('*')])for(const a of [...n.attributes]){
   if(a.name==='id'&&names.has(a.value))n.setAttribute(a.name,names.get(a.value));
   else if((a.localName==='href')&&a.value.startsWith('#')&&names.has(a.value.slice(1)))n.setAttributeNS(a.namespaceURI,a.name,'#'+names.get(a.value.slice(1)));
   else if(a.value.includes('url('))n.setAttributeNS(a.namespaceURI,a.name,a.value.replace(/url\(\s*(['"]?)#([^\s)'";]+)\1\s*\)/g,(match,quote,id)=>names.has(id)?'url(#'+names.get(id)+')':match));
  }
  return svg;
 }
 function standalone(count=1,prefix='appearance-copy-'+(++serial)+'-'){
  const n=$('art').firstElementChild.cloneNode(true);n.removeAttribute('id');
  for(const g of n.querySelectorAll('g[data-role]')){g.removeAttribute('class');g.removeAttribute('style');}
  namespace(n,prefix);
  const extra=instances(n,count).slice(1);n.append(...extra);
  n.setAttribute('viewBox','0 0 '+width*count+' '+canvasHeight);n.setAttribute('width',width*count);n.setAttribute('height',canvasHeight);
  return n;
 }
 return {width,shifts,mount,objects,instances,namespace,standalone};
})();
function cleanArt(){return PeriodicSvg.standalone().outerHTML;}
function repeatSvg(){return PeriodicSvg.standalone(3).outerHTML;}
function showRepeat(){const source=$('art').firstElementChild;if(!source)return;const count=typeof designSettings==='undefined'?3:designSettings.repeats,svg=el('svg',{viewBox:'0 0 '+(695*count)+' '+canvasHeight});svg.append(el('rect',{width:'100%',height:'100%',fill:'white'}),...PeriodicSvg.instances(source,count));svg.onclick=e=>{const id=e.target.closest('[data-object]')?.dataset.object;if(id)select(id);};$('repeat').replaceChildren(svg);}
function display(p){WarpPreview.stop();payload=p;project=p.project;lastShown=structuredClone(p.project.edits||{});if(p.edits)edits=structuredClone(p.edits);if(p.scene){scene=p.scene;canvasHeight=scene.height;$('overlay').setAttribute('viewBox','0 0 695 '+canvasHeight);$('stage').style.aspectRatio='695/'+canvasHeight;$('guideView').style.aspectRatio='695/'+canvasHeight;draftGuides={};brushes=scene.corrections||[];}
 if(p.art)$('art').innerHTML=p.art;else{const svg=$('art').firstElementChild;for(const id of p.removed||[])svg.querySelector('g[id="'+id+'"]')?.remove();for(const [id,html] of Object.entries(p.patch||{})){const doc=new DOMParser().parseFromString('<svg xmlns="'+NS+'">'+html+'</svg>','image/svg+xml'),g=document.importNode(doc.documentElement.firstElementChild,true),old=svg.querySelector('g[id="'+id+'"]');if(old)old.replaceWith(g);else svg.appendChild(g);}}PeriodicSvg.mount($('art').firstElementChild);showRepeat();$('guideView').innerHTML=p.guide;$('prompt').textContent=p.prompt;
 for(const g of $('art').querySelectorAll('g[data-role]')){g.classList.toggle('selected-object',selectionIds().has(g.id));g.onclick=e=>{e.stopPropagation();select(g.id);};}
 for(const g of $('guideView').querySelectorAll('[data-object]')){g.style.cursor='pointer';g.onclick=()=>select(g.dataset.object);}
 if(!obj())selected=objects()[0]?.id;buildList();controls();overlay();workflowDisplay(p);syncStructureView();syncSelectionHighlights();$('status').textContent=p.warnings?.length?p.warnings.join('；'):(mode==='recover'?'原图归属校正 · 设计修改保留':'');
}
function objects(){return (project?.objects||[]).filter(o=>!o.merged_into);}
function obj(id=selected){return objects().find(o=>o.id===id);}
function buildList(){const root=$('objects');root.replaceChildren();const ordered=[];
 for(const o of objects()){if(['child','ornament'].includes(o.role))continue;ordered.push(o);for(const child of objects().filter(c=>c.parent===o.id&&['child','ornament'].includes(c.role)))ordered.push(child);}
 for(const o of ordered){const b=document.createElement('button');b.textContent=o.name;b.dataset.id=o.id;b.className=[o.parent&&['child','ornament'].includes(o.role)?'child':'',o.id===selected?'selected':'',o.hidden?'removed':''].join(' ');b.onclick=()=>select(o.id);root.appendChild(b);}}
function select(id){selected=id;$('recoverObject').value=id;buildList();controls();overlay();syncSelectionHighlights();}
function syncStructureView(){const paired=mode==='edit'&&$('structure').checked;$('guideBoard').hidden=!((mode==='plan'&&scene?.appearance_ready!==false)||paired);document.querySelector('.canvases').classList.toggle('paired-view',paired);}
function syncSelectionHighlights(){
 const ids=selectionIds();for(const g of $('art').querySelectorAll('g[data-role]'))g.classList.toggle('selected-object',ids.has(g.id));
 for(const p of $('guideView').querySelectorAll('[data-object]')){p.setAttribute('stroke-width',ids.has(p.dataset.object)?'5':'2');p.style.opacity=ids.has(p.dataset.object)?'1':'.5';}
 const o=obj(),name=o?o.name+(o.role==='parent'&&ids.size>1?'及其子枝':''):'';
 $('guideTitle').textContent=mode==='edit'&&$('structure').checked?'结构 · '+name:'结构';
 if(mode==='edit')$('artTitle').textContent=$('structure').checked?'外观 · '+name:'设计';
}

function selectionIds(){const ids=new Set([selected]);if(mode!=='recover'&&obj()?.role==='parent'){let changed=true;while(changed){changed=false;for(const o of objects())if(ids.has(o.parent)&&!ids.has(o.id)){ids.add(o.id);changed=true;}}}return ids;}
function controls(){const o=obj();if(!o)return;$('selectedTitle').textContent=o.name;$('flowerControls').hidden=o.role!=='flower';$('leafControls').hidden=o.role!=='ornament';$('branchControls').hidden=!['parent','child','ornament'].includes(o.role);$('delete').textContent=o.role==='parent'?'移除整个枝组':'移除'+o.name;$('restore').disabled=!o.hidden;$('delete').disabled=o.hidden;const e=edits[selected]||{};$('leafScale').value=Math.round((e.scale||1)*100);$('leafScaleLabel').textContent=$('leafScale').value+'%';$('flowerScale').value=Math.round((e.scale||1)*100);$('scaleLabel').textContent=$('flowerScale').value+'%';$('flowerAsset').value=e.replacement||'';$('leafAsset').value=e.replacement||'';$('unlockFlower').checked=!!e.unlocked;
 $('editHelp').textContent=o.role==='unassigned'?'该部分暂未确定结构归属，可在分组中重新指定。':o.role==='main'||o.role==='support'?'花藤受保护。修改花位时，承花路径随接合点调整。':o.role==='flower'?'替换或缩放花头；勾选调整花位后拖动中心点。':o.role==='parent'?'整条分枝的控制柄同时显示。拖根点沿主藤换挂接位置，拖枝尖调长度和走势；子枝跟随。':o.role==='child'?'拖控制柄调整整条子枝；根点沿父枝移动，枝尖可直接拖动。':'拖控制柄调整叶饰走势；根点沿主藤移动。';}
function points(o){return mode==='recover'?(draftGuides[o.id]||o.alignment_guide||o.registered_guide||o.guide):o.guide;}
function el(tag,attrs){let n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;}
function overlay(){const root=$('overlay');root.replaceChildren();if(!project)return;const o=obj();if(!o)return;if(mode==='recover'){const original=$('art').querySelector('g[id="'+selected+'"]');if(original){const shade=original.cloneNode(true);shade.removeAttribute('id');shade.setAttribute('opacity','.4');for(const p of shade.querySelectorAll('path'))p.setAttribute('fill','#e5a339');root.appendChild(shade);}}if(mode==='recover')for(const b of selectionStrokes)root.appendChild(el('path',{d:'M'+b.points.map(v=>v.join(',')).join('L'),fill:'none',stroke:'#efad46','stroke-width':b.size,opacity:.35}));if(mode==='recover'&&(!$('alignmentTools').open||$('brush').checked))return;const show=mode==='recover'||($('structure').checked&&mode!=='edit');
 if(show){for(const a of objects()){const p=points(a);root.appendChild(el('path',{d:'M'+p.map(v=>v.join(',')).join('L'),fill:'none',stroke:a.id===selected?'#245e93':'#91a9bd','stroke-width':a.id===selected?2.5:1,'stroke-dasharray':'4 4',opacity:a.id===selected?1:.6}));}}
 const seamEdit=mode==='deliver'&&o.id==='vine'&&edits.vine?.unlocked;
 if(mode!=='edit'&&mode!=='recover'&&!seamEdit)return;
 let p=points(o),allowed=seamEdit||mode==='recover'||['parent','child','ornament'].includes(o.role)||(o.role==='flower'&&edits[o.id]?.unlocked);
 if(!allowed||o.hidden)return;if(mode==='edit'&&['parent','child','ornament'].includes(o.role)){CurveControls.draw(root,o);return;}
 root.appendChild(el('path',{d:'M'+p.map(v=>v.join(',')).join('L'),fill:'none',stroke:'#4077a4','stroke-width':1.4}));
 p.forEach((v,i)=>{if(o.role==='flower'&&i>0)return;if(seamEdit&&![0,1,p.length-2,p.length-1].includes(i))return;const fixed=mode==='edit'&&i<2&&o.role!=='flower';const c=el('circle',{cx:v[0],cy:v[1],r:fixed?4:6,class:'handle'+(fixed?' fixed':''),'data-point':i});root.appendChild(c);if(!fixed)c.onpointerdown=e=>{if(mode==='recover'&&$('brush').checked)return;e.stopPropagation();e.preventDefault();if(mode!=='recover')remember();drag={id:o.id,index:i,points:structuredClone(p),start:v,flower:o.role==='flower',seam:seamEdit};c.setPointerCapture(e.pointerId);c.onpointermove=move;c.onpointerup=finishDrag;};if(!fixed){c.setAttribute('tabindex','0');c.setAttribute('role','slider');c.setAttribute('aria-label',o.name+'控制点'+(i+1));c.setAttribute('aria-valuetext',v.map(x=>Math.round(x)).join(', '));c.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();if(mode!=='recover')remember();drag={id:o.id,index:i,points:structuredClone(p),start:v,flower:o.role==='flower',seam:seamEdit};const step=e.shiftKey?10:2,q=[v[0]+(e.key==='ArrowRight'?step:e.key==='ArrowLeft'?-step:0),v[1]+(e.key==='ArrowDown'?step:e.key==='ArrowUp'?-step:0)];updatePoint(q);finishDrag();};}});

}
function coords(e){const svg=$('overlay'),p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const q=p.matrixTransform(svg.getScreenCTM().inverse());return [Math.max(-20,Math.min(715,q.x)),Math.max(0,Math.min(canvasHeight,q.y))];}
function updatePoint(p){const previous=drag.points[drag.index];drag.points[drag.index]=p;if(drag.flower)drag.points[1]=[p[0]+1,p[1]];if(drag.seam){const q=drag.points,n=q.length;if(drag.index===0){q[n-1]=[p[0]+695,p[1]];q[1]=[q[1][0]+p[0]-previous[0],q[1][1]+p[1]-previous[1]];q[n-2]=[q[n-1][0]-(q[1][0]-p[0]),q[n-1][1]-(q[1][1]-p[1])];}if(drag.index===n-1){q[0]=[p[0]-695,p[1]];q[n-2]=[q[n-2][0]+p[0]-previous[0],q[n-2][1]+p[1]-previous[1]];q[1]=[q[0][0]+p[0]-q[n-2][0],q[0][1]+p[1]-q[n-2][1]];}if(drag.index===1)q[n-2]=[q[n-1][0]-(p[0]-q[0][0]),q[n-1][1]-(p[1]-q[0][1])];if(drag.index===n-2)q[1]=[q[0][0]+(q[n-1][0]-p[0]),q[0][1]+(q[n-1][1]-p[1])];}}
function move(e){if(!drag)return;const p=coords(e);updatePoint(p);e.currentTarget.setAttribute('cx',p[0]);e.currentTarget.setAttribute('cy',p[1]);}
function finishDrag(e){if(!drag)return;const d=drag;drag=null;if(mode==='recover'){draftGuides[d.id]=d.points;overlay();$('status').textContent='校准尚未应用';}else{edits[d.id]={...(edits[d.id]||{}),points:d.points};if(d.flower||d.seam)edits[d.id].unlocked=true;refresh();}}
$('stage').addEventListener('pointerdown',e=>{if(mode!=='recover'||!$('brush').checked)return;e.preventDefault();stroke={object:selected,size:Number($('brushSize').value),points:[coords(e)]};$('stage').setPointerCapture(e.pointerId);});
$('stage').addEventListener('pointermove',e=>{if(!stroke)return;stroke.points.push(coords(e));const o=$('overlay');let p=o.querySelector('.live-brush');if(!p){p=el('path',{class:'live-brush',fill:'none',stroke:'#edb34c','stroke-width':stroke.size,opacity:.4});o.appendChild(p);}p.setAttribute('d','M'+stroke.points.map(v=>v.join(',')).join('L'));});
$('stage').addEventListener('pointerup',()=>{if(stroke){selectionStrokes.push(stroke);stroke=null;overlay();$('selectionNote').textContent='已涂选 '+selectionStrokes.length+' 笔';}});
function setMode(m){mode=m;document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.mode===m));for(const a of ['plan','recover','edit','deliver'])$(a+'Panel').hidden=a!==m;$('objectPanel').hidden=m!=='edit';document.body.dataset.mode=m;syncStructureView();$('repeat').hidden=m==='recover'||m==='plan';$('raster').hidden=m!=='recover';$('art').style.opacity=m==='recover'?'0':'1';$('art').style.pointerEvents=m==='recover'?'none':'auto';$('artTitle').textContent=m==='recover'?'结构辅助分组':m==='plan'?(scene?.appearance_ready===false?'结构底稿':'当前外观'):'设计';overlay();}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>{setMode(b.dataset.mode);refresh(b.dataset.mode==='recover'?{}:undefined);});$('structure').onchange=()=>{syncStructureView();syncSelectionHighlights();overlay();};
$('delete').onclick=()=>{remember();edits[selected]={...(edits[selected]||{}),hidden:true};refresh();};$('restore').onclick=()=>{remember();edits[selected]={...(edits[selected]||{}),hidden:false};let p=obj().parent;while(p){edits[p]={...(edits[p]||{}),hidden:false};p=obj(p)?.parent;}refresh();};
$('leafScale').onchange=()=>{remember();edits[selected]={...(edits[selected]||{}),scale:Number($('leafScale').value)/100};refresh();};$('leafScale').oninput=()=>{$('leafScaleLabel').textContent=$('leafScale').value+'%';};
$('flowerScale').onchange=()=>{remember();edits[selected]={...(edits[selected]||{}),scale:Number($('flowerScale').value)/100};refresh();};$('flowerScale').oninput=()=>{$('scaleLabel').textContent=$('flowerScale').value+'%';};
for(const id of ['flowerAsset','leafAsset'])$(id).onchange=()=>{remember();edits[selected]={...(edits[selected]||{}),replacement:$(id).value};refresh();};
$('unlockFlower').onchange=()=>{remember();edits[selected]={...(edits[selected]||{}),unlocked:$('unlockFlower').checked};controls();overlay();};
$('undo').onclick=()=>{if(!history.length)return;future.push(JSON.stringify(edits));edits=JSON.parse(history.pop());updateHistory();refresh();};$('redo').onclick=()=>{if(!future.length)return;history.push(JSON.stringify(edits));edits=JSON.parse(future.pop());updateHistory();refresh();};$('reset').onclick=()=>{remember();edits={};refresh();};
$('recover').onclick=async()=>{try{cancelCurrentPreview();const r=await (await api('recover',{edits,settings:designSettings,guides:draftGuides,corrections:brushes})).json();history=[];future=[];display(r);updateHistory();toast('分组已更新，现有设计修改保留');}catch(e){fail(e);}};$('clearBrush').onclick=()=>{selectionStrokes=[];overlay();$('selectionNote').textContent='涂选要重新归属的部分';};
function download(blob,name){const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),10000);toast('已导出 '+name);}
async function file(path,body,name){try{const r=await api(path,body);download(await r.blob(),name);$('status').textContent='';}catch(e){fail(e);}}
$('condition').onclick=()=>file('condition',{edits,style:$('style').value},'渲染条件.zip');$('export').onclick=()=>file('export',{edits,settings:designSettings},'可编辑设计.zip');$('save').onclick=()=>file('save',{edits,settings:designSettings},'设计项目.json');
$('downloadSvg').onclick=()=>file('svg',{edits,settings:designSettings},'设计.svg');$('downloadRepeat').onclick=()=>file('repeat',{edits,settings:designSettings},'连续边饰.svg');
$('seam').onclick=()=>{edits.vine={...(edits.vine||{}),unlocked:!edits.vine?.unlocked};selected='vine';$('seam').textContent=edits.vine.unlocked?'结束接缝调整':'调整重复接缝';overlay();};
$('downloadPng').onclick=async()=>{const response=await api('svg',{edits,settings:designSettings});const u=URL.createObjectURL(await response.blob()),im=new Image();$('status').textContent='';im.onload=()=>{const c=document.createElement('canvas');c.width=1390;c.height=canvasHeight*2;c.getContext('2d').drawImage(im,0,0,c.width,c.height);c.toBlob(b=>download(b,'设计预览.png'),'image/png');URL.revokeObjectURL(u);};im.src=u;};
$('loadProject').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;const p=JSON.parse(await f.text());const r=await (await api('restore',{project:p})).json();edits=r.edits||p.edits||{};designSettings={...designSettings,...(r.settings||p.settings||{})};history=[];future=[];display(r);$('raster').src=dataFile('render.png')+'?t='+Date.now();updateHistory();toast('已恢复项目');}catch(err){fail(err);}e.target.value='';};
$('imageInput').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;const buf=new Uint8Array(await f.arrayBuffer());let binary='';for(let i=0;i<buf.length;i+=8192)binary+=String.fromCharCode(...buf.subarray(i,i+8192));const r=await (await api('import',{image:btoa(binary),edits,settings:designSettings,filename:f.name,generation_note:$('generationNote').value,render_input_id:$('renderInputVersion').value})).json();edits={};history=[];future=[];display(r);$('raster').src=dataFile('render.png')+'?t='+Date.now();setMode('recover');toast('已导入，请核对结构配准与归属');}catch(err){fail(err);}e.target.value='';};
fetch(API+'/state').then(r=>r.json()).then(p=>{scene=p.scene;display(p);$('raster').src=dataFile('render.png');setMode(scene.appearance_ready===false?'plan':mode);if(mode==='recover')refresh({});updateHistory();}).catch(fail);
