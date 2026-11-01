// Interaction rules follow web/editor/editor.js: all cubic handles, root on
// parent, tip with its adjacent handle, and shared join/tangent control.
const CurveControls=(()=>{
 const add=(a,b)=>[a[0]+b[0],a[1]+b[1]],sub=(a,b)=>[a[0]-b[0],a[1]-b[1]],mul=(a,t)=>a.map(v=>v*t),norm=a=>{const n=Math.hypot(...a)||1;return a.map(v=>v/n);};
 function path(cs){return 'M'+cs[0][0].join(',')+cs.map(c=>'C'+c.slice(1).map(p=>p.join(',')).join(' ')).join('');}
 function samples(cs){const ps=[];for(const c of cs)for(let i=0;i<12;i++){const t=i/12,u=1-t;ps.push([0,1].map(j=>u*u*u*c[0][j]+3*u*u*t*c[1][j]+3*u*t*t*c[2][j]+t*t*t*c[3][j]));}ps.push(cs.at(-1)[3]);return ps;}
 function frameAtFraction(points,fraction){let lengths=[],total=0;for(let i=0;i<points.length-1;i++){const n=Math.hypot(...sub(points[i+1],points[i]));lengths.push(n);total+=n;}let target=Math.max(.001,Math.min(.985,fraction))*total,done=0;for(let i=0;i<lengths.length;i++){const l=lengths[i];if(!l)continue;if(done+l>=target||i===lengths.length-1){const tangent=norm(sub(points[i+1],points[i]));return {point:add(points[i],mul(sub(points[i+1],points[i]),Math.max(0,Math.min(1,(target-done)/l)))),tangent,normal:[-tangent[1],tangent[0]],fraction:target/total};}done+=l;}}
 function projectPoint(p,points){let total=0,lengths=[];for(let i=0;i<points.length-1;i++){const l=Math.hypot(...sub(points[i+1],points[i]));lengths.push(l);total+=l;}let best=Infinity,fraction=0,done=0;for(let i=0;i<lengths.length;i++){const v=sub(points[i+1],points[i]),d=sub(p,points[i]),l=lengths[i];if(!l)continue;const t=Math.max(0,Math.min(1,(v[0]*d[0]+v[1]*d[1])/(l*l))),q=add(points[i],mul(v,t)),gap=Math.hypot(...sub(p,q));if(gap<best){best=gap;fraction=(done+t*l)/total;}done+=l;}return frameAtFraction(points,fraction);}
 function draw(root,o){
  let cs=structuredClone(o.curve),moving=null;const periodic=!!scene?.periodic_registration,period=695,last=cs.length-1,visualRoot=periodic?el('g',{'clip-path':'url(#curve-controls-period-clip)','pointer-events':'none'}):root;
  if(periodic){const defs=el('defs',{}),clip=el('clipPath',{id:'curve-controls-period-clip',clipPathUnits:'userSpaceOnUse'});clip.appendChild(el('rect',{x:0,y:0,width:period,height:canvasHeight}));defs.appendChild(clip);root.append(defs,visualRoot);}
  const curve=el('path',{d:path(cs),fill:'none',stroke:'#3673a5','stroke-width':1.6,'pointer-events':'none'});visualRoot.appendChild(curve);const arms=[],knobs=[],visualCopies=new Map();
  const screen=root.getScreenCTM(),unit=screen?1/Math.hypot(screen.a,screen.b):1,r=5.5*unit;
  for(let segment=0;segment<cs.length;segment++)for(const cp of [1,2]){
   const line=el('line',{stroke:'#b88445','stroke-width':1.1*unit,'stroke-dasharray':'3 3','pointer-events':'none'});visualRoot.appendChild(line);arms.push({line,segment,cp,anchor:cp===1?0:3});
   const h=el('circle',{r,class:'handle bezier-control',tabindex:0,role:'slider','aria-label':o.name+(cs.length>1?'第'+(segment+1)+'段':'')+(cp===1?'出向控制柄':'入向控制柄'),'data-control':cp,'data-segment':segment});root.appendChild(h);knobs.push({node:h,segment,cp});bind(h,{type:'control',segment,cp});
  }
  for(const [type,segment,cp,label] of [['root',0,0,'根点'],['tip',last,3,'枝尖']]){const h=el('circle',{r:r+unit,class:'handle bezier-anchor',tabindex:0,role:'slider','aria-label':o.name+label,'data-handle-type':type});root.appendChild(h);knobs.push({node:h,segment,cp});bind(h,{type});}
  for(let i=0;i<last;i++){const h=el('polygon',{class:'handle bezier-anchor',tabindex:0,role:'slider','aria-label':o.name+'连接点'+(i+1)});root.appendChild(h);knobs.push({node:h,segment:i,cp:3,join:true});bind(h,{type:'join',segment:i});}
  function wrapVisual(node,left,right){if(!periodic)return;for(const old of visualCopies.get(node)||[])old.remove();const copies=PeriodicSvg.shifts(left-1e-7,right+1e-7).map(k=>{const copy=node.cloneNode(true);copy.setAttribute('transform','translate('+(k*period)+',0)');copy.setAttribute('aria-hidden','true');visualRoot.appendChild(copy);return copy;});visualCopies.set(node,copies);}
  function position(){curve.setAttribute('d',path(cs));const xs=cs.flat().map(p=>p[0]);wrapVisual(curve,Math.min(...xs),Math.max(...xs));for(const a of arms){const c=cs[a.segment];a.line.setAttribute('x1',c[a.anchor][0]);a.line.setAttribute('y1',c[a.anchor][1]);a.line.setAttribute('x2',c[a.cp][0]);a.line.setAttribute('y2',c[a.cp][1]);wrapVisual(a.line,Math.min(c[a.anchor][0],c[a.cp][0]),Math.max(c[a.anchor][0],c[a.cp][0]));}for(const k of knobs){const source=cs[k.segment][k.cp],p=periodic?[((source[0]%period)+period)%period,source[1]]:source;k.node.dataset.periodicShift=source[0]-p[0];if(k.join)k.node.setAttribute('points',[[p[0],p[1]-r],[p[0]+r,p[1]],[p[0],p[1]+r],[p[0]-r,p[1]]].map(v=>v.join(',')).join(' '));else{k.node.setAttribute('cx',p[0]);k.node.setAttribute('cy',p[1]);}k.node.setAttribute('aria-valuetext',p.map(v=>v.toFixed(1)).join(', '));}}
  function change(target){
   const m=moving;if(!m.changed){remember();m.changed=true;}cs=structuredClone(m.base);
   if(m.type==='root'){
    const oldFrame=projectPoint(m.base[0][0],o.parent_guide),newFrame=projectPoint(target,o.parent_guide),origin=m.base[0][0];m.mount=newFrame.fraction;
    cs=m.base.map(c=>c.map(p=>{const d=sub(p,origin),x=d[0]*oldFrame.tangent[0]+d[1]*oldFrame.tangent[1],y=d[0]*oldFrame.normal[0]+d[1]*oldFrame.normal[1];return add(newFrame.point,add(mul(newFrame.tangent,x),mul(newFrame.normal,y)));}));
   }else if(m.type==='tip'){const delta=sub(target,m.base[last][3]);cs[last][3]=target;cs[last][2]=add(m.base[last][2],delta);
   }else if(m.type==='join'){const s=m.segment,delta=sub(target,m.base[s][3]);cs[s][3]=target;cs[s+1][0]=target.slice();cs[s][2]=add(m.base[s][2],delta);cs[s+1][1]=add(m.base[s+1][1],delta);
   }else{
    const s=m.segment,cp=m.cp;cs[s][cp]=target;
    // Same G1 rule as the source editor, without freezing the proximal segment.
    if(cp===2&&s<last){const join=cs[s][3],len=Math.hypot(...sub(m.base[s+1][1],m.base[s+1][0]));cs[s+1][1]=add(join,mul(norm(sub(join,target)),len));}
    if(cp===1&&s>0){const join=cs[s][0],len=Math.hypot(...sub(m.base[s-1][3],m.base[s-1][2]));cs[s-1][2]=add(join,mul(norm(sub(target,join)),-len));}
   }
   position();WarpPreview.update(samples(cs));
  }
  function commit(){if(!moving.changed){moving=null;WarpPreview.stop();return;}const e={...(edits[o.id]||{}),curve:structuredClone(cs),curve_basis:'source-cubic-v1',parent_ops:structuredClone(o.parent_ops||[])};delete e.points;if(moving.type==='root')e.mount_fraction=moving.mount;edits[o.id]=e;moving=null;refresh();}
  function bind(n,info){
   n.onpointerdown=e=>{e.preventDefault();e.stopPropagation();cancelCurrentPreview();moving={...info,base:structuredClone(cs),changed:false,periodicShift:Number(n.dataset.periodicShift)||0};WarpPreview.begin(o.id,samples(cs));n.setPointerCapture(e.pointerId);};
   n.onpointermove=e=>{if(moving){const p=coords(e);p[0]+=moving.periodicShift;change(p);}};n.onpointerup=e=>{if(moving){n.releasePointerCapture(e.pointerId);commit();}};n.onpointercancel=()=>{if(moving)cs=moving.base;moving=null;WarpPreview.stop();position();};
   n.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();moving={...info,base:structuredClone(cs),changed:false};WarpPreview.begin(o.id,samples(cs));const p=info.type==='root'?cs[0][0]:info.type==='tip'?cs[last][3]:info.type==='join'?cs[info.segment][3]:cs[info.segment][info.cp],d=e.shiftKey?10:2;change([p[0]+(e.key==='ArrowRight'?d:e.key==='ArrowLeft'?-d:0),p[1]+(e.key==='ArrowDown'?d:e.key==='ArrowUp'?-d:0)]);commit();};
  }
  position();
 }
 return {draw,samples,path,projectPoint};
})();

// Local mesh preview while dragging. Final SVG is computed from the same curve
// by the server on release; this preview never replaces exported vector paths.
const WarpPreview=(()=>{
 let state=null,frame=0,token=0;const canvas=document.createElement('canvas');canvas.id='dragPreview';canvas.width=695;canvas.height=724;canvas.hidden=true;document.getElementById('stage').appendChild(canvas);const ctx=canvas.getContext('2d'),repeatCanvas=document.createElement('canvas');repeatCanvas.hidden=true;repeatCanvas.style.cssText='position:absolute;pointer-events:none;';
 function stop(){token++;if(frame)cancelAnimationFrame(frame);frame=0;canvas.hidden=true;repeatCanvas.hidden=true;if(state)for(const g of state.groups)g.style.visibility='';state=null;}
 function begin(id,points){stop();const stamp=token;let ids=new Set([id]),changed=true;while(changed){changed=false;for(const o of objects())if(ids.has(o.parent)&&!ids.has(o.id)){ids.add(o.id);changed=true;}}
  const groups=[...document.querySelectorAll('#art g[data-role]')].filter(g=>ids.has(g.id)),copies=groups.map(g=>{let c=g.cloneNode(true);c.removeAttribute('class');c.removeAttribute('style');return c.outerHTML;});
  const boxes=groups.map(g=>g.getBBox()),box={x:Math.min(...boxes.map(b=>b.x))-2,y:Math.min(...boxes.map(b=>b.y))-2,right:Math.max(...boxes.map(b=>b.x+b.width))+2,bottom:Math.max(...boxes.map(b=>b.y+b.height))+2};
  // Keep off-cell material in the source image, so a drag through either edge
  // wraps the same material as the committed vector result.
  canvas.height=canvasHeight;state={groups,old:points,now:points,box,image:null,joint:obj(id).joint_boundary||[],parent:obj(id).parent_guide};const im=new Image(),defs=$('art').querySelector('defs')?.outerHTML||'',url=URL.createObjectURL(new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="'+Math.ceil(box.right-box.x)+'" height="'+Math.ceil(box.bottom-box.y)+'" viewBox="'+[box.x,box.y,box.right-box.x,box.bottom-box.y].join(' ')+'">'+defs+copies.join('')+'</svg>'],{type:'image/svg+xml'}));
  im.onload=()=>{URL.revokeObjectURL(url);if(token!==stamp||!state)return;state.image=im;update(state.now);};im.src=url;
 }
 function mapper(old,now){
  return p=>{const w=old.map(q=>1/Math.max((p[0]-q[0])**2+(p[1]-q[1])**2,1e-8)**2),total=w.reduce((a,b)=>a+b,0);for(let i=0;i<w.length;i++)w[i]/=total;
   const a=[0,1].map(j=>old.reduce((v,q,i)=>v+w[i]*q[j],0)),b=[0,1].map(j=>now.reduce((v,q,i)=>v+w[i]*q[j],0));let dot=0,cross=0;
   for(let i=0;i<w.length;i++){const x=old[i][0]-a[0],y=old[i][1]-a[1],u=now[i][0]-b[0],v=now[i][1]-b[1];dot+=w[i]*(x*u+y*v);cross+=w[i]*(x*v-y*u);}
   const angle=Math.atan2(cross,dot),co=Math.cos(angle),si=Math.sin(angle),x=p[0]-a[0],y=p[1]-a[1];return [b[0]+co*x-si*y,b[1]+si*x+co*y];
  };
 }
 function jointMapper(){
  const old=state.old,now=state.now,pins=state.joint;let angle=0;
  if(Math.hypot(now[0][0]-old[0][0],now[0][1]-old[0][1])>1e-7&&state.parent.length){const u=CurveControls.projectPoint(old[0],state.parent).tangent,v=CurveControls.projectPoint(now[0],state.parent).tangent;angle=Math.atan2(u[0]*v[1]-u[1]*v[0],u[0]*v[0]+u[1]*v[1]);}
  const co=Math.cos(angle),si=Math.sin(angle),target=pins.map(p=>{const x=p[0]-old[0][0],y=p[1]-old[0][1];return [now[0][0]+co*x-si*y,now[0][1]+si*x+co*y];});
  return mapper([...old,...pins],[...now,...target]);
 }

 function triangle(s,d,im){const det=(s[1][0]-s[0][0])*(s[2][1]-s[0][1])-(s[2][0]-s[0][0])*(s[1][1]-s[0][1]);if(Math.abs(det)<1e-8)return;const coefficients=j=>{const a=((d[1][j]-d[0][j])*(s[2][1]-s[0][1])-(d[2][j]-d[0][j])*(s[1][1]-s[0][1]))/det,b=((s[1][0]-s[0][0])*(d[2][j]-d[0][j])-(s[2][0]-s[0][0])*(d[1][j]-d[0][j]))/det;return [a,b,d[0][j]-a*s[0][0]-b*s[0][1]];};const x=coefficients(0),y=coefficients(1),box=state.box;for(const k of [0,...PeriodicSvg.shifts(Math.min(...d.map(p=>p[0])),Math.max(...d.map(p=>p[0])))]){ctx.save();ctx.translate(k*695,0);ctx.beginPath();ctx.moveTo(...d[0]);ctx.lineTo(...d[1]);ctx.lineTo(...d[2]);ctx.closePath();ctx.clip();ctx.transform(x[0],y[0],x[1],y[1],x[2],y[2]);ctx.drawImage(im,box.x,box.y,box.right-box.x,box.bottom-box.y);ctx.restore();}}
 function repeatPreview(){const host=$('repeat'),svg=host.querySelector('svg');if(!svg||host.hidden)return;const count=designSettings.repeats,width=Math.min(4096,695*count),height=Math.max(1,Math.round(canvasHeight*width/(695*count))),style=getComputedStyle(host);if(repeatCanvas.width!==width)repeatCanvas.width=width;if(repeatCanvas.height!==height)repeatCanvas.height=height;host.style.position='relative';Object.assign(repeatCanvas.style,{left:style.paddingLeft,top:style.paddingTop,width:'calc(100% - '+(parseFloat(style.paddingLeft)+parseFloat(style.paddingRight))+'px)',height:'calc(100% - '+(parseFloat(style.paddingTop)+parseFloat(style.paddingBottom))+'px)'});if(repeatCanvas.parentNode!==host)host.appendChild(repeatCanvas);const repeatContext=repeatCanvas.getContext('2d');repeatContext.clearRect(0,0,width,height);for(let i=0;i<count;i++)repeatContext.drawImage(canvas,i*width/count,0,width/count,height);repeatCanvas.hidden=false;}
 function update(p){if(!state)return;state.now=p;if(frame||!state.image)return;frame=requestAnimationFrame(()=>{frame=0;if(!state)return;const t=performance.now(),map=jointMapper(),b=state.box;ctx.clearRect(0,0,695,canvasHeight);for(let y=b.y;y<b.bottom;y+=20)for(let x=b.x;x<b.right;x+=20){const xx=Math.min(x+20,b.right),yy=Math.min(y+20,b.bottom),s=[[x,y],[xx,y],[xx,yy],[x,yy]],d=s.map(map);triangle([s[0],s[1],s[2]],[d[0],d[1],d[2]],state.image);triangle([s[0],s[2],s[3]],[d[0],d[2],d[3]],state.image);}for(const g of state.groups)g.style.visibility='hidden';canvas.hidden=false;repeatPreview();canvas.dataset.frameMs=(performance.now()-t).toFixed(1);});}
 return {begin,update,stop};
})();
