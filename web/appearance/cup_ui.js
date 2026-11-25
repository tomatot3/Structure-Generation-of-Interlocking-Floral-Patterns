let activeCup,cupModule,vesselOpen=0,vesselTimer,vesselTrigger;
function notifyVessel(open){if(window.parent!==window)window.parent.postMessage({type:'papera-vessel-modal',open},location.origin);}
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
  vesselTrigger=document.activeElement;$('cupDialog').showModal();notifyVessel(true);$('closeCup').focus();$('cupStatus').textContent='正在将边饰贴合器面…';$('cupView').value='front';
  document.querySelectorAll('[data-cup-format]').forEach(b=>b.disabled=true);
  cupModule=await import('./vessel3d.js?v=editorial-4');
  designSettings.application={...cupModule.defaults,...designSettings.application};syncVesselControls();
  const response=await api('svg',{edits,settings:designSettings}),svg=await response.text();
  if(token!==vesselOpen)return;
  activeCup?.dispose();activeCup=null;
  const preview=await cupModule.createVesselPreview($('cupViewer'),svg,designSettings.application);
  if(token!==vesselOpen){preview.dispose();return;}
  activeCup=preview;preview.setLighting($('cupDialog').classList.contains('vessel-night')?'night':'day');storeVessel();$('cupStatus').textContent='';$('status').textContent='';
  document.querySelectorAll('[data-cup-format]').forEach(b=>b.disabled=false);
 }catch(e){if(token===vesselOpen){$('cupStatus').textContent=e.message;$('status').textContent='';}}
};
$('closeCup').onclick=()=>$('cupDialog').close();
$('cupDialog').onclose=()=>{notifyVessel(false);vesselOpen++;clearTimeout(vesselTimer);setVesselControls();storeVessel();activeCup?.dispose();activeCup=null;vesselTrigger?.focus();};
for(const button of document.querySelectorAll('[data-vessel-theme]'))button.onclick=()=>{
 const theme=button.dataset.vesselTheme;
 $('cupDialog').classList.toggle('vessel-night',theme==='night');
 document.querySelectorAll('[data-vessel-theme]').forEach(option=>option.setAttribute('aria-pressed',String(option===button)));
 activeCup?.setLighting(theme);
};
$('cupView').onchange=e=>activeCup?.view(e.target.value);
for(const id of ['vesselKind','vesselMotif'])$(id).onchange=()=>{
 AtlasEditor.setDirty(true);
 if(id==='vesselKind'){
  const kind=$('vesselKind').value;$('vesselRepeats').value=kind==='plate'?8:kind==='bowl'?6:4;
  $('vesselBand').value=kind==='plate'?15:12;$('vesselPosition').value=85;$('cupView').value='front';
 }
 setVesselControls();
};
for(const id of ['vesselRepeats','vesselBand','vesselPosition']){
 $(id).oninput=()=>{
  AtlasEditor.setDirty(true);
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
  const names={plate:AtlasEditor.text('瓷盘'),bowl:AtlasEditor.text('碗'),cup:AtlasEditor.text('杯')};a.href=url;a.download='StructVine_'+names[preview.settings.vessel]+'.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);$('cupStatus').textContent='';
 }catch(e){$('cupStatus').textContent=e.message;}finally{buttons.forEach(b=>b.disabled=!activeCup);}
};

$('applyVessel').onclick=()=>$('showCup').click();
if(new URLSearchParams(location.search).get('application')==='1'){let attempts=0;const openWhenReady=()=>{if(project?.objects){$('showCup').click();}else if(++attempts<1200)setTimeout(openWhenReady,100);};openWhenReady();}
