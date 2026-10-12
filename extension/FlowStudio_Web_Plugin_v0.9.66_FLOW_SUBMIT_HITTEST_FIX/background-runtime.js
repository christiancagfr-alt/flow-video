// One owned debugger session per working Flow tab. Never activates a tab/window.
// Upload drag, Enter and lifecycle maintenance share a serial lane so they cannot
// detach each other's session. No task is resubmitted by this module.
(() => {
  const sessions=new Map(), lanes=new Map(), dismissed=new Map();
  let logger=()=>{};
  const log=(event,detail)=>{try{logger(event,detail);}catch(_){}};
  function serial(tabId,fn){
    const previous=lanes.get(tabId)||Promise.resolve();
    const promise=previous.catch(()=>{}).then(fn);
    const tail=promise.catch(()=>{});lanes.set(tabId,tail);
    tail.finally(()=>{if(lanes.get(tabId)===tail)lanes.delete(tabId);});
    return promise;
  }
  async function acquire(tabId){
    let entry=sessions.get(tabId);
    if(entry)return entry;
    const tab=await chrome.tabs.get(tabId);
    if(!/^https:\/\/flow\.google\.com\//.test(tab.url||''))throw Error('NOT_FLOW_TAB');
    // v0.9.64: a prior debugger detach must not permanently poison this Flow tab.
    // Re-acquire on demand before the next native action. If another debugger really owns
    // the tab, chrome.debugger.attach will still fail normally and the caller can fall back.
    if(dismissed.has(tabId)){
      const previous=dismissed.get(tabId);dismissed.delete(tabId);
      log('background_guard_reacquire',{tab_id:tabId,previous_reason:previous?.reason||'canceled_by_user'});
    }
    const target={tabId};
    await chrome.debugger.attach(target,'1.3');
    entry={target,held:false,configured:false,autoDiscardable:tab.autoDiscardable,attachedAt:Date.now(),lastError:''};
    sessions.set(tabId,entry);
    return entry;
  }
  async function configure(entry){
    // A background tab can be throttled without tab.frozen ever being true.
    // The emulation belongs to this session and must remain attached while busy.
    try{
      await chrome.debugger.sendCommand(entry.target,'Emulation.setFocusEmulationEnabled',{enabled:true});
      await chrome.debugger.sendCommand(entry.target,'Page.setWebLifecycleState',{state:'active'});
      entry.configured=true;entry.lastError='';
    }catch(error){entry.configured=false;entry.lastError=String(error?.message||error);throw error;}
  }
  async function releaseInside(tabId){
    const entry=sessions.get(tabId);if(!entry)return;
    // Restore flags only for a session owned by this module.
    try{await chrome.debugger.sendCommand(entry.target,'Emulation.setFocusEmulationEnabled',{enabled:false});}catch(_){}
    entry.releasing=true;
    try{await chrome.debugger.detach(entry.target);}catch(_){}
    sessions.delete(tabId);
    if(typeof entry.autoDiscardable==='boolean')try{await chrome.tabs.update(tabId,{autoDiscardable:entry.autoDiscardable});}catch(_){}
  }
  async function hold(tabId,command){
    return serial(tabId,async()=>{
      const entry=await acquire(tabId);entry.held=true;entry.command=command;
      await configure(entry);
      await chrome.tabs.update(tabId,{autoDiscardable:false});
      return {ok:true,attached:true,focus_emulated:true};
    });
  }
  async function run(tabId,fn){
    return serial(tabId,async()=>{
      const entry=await acquire(tabId);
      try{await configure(entry);return await fn(entry.target);}
      finally{if(!entry.held)await releaseInside(tabId);}
    });
  }
  function release(tabId){return serial(tabId,()=>releaseInside(tabId));}
  chrome.debugger.onDetach.addListener((target,reason)=>{
    const entry=sessions.get(target.tabId);if(!entry)return;
    sessions.delete(target.tabId);
    if(reason==='canceled_by_user' && !entry.releasing)dismissed.set(target.tabId,{reason,time:Date.now()});
    if(typeof entry.autoDiscardable==='boolean')void chrome.tabs.update(target.tabId,{autoDiscardable:entry.autoDiscardable}).catch(()=>{});
    log('background_guard_detached',{tab_id:target.tabId,reason,command_id:entry.command||''});
  });
  chrome.tabs.onRemoved.addListener(tabId=>{sessions.delete(tabId);dismissed.delete(tabId);});
  chrome.tabs.onUpdated.addListener((tabId,change)=>{
    if(change.url&&!/^https:\/\/flow\.google\.com\//.test(change.url))void release(tabId);
  });
  globalThis.FlowStudioBackground={hold,run,release,
    setLogger(fn){logger=fn;},
    ids(){return [...sessions.keys()];},
    diagnostics(){return [...sessions].map(([tab_id,s])=>({tab_id,command_id:s.command||'',attached:true,focus_emulated:s.configured,last_error:s.lastError,attached_at:s.attachedAt}));}
  };
})();
