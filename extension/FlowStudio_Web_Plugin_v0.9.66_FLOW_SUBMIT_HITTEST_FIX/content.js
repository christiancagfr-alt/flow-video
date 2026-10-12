(() => {
  'use strict';
  if (window.__FLOW_STUDIO_WEB_V091__) return;
  window.__FLOW_STUDIO_WEB_V091__ = true;

  const state = {
    open: true,
    downloadSummary:"正在连接下载后台…",
    connected: false,
    job: null,
    tasks: [],
    media: [],
    matched: 0,
    scanTimer: null,
    scanSeq: 0,
    stableHits: 0,
    lastSignature: '',
    ready: false,
    message: '正在连接本地 Studio…',
    lastSync: '',
    uploadInFlight: false,
    uploadAttempts: 0,
    uploadStageStartedAt: 0,
    uploadProgressAt: 0,
    lastUploadAt: 0,
    lastRecognizedMediaCount: 0,
    autoUploadEnabled: true,
    identity: '',
    baseIdentity: '',
    workSignature: '',
    thumbnailUrls: new Map(),
    panelAutoHidden: false,
    lastBoundEmit: 0,
    generationRunning: false,
    scanInFlight: false,
    mediaScanValid: false,
    generationCommand: '',
    generationSubmitted: 0,
    generationFailed: 0,
    generationDeferred: 0,
    generationPaused: false,
    downloadCounts: {total:0,complete:0,failed:0,waiting:0,downloading:0,ready:0,reserved:0},
    lastProgressScanVersion: -1,
    bridgePort: 17831,
    skippedUploadNames: new Map(),
    skippedUploadFailureTasks: new Set(),
    failedUploadHistory: new Map()
  };

  function clearThumbnailCache(){
    for(const url of state.thumbnailUrls.values())URL.revokeObjectURL(url);
    state.thumbnailUrls.clear();
  }

  const $ = (s,r=document)=>r.querySelector(s);
  const esc = (s='')=>String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const safeMediaUrl = (value)=>{ try{ const url=new URL(String(value||''), location.href); if(url.protocol==='https:'||url.protocol==='http:'||url.protocol==='blob:')return esc(url.href);}catch(_){} return ''; };
  const basename = p=>String(p||'').split(/[\\/]/).pop();
  const norm = s=>String(s||'').trim().toLowerCase();
  const nowText = ()=>new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});

  function expectedImageName(task) {
    return basename(task.image_path || task.reference_image || task.image || task.image_name || '');
  }

  function taskImagePath(task) {
    return String(task.image_path || task.reference_image || task.image || '').trim();
  }

  function documentNumber(task,index) {
    const explicit=task.document_number ?? task.script_number ?? task.copy_number ?? task.video_number;
    if(Number.isInteger(Number(explicit)) && Number(explicit)>0)return Number(explicit);
    // Studio task IDs such as 01-01 mean document 1, fragment 1.
    const pair=String(task.task_id||'').match(/^(\d+)[-_.](\d+)$/);
    return pair?Number(pair[1]):index+1;
  }
  function downloadMessage(message) {
    return new Promise((resolve,reject)=>{
      let settled=false;
      const timer=setTimeout(()=>{if(!settled){settled=true;reject(Error('BRIDGE_TIMEOUT:'+message.type));}},15000);
      chrome.runtime.sendMessage(message,result=>{
        if(settled)return;settled=true;clearTimeout(timer);
        const error=chrome.runtime.lastError?.message;
        if(error || !result?.ok)reject(Error(error||result?.error||'下载登记失败'));
        else resolve(result.result);
      });
    });
  }
  // MAIN-world Flow hooks publish a result as soon as Flow exposes it.
  // The background registry performs the exact ID check and ordered download.
  window.addEventListener('FLOW_STUDIO_VIDEO_READY',ev=>{
    const row=ev.detail?.row;
    if(!row || typeof row.id!=='string')return;
    downloadMessage({type:'FS_DOWNLOAD_OBSERVE',rows:[row],source:'flow_internal_realtime'}).catch(error=>{
      state.downloadSummary='实时下载通知失败：'+String(error.message||error);render();
    });
  });

  // MAIN-world page engine cannot call chrome.runtime directly. Bridge a narrowly-scoped
  // native click request to the extension background, which reuses the existing debugger
  // transport already used by native file drag. This produces a browser-level trusted click.
  // v0.9.66: the Flow Studio panel is a fixed, very-high-z-index overlay. When it is open it
  // can physically cover Flow's bottom-right Generate button, so CDP reports a successful
  // mouse dispatch while the click actually lands on this panel. Temporarily make only the
  // plugin root click-through, verify the underlying hit target, click once, then restore it.
  function nativeClickNodeInfo(node){
    if(!node)return {tag:'',id:'',className:'',ariaLabel:''};
    return {
      tag:String(node.tagName||'').toLowerCase(),
      id:String(node.id||''),
      className:typeof node.className==='string'?node.className:String(node.getAttribute?.('class')||''),
      ariaLabel:String(node.getAttribute?.('aria-label')||'')
    };
  }
  function isFlowGenerateHit(node){
    if(!node?.closest)return false;
    return !!node.closest('flow-generate-icon-button,button.generate-icon-button,button[aria-label="开始生成"],button[aria-label*="Generate"],button[type="submit"][aria-label*="生成"]');
  }
  window.addEventListener('FLOW_STUDIO_NATIVE_CLICK_REQUEST',ev=>{
    const d=ev.detail||{},requestId=String(d.request_id||'');
    if(!requestId)return;
    const x=Number(d.x),y=Number(d.y);
    const reply=(payload)=>window.dispatchEvent(new CustomEvent('FLOW_STUDIO_NATIVE_CLICK_RESULT',{detail:{request_id:requestId,...payload}}));
    const pluginRoot=document.getElementById('flow-studio-v050-root');
    const previousPointerEvents=pluginRoot?.style?.getPropertyValue('pointer-events')||'';
    const previousPriority=pluginRoot?.style?.getPropertyPriority('pointer-events')||'';
    let overlayBypassed=false,restored=false;
    const restore=()=>{
      if(restored)return;restored=true;
      if(!pluginRoot?.style)return;
      if(previousPointerEvents)pluginRoot.style.setProperty('pointer-events',previousPointerEvents,previousPriority);
      else pluginRoot.style.removeProperty('pointer-events');
    };
    const safetyTimer=setTimeout(restore,7000);
    try{
      if(!Number.isFinite(x)||!Number.isFinite(y))throw new Error('FLOW_NATIVE_CLICK_BAD_COORDINATES');
      let hit=document.elementFromPoint(x,y);
      if(pluginRoot && hit && pluginRoot.contains(hit)){
        pluginRoot.style.setProperty('pointer-events','none','important');
        overlayBypassed=true;
        // Force style/hit-test refresh before the debugger click is dispatched.
        void pluginRoot.offsetWidth;
        hit=document.elementFromPoint(x,y);
      }
      const hitInfo=nativeClickNodeInfo(hit);
      if(!isFlowGenerateHit(hit)){
        clearTimeout(safetyTimer);restore();
        return reply({ok:false,error:'FLOW_NATIVE_CLICK_TARGET_MISMATCH',overlay_bypassed:overlayBypassed,hit:hitInfo});
      }
      chrome.runtime.sendMessage({type:'FS_NATIVE_CLICK',x,y},result=>{
        clearTimeout(safetyTimer);restore();
        const err=chrome.runtime.lastError?.message;
        if(err)return reply({ok:false,error:err,overlay_bypassed:overlayBypassed,hit:hitInfo});
        reply({...((result&&typeof result==='object')?result:{ok:false,error:'native click 无响应'}),overlay_bypassed:overlayBypassed,hit:hitInfo});
      });
    }catch(error){clearTimeout(safetyTimer);restore();reply({ok:false,error:String(error?.message||error),overlay_bypassed:overlayBypassed});}
  });

  chrome.runtime.onMessage.addListener(msg=>{
    if(msg?.type==='FS_BACKGROUND_WAKE' && (!state.job || String(msg.command_id||'')===String(state.job.command_id||''))){
      signalBackgroundWake();
      queueMicrotask(()=>{
        void pullJob();
        if(state.job && !state.generationRunning && !state.uploadInFlight)void scanOnce();
        if(state.job && !state.generationRunning)maybeAutoUpload();
        maybeStartNativeGeneration();
      });
    }
    if(msg?.type==='FS_DOWNLOAD_SUMMARY'){
      state.downloadCounts={total:Number(msg.total||0),complete:Number(msg.complete||0),failed:Number(msg.failed||0),waiting:Number(msg.waiting||0),downloading:Number(msg.downloading||0),ready:Number(msg.ready||0),reserved:Number(msg.reserved||0)};
      state.downloadSummary=`已下载 ${msg.complete}/${msg.total}`+(msg.failed?` · 失败 ${msg.failed}`:'')+(msg.downloading?` · 下载中 ${msg.downloading}`:'')+(msg.waiting?` · 结果待核对 ${msg.waiting}`:'')+(msg.message?' · '+msg.message:'');render();
    }
    if(msg?.type==='FS_DOWNLOAD_SCAN' && !state.resultScanRunning) {
      state.resultScanRunning=true;
      submitViaMainWorld({action:'scan_video_results',ids:msg.ids},5000)
        .then(data=>downloadMessage({type:'FS_DOWNLOAD_OBSERVE',rows:data.rows||[],diagnostics:data.diagnostics})).catch(error=>{state.downloadSummary='扫描失败：'+String(error.message||error);render();}).finally(()=>{state.resultScanRunning=false;});
    }
    if(msg?.type==='FS_GENERATION_CONTROL'){
      state.generationPaused=!!msg.paused;
      // Do not overwrite a real upload/submission/recovery status with a generic
      // control heartbeat.  This used to make the panel look permanently stuck at
      // ‘已继续：生成队列恢复提交’ while an upload gate was actually waiting.
      if(state.generationPaused){state.message='已暂停：不会继续提交新的生成任务';}
      else if(!state.uploadInFlight && !state.generationRunning && !state.scanInFlight){state.message='已继续：生成队列恢复提交';}
      render();
    }
    if(msg?.type==='FS_PROGRESS_SCAN' && Number(msg.scanVersion)!==state.lastProgressScanVersion){
      state.lastProgressScanVersion=Number(msg.scanVersion);
      runProgressSync('studio-10s');
    }
  });
  let bindingRepairRunning=false;
  const repairedBindings=new Set();
  async function repairConfirmedBindings(){
    if(bindingRepairRunning || !state.job?.command_id)return;
    bindingRepairRunning=true;
    try{
      const job=state.job;const rounds=Math.max(1,Math.min(4,Number(job.generation_count||1)));
      const keys=state.tasks.flatMap(t=>Array.from({length:rounds},(_,i)=>'flowStudioConfirmedIds:'+taskLedgerKey(job,t,i+1)));
      const saved=await chrome.storage.local.get(keys);
      for(const t of state.tasks)for(let round=1;round<=rounds;round++){
        if(state.job?.command_id!==job.command_id)return;
        const ids=saved['flowStudioConfirmedIds:'+taskLedgerKey(job,t,round)];if(!ids?.length)continue;
        const key=JSON.stringify([new URL(location.href).origin+location.pathname.replace(/\/+$/,''),job.command_id,t.segment_id??t.task_name??t.task_id,round]);
        if(repairedBindings.has(key))continue;
        await downloadMessage({type:'FS_DOWNLOAD_BIND',key,ids});repairedBindings.add(key);
        if(repairedBindings.size>1000)repairedBindings.delete(repairedBindings.values().next().value);
        emit('generation_task_status',{host_id:t.host_id,recipient_id:t.recipient_id,segment_id:t.segment_id,round,state:'success',generation_ids:ids,message:'已恢复原生成结果绑定，继续等待下载'});
      }
    }catch(error){state.downloadSummary='结果绑定待恢复：'+String(error.message||error);}
    finally{bindingRepairRunning=false;}
  }
  setInterval(()=>{void repairConfirmedBindings();},30000);
  // Content heartbeat wakes a suspended MV3 worker; independent of generation/upload.
  setInterval(()=>{downloadMessage({type:'FS_DOWNLOAD_POLL'}).catch(error=>{state.downloadSummary='下载后台异常：'+String(error.message||error);render();});},2000);
  setInterval(()=>{chrome.runtime.sendMessage({type:'FS_CONNECTION_PING'},()=>void chrome.runtime.lastError);},2200);

  // Upload watchdog: no upload stage is allowed to hold the channel forever.
  // If the browser/native drag callback or Flow DOM stalls, release the local
  // in-flight gate and let the normal verified retry path rescan fresh DOM.
  setInterval(()=>{
    if(!state.uploadInFlight)return;
    const now=Date.now();
    const last=Number(state.uploadProgressAt||state.uploadStageStartedAt||now);
    if(now-last<35000)return;
    state.uploadInFlight=false;
    state.uploadStageStartedAt=0;
    state.lastUploadSucceeded=false;
    state.lastUploadAt=0;
    state.ready=false;
    state.stableHits=0;
    state.message='上传阶段超过 35 秒无真实进展，已自动释放并重新扫描；不会占死本地端通道';
    emit('upload_watchdog_released',{attempt:state.uploadAttempts,stalled_ms:now-last,message:state.message});
    startScanner();
    render();
    queueMicrotask(()=>maybeAutoUpload());
  },5000);
  function normalizeTasks(job) {
    return (job?.tasks || []).map((t,i)=>({
      document_number:documentNumber(t,i),
      task_id: String(t.task_id || t.segment_id || `${i+1}`),
      task_name: String(t.task_name || t.download_stem || t.task_id || t.segment_id || `${i+1}`),
      download_stem: String(t.download_stem || t.task_name || t.task_id || t.segment_id || `${i+1}`),
      download_names: Array.isArray(t.download_names) ? t.download_names.map(String) : [],
      dispatch_order: Number(t.dispatch_order || i+1),
      segment_id: t.segment_id ?? null,
      open_eye_prompt: String(t.open_eye_prompt || ''),
      host_id: Number(t.host_id || job?.host_id || 0),
      host_name: String(t.host_name || job?.host_name || ''),
      recipient_id: Number(t.recipient_id || job?.recipient_id || 0),
      recipient_name: String(t.recipient_name || job?.recipient_name || ''),
      video_seq: Number(t.video_seq || 0), seg_seq: Number(t.seg_seq || 0),
      image: expectedImageName(t),
      image_path: taskImagePath(t),
      dialogue: String(t.dialogue || t.script || t.text || ''),
      prompt: String(t.prompt || t.flow_prompt || t.final_prompt || ''),
      generation_mode: String(t.generation_mode || 'FRAME').toUpperCase()==='MATERIAL' ? 'MATERIAL' : 'FRAME',
      duration: Number(t.duration || 8),
      needs_split: Boolean(t.needs_split), force_submit: Boolean(t.force_submit),
      estimated_speech_seconds: Number(t.estimated_speech_seconds || 0),
      matched: false,
      flow_media_url: ''
    }));
  }

  function jobBaseIdentity(job) {
    if (!job) return '';
    return `${job.channel_key||job.host_id||''}|${job.image_set_id||''}|${job.command_id||''}`;
  }

  function taskWaveSignature(job) {
    const rows=(job?.tasks||[]).map((t,i)=>{
      const segment=String(t.segment_id ?? '');
      const task=String(t.task_id ?? t.task_name ?? '');
      const image=basename(t.image_path || t.reference_image || t.image || t.image_name || '');
      const mode=String(t.generation_mode||'FRAME').toUpperCase()==='MATERIAL'?'MATERIAL':'FRAME';
      return `${segment}|${task}|${image}|${mode}`;
    }).sort();
    return `${Number(job?.generation_count||1)}:${rows.join('~')}`;
  }

  function jobWorkIdentity(job) {
    if (!job) return '';
    return `${jobBaseIdentity(job)}|${taskWaveSignature(job)}`;
  }

  function jobExecutionKey(job) {
    if (!job?.command_id) return '';
    return `${job.command_id}|${taskWaveSignature(job)}`;
  }

  function readStartedWaves() {
    const key='flow-studio-work-waves:'+location.pathname;
    try {
      const rows=JSON.parse(sessionStorage.getItem(key)||'[]');
      return Array.isArray(rows)?rows.map(String):[];
    } catch (_) { return []; }
  }

  function hasStartedWave(executionKey) {
    return !!executionKey && readStartedWaves().includes(executionKey);
  }

  function markStartedWave(executionKey) {
    if(!executionKey)return;
    const key='flow-studio-work-waves:'+location.pathname;
    try {
      const rows=readStartedWaves().filter(x=>x!==executionKey);
      rows.push(executionKey);
      sessionStorage.setItem(key,JSON.stringify(rows.slice(-80)));
    } catch (_) {}
  }

  function retiredCommandStoreKey(){ return 'flow-studio-retired-commands:'+location.pathname; }
  function readRetiredCommands(){
    try{const rows=JSON.parse(sessionStorage.getItem(retiredCommandStoreKey())||'[]');return Array.isArray(rows)?rows.map(String):[];}catch(_){return [];}
  }
  function isRetiredCommand(commandId){ return !!commandId && readRetiredCommands().includes(String(commandId)); }
  function markRetiredCommand(commandId){
    const cmd=String(commandId||'');if(!cmd)return;
    try{const rows=readRetiredCommands().filter(x=>x!==cmd);rows.push(cmd);sessionStorage.setItem(retiredCommandStoreKey(),JSON.stringify(rows.slice(-80)));}catch(_){}
  }

  async function waveFullyConfirmed(job){
    const tasks=normalizeTasks(job).filter(t=>t.prompt||t.dialogue);
    const rounds=Math.max(1,Math.min(4,Number(job?.generation_count||1)));
    if(!tasks.length)return true;
    for(const t of tasks)for(let round=1;round<=rounds;round++)if(!(await taskAlreadyConfirmed(job,t,round)))return false;
    return true;
  }

  function clearLocalWave(message='当前任务已释放，正在领取下一批任务…'){
    stopScanner();
    clearThumbnailCache();
    repairedBindings.clear();
    state.identity='';state.baseIdentity='';state.workSignature='';state.job=null;state.tasks=[];state.media=[];state.matched=0;
    state.stableHits=0;state.lastSignature='';state.ready=false;state.mediaScanValid=false;state.uploadInFlight=false;
    state.uploadAttempts=0;state.lastUploadAt=0;state.lastRecognizedMediaCount=0;state.generationCommand='';state.cancelledCommand='';
    state.skippedUploadNames=new Map();state.skippedUploadFailureTasks=new Set();state.message=message;render();
  }

  function requestNextWaveSoon(){
    chrome.runtime.sendMessage({type:'FS_FORCE_SYNC'},()=>{void chrome.runtime.lastError;setTimeout(()=>pullJob(),120);});
    for(const delay of [700,1800,3600])setTimeout(()=>pullJob(),delay);
  }

  function retireCompletedWave(job, meta={}, reason='当前波次已完成'){
    const cmd=String(job?.command_id||'');
    if(cmd)markRetiredCommand(cmd);
    emit('generation_batch_finished',{command_id:cmd,channel_key:job?.channel_key||'',channel_id:job?.channel_id||0,host_id:job?.host_id||0,...meta,message:reason});
    clearLocalWave(reason+' · 已清空本页旧任务，正在领取下一批…');
    requestNextWaveSoon();
  }

  function getExpectedNames(job) {
    const fromJob = Array.isArray(job?.expected_image_names) ? job.expected_image_names : [];
    if (fromJob.length) return [...new Set(fromJob.map(x=>basename(x)).filter(Boolean))];
    const taskNames = state.tasks.map(t=>t.image).filter(Boolean);
    if (taskNames.length) return [...new Set(taskNames)];
    return [...new Set((job?.image_files || []).map(x=>basename(x?.name || x?.path)).filter(Boolean))];
  }

  function skipStoreKey(identity=state.identity) { return 'fs-upload-skips:'+String(identity||''); }
  function restoreSkippedUploads() {
    state.skippedUploadNames=new Map();
    state.skippedUploadFailureTasks=new Set();
    if(!state.identity)return;
    try{
      const rows=JSON.parse(sessionStorage.getItem(skipStoreKey())||'[]');
      for(const name of (Array.isArray(rows)?rows:[])){const full=String(name||'').trim();if(full)state.skippedUploadNames.set(norm(full),full);}
    }catch(_){}
  }
  function persistSkippedUploads() {
    if(!state.identity)return;
    try{sessionStorage.setItem(skipStoreKey(),JSON.stringify([...state.skippedUploadNames.values()]));}catch(_){}
  }
  function isUploadSkippedName(name) { return state.skippedUploadNames.has(norm(name)); }
  function skippedUploadFullNames() { return [...state.skippedUploadNames.values()]; }

  // Keep upload failure names visible for the whole task wave, including after retries,
  // successful recovery, and page refresh.  This is diagnostic history only and does
  // not change retry/skip/submission behavior.
  function uploadFailureStoreKey(identity=state.identity){return 'fs-upload-failures:'+String(identity||'');}
  function restoreUploadFailureHistory(){
    state.failedUploadHistory=new Map();
    if(!state.identity)return;
    try{
      const rows=JSON.parse(sessionStorage.getItem(uploadFailureStoreKey())||'[]');
      for(const row of (Array.isArray(rows)?rows:[])){
        const name=String(row?.name||'').trim();if(!name)continue;
        state.failedUploadHistory.set(norm(name),{name,status:String(row?.status||'上传失败'),reason:String(row?.reason||''),attempt:Number(row?.attempt||0),at:Number(row?.at||0)});
      }
    }catch(_){}
  }
  function persistUploadFailureHistory(){
    if(!state.identity)return;
    try{sessionStorage.setItem(uploadFailureStoreKey(),JSON.stringify([...state.failedUploadHistory.values()]));}catch(_){}
  }
  function rememberUploadFailure(names,reason='',attempt=0,status='上传失败'){
    for(const raw of (names||[])){
      const name=String(raw||'').trim();if(!name)continue;
      const key=norm(name),prev=state.failedUploadHistory.get(key)||{};
      state.failedUploadHistory.set(key,{name,status,reason:String(reason||prev.reason||''),attempt:Math.max(Number(prev.attempt||0),Number(attempt||0)),at:Date.now()});
    }
    persistUploadFailureHistory();
  }
  function markUploadFailureRecovered(name){
    const key=norm(name),prev=state.failedUploadHistory.get(key);if(!prev)return;
    state.failedUploadHistory.set(key,{...prev,name:String(name||prev.name),status:'曾失败，后续已上传成功',at:Date.now()});
    persistUploadFailureHistory();
  }
  function uploadFailureHistoryRows(){return [...state.failedUploadHistory.values()];}
  function effectiveExpectedNames() { return getExpectedNames(state.job).filter(name=>!isUploadSkippedName(name)); }
  function activeGenerationTasks() { return state.tasks.filter(t=>!isUploadSkippedName(t.image)); }
  function expectedMediaTotal() { return effectiveExpectedNames().length; }

  function recognizedMediaCount() {
    const expected=new Set(effectiveExpectedNames().map(norm));
    return new Set(state.media.filter(m=>expected.has(norm(m.name))).map(m=>norm(m.name))).size;
  }

  // v0.9.62 hard upload barrier: generation may start only after EVERY image
  // expected by the current Studio wave exists in Flow's real media catalog.
  function mediaUploadUsable(item){
    if(!item)return false;
    // page-engine explicitly marks fresh upload placeholders as upload_ready=false.
    // Keep compatibility with older/mocked scan results that predate this field.
    if(item.upload_error===true || item.uploading===true || item.upload_ready===false)return false;
    if(item.upload_ready===true)return true;
    return !!String(item.id||'').trim() && !!String(item.name||'').trim();
  }
  function requiredUploadStatus(media=state.media,job=state.job) {
    const expected=getExpectedNames(job);
    const rows=new Map();
    for(const item of (media||[])){const key=norm(item?.name);if(key&&!rows.has(key))rows.set(key,item);}
    const missing=[],pending=[];
    for(const name of expected){
      const item=rows.get(norm(name));
      if(!item)missing.push(name);
      else if(!mediaUploadUsable(item))pending.push(name);
    }
    const blocked=[...missing,...pending];
    return {expected,missing:blocked,missing_files:missing,pending,recognized:Math.max(0,expected.length-blocked.length),present:Math.max(0,expected.length-missing.length),total:expected.length,ready:expected.length>0&&blocked.length===0};
  }
  function uploadBarrierReady(){return !!state.mediaScanValid && requiredUploadStatus().ready;}
  async function confirmAllImagesInFlowBeforeSubmit(job){
    const expected=getExpectedNames(job);
    if(!expected.length)return {ok:false,missing:[],recognized:0,total:0,error:'当前批次没有可验证的图片'};
    const wanted=new Set(expected.map(norm));
    let previousSignature='';
    // This is a pre-submission existence/readiness gate, not a generation attempt.
    // Require two consecutive live Flow catalog confirmations so a just-created upload
    // placeholder cannot start attempt #1.
    for(let check=1;check<=2;check++){
      let snapshot;
      try{snapshot=await submitViaMainWorld({action:'scan_media'},5000);}
      catch(error){return {ok:false,missing:expected,recognized:0,total:expected.length,error:String(error?.message||error)};}
      const media=(snapshot.media||[]).filter(m=>wanted.has(norm(m.name)));
      const status=requiredUploadStatus(media,job);
      const signature=media.filter(mediaUploadUsable).map(m=>String(m.id||'')+':'+norm(m.name)).sort().join('|');
      if(!status.ready){return {ok:false,...status,media};}
      if(check===2 && signature!==previousSignature){
        return {ok:false,...status,missing:expected,recognized:0,media,error:'Flow 图片状态仍在变化，等待上传完成后再提交'};
      }
      previousSignature=signature;
      if(check<2)await sleep(900);
      if(isFlowUploading())return {ok:false,...status,missing:expected,recognized:0,media,error:'Flow 仍在上传图片，等待上传完成后再提交'};
      if(check===2){state.media=media;state.mediaScanValid=true;matchTasks(media);return {ok:true,...status,media};}
    }
    return {ok:false,missing:expected,recognized:0,total:expected.length,error:'图片上传确认未完成'};
  }

  function getPathMap(job) {
    const out = new Map();
    for (const t of state.tasks) {
      if (t.image && t.image_path) out.set(norm(t.image), t.image_path);
    }
    for (const item of (job?.image_files || [])) {
      const path = String(item?.path || item?.file_path || '').trim();
      const name = basename(item?.name || path);
      if (name && path) out.set(norm(name), path);
    }
    return out;
  }

  const thumbnailInFlight=new Set();
  async function ensureThumbnail(name) {
    const key=norm(name),identity=state.identity,flight=identity+'|'+key;
    if(!key || state.thumbnailUrls.has(key) || thumbnailInFlight.has(flight))return;
    const path=getPathMap(state.job).get(key);
    if(!path)return;
    thumbnailInFlight.add(flight);
    let bitmap=null;
    try {
      const r=await requestFile(path);
      if(identity!==state.identity)return;
      bitmap=await createImageBitmap(new Blob([new Uint8Array(r.bytes)],{type:r.mime||'image/jpeg'}));
      const scale=Math.min(1,320/Math.max(bitmap.width,bitmap.height));
      const canvas=new OffscreenCanvas(Math.max(1,Math.round(bitmap.width*scale)),Math.max(1,Math.round(bitmap.height*scale)));
      canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);
      bitmap.close();bitmap=null;
      const blob=await canvas.convertToBlob({type:'image/webp',quality:0.8});
      if(identity!==state.identity || state.thumbnailUrls.has(key) || blob.size>256*1024)return;
      while(state.thumbnailUrls.size>=64){
        const oldest=state.thumbnailUrls.keys().next().value;
        URL.revokeObjectURL(state.thumbnailUrls.get(oldest));state.thumbnailUrls.delete(oldest);
      }
      state.thumbnailUrls.set(key,URL.createObjectURL(blob));
      const img=document.querySelector(`#flow-studio-v050-root img[data-fs-thumb="${CSS.escape(key)}"]`);
      if(img)img.src=state.thumbnailUrls.get(key);
    }catch(_){}
    finally{if(bitmap)bitmap.close();thumbnailInFlight.delete(flight);}
  }

  function hydrateThumbnails() {
    for (const m of state.media) if (!m.url) ensureThumbnail(m.name);
  }

  function setPanelTemporarilyHidden(hidden) {
    // v0.7.2: do not toggle open/closed UI during upload.
    // Only make the overlay transparent/non-interactive for the exact drop window.
    const root=$('#flow-studio-v050-root');
    if(!root) return;
    if(hidden){
      root.dataset.fsDropGuard='1';
      root.style.pointerEvents='none';
      root.style.opacity='0.02';
    }else{
      delete root.dataset.fsDropGuard;
      root.style.pointerEvents='';
      root.style.opacity='';
    }
  }

  // 轻量扫描：只扫描媒体可能出现的节点，不使用 MutationObserver / querySelectorAll('*')。
  function isFlowUploading() {
    // Advisory only: Flow keeps unrelated generation/processing nodes in the DOM.
    // Never let stale or hidden "processing" UI block the authoritative media-store READY gate.
    const bars = document.querySelectorAll('[role="progressbar"],[aria-busy="true"]');
    for (const el of bars) {
      if (el.closest?.("#flow-studio-v050-root") || !visible(el)) continue;
      const label=`${el.getAttribute?.('aria-label')||''} ${el.getAttribute?.('title')||''} ${el.textContent||''}`.trim();
      const uploadSpecific=/(upload|上传)/i.test(label);
      if (!uploadSpecific) continue;
      if (el.getAttribute('aria-busy') === 'true') return true;
      const now = Number(el.getAttribute('aria-valuenow'));
      if (Number.isFinite(now) && now < 100) return true;
      if (/\b(?:[1-9]|[1-9]\d)\s*%\b/.test(label)) return true;
    }
    const labels = document.querySelectorAll('[aria-label],[title],span,p');
    let checked = 0;
    for (const el of labels) {
      if (el.closest?.("#flow-studio-v050-root") || !visible(el)) continue;
      if (checked++ > 450) break;
      const txt = `${el.getAttribute?.('aria-label')||''} ${el.getAttribute?.('title')||''} ${el.textContent||''}`.trim();
      if (!txt || txt.length > 120) continue;
      if (/(uploading|正在上传|上传中|上传图片|uploading media|upload media)/i.test(txt)) return true;
    }
    return false;
  }

  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && r.bottom > 0 && r.right > 0 &&
      r.left < innerWidth && r.top < innerHeight && st.display !== 'none' &&
      st.visibility !== 'hidden' && st.opacity !== '0';
  }

  // 仅在真正要上传时执行一次深层查找；不放进 2 秒扫描器，避免拖慢 Flow。
  function uploadSearchRoots(root=document, out=[]) {
    if (!root || out.includes(root)) return out;
    out.push(root);
    let nodes=[];
    try { nodes=root.querySelectorAll ? root.querySelectorAll('*') : []; } catch (_) {}
    for (const el of nodes) {
      if (el.shadowRoot) uploadSearchRoots(el.shadowRoot,out);
      if (el.tagName === 'IFRAME') {
        try { if (el.contentDocument) uploadSearchRoots(el.contentDocument,out); } catch (_) {}
      }
    }
    return out;
  }

  function uploadDeepQueryAll(selector) {
    const out=[];
    for (const root of uploadSearchRoots()) {
      try { out.push(...root.querySelectorAll(selector)); } catch (_) {}
    }
    return [...new Set(out)];
  }

  // 直接沿用之前 V0.12.20 已经跑通的 Flow 工作区定位方式：
  // 找“开始创建或拖放媒体”所在的最大可见区域，把文件 drop 到网页工作区内部，
  // 而不是用一个猜测坐标落到浏览器标签栏/页面边缘。
  function findDropPoint() {
    const phrases=['开始创建或拖放媒体','拖放媒体','drop media','drag media','drop files','drag files'];
    let best=null;
    for (const el of uploadDeepQueryAll('div,section,main,[role="main"],[role="button"],span,p').filter(visible)) {
      if (el.closest?.('#flow-studio-v050-root,#flow-studio-v050-root')) continue;
      const txt=String((el.innerText||el.textContent||'')+' '+(el.getAttribute?.('aria-label')||'')).replace(/\s+/g,' ').trim().toLowerCase();
      if (!phrases.some(p=>txt.includes(p))) continue;
      const r=el.getBoundingClientRect();
      if (r.width < 80 || r.height < 30) continue;
      const area=r.width*r.height;
      if (!best || area>best.area) best={r,area};
    }
    if (best) return {
      x:Math.max(10,Math.min(innerWidth-10,Math.round(best.r.left+best.r.width/2))),
      y:Math.max(10,Math.min(innerHeight-10,Math.round(best.r.top+best.r.height/2))),
      source:'flow_drop_zone'
    };
    // 旧版已验证的工作区 fallback；明确落在网页 viewport 内。
    return {
      x:Math.max(20,Math.min(innerWidth-20,Math.floor(Math.max(420,innerWidth*.58)))),
      y:Math.max(20,Math.min(innerHeight-20,Math.floor(Math.max(330,innerHeight*.46)))),
      source:'workspace_fallback'
    };
  }

  function requestFile(path) {
    return new Promise((resolve,reject)=>{
      chrome.runtime.sendMessage({type:'FS_GET_FILE',path},res=>{
        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
        if (!res?.ok) return reject(new Error(res?.error||'读取图片失败'));
        resolve(res);
      });
    });
  }

  async function syntheticDragUpload(paths, point) {
    const rows=await Promise.all(paths.map(requestFile));
    const dt=new DataTransfer();
    for (const r of rows) dt.items.add(new File([new Uint8Array(r.bytes)],r.filename,{type:r.mime||'image/jpeg'}));
    const target=document.elementFromPoint(point.x,point.y) || document.body;
    const chain=[];
    for (let el=target; el && chain.length<8; el=el.parentElement) chain.push(el);
    for (const type of ['dragenter','dragover']) {
      for (const el of chain) {
        try { el.dispatchEvent(new DragEvent(type,{bubbles:true,cancelable:true,composed:true,dataTransfer:dt,clientX:point.x,clientY:point.y})); } catch (_) {}
      }
    }
    target.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,composed:true,dataTransfer:dt,clientX:point.x,clientY:point.y}));
    return {ok:true,method:'synthetic_fallback',count:paths.length};
  }

  async function fileInputUpload(paths) {
    const candidates=uploadDeepQueryAll('input[type="file"]').filter(el=>!el.closest?.('#flow-studio-v050-root'));
    if (!candidates.length) return {ok:false,noCandidate:true,error:'未找到 Flow 文件选择控件'};
    const ranked=candidates.map(el=>{
      const accept=String(el.getAttribute('accept')||'').toLowerCase();
      let score=0;
      if (!accept || accept.includes('image') || accept.includes('.png') || accept.includes('.jpg') || accept.includes('.jpeg') || accept.includes('.webp')) score+=10;
      if (el.multiple) score+=3;
      if (!el.disabled) score+=2; else score-=100;
      return {el,score,accept};
    }).sort((a,b)=>b.score-a.score);
    const target=ranked[0]?.el;
    if (!target || ranked[0].score<0) return {ok:false,noCandidate:true,error:'没有可用的 Flow 图片文件控件'};
    const rows=await Promise.all(paths.map(requestFile));
    const dt=new DataTransfer();
    for (const r of rows) dt.items.add(new File([new Uint8Array(r.bytes)],r.filename,{type:r.mime||'image/jpeg'}));
    try { target.files=dt.files; }
    catch (_) {
      try { Object.defineProperty(target,'files',{configurable:true,value:dt.files}); }
      catch (e) { return {ok:false,error:'无法写入 Flow 文件控件：'+String(e?.message||e)}; }
    }
    target.dispatchEvent(new Event('input',{bubbles:true,composed:true}));
    target.dispatchEvent(new Event('change',{bubbles:true,composed:true}));
    return {ok:true,method:'file_input',count:paths.length,accept:ranked[0].accept};
  }


  function parentAcrossShadow(el) {
    if (!el) return null;
    if (el.parentElement) return el.parentElement;
    try { return el.getRootNode?.()?.host || null; } catch (_) { return null; }
  }

  function findMaterialComposerTarget() {
    const all=uploadDeepQueryAll('flow-generate-icon-button button,flow-generate-icon-button,button,[role="button"]');
    let generate=all.find(el=>{
      if (el.closest?.('#flow-studio-v050-root')) return false;
      const tag=String(el.tagName||'').toLowerCase();
      const txt=String((el.innerText||el.textContent||'')+' '+(el.getAttribute?.('aria-label')||'')+' '+(el.getAttribute?.('title')||'')).replace(/\s+/g,' ').trim();
      return tag==='flow-generate-icon-button' || /(^|\s)(generate|create|生成|创建)(\s|$)/i.test(txt);
    });
    if (!generate) generate=document.querySelector('flow-generate-icon-button button,flow-generate-icon-button');
    if (!generate) return null;

    const gr=generate.getBoundingClientRect();
    const roots=[];
    let node=generate;
    for(let depth=0;node&&depth<10;depth++,node=parentAcrossShadow(node)){
      if(node.closest?.('#flow-studio-v050-root')) continue;
      const r=node.getBoundingClientRect?.();
      if(!r||r.width<220||r.height<55||r.height>650||r.bottom<=0||r.top>=innerHeight)continue;
      let score=0;
      if(r.width>=320)score+=10;
      if(r.height>=80&&r.height<=380)score+=12;
      if(gr.left>=r.left&&gr.right<=r.right&&gr.top>=r.top&&gr.bottom<=r.bottom)score+=15;
      const text=String((node.getAttribute?.('aria-label')||'')+' '+(node.getAttribute?.('role')||'')+' '+(node.className||'')).toLowerCase();
      if(/prompt|composer|generate|creation|input/.test(text))score+=8;
      roots.push({node,r,score,depth});
    }
    roots.sort((a,b)=>b.score-a.score || a.r.height-b.r.height || a.depth-b.depth);
    const root=roots[0]?.node || parentAcrossShadow(generate) || document.body;
    const r=roots[0]?.r || root.getBoundingClientRect();
    // Drop inside the left/upper half of the composer, away from the Generate button itself.
    let x=Math.round(r.left+Math.min(Math.max(70,r.width*.20),Math.max(75,r.width-90)));
    let y=Math.round(r.top+Math.min(Math.max(34,r.height*.36),Math.max(38,r.height-34)));
    if(Math.hypot(x-(gr.left+gr.width/2),y-(gr.top+gr.height/2))<90){
      x=Math.round(r.left+Math.min(Math.max(90,r.width*.35),Math.max(100,r.width-120)));
      y=Math.round(r.top+Math.min(Math.max(30,r.height*.28),Math.max(34,r.height-40)));
    }
    x=Math.max(10,Math.min(innerWidth-10,x));
    y=Math.max(10,Math.min(innerHeight-10,y));
    return {root,x,y,source:'material_composer',root_rect:{left:r.left,top:r.top,width:r.width,height:r.height}};
  }

  async function materialComposerAttach(imagePath,imageName='') {
    if(!imagePath) return {ok:false,error:'素材模式没有本地图片路径，无法执行帧模式同源直挂'};
    const target=findMaterialComposerTarget();
    if(!target) return {ok:false,error:'未找到当前 Flow 生成输入区，无法把素材图片直挂到 composer'};
    const paths=[imagePath];

    // v0.9.51: first reuse the exact native-drag transport that has proven stable for FRAME/workspace
    // image delivery, but change only the destination: drop into the active generation composer.
    let result=await new Promise(resolve=>{
      const timer=setTimeout(()=>resolve({ok:false,uncertain:true,error:'素材直挂 native drag 超时'}),18000);
      try{
        chrome.runtime.sendMessage({type:'FS_NATIVE_DRAG',paths,x:target.x,y:target.y},r=>{
          clearTimeout(timer);
          const error=chrome.runtime.lastError?.message;
          resolve(error?{ok:false,uncertain:true,error}:(r||{ok:false,uncertain:true,error:'素材直挂无响应'}));
        });
      }catch(e){clearTimeout(timer);resolve({ok:false,error:String(e?.message||e)});}
    });
    if(result.ok)return {...result,method:(result.method||'chrome_debugger')+'_material_composer',target:{x:target.x,y:target.y,source:target.source},image_name:imageName};

    // If debugger drag was unavailable, reuse the same DataTransfer/File construction as FRAME upload,
    // but only accept file inputs belonging to / geometrically adjacent to the active composer.
    try{
      const inputs=uploadDeepQueryAll('input[type="file"]').filter(el=>!el.closest?.('#flow-studio-v050-root')&&!el.disabled);
      const ranked=inputs.map(el=>{
        const accept=String(el.getAttribute('accept')||'').toLowerCase();
        const pr=el.parentElement?.getBoundingClientRect?.()||el.getBoundingClientRect?.();
        const cx=pr&&pr.width?pr.left+pr.width/2:target.x, cy=pr&&pr.height?pr.top+pr.height/2:target.y;
        let score=0;
        if(!accept||accept.includes('image')||/\.(png|jpe?g|webp)/.test(accept))score+=20;
        if(target.root===el||target.root.contains?.(el))score+=80;
        const dist=Math.hypot(cx-target.x,cy-target.y);score+=Math.max(0,45-Math.min(45,dist/12));
        const semantics=String((el.getAttribute('aria-label')||'')+' '+(el.getAttribute('title')||'')+' '+(el.parentElement?.innerText||'')).slice(0,300);
        if(/reference|material|image|media|素材|参考|图片/i.test(semantics))score+=25;
        if(/drop media|拖放媒体|workspace|工作区/i.test(semantics))score-=35;
        return {el,score,accept};
      }).sort((a,b)=>b.score-a.score);
      if(ranked[0]?.score>=35){
        const row=await requestFile(imagePath),dt=new DataTransfer();
        dt.items.add(new File([new Uint8Array(row.bytes)],row.filename,{type:row.mime||'image/jpeg'}));
        try{ranked[0].el.files=dt.files;}catch(_){Object.defineProperty(ranked[0].el,'files',{configurable:true,value:dt.files});}
        ranked[0].el.dispatchEvent(new Event('input',{bubbles:true,composed:true}));
        ranked[0].el.dispatchEvent(new Event('change',{bubbles:true,composed:true}));
        return {ok:true,method:'composer_file_input',count:1,accept:ranked[0].accept,target:{x:target.x,y:target.y,source:target.source},image_name:imageName};
      }
    }catch(e){result={ok:false,error:String(e?.message||e)};}

    try{
      const synthetic=await syntheticDragUpload(paths,{x:target.x,y:target.y});
      if(synthetic.ok)return {...synthetic,method:'synthetic_material_composer',target:{x:target.x,y:target.y,source:target.source},image_name:imageName};
    }catch(e){result={ok:false,error:String(e?.message||e)};}
    return result.ok?result:{ok:false,error:result.error||'素材图片无法直挂到当前 composer'};
  }

  window.addEventListener('FLOW_STUDIO_MATERIAL_ATTACH_REQUEST',async ev=>{
    const d=ev.detail||{};if(!d.request_id)return;
    const reply=data=>window.dispatchEvent(new CustomEvent('FLOW_STUDIO_MATERIAL_ATTACH_RESULT',{detail:{request_id:d.request_id,...data}}));
    try{
      setPanelTemporarilyHidden(true);await sleep(80);
      const result=await materialComposerAttach(String(d.image_path||''),String(d.image_name||''));
      emit(result.ok?'material_direct_attach_dispatched':'material_direct_attach_failed',{task_id:d.task_id||'',segment_id:d.segment_id,image_name:d.image_name||'',method:result.method||'',target:result.target||null,error:result.error||''});
      reply(result.ok?{ok:true,...result}:{ok:false,error:result.error||'MATERIAL_DIRECT_ATTACH_FAILED'});
    }catch(e){reply({ok:false,error:String(e?.message||e)});}
    finally{setPanelTemporarilyHidden(false);}
  });


  function emit(type, extra={}) {
    const j = state.job || {};
    chrome.runtime.sendMessage({type:'FS_PUSH_EVENT', event:{
      type,
      host_id:j.host_id, host_name:j.host_name, recipient_id:j.recipient_id,
      channel_id:j.channel_id, channel_key:j.channel_key, channel_role:j.channel_role,
      command_id:j.command_id || '', image_set_id:j.image_set_id || '',
      collection_url:j.collection_url || location.href,
      ...extra
    }}, ()=>void chrome.runtime.lastError);
  }

  const rebalanceRevoked=new Set();
  let rebalanceInFlight=null;
  const rebalanceDone=new Set();
  async function applyRebalance(job){
    const request=job?.rebalance_request;
    if(!request)return;
    if(request.completed){for(const task of job.tasks||[])rebalanceRevoked.delete(job.command_id+':'+task.segment_id);return;}
    if(rebalanceDone.has(request.id))return;
    // Fence the queued tasks synchronously before yielding to any async work.
    for(const id of request.ids||[])rebalanceRevoked.add(job.command_id+':'+id);
    const safe=[];
    for(const id of request.ids||[]){
      if(rebalanceInFlight===job.command_id+':'+id){rebalanceRevoked.delete(job.command_id+':'+id);continue;}
      const task=normalizeTasks(job).find(t=>Number(t.segment_id)===Number(id));
      if(!task)continue;
      let submitted=false;
      for(let round=1;round<=Math.max(1,Number(job.generation_count||1));round++){
        if(await taskAlreadyConfirmed(job,task,round)){submitted=true;break;}
      }
      if(!submitted)safe.push(id);else rebalanceRevoked.delete(job.command_id+':'+id);
    }
    const reply=await new Promise(resolve=>chrome.runtime.sendMessage({type:'FS_REBALANCE_ACK',command_id:job.command_id,request_id:request.id,safe_ids:safe},r=>{void chrome.runtime.lastError;resolve(r);}));
    if(reply?.ok){for(const id of safe)if(!(reply.moved||[]).includes(id))rebalanceRevoked.delete(job.command_id+':'+id);rebalanceDone.add(request.id);}
  }

  async function pullJob() {
    const res = await new Promise(resolve=>{
      chrome.runtime.sendMessage({type:'FS_GET_JOB'}, r=>resolve(r || {ok:false,connected:false}));
    });
    state.connected = !!res.connected;
    let incoming = res.job || null;
    // A completed submission wave can remain visible in Studio for a short time while
    // the scheduler prepares the next one. Never re-adopt that retired command locally.
    if(incoming && isRetiredCommand(incoming.command_id)) incoming=null;
    if(incoming){await applyRebalance(incoming);}
    const incomingBase = incoming ? jobBaseIdentity(incoming) : '';
    const incomingWork = incoming ? jobWorkIdentity(incoming) : '';
    if (state.generationRunning || state.uploadInFlight) {
      // Studio may refill this channel with another task wave while the current
      // wave is still submitting. Same command/channel must NOT cancel the
      // in-flight wave; the next poll will adopt the new task set after it ends.
      if (incoming && incomingBase===state.baseIdentity) {
        // 同一命令运行中：只刷新设置（间隔/随机时间等），不改变任务集。
        if(state.job && incoming.settings && String(incoming.command_id||'')===String(state.job.command_id||'')) state.job.settings=incoming.settings;
        render();
      }
      else if(res.connected) {state.cancelledCommand=state.job?.command_id;}
      return;
    }
    const oldIdentity = state.identity;
    const newIdentity = incomingWork;
    if (oldIdentity !== newIdentity) {
      clearThumbnailCache();
      state.cancelledCommand='';
      state.identity = newIdentity;
      state.baseIdentity = incomingBase;
      state.workSignature = incoming ? taskWaveSignature(incoming) : '';
      state.job = incoming;
      state.tasks = normalizeTasks(incoming);
      state.media = [];
      state.matched = 0;
      state.stableHits = 0;
      state.lastSignature = '';
      state.ready = false;
      state.mediaScanValid = false;
      state.uploadInFlight = false;
      state.uploadAttempts = 0;
      state.lastUploadAt = 0;
      state.lastRecognizedMediaCount = 0;
      restoreSkippedUploads();
      restoreUploadFailureHistory();
      // A changed task set under the same Studio command is a new executable
      // wave. Keep per-task duplicate ledgers, but release the wave-level gate.
      state.generationCommand = '';
      if (incoming) {
        state.message = `已从 Studio 接收 ${state.tasks.length} 个任务，正在检查集合并准备自动上传…`;
        emit('web_plugin_bound',{task_count:state.tasks.length,image_total:getExpectedNames(incoming).length,plugin_version:'0.9.66'});
        emit('web_plugin_tasks_received',{task_count:state.tasks.length,image_total:getExpectedNames(incoming).length});
        state.lastBoundEmit=Date.now();
        startScanner();
      } else {
        state.message = state.connected ? '本集合暂时没有 Studio 任务' : '未连接本地 Studio';
        stopScanner();
      }
    }
    if (incoming) state.job = incoming;
    if (incoming && Date.now()-state.lastBoundEmit >= 2500) {
      emit('web_plugin_heartbeat',{
        ready:state.ready,
        task_matched:state.matched,
        task_total:state.tasks.length,
        image_recognized:recognizedMediaCount(),
        image_total:expectedMediaTotal(),
        plugin_version:'0.9.66'
      });
      state.lastBoundEmit=Date.now();
    }
    render();
    maybeStartNativeGeneration();
  }

  function matchTasks(media) {
    const counts=new Map();
    for(const m of media){const key=norm(m.name);counts.set(key,(counts.get(key)||0)+1);}
    const byName = new Map(media.filter(m=>counts.get(norm(m.name))===1).map(m=>[norm(m.name),m]));
    state.tasks = state.tasks.map(t=>{
      const hit = byName.get(norm(t.image));
      return {...t, matched:!!hit, flow_media_url:hit?.url || '', flow_media_id:hit?.id || ''};
    });
    state.matched = state.tasks.filter(t=>t.matched).length;
  }

  function missingTasks() { return state.tasks.filter(t=>!t.matched && t.image); }

  function allMissingImageNames() {
    const expected=getExpectedNames(state.job);
    const present=new Set(state.media.map(m=>norm(m.name)));
    return expected.filter(name=>!present.has(norm(name)));
  }

  function missingImageNames() {
    return allMissingImageNames().filter(name=>!isUploadSkippedName(name));
  }

  function missingImagePaths() {
    const pathMap=getPathMap(state.job);
    let names=missingImageNames();

    if (names.length > 0 && state.tasks) {
      const hostMap = new Map();
      for (const t of state.tasks) {
        if (t.image) hostMap.set(norm(t.image), String(t.host_name || t.host_id || ''));
      }
      const firstHost = hostMap.get(norm(names[0])) || '';
      names = names.filter(n => (hostMap.get(norm(n)) || '') === firstHost);
    }

    const paths=[];
    const noPath=[];
    for (const name of names) {
      const p=pathMap.get(norm(name)) || '';
      if (p) paths.push(p); else noPath.push(name);
    }
    return {names,paths:[...new Set(paths)],noPath};
  }

  // Upload is independent of native composer discovery. A failed scan cannot
  // authorize READY, but also must not prevent the first upload from Studio.
  // v0.9.37: a successful JS/CDP dispatch is NOT proof that Flow accepted the files.
  // Keep a timestamped per-image ledger so unverified drops can be retried safely.
  const uploadLedger = new Map();
  const uploadFailureLedger = new Set();
  const MAX_AUTO_UPLOAD_ATTEMPTS = 3;
  const UPLOAD_VERIFY_GRACE_MS = 12000;
  const UPLOAD_BUSY_STUCK_MS = 30000;
  function exhaustedUploadNames() {
    return allMissingImageNames().filter(name=>!isUploadSkippedName(name) && dispatchCount(name)>=MAX_AUTO_UPLOAD_ATTEMPTS);
  }
  function markSkippedUploadTaskFailures(names) {
    const failed=new Set(names.map(norm));
    for(const t of state.tasks){
      if(!failed.has(norm(t.image)) || state.skippedUploadFailureTasks.has(String(t.segment_id)))continue;
      state.skippedUploadFailureTasks.add(String(t.segment_id));
      emit('generation_task_status',{
        host_id:t.host_id,recipient_id:t.recipient_id,segment_id:t.segment_id,task_id:t.task_id,
        state:'failed',true_error:true,round:1,
        message:'图片上传失败，已在网页插件手动跳过：'+String(t.image||'未命名图片')
      });
    }
  }
  function skipFailedUploadsAndContinue() {
    const failed=exhaustedUploadNames();
    if(!failed.length){state.message='当前没有已用尽自动重试次数的失败图片';render();return;}
    for(const name of failed)state.skippedUploadNames.set(norm(name),name);
    persistSkippedUploads();
    markSkippedUploadTaskFailures(failed);
    state.ready=false;state.stableHits=0;state.lastSignature='';
    emit('media_upload_skipped_manual',{files:failed,count:failed.length,message:'已手动跳过上传失败图片；仅继续生成已成功上传并匹配的任务'});
    state.message=`已跳过 ${failed.length} 张上传失败图片，正在优先准备已上传成功的任务`;
    startScanner();render();
  }
  function uploadKey(name) {
    const j=state.job || {};
    return JSON.stringify([location.pathname,j.host_id,j.image_set_id,taskPathForName(name),norm(name)]);
  }
  function taskPathForName(name) { return getPathMap(state.job).get(norm(name)) || ''; }
  function readDispatchRecord(name) {
    const key=uploadKey(name);
    if (uploadLedger.has(key)) return uploadLedger.get(key);
    try {
      const raw=sessionStorage.getItem('fs-upload:'+key);
      if (!raw) return {count:0,at:0,method:''};
      // Compatibility with v0.9.36, which stored a permanent literal "sent" lock.
      if (raw==='sent') return {count:1,at:0,method:'legacy_v0936'};
      const row=JSON.parse(raw);
      return {count:Number(row?.count||0),at:Number(row?.at||0),method:String(row?.method||'')};
    } catch (_) { return {count:0,at:0,method:''}; }
  }
  function dispatchCount(name) { return readDispatchRecord(name).count; }
  function lastDispatchAt(name) { return readDispatchRecord(name).at; }
  function wasDispatched(name) { return dispatchCount(name)>0; }
  function canAutoRetry(name, now=Date.now()) {
    const rec=readDispatchRecord(name);
    return rec.count>0 && rec.count<MAX_AUTO_UPLOAD_ATTEMPTS && now-rec.at>=UPLOAD_VERIFY_GRACE_MS;
  }
  function markDispatched(name, method='') {
    const key=uploadKey(name), prev=readDispatchRecord(name);
    const row={count:prev.count+1,at:Date.now(),method:String(method||'')};
    uploadLedger.set(key,row);
    try {
      sessionStorage.setItem('fs-upload:'+key,JSON.stringify(row));
      while(uploadLedger.size>1000){
        const oldest=uploadLedger.keys().next().value;
        if(!sessionStorage.getItem('fs-upload:'+oldest))break;
        uploadLedger.delete(oldest);
      }
    } catch (_) {}
    return row;
  }
  function clearDispatchRecord(name) {
    const key=uploadKey(name); uploadLedger.delete(key);
    try { sessionStorage.removeItem('fs-upload:'+key); } catch (_) {}
  }
  function visibleMediaNames() {
    const found=new Set();
    for (const el of uploadDeepQueryAll('img,[title],[aria-label]')) {
      if (el.closest?.('#flow-studio-v050-root') || !visible(el)) continue;
      for (const a of ['alt','title','aria-label']) {
        const text=el.getAttribute?.(a);
        if (text) found.add(norm(text));
      }
    }
    return found;
  }
  async function uploadMissing(auto=false) {
    if (!state.job || state.ready || state.uploadInFlight || state.generationRunning) return;
    const batch=missingImagePaths();
    if (!batch.names.length) return;
    const hints=state.mediaScanValid ? new Set() : visibleMediaNames();
    const missing=batch.names.filter(name=>!hints.has(norm(name)) && taskPathForName(name));
    const now=Date.now();
    const fresh=missing.filter(name=>dispatchCount(name)===0);
    const retryable=missing.filter(name=>canAutoRetry(name,now));
    const exhausted=missing.filter(name=>dispatchCount(name)>=MAX_AUTO_UPLOAD_ATTEMPTS);
    const waiting=missing.filter(name=>{const c=dispatchCount(name);return c>0&&c<MAX_AUTO_UPLOAD_ATTEMPTS&&!canAutoRetry(name,now);});
    const names=(auto ? (fresh.length ? fresh : retryable) : missing).slice(0,20);

    if (!names.length) {
      if (!missing.length && batch.noPath.length) {
        state.message='缺失图片没有本地路径：'+batch.noPath.slice(0,3).join('、');
      } else if (exhausted.length && !fresh.length && !retryable.length && !waiting.length) {
        const signature=state.identity+'|'+exhausted.map(norm).sort().join('|');
        state.message=`图片上传失败：已发送拖放/文件选择，但 Flow 未接收到 ${exhausted.length} 张图片；自动重试 ${MAX_AUTO_UPLOAD_ATTEMPTS} 次已用完`;
        if(typeof rememberUploadFailure==='function')rememberUploadFailure(exhausted,'Flow 未在素材目录中确认图片',MAX_AUTO_UPLOAD_ATTEMPTS,'自动重试已用完');
        if (!uploadFailureLedger.has(signature)) {
          uploadFailureLedger.add(signature);
          emit('media_upload_failed_final',{files:exhausted,count:exhausted.length,max_attempts:MAX_AUTO_UPLOAD_ATTEMPTS,error:'Flow did not expose uploaded media after verified dispatch retries'});
        }
      } else {
        const nextAt=waiting.length ? Math.min(...waiting.map(name=>lastDispatchAt(name)+UPLOAD_VERIFY_GRACE_MS)) : 0;
        const seconds=nextAt ? Math.max(1,Math.ceil((nextAt-now)/1000)) : 0;
        state.message=seconds ? `图片已发送，等待 Flow 真实素材确认；${seconds} 秒后仍未出现将自动重试` : '图片已发送或页面已有同名素材，等待 Flow 素材确认';
      }
      render(); return;
    }

    const busy=isFlowUploading();
    const oldestDispatch=Math.min(...names.map(name=>lastDispatchAt(name)||now));
    const stuckBusy=busy && names.every(name=>dispatchCount(name)>0) && now-oldestDispatch>=UPLOAD_BUSY_STUCK_MS;
    if (busy && !stuckBusy) emit('upload_busy_advisory',{files:names,count:names.length,message:'页面进度仅作诊断，按本任务上传状态继续'});
    if (stuckBusy) emit('upload_busy_stuck_override',{files:names,count:names.length,waited_ms:now-oldestDispatch});

    const paths=[...new Set(names.map(taskPathForName).filter(Boolean))];
    if (!paths.length) { state.message='缺失图片没有本地路径：'+names.slice(0,3).join('、'); render(); return; }

    state.uploadInFlight=true;
    state.uploadStageStartedAt=Date.now();
    state.uploadProgressAt=state.uploadStageStartedAt;
    state.uploadAttempts+=1;
    const attempt=state.uploadAttempts;
    const perImageAttempt=Math.max(...names.map(name=>dispatchCount(name)))+1;
    let result={ok:false}, pt=null;
    try {
      state.message=`${auto?'自动':'手动'}向 Flow 工作区上传 ${paths.length} 张图片${perImageAttempt>1?`（第 ${perImageAttempt} 次验证重试）`:''}`;
      render();
      emit('media_upload_started',{attempt,per_image_attempt:perImageAttempt,count:paths.length,files:paths.map(basename)});
      emit('upload_drag_attempt',{attempt,per_image_attempt:perImageAttempt,missing:names.length,matched:state.matched,total:getExpectedNames(state.job).length});
      setPanelTemporarilyHidden(true);
      await sleep(180);
      pt=findDropPoint();
      state.uploadProgressAt=Date.now();
      emit('upload_target_found',{attempt,per_image_attempt:perImageAttempt,drop_point:pt});
      emit('file_attached',{attempt,per_image_attempt:perImageAttempt,count:paths.length,files:paths.map(basename),mode:'local_paths_ready'});

      // Attempt 1 preserves the proven native drag path. If Flow ignores that drop,
      // attempt 2+ first uses the real file input when Flow exposes one, then falls
      // back to a freshly located native drag target.
      if (perImageAttempt>=2) {
        try { result=await fileInputUpload(paths); }
        catch(e) { result={ok:false,error:String(e?.message||e)}; }
      }
      if (!result.ok) {
        state.uploadProgressAt=Date.now();
        result=await new Promise(resolve=>{
          const timer=setTimeout(()=>resolve({ok:false,uncertain:true,error:'上传执行超时，请等待 Flow 素材验证'}),20000);
          try {
            chrome.runtime.sendMessage({type:'FS_NATIVE_DRAG',paths,x:pt.x,y:pt.y},r=>{
              clearTimeout(timer);
              const error=chrome.runtime.lastError?.message;
              resolve(error ? {ok:false,uncertain:true,error} : (r || {ok:false,uncertain:true,error:'上传无响应'}));
            });
          } catch(e) { clearTimeout(timer); resolve({ok:false,error:String(e.message||e)}); }
        });
      }
      if (!result.ok && !result.uncertain) {
        try { result=await syntheticDragUpload(paths,pt); }
        catch(e) { result={ok:false,error:String(e.message||e)}; }
      }
      if (result.ok) {
        names.forEach(name=>markDispatched(name,result.method||'chrome_debugger'));
        state.message=`已向 Flow 发送 ${paths.length} 张图片，等待真实素材记录确认…`;
        emit('drop_dispatched',{attempt,per_image_attempt:perImageAttempt,count:paths.length,method:result.method||'chrome_debugger',drop_point:pt});
        emit('media_upload_dispatched',{attempt,per_image_attempt:perImageAttempt,count:paths.length,method:result.method||'chrome_debugger',drop_point:pt});
      } else {
        const reason=result.error||'未知错误';
        if(typeof rememberUploadFailure==='function')rememberUploadFailure(names,reason,perImageAttempt,`第 ${perImageAttempt} 次上传失败`);
        state.message='上传未确认：'+reason+'；稍后将根据 Flow 素材记录决定是否重试';
        emit('media_upload_dispatch_failed',{attempt,per_image_attempt:perImageAttempt,error:reason,drop_point:pt});
      }
    } catch(e) {
      const reason=String(e.message||e);
      if(typeof rememberUploadFailure==='function')rememberUploadFailure(names,reason,perImageAttempt,`第 ${perImageAttempt} 次上传失败`);
      state.message='上传失败：'+reason;
      emit('media_upload_dispatch_failed',{attempt,per_image_attempt:perImageAttempt,error:reason});
    } finally {
      state.uploadInFlight=false;
      state.uploadStageStartedAt=0;
      state.uploadProgressAt=Date.now();
      state.lastUploadSucceeded=!!result.ok;
      state.lastUploadAt=Date.now();
      setPanelTemporarilyHidden(false);
      render();
    }
  }

  function maybeAutoUpload() {
    if (!state.autoUploadEnabled || state.ready || state.uploadInFlight) return;
    const missing = missingImageNames();
    if (!missing.length) return;
    const elapsed = Date.now() - state.lastUploadAt;
    // Page-wide progress is diagnostic only. uploadMissing() retains this task
    // upload mutex, verified dispatch ledger, confirmation grace and three-attempt limit.
    if (state.uploadAttempts === 0 || elapsed >= (state.lastUploadSucceeded ? 2500 : 45000)) return uploadMissing(true);
  }

  async function scanOnce() {
    if (!state.job || state.scanInFlight || state.generationRunning || state.uploadInFlight) return;
    state.scanInFlight=true;
    const identity=state.identity;
    try {
    const expected = getExpectedNames(state.job);
    if (!expected.length) {
      state.message = skippedUploadFullNames().length && activeGenerationTasks().length===0 ? '当前批次所有图片任务都已被手动跳过，没有可继续生成的任务' : 'Studio 任务没有可用参考图片文件名，无法匹配';
      stopScanner(); render(); return;
    }
    let snapshot;
    try { snapshot=await submitViaMainWorld({action:'scan_media'},5000); }
    catch(e) {
      if (identity !== state.identity) return;
      state.mediaScanValid=false; state.ready=false;
      state.message=String(e.message || e); render();
      await maybeAutoUpload();
      return;
    }
    if (identity !== state.identity) return;
    state.mediaScanValid=true;
    const wanted=new Set(expected.map(norm));
    const media=(snapshot.media || []).filter(m=>wanted.has(norm(m.name)));
    const previousRecognized=state.lastRecognizedMediaCount;
    state.media = media;
    state.lastRecognizedMediaCount=recognizedMediaCount();
    for (const m of media) {
      if(mediaUploadUsable(m)){
        // Only a truly usable Flow image may clear the retry ledger. Uploading/error
        // placeholders must keep their attempt count so failures cannot be forgotten.
        clearDispatchRecord(m.name);
        markUploadFailureRecovered(m.name);
      }else if(m.upload_error===true){
        rememberUploadFailure([m.name],'Flow 素材记录报告图片上传失败',dispatchCount(m.name),'Flow 上传失败');
      }
    }
    if (state.lastRecognizedMediaCount>previousRecognized) {
      emit('flow_media_detected',{recognized:state.lastRecognizedMediaCount,total:expected.length,added:state.lastRecognizedMediaCount-previousRecognized,files:media.map(m=>m.name)});
    }
    matchTasks(media);
    const duplicates=media.filter((m,i)=>media.findIndex(x=>norm(x.name)===norm(m.name))!==i);
    if (duplicates.length) { state.ready=false; state.message='存在同名素材，请在 Flow 中清理重复图片：'+[...new Set(duplicates.map(m=>m.name))].join('、'); render(); return; }
    const sig = media.map(x=>x.id+':'+norm(x.name)).sort().join('|');
    const imageCountNow=media.length;
    const imageTotalNow=expected.length;
    const readyTasks=activeGenerationTasks();
    const readyMatched=readyTasks.filter(t=>t.matched).length;
    const readyNow=imageTotalNow>0 && imageCountNow>=imageTotalNow && readyTasks.length>0 && readyMatched===readyTasks.length;
    if (sig && sig === state.lastSignature && readyNow) state.stableHits++;
    else state.stableHits = readyNow ? 1 : 0;
    state.lastSignature = sig;
    state.scanSeq++;
    state.lastSync = nowText();

    const uploadStatus=requiredUploadStatus();
    const imageRecognized=uploadStatus.recognized;
    const imageTotal=uploadStatus.total;
    const activeTasks=activeGenerationTasks();
    const activeMatched=activeTasks.filter(t=>t.matched).length;
    const allImagesReady=uploadStatus.ready;
    const allTasksMapped=activeTasks.length>0 && activeMatched===activeTasks.length;

    const uploadBusy=isFlowUploading();
    const stableUploadReady=allImagesReady && allTasksMapped && state.stableHits>=2 && !uploadBusy;

    if (stableUploadReady) {
      state.ready = true;
      state.message = `全部图片已在 Flow 确认存在并上传完成：${imageRecognized}/${imageTotal}，可生成任务 ${activeMatched}/${activeTasks.length}，已准备完成`;
      stopScanner();
      emit('media_ready',{
        recognized:imageRecognized,total:imageTotal,stable_checks:state.stableHits,
        task_matched:activeMatched,task_total:activeTasks.length,
        skipped_upload_failed:skippedUploadFullNames(),
        matched_files:activeTasks.map(t=>({task_id:t.task_id,image_name:t.image}))
      });
      emit('upload_verified',{matched:imageRecognized,total:imageTotal,attempts:state.uploadAttempts,verified:true});
      maybeStartNativeGeneration();
    } else {
      const missing = requiredUploadStatus().missing;
      const busy = uploadBusy;
      state.message = allImagesReady && allTasksMapped
        ? (busy ? `Flow 正在完成图片上传 · 暂不允许提交生成` : `图片已存在，正在进行连续确认 · ${state.stableHits}/2`)
        : (busy
          ? `Flow 正在上传图片 · 已确认可用 ${imageRecognized}/${imageTotal} · 可生成任务 ${activeMatched}/${activeTasks.length}`
          : `正在扫描当前集合：已确认可用 ${imageRecognized}/${imageTotal} · 可生成任务 ${activeMatched}/${activeTasks.length}` + (missing.length ? ` · 未就绪 ${missing.slice(0,3).join('、')}${missing.length>3?'…':''}` : ' · 稳定确认中'));
      emit('media_match_progress',{recognized:imageRecognized,total:imageTotal,task_matched:activeMatched,task_total:activeTasks.length,missing_files:missing,skipped_upload_failed:skippedUploadFullNames(),scan_seq:state.scanSeq,uploading:busy});
      emit('upload_flow_progress',{matched:imageRecognized,total:imageTotal,task_matched:activeMatched,task_total:activeTasks.length,missing_files:missing,skipped_upload_failed:skippedUploadFullNames(),uploading:busy});
      setTimeout(maybeAutoUpload, 80);
    }
    render();
    } finally { state.scanInFlight=false; }
  }

  function startScanner() {
    stopScanner();
    scanOnce();
    state.scanTimer = setInterval(scanOnce, 2000);
  }
  function stopScanner() {
    if (state.scanTimer) clearInterval(state.scanTimer);
    state.scanTimer = null;
  }

  // ===== v0.9.14 Flow 内部状态执行器 =====
  // 不依赖旧插件 storage / UI / 开始按钮；直接操作当前 Flow 页面。
  // v0.9.62 incremental: hidden-page waits are armed from a non-timer task to avoid Chrome's
  // intensive chained-timer throttling. Foreground behavior and requested delays stay unchanged.
  const backgroundSleepWaiters=new Set();
  function signalBackgroundWake(){
    const now=Date.now();
    for(const waiter of [...backgroundSleepWaiters])if(waiter.deadline<=now)waiter.finish();
    try{window.dispatchEvent(new CustomEvent('FLOW_STUDIO_BACKGROUND_WAKE'));}catch(_){}
  }
  function sleep(ms){
    const delay=Math.max(0,Number(ms)||0);
    return new Promise(resolve=>{
      let settled=false,timer=null,channel=null;
      const waiter={deadline:Date.now()+delay,finish:()=>{
        if(settled)return;settled=true;
        if(timer)clearTimeout(timer);
        backgroundSleepWaiters.delete(waiter);
        try{channel?.port1?.close();channel?.port2?.close();}catch(_){}
        resolve();
      }};
      backgroundSleepWaiters.add(waiter);
      const arm=()=>{if(!settled)timer=setTimeout(waiter.finish,Math.max(0,waiter.deadline-Date.now()));};
      if(document.visibilityState==='hidden' && typeof MessageChannel!=='undefined'){
        try{channel=new MessageChannel();channel.port1.onmessage=arm;channel.port2.postMessage(0);}catch(_){arm();}
      }else arm();
    });
  }

  function finalPromptForTask(t) {
    const dialogue=String(t.dialogue||'').trim(), prompt=String(t.prompt||'').trim();
    if(!dialogue) return prompt;
    if(/文案\s*[:：]/.test(prompt) || prompt.includes(dialogue)) return prompt;
    return `文案：\n${dialogue}\n提示词：${prompt}`;
  }

  let mainEngineSeq=0;

  let backgroundGuardPromise=null,backgroundGuardAt=0,backgroundGuardCommand='';
  async function ensureBackgroundExecution(){
    const command=String(state.job?.command_id||'');
    if(!command)return;
    if(backgroundGuardCommand===command && Date.now()-backgroundGuardAt<5000)return;
    if(backgroundGuardPromise)return backgroundGuardPromise;
    backgroundGuardPromise=new Promise(resolve=>{
      let settled=false;
      const finish=result=>{
        if(settled)return;settled=true;clearTimeout(timer);
        if(result?.ok){backgroundGuardAt=Date.now();backgroundGuardCommand=command;}
        else if(result?.error)chrome.runtime.sendMessage({type:'FS_RUNTIME_LOG',stage:'background_guard_unavailable',detail:{command_id:command,error:result.error}},()=>void chrome.runtime.lastError);
        resolve();
      };
      const timer=setTimeout(()=>finish({error:'BACKGROUND_GUARD_TIMEOUT'}),5000);
      try{chrome.runtime.sendMessage({type:'FS_ENSURE_BACKGROUND',command_id:command},result=>{
        const error=chrome.runtime.lastError;finish(error?{error:error.message}:result);
      });}catch(error){finish({error:String(error?.message||error)});}
    }).finally(()=>{backgroundGuardPromise=null;});
    return backgroundGuardPromise;
  }

  async function submitViaMainWorld(payload, timeoutMs=110000) {
    await ensureBackgroundExecution();
    return new Promise((resolve,reject)=>{
      const request_id=`fs-main-${Date.now()}-${++mainEngineSeq}`;
      let done=false;
      const timer=setTimeout(()=>{
        if(done) return; done=true;
        window.removeEventListener('FLOW_STUDIO_MAIN_RESULT',onResult);
        reject(new Error('MAIN_ENGINE_TIMEOUT'));
      },timeoutMs);
      function onResult(ev){
        const d=ev.detail||{};
        if(d.request_id!==request_id) return;
        if(done) return; done=true; clearTimeout(timer);
        window.removeEventListener('FLOW_STUDIO_MAIN_RESULT',onResult);
        d.ok ? resolve(d) : reject(new Error(d.error||'MAIN_ENGINE_FAILED'));
      }
      window.addEventListener('FLOW_STUDIO_MAIN_RESULT',onResult);
      window.dispatchEvent(new CustomEvent('FLOW_STUDIO_MAIN_COMMAND',{detail:{...payload,request_id}}));
    });
  }

  function pageHealthSnapshot(){
    const text=(document.body?.innerText||'').slice(0,120000);
    const buttons=[...document.querySelectorAll('button,[role="button"]')];
    const generateCandidates=buttons.filter(el=>/生成|generate|create/i.test((el.innerText||el.getAttribute('aria-label')||el.getAttribute('title')||'').trim()));
    return {
      visibility:document.visibilityState,
      ready_state:document.readyState,
      generate_candidates:generateCandidates.length,
      body_text_length:text.length,
      location:location.href,
      ts:Date.now()
    };
  }

  const DURABLE_DISPATCH_LEDGER='flowStudioConfirmedDispatchLedgerV0923';
  function taskLedgerKey(job,t,round){
    return `${job?.command_id||''}:${t?.segment_id||t?.task_id||''}:${round}`;
  }
  async function taskAlreadyConfirmed(job,t,round){
    try{const k='flowStudioConfirmedIds:'+taskLedgerKey(job,t,round);if((await chrome.storage.local.get(k))[k]?.length)return true;}catch(_){}
    const key=taskLedgerKey(job,t,round);
    try{if(sessionStorage.getItem('flow-studio-dispatch:'+key)==='confirmed')return true;}catch(_){}
    try{
      const d=await chrome.storage.local.get(DURABLE_DISPATCH_LEDGER);
      return !!(d[DURABLE_DISPATCH_LEDGER]||{})[key];
    }catch(_){return false;}
  }
  async function markTaskConfirmed(job,t,round,ids=[]){
    const key=taskLedgerKey(job,t,round),ts=Date.now();
    try{await chrome.storage.local.set({['flowStudioConfirmedIds:'+key]:ids});}catch(error){throw Error('SUBMISSION_UNCONFIRMED:无法保存已提交视频ID，禁止重复点击');}
    try{sessionStorage.setItem('flow-studio-dispatch:'+key,'confirmed');}catch(_){}
    try{
      const d=await chrome.storage.local.get(DURABLE_DISPATCH_LEDGER);
      const ledger={...(d[DURABLE_DISPATCH_LEDGER]||{}),[key]:ts};
      const entries=Object.entries(ledger);
      if(entries.length>5000){
        entries.sort((a,b)=>Number(b[1])-Number(a[1]));
        const keep=Object.fromEntries(entries.slice(0,5000));
        await chrome.storage.local.set({[DURABLE_DISPATCH_LEDGER]:keep});
      }else await chrome.storage.local.set({[DURABLE_DISPATCH_LEDGER]:ledger});
    }catch(_){}
  }

  function isUncertainSubmissionError(error){
    return /SUBMISSION_UNCONFIRMED|SUBMIT_NOT_CONFIRMED|MAIN_ENGINE_TIMEOUT/.test(String(error?.message||error||''));
  }

  function claimSegment(command_id,segment_id,recovery=false){
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('SUBMISSION_UNCONFIRMED:任务归属核对超时')),15000);
      chrome.runtime.sendMessage({type:'FS_CLAIM_COMMAND',command_id,segment_id,recovery:!!recovery},r=>{
        clearTimeout(timer);const err=chrome.runtime.lastError;
        if(err||!r?.ok)reject(Error('SUBMISSION_UNCONFIRMED:'+(err?.message||r?.error||'无法核对当前片段归属')));else resolve(!!r.owned);
      });
    });
  }

  async function recoverReservation(job,t,round,reservation,prompt,taskMeta,windowMs=30000){
    const deadline=Date.now()+Math.max(0,Number(windowMs)||0);let attempts=0,lastError='';
    emit('submission_recovery_started',{...taskMeta,segment_id:t.segment_id,round,message:'提交确认超时，正在核对原生成结果；不会重复点击生成'});
    while(Date.now()<=deadline){
      attempts++;
      try{
        const result=await submitViaMainWorld({action:'recover_video_identity',prompt,recovery_key:reservation.key},10000);
        const ids=[...new Set((result.ids||[]).filter(x=>typeof x==='string'&&x))];
        if(ids.length===1){
          const owned=await claimSegment(job.command_id,t.segment_id,true).catch(()=>false);
          if(!owned){lastError='原任务归属已变化，停止自动绑定旧结果';break;}
          await markTaskConfirmed(job,t,round,ids);
          await downloadMessage({type:'FS_DOWNLOAD_BIND',key:reservation.key,ids});
          emit('submission_recovered',{...taskMeta,segment_id:t.segment_id,round,generation_ids:ids,message:'已自动找回原生成结果，未重复生成'});
          emit('generation_task_status',{...taskMeta,segment_id:t.segment_id,round,state:'success',generation_ids:ids,message:'已恢复原提交结果，继续等待下载'});
          try{const scan=await submitViaMainWorld({action:'scan_video_results',ids},10000);await downloadMessage({type:'FS_DOWNLOAD_OBSERVE',rows:scan.rows||[],diagnostics:scan.diagnostics});}catch(_){}
          return {recovered:true,ids};
        }
      }catch(error){lastError=String(error?.message||error||'');}
      if(Date.now()+2000>deadline)break;
      await sleep(2000);
    }
    emit('submission_recovery_pending',{...taskMeta,segment_id:t.segment_id,round,attempts,last_error:lastError,message:'暂未确认原生成结果，已转后台继续核对；后续任务继续执行，不会重复生成'});
    return {recovered:false,deferred:true,lastError};
  }

  let pendingRecoveryRunning=false;
  async function recoverPendingReservations(){
    if(pendingRecoveryRunning)return;pendingRecoveryRunning=true;
    try{
      const entries=await downloadMessage({type:'FS_DOWNLOAD_PENDING',all:true});
      for(const entry of entries||[]){
        if(!entry?.attempt_started_at && !entry?.uncertain_at && !entry?.submitted_at)continue;
        const info=entry.info||{};const prompt=String(info.recovery_prompt||'').trim();
        if(!prompt||!info.command_id||info.segment_id==null)continue;
        let result;try{result=await submitViaMainWorld({action:'recover_video_identity',prompt,recovery_key:entry.key},7000);}catch(_){continue;}
        const ids=[...new Set((result.ids||[]).filter(x=>typeof x==='string'&&x))];
        if(ids.length!==1){if(result.diag){const k='diag:'+entry.key,now=Date.now();if(!(recoverPendingReservations._d||(recoverPendingReservations._d={}))[k]||now-recoverPendingReservations._d[k]>60000){recoverPendingReservations._d[k]=now;emit('submission_recovery_diag',{command_id:info.command_id,channel_key:info.channel_key||state.job?.channel_key||'',host_id:info.host_id||0,segment_id:info.segment_id,task_id:info.task_id,message:'后台恢复未找到唯一视频：'+JSON.stringify(result.diag).slice(0,1500)});}}continue;}
        const owned=await claimSegment(info.command_id,info.segment_id,true).catch(()=>false);if(!owned)continue;
        const pseudoJob={command_id:info.command_id},pseudoTask={segment_id:info.segment_id,task_id:info.task_id};
        await markTaskConfirmed(pseudoJob,pseudoTask,Number(info.round||1),ids);
        await downloadMessage({type:'FS_DOWNLOAD_BIND',key:entry.key,ids});
        emit('submission_recovered',{command_id:info.command_id,channel_key:info.channel_key||state.job?.channel_key||'',host_id:info.host_id||0,recipient_id:info.recipient_id||0,segment_id:info.segment_id,task_id:info.task_id,round:Number(info.round||1),generation_ids:ids,message:'后台已自动找回原生成结果，未重复生成'});
        emit('generation_task_status',{command_id:info.command_id,channel_key:info.channel_key||state.job?.channel_key||'',host_id:info.host_id||0,recipient_id:info.recipient_id||0,segment_id:info.segment_id,task_id:info.task_id,round:Number(info.round||1),state:'success',generation_ids:ids,message:'已恢复原提交结果，继续等待下载'});
      }
    }catch(_){}finally{pendingRecoveryRunning=false;}
  }
  setInterval(()=>{void recoverPendingReservations();},10000);

  async function prepareOpenEyeReference(job,t) {
    if(!t.open_eye_prompt)return null;
    const identity=JSON.stringify([location.pathname,t.host_id,t.image,t.open_eye_prompt]);
    const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(identity));
    const eyeKey=[...new Uint8Array(hash)].map(n=>n.toString(16).padStart(2,'0')).join('');
    const prompt=t.open_eye_prompt+' Internal reference '+eyeKey+' (metadata only, do not render text).';
    const deadline=Date.now()+240000;
    state.message='正在准备同一人物的睁眼参考图，图片就绪后再生成睁眼视频';render();
    while(Date.now()<deadline){
      if(state.cancelledCommand===job.command_id)throw Error('COMMAND_CANCELLED');
      if(!await claimSegment(job.command_id,t.segment_id,false))throw Error('TASK_REMOVED');
      const result=await submitViaMainWorld({action:'ensure_open_eye',eye_key:eyeKey,
        image_id:t.flow_media_id,prompt,aspect_ratio:job.settings?.aspect_ratio||'9:16'},30000);
      if(result.ready && result.image_id)return result;
      await sleep(3000);
    }
    throw Error('睁眼参考图尚未就绪，未提交视频；重试将继续查找原图片任务，不会重复生成图片');
  }
  async function submitWithRecovery(payload, taskMeta){
    const normalWaits=[1500,3000,5000,8000,12000];
    // One retry sequence; ENGINE_BUSY only reports the actual submit mutex.
    let attempt=0, readinessWaits=0;
    while(true){
      if(payload.command_id && (state.cancelledCommand===payload.command_id || state.job?.command_id!==payload.command_id)) throw Error('COMMAND_CANCELLED');
      if(state.generationPaused){await sleep(500);continue;}
      try{
        const result=await submitViaMainWorld(payload);
        if(attempt) emit('flow_page_recovered',{...taskMeta,attempts:attempt,health:pageHealthSnapshot(),message:'Flow 页面已恢复，可继续提交'});
        return result;
      }catch(error){
        const msg=String(error?.message||error||'');
        // Never retry uncertain submission states: Flow may already have received the click.
        if(isUncertainSubmissionError(error)) throw error;
        if(state.cancelledCommand && payload?.command_id && state.cancelledCommand===payload.command_id) throw Error('COMMAND_CANCELLED');
        // These exact errors are emitted before button.click(). Waiting here cannot
        // duplicate a submitted video. Keep ambiguous/post-click errors above untouched.
        const awaitingInput=/^(?:REFERENCE_STATE_NOT_DETECTED|FIRST_FRAME_NOT_CONFIRMED|FLOW_GENERATE_BUTTON_NOT_READY|BUTTON_NOT_READY|FLOW_IMAGE_ASSET_NOT_READY)(?:$|[:：])/.test(msg);
        if(awaitingInput && readinessWaits<36){
          readinessWaits++;
          if(readinessWaits===1 || readinessWaits%6===0) emit('flow_page_recovering',{...taskMeta,error:msg,attempt:readinessWaits,wait_ms:5000,health:pageHealthSnapshot(),message:'图片或生成框尚未就绪，尚未点击生成，继续等待'});
          state.message='等待图片处理和生成框就绪 · 尚未点击生成';render();
          await sleep(5000);continue;
        }
        if(awaitingInput) throw error;
        const engineBusy=/^ENGINE_BUSY(?:$|[:_\s])/i.test(msg);
        // v0.9.57+: MATERIAL binding-protection retries are intentionally removed.
        // Keep generic Flow page/button recovery, plus v0.9.62 transient engine-busy
        // serialization. Native asset selection itself remains unchanged.
        const recoverable=engineBusy || /REFERENCE_STATE_NOT_DETECTED|FIRST_FRAME_NOT_CONFIRMED|FLOW_GENERATE_BUTTON_NOT_READY|GENERATE_BUTTON|FLOW_INSTANCE_NOT_FOUND|BUTTON_NOT_READY|FLOW_SUBMISSION_NOT_STARTED/i.test(msg);
        const transientPage=/REFERENCE_STATE_NOT_DETECTED|FIRST_FRAME_NOT_CONFIRMED|FLOW_GENERATE_BUTTON_NOT_READY|BUTTON_NOT_READY/.test(msg);
        const waits=transientPage?normalWaits.slice(0,2):normalWaits;
        if(!recoverable || attempt>=waits.length) throw error;
        const health=pageHealthSnapshot();
        const waitMs=waits[attempt];
        if(engineBusy){
          emit('engine_busy_waiting',{...taskMeta,error:msg,attempt:attempt+1,wait_ms:waitMs,health,message:'当前提交锁尚未释放，使用普通提交重试，不增加单独繁忙等待队列'});
          state.message=`等待当前提交完成 ${attempt+1}/${waits.length} · ${Math.ceil(waitMs/1000)}秒后继续`;
        }else{
          const reason=/^FLOW_SUBMISSION_NOT_STARTED/.test(msg)?'Flow 未接收到生成点击':
            /^FLOW_GENERATE_BUTTON_STALE_OR_DISABLED/.test(msg)?'生成按钮已刷新或暂不可点击':
            /GENERATE_BUTTON/.test(msg)?'生成按钮状态尚未稳定':'Flow 页面状态暂不可提交';
          emit('flow_page_recovering',{...taskMeta,error:msg,attempt:attempt+1,wait_ms:waitMs,health,message:reason+'，正在自动恢复'});
          state.message=`${reason} · 恢复重试 ${attempt+1}/${waits.length} · ${Math.ceil(waitMs/1000)}秒后继续`;
        }
        render();
        await sleep(waitMs);
        attempt++;
      }
    }
  }

  async function setPausedFromPlugin(paused){
    const res=await new Promise(resolve=>chrome.runtime.sendMessage({type:'FS_SET_PAUSED',paused:!!paused},r=>resolve(r||{ok:false})));
    if(!res.ok) throw new Error(res.error||'无法同步暂停状态');
    state.generationPaused=!!paused;
    state.message=state.generationPaused?'已暂停：当前云端生成不会取消，新的任务停止提交':'已继续：恢复提交等待中的生成任务';
    render();
  }

  async function waitWhilePaused(){
    while(state.generationPaused){
      state.message='⏸ 批量生成已暂停 · 当前云端任务继续运行 · 等待继续';
      render();
      await sleep(500);
    }
  }

  async function runProgressSync(source='manual'){
    try{
      await downloadMessage({type:'FS_DOWNLOAD_POLL'});
      const c=state.downloadCounts;
      const rounds=Math.max(1,Number(state.job?.generation_count||1));
      const planned=activeGenerationTasks().length*rounds;
      const submitted=Math.min(planned,state.generationSubmitted+state.generationFailed);
      emit('web_plugin_progress_snapshot',{
        source,planned,waiting_generation:Math.max(0,planned-submitted),
        generating:c.waiting||0,generated_success:(c.ready||0)+(c.downloading||0)+(c.complete||0),
        failed:c.failed||state.generationFailed||0,deferred:state.generationDeferred||0,downloading:c.downloading||0,downloaded:c.complete||0,
        paused:state.generationPaused,scan_version:state.lastProgressScanVersion
      });
      state.lastSync=nowText();render();
    }catch(error){state.downloadSummary='10秒进度同步失败：'+String(error.message||error);render();}
  }

  async function runOneTask(job,t,round,totalIndex,totalRuns) {
    const key=job.command_id+':'+t.segment_id;
    if(rebalanceRevoked.has(key))throw Error('TASK_REMOVED');
    rebalanceInFlight=key;
    try{return await runOneTaskImpl(job,t,round,totalIndex,totalRuns);}
    finally{if(rebalanceInFlight===key)rebalanceInFlight=null;}
  }
  async function runOneTaskImpl(job,t,round,totalIndex,totalRuns) {
    await waitWhilePaused();
    if(state.cancelledCommand===job.command_id)throw Error('COMMAND_CANCELLED');
    const taskLabel=t.task_name||t.task_id;
    const rounds=Math.max(1,Number(job.generation_count||1));
    const downloadName=String(t.download_names?.[round-1] || (t.download_stem + (rounds>1?`-R${String(round).padStart(2,'0')}`:'')));
    const taskMeta={host_id:t.host_id,host_name:t.host_name,recipient_id:t.recipient_id,recipient_name:t.recipient_name,
      task_id:t.task_id,task_name:taskLabel,dispatch_order:t.dispatch_order,round,generation_mode:t.generation_mode};
    emit('generation_task_status',{...taskMeta,segment_id:t.segment_id,state:'preparing',message:`准备提交 ${taskLabel} · 第 ${round}/${rounds} 轮` });
    state.message=`正在生成 ${totalIndex}/${totalRuns} · ${taskLabel}`; render();

    const prompt=finalPromptForTask(t);
    if(!prompt) throw new Error(`任务 ${taskLabel} 没有可提交的提示词`);

    const eyeReference=await prepareOpenEyeReference(job,t);
    const reservation=await downloadMessage({type:'FS_DOWNLOAD_RESERVE',info:{
      document_number:t.document_number,task_id:t.task_id,task_name:taskLabel,download_name:downloadName,dispatch_order:t.dispatch_order,
      segment_id:t.segment_id,round,command_id:job.command_id,
      host_id:t.host_id,host_name:t.host_name,recipient_id:t.recipient_id,recipient_name:t.recipient_name,
      channel_id:job.channel_id,channel_key:job.channel_key,channel_role:job.channel_role,image_set_id:job.image_set_id,collection_url:job.collection_url,
      collection_name:job.collection_name||job.channel_key||'Flow通道',download_folder:job.download_folder||`FlowStudio_Channels/${job.channel_key||'CH'}`,
      recovery_prompt:prompt,generation_mode:t.generation_mode
    }});
    if(await taskAlreadyConfirmed(job,t,round)) {
      const idKey='flowStudioConfirmedIds:'+taskLedgerKey(job,t,round);
      const saved=await chrome.storage.local.get(idKey);
      if(saved[idKey]?.length)await downloadMessage({type:'FS_DOWNLOAD_BIND',key:reservation.key,ids:saved[idKey]});
      emit('generation_task_status',{...taskMeta,segment_id:t.segment_id,state:'success',message:`已确认提交过 ${taskLabel} · 第 ${round} 轮，为避免重复生成已跳过再次点击`,deduplicated:true});
      return;
    }
    if(reservation.existing&&reservation.status==='reserved'&&(reservation.attempt_started_at||reservation.uncertain_at||reservation.submitted_at)){
      const recovered=await recoverReservation(job,t,round,reservation,prompt,taskMeta,12000);
      if(recovered.recovered)return recovered;
      const marker=Number(reservation.uncertain_at||reservation.submitted_at||reservation.attempt_started_at||0);
      const legacyOnly=!!reservation.submitted_at && !reservation.uncertain_at;
      const attemptOnly=!!reservation.attempt_started_at && !reservation.uncertain_at && !reservation.submitted_at;
      // v0.9.48 migration/restart recovery. Old builds wrote submitted_at before the
      // real Flow click; a service-worker restart can also leave only attempt_started_at.
      // We first try identity recovery above. Only after a long no-result grace window
      // do we re-arm, so a real but delayed Flow request is not duplicated.
      if((legacyOnly||attemptOnly) && marker && Date.now()-marker>90000){
        await downloadMessage({type:'FS_DOWNLOAD_REARM_UNCONFIRMED',key:reservation.key});
        reservation.submitted_at=0;reservation.attempt_started_at=0;
        emit('submission_false_marker_rearmed',{...taskMeta,segment_id:t.segment_id,round,message:'已清理过期的确认前提交标记，重新执行真实 Flow 提交'});
      }else{
        emit('generation_task_status',{...taskMeta,segment_id:t.segment_id,round,state:'uncertain',message:'原任务存在未确认点击记录，正在后台恢复；未确认前不会重复生成'});
        return {deferred:true};
      }
    }
    const allowed=await claimSegment(job.command_id,t.segment_id,false);
    if(!allowed){await downloadMessage({type:'FS_DOWNLOAD_CANCEL',key:reservation.key,error:'TASK_REMOVED'}).catch(()=>{});throw Error('TASK_REMOVED');}
    let result;
    if(state.cancelledCommand===job.command_id)throw Error('COMMAND_CANCELLED');
    await downloadMessage({type:'FS_DOWNLOAD_SUBMITTING',key:reservation.key});
    // Persist the submit gate before the real Flow submission. This survives wave
    // release/refill so a one-task wave cannot bypass the configured spacing.
    noteSubmissionAttempt(job);
    try { result=await submitWithRecovery({
      action:'submit_task', recovery_key:reservation.key, image_name:eyeReference?.image_name||t.image, image_id:eyeReference?.image_id||t.flow_media_id, open_eye_reference:!!eyeReference,
      model:job.video_model || job.videoModel || job.generation_model || job.model || 'veo_3_1_lite_low_priority',
      aspect_ratio:job.aspect_ratio ?? job.aspectRatio ?? job.video_aspect_ratio ?? job.video_ratio ?? job.ratio ?? job.settings?.aspect_ratio ?? job.settings?.aspectRatio ?? job.generation_settings?.aspect_ratio ?? '9:16',
      duration:t.duration, needs_split:t.needs_split, force_submit:t.force_submit, image_path:t.image_path, prompt, mode:(t.generation_mode==='MATERIAL'?'VIDEO_REFERENCES':'VIDEO_FRAMES'), generation_mode:t.generation_mode, round,
      task_id:t.task_id, task_name:taskLabel, segment_id:t.segment_id, command_id:job.command_id
    }, taskMeta); } catch(error) {
      if(isUncertainSubmissionError(error)){
        await downloadMessage({type:'FS_DOWNLOAD_UNCERTAIN',key:reservation.key,error:String(error.message||error)}).catch(()=>{});
        const recovered=await recoverReservation(job,t,round,reservation,prompt,taskMeta,30000);
        if(recovered.recovered)return recovered;
        noteSubmissionOutcome(job,'uncertain');
        emit('generation_task_status',{...taskMeta,segment_id:t.segment_id,round,state:'uncertain',message:'提交状态暂未确认，后台继续核对；不会重复生成，后续任务继续执行'});
        state.message=`${taskLabel} 提交确认超时 · 已转后台恢复 · 正在继续后续任务`;render();
        return {deferred:true};
      }
      await downloadMessage({type:'FS_DOWNLOAD_CANCEL',key:reservation.key,error:String(error.message||error)}).catch(()=>{});
      throw error;
    }
    await markTaskConfirmed(job,t,round,result.generation_ids||[]);
    // v0.9.57: start the configured interval from the *confirmed* Flow submission, not
    // from the initial click attempt. This prevents one-task waves from clearing and
    // immediately submitting the next wave when confirmation itself consumed the delay.
    noteSubmissionOutcome(job,'confirmed');
    try { await downloadMessage({type:'FS_DOWNLOAD_BIND',key:reservation.key,ids:result.generation_ids||[]}); }
    catch(error){
      emit('submission_recovery_pending',{...taskMeta,segment_id:t.segment_id,round,message:'生成已提交，但结果绑定暂未完成；后台会自动恢复，不会重复生成'});
      emit('generation_task_status',{...taskMeta,segment_id:t.segment_id,round,state:'uncertain',message:'已提交，结果绑定待自动恢复；后续任务继续'});
      return {deferred:true};
    }

    emit('generation_task_status',{...taskMeta,segment_id:t.segment_id,state:'success',
      message:`已提交 ${taskLabel} · 第 ${round} 轮`,method:result?.method||'flow_native_state',generation_ids:result.generation_ids || [],applied_settings:result.settings || {}});
    return {deferred:false,generation_ids:result.generation_ids||[]};
  }

  function submissionInterval(job) {
    const sources=[job,job?.settings,job?.generation_settings].filter(Boolean);
    for(const cfg of sources) {
      for(const key of ['generation_interval_ms','submission_interval_ms','interval_ms']) {
        if(cfg[key]!=null && cfg[key]!=='') {
          const ms=Number(cfg[key]);if(Number.isFinite(ms)&&ms>0)return ms;
          throw new Error('提交间隔必须是大于0的有效数字');
        }
      }
      for(const key of ['generation_interval_seconds','submission_interval_seconds','interval_seconds','generation_interval','interval']) {
        if(cfg[key]!=null && cfg[key]!=='') {
          const seconds=Number(cfg[key]);if(Number.isFinite(seconds)&&seconds>0)return seconds*1000;
          throw new Error('提交间隔必须是大于0的有效数字');
        }
      }
    }
    return 20000;
  }
  function submissionRandomInterval(job) {
    const sources=[job,job?.settings,job?.generation_settings].filter(Boolean);
    for(const cfg of sources) {
      for(const key of ['generation_interval_random_ms','submission_interval_random_ms','interval_random_ms']) {
        if(cfg[key]!=null && cfg[key]!=='') {
          const ms=Number(cfg[key]);if(Number.isFinite(ms)&&ms>=0)return ms;
        }
      }
      for(const key of ['generation_interval_random_seconds','submission_interval_random_seconds','interval_random_seconds','intervalRandom']) {
        if(cfg[key]!=null && cfg[key]!=='') {
          const seconds=Number(cfg[key]);if(Number.isFinite(seconds)&&seconds>=0)return seconds*1000;
        }
      }
    }
    return 0;
  }
  function submissionGateKey(job){
    return 'flow-studio-submit-gate:'+String(job?.channel_key||job?.channel_id||job?.host_id||location.pathname||'default');
  }
  function readSubmissionGate(job){
    try{const row=JSON.parse(sessionStorage.getItem(submissionGateKey(job))||'{}');return {last_at:Number(row?.last_at||0),next_at:Number(row?.next_at||0),delay_ms:Number(row?.delay_ms||0),base_ms:Number(row?.base_ms||0),rand_ms:Number(row?.rand_ms||0),source:String(row?.source||'')};}catch(_){return {last_at:0,next_at:0,delay_ms:0,base_ms:0,rand_ms:0,source:''};}
  }
  function scheduleSubmissionGate(job,source='attempt'){
    const base=submissionInterval(job),jitterMax=submissionRandomInterval(job);
    const jitter=jitterMax>0?Math.floor(Math.random()*(jitterMax+1)):0;
    const now=Date.now(),delay=base+jitter,row={last_at:now,next_at:now+delay,delay_ms:delay,source,base_ms:base,rand_ms:jitterMax};
    try{sessionStorage.setItem(submissionGateKey(job),JSON.stringify(row));}catch(_){}
    emit('generation_interval_scheduled',{interval_ms:delay,base_interval_ms:base,random_interval_ms:jitter,source});
    return row;
  }
  function noteSubmissionAttempt(job){ return scheduleSubmissionGate(job,'attempt'); }
  function noteSubmissionOutcome(job,source='confirmed'){ return scheduleSubmissionGate(job,source); }
  async function waitForNextSubmission(previousConfirmedAt,job) {
    let reported=-1;
    while(true) {
      await waitWhilePaused();
      if(state.cancelledCommand===job.command_id)throw Error('COMMAND_CANCELLED');
      const current=state.job?.command_id===job.command_id?state.job:job;
      let gate=readSubmissionGate(current);
      const base=submissionInterval(current);
      // Studio 里修改间隔/随机时间后，立即按新值重算当前这次等待（以上次提交时间为起点）。
      try{
        const newRand=submissionRandomInterval(current);
        if(gate.last_at>0 && gate.next_at>Date.now() && gate.base_ms>0 && (gate.base_ms!==base || gate.rand_ms!==newRand)){
          const jit=newRand>0?Math.floor(Math.random()*(newRand+1)):0,delay=base+jit;
          gate={...gate,next_at:gate.last_at+delay,delay_ms:delay,base_ms:base,rand_ms:newRand};
          sessionStorage.setItem(submissionGateKey(current),JSON.stringify({last_at:gate.last_at,next_at:gate.next_at,delay_ms:delay,source:gate.source||'resync',base_ms:base,rand_ms:newRand}));
        }
      }catch(_){}
      const fallbackAt=Number(previousConfirmedAt||0);
      const nextAt=gate.next_at>0?gate.next_at:(fallbackAt>0?fallbackAt+base:0);
      const remaining=nextAt-Date.now();
      const interval=gate.delay_ms>0?gate.delay_ms:base;
      if(interval!==reported){reported=interval;emit('generation_interval_applied',{interval_ms:interval,base_interval_ms:base,random_interval_ms:Math.max(0,interval-base)});}
      if(remaining<=0)return;
      const randomPart=Math.max(0,interval-base);
      state.message=`等待下一次提交：${Math.ceil(remaining/1000)}秒 · 本次间隔 ${Math.round(interval/1000)}秒${randomPart?`（基础 ${Math.round(base/1000)} + 随机 ${Math.round(randomPart/1000)}）`:''}`;
      render();
      await sleep(Math.min(500,remaining));
    }
  }
  async function runNativeBatch(job) {
    if(state.generationRunning || state.uploadInFlight) return;
    const cmd=String(job?.command_id||'');
    const executionKey=jobExecutionKey(job);
    if(!cmd || !executionKey || state.generationCommand===executionKey) return;
    if(!state.ready || !job?.dispatch_tasks || !job?.auto_execute) return;
    if(state.commandClaimRunning || state.generationRunning)return;
    state.commandClaimRunning=true;
    try{
    const uploadPreflight=await confirmAllImagesInFlowBeforeSubmit(job);
    if(jobExecutionKey(state.job)!==executionKey || state.cancelledCommand===cmd)return;
    if(!uploadPreflight.ok){
      state.ready=false;state.stableHits=0;
      state.message=uploadPreflight.error
        ? `提交前图片确认失败：${uploadPreflight.error}`
        : `禁止开始生成：图片尚未全部进入 Flow（${uploadPreflight.recognized}/${uploadPreflight.total}）`+(uploadPreflight.missing?.length?` · 缺 ${uploadPreflight.missing.slice(0,3).join('、')}${uploadPreflight.missing.length>3?'…':''}`:'');
      emit('generation_upload_barrier_blocked',{recognized:uploadPreflight.recognized||0,total:uploadPreflight.total||0,missing_files:uploadPreflight.missing||[],message:state.message});
      startScanner();render();return;
    }
    emit('generation_upload_barrier_passed',{recognized:uploadPreflight.recognized,total:uploadPreflight.total,message:'全部图片已在 Flow 媒体目录确认，允许开始提交生成'});
    }catch(error){state.message=String(error.message||error);render();return;}
    finally{state.commandClaimRunning=false;}
    if(jobExecutionKey(state.job)!==executionKey || state.cancelledCommand===cmd || state.generationRunning)return;
    markStartedWave(executionKey);
    state.generationRunning=true; state.generationCommand=executionKey; state.generationSubmitted=0; state.generationFailed=0; state.generationDeferred=0;
    const tasks=activeGenerationTasks().filter(t=>t.prompt||t.dialogue);
    if(!tasks.length){state.message='没有可生成任务：当前批次图片均未成功上传或已被手动跳过';state.generationRunning=false;render();return;}
    const rounds=Math.max(1,Math.min(4,Number(job.generation_count||1)));
    const totalRuns=tasks.length*rounds;
    emit('generation_auto_started',{total:tasks.length,segment_ids:tasks.map(t=>t.segment_id).filter(Boolean),rounds});
    let index=0, paused=false;
    try{
      submissionInterval(state.job || job);
      // v0.9.45: enforce spacing across wave boundaries as well. If the previous
      // one-task wave was just submitted, the first task of this new wave waits
      // for the same channel-level gate instead of firing immediately.
      await waitForNextSubmission(0,job);
      batch: for(let round=1;round<=rounds;round++){
        for(const t of tasks){
          index++;
          try {
            const outcome=await runOneTask(job,t,round,index,totalRuns);
            if(outcome?.deferred)state.generationDeferred++;else state.generationSubmitted++;
          }
          catch(e){
            if(String(e?.message||e)==='TASK_REMOVED')continue;
            if(String(e?.message||e)==='COMMAND_CANCELLED'){paused=true;break batch;}
            if(isUncertainSubmissionError(e)){
              state.generationDeferred++;
              emit('generation_task_status',{host_id:t.host_id,recipient_id:t.recipient_id,segment_id:t.segment_id,state:'uncertain',message:'提交状态待后台确认；不会重复生成，后续任务继续',task_id:t.task_id,round});
            }else{
              state.generationFailed++;
              emit('generation_task_status',{host_id:t.host_id,recipient_id:t.recipient_id,segment_id:t.segment_id,state:'failed',message:String(e?.message||e),task_id:t.task_id,round,true_error:true});
            }
          }
          emit('generation_progress',{total:totalRuns,success:state.generationSubmitted,failed:state.generationFailed,deferred:state.generationDeferred,running:0,pending:Math.max(0,totalRuns-index)});
          if(index<totalRuns) await waitForNextSubmission(Date.now(),job);
        }
      }
      if (!paused && state.generationDeferred===0){
        state.generationRunning=false;
        retireCompletedWave(job,{total:totalRuns,success:state.generationSubmitted,failed:state.generationFailed,deferred:0},`批量提交结束：已确认 ${state.generationSubmitted} · 真正错误 ${state.generationFailed}`);
      }else if(!paused){
        emit('generation_batch_finished',{total:totalRuns,success:state.generationSubmitted,failed:state.generationFailed,deferred:state.generationDeferred});
        state.message=`批量提交结束：已确认 ${state.generationSubmitted} · 真正错误 ${state.generationFailed} · 待后台确认 ${state.generationDeferred} · 暂保留当前波次用于后台核对`;
      }
    } catch(error) {state.message='批次暂停：'+String(error.message||error);emit('generation_paused',{message:state.message});} finally {
      if(state.generationRunning)state.generationRunning=false;
      render();
      if(!paused && state.generationDeferred>0) requestNextWaveSoon();
    }
  }

  function maybeStartNativeGeneration() {
    const job=state.job;
    if(!job || !state.ready || !uploadBarrierReady() || !job.dispatch_tasks || !job.auto_execute || !job.command_id) return;
    queueMicrotask(()=>runNativeBatch(job));
  }

  function renderRows() {
    if (!state.tasks.length) return '<div class="fs-empty">等待本地 Studio 下发任务…</div>';
    return state.tasks.map(t=>`<div class="fs-row">
      <div class="fs-taskid">${esc(t.task_name||t.task_id)}</div>
      <div class="fs-ref"><span class="fs-dot ${t.matched?'ok':''}">${t.matched?'✓':'○'}</span><span>${esc(t.image||'未指定')}</span></div>
      <div class="fs-text">${esc(t.dialogue)}<br><small>${String(t.duration||8)+' 秒 · '+(t.generation_mode==='MATERIAL'?'素材':'帧')}</small></div>
      <div class="fs-text prompt">${esc(t.prompt)}</div>
      <div><span class="fs-pill ${isUploadSkippedName(t.image)?'fail':(t.matched?'ok':'wait')}">${isUploadSkippedName(t.image)?'上传失败已跳过':(t.matched?'已匹配':'待匹配')}</span></div>
    </div>`).join('');
  }

  function renderUploadFailures() {
    const exhausted=exhaustedUploadNames();
    const skipped=skippedUploadFullNames();
    const rowsByName=new Map();
    for(const row of uploadFailureHistoryRows())rowsByName.set(norm(row.name),{name:row.name,status:row.status||'上传失败'});
    for(const name of exhausted)rowsByName.set(norm(name),{name,status:'自动重试已用完'});
    for(const name of skipped)rowsByName.set(norm(name),{name,status:'已手动跳过'});
    const rows=[...rowsByName.values()];
    if(!rows.length)return '';
    return `<div class="fs-upload-failures"><div class="fs-upload-failures-head"><b>上传失败图片（完整文件名）</b><span>${rows.length} 张</span></div>${rows.map(r=>`<div class="fs-upload-failure-row"><code>${esc(r.name)}</code><span>${esc(r.status)}</span></div>`).join('')}</div>`;
  }

  function renderMedia() {
    if (!state.media.length) return '<div class="fs-empty media">当前还没有识别到本批任务对应的集合图片。</div>';
    return `<div class="fs-media-grid">${state.media.map(m=>{const u=m.url||state.thumbnailUrls.get(norm(m.name))||'';const src=safeMediaUrl(u);return `<div class="fs-media-card">${src?`<img data-fs-thumb="${esc(norm(m.name))}" src="${src}">`:`<div class="fs-media-placeholder" data-fs-name="${esc(norm(m.name))}">图片</div>`}<div>${esc(m.name)}</div><span>已识别</span></div>`}).join('')}</div>`;
  }

  function shell() {
    let root = $('#flow-studio-v050-root');
    if (!root) { root=document.createElement('div'); root.id='flow-studio-v050-root'; document.documentElement.appendChild(root); }
    return root;
  }

  function render() {
    const root = shell();
    const savedScroll = root.querySelector("#fs-panel")?.scrollTop || 0;
    const j = state.job || {};
    const total = state.tasks.length;
    const activeTotal = activeGenerationTasks().length;
    const imageTotal = expectedMediaTotal();
    const imageRecognized = recognizedMediaCount();
    const percent = imageTotal ? Math.round(imageRecognized/imageTotal*100) : 0;
    const missingCount = state.job ? missingImageNames().length : 0;
    const rounds=Math.max(1,Number(j.generation_count||1));
    const planned=activeTotal*rounds;
    const dc=state.downloadCounts;
    const generatedSuccess=(dc.ready||0)+(dc.downloading||0)+(dc.complete||0);
    const waitingGeneration=Math.max(0,planned-(state.generationSubmitted+state.generationFailed));
    const html = `
      <button id="fs-launcher" title="打开 Flow Studio 插件">F</button>
      <section id="fs-panel" class="${state.open?'':'fs-hidden'}">
        <header><div class="fs-brand"><span>F</span><div><b>Flow Studio 网页插件</b><small>v0.9.66 · Flow 提交命中检测修复 · 素材固定8秒</small></div></div><div class="fs-head-state ${state.connected?'on':'off'}">● ${state.connected?'本地 Studio 已连接':'本地 Studio 未连接'}</div><button id="fs-close">×</button></header>
        <div class="fs-bridge-config"><span>本地连接</span><code>127.0.0.1:</code><input id="fs-bridge-port" type="number" min="1024" max="65535" value="${esc(state.bridgePort)}"><button id="fs-save-port">保存端口并重连</button><small>需与 Flow Studio → Flow设置 → 本地 Bridge 端口一致</small></div>
        <div class="fs-summary">
          <div><span>AI 主播</span><b>${esc(j.host_name||'—')}</b></div>
          <div><span>生成方式</span><b>${state.tasks.length?(new Set(state.tasks.map(t=>t.generation_mode)).size>1?'帧 / 素材混合':(state.tasks[0].generation_mode==='MATERIAL'?'素材':'帧')):'—'}</b></div>
          <div><span>生成轮数</span><b>${esc(j.generation_count_label||j.generation_count||1)}</b></div>
          <div><span>任务数量</span><b>${activeTotal}${activeTotal!==total?` / 原 ${total}`:''}</b></div>
          <div><span>可用图片匹配</span><b>${recognizedMediaCount()} / ${expectedMediaTotal()}</b></div>
          <div><span>准备状态</span><b class="${state.ready?'ready':''}">${state.ready?'READY':(state.uploadInFlight?'UPLOADING':'WAITING')}</b></div>
        </div>
        <section class="fs-box">
          <div class="fs-box-head"><div><b>🖼 当前集合图片自动同步与匹配</b><p>每 2 秒读取 Flow 素材记录并按图片 ID 匹配；失败图片可手动跳过，已上传成功的任务优先继续生成。</p></div><div><button id="fs-upload" ${!state.job||state.ready||state.uploadInFlight?'disabled':''}>${missingCount?'拖拽上传缺失图片':'重新验证图片'}</button>${exhaustedUploadNames().length?`<button id="fs-skip-failed" class="danger">跳过失败图片并继续</button>`:''}<button id="fs-scan">立即扫描</button><button id="fs-sync" class="primary">重新同步 Studio</button></div></div>
          <div class="fs-progress"><span style="width:${percent}%"></span></div>
          <div class="fs-message">${esc(state.message)} <small>${state.lastSync?`· 最近扫描 ${state.lastSync}`:''} ${state.uploadAttempts?`· 上传尝试 ${state.uploadAttempts}`:''}</small></div>
          ${renderUploadFailures()}
          ${renderMedia()}
        </section>
        <section class="fs-box tasks">
          <div class="fs-box-head"><div><b>▣ Studio 任务映射 (${total})</b><button id="fs-export-download-log">导出完整运行日志</button><button id="fs-recover-generated">恢复已生成视频</button><p>任务来自本地 Studio；每 10 秒与本地端同步生成/失败/下载进度。${esc(state.downloadSummary)}</p></div><div><button id="fs-pause-all" class="${state.generationPaused?'primary':''}">${state.generationPaused?'▶ 继续全部':'⏸ 暂停全部'}</button></div></div>
          <div class="fs-status-strip"><span>生成成功 <b>${generatedSuccess}</b></span><span>真正错误 <b>${dc.failed||state.generationFailed}</b></span><span>待确认 <b>${state.generationDeferred||0}</b></span><span>生成中 <b>${dc.waiting||0}</b></span><span>等待生成 <b>${waitingGeneration}</b></span><span>成功下载 <b>${dc.complete||0}</b></span></div>
          <div class="fs-table-head"><div>任务</div><div>参考图</div><div>人物文案</div><div>最终 Flow 提示词</div><div>状态</div></div>
          <div class="fs-rows">${renderRows()}</div>
        </section>
        <footer><div>当前集合：${esc(location.pathname)}</div><div><button id="fs-rescan">重新匹配图片</button></div></footer>
      </section>`;
    if(root.__flowLastHTML===html)return;
    root.__flowLastHTML=html;
    root.innerHTML=html;
    const panel=root.querySelector('#fs-panel');
    if(panel){panel.scrollTop=savedScroll;panel.addEventListener('wheel',event=>event.stopPropagation(),{passive:true});}
    bind();
    queueMicrotask(hydrateThumbnails);
  }

  async function recoverGeneratedVideo(){
    try{
      const job=state.job;if(!job?.command_id)throw Error('请先回到对应通道集合');
      const pending=await downloadMessage({type:'FS_DOWNLOAD_PENDING',command_id:job.command_id});
      if(pending.length!==1)throw Error('需要恰好一个待绑定任务，当前 '+pending.length+' 个；请导出日志核对');
      const entry=pending[0],t=state.tasks.find(t=>String(t.segment_id)===String(entry.info.segment_id));
      if(!t)throw Error('原任务已变化，停止恢复');
      const text=window.prompt('恢复任务 '+(t.task_name||t.task_id)+'：请粘贴该视频详情页网址（/edit/…）。请先核对视频详情的提示词。此操作只绑定和下载，不重新生成。');
      if(!text)return;
      const url=new URL(text),collection=new URL(location.href);
      const match=url.pathname.match(/^\/project\/([^/]+)\/edit\/([0-9a-f-]{36})$/i);
      if(url.origin!==collection.origin||!match||!collection.pathname.startsWith('/project/'+match[1]+'/collection/'))throw Error('必须使用当前项目的视频详情网址');
      const result=await submitViaMainWorld({action:'recover_video_identity',prompt:finalPromptForTask(t),video_id:match[2],recovery_key:entry.key},10000);
      if(result.ids?.length!==1)throw Error('视频记录与完整提示词未能唯一对应，未绑定；请导出日志');
      if(state.job?.command_id!==job.command_id)throw Error('当前任务已切换，未绑定');
      const owned=await new Promise((resolve,reject)=>{
        const timer=setTimeout(()=>reject(Error('任务归属核对超时，未绑定')),15000);
        chrome.runtime.sendMessage({type:'FS_CLAIM_COMMAND',command_id:job.command_id,segment_id:t.segment_id},r=>{clearTimeout(timer);const error=chrome.runtime.lastError;if(error||!r?.ok)reject(Error('无法核对任务归属'));else resolve(r.owned);});
      });
      if(!owned)throw Error('原任务已取消或转移，未绑定');
      await downloadMessage({type:'FS_DOWNLOAD_BIND',key:entry.key,ids:result.ids});
      await markTaskConfirmed(job,t,entry.info.round||1,result.ids);
      emit('generation_task_status',{host_id:t.host_id,recipient_id:t.recipient_id,segment_id:t.segment_id,round:entry.info.round||1,state:'success',generation_ids:result.ids,message:'已恢复原视频绑定，等待自动下载'});
      const scan=await submitViaMainWorld({action:'scan_video_results',ids:result.ids},10000);
      await downloadMessage({type:'FS_DOWNLOAD_OBSERVE',rows:scan.rows||[],diagnostics:scan.diagnostics});
      state.message='已恢复原视频绑定；未重新生成。';render();
    }catch(error){state.message='恢复未完成：'+String(error.message||error);render();}
  }
  async function exportDownloadDiagnostics(){
    try {
      try{const scan=await submitViaMainWorld({action:'scan_video_results',ids:[]},10000);await downloadMessage({type:'FS_DOWNLOAD_OBSERVE',rows:[],diagnostics:scan.diagnostics});}catch(_){}
      const report=await downloadMessage({type:'FS_DOWNLOAD_DIAGNOSTICS'});
      const runtime=await new Promise(resolve=>chrome.runtime.sendMessage({type:'FS_PLUGIN_DIAGNOSTICS'},r=>resolve(r?.ok?r.result:{error:r?.error||chrome.runtime.lastError?.message||'读取失败'})));
      report.runtime=runtime;
      report.panel={channel:state.job?.channel_key||'',command_id:state.job?.command_id||'',tasks:state.tasks.map(t=>({task_id:t.task_id,task_name:t.task_name,host_id:t.host_id,dispatch_order:t.dispatch_order,matched:t.matched,upload_skipped:isUploadSkippedName(t.image)})),skipped_upload_failed:skippedUploadFullNames(),message:state.message,downloadSummary:state.downloadSummary};
      const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download='FlowStudio-download-diagnostics.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
    }catch(error){state.downloadSummary='导出失败：'+String(error.message||error);render();}
  }
  function bind() {
    $('#fs-recover-generated')?.addEventListener('click',recoverGeneratedVideo);
    $('#fs-export-download-log')?.addEventListener('click',exportDownloadDiagnostics);
    $('#fs-pause-all')?.addEventListener('click',()=>setPausedFromPlugin(!state.generationPaused).catch(error=>{state.message='暂停/继续失败：'+String(error.message||error);render();}));
    $('#fs-launcher')?.addEventListener('click',()=>{state.open=true;render();});
    $('#fs-close')?.addEventListener('click',()=>{state.open=false;render();});
    $('#fs-skip-failed')?.addEventListener('click',skipFailedUploadsAndContinue);
    $('#fs-upload')?.addEventListener('click',()=>{const missing=missingImageNames();if(missing.length)uploadMissing(false);else{state.ready=false;state.stableHits=0;state.message='正在重新验证已上传图片与任务映射…';startScanner();render();}});
    $('#fs-scan')?.addEventListener('click',scanOnce);
    $('#fs-rescan')?.addEventListener('click',()=>{state.ready=false;state.stableHits=0;startScanner();render();});
    $('#fs-sync')?.addEventListener('click',()=>chrome.runtime.sendMessage({type:'FS_FORCE_SYNC'},()=>pullJob()));
    $('#fs-save-port')?.addEventListener('click',()=>{
      const n=Number($('#fs-bridge-port')?.value||0);
      chrome.runtime.sendMessage({type:'FS_SET_BRIDGE_PORT',port:n},res=>{
        if(res?.ok){state.bridgePort=Number(res.port||n);state.message=res.connected?'端口已保存，本地 Studio 已重新连接':'端口已保存，正在等待本地 Studio';}
        else state.message='端口保存失败：'+String(res?.error||chrome.runtime.lastError?.message||'未知错误');
        render();
      });
    });
  }

  // MAIN-world Flow hooks publish a result as soon as Flow exposes it.
  // The background registry performs the exact ID check and ordered download.


  chrome.runtime.onMessage.addListener(msg=>{
    if (msg?.type==='FS_STUDIO_CONNECTION') { state.connected=!!msg.connected; render(); }
    if (msg?.type==='FS_STUDIO_JOBS_CHANGED') {pullJob();}
  });

  chrome.runtime.sendMessage({type:'FS_GET_BRIDGE_PORT'},res=>{if(res?.ok){state.bridgePort=Number(res.port||17831);render();}});
  pullJob();
  chrome.runtime.sendMessage({type:'FS_GET_CONTROL'},res=>{if(res?.ok){state.generationPaused=!!res.paused;render();}});
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){signalBackgroundWake();void pullJob();}});
  document.addEventListener('resume',()=>{signalBackgroundWake();void pullJob();});
  window.addEventListener('pageshow',()=>{signalBackgroundWake();void pullJob();});
  setInterval(pullJob, 3000);
  window.addEventListener('pagehide',clearThumbnailCache);
})();
