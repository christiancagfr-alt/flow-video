const assert=require('assert');
const fs=require('fs');
const path=require('path');
const root=path.resolve(__dirname,'..');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json'),'utf8'));
const c=fs.readFileSync(path.join(root,'content.js'),'utf8');
assert.equal(manifest.version,'0.9.62');
assert.match(c,/const engineBusy=\/\^ENGINE_BUSY/);
assert.match(c,/engine_busy_waiting/);
assert.match(c,/const waits=transientPage\?normalWaits.slice\(0,2\):normalWaits/);
assert.match(c,/command_id:job\.command_id/);
assert.match(c,/state\.cancelledCommand===payload\.command_id/);
console.log('PASS: v0.9.62 treats ENGINE_BUSY as transient serialized recovery instead of immediate task failure');

assert.doesNotMatch(c,/const engineBusyWaits=/);
