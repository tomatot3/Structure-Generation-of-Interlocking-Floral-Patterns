let activeCup,cupModule,vesselOpen=0,vesselTimer;
function syncVesselControls(){
 const s=designSettings.application||cupModule.defaults;
 if(s.motif==='sea')s.motif='none';
 $('vesselKind').value=s.vessel;$('vesselMotif').value=s.motif;
 $('vesselRepeats').value=s.repeats;$('vesselBand').value=s.band;$('vesselPosition').value=s.position;
 $('vesselRepeatsValue').textContent=s.repeats;$('vesselBandValue').textContent=s.band+'%';
}
function storeVessel(){if(activeCup)designSettings.application=activeCup.settings;}
function setVesselControls(){
 if(!activeCup)return;
 activeCup.update({vessel:$('vesselKind').value,motif:$('vesselMotif').value,repeats:Number($('vesselRepeats').value),band:Number($('vesselBand').value),position:Number($('vesselPosition').value)});
 storeVessel();syncVesselControls();
}
$('showCup').onclick=async()=>{
 const token=++vesselOpen;
 try{
  $('cupDialog').showModal();$('cupStatus').textContent='正在载入当前边饰…';$('cupView').value='front';
  document.querySelectorAll('[data-cup-format]').forEach(b=>b.disabled=true);
  cupModule=await import('./vessel3d.js?v=20261029-motifs3');
  designSettings.application={...cupModule.defaults,...designSettings.application};syncVesselControls();
  const response=await api('svg',{edits,settings:designSettings}),svg=await response.text();
  if(token!==vesselOpen)return;
  activeCup?.dispose();activeCup=null;
  const preview=await cupModule.createVesselPreview($('cupViewer'),svg,designSettings.application);
  if(token!==vesselOpen){preview.dispose();return;}
  activeCup=preview;storeVessel();$('cupStatus').textContent='';$('status').textContent='';
  document.querySelectorAll('[data-cup-format]').forEach(b=>b.disabled=false);
 }catch(e){if(token===vesselOpen){$('cupStatus').textContent=e.message;$('status').textContent='';}}
};
$('closeCup').onclick=()=>$('cupDialog').close();
$('cupDialog').onclose=()=>{vesselOpen++;clearTimeout(vesselTimer);setVesselControls();storeVessel();activeCup?.dispose();activeCup=null;};
$('cupView').onchange=e=>activeCup?.view(e.target.value);
for(const id of ['vesselKind','vesselMotif'])$(id).onchange=()=>{
 if(id==='vesselKind'){
  const kind=$('vesselKind').value;$('vesselRepeats').value=kind==='plate'?8:kind==='bowl'?6:4;
  $('vesselBand').value=kind==='plate'?15:12;$('vesselPosition').value=85;$('cupView').value='front';
 }
 setVesselControls();
};
for(const id of ['vesselRepeats','vesselBand','vesselPosition']){
 $(id).oninput=()=>{
  $('vesselRepeatsValue').textContent=$('vesselRepeats').value;$('vesselBandValue').textContent=$('vesselBand').value+'%';
  clearTimeout(vesselTimer);vesselTimer=setTimeout(setVesselControls,80);
 };
 $(id).onchange=()=>{clearTimeout(vesselTimer);setVesselControls();};
}
for(const button of document.querySelectorAll('[data-cup-format]'))button.onclick=async()=>{
 if(!activeCup)return;const preview=activeCup,format=button.dataset.cupFormat;
 const buttons=[...document.querySelectorAll('[data-cup-format]')];
 try{
  clearTimeout(vesselTimer);setVesselControls();buttons.forEach(b=>b.disabled=true);$('cupStatus').textContent='正在导出…';
  const blob=await preview.snapshot(format),url=URL.createObjectURL(blob),a=document.createElement('a');
  const names={plate:'瓷盘',bowl:'碗',cup:'杯'};a.href=url;a.download='StructVine_'+names[preview.settings.vessel]+'.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);$('cupStatus').textContent='';
 }catch(e){$('cupStatus').textContent=e.message;}finally{buttons.forEach(b=>b.disabled=!activeCup);}
};

$('applyVessel').onclick=()=>$('showCup').click();
if(new URLSearchParams(location.search).get('application')==='1'){let attempts=0;const openWhenReady=()=>{if(project?.objects){$('showCup').click();}else if(++attempts<1200)setTimeout(openWhenReady,100);};openWhenReady();}
