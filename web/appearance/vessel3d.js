import * as THREE from 'three';
import {OrbitControls} from './vendor/three/examples/jsm/controls/OrbitControls.js';
import {RoomEnvironment} from './vendor/three/examples/jsm/environments/RoomEnvironment.js';
import {GLTFExporter} from './vendor/three/examples/jsm/exporters/GLTFExporter.js';

export const defaults={vessel:'plate',motif:'dragon',repeats:8,band:15,position:85};
const sizes={plate:[280,29.4],bowl:[160,72],cup:[80,95]};
function profile(kind){
 const p=[];const line=(r,y)=>p.push(new THREE.Vector2(r/1000,y/1000));
 const curve=(a,b,e)=>{const s=p.at(-1);for(let i=1;i<=18;i++){const t=i/18,u=1-t;line(u**3*s.x*1000+3*u*u*t*a[0]+3*u*t*t*b[0]+t**3*e[0],u**3*s.y*1000+3*u*u*t*a[1]+3*u*t*t*b[1]+t**3*e[1]);}};
 if(kind==='plate'){
  line(0,7);line(60,7);curve([64,7],[65,7],[65,4]);curve([65,1],[66,0],[68,0]);line(71,0);curve([73,0],[74,1],[74,3]);line(74,5);curve([74,7],[78,7],[84,9]);curve([91,12],[95,16],[101,19]);curve([111,23],[126,25],[137,26]);curve([141,26.3],[141,29.4],[137,29.4]);curve([126,28.7],[115,27],[106,24]);curve([98,21.5],[94,15],[86,12.8]);curve([80,11],[77,11],[71,11]);line(0,11);
 }else if(kind==='bowl'){
  line(0,5);line(31,5);line(31,1);curve([31,0],[35,0],[36,1]);line(36,6);curve([48,7],[65,28],[77,66]);curve([79,70],[80,72],[78,72]);curve([76,72],[75,70],[74,66]);curve([63,33],[47,12],[30,11]);line(0,11);
 }else{
  line(0,5);line(30,5);line(30,1);curve([30,0],[34,0],[35,1]);line(35,6);curve([38,8],[38,12],[38,18]);line(40,92);curve([40,96],[37,96],[37,92]);line(35,18);curve([35,12],[32,10],[28,10]);line(0,10);
 }
 return p;
}
function geometry(kind){
 const p=profile(kind),g=new THREE.LatheGeometry(p,256),[diameter,height]=sizes[kind];
 let rim=0;for(let i=0;i<p.length;i++)if(p[i].y>p[rim].y)rim=i;
 if(kind==='plate'){const a=g.attributes.position;for(let i=0;i<a.count;i++)g.attributes.uv.setXY(i,.5+a.getX(i)/(diameter/1000),.5-a.getZ(i)/(diameter/1000));}
 else{for(let j=0;j<=256;j++)for(let i=0;i<p.length;i++)g.attributes.uv.setXY(j*p.length+i,j/256,p[i].y/(height/1000));}
 g.clearGroups();for(let j=0;j<256;j++){const start=j*(p.length-1)*6;g.addGroup(start,rim*6,kind==='plate'?0:1);g.addGroup(start+rim*6,(p.length-1-rim)*6,kind==='plate'?1:0);}return g;
}
async function imageOf(url){const image=new Image();image.src=url;await image.decode();return image;}
function decorate(svgImage,dragon,dragonWrap,settings){
 const c=document.createElement('canvas');c.width=c.height=2048;const ctx=c.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,2048,2048);
 const n=2048,repeats=Math.round(settings.repeats),kind=settings.vessel;
 if(kind==='plate'){
  const outer=.82+.00165*settings.position,inner=outer-settings.band/100;
  const strip=document.createElement('canvas');strip.width=n;strip.height=384;const s=strip.getContext('2d');s.fillStyle='#fff';s.fillRect(0,0,n,384);
  for(let i=0;i<repeats;i++)s.drawImage(svgImage,i*n/repeats,0,n/repeats,384);
  const source=s.getImageData(0,0,n,384).data,dst=ctx.getImageData(0,0,n,n),a=dst.data;
  for(let y=0;y<n;y++)for(let x=0;x<n;x++){
   const dx=(x-n/2)/(n/2),dy=(y-n/2)/(n/2),r=Math.hypot(dx,dy);if(r<inner||r>outer)continue;
   const u=(Math.atan2(dy,dx)/(Math.PI*2)+1)%1,v=(outer-r)/(outer-inner),sx=Math.min(n-1,Math.floor(u*n)),sy=Math.min(383,Math.floor(v*384)),q=(sy*n+sx)*4,p=(y*n+x)*4;
   a[p]=source[q];a[p+1]=source[q+1];a[p+2]=source[q+2];a[p+3]=255;
  }ctx.putImageData(dst,0,0);
  const centerRadius=Math.min(.61,inner-.08)*n/2;
  ctx.save();ctx.beginPath();ctx.arc(n/2,n/2,centerRadius,0,Math.PI*2);ctx.clip();
  if(settings.motif==='dragon'){const size=dragon.width*.65;ctx.drawImage(dragon,(dragon.width-size)/2,(dragon.height-size)/2,size,size,n/2-centerRadius,n/2-centerRadius,centerRadius*2,centerRadius*2);}
  ctx.restore();
 }else{
  const h=n*settings.band/100,margin=n*(.025+(100-settings.position)*.0013);
  const top=margin,bottom=n-margin-h;
  for(const y of [top,bottom])for(let i=0;i<repeats;i++)ctx.drawImage(svgImage,i*n/repeats,y,n/repeats,h);
  const y=top+h,height=Math.max(1,bottom-y);
  if(settings.motif==='dragon'){
   // Fill the whole circumference between the two border bands. The motif
   // repeat count follows surface proportions, independently of the border.
   const circumference=Math.PI*(kind==='cup'?77:120),physicalHeight=sizes[kind][1]*height/n;
   const count=Math.max(1,Math.min(12,Math.round(circumference/(physicalHeight*dragonWrap.width/dragonWrap.height))));
   for(let i=0;i<count;i++)ctx.drawImage(dragonWrap,i*n/count,y,n/count+1,height);
  }
 }
 return c;
}
export async function createVesselPreview(host,svg,initial={}){
 let settings={...defaults,...initial},alive=true,mesh,texture,canvas;
 const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));let artwork;try{artwork=await imageOf(url);}finally{URL.revokeObjectURL(url);}
 const dragon=await imageOf(new URL('./assets/sea-dragon.png',import.meta.url).href);
 const dragonWrap=await imageOf(new URL('./assets/sea-dragon-wrap.png',import.meta.url).href);
 const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.95;renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;host.replaceChildren(renderer.domElement);
 const scene=new THREE.Scene();scene.background=new THREE.Color('white');const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment(),env=pmrem.fromScene(room,.04);room.dispose();scene.environment=env.texture;scene.environmentIntensity=.18;
 const plain=new THREE.MeshPhysicalMaterial({color:0xfafaf7,roughness:.32,clearcoat:.35,clearcoatRoughness:.32}),paint=plain.clone();
 const floor=new THREE.Mesh(new THREE.PlaneGeometry(3,3),new THREE.ShadowMaterial({opacity:.07}));floor.rotation.x=-Math.PI/2;floor.receiveShadow=true;scene.add(floor);
 const key=new THREE.DirectionalLight(0xffffff,1.8);key.position.set(-.32,.3,.2);key.castShadow=true;key.shadow.mapSize.set(2048,2048);Object.assign(key.shadow.camera,{left:-.22,right:.22,top:.22,bottom:-.22,near:.01,far:2});key.shadow.normalBias=.0003;scene.add(key);
 const fill=new THREE.DirectionalLight(0xffffff,.55);fill.position.set(.3,.25,-.2);scene.add(fill);
 const camera=new THREE.PerspectiveCamera(32,1,.001,10),controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.enablePan=false;controls.minDistance=.12;controls.maxDistance=1.2;controls.maxPolarAngle=Math.PI*.49;
 function view(name='front'){
  const [d,h]=sizes[settings.vessel],distance=Math.max(d,h*1.7)/1000*2.05,target=h/2000,angle=(name==='top'?78:name==='low'?20:settings.vessel==='plate'?38:18)*Math.PI/180;
  const azimuth=settings.vessel==='plate'?0:-Math.PI*.5;
  camera.position.set(distance*Math.cos(angle)*Math.sin(azimuth),target+distance*Math.sin(angle),distance*Math.cos(angle)*Math.cos(azimuth));controls.target.set(0,target,0);controls.update();
 }
 function update(next){
  if(!alive)return;const old=settings.vessel;settings={...settings,...next};if(settings.motif==='sea')settings.motif='none';settings.repeats=THREE.MathUtils.clamp(Math.round(settings.repeats)||8,2,16);settings.band=THREE.MathUtils.clamp(Number(settings.band)||15,8,24);settings.position=THREE.MathUtils.clamp(Number(settings.position)||0,0,100);
  canvas=decorate(artwork,dragon,dragonWrap,settings);texture?.dispose();texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=renderer.capabilities.getMaxAnisotropy();texture.wrapS=THREE.RepeatWrapping;paint.map=texture;paint.needsUpdate=true;
  if(!mesh||old!==settings.vessel){if(mesh){scene.remove(mesh);mesh.geometry.dispose();}mesh=new THREE.Mesh(geometry(settings.vessel),[plain,paint]);mesh.name='StructVine ceramic '+settings.vessel;mesh.castShadow=true;scene.add(mesh);view();}
  mesh.userData={application:{...settings},dimensions_mm:sizes[settings.vessel],source:'current edited periodic SVG'};
 }
 update(settings);
 function resize(){const w=Math.max(1,host.clientWidth),h=Math.max(1,host.clientHeight);renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
 const observer=new ResizeObserver(resize);observer.observe(host);resize();let frame;
 function tick(){if(!alive)return;controls.update();renderer.render(scene,camera);frame=requestAnimationFrame(tick);}tick();
 async function snapshot(format){
  if(format==='glb')return new Blob([await new GLTFExporter().parseAsync(mesh,{binary:true,maxTextureSize:2048})],{type:'model/gltf-binary'});
  const size=new THREE.Vector2();renderer.getSize(size);const ratio=renderer.getPixelRatio(),aspect=camera.aspect;
  renderer.setPixelRatio(1);renderer.setSize(2200,1800,false);camera.aspect=2200/1800;camera.updateProjectionMatrix();renderer.render(scene,camera);
  const blob=await new Promise(resolve=>renderer.domElement.toBlob(resolve,'image/png'));
  renderer.setPixelRatio(ratio);renderer.setSize(size.x,size.y,false);camera.aspect=aspect;camera.updateProjectionMatrix();return blob;
 }
 return {update,view,snapshot,get settings(){return {...settings};},dispose(){alive=false;cancelAnimationFrame(frame);observer.disconnect();controls.dispose();mesh.geometry.dispose();texture.dispose();plain.dispose();paint.dispose();floor.geometry.dispose();floor.material.dispose();key.shadow.map?.dispose();env.dispose();pmrem.dispose();renderer.dispose();host.replaceChildren();}};
}
