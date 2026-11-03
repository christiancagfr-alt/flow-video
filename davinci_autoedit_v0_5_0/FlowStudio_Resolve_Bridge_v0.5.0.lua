local platformSource=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local platform=assert(loadfile(platformSource:match('^(.*)/[^/]+$')..'/FlowStudio_Platform.lua'))()
local os,io,loadfile=platform.os,platform.io,platform.loadfile
if jit and jit.off then pcall(jit.off) end
-- FlowStudio Bridge v0.5.0 / phase 1: internal Resolve Lua only.
-- File command/heartbeat architecture retained from v0.4.5.3.
-- Original AutoEditing, Cleanup and Export algorithms remain untouched.
-- Acquire inside Resolve, never from an external Python process.
local function acquireResolve(env)
    env = env or _G
    local factories = {
        function() return env.bmd and env.bmd.scriptapp and env.bmd.scriptapp('Resolve') end,
        function() return env.fu and env.fu:GetResolve() end,
        function() return env.fusion and env.fusion:GetResolve() end,
        function() return type(env.Resolve)=='function' and env.Resolve() end,
        function() return env.resolve end,
    }
    for _,factory in ipairs(factories) do
        local ok, candidate = pcall(factory)
        if ok and candidate then
            -- A Fusion object can have GetVersionString but no GetProjectManager.
            local valid, manager = pcall(function() return candidate:GetProjectManager() end)
            if valid and manager then return candidate, manager end
        end
    end
    error('RESOLVE_NOT_READY: 无法取得 Resolve 项目管理器，请等待达芬奇初始化后重新唤醒')
end
local function isValidDayTimeline(day, tlName)
    if type(day)~='string' or type(tlName)~='string' then return false end
    local mainName = 'MAIN-' .. day
    if tlName == mainName then return true end
    local escaped = mainName:gsub('%-', '%%-')
    return tlName:match('^' .. escaped .. '%-B%d+$') ~= nil
end
local function prepareDaily(resolve, job, report)
    local day = job.work_date
    assert(type(day)=='string' and day:match('^%d%d%d%d%-%d%d%-%d%d$'),'INVALID_DATE')
    local fps = tonumber(job.timeline_fps)
    local allowed = {[23.976]=true,[24]=true,[25]=true,[29.97]=true,[30]=true,[50]=true,[59.94]=true,[60]=true}
    if not allowed[fps] then error('INVALID_FPS: 请检查 Flow Studio 系统设置') end
    local pm = assert(resolve:GetProjectManager(), 'PROJECT_MANAGER_UNAVAILABLE')
    local projectName = 'FlowStudio-' .. day
    local timelineName = (type(job.timeline_name)=='string' and job.timeline_name~='') and job.timeline_name or ('MAIN-' .. day)
    assert(isValidDayTimeline(day, timelineName), 'INVALID_TIMELINE_NAME: ' .. tostring(timelineName))
    report('PREPARING_PROJECT', '准备所选日期项目：'..day..'（'..timelineName..'）')
    local project = pm:GetCurrentProject()
    local created = false
    local switchedProject = false
    if not project or project:GetName() ~= projectName then
        switchedProject = true
        if project then
            -- SaveProject on an unsaved startup project opens a blocking Save As dialog.
            local listed = assert(pm:GetProjectListInCurrentFolder(), 'PROJECT_LIST_UNAVAILABLE')
            local persisted = false
            for _,name in ipairs(listed) do if name==project:GetName() then persisted=true end end
            if persisted then
                if not pm:SaveProject() then error('SAVE_PROJECT_FAILED: 无法保存当前项目，停止切换') end
            else
                local function emptyFolder(folder)
                    if not folder then return false end
                    local clips, children = folder:GetClipList(), folder:GetSubFolderList()
                    if not clips or not children then return false end
                    -- Resolve RPC lists carry __flags even when they contain no items.
                    -- Ignore only known transport metadata; unknown entries stay protective.
                    for key in pairs(clips) do
                        if key~='__flags' then return false end
                    end
                    for key,child in pairs(children) do
                        if key~='__flags' and not emptyFolder(child) then return false end
                    end
                    return true
                end
                local name=project:GetName()
                local unnamed=name=='' or name=='Untitled Project' or name=='Untitled' or name=='未命名项目' or name=='无标题项目'
                local pool=project:GetMediaPool()
                if not unnamed or project:GetTimelineCount()~=0 or not pool or not emptyFolder(pool:GetRootFolder()) then
                    error('UNSAVED_PROJECT: 当前项目未保存，且不是可安全切换的空白启动项目。请先手动保存，再唤醒')
                end
                -- Unsaved startup placeholder cannot be closed via CloseProject.
                -- Once proven empty, let LoadProject/CreateProject switch directly.
            end
        end
        if not pm:GotoRootFolder() then error('PROJECT_ROOT_UNAVAILABLE') end
        -- A failed load must never be mistaken for a missing project.
        local names = pm:GetProjectListInCurrentFolder()
        if not names then error('PROJECT_LIST_UNAVAILABLE') end
        local exists = false
        for _, name in ipairs(names) do if name == projectName then exists = true end end
        if exists then
            project = pm:LoadProject(projectName)
            if not project then error('LOAD_PROJECT_FAILED: ' .. projectName) end
        else
            project = pm:CreateProject(projectName)
            created = true
            if not project then error('CREATE_PROJECT_FAILED: ' .. projectName) end
        end
    end
    if created then
        for _, pair in ipairs({{'timelineResolutionWidth','720'}, {'timelineResolutionHeight','1280'}, {'timelineFrameRate',job.timeline_fps}}) do
            if not project:SetSetting(pair[1], pair[2]) then error('PROJECT_SETTING_FAILED: ' .. pair[1]) end
        end
    end
    -- Low-RAM runtime optimization: disable background render/optimised/proxy caches (zero impact on final MP4 export or QC transforms).
    if created or switchedProject then
        pcall(function()
            project:SetSetting('perfAutoRenderCacheEnable', '0')
            project:SetSetting('perfRenderCacheMode', 'none')
            project:SetSetting('perfOptimisedMediaOn', '0')
            project:SetSetting('perfProxyMediaMode', '0')
        end)
    end
    report('PREPARING_TIMELINE', '准备时间线：'..timelineName)
    local timeline = nil
    local timelineCreated = false
    local switchedTimeline = false
    for i=1,project:GetTimelineCount() do
        local candidate = project:GetTimelineByIndex(i)
        if not candidate then error('TIMELINE_READ_FAILED') end
        if candidate:GetName() == timelineName then
            if timeline then error('DUPLICATE_MAIN_TIMELINE: 检测到同名主时间线，停止操作') end
            timeline = candidate
        end
    end
    if not timeline then
        timeline = project:GetMediaPool():CreateEmptyTimeline(timelineName)
        if not timeline then error('CREATE_TIMELINE_FAILED: ' .. timelineName) end
        timelineCreated = true
        -- Existing projects may still have 1080x1920 defaults. Only the newly
        -- created timeline receives an override; existing timelines are retained.
        assert(timeline:SetSetting('useCustomSettings','1'),'TIMELINE_CUSTOM_SETTINGS_FAILED')
        for _,pair in ipairs({{'timelineResolutionWidth','720'},{'timelineResolutionHeight','1280'}}) do
            assert(timeline:SetSetting(pair[1],pair[2]),'TIMELINE_RESOLUTION_FAILED: '..pair[1])
            assert(tonumber(timeline:GetSetting(pair[1]))==tonumber(pair[2]),'TIMELINE_RESOLUTION_NOT_CONFIRMED')
        end
        pcall(function()
            if timeline:GetTrackCount('subtitle') == 0 then
                timeline:AddTrack('subtitle')
            end
        end)
    end
    local curTl = project.GetCurrentTimeline and project:GetCurrentTimeline() or nil
    if not curTl or curTl:GetName() ~= timelineName then
        if not project:SetCurrentTimeline(timeline) then error('SET_TIMELINE_FAILED') end
        switchedTimeline = true
    end
    report('VALIDATING', '检查项目及时间线参数')
    local warnings = {}
    local function numPrefix(v)
        local n = tonumber(v)
        if n then return n end
        local m = tostring(v or ''):match('([%d%.]+)')
        return m and tonumber(m) or nil
    end
    for _, pair in ipairs({{'timelineResolutionWidth',720}, {'timelineResolutionHeight',1280}, {'timelineFrameRate',fps}}) do
        local key, wanted = pair[1], pair[2]
        local projectValue = numPrefix(project:GetSetting(key))
        local customTl = tostring(timeline:GetSetting('useCustomSettings') or '') == '1'
        local timelineValue = customTl and numPrefix(timeline:GetSetting(key)) or (numPrefix(timeline:GetSetting(key)) or projectValue)
        if not projectValue or math.abs(projectValue-wanted)>0.001 then
            warnings[#warnings+1] = '项目 ' .. key .. ' 与设置不一致（期望 ' .. wanted .. '），已保留原参数'
        end
        if not timelineValue or math.abs(timelineValue-wanted)>0.001 then
            warnings[#warnings+1] = '时间线 ' .. key .. ' 与设置不一致（期望 ' .. wanted .. '），已保留原参数'
        end
    end
    local active=pm:GetCurrentProject()
    if not active or active:GetName()~=projectName then error('PROJECT_SWITCH_NOT_CONFIRMED') end
    local presetsModified = false
    if not FLOWSTUDIO_DAILY_TEST and not _G.__FLOWSTUDIO_WAV16_VERIFIED then
        pcall(function()
            local presetFlag=(os.getenv('HOME') or '')..'/Documents/FlowStudioResolveBridge/v0_5_0/wav_preset_verified.ini'
            local pf=io.open(presetFlag,'r')
            if pf then
                pf:close()
                _G.__FLOWSTUDIO_WAV16_VERIFIED=true
                return
            end
            if project.LoadRenderPreset and project.SetCurrentRenderFormatAndCodec and project.SaveAsNewRenderPreset and not project:IsRenderingInProgress() then
                local wavReady=project:LoadRenderPreset('FlowStudio_WAV16')
                if not wavReady then
                    pcall(function() return project:LoadRenderPreset('Audio Only') or project:LoadRenderPreset('仅音频') end)
                    local wavOk=false
                    if project.GetRenderFormats and project.GetRenderCodecs then
                        local okF,fmts=pcall(function() return project:GetRenderFormats() end)
                        if okF and type(fmts)=='table' then
                            for fmtName,ext in pairs(fmts) do
                                local fn,ex=tostring(fmtName or ''):lower(),tostring(ext or ''):lower()
                                if ex=='wav' or ex=='.wav' or fn=='wav' or fn=='wave' then
                                    local okC,codecs=pcall(function() return project:GetRenderCodecs(fmtName) end)
                                    if okC and type(codecs)=='table' then
                                        for desc,cName in pairs(codecs) do
                                            if tostring(cName or ''):lower():find('pcm',1,true) or tostring(desc or ''):lower():find('pcm',1,true) then
                                                if project:SetCurrentRenderFormatAndCodec(fmtName,cName) then wavOk=true;break end
                                            end
                                        end
                                    end
                                    if wavOk then break end
                                end
                            end
                        end
                    end
                    if not wavOk then
                        for _,pair in ipairs({{'wav','LinearPCM'},{'wav','lpcm'},{'Wave','LinearPCM'},{'Wave','lpcm'}}) do
                            if project:SetCurrentRenderFormatAndCodec(pair[1],pair[2]) then wavOk=true;break end
                        end
                    end
                    if wavOk then
                        pcall(function() project:SetCurrentRenderMode(1) end)
                        pcall(function() project:SetRenderSettings({ExportVideo=false,ExportAudio=true,AudioBitDepth=16,AudioSampleRate=48000,ExportSubtitle=false}) end)
                        pcall(function() project:SaveAsNewRenderPreset('FlowStudio_WAV16') end)
                        wavReady=true
                        presetsModified=true
                    end
                end
                if not (project:LoadRenderPreset('FlowStudio_Final') or project:LoadRenderPreset('H.264 Master')) then
                    if project:SetCurrentRenderFormatAndCodec('mp4','H264') then
                        pcall(function() project:SetCurrentRenderMode(1) end)
                        pcall(function() project:SetRenderSettings({ExportVideo=true,ExportAudio=true,AudioCodec='aac',AudioSampleRate=48000}) end)
                        pcall(function() project:SaveAsNewRenderPreset('FlowStudio_Final') end)
                        presetsModified=true
                    end
                end
                if wavReady then
                    _G.__FLOWSTUDIO_WAV16_VERIFIED=true
                    local wf=io.open(presetFlag,'w')
                    if wf then wf:write('verified=1\n');wf:close() end
                end
            end
        end)
    end
    if FLOWSTUDIO_DAILY_TEST or created or timelineCreated or switchedTimeline or presetsModified then
        if not pm:SaveProject() then error('SAVE_PROJECT_FAILED') end
    end
    return {project=projectName, timeline=timelineName, timeline_created=tostring(timelineCreated), project_created=tostring(created), warning=table.concat(warnings, '; '), timeline_fps=job.timeline_fps}
end

-- Test harness returns only the pure preparation function; no application connection.
if FLOWSTUDIO_DAILY_TEST then return prepareDaily, acquireResolve end

local home = assert(os.getenv('HOME'), 'HOME unavailable')
local root = home .. '/Documents/FlowStudioResolveBridge'
local inbox = root .. '/v0_5_0/commands'
local stateFile = root .. '/bridge_state.ini'
local lockDir = root .. '/v0_5_0/instance.lock'
local function quote(s) return "'" .. tostring(s):gsub("'", "'\\''") .. "'" end
local function runOK(cmd)
    local a, _, c = os.execute(cmd)
    return a == 0 or a == true and (c == nil or c == 0)
end
local function readPairs(path)
    local f = io.open(path, 'r'); local values = {}
    if not f then return values end
    for line in f:lines() do
        local k,v = line:match('^([^=]+)=(.*)$'); if k then values[k] = v end
    end
    f:close(); return values
end
local function atomicWrite(path, text)
    local f = assert(io.open(path .. '.tmp', 'w'), 'Cannot write ' .. path)
    f:write(text or ''); f:close()
    assert(os.rename(path .. '.tmp', path), 'Cannot publish ' .. path)
end
local function exists(path) local f=io.open(path,'r'); if f then f:close(); return true end; return false end
local dirs = {inbox, root..'/v0_5_0/done', root..'/v0_5_0/error', root..'/v0_5_0/suspended', root..'/logs'}
for _,dir in ipairs(dirs) do assert(runOK('mkdir -p '..quote(dir)), 'Cannot create '..dir) end
-- Manual Workspace launches must also refuse a live legacy bridge.
local legacyHeartbeat = io.open(root..'/bridge_heartbeat.txt','r')
if legacyHeartbeat then
    local value = legacyHeartbeat:read('*a'); legacyHeartbeat:close()
    if not tonumber(value) then
        local stat = io.popen('/usr/bin/stat -f %m '..quote(root..'/bridge_heartbeat.txt'))
        local stamp = stat and tonumber(stat:read('*l'))
        if stat then stat:close() end
        if stamp and os.time()-stamp<30 then
            error('LEGACY_BRIDGE_RUNNING: 请先停止旧版 Bridge，新版未启动')
        end
    end
end
local old = readPairs(stateFile)
local age = os.time() - (tonumber(old.updated_at) or 0)
-- A Resolve API call can block longer than a few seconds. 30s avoids a second Bridge during that gap.
if old.version == '0.5.0' and old.stage~='OFFLINE' and age >= 0 and age < 30 then
    print('[FlowStudio] Bridge 已在线，不重复启动'); return
end
-- Reclaim only an expired instance directory; mkdir remains the exclusive acquisition.
if not runOK('mkdir '..quote(lockDir)..' 2>/dev/null') then
    -- Recheck the lease after losing mkdir: another script may just have started.
    local fresh = readPairs(stateFile)
    local leaseAge = os.time() - (tonumber(fresh.updated_at) or 0)
    local stat = io.popen('/usr/bin/stat -f %m '..quote(lockDir))
    local lockTime = stat and tonumber(stat:read('*l')) or os.time()
    if stat then stat:close() end
    if (fresh.version=='0.5.0' and fresh.stage~='OFFLINE' and leaseAge>=0 and leaseAge<30) or os.time()-(lockTime or os.time())<30 then
        print('[FlowStudio] Bridge 正在启动，不重复启动'); return
    end
    local importing=readPairs(root..'/pipeline.lock')
    local resumable=importing.action=='FINISH_BATCH' or importing.stage=='WAITING_USER_REVIEW' or importing.stage=='ANALYSIS_ERROR' or importing.stage=='CUTTING_ERROR' or importing.stage=='IMPORT_ERROR'
    if resumable then
        local connected,app=pcall(acquireResolve)
        local project=connected and app:GetProjectManager():GetCurrentProject()
        if project and project:IsRenderingInProgress() then error('RENDER_STILL_RUNNING: 达芬奇仍在渲染，请等待结束后重新唤醒') end
    end
    if not runOK('rmdir '..quote(lockDir)..' 2>/dev/null') or not runOK('mkdir '..quote(lockDir)..' 2>/dev/null') then
        error('BRIDGE_LOCKED: Bridge 启动锁被占用')
    end
end
local state = {version='0.5.0',build='V0.13.5.67',capabilities='PREPARE_DAILY,IMPORT_BATCH,START_AUTOEDIT,RESUME_AUTOEDIT,FINISH_BATCH',stage='IDLE',detail='Bridge 在线，等待唤醒',whisper_language='sw'}
local function log(message)
    local f=assert(io.open(root..'/logs/bridge.log','a'))
    f:write(os.date('%Y-%m-%d %H:%M:%S') .. ' version=0.5.0 ' .. tostring(message) .. '\n'); f:close()
end
local function publish()
    state.updated_at = tostring(os.time())
    local rows={}
    for k,v in pairs(state) do rows[#rows+1]=k..'='..tostring(v):gsub('[\r\n]', ' ') end
    table.sort(rows)
    atomicWrite(stateFile,table.concat(rows,'\n')..'\n')
    atomicWrite(root..'/bridge_heartbeat.txt',state.updated_at)
    atomicWrite(root..'/bridge_status.txt',state.stage..' | '..state.detail)
end
local function report(stage, detail, fields)
    for k,v in pairs(fields or {}) do state[k]=v end
    state.stage, state.detail = stage, detail
    publish(); log('request='..(state.request_id or '')..' stage='..stage..' '..detail)
end
local ok, err = pcall(function()
    -- Resolve provides this object to scripts invoked from Workspace -> Scripts.
    local app
    state.resolve_version = 'pending'
    log('START Resolve='..state.resolve_version)
    report('IDLE', 'Bridge 在线，等待唤醒')
    local lostChecks=0
    local cachedResolve, cachedPM = nil, nil
    local function getCachedResolve()
        if cachedResolve and cachedPM then
            local ok = pcall(function() return cachedResolve:GetVersionString() end)
            if ok then return cachedResolve, cachedPM end
        end
        cachedResolve, cachedPM = acquireResolve()
        return cachedResolve, cachedPM
    end
    local idleTick=0
    local monitorState={}
    local okMon, idleMonitor = pcall(function()
        return assert(loadfile(platform.directory..'/FlowStudio_Idle_Monitor.lua'))()
    end)
    while not exists(root..'/v0_5_0/STOP') do
        -- Publish before the Resolve call so a slow or briefly failing API does not look offline.
        publish()
        local linked=pcall(getCachedResolve)
        lostChecks=linked and 0 or lostChecks+1
        if lostChecks>=15 then
            report('OFFLINE','达芬奇连接已失效，旧 Bridge 已退出；请重新唤醒')
            return
        end
        publish()
        local manualRendering=false
        if linked and okMon and idleMonitor and idleMonitor.tick then
            local mOk, mActive = pcall(idleMonitor.tick, getCachedResolve, state, report, publish, root, idleTick, monitorState)
            manualRendering = (mOk and mActive) and true or false
        end
        local paths={}
        if not manualRendering then
            local p=assert(io.popen('find '..quote(inbox)..' -maxdepth 1 -type f -name "*.job" -print | sort'))
            for path in p:lines() do paths[#paths+1]=path end; p:close()
        end
        for _,path in ipairs(paths) do
            local job=readPairs(path)
            state.request_id=job.request_id or ''
            state.warning=''
            local success, result=pcall(function()
                if job.action~='PREPARE_DAILY' and job.action~='IMPORT_BATCH' and job.action~='START_AUTOEDIT' and job.action~='FINISH_BATCH' then error('UNSUPPORTED_ACTION') end
                if not state.request_id:match('^[a-f0-9]+$') then error('INVALID_REQUEST_ID') end
                app = getCachedResolve()
                local versionOK, version = pcall(function() return app:GetVersionString() end)
                state.resolve_version = versionOK and tostring(version) or 'unknown'
                if job.action=='IMPORT_BATCH' then
                    state.batch_id=job.batch_id or ''
                    local path=platform.directory..'/FlowStudio_Import_Batch.lua'
                    local importBatch=assert(loadfile(path),'IMPORT_MODULE_MISSING')()
                    local r=importBatch(app,job,report)
                    collectgarbage('collect')
                    return r
                end
                if job.action=='FINISH_BATCH' then
                    local module=assert(loadfile(platform.directory..'/FlowStudio_Finish_Batch.lua'))()
                    local r=module.run(app,job,report)
                    collectgarbage('collect')
                    return r
                end
                if job.action=='START_AUTOEDIT' then
                    state.batch_id=job.batch_id or ''
                    local path=platform.directory..'/Autoediting_V1.7_FlowStudio.lua'
                    local module=assert(loadfile(path),'AUTOEDIT_MODULE_MISSING')()
                    local r=module.run(app,job,report)
                    collectgarbage('collect')
                    return r
                end
                local pipelinePath=root..'/pipeline.lock'
                local suspendedDir=root..'/v0_5_0/suspended'
                local pipeline=readPairs(pipelinePath)
                -- Older import-error locks did not persist work_date. Recover it from
                -- the durable batch manifest so a historical batch never blocks today.
                if pipeline.batch_id and (not pipeline.work_date or pipeline.work_date=='') then
                    local manifest=readPairs(root..'/v0_5_0/batches/'..pipeline.batch_id..'/manifest.ini')
                    if manifest.work_date then pipeline.work_date=manifest.work_date end
                end
                -- Park another date's lock and restore the selected date's lock when switching history/today.
                if pipeline.action and pipeline.work_date and pipeline.work_date~=job.work_date then
                    if pipeline.work_date:match('^%d%d%d%d%-%d%d%-%d%d$') then
                        local parked=suspendedDir..'/pipeline_'..pipeline.work_date..'.ini'
                        os.remove(parked)
                        os.rename(pipelinePath,parked)
                    else
                        os.remove(pipelinePath)
                    end
                    pipeline={}
                end
                local selected=suspendedDir..'/pipeline_'..job.work_date..'.ini'
                if not pipeline.action and exists(selected) then
                    os.rename(selected,pipelinePath)
                    pipeline=readPairs(pipelinePath)
                end
                local prepared=prepareDaily(app,job,report)
                if prepared.timeline_created=='true' then
                    -- Durable receipt scoped to the exact timeline name so creating B2/B3 never invalidates B1.
                    atomicWrite(root..'/v0_5_0/rebuild_'..prepared.timeline..'.ini',
                        'rebuild_id='..job.request_id..'\nwork_date='..job.work_date..'\nproject='..prepared.project..'\ntimeline='..prepared.timeline..'\n')
                    if pipeline.batch_id and pipeline.work_date==job.work_date then
                        local pManifest=readPairs(root..'/v0_5_0/batches/'..pipeline.batch_id..'/manifest.ini')
                        if (pManifest.timeline_name or ('MAIN-'..job.work_date))==prepared.timeline then
                            assert(os.rename(root..'/pipeline.lock',root..'/logs/pipeline_before_rebuild_'..job.request_id..'.ini'),'ARCHIVE_OLD_PIPELINE_FAILED')
                        end
                    end
                end
                return prepared
            end)
            if success then
                for k,v in pairs(result) do state[k]=v end
                report(result.stage or 'READY',job.action=='FINISH_BATCH' and (result.detail or '批次导出完成，成品记录已保留') or job.action=='START_AUTOEDIT' and '自动剪辑完成，等待人工检查；未执行清理或导出' or job.action=='IMPORT_BATCH' and ('剪辑素材导入完成 · 新增 '..tostring(result.imported_count)..' · 已存在跳过 '..tostring(result.skipped_count)) or ('达芬奇已就绪（'..tostring(result.timeline or '')..'）'))
            else
                local rawErr=tostring(result or '')
                local cleanErr=rawErr:gsub('%.%.%.[^:%s]*%.lua:%d+:%s*',''):gsub('/[^:%s]*%.lua:%d+:%s*','')
                if #cleanErr>180 then cleanErr=cleanErr:sub(1,180)..'…' end
                report('ERROR',cleanErr)
                atomicWrite(root..'/v0_5_0/error/'..(path:match('([^/]+)$'))..'.txt',rawErr)
            end
            assert(os.rename(path,root..'/v0_5_0/'..(success and 'done/' or 'error/')..path:match('([^/]+)$')))
            monitorState.bootSynced=false
        end
        -- Auto-recover READY status if the batch that produced a stale ERROR was manually closed/skipped by the user.
        if state.stage=='ERROR' and state.batch_id and state.batch_id~='' and exists(root..'/v0_5_0/batches/'..state.batch_id..'/manual_close.ini') then
            local connected, manager = pcall(function() local _, pm = getCachedResolve(); return pm end)
            local project=connected and manager:GetCurrentProject()
            local timeline=project and project:GetCurrentTimeline()
            if project and timeline then
                state.project=project:GetName()
                state.timeline=timeline:GetName()
                report('READY','达芬奇已就绪（'..tostring(state.timeline)..'）')
            end
        end
        -- Detect manual project / timeline changes while idle; READY must be truthful.
        idleTick=idleTick+1
        if state.stage=='READY' and idleTick%5==0 then
            local connected, manager = pcall(function() local _, pm = getCachedResolve(); return pm end)
            local project=connected and manager:GetCurrentProject()
            local timeline=project and project:GetCurrentTimeline()
            if not project or project:GetName()~=state.project or not timeline or timeline:GetName()~=state.timeline then
                report('IDLE','当前项目或时间线已切换，请再次唤醒达芬奇')
            end
        end
        if idleTick%30==0 then collectgarbage('collect') end
        if platform.windows then
            os.execute('/bin/sleep 1')
        else
            for _=1,3 do
                os.execute('/bin/sleep 0.33')
                if exists(root..'/v0_5_0/STOP') then break end
                local quick=io.popen('find '..quote(inbox)..' -maxdepth 1 -type f -name "*.job" -print -quit 2>/dev/null')
                local hasJob=quick and quick:read('*l')
                if quick then quick:close() end
                if hasJob and hasJob~='' then break end
            end
        end
    end
    os.remove(root..'/v0_5_0/STOP')
    report('OFFLINE','Bridge 已停止')
end)
if not ok then pcall(report,'OFFLINE',tostring(err)) end
runOK('rmdir '..quote(lockDir)..' 2>/dev/null')
if not ok then error(err) end
