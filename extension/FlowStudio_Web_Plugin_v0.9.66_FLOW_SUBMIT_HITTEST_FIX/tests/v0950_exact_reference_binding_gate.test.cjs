const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const engine=fs.readFileSync(path.join(__dirname,'../page-engine.js'),'utf8');
const manifest=JSON.parse(fs.readFileSync(path.join(__dirname,'../manifest.json'),'utf8'));
assert.ok(['0.9.50','0.9.51','0.9.52','0.9.56','0.9.57','0.9.58','0.9.59','0.9.60','0.9.62'].includes(manifest.version));
if(['0.9.57','0.9.58','0.9.59','0.9.60','0.9.62'].includes(manifest.version)){
  assert.match(engine,/material_binding_protection='disabled'/);
  assert.match(engine,/requireMaterial:false/);
  console.log('PASS: v0.9.57 intentionally relaxes exact binding enforcement while keeping diagnostics');
  process.exit(0);
}
const start=engine.indexOf('  function requestBodyObject(');
const end=engine.indexOf('  const videoResults=new Map();',start);
assert.ok(start>0&&end>start,'material gate helper block not found');
const source=engine.slice(start,end);
const context=vm.createContext({
  console,URLSearchParams,TextDecoder,ArrayBuffer,Uint8Array,Set,Map,JSON,decodeURIComponent,
  hasTarget:(value,ids,depth=0)=>{
    if(depth>8||value==null)return false;
    if(typeof value==='string'||typeof value==='number')return ids.has(value);
    if(Array.isArray(value))return value.some(v=>context.hasTarget(v,ids,depth+1));
    if(typeof value==='object')return Object.values(value).some(v=>context.hasTarget(v,ids,depth+1));
    return false;
  },
  stateSnapshot:()=>new Map(),sessionStorage:{removeItem(){}},ticketKey:x=>x,submissionDiagnostics:[]
});
vm.runInContext(source,context);
const run=(body,extra={})=>{
  context.body=body;
  context.ticket={requireMaterial:true,requiredMaterialPrimaryId:'img-12345678',requiredMaterialBindingIds:['img-12345678','asset-abcdef12'],requiredMaterialIds:['img-12345678'],prompt:'PROMPT-XYZ',expectedMode:'VIDEO_REFERENCES',...extra};
  return vm.runInContext('materialBindingProof(body,ticket)',context);
};
let p=run({generation:{prompt:'PROMPT-XYZ',referenceMedia:[{id:'img-12345678',mediaType:'IMAGE'}]}});
assert.equal(p.ok,true,'named reference branch must pass');
assert.equal(p.kind,'semantic_reference_branch');

p=run({generation:{prompt:'PROMPT-XYZ',mode:'VIDEO_REFERENCES'},cache:{media:[{id:'img-12345678',mediaType:'IMAGE'}]}});
assert.equal(p.ok,false,'image ID found only in cache must NOT pass');

p=run({generation:{prompt:'PROMPT-XYZ',mode:'VIDEO_REFERENCES'},history:{referenceMedia:[{id:'img-12345678',mediaType:'IMAGE'}]}});
assert.equal(p.ok,false,'history reference must NOT pass');

p=run({generation:{prompt:'PROMPT-XYZ',media:[{id:'img-12345678',mediaType:'IMAGE'}]}});
assert.equal(p.ok,true,'local generation media branch with exact selected binding must pass');

p=run({generation:{prompt:'PROMPT-XYZ',referenceMedia:[{id:'img-12345678',mediaType:'IMAGE'}],mode:'VIDEO_FRAMES'}});
assert.equal(p.ok,false,'FRAME mode evidence must block MATERIAL request');

const positional=JSON.stringify([['rpc',['VIDEO_REFERENCES','PROMPT-XYZ',['img-12345678','IMAGE']]]]);
p=run('f.req='+encodeURIComponent(positional));
assert.equal(p.ok,true,'URL-encoded f.req positional reference tuple must pass');

const farApart=JSON.stringify([['VIDEO_REFERENCES','PROMPT-XYZ'],['cache',['img-12345678','IMAGE']]]);
p=run('f.req='+encodeURIComponent(farApart));
assert.equal(p.ok,false,'ID and reference marker in separate branches must NOT pass');

p=run({generation:{prompt:'PROMPT-XYZ',referenceMedia:[{id:'asset-abcdef12',mediaType:'IMAGE'}]}});
assert.equal(p.ok,true,'identifier captured from the exact selected attachment fingerprint may pass');

p=run({generation:{prompt:'PROMPT-XYZ'},library:{asset:{id:'asset-abcdef12',mediaType:'IMAGE'}},mode:'VIDEO_REFERENCES'});
assert.equal(p.ok,false,'fingerprint alias in library/cache must NOT pass');

assert.match(engine,/captureMaterialBinding\(/,'selected attachment fingerprint capture missing');
assert.match(engine,/requiredMaterialBindingIds/,'network gate is not using attachment fingerprint identities');
assert.match(engine,/REFERENCE_MATERIAL_NOT_BOUND_IN_GENERATION_REQUEST/,'semantic request binding failure missing');
assert.match(engine,/FLOW_MODE_CHANGED_BEFORE_SUBMIT/,'final mode re-check missing');
console.log('PASS: v0.9.50 requires exact current-reference binding; cache/history/far-apart IDs and FRAME-mode requests are blocked');
