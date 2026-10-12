/* Flow response normalization. Pure functions shared by page adapter and tests. */
(function(root){
 'use strict';
 function videoURL(value){
  try{const u=new URL(value);return u.protocol==='https:'&&/(^|\.)(flow-content\.google|googleusercontent\.com|googleapis\.com|googlevideo\.com|google\.com)$/.test(u.hostname)?u.href:null}catch(_){return null}
 }
 function urlIdentity(value){
  const safe=videoURL(value);if(!safe)return null;
  const u=new URL(safe);
  // The legacy batchexecute branch identifies /video/<media ID> responses.
  if(!u.pathname.includes('/video/'))return null;
  const id=decodeURIComponent(u.pathname.split('/').filter(Boolean).pop()||'');
  return id?{id,url:safe}:null;
 }
 function walk(input,visit){
  let budget=30000;const seen=new WeakSet();
  function run(v,depth){
   if(--budget<0||depth>32||v==null)return;
   if(typeof v==='string'){
    const t=v.trim();if(t.length>8*1024*1024)return;
    if(t.startsWith('https://')){visit(v);return;}
    const clean=t.replace(/^\)\]\}'\s*/,'').replace(/^for\s*\(\s*;;\s*\);/,'').trim();
    try{const parsed=JSON.parse(clean);if(parsed!==v)run(parsed,depth+1);return}catch(_){}
    // Google batchexecute has an XSSI prefix and length-prefixed JSON lines.
    if(clean.includes('\n'))for(const line of clean.split('\n'))if(/^[\[{]/.test(line.trim()))run(line.trim(),depth+1);
    return;
   }
   if(typeof v!=='object'||seen.has(v))return;seen.add(v);visit(v);
   for(const child of Object.values(v))run(child,depth+1);
  }
  run(input,0);
 }
 function failureEvidence(value){
  const seen=new WeakSet();let budget=500;
  function visit(v,depth=0){
   if(--budget<0||depth>10||v==null)return '';
   if(typeof v==='string')return /^(?:(?:MEDIA|VIDEO|GENERATION|STATUS|OPERATION|TASK|STATE)_)*(FAILED|FAILURE|CANCELLED|CANCELED|ERROR|REJECTED|BLOCKED|FILTERED|SAFETY_FILTERED)$/.test(v.toUpperCase())?v:'';
   if(typeof v!=='object'||seen.has(v))return '';seen.add(v);
   if(v.done===true&&v.error)return String(v.error.message||'GENERATION_FAILED');
   for(const [key,child] of Object.entries(v)){
    if(/history|previous|reference|input|thumbnail|poster|prompt|description/i.test(key))continue;
    if(/^(failed|isFailed|hasError)$/.test(key)&&child===true)return key;
    const hit=visit(child,depth+1);if(hit)return hit;
   }
   return '';
  }
  return visit(value);
 }
 function records(input){
  const found=new Map();
  walk(input,v=>{
   if(typeof v==='string'){
    const hit=urlIdentity(v);if(hit)found.set(hit.id,{...hit,status:'ready',media_id:hit.id,evidence:'video_url'});return;
   }
   if(Array.isArray(v))return;
   const op=v.operation||v,media=op.response?.video||op.response?.media||v.video||(!Array.isArray(v.media)&&v.media);
   const status=String(v.mediaMetadata?.mediaStatus?.mediaGenerationStatus||v.mediaStatus?.mediaGenerationStatus||v.mediaGenerationStatus||v.generationStatus||v.state||v.status||op.status||'').toUpperCase();
   const failed=Boolean(failureEvidence(v))||/(?:^|_)(FAILED|FAILURE|CANCELLED|CANCELED|ERROR|REJECTED)$/.test(status)||(op.done===true&&!!op.error);
   const ready=/(?:^|_)(SUCCESSFUL|SUCCEEDED|COMPLETE|COMPLETED|SUCCESS)$/.test(status)||(op.done===true&&!op.error&&!!media);
   if(!ready&&!failed)return;
   const ids=[v.name,v.id,v.workflowId,v.operationId,op.name,media?.name,media?.id].filter(x=>typeof x==='string'&&x);
   const url=videoURL(media?.fifeUrl||media?.url||media?.uri||v.fifeUrl||v.url);
   const mediaId=media?.name||media?.id||urlIdentity(url)?.id||v.name||v.id;
   for(const id of ids)found.set(id,{id,status:failed?'failed':'ready',media_id:mediaId,url:ready?url:null,evidence:'status',error:failed?String(op.error?.message||v.error?.message||status):''});
  });return [...found.values()];
 }
 function requestIds(body,excluded=[]){
  let payload;try{payload=new URLSearchParams(String(body||'')).get('f.req')}catch(_){};
  if(!payload)return [];
  const omit=new Set(excluded);
  return [...new Set(payload.match(/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/gi)||[])].filter(id=>!omit.has(id));
 }
 // A catalog item ID can differ from the /video/ file ID. Only link a
 // unique video URL contained in that very item, excluding historical outputs.
 function catalogLinks(item, observed=new Map()){
  if(item?.type!=='VIDEO'||typeof item.id!=='string')return {rows:[],reason:'not_video'};
  // Live diagnostic evidence: catalog id == workflowId, current rb.id ==
  // captured CDN file id; rb.workflowId points back to the catalog item.
  // Only current result fields may propagate failure to the catalog task ID.
  const nestedFailure=failureEvidence(item);
  if(nestedFailure)return {rows:[{id:item.id,status:'failed',evidence:'catalog_current_failure',error:nestedFailure}],reason:'generation_failed'};
  const directStatus=String(item.status||item.mediaGenerationStatus||item.mediaMetadata?.mediaStatus?.mediaGenerationStatus||'').toUpperCase();
  if(/(?:^|_)(FAILED|FAILURE|CANCELLED|CANCELED|ERROR|REJECTED)$/.test(directStatus))return {rows:[{id:item.id,status:'failed',evidence:'catalog_status',error:item.error?.message||directStatus}],reason:'generation_failed'};
  const current=Object.entries(item).filter(([key,v])=>key!=='history' && v && typeof v==='object' && !Array.isArray(v) && v.workflowId===item.id && typeof v.id==='string' && v.id!==item.id);
  const currentIds=[...new Set(current.map(([,v])=>v.id))];
  if(item.workflowId===item.id && currentIds.length===1){
    const fileId=currentIds[0], result=observed.get(fileId);
    if(result?.status==='failed')return {rows:[{...result,id:item.id,media_id:fileId}],reason:'generation_failed'};
    if(result?.status==='ready' && urlIdentity(result.url)?.id===fileId){
      return {rows:[{...result,id:item.id,media_id:fileId,evidence:'workflow_file_id',link_paths:current.map(([key])=>'item.'+key+'.id')}],reason:'linked_workflow_file',paths:current.map(([key])=>({path:'item.'+key+'.id',file_id:fileId}))};
    }
  }
  const directResults=records(Object.fromEntries(Object.entries(item).filter(([key])=>!/history|previous|reference|input|prompt/i.test(key))));
  const success=directResults.find(row=>row.status==='ready' && (row.id===item.id || currentIds.length===1&&row.id===currentIds[0]));
  if(success)return {rows:[{...success,id:item.id,media_id:success.media_id||currentIds[0]||item.id}],reason:'current_success_status'};
  const candidates=new Map(),paths=[],seen=new WeakSet();let budget=2000;
  function visit(v,path,depth){
   if(--budget<0||depth>12||v==null)return;
   if(typeof v==='string'){
    const hit=urlIdentity(v);
    if(hit){candidates.set(hit.id,hit);paths.push({path,file_id:hit.id});}
    return;
   }
   if(typeof v!=='object'||seen.has(v))return;seen.add(v);
   for(const [k,c] of Object.entries(v)){
    if(/history|previous|reference|input|thumbnail|poster/i.test(k))continue;
    visit(c,path+'.'+k,depth+1);
   }
  }
  visit(item,'item',0);
  const values=[...candidates.values()];
  return {rows:values.length===1?[{id:item.id,media_id:values[0].id,url:values[0].url,status:'ready',evidence:'catalog_video_url',link_paths:paths.map(p=>p.path)}]:[],reason:values.length===1?'linked':values.length?'ambiguous_video_urls':'no_current_video_url',paths};
 }
 function catalogShape(item){
  // Field types and IDs only; do not export script text or signed URLs.
  const fields=[];const seen=new WeakSet();let budget=160;
  function visit(v,path,depth){
   if(--budget<0||depth>5)return;
   if(v&&typeof v==='object'){
    if(seen.has(v))return;seen.add(v);
    fields.push({path,type:Array.isArray(v)?'array':'object',size:Object.keys(v).length});
    for(const [k,c]of Object.entries(v)){if(k==='history')continue;visit(c,path+'.'+k,depth+1);}return;
   }
   const field={path,type:typeof v};
   if(typeof v==='string'){
    if(/^[0-9a-f-]{36}$/i.test(v)||/^(VIDEO|IMAGE|SUCCESSFUL|FAILED|PENDING|COMPLETE|RUNNING)$/.test(v))field.value=v;
    else if(v.startsWith('https://')){try{const u=new URL(v);field.value=u.origin+u.pathname}catch(_){}}
   }
   fields.push(field);
  }
  visit(item,'item',0);return fields;
 }
 // Match a full prompt on the current video record, never a title, substring or history.
 function exactPromptVideoIds(catalog,prompt,excluded=[]){
  const normalize=v=>String(v||'').normalize('NFC').replace(/\r\n/g,'\n').trim();
  const wanted=normalize(prompt);if(wanted.length<30)return [];
  const omit=new Set(excluded),ids=new Set();
  for(const item of catalog||[]){
   if(item?.type!=='VIDEO'||typeof item.id!=='string'||omit.has(item.id))continue;
   let budget=1500;const seen=new WeakSet();
   function matches(v,depth=0){
    if(--budget<0||depth>12)return false;
    if(typeof v==='string')return normalize(v)===wanted;
    if(!v||typeof v!=='object'||seen.has(v))return false;seen.add(v);
    return Object.entries(v).some(([k,child])=>!/history|previous|reference|input|thumbnail|poster|displayName|title/i.test(k)&&matches(child,depth+1));
   }
   if(matches(item))ids.add(item.id);
  }
  return [...ids];
 }
 root.FlowStudioResults={exactPromptVideoIds,failureEvidence,records,walk,videoURL,urlIdentity,requestIds,catalogLinks,catalogShape};
 if(typeof module==='object')module.exports=root.FlowStudioResults;
})(globalThis);
