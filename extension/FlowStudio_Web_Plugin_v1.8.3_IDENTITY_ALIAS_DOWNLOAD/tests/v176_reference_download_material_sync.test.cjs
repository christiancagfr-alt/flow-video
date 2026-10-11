const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const page=fs.readFileSync(path.join(__dirname,'../page-engine.js'),'utf8');
const content=fs.readFileSync(path.join(__dirname,'../content.js'),'utf8');
const downloads=fs.readFileSync(path.join(__dirname,'../downloads.js'),'utf8');

test('reference-style status response publishes immediate VIDEO ready keyed by media name',()=>{
  const a=page.indexOf('  const flowStatusReadySeen=new Set();');
  const b=page.indexOf('  function installFlowVideoStatusBridge()',a);
  assert.ok(a>=0&&b>a);
  const emitted=[];
  class CE{constructor(name,opt){this.type=name;this.detail=opt.detail;}}
  const context=vm.createContext({
    window:{CustomEvent:CE,dispatchEvent:e=>emitted.push(e)},CustomEvent:CE,
    URL,Request:undefined,encodeURIComponent,JSON,String,Object,Array,Set,Map
  });
  vm.runInContext(page.slice(a,b),context);
  const payload={media:[{name:'generation-123',mediaMetadata:{mediaStatus:{mediaGenerationStatus:'SUCCESSFUL'}}}]};
  const n=vm.runInContext('publishSuccessfulVideoMedia',context)(payload,'test');
  assert.equal(n,1);
  assert.equal(emitted.length,1);
  assert.equal(emitted[0].type,'FLOW_STUDIO_VIDEO_READY');
  assert.equal(emitted[0].detail.row.id,'generation-123');
  assert.equal(emitted[0].detail.row.media_id,'generation-123');
  assert.equal(emitted[0].detail.row.media_kind,'VIDEO');
  assert.match(emitted[0].detail.row.url,/media\.getMediaUrlRedirect\?name=generation-123/);
  assert.equal(vm.runInContext('publishSuccessfulVideoMedia',context)(payload,'test'),0,'duplicate SUCCESSFUL status must not redeliver');
});

test('MATERIAL is inherited independently from explicit auxiliary endpoints',()=>{
  const a=content.indexOf('  function resolveTaskGenerationMode(');
  const b=content.indexOf('  function normalizeTasks(',a);
  const context=vm.createContext({String,Array});
  vm.runInContext(content.slice(a,b),context);
  const resolve=vm.runInContext('resolveTaskGenerationMode',context);
  assert.equal(resolve({generation_mode:'MATERIAL'},{task_type:'VIDEO'},'VIDEO'),'MATERIAL');
  assert.equal(resolve({}, {task_type:'VIDEO',material_image_paths:['/tmp/aux.png']},'VIDEO'),'FRAME');
  assert.equal(resolve({generation_mode:'IMAGE'},{task_type:'VIDEO'},'VIDEO'),'FRAME');
  assert.match(content,/end_image_name:basename\(t.end_image_path/);
  assert.doesNotMatch(content,/material_image_names/);
});

test('Chrome download creation no longer waits for prior downloading item to complete',()=>{
  assert.match(downloads,/if\(dlState\.entries\.some\(e=>e\.group===group&&e\.status==='starting'\)\)return;/);
  assert.doesNotMatch(downloads,/e\.group===group&&\['starting','downloading'\]\.includes\(e\.status\)/);
  assert.match(downloads,/setTimeout\(\(\)=>\{void dlPump\(\);\},0\);/);
});
