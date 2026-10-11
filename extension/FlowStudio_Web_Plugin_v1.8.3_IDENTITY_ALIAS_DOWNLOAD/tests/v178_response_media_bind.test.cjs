const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const page=fs.readFileSync(path.join(__dirname,'../page-engine.js'),'utf8');
const content=fs.readFileSync(path.join(__dirname,'../content.js'),'utf8');

function responseBridgeContext(){
  const a=page.indexOf('  const flowStatusReadySeen=new Set();');
  const b=page.indexOf('  function installFlowVideoStatusBridge()',a);
  assert.ok(a>=0&&b>a);
  const emitted=[];
  class CE{constructor(name,opt){this.type=name;this.detail=opt.detail;}}
  const writes=[];
  const context=vm.createContext({
    window:{CustomEvent:CE,dispatchEvent:e=>emitted.push(e)},CustomEvent:CE,
    URL,Request:undefined,encodeURIComponent,decodeURIComponent,JSON,String,Object,Array,Set,Map,Date,
    pending:null,submissionDiagnostics:[],safeRecoveryWrite:(k,v)=>{writes.push([k,v]);return true;}
  });
  vm.runInContext(page.slice(a,b),context);
  return {context,emitted,writes};
}

test('generation response media.name binds the currently clicked task immediately',()=>{
  const {context,writes}=responseBridgeContext();
  const ticket={prompt:'hello',excludedIds:['old-id'],recoveryKey:'rk'};
  const payload={media:[{name:'generation-new'}]};
  const ok=vm.runInContext('observeFlowGenerationPayload',context)(ticket,200,payload,'test',[]);
  assert.equal(ok,true);
  assert.equal(Array.from(ticket.accepted).join(','),'generation-new');
  assert.equal(ticket.responseAccepted,true);
  assert.equal(writes.at(-1)[1].acceptedIds[0],'generation-new');
});

test('reference-style framed status response parses SUCCESSFUL and direct video URL',()=>{
  const {context,emitted}=responseBridgeContext();
  const wire='2:[["{\\"media\\":[{\\"name\\":\\"generation-42\\",\\"mediaMetadata\\":{\\"mediaStatus\\":{\\"mediaGenerationStatus\\":\\"SUCCESSFUL\\"}},\\"result\\":\\"https://flow-content.google/video/file-42\\"}]}" ]]';
  const parsed=vm.runInContext('parseFlowPayloadText',context)(wire);
  const n=vm.runInContext('publishSuccessfulVideoMedia',context)(parsed,'test');
  assert.equal(n,1);
  assert.equal(emitted[0].detail.row.id,'generation-42');
  assert.equal(emitted[0].detail.row.media_id,'file-42');
  assert.equal(emitted[0].detail.row.url,'https://flow-content.google/video/file-42');
});

test('post-click missing response is uncertain and never automatic safe retry',()=>{
  assert.match(page,/fallbackAt=\[5000,15000,30000,50000\]/);
  assert.match(page,/SUBMISSION_UNCONFIRMED：已点击生成但未及时收到 generation response/);
  assert.doesNotMatch(page,/throw new Error\('FLOW_SUBMISSION_NOT_STARTED/);
  assert.doesNotMatch(content,/FLOW_INSTANCE_NOT_FOUND\|BUTTON_NOT_READY\|FLOW_SUBMISSION_NOT_STARTED/);
});

test('existing CDP Generate submission path remains intact',()=>{
  assert.match(page,/await requestNativeGenerateClick\(button\);/);
  assert.match(page,/method:'native_cdp_click'/);
  assert.match(page,/FLOW_STUDIO_NATIVE_CLICK_REQUEST/);
  assert.match(content,/FS_NATIVE_CLICK/);
});
