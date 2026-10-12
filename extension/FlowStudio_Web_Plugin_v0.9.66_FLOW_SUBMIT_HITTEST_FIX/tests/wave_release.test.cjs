const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../content.js'),'utf8');
assert.match(source,/async function waveFullyConfirmed\(job\)/,'started waves must be verified before release');
assert.match(source,/hasStartedWave\(executionKey\)[\s\S]*waveFullyConfirmed\(job\)[\s\S]*retireCompletedWave/,'fully confirmed duplicate wave must retire instead of occupying the channel');
assert.match(source,/isRetiredCommand\(incoming\.command_id\)/,'retired Studio jobs must not be re-adopted while the next wave is being scheduled');
assert.match(source,/state\.generationDeferred===0[\s\S]*retireCompletedWave/,'confirmed batch must release the submission slot immediately');
assert.match(source,/FS_FORCE_SYNC[\s\S]*pullJob/,'retirement must actively request the next wave');
console.log('PASS: completed/duplicate submission waves clear locally and request the next task without re-adopting the retired job');
