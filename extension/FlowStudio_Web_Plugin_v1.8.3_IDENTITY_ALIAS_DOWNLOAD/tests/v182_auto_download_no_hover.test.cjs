const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const page=fs.readFileSync(path.join(__dirname,'../page-engine.js'),'utf8');
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'../manifest.json'),'utf8'));

test('v182 keeps existing CDP submission unchanged',()=>{
  assert.ok(['1.8.2','1.8.3','1.8.5','1.8.6'].includes(manifest.version));
  assert.match(page,/await requestNativeGenerateClick\(button\);/);
  assert.match(page,/method:'native_cdp_click'/);
});

test('v182 SUCCESSFUL result is keyed back to the bound generation identity',()=>{
  assert.match(page,/const flowIdentityPrimary=new Map\(\)/);
  assert.match(page,/bindFlowIdentityAliases\(primary,\[\.\.\.ids,\.\.\.requestFallbackIds\],source\)/);
  assert.match(page,/id:boundId,media_id:mediaId,status:'ready'/);
  assert.match(page,/media\.getMediaUrlRedirect\?name=/);
});

test('v182 replays Flow own status request only while VIDEO is waiting',()=>{
  assert.match(page,/const flowStatusReplay=/);
  assert.match(page,/captureFlowStatusFetchTemplate\(args\)/);
  assert.match(page,/setInterval\(\(\)=>\{if\(!flowWaitingVideoIds\.size\)return stopFlowStatusReplay\(\);void replayFlowStatusOnce\(\);\},2500\)/);
  assert.match(page,/publishSuccessfulVideoMedia\(payload,'flow_status_replay'\)/);
});

test('v182 waiting-only keepalive includes favicon heartbeat after submit',()=>{
  assert.match(page,/faviconTimer/);
  assert.match(page,/__fs_wait_video/);
  assert.match(page,/if\(!flowWaitingVideoIds\.size\)\{stopFlowWaitingKeepAlive\(reason\);stopFlowStatusReplay\(\);\}/);
});
