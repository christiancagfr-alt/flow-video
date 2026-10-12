function trustedFlowSender(sender){
 try{return sender.id===chrome.runtime.id && new URL(sender.url||sender.tab?.url||'').origin==='https://flow.google.com';}catch(_){return false;}
}
importScripts('background-runtime.js');
chrome.runtime.onMessage.addListener((msg,sender,reply)=>{
 if(!trustedFlowSender(sender))return;
 if(msg?.type!=='FS_REBALANCE_ACK')return;
 (async()=>{
  if(!sender.tab?.id)throw Error('缺少通道标签页');
  const owner=(await browserInstanceReady)+':'+sender.tab.id;
  const r=await fsFetch('/rebalance-ack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...msg,owner})});
  if(!r.ok)throw Error('撤回确认失败');return await r.json();
 })().then(reply).catch(e=>reply({ok:false,error:String(e)}));return true;
});
async function claimBrowserCommand(command,sender,segment_id,recovery=false){
 if(!sender.tab?.id)throw Error('缺少通道标签页');
 const owner=(await browserInstanceReady)+':'+sender.tab.id;
 const response=await fsFetch('/claim-command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command_id:command,owner,segment_id,recovery:!!recovery})});
 if(!response.ok)throw Error('任务归属确认失败');return await response.json();
}
chrome.runtime.onMessage.addListener((msg,sender,reply)=>{
 if(!trustedFlowSender(sender))return;
 if(msg?.type!=='FS_CLAIM_COMMAND')return;
 claimBrowserCommand(msg.command_id,sender,msg.segment_id,!!msg.recovery).then(reply).catch(e=>reply({ok:false,error:String(e.message||e)}));return true;
});
// A profile-local identity prevents tab IDs from colliding across Chrome profiles.
const browserInstanceReady=chrome.storage.local.get('flowStudioBrowserInstance').then(async d=>{
 const id=d.flowStudioBrowserInstance||crypto.randomUUID();
 if(!d.flowStudioBrowserInstance)await chrome.storage.local.set({flowStudioBrowserInstance:id});return id;
});
const focusedRequests=new Set();
async function focusOwnedChannels(requests){
 const owner=await browserInstanceReady;
 for(const req of requests||[]){
  if(req.browser_instance!==owner || req.expires*1000<Date.now() || focusedRequests.has(req.id))continue;
  focusedRequests.add(req.id);if(focusedRequests.size>200)focusedRequests.delete(focusedRequests.values().next().value);
  try{
   const tab=await chrome.tabs.get(Number(req.tab_id));
   const actual=new URL(tab.url),expected=new URL(req.url);
   if(actual.origin!==expected.origin || actual.pathname.replace(/\/+$/,'')!==expected.pathname.replace(/\/+$/,''))throw Error('原标签页已切换到其他页面，请重新打开对应通道');
   await chrome.tabs.update(tab.id,{active:true});
   await chrome.windows.update(tab.windowId,{focused:true});
   await pushEvent({type:'channel_focus_completed',channel_id:req.channel_id,request_id:req.id,message:'已定位对应通道'});
  }catch(error){await pushEvent({type:'channel_focus_failed',channel_id:req.channel_id,request_id:req.id,message:String(error.message||error)});}
 }
}
let bridgePort = 17831;
let BASE = 'http://127.0.0.1:' + bridgePort;
const BRIDGE_PORT_KEY='flowStudioBridgePort';
chrome.storage.local.get(BRIDGE_PORT_KEY).then(d=>{const n=Number(d[BRIDGE_PORT_KEY]||17831);if(Number.isInteger(n)&&n>=1024&&n<=65535){bridgePort=n;BASE='http://127.0.0.1:'+bridgePort;}}).catch(()=>{});
let token = '';
let jobs = [];
let jobsVersion = -1;
let controlVersion = -1;
let progressScanVersion = -1;
let generationPaused = false;
let channelConfigs = [];
let heartbeatInFlight=null;
let pollJobsInFlight=null;
let lastSuccessfulContact=0;
let lastJobsPollOk=0;
let reconnectAttempts=0;
let lastReconnectLog=0;
let sourceFetchInFlight=new Set();
let lastSourcePoll=0;
const tabReloadAttemptAt=new Map();
let lastBackgroundWakeAt=0;
const BACKGROUND_WAKE_MIN_MS=5000;
let backgroundWakeInFlight=null;
const backgroundGuardFailures=new Map();

function arrayBufferToBase64(buffer){
  const bytes=new Uint8Array(buffer);let binary='';const chunk=0x8000;
  for(let i=0;i<bytes.length;i+=chunk)binary+=String.fromCharCode(...bytes.subarray(i,Math.min(i+chunk,bytes.length)));
  return btoa(binary);
}

async function postSourceResult(job,result,error=''){
  const r=await fsFetch('/source-result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:job.job_id,kind:job.kind,result:result||{},error:String(error||'')})});
  if(!r.ok)throw new Error('source-result HTTP '+r.status);
}

async function executeSourceFetch(job){
  if(!job?.job_id || sourceFetchInFlight.has(job.job_id))return;
  sourceFetchInFlight.add(job.job_id);
  try{
    void pluginLog('source_fetch_started',{job_id:job.job_id,kind:job.kind,url:job.url});
    const r=await fetch(job.url,{credentials:'include',redirect:'follow',cache:'no-store',signal:AbortSignal.timeout(30000)});
    if(!r.ok)throw new Error('Google source HTTP '+r.status);
    if(job.kind==='asset_file'){
      const contentType=(r.headers.get('Content-Type')||'').toLowerCase();
      if(contentType.includes('text/html'))throw new Error('Drive 返回了网页而不是图片；可能需要重新登录或素材链接没有访问权限');
      const buf=await r.arrayBuffer();
      if(!buf.byteLength)throw new Error('素材文件为空');
      await postSourceResult(job,{base64:arrayBufferToBase64(buf),content_type:contentType,final_url:r.url,size:buf.byteLength});
    }else{
      const text=await r.text();
      await postSourceResult(job,{text,content_type:r.headers.get('Content-Type')||'',final_url:r.url});
    }
    void pluginLog('source_fetch_completed',{job_id:job.job_id,kind:job.kind});
  }catch(e){
    try{await postSourceResult(job,{},String(e?.message||e));}catch(_){}
    void pluginLog('source_fetch_failed',{job_id:job?.job_id,kind:job?.kind,error:String(e?.message||e)});
  }finally{sourceFetchInFlight.delete(job.job_id);}
}

async function pollSourceJobs(){
  if(!token)return;
  try{
    const r=await fsFetch('/source-jobs');if(!r.ok)return;
    const d=await r.json();if(!d?.ok)return;
    for(const job of (d.jobs||[]).slice(0,8))void executeSourceFetch(job);
  }catch(e){void pluginLog('source_jobs_poll_failed',{error:String(e?.message||e)});}
}

const PLUGIN_LOG_KEY='flowStudioRuntimeLogsV0921';
let runtimeLogs=[],runtimeLogSerial=Promise.resolve(),lastConnectionState=null,lastHeartbeatLog=0;
const runtimeLogLoaded=chrome.storage.local.get(PLUGIN_LOG_KEY).then(d=>{runtimeLogs=Array.isArray(d[PLUGIN_LOG_KEY])?d[PLUGIN_LOG_KEY].slice(-3000):[];});
function safeLogValue(v){
  if(v==null)return v;
  if(typeof v==='string')return v.length>500?v.slice(0,500)+'…':v;
  if(Array.isArray(v))return v.slice(0,100).map(safeLogValue);
  if(typeof v==='object'){const o={};for(const [k,x] of Object.entries(v)){if(/prompt|dialogue|text/i.test(k))continue;o[k]=safeLogValue(x)}return o;}
  return v;
}
function pluginLog(stage,detail={}){
  const row={time:new Date().toISOString(),stage,...safeLogValue(detail)};
  console.info('[FlowStudio runtime]',row);
  const p=runtimeLogSerial.then(async()=>{await runtimeLogLoaded;runtimeLogs.push(row);runtimeLogs=runtimeLogs.slice(-3000);await chrome.storage.local.set({[PLUGIN_LOG_KEY]:runtimeLogs});});
  runtimeLogSerial=p.catch(()=>{});return p;
}
async function pluginDiagnostics(){await runtimeLogLoaded;await runtimeLogSerial;return {version:'0.9.66',background_runtime:FlowStudioBackground.diagnostics(),exported_at:new Date().toISOString(),connected:!!token,jobsVersion,job_count:jobs.length,lastSuccessfulContact,lastJobsPollOk,reconnectAttempts,channels:channelConfigs.map(c=>({channel_key:c.channel_key,id:c.id,role:c.role,collection_url:c.collection_url})),jobs:jobs.map(j=>({channel_key:j.channel_key,channel_id:j.channel_id,command_id:j.command_id,collection_url:j.collection_url,task_count:(j.tasks||[]).length,execute_upload:!!j.execute_upload,dispatch_tasks:!!j.dispatch_tasks})),logs:runtimeLogs.slice()};}
const tabJobMemo=new Map();
const tabChannelMemo=new Map();

function normUrl(raw='') {
  try {
    const u = new URL(raw);
    return u.origin + u.pathname.replace(/\/+$/, '');
  } catch (_) {
    return String(raw).replace(/[?#].*$/, '').replace(/\/+$/, '');
  }
}
function normFullUrl(raw='') {
  try {
    const u=new URL(raw);
    const params=[...u.searchParams.entries()].sort((a,b)=>a[0].localeCompare(b[0])||String(a[1]).localeCompare(String(b[1])));
    const q=new URLSearchParams(params).toString();
    return u.origin+u.pathname.replace(/\/+$/,'')+(q?'?'+q:'');
  } catch (_) {
    return String(raw).replace(/#.*$/,'').replace(/\/+$/,'');
  }
}

async function heartbeat(force=false) {
  if(heartbeatInFlight && !force)return heartbeatInFlight;
  heartbeatInFlight=(async()=>{
    const started=Date.now();
    try {
      const r = await fetch(BASE + '/heartbeat', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          extensionId:chrome.runtime.id,
          extensionVersion:chrome.runtime.getManifest().version,
          mode:'flowstudio-web-v0923-background-resilient',
          time:Date.now(),
          reconnectAttempt:reconnectAttempts
        }),
        signal:AbortSignal.timeout(5000)
      });
      if(!r.ok)throw new Error('heartbeat HTTP '+r.status);
      const d = await r.json();
      if (!d?.token) throw new Error('heartbeat missing token');
      const wasDisconnected=!token || lastConnectionState===false;
      token=d.token;
      lastSuccessfulContact=Date.now();
      reconnectAttempts=0;
      const ok=!!d?.ok;
      if(wasDisconnected || lastConnectionState!==ok || Date.now()-lastHeartbeatLog>30000){
        void pluginLog(wasDisconnected?'studio_reconnected':'studio_heartbeat',
          {ok,http_status:r.status,latency_ms:Date.now()-started});
        lastHeartbeatLog=Date.now();lastConnectionState=ok;
      }
      return ok;
    } catch (e) {
      token='';
      reconnectAttempts++;
      const now=Date.now();
      if(lastConnectionState!==false || now-lastReconnectLog>8000){
        void pluginLog('studio_connection_lost',{
          error:String(e?.message||e),attempt:reconnectAttempts,last_success_age_ms:lastSuccessfulContact?now-lastSuccessfulContact:null
        });
        lastReconnectLog=now;lastHeartbeatLog=now;lastConnectionState=false;
      }
      return false;
    } finally {
      heartbeatInFlight=null;
    }
  })();
  return heartbeatInFlight;
}

async function fsFetch(path, options={}, retryAuth=true) {
  if(!token && !(await heartbeat()))throw new Error('本地 Studio 未连接');
  const headers = {...(options.headers || {})};
  if (token) headers['X-FlowStudio-Token'] = token;
  const supplied=options.signal;
  const opts={...options,headers,signal:supplied || AbortSignal.timeout(7000)};
  try{
    let r=await fetch(BASE + path, opts);
    if((r.status===401 || r.status===403) && retryAuth){
      const oldToken=token;token='';
      void pluginLog('studio_token_rejected',{path,status:r.status,had_token:!!oldToken});
      if(await heartbeat(true)){
        const h2={...(options.headers||{}),'X-FlowStudio-Token':token};
        r=await fetch(BASE+path,{...options,headers:h2,signal:options.signal || AbortSignal.timeout(7000)});
        if(r.ok)void pluginLog('studio_request_recovered_after_reauth',{path,status:r.status});
      }
    }
    if(r.ok)lastSuccessfulContact=Date.now();
    return r;
  }catch(e){
    token='';
    void pluginLog('studio_request_transport_error',{path,error:String(e?.message||e)});
    throw e;
  }
}

async function ensureStudioConnection(reason='tick') {
  if(token && lastSuccessfulContact && Date.now()-lastSuccessfulContact<4500)return true;
  const ok=await heartbeat();
  if(ok && reason!=='tick')void pluginLog('studio_connection_verified',{reason});
  return ok;
}

const OUTBOX_KEY='flowStudioEventOutboxV085';
let outbox=[], flushing=false, mutation=Promise.resolve();
const loaded=chrome.storage.local.get(OUTBOX_KEY).then(data=>{outbox=Array.isArray(data[OUTBOX_KEY])?data[OUTBOX_KEY]:[];});
function mutateOutbox(fn) {
  const result=mutation.then(async()=>{await loaded; await fn(); await chrome.storage.local.set({[OUTBOX_KEY]:outbox});});
  mutation=result.catch(()=>{}); return result;
}
async function pushEvent(event) {
  event={...event,browser_instance:await browserInstanceReady};
  void pluginLog('event_queued',{type:event?.type,channel_key:event?.channel_key,host_id:event?.host_id,segment_id:event?.segment_id,command_id:event?.command_id,message:event?.message,error:event?.error});
  await mutateOutbox(()=>{
    const coalesced=['web_plugin_progress_snapshot','web_plugin_heartbeat','media_match_progress','upload_flow_progress','generation_progress'];
    if(coalesced.includes(event.type)) outbox=outbox.filter(x=>!(x.type===event.type && x.host_id===event.host_id && x.command_id===event.command_id && String(x.channel_key||'')===String(event.channel_key||'')));
    outbox.push({...event,event_id:event.event_id || crypto.randomUUID()});
  });
  void flushEvents();
  return true; // Durably queued; HTTP delivery may follow after reconnection.
}
async function flushEvents() {
  if(flushing)return;
  flushing=true;
  try {
    await loaded;
    if(!outbox.length)return;
    if(!token && !(await heartbeat()))return;
    for(let i=0;i<25;i++) {
      await mutation;
      const telemetry=new Set(['web_plugin_heartbeat','web_plugin_progress_snapshot','generation_progress','media_match_progress','upload_flow_progress']);
      const event=outbox.find(e=>!telemetry.has(e.type)) || outbox[0]; if(!event)break;
      try {
        const r=await fsFetch('/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(event),signal:AbortSignal.timeout(8000)});
        if(!r.ok) { void pluginLog('event_delivery_http_error',{status:r.status,type:event?.type,event_id:event?.event_id}); if(r.status===401 || r.status===403)token=''; break; }
        await mutateOutbox(()=>{outbox=outbox.filter(x=>x.event_id!==event.event_id);});
      } catch (e) { void pluginLog('event_delivery_failed',{type:event?.type,event_id:event?.event_id,error:String(e?.message||e)}); break; }
    }
  } finally { flushing=false; }
}

async function pollJobs() {
  if(pollJobsInFlight)return pollJobsInFlight;
  pollJobsInFlight=(async()=>{
    void flushEvents();
    if (!(await ensureStudioConnection('poll_jobs'))) {
      broadcast({type:'FS_STUDIO_CONNECTION', connected:false});
      return false;
    }
    try {
      const r = await fsFetch('/host-jobs?eye_reference=1');
      if(!r.ok)throw new Error('host-jobs HTTP '+r.status);
      const d = await r.json();
      if (!d?.ok)throw new Error(d?.error||'host-jobs not ok');
      await focusOwnedChannels(d.focus_requests);
      jobs = Array.isArray(d.jobs) ? d.jobs : [];
      channelConfigs = Array.isArray(d.channels) ? d.channels : [];
      lastJobsPollOk=Date.now();
      lastSuccessfulContact=Date.now();
      if (d.version !== jobsVersion) {
        jobsVersion = d.version;
        void pluginLog('jobs_changed',{
          version:jobsVersion,count:jobs.length,scheduled_total:d.scheduled_total,released_total:d.released_total,
          jobs:jobs.map(j=>({browser_group:j.browser_group||'',channel_key:j.channel_key,command_id:j.command_id,
                            task_count:(j.tasks||[]).length,release_at:j.release_at||0,collection_url:j.collection_url}))
        });
        // Wake every Flow tab immediately when Studio publishes a new batch.
        // Content scripts still keep their channel binding, so this does not
        // duplicate submission; it only removes the wait for the next UI poll.
        await broadcast({type:'FS_STUDIO_JOBS_CHANGED', version:jobsVersion});
      }
      if(lastConnectionState!==true){
        void pluginLog('studio_connection_restored_by_jobs',{job_count:jobs.length});
      }
      lastConnectionState=true;
      broadcast({type:'FS_STUDIO_CONNECTION', connected:true});
      void reportChannelPresence();
      return true;
    } catch (e) {
      token='';
      lastConnectionState=false;
      void pluginLog('jobs_poll_failed',{error:String(e?.message||e),attempt:reconnectAttempts});
      broadcast({type:'FS_STUDIO_CONNECTION', connected:false});
      return false;
    }
  })().finally(()=>{pollJobsInFlight=null;});
  return pollJobsInFlight;
}

async function pollGenerationControl() {
  if (!token && !(await heartbeat())) return;
  try {
    const r = await fsFetch('/generation-control');
    const d = await r.json();
    if (!d?.ok) return;
    generationPaused = !!d.paused;
    if (d.control_version !== controlVersion) {
      controlVersion = d.control_version;
      broadcast({type:'FS_GENERATION_CONTROL', paused:generationPaused, controlVersion});
    }
    if (d.progress_scan_version !== progressScanVersion) {
      progressScanVersion = d.progress_scan_version;
      broadcast({type:'FS_PROGRESS_SCAN', scanVersion:progressScanVersion});
    }
  } catch (e) {
    token='';
    void pluginLog('generation_control_poll_failed',{error:String(e?.message||e)});
  }
}

async function setGenerationPaused(paused) {
  if (!token && !(await heartbeat())) throw new Error('本地 Studio 未连接');
  const r = await fsFetch('/generation-control', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({paused:!!paused})
  });
  const d = await r.json();
  if (!r.ok || !d?.ok) throw new Error(d?.error || ('HTTP '+r.status));
  generationPaused = !!d.paused;
  controlVersion = d.control_version;
  broadcast({type:'FS_GENERATION_CONTROL', paused:generationPaused, controlVersion});
  return d;
}

async function broadcast(msg) {
  const tabs = await chrome.tabs.query({url:['https://flow.google.com/*']});
  for (const tab of tabs) {
    try { await chrome.tabs.sendMessage(tab.id, msg); } catch (_) {}
  }
}

async function jobForTab(tab) {
  if (!tab?.url) return null;
  const hereFull=normFullUrl(tab.url), herePath=normUrl(tab.url);
  // Prefer the exact configured channel link, including query parameters.
  const exact=jobs.filter(j=>normFullUrl(j?.collection_url||'')===hereFull);
  const pathMatches=jobs.filter(j=>normUrl(j?.collection_url||'')===herePath);
  let job=exact.length===1 ? exact[0] : (pathMatches.length===1 ? pathMatches[0] : null);
  // Flow can normalize/remove a collection query after the tab loads. Once this tab
  // has been matched to a configured channel, keep that tab-local identity instead of
  // asking the plugin UI for a number/name.
  if(!job && tab?.id!=null){
    const remembered=String(tabChannelMemo.get(tab.id)||'');
    if(remembered){
      const m=jobs.filter(j=>String(j?.channel_key||'')===remembered);
      if(m.length===1)job=m[0];
    }
  }
  if(job && tab?.id!=null)tabChannelMemo.set(tab.id,String(job.channel_key||''));
  const key=job?`${job.channel_key||''}|${job.command_id||''}`:'none';
  if(tab?.id!=null && tabJobMemo.get(tab.id)!==key){tabJobMemo.set(tab.id,key);void pluginLog('tab_job_binding',{tab_id:tab.id,url:hereFull,matched:!!job,exact_matches:exact.length,path_matches:pathMatches.length,remembered_channel:tabChannelMemo.get(tab.id)||'',channel_key:job?.channel_key||'',command_id:job?.command_id||'',task_count:(job?.tasks||[]).length});}
  return job;
}


function channelForTab(tab) {
  if(!tab?.url)return null;
  const full=normFullUrl(tab.url),path=normUrl(tab.url);
  const exact=channelConfigs.filter(c=>normFullUrl(c?.collection_url||'')===full);
  const pathMatches=channelConfigs.filter(c=>normUrl(c?.collection_url||'')===path);
  let ch=exact.length===1?exact[0]:(pathMatches.length===1?pathMatches[0]:null);
  if(!ch && tab?.id!=null){
    const remembered=String(tabChannelMemo.get(tab.id)||'');
    if(remembered)ch=channelConfigs.find(c=>String(c.channel_key||'')===remembered)||null;
  }
  if(ch && tab?.id!=null)tabChannelMemo.set(tab.id,String(ch.channel_key||''));
  return ch;
}
let lastIdleChannelReport=0;
async function reportChannelPresence() {
  if(!token || !channelConfigs.length)return;
  if(Date.now()-lastIdleChannelReport<3500)return;
  lastIdleChannelReport=Date.now();
  let tabs=[];try{tabs=await chrome.tabs.query({url:['https://flow.google.com/*']});}catch(_){return;}
  for(const tab of tabs){
    const ch=channelForTab(tab);if(!ch)continue;
    // Ask Chrome not to discard long-running Flow worker tabs when windows are minimized.
    // This is best-effort: the OS can still suspend the whole browser/computer.
    if(tab.id!=null){ try{ await chrome.tabs.update(tab.id,{autoDiscardable:false}); }catch(_){} }
    // If Chrome already discarded a worker tab, a released job cannot execute its content script.
    // Recover it in-place (without activating the window) with a per-tab cooldown.
    if(tab.discarded && tab.id!=null){
      const last=Number(tabReloadAttemptAt.get(tab.id)||0);
      if(Date.now()-last>30000){
        tabReloadAttemptAt.set(tab.id,Date.now());
        try{await chrome.tabs.reload(tab.id);void pluginLog('discarded_tab_reload_requested',{tab_id:tab.id,channel_key:String(ch.channel_key||'')});}catch(e){void pluginLog('discarded_tab_reload_failed',{tab_id:tab.id,channel_key:String(ch.channel_key||''),error:String(e?.message||e)});}
      }
    }
    const pageState=tab.discarded?'discarded':(tab.frozen?'frozen':(tab.status==='loading'?'loading':(tab.active?'complete':'background')));
    // v0.9.48: heartbeat busy/idle must describe the SAME scheduler truth as the
    // currently bound Bridge job. Older builds always emitted idle_channel=true and
    // command_id='', even while the tab owned an active wave. Studio therefore showed
    // an idle channel while its scheduler correctly kept the submission slot occupied.
    const boundJob=await jobForTab(tab);
    const actionable=!!(boundJob?.command_id && (boundJob.dispatch_tasks || boundJob.auto_execute || boundJob.execute_upload));
    const idle=!actionable;
    const msg=tab.discarded?'通道标签页被Chrome丢弃，已请求后台恢复':(tab.frozen?'通道标签页被Chrome冻结，正在请求后台解冻':(idle?(tab.active?'通道标签页在线 · 空闲':'通道标签页后台在线 · 空闲'):'通道标签页在线 · 正在执行任务'));
    void pushEvent({type:'web_plugin_heartbeat',host_id:0,recipient_id:0,channel_id:Number(ch.id)||0,channel_key:String(ch.channel_key||''),channel_role:String(ch.role||'normal'),browser_group:String(ch.browser_group||''),command_id:actionable?String(boundJob.command_id||''):'',collection_url:String(ch.collection_url||tab.url||''),tab_id:tab.id,idle_channel:idle,job_active:actionable,dispatch_tasks:!!boundJob?.dispatch_tasks,execute_upload:!!boundJob?.execute_upload,tab_discarded:!!tab.discarded,tab_frozen:!!tab.frozen,tab_status:pageState,window_id:tab.windowId,message:msg});
  }
}

async function wakeActionableFlowTabs(force=false) {
  if(backgroundWakeInFlight)return backgroundWakeInFlight;
  const now=Date.now();
  if(!force && now-lastBackgroundWakeAt<BACKGROUND_WAKE_MIN_MS)return;
  lastBackgroundWakeAt=now;
  FlowStudioBackground.setLogger(pluginLog);
  backgroundWakeInFlight=(async()=>{
    const tabs=await chrome.tabs.query({url:['https://flow.google.com/*']});
    const wanted=new Set();
    for(const tab of tabs){
      const job=await jobForTab(tab);
      if(!job?.command_id || !(job.dispatch_tasks||job.auto_execute||job.execute_upload) || tab.id==null)continue;
      wanted.add(tab.id);
      try{
        await FlowStudioBackground.hold(tab.id,String(job.command_id));
        backgroundGuardFailures.delete(tab.id);
      }catch(error){
        const last=backgroundGuardFailures.get(tab.id)||0;
        if(now-last>30000){backgroundGuardFailures.set(tab.id,now);void pluginLog('background_guard_unavailable',{
          tab_id:tab.id,channel_key:job.channel_key,command_id:job.command_id,error:String(error?.message||error)});}
      }
      // Wake only existing task loops. Content checks command identity and its mutex.
      try{await chrome.tabs.sendMessage(tab.id,{type:'FS_BACKGROUND_WAKE',ts:now,command_id:String(job.command_id),macos_space_guard:true});}catch(_){}
    }
    for(const tabId of FlowStudioBackground.ids())if(!wanted.has(tabId))await FlowStudioBackground.release(tabId);
  })().catch(error=>{void pluginLog('background_wake_failed',{error:String(error?.message||error)});}).finally(()=>{backgroundWakeInFlight=null;});
  return backgroundWakeInFlight;
}

async function dispatchNativeFileDrag(tabId, paths, x, y) {
  const clean = [...new Set((paths || []).map(String).filter(Boolean))];
  if (!clean.length) throw new Error('没有可上传的本地文件路径');
  return FlowStudioBackground.run(tabId,async target=>{
    const dragData = {
      items: [{mimeType:'application/octet-stream', data:'', title:'', baseURL:''}],
      files: clean,
      dragOperationsMask: 1
    };
    const px = Number.isFinite(Number(x)) ? Number(x) : 640;
    const py = Number.isFinite(Number(y)) ? Number(y) : 420;
    for (const type of ['dragEnter','dragOver','drop']) {
      await chrome.debugger.sendCommand(target, 'Input.dispatchDragEvent', {
        type, x:px, y:py, data:dragData
      });
      if (type !== 'drop') await new Promise(r=>setTimeout(r,120));
    }
    return {ok:true, count:clean.length};
  });
}


async function pressNativeEnter(tabId) {
  return FlowStudioBackground.run(tabId,async target=>{
    await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {type:'keyDown', key:'Enter', code:'Enter', windowsVirtualKeyCode:13, nativeVirtualKeyCode:13});
    await new Promise(r=>setTimeout(r,45));
    await chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {type:'keyUp', key:'Enter', code:'Enter', windowsVirtualKeyCode:13, nativeVirtualKeyCode:13});
    return {ok:true};
  });
}

async function dispatchNativeClick(tabId, x, y) {
  const px=Number(x), py=Number(y);
  if(!Number.isFinite(px)||!Number.isFinite(py))throw new Error('无效的生成按钮坐标');
  return FlowStudioBackground.run(tabId,async target=>{
    await chrome.debugger.sendCommand(target,'Input.dispatchMouseEvent',{type:'mouseMoved',x:px,y:py,button:'none',buttons:0,pointerType:'mouse'});
    await new Promise(r=>setTimeout(r,35));
    await chrome.debugger.sendCommand(target,'Input.dispatchMouseEvent',{type:'mousePressed',x:px,y:py,button:'left',buttons:1,clickCount:1,pointerType:'mouse'});
    await new Promise(r=>setTimeout(r,55));
    await chrome.debugger.sendCommand(target,'Input.dispatchMouseEvent',{type:'mouseReleased',x:px,y:py,button:'left',buttons:0,clickCount:1,pointerType:'mouse'});
    return {ok:true,method:'chrome_debugger_native_click',x:px,y:py};
  });
}
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
 if(!trustedFlowSender(sender))return;
  if (msg?.type === 'FS_GET_BRIDGE_PORT') {
    sendResponse({ok:true,port:bridgePort,base:BASE});
    return true;
  }
  if (msg?.type === 'FS_SET_BRIDGE_PORT') {
    (async()=>{
      const n=Number(msg.port);
      if(!Number.isInteger(n)||n<1024||n>65535)throw new Error('端口必须在 1024-65535 之间');
      bridgePort=n;BASE='http://127.0.0.1:'+bridgePort;token='';lastSuccessfulContact=0;
      await chrome.storage.local.set({[BRIDGE_PORT_KEY]:bridgePort});
      const ok=await heartbeat(true);
      sendResponse({ok:true,port:bridgePort,connected:ok});
    })().catch(e=>sendResponse({ok:false,error:String(e?.message||e)}));
    return true;
  }
  if(msg?.type==='FS_ENSURE_BACKGROUND'){
    const tab=sender.tab;
    if(!tab?.id){sendResponse({ok:false,error:'missing_tab'});return;}
    (async()=>{
      const job=await jobForTab(tab);
      if(!job?.command_id || String(job.command_id)!==String(msg.command_id||''))return {ok:false,error:'COMMAND_CHANGED'};
      return await FlowStudioBackground.hold(tab.id,String(job.command_id));
    })().then(sendResponse).catch(error=>sendResponse({ok:false,error:String(error?.message||error)}));
    return true;
  }
  if (msg?.type === 'FS_PLUGIN_DIAGNOSTICS') {
    pluginDiagnostics().then(result=>sendResponse({ok:true,result})).catch(e=>sendResponse({ok:false,error:String(e?.message||e)}));
    return true;
  }
  if (msg?.type === 'FS_RUNTIME_LOG') {
    pluginLog(String(msg.stage||'content'),msg.detail||{}).then(()=>sendResponse({ok:true}));
    return true;
  }
  if (msg?.type === 'FS_GET_JOB') {
    (async()=>{
      if (!token || !lastJobsPollOk || Date.now()-lastJobsPollOk>3500) await pollJobs();
      sendResponse({ok:true, connected:!!token && !!lastJobsPollOk && Date.now()-lastJobsPollOk<8000,
                    job:await jobForTab(sender.tab), version:jobsVersion,
                    last_contact:lastSuccessfulContact,reconnect_attempts:reconnectAttempts});
    })();
    return true;
  }
  if (msg?.type === 'FS_CONNECTION_PING') {
    (async()=>{
      const ok=await ensureStudioConnection('content_ping');
      if(ok && (!lastJobsPollOk || Date.now()-lastJobsPollOk>2500))await pollJobs();
      sendResponse({ok,connected:!!token,last_contact:lastSuccessfulContact,reconnect_attempts:reconnectAttempts});
    })();
    return true;
  }
  if (msg?.type === 'FS_PUSH_EVENT') {
    pushEvent(msg.event || {}).then(ok=>sendResponse({ok,queued:true})).catch(e=>sendResponse({ok:false,error:String(e.message||e)}));
    return true;
  }
  if (msg?.type === 'FS_FORCE_SYNC') {
    pollJobs().then(()=>sendResponse({ok:true}));
    return true;
  }
  if (msg?.type === 'FS_SET_PAUSED') {
    setGenerationPaused(!!msg.paused)
      .then(result=>sendResponse({ok:true,result}))
      .catch(err=>sendResponse({ok:false,error:String(err?.message||err)}));
    return true;
  }
  if (msg?.type === 'FS_GET_CONTROL') {
    pollGenerationControl().then(()=>sendResponse({ok:true,paused:generationPaused,controlVersion,progressScanVersion}));
    return true;
  }
  if (msg?.type === 'FS_GET_FILE') {
    (async()=>{
      try {
        const path = String(msg.path || '');
        if (!path) throw new Error('缺少本地文件路径');
        if (!token && !(await heartbeat())) throw new Error('本地 Studio 未连接');
        const r = await fsFetch('/file?path=' + encodeURIComponent(path));
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const buf = await r.arrayBuffer();
        const h = r.headers.get('X-FlowStudio-Filename') || '';
        sendResponse({
          ok:true,
          filename:h ? decodeURIComponent(h) : path.split(/[\\/]/).pop(),
          mime:r.headers.get('Content-Type') || 'image/jpeg',
          bytes:Array.from(new Uint8Array(buf))
        });
      } catch (e) { sendResponse({ok:false,error:String(e?.message || e)}); }
    })();
    return true;
  }
  if (msg?.type === 'FS_PRESS_ENTER') {
    const tabId = sender.tab?.id;
    if (!tabId) { sendResponse({ok:false,error:'找不到当前 Flow 标签页'}); return; }
    pressNativeEnter(tabId)
      .then(result=>sendResponse(result))
      .catch(err=>sendResponse({ok:false,error:String(err?.message || err)}));
    return true;
  }
  if (msg?.type === 'FS_NATIVE_CLICK') {
    const tabId = sender.tab?.id;
    if (!tabId) { sendResponse({ok:false,error:'找不到当前 Flow 标签页'}); return; }
    dispatchNativeClick(tabId,msg.x,msg.y)
      .then(result=>sendResponse(result))
      .catch(err=>sendResponse({ok:false,error:String(err?.message || err)}));
    return true;
  }
  if (msg?.type === 'FS_NATIVE_DRAG') {
    const tabId = sender.tab?.id;
    if (!tabId) { sendResponse({ok:false,error:'找不到当前 Flow 标签页'}); return; }
    dispatchNativeFileDrag(tabId, msg.paths || [], msg.x, msg.y)
      .then(result=>sendResponse(result))
      .catch(err=>sendResponse({ok:false,error:String(err?.message || err)}));
    return true;
  }
});

chrome.tabs.onUpdated.addListener((tabId,changeInfo,tab)=>{
  if(!changeInfo.url)return;
  const ch=channelForTab({...tab,id:tabId,url:changeInfo.url});
  if(ch)void pluginLog('tab_channel_captured',{tab_id:tabId,channel_key:ch.channel_key,url:normFullUrl(changeInfo.url)});
});
chrome.tabs.onRemoved.addListener(tabId=>{tabJobMemo.delete(tabId);tabChannelMemo.delete(tabId);backgroundGuardFailures.delete(tabId);});

async function connectionTick(){
  const ok=await ensureStudioConnection('tick');
  if(ok){
    await pollJobs();
    void pollGenerationControl();
    void flushEvents();
    void wakeActionableFlowTabs(false);
    // Manual Studio OAuth sync owns Google source reads; no background source polling.
  }else{
    broadcast({type:'FS_STUDIO_CONNECTION',connected:false});
  }
}
void connectionTick();
setInterval(()=>void connectionTick(),1200);

// MV3 workers can sleep. Alarm + Flow content pings rebuild localhost connectivity automatically.
try{const alarm=chrome.alarms.create('flowstudio-keepalive',{periodInMinutes:0.5});alarm?.catch(()=>chrome.alarms.create('flowstudio-keepalive',{periodInMinutes:1}));}catch(_){chrome.alarms.create('flowstudio-keepalive',{periodInMinutes:1});}
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm?.name==='flowstudio-keepalive'){void connectionTick();void wakeActionableFlowTabs(true);}});
chrome.runtime.onStartup.addListener(()=>void connectionTick());
chrome.runtime.onInstalled.addListener(()=>void connectionTick());

importScripts('downloads.js');
