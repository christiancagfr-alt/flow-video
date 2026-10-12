const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const p=path.join(__dirname,'..');
const page=fs.readFileSync(path.join(p,'page-engine.js'),'utf8');
const content=fs.readFileSync(path.join(p,'content.js'),'utf8');
const manifest=JSON.parse(fs.readFileSync(path.join(p,'manifest.json'),'utf8'));
assert.ok(['0.9.51','0.9.52','0.9.56','0.9.57','0.9.58','0.9.59','0.9.60','0.9.62'].includes(manifest.version));
if(manifest.version==='0.9.51'){
  assert.match(page,/requestMaterialDirectAttach\(detail\)/,'v0.9.51 MATERIAL direct composer fallback missing');
}else{
  assert.doesNotMatch(page,/await requestMaterialDirectAttach\(detail\)/,'v0.9.52 must not locally drag/upload into MATERIAL composer');
  assert.match(page,/selectMaterialAssetLikeFrame\(/,'v0.9.52 native Flow asset selection helper missing');
  assert.match(page,/material_attach_method='flow_native_asset_select'/,'v0.9.52 must report native asset binding');
}
assert.match(page,/requiredMaterialBindingIds/,'binding diagnostics should remain available');
console.log('PASS: v0.9.51 direct attach regression is superseded safely by v0.9.52 native Flow asset binding');
