const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const page=fs.readFileSync(path.join(__dirname,'../page-engine.js'),'utf8');
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'../manifest.json'),'utf8'));

test('reference-style result parsing remains available without document-start antifreeze',()=>{
  const main=manifest.content_scripts.find(x=>x.world==='MAIN'&&x.js.includes('page-engine.js'));
  assert.ok(main);
  assert.equal(main.js.includes('reference-antifreeze.js'),false);
  assert.match(page,/referenceBatchHttpsURLsFromXHRText/);
  assert.match(page,/publishReferenceBatchXHRVideos\(rawText,'flow_xhr_any_video_url'\)/);
  assert.match(page,/parsed\.pathname\.includes\('\/video\/'\)/);
});

test('reference XHR video scan is gated until a confirmed waiting media id exists',()=>{
  assert.match(page,/if\(rawText && flowWaitingVideoIds\.size\)publishReferenceBatchXHRVideos/);
  assert.match(page,/function publishReferenceBatchXHRVideos[\s\S]*if\(!flowWaitingVideoIds\.size\)return 0/);
  assert.doesNotMatch(page,/flowWaitingVideoIds\.size\|\|pending/);
});

test('known-working CDP submit path is preserved',()=>{
  assert.match(page,/await requestNativeGenerateClick\(button\);/);
  assert.match(page,/method:'native_cdp_click'/);
});
