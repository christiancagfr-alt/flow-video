local platformSource=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local platform=assert(loadfile(platformSource:match('^(.*)/[^/]+$')..'/FlowStudio_Platform.lua'))()
local os,io,loadfile=platform.os,platform.io,platform.loadfile
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
    assert(m.project_name=='FlowStudio-'..m.work_date and m.timeline_name=='MAIN-'..m.work_date,'TARGET_NAME_MISMATCH')
    assert(m.group_gap_frames=='50','GROUP_GAP_MUST_BE_50_FRAMES')

    local pm=assert(app:GetProjectManager(),'PROJECT_MANAGER_UNAVAILABLE')
    local project=assert(pm:GetCurrentProject(),'PROJECT_NOT_OPEN')
    assert(project:GetName()==m.project_name,'PROJECT_MISMATCH: 请先唤醒当天项目')
    local timeline=assert(project:GetCurrentTimeline(),'TIMELINE_NOT_OPEN')
    assert(timeline:GetName()==m.timeline_name,'TIMELINE_MISMATCH: 请先唤醒当天主时间线')
    local origin=number(timeline:GetStartFrame(),'timeline origin')

    local function guard()
        local current=pm:GetCurrentProject()
        local currentTimeline=current and current:GetCurrentTimeline()
        assert(current and current:GetName()==m.project_name and currentTimeline and currentTimeline:GetName()==m.timeline_name,'TARGET_CHANGED_DURING_IMPORT')
    end

    local function log(message)
        local f=io.open(root..'/logs/'..bid..'/import.log','a')
        if f then f:write(os.date('%Y-%m-%d %H:%M:%S')..' '..message..'\n');f:close() end
    end

    local pool=assert(project:GetMediaPool(),'MEDIA_POOL_UNAVAILABLE')
    local previousFolder=pool:GetCurrentFolder()
    local count=number(m.video_count,'video count');assert(count>0,'EMPTY_BATCH')

    local lockPath=root..'/pipeline.lock'
    local lock=read(lockPath)
    assert(not lock.batch_id or lock.batch_id==bid,'PIPELINE_LOCKED: 当前批次尚未结束')
    assert(not lock.action or lock.action=='IMPORT_BATCH','PIPELINE_LOCKED: 当前批次正在剪辑')

    local videos,ids,segments={},{},{}
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
                for _,key in ipairs({'ZoomX','ZoomY','Pan','Tilt','width','height'}) do transform[key]=number(m[tp..key],'transform '..key) end
                assert(tonumber(timeline:GetSetting('timelineResolutionWidth'))==transform.width and tonumber(timeline:GetSetting('timelineResolutionHeight'))==transform.height,'TRANSFORM_TIMELINE_SIZE_MISMATCH: '..sid)
            end
            v.parts[#v.parts+1]={id=sid,path=path,transform=transform}
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
    local nextStart=lastEnd and (lastEnd+50) or origin
    log('APPEND_ANCHOR last_yellow_end='..tostring(lastEnd or 'NONE')..' next_start='..nextStart..' gap=50')

    write(lockPath,{batch_id=bid,action='IMPORT_BATCH',stage='IMPORTING'})
    local result={batch_id=bid,status='IMPORTED',imported_count=0,skipped_count=0,video_count=count}

    local ok,err=pcall(function()
        for i,v in ipairs(videos) do
            report('IMPORTING','正在导入剪辑素材 '..i..' / '..count,{batch_id=bid,current=i,total=count,video_id=v.id})
            guard()

            local start,finish,sourceBatch=nextStart,nextStart,bid
            local bin=ensureBin(pool,assert(pool:GetRootFolder()),v.recipient)
            bin=ensureBin(pool,bin,v.host)
            bin=ensureBin(pool,bin,string.format('%02d',v.seq))
            assert(pool:SetCurrentFolder(bin),'SET_MEDIA_FOLDER_FAILED')

            local media={}
            for j,part in ipairs(v.parts) do
                report('IMPORTING','读取素材 '..i..' / '..count..' · 片段 '..j..' / '..#v.parts,{batch_id=bid,current=i,total=count,video_id=v.id})
                local imported=assert(pool:ImportMedia({part.path}),'MEDIA_IMPORT_FAILED: '..part.path)
                assert(imported[1] and not imported[2],'MEDIA_IMPORT_COUNT_MISMATCH')
                media[j]=imported[1]
            end

            write(base..'/progress.ini',{pending_video=v.id,stage='BEFORE_APPEND',start_frame=start})
            assert(timeline:AddMarker(
                start-origin,'Yellow',
                string.format('%02d | %s | %s',v.seq,v.recipient,v.host),
                'Flow Studio 批次：'..bid,1,
                custom(v.id,bid,'PENDING',start,start)
            ),'RESERVE_MARKER_FAILED')
            assert(pm:SaveProject(),'SAVE_RESERVATION_FAILED')

            for j,item in ipairs(media) do
                report('IMPORTING','视频 '..i..' / '..count..' · 片段 '..j..' / '..#media,{batch_id=bid,current=i,total=count,video_id=v.id})
                guard()
                log('APPEND video_id='..v.id..' segment_id='..v.parts[j].id..' recordFrame='..finish..' path='..v.parts[j].path)
                local placed=assert(pool:AppendToTimeline({{mediaPoolItem=item,recordFrame=finish,trackIndex=1}}),'APPEND_FAILED')
                local actualEnd=nil
                local transform=v.parts[j].transform
                local transformApplied=false
                for _,clip in ipairs(placed) do
                    assert(number(clip:GetStart(),'actual start')==finish,'INSERT_POSITION_MISMATCH')
                    actualEnd=math.max(actualEnd or finish,number(clip:GetEnd(),'actual end'))
                    if transform and clip:GetProperty('ZoomX')~=nil then
                        for _,key in ipairs({'ZoomX','ZoomY','Pan','Tilt'}) do
                            assert(clip:SetProperty(key,transform[key]),'TRANSFORM_SET_FAILED: '..v.parts[j].id..' '..key)
                            assert(math.abs(number(clip:GetProperty(key),'transform readback')-transform[key])<0.001,'TRANSFORM_VERIFY_FAILED: '..key)
                        end
                        transformApplied=true
                    end
                end
                assert(not transform or transformApplied,'TRANSFORM_VIDEO_CLIP_NOT_FOUND')
                assert(actualEnd and actualEnd>finish,'INSERT_LENGTH_INVALID')
                log('ACTUAL video_id='..v.id..' segment_id='..v.parts[j].id..' start='..finish..' end='..actualEnd)
                finish=actualEnd
                write(base..'/progress.ini',{pending_video=v.id,stage='APPENDED',segment_id=v.parts[j].id,start_frame=start,end_frame=finish})
            end

            assert(timeline:UpdateMarkerCustomData(start-origin,custom(v.id,bid,'COMPLETE',start,finish)),'COMPLETE_MARKER_FAILED')
            assert(pm:SaveProject(),'SAVE_IMPORTED_VIDEO_FAILED')
            write(base..'/progress.ini',{pending_video='',stage='VIDEO_COMPLETE',video_id=v.id,end_frame=finish})

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

        guard()
        assert(pm:SaveProject(),'SAVE_BATCH_FAILED')
        log('IMPORTED append_only added='..result.imported_count..' anchor_end='..tostring(lastEnd or 'NONE')..' gap=50')
        write(base..'/result.ini',result)
        os.remove(lockPath)
    end)

    if previousFolder then pcall(function() pool:SetCurrentFolder(previousFolder) end) end
    if not ok then
        log('ERROR '..tostring(err))
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
