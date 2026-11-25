import {useEffect, useRef, useState} from 'react';
import type {Item, Params} from './types';

export type Translate = (english: string, chinese: string) => string;
export type Side = 'A' | 'B';
export type View = 'home' | 'studio' | 'compare' | 'collection' | 'editor' | 'appearance' | 'research';
export type Catalog = {prototypes: {id: string; preview: Item}[]};
export type Assets = {items: Item[]; total: number};
export type Reference = {kind: 'asset' | 'job' | 'edit'; id: string};
export type Job = {
 job_id: string; state: string; queue_position?: number; target: 'main' | Side;
 continuation?: Params;
};
export const DEFAULT: Params = {prototype:'SW1-A',variant:'expanded',density:'medium',control:'soft',seed:20260920};
export const PROTOTYPES = ['SW1-A','SW1-B','SW1-C','SW2-A','SW3-A','SW3-B'];
export const FEATURED = 'sw1-C-01';
export const featuredMedia = {
 rendering:'/media/pairs/renderings/'+FEATURED+'.png',
};
export const ROLES = [
 ['backbone','var(--curve-vine)','Main vine','主藤'],
 ['flower_anchor','var(--curve-flower)','Flower sites','花位'],
 ['flower_support','var(--curve-support)','Flower-bearing paths','承花路径'],
 ['L1','var(--curve-parent)','Parent branches','父枝'],
 ['L2','var(--curve-child)','Child branches','子枝'],
] as const;
export function displayCatalogId(id:string) {
 const match=/^(sw\d)-([a-z])(?:-(\d+))?$/i.exec(id);
 return match?match[1].toUpperCase()+'–'+match[2].toUpperCase()+(match[3]?' · '+match[3]:''):id;
}
export function catalogSearch(query:string) {
 const match=/^(sw\d)[\s–-]*([a-z])(?:\s*[·–-]\s*(\d+))?$/i.exec(query.trim());
 return match?match[1].toLowerCase()+'-'+match[2].toUpperCase()+(match[3]?'-'+match[3]:''):query;
}
export const assetRoute = (id:string) => '#/collection/'+encodeURIComponent(id);
export function parseRoute(hash:string) {
 const [path, query] = hash.slice(1).split('?');
 const [section, id] = (path||'').split('/').filter(Boolean);
 const valid: View[] = ['studio','compare','collection','editor','appearance','research'];
 let pairId = '';
 try { if(section==='collection' && id) pairId=decodeURIComponent(id); } catch {}
 return {view:valid.find(v=>v===section)||'home' as View, pairId, query:new URLSearchParams(query), hash};
}
export function stored<T>(key:string, fallback:T):T {
 try {return JSON.parse(localStorage.getItem(key)||'null')??fallback;} catch {return fallback;}
}
export function referenceFor(item:Item):Reference|null {
 if(item.edit_id) return {kind:'edit',id:item.edit_id};
 if(item.job_id) return {kind:'job',id:item.job_id};
 return item.asset_id?{kind:'asset',id:item.asset_id}:null;
}
export class ApiError extends Error {
 constructor(message:string, readonly status:number){super(message);}
}
export async function api<T>(path:string, options:RequestInit={}):Promise<T> {
 const r = await fetch('/api/v1'+path,options);
 if(!r.ok) {
  const detail = await r.json().catch(()=>null);
  throw new ApiError(typeof detail?.detail==='string'?detail.detail:'HTTP '+r.status,r.status);
 }
 return r.json();
}
export function post<T>(path:string, body:unknown) {
 return api<T>(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}

export function useGeneration(onResult:(item:Item,target:Job['target'])=>void,t:Translate) {
 const [job,setJob] = useState<Job|null>(()=>stored('papera-active-job-v2',null));
 const [submitting,setSubmitting] = useState(false);
 const [error,setError] = useState('');
 const [recovering,setRecovering] = useState(false);
 const present=useRef({onResult,t});
 present.current={onResult,t};
 const active=useRef(false);
 const lastRequest=useRef<{payload:Params;target:Job['target'];continuation?:Params}|null>(null);
 async function start(payload:Params,target:Job['target'],continuation?:Params) {
  if(active.current) return;
  active.current=true;
  lastRequest.current={payload,target,continuation};
  setError('');setSubmitting(true);
  try {const handle=await post<Job>('/jobs',payload);setJob({...handle,target,continuation});}
  catch(e){setError((e as Error).message);}
  finally{active.current=false;setSubmitting(false);}
 }
 useEffect(()=>{
  if(job) localStorage.setItem('papera-active-job-v2',JSON.stringify(job));
  else localStorage.removeItem('papera-active-job-v2');
 },[job]);
 useEffect(()=>{
  if(!job) return;
  const pinned=job;
  const controller=new AbortController();
  let timer:number|undefined;
  async function poll(){
   try{
    const state=await api<{state:string;queue_position?:number;result:Item;error?:string}>('/jobs/'+pinned.job_id,{signal:controller.signal});
    if(controller.signal.aborted)return;
    setRecovering(false);
    if(state.state==='succeeded'){
     present.current.onResult(state.result,pinned.target);
     if(!pinned.continuation){setJob(null);return;}
     const next=pinned.continuation;
     const condition=await post<{condition_id:string}>('/conditions',{job_id:state.result.job_id});
     const payload={...next,prototype:state.result.prototype,variant:state.result.parameters.variant,condition_id:condition.condition_id};
     lastRequest.current={payload,target:'B'};
     const generated=await post<Job>('/jobs',payload);
     setJob({...generated,target:'B'});
     return;
    }
    if(['failed','interrupted','expired'].includes(state.state)){
     setError(state.error||present.current.t('Generation did not finish.','生成未完成。'));setJob(null);return;
    }
    setJob(current=>current?{...current,state:state.state,queue_position:state.queue_position}:null);
    timer=window.setTimeout(poll,1500);
   }catch(e){
    if(controller.signal.aborted)return;
    if(e instanceof ApiError && e.status===404 || pinned.continuation && e instanceof ApiError && e.status<500){
     setError(present.current.t('This generation session is no longer available.','当前生成记录已失效，请重新生成。'));setJob(null);return;
    }
    setRecovering(true);
    timer=window.setTimeout(poll,2500);
   }
  }
  void poll();
  return()=>{controller.abort();window.clearTimeout(timer);setRecovering(false);};
 },[job?.job_id]);
 function retry(){
  const request=lastRequest.current;
  if(request&&!job)void start(request.payload,request.target,request.continuation);
 }
 return {job,submitting,busy:!!job||submitting,error,recovering,start,retry,canRetry:!!error&&!!lastRequest.current,clear:()=>setError('')};
}
