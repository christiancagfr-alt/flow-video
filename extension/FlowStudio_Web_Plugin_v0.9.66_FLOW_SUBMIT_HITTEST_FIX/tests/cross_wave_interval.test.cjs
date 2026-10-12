const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../content.js'),'utf8');
assert.match(source,/function submissionGateKey\(job\)/,'submission gate must persist per channel');
assert.match(source,/sessionStorage\.setItem\(submissionGateKey\(job\),JSON\.stringify\(row\)\)/,'next allowed submit time must be persisted across wave release');
assert.match(source,/noteSubmissionAttempt\(job\);[\s\S]*submitWithRecovery/,'real Flow submit must arm the gate');
assert.match(source,/await waitForNextSubmission\(0,job\);[\s\S]*batch: for/,'first task of a newly refilled wave must respect the previous wave interval');
assert.match(source,/intervalRandom/,'Studio random interval must be recognized');
assert.doesNotMatch(source,/clearLocalWave[\s\S]{0,800}removeItem\(submissionGateKey/,'wave release must not clear the channel submit gate');
console.log('PASS: task spacing survives completed-wave release and auto-refill; Studio intervalRandom is honored');
