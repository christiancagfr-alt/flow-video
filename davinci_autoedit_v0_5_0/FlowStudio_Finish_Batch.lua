local platformSource=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local platform=assert(loadfile(platformSource:match('^(.*)/[^/]+$')..'/FlowStudio_Platform.lua'))()
local os,io,loadfile=platform.os,platform.io,platform.loadfile
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
    assert(state.stage~='CLEANING' and (state.stage~='CLEANING_ERROR' or recoveringAppliedCleanup),
        'CLEANUP_INTERRUPTED: 保留现场，禁止重复删除')
    local lock=read(root..'/pipeline.lock')
    assert(lock.batch_id==bid and lock.attempt_id==attempt,'PIPELINE_IDENTITY_MISMATCH')
    assert(lock.stage=='WAITING_USER_REVIEW' or lock.action=='FINISH_BATCH','PIPELINE_BUSY')
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
    -- An explicit choice separates cleanup from export of an already edited timeline.
    -- Never infer that old red/blue markers should be applied again.
    local finishMode=test.finishMode
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
    assert(finishMode=='cleanup' or finishMode=='export','INVALID_FINISH_MODE')
    local exportOnly=finishMode=='export'
    guard();assert(not project:IsRenderingInProgress(),'RENDER_ALREADY_RUNNING')

    local function pulse(stage,detail)
        if test.inspectOnly then return end
        state={batch_id=bid,attempt_id=attempt,stage=stage,detail=detail}
        write(base..'/finish.ini',state)
        write(root..'/pipeline.lock',{batch_id=bid,attempt_id=attempt,action='FINISH_BATCH',work_date=p.work_date,stage=stage})
        report(stage,detail,{batch_id=bid,project=p.project_name,timeline=p.timeline_name})
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
        assert(project:LoadRenderPreset('FlowStudio_Final') or project:LoadRenderPreset('H.264 Master'),'FINAL_PRESET_MISSING: 未找到 FlowStudio_Final 或 H.264 Master 视频预设')
        assert(project:SetCurrentRenderFormatAndCodec('mp4','H264'),'MP4_H264_UNAVAILABLE')
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
    local cleaning=false
    local ok,result=pcall(function()
        local plan=read(base..'/cleaned.ini')
        if exportOnly or (not plan.batch_id and recoveringAppliedCleanup) then
            -- The previous run already executed DeleteClips(). Do NOT delete again.
            -- Reconstruct the finished export ranges from the CURRENT V1 only, ignoring V2+ entirely.
            local intent=read(base..'/cleanup_intent.ini')
            assert(exportOnly or intent.count,'CLEANUP_RECOVERY_INTENT_MISSING')
            if exportOnly and plan.batch_id then
                assert(plan.batch_id==bid and plan.timeline_id==uid,'TIMELINE_MISMATCH: 请确保你打开了对应的批次时间线')
            end
            local all=items()
            local manifest=read(root..'/v0_5_0/batches/'..bid..'/manifest.ini')
            local owners={};local current={}
            for i=1,assert(tonumber(manifest.video_count),'IMPORT_MANIFEST_MISSING') do
                local pre='v'..i..'_';local id=manifest[pre..'id']
                for j=1,tonumber(manifest[pre..'segment_count']) do
                    local path=assert(manifest[pre..'s'..j..'_path'])
                    assert(not owners[path] or owners[path]==id,'AMBIGUOUS_SOURCE_OWNERSHIP');owners[path]=id
                end
            end
            for _,c in ipairs(all) do
                if c.kind=='video' then
                    local media=c.item:GetMediaPoolItem();local path=media and media:GetClipProperty('File Path')
                    c.owner=path and owners[path]
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
                        assert((exportOnly and c.s>=last) or c.s==last,
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
            plan.snapshot=fingerprint()
            if test.inspectOnly then return {stage='PREFLIGHT',remove_count=0,plan=plan} end
            assert(pm:SaveProject(),'SAVE_CLEANUP_RECOVERY_FAILED')
            write(base..'/cleaned.ini',plan)
            pulse('PREPARING_EXPORT',exportOnly and '直接批量导出：按当前 V1 视频范围导出，不检查清理标记、不删除片段' or '上次清理已执行；已仅按 V1 主轨恢复核验，V2 及以上完全忽略，不重复删除')
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
                    assert(not owners[path] or owners[path]==id,'AMBIGUOUS_SOURCE_OWNERSHIP');owners[path]=id
                end
            end
            for _,c in ipairs(all) do
                if c.kind=='video' then
                    local media=c.item:GetMediaPoolItem()
                    local path=media and media:GetClipProperty('File Path')
                    c.owner=path and owners[path]
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
            for frame,m in pairs(tl:GetMarkers() or {}) do
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
            for frame,m in pairs(tl:GetMarkers() or {}) do
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
                for frame,m in pairs(tl:GetMarkers() or {}) do
                    if type(m)=='table' then
                        local tags={};for k,v in tostring(m.customData):gmatch('|([^=|]+)=([^|]*)') do tags[k]=v end
                        if tags.batch_id==bid and tags.video_id==p[pre..'id'] and tags.status=='COMPLETE' then
                            found=found+1
                        end
                    end
                end
                if found~=1 then
                    error('VIDEO_MARKER_MISSING: video='..tostring(videoId)..
                        '；COMPLETE Marker数量='..tostring(found)..
                        '；完整视频范围='..frameTimecode(s-tl:GetStartFrame(),p.timeline_fps)..
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
            prepareExport()
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

            assert(pm:SaveProject(),'SAVE_CLEANUP_FAILED')
            plan.snapshot=fingerprint();write(base..'/cleaned.ini',plan)
            pulse('PREPARING_EXPORT','清理完成，准备逐个导出');cleaning=false
        end
        assert(plan.timeline_id==uid,'TIMELINE_MISMATCH: 导出前发现当前时间线与预期不符')
        -- Require an explicit reusable video preset; never inherit WAV settings.
        prepareExport()
        local pending,ids={},{}
        for i=1,tonumber(p.video_count) do
            guard();local pre='v'..i..'_';local id=p[pre..'id'];local receipt=base..'/export_'..id..'.ini'
            if plan[pre..'skip']=='true' then
                local skipped={video_id=id,status='SKIPPED',reason=plan[pre..'skip_reason'] or 'VIDEO_SOURCE_MISSING_SKIPPED'}
                write(receipt,skipped)
                pulse('PREPARING_EXPORT','跳过缺失的完整视频 '..i..' / '..p.video_count..' · video_id='..tostring(id)..' · '..skipped.reason)
            else
            local out=read(receipt)
            local stem=p[pre..'final_filename']:gsub('%.[mM][pP]4$','')
            stem=stem:gsub('[\240-\244][\128-\191][\128-\191][\128-\191]',''):gsub('\239\191\189',''):gsub('\239\184\143',''):gsub('\226\128\141','')
            local output=p[pre..'output_dir']..'/'..stem..'.mp4'
            if out.status=='COMPLETE' then
                assert(out.video_id==id and nonempty(out.output_path),'COMPLETED_OUTPUT_MISSING: 已有成功记录保留')
            else
                local status=out.render_id and (project:GetRenderJobStatus(out.render_id) or {}) or {}
                local state=renderStatus(status.JobStatus)
                if out.output_path==output and state=='Complete' and nonempty(output) then
                    out.status='COMPLETE';write(receipt,out)
                else
                    assert(state~='Rendering','RENDER_STILL_RUNNING')
                    if nonempty(output) and (state=='Failed' or state=='Cancelled') then
                        local backup=output..'.failed-'..tostring(out.render_id):gsub('[^%w_-]','_')
                        assert(not nonempty(backup),'FAILED_BACKUP_EXISTS');assert(os.rename(output,backup),'PRESERVE_FAILED_OUTPUT_FAILED')
                    end
                    assert(not nonempty(output),'OUTPUT_ALREADY_EXISTS: 未确认文件不会覆盖')
                    local rid
                    if out.output_path==output and (state=='Queued' or state=='Ready') then rid=out.render_id end
                    if not rid then
                        pulse('PREPARING_EXPORT','按 V1 完整视频范围添加渲染 '..i..' / '..p.video_count..'；V2 及以上可见轨道一起合成，但不参与范围计算')
                        assert(project:SetRenderSettings({SelectAllFrames=false,MarkIn=tonumber(plan[pre..'start']),MarkOut=tonumber(plan[pre..'end'])-1,TargetDir=p[pre..'output_dir'],CustomName=stem,ExportVideo=true,ExportAudio=true,FormatWidth=720,FormatHeight=1280}),'EXPORT_SETTINGS_FAILED')
                        rid=assert(project:AddRenderJob(),'ADD_RENDER_FAILED')
                        out={video_id=id,render_id=rid,status='QUEUED',output_path=output};write(receipt,out)
                    end
                    ids[#ids+1]=rid;pending[#pending+1]={out=out,receipt=receipt,output=output}
                end
            end
            end -- not skipped
        end
        if #ids>0 then
            pulse('RENDERING','已添加 '..#ids..' 个完整视频，按 V1 范围批量渲染；包含所有可见上层视频轨')
            assert(project:StartRendering(ids),'START_RENDER_FAILED')
            local started=os.time();local idle=0
            while true do
                guard();local remaining=0;local errors={}
                for _,entry in ipairs(pending) do
                    if entry.out.status~='COMPLETE' then
                        local state=renderStatus((project:GetRenderJobStatus(entry.out.render_id) or {}).JobStatus)
                        if state=='Complete' and nonempty(entry.output) then
                            entry.out.status='COMPLETE';write(entry.receipt,entry.out)
                        else
                            remaining=remaining+1
                            if state=='Failed' or state=='Cancelled' then errors[#errors+1]='视频 '..entry.out.video_id..' '..state end
                        end
                    end
                end
                pulse('RENDERING','批量渲染完成 '..(#pending-remaining)..' / '..#pending)
                if remaining==0 then break end
                if project:IsRenderingInProgress() then idle=0 else idle=idle+1 end
                assert(idle<=10,'BATCH_RENDER_INCOMPLETE: '..remaining..' 个未确认；'..table.concat(errors,'；')..'；成功成品已保存，可重试未完成导出')
                assert(os.time()-started<7200*#pending,'RENDER_TIMEOUT')
                if not test.noSleep then os.execute('/bin/sleep 1') end
            end
        end
        pulse('COMPLETED','所有视频已导出，成品记录已保留')
        os.remove(root..'/pipeline.lock')
        return {stage='READY',detail='批次导出完成',project=p.project_name,timeline=p.timeline_name}
    end)
    if not ok then pulse(cleaning and 'CLEANING_ERROR' or 'EXPORT_ERROR',tostring(result));error(result) end
    return result
end
return {run=run}
