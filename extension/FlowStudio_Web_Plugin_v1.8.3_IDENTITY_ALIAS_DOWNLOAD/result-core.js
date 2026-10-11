/* Flow response normalization. Pure functions shared by page adapter and tests. */
(function(root){
 'use strict';
 function videoURL(value){
  try{const u=new URL(value);return u.protocol==='https:'&&/(^|\.)(flow-content\.google|googleusercontent\.com|googleapis\.com|googlevideo\.com|google\.com)$/.test(u.hostname)?u.href:null}catch(_){return null}
 }
 function mediaKind(value){return ['VIDEO','IMAGE'].includes(String(value||'').toUpperCase())?String(value).toUpperCase():'UNKNOWN';}
 function ignoredResultKey(key){return /history|previous|reference|input|thumbnail|poster|preview|prompt|description/i.test(key);}
 function mediaMismatch(detail){if(typeof console!=='undefined')console.info('[FlowStudio result]',{stage:'RESULT_MEDIA_KIND_MISMATCH',...detail});}
 function urlIdentity(value){
  const safe=videoURL(value);if(!safe)return null;
  const u=new URL(safe),video=u.pathname.includes('/video/'),image=u.pathname.includes('/image/');
  if(video===image)return null;
  let id;try{id=decodeURIComponent(u.pathname.split('/').filter(Boolean).pop()||'');}catch(_){return null;}
  return id?{id,url:safe,media_kind:video?'VIDEO':'IMAGE'}:null;
 }
 function walk(input,visit,skipKey=()=>false){
  let budget=30000;const seen=new WeakSet();
  function run(v,depth,hint='UNKNOWN'){
   if(--budget<0||depth>32||v==null)return;
   if(typeof v==='string'){
    const t=v.trim();if(t.length>8*1024*1024)return;
    if(t.startsWith('https://')){visit(v,hint);return;}
    const clean=t.replace(/^\)\]\}'\s*/,'').replace(/^for\s*\(\s*;;\s*\);/,'').trim();
    try{const parsed=JSON.parse(clean);if(parsed!==v)run(parsed,depth+1,hint);return}catch(_){}
    if(clean.includes('\n'))for(const line of clean.split('\n'))if(/^[\[{]/.test(line.trim()))run(line.trim(),depth+1,hint);
    return;
   }
   if(typeof v!=='object'||seen.has(v))return;seen.add(v);
   const ownKind=mediaKind(v.media_kind||v.type),kind=ownKind==='UNKNOWN'?hint:ownKind;
   visit(v,kind);
   for(const [key,child]of Object.entries(v))if(!skipKey(key))run(child,depth+1,key==='video'?'VIDEO':key==='image'?'IMAGE':kind);
  }
  run(input,0);
 }
 function failureEvidence(value,expected=mediaKind(value?.type||value?.media_kind)){
  const seen=new WeakSet();let budget=500;
  function visit(v,depth=0){
   if(--budget<0||depth>10||v==null)return '';
   if(typeof v==='string')return /^(?:(?:MEDIA|VIDEO|GENERATION|STATUS|OPERATION|TASK|STATE)_)*(FAILED|FAILURE|CANCELLED|CANCELED|ERROR|REJECTED|BLOCKED|FILTERED|SAFETY_FILTERED)$/.test(v.toUpperCase())?v:'';
   if(typeof v!=='object'||seen.has(v))return '';seen.add(v);
   const kind=mediaKind(v.type||v.media_kind);if(expected!=='UNKNOWN'&&kind!=='UNKNOWN'&&kind!==expected)return '';
   if(v.done===true&&v.error)return String(v.error.message||'GENERATION_FAILED');
   for(const [key,child] of Object.entries(v)){
    if(ignoredResultKey(key)||(expected==='VIDEO'&&key==='image'))continue;
    if(/^(failed|isFailed|hasError)$/.test(key)&&child===true)return key;
    const hit=visit(child,depth+1);if(hit)return hit;
   }
   return '';
  }
  return visit(value);
 }
 function currentURLKinds(input){
  const kinds=new Set(),seen=new WeakSet();let budget=1000;
  function visit(v,depth){
   if(--budget<0||depth>12||v==null)return;
   if(typeof v==='string'){const hit=urlIdentity(v);if(hit)kinds.add(hit.media_kind);return;}
   if(typeof v!=='object'||seen.has(v))return;seen.add(v);
   const kind=mediaKind(v.type||v.media_kind);if(depth>0&&kind!=='UNKNOWN'){kinds.add(kind);return;}
   for(const [key,child]of Object.entries(v))if(!ignoredResultKey(key)){
    if(child&&(key==='video'||key==='image'))kinds.add(key==='video'?'VIDEO':'IMAGE');
    else visit(child,depth+1);
   }
  }
  visit(input,0);return kinds;
 }
 function records(input){
  const found=new Map();
  function save(row){
   const key=row.media_kind+'|'+row.id,previous=found.get(key);
   if(previous?.status==='failed'&&row.status==='ready')return;
   // Keep status evidence/aliases when the later traversal reaches the same URL.
   if(previous?.evidence?.includes('status')&&row.evidence.endsWith('_url'))return;
   found.set(key,row);
  }
  walk(input,(v,hint)=>{
   if(typeof v==='string'){
    const hit=urlIdentity(v);if(hit)save({...hit,status:'ready',media_id:hit.id,evidence:'video_url'});return;
   }
   if(Array.isArray(v))return;
   const op=v.operation||v,declared=mediaKind(v.media_kind||v.type||op.type),expected=declared==='UNKNOWN'?hint:declared;
   const branches=[],seen=new Set();
   function add(media,kind){if(!media||typeof media!=='object'||Array.isArray(media)||seen.has(media))return;seen.add(media);branches.push({media,kind});}
   // Parse both response branches independently, never image || video.
   add(op.response?.video,'VIDEO');add(op.response?.image,'IMAGE');
   add(v.video,'VIDEO');add(v.image,'IMAGE');
   add(op.response?.media,mediaKind(op.response?.media?.type));add(v.media,mediaKind(v.media?.type));
   const status=String(v.mediaMetadata?.mediaStatus?.mediaGenerationStatus||v.mediaStatus?.mediaGenerationStatus||v.mediaGenerationStatus||v.generationStatus||v.state||v.status||op.status||'').toUpperCase();
   const failedStatus=/(?:^|_)(FAILED|FAILURE|CANCELLED|CANCELED|ERROR|REJECTED)$/.test(status)||(op.done===true&&!!op.error);
   const failed=Boolean(failureEvidence(v,expected))||failedStatus;
   const ready=/(?:^|_)(SUCCESSFUL|SUCCEEDED|COMPLETE|COMPLETED|SUCCESS)$/.test(status)||(op.done===true&&!op.error&&branches.length>0);
   if(!ready&&!failed)return;
   if(ready&&!failed&&!branches.length&&expected!=='UNKNOWN'){
    const kinds=currentURLKinds(v);
    if(kinds.size&&!kinds.has(expected)){mediaMismatch({id:v.id||op.name||'',catalog_type:declared,media_kind:[...kinds][0],url_type:[...kinds][0]});return;}
   }
   const parsed=(branches.length?branches:[{media:v,kind:expected}]).map(branch=>{
    const url=videoURL(branch.media.fifeUrl||branch.media.url||branch.media.uri||(!branches.length&&(v.fifeUrl||v.url)));
    const hit=urlIdentity(url),own=mediaKind(branch.media.media_kind||branch.media.type);
    const kind=branch.kind!=='UNKNOWN'?branch.kind:own!=='UNKNOWN'?own:hit?.media_kind||expected;
    if((hit&&kind!=='UNKNOWN'&&hit.media_kind!==kind)||(expected!=='UNKNOWN'&&kind!=='UNKNOWN'&&expected!==kind)){
     mediaMismatch({id:v.id||op.name||'',catalog_type:declared,media_kind:kind,url_type:hit?.media_kind||'UNKNOWN'});return null;
    }
    if(!failed&&kind==='UNKNOWN')return null;
    return {...branch,url,hit,kind};
   }).filter(Boolean);
   const kinds=new Set(parsed.map(row=>row.kind));
   const identities=new Set(parsed.map(row=>row.media.name||row.media.id||row.hit?.id).filter(Boolean));
   const allowAliases=kinds.size===1&&identities.size<=1;
   for(const row of parsed){
    const media=row.media,mediaId=media.name||media.id||row.hit?.id||v.name||v.id||op.name;
    const ownIds=[media.name,media.id,row.hit?.id];
    const aliases=allowAliases?[v.name,v.id,branches.length?v.workflowId:null,v.operationId,op.name]:[];
    const branchFailed=branches.length?(failedStatus||Boolean(failureEvidence(media,row.kind))):failed;
    for(const id of new Set([...ownIds,...aliases].filter(x=>typeof x==='string'&&x)))save({id,status:branchFailed?'failed':'ready',media_id:mediaId,url:ready?row.url:null,media_kind:row.kind,evidence:branches.length?'video_object_status':'status',error:branchFailed?String(op.error?.message||media.error?.message||v.error?.message||status):''});
   }
  },ignoredResultKey);
  return [...found.values()].filter(row=>row.media_kind!=='IMAGE');
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
  if(item?.type!=='VIDEO'||typeof item.id!=='string')return {rows:[],reason:'not_media'};
  const expected='VIDEO';
  function accepted(row){
   const urlKind=urlIdentity(row?.url)?.media_kind||'UNKNOWN',kind=mediaKind(row?.media_kind);
   const actual=kind==='UNKNOWN'?urlKind:kind;
   if(actual!==expected||(urlKind!=='UNKNOWN'&&urlKind!==expected)){
    mediaMismatch({id:item.id,catalog_type:expected,media_kind:actual,url_type:urlKind});return false;
   }
   return true;
  }
  function result(row,reason,extra={}){return {rows:[{...row,id:item.id,media_kind:expected,catalog_type:expected}],reason,...extra};}
  const nestedFailure=failureEvidence(item);
  if(nestedFailure)return result({status:'failed',evidence:'catalog_current_failure',error:nestedFailure},'generation_failed');
  const directStatus=String(item.status||item.mediaGenerationStatus||item.mediaMetadata?.mediaStatus?.mediaGenerationStatus||'').toUpperCase();
  if(/(?:^|_)(FAILED|FAILURE|CANCELLED|CANCELED|ERROR|REJECTED)$/.test(directStatus))return result({status:'failed',evidence:'catalog_status',error:item.error?.message||directStatus},'generation_failed');
  const current=Object.entries(item).filter(([key,v])=>!ignoredResultKey(key)&&v&&typeof v==='object'&&!Array.isArray(v)&&v.workflowId===item.id&&typeof v.id==='string'&&v.id!==item.id&&
    (mediaKind(v.type||v.media_kind)==='UNKNOWN'||mediaKind(v.type||v.media_kind)===expected)&&
    (!currentURLKinds(v).size||currentURLKinds(v).has(expected)));
  const currentIds=[...new Set(current.map(([,v])=>v.id))];
  if(item.workflowId===item.id&&currentIds.length===1){
   const fileId=currentIds[0],row=observed.get(fileId);
   if(row?.status==='failed'&&(mediaKind(row.media_kind)==='UNKNOWN'||accepted(row)))return result({...row,media_id:fileId},'generation_failed');
   if(row?.status==='ready'&&urlIdentity(row.url)?.id===fileId&&accepted(row))return result({...row,media_id:fileId,evidence:'workflow_file_id',link_paths:current.map(([key])=>'item.'+key+'.id')},'linked_workflow_file',{paths:current.map(([key])=>({path:'item.'+key+'.id',file_id:fileId}))});
  }
  const candidates=new Map(),paths=[],seen=new WeakSet();let budget=2000,wrongKindSeen=false;
  function visit(v,path,depth){
   if(--budget<0||depth>12||v==null)return;
   if(typeof v==='string'){
    const hit=urlIdentity(v);
    if(hit){
     if(hit.media_kind!==expected){wrongKindSeen=true;mediaMismatch({id:item.id,catalog_type:expected,media_kind:hit.media_kind,url_type:hit.media_kind});return;}
     candidates.set(hit.id,hit);paths.push({path,file_id:hit.id});
    }
    return;
   }
   if(typeof v!=='object'||seen.has(v))return;seen.add(v);
   const kind=mediaKind(v.type||v.media_kind);
   if(kind!=='UNKNOWN'&&kind!==expected){wrongKindSeen=true;mediaMismatch({id:item.id,catalog_type:expected,media_kind:kind,url_type:'UNKNOWN'});return;}
   for(const [key,child]of Object.entries(v)){
    if(ignoredResultKey(key))continue;
    const branch=key==='video'?'VIDEO':key==='image'?'IMAGE':'UNKNOWN';
    if(branch!=='UNKNOWN'&&branch!==expected){wrongKindSeen=true;mediaMismatch({id:item.id,catalog_type:expected,media_kind:branch,url_type:'UNKNOWN'});continue;}
    visit(child,path+'.'+key,depth+1);
   }
  }
  visit(item,'item',0);
  const directResults=records(item).filter(row=>row.status==='ready'&&accepted(row)&&
    (row.id===item.id||(currentIds.length===1&&row.id===currentIds[0]))&&
    (!wrongKindSeen||row.url||row.evidence==='video_object_status'));
  const successIds=new Set(directResults.map(row=>row.media_id||row.id));
  if(successIds.size>1)return {rows:[],reason:'ambiguous_media_results',paths};
  if(directResults.length){const row=directResults[0];return result({...row,media_id:row.media_id||currentIds[0]||item.id},'current_success_status');}
  const values=[...candidates.values()];
  if(values.length===1)return result({media_id:values[0].id,url:values[0].url,status:'ready',evidence:'catalog_video_url',link_paths:paths.map(p=>p.path)},'linked',{paths});
  return {rows:[],reason:values.length?'ambiguous_video_urls':wrongKindSeen?'RESULT_MEDIA_KIND_MISMATCH':'no_current_video_url',paths};
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
    if(/^[0-9a-f-]{36}$/i.test(v)||/^(VIDEO|SUCCESSFUL|FAILED|PENDING|COMPLETE|RUNNING)$/.test(v))field.value=v;
    else if(v.startsWith('https://')){try{const u=new URL(v);field.value=u.origin+u.pathname}catch(_){}}
   }
   fields.push(field);
  }
  visit(item,'item',0);return fields;
 }
 // Match a full prompt on the current video record, never a title, substring or history.
 function exactPromptVideoIds(catalog,prompt,excluded=[],kind="VIDEO"){
  const normalize=v=>String(v||'').normalize('NFC').replace(/\r\n/g,'\n').trim();
  const wanted=normalize(prompt);if(wanted.length<30)return [];
  const omit=new Set(excluded),ids=new Set();
  for(const item of catalog||[]){
   if(item?.type!==kind||typeof item.id!=='string'||omit.has(item.id))continue;
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
