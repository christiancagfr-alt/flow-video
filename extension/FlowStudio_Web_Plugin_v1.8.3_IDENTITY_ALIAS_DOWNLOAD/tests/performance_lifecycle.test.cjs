// BG2 deliberately restores baseline polling; thumbnail memory limits stay in place.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const text=fs.readFileSync(require('node:path').join(__dirname,'../content.js'),'utf8');
assert.doesNotMatch(text,/performanceInterval|updatePowerMode|powerMode/);
assert.match(text,/setInterval\(pullJob, 3000\)/);
assert.match(text,/state.scanTimer = setInterval\(scanOnce, 2000\)/);
assert.match(text,/setInterval\(\(\)=>\{void recoverPendingReservations\(\);\},10000\)/);
const revoked=[],state={thumbnailUrls:new Map([['a','blob:a'],['b','blob:b']])};
const source=text.slice(text.indexOf('  function clearThumbnailCache()'),text.indexOf('  const $ ='));
vm.runInNewContext(source+';clearThumbnailCache()',{state,URL:{revokeObjectURL:x=>revoked.push(x)}});
assert.equal(state.thumbnailUrls.size,0);assert.deepEqual(revoked,['blob:a','blob:b']);
console.log('PASS restored fixed polling with no idle/visibility gate; bounded thumbnail cleanup retained');
