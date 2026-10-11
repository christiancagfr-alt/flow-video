// Persistent download registry. Uses Chrome's configured default download directory.
const dlDiagnostics=new Map();
let dlTickFlight=null,dlLastTick=0;
const dlResultCache=new Map();
function dlBounded(promise,label,ms=12000){
 let timer;return Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(label+'_TIMEOUT')),ms);})]).finally(()=>clearTimeout(timer));
}

const DL_KEY='flowStudioDownloadsV0921';
let dlState={entries:[],counters:{}},dlSerial=Promise.resolve(),dlPumping=false;

// Legacy auxiliary-image history is purged from the persistent registry on load.
function dlIsLegacyAuxEntry(e){
  const info=e?.info||{},type=String(info.task_type||e?.task_type||'').toUpperCase();
  const mode=String(info.generation_mode||info.mode||'').toUpperCase();
  const paths=[e?.filename,e?.folder,e?.target_folder,info.download_folder,info.targetRelativePath].map(x=>String(x||'').replace(/\\/g,'/')).join('|');
  const legacyTypes=['BROLL_'+'IMAGE','CAMERA_'+'AUX','CAMERA_'+'AUX_IMAGE'];
  return legacyTypes.includes(type)||mode==='IMAGE'||/\/(?:CAMERA_|AUX_)(?:AUX|IMAGE)(?:\/|$)/.test(paths);
}
// A result row is usable only when it is not declared/addressed as a non-video object.
function dlIsVideoRow(row){
  const kind=String(row?.media_kind||'VIDEO').toUpperCase();
  if(kind!=='VIDEO')return false;
  try{if(row?.url&&new URL(row.url).pathname.includes('/image/'))return false;}catch(_){}
  return true;
}
let dlRegistryReady=false;
const dlLoaded=chrome.storage.local.get(DL_KEY).then(data=>{
 if(data[DL_KEY])dlState=data[DL_KEY];
if(Array.isArray(dlState.entries)){
  const before=dlState.entries.length;
  dlState.entries=dlState.entries.filter(e=>!dlIsLegacyAuxEntry(e));
  if(dlState.entries.length!==before)void chrome.storage.local.set({[DL_KEY]:dlState});
}
 dlRegistryReady=true;
});
// Bounded persistent diagnostics; omit prompts and signed query strings.
function dlLog(stage, detail={}) {
 const row={time:new Date().toISOString(),stage,...detail};
 console.info('[FlowStudio download]',row);
 return dlMutate(()=>{dlState.logs=dlState.logs||[];dlState.logs.push(row);dlState.logs=dlState.logs.slice(-1000);});
}
function dlEntry(e){return {group:e.group,task_id:e.info?.task_id,media_id:e.media_id,status:e.status,filename:e.filename,download_id:e.download_id,attempts:e.attempts,segment_id:e.info?.segment_id,attempt_started_at:e.attempt_started_at||0,uncertain_at:e.uncertain_at||0,submitted_at:e.submitted_at||0,confirmed_at:e.confirmed_at||0,error:e.error,url:dlRedactURL(e.url)};}
function dlRedactURL(value){try{const u=new URL(value);return u.origin+u.pathname}catch(_){return null;}}
async function dlReport(sender){await dlLoaded;await dlSerial;const group=dlGroup(sender.tab.url);return {version:'1',exported_at:new Date().toISOString(),group,entries:dlState.entries.filter(e=>e.group===group).map(dlEntry),scan:dlDiagnostics.get(group)||null,logs:(dlState.logs||[]).filter(e=>!e.group||e.group===group)};}
function dlMutate(fn){const p=dlSerial.then(async()=>{await dlLoaded;const value=await fn();await chrome.storage.local.set({[DL_KEY]:dlState});return value});dlSerial=p.catch(()=>{});return p;}
function dlSafe(value){return String(value||'集合').normalize('NFC').replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').replace(/\.{2,}/g,'_').replace(/[. ]+$/g,'').slice(0,80)||'集合';}
function dlGroup(url){const u=new URL(url);return u.origin+u.pathname.replace(/\/+$/,'');}
function dlHash(text){let h=2166136261;for(const c of text)h=Math.imul(h^c.charCodeAt(0),16777619);return (h>>>0).toString(16).padStart(8,'0');}
// New reservations freeze business identity. Legacy entries/B-roll keep their targets.
function normalizeFlowStudioRelativePath(path){
 const parts=String(path||'').replace(/\\/g,'/').replace(/^\/+|\/+$/g,'').split('/').filter(Boolean);
 return parts.filter((part,i)=>part!=='FlowStudio_Channels'||parts[i-1]!==part).join('/');
}
function dlBusinessBase(value){
 const name=String(value||'').replace(/\\/g,'/').split('/').pop().normalize('NFC');
const base=name.replace(/\.mp4$/i,'');
 return base.replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').replace(/\.{2,}/g,'_').replace(/[. ]+$/g,'');
}
function buildDownloadTarget(info){
 const taskType=String(info.task_type||'VIDEO');
 const channelKey=dlSafe(info.channel_key||'CH');
 let targetFolder=normalizeFlowStudioRelativePath(info.targetRelativePath||info.download_folder||('FlowStudio_Channels/'+channelKey));
 let explicitName=info.targetFilename||info.download_name;
 // targetRelativePath may carry a complete relative filename, or only a folder.
 const tail=targetFolder.split('/').pop();
 if(/\.mp4$/i.test(tail)||
    (explicitName&&tail===String(explicitName).replace(/\\/g,'/').split('/').pop())){
  if(!explicitName)explicitName=tail;
  targetFolder=targetFolder.slice(0,-tail.length).replace(/\/$/,'');
 }
 if(!targetFolder||targetFolder==='FlowStudio_Channels')targetFolder='FlowStudio_Channels/'+channelKey;
 if(!targetFolder.startsWith('FlowStudio_Channels/'))targetFolder='FlowStudio_Channels/'+targetFolder;
// Keep supplied business names intact; identifiers never replace them.
 const targetBaseName=dlBusinessBase(explicitName||info.download_stem||info.task_name||('task-'+Date.now()));
 if(!targetBaseName || targetFolder.split('/').some(part=>part==='.'||part==='..') ||
    /[:*?"<>|\x00-\x1f]/.test(targetFolder))throw Error('DOWNLOAD_TARGET_INVALID');
const expectedExtension='.mp4';
 return {taskType,channelKey,targetFolder,targetBaseName,expectedExtension,relativeFilename:targetFolder+'/'+targetBaseName+expectedExtension};
}
function dlChromeRelativeFilename(entry,item,ext){
 const relative=entry.target_folder+'/'+entry.target_filename+ext;
 // item.filename is Chrome's tentative absolute path — but Chrome frequently leaves it EMPTY inside
 // onDeterminingFilename. When present, derive the real download root from it; never assume the
 // parent folder is the root. When empty, fall back to what this browser profile learned from its
 // previous completed downloads (dlState.chrome_root_is_channels): some profiles use
 // ~/Downloads/FlowStudio_Channels as the Chrome download folder, which doubled the folder name.
 const tentative=String(item?.filename||'').replace(/\\/g,'/');
 let root='';
 if(tentative){
  if(tentative.endsWith('/'+relative))root=tentative.slice(0,tentative.length-relative.length-1);
  else{const slash=tentative.lastIndexOf('/');root=slash<0?'':tentative.slice(0,slash);}
 }
 const rootIsChannels=root?root.split('/').pop()==='FlowStudio_Channels':dlState.chrome_root_is_channels===true;
 const suggestFilename=rootIsChannels?relative.replace(/^FlowStudio_Channels\//,''):relative;
 return {relativeFilename:relative,suggestFilename,actualPath:root?root+'/'+suggestFilename:''};
}
// Called with the FINAL absolute path of a completed download: remembers whether the profile's
// Chrome download folder already is FlowStudio_Channels so the next suggestion is correct.
async function dlLearnDownloadRoot(entry,item){
 try{
  const p=String(item?.filename||'').replace(/\\/g,'/');
  if(!p||!entry?.target_folder)return;
  const count=p.split('/').filter(x=>x==='FlowStudio_Channels').length;
  const stripped=!String(entry.suggest_filename||'').startsWith('FlowStudio_Channels/');
  const learned=stripped?true:count>=2;
  if(dlState.chrome_root_is_channels!==learned)await dlMutate(()=>{dlState.chrome_root_is_channels=learned;});
 }catch(_){}
}
function dlVerifyCompletedPath(entry,item){
 const actualPath=String(item?.filename||''),normalizedActualPath=actualPath.replace(/\\/g,'/');
const ext='.mp4';
const expectedRelativeFilename=entry.target_folder+'/'+entry.target_filename+ext;
const expectedPath=String(entry.expected_actual_path||'');
const extensionKnown=true;
 const exactPath=!entry.expected_actual_path||normalizedActualPath===expectedPath;
 const rootCount=normalizedActualPath.split('/').filter(part=>part==='FlowStudio_Channels').length;
 // rootCount 2 = the profile's Chrome download folder is itself FlowStudio_Channels (the file is
 // still saved and named exactly right; dlLearnDownloadRoot fixes the next suggestion and Studio
 // also scans that folder), so it must not be reported as a failed download.
 return {actualPath,expectedRelativeFilename,verified:item?.state==='complete'&&item.exists!==false&&extensionKnown&&(exactPath||rootCount===2)&&rootCount>=1&&rootCount<=2&&normalizedActualPath.endsWith('/'+expectedRelativeFilename)};
}

async function dlReserve(msg,sender){
 const group=dlGroup(sender.tab.url), info=msg.info||{};
 const doc=Number(info.document_number);if(!Number.isInteger(doc)||doc<1)throw Error('无效文案编号');
 // Display numbers such as 01-01 repeat across hosts; segment_id is global.
 const key=JSON.stringify([group,info.command_id,info.segment_id??info.task_name??info.task_id,info.round]);
 return dlMutate(()=>{
  let entry=dlState.entries.find(x=>x.key===key);
  if(!entry && info.segment_id!=null) entry=dlState.entries.find(x=>x.group===group && x.info?.command_id===info.command_id && String(x.info?.segment_id)===String(info.segment_id) && Number(x.info?.round||1)===Number(info.round||1));
  if(entry)return {...entry,existing:true};
const ext='.mp4';
const isBroll=info.task_type==='BROLL_VIDEO';
  let target;
  if(isBroll){
   // Unchanged B-roll naming and directory policy.
   const channel=dlSafe(info.channel_key||'CH');
   let folder=String(info.download_folder||('FlowStudio_Channels/'+channel)).replace(/^\/+|\/+$/g,'');
   let requested=dlSafe(info.download_name||info.task_name||info.task_id||('task-'+Date.now()));
   const revision=Math.max(1,Number(info.revision||1));
   if(info.video_id&&info.broll_id){folder=String(info.video_id+'/BROLL/'+info.broll_id);requested='VIDEO';}
   else if(info.video_id&&info.segment_id){folder=String(info.video_id);requested=String(info.segment_id);}
   target={targetFolder:folder,targetBaseName:requested,relativeFilename:folder+'/'+requested+ext};
  }else target=buildDownloadTarget(info);
  const filenameBase=target.targetFolder+'/'+target.targetBaseName;
  entry={key,group,folder:target.targetFolder,document_number:doc,part:Number(info.dispatch_order||1),filename:target.relativeFilename,filename_base:'',sequence:dlState.entries.length,created_at:Date.now(),status:'reserved',attempts:0,info};
  if(!isBroll)Object.assign(entry,{target_folder:target.targetFolder,target_filename:target.targetBaseName,targetRelativePath:target.targetFolder,targetFilename:target.targetBaseName,filename_base:filenameBase,task_type:target.taskType,channel_key:target.channelKey,video_id:info.video_id,shot_id:info.shot_id});
  dlState.entries.push(entry);
  const reservedLog={time:new Date().toISOString(),stage:isBroll?'reserve_exact_name':'DOWNLOAD_TARGET_RESERVED',group,task_type:target.taskType||info.task_type,channel_key:target.channelKey||info.channel_key,video_id:info.video_id,shot_id:info.shot_id,download_folder:info.download_folder,download_name:info.download_name,targetFolder:target.targetFolder,targetFilename:target.targetBaseName,relativeFilename:entry.filename,task_id:info.task_id,task_name:info.task_name,filename:entry.filename,command_id:info.command_id,round:info.round};
  dlState.logs=dlState.logs||[];dlState.logs.push(reservedLog);dlState.logs=dlState.logs.slice(-1500);
  if(!isBroll)console.info('[FlowStudio download]',reservedLog);
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
  e.media_id=ids[0];e.identity_aliases=[...new Set([...(e.identity_aliases||[]),ids[0]])];e.confirmed_at=e.confirmed_at||Date.now();e.submitted_at=e.submitted_at||e.confirmed_at;e.uncertain_at=0;
  if(e.status==='reserved')e.status='waiting';return e;
 });
 const cacheKey=entry.group+'|'+entry.media_id,kindKey=cacheKey+'|VIDEO';
 const typed=dlResultCache.get(kindKey)||(dlState.observations||{})[kindKey],legacy=dlResultCache.get(cacheKey)||(dlState.observations||{})[cacheKey];
 const cached=legacy?.status==='failed'&&Number(legacy.observed_at||0)>=Number(typed?.observed_at||0)?legacy:(typed||legacy);
 if(cached)await dlObserve({rows:[cached]}, {tab:{url:entry.group}});
 return entry;
}
async function dlObserve(msg,sender){
 const group=dlGroup(sender.tab.url),failed=[],mediaLogs=[];
 if(msg.diagnostics){
  dlDiagnostics.set(group,{...msg.diagnostics,time:Date.now()});
  while(dlDiagnostics.size>100)dlDiagnostics.delete(dlDiagnostics.keys().next().value);
 }
 const relevant=(msg.rows||[]).filter(row=>row && typeof row.id==='string' && ['ready','failed'].includes(row.status));
 if(!relevant.length)return;
 await dlMutate(()=>{
  dlState.observations=dlState.observations||{};
  for(const row of relevant){
if(!dlIsVideoRow(row))continue;
const rowKind=row.status==='failed'&&!row.media_kind?'UNKNOWN':'VIDEO';
   const aliases=[...new Set([row.id,row.media_id,...(Array.isArray(row.identity_aliases)?row.identity_aliases:[])].filter(x=>typeof x==='string'&&x))];
   const observation={...row,identity_aliases:aliases,observed_at:Date.now()};
   for(const alias of aliases){const key=group+'|'+alias+(row.status==='failed'&&rowKind==='UNKNOWN'?'':'|'+rowKind);dlResultCache.set(key,observation);dlState.observations[key]=observation;}
  }
  const keys=Object.keys(dlState.observations);
  for(const key of keys.slice(0,Math.max(0,keys.length-600)))delete dlState.observations[key];
  while(dlResultCache.size>600)dlResultCache.delete(dlResultCache.keys().next().value);
for(const row of (msg.rows||[]).filter(dlIsVideoRow))for(const e of dlState.entries){
   const rowAliases=new Set([row.id,row.media_id,...(Array.isArray(row.identity_aliases)?row.identity_aliases:[])].filter(x=>typeof x==='string'&&x));
   const entryAliases=new Set([e.media_id,...(Array.isArray(e.identity_aliases)?e.identity_aliases:[])].filter(x=>typeof x==='string'&&x));
   const identityMatch=[...rowAliases].some(id=>entryAliases.has(id));
   if(e.group!==group || !identityMatch || !['waiting','ready'].includes(e.status))continue;
   e.identity_aliases=[...new Set([...(e.identity_aliases||[]),...rowAliases])];
   if(row.status==='failed'){
e.status='failed';e.failure_kind='generation';e.error=row.error||'Flow 视频生成失败';e.failure_reported=false;failed.push(e);continue;}
   if(row.status==='ready'){
mediaLogs.push({stage:'RESULT_MEDIA_SELECTED',group,task_type:e.info?.task_type||'VIDEO',media_id:row.media_id||row.id});
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
 });
 for(const {stage,...detail}of mediaLogs)await dlLog(stage,detail);
for(const e of failed){await dlEvent(e,'generation_task_failed',{event_id:'flow-generation-failed:'+e.key,state:'failed',message:e.error,failure_kind:'generation'});await dlMutate(()=>{e.failure_reported=true});}
 void dlPump();
}
function dlEvent(e,type,extra={}){return Promise.resolve().then(()=>pushEvent({...e.info,type,event_id:type+':'+e.key+':'+String(extra.download_id??e.download_id??e.attempts??0),filename:e.filename,media_id:e.media_id,document_number:e.document_number,part_number:e.part,...extra}));}
function dlVideoURL(value){
 try{const u=new URL(value);return u.protocol==='https:'&& /(^|\.)(flow-content\.google|googleusercontent\.com|googleapis\.com|googlevideo\.com|google\.com)$/.test(u.hostname)?u.href:null}catch(_){return null}
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
  // A retried segment gets a new command; results of the older command are discarded by Studio,
  // so its leftover 'waiting' entries must not inflate the generating count or the scan list.
  const stampOf=e=>Number(e.created_at||e.submitted_at||0);
  const isSuperseded=e=>e.status==='waiting'&&e.info?.segment_id!=null&&dlState.entries.some(o=>o!==e&&o.group===e.group&&String(o.info?.segment_id)===String(e.info.segment_id)&&o.info?.command_id!==e.info?.command_id&&o.status!=='cancelled'&&stampOf(o)>stampOf(e));
  if(dlState.entries.some(isSuperseded)){
   try{await dlMutate(()=>{for(const e of dlState.entries)if(isSuperseded(e)){e.status='cancelled';e.error='已被同一片段的新一轮任务取代';}});}catch(_){}
  }
  const groups=[...new Set(dlState.entries.map(e=>e.group))];
  await Promise.allSettled(groups.map(async group=>{
   // Only serialize the brief Chrome download creation step. Once a downloadId has
   // been accepted, Chrome owns that transfer and the next READY video may start.
   if(dlState.entries.some(e=>e.group===group&&e.status==='starting'))return;
   const first=dlState.entries.filter(e=>e.group===group&&e.status==='ready'&&(!e.retry_at||e.retry_at<=Date.now())).sort((a,b)=>a.document_number-b.document_number||a.part-b.part||a.sequence-b.sequence)[0];
   if(!first)return;
   const key=first.key;
await dlMutate(()=>{first.status='starting';first.attempts++;});
   try{
    await dlLog('chrome_download_call',dlEntry(first));
    const downloadOptions={url:first.url,saveAs:false,conflictAction:'overwrite'};
downloadOptions.filename=first.filename;
const id=await dlBounded(chrome.downloads.download(downloadOptions).then(async id=>{
      await dlMutate(()=>{if(!(first.blocked_download_ids||[]).includes(id)){first.download_id=id;first.status='downloading';}});return id;
    }),'DOWNLOAD_START');
    if((first.blocked_download_ids||[]).includes(id))return;
    await dlLog('chrome_download_accepted',dlEntry(first));
    await dlEvent(first,'video_download_started',{download_id:id});
    // Match the successful reference plugin: creation of the Chrome download releases
    // the Flow-side slot immediately. Do not wait for this MP4 to finish before starting
    // the next READY result.
    setTimeout(()=>{void dlPump();},0);
    const rows=await chrome.downloads.search({id});
    if(rows[0]?.state==='complete')await dlFinish(id,'complete');
    else if(rows[0]?.state==='interrupted')await dlFinish(id,'interrupted');
   }catch(error){if(String(error.message||error)==='DOWNLOAD_START_TIMEOUT'){await dlMutate(()=>{first.error='下载启动回执超时，正在核对Chrome记录；不重复启动';});return;}await dlMutate(()=>{const e=dlState.entries.find(x=>x.key===key);e.status=e.attempts<3?'waiting':'failed';e.failure_kind='download';e.retry_at=Date.now()+10000;e.error=String(error.message||error)});await dlEvent(first,'video_download_failed',{message:String(error.message||error)});}
  }));
 }finally{dlPumping=false;}
}
async function dlFinishTarget(id,state,reason=''){
 await dlLoaded;await dlSerial;
 const entry=dlState.entries.find(e=>e.download_id===id);
 if(!entry || (entry.status==='complete'&&entry.completion_path_synced) || entry.error==='DOWNLOAD_PATH_MISMATCH')return;
 let check,reportedState=state;
 if(state==='complete'){
  let item;
  try{item=(await chrome.downloads.search({id}))[0];}catch(_){}
  check=dlVerifyCompletedPath(entry,item);
  await dlLearnDownloadRoot(entry,item);
  if(!check.verified)reportedState='mismatch';
 }
 await dlMutate(()=>{
  if(reportedState==='complete'){
   entry.status='complete';entry.error='';entry.retry_at=0;
   entry.output_path=check.actualPath;entry.filename=check.expectedRelativeFilename;
   entry.expected_actual_path=check.actualPath.replace(/\\/g,'/');
entry.detected_extension='mp4';
  }else if(reportedState==='mismatch'){
   entry.status='failed';entry.failure_kind='download_path';entry.error='DOWNLOAD_PATH_MISMATCH';
   entry.actual_path=check.actualPath;entry.path_verified=false;
  }else{
   entry.status=entry.attempts<3?'waiting':'failed';entry.failure_kind='download';entry.retry_at=Date.now()+10000;entry.error=reason||'Chrome 下载中断';
  }
 });
 const completed=reportedState==='complete';
 await dlLog(completed?'DOWNLOAD_PATH_COMPLETED':reportedState==='mismatch'?'DOWNLOAD_PATH_MISMATCH':'chrome_download_'+state,{...dlEntry(entry),expectedRelativeFilename:check?.expectedRelativeFilename,actualPath:check?.actualPath||''});
 const actualPath=check?.actualPath||'';
 await dlEvent(entry,completed?'video_download_completed':'video_download_failed',{download_id:id,output_path:actualPath,actual_path:actualPath,local_path:actualPath,download_path:actualPath,path_verified:completed,mime_type:entry.mime_type||'',extension:entry.detected_extension||'',message:completed?'下载完成':reportedState==='mismatch'?'DOWNLOAD_PATH_MISMATCH':(reason||'Chrome 下载中断，将在重试上限内自动重试')});
 if(completed)await dlMutate(()=>{entry.completion_path_synced=true;entry.qc_recovery_v27=true;entry.path_verified=true;});
}
async function dlFinish(id,state,reason=''){
 await dlLoaded;await dlSerial;
 if(dlState.entries.some(e=>(e.blocked_download_ids||[]).includes(id)))return;
 if(dlState.entries.some(e=>e.download_id===id&&e.target_folder))return dlFinishTarget(id,state,reason);
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
  const eventType=state==='complete'?'video_download_completed':'video_download_failed';
  await dlEvent(entry,eventType,{download_id:id,output_path,local_path:output_path,download_path:output_path,path_verified:!!output_path,mime_type:entry.mime_type||'',extension:entry.detected_extension||'',message:state==='complete'?'下载完成':(reason||'Chrome 下载中断，将在重试上限内自动重试')});
  if(state==='complete' && output_path) await dlMutate(()=>{const e=dlState.entries.find(x=>x.key===entry.key);if(e){e.output_path=output_path;e.completion_path_synced=true;e.qc_recovery_v27=true;}});
 }
}
function dlDetermineFilename(item,suggest){
 if(!dlRegistryReady){void dlLoaded.then(()=>dlDetermineFilename(item,suggest)).catch(()=>suggest());return true;}
 const itemUrl=String(item?.url||''),finalUrl=String(item?.finalUrl||'');
 const candidates=(dlState.entries||[]).filter(e=>['starting','downloading'].includes(e.status));
 let entry=candidates.find(e=>e.download_id!=null&&e.download_id===item.id);
 if(!entry && (!item.byExtensionId||item.byExtensionId===chrome.runtime.id)){
  const matching=candidates.filter(e=>{const u=String(e.url||'');return !!u&&(u===itemUrl||u===finalUrl);});
  if(matching.length===1)entry=matching[0];
 }
 // IDs or full URLs only. No singleton or query-stripped fallback, including legacy/B-roll.
 if(!entry){suggest();return;}
 if(entry.target_folder){
const ext='.mp4';
  const resolved=dlChromeRelativeFilename(entry,item,ext);
  entry.download_id=item.id;
  entry.filename=resolved.relativeFilename;entry.suggest_filename=resolved.suggestFilename;
  entry.expected_actual_path=resolved.actualPath;
  entry.detected_extension=ext.replace(/^\./,'');entry.mime_type=String(item?.mime||'');
  void dlLog('DOWNLOAD_FILENAME_FINAL',{group:entry.group,task_type:entry.info?.task_type||'VIDEO',channel:entry.info?.channel_key||'',final_filename:resolved.suggestFilename});
  void dlLog('DOWNLOAD_FILENAME_SUGGESTED',{group:entry.group,task_id:entry.info?.task_id,filename_base:entry.filename_base,detectedExtension:ext,suggestFilename:resolved.suggestFilename});
  suggest({filename:resolved.suggestFilename,conflictAction:'overwrite'});
  return;
 }
const ext='.mp4';
const base=entry.filename_base||String(entry.filename).replace(/\.mp4$/i,'');
 const resolved=base+ext;
 entry.filename_base=base;entry.filename=resolved;entry.detected_extension=ext.replace(/^\./,'');entry.mime_type=String(item?.mime||'');
 void dlLog('DOWNLOAD_FILENAME_FINAL',{group:entry.group,task_type:entry.info?.task_type||'VIDEO',channel:entry.info?.channel_key||'',final_filename:resolved});
 void dlMutate(()=>{});
 suggest({filename:resolved,conflictAction:'overwrite'});
}
if(chrome.downloads.onDeterminingFilename?.addListener)chrome.downloads.onDeterminingFilename.addListener(dlDetermineFilename);
chrome.downloads.onChanged.addListener(delta=>{if(delta.state && ['complete','interrupted'].includes(delta.state.current))void dlFinish(delta.id,delta.state.current,delta.error?.current||'').then(dlPump);});
async function dlProbeWaiting(){ return; }
function dlSummary(group, entries) {
 const counts={};for(const e of entries)counts[e.status]=(counts[e.status]||0)+1;
 const d=dlDiagnostics.get(group);
 const parts=['v1.7', '已登记 '+entries.length, '待绑定 '+(counts.reserved||0), '待下载 '+(counts.ready||0), '下载完成 '+(counts.complete||0)];
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
let dlLastStudioReconcile=0;
// A 'waiting' entry is only a "result not seen yet" marker. It must end when Studio no longer
// expects that result (re-dispatched on another channel, already completed, cancelled) or when
// it is clearly stale; otherwise the plugin's 生成中 counter grows forever.
async function dlReconcileWithStudio(){
 if(Date.now()-dlLastStudioReconcile<30000)return;dlLastStudioReconcile=Date.now();
 const waiting=dlState.entries.filter(e=>e.status==='waiting'&&e.info?.segment_id!=null);
 if(!waiting.length)return;
 let states=null;
 try{
  const ids=[...new Set(waiting.map(e=>Number(e.info.segment_id)).filter(Number.isFinite))];
  const r=await fsFetch('/segment-states',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({segment_ids:ids})});
  if(r.ok)states=(await r.json()).states||{};
 }catch(_){}
 const now=Date.now(),stale=90*60000,hardStale=3*3600000;
 const reasonFor=e=>{
  const age=now-Number(e.submitted_at||e.created_at||now),s=states?states[String(e.info.segment_id)]:null;
  if(s){
   if(s.missing)return 'Studio 中已不存在该片段';
   if(s.cancelled)return 'Studio 中该片段已撤销/作废';
   if(s.command&&e.info.command_id&&s.command!==e.info.command_id)return '该片段已被新一轮任务取代';
   if(s.done)return 'Studio 已收到该片段的结果';
   if(age>stale&&!['生成中','已提交','下载中'].includes(s.flow_status))return 'Studio 不再等待此结果（'+s.flow_status+'）';
  }
  if(age>hardStale)return '超过3小时仍未取得结果';
  return '';
 };
 const doomed=waiting.map(e=>[e,reasonFor(e)]).filter(x=>x[1]);
 if(!doomed.length)return;
 try{await dlMutate(()=>{for(const [e,why] of doomed)if(e.status==='waiting'){e.status='cancelled';e.error=why;}});}catch(_){}
 try{await dlLog('WAITING_ENTRIES_RETIRED',{count:doomed.length,reasons:[...new Set(doomed.map(x=>x[1]))]});}catch(_){}
}
async function dlTickOnce(){
 await dlLoaded;await dlSerial;
 try{await dlReconcileWithStudio();}catch(_){}
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
   if(['complete','interrupted'].includes(rows[0]?.state))await dlFinish(e.download_id,rows[0].state,rows[0].error||'');
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
   if(e.target_folder){await dlFinish(e.download_id,'complete');continue;}
   const rows=await chrome.downloads.search({id:e.download_id});
   const output_path=String(rows[0]?.filename||'');
   if(output_path){await dlEvent(e,'video_download_completed',{download_id:e.download_id,output_path,local_path:output_path,download_path:output_path,path_verified:true,mime_type:e.mime_type||'',extension:e.detected_extension||'',message:'下载完成 · 路径同步'});await dlMutate(()=>{e.output_path=output_path;e.completion_path_synced=true;e.qc_recovery_v27=true;});}
  }catch(_){}
 }
 await dlPump();
}
async function dlRecover(){
 await dlLoaded;
 for(const e of dlState.entries.filter(e=>!(e.target_folder&&e.error==='DOWNLOAD_PATH_MISMATCH')&&(['starting','downloading'].includes(e.status)||(e.status==='failed'&&e.download_id!=null)))){
  const rows=await chrome.downloads.search(e.download_id!=null?{id:e.download_id}:{query:[e.filename.split('/').pop()],startedAfter:new Date(e.created_at).toISOString()});
  const item=e.download_id!=null?rows.find(r=>r.id===e.download_id):rows.find(r=>r.filename.replace(/\\/g,'/').endsWith('/'+e.filename));
  if(e.target_folder&&item?.state==='complete'){await dlMutate(()=>{e.download_id=item.id;});await dlFinish(item.id,'complete');continue;}
  await dlMutate(()=>{if(item){e.download_id=item.id;e.status=item.state==='complete'?'complete':item.state==='interrupted'?'failed':'downloading'}else{e.status='ready'}});
 }
 // One-time recovery of old failed transfers. Never reopen a completed entry or Flow generation failure.
 await dlMutate(()=>{
  for(const e of dlState.entries){
   if((e.target_folder&&e.error==='DOWNLOAD_PATH_MISMATCH')||e.recovery_v094)continue;e.recovery_v094=true;
   if(e.status==='failed'&&e.media_id&&e.failure_kind!=='generation'&&e.error!=='Flow 视频生成失败'){
    e.status='waiting';e.attempts=0;e.retry_at=0;e.probe_message='重新检查旧版未完成下载';
   }
  }
 });
 await dlTick();
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
// v1.3: seed the "Chrome download folder is FlowStudio_Channels" flag from this profile's own history,
// so even the first download after an update is saved to the right place.
void (async()=>{try{
 await dlLoaded;
 if(dlState.chrome_root_is_channels!==undefined)return;
 const rows=await chrome.downloads.search({orderBy:['-startTime'],limit:200,state:'complete'});
 const nested=rows.some(r=>/\/FlowStudio_Channels\/FlowStudio_Channels\//.test(String(r.filename||'').replace(/\\/g,'/')));
 if(nested)await dlMutate(()=>{dlState.chrome_root_is_channels=true;});
}catch(_){}})();
