const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const page=fs.readFileSync(path.join(__dirname,'../page-engine.js'),'utf8');
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'../manifest.json'),'utf8'));

test('v179 starts conditional keepalive from accepted generation media id',()=>{
  assert.match(page,/const flowWaitingVideoIds=new Set\(\)/);
  assert.match(page,/trackWaitingVideoIds\(\[id\],source\)/);
  assert.match(page,/navigator\?\.locks\?\.request/);
  assert.match(page,/new RTCPeerConnection\(\)/);
  assert.match(page,/VIDEO_WAIT_KEEPALIVE_START/);
});

test('v179 releases keepalive on terminal Flow status response',()=>{
  assert.match(page,/settleWaitingVideoIdsFromStatus\(payload\)/);
  assert.match(page,/\(SUCCESS\|FAILED\|FAILURE\|CANCEL\|ERROR\)/);
  assert.match(page,/stopFlowWaitingKeepAlive\(reason\)/);
});

test('v179 preserves existing CDP Generate submission path',()=>{
  assert.match(page,/await requestNativeGenerateClick\(button\);/);
  assert.match(page,/method:'native_cdp_click'/);
  assert.ok(['1.8.0','1.8.1','1.8.2','1.8.3','1.8.5','1.8.6'].includes(manifest.version));
});
