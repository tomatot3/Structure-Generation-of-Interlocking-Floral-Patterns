import * as THREE from 'three';
import {OrbitControls} from './vendor/three/examples/jsm/controls/OrbitControls.js';
import {RoomEnvironment} from './vendor/three/examples/jsm/environments/RoomEnvironment.js';
import {GLTFExporter} from './vendor/three/examples/jsm/exporters/GLTFExporter.js';

// A revolved, closed ceramic wall: recessed underside -> foot -> outside ->
// rounded rim -> inside -> inner floor. Geometry is exported in metres.
function cupGeometry(radius,height){
 const reference=50*695/724*4/(2*Math.PI),scale=radius/reference;
 const profile=[[0,3.2],[18,3.2],[23.8,3.1],[24.6,2.6],[25,.6],[25.5,.1],[26.8,.1],[27.4,.5],[27.7,2],[27.8,4],[28.2,5.8],[29.2,8],[30,11],[reference,15],[reference,20],[reference,70],[30.8,73],[31.2,76],[31.8,79],[32,81],[31.8,82],[31.2,82.4],[30.6,82.1],[30.3,81.4],[30.1,79],[29.3,75],[28.6,70],[28.6,14],[28.3,11],[27.5,9],[26,8],[20,7.6],[0,7.6]];
 const curve=new THREE.CatmullRomCurve3(profile.map(([r,y])=>new THREE.Vector3(r*scale,y*height/82.4,0)),false,'centripetal');
 const rows=240,segments=256,points=curve.getPoints(rows),position=[],uv=[],outer=[],plain=[];
 for(let j=0;j<=segments;j++)for(let i=0;i<=rows;i++){
  const phi=j/segments*Math.PI*2,p=points[i];position.push(Math.sin(phi)*p.x/1000,p.y/1000,Math.cos(phi)*p.x/1000);uv.push(j/segments,p.y/height);
 }
 for(let j=0;j<segments;j++)for(let i=0;i<rows;i++){
  const a=j*(rows+1)+i,b=(j+1)*(rows+1)+i,d=a+1,c=b+1;
  const indices=(i/rows>=8/32&&i/rows<21/32)?outer:plain;indices.push(a,b,d,b,c,d);
 }
 const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(position,3));g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));g.setIndex([...outer,...plain]);g.addGroup(0,outer.length,0);g.addGroup(outer.length,plain.length,1);g.computeVertexNormals();
 const n=g.attributes.normal;
 for(let i=0;i<=rows;i++){const j=segments*(rows+1)+i,v=new THREE.Vector3(n.getX(i)+n.getX(j),n.getY(i)+n.getY(j),n.getZ(i)+n.getZ(j)).normalize();n.setXYZ(i,v.x,v.y,v.z);n.setXYZ(j,v.x,v.y,v.z);}
 return g;
}
async function patternTexture(svg,height,bandHeight,repeats){
 const canvas=document.createElement('canvas');canvas.width=4096;canvas.height=2048;const ctx=canvas.getContext('2d');ctx.fillStyle='#ffffff';ctx.fillRect(0,0,canvas.width,canvas.height);
 const blob=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml'}));const image=new Image();image.src=blob;await image.decode();
 const bottom=bandHeight*.3,top=bottom+bandHeight,y=(height-top)/height*canvas.height,h=bandHeight/height*canvas.height;
 for(let i=0;i<repeats;i++)ctx.drawImage(image,i*canvas.width/repeats,y,canvas.width/repeats,h);
 URL.revokeObjectURL(blob);const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;texture.wrapS=THREE.RepeatWrapping;texture.anisotropy=8;
 return {texture,canvas};
}
export async function createCupPreview(host,svg,settings={}){
 const repeats=Math.max(1,Math.min(24,settings.repeats||4)),bandHeight=Number(settings.height_mm)||50,unitAspect=(settings.width||695)/(settings.height||724),circumference=bandHeight*unitAspect*repeats,radius=circumference/(2*Math.PI),height=bandHeight*1.648;
 const {texture,canvas}=await patternTexture(svg,height,bandHeight,repeats);
 const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,preserveDrawingBuffer:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.08;host.replaceChildren(renderer.domElement);
 const scene=new THREE.Scene();scene.background=new THREE.Color('#f3f1ed');
 const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment(),environment=pmrem.fromScene(room,.04);scene.environment=environment.texture;scene.environmentIntensity=.6;room.dispose();
 const materialOptions={color:0xffffff,roughness:.25,metalness:0,clearcoat:.85,clearcoatRoughness:.15,ior:1.5,envMapIntensity:.8};
 const body=new THREE.MeshPhysicalMaterial({...materialOptions,map:texture}),porcelain=new THREE.MeshPhysicalMaterial(materialOptions);
 const cup=new THREE.Mesh(cupGeometry(radius,height),[body,porcelain]);cup.name='Porcelain cup with edited floral-scroll border';cup.rotation.y=Math.PI;cup.castShadow=true;cup.receiveShadow=true;scene.add(cup);
 const scale=height/82.4;
 const ground=new THREE.Mesh(new THREE.PlaneGeometry(2*scale,2*scale),new THREE.MeshStandardMaterial({color:'#edeae5',roughness:1}));ground.rotation.x=-Math.PI/2;ground.receiveShadow=true;scene.add(ground);
 const light=new THREE.DirectionalLight('#fff6e9',2.2);light.position.set(-.12*scale,.22*scale,.14*scale);light.castShadow=true;light.shadow.mapSize.set(2048,2048);light.shadow.camera.left=-.13*scale;light.shadow.camera.right=.13*scale;light.shadow.camera.top=.13*scale;light.shadow.camera.bottom=-.13*scale;light.shadow.camera.near=.01;light.shadow.camera.far=1*scale;light.shadow.normalBias=.00025*scale;light.shadow.bias=-.00004;light.shadow.radius=4;scene.add(light);
 const fill=new THREE.DirectionalLight('#eef4ff',.8);fill.position.set(.14*scale,.12*scale,-.12*scale);scene.add(fill);
 const camera=new THREE.PerspectiveCamera(32,1,.001*scale,10*scale),controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,height/2000,0);controls.enableDamping=true;controls.enablePan=false;controls.minDistance=.10*scale;controls.maxDistance=.45*scale;controls.maxPolarAngle=Math.PI*.49;
 const distance=Math.max(.205*scale,radius/1000*5.5);
 function view(name){
  const y=height/2000;
  if(name==='back')camera.position.set(0,y+distance*.23,-distance);
  else if(name==='top')camera.position.set(distance*.35,y+distance*.9,distance*.38);
  else camera.position.set(distance*.56,y+distance*.3,distance*.82);
  controls.target.set(0,y,0);controls.update();
 }
 view('front');
 function resize(){const w=host.clientWidth,h=host.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}
 const observer=new ResizeObserver(resize);observer.observe(host);resize();let running=true;
 function tick(){if(!running)return;controls.update();renderer.render(scene,camera);requestAnimationFrame(tick);}tick();
 async function snapshot(){
  const size=new THREE.Vector2();renderer.getSize(size);const pixelRatio=renderer.getPixelRatio(),aspect=camera.aspect;
  renderer.setPixelRatio(1);renderer.setSize(2200,2200,false);camera.aspect=1;camera.updateProjectionMatrix();renderer.render(scene,camera);
  const png=renderer.domElement.toDataURL('image/png');renderer.setPixelRatio(pixelRatio);renderer.setSize(size.x,size.y,false);camera.aspect=aspect;camera.updateProjectionMatrix();
  const exporter=new GLTFExporter(),model=await exporter.parseAsync(cup,{binary:true,onlyVisible:true,maxTextureSize:4096});
  return {png,model,texture:canvas.toDataURL('image/png'),settings:{band_height_mm:bandHeight,repeats,cup_height_mm:height,reference_diameter_mm:radius*2,circumference_mm:circumference,units:'metres',source:'current editable SVG',vertices:cup.geometry.attributes.position.count,triangles:cup.geometry.index.count/3}};
 }
 return {view,snapshot,dispose(){running=false;observer.disconnect();controls.dispose();cup.geometry.dispose();body.dispose();porcelain.dispose();texture.dispose();ground.geometry.dispose();ground.material.dispose();environment.dispose();pmrem.dispose();renderer.dispose();host.replaceChildren();}};
}

export async function saveCupPreview(preview,apiBase,edits,designSettings){
 const result=await preview.snapshot();const bytes=new Uint8Array(result.model);let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
 const response=await fetch(apiBase+'/preview-3d',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({png:result.png,glb:btoa(binary),texture:result.texture,settings:result.settings,edits,design_settings:designSettings})});
 const data=await response.json();if(!response.ok)throw Error(data.detail||data.error||'保存失败');return data;
}
