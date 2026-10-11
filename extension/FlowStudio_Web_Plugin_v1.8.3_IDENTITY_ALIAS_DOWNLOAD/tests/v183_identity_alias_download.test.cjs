const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const page=fs.readFileSync(path.join(root,'page-engine.js'),'utf8');
const downloads=fs.readFileSync(path.join(root,'downloads.js'),'utf8');

test('v183 page engine emits identity aliases for successful VIDEO results',()=>{
  assert.match(page,/const flowPrimaryAliases=new Map\(\)/);
  assert.match(page,/identity_aliases:aliasesForPrimary\(boundId\)/);
  assert.match(page,/bindFlowIdentityAliases\(boundId,\[item\.name,mediaId,\.\.\.\(item\.aliases\|\|\[\]\)\]/);
});

test('v183 download matching accepts any trusted identity alias',()=>{
  assert.match(downloads,/const rowAliases=new Set\(\[row\.id,row\.media_id/);
  assert.match(downloads,/const identityMatch=\[\.\.\.rowAliases\]\.some\(id=>entryAliases\.has\(id\)\)/);
  assert.doesNotMatch(downloads,/e\.group!==group \|\| e\.media_id!==row\.id \|\|/);
});

test('v183 result cache indexes observations by every alias',()=>{
  assert.match(downloads,/for\(const alias of aliases\)/);
  assert.match(downloads,/dlResultCache\.set\(key,observation\)/);
});
