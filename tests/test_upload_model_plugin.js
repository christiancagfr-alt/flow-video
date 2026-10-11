const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),path=require('path');
const root=path.join(__dirname,'../extension/FlowStudio_Web_Plugin_v1.8.3_IDENTITY_ALIAS_DOWNLOAD');
const code=fs.readFileSync(path.join(root,'content.js'),'utf8');
const norm=code.split('\n').find(x=>x.includes('const norm ='));
const upload=code.slice(code.indexOf('  let uploadCheckInFlight='),code.indexOf('  function maybeAutoUpload()'));
function setup(scan){
 let scanned=0,uploads=0;
 const context={Date,Map,Set,JSON,Error,console,navigator:{},location:{pathname:'/project/test'},
 state:{job:{},ready:false,media:[]},submitViaMainWorld:async()=>{scanned++;return scan();},
 effectiveRequiredNames:()=>['a-1234567890abcdef.png'],render(){},emit(){},queueMicrotask(){},
 missingImagePaths(){uploads++;throw Error('Should not upload');}};
 vm.createContext(context);vm.runInContext(norm+'\n'+upload+'\nglobalThis.run=uploadMissing;',context);
 return {context,run:context.run,scanned:()=>scanned,uploads:()=>uploads};
}
(async()=>{
 const fail=setup(()=>{throw Error('scan unavailable');});await fail.run(true);assert.equal(fail.uploads(),0);assert.match(fail.context.state.message,/暂停/);
 const invalid=setup(()=>({}));await invalid.run(true);assert.equal(invalid.uploads(),0);
 let resolve;const concurrent=setup(()=>new Promise(r=>resolve=r));const first=concurrent.run(true);await concurrent.run(true);assert.equal(concurrent.scanned(),1);resolve({});await first;
 const exists=setup(()=>({media:[{name:'other-1234567890abcdef.png'}]}));exists.context.missingImagePaths=()=>({names:[],noPath:[]});await exists.run(true);assert.equal(exists.context.state.media.length,1);assert.match(exists.context.state.message,/无需重复上传/);
 const ledger=new Map(),ctx={Map,JSON,Date,state:{job:{image_set_id:'first'}},location:{pathname:'/p'},uploadLedger:new Map(),localStorage:{getItem:k=>ledger.get(k)||null,setItem:(k,v)=>ledger.set(k,v),removeItem:k=>ledger.delete(k)}};
 vm.createContext(ctx);vm.runInContext(norm+'\n'+code.slice(code.indexOf('  function uploadKey('),code.indexOf('  function visibleMediaNames('))+'\nglobalThis.mark=markDispatched;globalThis.read=readDispatchRecord;',ctx);
 ctx.mark('a-1234567890abcdef.png');ctx.state.job={image_set_id:'second'};assert.equal(ctx.read('b-1234567890abcdef.png').count,1);
 const key=[...ledger.keys()][0];ledger.set(key,JSON.stringify({count:2,at:Date.now(),method:'other-tab'}));assert.equal(ctx.read('b-1234567890abcdef.png').count,2);
 const engine=fs.readFileSync(path.join(root,'page-engine.js'),'utf8');const omni=engine.slice(engine.indexOf('  async function chooseOmni('),engine.indexOf('  async function configure('));
 let native='veo';const sig=()=>native;sig.set=x=>native=x;
 const button={innerText:'Veo',click(){}},option={innerText:'Gemini Omni',click(){native='observed-native-model';}};
 const m={models:['veo'],signal:()=>sig,composerContext:()=>({root:{querySelectorAll:()=>[button]}}),document:{querySelectorAll:()=>[option]},renderedNode:()=>true,sleep:async()=>{},Date,Error};vm.createContext(m);vm.runInContext(omni+'\nglobalThis.choose=chooseOmni;',m);
 assert.equal((await m.choose({}))(),'observed-native-model');assert.ok(m.models.includes('observed-native-model'));
 m.document.querySelectorAll=()=>[];await assert.rejects(m.choose({}),/Omni/);
 console.log('Upload scan, concurrency, cross-wave/cross-tab dedup and native Omni selection checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
