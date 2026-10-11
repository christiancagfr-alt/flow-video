const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const page=fs.readFileSync(path.join(__dirname,'../page-engine.js'),'utf8');
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'../manifest.json'),'utf8'));

test('v181 isolates download-side global behavior from submission stage',()=>{
  assert.ok(['1.8.1','1.8.2','1.8.3','1.8.5','1.8.6'].includes(manifest.version));
  const main=manifest.content_scripts.find(x=>x.world==='MAIN'&&x.js.includes('page-engine.js'));
  assert.ok(main);
  assert.equal(main.js.includes('reference-antifreeze.js'),false);
  assert.match(page,/trackWaitingVideoIds\(\[id\],source\)/);
  assert.match(page,/if\(rawText && flowWaitingVideoIds\.size\)publishReferenceBatchXHRVideos/);
});

test('v181 preserves generation-response mediaId binding and status-response download bridge',()=>{
  assert.match(page,/GENERATION_RESPONSE_BOUND/);
  assert.match(page,/FLOW_VIDEO_STATUS_MARKER='video:batchCheckAsyncVideoGenerationStatus'/);
  assert.match(page,/publishSuccessfulVideoMedia\(payload,'flow_status_xhr'\)/);
  assert.match(page,/publishSuccessfulVideoMedia\(payload,'flow_status_fetch'\)/);
});

test('v181 does not replace the CDP Generate submission path',()=>{
  assert.match(page,/await requestNativeGenerateClick\(button\);/);
  assert.match(page,/method:'native_cdp_click'/);
});
