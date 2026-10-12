const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const bg=fs.readFileSync(path.join(root,'background.js'),'utf8')+fs.readFileSync(path.join(root,'background-runtime.js'),'utf8');

test('macOS Spaces guard resumes frozen lifecycle without focusing window',()=>{
  assert.match(bg,/Page\.setWebLifecycleState/);
  assert.match(bg,/state:'active'/);
  assert.match(bg,/Emulation\.setFocusEmulationEnabled/);
  assert.match(bg,/macos_space_guard:true/);
  const start=bg.indexOf('async function wakeActionableFlowTabs');
  const end=bg.indexOf('async function dispatchNativeFileDrag');
  const wake=bg.slice(start,end);
  assert.doesNotMatch(wake,/chrome\.windows\.update\(/);
  assert.doesNotMatch(wake,/chrome\.tabs\.update\(tab\.id,\{active:true\}/);
});
