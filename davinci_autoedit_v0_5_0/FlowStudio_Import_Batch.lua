local platformSource=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local platform=assert(loadfile(platformSource:match('^(.*)/[^/]+$')..'/FlowStudio_Platform.lua'))()
local os,io,loadfile=platform.os,platform.io,platform.loadfile
if jit and jit.off then pcall(jit.off) end
-- FlowStudio Import Batch - simple append mode.
-- Rule: ignore all earlier timeline content/markers. Find only the last yellow Flow Studio
-- import marker, use its recorded video end as the anchor, then append the new batch after
-- a 50-frame gap. Never deduplicate against older batches/video IDs.

local function read(path)
    local f=io.open(path,'r');local t={};if not f then return t end
    for line in f:lines() do local k,v=line:match('^([^=]+)=(.*)$');if k then t[k]=v end end
    f:close();return t
end

local function write(path,t)
    local f=assert(io.open(path..'.tmp','w'),'WRITE_FAILED: '..path)
    local keys={};for k in pairs(t) do keys[#keys+1]=k end;table.sort(keys)
    for _,k in ipairs(keys) do f:write(k..'='..tostring(t[k]):gsub('[\r\n]',' ')..'\n') end
    f:close();assert(os.rename(path..'.tmp',path),'PUBLISH_FAILED: '..path)
end

local function number(v,label)
    local n=tonumber(v);assert(n and n==math.floor(n),'INVALID_INTEGER: '..label);return n
end

-- Resolve can briefly return nil / a fractional value right after AppendToTimeline (e.g. while it is saving).
-- Re-read a few times, accept values within 0.01 of an integer, and report the raw value if it never settles.
local ffiOK,ffiMod=pcall(require,'ffi')
if ffiOK and ffiMod and not platform.windows then
    pcall(function() ffiMod.cdef[[ int usleep(unsigned int usec); ]] end)
end
local function fastSleep(sec)
    local s=tonumber(sec) or 0
    if s<=0 then return end
    if ffiOK and ffiMod and not platform.windows then
        if pcall(function() ffiMod.C.usleep(math.floor(s*1000000)) end) then return end
    end
    if os.clock then local t=os.clock();while os.clock()-t<s do end end
end

local function clipFrame(clip,method,label)
    local last
    for attempt=1,8 do
        local ok,v=pcall(function() return clip[method](clip) end)
        local n=ok and tonumber(v) or nil
        last=ok and tostring(v) or ('error: '..tostring(v))
        if n and n==n and math.abs(n)~=math.huge then
            local r=math.floor(n+0.5)
            if math.abs(n-r)<0.01 then return r end
        end
        fastSleep(0.05)
    end
    error('INVALID_INTEGER: '..label..' (Resolve returned '..tostring(last)..')')
end

local function float(v,label)
    local n=tonumber(v);assert(n and n==n and math.abs(n)~=math.huge,'INVALID_NUMBER: '..label);return n
end

local function tag(text)
    local t={};if type(text)~='string' or text:sub(1,11)~='FLOWSTUDIO|' then return t end
    for k,v in text:gmatch('([%w_]+)=([^|]+)') do t[k]=v end
    return t
end

local function custom(vid,bid,status,start,finish)
    return 'FLOWSTUDIO|video_id='..vid..'|batch_id='..bid..'|status='..status..'|start='..start..'|end='..finish
end

local function lastImportMarkerEnd(timeline,origin)
    local markers=assert(timeline:GetMarkers(),'MARKERS_UNAVAILABLE')
    local bestFrame,bestMarker=nil,nil
    for frame,marker in pairs(markers) do
        if type(frame)=='number' and type(marker)=='table' and marker.color=='Yellow' then
            local info=tag(marker.customData)
            if info.video_id and info.batch_id and (not bestFrame or frame>bestFrame) then
                bestFrame,bestMarker=frame,marker
            end
        end
    end
    if not bestFrame then return nil end

    local markerAbs=origin+bestFrame
    local info=tag(bestMarker.customData)
    local savedEnd=tonumber(info['end'])
    if savedEnd and savedEnd>markerAbs then return savedEnd end

    local duration=tonumber(bestMarker.duration) or 1
    return markerAbs+math.max(1,math.floor(duration))
end

local function ensureBin(pool,parent,name)
    assert(pool:SetCurrentFolder(parent),'SET_MEDIA_FOLDER_FAILED')
    for _,f in ipairs(assert(parent:GetSubFolderList(),'MEDIA_FOLDERS_UNAVAILABLE')) do
        if f:GetName()==name then return f end
    end
    return assert(pool:AddSubFolder(parent,name),'CREATE_MEDIA_FOLDER_FAILED: '..name)
end

local function run(app,job,report,rootOverride)
    local root=rootOverride or os.getenv('HOME')..'/Documents/FlowStudioResolveBridge'
    local bid=assert(job.batch_id,'BATCH_ID_REQUIRED')
    assert(bid:match('^[%w_]+$'),'INVALID_BATCH_ID')
    local base=root..'/v0_5_0/batches/'..bid
    assert(job.manifest_path==base..'/manifest.ini','MANIFEST_PATH_MISMATCH')

    local m=read(job.manifest_path)
    assert(m.batch_id==bid and m.work_date==job.work_date,'BATCH_DATE_MISMATCH')
    local expectedMain='MAIN-'..m.work_date
    local slotSuffix=tostring(m.timeline_name or ''):match('^'..expectedMain:gsub('%-','%%-')..'%-(B%d+)$')
    assert(m.project_name=='FlowStudio-'..m.work_date and (m.timeline_name==expectedMain or slotSuffix~=nil),'TARGET_NAME_MISMATCH')
    assert(m.group_gap_frames=='50','GROUP_GAP_MUST_BE_50_FRAMES')

    local pm=assert(app:GetProjectManager(),'PROJECT_MANAGER_UNAVAILABLE')
    local project=assert(pm:GetCurrentProject(),'PROJECT_NOT_OPEN')
    assert(project:GetName()==m.project_name,'PROJECT_MISMATCH: 请先唤醒当天项目')
    local timeline=assert(project:GetCurrentTimeline(),'TIMELINE_NOT_OPEN')
    assert(timeline:GetName()==m.timeline_name,'TIMELINE_MISMATCH: 请先唤醒对应批次时间线')
    local origin=number(timeline:GetStartFrame(),'timeline origin')

    local function guard()
        local current=pm:GetCurrentProject()
        local currentTimeline=current and current:GetCurrentTimeline()
        assert(current and current:GetName()==m.project_name and currentTimeline and currentTimeline:GetName()==m.timeline_name,'TARGET_CHANGED_DURING_IMPORT')
    end

    local logDir=root..'/logs/'..bid
    if not platform.windows then
        os.execute("/bin/mkdir -p '"..tostring(logDir):gsub("'","'\\''").."' >/dev/null 2>&1")
    end
    local logPath=logDir..'/import.log'
    local logBuf={}
    local function flushLogs()
        if #logBuf==0 then return end
        local f=io.open(logPath,'a')
        if f then f:write(table.concat(logBuf,'\n')..'\n');f:close() end
        logBuf={}
    end
    local function log(message)
        logBuf[#logBuf+1]=os.date('%Y-%m-%d %H:%M:%S')..' '..message
        if #logBuf>=80 then flushLogs() end
    end

    local pool=assert(project:GetMediaPool(),'MEDIA_POOL_UNAVAILABLE')
    local previousFolder=pool:GetCurrentFolder()
    local count=number(m.video_count,'video count');assert(count>0,'EMPTY_BATCH')

    local lockPath=root..'/pipeline.lock'

    local tlWidth=tonumber(timeline:GetSetting('timelineResolutionWidth'))
    local tlHeight=tonumber(timeline:GetSetting('timelineResolutionHeight'))
    local videos,ids,segments={},{},{}
    local allUniquePaths,seenGlobalPath={},{}
    -- Only validate the NEW batch itself. Old timeline IDs/markers are deliberately ignored.
    for i=1,count do
        local p='v'..i..'_'
        local vid=tostring(number(m[p..'id'],'video id'))
        assert(not ids[vid],'DUPLICATE_VIDEO_ID_IN_CURRENT_BATCH: '..vid);ids[vid]=true
        local v={
            id=vid,prefix=p,seq=number(m[p..'seq'],'video seq'),
            recipient=assert(m[p..'recipient']),host=assert(m[p..'host']),parts={}
        }
        local n=number(m[p..'segment_count'],'segment count');assert(n>0,'EMPTY_VIDEO')
        for j=1,n do
            local sid=tostring(number(m[p..'s'..j..'_id'],'segment id'))
            assert(not segments[sid],'DUPLICATE_SEGMENT_ID_IN_CURRENT_BATCH: '..sid);segments[sid]=true
            local path=assert(m[p..'s'..j..'_path'],'MISSING_SEGMENT_PATH')
            local f=assert(io.open(path,'rb'),'SOURCE_NOT_READABLE: '..path)
            local byte=f:read(1);f:close();assert(byte,'SOURCE_EMPTY: '..path)
            local transform=nil
            local tp=p..'s'..j..'_transform_'
            if m[tp..'ZoomX'] then
                transform={}
                for _,key in ipairs({'ZoomX','ZoomY','Pan','Tilt'}) do transform[key]=float(m[tp..key],'transform '..key) end
                for _,key in ipairs({'width','height'}) do transform[key]=number(m[tp..key],'transform '..key) end
                if (tlWidth~=transform.width or tlHeight~=transform.height) and timeline.SetSetting and tlWidth and tlHeight and ((tlWidth==transform.height and tlHeight==transform.width) or (tlWidth>tlHeight and transform.width<transform.height)) then
                    -- Timeline was in landscape mode (e.g. pure-16:9 batch or interrupted 16:9 export); restore portrait dimensions required by clip_transform.
                    assert(timeline:SetSetting('useCustomSettings','1'),'TIMELINE_CUSTOM_SETTINGS_FAILED')
                    if transform.width<=transform.height then
                        assert(timeline:SetSetting('timelineResolutionWidth',tostring(transform.width)),'TIMELINE_RESOLUTION_FAILED')
                        assert(timeline:SetSetting('timelineResolutionHeight',tostring(transform.height)),'TIMELINE_RESOLUTION_FAILED')
                    else
                        assert(timeline:SetSetting('timelineResolutionHeight',tostring(transform.height)),'TIMELINE_RESOLUTION_FAILED')
                        assert(timeline:SetSetting('timelineResolutionWidth',tostring(transform.width)),'TIMELINE_RESOLUTION_FAILED')
                    end
                    tlWidth=tonumber(timeline:GetSetting('timelineResolutionWidth'))
                    tlHeight=tonumber(timeline:GetSetting('timelineResolutionHeight'))
                end
                assert(tlWidth==transform.width and tlHeight==transform.height,'TRANSFORM_TIMELINE_SIZE_MISMATCH: '..sid)
            end
            v.parts[#v.parts+1]={id=sid,path=path,transform=transform}
            if not seenGlobalPath[path] then
                seenGlobalPath[path]=true
                allUniquePaths[#allUniquePaths+1]=path
            end
        end
        videos[#videos+1]=v
    end

    -- Keep one simple safety check for an interrupted run of THIS SAME batch. This does not
    -- inspect historical markers; it only prevents blindly duplicating a half-imported current batch.
    local journal=read(base..'/progress.ini')
    if journal.pending_video and journal.pending_video~='' then
        error('IMPORT_UNCERTAIN: 当前批次上次导入未完成，请先确认现场，避免重复追加')
    end

    local lastEnd=lastImportMarkerEnd(timeline,origin)
    if not lastEnd and timeline.SetSetting then
        local allLand,landW,landH=true,nil,nil
        for i=1,count do
            local p='v'..i..'_'
            local ew=tonumber(m[p..'export_width'])
            local eh=tonumber(m[p..'export_height'])
            local hasTransform=(m[p..'s1_transform_ZoomX']~=nil)
            if not ew or not eh or ew<=eh or hasTransform then
                allLand=false;break
            end
            if not landW or (ew*eh)>(landW*landH) then landW,landH=ew,eh end
        end
        if allLand and landW and landH and (tlWidth~=landW or tlHeight~=landH) then
            pcall(function()
                timeline:SetSetting('useCustomSettings','1')
                timeline:SetSetting('timelineResolutionHeight',tostring(landH))
                timeline:SetSetting('timelineResolutionWidth',tostring(landW))
                tlWidth=tonumber(timeline:GetSetting('timelineResolutionWidth')) or tlWidth
                tlHeight=tonumber(timeline:GetSetting('timelineResolutionHeight')) or tlHeight
            end)
        end
    end
    local nextStart=lastEnd and (lastEnd+50) or origin
    log('APPEND_ANCHOR last_yellow_end='..tostring(lastEnd or 'NONE')..' next_start='..nextStart..' gap=50')
    flushLogs()

    write(lockPath,{batch_id=bid,action='IMPORT_BATCH',work_date=m.work_date,stage='IMPORTING'})
    local result={batch_id=bid,status='IMPORTED',imported_count=0,skipped_count=0,video_count=count}

    -- Switch to Deliver page during bulk import: hides both the Edit-page waveform/filmstrip canvas
    -- AND the Media-page folder tree / thumbnail poster generator, eliminating UI redraw bottlenecks.
    pcall(function()
        if app.OpenPage then app:OpenPage('deliver') end
    end)

    local ok,err=pcall(function()
        local rootFolder=assert(pool:GetRootFolder(),'MEDIA_ROOT_UNAVAILABLE')
        local batchRoot=slotSuffix and ensureBin(pool,rootFolder,slotSuffix) or rootFolder
        local batchBin=ensureBin(pool,batchRoot,'Batch_'..bid)
        assert(pool:SetCurrentFolder(batchBin),'SET_MEDIA_FOLDER_FAILED')

        -- Bulk ImportMedia across the entire batch into 1 flat batch bin (1-3 C++ transactions instead of 150+ serial transactions).
        local mediaByPath={}
        local CHUNK_SIZE=250
        for idx=1,#allUniquePaths,CHUNK_SIZE do
            guard()
            local chunk={}
            local chunkEnd=math.min(#allUniquePaths,idx+CHUNK_SIZE-1)
            for k=idx,chunkEnd do chunk[#chunk+1]=allUniquePaths[k] end
            report('IMPORTING','正在极速批量入库媒体池 '..chunkEnd..' / '..#allUniquePaths..' 个片段',{batch_id=bid,current=0,total=count})
            local batchImported=pool:ImportMedia(chunk)
            local mappedCount=0
            if type(batchImported)=='table' then
                for _,it in ipairs(batchImported) do
                    local okP,fp=pcall(function() return it:GetClipProperty('File Path') end)
                    if okP and type(fp)=='string' and fp~='' then
                        mediaByPath[fp]=it
                        mediaByPath[platform.path(fp)]=it
                        mappedCount=mappedCount+1
                    end
                end
                if mappedCount==0 and #batchImported==#chunk then
                    for k=1,#chunk do
                        mediaByPath[chunk[k]]=batchImported[k]
                        mediaByPath[platform.path(chunk[k])]=batchImported[k]
                    end
                end
            end
        end

        local scannedExisting=false
        local function resolveMediaItem(path)
            local norm=platform.path(path)
            local hit=mediaByPath[path] or mediaByPath[norm]
            if hit then return hit end
            if not scannedExisting then
                scannedExisting=true
                pcall(function()
                    for _,existing in ipairs(batchBin:GetClipList() or {}) do
                        local fp=existing:GetClipProperty('File Path')
                        if type(fp)=='string' and fp~='' then
                            mediaByPath[fp]=existing
                            mediaByPath[platform.path(fp)]=existing
                        end
                    end
                end)
                hit=mediaByPath[path] or mediaByPath[norm]
                if hit then return hit end
            end
            local single=assert(pool:ImportMedia({path}),'MEDIA_IMPORT_FAILED: '..path)
            hit=assert(single[1],'MEDIA_IMPORT_COUNT_MISMATCH')
            mediaByPath[path]=hit
            mediaByPath[norm]=hit
            return hit
        end

        write(base..'/progress.ini',{pending_video=videos[1].id,stage='BEFORE_APPEND',start_frame=nextStart})

        for i,v in ipairs(videos) do
            if i==1 or i==count or i%5==0 then
                report('IMPORTING','正在极速铺设时间线 '..i..' / '..count..'（'..v.recipient..' · '..v.host..'）',{batch_id=bid,current=i,total=count,video_id=v.id})
            end
            if i==1 or i%15==0 then
                guard()
            end

            local start,finish,sourceBatch=nextStart,nextStart,bid
            for j,part in ipairs(v.parts) do
                local item=resolveMediaItem(part.path)
                log('APPEND video_id='..v.id..' segment_id='..part.id..' recordFrame='..finish..' path='..part.path)
                local placed=assert(pool:AppendToTimeline({{mediaPoolItem=item,recordFrame=finish,trackIndex=1}}),'APPEND_FAILED')
                local actualEnd=nil
                local transform=part.transform
                local transformApplied=false
                for _,clip in ipairs(placed) do
                    assert(clipFrame(clip,'GetStart','actual start')==finish,'INSERT_POSITION_MISMATCH')
                    actualEnd=math.max(actualEnd or finish,clipFrame(clip,'GetEnd','actual end'))
                    if transform and clip:GetProperty('ZoomX')~=nil then
                        for _,key in ipairs({'ZoomX','ZoomY','Pan','Tilt'}) do
                            assert(clip:SetProperty(key,transform[key]),'TRANSFORM_SET_FAILED: '..part.id..' '..key)
                            assert(math.abs(float(clip:GetProperty(key),'transform readback')-transform[key])<0.001,'TRANSFORM_VERIFY_FAILED: '..key)
                        end
                        transformApplied=true
                    end
                end
                assert(not transform or transformApplied,'TRANSFORM_VIDEO_CLIP_NOT_FOUND')
                assert(actualEnd and actualEnd>finish,'INSERT_LENGTH_INVALID')
                log('ACTUAL video_id='..v.id..' segment_id='..part.id..' start='..finish..' end='..actualEnd)
                finish=actualEnd
            end

            assert(timeline:AddMarker(
                start-origin,'Yellow',
                string.format('%02d | %s | %s',v.seq,v.recipient,v.host),
                'Flow Studio 批次：'..bid,1,
                custom(v.id,bid,'COMPLETE',start,finish)
            ),'COMPLETE_MARKER_FAILED')

            if i%40==0 then
                collectgarbage('collect')
            end

            result.imported_count=result.imported_count+1
            result[v.prefix..'id']=v.id
            result[v.prefix..'start']=start
            result[v.prefix..'end']=finish
            result[v.prefix..'source_batch']=sourceBatch
            result.batch_start_frame=math.min(result.batch_start_frame or start,start)
            result.batch_end_frame=math.max(result.batch_end_frame or finish,finish)

            -- Every complete video in the new batch is separated by the same 50-frame gap.
            nextStart=finish+50
        end

        write(base..'/progress.ini',{pending_video='',stage='VIDEO_COMPLETE',video_id=videos[count].id,end_frame=result.batch_end_frame or nextStart})
        guard()
        assert(pm:SaveProject(),'SAVE_BATCH_FAILED')
        log('IMPORTED append_only added='..result.imported_count..' anchor_end='..tostring(lastEnd or 'NONE')..' gap=50')
        flushLogs()
        write(base..'/result.ini',result)
        os.remove(lockPath)
    end)

    if previousFolder then pcall(function() pool:SetCurrentFolder(previousFolder) end) end
    pcall(function()
        if app.OpenPage then app:OpenPage('edit') end
    end)
    if not ok then
        log('ERROR '..tostring(err))
        flushLogs()
        write(lockPath,{batch_id=bid,action='IMPORT_BATCH',work_date=m.work_date,stage='IMPORT_ERROR'})
        error(err)
    end

    return {
        project=m.project_name,timeline=m.timeline_name,batch_id=bid,
        imported_count=result.imported_count,skipped_count=result.skipped_count,
        batch_start_frame=result.batch_start_frame,batch_end_frame=result.batch_end_frame
    }
end

return run
