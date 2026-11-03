// Persistent download registry. Uses Chrome's configured default download directory.
const dlDiagnostics=new Map();
let dlTickFlight=null,dlLastTick=0;
const dlResultCache=new Map();
function dlBounded(promise,label,ms=12000){
 let timer;return Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(label+'_TIMEOUT')),ms);})]).finally(()=>clearTimeout(timer));
}

const DL_KEY='flowStudioDownloadsV0921';
let dlState={entries:[],counters:{}},dlSerial=Promise.resolve(),dlPumping=false,dlPumpPending=false;
const dlEarlyEvents=new Map();

function dlCompactState(aggressive=false){
 if(!dlState||typeof dlState!=='object')dlState={entries:[],counters:{}};
 if(!Array.isArray(dlState.entries))dlState.entries=[];
 // Strip bulky recovery_prompt once an entry is no longer in 'reserved' status.
 for(const e of dlState.entries){
  const badAsb=e && e.url && String(e.url).includes('/asb/') && !/=mm,/i.test(String(e.url));
  const badImageOut=e && e.output_path && /\.(jpe?g|png|webp)$/i.test(String(e.output_path));
  if(badAsb || badImageOut){
   e.status='waiting';e.url='';e.output_path='';e.download_id=null;e.attempts=0;e.error='';e.completion_path_synced=false;
  }
  if(e && e.status!=='reserved' && e.info && e.info.recovery_prompt){
   delete e.info.recovery_prompt;
  }
 }
 if(dlState.observations && typeof dlState.observations==='object'){
  for(const [k,obs] of Object.entries(dlState.observations)){
   if(obs && obs.url && String(obs.url).includes('/asb/') && !/=mm,/i.test(String(obs.url))){
    delete dlState.observations[k];
   }
  }
 }
 const maxEntries=aggressive?150:400;
 if(dlState.entries.length>maxEntries){
  const active=[],terminal=[];
  for(const e of dlState.entries){
   if(!e)continue;
   if(['reserved','waiting','ready','starting','downloading'].includes(e.status) || (e.status==='complete' && (!e.completion_path_synced || !e.qc_recovery_v27)) || (e.failure_kind==='generation' && !e.failure_reported)){
    active.push(e);
   }else{
    terminal.push(e);
   }
  }
  const keepTerminal=Math.max(40,maxEntries-active.length);
  dlState.entries=[...terminal.slice(-keepTerminal),...active];
 }
 if(Array.isArray(dlState.logs)){
  const maxLogs=aggressive?60:150;
  if(dlState.logs.length>maxLogs)dlState.logs=dlState.logs.slice(-maxLogs);
 }
 if(dlState.observations && typeof dlState.observations==='object'){
  const keys=Object.keys(dlState.observations);
  const maxObs=aggressive?40:120;
  if(keys.length>maxObs){
   for(const k of keys.slice(0,keys.length-maxObs))delete dlState.observations[k];
  }
 }
}

async function dlEmergencyTrimStorage(){
 try{
  const sub=await chrome.storage.local.get('flowStudioRuntimeLogsV0921');
  if(Array.isArray(sub?.flowStudioRuntimeLogsV0921) && sub.flowStudioRuntimeLogsV0921.length>150){
   await chrome.storage.local.set({flowStudioRuntimeLogsV0921:sub.flowStudioRuntimeLogsV0921.slice(-150)});
  }
 }catch(_){}
}

const dlLoaded=chrome.storage.local.get(DL_KEY).then(async data=>{
 if(data[DL_KEY])dlState=data[DL_KEY];
 dlCompactState(false);
 try{await chrome.storage.local.set({[DL_KEY]:dlState});}
 catch(_){dlCompactState(true);await dlEmergencyTrimStorage();try{await chrome.storage.local.set({[DL_KEY]:dlState});}catch(_){}}
});

// Bounded diagnostics; append in memory and persist on state mutation to avoid storage write amplification.
function dlLog(stage, detail={}) {
 const row={time:new Date().toISOString(),stage,...detail};
 console.info('[FlowStudio download]',row);
 dlState.logs=dlState.logs||[];
 dlState.logs.push(row);
 if(dlState.logs.length>250)dlState.logs=dlState.logs.slice(-250);
 return Promise.resolve();
}
function dlEntry(e){return {group:e.group,task_id:e.info?.task_id,media_id:e.media_id,status:e.status,filename:e.filename,download_id:e.download_id,attempts:e.attempts,segment_id:e.info?.segment_id,attempt_started_at:e.attempt_started_at||0,uncertain_at:e.uncertain_at||0,submitted_at:e.submitted_at||0,confirmed_at:e.confirmed_at||0,error:e.error,url:dlRedactURL(e.url)};}
function dlRedactURL(value){try{const u=new URL(value);return u.origin+u.pathname}catch(_){return null;}}
async function dlReport(sender){await dlLoaded;await dlSerial;const group=dlGroup(sender.tab.url);return {version:'0.9.69',exported_at:new Date().toISOString(),group,entries:dlState.entries.filter(e=>e.group===group).map(dlEntry),scan:dlDiagnostics.get(group)||null,logs:(dlState.logs||[]).filter(e=>!e.group||e.group===group)};}
function dlMutate(fn){
 const p=dlSerial.then(async()=>{
  await dlLoaded;
  const value=await fn();
  dlCompactState(false);
  try{
   await chrome.storage.local.set({[DL_KEY]:dlState});
  }catch(err){
   console.warn('[FlowStudio download] storage quota/write error, compacting and retrying',err);
   dlCompactState(true);
   await dlEmergencyTrimStorage();
   try{await chrome.storage.local.set({[DL_KEY]:dlState});}
   catch(err2){console.error('[FlowStudio download] storage retry failed (continuing with in-memory state)',err2);}
  }
  return value;
 });
 dlSerial=p.catch(()=>{});
 return p;
}
function dlSafe(value){return String(value||'集合').normalize('NFC').replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').replace(/\.{2,}/g,'_').replace(/[. ]+$/g,'').slice(0,80)||'集合';}
function dlNormPath(value){return String(value||'').normalize('NFC').replace(/\\/g,'/');}
function dlMatchesFilename(candidatePath, expectedFilename){
 const cand=dlNormPath(candidatePath), exp=dlNormPath(expectedFilename);
 return !!cand && !!exp && cand.endsWith('/'+exp);
}
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
  dlState.logs=dlState.logs||[];dlState.logs.push({time:new Date().toISOString(),stage:'reserve_exact_name',group,channel,task_id:info.task_id,task_name:info.task_name,filename,command_id:info.command_id,round:info.round});if(dlState.logs.length>250)dlState.logs=dlState.logs.slice(-250);
  return entry;
 });
}
async function dlBind(msg){
 let repairedFromReserved=false;
 const entry=await dlMutate(()=>{
  const e=dlState.entries.find(x=>x.key===msg.key);if(!e)throw Error('下载任务未登记');
  const ids=[...new Set((msg.ids||[]).filter(x=>typeof x==='string'))];
  if(ids.length!==1)throw Error('下载需要单个视频ID，收到 '+ids.length);
  if(dlState.entries.some(other=>other.key!==e.key && other.media_id===ids[0] && String(other.info?.segment_id)!==String(e.info?.segment_id)))throw Error('RESULT_ID_CONFLICT:同一生成结果不能绑定两个片段，请核对原任务');
  if(e.media_id && e.media_id!==ids[0])throw Error('GENERATION_ID_CONFLICT');
  if(e.status==='cancelled')throw Error('COMMAND_CANCELLED');
  e.media_id=ids[0];e.confirmed_at=e.confirmed_at||Date.now();e.submitted_at=e.submitted_at||e.confirmed_at;e.uncertain_at=0;
  if(e.status==='reserved'){e.status='waiting';repairedFromReserved=true;}
  if(e.info && e.info.recovery_prompt)delete e.info.recovery_prompt;
  return e;
 });
 const cached=dlResultCache.get(entry.group+'|'+entry.media_id) || (dlState.observations||{})[entry.group+'|'+entry.media_id];
 if(cached)await dlObserve({rows:[cached]}, {tab:{url:entry.group}});
 return {...entry,repaired_from_reserved:repairedFromReserved};
}
const DL_MAX_ATTEMPTS=4;
function dlNeedsFreshUrl(reason){
 return /SERVER_UNAUTHORIZED|SERVER_FORBIDDEN|SERVER_BAD_CONTENT|SERVER_FAILED|NETWORK_|CRASH|INVALID_URL/i.test(String(reason||''));
}
async function dlObserve(msg,sender){
 const group=dlGroup(sender.tab.url), failed=[];
 if(msg.diagnostics){
  dlDiagnostics.set(group,{...msg.diagnostics,time:Date.now()});
  while(dlDiagnostics.size>100)dlDiagnostics.delete(dlDiagnostics.keys().next().value);
 }
 const relevant=(msg.rows||[]).filter(row=>row && typeof row.id==='string' && ['ready','failed'].includes(row.status));
 if(!relevant.length)return;
 await dlLoaded;
 for(const row of relevant){
  const key=group+'|'+row.id;dlResultCache.set(key,row);
 }
 while(dlResultCache.size>300)dlResultCache.delete(dlResultCache.keys().next().value);
 // Skip serial storage writes when no tracked download entry actually needs an update.
 const hasEntryChange=(msg.rows||[]).some(row=>{
  if(!row||typeof row.id!=='string')return false;
  return dlState.entries.some(e=>{
   if(e?.url && String(e.url).includes('/asb/') && !/=mm,/i.test(String(e.url)))return true;
   if(e?.group!==group || e?.media_id!==row.id || !['waiting','ready'].includes(e.status))return false;
   if(row.status==='failed')return true;
   if(row.status==='ready'){
    const direct=dlVideoURL(row.url);
    return (!direct && e.probe_message!=='Flow 已生成完成，正在获取最新视频下载地址...') || (!!direct && (e.status!=='ready' || e.url!==direct));
   }
   return false;
  });
 });
 if(!hasEntryChange){
  if(dlState.entries.some(e=>e.group===group&&e.status==='ready'&&(!e.retry_at||e.retry_at<=Date.now())))void dlPump();
  return;
 }
 await dlMutate(()=>{
  dlState.observations=dlState.observations||{};
  for(const row of relevant){
   const key=group+'|'+row.id;dlResultCache.set(key,row);dlState.observations[key]={...row,observed_at:Date.now()};
  }
  const keys=Object.keys(dlState.observations);
  for(const key of keys.slice(0,Math.max(0,keys.length-120)))delete dlState.observations[key];
  for(const row of msg.rows||[])for(const e of dlState.entries){
   if(e.url && String(e.url).includes('/asb/') && !/=mm,/i.test(String(e.url))){
    e.status='waiting';e.url='';e.download_id=null;e.attempts=0;e.error='';
   }
   if(e.group!==group || e.media_id!==row.id || !['waiting','ready'].includes(e.status))continue;
   if(row.status==='failed'){e.status='failed';e.failure_kind='generation';e.error=row.error||'Flow 视频生成失败';e.failure_reported=false;failed.push(e);continue;}
   if(row.status==='ready'){
    // Same redirect endpoint used by the supplied legacy plugin; never accept arbitrary page URLs.
    const direct=dlVideoURL(row.url);
    if(!direct){
     e.probe_message='Flow 已生成完成，正在获取最新视频下载地址...';
     continue;
    }
    e.url=direct;
    e.status='ready';
    e.force_refresh_url=false;
    e.probe_message='Flow 内部已返回视频文件地址';
   }
  }
 });
 for(const e of failed){await dlEvent(e,'generation_task_failed',{event_id:'flow-generation-failed:'+e.key,state:'failed',message:e.error,failure_kind:'generation'});await dlMutate(()=>{e.failure_reported=true});}
 void dlPump();
}
function dlEvent(e,type,extra={}){const rd=e?.info?.redownload_request_id?(':'+String(e.info.redownload_request_id)):'';return Promise.resolve().then(()=>pushEvent({...e.info,type,event_id:type+':'+e.key+':'+String(extra.download_id??e.download_id??e.attempts??0)+rd,filename:e.filename,media_id:e.media_id,document_number:e.document_number,part_number:e.part,...extra}));}
const dlHelperTabs=new Map();
async function dlEnsureProjectTab(collectionUrl){
 const group=dlGroup(collectionUrl);
 try{
  const tabs=await chrome.tabs.query({url:['https://flow.google.com/*']});
  const openTab=tabs.find(t=>t?.url && dlGroup(t.url)===group);
  if(openTab)return openTab;
  const existingHelper=dlHelperTabs.get(group);
  if(existingHelper?.tabId){
   try{const t=await chrome.tabs.get(existingHelper.tabId);if(t)return t;}catch(_){dlHelperTabs.delete(group);}
  }
  if(chrome.tabs?.create){
   const created=await chrome.tabs.create({url:collectionUrl,active:false});
   if(created?.id!=null){
    dlHelperTabs.set(group,{tabId:created.id,openedAt:Date.now()});
    try{await chrome.tabs.update(created.id,{autoDiscardable:false});}catch(_){}
   }
   return created;
  }
 }catch(_){}
 return null;
}
async function dlEnqueueRedownloads(requests){
 const list=(requests||[]).filter(r=>r && r.media_id && r.collection_url);
 if(!list.length)return 0;
 await dlLoaded;
 const groupsToRefresh=new Map();
 const now=Date.now();
 await dlMutate(()=>{
  for(const req of list){
   let group='';
   try{group=dlGroup(req.collection_url);}catch(_){continue;}
   const mediaId=String(req.media_id).trim();
   if(!group||!mediaId)continue;
   const cacheKey=group+'|'+mediaId;
   dlResultCache.delete(cacheKey);
   if(dlState.observations)delete dlState.observations[cacheKey];
   const roundNo=Number(req.round||1);
   const key=JSON.stringify([group,req.command_id||'',req.segment_id,roundNo]);
   let entry=dlState.entries.find(x=>x.key===key);
   if(!entry && req.segment_id!=null){
    entry=dlState.entries.find(x=>x.group===group && String(x.info?.command_id||'')===String(req.command_id||'') && String(x.info?.segment_id)===String(req.segment_id) && Number(x.info?.round||1)===roundNo);
   }
   const channel=dlSafe(req.channel_key||'CH1');
   const folder=String(req.download_folder||('FlowStudio_Channels/'+channel)).replace(/^\/+|\/+$/g,'');
   const requested=dlSafe(req.download_name||req.task_name||req.task_id||('S'+String(req.segment_id||now)));
   const filename=folder+'/'+requested+'.mp4';
   const doc=Math.max(1,Number(req.document_number||1));
   const part=Math.max(1,Number(req.dispatch_order||1));
   const info={
    ...(entry?.info||{}),
    command_id:String(req.command_id||''),
    segment_id:Number(req.segment_id||0),
    round:roundNo,
    task_id:String(req.task_id||''),
    task_name:String(req.task_name||requested),
    download_name:requested,
    download_folder:folder,
    dispatch_order:part,
    document_number:doc,
    host_id:Number(req.host_id||0),
    host_name:String(req.host_name||''),
    recipient_id:Number(req.recipient_id||0),
    recipient_name:String(req.recipient_name||''),
    channel_id:Number(req.channel_id||0),
    channel_key:String(req.channel_key||channel),
    collection_url:String(req.collection_url||''),
    redownload_request_id:String(req.request_id||('redl-'+now))
   };
   if(info.recovery_prompt)delete info.recovery_prompt;
   if(entry){
    entry.folder=folder;
    entry.filename=filename;
    entry.document_number=doc;
    entry.part=part;
    entry.media_id=mediaId;
    entry.status='waiting';
    entry.url='';
    entry.output_path='';
    entry.download_id=null;
    entry.attempts=0;
    entry.retry_at=0;
    entry.error='';
    entry.failure_kind='';
    entry.failure_reported=false;
    entry.force_refresh_url=true;
    entry.completion_path_synced=false;
    entry.created_at=now;
    entry.redownload_at=now;
    entry.redownload_scans=0;
    entry.info=info;
   }else{
    entry={
     key,group,folder,document_number:doc,part,filename,
     sequence:dlState.entries.length,
     created_at:now,confirmed_at:now,submitted_at:now,
     redownload_at:now,redownload_scans:0,
     media_id:mediaId,status:'waiting',url:'',attempts:0,
     force_refresh_url:true,info
    };
    dlState.entries.push(entry);
   }
   if(!groupsToRefresh.has(group))groupsToRefresh.set(group,{url:String(req.collection_url),ids:new Set()});
   groupsToRefresh.get(group).ids.add(mediaId);
  }
 });
 for(const [group,meta] of groupsToRefresh.entries()){
  const tab=await dlEnsureProjectTab(meta.url);
  if(tab?.id!=null && tab.status==='complete'){
   const ids=[...meta.ids];
   await dlBounded(chrome.tabs.sendMessage(tab.id,{type:'FS_DOWNLOAD_SCAN',ids,refresh_ids:ids}),'REDOWNLOAD_SCAN',3500).catch(()=>{});
  }
 }
 dlLastTick=0;
 void dlTick();
 return list.length;
}
function dlVideoURL(value){
 try{
  const u=new URL(value);
  if(u.protocol!=='https:')return null;
  if(!/(^|\.)(flow-content\.google|googleusercontent\.com|googleapis\.com|googlevideo\.com|google\.com)$/.test(u.hostname))return null;
  if(/=(?:s\d+|w\d+|h\d+)/i.test(u.pathname))return null;
  if(u.pathname.startsWith('/asb/')&&!/=mm,/i.test(u.pathname))return null;
  if(u.hostname==='flow.google.com'&&!u.pathname.includes('/video/')&&!/=mm,/i.test(u.pathname))return null;
  return u.href;
 }catch(_){return null}
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
async function dlScheduleRetryOrFail(e,reason){
 const rsn=String(reason||'Chrome 下载中断');
 const terminal=rsn==='USER_CANCELED' || Number(e.attempts||0)>=DL_MAX_ATTEMPTS;
 e.failure_kind='download';
 if(terminal){
  e.status='failed';
  e.retry_at=0;
  e.error=rsn;
  return {terminal:true,needsRefresh:false};
 }
 const refresh=dlNeedsFreshUrl(rsn);
 if(refresh){
  const cacheKey=e.group+'|'+e.media_id;
  dlResultCache.delete(cacheKey);
  if(dlState.observations)delete dlState.observations[cacheKey];
  e.url='';
  e.download_id=null;
  e.status='waiting';
  e.force_refresh_url=true;
  e.retry_at=Date.now()+4000;
  e.error=`下载中断（${rsn}），正在刷新签名地址自动重试 (${e.attempts}/${DL_MAX_ATTEMPTS})`;
  return {terminal:false,needsRefresh:true};
 }
 e.download_id=null;
 e.status='ready';
 e.retry_at=Date.now()+6000;
 e.error=`下载中断（${rsn}），正在自动重试 (${e.attempts}/${DL_MAX_ATTEMPTS})`;
 return {terminal:false,needsRefresh:false};
}
async function dlNotifyRefreshUrl(group,mediaId){
 if(!mediaId)return;
 try{
  const tabs=await chrome.tabs.query({url:['https://flow.google.com/*']});
  for(const tab of tabs){
   if(dlGroup(tab.url)===group){
    await dlBounded(chrome.tabs.sendMessage(tab.id,{type:'FS_DOWNLOAD_SCAN',ids:[mediaId],refresh_ids:[mediaId]}),'REFRESH_SCAN',3000).catch(()=>{});
   }
  }
 }catch(_){}
}
async function dlPump(){
 if(dlPumping){dlPumpPending=true;return;}
 dlPumping=true;dlPumpPending=false;
 try{
  await dlLoaded;
  for(const e of dlState.entries.filter(x=>x.failure_kind==='generation'&&!x.failure_reported)){
   await dlEvent(e,'generation_task_failed',{event_id:'flow-generation-failed:'+e.key,state:'failed',message:e.error,failure_kind:'generation'});
   await dlMutate(()=>{e.failure_reported=true});
  }

  await dlLoaded;await dlSerial;
  const groups=[...new Set(dlState.entries.map(e=>e.group))];
  await Promise.allSettled(groups.map(async group=>{
   // Only block while a download call is actively being initiated ('starting') or if 3 downloads are already in flight for this group.
   if(dlState.entries.some(e=>e.group===group&&e.status==='starting'))return;
   if(dlState.entries.filter(e=>e.group===group&&e.status==='downloading').length>=3)return;
   const first=dlState.entries.filter(e=>e.group===group&&e.status==='ready'&&(!e.retry_at||e.retry_at<=Date.now())).sort((a,b)=>a.document_number-b.document_number||a.part-b.part||a.sequence-b.sequence)[0];
   if(!first)return;
   const key=first.key;
   try{
    await dlMutate(()=>{first.status='starting';first.attempts=(Number(first.attempts)||0)+1;first.attempt_started_at=Date.now();});
    await dlLog('chrome_download_call',dlEntry(first));
    const id=await dlBounded(dlStartDownload(first).then(async id=>{
      await dlMutate(()=>{first.download_id=id;first.status='downloading';});return id;
    }),'DOWNLOAD_START');
    await dlLog('chrome_download_accepted',dlEntry(first));
    await dlEvent(first,'video_download_started',{download_id:id});
    // Immediately schedule pumping the next 'ready' video in the queue.
    if(dlState.entries.some(e=>e.group===group&&e.status==='ready'&&(!e.retry_at||e.retry_at<=Date.now()))){
     dlPumpPending=true;
    }
    const early=dlEarlyEvents.get(id);
    if(early){
     dlEarlyEvents.delete(id);
     await dlFinish(id,early.state,early.reason||'');
    }else{
     const rows=await chrome.downloads.search({id});
     if(rows[0]?.state==='complete')await dlFinish(id,'complete');
     else if(rows[0]?.state==='interrupted')await dlFinish(id,'interrupted',rows[0]?.error||'');
    }
   }catch(error){
    if(String(error.message||error)==='DOWNLOAD_START_TIMEOUT'){
     await dlMutate(()=>{first.error='下载启动回执超时，正在核对Chrome记录；不重复启动';});
     return;
    }
    const errMsg=String(error.message||error);
    let outcome={terminal:true,needsRefresh:false};
    await dlMutate(()=>{const e=dlState.entries.find(x=>x.key===key);if(e){outcome=dlScheduleRetryOrFail(e,errMsg);}});
    outcome=await outcome;
    if(outcome?.needsRefresh)void dlNotifyRefreshUrl(first.group,first.media_id);
    if(outcome?.terminal){
     await dlEvent(first,'video_download_failed',{attempts:first.attempts,max_attempts:DL_MAX_ATTEMPTS,retrying:false,message:errMsg});
    }else{
     await dlLog('chrome_download_retry_scheduled',{...dlEntry(first),reason:errMsg});
    }
   }
  }));
 }finally{
  dlPumping=false;
  if(dlPumpPending){dlPumpPending=false;setTimeout(()=>{void dlPump();},50);}
 }
}
async function dlFinish(id,state,reason=''){
 let entry,outcome={terminal:false,needsRefresh:false};
 await dlMutate(()=>{
  entry=dlState.entries.find(e=>e.download_id===id);
  if(!entry){
   dlEarlyEvents.set(id,{state,reason,at:Date.now()});
   while(dlEarlyEvents.size>200)dlEarlyEvents.delete(dlEarlyEvents.keys().next().value);
   return;
  }
  if(entry.status==='complete'){entry=null;return;}
  if(state==='complete'){
   entry.status='complete';entry.error='';entry.retry_at=0;entry.force_refresh_url=false;
  }else{
   outcome=dlScheduleRetryOrFail(entry,reason||'Chrome 下载中断');
  }
 });
 outcome=await outcome;
 if(entry)await dlLog('chrome_download_'+state,dlEntry(entry));
 if(entry){
  let output_path='',mime='';
  if(state==='complete'){
   try{const rows=await chrome.downloads.search({id});output_path=String(rows[0]?.filename||'');mime=String(rows[0]?.mime||'');}catch(_){}
   if(/\.(jpe?g|png|webp)$/i.test(output_path) || /^image\//i.test(mime)){
    await dlMutate(()=>{const e=dlState.entries.find(x=>x.key===entry.key);if(e){e.status='waiting';e.url='';e.output_path='';e.download_id=null;e.attempts=0;e.force_refresh_url=true;e.error='跳过缩略图，等待MP4视频流';e.completion_path_synced=false;}});
    void dlNotifyRefreshUrl(entry.group,entry.media_id);
    return;
   }
   await dlEvent(entry,'video_download_completed',{download_id:id,output_path,local_path:output_path,download_path:output_path,path_verified:!!output_path,message:'下载完成'});
   if(output_path) await dlMutate(()=>{const e=dlState.entries.find(x=>x.key===entry.key);if(e){e.output_path=output_path;e.completion_path_synced=true;e.qc_recovery_v27=true;}});
  }else{
   if(outcome?.needsRefresh)void dlNotifyRefreshUrl(entry.group,entry.media_id);
   if(outcome?.terminal){
    await dlEvent(entry,'video_download_failed',{download_id:id,attempts:entry.attempts,max_attempts:DL_MAX_ATTEMPTS,retrying:false,message:reason||'Chrome 下载多次重试仍失败'});
   }
  }
 }
}
chrome.downloads?.onDeterminingFilename?.addListener((item,suggest)=>{
 try{
  if(item?.byExtensionId && chrome.runtime?.id && item.byExtensionId!==chrome.runtime.id)return;
  const match=dlState.entries.find(e=>(e.download_id!=null && e.download_id===item.id) || (['starting','downloading'].includes(e.status) && e.url && e.url===item.url));
  if(match?.filename)suggest({filename:String(match.filename),conflictAction:'overwrite'});
 }catch(_){}
});
chrome.downloads.onChanged.addListener(delta=>{if(delta.state && ['complete','interrupted'].includes(delta.state.current))void dlFinish(delta.id,delta.state.current,delta.error?.current||'').then(dlPump);});
async function dlProbeWaiting(){ return; }
function dlSummary(group, entries) {
 const counts={};for(const e of entries)counts[e.status]=(counts[e.status]||0)+1;
 const d=dlDiagnostics.get(group);
 const parts=['v0.9.69', '已登记 '+entries.length, '待绑定 '+(counts.reserved||0), '待下载 '+(counts.ready||0), '下载完成 '+(counts.complete||0)];
 if(d)parts.push('集合视频 '+d.videos,'ID匹配 '+d.boundMatches,'结果已识别 '+d.recognized);
 const error=entries.find(e=>e.error && e.status!=='complete');
 if(error)parts.push(error.error);
 if(d?.error)parts.push('扫描错误：'+d.error);
 return parts.join(' · ');
}
function dlTick(){
 if(dlTickFlight)return dlTickFlight;
 if(Date.now()-dlLastTick<1500)return Promise.resolve();
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

  if(waiting.length||all.some(e=>e.status==='reserved')){
   try{
    await dlBounded(chrome.tabs.sendMessage(tab.id,{type:'FS_DOWNLOAD_SCAN',ids:[...new Set(waiting.map(e=>e.media_id).filter(Boolean))],refresh_ids:[...new Set(waiting.filter(e=>e.force_refresh_url).map(e=>e.media_id).filter(Boolean))]}),'SCAN_DELIVERY',3000);
    if(!tab.status || tab.status==='complete'){
     for(const w of waiting){if(w.info?.redownload_request_id)w.redownload_scans=(Number(w.redownload_scans)||0)+1;}
    }
   }catch(_){}
  }
 }));
 const timedOutRedls=dlState.entries.filter(e=>e.status==='waiting' && e.info?.redownload_request_id && Number(e.redownload_scans||0)>=9 && Date.now()-Number(e.redownload_at||0)>35000);
 if(timedOutRedls.length){
  await dlMutate(()=>{for(const e of timedOutRedls){if(e.status==='waiting'){e.status='failed';e.failure_kind='download';e.error='未在该项目页面找到对应云端视频（请确认当前浏览器已登录原生成账号）';}}});
  for(const e of timedOutRedls){await dlEvent(e,'video_download_failed',{retrying:false,message:e.error});}
 }
 for(const [hGroup,hInfo] of [...dlHelperTabs.entries()]){
  const busy=dlState.entries.some(e=>e.group===hGroup && ['waiting','ready','starting','downloading'].includes(e.status));
  if(!busy && Date.now()-Number(hInfo.openedAt||0)>8000){
   dlHelperTabs.delete(hGroup);
   try{await chrome.tabs.remove(hInfo.tabId);}catch(_){}
  }
 }
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
   const minStart=e.redownload_at?(Number(e.redownload_at)-2000):(Number(e.attempt_started_at||e.created_at||0)-60000);
   const item=rows.find(x=>dlMatchesFilename(x.filename,e.filename)&&Number(x.fileSize||x.totalBytes||1)>0&&new Date(x.startTime).getTime()>=minStart);
   if(item){await dlMutate(()=>{e.download_id=item.id;});await dlFinish(item.id,'complete');}
  }catch(_){}
 }
 for(const e of dlState.entries.filter(e=>e.status==='starting')){
  try{const rows=await dlBounded(chrome.downloads.search({query:[e.filename.split('/').pop()],startedAfter:new Date(e.created_at).toISOString()}),'DOWNLOAD_LOOKUP');
   const item=rows.find(x=>dlMatchesFilename(x.filename,e.filename));
   if(item){await dlMutate(()=>{e.download_id=item.id;e.status='downloading';});if(['complete','interrupted'].includes(item.state))await dlFinish(item.id,item.state,item.error||'');}
   else if(Date.now()-Number(e.attempt_started_at||e.created_at||0)>15000){
    await dlMutate(()=>{e.status='ready';});
   }
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
  const item=e.download_id!=null?rows.find(r=>r.id===e.download_id):rows.find(r=>dlMatchesFilename(r.filename,e.filename));
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
 dlLastTick=0;
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
