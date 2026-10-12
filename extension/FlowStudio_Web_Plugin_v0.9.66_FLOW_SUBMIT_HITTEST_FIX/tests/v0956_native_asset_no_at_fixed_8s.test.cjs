const fs=require('fs');
const assert=require('assert');
const pe=fs.readFileSync(require('path').join(__dirname,'..','page-engine.js'),'utf8');
const content=fs.readFileSync(require('path').join(__dirname,'..','content.js'),'utf8');
const bg=fs.readFileSync(require('path').join(__dirname,'..','background.js'),'utf8');
const manifest=JSON.parse(fs.readFileSync(require('path').join(__dirname,'..','manifest.json'),'utf8'));
assert.ok(['0.9.56','0.9.57','0.9.58','0.9.59','0.9.60','0.9.62'].includes(manifest.version));
assert(pe.includes("selectMaterialAssetLikeFrame({service,select,item,targetIdentities,editor,key,detail})"),'MATERIAL must use native formal asset selection');
assert(!pe.includes('requestIngredientMention('),'@ Ingredient page-engine path must be removed');
assert(!pe.includes('selectMaterialByIngredientMention('),'@ Ingredient material selection must be removed');
assert(!content.includes('FLOW_STUDIO_INGREDIENT_MENTION_REQUEST'),'content @ Ingredient listener must be removed');
assert(!bg.includes('FS_NATIVE_INGREDIENT_TEXT'),'native @ typing bridge must be removed');
if(['0.9.58','0.9.59','0.9.60','0.9.62'].includes(manifest.version)){ 
  assert(pe.includes("durationSignal.set(mode==='VIDEO_REFERENCES' ? 8 : Number(detail.duration || 8))"),'v0.9.58 MATERIAL must force hidden duration signal to 8');
}else{
  assert(pe.includes("if (mode!=='VIDEO_REFERENCES') constructorSignal(service,/this\\.(\\w+)=[^;]+8\\);/,'duration').set(Number(detail.duration || 8));"),'legacy MATERIAL must not write duration signal');
}
assert(pe.includes("if ((detail.mode||'VIDEO_FRAMES')==='VIDEO_REFERENCES')"),'MATERIAL duration normalization missing');
assert(pe.includes('detail.duration=8;'),'MATERIAL must normalize to 8s');
console.log('v0.9.56 native asset/no-@/fixed-8s tests passed');
