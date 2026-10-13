// Persistent download registry. Uses Chrome's configured default download directory.
const dlDiagnostics=new Map();
let dlTickFlight=null,dlLastTick=0;
const dlResultCache=new Map();
function dlBounded(promise,label,ms=12000){
 let timer;return Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(label+'_TIMEOUT')),ms);})]).finally(()=>clearTimeout(timer));
}

const DL_KEY='flowStudioDownloadsV0921';
let dlState={entries:[],counters:{}},dlSerial=Promise.resolve(),dlPumping=false;
const dlLoaded=chrome.storage.local.get(DL_KEY).then(data=>{if(data[DL_KEY])dlState=data[DL_KEY]});
// Bounded persistent diagnostics; omit prompts and signed query strings.
function dlLog(stage, detail={}) {
 const row={time:new Date().toISOString(),stage,...detail};
 console.info('[FlowStudio download]',row);
 return dlMutate(()=>{dlState.logs=dlState.logs||[];dlState.logs.push(row);dlState.logs=dlState.logs.slice(-1000);});
}
function dlEntry(e){return {group:e.group,task_id:e.info?.task_id,media_id:e.media_id,status:e.status,filename:e.filename,download_id:e.download_id,attempts:e.attempts,segment_id:e.info?.segment_id,attempt_started_at:e.attempt_started_at||0,uncertain_at:e.uncertain_at||0,submitted_at:e.submitted_at||0,confirmed_at:e.confirmed_at||0,error:e.error,url:dlRedactURL(e.url)};}
function dlRedactURL(value){try{const u=new URL(value);return u.origin+u.pathname}catch(_){return null;}}
async function dlReport(sender){await dlLoaded;await dlSerial;const group=dlGroup(sender.tab.url);return {version:'0.9.66',exported_at:new Date().toISOString(),group,entries:dlState.entries.filter(e=>e.group===group).map(dlEntry),scan:dlDiagnostics.get(group)||null,logs:(dlState.logs||[]).filter(e=>!e.group||e.group===group)};}
function dlMutate(fn){const p=dlSerial.then(async()=>{await dlLoaded;const value=await fn();await chrome.storage.local.set({[DL_KEY]:dlState});return value});dlSerial=p.catch(()=>{});return p;}
function dlSafe(value){return String(value||'集合').normalize('NFC').replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').replace(/\.{2,}/g,'_').replace(/[. ]+$/g,'').slice(0,80)||'集合';}
function dlGroup(url){const u=new URL(url);return u.origin+u.pathname.replace(/\/+$/,'');}
function dlHash(text){let h=2166136261;for(const c of text)h=Math.imul(h^c.charCodeAt(0),16777619);return (h>>>0).toString(16).padStart(8,'0');}
async function dlReserve(msg,sender){
 const group=dlGroup(sender.tab.url), info=msg.info||{};
 const doc=Number(info.document_number);if(!Number.isInteger(doc)||doc<1)throw Error('无效文案编号');
 // Display numbers such as 01-01 repeat across hosts; segment_id is global.
 const key=JSON.stringify([group,info.command_id,info.segment_id??info.task_name??info.task_id,info.round]);
 return dlMutate(()=>{
  let entry=dlState.entries.find(x=>x.key===key);
  if(!entry && info.segment_id!=null) entry=dlState.entries.find(x=>x.group===group && x.info?.command_id===info.command_id && String(x.info?.segment_id)===String(info.segment_id) && Number(x.info?.round||1)===Number(info.round||1));
  if(entry)return {...entry,existing:true};
  const channel=dlSafe(info.channel_key||'CH');
  const folder=String(info.download_folder||('FlowStudio_Channels/'+channel)).replace(/^\/+|\/+$/g,'');
  const requested=dlSafe(info.download_name||info.task_name||info.task_id||('task-'+Date.now()));
  const filename=folder+'/'+requested+'.mp4';
  entry={key,group,folder,document_number:doc,part:Number(info.dispatch_order||1),filename,sequence:dlState.entries.length,created_at:Date.now(),status:'reserved',attempts:0,info};
  dlState.entries.push(entry);
  dlState.logs=dlState.logs||[];dlState.logs.push({time:new Date().toISOString(),stage:'reserve_exact_name',group,channel,task_id:info.task_id,task_name:info.task_name,filename,command_id:info.command_id,round:info.round});dlState.logs=dlState.logs.slice(-1500);
  return entry;
 });
}
async function dlBind(msg){
 const entry=await dlMutate(()=>{
  const e=dlState.entries.find(x=>x.key===msg.key);if(!e)throw Error('下载任务未登记');
  const ids=[...new Set((msg.ids||[]).filter(x=>typeof x==='string'))];
  if(ids.length!==1)throw Error('下载需要单个视频ID，收到 '+ids.length);
  if(dlState.entries.some(other=>other.key!==e.key && other.media_id===ids[0] && String(other.info?.segment_id)!==String(e.info?.segment_id)))throw Error('RESULT_ID_CONFLICT:同一生成结果不能绑定两个片段，请核对原任务');
  if(e.media_id && e.media_id!==ids[0])throw Error('GENERATION_ID_CONFLICT');
  if(e.status==='cancelled')throw Error('COMMAND_CANCELLED');
  e.media_id=ids[0];e.confirmed_at=e.confirmed_at||Date.now();e.submitted_at=e.submitted_at||e.confirmed_at;e.uncertain_at=0;
  if(e.status==='reserved')e.status='waiting';return e;
 });
 const cached=dlResultCache.get(entry.group+'|'+entry.media_id) || (dlState.observations||{})[entry.group+'|'+entry.media_id];
 if(cached)await dlObserve({rows:[cached]}, {tab:{url:entry.group}});
 return entry;
}
async function dlObserve(msg,sender){
 const group=dlGroup(sender.tab.url), failed=[];
 if(msg.diagnostics){
  dlDiagnostics.set(group,{...msg.diagnostics,time:Date.now()});
  while(dlDiagnostics.size>100)dlDiagnostics.delete(dlDiagnostics.keys().next().value);
 }
 const relevant=(msg.rows||[]).filter(row=>row && typeof row.id==='string' && ['ready','failed'].includes(row.status));
 if(!relevant.length)return;
 await dlMutate(()=>{
  dlState.observations=dlState.observations||{};
  for(const row of relevant){
   const key=group+'|'+row.id;dlResultCache.set(key,row);dlState.observations[key]={...row,observed_at:Date.now()};
  }
  const keys=Object.keys(dlState.observations);
  for(const key of keys.slice(0,Math.max(0,keys.length-600)))delete dlState.observations[key];
  while(dlResultCache.size>600)dlResultCache.delete(dlResultCache.keys().next().value);
  for(const row of msg.rows||[])for(const e of dlState.entries){
   if(e.group!==group || e.media_id!==row.id || !['waiting','ready'].includes(e.status))continue;
   if(row.status==='failed'){e.status='failed';e.failure_kind='generation';e.error=row.error||'Flow 视频生成失败';e.failure_reported=false;failed.push(e);continue;}
   if(row.status==='ready'){
    // Same redirect endpoint used by the supplied legacy plugin; never accept arbitrary page URLs.
    const direct=dlVideoURL(row.url);
    // Legacy v1.0.6 behavior: once Flow reports SUCCESSFUL, hand the
    // authenticated Flow redirect URL directly to chrome.downloads. Do not
    // preflight it with service-worker fetch; that request has different
    // navigation/cookie behavior and may return the Flow HTML shell.
    e.url=direct || 'https://flow.google.com/fx/api/trpc/media.getMediaUrlRedirect?name='+encodeURIComponent(row.media_id || e.media_id);
    e.status='ready';
    e.probe_message=direct?'Flow 内部已返回视频文件地址':'Flow 已完成，使用原生媒体重定向下载';
   }
  }
 });for(const e of failed){await dlEvent(e,'generation_task_failed',{event_id:'flow-generation-failed:'+e.key,state:'failed',message:e.error,failure_kind:'generation'});await dlMutate(()=>{e.failure_reported=true});}void dlPump();
}
function dlEvent(e,type,extra={}){return Promise.resolve().then(()=>pushEvent({...e.info,type,event_id:type+':'+e.key+':'+String(extra.download_id??e.download_id??e.attempts??0),filename:e.filename,media_id:e.media_id,document_number:e.document_number,part_number:e.part,...extra}));}
function dlVideoURL(value){
 try{const u=new URL(value);return u.protocol==='https:'&& /(^|\.)(flow-content\.google|googleusercontent\.com|googleapis\.com|googlevideo\.com|google\.com)$/.test(u.hostname)?u.href:null}catch(_){return null}
}
async function dlStartDownload(entry){
  const filename=String(entry.filename||'');
  const options={url:entry.url,filename,saveAs:false,conflictAction:'overwrite'};
  try{return await chrome.downloads.download(options);}
  catch(error){
    const message=String(error?.message||error);
    if(!/conflictAction|illegal|filename|invalid/i.test(message))throw error;
    return await chrome.downloads.download({url:entry.url,filename:filename.split(/[\\/]/).pop()||filename,saveAs:false});
  }
}
async function dlPump(){
 if(dlPumping)return;dlPumping=true;
 try{
  await dlLoaded;
  for(const e of dlState.entries.filter(x=>x.failure_kind==='generation'&&!x.failure_reported)){
   await dlEvent(e,'generation_task_failed',{event_id:'flow-generation-failed:'+e.key,state:'failed',message:e.error,failure_kind:'generation'});
   await dlMutate(()=>{e.failure_reported=true});
  }

  await dlLoaded;await dlSerial;
  const groups=[...new Set(dlState.entries.map(e=>e.group))];
  await Promise.allSettled(groups.map(async group=>{
   if(dlState.entries.some(e=>e.group===group&&['starting','downloading'].includes(e.status)))return;
   const first=dlState.entries.filter(e=>e.group===group&&e.status==='ready'&&(!e.retry_at||e.retry_at<=Date.now())).sort((a,b)=>a.document_number-b.document_number||a.part-b.part||a.sequence-b.sequence)[0];
   if(!first)return;
   const key=first.key;
   await dlMutate(()=>{first.status='starting';first.attempts++;});
   try{
    await dlLog('chrome_download_call',dlEntry(first));
    const id=await dlBounded(dlStartDownload(first).then(async id=>{
      await dlMutate(()=>{first.download_id=id;first.status='downloading';});return id;
    }),'DOWNLOAD_START');
    await dlLog('chrome_download_accepted',dlEntry(first));
    await dlEvent(first,'video_download_started',{download_id:id});
    const rows=await chrome.downloads.search({id});
    if(rows[0]?.state==='complete')await dlFinish(id,'complete');
    else if(rows[0]?.state==='interrupted')await dlFinish(id,'interrupted');
   }catch(error){if(String(error.message||error)==='DOWNLOAD_START_TIMEOUT'){await dlMutate(()=>{first.error='下载启动回执超时，正在核对Chrome记录；不重复启动';});return;}await dlMutate(()=>{const e=dlState.entries.find(x=>x.key===key);e.status=e.attempts<3?'waiting':'failed';e.failure_kind='download';e.retry_at=Date.now()+10000;e.error=String(error.message||error)});await dlEvent(first,'video_download_failed',{message:String(error.message||error)});}
  }));
 }finally{dlPumping=false;}
}
async function dlFinish(id,state,reason=''){
 let entry;
 await dlMutate(()=>{entry=dlState.entries.find(e=>e.download_id===id);if(!entry || entry.status==='complete') {entry=null;return;}
 entry.status=state==='complete'?'complete':entry.attempts<3?'waiting':'failed';
 if(state!=='complete'){entry.failure_kind='download';entry.retry_at=Date.now()+10000;entry.error=reason||'Chrome 下载中断';}else{entry.error='';entry.retry_at=0;}});
 if(entry)await dlLog('chrome_download_'+state,dlEntry(entry));
 if(entry){
  let output_path='';
  if(state==='complete'){
   try{const rows=await chrome.downloads.search({id});output_path=String(rows[0]?.filename||'');}catch(_){}
  }
  await dlEvent(entry,state==='complete'?'video_download_completed':'video_download_failed',{download_id:id,output_path,local_path:output_path,download_path:output_path,path_verified:!!output_path,message:state==='complete'?'下载完成':(reason||'Chrome 下载中断，将在重试上限内自动重试')});
  if(state==='complete' && output_path) await dlMutate(()=>{const e=dlState.entries.find(x=>x.key===entry.key);if(e){e.output_path=output_path;e.completion_path_synced=true;e.qc_recovery_v27=true;}});
 }
}
chrome.downloads.onChanged.addListener(delta=>{if(delta.state && ['complete','interrupted'].includes(delta.state.current))void dlFinish(delta.id,delta.state.current,delta.error?.current||'').then(dlPump);});
async function dlProbeWaiting(){ return; }
function dlSummary(group, entries) {
 const counts={};for(const e of entries)counts[e.status]=(counts[e.status]||0)+1;
 const d=dlDiagnostics.get(group);
 const parts=['v0.9.67', '已登记 '+entries.length, '待绑定 '+(counts.reserved||0), '待下载 '+(counts.ready||0), '下载完成 '+(counts.complete||0)];
 if(d)parts.push('集合视频 '+d.videos,'ID匹配 '+d.boundMatches,'结果已识别 '+d.recognized);
 const error=entries.find(e=>e.error && e.status!=='complete');
 if(error)parts.push(error.error);
 if(d?.error)parts.push('扫描错误：'+d.error);
 return parts.join(' · ');
}
function dlTick(){
 if(dlTickFlight)return dlTickFlight;
 if(Date.now()-dlLastTick<4000)return Promise.resolve();
 dlLastTick=Date.now();
 dlTickFlight=dlTickOnce().finally(()=>{dlTickFlight=null;});return dlTickFlight;
}
async function dlTickOnce(){
 await dlLoaded;await dlSerial;
 void dlProbeWaiting().then(dlPump).catch(()=>{});
 const tabs=await dlBounded(chrome.tabs.query({url:['https://flow.google.com/*']}),'TABS_QUERY');
 await Promise.allSettled(tabs.map(async tab=>{
  const group=dlGroup(tab.url),waiting=dlState.entries.filter(e=>e.group===group&&e.status==='waiting');
  const all=dlState.entries.filter(e=>e.group===group && e.status!=='cancelled');
  try{await dlBounded(chrome.tabs.sendMessage(tab.id,{type:'FS_DOWNLOAD_SUMMARY',total:all.length,complete:all.filter(e=>e.status==='complete').length,failed:all.filter(e=>e.status==='failed').length,waiting:waiting.length,downloading:all.filter(e=>['starting','downloading'].includes(e.status)).length,ready:all.filter(e=>e.status==='ready').length,reserved:all.filter(e=>e.status==='reserved').length,message:dlSummary(group,all)}),'SUMMARY',3000)}catch(error){console.error('[FlowStudio download] summary_failed',error);}
  // Scan even without a registered ID, so missing registration is visible.

  if(waiting.length||all.some(e=>e.status==='reserved'))try{await dlBounded(chrome.tabs.sendMessage(tab.id,{type:'FS_DOWNLOAD_SCAN',ids:[...new Set(waiting.map(e=>e.media_id).filter(Boolean))]}),'SCAN_DELIVERY',3000)}catch(_){}
 }));
 for(const e of dlState.entries.filter(e=>e.status==='downloading' && e.download_id!=null)){
  try{const rows=await dlBounded(chrome.downloads.search({id:e.download_id}),'DOWNLOAD_STATUS');
   const row=rows.find(r=>r.id===e.download_id);
   if(['complete','interrupted'].includes(row?.state))await dlFinish(e.download_id,row.state,row.error||'');
   else if(!row){
    // Chrome has no record of this id (restart / cleared list): requeue instead of blocking the whole group.
    await dlMutate(()=>{e.status='ready';e.download_id=null;e.error='';e.dl_bytes=0;e.dl_bytes_at=0;});
   }else{
    // In progress: if no bytes arrive for 3 minutes, cancel and requeue.
    const got=Number(row.bytesReceived||0),now=Date.now();
    if(got!==e.dl_bytes||!e.dl_bytes_at){await dlMutate(()=>{e.dl_bytes=got;e.dl_bytes_at=now;});}
    else if(now-e.dl_bytes_at>180000){
     try{await chrome.downloads.cancel(e.download_id);}catch(_){}
     await dlMutate(()=>{e.status=e.attempts<3?'ready':'failed';e.download_id=null;e.error='下载停滞，已取消并重新排队';e.dl_bytes=0;e.dl_bytes_at=0;});
    }
   }
  }catch(_){}
 }
 // Reconcile by filename: if Chrome already holds the finished file but the id-based check/onChanged
 // missed it, mark the entry complete so it cannot block the group's queue.
 for(const e of dlState.entries.filter(e=>e.status==='downloading')){
  try{
   const rows=await dlBounded(chrome.downloads.search({query:[e.filename.split('/').pop()],state:'complete'}),'DOWNLOAD_RECONCILE',5000);
   const item=rows.find(x=>String(x.filename||'').replace(/\\/g,'/').endsWith('/'+e.filename)&&Number(x.fileSize||x.totalBytes||1)>0&&new Date(x.startTime).getTime()>=Number(e.attempt_started_at||0)-60000);
   if(item){await dlMutate(()=>{e.download_id=item.id;});await dlFinish(item.id,'complete');}
  }catch(_){}
 }
 for(const e of dlState.entries.filter(e=>e.status==='starting')){
  try{const rows=await dlBounded(chrome.downloads.search({query:[e.filename.split('/').pop()],startedAfter:new Date(e.created_at).toISOString()}),'DOWNLOAD_LOOKUP');
   const item=rows.find(x=>String(x.filename||'').replace(/\\/g,'/').endsWith('/'+e.filename));
   if(item){await dlMutate(()=>{e.download_id=item.id;e.status='downloading';});if(['complete','interrupted'].includes(item.state))await dlFinish(item.id,item.state,item.error||'');}
  }catch(_){}
 }
 // Re-send completed download paths that older builds could not deliver. This
 // is idempotent on the Studio side and makes already-downloaded videos appear
 // in QC without a manual import step.
 for(const e of dlState.entries.filter(x=>x.status==='complete' && (!x.completion_path_synced || !x.qc_recovery_v27) && x.download_id!=null)){
  try{
   const rows=await chrome.downloads.search({id:e.download_id});
   const output_path=String(rows[0]?.filename||'');
   if(output_path){await dlEvent(e,'video_download_completed',{download_id:e.download_id,output_path,local_path:output_path,download_path:output_path,path_verified:true,message:'下载完成 · 路径同步'});await dlMutate(()=>{e.output_path=output_path;e.completion_path_synced=true;e.qc_recovery_v27=true;});}
  }catch(_){}
 }
 await dlPump();
}
async function dlRecover(){
 await dlLoaded;
 for(const e of dlState.entries.filter(e=>['starting','downloading'].includes(e.status)||(e.status==='failed'&&e.download_id!=null))){
  const rows=await chrome.downloads.search(e.download_id!=null?{id:e.download_id}:{query:[e.filename.split('/').pop()],startedAfter:new Date(e.created_at).toISOString()});
  const item=e.download_id!=null?rows.find(r=>r.id===e.download_id):rows.find(r=>r.filename.replace(/\\/g,'/').endsWith('/'+e.filename));
  await dlMutate(()=>{if(item){e.download_id=item.id;e.status=item.state==='complete'?'complete':item.state==='interrupted'?'failed':'downloading'}else{e.status='ready'}});
 }
 // One-time recovery of old failed transfers. Never reopen a completed entry or Flow generation failure.
 await dlMutate(()=>{
  for(const e of dlState.entries){
   if(e.recovery_v094)continue;e.recovery_v094=true;
   if(e.status==='failed'&&e.media_id&&e.failure_kind!=='generation'&&e.error!=='Flow 视频生成失败'){
    e.status='waiting';e.attempts=0;e.retry_at=0;e.probe_message='重新检查旧版未完成下载';
   }
  }
 });
 await dlTick();
}
function trustedFlowSender(sender){
 try{return sender.id===chrome.runtime.id && new URL(sender.url||sender.tab?.url||'').origin==='https://flow.google.com';}catch(_){return false;}
}
chrome.runtime.onMessage.addListener((msg,sender,reply)=>{
 if(!trustedFlowSender(sender))return;
 if(!msg?.type?.startsWith('FS_DOWNLOAD_'))return;
 const handlers={
  FS_DOWNLOAD_DIAGNOSTICS:()=>dlReport(sender),
  FS_DOWNLOAD_PENDING:async()=>{await dlLoaded;await dlSerial;return dlState.entries.filter(e=>e.group===dlGroup(sender.tab.url)&&e.status==='reserved'&&(msg.all||e.info?.command_id===msg.command_id)).map(e=>({key:e.key,attempt_started_at:e.attempt_started_at||0,uncertain_at:e.uncertain_at||0,submitted_at:e.submitted_at||0,info:{command_id:e.info?.command_id,segment_id:e.info?.segment_id,round:e.info?.round,task_id:e.info?.task_id,task_name:e.info?.task_name,host_id:e.info?.host_id,recipient_id:e.info?.recipient_id,channel_key:e.info?.channel_key,recovery_prompt:e.info?.recovery_prompt||''}}));},
  FS_DOWNLOAD_SUBMITTING:()=>dlMutate(()=>{const e=dlState.entries.find(x=>x.key===msg.key&&x.group===dlGroup(sender.tab.url));if(!e||e.status!=='reserved'||e.media_id||e.confirmed_at||e.attempt_started_at)throw Error('SUBMISSION_UNCONFIRMED: 已存在提交尝试，不能重复生成');e.attempt_started_at=Date.now();return true;}),
  FS_DOWNLOAD_UNCERTAIN:()=>dlMutate(()=>{const e=dlState.entries.find(x=>x.key===msg.key&&x.group===dlGroup(sender.tab.url));if(!e||e.status!=='reserved')return false;e.uncertain_at=Date.now();e.error=msg.error||'提交待确认';return true;}),
  FS_DOWNLOAD_REARM_UNCONFIRMED:()=>dlMutate(()=>{const e=dlState.entries.find(x=>x.key===msg.key&&x.group===dlGroup(sender.tab.url));if(!e||e.status!=='reserved'||e.media_id||e.confirmed_at)return false;e.submitted_at=0;e.uncertain_at=0;e.attempt_started_at=0;e.error='';e.rearmed_v0948=true;return true;}),
  FS_DOWNLOAD_RESERVE:async()=>{return await dlReserve(msg,sender);},
  FS_DOWNLOAD_POLL:()=>dlTick(),
  FS_DOWNLOAD_BIND:async()=>{return await dlBind(msg);},
  FS_DOWNLOAD_OBSERVE:()=>dlObserve(msg,sender),
  FS_DOWNLOAD_CANCEL:()=>dlMutate(()=>{const e=dlState.entries.find(x=>x.key===msg.key);if(e&&e.status==='reserved'){e.status='cancelled';e.error=msg.error}})
 };
 if(!handlers[msg.type])return;
 handlers[msg.type]().then(result=>reply({ok:true,result})).catch(async e=>{console.error('[FlowStudio download]',msg.type,e);try{await dlLog('request_error',{request:msg.type,error:String(e.message||e)})}catch(_){}reply({ok:false,error:String(e.message||e)});});return true;
});
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='flow-download-watch')void dlTick()});
chrome.alarms.create('flow-download-watch',{periodInMinutes:1});
void dlRecover().catch(()=>{});
setInterval(()=>{void dlTick()},5000);
