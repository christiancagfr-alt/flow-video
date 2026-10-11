const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../content.js'),'utf8');
const method=source.slice(source.indexOf('  let uploadCheckInFlight=false;'),source.indexOf('  function maybeAutoUpload('));
const names=Array.from({length:45},(_,i)=>'image'+i+'.png'),ledger=new Map(),batches=[];
let retryEnabled=false;
const count=x=>ledger.get(x)||0;
const ctx=vm.createContext({navigator:{},location:{pathname:"/test"},
  console,Date,Set,Math,setTimeout:()=>0,clearTimeout:()=>{},
  state:{job:{},ready:false,uploadInFlight:false,generationRunning:false,mediaScanValid:true,uploadAttempts:0,matched:0,identity:'T',lastUploadAt:0},
  missingImagePaths:()=>({names,noPath:[]}),isFlowUploading:()=>false,norm:x=>x,
  dispatchCount:count,lastDispatchAt:()=>0,canAutoRetry:x=>retryEnabled&&count(x)>0&&count(x)<3,
  taskPathForName:x=>'/images/'+x,markDispatched:x=>ledger.set(x,count(x)+1),
  uploadFailureLedger:new Set(),MAX_AUTO_UPLOAD_ATTEMPTS:3,UPLOAD_VERIFY_GRACE_MS:12000,UPLOAD_BUSY_STUCK_MS:30000,
  render(){},emit(){},basename:x=>x.split('/').pop(),getExpectedNames:()=>names,setPanelTemporarilyHidden(){},sleep:async()=>{},findDropPoint:()=>({x:1,y:1,source:'test'}),
  fileInputUpload:async paths=>{batches.push(paths);return {ok:true,method:'file_input'};},
  syntheticDragUpload:async()=>({ok:false}),
  chrome:{runtime:{sendMessage:(m,cb)=>{batches.push(m.paths);cb({ok:true,method:'chrome_debugger'})}}}
});
vm.runInContext(method,ctx);
(async()=>{
 await vm.runInContext('uploadMissing(true)',ctx);
 await vm.runInContext('uploadMissing(true)',ctx);
 await vm.runInContext('uploadMissing(true)',ctx);
 assert.deepEqual(batches.map(x=>x.length),[20,20,5]);
 assert.equal(new Set(batches.flat()).size,45);
 await vm.runInContext('uploadMissing(true)',ctx);
 assert.equal(batches.length,3,'unverified files must not duplicate before verification grace');
 retryEnabled=true;
 await vm.runInContext('uploadMissing(true)',ctx);
 assert.equal(batches.length,4,'stale unverified files should retry after verification grace');
 assert.equal(batches[3].length,20);
 assert.ok(batches[3].every(x=>batches[0].includes(x)),'retry should target the first still-missing batch');
 console.log('PASS: 45 images upload as 20/20/5 without immediate duplicates; stale unverified batch becomes retryable');
})().catch(e=>{console.error(e);process.exit(1)});
