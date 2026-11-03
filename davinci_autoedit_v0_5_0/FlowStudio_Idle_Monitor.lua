local platformSource=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local platform=assert(loadfile(platformSource:match('^(.*)/[^/]+$')..'/FlowStudio_Platform.lua'))()
local os,io=platform.os,platform.io

-- FlowStudio Idle Monitor: detects user-initiated manual rendering inside DaVinci Resolve's
-- Deliver page in real time, publishes live progress to bridge_state.ini, and syncs newly
-- completed MP4 exports back to Flow Studio's database and export_<vid>.ini receipts.

local function renderStatus(value)
    local s=tostring(value or ''):match('^%s*(.-)%s*$')
    local mapped={
        ['完成']='Complete',['已完成']='Complete',
        ['失败']='Failed',['已失败']='Failed',
        ['取消']='Cancelled',['已取消']='Cancelled',
        ['正在渲染']='Rendering',
        ['排队中']='Queued',['等待']='Queued',['准备就绪']='Ready',
        completed='Complete',complete='Complete',
        failed='Failed',cancelled='Cancelled',canceled='Cancelled',
        rendering='Rendering',queued='Queued',ready='Ready',
    }
    return mapped[s] or mapped[s:lower()] or s
end

local function nonempty(path)
    if not path or path=='' then return false end
    local f=io.open(path,'rb')
    if not f then return false end
    local n=f:seek('end')
    f:close()
    return (n and n>0) and true or false
end

local function atomicWritePairs(path, values)
    local rows={}
    for k,v in pairs(values) do
        rows[#rows+1]=tostring(k)..'='..tostring(v):gsub('[\r\n]',' ')
    end
    table.sort(rows)
    local tmp=path..'.tmp'
    local f=assert(io.open(tmp,'w'),'Cannot write '..tostring(path))
    f:write(table.concat(rows,'\n')..'\n')
    f:close()
    assert(os.rename(tmp,path),'Cannot publish '..tostring(path))
end

local function readPairs(path)
    local f=io.open(path,'r')
    local values={}
    if not f then return values end
    for line in f:lines() do
        local k,v=line:match('^([^=]+)=(.*)$')
        if k then values[k]=v end
    end
    f:close()
    return values
end

local function quote(s)
    return "'"..tostring(s):gsub("'","'\\''").."'"
end

local function isValidDayTimeline(day, tlName)
    if type(day)~='string' or type(tlName)~='string' then return false end
    local mainName='MAIN-'..day
    if tlName==mainName then return true end
    local escaped=mainName:gsub('%-','%%-')
    return tlName:match('^'..escaped..'%-B%d+$')~=nil
end

local function resolveJobOutputPath(targetDir, outName)
    targetDir=tostring(targetDir or ''):gsub('[/\\]+$','')
    outName=tostring(outName or '')
    if targetDir=='' or outName=='' then return '' end
    local p=targetDir..'/'..outName
    if not p:lower():match('%.[a-z0-9]+$') then
        if nonempty(p..'.mp4') or not nonempty(p) then
            p=p..'.mp4'
        end
    end
    return p
end

local function isVideoJob(j, timelineName)
    if type(j)~='table' then return false end
    if j.IsExportVideo==false then return false end
    local outName=tostring(j.OutputFilename or '')
    local targetDir=tostring(j.TargetDir or '')
    if outName:lower():match('%.wav$') or targetDir:match('[/\\]audio[/\\]?$') then
        return false
    end
    local jTl=tostring(j.TimelineName or '')
    if jTl~='' and timelineName~='' and jTl~=timelineName then
        return false
    end
    return true
end

local function scanProjectRenderQueue(project, timelineName, completeCache, fullRefresh)
    local okList,rawJobs=pcall(function() return project:GetRenderJobList() end)
    if not okList or type(rawJobs)~='table' then return nil end
    local completed,rendering,waiting={},{},{}
    local failedCount,cancelledCount=0,0
    for _,j in ipairs(rawJobs) do
        if isVideoJob(j, timelineName) then
            local jid=tostring(j.JobId or '')
            local outName=tostring(j.OutputFilename or '')
            local targetDir=tostring(j.TargetDir or '')
            local fullPath=resolveJobOutputPath(targetDir,outName)
            if not fullRefresh and completeCache and jid~='' and completeCache[jid] then
                completed[#completed+1]={job_id=jid,path=completeCache[jid]}
            else
                local okSt,st=pcall(function() return (jid~='' and project:GetRenderJobStatus(jid)) or {} end)
                st=(okSt and type(st)=='table') and st or {}
                local norm=renderStatus(st.JobStatus)
                local pct=math.max(0,math.min(100,math.floor(tonumber(st.CompletionPercentage) or 0)))
                if norm=='Rendering' then
                    if completeCache and jid~='' then completeCache[jid]=nil end
                    rendering[#rendering+1]={job_id=jid,path=fullPath,pct=pct,name=outName}
                elseif norm=='Complete' then
                    if fullPath=='' or nonempty(fullPath) then
                        completed[#completed+1]={job_id=jid,path=fullPath}
                        if completeCache and jid~='' and fullPath~='' then
                            completeCache[jid]=fullPath
                        end
                    end
                elseif norm=='Queued' or norm=='Ready' then
                    if completeCache and jid~='' then completeCache[jid]=nil end
                    waiting[#waiting+1]={job_id=jid,path=fullPath}
                elseif norm=='Failed' then
                    if completeCache and jid~='' then completeCache[jid]=nil end
                    failedCount=failedCount+1
                elseif norm=='Cancelled' then
                    if completeCache and jid~='' then completeCache[jid]=nil end
                    cancelledCount=cancelledCount+1
                end
            end
        end
    end
    return {
        completed=completed,
        rendering=rendering,
        waiting=waiting,
        failed=failedCount,
        cancelled=cancelledCount,
    }
end

local function writeManualRenderSnapshot(root, active, projectName, timelineName, q)
    q=q or {completed={},rendering={},waiting={},failed=0,cancelled=0}
    local activeJob=q.rendering[1]
    local payload={
        active=active and 'true' or 'false',
        updated_at=tostring(os.time()),
        project=tostring(projectName or ''),
        timeline=tostring(timelineName or ''),
        active_job_id=activeJob and activeJob.job_id or '',
        active_path=activeJob and activeJob.path or '',
        active_pct=tostring(activeJob and activeJob.pct or 0),
        q_complete=tostring(#q.completed),
        q_rendering=tostring(#q.rendering),
        q_waiting=tostring(#q.waiting),
        q_failed=tostring(q.failed or 0),
        q_cancelled=tostring(q.cancelled or 0),
        complete_count=tostring(#q.completed),
        rendering_count=tostring(#q.rendering),
        queued_count=tostring(#q.waiting),
    }
    for i,item in ipairs(q.completed) do
        payload['c'..i..'_job_id']=item.job_id or ''
        payload['c'..i..'_path']=item.path or ''
    end
    for i,item in ipairs(q.rendering) do
        payload['r'..i..'_job_id']=item.job_id or ''
        payload['r'..i..'_path']=item.path or ''
    end
    for i,item in ipairs(q.waiting) do
        payload['w'..i..'_job_id']=item.job_id or ''
        payload['w'..i..'_path']=item.path or ''
    end
    local snapPath=root..'/v0_5_0/manual_render.ini'
    atomicWritePairs(snapPath,payload)
    return snapPath,payload
end

local function syncWithPython(root, active, projectName, timelineName, q, testHook)
    local snapPath,payload=writeManualRenderSnapshot(root, active, projectName, timelineName, q)
    if testHook and testHook.onSync then
        return testHook.onSync(payload, snapPath) or {}
    end
    local batchReplyPath=root..'/v0_5_0/manual_render_batch.ini'
    if not platform.windows then
        local pyBin='/Applications/Flow Studio.app/Contents/Resources/python/bin/python3'
        local pyRoot='/Applications/Flow Studio.app/Contents/Resources'
        local f=io.open(pyBin,'rb')
        if f then
            f:close()
            pcall(function()
                local cmd='PYTHONPATH='..quote(pyRoot)..' '..quote(pyBin)..' -m app.services.resolve_finish --sync-manual-render --root '..quote(root)..' 2>/dev/null'
                local h=io.popen(cmd)
                if h then h:read('*a'); h:close() end
            end)
        end
    end
    local res=readPairs(batchReplyPath)
    if res.project==tostring(projectName or '') and res.timeline==tostring(timelineName or '') then
        return res
    end
    return {}
end

local function applyBatchStats(monitorState, res)
    if type(res)~='table' then return end
    monitorState.batchId=tostring(res.batch_id or '')
    monitorState.batchDone=tonumber(res.batch_done) or 0
    monitorState.batchTotal=tonumber(res.batch_total) or 0
    monitorState.newlyExported=tonumber(res.newly_exported) or 0
end

local function tick(getCachedResolve, state, report, publish, root, idleTick, monitorState, testHook)
    monitorState=monitorState or {}
    local okConn,_,pm=pcall(getCachedResolve)
    if not okConn or not pm then return false end
    local okProj,project=pcall(function() return pm:GetCurrentProject() end)
    if not okProj or not project then return false end
    local okProg,inProgress=pcall(function() return project:IsRenderingInProgress() end)
    inProgress=(okProg and inProgress) and true or false

    if inProgress then
        local okName,projectName=pcall(function() return project:GetName() end)
        projectName=(okName and projectName) or ''
        local okTl,tl=pcall(function() return project:GetCurrentTimeline() end)
        local timelineName=(okTl and tl and tl:GetName()) or state.timeline or ''

        local justStarted=not monitorState.wasRendering
        if justStarted then
            monitorState.preStage=state.stage
            monitorState.preProject=state.project
            monitorState.preTimeline=state.timeline
            monitorState.sessionComplete={}
            monitorState.renderTicks=0
            monitorState.batchId=''
            monitorState.batchDone=0
            monitorState.batchTotal=0
        end
        monitorState.renderTicks=(monitorState.renderTicks or 0)+1
        local fullRefresh=justStarted or (monitorState.renderTicks%5==0)
        local q=scanProjectRenderQueue(project, timelineName, monitorState.sessionComplete, fullRefresh)
        local qComplete=q and #q.completed or 0
        local qRendering=q and #q.rendering or 0
        local qWaiting=q and #q.waiting or 0
        local activeJob=q and q.rendering[1] or nil
        local activePct=activeJob and activeJob.pct or 0
        if justStarted then
            monitorState.initialComplete=qComplete
        end

        local needSync=justStarted
            or (qComplete~=monitorState.lastComplete)
            or ((qRendering+qWaiting)~=monitorState.lastPending)
            or (projectName~=monitorState.lastProject)
            or (timelineName~=monitorState.lastTimeline)

        if needSync and q then
            local res=syncWithPython(root, true, projectName, timelineName, q, testHook)
            applyBatchStats(monitorState, res)
            monitorState.lastComplete=qComplete
            monitorState.lastPending=qRendering+qWaiting
            monitorState.lastProject=projectName
            monitorState.lastTimeline=timelineName
        elseif not platform.windows then
            -- Refresh cached stats if Python updated manual_render_batch.ini in background.
            local res=readPairs(root..'/v0_5_0/manual_render_batch.ini')
            if res.project==projectName and res.timeline==timelineName then
                applyBatchStats(monitorState, res)
            end
        else
            local res=readPairs(root..'/v0_5_0/manual_render_batch.ini')
            if res.project==projectName and res.timeline==timelineName then
                applyBatchStats(monitorState, res)
            end
        end

        local bTotal=tonumber(monitorState.batchTotal) or 0
        local bDone=tonumber(monitorState.batchDone) or 0
        local runDone=math.max(0,qComplete-(tonumber(monitorState.initialComplete) or 0))
        local runScope=runDone+qRendering+qWaiting
        local curNum,totNum,detail
        if bTotal>0 then
            curNum,totNum=bDone,bTotal
            if runScope>0 and (runScope~=bTotal or bDone~=runDone) then
                detail=string.format('⟳ 正在达芬奇手动渲染导出：本轮 %d / %d · 整批 %d / %d（当前 %d%%）',runDone,runScope,bDone,bTotal,activePct)
            else
                detail=string.format('⟳ 正在达芬奇手动渲染导出：已完成 %d / %d（当前视频 %d%%）',bDone,bTotal,activePct)
            end
        else
            totNum=math.max(1,runScope)
            curNum=runDone
            detail=string.format('⟳ 正在达芬奇手动渲染导出：已完成 %d / %d（当前视频 %d%%）',curNum,totNum,activePct)
        end

        monitorState.wasRendering=true
        local fields={
            manual_render='true',
            current=tostring(curNum),
            total=tostring(totNum),
            project=projectName,
            timeline=timelineName,
        }
        if monitorState.batchId and monitorState.batchId~='' then
            fields.batch_id=monitorState.batchId
        end
        if needSync then
            report('RENDERING', detail, fields)
        else
            for k,v in pairs(fields) do state[k]=v end
            state.stage='RENDERING'
            state.detail=detail
            publish()
        end
        return true
    end

    if monitorState.wasRendering then
        local okName,projectName=pcall(function() return project:GetName() end)
        projectName=(okName and projectName) or monitorState.lastProject or ''
        local okTl,tl=pcall(function() return project:GetCurrentTimeline() end)
        local timelineName=(okTl and tl and tl:GetName()) or monitorState.lastTimeline or state.timeline or ''

        local q=scanProjectRenderQueue(project, timelineName, nil, true)
        local qComplete=q and #q.completed or 0
        local qTotal=q and (#q.completed+#q.rendering+#q.waiting+(q.failed or 0)+(q.cancelled or 0)) or 0
        if q then
            local res=syncWithPython(root, false, projectName, timelineName, q, testHook)
            applyBatchStats(monitorState, res)
        end

        local bTotal=tonumber(monitorState.batchTotal) or 0
        local bDone=tonumber(monitorState.batchDone) or 0
        local dayMatch=projectName:match('^FlowStudio%-(%d%d%d%d%-%d%d%-%d%d)$')
        local nextStage='IDLE'
        if dayMatch and isValidDayTimeline(dayMatch, timelineName) then
            nextStage='READY'
        elseif monitorState.preStage=='READY' and monitorState.preProject==projectName and monitorState.preTimeline==timelineName then
            nextStage='READY'
        end

        local detail
        local labelTl=timelineName~='' and timelineName or projectName
        if bTotal>0 and bDone>=bTotal then
            detail=string.format('✓ 达芬奇手动渲染完成：整批 %d / %d 条已全部导出（%s）',bDone,bTotal,labelTl)
        elseif bTotal>0 then
            detail=string.format('达芬奇手动渲染已停止：当前批次已导出 %d / %d（%s）',bDone,bTotal,labelTl)
        else
            detail=string.format('✓ 达芬奇手动渲染已结束：已完成 %d 条（%s）',qComplete,labelTl)
        end

        monitorState.wasRendering=false
        monitorState.sessionComplete=nil
        monitorState.lastIdleCompleteCount=qComplete
        monitorState.lastIdleProject=projectName
        monitorState.lastIdleTimeline=timelineName

        local outFields={
            manual_render='false',
            current=tostring(bTotal>0 and bDone or qComplete),
            total=tostring(bTotal>0 and bTotal or math.max(1,qTotal)),
        }
        if nextStage=='READY' then
            outFields.project=projectName
            outFields.timeline=timelineName
        end
        if monitorState.batchId and monitorState.batchId~='' then
            outFields.batch_id=monitorState.batchId
        end
        report(nextStage, detail, outFields)
        return false
    end

    -- Lightweight background reconciliation (boot + every 15s) in case short clips finished
    -- between ticks or were manually rendered before Bridge connected.
    if (not monitorState.bootSynced) or ((tonumber(idleTick) or 0)%15==0) then
        local okName,projectName=pcall(function() return project:GetName() end)
        projectName=(okName and projectName) or ''
        local dayMatch=projectName:match('^FlowStudio%-(%d%d%d%d%-%d%d%-%d%d)$')
        if dayMatch then
            local okTl,tl=pcall(function() return project:GetCurrentTimeline() end)
            local timelineName=(okTl and tl and tl:GetName()) or ''
            monitorState.idleCompleteCache=monitorState.idleCompleteCache or {}
            local q=scanProjectRenderQueue(project, timelineName, monitorState.idleCompleteCache, not monitorState.bootSynced)
            monitorState.bootSynced=true
            local qComplete=q and #q.completed or 0
            if q and qComplete>0 and (
                qComplete~=monitorState.lastIdleCompleteCount
                or projectName~=monitorState.lastIdleProject
                or timelineName~=monitorState.lastIdleTimeline
            ) then
                monitorState.lastIdleCompleteCount=qComplete
                monitorState.lastIdleProject=projectName
                monitorState.lastIdleTimeline=timelineName
                local res=syncWithPython(root, false, projectName, timelineName, q, testHook)
                applyBatchStats(monitorState, res)
                local newly=tonumber(monitorState.newlyExported) or 0
                local bTotal=tonumber(monitorState.batchTotal) or 0
                local bDone=tonumber(monitorState.batchDone) or 0
                if newly>0 and bTotal>0 then
                    local nextStage=(state.stage=='ERROR' and isValidDayTimeline(dayMatch, timelineName)) and 'READY' or state.stage
                    local msg=(bDone>=bTotal)
                        and string.format('✓ 已同步达芬奇手动渲染成品：整批 %d / %d 条已全部导出（%s）',bDone,bTotal,timelineName)
                        or string.format('✓ 已同步达芬奇手动渲染新增 %d 条：当前批次已导出 %d / %d（%s）',newly,bDone,bTotal,timelineName)
                    report(nextStage, msg, {
                        manual_render='false',
                        current=tostring(bDone),
                        total=tostring(bTotal),
                        project=projectName,
                        timeline=timelineName,
                    })
                end
            end
        else
            monitorState.bootSynced=true
        end
    end

    return false
end

return {
    tick=tick,
    renderStatus=renderStatus,
    scanProjectRenderQueue=scanProjectRenderQueue,
}
