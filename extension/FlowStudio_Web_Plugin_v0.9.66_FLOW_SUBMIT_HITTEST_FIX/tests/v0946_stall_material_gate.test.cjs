const fs=require('fs');
const content=fs.readFileSync(require('path').join(__dirname,'..','content.js'),'utf8');
const page=fs.readFileSync(require('path').join(__dirname,'..','page-engine.js'),'utf8');
function ok(v,m){if(!v)throw new Error(m)}
ok(content.includes('upload_watchdog_released'),'upload watchdog event missing');
ok(content.includes('now-last<35000'),'35s no-progress watchdog missing');
ok(content.includes("state:'preparing'"),'preparing state missing');
ok(content.includes("!state.uploadInFlight && !state.generationRunning && !state.scanInFlight"),'control heartbeat must not mask active work');
const manifest=JSON.parse(fs.readFileSync(require('path').join(__dirname,'..','manifest.json'),'utf8'));
if(['0.9.57','0.9.58','0.9.59','0.9.60','0.9.62'].includes(manifest.version)){
  ok(page.includes("material_binding_protection='disabled'"),'v0.9.57 must explicitly disable MATERIAL binding protection');
  console.log('PASS: upload watchdog preserved; v0.9.57 intentionally disables MATERIAL hard gate');
}else{
  ok(page.includes('REFERENCE_MATERIAL_NOT_STABLE_BEFORE_SUBMIT'),'material stability hard gate missing');
  ok(page.includes('stableMaterial<3'),'three consecutive material checks missing');
  ok(page.includes("prev && prev.serialized===cur.serialized"),'stale material state rejection missing');
  console.log('PASS: v0.9.46 upload watchdog + material hard gate present');
}
