// Auxiliary images have a separate registry and never enter VIDEO matching.
let auxDownloadFlight=null;
function auxDownloadMatches(item, job){
  if(!/^image\//.test(String(item.mime||'')))return false;
  return [item.url,item.finalUrl].some(raw=>{
    try{const u=new URL(raw);return u.protocol==='https:' &&
      (u.hostname==='flow.google.com'||u.hostname.endsWith('.googleapis.com')||u.hostname.endsWith('.googleusercontent.com')||u.hostname==='flow-content.google') &&
      decodeURIComponent(u.href).includes(job.media_id);}catch(_){return false;}
  });
}
chrome.downloads.onDeterminingFilename.addListener((item,suggest)=>{
  if(auxDownloadFlight && auxDownloadMatches(item,auxDownloadFlight))suggest({filename:auxDownloadFlight.filename,conflictAction:'uniquify'});
});
chrome.runtime.onMessage.addListener((msg,sender,reply)=>{
  if(!trustedFlowSender(sender)||msg?.type!=='FS_AUX_NATIVE_DOWNLOAD')return;
  (async()=>{
    if(auxDownloadFlight)throw Error('AUX_DOWNLOAD_BUSY');
    if(!/^[A-Za-z0-9_-]{8,}$/.test(String(msg.media_id))||!/^SHOT_[0-9]+$/.test(String(msg.shot_id))||!Number.isSafeInteger(msg.video_id)||msg.video_id<=0)throw Error('INVALID_AUX_ID');
    const filename=`FlowStudio/.incoming/VIDEO_${msg.video_id}/CAMERA_AUX/${msg.shot_id}.png`;
    const key='flowstudio.auxdownload:'+msg.video_id+':'+msg.shot_id+':'+msg.media_id;
    const saved=(await chrome.storage.local.get(key))[key];
    if(saved?.download_id){
      const [item]=await chrome.downloads.search({id:saved.download_id});
      if(item?.state==='complete'&&item.exists)return {ok:true,output_path:item.filename,resolution:saved.resolution};
      if(item?.state==='in_progress')throw Error('AUX_DOWNLOAD_IN_PROGRESS');
    }
    if(saved?.attempted)throw Error('AUX_DOWNLOAD_UNCERTAIN: 请检查原生下载状态，避免重复下载');
    auxDownloadFlight={media_id:msg.media_id,filename};
    const started=Date.now();
    try{
      await chrome.storage.local.set({[key]:{attempted:true,at:started}});
      const click=await chrome.tabs.sendMessage(sender.tab.id,{type:'FS_AUX_CLICK_DOWNLOAD',media_id:msg.media_id});
      if(!click?.ok)throw Error(click?.error||'AUX_NATIVE_DOWNLOAD_FAILED');
      const deadline=Date.now()+180000;
      let id=null;
      while(Date.now()<deadline){
        const rows=await chrome.downloads.search(id?{id}:{startedAfter:new Date(started-1000).toISOString()});
        const matches=rows.filter(item=>auxDownloadMatches(item,auxDownloadFlight));
        if(matches.length>1)throw Error('AUX_DOWNLOAD_AMBIGUOUS');
        if(matches.length===1){
          const item=matches[0];id=item.id;
          await chrome.storage.local.set({[key]:{attempted:true,download_id:id,resolution:click.resolution}});
          if(item.state==='interrupted')throw Error('AUX_DOWNLOAD_INTERRUPTED');
          if(item.state==='complete')return {ok:true,output_path:item.filename,resolution:click.resolution};
        }
        await new Promise(r=>setTimeout(r,1000));
      }
      throw Error('AUX_DOWNLOAD_TIMEOUT');
    }finally{auxDownloadFlight=null;}
  })().then(reply).catch(e=>reply({ok:false,error:String(e.message||e)}));
  return true;
});
