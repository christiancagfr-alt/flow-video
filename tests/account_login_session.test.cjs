const fs = require('fs');
const vm = require('vm');
const path = require('path');

const file = path.join(__dirname, '..', 'extension', 'FlowStudio_Web_Plugin_v0.9.66_FLOW_SUBMIT_HITTEST_FIX', 'account-login.js');
const context = {console, setTimeout, clearTimeout, URL, crypto};
vm.createContext(context);
vm.runInContext(fs.readFileSync(file, 'utf8'), context);
const api = context.FlowStudioAccountLogin;

function assert(condition, message){
  if(!condition) throw new Error(message);
}

assert(api.decideSession('', 'a@example.com') === 'reuse', 'blank flow session is reused');
assert(api.decideSession('a@example.com', 'A@example.com') === 'reuse', 'same account is reused');
assert(api.decideSession('b@example.com', 'a@example.com') === 'switch', 'different account switches once');
assert(api.isExtraChallenge('https://accounts.google.com/v3/signin/challenge/pwd') === false, 'password page is not an extra prompt');
assert(api.isExtraChallenge('https://accounts.google.com/v3/signin/challenge/totp') === false, 'authenticator page can be filled');
assert(api.isExtraChallenge('https://accounts.google.com/v3/signin/challenge/selection') === true, 'method picker is an extra prompt');
assert(api.isExtraChallenge('https://flow.google.com/') === false, 'flow itself is logged in');
console.log('account-login-session-ok');
