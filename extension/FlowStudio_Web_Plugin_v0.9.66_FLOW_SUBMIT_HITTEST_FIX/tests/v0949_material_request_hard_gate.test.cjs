const fs=require('fs'),assert=require('assert');
const engine=fs.readFileSync(__dirname+'/../page-engine.js','utf8');
const content=fs.readFileSync(__dirname+'/../content.js','utf8');
const manifest=JSON.parse(fs.readFileSync(__dirname+'/../manifest.json','utf8'));
assert.ok(['0.9.49','0.9.50','0.9.51','0.9.52','0.9.56','0.9.57','0.9.58','0.9.59','0.9.60','0.9.62'].includes(manifest.version));
if(['0.9.57','0.9.58','0.9.59','0.9.60','0.9.62'].includes(manifest.version)){
  assert.match(engine,/requireMaterial:false/,'v0.9.57 must not require request-level material proof');
  assert.match(engine,/materialRequestProtectionDisabled=true/,'v0.9.57 must explicitly disable request blocking');
  assert.doesNotMatch(content,/已阻止无图提交/,'old material hard-gate operator block must be gone');
  console.log('PASS: v0.9.57 intentionally disables MATERIAL request hard gate');
  process.exit(0);
}
assert.match(engine,/function bodyHasRequiredMaterial\(/,'request body material verifier missing');
assert.match(engine,/function blockMateriallessGeneration\(/,'material request blocker missing');
assert.match(engine,/requireMaterial:mode==='VIDEO_REFERENCES'/,'MATERIAL ticket must require exact material');
assert.match(engine,/requiredMaterialIds:mode==='VIDEO_REFERENCES'\?\[\.\.\.targetIdentities\]/,'current-task material identities missing');
assert.match(engine,/if\(generation && blockMateriallessGeneration\(ticket,url,requestBody\)\)throw new Error\(ticket\.failure\)/,'fetch must be blocked before network');
assert.match(engine,/if\(blockMateriallessGeneration\(ticket,meta\.url,body\)\)\{try\{this\.abort\(\)/,'XHR must be blocked before network');
assert.match(engine,/REFERENCE_MATERIAL_(?:MISSING|NOT_BOUND)_IN_GENERATION_REQUEST/,'missing/binding material request error absent');
assert.match(engine,/REFERENCE_MATERIAL_REQUEST_UNVERIFIABLE/,'unverifiable MATERIAL request must fail closed');
assert.match(content,/material_attachment_recovering/,'material gate must enter safe retry path');
assert.match(content,/已阻止无图提交/,'operator status must state prompt-only submission was blocked');
console.log('PASS: v0.9.49 material request hard gate present');
