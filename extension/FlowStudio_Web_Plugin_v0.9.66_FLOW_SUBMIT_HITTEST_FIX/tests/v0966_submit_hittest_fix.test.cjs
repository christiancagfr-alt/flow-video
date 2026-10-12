const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'content.js'),'utf8');
const start=source.indexOf('  function nativeClickNodeInfo');
const end=source.indexOf("\n\n  chrome.runtime.onMessage.addListener",start);
assert.ok(start>0 && end>start,'native click bridge block must exist');
const bridge=source.slice(start,end);

function styleState(){
  const values=new Map(),priorities=new Map();
  return {
    setProperty(k,v,p=''){values.set(k,String(v));priorities.set(k,String(p));},
    removeProperty(k){values.delete(k);priorities.delete(k);},
    getPropertyValue(k){return values.get(k)||'';},
    getPropertyPriority(k){return priorities.get(k)||'';}
  };
}

async function runCase({underlyingGenerate=true}){
  const listeners=new Map();
  const replies=[];
  const pluginRoot={style:styleState(),offsetWidth:100,contains:n=>n?.kind==='plugin'};
  const pluginHit={kind:'plugin',tagName:'SECTION',id:'fs-panel',className:'',getAttribute:k=>k==='class'?'fs-panel':'',closest:()=>null};
  const flowButton={kind:'flow',tagName:'BUTTON',id:'',className:'generate-icon-button',getAttribute:k=>k==='aria-label'?'开始生成':(k==='class'?'generate-icon-button':''),closest:sel=>underlyingGenerate?flowButton:null};
  let hitCalls=0,sendCalls=0;
  const document={
    getElementById:id=>id==='flow-studio-v050-root'?pluginRoot:null,
    elementFromPoint(){hitCalls++;return pluginRoot.style.getPropertyValue('pointer-events')==='none'?flowButton:pluginHit;}
  };
  const window={
    addEventListener(type,fn){listeners.set(type,fn);},
    dispatchEvent(ev){replies.push(ev.detail);return true;},
    CustomEvent:function(type,opts){this.type=type;this.detail=opts?.detail;}
  };
  const chrome={runtime:{lastError:null,sendMessage(msg,cb){sendCalls++;assert.equal(msg.type,'FS_NATIVE_CLICK');cb({ok:true,method:'test'});}}};
  const context={window,document,chrome,CustomEvent:window.CustomEvent,setTimeout,clearTimeout,console};
  vm.createContext(context);
  vm.runInContext(bridge,context);
  const handler=listeners.get('FLOW_STUDIO_NATIVE_CLICK_REQUEST');
  assert.equal(typeof handler,'function');
  handler({detail:{request_id:'r1',x:100,y:100}});
  await new Promise(r=>setTimeout(r,5));
  return {replies,sendCalls,hitCalls,pointerEvents:pluginRoot.style.getPropertyValue('pointer-events')};
}

(async()=>{
  const ok=await runCase({underlyingGenerate:true});
  assert.equal(ok.sendCalls,1,'trusted click must be sent exactly once');
  assert.equal(ok.replies.at(-1).ok,true);
  assert.equal(ok.replies.at(-1).overlay_bypassed,true);
  assert.equal(ok.pointerEvents,'','plugin pointer-events must be restored');
  assert.ok(ok.hitCalls>=2,'hit target must be checked again after overlay bypass');

  const bad=await runCase({underlyingGenerate:false});
  assert.equal(bad.sendCalls,0,'mismatched target must not receive a native click');
  assert.equal(bad.replies.at(-1).ok,false);
  assert.match(bad.replies.at(-1).error,/FLOW_NATIVE_CLICK_TARGET_MISMATCH/);
  assert.equal(bad.pointerEvents,'','plugin pointer-events must also be restored on mismatch');

  const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json'),'utf8'));
  assert.equal(manifest.version,'0.9.66');
  console.log('PASS v0.9.66 overlay bypass, hit-test, single click, and restoration');
})().catch(e=>{console.error(e);process.exit(1);});
