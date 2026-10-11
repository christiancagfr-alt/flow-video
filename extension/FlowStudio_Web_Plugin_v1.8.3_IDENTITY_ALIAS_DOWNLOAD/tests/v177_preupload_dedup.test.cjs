const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../content.js'),'utf8');
assert.ok(source.includes("emit('preupload_existing_media_checked'"),'upload path must perform live pre-upload existence check');
assert.ok(!source.includes("存在同名素材，请在 Flow 中清理重复图片"),'duplicate filenames must not hard-block generation');
assert.ok(source.includes("const isBrollVideo = taskType === 'BROLL_VIDEO';"),'v1.7.6 isBrollVideo regression must be fixed');
const start=source.indexOf('  function matchTasks(media) {');
const end=source.indexOf('\n  function missingTasks()',start);
const code=source.slice(start,end);
const ctx=vm.createContext({
  state:{tasks:[{image:'a.png',generation_mode:'FRAME'}],matched:0},
  norm:x=>String(x||'').toLowerCase(),
  mediaUploadUsable:x=>!!x&&x.ready===true
});
vm.runInContext(code,ctx);
vm.runInContext("matchTasks([{name:'a.png',id:'old',ready:false},{name:'a.png',id:'good',url:'u',ready:true}])",ctx);
assert.equal(ctx.state.tasks[0].matched,true);
assert.equal(ctx.state.tasks[0].flow_media_id,'good');
console.log('PASS v1.7.7: duplicate existing images are reused before upload and do not block task mapping');
