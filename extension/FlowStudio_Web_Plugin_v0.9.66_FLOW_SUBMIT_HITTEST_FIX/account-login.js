// Login and credit reading for Flow accounts. This file does not submit,
// upload, or download videos. It only runs when Studio asks.
(() => {
  function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms));}
  function parseAccount(text){
    const raw=String(text||'');
    const email=(raw.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)||[])[0]||'';
    const credit=raw.match(/(\d[\d,]*)\s*(?:credits?|积分)/i)||raw.match(/(?:credits?|积分|剩余|余额)\s*[:：]?\s*(\d[\d,]*)/i);
    return {email,credits:credit?Number(String(credit[1]).replace(/,/g,'')):null};
  }
  function sameEmail(left,right){
    return String(left||'').trim().toLowerCase()===String(right||'').trim().toLowerCase();
  }
  function isFlow(url){
    return /^https:\/\/flow\.google\.com\//.test(String(url||''));
  }
  // Password and authenticator pages also contain "challenge". Only a real
  // extra prompt should stop the login. A normal password page must continue.
  function isExtraChallenge(url){
    return /signin\/rejected|\/challenge\/(selection|dp|ipp|iap|recaptcha|az|sk|ootp|pk)\b/i.test(String(url||''));
  }
  function decideSession(openEmail, wanted){
    const seen=String(openEmail||'').trim().toLowerCase();
    const need=String(wanted||'').trim().toLowerCase();
    if(!seen || seen===need)return 'reuse';
    return 'switch';
  }
  async function readFlowTab(tabId){
    for(let attempt=0; attempt<4; attempt++){
      try{
        const reply=await chrome.tabs.sendMessage(tabId,{type:'FS_READ_ACCOUNT'});
        if(reply?.ok)return {ok:true,email:reply.email||'',credits:reply.credits==null?null:Number(reply.credits)};
      }catch(_){}
      await sleep(300);
    }
    return {ok:false,email:'',credits:null};
  }
  async function readOpenFlow(){
    const tabs=await chrome.tabs.query({url:['https://flow.google.com/*']});
    let first=null;
    for(const tab of tabs){
      if(tab.id==null)continue;
      const read=await readFlowTab(tab.id);
      if(!read.ok)continue;
      if(!first)first={ok:true,email:read.email||'',credits:read.credits,text:''};
      if(read.email)return {ok:true,email:read.email,credits:read.credits,text:''};
    }
    return first || {ok:false,error:'没有打开的 Flow 页面，无法读取积分'};
  }
  async function findSession(email){
    const tabs=await chrome.tabs.query({url:['https://flow.google.com/*']});
    let blank=null;
    let other='';
    for(const tab of tabs.slice(0,8)){
      if(tab.id==null)continue;
      const read=await readFlowTab(tab.id);
      if(!read.ok)continue;
      if(sameEmail(read.email,email))return {kind:'match',email:read.email,credits:read.credits};
      if(read.email)other=read.email;
      else if(!blank)blank={kind:'blank',email:'',credits:read.credits};
    }
    if(other)return {kind:'other',email:other,credits:null};
    if(blank)return blank;
    return {kind:'none',email:'',credits:null};
  }
  async function login(cred){
    const wanted=String(cred.email||'').trim();
    const session=await findSession(wanted);
    // Chrome profile selection lives in the desktop app. This script only
    // reports a Flow page that is already open. It does not type a password
    // or a verification code, because some accounts do not have 2FA.
    if(session.kind==='match' || session.kind==='blank'){
      return {ok:true,email:session.email||wanted,credits:session.credits,text:''};
    }
    if(session.kind==='other'){
      return {ok:false,error:'当前打开的是另一个 Chrome 用户。请在账号管理勾选对应的 Chrome 用户。'};
    }
    return {ok:false,error:'这个 Chrome 用户还没有打开 Flow。在账号管理勾选该用户后打开 Flow。'};
  }
  globalThis.FlowStudioAccountLogin={login,readOpenFlow,parseAccount,decideSession,isExtraChallenge};
})();
