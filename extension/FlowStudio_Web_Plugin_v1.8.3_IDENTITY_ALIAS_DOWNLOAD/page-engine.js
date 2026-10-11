/* Flow Studio native adapter. Reconstructed from the supplied v1.0.6 runtime,
   without its UI, downloads, account code or third-party dependencies. */
(() => {
  'use strict';
  if (window.__FLOW_STUDIO_NATIVE_V090__) return;
  window.__FLOW_STUDIO_NATIVE_V090__ = true;
  
  // v0.9.61 incremental: keep Flow execution progressing when its window/tab is hidden.
  // Hidden Chrome pages throttle chained timers heavily; arm hidden waits from a
  // MessageChannel task so the timer chain does not escalate into minute-level throttling.
  // A shared, plugin-specific Web Lock also keeps an active Flow worker page out of
  // Chrome Energy Saver freezing while this page is loaded. Foreground timing is unchanged.
  const backgroundSleepWaiters=new Set();
  function signalBackgroundWake(){
    const now=Date.now();
    for(const waiter of [...backgroundSleepWaiters])if(waiter.deadline<=now)waiter.finish();
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
      const arm=()=>{
        if(settled)return;
        const remaining=Math.max(0,waiter.deadline-Date.now());
        timer=setTimeout(waiter.finish,remaining);
      };
      if(document.visibilityState==='hidden' && typeof MessageChannel!=='undefined'){
        try{channel=new MessageChannel();channel.port1.onmessage=arm;channel.port2.postMessage(0);}catch(_){arm();}
      }else arm();
    });
  }
  window.addEventListener('FLOW_STUDIO_BACKGROUND_WAKE',signalBackgroundWake);
  try{
    if(navigator.locks?.request){
      const lockName='__flowstudio_background_guard_'+location.pathname.replace(/[^a-z0-9_-]+/gi,'_');
      navigator.locks.request(lockName,{mode:'shared'},()=>new Promise(()=>{})).catch(()=>{});
    }
  }catch(_){}
  const source = fn => Function.prototype.toString.call(fn);
  const normal = value => {const text=String(value||'').normalize('NFC').trim().toLowerCase();const hash=text.match(/-([a-f0-9]{16})\.(?:png|jpe?g|webp)$/);return hash?'image-hash:'+hash[1]:text;};
  let page = null, busy = false, pending = null;
  const submissionDiagnostics=[];
  let resourceObserver=null;
  const ticketKey=key=>'flowStudioPending935:'+location.pathname+':'+key;
  // v0.9.64: recovery bookkeeping must never be allowed to abort a real Flow submission.
  // Old pending records can accumulate in sessionStorage until Chromium rejects setItem().
  // Keep only this tab/path's newest recovery record, retry once, then continue without the
  // recovery marker if storage is still unavailable. Generation itself remains authoritative.
  const pendingStoragePrefix='flowStudioPending935:';
  function safeRecoveryRead(key){
    try{return sessionStorage.getItem(ticketKey(key));}catch(error){
      console.warn('[FlowStudio][RECOVERY_STORAGE_READ_FAILED]',String(error?.message||error));return null;
    }
  }
  function cleanupOldRecoveryRecords(keepFullKey=''){
    try{
      const remove=[];
      for(let i=0;i<sessionStorage.length;i++){
        const k=sessionStorage.key(i);
        if(k && k.startsWith(pendingStoragePrefix) && k!==keepFullKey)remove.push(k);
      }
      for(const k of remove)sessionStorage.removeItem(k);
      if(remove.length)console.info('[FlowStudio][RECOVERY_STORAGE_CLEANUP]',{removed:remove.length});
      return remove.length;
    }catch(error){console.warn('[FlowStudio][RECOVERY_STORAGE_CLEANUP_FAILED]',String(error?.message||error));return 0;}
  }
  function safeRecoveryWrite(key,value){
    if(!key)return false;
    const full=ticketKey(key),payload=JSON.stringify(value);
    try{sessionStorage.setItem(full,payload);return true;}catch(firstError){
      console.warn('[FlowStudio][RECOVERY_STORAGE_QUOTA]',String(firstError?.message||firstError));
      cleanupOldRecoveryRecords(full);
      try{sessionStorage.setItem(full,payload);return true;}catch(secondError){
        // Critical behavior: failure to persist an anti-duplicate recovery marker is a warning,
        // not a generation failure. Existing request-observation gates still prevent false success.
        console.warn('[FlowStudio][RECOVERY_STORAGE_BYPASSED]',String(secondError?.message||secondError));
        return false;
      }
    }
  }
  function safeRecoveryRemove(key){
    if(!key)return;
    try{sessionStorage.removeItem(ticketKey(key));}catch(error){console.warn('[FlowStudio][RECOVERY_STORAGE_REMOVE_FAILED]',String(error?.message||error));}
  }
  const wrapped = new WeakMap();
  const exportName = 'default_AiSandboxAngularFrontend';
  function wrap(value) {
    if (typeof value !== 'function') return value;
    const text = source(value);
    if (!text.startsWith('class') || !text.includes('("pageContainer"') || !text.includes('("tilesContainer"')) return value;
    if (!wrapped.has(value)) wrapped.set(value, class extends value {
      constructor(...args) { super(...args); page = this; }
    });
    return wrapped.get(value);
  }
  // The legacy transformer captures the same Angular page class at export time.
  const exports = window[exportName] || {};
  for (const key of Reflect.ownKeys(exports)) {
    const desc = Object.getOwnPropertyDescriptor(exports,key);
    if (desc?.writable && typeof desc.value === 'function') exports[key] = wrap(desc.value);
  }
  window[exportName] = new Proxy(exports, {
    set(target, key, value, receiver) { return Reflect.set(target,key,wrap(value),receiver); },
    defineProperty(target,key,desc) {
      if ('value' in desc) desc = {...desc,value:wrap(desc.value)};
      return Reflect.defineProperty(target,key,desc);
    }
  });
  function context() {
    const instance = page || window.pageInstance;
    if (!instance) throw new Error('FLOW_RUNTIME_NOT_READY：请刷新 Flow 页面后重试');
    const service = Object.values(instance).find(v => v && typeof v === 'object' && 'firstFrame' in v && 'aspectRatio' in v);
    if (!service) throw new Error('FLOW_COMPOSER_SERVICE_NOT_FOUND：Flow 页面内部结构不兼容');
    return {instance,service};
  }
  function signal(service,predicate) {
    for (const v of Object.values(service)) if (typeof v === 'function' && typeof v.set === 'function' && typeof v.update === 'function') {
      try { if (predicate(v())) return v; } catch (_) {}
    }
    throw new Error('FLOW_SIGNAL_NOT_FOUND');
  }
  function constructorSignal(service,regex,label) {
    const key = source(service.constructor).match(regex)?.[1];
    const result = key && service[key];
    if (typeof result !== 'function' || typeof result.set !== 'function') throw new Error('FLOW_SETTING_NOT_FOUND:'+label);
    return result;
  }
  function mediaList(instance) {
    // Legacy V66: the assignment immediately before `filters` in the base constructor.
    const text = source(Object.getPrototypeOf(instance.constructor));
    const at = text.indexOf('filters'), assignments = [...text.matchAll(/this\.(\w+)=/g)];
    const after = assignments.findIndex(m => m.index > at);
    if (at < 0 || after < 1) throw new Error('FLOW_MEDIA_STORE_NOT_FOUND');
    const getter = instance[assignments[after-1][1]];
    if (typeof getter !== 'function') throw new Error('FLOW_MEDIA_STORE_NOT_FOUND');
    const items = getter.call(instance);
    if (!Array.isArray(items)) throw new Error('FLOW_MEDIA_STORE_INVALID');
    return items;
  }
  function mediaURL(item) {
    if (typeof item.url === 'string') return item.url;
    for (const v of Object.values(item)) if (v && typeof v === 'object') {
      const url = Object.values(v).find(s => typeof s === 'string' && s.startsWith('https://'));
      if (url) return url;
    }
    return '';
  }
  function scan() {
    const {instance} = context();
    return mediaList(instance).filter(x => x.type === 'IMAGE').map(x => {
      const flags=flowAssetFlags(x),url=mediaURL(x);
      // Do not treat a freshly-created upload placeholder as a usable Flow image.
      // upload_ready is only true after Flow no longer reports uploading/pending/error
      // and exposes either a real preview URL or an explicit completed/ready state.
      // A formal IMAGE row with a stable Flow id is already real catalog evidence.
      // Some Flow builds do not expose preview URL / explicit READY until a page refresh,
      // which previously left the plugin stuck at 0/N even though the image was present.
      // Explicit loading/pending/error still blocks submission, so fresh placeholders cannot pass.
      const formalAsset=String(x.id||'').trim().length>=8 && !!String(x.displayName||'').trim();
      const uploadReady=!flags.loading && !flags.error && (!!url || !!flags.ready || formalAsset);
      return {id:x.id,name:x.displayName,url,upload_ready:uploadReady,uploading:!!flags.loading,upload_error:!!flags.error,upload_status_ready:!!flags.ready};
    });
  }
  function selectMethod(instance) {
    let proto = instance;
    while (proto && proto !== Object.prototype) {
      for (const key of Reflect.ownKeys(proto)) {
        const fn = Object.getOwnPropertyDescriptor(proto,key)?.value;
        if (typeof fn !== 'function' || key === 'constructor') continue;
        const text = source(fn);
        if (['VIDEO_FRAMES','VIDEO_REFERENCES','VIDEO_TILE_REFERENCE'].every(s => text.includes(s))) return fn.bind(instance);
      }
      proto = Object.getPrototypeOf(proto);
    }
    throw new Error('FLOW_IMAGE_SELECTION_METHOD_NOT_FOUND');
  }
  const modes = ['VIDEO_EXTEND','VIDEO_FRAMES','VIDEO_REFERENCES','IMAGE','IMAGE_EDIT'];
  const models = ['abra','veo_3_1_lite','veo_3_1_fast','veo_3_1_quality','veo_3_1_lite_low_priority','nano','banana2'];
  function aspectValue(value) {
    const text=String(value??'9:16').trim().toUpperCase().replace(/\s/g,'').replace('：',':');
    if (['9:16','PORTRAIT','VERTICAL','竖版','竖屏','VIDEO_ASPECT_RATIO_PORTRAIT'].includes(text)) return 'PORTRAIT';
    if (['16:9','LANDSCAPE','HORIZONTAL','横版','横屏','VIDEO_ASPECT_RATIO_LANDSCAPE'].includes(text)) return 'LANDSCAPE';
    if (['1:1','SQUARE'].includes(text)) return 'SQUARE';
    throw new Error('UNSUPPORTED_ASPECT_RATIO:'+value);
  }
  async function verifySettings(service,detail) {
    const expected=aspectValue(detail.aspect_ratio);
    // Selecting a reference can reset the ratio. Apply after attachment too.
    service.setAspectRatio(expected);
    const until=Date.now()+2000;
    let actual;
    do {
      actual=typeof service.aspectRatio==='function'?service.aspectRatio():service.aspectRatio;
      try { if (aspectValue(actual)===expected && actual!=null) break; } catch (_) {}
      await sleep(100);
    } while (Date.now()<until);
    let normalized;try { normalized=actual==null?null:aspectValue(actual); } catch (_) {}
    if (normalized!==expected) throw new Error('FLOW_ASPECT_NOT_CONFIRMED:expected='+expected+';actual='+String(actual));
    const model=detail.resolved_model || detail.model || 'veo_3_1_lite_low_priority';
    if ((detail._modelSignal||signal(service,v=>(models.includes(v)||(typeof v==='string'&&/omni/i.test(v)))))()!==model) throw new Error('FLOW_MODEL_NOT_CONFIRMED');
    const materialMode=false;
    const effectiveDuration=materialMode?8:Number(detail.duration||8);
    // MATERIAL / VIDEO_REFERENCES is fixed by Flow at 8s. Flow may keep the last
    // FRAME duration in its hidden signal even though MATERIAL exposes no duration picker.
    // Force the hidden duration signal to 8 and verify it after asset selection; never use
    // the FRAME duration picker in MATERIAL mode.
    const durationSignal=constructorSignal(service,/this\.(\w+)=[^;]+8\);/,'duration');
    if (materialMode && Number(durationSignal())!==8) durationSignal.set(8);
    if (Number(durationSignal())!==effectiveDuration) throw new Error('FLOW_DURATION_NOT_CONFIRMED:expected='+effectiveDuration+';actual='+String(durationSignal()));
    return {aspect_ratio:expected,model,duration:effectiveDuration,duration_policy:materialMode?'FLOW_FIXED_8S':'SELECTABLE'};
  }
  async function chooseOmni(service) {
    const modelSignal=signal(service,v=>(models.includes(v)||(typeof v==='string'&&/omni/i.test(v))));
    const root=composerContext()?.root;
    if(!root)throw Error('OMNI_MODEL_PICKER_NOT_FOUND');
    const name=el=>String(el.innerText||el.getAttribute('aria-label')||'').trim();
    const controls=[...root.querySelectorAll('button,[role="combobox"]')].filter(el=>renderedNode(el)&&/veo|omni/i.test(name(el)));
    if(controls.length!==1)throw Error('请先在 Flow 网页选择 Omni 模型，再重试');
    if(/omni/i.test(name(controls[0]))&&!/draft|360p/i.test(name(controls[0])))return modelSignal;
    controls[0].click();await sleep(250);
    const choices=[...document.querySelectorAll('[role="option"],[role="menuitem"]')].filter(el=>renderedNode(el)&&/omni/i.test(name(el))&&!/draft|360p/i.test(name(el)));
    if(choices.length!==1)throw Error('网页中未找到唯一可用的 Omni 模型，请在 Flow 选择后重试');
    const prior=modelSignal();choices[0].click();
    const deadline=Date.now()+3000;
    while(modelSignal()===prior&&Date.now()<deadline)await sleep(100);
    if(modelSignal()===prior)throw Error('OMNI_MODEL_NOT_CONFIRMED');
    if(!models.includes(modelSignal()))models.push(modelSignal());
    return modelSignal;
  }
  async function configure(service,detail) {
    const mode = detail.mode || 'VIDEO_FRAMES';
    if (!['VIDEO_FRAMES','VIDEO_REFERENCES'].includes(mode)) throw new Error('UNSUPPORTED_MODE:'+mode);
    signal(service,v => modes.includes(v)).set(mode);
    let model = detail.model || 'veo_3_1_lite_low_priority';
    if(model==='flow_omni'){detail._modelSignal=await chooseOmni(service);model=detail._modelSignal();detail.resolved_model=model;}
    if (!detail._modelSignal && !models.includes(model)) throw new Error('UNSUPPORTED_MODEL:'+model);
    if (typeof service.setAspectRatio !== 'function') throw new Error('FLOW_ASPECT_METHOD_NOT_FOUND');
    service.setAspectRatio(aspectValue(detail.aspect_ratio));
    (detail._modelSignal||signal(service,v => (models.includes(v)||(typeof v==='string'&&/omni/i.test(v))))).set(model);
    constructorSignal(service,/this\.(\w+)=[^;]+1\);/,'outputs').set(1);
    // MATERIAL has no visible duration picker but Flow can retain the previous FRAME
    // duration internally. Set the same hidden duration signal to 8 before attaching the
    // reference asset. FRAME behavior is unchanged and still uses the requested 4/6/8s.
    const durationSignal=constructorSignal(service,/this\.(\w+)=[^;]+8\);/,'duration');
    durationSignal.set(mode==='VIDEO_REFERENCES' ? 8 : Number(detail.duration || 8));
  }
  function stateSnapshot(service) {
    const result=new Map();
    for (const [key,value] of Object.entries(service)) {
      // Only read writable Angular signals, not arbitrary service methods.
      if (typeof value !== 'function' || typeof value.set !== 'function' || typeof value.update !== 'function') continue;
      try {
        const data=value();
        if (data && typeof data === 'object') {
          const serialized=JSON.stringify(data);
          if (serialized && serialized.length<200000) result.set(key,{data:JSON.parse(serialized),serialized});
        }
      } catch (_) {}
    }
    return result;
  }
  function hasTarget(value,identities,depth=0) {
    if (depth>8 || value==null) return false;
    if (typeof value==='string' || typeof value==='number') return identities.has(value);
    if (Array.isArray(value)) return value.some(v=>hasTarget(v,identities,depth+1));
    if (typeof value==='object') return Object.values(value).some(v=>hasTarget(v,identities,depth+1));
    return false;
  }
  function attachmentIdentities(item,catalog) {
    const ids=new Set([item.id]);
    // Only identifier-shaped aliases. Numbers, ratios and timestamps are not image identity.
    for(const [key,value] of Object.entries(item)){
      if(typeof value!=='string'||value===item.displayName||/^(type|mediaType|aspectRatio|status|displayName)$/i.test(key))continue;
      if(!/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(value) && !(/(?:^id$|Id$|_id$)/.test(key)&&value.length>=8))continue;
      if(!catalog.some(other=>other!==item&&Object.values(other).includes(value)))ids.add(value);
    }
    ids.delete(undefined);ids.delete('');return ids;
  }
  function retainedReference(snapshot,ids) {
    for (const [key,value] of snapshot) {
      const list=value.data;
      // Actual reported composer records: id, <minified>, mediaType,
      // aspectRatio, <minified>... Catalog rows have type/displayName instead.
      if (Array.isArray(list) && list.length===1) {
        const row=list[0];
        if (row && ids.has(row.id) && 'mediaType' in row && 'aspectRatio' in row && !('displayName' in row)) return key;
      }
    }
    return null;
  }
  function selectedEvidence(before,after,ids) {
    for (const [key,current] of after) {
      const prior=before.get(key);
      // A pre-existing library list is not proof of selecting a reference.
      if (prior?.serialized===current.serialized || (prior && hasTarget(prior.data,ids))) continue;
      if (hasTarget(current.data,ids)) return key;
    }
    return null;
  }
  function stateShapes(snapshot) {
    return [...snapshot.entries()].slice(0,12).map(([key,v])=>({key,kind:Array.isArray(v.data)?'array':'object',size:Array.isArray(v.data)?v.data.length:Object.keys(v.data).length,fields:Array.isArray(v.data)?Object.keys(v.data[0]||{}).slice(0,6):Object.keys(v.data).slice(0,6)}));
  }
  function firstFrameMatches(service, ids) {
    try { const frame=typeof service.firstFrame==='function' ? service.firstFrame() : service.firstFrame;
      return hasTarget(frame,ids);
    } catch (_) { return false; }
  }
  function editorSignal(service) {
    return signal(service,v => v && typeof v === 'object' && Object.values(v).length === 1 && Array.isArray(Object.values(v)[0]));
  }

  function flowAssetFlags(value,depth=0,state={loading:false,error:false,ready:false}) {
    if(value==null||depth>4)return state;
    if(Array.isArray(value)){for(const v of value)flowAssetFlags(v,depth+1,state);return state;}
    if(typeof value!=='object')return state;
    for(const [k,v] of Object.entries(value)){
      const key=String(k).toLowerCase();
      if(/(?:isloading|loading|uploading|isuploading|pendingupload)/.test(key) && v===true)state.loading=true;
      if(/(?:error|failed|failure|uploaderror)/.test(key) && (v===true || (typeof v==='string'&&v.trim())))state.error=true;
      if(typeof v==='string' && /(?:status|state|phase|uploadstatus|mediastatus|operationstatus)/.test(key)){
        const status=v.trim().toLowerCase();
        if(/(?:uploading|pending|processing|queued|creating|in[_ -]?progress|loading)/.test(status))state.loading=true;
        if(/(?:error|failed|failure|cancelled|canceled)/.test(status))state.error=true;
        if(/(?:ready|complete|completed|success|succeeded|done)/.test(status))state.ready=true;
      }
      if(v&&typeof v==='object')flowAssetFlags(v,depth+1,state);
    }
    return state;
  }
  async function waitExistingFlowImageAssetReady(instance,item,timeout=15000) {
    const id=String(item?.id||''),name=normal(item?.displayName||'');
    let last=null,lastFlags=null,reboundLogged=false;
    const until=Date.now()+timeout;
    while(Date.now()<until){
      const catalog=mediaList(instance);
      const sameName=catalog.filter(x=>x?.type==='IMAGE' && normal(x.displayName)===name);
      const exact=id?sameName.find(x=>String(x.id||'')===id):null;
      // Flow may replace the short-lived upload placeholder with a final IMAGE row.
      // Its displayName stays the same while its internal id changes. When the name is
      // unique, rebind to that final row instead of falsely reporting that the image vanished.
      const row=exact || (sameName.length===1?sameName[0]:null);
      if(row){
        last=row;
        if(id && String(row.id||'')!==id && !reboundLogged){
          reboundLogged=true;
          console.info('[FlowStudio][IMAGE_ID_REBOUND_BY_NAME]',{name:String(row.displayName||item?.displayName||''),previous_id:id,current_id:String(row.id||'')});
        }
        const flags=flowAssetFlags(row);lastFlags=flags;
        if(flags.error)throw new Error('FLOW_IMAGE_ASSET_ERROR:'+String(row.displayName||item?.displayName||id));
        // One real, non-loading formal asset is sufficient. Background timer
        // throttling must not turn repeated identical reads into a readiness gate.
        if(!flags.loading && (mediaURL(row) || String(row.id||'').length>=8))return row;
      }
      await sleep(180);
    }
    // Do not convert an otherwise stable formal IMAGE asset into a hard failure just because
    // Flow's current build hides its preview URL. Explicit loading/error is still respected.
    if(last && !lastFlags?.loading && !lastFlags?.error && String(last.id||'').length>=8)return last;
    throw new Error('FLOW_IMAGE_ASSET_NOT_READY:'+String(last?.displayName||item?.displayName||id));
  }

  async function settleMaterialModeForSelect(service,detail) {
    const modeSignal=signal(service,v=>modes.includes(v));
    // Request the mode once; observation is diagnostic, never a pre-submit gate.
    modeSignal.set('VIDEO_REFERENCES');
    let observed=false;
    return {observed,attempt:1};
  }
  function freshRetainedReference(before,after,ids) {
    const key=retainedReference(after,ids);
    if(!key)return null;
    const prior=before.get(key);
    // A reference that already existed before this select() attempt is stale and cannot
    // prove that the current task was attached. MATERIAL must create/change the active
    // reference state in this attempt, exactly like FRAME changes firstFrame.
    if(prior && hasTarget(prior.data,ids))return null;
    return key;
  }
  async function selectMaterialAssetLikeFrame({service,select,item,targetIdentities,editor,key,detail}) {
    // v0.9.60: MATERIAL mode confirmation is intentionally non-blocking.
    // We still request VIDEO_REFERENCES before selecting the already-uploaded Flow asset,
    // but Flow is allowed to mutate/alias its internal mode after select(item). That internal
    // transition must never turn an otherwise valid native asset selection into a task failure.
    const modePrep=await settleMaterialModeForSelect(service,detail);
    const before=stateSnapshot(service);
    const beforeEditor=JSON.stringify(editor()?.[key]||[]);
    await select(item);
    const after=stateSnapshot(service);
    const editorBlocks=editor()?.[key];
    const editorChanged=JSON.stringify(editorBlocks||[])!==beforeEditor;
    const selectedKey=selectedEvidence(before,after,targetIdentities)
      || retainedReference(after,targetIdentities)
      || (editorChanged && hasTarget(editorBlocks,targetIdentities)?'editorAttachment':null)
      || 'flowNativeAssetSelect';
    return {selectedKey,beforeSelection:before,lastSnapshot:after,attempt:modePrep.attempt,mode_pre_observed:modePrep.observed,verified:selectedKey!=='flowNativeAssetSelect'};
  }

  function referenceRecordIds(value,out=new Set(),depth=0) {
    if(value==null||depth>8)return out;
    if(Array.isArray(value)){for(const v of value)referenceRecordIds(v,out,depth+1);return out;}
    if(typeof value!=='object')return out;
    const mt=String(value.mediaType||value.type||value.kind||'').toUpperCase();
    const id=typeof value.id==='string'?value.id:(typeof value.mediaId==='string'?value.mediaId:'');
    // Flow's active reference records are small IMAGE objects and generally do not carry displayName.
    // Catalog/library rows do carry displayName and are deliberately excluded here.
    if(id && /IMAGE/.test(mt) && !('displayName' in value)){
      out.add(id);identifierStrings(value,out);
    }
    for(const child of Object.values(value))referenceRecordIds(child,out,depth+1);
    return out;
  }
  function requestBodyObject(value,depth=0) {
    if (depth>10 || value==null) return value;
    try {
      if (typeof URLSearchParams!=='undefined' && value instanceof URLSearchParams) {
        const out={};
        for(const [k,v] of value.entries()) out[k]=requestBodyObject(v,depth+1);
        return out;
      }
      if (typeof FormData!=='undefined' && value instanceof FormData) {
        const out={};
        for(const [k,v] of value.entries()) out[k]=typeof v==='string'?requestBodyObject(v,depth+1):{name:v?.name||'',type:v?.type||''};
        return out;
      }
      if(value instanceof ArrayBuffer) return requestBodyObject(new TextDecoder().decode(new Uint8Array(value)),depth+1);
      if(ArrayBuffer.isView(value)) return requestBodyObject(new TextDecoder().decode(new Uint8Array(value.buffer,value.byteOffset,value.byteLength)),depth+1);
    } catch (_) {}
    if (typeof value==='string') {
      let text=value.replace(/^\)\]\}'\s*/, '').replace(/^for\s*\(\s*;;\s*\);/,'').trim();
      if(!text) return '';
      try { return requestBodyObject(JSON.parse(text),depth+1); } catch (_) {}
      // Flow often wraps batchexecute payloads inside application/x-www-form-urlencoded
      // (notably f.req). Decode every value and recurse instead of scanning the raw string.
      if(depth===0 && /(?:^|&)(?:f\.req|rpcids|at)=/i.test(text)) {
        try {
          const params=new URLSearchParams(text);
          const entries=[...params.entries()];
          if(entries.length){
            const out={};
            for(const [k,v] of entries) out[k]=requestBodyObject(v,depth+1);
            return out;
          }
        } catch (_) {}
      }
      // Some nested f.req values are URI encoded one extra time.
      if(/%5B|%7B|%22|%3A/i.test(text)) {
        try { const decoded=decodeURIComponent(text.replace(/\+/g,' ')); if(decoded!==text)return requestBodyObject(decoded,depth+1); } catch (_) {}
      }
      const lines=text.split('\n').map(s=>s.trim()).filter(s=>s.startsWith('[')||s.startsWith('{'));
      if(lines.length && !(lines.length===1 && lines[0]===text)) return lines.map(s=>requestBodyObject(s,depth+1));
      return value;
    }
    if (Array.isArray(value)) return value.map(v=>requestBodyObject(v,depth+1));
    if (value && typeof value==='object') return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,requestBodyObject(v,depth+1)]));
    return value;
  }
  const decodeBody=requestBodyObject;
  function idsFrom(body) {
    const ids=new Set();
    function visit(v,depth=0) {
      if (!v || typeof v!=='object' || depth>12) return;
      for (const [key,value] of Object.entries(v)) {
        if (['media','operations'].includes(key) && Array.isArray(value)) for(const row of value) {
          const id=row?.name || row?.id || row?.operation?.name;
          if (typeof id==='string' && id) ids.add(id);
        }
        visit(value,depth+1);
      }
    }
    visit(requestBodyObject(body)); return [...ids];
  }
  function containsPrompt(body,prompt) {
    if (!body || !prompt) return false;
    const needle=String(prompt);
    const escaped=JSON.stringify(needle).slice(1,-1);
    const seen=new Set();
    function visit(v,depth=0){
      if(v==null||depth>12)return false;
      if(typeof v==='string')return v.includes(needle)||v.includes(escaped);
      if(typeof v!=='object'||seen.has(v))return false;
      seen.add(v);
      if(Array.isArray(v))return v.some(x=>visit(x,depth+1));
      return Object.entries(v).some(([k,x])=>String(k).includes(needle)||visit(x,depth+1));
    }
    return visit(requestBodyObject(body));
  }
  function generationRequest(url,body,ticket) {
    if (!ticket) return false;
    try { if(typeof location!=='undefined') url=new URL(url,location.href).href; } catch (_) {}
    if (/video[^/?]*:.*(?:generate|extend)|batchAsyncGenerateVideo|generateVideo/i.test(url)) return true;
    return /(?:flow\.google\.com|labs\.google|googleapis\.com)/i.test(url) && containsPrompt(body,ticket.prompt);
  }
  function bodyFragments(value,depth=0,out=[]) {
    if(depth>9 || value==null)return out;
    const decoded=depth===0?requestBodyObject(value):value;
    if(decoded!==value)return bodyFragments(decoded,depth+1,out);
    if(typeof value==='string'){out.push(value);return out;}
    if(Array.isArray(value)){for(const v of value)bodyFragments(v,depth+1,out);return out;}
    if(typeof value==='object'){
      for(const [k,v] of Object.entries(value)){out.push(String(k));bodyFragments(v,depth+1,out);}
    }
    return out;
  }
  function identifierStrings(value,out=new Set(),depth=0) {
    if(value==null||depth>7)return out;
    if(typeof value==='string'){
      if(/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(value)||/^(?:media|asset|image|ref)[\/:_-][A-Za-z0-9._:-]{6,}$/i.test(value))out.add(value);
      return out;
    }
    if(Array.isArray(value)){for(const v of value)identifierStrings(v,out,depth+1);return out;}
    if(typeof value==='object')for(const [k,v] of Object.entries(value)){
      if(typeof v==='string'&&/(?:^id$|Id$|_id$|name$|media$|asset$|image$|reference$)/i.test(k)&&v.length>=6)out.add(v);
      identifierStrings(v,out,depth+1);
    }
    return out;
  }
  function matchingSubtree(value,ids,depth=0) {
    if(value==null||depth>8)return null;
    if(Array.isArray(value)){
      for(const row of value){const hit=matchingSubtree(row,ids,depth+1);if(hit)return hit;}
      return hasTarget(value,ids)?value:null;
    }
    if(typeof value==='object'){
      for(const child of Object.values(value)){const hit=matchingSubtree(child,ids,depth+1);if(hit)return hit;}
      return hasTarget(value,ids)?value:null;
    }
    return null;
  }
  function captureMaterialBinding(service,editor,key,selectedKey,targetIds) {
    const candidates=[];
    try{
      const blocks=editor()?.[key];
      const hit=matchingSubtree(blocks,targetIds);
      if(hit)candidates.push({source:'editor',value:hit});
    }catch(_){}
    try{
      if(selectedKey){
        const snap=stateSnapshot(service),value=snap.get(selectedKey)?.data;
        const hit=matchingSubtree(value,targetIds);
        if(hit)candidates.push({source:'signal:'+selectedKey,value:hit});
      }
    }catch(_){}
    const ids=new Set(targetIds),shapes=[];
    for(const row of candidates){
      identifierStrings(row.value,ids);
      try{shapes.push({source:row.source,fields:Array.isArray(row.value)?Object.keys(row.value[0]||{}).slice(0,8):Object.keys(row.value||{}).slice(0,8)});}catch(_){}
    }
    return {ids,shapes};
  }
  function materialBindingProof(body,ticket) {
    if(!ticket?.requireMaterial)return {ok:true,kind:'not_required'};
    const primary=String(ticket.requiredMaterialPrimaryId||'');
    const ids=[...new Set([primary,...(ticket.requiredMaterialBindingIds||[]),...(ticket.requiredMaterialIds||[])].map(v=>String(v||'')).filter(v=>v.length>=6))];
    if(!ids.length)return {ok:false,reason:'no_required_identity'};
    const root=requestBodyObject(body);
    if(root==null || (typeof root==='string' && root===String(body)))return {ok:false,reason:'unparsed_request'};
    const wholeText=bodyFragments(root).join('\n');
    if(false && /(?:VIDEO_FRAMES|FIRST_FRAME|FRAME_REFERENCE)/i.test(wholeText))return {ok:false,reason:'wrong_generation_mode'};
    const prompt=String(ticket.prompt||'');
    const strongKey=/(?:reference|material|attachment|input[_-]?(?:media|image|asset)|source[_-]?(?:media|image|asset)|image[_-]?reference|media[_-]?reference|reference[_-]?(?:media|image|asset))/i;
    const genericKey=/(?:media|image|asset|input|source|seed|frame)/i;
    const excludedKey=/(?:history|previous|cache|catalog|library|thumbnail|poster|preview|suggestion|recent|gallery)/i;
    const referenceToken=/(?:VIDEO_REFERENCES|REFERENCE_MATERIAL|REFERENCE[_ -]?(?:IMAGE|MEDIA|ASSET)|INPUT[_ -]?(?:IMAGE|MEDIA)|IMAGE[_ -]?REFERENCE)/i;
    const imageToken=/(?:^|[^A-Z0-9])IMAGE(?:$|[^A-Z0-9])|MEDIA_TYPE_IMAGE|IMAGE_ASSET/i;
    let best=null;
    function localScalars(v,depth=0,out=[]){
      if(v==null||depth>4||out.length>120)return out;
      if(typeof v==='string'||typeof v==='number'||typeof v==='boolean'){out.push(String(v));return out;}
      if(Array.isArray(v)){for(const x of v)localScalars(x,depth+1,out);return out;}
      if(typeof v==='object')for(const [k,x] of Object.entries(v)){out.push(String(k));localScalars(x,depth+1,out);}
      return out;
    }
    function inspect(v,path=[],depth=0){
      if(v==null||depth>13||typeof v!=='object')return;
      const pathText=path.join('.');
      const keys=Array.isArray(v)?[]:Object.keys(v);
      const keyText=keys.join('|');
      const scalars=localScalars(v);
      const scalarText=scalars.join('\n');
      const matchedIds=ids.filter(id=>scalarText.includes(id));
      if(matchedIds.length){
        let size=0;try{size=JSON.stringify(v).length}catch(_){size=999999}
        // Reject broad root/body containers. A valid binding proof must be local to the
        // current reference/input branch, not merely co-exist somewhere in the request.
        if(size<=18000){
          const directText=localScalars(v,1,[]).join('\n');
          const excluded=excludedKey.test(pathText)||excludedKey.test(keyText)||/(?:^|\n)(?:history|previous|cache|catalog|library|thumbnail|poster|preview|suggestion|recent|gallery)(?:$|\n)/i.test(directText);
          const strong=strongKey.test(pathText)||strongKey.test(keyText);
          const generic=genericKey.test(pathText)||genericKey.test(keyText);
          const refMarker=referenceToken.test(scalarText);
          const imgMarker=imageToken.test(scalarText)||/mediaType/i.test(keyText)&&/IMAGE/i.test(scalarText);
          const promptLocal=!!prompt && (scalarText.includes(prompt)||scalarText.includes(JSON.stringify(prompt).slice(1,-1)));
          const exactPrimary=!!primary&&matchedIds.includes(primary);
          const bindingSet=new Set((ticket.requiredMaterialBindingIds||[]).map(String));
          const exactBinding=matchedIds.some(id=>bindingSet.has(id));
          const directId=matchedIds.some(id=>directText.includes(id));
          const directRef=referenceToken.test(directText);
          const directImage=imageToken.test(directText)||/mediaType/i.test(keyText)&&/IMAGE/i.test(directText);
          const frameMode=/(?:VIDEO_FRAMES|FIRST_FRAME|FRAME_REFERENCE)/i.test(scalarText);
          let score=(exactPrimary?4:0)+(exactBinding?4:0)+(strong?6:0)+(generic?2:0)+(refMarker?4:0)+(imgMarker?2:0)+(promptLocal?3:0)-(excluded?12:0)-(frameMode?10:0);
          let kind='';
          // Named semantic branch: the matched identity lives under a reference/material/input key.
          if(!excluded && !frameMode && strong && (exactPrimary||exactBinding) && (refMarker||imgMarker||directImage)){kind='semantic_reference_branch';score+=4;}
          // Positional/minified Flow payload: demand LOCAL co-occurrence. Merely finding the
          // image ID and VIDEO_REFERENCES somewhere else in the overall request is rejected.
          else if(!excluded && !frameMode && Array.isArray(v) && depth>=2 && directId && directRef && (exactPrimary||exactBinding)){kind='reference_tuple';score+=4;}
          else if(!excluded && !frameMode && Array.isArray(v) && depth>=2 && size<=6000 && directId && directImage && promptLocal && (exactPrimary||exactBinding)){kind='positional_generation_tuple';score+=3;}
          else if(!excluded && !frameMode && generic && imgMarker && promptLocal && (exactPrimary||exactBinding)){kind='generation_media_branch';score+=3;}
          if(kind && score>=11 && (!best||score>best.score))best={ok:true,kind,path:pathText||'<root>',id:matchedIds[0],score,size,markers:{strong,generic,refMarker,imgMarker,promptLocal,exactPrimary,exactBinding,directId,directRef,directImage,frameMode}};
        }
      }
      if(Array.isArray(v))v.forEach((x,i)=>inspect(x,path.concat('['+i+']'),depth+1));
      else for(const [k,x] of Object.entries(v))inspect(x,path.concat(k),depth+1);
    }
    inspect(root,[],0);
    return best||{ok:false,reason:'identity_not_bound_to_reference_branch',ids_seen:ids.filter(id=>bodyFragments(root).some(part=>String(part).includes(id))).slice(0,4)};
  }
  function bodyHasRequiredMaterial(body,ticket) {
    return materialBindingProof(body,ticket).ok;
  }
  function blockMateriallessGeneration(ticket,url,body) {
    if(!ticket?.requireMaterial)return false;
    const proof=materialBindingProof(body,ticket);
    ticket.materialBindingProof=proof;
    if(proof.ok){
      ticket.materialRequestConfirmed=true;
      submissionDiagnostics.push({time:Date.now(),blocked:false,material_proof:{kind:proof.kind,path:proof.path,id:proof.id,score:proof.score},url:String(url||'').slice(0,220),image_name:ticket.imageName||''});
      if(submissionDiagnostics.length>8)submissionDiagnostics.shift();
      return false;
    }
    const inspectable=body!=null && bodyFragments(body).length>0;
    const code=!inspectable||proof.reason==='unparsed_request'?'REFERENCE_MATERIAL_REQUEST_UNVERIFIABLE':'REFERENCE_MATERIAL_NOT_BOUND_IN_GENERATION_REQUEST';
    ticket.materialRequestBlocked=true;ticket.started=false;
    ticket.failure=code+':'+String(ticket.imageName||'');
    safeRecoveryRemove(ticket.recoveryKey);
    submissionDiagnostics.push({time:Date.now(),blocked:true,reason:code,proof_reason:proof.reason||'',ids_seen:proof.ids_seen||[],url:String(url||'').slice(0,220),image_name:ticket.imageName||'',required_material_count:(ticket.requiredMaterialIds||[]).length});
    if(submissionDiagnostics.length>8)submissionDiagnostics.shift();
    return true;
  }
  // v1.7.8: use Flow's own generation/status responses as the primary identity and
  // completion source, following the proven v1.0.6 flow. The existing CDP Generate click,
  // upload path, prompt path and Studio task ordering are intentionally untouched.
  const flowStatusReadySeen=new Set();
  const flowSubmitMediaSeen=new Set();
  const flowDirectVideoSeen=new Set();
  const FLOW_VIDEO_GENERATE_MARKERS=[
    'video:batchAsyncGenerateVideoStartAndEndImage',
    'video:batchAsyncGenerateVideoStartImage',
    'video:batchAsyncGenerateVideoReferenceImages',
    'video:batchAsyncGenerateVideoText'
  ];
  const FLOW_VIDEO_STATUS_MARKER='video:batchCheckAsyncVideoGenerationStatus';

  // v1.7.9: keep the Flow page naturally active only while submitted VIDEO generations are
  // still waiting for Flow's own status responses. This mirrors the proven batch plugin's
  // AntiFreeze idea, but is scoped to WAITING_RESULT only and never uses focus/lifecycle spoofing.
  const flowWaitingVideoIds=new Set();
  const flowWaitKeepAlive={running:false,releaseLock:null,lockAbort:null,pc1:null,pc2:null,dc:null,dcHeartbeat:null,titleTimer:null,faviconTimer:null,safetyTimer:null,originalTitle:'',originalFavicon:'',tick:0,startedAt:0};
  function stopFlowWaitingKeepAlive(reason='idle'){
    if(!flowWaitKeepAlive.running)return;
    flowWaitKeepAlive.running=false;
    try{flowWaitKeepAlive.releaseLock?.();}catch(_){}
    try{flowWaitKeepAlive.lockAbort?.abort?.();}catch(_){}
    flowWaitKeepAlive.releaseLock=null;flowWaitKeepAlive.lockAbort=null;
    if(flowWaitKeepAlive.dcHeartbeat&&typeof clearInterval==='function'){clearInterval(flowWaitKeepAlive.dcHeartbeat);flowWaitKeepAlive.dcHeartbeat=null;}
    try{flowWaitKeepAlive.dc?.close?.();flowWaitKeepAlive.pc1?.close?.();flowWaitKeepAlive.pc2?.close?.();}catch(_){}
    flowWaitKeepAlive.dc=null;flowWaitKeepAlive.pc1=null;flowWaitKeepAlive.pc2=null;
    if(flowWaitKeepAlive.titleTimer&&typeof clearInterval==='function'){clearInterval(flowWaitKeepAlive.titleTimer);flowWaitKeepAlive.titleTimer=null;}
    if(flowWaitKeepAlive.faviconTimer&&typeof clearInterval==='function'){clearInterval(flowWaitKeepAlive.faviconTimer);flowWaitKeepAlive.faviconTimer=null;}
    try{if(typeof document!=='undefined'&&flowWaitKeepAlive.originalFavicon){const icon=document.querySelector("link[rel~='icon']");if(icon)icon.href=flowWaitKeepAlive.originalFavicon;}}catch(_){}
    if(flowWaitKeepAlive.safetyTimer&&typeof clearTimeout==='function'){clearTimeout(flowWaitKeepAlive.safetyTimer);flowWaitKeepAlive.safetyTimer=null;}
    try{
      if(typeof document!=='undefined'&&flowWaitKeepAlive.originalTitle && document.title.replace(/\u200B$/,'')===flowWaitKeepAlive.originalTitle.replace(/\u200B$/,''))document.title=flowWaitKeepAlive.originalTitle;
    }catch(_){}
    console.info('[FlowStudio][VIDEO_WAIT_KEEPALIVE_STOP]',{reason,waiting:flowWaitingVideoIds.size});
  }
  async function startFlowWaitingWebRTC(){
    if(!flowWaitKeepAlive.running||typeof window==='undefined'||!window.RTCPeerConnection||flowWaitKeepAlive.pc1)return;
    try{
      const pc1=new RTCPeerConnection(),pc2=new RTCPeerConnection();
      flowWaitKeepAlive.pc1=pc1;flowWaitKeepAlive.pc2=pc2;
      pc1.onicecandidate=e=>{if(e.candidate&&flowWaitKeepAlive.pc2)flowWaitKeepAlive.pc2.addIceCandidate(e.candidate).catch(()=>{});};
      pc2.onicecandidate=e=>{if(e.candidate&&flowWaitKeepAlive.pc1)flowWaitKeepAlive.pc1.addIceCandidate(e.candidate).catch(()=>{});};
      const dc=pc1.createDataChannel('__flow_studio_waiting_video__');flowWaitKeepAlive.dc=dc;
      dc.onopen=()=>{
        if(!flowWaitKeepAlive.running)return;
        flowWaitKeepAlive.dcHeartbeat=setInterval(()=>{if(flowWaitKeepAlive.running&&dc.readyState==='open')try{dc.send('ping');}catch(_){}},30000);
      };
      const offer=await pc1.createOffer();await pc1.setLocalDescription(offer);await pc2.setRemoteDescription(offer);
      const answer=await pc2.createAnswer();await pc2.setLocalDescription(answer);await pc1.setRemoteDescription(answer);
    }catch(error){console.warn('[FlowStudio][VIDEO_WAIT_WEBRTC_FAILED]',String(error?.message||error));}
  }
  function startFlowWaitingKeepAlive(reason='waiting_video'){
    // v1.8.1: keepalive is allowed only after a VIDEO mediaId has been accepted.
    // No document_start/global anti-freeze is installed, so submission/upload remain untouched.
    if(!flowWaitingVideoIds.size||flowWaitKeepAlive.running)return;
    flowWaitKeepAlive.running=true;flowWaitKeepAlive.startedAt=Date.now();flowWaitKeepAlive.tick=0;flowWaitKeepAlive.originalTitle=typeof document!=='undefined'?document.title:'';
    try{
      if(typeof navigator!=='undefined'&&navigator?.locks?.request){
        const ctl=new AbortController();flowWaitKeepAlive.lockAbort=ctl;
        navigator.locks.request('__flow_studio_waiting_video_lock__',{mode:'exclusive',signal:ctl.signal},()=>new Promise(resolve=>{flowWaitKeepAlive.releaseLock=resolve;})).catch(()=>{});
      }
    }catch(_){}
    void startFlowWaitingWebRTC();
    // Reference plugin uses a zero-width title heartbeat. It is intentionally tiny and only
    // exists while there are waiting VIDEO ids; no focus/visibility/lifecycle state is spoofed.
    if(typeof setInterval==='function'&&typeof document!=='undefined')flowWaitKeepAlive.titleTimer=setInterval(()=>{
      if(!flowWaitKeepAlive.running||!flowWaitingVideoIds.size)return stopFlowWaitingKeepAlive('waiting_empty');
      try{
        flowWaitKeepAlive.tick++;
        const base=document.title.replace(/\u200B$/,'');
        document.title=flowWaitKeepAlive.tick%2?base+'\u200B':base;
      }catch(_){}
    },5000);
    // The reference batch plugin also touches the favicon while waiting. Keep the same
    // post-submit-only heartbeat here so Chromium continues to service Flow's status work
    // without changing focus/visibility/lifecycle state.
    if(typeof setInterval==='function'&&typeof document!=='undefined')flowWaitKeepAlive.faviconTimer=setInterval(()=>{
      if(!flowWaitKeepAlive.running||!flowWaitingVideoIds.size)return;
      try{
        let icon=document.querySelector("link[rel~='icon']");
        if(!icon){icon=document.createElement('link');icon.rel='icon';document.head?.appendChild(icon);}
        if(!flowWaitKeepAlive.originalFavicon&&icon?.href)flowWaitKeepAlive.originalFavicon=icon.href;
        const raw=String(icon?.href||flowWaitKeepAlive.originalFavicon||'');
        if(!raw)return;
        const u=new URL(raw,location.href);u.searchParams.set('__fs_wait_video',String(flowWaitKeepAlive.tick%2));icon.href=u.href;
      }catch(_){}
    },5000);
    // Never keep a stale page alive indefinitely if a terminal response is missed.
    if(typeof setTimeout==='function')flowWaitKeepAlive.safetyTimer=setTimeout(()=>stopFlowWaitingKeepAlive('safety_timeout'),45*60*1000);
    console.info('[FlowStudio][VIDEO_WAIT_KEEPALIVE_START]',{reason,waiting:flowWaitingVideoIds.size});
  }
  function trackWaitingVideoIds(ids,source='generation_response'){
    let added=0;
    for(const id of ids||[]){const v=String(id||'');if(v&&!flowWaitingVideoIds.has(v)){flowWaitingVideoIds.add(v);added++;}}
    if(flowWaitingVideoIds.size){startFlowWaitingKeepAlive(source);ensureFlowStatusReplay();}
    return added;
  }
  function finishWaitingVideoId(id,reason='terminal'){
    const key=String(id||'');if(!key)return false;
    const removed=flowWaitingVideoIds.delete(key);
    if(!flowWaitingVideoIds.size){stopFlowWaitingKeepAlive(reason);stopFlowStatusReplay();}
    return removed;
  }
  function settleWaitingVideoIdsFromStatus(root){
    const seen=new Set();
    function visit(value,depth=0){
      if(value==null||depth>18)return;
      if(typeof value==='string'){
        const t=value.trim();
        if((t.startsWith('{')&&t.endsWith('}'))||(t.startsWith('[')&&t.endsWith(']'))){try{visit(JSON.parse(t),depth+1);}catch(_){}}
        return;
      }
      if(typeof value!=='object'||seen.has(value))return;seen.add(value);
      if(Array.isArray(value)){for(const item of value)visit(item,depth+1);return;}
      const name=String(value.name||'');
      const status=String(value?.mediaMetadata?.mediaStatus?.mediaGenerationStatus||value?.mediaStatus?.mediaGenerationStatus||value?.mediaGenerationStatus||'').toUpperCase();
      if(name && /(SUCCESS|FAILED|FAILURE|CANCEL|ERROR)/.test(status))finishWaitingVideoId(name,status);
      for(const child of Object.values(value))visit(child,depth+1);
    }
    visit(root);
  }
  function flowRequestURL(input){
    try{
      if(typeof input==='string')return input;
      if(input instanceof URL)return input.href;
      if(typeof Request!=='undefined'&&input instanceof Request)return input.url;
      return String(input?.url||input||'');
    }catch(_){return '';}
  }
  function isFlowVideoGenerateURL(url){
    const text=String(url||'');
    return FLOW_VIDEO_GENERATE_MARKERS.some(marker=>text.includes(marker));
  }
  function isFlowVideoStatusURL(url){return String(url||'').includes(FLOW_VIDEO_STATUS_MARKER);}
  function parseFlowPayloadText(text){
    let value=String(text||'').replace(/^for\s*\(\s*;;\s*\);/,'').trim();
    if(!value)return null;
    try{return JSON.parse(value);}catch(_){}
    // Flow batched responses can be framed as "2:[...]" lines. The reference plugin
    // successfully unwraps those frames and then recursively parses JSON strings inside them.
    const parsed=[];
    for(const rawLine of value.split(/\r?\n/)){
      const line=rawLine.trim().replace(/^\d+\s*:/,'').trim();
      if(!line || !((line.startsWith('[')&&line.endsWith(']'))||(line.startsWith('{')&&line.endsWith('}'))))continue;
      try{parsed.push(JSON.parse(line));}catch(_){}
    }
    return parsed.length?parsed:value;
  }
  async function readFlowResponse(response){
    try{
      if(!response)return null;
      const type=String(response.headers?.get?.('Content-Type')||'').toLowerCase();
      if(type.includes('application/json'))return await response.json();
      const text=await response.text();
      return parseFlowPayloadText(text);
    }catch(_){return null;}
  }
  function walkFlowValues(root,visitor,depth=0,seen=new Set()){
    if(root==null||depth>20)return;
    if(typeof root==='string'){
      visitor(root,null);
      const t=root.trim();
      if((t.startsWith('{')&&t.endsWith('}'))||(t.startsWith('[')&&t.endsWith(']'))){
        try{walkFlowValues(JSON.parse(t),visitor,depth+1,seen);}catch(_){}
      }
      return;
    }
    if(typeof root!=='object'||seen.has(root))return;
    seen.add(root);
    visitor(root,root);
    if(Array.isArray(root)){for(const item of root)walkFlowValues(item,visitor,depth+1,seen);return;}
    for(const child of Object.values(root))walkFlowValues(child,visitor,depth+1,seen);
  }
  function directVideoURLs(root){
    const urls=new Set();
    const re=/https:\/\/[^\s"'\\]+\/video\/[^\s"'\\\]\[{}(),]+/g;
    walkFlowValues(root,value=>{
      if(typeof value!=='string')return;
      for(const hit of value.match(re)||[]){
        try{const u=new URL(hit); if(u.pathname.includes('/video/'))urls.add(u.href);}catch(_){}
      }
      if(value.startsWith('https://')){
        try{const u=new URL(value);if(u.pathname.includes('/video/'))urls.add(u.href);}catch(_){}
      }
    });
    return [...urls];
  }
  // Mirrors the supplied batch plugin's XHR fallback: Flow sometimes returns nested
  // JSON-array frames that contain the final signed /video/ URL even when the request URL
  // itself is not the generation-status endpoint. Parse those frames directly instead of
  // waiting for a hover-created <video> resource.
  function referenceBatchHttpsURLsFromXHRText(text){
    const out=[];
    const isArrayFrame=value=>typeof value==='string'&&value.startsWith('[')&&value.endsWith(']');
    try{
      for(const raw of String(text||'').split(/\r?\n/)){
        const line=raw.trim();
        if(!isArrayFrame(line))continue;
        let outer;try{outer=JSON.parse(line);}catch(_){continue;}
        const flat1=Array.isArray(outer)?outer.flat(Infinity):[];
        for(const value of flat1){
          if(typeof value!=='string'||!isArrayFrame(value))continue;
          let inner;try{inner=JSON.parse(value);}catch(_){continue;}
          const flat2=Array.isArray(inner)?inner.flat(Infinity):[];
          for(const candidate of flat2)if(typeof candidate==='string'&&candidate.startsWith('https://'))out.push(candidate);
        }
      }
    }catch(_){}
    return [...new Set(out)];
  }
  function publishReferenceBatchXHRVideos(text,source='flow_xhr_any_video_url'){
    if(!flowWaitingVideoIds.size)return 0;
    const EventCtor=window.CustomEvent||(typeof CustomEvent==='function'?CustomEvent:null);
    let emitted=0;
    for(const url of referenceBatchHttpsURLsFromXHRText(text)){
      let parsed;try{parsed=new URL(url);}catch(_){continue;}
      if(!parsed.pathname.includes('/video/'))continue;
      const id=parsed.pathname.split('/').filter(Boolean).pop()||'';
      if(!id)continue;
      // Do not suppress repeated delivery here. downloads.js already de-duplicates by the
      // bound media id/status, while re-delivery lets a result survive an early race with bind.
      let boundId=primaryFlowIdentity(id);
      if(boundId===id&&flowWaitingVideoIds.size===1){const only=[...flowWaitingVideoIds][0];bindFlowIdentityAliases(only,[id],source+'_single_waiting');boundId=only;}
      bindFlowIdentityAliases(boundId,[id],source+'_xhr_video');
      const row={id:boundId,media_id:id,status:'ready',media_kind:'VIDEO',catalog_type:'VIDEO',identity_aliases:aliasesForPrimary(boundId),url:parsed.href,evidence:source};
      if(EventCtor)window.dispatchEvent(new EventCtor('FLOW_STUDIO_VIDEO_READY',{detail:{row}}));
      emitted++;
    }
    return emitted;
  }
  // v1.8.2: one Flow task may be represented by several identities (request UUID,
  // generation media.name, catalog id, final /video/ id). Keep aliases so SUCCESSFUL can
  // wake the already-bound download entry without waiting for hover-created video resources.
  const flowIdentityPrimary=new Map();
  const flowPrimaryAliases=new Map();
  const flowSuccessRows=new Map();
  function emitFlowReadyRow(primary,item,extraAliases=[]){
    const EventCtor=window.CustomEvent||(typeof CustomEvent==='function'?CustomEvent:null);
    if(!EventCtor)return;
    const url=item.url||('https://flow.google.com/fx/api/trpc/media.getMediaUrlRedirect?name='+encodeURIComponent(item.name));
    const row={id:primary,media_id:item.mediaId||item.name,status:'ready',media_kind:'VIDEO',catalog_type:'VIDEO',
      identity_aliases:[...new Set([...aliasesForPrimary(primary),item.name,...(item.aliases||[]),...extraAliases])].filter(Boolean),
      url,evidence:'identity_alias_replay',flow_status_id:item.name};
    window.dispatchEvent(new EventCtor('FLOW_STUDIO_VIDEO_READY',{detail:{row}}));
  }
  function bindFlowIdentityAliases(primary,aliases,source='identity'){
     const p=String(primary||'');if(!p)return;
     const values=[p,...(aliases||[])].map(v=>String(v||'')).filter(Boolean);
     let set=flowPrimaryAliases.get(p);if(!set){set=new Set([p]);flowPrimaryAliases.set(p,set);}
     for(const id of new Set(values)){flowIdentityPrimary.set(id,p);set.add(id);}
     while(flowIdentityPrimary.size>4000)flowIdentityPrimary.delete(flowIdentityPrimary.keys().next().value);
     while(flowPrimaryAliases.size>2000)flowPrimaryAliases.delete(flowPrimaryAliases.keys().next().value);
     if(typeof submissionDiagnostics!=='undefined'&&submissionDiagnostics){submissionDiagnostics.push({time:Date.now(),stage:'FLOW_IDENTITY_ALIAS',source,primary:p,aliases:[...set].slice(0,12)});if(submissionDiagnostics.length>8)submissionDiagnostics.shift();}
     // A SUCCESSFUL status may have arrived before this alias was known. Re-deliver it now
     // under the task's primary identity so it is never stranded waiting for a /video/ resource.
     for(const id of new Set(values)){
       const item=flowSuccessRows.get(id);
       if(item&&item.deliveredTo!==p){item.deliveredTo=p;try{emitFlowReadyRow(p,item);finishWaitingVideoId(p,'successful_alias_replay');}catch(_){}}
     }
   }
  function primaryFlowIdentity(id){return flowIdentityPrimary.get(String(id||''))||String(id||'');}
  function aliasesForPrimary(primary){
    const p=primaryFlowIdentity(primary);const set=flowPrimaryAliases.get(p);return [...new Set([p,...(set?[...set]:[])])].filter(Boolean);
  }

  // Re-use Flow's own status request after submission. This is deliberately scoped to
  // WAITING_RESULT and uses the exact request Flow already made; it never touches Generate.
  const flowStatusReplay={template:null,timer:null,inFlight:false,lastRun:0,lastCapture:0,nativeFetch:null};
  function stopFlowStatusReplay(){if(flowStatusReplay.timer&&typeof clearInterval==='function')clearInterval(flowStatusReplay.timer);flowStatusReplay.timer=null;flowStatusReplay.inFlight=false;}
  async function replayFlowStatusOnce(){
    if(!flowWaitingVideoIds.size||!flowStatusReplay.template||flowStatusReplay.inFlight||typeof flowStatusReplay.nativeFetch!=='function')return;
    flowStatusReplay.inFlight=true;flowStatusReplay.lastRun=Date.now();
    try{
      const t=flowStatusReplay.template;
      const response=await flowStatusReplay.nativeFetch(t.url,{method:t.method,headers:t.headers,body:t.body,credentials:t.credentials,mode:t.mode,cache:'no-store',redirect:t.redirect,referrer:t.referrer,referrerPolicy:t.referrerPolicy});
      let clone=null;try{clone=response.clone();}catch(_){}
      if(clone){const payload=await readFlowResponse(clone);if(payload){publishSuccessfulVideoMedia(payload,'flow_status_replay');publishDirectVideoFallback(payload,'flow_status_replay_url');}}
    }catch(error){submissionDiagnostics.push({time:Date.now(),stage:'FLOW_STATUS_REPLAY_ERROR',error:String(error?.message||error).slice(0,180)});if(submissionDiagnostics.length>8)submissionDiagnostics.shift();}
    finally{flowStatusReplay.inFlight=false;}
  }
  function ensureFlowStatusReplay(){
    if(!flowWaitingVideoIds.size||!flowStatusReplay.template||flowStatusReplay.timer)return;
    flowStatusReplay.timer=setInterval(()=>{if(!flowWaitingVideoIds.size)return stopFlowStatusReplay();void replayFlowStatusOnce();},2500);
    setTimeout(()=>{if(flowWaitingVideoIds.size)void replayFlowStatusOnce();},700);
  }
  async function captureFlowStatusFetchTemplate(args){
    try{
      const input=args?.[0],init=args?.[1]||{};let url=flowRequestURL(input),method=String(init.method||'GET').toUpperCase(),body=init.body??null,headers=[];
      let credentials=init.credentials||'include',mode=init.mode,redirect=init.redirect||'follow',referrer=init.referrer,referrerPolicy=init.referrerPolicy;
      if(typeof Request!=='undefined'&&input instanceof Request){
        const clone=input.clone();url=clone.url;method=clone.method||method;credentials=clone.credentials||credentials;mode=clone.mode||mode;redirect=clone.redirect||redirect;referrer=clone.referrer||referrer;referrerPolicy=clone.referrerPolicy||referrerPolicy;headers=[...clone.headers.entries()];
        if(body==null && !['GET','HEAD'].includes(method)){try{body=await clone.text();}catch(_){}}
      }else{try{headers=[...new Headers(init.headers||{}).entries()];}catch(_){}}
      flowStatusReplay.template={url,method,body,headers,credentials,mode,redirect,referrer,referrerPolicy};flowStatusReplay.lastCapture=Date.now();ensureFlowStatusReplay();
    }catch(_){}
  }

  function collectGenerationMediaIds(root){
    const ids=new Set();
    const seen=new Set();
    function visit(value,depth=0){
      if(value==null||depth>18)return;
      if(typeof value==='string'){
        const t=value.trim();
        if((t.startsWith('{')&&t.endsWith('}'))||(t.startsWith('[')&&t.endsWith(']'))){try{visit(JSON.parse(t),depth+1);}catch(_){}}
        return;
      }
      if(typeof value!=='object'||seen.has(value))return;seen.add(value);
      if(Array.isArray(value)){for(const item of value)visit(item,depth+1);return;}
      if(Array.isArray(value.media))for(const row of value.media){
        const id=row?.name||row?.id||row?.operation?.name;
        if(typeof id==='string'&&id)ids.add(id);
      }
      for(const child of Object.values(value))visit(child,depth+1);
    }
    visit(root);return [...ids];
  }
  function flowRequestUUIDs(body){
    const out=new Set(),text=String(body||'');
    for(const hit of text.match(/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/ig)||[])out.add(hit);
    return [...out];
  }
  function rememberAcceptedGeneration(ticket,ids,source){
    if(!ticket||ticket.accepted)return false;
    const filtered=[...new Set((ids||[]).map(String).filter(Boolean).filter(id=>!(ticket.excludedIds||[]).includes(id)))];
    if(filtered.length!==1){
      if(filtered.length>1){submissionDiagnostics.push({time:Date.now(),stage:'GENERATION_RESPONSE_AMBIGUOUS',source,ids:filtered.slice(0,8)});if(submissionDiagnostics.length>8)submissionDiagnostics.shift();}
      return false;
    }
    const id=filtered[0];
    ticket.accepted=[id];ticket.started=true;ticket.responseAccepted=true;ticket.responseAcceptedAt=Date.now();
    flowSubmitMediaSeen.add(id);while(flowSubmitMediaSeen.size>1000)flowSubmitMediaSeen.delete(flowSubmitMediaSeen.values().next().value);
    trackWaitingVideoIds([id],source);
    if(ticket.recoveryKey)safeRecoveryWrite(ticket.recoveryKey,{prompt:ticket.prompt,excludedIds:ticket.excludedIds,acceptedIds:[id],acceptedSource:source});
    submissionDiagnostics.push({time:Date.now(),stage:'GENERATION_RESPONSE_BOUND',source,id});if(submissionDiagnostics.length>8)submissionDiagnostics.shift();
    return true;
  }
  function observeFlowGenerationPayload(ticket,status,payload,source='flow_generate_response',requestFallbackIds=[]){
    if(!ticket)return false;
    if(status && (status<200||status>=300)){ticket.failure='FLOW_GENERATION_REJECTED:'+status;return false;}
    const ids=collectGenerationMediaIds(payload);
    let accepted=rememberAcceptedGeneration(ticket,ids,source);
    // The reference plugin also recovers a UUID from f.req. Only use that fallback after a
    // successful recognized generation response, never merely because a request was attempted.
    if(!accepted)accepted=rememberAcceptedGeneration(ticket,requestFallbackIds,source+'_request_uuid');
    const primary=ticket.accepted?.[0];
    if(primary)bindFlowIdentityAliases(primary,[...ids,...requestFallbackIds],source);
    return accepted;
  }
  function collectSuccessfulVideoMedia(root){
    const out=[],seen=new Set();
    function visit(value,depth=0){
      if(value==null||depth>18)return;
      if(typeof value==='string'){
        const t=value.trim();
        if((t.startsWith('{')&&t.endsWith('}'))||(t.startsWith('[')&&t.endsWith(']'))){try{visit(JSON.parse(t),depth+1);}catch(_){}}
        return;
      }
      if(typeof value!=='object'||seen.has(value))return;seen.add(value);
      if(Array.isArray(value)){for(const item of value)visit(item,depth+1);return;}
      const name=String(value.name||value.mediaId||value.operation?.name||value.media?.name||'');
      const status=String(value?.mediaMetadata?.mediaStatus?.mediaGenerationStatus||value?.mediaStatus?.mediaGenerationStatus||value?.mediaGenerationStatus||'').toUpperCase();
      if(name&&status.includes('SUCCESSFUL')){
        const urls=directVideoURLs(value);
        const aliases=[value.name,value.id,value.mediaId,value.operation?.name,value.media?.name].filter(x=>typeof x==='string'&&x&&x!==name);
        out.push({name,status,url:urls[0]||'',aliases});
      }
      for(const child of Object.values(value))visit(child,depth+1);
    }
    visit(root);
    const uniq=new Map();for(const row of out)if(!uniq.has(row.name)||(!uniq.get(row.name).url&&row.url))uniq.set(row.name,row);
    const rows=[...uniq.values()];
    if(rows.length===1&&!rows[0].url){const urls=directVideoURLs(root);if(urls.length===1)rows[0].url=urls[0];}
    return rows;
  }
  function publishSuccessfulVideoMedia(payload,source='flow_status'){
    settleWaitingVideoIdsFromStatus(payload);
    const rows=collectSuccessfulVideoMedia(payload);
    if(!rows.length)return 0;
    const EventCtor=window.CustomEvent||(typeof CustomEvent==='function'?CustomEvent:null);
    let emitted=0;
    for(const item of rows){
      if(flowStatusReadySeen.has(item.name))continue;
      flowStatusReadySeen.add(item.name);
      while(flowStatusReadySeen.size>1000)flowStatusReadySeen.delete(flowStatusReadySeen.values().next().value);
      let mediaId=item.name,url=item.url||'';
      if(url){
        try{mediaId=new URL(url).pathname.split('/').filter(Boolean).pop()||item.name;}catch(_){}
      }
      let boundId=primaryFlowIdentity(item.name);
      if(boundId===item.name){
        for(const a of item.aliases||[]){const p=primaryFlowIdentity(a);if(p!==a||flowWaitingVideoIds.has(a)){boundId=p;break;}}
      }
      // Single-page/single-result recovery: if Flow reports one SUCCESSFUL id that is not yet
      // known as an alias and only one generation is currently waiting, bind it immediately.
      if(boundId===item.name&&!flowWaitingVideoIds.has(item.name)&&flowWaitingVideoIds.size===1){
        const only=[...flowWaitingVideoIds][0];bindFlowIdentityAliases(only,[item.name,mediaId],source+'_single_waiting');boundId=only;
      }
      const remembered={name:item.name,mediaId,url,aliases:item.aliases||[],deliveredTo:boundId};
      for(const k of [item.name,mediaId,...(item.aliases||[])])flowSuccessRows.set(k,remembered);
      while(flowSuccessRows.size>2000)flowSuccessRows.delete(flowSuccessRows.keys().next().value);
      bindFlowIdentityAliases(boundId,[item.name,mediaId,...(item.aliases||[])],source+'_successful');
      const row={
        id:boundId,media_id:mediaId,status:'ready',media_kind:'VIDEO',catalog_type:'VIDEO',
        identity_aliases:aliasesForPrimary(boundId),
        url:url||('https://flow.google.com/fx/api/trpc/media.getMediaUrlRedirect?name='+encodeURIComponent(item.name)),
        evidence:url?(source+'_direct_video'):(source+'_redirect'),flow_status_id:item.name
      };
      if(EventCtor)window.dispatchEvent(new EventCtor('FLOW_STUDIO_VIDEO_READY',{detail:{row}}));
      finishWaitingVideoId(boundId,'successful_status');
      if(!flowWaitingVideoIds.size)stopFlowStatusReplay();
      emitted++;
    }
    return emitted;
  }
  function publishDirectVideoFallback(payload,source='flow_direct_video'){
    const EventCtor=window.CustomEvent||(typeof CustomEvent==='function'?CustomEvent:null);let emitted=0;
    for(const url of directVideoURLs(payload)){
      let id='';try{id=new URL(url).pathname.split('/').filter(Boolean).pop()||'';}catch(_){}
      if(!id||flowDirectVideoSeen.has(url))continue;
      flowDirectVideoSeen.add(url);while(flowDirectVideoSeen.size>1000)flowDirectVideoSeen.delete(flowDirectVideoSeen.values().next().value);
      let boundId=primaryFlowIdentity(id);
      if(boundId===id&&flowWaitingVideoIds.size===1){const only=[...flowWaitingVideoIds][0];bindFlowIdentityAliases(only,[id],source+'_single_waiting');boundId=only;}
      bindFlowIdentityAliases(boundId,[id],source+'_direct');
      const row={id:boundId,media_id:id,status:'ready',media_kind:'VIDEO',catalog_type:'VIDEO',identity_aliases:aliasesForPrimary(boundId),url,evidence:source};
      if(EventCtor)window.dispatchEvent(new EventCtor('FLOW_STUDIO_VIDEO_READY',{detail:{row}}));
      if(boundId!==id||flowWaitingVideoIds.has(boundId))finishWaitingVideoId(boundId,'direct_video');
      emitted++;
    }
    return emitted;
  }
  function assertAuxRequest(body,ticket){
    if(!ticket?.requireAux)return;
    let root=body;
    try{if(typeof root==='string')root=JSON.parse(root);}catch(_){root=null;}
    const checks=[];
    function visit(v){
      if(!v||typeof v!=='object')return;
      if(Array.isArray(v)){v.forEach(visit);return;}
      const keys=Object.keys(v),start=keys.filter(k=>/^(startImage|firstFrame|start_image|first_frame)$/i.test(k)),end=keys.filter(k=>/^(endImage|lastFrame|end_image|last_frame)$/i.test(k));
      if(start.length||end.length)checks.push(start.length===1&&end.length===1&&hasTarget(v[start[0]],new Set(ticket.requiredStartIds))&&hasTarget(v[end[0]],new Set(ticket.requiredEndIds)));
      Object.values(v).forEach(visit);
    }
    visit(root);
    if(!checks.length||checks.some(ok=>!ok)){
      ticket.failure='AUX_FRAMES_MISSING_FROM_FLOW_REQUEST';ticket.started=false;
      throw Error(ticket.failure);
    }
    ticket.auxRequestConfirmed=true;
  }
  function installFlowVideoStatusBridge(){
    if(window.__FLOW_STUDIO_VIDEO_STATUS_BRIDGE__)return;
    window.__FLOW_STUDIO_VIDEO_STATUS_BRIDGE__=true;
    try{
      const originalFetch=window.fetch;
      if(typeof originalFetch==='function'&&!originalFetch.__flowStudioStatusWrapped){
        flowStatusReplay.nativeFetch=originalFetch.bind(window);
        const wrapped=async function(...args){
          const url=flowRequestURL(args[0]),isGenerate=isFlowVideoGenerateURL(url),isStatus=isFlowVideoStatusURL(url);
          const requestFallbackIds=isGenerate?flowRequestUUIDs(args?.[1]?.body||''):[];
          if(isStatus)void captureFlowStatusFetchTemplate(args);
          if(isGenerate&&pending?.requireAux){
            const body=args?.[1]?.body??(typeof Request!=='undefined'&&args[0] instanceof Request?await args[0].clone().text():null);
            assertAuxRequest(body,pending);
          }
          const response=await originalFetch.apply(this,args);
          if(isGenerate||isStatus){
            // Clone immediately, before Flow consumes the body. Parsing stays async and does not
            // delay the page's own response handling.
            let clone=null;try{clone=response.clone();}catch(_){}
            if(clone)Promise.resolve(readFlowResponse(clone)).then(payload=>{
              if(!payload)return;
              if(isGenerate)observeFlowGenerationPayload(pending,response.status,payload,'flow_generate_fetch',requestFallbackIds);
              if(isStatus){publishSuccessfulVideoMedia(payload,'flow_status_fetch');publishDirectVideoFallback(payload,'flow_status_fetch_url');}
            }).catch(()=>{});
          }
          return response;
        };
        try{Object.defineProperty(wrapped,'__flowStudioStatusWrapped',{value:true});}catch(_){}
        window.fetch=wrapped;
      }
    }catch(error){console.warn('[FlowStudio][STATUS_BRIDGE_FETCH_INSTALL_FAILED]',String(error?.message||error));}
    try{
      const proto=typeof XMLHttpRequest!=='undefined'?XMLHttpRequest.prototype:null;
      const originalOpen=proto?.open;
      if(proto&&typeof originalOpen==='function')proto.open=function(method,url,...rest){this.__flowStudioRequestURL=String(url);return originalOpen.call(this,method,url,...rest);};
      const originalSend=proto?.send;
      if(proto&&typeof originalSend==='function'&&!originalSend.__flowStudioStatusWrapped){
        const wrappedSend=function(...args){
          if(isFlowVideoGenerateURL(this.__flowStudioRequestURL||'')&&pending?.requireAux)assertAuxRequest(args[0],pending);
          if(!this.__flowStudioStatusListener){
            this.__flowStudioStatusListener=true;
            this.__flowStudioRequestUUIDs=flowRequestUUIDs(args?.[0]||'');
            this.addEventListener('readystatechange',()=>{
              if(this.readyState!==XMLHttpRequest.DONE)return;
              try{
                const url=String(this.responseURL||''),isGenerate=isFlowVideoGenerateURL(url),isStatus=isFlowVideoStatusURL(url);
                const rawText=(!this.responseType||this.responseType==='text')?String(this.responseText||''):'';
                // Exact reference-plugin behavior: inspect every completed text XHR for nested
                // signed /video/ URLs, not only requests whose URL happens to contain the status RPC name.
                if(rawText && flowWaitingVideoIds.size)publishReferenceBatchXHRVideos(rawText,'flow_xhr_any_video_url');
                if(!isGenerate&&!isStatus)return;
                let payload=null;
                if(this.responseType==='json')payload=this.response;
                else if(rawText)payload=parseFlowPayloadText(rawText);
                if(!payload)return;
                if(isGenerate)observeFlowGenerationPayload(pending,Number(this.status||0),payload,'flow_generate_xhr',this.__flowStudioRequestUUIDs||[]);
                if(isStatus){publishSuccessfulVideoMedia(payload,'flow_status_xhr');publishDirectVideoFallback(payload,'flow_status_xhr_url');}
              }catch(_){}
            });
          }
          return originalSend.apply(this,args);
        };
        try{Object.defineProperty(wrappedSend,'__flowStudioStatusWrapped',{value:true});}catch(_){}
        proto.send=wrappedSend;
      }
    }catch(error){console.warn('[FlowStudio][STATUS_BRIDGE_XHR_INSTALL_FAILED]',String(error?.message||error));}
  }
  installFlowVideoStatusBridge();

  const videoResults=new Map();
  function recordVideoResults(body) {
    for(const row of FlowStudioResults.records(body)) {
      const previous=videoResults.get(row.id);
      videoResults.delete(row.id);
      videoResults.set(row.id,row);
      while(!videoResults._scanning && videoResults.size>2000)videoResults.delete(videoResults.keys().next().value);
      if(row.status==='ready' && (!previous || previous.status!=='ready' || previous.url!==row.url || previous.media_id!==row.media_id)) {
        const EventCtor=window.CustomEvent||(typeof CustomEvent==='function'?CustomEvent:null);
        if(EventCtor)window.dispatchEvent(new EventCtor('FLOW_STUDIO_VIDEO_READY',{detail:{row}}));
      } else if(row.status==='failed' && previous?.status!=='failed') {
        const EventCtor=window.CustomEvent||(typeof CustomEvent==='function'?CustomEvent:null);
        if(EventCtor)window.dispatchEvent(new EventCtor('FLOW_STUDIO_VIDEO_READY',{detail:{row}}));
      }
    }
  }
  function recordLoadedVideoResources() {
    try {
      for(const entry of performance.getEntriesByType('resource')) recordVideoResults(entry?.name || '');
    } catch (_) {}
  }
  // Performance entries preserve Flow's real signed flow-content.google URL even
  // when the minified media object only exposes opaque Angular fields.
  try {
    recordLoadedVideoResources();
    resourceObserver=new PerformanceObserver(list=>{
      for(const entry of list.getEntries()) recordVideoResults(entry?.name || '');
    });
    resourceObserver.observe({type:'resource',buffered:true});
  } catch (_) {}
  function completedVideos(ids) {
    videoResults._scanning=true;
    try{
    let catalog=[],error='';
    try { catalog=mediaList(context().instance);recordVideoResults(catalog); } catch (e) {error=String(e.message||e);}
    recordLoadedVideoResources();
    const linkDiagnostics=[];
    for(const item of catalog){
      if(!(ids||[]).includes(item.id))continue;
      const link=FlowStudioResults.catalogLinks(item,videoResults);
      for(const row of link.rows)videoResults.set(row.id,row);
      linkDiagnostics.push({id:item.id,reason:link.reason,paths:link.paths,fields:FlowStudioResults.catalogShape(item)});
    }
    // Already-rendered videos remain discoverable after page refresh. Match exact media IDs only.
    for(const node of document.querySelectorAll('video,video source'))recordVideoResults(node.currentSrc||node.src||'');
    // DOM fallback is permitted only when the failed tile carries an exact bound output ID.
    // Never assign a generic page error to whichever task happens to be running.
    const wantedIds=new Set(ids||[]);
    for(const node of document.querySelectorAll('[data-media-id],[data-generation-id],[data-workflow-id],[id]')) {
      const matches=['data-media-id','data-generation-id','data-workflow-id','id'].map(k=>node.getAttribute(k)).filter(id=>wantedIds.has(id));
      if(matches.length!==1)continue;
      const text=String(node.innerText||node.textContent||'').trim();
      if(text.length<1500 && /generation failed|failed to generate|couldn.t generate|生成失败|无法生成|生成に失敗/i.test(text))
        videoResults.set(matches[0],{id:matches[0],status:'failed',evidence:'bound_tile_error',error:text.slice(0,200)});
    }
    const rows=[...new Set(ids||[])].map(id=>videoResults.get(id)).filter(Boolean);
    const wanted=new Set(ids||[]);
    const matches=catalog.filter(v=>wanted.has(v.id)||wanted.has(v.name));
    return {rows,diagnostics:{catalog:catalog.length,videos:catalog.filter(v=>v.type==='VIDEO').length,
      submission:submissionDiagnostics.slice(-8),unboundVideoShapes:!(ids||[]).length?catalog.filter(v=>v.type==='VIDEO').slice(0,3).map(v=>FlowStudioResults.catalogShape(v)):[],identityLinks:linkDiagnostics,boundMatches:matches.length,recognized:rows.length,resourceVideos:[...videoResults.values()].filter(v=>v.evidence==='video_url').length,error,
      samples:matches.slice(0,3).map(v=>({id:v.id||v.name,type:v.type,keys:Object.keys(v),status:v.status||v.mediaGenerationStatus||v.mediaMetadata?.mediaStatus}))}};
    }finally{
      videoResults._scanning=false;
      while(videoResults.size>2000)videoResults.delete(videoResults.keys().next().value);
    }
  }

  function observeResponse(ticket,status,body) {
    const parsed=decodeBody(body);
    recordVideoResults(parsed);
    submissionDiagnostics.push({time:Date.now(),status,ids:idsFrom(parsed),fields:FlowStudioResults.catalogShape(parsed)});if(submissionDiagnostics.length>8)submissionDiagnostics.shift();
    if (status<200 || status>=300 || parsed?.error) ticket.failure='FLOW_GENERATION_REJECTED:'+status+':'+String(parsed?.error?.message||'').slice(0,180);
    else { const ids=idsFrom(parsed).filter(id=>!(ticket.excludedIds||[]).includes(id)); if(ids.length===1) ticket.accepted=ids;

    }
  }

  function validateDuration(detail) {
    // IMAGE generation has no video duration. Never touch the legacy video duration rules.
    
    if (![4,6,8].includes(Number(detail.duration || 8))) throw new Error('INVALID_VIDEO_DURATION');
  }
  // DOM visibility here means a rendered element, never foreground-tab visibility.
  const composerNodeOrder=new WeakMap();let composerNodeSequence=0;
  function renderedNode(node) {
    if(!node?.isConnected)return false;
    for(let el=node;el && el.nodeType===1;el=el.parentElement){
      if(el.getAttribute?.('aria-hidden')==='true' || el.hidden)return false;
      const css=getComputedStyle(el);
      if(css.display==='none'||css.visibility==='hidden'||css.visibility==='collapse')return false;
    }
    const r=node.getBoundingClientRect();return r.width>0&&r.height>0;
  }
  const generateButtonSelectors=[
    'flow-generate-icon-button button',
    'button[aria-label="开始生成"]',
    'button.generate-icon-button',
    'button[type="submit"][aria-label*="生成"]',
    'flow-generate-icon-button [role="button"]'
  ];
  function generateButtons(root=document) {
    const seen=new Set(),out=[];
    for(const selector of generateButtonSelectors){
      for(const node of root.querySelectorAll?.(selector)||[]){
        if(seen.has(node)||!renderedNode(node))continue;
        seen.add(node);out.push(node);
      }
    }
    return out;
  }
  // Flow renders prompt line breaks as <br>; textContent drops those breaks.
  // Compare rendered text while preserving words, punctuation and spacing.
  function normalizedComposerPrompt(value) {
    return String(value ?? '').replace(/\r\n?/g,'\n').trim();
  }
  function composerPromptText(editor) {
    if(!editor)return '';
    if(typeof editor.value==='string')return editor.value;
    if(typeof editor.innerText==='string')return editor.innerText;
    return editor.textContent || '';
  }
  function composerContext(prompt='') {
    const editors=[...document.querySelectorAll('[contenteditable="true"],textarea')].filter(renderedNode);
    const candidates=[];
    for(const editor of editors){
      if(!composerNodeOrder.has(editor))composerNodeOrder.set(editor,++composerNodeSequence);
      for(let root=editor.parentElement;root && root!==document.body;root=root.parentElement){
        const buttons=generateButtons(root);
        if(buttons.length){
          const er=editor.getBoundingClientRect();
          buttons.sort((a,b)=>{const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect();return Math.hypot(ar.x-er.x,ar.y-er.y)-Math.hypot(br.x-er.x,br.y-er.y)});
          candidates.push({root,editor,button:buttons[0],exact:!!prompt && normalizedComposerPrompt(composerPromptText(editor))===normalizedComposerPrompt(prompt),order:composerNodeOrder.get(editor)});break;
        }
      }
    }
    candidates.sort((a,b)=>Number(b.exact)-Number(a.exact)||b.order-a.order);
    return candidates[0]||null;
  }
  function composerPreviews(composer) {
    if(!composer)return [];
    return [...composer.root.querySelectorAll('img')].filter(node=>renderedNode(node) && (node.currentSrc||node.src) && node.complete!==false && node.naturalWidth!==0).map(node=>{
      if(!composerNodeOrder.has(node))composerNodeOrder.set(node,++composerNodeSequence);
      return {node,src:node.currentSrc||node.src,order:composerNodeOrder.get(node)};
    });
  }
  function referencePreview(item,ids,before,prompt='',allowNativePreview=false) {
    const composer=composerContext(prompt);if(!composer)return null;
    const er=composer.editor.getBoundingClientRect(),url=mediaURL(item);
    const candidates=composerPreviews(composer).filter(p=>{
      const matched=(url && p.src===url) || ['data-id','data-media-id','data-asset-id'].some(k=>ids.has(p.node.getAttribute(k)));
      // Only the selected task's identity, and a new/changed preview after native clear/select.
      const explicitIds=['data-id','data-media-id','data-asset-id'].map(k=>p.node.getAttribute(k)).filter(Boolean);
      if(explicitIds.length && !explicitIds.some(id=>ids.has(id)))return false;
      return (matched || allowNativePreview) && (!before.has(p.node)||before.get(p.node)!==p.src);
    });
    candidates.sort((a,b)=>{const ar=a.node.getBoundingClientRect(),br=b.node.getBoundingClientRect();return Math.hypot(ar.x-er.x,ar.y-er.y)-Math.hypot(br.x-er.x,br.y-er.y)||b.order-a.order});
    return candidates[0]||null;
  }
  function generateButtonReady(button) {
    return !!(button && button.isConnected && renderedNode(button) && !button.disabled && button.getAttribute('aria-disabled')!=='true');
  }
  function logGenerateButtonState(stage,prompt,current) {
    try{
      const button=current?.button,rect=button?.getBoundingClientRect?.();
      console.info('[FlowStudio][CLICK_SCAN]',{
        stage,
        promptMatch:!!current?.exact,
        found:!!button,
        disabled:button?.disabled,
        ariaDisabled:button?.getAttribute?.('aria-disabled'),
        connected:button?.isConnected,
        tag:button?.tagName,
        ariaLabel:button?.getAttribute?.('aria-label'),
        role:button?.getAttribute?.('role'),
        rect:rect?{x:rect.x,y:rect.y,width:rect.width,height:rect.height}:null,
        text:(button?.textContent||'').trim().slice(0,120),
        promptLength:String(prompt||'').length
      });
    }catch(_){}
  }
  async function syncComposerUi(prompt, timeout=1800) {
    const deadline=Date.now()+timeout;
    let current=null;
    do{
      current=composerContext(prompt);
      if(current?.editor){
        try{
          current.editor.focus?.({preventScroll:true});
          current.editor.dispatchEvent(new InputEvent('input',{bubbles:true,composed:true,inputType:'insertText',data:null}));
        }catch(_){try{current.editor.dispatchEvent(new Event('input',{bubbles:true,composed:true}));}catch(__){}}
        try{current.editor.dispatchEvent(new Event('change',{bubbles:true,composed:true}));}catch(_){}
        if(current.exact)return current;
      }
      await sleep(120);
    }while(Date.now()<deadline);
    return current;
  }
  async function waitGenerateButton(prompt, timeout=6500) {
    const deadline=Date.now()+timeout;
    let lastLog=0;
    do {
      const current=composerContext(prompt),button=current?.button;
      if(generateButtonReady(button))return button;
      if(Date.now()-lastLog>1000){logGenerateButtonState('waiting',prompt,current);lastLog=Date.now();}
      await sleep(250);
    }while(Date.now()<deadline);
    // Explicit fresh composer lookup after the dynamic wait; never reload the tab.
    const current=composerContext(prompt),button=current?.button;
    logGenerateButtonState('timeout',prompt,current);
    if(generateButtonReady(button))return button;
    if(current?.exact && button && !generateButtonReady(button))console.warn('[FlowStudio][FLOW_COMPOSER_STATE_NOT_SYNCED] 提示词已写入，但 Flow 生成按钮仍不可点击');
    throw new Error('FLOW_GENERATE_BUTTON_NOT_READY');
  }


  function requestNativeGenerateClick(button, timeout=5000) {
    const r=button?.getBoundingClientRect?.();
    if(!r || r.width<=0 || r.height<=0) return Promise.reject(new Error('FLOW_GENERATE_BUTTON_NO_RECT'));
    const requestId='fs-native-click-'+Date.now()+'-'+Math.random().toString(36).slice(2);
    const x=Math.round(r.left+r.width/2), y=Math.round(r.top+r.height/2);
    return new Promise((resolve,reject)=>{
      let done=false;
      const finish=(fn,v)=>{if(done)return;done=true;clearTimeout(timer);window.removeEventListener('FLOW_STUDIO_NATIVE_CLICK_RESULT',onResult);fn(v);};
      const onResult=ev=>{const d=ev.detail||{};if(String(d.request_id||'')!==requestId)return;d.ok?finish(resolve,d):finish(reject,new Error('FLOW_NATIVE_CLICK_FAILED:'+String(d.error||'unknown')));};
      const timer=setTimeout(()=>finish(reject,new Error('FLOW_NATIVE_CLICK_TIMEOUT')),timeout);
      window.addEventListener('FLOW_STUDIO_NATIVE_CLICK_RESULT',onResult);
      window.dispatchEvent(new CustomEvent('FLOW_STUDIO_NATIVE_CLICK_REQUEST',{detail:{request_id:requestId,x,y}}));
    });
  }

  async function safeGenerateClick(prompt) {
    const current=composerContext(prompt),button=current?.button;
    logGenerateButtonState('before_click',prompt,current);
    if(!generateButtonReady(button))throw new Error('FLOW_GENERATE_BUTTON_STALE_OR_DISABLED');
    try{button.scrollIntoView?.({block:'center',inline:'center',behavior:'instant'});}catch(_){}
    await requestNativeGenerateClick(button);
    console.info('[FlowStudio][CLICK_ATTEMPT]',{method:'native_cdp_click',ariaLabel:button.getAttribute?.('aria-label')||'',type:button.getAttribute?.('type')||''});
    return button;
  }
  async function execute(detail) {
    const {instance,service} = context();
    if(detail.recovery_key){
      const saved=safeRecoveryRead(detail.recovery_key);
      if(saved){
        const ticket=JSON.parse(saved);
        if(ticket.prompt===detail.prompt&&Array.isArray(ticket.acceptedIds)&&ticket.acceptedIds.length===1)
          return {method:'recovered_generation_response',generation_ids:ticket.acceptedIds};
        const ids=FlowStudioResults.exactPromptVideoIds(mediaList(instance),ticket.prompt,ticket.excludedIds||[]);
        if(ticket.prompt===detail.prompt&&ids.length===1)return {method:'recovered_catalog_identity',generation_ids:ids};
        throw Error('SUBMISSION_UNCONFIRMED: 此任务已有点击记录，等待恢复视频绑定，不会再次生成');
      }
    }
    validateDuration(detail);
    if (!String(detail.prompt || '').trim()) throw new Error('EMPTY_PROMPT');
    const mode=detail.mode || 'VIDEO_FRAMES';
    const catalog=mediaList(instance);
    const wantedName=normal(detail.image_name),requestedId=String(detail.image_id||'');
    const derived=detail.open_eye_reference===true;
    const wantsReference=!!wantedName || (derived && !!requestedId);
    const nameMatches=wantsReference?catalog.filter(x=>x.type==='IMAGE' && (derived?String(x.id)===requestedId:normal(x.displayName)===wantedName)):[];
    const exactMatches=requestedId?nameMatches.filter(x=>String(x.id||'')===requestedId):nameMatches;
    let item=null;
    if(exactMatches.length===1)item=exactMatches[0];
    else if(requestedId && exactMatches.length===0 && nameMatches.length===1){
      // The upload placeholder and final Flow asset can have different ids. Exact filename
      // remains authoritative only when it is unique, so this cannot silently bind a duplicate.
      item=nameMatches[0];
      console.info('[FlowStudio][IMAGE_ID_REBOUND_BY_NAME]',{name:String(item.displayName||detail.image_name||''),previous_id:requestedId,current_id:String(item.id||'')});
    }else if(nameMatches.length>1)throw new Error('AMBIGUOUS_IMAGE_NAME：同名图片超过一张，请清理重复素材');
    if(wantsReference && !item)throw new Error('IMAGE_NOT_UPLOADED:'+detail.image_name);
    if(!wantsReference)throw new Error('IMAGE_NOT_UPLOADED:未指定参考图片');
    const select = item?selectMethod(instance):null;
    // The input reference must be a finished Flow image asset before VIDEO submission.
    if(item && typeof waitExistingFlowImageAssetReady==='function')item=await waitExistingFlowImageAssetReady(instance,item,20000);
    if (typeof service.clear !== 'function') throw new Error('FLOW_CLEAR_METHOD_NOT_FOUND');
    const priorPreviews=new Map(composerPreviews(composerContext()).map(p=>[p.node,p.src]));
    service.clear();
    await configure(service,detail);
    const editor=editorSignal(service), key=Object.keys(editor())[0];
    const beforeSelection=stateSnapshot(service);
    let targetIdentities=item?attachmentIdentities(item,mediaList(instance)):new Set();

    // v0.9.52: FRAME keeps its existing first-frame path. MATERIAL now mirrors the
    // stable part of FRAME: use the already-uploaded Flow IMAGE asset + Flow's own
    // select(item) handler. Local file drag/drop into VIDEO_REFERENCES is deliberately
    // forbidden because it can create a grey/error placeholder instead of a valid asset.
    let selectedKey=null,lastSnapshot,beforeSelectionForBinding=beforeSelection,materialSelectAttempt=0;
    if(mode==='VIDEO_FRAMES'){
      await select(item);
      const deadlineAttach=Date.now()+5000;
      do{
        lastSnapshot=stateSnapshot(service);
        selectedKey=firstFrameMatches(service,targetIdentities)?'firstFrame':(referencePreview(item,targetIdentities,priorPreviews)?'composerPreview':null);
        if(selectedKey)break;
        await sleep(100);
      }while(Date.now()<deadlineAttach);
      if(!selectedKey)throw new Error('REFERENCE_STATE_NOT_DETECTED:'+detail.image_name+'; identity_candidates='+targetIdentities.size+'; before='+JSON.stringify(stateShapes(beforeSelection))+'; after='+JSON.stringify(stateShapes(lastSnapshot)));
    }else{
      const result=await selectMaterialAssetLikeFrame({service,select,item,targetIdentities,editor,key,detail});
      selectedKey=result.selectedKey;lastSnapshot=result.lastSnapshot;
      beforeSelectionForBinding=result.beforeSelection;materialSelectAttempt=result.attempt;
    }
    // FRAME keeps its original strict mode confirmation. MATERIAL deliberately does not:
    // Flow may internally transition away from the literal VIDEO_REFERENCES string after
    // native asset selection, and the user requested that this check no longer block jobs.
    if (mode==='VIDEO_FRAMES' && signal(service,v => modes.includes(v))() !== mode) throw new Error('FLOW_MODE_NOT_CONFIRMED:'+mode);
    let endIdentities=new Set();
    if(detail.end_image_name){
      if(mode!=='VIDEO_FRAMES')throw Error('AUX_REQUIRES_FRAME_MODE');
      const ends=mediaList(instance).filter(x=>x.type==='IMAGE'&&normal(x.displayName)===normal(detail.end_image_name));
      if(ends.length!==1)throw Error('AUX_END_IMAGE_NOT_UNIQUE');
      const endpoint=await waitExistingFlowImageAssetReady(instance,ends[0],20000);
      endIdentities=attachmentIdentities(endpoint,mediaList(instance));
      if(typeof service.lastFrame?.set!=='function')throw Error('AUX_END_FRAME_BINDING_UNAVAILABLE');
      service.lastFrame.set(endpoint);
      if(!hasTarget(service.lastFrame(),endIdentities)||!firstFrameMatches(service,targetIdentities))throw Error('AUX_FRAMES_NOT_CONFIRMED');
    }
    const appliedSettings=await verifySettings(service,detail);
    if (mode==='VIDEO_FRAMES' && !firstFrameMatches(service,targetIdentities) && !referencePreview(item,targetIdentities,priorPreviews)) throw new Error('FIRST_FRAME_NOT_CONFIRMED');
    appliedSettings.mode=mode;
    appliedSettings.image_placement=mode==='VIDEO_REFERENCES'?'REFERENCE_MATERIAL':'FIRST_FRAME';
    if(mode==='VIDEO_REFERENCES')appliedSettings.material_attach_method='flow_native_asset_select';
    if(materialSelectAttempt)appliedSettings.material_select_attempt=materialSelectAttempt;

    // Writing text must not delete MATERIAL-mode media chips. FRAME mode stores its image
    // separately in firstFrame, but VIDEO_REFERENCES may keep the selected material inside
    // the composer editor array itself. Preserve every non-text block while replacing text.
    // v1.7.1: write once, then continue to the Generate button. Flow's rendered
    // editor/model text equality is no longer a submission gate.
    const currentBlocks=Array.isArray(editor()?.[key]) ? editor()[key] : [];
    const attachmentBlocks=mode==='VIDEO_REFERENCES'
      ? currentBlocks.filter(block=>!block || String(block.type||'').toLowerCase()!=='text')
      : [];
    editor.set({[key]:[...attachmentBlocks,{type:'text',content:detail.prompt}]});
    if(typeof syncComposerUi==='function') await syncComposerUi(detail.prompt);

    let materialBinding={ids:new Set(targetIdentities),shapes:[]};
    
    await waitGenerateButton(detail.prompt);
    if(mode==='VIDEO_FRAMES' && !firstFrameMatches(service,targetIdentities) && !referencePreview(item,targetIdentities,priorPreviews,detail.prompt))throw Error('REFERENCE_STATE_NOT_DETECTED:'+detail.image_name);
    if(mode==='VIDEO_REFERENCES' && selectedKey==='flowNativeAssetSelect' && !referencePreview(item,targetIdentities,priorPreviews,detail.prompt,true))throw Error('REFERENCE_STATE_NOT_DETECTED:'+detail.image_name);
    const baselineIds=new Set(mediaList(instance).map(x=>x.id));
    const ticket={
      started:false,prompt:detail.prompt,excludedIds:[...baselineIds],
      requireAux:!!detail.end_image_name,requiredStartIds:[...targetIdentities],requiredEndIds:[...endIdentities],
      requireMaterial:false,
      requiredMaterialPrimaryId:mode==='VIDEO_REFERENCES'?String(item.id||''):'',
      requiredMaterialIds:mode==='VIDEO_REFERENCES'?[...targetIdentities]:[],
      requiredMaterialBindingIds:mode==='VIDEO_REFERENCES'?[...materialBinding.ids]:[],
      materialBindingShapes:mode==='VIDEO_REFERENCES'?materialBinding.shapes:[],
      imageName:detail.image_name||'',recoveryKey:detail.recovery_key||'',expectedMode:mode,
      materialRequestConfirmed:false,materialRequestBlocked:false,materialBindingProtectionDisabled:mode==='VIDEO_REFERENCES'
    }; pending=ticket;
    if(detail.recovery_key)safeRecoveryWrite(detail.recovery_key,{prompt:detail.prompt,excludedIds:ticket.excludedIds});
    {
      const current=composerContext(detail.prompt),button=current?.button;
      if(typeof logGenerateButtonState==='function')logGenerateButtonState('native_click_prepare',detail.prompt,current);
      if(!generateButtonReady(button))throw new Error('FLOW_GENERATE_BUTTON_STALE_OR_DISABLED');
      await safeGenerateClick(detail.prompt);
    }
    const deadline=Date.now()+60000;
    const fallbackAt=[5000,15000,30000,50000].map(ms=>Date.now()+ms);let fallbackIndex=0;
    try {
      while (Date.now()<deadline) {
        if (ticket.failure) throw new Error(ticket.failure);
        if (ticket.accepted) return {method:ticket.responseAccepted?'flow_generation_response':'flow_native_state',image_id:item?.id||'',attachment_signal:selectedKey,settings:appliedSettings,generation_ids:ticket.accepted};
        // Response mediaId is authoritative. Catalog/prompt matching is now a sparse recovery
        // fallback only, instead of a 150ms polling loop that grows heavier as Collection grows.
        if(fallbackIndex<fallbackAt.length && Date.now()>=fallbackAt[fallbackIndex]){
          fallbackIndex++;
          const ids=FlowStudioResults.exactPromptVideoIds(mediaList(instance),detail.prompt,ticket.excludedIds);
          if(ids.length===1){ticket.accepted=ids;ticket.started=true;trackWaitingVideoIds(ids,'catalog_recovery');}
        }
        await sleep(100);
      }
      const observedPromptIds=FlowStudioResults.exactPromptVideoIds(mediaList(instance),detail.prompt,ticket.excludedIds);
      if(observedPromptIds.length===1){trackWaitingVideoIds(observedPromptIds,'catalog_recovery_final');return {method:'flow_catalog_recovery',image_id:item?.id||'',attachment_signal:selectedKey,settings:appliedSettings,generation_ids:observedPromptIds};}
      // A real native click has already happened. Missing/late identity evidence is uncertain,
      // never proof that Flow did not receive the click, so automatic re-click is forbidden.
      throw new Error('SUBMISSION_UNCONFIRMED：已点击生成但未及时收到 generation response，保留恢复记录并禁止重复点击');
    } finally { if (pending===ticket) pending=null; if(!execute._generateButton?.isConnected)execute._generateButton=null; }
  }

  // Open-eye edits have their own ledger and never enter the VIDEO result bridge.
  // Persist before clicking; uncertain edits are polled, never clicked a second time.
  async function ensureOpenEye(detail) {
    const {instance,service}=context();
    if(!/^[a-f0-9]{64}$/.test(String(detail.eye_key||'')))throw Error('INVALID_EYE_REFERENCE_KEY');
    const storageKey='flowstudio.open-eye.v1.'+detail.eye_key;
    const prompt=String(detail.prompt||'');
    if(!prompt.trim())throw Error('EMPTY_EYE_PROMPT');
    const raw=localStorage.getItem(storageKey),saved=raw?JSON.parse(raw):null;
    const catalog=mediaList(instance);
    if(saved && saved.prompt!==prompt)throw Error('EYE_REFERENCE_PROMPT_CHANGED');
    const ids=FlowStudioResults.exactPromptVideoIds(catalog,prompt,saved?.excluded||[],'IMAGE');
    if(ids.length>1)throw Error('EYE_REFERENCE_AMBIGUOUS');
    const found=ids.length===1?catalog.find(x=>x.id===ids[0] && x.type==='IMAGE'):null;
    if(found){
      const flags=flowAssetFlags(found);
      if(flags.error)throw Error('睁眼参考图生成失败，请在 Flow 中检查该图片任务');
      // A generic IMAGE placeholder / thumbnail is not a completed generated edit.
      if(!flags.loading && flags.ready && mediaURL(found)){
        localStorage.setItem(storageKey,JSON.stringify({...(saved||{}),prompt,image_id:found.id,ready:true}));
        return {ready:true,image_id:found.id,image_name:found.displayName||'',image_url:mediaURL(found)};
      }
      return {ready:false,state:'generating'};
    }
    if(saved)return {ready:false,state:'awaiting_identity'};
    const original=catalog.find(x=>x.type==='IMAGE' && String(x.id)===String(detail.image_id));
    if(!original)throw Error('EYE_REFERENCE_SOURCE_MISSING');
    const item=await waitExistingFlowImageAssetReady(instance,original,15000);
    const identities=attachmentIdentities(item,catalog);
    const before=new Map(composerPreviews(composerContext()).map(p=>[p.node,p.src]));
    service.clear();
    signal(service,v=>modes.includes(v)).set('IMAGE_EDIT');
    signal(service,v=>(models.includes(v)||(typeof v==='string'&&/omni/i.test(v)))).set('banana2');
    service.setAspectRatio(aspectValue(detail.aspect_ratio));
    constructorSignal(service,/this\.(\w+)=[^;]+1\);/,'outputs').set(1);
    await selectMethod(instance)(item);
    const editor=editorSignal(service),key=Object.keys(editor())[0];
    const attachments=(Array.isArray(editor()?.[key])?editor()[key]:[]).filter(x=>x?.type!=='text');
    editor.set({[key]:[...attachments,{type:'text',content:prompt}]});
    await syncComposerUi(prompt);
    await waitGenerateButton(prompt);
    if(!['IMAGE','IMAGE_EDIT'].includes(signal(service,v=>modes.includes(v))()))throw Error('EYE_IMAGE_MODE_NOT_CONFIRMED');
    if(signal(service,v=>(models.includes(v)||(typeof v==='string'&&/omni/i.test(v))))()!=='banana2')throw Error('EYE_IMAGE_MODEL_NOT_CONFIRMED');
    const attached=[...stateSnapshot(service).values()].some(x=>hasTarget(x.data,identities));
    if(!attached && !referencePreview(item,identities,before,prompt))throw Error('EYE_REFERENCE_NOT_ATTACHED');
    const record={prompt,source_id:item.id,excluded:catalog.map(x=>x.id),attempted_at:Date.now()};
    localStorage.setItem(storageKey,JSON.stringify(record));
    if(!localStorage.getItem(storageKey))throw Error('EYE_LEDGER_UNAVAILABLE');
    await safeGenerateClick(prompt);
    return {ready:false,state:'submitted'};
  }
  async function downloadAuxNative(detail){
    const id=String(detail.image_id||'');
    if(!/^[A-Za-z0-9_-]{8,}$/.test(id))throw Error('INVALID_AUX_ID');
    const cards=[...document.querySelectorAll('[data-id],[data-media-id],[data-generation-id]')].filter(el=>[el.dataset.id,el.dataset.mediaId,el.dataset.generationId].includes(id)&&renderedNode(el));
    if(cards.length!==1)throw Error('AUX_NATIVE_RESULT_CARD_NOT_FOUND');
    const buttons=[...cards[0].querySelectorAll('button,[role="button"]')].filter(el=>/download|下载/i.test((el.getAttribute('aria-label')||'')+' '+el.textContent));
    if(buttons.length!==1)throw Error('AUX_NATIVE_DOWNLOAD_BUTTON_NOT_FOUND');
    buttons[0].click();await sleep(300);
    const options=[...document.querySelectorAll('[role="menuitem"],[role="option"],button')].filter(el=>renderedNode(el)&&/\b[24]K\b/i.test(el.textContent||''));
    const two=options.filter(el=>/\b2K\b/i.test(el.textContent||'')),four=options.filter(el=>/\b4K\b/i.test(el.textContent||''));
    const selected=two.length===1?two[0]:four.length===1?four[0]:null;
    if(!selected)throw Error('AUX_NATIVE_2K_OPTION_NOT_FOUND');
    const resolution=/\b2K\b/i.test(selected.textContent)?'2K':'4K';selected.click();
    return {resolution};
  }
  window.addEventListener('FLOW_STUDIO_MAIN_COMMAND', async ev => {
    const d=ev.detail || {};
    if (!d.request_id) return;
    const reply = data => window.dispatchEvent(new CustomEvent('FLOW_STUDIO_MAIN_RESULT',{detail:{request_id:d.request_id,...data}}));
    if(d.action==='recover_video_identity'){
      try{
        let ids=FlowStudioResults.exactPromptVideoIds(mediaList(context().instance),d.prompt,[]);
        if(d.video_id)ids=ids.filter(id=>id===d.video_id);
        else {
          const saved=safeRecoveryRead(d.recovery_key);
          if(!saved)return reply({ok:true,ids:[],reason:'explicit_video_required'});
          const ticket=JSON.parse(saved);
          if(ticket.prompt!==d.prompt)throw Error('RECOVERY_PROMPT_CHANGED');
          if(Array.isArray(ticket.acceptedIds)&&ticket.acceptedIds.length===1)ids=ticket.acceptedIds;
          else ids=ids.filter(id=>!(ticket.excludedIds||[]).includes(id));
        }
        return reply({ok:true,ids,reason:ids.length===1?'matched':'ambiguous_or_not_found'});
      }catch(e){return reply({ok:false,error:String(e.message||e)});}
    }
    if(d.action==='scan_video_results')return reply({ok:true,...completedVideos(d.ids)});
    if (d.action === 'scan_media') {
      try { reply({ok:true,media:scan()}); } catch(e) { reply({ok:false,error:String(e.message || e)}); }
      return;
    }
    if(d.action==='download_aux_native'){
      if(busy)return reply({ok:false,error:'ENGINE_BUSY'});busy=true;
      try{reply({ok:true,...await downloadAuxNative(d)});}catch(e){reply({ok:false,error:String(e.message||e)});}finally{busy=false;}return;
    }
    if(d.action==='ensure_open_eye'){
      if(busy)return reply({ok:false,error:'ENGINE_BUSY'});
      busy=true;
      try{
        if(!navigator.locks)throw Error('EYE_REFERENCE_LOCK_UNAVAILABLE');
        const result=await navigator.locks.request('flowstudio.eye.'+d.eye_key,()=>ensureOpenEye(d));
        reply({ok:true,...result});
      }catch(e){reply({ok:false,error:String(e.message||e)});}finally{busy=false;}
      return;
    }
    if (d.action !== 'submit_task') return reply({ok:false,error:'UNKNOWN_ACTION'});
    if (busy) return reply({ok:false,error:'ENGINE_BUSY'});
    busy=true;
    try { reply({ok:true,...await execute(d)}); }
    catch(e) { reply({ok:false,error:String(e.message || e)}); }
    finally { busy=false; }
  });
})();
