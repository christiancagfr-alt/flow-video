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
  const normal = value => String(value || '').normalize('NFC').trim().toLowerCase();
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
  const models = ['abra','veo_3_1_lite','veo_3_1_fast','veo_3_1_quality','veo_3_1_lite_low_priority'];
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
    const model=detail.model || 'veo_3_1_lite_low_priority';
    if (signal(service,v=>models.includes(v))()!==model) throw new Error('FLOW_MODEL_NOT_CONFIRMED');
    const materialMode=(detail.mode||'VIDEO_FRAMES')==='VIDEO_REFERENCES';
    const effectiveDuration=materialMode?8:Number(detail.duration||8);
    // MATERIAL / VIDEO_REFERENCES is fixed by Flow at 8s. Flow may keep the last
    // FRAME duration in its hidden signal even though MATERIAL exposes no duration picker.
    // Force the hidden duration signal to 8 and verify it after asset selection; never use
    // the FRAME duration picker in MATERIAL mode.
    const durationSignal=constructorSignal(service,/this\.(\w+)=[^;]+8\);/,'duration');
    if (materialMode && Number(durationSignal())!==8) durationSignal.set(8);
    if (Number(durationSignal())!==effectiveDuration) throw new Error('FLOW_DURATION_NOT_CONFIRMED:expected='+effectiveDuration+';actual='+String(durationSignal()));
    // 选择参考图后 Flow 可能把“每次生成数量”重置为界面默认值（如 x2）；提交前再强制为 1，避免一次提交生成两个视频。
    try{const _o=constructorSignal(service,/this\.(\w+)=[^;]+1\);/,'outputs');if(Number(_o())!==1)_o.set(1);}catch(_){}
    return {aspect_ratio:expected,model,duration:effectiveDuration,duration_policy:materialMode?'FLOW_FIXED_8S':'SELECTABLE'};
  }
  function configure(service,detail) {
    const mode = detail.mode || 'VIDEO_FRAMES';
    if (!['VIDEO_REFERENCES','VIDEO_FRAMES'].includes(mode)) throw new Error('UNSUPPORTED_MODE:'+mode);
    const model = detail.model || 'veo_3_1_lite_low_priority';
    if (!models.includes(model)) throw new Error('UNSUPPORTED_MODEL:'+model);
    signal(service,v => modes.includes(v)).set(mode);
    if (typeof service.setAspectRatio !== 'function') throw new Error('FLOW_ASPECT_METHOD_NOT_FOUND');
    service.setAspectRatio(aspectValue(detail.aspect_ratio));
    signal(service,v => models.includes(v)).set(model);
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
    let last=null,lastFlags=null;
    const until=Date.now()+timeout;
    while(Date.now()<until){
      const catalog=mediaList(instance);
      const row=catalog.find(x=>x?.type==='IMAGE' && ((id&&String(x.id||'')===id)||(!id&&normal(x.displayName)===name)));
      if(row){
        last=row;
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
    try{modeSignal.set('VIDEO_REFERENCES');}catch(_){}
    let observed=false;try{observed=modeSignal()==='VIDEO_REFERENCES';}catch(_){}
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
    if(ticket.expectedMode==='VIDEO_REFERENCES' && /(?:VIDEO_FRAMES|FIRST_FRAME|FRAME_REFERENCE)/i.test(wholeText))return {ok:false,reason:'wrong_generation_mode'};
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
  // Observe Flow-owned fetch AND XHR; never send generation requests ourselves.
  const originalFetch=window.fetch;
  window.fetch=async function(input,init) {
    const url=typeof input==='string'?input:input?.url||String(input);
    const ticket=pending;
    let requestBody=init?.body;
    if(ticket && requestBody==null && typeof Request!=='undefined' && input instanceof Request){try{requestBody=await input.clone().text();}catch(_){}}
    const generation=generationRequest(url,requestBody,ticket);
    // v0.9.50: MATERIAL requires exact reference-BINDING proof at the real Flow request boundary.
    // A prompt-only request is blocked BEFORE it reaches Flow, even if a stale
    // composer signal incorrectly looked attached immediately before the click.
    // v0.9.57: MATERIAL exact-binding request blocking disabled by user preference.
    // Keep request observation/recovery, but do not reject a Flow-owned request solely because
    // the internal reference shape cannot be proven.
    if(generation && ticket) ticket.materialRequestProtectionDisabled=true;
    if(generation) {ticket.started=true;ticket.requestIds=FlowStudioResults.requestIds(requestBody,ticket.excludedIds);}
    let response;
    try { response=await originalFetch.apply(this,arguments); }
    catch(e) { if(generation && !ticket?.materialRequestBlocked)ticket.uncertain=true; throw e; }
    if(!generation && /(?:video|media|operation|project|collection|batchexecute)/i.test(url)) {
      const copy=response.clone();
      (copy.text?copy.text():copy.json()).then(recordVideoResults).catch(()=>{});
    }
    if(generation) {
      const clone=response.clone();
      (clone.text?clone.text():clone.json()).then(body=>observeResponse(ticket,response.status,body)).catch(()=>{ticket.uncertain=true});
    }
    return response;
  };
  if (typeof XMLHttpRequest!=='undefined') {
    const xhrMeta=new WeakMap(), proto=XMLHttpRequest.prototype;
    const originalOpen=proto.open, originalSend=proto.send;
    proto.open=function(method,url) { xhrMeta.set(this,{method:String(method),url:String(url)}); return originalOpen.apply(this,arguments); };
    proto.send=function(body) {
      const meta=xhrMeta.get(this), ticket=pending;
      const listeners=new AbortController();
      const release=()=>{listeners.abort();xhrMeta.delete(this);};
      this.addEventListener('loadend',release,{once:true});
      this.addEventListener('load',()=>{try{recordVideoResults(this.responseType==='json'?this.response:this.responseText)}catch(_){}},{once:true,signal:listeners.signal});
      if(meta && meta.method.toUpperCase()==='POST' && generationRequest(meta.url,body,ticket)) {
        // Same fail-closed gate for XHR. Do not let Flow receive a MATERIAL
        // generation POST unless the current task's exact image identity is present.
        // v0.9.57: do not abort Flow-owned MATERIAL requests on binding-shape heuristics.
        if(ticket) ticket.materialRequestProtectionDisabled=true;
        ticket.started=true;
        ticket.requestIds=FlowStudioResults.requestIds(body,ticket.excludedIds);
        this.addEventListener('load',()=>{
          try { observeResponse(ticket,this.status,this.responseType==='json'?this.response:this.responseText); }
          catch (_) { ticket.uncertain=true; }
        },{once:true,signal:listeners.signal});
        this.addEventListener('error',()=>{ticket.uncertain=true},{once:true,signal:listeners.signal});
      }
      try{return originalSend.apply(this,arguments);}
      catch(error){release();this.removeEventListener('loadend',release);throw error;}
    };
  }
  function validateDuration(detail) {
    // The generation center submits approved text without a second speech-length gate.
    if ((detail.mode||'VIDEO_FRAMES')==='VIDEO_REFERENCES') {
      detail.duration=8;
      return;
    }
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
          candidates.push({root,editor,button:buttons[0],exact:!!prompt && (editor.value||editor.textContent||'').trim()===prompt.trim(),order:composerNodeOrder.get(editor)});break;
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
    if(current?.exact && button)console.warn('[FlowStudio][FLOW_COMPOSER_STATE_NOT_SYNCED] 提示词已写入，但 Flow 生成按钮仍不可点击');
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

  function safeGenerateClick(prompt) {
    // Always re-query immediately before clicking: Flow may rebuild Angular nodes after
    // attachments/settings/prompt updates. Do one physical-style event chain with ONE click
    // only, avoiding a second automatic click that could duplicate a generation request.
    const current=composerContext(prompt),button=current?.button;
    logGenerateButtonState('before_click',prompt,current);
    if(!generateButtonReady(button))throw new Error('FLOW_GENERATE_BUTTON_STALE_OR_DISABLED');
    try{button.scrollIntoView?.({block:'center',inline:'center',behavior:'instant'});}catch(_){try{button.scrollIntoView?.({block:'center',inline:'center'});}catch(__){}}
    try{button.focus?.({preventScroll:true});}catch(_){try{button.focus?.();}catch(__){}}
    const common={bubbles:true,cancelable:true,composed:true,view:window,button:0,buttons:1};
    try{button.dispatchEvent(new PointerEvent('pointerdown',{...common,pointerId:1,pointerType:'mouse',isPrimary:true}));}catch(_){}
    try{button.dispatchEvent(new MouseEvent('mousedown',common));}catch(_){}
    try{button.dispatchEvent(new PointerEvent('pointerup',{...common,buttons:0,pointerId:1,pointerType:'mouse',isPrimary:true}));}catch(_){}
    try{button.dispatchEvent(new MouseEvent('mouseup',{...common,buttons:0}));}catch(_){}
    button.click();
    console.info('[FlowStudio][CLICK_ATTEMPT]',{method:'pointer_mouse_plus_single_native_click',ariaLabel:button.getAttribute?.('aria-label')||'',type:button.getAttribute?.('type')||''});
    return button;
  }
  async function execute(detail) {
    const {instance,service} = context();
    if(detail.recovery_key){
      const saved=safeRecoveryRead(detail.recovery_key);
      if(saved){
        const ticket=JSON.parse(saved),ids=FlowStudioResults.exactPromptVideoIds(mediaList(instance),ticket.prompt,ticket.excludedIds);
        if(ticket.prompt===detail.prompt&&ids.length===1)return {method:'recovered_catalog_identity',generation_ids:ids};
        throw Error('SUBMISSION_UNCONFIRMED: 此任务已有点击记录，等待恢复视频绑定，不会再次生成');
      }
    }
    validateDuration(detail);
    if (!String(detail.prompt || '').trim()) throw new Error('EMPTY_PROMPT');
    const catalog=mediaList(instance);
    const matches = catalog.filter(x => x.type === 'IMAGE' && (detail.image_id ? x.id === detail.image_id && normal(x.displayName) === normal(detail.image_name) : normal(x.displayName) === normal(detail.image_name)));
    if (matches.length !== 1) throw new Error(matches.length ? 'AMBIGUOUS_IMAGE_NAME：同名图片超过一张，请清理重复素材' : 'IMAGE_NOT_UPLOADED:'+detail.image_name);
    let item = matches[0]; const select = selectMethod(instance);
    // All generation modes must consume a finished Flow IMAGE asset. A catalog placeholder
    // created immediately after drag/drop is not permission to start the first submission.
    if(typeof waitExistingFlowImageAssetReady==='function')item=await waitExistingFlowImageAssetReady(instance,item,20000);
    if (typeof service.clear !== 'function') throw new Error('FLOW_CLEAR_METHOD_NOT_FOUND');
    const priorPreviews=new Map(composerPreviews(composerContext()).map(p=>[p.node,p.src]));
    service.clear();
    configure(service,detail);
    const editor=editorSignal(service), key=Object.keys(editor())[0];
    const beforeSelection=stateSnapshot(service);
    let targetIdentities=attachmentIdentities(item,mediaList(instance));
    const mode=detail.mode || 'VIDEO_FRAMES';

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
      const materialResult=await selectMaterialAssetLikeFrame({service,select,item,targetIdentities,editor,key,detail});
      selectedKey=materialResult.selectedKey;
      lastSnapshot=materialResult.lastSnapshot;
      beforeSelectionForBinding=materialResult.beforeSelection;
      materialSelectAttempt=materialResult.attempt;
    }
    // FRAME keeps its original strict mode confirmation. MATERIAL deliberately does not:
    // Flow may internally transition away from the literal VIDEO_REFERENCES string after
    // native asset selection, and the user requested that this check no longer block jobs.
    if (mode==='VIDEO_FRAMES' && signal(service,v => modes.includes(v))() !== mode) throw new Error('FLOW_MODE_NOT_CONFIRMED:'+mode);
    const appliedSettings=await verifySettings(service,detail);
    if (mode==='VIDEO_FRAMES' && !firstFrameMatches(service,targetIdentities) && !referencePreview(item,targetIdentities,priorPreviews)) throw new Error('FIRST_FRAME_NOT_CONFIRMED');
    appliedSettings.mode=mode; appliedSettings.image_placement=(mode==='VIDEO_REFERENCES'?'REFERENCE_MATERIAL':'FIRST_FRAME'); if(mode==='VIDEO_REFERENCES')appliedSettings.material_attach_method='flow_native_asset_select'; if(materialSelectAttempt)appliedSettings.material_select_attempt=materialSelectAttempt;

    // Writing text must not delete MATERIAL-mode media chips. FRAME mode stores its image
    // separately in firstFrame, but VIDEO_REFERENCES may keep the selected material inside
    // the composer editor array itself. Preserve every non-text block while replacing text.
    const currentBlocks=Array.isArray(editor()?.[key]) ? editor()[key] : [];
    const attachmentBlocks=mode==='VIDEO_REFERENCES'
      ? currentBlocks.filter(block=>!block || String(block.type||'').toLowerCase()!=='text')
      : [];
    editor.set({[key]:[...attachmentBlocks,{type:'text',content:detail.prompt}]});

    const promptText=()=>{
      const blocks=Array.isArray(editor()?.[key]) ? editor()[key] : [];
      return blocks.filter(x=>String(x?.type||'').toLowerCase()==='text' || typeof x?.content==='string').map(x=>x?.content||'').join('');
    };
    if (promptText() !== detail.prompt) throw new Error('PROMPT_WRITE_NOT_CONFIRMED');
    // Flow's current Angular composer may keep submit disabled until its rendered editor/form
    // receives a UI-side input/change cycle, even though the internal editor signal is correct.
    if(typeof syncComposerUi==='function')await syncComposerUi(detail.prompt);

    let materialBinding={ids:new Set(targetIdentities),shapes:[]};
    if(mode==='VIDEO_REFERENCES') {
      // v0.9.57: no MATERIAL binding protection. Flow-native select(item) above remains the
      // attachment action. We only collect best-effort diagnostics here and never block
      // Generate because a minified internal signal/fingerprint cannot be proven.
      if(promptText()!==detail.prompt) throw new Error('PROMPT_CHANGED_BEFORE_SUBMIT');
      // No post-select/pre-submit MATERIAL mode gate. The native Flow select(item) action is
      // allowed to control its own internal mode representation without plugin-side vetoes.
      try { materialBinding=captureMaterialBinding(service,editor,key,selectedKey,targetIdentities); }
      catch (_) { materialBinding={ids:new Set(targetIdentities),shapes:[]}; }
      appliedSettings.material_binding_protection='disabled';
    }
    await waitGenerateButton(detail.prompt);
    if(mode==='VIDEO_FRAMES' && !firstFrameMatches(service,targetIdentities) && !referencePreview(item,targetIdentities,priorPreviews,detail.prompt))throw Error('REFERENCE_STATE_NOT_DETECTED:'+detail.image_name);
    if(mode==='VIDEO_REFERENCES' && selectedKey==='flowNativeAssetSelect' && !referencePreview(item,targetIdentities,priorPreviews,detail.prompt,true))throw Error('REFERENCE_STATE_NOT_DETECTED:'+detail.image_name);
    try{const _o=constructorSignal(service,/this\.(\w+)=[^;]+1\);/,'outputs');if(Number(_o())!==1)_o.set(1);}catch(_){}
    const baselineIds=new Set(mediaList(instance).map(x=>x.id));
    const ticket={
      started:false,prompt:detail.prompt,excludedIds:[...baselineIds],
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
      try{button.scrollIntoView?.({block:'center',inline:'center',behavior:'instant'});}catch(_){try{button.scrollIntoView?.({block:'center',inline:'center'});}catch(__){}}
      try{button.focus?.({preventScroll:true});}catch(_){try{button.focus?.();}catch(__){}}
      // Let scroll/layout and fixed overlays settle before measuring the CDP click point.
      await sleep(90);
      try{
        const nativeResult=await requestNativeGenerateClick(button,5000);
        console.info('[FlowStudio][CLICK_ATTEMPT]',{method:nativeResult?.method||'chrome_debugger_native_click',x:nativeResult?.x,y:nativeResult?.y,overlayBypassed:!!nativeResult?.overlay_bypassed,hit:nativeResult?.hit||null});
      }catch(nativeError){
        console.warn('[FlowStudio][NATIVE_CLICK_FALLBACK]',String(nativeError?.message||nativeError));
        if(typeof safeGenerateClick==='function')safeGenerateClick(detail.prompt);
        else button.click();
      }
    }
    const deadline=Date.now()+60000;
    try {
      while (Date.now()<deadline) {
        if (ticket.failure) throw new Error(ticket.failure);
        if(!ticket.accepted){const ids=FlowStudioResults.exactPromptVideoIds(mediaList(instance),detail.prompt,ticket.excludedIds);if(ids.length===1)ticket.accepted=ids;}
        if (ticket.accepted) return {method:'flow_native_state',image_id:item.id,attachment_signal:selectedKey,settings:appliedSettings,generation_ids:ticket.accepted};
        await sleep(150);
      }
      const observedPromptIds=FlowStudioResults.exactPromptVideoIds(mediaList(instance),detail.prompt,ticket.excludedIds);
      if(!ticket.started && observedPromptIds.length===0){
        // No Flow generation POST/XHR and no new prompt-matching video object were
        // observed at all. This is safe to retry and must NOT become “已提交”.
        safeRecoveryRemove(detail.recovery_key);
        throw new Error('FLOW_SUBMISSION_NOT_STARTED：已点击按钮但 Flow 未发起生成请求，可安全重试');
      }
      throw new Error('SUBMISSION_UNCONFIRMED：Flow 已发起生成请求但未收到确认，保留恢复记录并禁止重复点击');
    } finally { if (pending===ticket) pending=null; if(!execute._generateButton?.isConnected)execute._generateButton=null; }
  }
  window.addEventListener('FLOW_STUDIO_MAIN_COMMAND', async ev => {
    const d=ev.detail || {};
    if (!d.request_id) return;
    const reply = data => window.dispatchEvent(new CustomEvent('FLOW_STUDIO_MAIN_RESULT',{detail:{request_id:d.request_id,...data}}));
    if(d.action==='recover_video_identity'){
      try{
        const _items=mediaList(context().instance);
        let ids=FlowStudioResults.exactPromptVideoIds(_items,d.prompt,[]);
        let _excluded=[];
        if(d.video_id)ids=ids.filter(id=>id===d.video_id);
        else {
          const saved=safeRecoveryRead(d.recovery_key);
          if(!saved)return reply({ok:true,ids:[],reason:'explicit_video_required'});
          const ticket=JSON.parse(saved);
          if(ticket.prompt!==d.prompt)throw Error('RECOVERY_PROMPT_CHANGED');
          _excluded=ticket.excludedIds||[];
          ids=ids.filter(id=>!_excluded.includes(id));
        }
        let reason=ids.length===1?'matched':'ambiguous_or_not_found',diag=null;
        // 同一提示词在点击后出现多个完全相同的视频（重复生成）：它们都属于该任务，取列表中的第一个。
        if(ids.length>1 && !d.video_id){ids=[ids[0]];reason='matched_duplicate_first';}
        if(ids.length!==1 && !d.video_id){
          // 兜底：忽略空白/标点差异后再匹配（仍要求不在点击前的列表中、且结果唯一）；同时输出诊断。
          const norm=v=>String(v||'').normalize('NFKC').replace(/[\s\p{P}\p{S}]+/gu,'').toLowerCase();
          const wanted=norm(d.prompt),omit=new Set(_excluded),fuzzy=new Set(),fresh=[];
          const skipKey=/history|previous|reference|input|thumbnail|poster|displayName|title/i;
          for(const item of _items||[]){
            if(item?.type!=='VIDEO'||typeof item.id!=='string'||omit.has(item.id))continue;
            const strs=[];let budget=1500;const seen=new WeakSet();
            (function walk(v,depth){
              if(--budget<0||depth>12)return;
              if(typeof v==='string'){if(v.length>=30)strs.push(v);return;}
              if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
              for(const [k,c] of Object.entries(v))if(!skipKey.test(k))walk(c,depth+1);
            })(item,0);
            fresh.push({id:item.id,strs});
            if(wanted.length>=30&&strs.some(x=>{const n=norm(x);return n===wanted||(n.length>=120&&wanted.length>=120&&n.startsWith(wanted.slice(0,80))&&n.endsWith(wanted.slice(-80)));}))fuzzy.add(item.id);
          }
          diag={wanted_len:wanted.length,new_video_count:fresh.length,
            samples:fresh.slice(0,3).map(f=>{const best=f.strs.sort((a,b)=>b.length-a.length)[0]||'';return {id:f.id.slice(0,8),len:norm(best).length,head:best.slice(0,40),tail:best.slice(-40)};}),
            wanted_head:String(d.prompt||'').slice(0,40),wanted_tail:String(d.prompt||'').slice(-40)};
          if(fuzzy.size>=1){ids=[[...fuzzy][0]];reason=fuzzy.size===1?'matched_fuzzy':'matched_fuzzy_duplicate_first';}
        }
        return reply({ok:true,ids,reason,diag});
      }catch(e){return reply({ok:false,error:String(e.message||e)});}
    }
    if(d.action==='scan_video_results')return reply({ok:true,...completedVideos(d.ids)});
    if (d.action === 'scan_media') {
      try { reply({ok:true,media:scan()}); } catch(e) { reply({ok:false,error:String(e.message || e)}); }
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
