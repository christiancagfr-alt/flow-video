local platformSource=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local platform=assert(loadfile(platformSource:match('^(.*)/[^/]+$')..'/FlowStudio_Platform.lua'))()
local os,io,loadfile=platform.os,platform.io,platform.loadfile
if jit and jit.off then pcall(jit.off) end
-- FlowStudio Finish Batch V7.2.2 - ignore ghost/misaligned blue API markers safely
-- Missing complete videos are skipped consistently in normal/recovery/export paths.
-- Structural ambiguity remains fatal to prevent wrong deletion/export.
-- V1 defines video ranges; A1 participates in cleanup safety; V2+ and A2+ stay protected.
-- Finish phase. Never replay a possibly partially applied deletion.
local function read(path)
    local f=io.open(path,'r');local t={};if not f then return t end
    for line in f:lines() do local k,v=line:match('^([^=]+)=(.*)$');if k then t[k]=v end end
    f:close();return t
end
local function write(path,t)
    local f=assert(io.open(path..'.tmp','w'))
    for k,v in pairs(t) do f:write(k..'='..tostring(v):gsub('[\r\n]',' ')..'\n') end
    f:close();assert(os.rename(path..'.tmp',path))
end
local function nonempty(path)
    local f=io.open(path or '','rb');if not f then return false end
    local n=f:seek('end');f:close();return n and n>0
end
local function renderStatus(value)
    local s=tostring(value or ''):match('^%s*(.-)%s*$')
    local mapped={['完成']='Complete',['已完成']='Complete',['失败']='Failed',['已失败']='Failed',['取消']='Cancelled',['已取消']='Cancelled',['正在渲染']='Rendering',['排队中']='Queued',['等待']='Queued',['准备就绪']='Ready',completed='Complete',complete='Complete',failed='Failed',cancelled='Cancelled',canceled='Cancelled',rendering='Rendering'}
    return mapped[s] or mapped[s:lower()] or s
end
local function frameTimecode(frame,fps)
    fps=tonumber(fps) or 30
    local nominal=math.floor(fps+0.5)
    if nominal<1 then nominal=30 end
    local f=math.max(0,math.floor(tonumber(frame) or 0))
    local ff=f%nominal;local total=math.floor(f/nominal)
    local ss=total%60;local mm=math.floor(total/60)%60;local hh=math.floor(total/3600)
    return string.format('%02d:%02d:%02d:%02d',hh,mm,ss,ff)
end
local function run(app,job,report,test)
    test=test or {};local root=test.root or os.getenv('HOME')..'/Documents/FlowStudioResolveBridge'
    local bid,attempt=job.batch_id,job.attempt_id
    assert(bid and bid:match('^[%w_-]+$') and attempt and attempt:match('^[a-f0-9]+$'),'INVALID_ID')
    local base=root..'/v0_5_0/batches/'..bid..'/autoedit/'..attempt
    assert(job.payload_path==base..'/autoedit.ini','PAYLOAD_PATH_MISMATCH')
    local p=read(job.payload_path);assert(p.batch_id==bid and p.attempt_id==attempt and p.work_date==job.work_date,'IDENTITY_MISMATCH')
    local state=read(base..'/finish.ini')
    -- A previous build could finish the actual delete successfully and then fail only because
    -- V2+ protected video layers did not ripple exactly like V1. That specific failure is safe
    -- to recover by re-validating V1 only; NEVER replay the delete itself.
    local detail=tostring(state.detail or '')
    local recoveringAppliedCleanup=state.stage=='CLEANING_ERROR' and (
        detail:find('RIPPLE_RANGE_MISMATCH',1,true)~=nil or
        detail:find('RECOVERY_VIDEO_SOURCE_MISSING',1,true)~=nil or
        detail:find('RECOVERY_VIDEO_EMPTY',1,true)~=nil
    )
    local explicitMode=test.finishMode or (
        (job.finish_mode=='export' or job.finish_mode=='cleanup_only' or job.finish_mode=='watermark_only' or job.finish_mode=='cleanup')
        and job.finish_mode or nil
    )
    assert(state.stage~='CLEANING' and (explicitMode=='watermark_only' or explicitMode=='export' or state.stage~='CLEANING_ERROR' or recoveringAppliedCleanup),
        'CLEANUP_INTERRUPTED: 保留现场，禁止重复删除')
    local pm=assert(app:GetProjectManager());local project=assert(pm:GetCurrentProject());local tl=assert(project:GetCurrentTimeline())
    local uid=tl:GetUniqueId()
    -- Convert an absolute Resolve timeline frame to the timecode visible in the Edit page
    -- and move the playhead there. This is diagnostic-only: it never edits clips or markers.
    local function locateTimelineFrame(absFrame)
        local tc=frameTimecode(absFrame,p.timeline_fps)
        local ok=false
        pcall(function() ok=tl:SetCurrentTimecode(tc) and true or false end)
        return tc,ok
    end
    local function guard()
        local a=pm:GetCurrentProject();local t=a and a:GetCurrentTimeline()
        assert(a and a:GetName()==p.project_name and t and t:GetName()==p.timeline_name and t:GetUniqueId()==uid,'ACTIVE_TIMELINE_CHANGED')
    end
    guard();assert(not project:IsRenderingInProgress(),'RENDER_ALREADY_RUNNING')
    -- An explicit choice separates cleanup, watermark refresh, and batch export.
    -- Never infer that old red/blue markers should be applied again.
    local finishMode=explicitMode
    if not finishMode and test.inspectOnly then finishMode='cleanup' end
    if not finishMode and platform.windows then finishMode=platform.finishChoice() end
    if not finishMode then
        local command = [[/usr/bin/osascript -e 'button returned of (display dialog "请选择本次操作。\n\n清理并导出：按红色／蓝色标记删除片段，再批量导出。\n\n直接批量导出：你已经完成清理，按当前时间线导出，不再检查清理标记或删除片段。" with title "Flow Studio · 完成批次" buttons {"取消", "清理并导出", "直接批量导出"} default button "直接批量导出" cancel button "取消")' 2>/dev/null]]
        local process=assert(io.popen(command,'r'),'FINISH_CHOICE_UNAVAILABLE')
        local selected=process:read('*a'):match('^%s*(.-)%s*$');process:close()
        if selected=='清理并导出' then finishMode='cleanup'
        elseif selected=='直接批量导出' then finishMode='export'
        else error('FINISH_CANCELLED: 已取消，未清理、未启动导出') end
    end
    assert(finishMode=='cleanup' or finishMode=='cleanup_only' or finishMode=='watermark_only' or finishMode=='export','INVALID_FINISH_MODE')
    local exportOnly=(finishMode=='export')
    local watermarkOnly=(finishMode=='watermark_only')
    local cleanupOnly=(finishMode=='cleanup_only')
    guard();assert(not project:IsRenderingInProgress(),'RENDER_ALREADY_RUNNING')

    local function pulse(stage,detail,extra)
        if test.inspectOnly then return end
        state={batch_id=bid,attempt_id=attempt,stage=stage,detail=detail}
        for k,v in pairs(extra or {}) do state[k]=v end
        write(base..'/finish.ini',state)
        write(root..'/pipeline.lock',{batch_id=bid,attempt_id=attempt,action='FINISH_BATCH',work_date=p.work_date,stage=stage})
        local repFields={batch_id=bid,project=p.project_name,timeline=p.timeline_name,manual_render='false'}
        for k,v in pairs(extra or {}) do repFields[k]=v end
        report(stage,detail,repFields)
    end
    -- IMPORTANT: Flow Studio cleanup owns VIDEO TRACK 1 (V1) only.
    -- V2/V3/... are user-protected overlay/title/effect layers and are intentionally invisible
    -- to this script: no item scan, no ownership check, no marker candidate check, no fingerprint,
    -- no ripple verification and no cleaned-timeline verification ever includes them.
    local MAIN_VIDEO_TRACK=1
    local function items()
        local out={}
        assert(tl:GetTrackCount('video')>=MAIN_VIDEO_TRACK,'V1_VIDEO_TRACK_MISSING')
        for _,item in ipairs(assert(tl:GetItemListInTrack('video',MAIN_VIDEO_TRACK))) do
            out[#out+1]={item=item,id=item:GetUniqueId(),kind='video',track=MAIN_VIDEO_TRACK,s=item:GetStart(),e=item:GetEnd()}
        end
        -- Audio behavior is unchanged: all audio tracks remain available for exact A/V cleanup checks.
        for track=1,tl:GetTrackCount('audio') do
            for _,item in ipairs(assert(tl:GetItemListInTrack('audio',track))) do
                out[#out+1]={item=item,id=item:GetUniqueId(),kind='audio',track=track,s=item:GetStart(),e=item:GetEnd()}
            end
        end
        return out
    end
    local function fingerprint()
        local rows={}
        for _,c in ipairs(items()) do rows[#rows+1]=c.kind..':'..c.track..':'..c.id..':'..c.s..':'..c.e end
        table.sort(rows);return table.concat(rows,';')
    end
    -- Export rule: MarkIn/MarkOut are calculated ONLY from V1 complete-video ranges.
    -- Rendering itself is the normal Resolve timeline composite, so every visible/enabled upper
    -- video track (V2/V3/...) is included in the final picture without participating in range logic.
    local function prepareExport()
        local loaded=(project:LoadRenderPreset('FlowStudio_Final') or project:LoadRenderPreset('H.264 Master') or project:LoadRenderPreset('MP4'))
        if not loaded then
            -- First-time user without FlowStudio_Final or English 'H.264 Master': configure MP4 + H.264 + AAC directly via API and auto-save FlowStudio_Final.
            local fmtOk=project:SetCurrentRenderFormatAndCodec('mp4','H264')
            if not fmtOk and project.GetRenderFormats and project.GetRenderCodecs then
                local okF,fmts=pcall(function() return project:GetRenderFormats() end)
                if okF and type(fmts)=='table' then
                    for fmtName,ext in pairs(fmts) do
                        local ex=tostring(ext or ''):lower()
                        local fn=tostring(fmtName or ''):lower()
                        if ex=='mp4' or ex=='.mp4' or fn=='mp4' then
                            local okC,codecs=pcall(function() return project:GetRenderCodecs(fmtName) end)
                            if okC and type(codecs)=='table' then
                                for desc,cName in pairs(codecs) do
                                    local cl=tostring(cName or ''):lower()
                                    local dl=tostring(desc or ''):lower()
                                    if cl:find('264',1,true) or dl:find('264',1,true) then
                                        local okS,sRes=pcall(function() return project:SetCurrentRenderFormatAndCodec(fmtName,cName) end)
                                        if okS and sRes then fmtOk=true;break end
                                    end
                                end
                            end
                            if fmtOk then break end
                        end
                    end
                end
            end
            assert(fmtOk,'MP4_H264_UNAVAILABLE')
            pcall(function() project:SetRenderSettings({ExportVideo=true,ExportAudio=true,AudioCodec='aac',AudioSampleRate=48000}) end)
            pcall(function() if project.SaveAsNewRenderPreset then project:SaveAsNewRenderPreset('FlowStudio_Final') end end)
        else
            assert(project:SetCurrentRenderFormatAndCodec('mp4','H264'),'MP4_H264_UNAVAILABLE')
        end
        assert(project:SetCurrentRenderMode(1),'SINGLE_CLIP_MODE_FAILED')
    end
    -- Ripple-delete V1/A only while temporarily protecting every video track above V1.
    -- We never enumerate items on V2+; only their track lock state is preserved/restored.
    local function withUpperVideoTracksProtected(fn)
        local states={};local total=tl:GetTrackCount('video')
        for track=2,total do
            states[track]=tl:GetIsTrackLocked('video',track) and true or false
            if not states[track] then
                assert(tl:SetTrackLock('video',track,true),'UPPER_VIDEO_TRACK_PROTECT_FAILED: V'..track)
            end
        end
        local ok,value=pcall(fn)
        local restoreError=nil
        for track=2,total do
            local wanted=states[track]
            local now=tl:GetIsTrackLocked('video',track) and true or false
            if now~=wanted then
                local restored=tl:SetTrackLock('video',track,wanted)
                if not restored and not restoreError then restoreError='UPPER_VIDEO_TRACK_RESTORE_FAILED: V'..track end
            end
        end
        if restoreError then error(restoreError) end
        if not ok then error(value) end
        return value
    end
    -- AI Watermark helper: mounts/refreshes contiguous per-host Main (lower track) + Sub (upper track) PNG watermarks.
    -- Safely replaces any previous Flow Studio watermark clips (`flowstudio_wm_`) using non-ripple DeleteClips(clips, false).
    local function clipFrameSafe(clip,method)
        for _=1,6 do
            local ok,v=pcall(function() return clip[method](clip) end)
            local n=ok and tonumber(v) or nil
            if n and n==n and math.abs(n)~=math.huge then
                return math.floor(n+0.5)
            end
            if os.clock then local t0=os.clock();while os.clock()-t0<0.15 do end end
        end
        return nil
    end

    local function isFlowStudioWmClip(clip)
        local okN,cname=pcall(function() return clip:GetName() end)
        if okN and type(cname)=='string' and cname:find('flowstudio_wm_',1,true) then return true end
        local okM,mp=pcall(function() return clip:GetMediaPoolItem() end)
        if okM and mp then
            local okF,fp=pcall(function() return mp:GetClipProperty('File Path') end)
            if okF and type(fp)=='string' and fp:find('flowstudio_wm_',1,true) then return true end
            local okMN,mn=pcall(function() return mp:GetName() end)
            if okMN and type(mn)=='string' and mn:find('flowstudio_wm_',1,true) then return true end
        end
        return false
    end

    local function normalizeResolveFreeRes(w,h)
        w=math.max(2,math.floor((tonumber(w) or 720)+0.5))
        h=math.max(2,math.floor((tonumber(h) or 1280)+0.5))
        local maxW,maxH=2160,3840
        if w>=h then maxW,maxH=3840,2160 end
        if w>maxW or h>maxH then
            local sc=math.min(maxW/w,maxH/h)
            w=math.max(2,math.floor(w*sc+0.5))
            h=math.max(2,math.floor(h*sc+0.5))
        end
        w=math.max(2,math.min(maxW,math.floor(w/2)*2))
        h=math.max(2,math.min(maxH,math.floor(h/2)*2))
        return w,h
    end

    local function parseResPair(raw)
        if type(raw)~='string' then return nil,nil end
        local sw,sh=raw:match('^(%s*%d+)%s*[xX×]%s*(%d+%s*)$')
        if not sw or not sh then
            sw,sh=raw:match('(%d+)%s*[xX×]%s*(%d+)')
        end
        local nw,nh=tonumber(sw),tonumber(sh)
        if nw and nh and nw>0 and nh>0 then return nw,nh end
        return nil,nil
    end

    local function isStillMediaItem(mp)
        if not mp then return true end
        local okT,tp=pcall(function() return mp:GetClipProperty('Type') end)
        if okT and type(tp)=='string' and tp:lower():find('still',1,true) then return true end
        local okF,fp=pcall(function() return mp:GetClipProperty('File Path') end)
        if okF and type(fp)=='string' and fp~='' then
            local low=fp:lower()
            if low:match('%.png$') or low:match('%.jpe?g$') or low:match('%.webp$') or low:match('%.gif$') or low:match('%.bmp$') or low:match('%.tiff?$') then
                return true
            end
        end
        return false
    end

    local function getMediaCacheKey(mp)
        if not mp then return nil end
        if mp.GetUniqueId then
            local okU,uidVal=pcall(function() return mp:GetUniqueId() end)
            if okU and uidVal and uidVal~='' then return tostring(uidVal) end
        end
        return mp
    end

    local function getCachedMediaPath(mp,pathCache)
        if not mp or not mp.GetClipProperty then return nil end
        local key=pathCache and getMediaCacheKey(mp) or nil
        if key~=nil and pathCache[key]~=nil then
            return pathCache[key]~='' and pathCache[key] or nil
        end
        local okF,fp=pcall(function() return mp:GetClipProperty('File Path') end)
        local val=(okF and type(fp)=='string') and fp or ''
        if key~=nil then pathCache[key]=val end
        return val~='' and val or nil
    end

    local function collectTimelineVideoSnapshots()
        local v1Snap,upperSnap={},{}
        local resCache={}
        local function queryMpInfo(mp,checkStill)
            if not mp or not mp.GetClipProperty then return nil,nil,true end
            local key=getMediaCacheKey(mp)
            local cached=key~=nil and resCache[key] or nil
            if not cached then
                local cw,ch=nil,nil
                local okR,rStr=pcall(function() return mp:GetClipProperty('Resolution') end)
                if okR then cw,ch=parseResPair(rStr) end
                cached={w=cw,h=ch}
                if key~=nil then resCache[key]=cached end
            end
            if checkStill and cached.still==nil then
                cached.still=isStillMediaItem(mp) and true or false
            end
            return cached.w,cached.h,cached.still
        end
        local vCnt=tonumber(tl.GetTrackCount and tl:GetTrackCount('video')) or 1
        for _,clip in ipairs(tl:GetItemListInTrack('video',MAIN_VIDEO_TRACK) or {}) do
            local cs=clipFrameSafe(clip,'GetStart')
            local ce=clipFrameSafe(clip,'GetEnd')
            if cs and ce and ce>cs then
                local cw,ch=nil,nil
                local okM,mp=pcall(function() return clip:GetMediaPoolItem() end)
                if okM and mp then
                    cw,ch=queryMpInfo(mp,false)
                end
                v1Snap[#v1Snap+1]={s=cs,e=ce,w=cw,h=ch}
            end
        end
        for trk=2,vCnt do
            local en=true
            if tl.GetIsTrackEnabled then
                local okE,valE=pcall(function() return tl:GetIsTrackEnabled('video',trk) end)
                if okE and valE==false then en=false end
            end
            if en then
                for _,clip in ipairs(tl:GetItemListInTrack('video',trk) or {}) do
                    if not isFlowStudioWmClip(clip) then
                        local cs=clipFrameSafe(clip,'GetStart')
                        local ce=clipFrameSafe(clip,'GetEnd')
                        if cs and ce and ce>cs then
                            local okM,mp=pcall(function() return clip:GetMediaPoolItem() end)
                            if okM and mp then
                                local uw,uh,isStill=queryMpInfo(mp,true)
                                if not isStill and uw and uh then
                                    upperSnap[#upperSnap+1]={s=cs,e=ce,w=uw,h=uh,track=trk}
                                end
                            end
                        end
                    end
                end
            end
        end
        return v1Snap,upperSnap
    end

    local function detectVideoExportRes(vStart,vEnd,pre,v1Snap,upperSnap,baseTlW,baseTlH)
        local bestW,bestH,bestOv=nil,nil,0
        for _,c in ipairs(v1Snap or {}) do
            if c.w and c.h and c.s<vEnd and c.e>vStart then
                local ov=math.min(c.e,vEnd)-math.max(c.s,vStart)
                if ov>bestOv then
                    bestOv=ov;bestW=c.w;bestH=c.h
                end
            end
        end
        if not bestW or not bestH then
            local ew=tonumber(p[pre..'export_width'])
            local eh=tonumber(p[pre..'export_height'])
            if ew and eh and ew>0 and eh>0 then
                bestW,bestH=ew,eh
            elseif tostring(p[pre..'aspect_ratio'] or '')=='16:9' then
                bestW,bestH=1280,720
            else
                bestW,bestH=720,1280
            end
        end
        -- Vertical split-screen composite safeguard (e.g. 拼接视频: 16:9 V1 top + 9:16 video B-roll on V2+):
        -- When a 16:9 V1 clip is composited together with a portrait video clip on V2+ on a portrait timeline,
        -- preserve the portrait timeline resolution so both top and bottom split-screen halves export intact.
        if bestW>bestH and (tonumber(baseTlW) or 720)<(tonumber(baseTlH) or 1280) then
            for _,uc in ipairs(upperSnap or {}) do
                if uc.w<uc.h and uc.s<vEnd and uc.e>vStart and (math.min(uc.e,vEnd)-math.max(uc.s,vStart))>=5 then
                    return normalizeResolveFreeRes(baseTlW or 720,baseTlH or 1280)
                end
            end
        end
        return normalizeResolveFreeRes(bestW,bestH)
    end

    local function setTimelineResolution(targetW,targetH)
        if not tl.SetSetting or not tl.GetSetting then return false end
        local curW=tonumber(tl:GetSetting('timelineResolutionWidth'))
        local curH=tonumber(tl:GetSetting('timelineResolutionHeight'))
        if curW==targetW and curH==targetH then return false end
        assert(tl:SetSetting('useCustomSettings','1'),'TIMELINE_CUSTOM_SETTINGS_FAILED')
        -- Always apply the smaller (<=2160) axis first so DaVinci Resolve Free never rejects an intermediate >2160 short edge.
        if targetW>=targetH then
            assert(tl:SetSetting('timelineResolutionHeight',tostring(targetH)),'TIMELINE_RESOLUTION_FAILED: timelineResolutionHeight='..tostring(targetH))
            assert(tl:SetSetting('timelineResolutionWidth',tostring(targetW)),'TIMELINE_RESOLUTION_FAILED: timelineResolutionWidth='..tostring(targetW))
        else
            assert(tl:SetSetting('timelineResolutionWidth',tostring(targetW)),'TIMELINE_RESOLUTION_FAILED: timelineResolutionWidth='..tostring(targetW))
            assert(tl:SetSetting('timelineResolutionHeight',tostring(targetH)),'TIMELINE_RESOLUTION_FAILED: timelineResolutionHeight='..tostring(targetH))
        end
        local chkW=tonumber(tl:GetSetting('timelineResolutionWidth'))
        local chkH=tonumber(tl:GetSetting('timelineResolutionHeight'))
        assert(chkW==targetW and chkH==targetH,'TIMELINE_RESOLUTION_NOT_CONFIRMED: '..tostring(chkW)..'x'..tostring(chkH)..' ~= '..tostring(targetW)..'x'..tostring(targetH))
        if project.SetCurrentTimeline then
            pcall(function() project:SetCurrentTimeline(tl) end)
        end
        return true
    end

    local function applyBatchWatermarks(activePlan)
        local wmPath=job.watermark_plan_path or (root..'/v0_5_0/batches/'..bid..'/watermark_plan.ini')
        if not test.root and not platform.windows and not nonempty(wmPath) then
            local pyBin=p.python_path or '/Applications/Flow Studio.app/Contents/Resources/python/bin/python3'
            local pyRoot='/Applications/Flow Studio.app/Contents/Resources'
            if nonempty(pyBin) then
                local sq=function(s) return "'"..tostring(s):gsub("'","'\\''").."'" end
                local prepCmd='PYTHONPATH='..sq(pyRoot)..' '..sq(pyBin)..' -m app.services.ai_watermark --prepare-batch '..sq(bid)..' '..sq(root..'/v0_5_0/batches/'..bid)..' 2>/dev/null'
                pcall(function()
                    local h=io.popen(prepCmd,'r')
                    if h then h:read('*a');h:close() end
                end)
            end
        end
        local wmPlan=read(wmPath)
        local curTlW=(tl.GetSetting and tonumber(tl:GetSetting('timelineResolutionWidth'))) or 720
        local curTlH=(tl.GetSetting and tonumber(tl:GetSetting('timelineResolutionHeight'))) or 1280
        local wmV1Snap,wmUpperSnap=collectTimelineVideoSnapshots()
        local surviving={}
        local minFrame,maxFrame=nil,nil
        for i=1,tonumber(p.video_count) or 0 do
            local pre='v'..i..'_'
            if activePlan[pre..'skip']~='true' then
                local s=tonumber(activePlan[pre..'start'])
                local e=tonumber(activePlan[pre..'end'])
                local vid=tostring(p[pre..'id'] or '')
                if s and e and e>s and vid~='' then
                    local vw,vh=detectVideoExportRes(s,e,pre,wmV1Snap,wmUpperSnap,curTlW,curTlH)
                    local vOrient=(vw>vh) and 'landscape' or 'portrait'
                    surviving[#surviving+1]={vid=vid,s=s,e=e,orient=vOrient}
                    minFrame=minFrame and math.min(minFrame,s) or s
                    maxFrame=maxFrame and math.max(maxFrame,e) or e
                end
            end
        end
        if #surviving==0 or not minFrame or not maxFrame then
            return ''
        end
        table.sort(surviving,function(a,b) return a.s<b.s end)

        -- 1. Remove any previously auto-added Flow Studio watermark clips in this batch's frame span (non-ripple!).
        local oldWmClips={}
        local unlockRestore={}
        local vTrackTotal=tl:GetTrackCount('video')
        for trk=2,vTrackTotal do
            local list=tl:GetItemListInTrack('video',trk) or {}
            local hitOnTrack=false
            for _,clip in ipairs(list) do
                local cs=clipFrameSafe(clip,'GetStart')
                local ce=clipFrameSafe(clip,'GetEnd')
                if cs and ce and ce>(minFrame-100) and cs<(maxFrame+100) and isFlowStudioWmClip(clip) then
                    oldWmClips[#oldWmClips+1]=clip
                    hitOnTrack=true
                end
            end
            if hitOnTrack and tl:GetIsTrackLocked('video',trk) then
                unlockRestore[trk]=true
                tl:SetTrackLock('video',trk,false)
            end
        end
        if #oldWmClips>0 then
            assert(tl:DeleteClips(oldWmClips,false),'WATERMARK_OLD_DELETE_FAILED')
        end
        for trk,_ in pairs(unlockRestore) do
            pcall(function() tl:SetTrackLock('video',trk,true) end)
        end

        local scripturesMounted=false
        local mountedSrtPath=''
        local function mountBatchScriptures()
            if test.root and not test.allowScriptureMount then return false end
            local pyBin=p.python_path or '/Applications/Flow Studio.app/Contents/Resources/python/bin/python3'
            local pyRoot='/Applications/Flow Studio.app/Contents/Resources'
            local sq=function(s) return "'"..tostring(s):gsub("'","'\\''").."'" end
            local srtPath=base..'/scriptures_'..bid..'.srt'
            local batchSrtPath=root..'/v0_5_0/batches/'..bid..'/经文字幕_'..bid..'.srt'
            if nonempty(pyBin) and not platform.windows then
                pcall(function() os.remove(srtPath) end)
                pcall(function() os.remove(batchSrtPath) end)
                pulse('CLEANING','正在按清理后时间线生成并对齐经文字幕 (SUV)…')
                local subCmd='PYTHONPATH='..sq(pyRoot)..' '..sq(pyBin)..' -m app.services.scripture_subtitles '..sq(base)..' 2>/dev/null'
                pcall(function()
                    local sh=io.popen(subCmd,'r')
                    if sh then sh:read('*a');sh:close() end
                end)
            end
            local activeSrt=nonempty(batchSrtPath) and batchSrtPath or (nonempty(srtPath) and srtPath or nil)
            if not activeSrt then return false end
            local freshSrt=base..'/scriptures_'..bid..'_'..tostring(os.time())..'.srt'
            pcall(function()
                local rf=io.open(activeSrt,'rb')
                if rf then
                    local raw=rf:read('*a');rf:close()
                    if raw and #raw>0 then
                        local wf=io.open(freshSrt,'wb')
                        if wf then wf:write(raw);wf:close();activeSrt=freshSrt end
                    end
                end
            end)
            mountedSrtPath=tostring(activeSrt or '')
            local subOk=false
            pcall(function()
                local pool=project:GetMediaPool()
                if not pool then return end
                local rootFolder=pool:GetRootFolder()
                local prevFolder=pool:GetCurrentFolder()
                local subFolder=nil
                for _,sf in ipairs(rootFolder:GetSubFolderList() or {}) do
                    if sf:GetName()=='Subtitles' then subFolder=sf;break end
                end
                if not subFolder then subFolder=pool:AddSubFolder(rootFolder,'Subtitles') end
                if subFolder then pool:SetCurrentFolder(subFolder) end
                local subTrackCnt=tonumber(tl.GetTrackCount and tl:GetTrackCount('subtitle')) or 0
                local oldSubs={}
                for strk=1,subTrackCnt do
                    pcall(function() tl:SetTrackLock('subtitle',strk,false) end)
                    pcall(function() tl:SetTrackEnable('subtitle',strk,true) end)
                    for _,sc in ipairs(tl:GetItemListInTrack('subtitle',strk) or {}) do
                        oldSubs[#oldSubs+1]=sc
                    end
                end
                if #oldSubs>0 then
                    pcall(function() tl:DeleteClips(oldSubs,false) end)
                end
                if subTrackCnt<1 and tl.AddTrack then
                    pcall(function() tl:AddTrack('subtitle') end)
                end
                pcall(function() tl:SetTrackLock('subtitle',1,false) end)
                pcall(function() tl:SetTrackEnable('subtitle',1,true) end)
                if subFolder and pool.DeleteClips then
                    local staleSrt={}
                    for _,existing in ipairs(subFolder:GetClipList() or {}) do
                        local okP,fp=pcall(function() return existing:GetClipProperty('File Path') end)
                        local okN,nm=pcall(function() return existing:GetName() end)
                        if (okP and fp==activeSrt) or (okN and type(nm)=='string' and (nm:find(bid,1,true) or nm:find('经文字幕',1,true))) then
                            staleSrt[#staleSrt+1]=existing
                        end
                    end
                    if #staleSrt>0 then pcall(function() pool:DeleteClips(staleSrt) end) end
                end
                local clips=pool:ImportMedia({activeSrt})
                if clips and clips[1] then
                    if pool.SetSelectedClip then pcall(function() pool:SetSelectedClip(clips[1]) end) end
                    pcall(function() tl:SetCurrentTimecode('01:00:00:00') end)
                    local appended=pool:AppendToTimeline({clips[1]})
                    if appended and appended[1] then subOk=true end
                end
                if prevFolder then pcall(function() pool:SetCurrentFolder(prevFolder) end) end
            end)
            return subOk
        end

        local function syncProjectDbAndReload(wmSyncItems)
            if (#wmSyncItems==0) and (not scripturesMounted) then
                return false
            end
            local prevPage,prevTc=nil,nil
            pcall(function() if app.GetCurrentPage then prevPage=app:GetCurrentPage() end end)
            pcall(function() if tl.GetCurrentTimecode then prevTc=tl:GetCurrentTimecode() end end)
            assert(pm:SaveProject(),'SAVE_WATERMARK_PRE_SYNC_FAILED')
            local syncDummy='__FlowStudio_Sync__'
            local switchedOff=false
            if pm.CloseProject then
                local okC,closed=pcall(function() return pm:CloseProject(project) end)
                if okC and closed then switchedOff=true end
            end
            if not switchedOff then
                local dummy=pm:LoadProject(syncDummy)
                if not dummy and pm.GotoRootFolder then
                    pcall(function() pm:GotoRootFolder() end)
                    dummy=pm:LoadProject(syncDummy)
                end
                if not dummy and pm.CreateProject then
                    dummy=pm:CreateProject(syncDummy)
                    if dummy then pcall(function() pm:SaveProject() end) end
                end
            end
            local pyBin=p.python_path or '/Applications/Flow Studio.app/Contents/Resources/python/bin/python3'
            local pyRoot='/Applications/Flow Studio.app/Contents/Resources'
            local sq=function(s) return "'"..tostring(s):gsub("'","'\\''").."'" end
            local syncPath=nil
            if #wmSyncItems>0 then
                syncPath=root..'/v0_5_0/batches/'..bid..'/watermark_sync.ini'
                local syncSpec={
                    project_name=p.project_name,
                    timeline_name=p.timeline_name,
                    timeline_uid=uid,
                    project_db_path=tostring(test.projectDbPath or ''),
                    item_count=#wmSyncItems,
                }
                for idx_w,entry in ipairs(wmSyncItems) do
                    local wp='item_'..tostring(idx_w)..'_'
                    syncSpec[wp..'uid']=entry.uid
                    syncSpec[wp..'track']=entry.track
                    syncSpec[wp..'start']=entry.start
                    syncSpec[wp..'duration']=entry.duration
                    syncSpec[wp..'png']=entry.png
                    syncSpec[wp..'kind']=entry.kind
                    syncSpec[wp..'label']=entry.label
                end
                write(syncPath,syncSpec)
            end
            local wantStyle=scripturesMounted and not platform.windows and nonempty(pyBin)
            if syncPath and wantStyle and not test.root then
                local pyOneLiner="import sys\n"
                    .."try:\n"
                    .."    from app.services import ai_watermark\n"
                    .."    ai_watermark.sync_resolve_project_watermark_durations(sys.argv[1])\n"
                    .."except Exception:\n"
                    .."    pass\n"
                    .."try:\n"
                    .."    from app.services import scripture_subtitles\n"
                    .."    scripture_subtitles.ensure_resolve_project_subtitle_track_style(sys.argv[2], sys.argv[3], sys.argv[4])\n"
                    .."except Exception:\n"
                    .."    pass\n"
                local bothCmd='PYTHONPATH='..sq(pyRoot)..' '..sq(pyBin)..' -c '..sq(pyOneLiner)..' '..sq(syncPath)..' '..sq(p.project_name)..' '..sq(p.timeline_name or '')..' '..sq(mountedSrtPath or '')..' 2>/dev/null'
                local sh=io.popen(bothCmd,'r')
                if sh then sh:read('*a');sh:close() end
            else
                if syncPath then
                    local syncCmd='PYTHONPATH='..sq(pyRoot)..' '..sq(pyBin)..' -m app.services.ai_watermark --sync-durations '..sq(syncPath)
                    local sh=io.popen(syncCmd,'r')
                    if sh then sh:read('*a');sh:close() end
                end
                if wantStyle then
                    local styleCmd='PYTHONPATH='..sq(pyRoot)..' '..sq(pyBin)..' -m app.services.scripture_subtitles --style-project '..sq(p.project_name)..' '..sq(p.timeline_name or '')..' '..sq(mountedSrtPath or '')..' 2>/dev/null'
                    pcall(function()
                        local sh=io.popen(styleCmd,'r')
                        if sh then sh:read('*a');sh:close() end
                    end)
                end
            end
            local reloaded=pm:LoadProject(p.project_name)
            if not reloaded and pm.GotoRootFolder then
                pcall(function() pm:GotoRootFolder() end)
                reloaded=pm:LoadProject(p.project_name)
            end
            assert(reloaded,'RELOAD_WATERMARK_PROJECT_FAILED')
            local matchedTl=nil
            if reloaded.GetTimelineCount and reloaded.GetTimelineByIndex then
                for ti=1,(tonumber(reloaded:GetTimelineCount()) or 0) do
                    local cand=reloaded:GetTimelineByIndex(ti)
                    if cand and cand:GetName()==p.timeline_name then
                        reloaded:SetCurrentTimeline(cand)
                        matchedTl=cand
                        break
                    end
                end
            end
            project=reloaded
            tl=assert(matchedTl or reloaded:GetCurrentTimeline(),'RELOAD_WATERMARK_TIMELINE_MISSING')
            uid=tl:GetUniqueId()
            if activePlan and activePlan.timeline_id then activePlan.timeline_id=uid end
            if prevPage and prevPage~='' and app.GetCurrentPage and app.OpenPage then
                pcall(function()
                    if app:GetCurrentPage()~=prevPage then app:OpenPage(prevPage) end
                end)
            end
            if prevTc and prevTc~='' and tl.SetCurrentTimecode then
                pcall(function() tl:SetCurrentTimecode(prevTc) end)
            end
            return true
        end

        scripturesMounted=mountBatchScriptures()
        local subSuffix=scripturesMounted and ' + 已挂载并对齐经文字幕 (SUV)' or ''

        if wmPlan.enabled~='1' then
            local syncedReloaded=syncProjectDbAndReload({})
            if watermarkOnly then
                return 'AI 水印当前未开启（已清除旧自动水印；如需添加请点击顶部「💧 AI水印」勾选启用）'..subSuffix,syncedReloaded
            end
            return scripturesMounted and '已按清理后时间线挂载并对齐经文字幕 (SUV)' or '',syncedReloaded
        end

        -- 2. Group consecutive surviving videos belonging to the same host into contiguous [first_start, last_end) spans.
        local function ensurePngSuffix(name)
            local s=tostring(name or ''):match('^%s*(.-)%s*$')
            if s=='' then return '' end
            if not s:lower():match('%.png$') then s=s..'.png' end
            return s
        end
        local function deriveSubPngLabel(subLbl,note,hostName,hostKey)
            local direct=ensurePngSuffix(subLbl)
            if direct~='' then return direct end
            local nt=tostring(note or '')
            local _,eIdx=nt:find('：',1,true)
            if eIdx and eIdx<#nt then
                local tail=ensurePngSuffix(nt:sub(eIdx+1))
                if tail~='' then return tail end
            end
            local fallback=tostring(hostName or '')
            if fallback=='' then fallback=tostring(hostKey or '副水印') end
            return ensurePngSuffix(fallback)
        end
        local mainLabel=ensurePngSuffix(wmPlan.main_label)
        if mainLabel=='' then mainLabel='主水印.png' end

        local wmByVid={}
        for k=1,tonumber(wmPlan.video_count) or 0 do
            local wp='v'..k..'_'
            local wid=tostring(wmPlan[wp..'id'] or '')
            if wid~='' then
                local hKey=tostring(wmPlan[wp..'host_key'] or '')
                local hName=tostring(wmPlan[wp..'host_name'] or '')
                wmByVid[wid]={
                    host_key=hKey,
                    host_name=hName,
                    orient=tostring(wmPlan[wp..'orient'] or ''),
                    wm_active=tostring(wmPlan[wp..'wm_active'] or '0'),
                    main_png=tostring(wmPlan[wp..'main_png'] or ''),
                    sub_png=tostring(wmPlan[wp..'sub_png'] or ''),
                    main_png_portrait=tostring(wmPlan[wp..'main_png_portrait'] or ''),
                    sub_png_portrait=tostring(wmPlan[wp..'sub_png_portrait'] or ''),
                    sub_label=deriveSubPngLabel(wmPlan[wp..'sub_label'],wmPlan[wp..'note'],hName,hKey),
                }
            end
        end

        local spans={}
        local curSpan=nil
        local needMain,needSub=false,false
        for _,sv in ipairs(surviving) do
            local w=wmByVid[sv.vid]
            local svOrient=sv.orient or 'portrait'
            local mainPng=w and w.main_png or ''
            local subPng=w and w.sub_png or ''
            if w and svOrient=='portrait' and w.orient=='landscape' then
                if w.main_png_portrait~='' then mainPng=w.main_png_portrait end
                if w.sub_png_portrait~='' then subPng=w.sub_png_portrait end
            end
            local active=w and w.wm_active=='1' and (mainPng~='' or subPng~='')
            if not active then
                curSpan=nil
            else
                if mainPng~='' then needMain=true end
                if subPng~='' then needSub=true end
                if curSpan and curSpan.host_key==w.host_key and curSpan.orient==svOrient and curSpan.main_png==mainPng and curSpan.sub_png==subPng then
                    curSpan.finish=math.max(curSpan.finish,sv.e)
                    curSpan.count=curSpan.count+1
                else
                    curSpan={
                        host_key=w.host_key,
                        host_name=w.host_name,
                        orient=svOrient,
                        main_png=mainPng,
                        sub_png=subPng,
                        sub_label=w.sub_label,
                        start=sv.s,
                        finish=sv.e,
                        count=1,
                    }
                    spans[#spans+1]=curSpan
                end
            end
        end

        if #spans==0 then
            local syncedReloaded=syncProjectDbAndReload({})
            return '当前批次主播「素材来源」为空，已按规则跳过挂载水印'..subSuffix,syncedReloaded
        end

        -- 3. Find or create empty video tracks above V1 across [minFrame, maxFrame): baseTrack (lower) < subTrack (upper).
        local neededTracks=(needMain and 1 or 0)+(needSub and 1 or 0)
        local emptyTracks={}
        for trk=2,tl:GetTrackCount('video') do
            if not tl:GetIsTrackLocked('video',trk) then
                local busy=false
                for _,clip in ipairs(tl:GetItemListInTrack('video',trk) or {}) do
                    local cs=clipFrameSafe(clip,'GetStart')
                    local ce=clipFrameSafe(clip,'GetEnd')
                    if cs and ce and cs<maxFrame and ce>minFrame then
                        busy=true;break
                    end
                end
                if not busy then
                    emptyTracks[#emptyTracks+1]=trk
                    if #emptyTracks>=neededTracks then break end
                end
            end
        end
        while #emptyTracks<neededTracks do
            assert(tl:AddTrack('video'),'ADD_WATERMARK_VIDEO_TRACK_FAILED')
            emptyTracks[#emptyTracks+1]=tl:GetTrackCount('video')
        end
        for idx_t=1,neededTracks do
            local trk=emptyTracks[idx_t]
            pcall(function() tl:SetTrackLock('video',trk,false) end)
            pcall(function() tl:SetTrackEnable('video',trk,true) end)
        end

        local baseTrack,subTrack=nil,nil
        if needMain and needSub then
            baseTrack=emptyTracks[1]
            subTrack=emptyTracks[2]
        elseif needMain then
            baseTrack=emptyTracks[1]
        else
            subTrack=emptyTracks[1]
        end

        -- 4. Import staged PNGs into _FlowStudio_AI_Watermarks bin and place single plain PNG Still clips per host span.
        local pool=assert(project:GetMediaPool(),'WM_MEDIA_POOL_UNAVAILABLE')
        local prevFolder=pool:GetCurrentFolder()
        local rootFolder=assert(pool:GetRootFolder(),'WM_MEDIA_ROOT_UNAVAILABLE')
        local wmBin=nil
        assert(pool:SetCurrentFolder(rootFolder),'WM_SET_ROOT_FAILED')
        for _,sub in ipairs(rootFolder:GetSubFolderList() or {}) do
            if sub:GetName()=='_FlowStudio_AI_Watermarks' then wmBin=sub;break end
        end
        if not wmBin then
            wmBin=assert(pool:AddSubFolder(rootFolder,'_FlowStudio_AI_Watermarks'),'WM_CREATE_BIN_FAILED')
        end
        assert(pool:SetCurrentFolder(wmBin),'WM_SET_BIN_FAILED')

        local itemByPath={}
        local staleCompItems={}
        for _,existing in ipairs(wmBin:GetClipList() or {}) do
            local okP,fp=pcall(function() return existing:GetClipProperty('File Path') end)
            if okP and type(fp)=='string' and fp~='' then
                itemByPath[fp]=existing
            else
                local okN,en=pcall(function() return existing:GetName() end)
                if okN and type(en)=='string' and en:find('flowstudio_wm_',1,true) then
                    staleCompItems[#staleCompItems+1]=existing
                end
            end
        end
        if #staleCompItems>0 and project.GetTimelineCount and (tonumber(project:GetTimelineCount()) or 1)<=1 and pool.DeleteClips then
            pcall(function() pool:DeleteClips(staleCompItems) end)
        end

        local function getWmPoolItem(pngPath)
            if itemByPath[pngPath] then return itemByPath[pngPath] end
            assert(nonempty(pngPath),'WATERMARK_PNG_MISSING: '..tostring(pngPath))
            assert(pool:SetCurrentFolder(wmBin),'WM_SET_BIN_FAILED')
            local imported=assert(pool:ImportMedia({pngPath}),'WATERMARK_IMPORT_FAILED: '..tostring(pngPath))
            local it=assert(imported[1],'WATERMARK_IMPORT_EMPTY: '..tostring(pngPath))
            itemByPath[pngPath]=it
            return it
        end

        local wmSyncItems={}
        local function placePlainStill(wmItem,pngPath,targetTrack,spanStart,spanEnd,clipLabel,kind)
            local dur=spanEnd-spanStart
            if dur<=0 then return end
            local placed=assert(pool:AppendToTimeline({{
                mediaPoolItem=wmItem,
                startFrame=0,
                endFrame=dur-1,
                mediaType=1,
                trackIndex=targetTrack,
                recordFrame=spanStart,
            }}),'WATERMARK_APPEND_FAILED: '..clipLabel)
            local firstClip=assert(placed[1],'WATERMARK_CLIP_NOT_RETURNED: '..clipLabel)
            pcall(function() firstClip:SetName(clipLabel) end)
            local clipUid=''
            pcall(function() clipUid=tostring(firstClip:GetUniqueId() or '') end)
            wmSyncItems[#wmSyncItems+1]={
                uid=clipUid,
                track=targetTrack,
                start=spanStart,
                duration=dur,
                png=pngPath,
                kind=kind,
                label=clipLabel,
            }
        end

        pulse('CLEANING','正在按主播连续区间挂载纯 PNG 水印（共 '..tostring(#spans)..' 段）…')
        for _,sp in ipairs(spans) do
            guard()
            if baseTrack and sp.main_png~='' then
                local mItem=getWmPoolItem(sp.main_png)
                placePlainStill(mItem,sp.main_png,baseTrack,sp.start,sp.finish,mainLabel,'main')
            end
            if subTrack and sp.sub_png~='' then
                local sItem=getWmPoolItem(sp.sub_png)
                placePlainStill(sItem,sp.sub_png,subTrack,sp.start,sp.finish,sp.sub_label,'sub')
            end
        end
        if prevFolder then pcall(function() pool:SetCurrentFolder(prevFolder) end) end

        -- 5. Sync exact [Start, Duration) onto Sm2TiItem in Project.db and style scripture subtitles in one pass.
        local syncedReloaded=syncProjectDbAndReload(wmSyncItems)

        local trkDesc=baseTrack and subTrack and ('V'..baseTrack..'主水印 + V'..subTrack..'副水印') or ('V'..tostring(baseTrack or subTrack))
        return '已挂载 '..tostring(#spans)..' 段主播纯 PNG 连续水印（'..trkDesc..'）'..subSuffix,syncedReloaded
    end

    -- After any cleanup pass (first-time or supplementary second-time), remove all Red/Blue/Orange
    -- markers in the current batch's span and re-anchor ONLY the Yellow per-video boundary markers
    -- at the exact post-cleanup start of each surviving complete video.
    local function syncBatchYellowMarkersOnly(activePlan, preSpanMin, preSpanMax)
        if test.inspectOnly then return end
        pcall(function()
            local origin = tonumber(tl:GetStartFrame()) or 0
            local manifestM = read(root..'/v0_5_0/batches/'..bid..'/manifest.ini')
            local vidSet = {}
            local metaByVid = {}
            local spanMin = preSpanMin
            local spanMax = preSpanMax
            local vCnt = tonumber(p.video_count) or tonumber(manifestM.video_count) or 0
            for i = 1, vCnt do
                local pre = 'v'..i..'_'
                local vid = tostring(p[pre..'id'] or manifestM[pre..'id'] or '')
                if vid ~= '' then
                    vidSet[vid] = true
                    metaByVid[vid] = {
                        seq = tonumber(manifestM[pre..'seq'] or p[pre..'seq']) or i,
                        recipient = tostring(manifestM[pre..'recipient'] or p[pre..'recipient'] or ''),
                        host = tostring(manifestM[pre..'host'] or p[pre..'host'] or ''),
                    }
                end
                for _, candF in ipairs({
                    tonumber(p[pre..'start']), tonumber(p[pre..'end']),
                    tonumber(manifestM[pre..'start']), tonumber(manifestM[pre..'end']),
                    activePlan and tonumber(activePlan[pre..'start']) or nil,
                    activePlan and tonumber(activePlan[pre..'end']) or nil,
                }) do
                    if candF then
                        spanMin = spanMin and math.min(spanMin, candF) or candF
                        spanMax = spanMax and math.max(spanMax, candF) or candF
                    end
                end
            end

            local savedYellowByVid = {}
            local toDeleteFrames = {}
            for mFrame, mObj in pairs(tl:GetMarkers() or {}) do
                local mf = tonumber(mFrame)
                if mf and type(mObj) == 'table' then
                    local absF = origin + mf
                    local cData = tostring(mObj.customData or '')
                    local tags = {}
                    if cData:sub(1, 11) == 'FLOWSTUDIO|' then
                        for k, v in cData:gmatch('([%w_]+)=([^|]*)') do tags[k] = v end
                    end
                    local tVid = tostring(tags.video_id or '')
                    local inBatch = false
                    if tostring(tags.batch_id or '') == tostring(bid) then
                        inBatch = true
                    elseif tVid ~= '' and vidSet[tVid] then
                        inBatch = true
                    elseif spanMin and spanMax and absF >= (spanMin - 50) and absF <= (spanMax + 50) then
                        if tags.batch_id == nil or tostring(tags.batch_id) == '' or tostring(tags.batch_id) == tostring(bid) then
                            inBatch = true
                        end
                    end
                    if inBatch then
                        if mObj.color == 'Yellow' and tVid ~= '' and not savedYellowByVid[tVid] then
                            savedYellowByVid[tVid] = {
                                name = tostring(mObj.name or ''),
                                note = tostring(mObj.note or ''),
                            }
                        end
                        toDeleteFrames[#toDeleteFrames + 1] = mf
                    end
                end
            end

            for _, df in ipairs(toDeleteFrames) do
                pcall(function() tl:DeleteMarkerAtFrame(df) end)
            end

            if not activePlan then return end
            for i = 1, tonumber(p.video_count) or 0 do
                local pre = 'v'..i..'_'
                if activePlan[pre..'skip'] ~= 'true' then
                    local vid = tostring(p[pre..'id'] or '')
                    local vs = tonumber(activePlan[pre..'start'])
                    local ve = tonumber(activePlan[pre..'end'])
                    if vid ~= '' and vs and ve and ve > vs then
                        local relFrame = math.max(0, math.floor(vs - origin + 0.5))
                        local saved = savedYellowByVid[vid]
                        local meta = metaByVid[vid] or {seq = i, recipient = '', host = ''}
                        local mName = (saved and saved.name ~= '') and saved.name or string.format('%02d | %s | %s', meta.seq, meta.recipient, meta.host)
                        local mNote = (saved and saved.note ~= '') and saved.note or ('Flow Studio 批次：'..tostring(bid))
                        local mCustom = 'FLOWSTUDIO|video_id='..vid..'|batch_id='..tostring(bid)..'|status=COMPLETE|start='..tostring(vs)..'|end='..tostring(ve)
                        pcall(function() tl:DeleteMarkerAtFrame(relFrame) end)
                        pcall(function() tl:AddMarker(relFrame, 'Yellow', mName, mNote, 1, mCustom) end)
                    end
                end
            end
        end)
    end

    local cleaning=false
    local ok,result=pcall(function()
        local plan=read(base..'/cleaned.ini')
        local prevCleaned=plan
        local liveScanOnly=(exportOnly or watermarkOnly or (cleanupOnly and plan.batch_id~=nil) or (not plan.batch_id and recoveringAppliedCleanup))
        if liveScanOnly then
            local extraPreMin, extraPreMax = nil, nil
            -- If cleanupOnly was clicked again after initial cleanup and the user placed extra Blue or Red delete markers,
            -- delete ONLY those newly marked V1 fragments (+ aligned A1) before re-scanning live V1 ranges.
            if cleanupOnly and plan.batch_id~=nil then
                local preItems=items()
                local manifestPre=read(root..'/v0_5_0/batches/'..bid..'/manifest.ini')
                local ownedPaths={}
                for i=1,tonumber(manifestPre.video_count) or 0 do
                    local pre='v'..i..'_'
                    for j=1,tonumber(manifestPre[pre..'segment_count']) or 0 do
                        local spath=manifestPre[pre..'s'..j..'_path']
                        if spath then ownedPaths[spath]=true end
                    end
                end
                local prePathCache={}
                for _,it in ipairs(preItems) do
                    if it.kind=='video' then
                        local fp=getCachedMediaPath(it.item:GetMediaPoolItem(),prePathCache)
                        if fp and ownedPaths[fp] then
                            it.owned=true
                            extraPreMin=extraPreMin and math.min(extraPreMin,it.s) or it.s
                            extraPreMax=extraPreMax and math.max(extraPreMax,it.e) or it.e
                        end
                    end
                end
                local extraDel,extraRanges,extraIds={},{},{}
                for mFrame,mObj in pairs(tl:GetMarkers() or {}) do
                    if type(mObj)=='table' and (mObj.color=='Blue' or mObj.color=='Red') then
                        local mf=tonumber(mFrame)
                        if mf then
                            local absF=mf+tl:GetStartFrame()
                            local dur=math.max(1,tonumber(mObj.duration) or 1)
                            for _,it in ipairs(preItems) do
                                if it.kind=='video' and it.owned and not extraIds[it.id] then
                                    local matched=false
                                    if mObj.color=='Blue' then
                                        matched=(math.abs(it.s-absF)<=1)
                                    elseif mObj.color=='Red' then
                                        if dur>1 then
                                            matched=(it.s>=(absF-1) and it.e<=(absF+dur+1)) or (math.abs(it.s-absF)<=1)
                                        else
                                            matched=(math.abs(it.s-absF)<=1)
                                        end
                                    end
                                    if matched then
                                        extraIds[it.id]=true
                                        extraDel[#extraDel+1]=it.item
                                        extraRanges[#extraRanges+1]={s=it.s,e=it.e}
                                    end
                                end
                            end
                        end
                    end
                end
                if #extraDel>0 then
                    for _,it in ipairs(preItems) do
                        if it.kind=='audio' and it.track==1 then
                            for _,br in ipairs(extraRanges) do
                                if it.s>=br.s and it.e<=br.e and not extraIds[it.id] then
                                    extraIds[it.id]=true
                                    extraDel[#extraDel+1]=it.item
                                end
                            end
                        end
                    end
                    cleaning=true
                    pulse('CLEANING','检测到新增手动/自动清理标记，正在补充清理 '..tostring(#extraRanges)..' 个视频片段…')
                    withUpperVideoTracksProtected(function()
                        assert(tl:DeleteClips(extraDel,true),'EXTRA_BLUE_DELETE_FAILED')
                    end)
                    cleaning=false
                end
            end

            -- Reconstruct the finished export ranges from the CURRENT V1 only, ignoring V2+ entirely.
            local intent=read(base..'/cleanup_intent.ini')
            assert(exportOnly or watermarkOnly or cleanupOnly or intent.count,'CLEANUP_RECOVERY_INTENT_MISSING')
            if (exportOnly or watermarkOnly or cleanupOnly) and plan.batch_id then
                assert(plan.batch_id==bid and plan.timeline_id==uid,'TIMELINE_MISMATCH: 请确保你打开了对应的批次时间线')
            end
            local liveFp=fingerprint()
            if exportOnly and not test.inspectOnly and prevCleaned.batch_id==bid and prevCleaned.timeline_id==uid and prevCleaned.snapshot and prevCleaned.snapshot~='' and prevCleaned.snapshot==liveFp then
                plan=prevCleaned
                pulse('PREPARING_EXPORT','批量导出：复用已清理 V1 视频范围导出（包含上层可见水印与字幕轨）')
            else
                local all=items()
                local mpPathCache={}
                local manifest=read(root..'/v0_5_0/batches/'..bid..'/manifest.ini')
                local owners={};local current={}
                for i=1,assert(tonumber(manifest.video_count),'IMPORT_MANIFEST_MISSING') do
                    local pre='v'..i..'_';local id=manifest[pre..'id']
                    for j=1,tonumber(manifest[pre..'segment_count']) do
                        local path=assert(manifest[pre..'s'..j..'_path'])
                        if not owners[path] then owners[path]={} end
                        local exists=false
                        for _,oid in ipairs(owners[path]) do if oid==id then exists=true;break end end
                        if not exists then table.insert(owners[path],id) end
                    end
                end
                for _,c in ipairs(all) do
                    if c.kind=='video' then
                        local media=c.item:GetMediaPoolItem()
                        local path=getCachedMediaPath(media,mpPathCache)
                        c.path=path
                        local olist=path and owners[path] or nil
                        if olist and #olist==1 then
                            c.owner=olist[1]
                        elseif olist and #olist>1 then
                            local bestId=olist[1];local bestDist=math.huge
                            for idx_m=1,tonumber(manifest.video_count) do
                                local mpre='v'..idx_m..'_';local mid=manifest[mpre..'id']
                                for _,oid in ipairs(olist) do
                                    if oid==mid then
                                        local ps=tonumber(prevCleaned[mpre..'start']) or tonumber(p[mpre..'start']) or tonumber(manifest[mpre..'start'])
                                        if ps then
                                            local d=math.abs(c.s-ps)
                                            if d<bestDist then bestDist=d;bestId=mid end
                                        end
                                    end
                                end
                            end
                            c.owner=bestId
                        end
                        if c.owner then
                            local group=current[c.owner] or {s=c.s,e=c.e};current[c.owner]=group
                            group.s=math.min(group.s,c.s);group.e=math.max(group.e,c.e)
                        end
                    end
                end
                plan={batch_id=bid,timeline_id=uid,video_count=p.video_count,recovered_from='RIPPLE_ACTUAL_V1'}
                for i=1,tonumber(p.video_count) do
                    local pre='v'..i..'_';local id=p[pre..'id'];local group=current[id]
                    local clips={}
                    for _,c in ipairs(all) do if c.kind=='video' and c.owner==id then clips[#clips+1]=c end end
                    table.sort(clips,function(a,b)return a.s<b.s end)

                    -- V7 unified missing-video rule: a complete video manually removed
                    -- from V1 is skipped in recovery exactly like in the normal path.
                    if not group or #clips==0 then
                        plan[pre..'skip']='true'
                        plan[pre..'skip_reason']='RECOVERY_VIDEO_SOURCE_MISSING_SKIPPED'
                        plan[pre..'start']=''
                        plan[pre..'end']=''
                    else
                        local last=clips[1].s
                        for _,c in ipairs(clips) do
                            assert(c.track==MAIN_VIDEO_TRACK,
                                'RECOVERY_NON_V1_VIDEO_FOUND: video='..tostring(id)..'；frame='..tostring(c.s))
                            assert(((exportOnly or watermarkOnly or cleanupOnly) and c.s>=last) or c.s==last,
                                'RECOVERY_V1_GAP_OR_OVERLAP: video='..tostring(id)..
                                '；位置='..frameTimecode(c.s-tl:GetStartFrame(),p.timeline_fps)..
                                '；timeline_frame='..tostring(c.s))
                            last=c.e
                        end
                        -- Use Resolve's actual surviving V1 range. Do not require it
                        -- to equal a stale pre-cleanup theoretical range.
                        plan[pre..'start']=clips[1].s
                        plan[pre..'end']=last
                        plan[pre..'skip']='false'
                    end
                end
                -- Reject ranges containing another video's or unknown V1 footage.
                for i=1,tonumber(p.video_count) do
                    local pre='v'..i..'_'
                    if plan[pre..'skip']~='true' then
                        for _,c in ipairs(all) do
                            if c.kind=='video' and c.s<plan[pre..'end'] and c.e>plan[pre..'start'] then
                                assert(c.owner==p[pre..'id'],'EXPORT_RANGE_FOREIGN_CLIP: video='..tostring(p[pre..'id']))
                            end
                        end
                    end
                end
                plan.snapshot=liveFp
                if test.inspectOnly then return {stage='PREFLIGHT',remove_count=0,plan=plan} end
                if cleanupOnly or (not prevCleaned.batch_id and recoveringAppliedCleanup) then
                    syncBatchYellowMarkersOnly(plan, extraPreMin, extraPreMax)
                end
                if not exportOnly then
                    assert(pm:SaveProject(),'SAVE_CLEANUP_RECOVERY_FAILED')
                end
                if not watermarkOnly or read(base..'/cleaned.ini').batch_id~=nil then
                    write(base..'/cleaned.ini',plan)
                end
                pcall(function()
                    local prevClipMeta=read(base..'/cleaned_clips.ini')
                    local prevPreByUid={}
                    for pci=1,tonumber(prevClipMeta.clip_count) or 0 do
                        local pcp='c'..tostring(pci)..'_'
                        local puid=tostring(prevClipMeta[pcp..'uid'] or '')
                        if puid~='' then
                            prevPreByUid[puid]={pre_s=prevClipMeta[pcp..'pre_s'],pre_e=prevClipMeta[pcp..'pre_e']}
                        end
                    end
                    local cleanedClipsMeta={batch_id=bid,attempt_id=attempt,timeline_id=uid}
                    local ccIdx=0
                    for _,c in ipairs(all) do
                        if c.kind=='video' then
                            local cpath=c.path or getCachedMediaPath(c.item:GetMediaPoolItem(),mpPathCache) or ''
                            local loff=0
                            pcall(function() if c.item.GetLeftOffset then loff=tonumber(c.item:GetLeftOffset()) or 0 end end)
                            local prevPre=prevPreByUid[tostring(c.id or '')]
                            ccIdx=ccIdx+1
                            local cp='c'..tostring(ccIdx)..'_'
                            cleanedClipsMeta[cp..'uid']=tostring(c.id or '')
                            cleanedClipsMeta[cp..'video_id']=tostring(c.owner or '')
                            cleanedClipsMeta[cp..'path']=tostring(cpath or '')
                            cleanedClipsMeta[cp..'left_offset']=tostring(math.floor(loff+0.5))
                            cleanedClipsMeta[cp..'pre_s']=tostring((prevPre and prevPre.pre_s) or '')
                            cleanedClipsMeta[cp..'pre_e']=tostring((prevPre and prevPre.pre_e) or '')
                            cleanedClipsMeta[cp..'post_s']=tostring(c.s)
                            cleanedClipsMeta[cp..'post_e']=tostring(c.e)
                        end
                    end
                    cleanedClipsMeta.clip_count=tostring(ccIdx)
                    write(base..'/cleaned_clips.ini',cleanedClipsMeta)
                    write(root..'/v0_5_0/batches/'..bid..'/cleaned_clips.ini',cleanedClipsMeta)
                end)
                if exportOnly then
                    pulse('PREPARING_EXPORT','批量导出：按当前 V1 视频范围导出（包含上层可见水印与字幕轨）')
                end
            end
            cleaning=false
        elseif not plan.batch_id then
            assert(read(base..'/state.ini').stage=='WAITING_USER_REVIEW','REVIEW_REQUIRED')
            -- Select current clips using owned red range markers. Only one
            -- video track and exactly aligned audio are supported for ripple safety.
            local all=items();local ranges,remove,deleted={}, {}, {}
            -- Reconstruct current group ranges from source ownership, after manual ripple edits.
            local manifest=read(root..'/v0_5_0/batches/'..bid..'/manifest.ini')
            local owners={};local current={}
            for i=1,assert(tonumber(manifest.video_count),'IMPORT_MANIFEST_MISSING') do
                local pre='v'..i..'_';local id=manifest[pre..'id']
                for j=1,tonumber(manifest[pre..'segment_count']) do
                    local path=assert(manifest[pre..'s'..j..'_path'])
                    if not owners[path] then owners[path]={} end
                    local exists=false
                    for _,oid in ipairs(owners[path]) do if oid==id then exists=true;break end end
                    if not exists then table.insert(owners[path],id) end
                end
            end
            local cleanPathCache={}
            for _,c in ipairs(all) do
                if c.kind=='video' then
                    local media=c.item:GetMediaPoolItem()
                    local path=getCachedMediaPath(media,cleanPathCache)
                    c.path=path
                    local olist=path and owners[path] or nil
                    if olist and #olist==1 then
                        c.owner=olist[1]
                    elseif olist and #olist>1 then
                        local bestId=olist[1];local bestDist=math.huge
                        for idx_m=1,tonumber(manifest.video_count) do
                            local mpre='v'..idx_m..'_';local mid=manifest[mpre..'id']
                            for _,oid in ipairs(olist) do
                                if oid==mid then
                                    local ps=tonumber(prevCleaned[mpre..'start']) or tonumber(p[mpre..'start']) or tonumber(manifest[mpre..'start'])
                                    if ps then
                                        local d=math.abs(c.s-ps)
                                        if d<bestDist then bestDist=d;bestId=mid end
                                    end
                                end
                            end
                        end
                        c.owner=bestId
                    end
                    if c.owner then
                        local group=current[c.owner] or {s=c.s,e=c.e};current[c.owner]=group
                        group.s=math.min(group.s,c.s);group.e=math.max(group.e,c.e)
                    end
                end
            end
            -- Deletion ownership rules:
            --   Red  = Flow Studio auto-clean candidate (existing behavior).
            --   Blue = manual-delete marker. Put the default blue timeline marker at the
            --          FIRST FRAME of a manually cut video fragment; cleanup deletes ONLY
            --          that fragment (plus exactly aligned audio), never its neighbours.
            --   Orange/other colors = never deleted by this cleanup selector.
            --   Upper/manual video layers not owned by the current Flow Studio source are protected:
            --   they never participate in candidate detection or main-video range validation.
            local selected={}
            local redMarkerCount,blueMarkerCount,redSkippedCount=0,0,0
            local cutPlan=read(base..'/cut_plan.ini')
            assert(cutPlan.batch_id==bid and cutPlan.attempt_id==attempt,'CUT_PLAN_IDENTITY_MISMATCH')
            local candidates={}
            for i=1,assert(tonumber(cutPlan.candidate_count),'CUT_PLAN_MISSING') do
                candidates[attempt..'_'..i]={video=cutPlan['c'..i..'_video_id'],s=tonumber(cutPlan['c'..i..'_start']),e=tonumber(cutPlan['c'..i..'_end']),kind=cutPlan['c'..i..'_type']}
            end

            -- V7.1: red auto-clean markers are fail-safe.
            -- If a candidate cannot be matched exactly to the current V1 timeline,
            -- skip ONLY that candidate and delete nothing for it. This is safer than
            -- aborting the whole batch or guessing a neighbouring fragment.
            local seen={}
            local cachedMarkers=tl:GetMarkers() or {}
            for frame,m in pairs(cachedMarkers) do
                if type(m)=='table' then
                    local tags={};for k,v in tostring(m.customData):gmatch('|([^=|]+)=([^|]*)') do tags[k]=v end
                    if tags.batch_id==bid and tags.candidate_id and m.color=='Red' then
                        local candidateId=tags.candidate_id
                        local c=candidates[candidateId]
                        local skipReason=nil

                        if not c then
                            skipReason='CANDIDATE_IDENTITY_MISSING'
                        elseif seen[candidateId] then
                            skipReason='DUPLICATE_CANDIDATE_MARKER'
                        elseif not (tags.video_id==c.video and tonumber(tags.start)==c.s and tonumber(tags['end'])==c.e and tags.type==c.kind) then
                            skipReason='CANDIDATE_IDENTITY_MISMATCH'
                        end

                        if not skipReason then
                            seen[candidateId]=true
                            local mf=tonumber(frame)
                            local duration=tonumber(m.duration)
                            if not mf or not duration or duration<=0 then
                                skipReason='CANDIDATE_MARKER_RANGE_INVALID'
                            else
                                local ms=mf+tl:GetStartFrame()
                                local me=ms+duration
                                local probe=c.kind=='HEAD' and ms or me-1
                                local hit=nil
                                local ambiguous=false
                                for _,item in ipairs(all) do
                                    -- Only current Flow Studio-owned V1 can be auto-deleted.
                                    if item.kind=='video' and item.owner==c.video and item.s<=probe and item.e>probe then
                                        if hit and hit.id~=item.id then
                                            ambiguous=true
                                            break
                                        end
                                        hit=item
                                    end
                                end

                                if ambiguous then
                                    skipReason='AMBIGUOUS_CANDIDATE'
                                elseif not hit then
                                    skipReason='CANDIDATE_CLIP_MISSING'
                                else
                                    -- Exact safe match: this is the only path that selects
                                    -- a red candidate for deletion.
                                    selected[hit.id]=c.video
                                    redMarkerCount=redMarkerCount+1
                                end
                            end
                        end

                        if skipReason then
                            redSkippedCount=redSkippedCount+1
                            local mf=tonumber(frame) or 0
                            local absFrame=mf+tl:GetStartFrame()
                            pulse('CLEANING',
                                '跳过无法安全匹配的红色自动清理点 · '..skipReason..
                                ' · candidate='..tostring(candidateId)..
                                ' · video='..tostring(c and c.video or tags.video_id or '')..
                                ' · 位置='..frameTimecode(mf,p.timeline_fps)..
                                ' · timeline_frame='..tostring(absFrame))
                        end
                    end
                end
            end

            -- Manual cleanup selector: only a plain BLUE timeline marker that is actually
            -- aligned to an owned V1 fragment start is actionable. Resolve can sometimes
            -- return stale/ghost blue marker records through GetMarkers() that are not
            -- visible in the UI. Those records must never block cleanup or delete a clip.
            -- Matching remains START-only with +/-1 frame tolerance.
            for frame,m in pairs(cachedMarkers) do
                local markerCustomData=(type(m)=='table') and tostring(m.customData or '') or ''
                if type(m)=='table' and m.color=='Blue' and markerCustomData=='' then
                    local mf=assert(tonumber(frame),'BLUE_MARKER_FRAME_INVALID')
                    local absFrame=mf+tl:GetStartFrame()
                    local inOwnedRange=false
                    for _,group in pairs(current) do
                        if absFrame>=group.s and absFrame<group.e then inOwnedRange=true;break end
                    end
                    if inOwnedRange then
                        local hit,bestDist=nil,nil
                        for _,item in ipairs(all) do
                            if item.kind=='video' and item.owner then
                                local dist=math.abs(item.s-absFrame)
                                if dist<=1 then
                                    if not hit or dist<bestDist then
                                        hit,bestDist=item,dist
                                    elseif dist==bestDist and hit.id~=item.id then
                                        local uiTc,located=locateTimelineFrame(absFrame)
                                        error('AMBIGUOUS_BLUE_MARKER: 蓝色 Marker 对应多个片段；达芬奇位置='..uiTc..'；timeline_frame='..tostring(absFrame)..'；'..(located and '播放头已自动定位；' or '自动定位失败；')..'请把 Marker 精确放到待删除片段开头')
                                    end
                                end
                            end
                        end

                        if hit then
                            selected[hit.id]=hit.owner
                            blueMarkerCount=blueMarkerCount+1
                        else
                            -- Safety rule: an off-start blue record is not a delete instruction.
                            -- Do not stop, do not move the playhead, and never auto-snap/delete.
                            local nearest,nearestDist=nil,nil
                            for _,item in ipairs(all) do
                                if item.kind=='video' and item.owner then
                                    local d=math.abs(item.s-absFrame)
                                    if not nearestDist or d<nearestDist then nearest,nearestDist=item,d end
                                end
                            end
                            local msg='忽略未对齐的蓝色 Marker API记录（未执行删除）'..
                                '；Marker位置='..frameTimecode(absFrame,p.timeline_fps)..
                                '；timeline_frame='..tostring(absFrame)
                            if nearest then
                                msg=msg..'；最近片段开头='..frameTimecode(nearest.s,p.timeline_fps)..
                                    '；nearest_frame='..tostring(nearest.s)..
                                    '；相差='..tostring(nearestDist)..'帧'
                            end
                            pulse('CLEANING',msg)
                        end
                    end
                end
            end
            local skippedVideos={}
            for i=1,tonumber(p.video_count) do
                local pre='v'..i..'_';local videoId=p[pre..'id'];local group=current[videoId]
                if not group then
                    skippedVideos[videoId]=true
                    pulse('CLEANING','跳过缺失的完整视频 '..tostring(i)..' / '..p.video_count..' · video_id='..tostring(videoId)..' · VIDEO_SOURCE_MISSING_SKIPPED')
                else
                local s,e=group.s,group.e
                local found=0
                for frame,m in pairs(cachedMarkers) do
                    if type(m)=='table' then
                        local tags={};for k,v in tostring(m.customData):gmatch('|([^=|]+)=([^|]*)') do tags[k]=v end
                        if (tags.batch_id==bid or tostring(tags.video_id or '')==tostring(p[pre..'id'] or '')) and tags.video_id==p[pre..'id'] and tags.status=='COMPLETE' then
                            found=found+1
                        end
                    end
                end
                if found~=1 then
                    -- A COMPLETE marker at the start frame can be replaced when the user puts a
                    -- Blue manual-delete marker on the first fragment. V1 clip ownership/range is
                    -- authoritative and validated below, so do not abort the batch.
                    pulse('CLEANING','忽略缺失/被覆盖的 COMPLETE Marker · video='..tostring(videoId)..
                        ' · COMPLETE Marker数量='..tostring(found)..
                        ' · 完整视频范围='..frameTimecode(s-tl:GetStartFrame(),p.timeline_fps)..
                        ' - '..frameTimecode(e-tl:GetStartFrame(),p.timeline_fps))
                end
                local track,last=nil,s
                local video={}
                for _,c in ipairs(all) do
                    -- Validate only the current Flow Studio-owned MAIN video. Manually-added upper
                    -- layers are protected content and are intentionally excluded from cleanup/range checks.
                    if c.kind=='video' and c.owner==p[pre..'id'] and c.s<e and c.e>s then
                        assert(c.s>=s and c.e<=e and (not track or track==c.track),
                            'AMBIGUOUS_VIDEO_RANGE: video='..tostring(videoId)..
                            '；位置='..frameTimecode(c.s-tl:GetStartFrame(),p.timeline_fps)..
                            '；timeline_frame='..tostring(c.s))
                        track=c.track;video[#video+1]=c
                    end
                end
                table.sort(video,function(a,b)return a.s<b.s end)
                local keep=0
                for _,c in ipairs(video) do
                    assert(c.s>=last,
                        'VIDEO_OVERLAP: video='..tostring(videoId)..
                        '；位置='..frameTimecode(c.s-tl:GetStartFrame(),p.timeline_fps)..
                        '；timeline_frame='..tostring(c.s));last=c.e
                    if selected[c.id] then
                        assert(selected[c.id]==p[pre..'id'],'CANDIDATE_VIDEO_MISMATCH')
                        ranges[#ranges+1]={s=c.s,e=c.e};remove[#remove+1]=c.item;deleted[c.id]=true
                    else keep=keep+c.e-c.s end
                end
                assert(last==e and keep>0,
                    'EMPTY_OR_INCOMPLETE_VIDEO: video='..tostring(videoId)..
                    '；范围='..frameTimecode(s-tl:GetStartFrame(),p.timeline_fps)..
                    ' - '..frameTimecode(e-tl:GetStartFrame(),p.timeline_fps))
                end -- group exists
            end
            table.sort(ranges,function(a,b)return a.s<b.s end)
            -- Audio cleanup follows the V1 deletion range, but only A1 is part of
            -- Flow Studio's primary A/V cleanup. A2+ (music/manual audio) is protected
            -- and must never trigger AUDIO_CUT_MISMATCH.
            --
            -- Do NOT require an A1 clip's original start/end to be byte-for-byte equal
            -- to the V1 fragment. Manual cuts and Resolve can leave slightly different
            -- audio fragment boundaries. We only delete an A1 item when that item is
            -- fully contained inside the V1 range selected for deletion. If an A1 item
            -- crosses a V1 deletion boundary, stop safely and report the exact location
            -- instead of silently deleting neighbouring audio.
            for _,c in ipairs(all) do
                if c.kind=='audio' and c.track==1 then
                    for _,r in ipairs(ranges) do
                        if c.s<r.e and c.e>r.s then
                            if c.s>=r.s and c.e<=r.e then
                                if not deleted[c.id] then
                                    remove[#remove+1]=c.item
                                    deleted[c.id]=true
                                end
                            else
                                local boundary = c.s<r.s and r.s or r.e
                                local relFrame = boundary-tl:GetStartFrame()
                                error(
                                    'AUDIO_CUT_MISMATCH: A1 音频跨过 V1 待删除边界；位置='..
                                    frameTimecode(relFrame,p.timeline_fps)..
                                    '；timeline_frame='..tostring(boundary)..
                                    '；V1删除范围='..frameTimecode(r.s-tl:GetStartFrame(),p.timeline_fps)..
                                    ' - '..frameTimecode(r.e-tl:GetStartFrame(),p.timeline_fps)..
                                    '；A1范围='..frameTimecode(c.s-tl:GetStartFrame(),p.timeline_fps)..
                                    ' - '..frameTimecode(c.e-tl:GetStartFrame(),p.timeline_fps)..
                                    '；请只调整该位置的 A1/V1 切点'
                                )
                            end
                        end
                    end
                end
            end
            local function shift(frame)
                local n=0;for _,r in ipairs(ranges) do if r.e<=frame then n=n+r.e-r.s end end;return frame-n
            end
            plan={batch_id=bid,timeline_id=uid,video_count=p.video_count,red_marker_count=redMarkerCount,red_skipped_count=redSkippedCount,blue_marker_count=blueMarkerCount}
            for i=1,tonumber(p.video_count) do
                local pre='v'..i..'_';local videoId=p[pre..'id'];local group=current[videoId]
                if group then
                    plan[pre..'start']=shift(group.s);plan[pre..'end']=shift(group.e)
                    plan[pre..'skip']='false'
                else
                    plan[pre..'skip']='true'
                    plan[pre..'skip_reason']='VIDEO_SOURCE_MISSING_SKIPPED'
                end
            end
            if test.inspectOnly then return {stage='PREFLIGHT',remove_count=#remove,plan=plan} end
            if not cleanupOnly then prepareExport() end
            guard();cleaning=true;pulse('CLEANING','仅清理 V1 主轨的红色自动范围 + 蓝色人工指定片段；V2 及以上完全忽略并保护；中断后不会重复删除')
            write(base..'/cleanup_intent.ini',{snapshot=fingerprint(),count=#remove})
            if #remove>0 then
                withUpperVideoTracksProtected(function()
                    assert(tl:DeleteClips(remove,true),'DELETE_FAILED')
                end)
            end
            -- V6.1: verify deletion safety from the ACTUAL post-ripple timeline.
            -- Resolve's real ripple result can differ from the old mathematical shift()
            -- prediction when there are manual cuts, missing complete videos or protected
            -- audio. Do not fail merely because a surviving clip moved to a different
            -- frame than shift() predicted.
            local afterList=items()
            local after={};for _,c in ipairs(afterList) do after[c.id]=c end

            -- Safety invariant 1: every item explicitly selected for deletion must be gone.
            for _,c in ipairs(all) do
                if deleted[c.id] then
                    assert(not after[c.id],'DELETE_NOT_CONFIRMED: 指定删除片段仍存在；清理现场已保留')
                end
            end

            -- Safety invariant 2: surviving pre-cleanup V1/A1 items must still exist.
            -- Their positions are allowed to follow Resolve's actual ripple result.
            for _,c in ipairs(all) do
                if not deleted[c.id] then
                    assert(after[c.id],
                        'UNEXPECTED_CLIP_REMOVED: 非目标片段被删除；kind='..tostring(c.kind)..
                        '；track='..tostring(c.track)..'；原frame='..tostring(c.s)..
                        '；清理现场已保留')
                end
            end

            -- Rebuild every complete-video export range from surviving V1 clips instead
            -- of using the theoretical shift() result. This makes subsequent MarkIn /
            -- MarkOut match the timeline Resolve actually produced.
            local rebuilt={}
            for _,c in ipairs(afterList) do
                if c.kind=='video' then
                    -- Ownership survives because afterList items are the same timeline
                    -- objects/IDs. Recover owner from the pre-cleanup scan.
                    local owner=nil
                    for _,before in ipairs(all) do
                        if before.id==c.id then owner=before.owner;break end
                    end
                    if owner then
                        local g=rebuilt[owner]
                        if not g then
                            rebuilt[owner]={s=c.s,e=c.e}
                        else
                            if c.s<g.s then g.s=c.s end
                            if c.e>g.e then g.e=c.e end
                        end
                    end
                end
            end

            for i=1,tonumber(p.video_count) do
                local pre='v'..i..'_'
                if plan[pre..'skip']~='true' then
                    local videoId=p[pre..'id']
                    local g=rebuilt[videoId]
                    if not g then
                        -- If the whole source disappeared unexpectedly, do not guess a
                        -- render range. Treat this one video as skipped; later videos continue.
                        plan[pre..'skip']='true'
                        plan[pre..'skip_reason']='VIDEO_SOURCE_MISSING_AFTER_CLEANUP_SKIPPED'
                    else
                        plan[pre..'start']=g.s
                        plan[pre..'end']=g.e
                    end
                end
            end

            local preSpanMin, preSpanMax = nil, nil
            for _, g in pairs(current) do
                if g.s then preSpanMin = preSpanMin and math.min(preSpanMin, g.s) or g.s end
                if g.e then preSpanMax = preSpanMax and math.max(preSpanMax, g.e) or g.e end
            end
            syncBatchYellowMarkersOnly(plan, preSpanMin, preSpanMax)

            local willApplyWatermarks=(cleanupOnly or watermarkOnly or (finishMode=='cleanup' and (not test.root or (job.watermark_plan_path and job.watermark_plan_path~=''))))
            if not willApplyWatermarks then
                assert(pm:SaveProject(),'SAVE_CLEANUP_FAILED')
            end
            plan.snapshot=fingerprint();write(base..'/cleaned.ini',plan)
            pcall(function()
                local beforeById={}
                for _,b in ipairs(all) do
                    if b.kind=='video' then beforeById[b.id]=b end
                end
                local afterPathCache={}
                local cleanedClipsMeta={batch_id=bid,attempt_id=attempt,timeline_id=uid}
                local ccIdx=0
                for _,c in ipairs(afterList) do
                    if c.kind=='video' then
                        local b=beforeById[c.id]
                        local owner=b and b.owner or nil
                        local cpath=(b and b.path) or getCachedMediaPath(c.item:GetMediaPoolItem(),afterPathCache) or ''
                        local loff=0
                        pcall(function() if c.item.GetLeftOffset then loff=tonumber(c.item:GetLeftOffset()) or 0 end end)
                        ccIdx=ccIdx+1
                        local cp='c'..tostring(ccIdx)..'_'
                        cleanedClipsMeta[cp..'uid']=tostring(c.id or '')
                        cleanedClipsMeta[cp..'video_id']=tostring(owner or '')
                        cleanedClipsMeta[cp..'path']=tostring(cpath or '')
                        cleanedClipsMeta[cp..'left_offset']=tostring(math.floor(loff+0.5))
                        cleanedClipsMeta[cp..'pre_s']=tostring(b and b.s or c.s)
                        cleanedClipsMeta[cp..'pre_e']=tostring(b and b.e or c.e)
                        cleanedClipsMeta[cp..'post_s']=tostring(c.s)
                        cleanedClipsMeta[cp..'post_e']=tostring(c.e)
                    end
                end
                cleanedClipsMeta.clip_count=tostring(ccIdx)
                write(base..'/cleaned_clips.ini',cleanedClipsMeta)
                write(root..'/v0_5_0/batches/'..bid..'/cleaned_clips.ini',cleanedClipsMeta)
            end)
            if not cleanupOnly then
                pulse('PREPARING_EXPORT','清理完成，准备逐个导出')
            end
            cleaning=false
        end
        if cleanupOnly or watermarkOnly or (finishMode=='cleanup' and (not test.root or (job.watermark_plan_path and job.watermark_plan_path~=''))) then
            cleaning=true
            local wmSummary,wmReloaded=applyBatchWatermarks(plan)
            cleaning=false
            if wmReloaded then
                plan.snapshot=fingerprint()
                if not watermarkOnly or read(base..'/cleaned.ini').batch_id~=nil then
                    write(base..'/cleaned.ini',plan)
                end
            else
                assert(pm:SaveProject(),'SAVE_WATERMARK_PROJECT_FAILED')
            end
            if cleanupOnly or watermarkOnly then
                local doneMsg
                if watermarkOnly then
                    doneMsg=(wmSummary~='' and wmSummary or '已刷新当前时间线 AI 水印')..'；确认无误后可点击「批量导出」'
                else
                    doneMsg='已完成清理'..(wmSummary~='' and (' · '..wmSummary) or '')..'；请检查时间线后点击「批量导出」'
                end
                write(base..'/finish.ini',{batch_id=bid,attempt_id=attempt,stage='CLEANED_READY',detail=doneMsg})
                os.remove(root..'/pipeline.lock')
                return {stage='READY',detail=doneMsg,project=p.project_name,timeline=p.timeline_name}
            end
        end
        assert(plan.timeline_id==uid,'TIMELINE_MISMATCH: 导出前发现当前时间线与预期不符')
        -- If cleanup ran before 16:9 watermark orientation support, auto-upgrade legacy portrait AI watermarks on 16:9 batches before export.
        if exportOnly and (not test.root or test.allowAutoWmUpgrade) then
            local preWm=read(job.watermark_plan_path or (root..'/v0_5_0/batches/'..bid..'/watermark_plan.ini'))
            if preWm.enabled=='1' and tostring(preWm.v1_orient or '')=='' then
                local chkTlW=(tl.GetSetting and tonumber(tl:GetSetting('timelineResolutionWidth'))) or 720
                local chkTlH=(tl.GetSetting and tonumber(tl:GetSetting('timelineResolutionHeight'))) or 1280
                local chkV1,chkUp=collectTimelineVideoSnapshots()
                local hasLandscapeVid=false
                for i=1,tonumber(p.video_count) or 0 do
                    local pre='v'..i..'_'
                    if plan[pre..'skip']~='true' then
                        local s=tonumber(plan[pre..'start'])
                        local e=tonumber(plan[pre..'end'])
                        if s and e and e>s then
                            local vw,vh=detectVideoExportRes(s,e,pre,chkV1,chkUp,chkTlW,chkTlH)
                            if vw>vh then hasLandscapeVid=true;break end
                        end
                    end
                end
                if hasLandscapeVid then
                    pulse('PREPARING_EXPORT','检测到 16:9 横屏视频，正在自动升级适配横屏 AI 水印比例…')
                    cleaning=true
                    local _,wmReloaded=applyBatchWatermarks(plan)
                    cleaning=false
                    if wmReloaded then
                        write(base..'/cleaned.ini',plan)
                    else
                        assert(pm:SaveProject(),'SAVE_WATERMARK_PROJECT_FAILED')
                    end
                    assert(plan.timeline_id==uid,'TIMELINE_MISMATCH: 水印适配刷新后当前时间线与预期不符')
                end
            end
        end
        -- Snapshot original timeline resolution before per-resolution grouped rendering, and inspect live V1/V2+ media resolutions.
        local origTlW=(tl.GetSetting and tonumber(tl:GetSetting('timelineResolutionWidth'))) or 720
        local origTlH=(tl.GetSetting and tonumber(tl:GetSetting('timelineResolutionHeight'))) or 1280
        local expV1Snap,expUpperSnap=collectTimelineVideoSnapshots()
        -- Require an explicit reusable video preset; never inherit WAV settings.
        prepareExport()
        -- Flow Studio itself records the exact video_ids that received scripture subtitles
        -- (`job.subtitle_video_ids` / `scripture_videos.ini`). Direct O(1) lookup by video_id,
        -- zero timeline scanning!
        local onlySet=nil
        if job.only_video_ids and job.only_video_ids~='' then
            onlySet={};for token in tostring(job.only_video_ids):gmatch('[^,]+') do onlySet[token]=true end
        end
        local rawSubIds=job.subtitle_video_ids
        if rawSubIds==nil then
            local sv=read(base..'/scripture_videos.ini')
            if sv.subtitle_video_ids==nil then
                sv=read(root..'/v0_5_0/batches/'..bid..'/scripture_videos.ini')
            end
            rawSubIds=sv.subtitle_video_ids or ''
        end
        local subtitleVideoSet={}
        for token in tostring(rawSubIds or ''):gmatch('%d+') do
            subtitleVideoSet[token]=true
        end
        local hasAnySubtitleVideo=false
        for i=1,tonumber(p.video_count) do
            local pre='v'..i..'_'
            local id=tostring(p[pre..'id'] or '')
            if subtitleVideoSet[id] and (not onlySet or onlySet[id]) and plan[pre..'skip']~='true' then
                hasAnySubtitleVideo=true
                break
            end
        end
        local function enableSubtitleTracksIfNeeded()
            if hasAnySubtitleVideo then
                if tl.SetTrackEnable then
                    local subTrackCount=tonumber(tl.GetTrackCount and tl:GetTrackCount('subtitle')) or 0
                    for sTrk=1,subTrackCount do
                        pcall(function() tl:SetTrackEnable('subtitle',sTrk,true) end)
                    end
                end
            else
                pcall(function() project:SetRenderSettings({ExportSubtitle=false}) end)
            end
        end
        enableSubtitleTracksIfNeeded()

        local subBurnVideoCount=0
        local resGroups,resGroupMap={},{}
        local totalToRender=0
        for i=1,tonumber(p.video_count) do
            guard();local pre='v'..i..'_';local id=p[pre..'id'];local receipt=base..'/export_'..id..'.ini'
            if onlySet and not onlySet[tostring(id)] then
                -- Re-export of selected videos only: leave every other video untouched.
            elseif plan[pre..'skip']=='true' then
                local skipped={video_id=id,status='SKIPPED',reason=plan[pre..'skip_reason'] or 'VIDEO_SOURCE_MISSING_SKIPPED'}
                write(receipt,skipped)
                pulse('PREPARING_EXPORT','跳过缺失的完整视频 '..i..' / '..p.video_count..' · video_id='..tostring(id)..' · '..skipped.reason)
            else
                local out=read(receipt)
                local stem=p[pre..'final_filename']:gsub('%.[mM][pP]4$','')
                stem=stem:gsub('[\240-\244][\128-\191][\128-\191][\128-\191]',''):gsub('\239\191\189',''):gsub('\239\184\143',''):gsub('\226\128\141','')
                local output=p[pre..'output_dir']..'/'..stem..'.mp4'
                local vStart=tonumber(plan[pre..'start'])
                local vEnd=tonumber(plan[pre..'end'])
                local hasSubtitle=(subtitleVideoSet[tostring(id)]==true)
                local wantBurn=hasSubtitle and '1' or '0'
                local targetW,targetH=detectVideoExportRes(vStart,vEnd,pre,expV1Snap,expUpperSnap,origTlW,origTlH)
                local wantRes=tostring(targetW)..'x'..tostring(targetH)
                if out.status=='COMPLETE' then
                    assert(out.video_id==id and nonempty(out.output_path),'COMPLETED_OUTPUT_MISSING: 已有成功记录保留')
                else
                    local status=out.render_id and (project:GetRenderJobStatus(out.render_id) or {}) or {}
                    local state=renderStatus(status.JobStatus)
                    if out.output_path==output and state=='Complete' and nonempty(output) and (out.export_res or '720x1280')==wantRes then
                        out.status='COMPLETE';out.export_res=wantRes;write(receipt,out)
                    else
                        assert(state~='Rendering','RENDER_STILL_RUNNING')
                        if nonempty(output) and (state=='Failed' or state=='Cancelled' or (out.render_id and (out.export_res or '720x1280')~=wantRes)) then
                            local backup=output..'.failed-'..tostring(out.render_id):gsub('[^%w_-]','_')
                            assert(not nonempty(backup),'FAILED_BACKUP_EXISTS');assert(os.rename(output,backup),'PRESERVE_FAILED_OUTPUT_FAILED')
                        end
                        assert(not nonempty(output),'OUTPUT_ALREADY_EXISTS: 未确认文件不会覆盖')
                        local reuseRid=nil
                        if out.output_path==output and (state=='Queued' or state=='Ready') and (out.subtitle_burnin or '0')==wantBurn and (out.export_res or '720x1280')==wantRes then
                            reuseRid=out.render_id
                        elseif out.render_id and (state=='Queued' or state=='Ready') then
                            pcall(function() if project.DeleteRenderJob then project:DeleteRenderJob(out.render_id) end end)
                        end
                        if hasSubtitle then
                            subBurnVideoCount=subBurnVideoCount+1
                        end
                        local grp=resGroupMap[wantRes]
                        if not grp then
                            grp={resKey=wantRes,w=targetW,h=targetH,items={}}
                            resGroupMap[wantRes]=grp
                            resGroups[#resGroups+1]=grp
                        end
                        grp.items[#grp.items+1]={
                            idx=i,id=id,pre=pre,stem=stem,output=output,
                            targetDir=p[pre..'output_dir'],vStart=vStart,vEnd=vEnd,
                            hasSubtitle=hasSubtitle,wantBurn=wantBurn,
                            receipt=receipt,out=out,reuseRid=reuseRid,
                        }
                        totalToRender=totalToRender+1
                    end
                end
            end
        end

        if totalToRender>0 then
            local subSummary=subBurnVideoCount>0 and ('（其中 '..tostring(subBurnVideoCount)..' 条含字幕视频已开启字幕烧录）') or ''
            local doneBeforeGroup=0
            for _,grp in ipairs(resGroups) do
                guard()
                local orientTag=(grp.w>grp.h) and '16:9横屏' or '9:16竖屏'
                local resLabel=grp.resKey..'（'..orientTag..'）'
                local switchedTl=setTimelineResolution(grp.w,grp.h)
                if switchedTl then
                    prepareExport()
                    enableSubtitleTracksIfNeeded()
                end
                local grpIds,grpPending={},{}
                for itemPos,it in ipairs(grp.items) do
                    guard()
                    local rid=it.reuseRid
                    if switchedTl and rid then
                        pcall(function() if project.DeleteRenderJob then project:DeleteRenderJob(rid) end end)
                        rid=nil
                    end
                    local out=it.out
                    if not rid then
                        if itemPos==1 or itemPos==#grp.items or itemPos%8==0 then
                            local subHint=it.hasSubtitle and '（含经文字幕，已开启烧录到视频）' or ''
                            pulse('PREPARING_EXPORT','按 V1 完整视频范围添加渲染 '..it.idx..' / '..p.video_count..' · '..resLabel..subHint..'；V2 及以上可见轨道一起合成')
                        end
                        if it.hasSubtitle then
                            local mergedOk=project:SetRenderSettings({SelectAllFrames=false,MarkIn=it.vStart,MarkOut=it.vEnd-1,TargetDir=it.targetDir,CustomName=it.stem,ExportVideo=true,ExportAudio=true,FormatWidth=grp.w,FormatHeight=grp.h,ExportSubtitle=true,SubtitleFormat='BurnIn'})
                            if not mergedOk then
                                assert(project:SetRenderSettings({SelectAllFrames=false,MarkIn=it.vStart,MarkOut=it.vEnd-1,TargetDir=it.targetDir,CustomName=it.stem,ExportVideo=true,ExportAudio=true,FormatWidth=grp.w,FormatHeight=grp.h,ExportSubtitle=true}),'EXPORT_SETTINGS_FAILED')
                                assert(project:SetRenderSettings({ExportSubtitle=true,SubtitleFormat='BurnIn'}),'SUBTITLE_BURNIN_SETTINGS_FAILED: 无法开启字幕烧录（video_id='..tostring(it.id)..'）')
                            end
                        elseif hasAnySubtitleVideo then
                            assert(project:SetRenderSettings({SelectAllFrames=false,MarkIn=it.vStart,MarkOut=it.vEnd-1,TargetDir=it.targetDir,CustomName=it.stem,ExportVideo=true,ExportAudio=true,FormatWidth=grp.w,FormatHeight=grp.h,ExportSubtitle=false}),'EXPORT_SETTINGS_FAILED')
                        else
                            assert(project:SetRenderSettings({SelectAllFrames=false,MarkIn=it.vStart,MarkOut=it.vEnd-1,TargetDir=it.targetDir,CustomName=it.stem,ExportVideo=true,ExportAudio=true,FormatWidth=grp.w,FormatHeight=grp.h}),'EXPORT_SETTINGS_FAILED')
                        end
                        rid=assert(project:AddRenderJob(),'ADD_RENDER_FAILED')
                        out={video_id=it.id,render_id=rid,status='QUEUED',output_path=it.output,subtitle_burnin=it.wantBurn,export_res=grp.resKey}
                        write(it.receipt,out)
                    end
                    grpIds[#grpIds+1]=rid
                    grpPending[#grpPending+1]={out=out,receipt=it.receipt,output=it.output}
                end

                local multiHint=(#resGroups>1) and (' · 当前规格 '..resLabel) or (' · '..resLabel)
                pulse('RENDERING','已添加 '..#grpIds..' 个完整视频'..multiHint..'，按 V1 范围批量渲染'..subSummary..'；包含所有可见上层视频轨',{current=tostring(doneBeforeGroup),total=tostring(totalToRender)})
                assert(project:StartRendering(grpIds),'START_RENDER_FAILED')
                local started=os.time();local idle=0
                local maxIdle=(not test.noSleep and not platform.windows) and 20 or 10
                local lastPulseKey,lastPulseTs='',0
                while true do
                    guard();local remaining=0;local failedCount,cancelledCount=0,0;local activePct=nil
                    local liveRendering=project:IsRenderingInProgress() and true or false
                    for entryIdx,entry in ipairs(grpPending) do
                        if entry.out.status~='COMPLETE' then
                            local jst=project:GetRenderJobStatus(entry.out.render_id) or {}
                            local state=renderStatus(jst.JobStatus)
                            if state=='Complete' and nonempty(entry.output) then
                                entry.out.status='COMPLETE';write(entry.receipt,entry.out)
                            else
                                remaining=remaining+1
                                if state=='Rendering' then
                                    if activePct==nil and jst.CompletionPercentage~=nil then
                                        activePct=math.max(0,math.min(100,math.floor(tonumber(jst.CompletionPercentage) or 0)))
                                    end
                                    if liveRendering then
                                        for tailIdx=entryIdx+1,#grpPending do
                                            if grpPending[tailIdx].out.status~='COMPLETE' then
                                                remaining=remaining+1
                                            end
                                        end
                                        break
                                    end
                                elseif state=='Failed' then failedCount=failedCount+1
                                elseif state=='Cancelled' then cancelledCount=cancelledCount+1 end
                            end
                        end
                    end
                    local doneInGrp=#grpPending-remaining
                    local doneOverall=doneBeforeGroup+doneInGrp
                    local pctSuffix=(activePct~=nil and remaining>0) and ('（当前视频 '..tostring(activePct)..'%）') or ''
                    local specSuffix=(#resGroups>1 or grp.w>grp.h) and (' · '..resLabel) or ''
                    local nowTs=os.time()
                    local pulseKey=tostring(doneOverall)..':'..tostring(activePct or '')
                    if pulseKey~=lastPulseKey or (nowTs-lastPulseTs)>=3 or remaining==0 then
                        pulse('RENDERING','批量渲染完成 '..doneOverall..' / '..totalToRender..specSuffix..pctSuffix,{current=tostring(doneOverall),total=tostring(totalToRender)})
                        lastPulseKey=pulseKey
                        lastPulseTs=nowTs
                    end
                    if remaining==0 then break end
                    if liveRendering then idle=0 else idle=idle+1 end
                    if idle>maxIdle then
                        local remOverall=totalToRender-doneOverall
                        local parts={'已完成 '..tostring(doneOverall)..'/'..tostring(totalToRender)..' 条'}
                        if failedCount>0 then parts[#parts+1]='失败 '..tostring(failedCount)..' 条' end
                        if cancelledCount>0 then parts[#parts+1]='已取消 '..tostring(cancelledCount)..' 条' end
                        if failedCount==0 and cancelledCount==0 then parts[#parts+1]=tostring(remOverall)..' 条未确认' end
                        error('BATCH_RENDER_INCOMPLETE: 导出未完成（'..table.concat(parts,'，')..'）；成功成品已保存，可重试导出',0)
                    end
                    assert(os.time()-started<7200*#grpPending,'RENDER_TIMEOUT')
                    if not test.noSleep then os.execute(platform.windows and '/bin/sleep 1' or '/bin/sleep 0.5') end
                end
                doneBeforeGroup=doneBeforeGroup+#grpPending
            end
            pcall(function()
                if setTimelineResolution(origTlW,origTlH) then
                    pm:SaveProject()
                end
            end)
        end
        pulse('COMPLETED','所有视频已导出，成品记录已保留')
        os.remove(root..'/pipeline.lock')
        return {stage='READY',detail='批次导出完成',project=p.project_name,timeline=p.timeline_name}
    end)
    if not ok then
        local cleanErr=tostring(result or ''):gsub('%.%.%.[^:%s]*%.lua:%d+:%s*',''):gsub('/[^:%s]*%.lua:%d+:%s*','')
        pulse(cleaning and 'CLEANING_ERROR' or 'EXPORT_ERROR',cleanErr)
        error(cleanErr,0)
    end
    return result
end
return {run=run}
