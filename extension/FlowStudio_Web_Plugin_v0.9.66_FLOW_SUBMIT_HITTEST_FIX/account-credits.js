// Read the Flow balance already shown on the account card. Does not read cookies
// and does not log in. The top Flow page is handled by content.js, which scores
// the signed-in account button. This file only reads a card frame.
const emailRe=/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/ig;
function flowCreditCount(text){
  const raw=String(text||'');
  const patterns=[
    /(\d[\d,]*)\s*个\s*Google\s*Flow\s*点数/i,
    /(\d[\d,]*)\s*个\s*点数/,
    /(\d[\d,]*)\s*(?:Google\s*Flow\s*)?credits?/i,
    /(\d[\d,]*)\s*积分/,
    /(?:积分|剩余|余额)\s*[:：]?\s*(\d[\d,]*)/i
  ];
  for(const pattern of patterns){
    const found=raw.match(pattern);
    if(!found)continue;
    const value=Number(String(found[1]).replace(/,/g,''));
    if(Number.isFinite(value))return value;
  }
  return null;
}
function cardText(){
  const parts=[];
  const seen=new Set();
  function visit(node, depth){
    if(!node || depth>6 || seen.has(node))return;
    seen.add(node);
    const kids=node.children||[];
    for(const el of kids){
      if(el.shadowRoot){
        parts.push(el.shadowRoot.textContent||'');
        visit(el.shadowRoot, depth+1);
      }
      visit(el, depth+1);
    }
  }
  try{visit(document.documentElement, 0);}catch(_){}
  parts.push(document.body?.innerText||'');
  return parts.join('\n');
}
function emailForPoints(raw){
  const mark=raw.search(/Google\s*Flow\s*点数|Flow\s*credits/i);
  const head=mark>=0?raw.slice(0, mark):raw;
  const emails=head.match(emailRe)||[];
  return String(emails[emails.length-1]||'').trim();
}
let lastCreditKey='';
let sawPoints=false;
let cardObserver=null;
function publishCardCredits(){
  const raw=cardText();
  if(!/Google\s*Flow\s*点数|Flow\s*credits/i.test(raw))return false;
  const credits=flowCreditCount(raw);
  const email=emailForPoints(raw);
  if(credits==null || !email)return false;
  const key=email.toLowerCase()+'|'+credits;
  if(key===lastCreditKey)return true;
  lastCreditKey=key;
  sawPoints=true;
  try{chrome.runtime.sendMessage({type:'FS_PAGE_CREDITS',email,credits});}catch(_){}
  if(cardObserver){cardObserver.disconnect();cardObserver=null;}
  return true;
}
function watchCard(){
  if(window.top===window && location.hostname==='flow.google.com')return;
  [800, 2500, 6000].forEach(delay=>setTimeout(publishCardCredits, delay));
  setInterval(()=>{if(!publishCardCredits() && sawPoints)lastCreditKey='';}, 60000);
  if(!document.documentElement)return;
  let timer=0;
  cardObserver=new MutationObserver(()=>{
    if(sawPoints)return;
    clearTimeout(timer);
    timer=setTimeout(publishCardCredits, 800);
  });
  cardObserver.observe(document.documentElement,{subtree:true,childList:true});
}
watchCard();
