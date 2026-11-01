let designSettings={height_mm:50,repeats:3},selectionStrokes=[],renderInputs=[];
function workflowDisplay(p){
 if(p.edits)edits=structuredClone(p.edits);if(p.settings)designSettings={...designSettings,...p.settings};
 $('bandHeight').value=designSettings.height_mm;$('repeatCount').value=designSettings.repeats;updateBand();
 const source=p.project.provenance||{};for(const key of ['source','interpretation','task'])if(document.activeElement!==$(key))$(key).value=source[key]||'';
 const options=objects().filter(o=>!o.merged_into&&o.role!=='unassigned');
 $('recoverObject').replaceChildren(...objects().map(o=>new Option(o.name,o.id)));$('recoverObject').value=selected;
 for(const [id,role,label] of [['flowerAsset','flower','原花头'],['leafAsset','ornament','原叶饰']]){const old=$(id).value;$(id).replaceChildren(new Option(label,''),...options.filter(o=>o.role===role).map(o=>new Option(o.name,o.id)));$(id).value=old;}
 for(const id of ['assignTarget','parentTarget']){const old=$(id).value;const choices=id==='parentTarget'?options.filter(o=>['main','support','parent'].includes(o.role)):options;$(id).replaceChildren(...(id==='parentTarget'?[new Option('不依附其他对象','')]:[]),...choices.map(o=>new Option(o.name,o.id)));if(choices.some(o=>o.id===old))$(id).value=old;else if(id==='assignTarget')$(id).value=selected;}
 showVersions(p.versions||[]);$('selectionNote').textContent=selectionStrokes.length?'已涂选 '+selectionStrokes.length+' 笔':'涂选要重新归属的部分';
 if(p.scene)showRenderInputs(p.scene.render_inputs||[]);
 $('undoRegion').disabled=!(p.project.scene.correction_history||[]).length;
 $('appearanceState').textContent=p.project.scene.appearance_ready===false?'已载入结构。导出条件后生成外观，再导入图像。':'';
 const rec=(p.project.render_records||[]).at(-1);$('recordInfo').textContent=rec?.pair_record?'配对记录 '+rec.pair_record.pair_id+' · '+rec.pair_record.started_at.slice(0,10):rec?'已导入外观；生成说明：'+(rec.generation_note||'未填写'):'尚无外观生成记录';$('actualPrompt').textContent=rec?.prompt||rec?.input?.prompt||'';const img=$('actualInput');img.hidden=!(rec?.structure_image_base64||rec?.structure_image_url);if(rec?.structure_image_base64)img.src='data:image/png;base64,'+rec.structure_image_base64;else if(rec?.structure_image_url)img.src=rec.structure_image_url;
}
function updateBand(){designSettings.height_mm=Number($('bandHeight').value)||50;designSettings.repeats=Math.max(1,Math.min(24,Number($('repeatCount').value)||3));$('bandSize').textContent='总宽约 '+(designSettings.height_mm*695/canvasHeight*designSettings.repeats).toFixed(1)+' mm · 等比缩放';if(project)showRepeat();}
function showVersions(list){const old=$('versionList').value;$('versionList').replaceChildren(new Option('选择已保存版本',''),...list.map(v=>new Option(v.name+' · '+v.created,v.id)));if(list.some(v=>v.id===old))$('versionList').value=old;}
async function jsonApi(path,data){const r=await api(path,{...data,settings:designSettings});return r.json();}
async function saveNamed(name){const p=await jsonApi('version-save',{edits,name});showVersions(p.versions);$('status').textContent='';}
$('saveVersion').onclick=async()=>{try{await saveNamed($('versionName').value);toast('版本已保存');}catch(e){fail(e);}};
$('openVersion').onclick=async()=>{try{if(!$('versionList').value)return;const p=await jsonApi('version-open',{id:$('versionList').value});history=[];future=[];selectionStrokes=[];display(p);setMode(p.project.scene.appearance_ready===false?'plan':'edit');$('raster').src=dataFile('render.png')+'?t='+Date.now();updateHistory();}catch(e){fail(e);}};
$('compareVersion').onclick=()=>{const id=$('versionList').value;if(!id)return;$('compareOriginal').src=dataFile('named_versions/'+id+'.svg');$('compareCurrent').innerHTML=cleanArt();$('compareModal').showModal();};
$('closeCompare').onclick=()=>$('compareModal').close();
$('saveSource').onclick=async()=>{try{const p=await jsonApi('provenance',Object.fromEntries(['source','interpretation','task'].map(k=>[k,$(k).value])));scene.provenance=p.provenance;toast('来源与任务已保存');$('status').textContent='';}catch(e){fail(e);}};
$('structureInput').onchange=async e=>{try{const f=e.target.files[0];if(!f)return;let data={edits};if(f.name.toLowerCase().endsWith('.zip')){const buf=new Uint8Array(await f.arrayBuffer());let bin='';for(let i=0;i<buf.length;i+=8192)bin+=String.fromCharCode(...buf.subarray(i,i+8192));data.zip=btoa(bin);}else data.raw=JSON.parse(await f.text());const p=await jsonApi('structure',data);edits={};history=[];future=[];selected='vine';display(p);setMode('plan');$('raster').src=dataFile('render.png')+'?t='+Date.now();toast('结构已载入，上一设计已保存为版本');}catch(e){fail(e);}e.target.value='';};
$('bandHeight').onchange=updateBand;$('repeatCount').onchange=updateBand;$('bandHeight').oninput=updateBand;$('repeatCount').oninput=updateBand;
$('showSeam').onclick=()=>{drawSeam();$('seamDialog').showModal();};$('closeSeam').onclick=()=>$('seamDialog').close();
async function groupAction(action){try{
 cancelCurrentPreview();
 const p=await jsonApi('objects',{action,object:selected,target:$('assignTarget').value,parent:$('parentTarget').value,name:$('newObjectName').value,strokes:selectionStrokes,edits,view:mode});
 history=[];future=[];selectionStrokes=[];display(p);updateHistory();toast(action==='undo_region'?'已撤销归属校正，设计修改保留':'归属已更新，枝形与删减保留');
 }catch(e){fail(e);}}
$('assignRegion').onclick=()=>groupAction('assign');$('newRegion').onclick=()=>groupAction('new');$('unknownRegion').onclick=()=>groupAction('unassigned');$('reparent').onclick=()=>groupAction('parent');$('mergeObject').onclick=()=>groupAction('merge');$('undoRegion').onclick=()=>groupAction('undo_region');

function showRenderInputs(items){
 renderInputs=items;const sel=$('renderInputVersion'),old=sel.value;
 sel.replaceChildren(new Option('选择生成时使用的结构',''),...items.slice().reverse().map(r=>new Option(r.created+' · '+r.case,r.id)),new Option('以当前结构配准（没有原始生成记录）','current'));
 if(old==='current'||items.some(r=>r.id===old))sel.value=old;
 updateRenderInput();
}
function updateRenderInput(){
 const id=$('renderInputVersion').value,r=renderInputs.find(r=>r.id===id),img=$('renderInputPreview');
 img.hidden=!id;if(id)img.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(r?.structure_svg||payload.guide);
 $('imageImportLabel').classList.toggle('disabled',!id);$('imageInput').disabled=!id;
 $('renderInputNote').textContent=r?'导入时使用此结构快照。之后的设计修改会另存为版本。':id==='current'?'当前结构只作恢复参照，不登记为已确认的生成输入。':'';
}
$('renderInputVersion').onchange=updateRenderInput;
$('condition').onclick=async()=>{try{const r=await api('condition',{edits,style:$('style').value});download(await r.blob(),'渲染条件.zip');const list=await jsonApi('render-inputs',{});showRenderInputs(list.inputs);$('status').textContent='';}catch(e){fail(e);}};
$('continueEditing').onclick=()=>{setMode('edit');refresh();};
$('recoverObject').onchange=()=>select($('recoverObject').value);
$('alignmentTools').ontoggle=overlay;
$('brush').onchange=overlay;

function seamFragment(prefix,viewBox){
 const svg=PeriodicSvg.standalone(3,prefix);
 svg.setAttribute('viewBox',viewBox);svg.removeAttribute('width');svg.removeAttribute('height');
 // A root SVG's letterbox can expose content beyond its viewBox. Clip the actual
 // inspection rectangle so right/left panels cannot show neighbouring material.
 const [x,y,w,h]=viewBox.split(' ').map(Number),defs=svg.querySelector('defs'),clip=el('clipPath',{id:prefix+'crop'});clip.appendChild(el('rect',{x,y,width:w,height:h}));defs.appendChild(clip);
 const content=el('g',{'clip-path':`url(#${prefix}crop)`});for(const n of [...svg.children])if(n!==defs)content.appendChild(n);svg.appendChild(content);
 return svg;
}
function drawSeam(){
 const width=Number($('seamWidth').value),mid=695;
 const vine=objects().find(o=>o.role==='main')?.guide,center=vine?(vine[0][1]+vine.at(-1)[1])/2:362;
 const height=$('seamFullHeight').checked?canvasHeight:Math.min(320,canvasHeight),top=Math.max(0,Math.min(canvasHeight-height,center-height/2));
 $('seamView').replaceChildren(seamFragment('join-',`${mid-width} ${top} ${width*2} ${height}`));
 $('seamRight').replaceChildren(seamFragment('right-',`${695-width} ${top} ${width} ${height}`));
 $('seamLeft').replaceChildren(seamFragment('left-',`0 ${top} ${width} ${height}`));
 const svg=$('seamView').firstElementChild;
 if($('seamLine').checked)svg.appendChild(el('line',{x1:695,y1:0,x2:695,y2:canvasHeight,stroke:'#bd7940','stroke-width':.7,'stroke-dasharray':'5 5','pointer-events':'none'}));
 // Any selected edge object is the same object repeated across every period.
 const n=new Set(selectionIds());for(const box of ['seamView','seamRight','seamLeft']){
  for(const g of $(box).querySelectorAll('[data-periodic-object]')){g.style.cursor='pointer';if($('seamHighlight').checked&&n.has(g.dataset.periodicObject))g.setAttribute('filter','drop-shadow(0 0 2px #cc8a37)');}
  $(box).onclick=e=>{const original=e.target.closest('[data-object]')?.dataset.object;if(!original)return;$('seamDialog').close();setMode('edit');select(original);toast('已选中对象；修改会同步到所有重复单元');};
 }
 $('seamSize').textContent='带高 '+designSettings.height_mm+' mm · 单元宽 '+(designSettings.height_mm*695/canvasHeight).toFixed(1)+' mm';
}
for(const id of ['seamWidth','seamLine','seamHighlight','seamFullHeight'])$(id).oninput=drawSeam;
