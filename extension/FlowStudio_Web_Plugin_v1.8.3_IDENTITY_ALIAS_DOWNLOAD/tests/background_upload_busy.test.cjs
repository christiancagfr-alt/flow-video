const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../content.js'),'utf8');
const method=source.slice(source.indexOf('  let uploadCheckInFlight=false;'),source.indexOf('  function maybeAutoUpload('));
const name='stuck.png',ledger=new Map(),calls=[],events=[];
const count=x=>ledger.get(x)||0;
const ctx=vm.createContext({navigator:{},location:{pathname:"/test"},console,Date,Set,Math,setTimeout:()=>0,clearTimeout:()=>{},
 state:{job:{},ready:false,uploadInFlight:false,generationRunning:false,mediaScanValid:true,uploadAttempts:0,matched:0,identity:'T',lastUploadAt:0},
 missingImagePaths:()=>({names:[name],noPath:[]}),isFlowUploading:()=>true,norm:x=>x,
 dispatchCount:count,lastDispatchAt:()=>0,canAutoRetry:x=>count(x)>0&&count(x)<3,
 taskPathForName:x=>'/images/'+x,markDispatched:x=>ledger.set(x,count(x)+1),
 uploadFailureLedger:new Set(),MAX_AUTO_UPLOAD_ATTEMPTS:3,UPLOAD_VERIFY_GRACE_MS:12000,UPLOAD_BUSY_STUCK_MS:30000,
 render(){},emit:(t,d)=>events.push([t,d]),basename:x=>x.split('/').pop(),getExpectedNames:()=>[name],setPanelTemporarilyHidden(){},sleep:async()=>{},findDropPoint:()=>({x:1,y:1,source:'test'}),
 fileInputUpload:async paths=>{calls.push(['input',paths]);return {ok:true,method:'file_input'};},syntheticDragUpload:async()=>({ok:false}),
 chrome:{runtime:{sendMessage:(m,cb)=>{calls.push(['drag',m.paths]);cb({ok:true,method:'chrome_debugger'})}}}
});
vm.runInContext(method,ctx);
(async()=>{
 for(let i=0;i<4;i++) await vm.runInContext('uploadMissing(true)',ctx);
 assert.equal(count(name),3);
 assert.equal(calls.length,3);
 assert.equal(events.filter(e=>e[0]==='media_upload_failed_final').length,1);
 console.log('PASS: unrelated page busy does not block first upload; true per-image retry ledger still caps attempts at 3');
})().catch(e=>{console.error(e);process.exit(1)});
