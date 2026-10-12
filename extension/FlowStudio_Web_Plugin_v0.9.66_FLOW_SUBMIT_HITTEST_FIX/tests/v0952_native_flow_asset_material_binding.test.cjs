const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.join(__dirname,'..');
const page=fs.readFileSync(path.join(root,'page-engine.js'),'utf8');
const content=fs.readFileSync(path.join(root,'content.js'),'utf8');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json'),'utf8'));
assert.ok(['0.9.52','0.9.56','0.9.57','0.9.58','0.9.59','0.9.60','0.9.62'].includes(manifest.version));
assert.match(page,/waitExistingFlowImageAssetReady\(/,'formal Flow IMAGE asset readiness gate missing');
assert.match(page,/mediaURL\(row\)/,'asset readiness must require a resolved remote Flow media URL');
assert.match(page,/modeSignal.set\('VIDEO_REFERENCES'\)/,'native MATERIAL mode request remains');
assert.match(page,/selectMaterialAssetLikeFrame\(/,'native asset binding helper missing');
assert.match(page,/await select\(item\)/,'native Flow select(item) primitive must be used');
assert.doesNotMatch(page,/await requestMaterialDirectAttach\(detail\)/,'local file direct-attach path must be disabled for MATERIAL');
assert.match(page,/flow_native_asset_select/,'reported MATERIAL attachment method must identify Flow-native asset selection');
if(['0.9.57','0.9.58','0.9.59','0.9.60','0.9.62'].includes(manifest.version)){
  assert.doesNotMatch(page,/const attempts=3/,'v0.9.57 must remove strict bounded binding retry loop');
  assert.match(page,/material_binding_protection='disabled'/,'v0.9.57 relaxed binding flag missing');
  assert.doesNotMatch(content,/素材绑定保护/,'v0.9.57 content must not run MATERIAL protection retry loop');
  console.log('PASS: v0.9.57 keeps Flow-native asset select while removing strict binding protection');
}else{
  assert.match(page,/const attempts=3/,'native material binding must have bounded retries');
  assert.match(page,/service\.clear\(\);[\s\S]*configure\(service,detail\)/,'failed native bind must reset composer and rebuild MATERIAL mode before retry');
  assert.match(page,/requiredMaterialBindingIds/,'exact request binding gate must remain after native selection');
  assert.match(content,/REFERENCE_MATERIAL_NATIVE_ASSET_SELECT_FAILED/,'native asset selection failures must enter safe material retry path');
  assert.match(content,/FLOW_IMAGE_ASSET_NOT_READY/,'formal Flow asset readiness failures must be recoverable');
  console.log('PASS: v0.9.52 MATERIAL binds an already-uploaded Flow IMAGE asset with native select(item), bounded reset/retry, and no local composer drag');
}
