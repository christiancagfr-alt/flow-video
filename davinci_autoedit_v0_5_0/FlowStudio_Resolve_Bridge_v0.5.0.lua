local platformSource=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local platform=assert(loadfile(platformSource:match('^(.*)/[^/]+$')..'/FlowStudio_Platform.lua'))()
local os,io,loadfile=platform.os,platform.io,platform.loadfile
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
local function prepareDaily(resolve, job, report)
    local day = job.work_date
    assert(type(day)=='string' and day:match('^%d%d%d%d%-%d%d%-%d%d$'),'INVALID_DATE')
    local fps = tonumber(job.timeline_fps)
    local allowed = {[23.976]=true,[24]=true,[25]=true,[29.97]=true,[30]=true,[50]=true,[59.94]=true,[60]=true}
    if not allowed[fps] then error('INVALID_FPS: 请检查 Flow Studio 系统设置') end
    local pm = assert(resolve:GetProjectManager(), 'PROJECT_MANAGER_UNAVAILABLE')
    local projectName, timelineName = 'FlowStudio-' .. day, 'MAIN-' .. day
    report('PREPARING_PROJECT', '准备所选日期项目：'..day)
    local project = pm:GetCurrentProject()
    local created = false
    if not project or project:GetName() ~= projectName then
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
    report('PREPARING_TIMELINE', '准备所选日期主时间线：'..day)
    local timeline = nil
    local timelineCreated = false
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
    end
    if not project:SetCurrentTimeline(timeline) then error('SET_TIMELINE_FAILED') end
    report('VALIDATING', '检查项目及时间线参数')
    local warnings = {}
    for _, pair in ipairs({{'timelineResolutionWidth',720}, {'timelineResolutionHeight',1280}, {'timelineFrameRate',fps}}) do
        local key, wanted = pair[1], pair[2]
        local projectValue = tonumber(project:GetSetting(key))
        local timelineValue = tonumber(timeline:GetSetting(key))
        if not projectValue or math.abs(projectValue-wanted)>0.001 then
            warnings[#warnings+1] = '项目 ' .. key .. ' 与设置不一致（期望 ' .. wanted .. '），已保留原参数'
        end
        if not timelineValue or math.abs(timelineValue-wanted)>0.001 then
            warnings[#warnings+1] = '时间线 ' .. key .. ' 与设置不一致（期望 ' .. wanted .. '），已保留原参数'
        end
    end
    local active=pm:GetCurrentProject()
    if not active or active:GetName()~=projectName then error('PROJECT_SWITCH_NOT_CONFIRMED') end
    if not pm:SaveProject() then error('SAVE_PROJECT_FAILED') end
    return {project=projectName, timeline=timelineName, timeline_created=tostring(timelineCreated), project_created=tostring(created), warning=table.concat(warnings, '; '), timeline_fps=job.timeline_fps}
end

-- Test harness returns only the pure preparation function; no application connection.
if FLOWSTUDIO_DAILY_TEST then return prepareDaily, acquireResolve end

local function noteFailure(msg)
    local text = os.date('%Y-%m-%d %H:%M:%S ') .. tostring(msg)
    pcall(function()
        local f = io.open('/tmp/flowstudio-bridge-error.txt', 'w')
        if f then f:write(text); f:close() end
    end)
    -- The script folder already exists. This remains visible when /tmp is not.
    pcall(function()
        local f = io.open(tostring(platform.directory) .. '/flowstudio-bridge-boot.txt', 'w')
        if f then f:write(text); f:close() end
    end)
end
-- Written before any shell call. A shell call inside Resolve can sit forever and leave no files.
noteFailure('BOOT '..tostring(platform.directory))
local function bridgeHome()
    -- Resolve is busy running this script, so asking macOS for the home folder from here never returns.
    local home = os.getenv('HOME')
    if type(home) == 'string' and home ~= '' then return home end
    local dir = tostring(platform.directory or '')
    home = dir:match('^(/Users/[^/]+)/') or dir:match('^(/home/[^/]+)/') or ''
    if home ~= '' then return home end
    noteFailure('HOME unavailable dir='..dir)
    error('HOME unavailable')
end
local home = bridgeHome()
local root = home .. '/Documents/FlowStudioResolveBridge'
local inbox = root .. '/v0_5_0/commands'
local stateFile = root .. '/bridge_state.ini'
local lockDir = root .. '/v0_5_0/instance.lock'
local function quote(s) return "'" .. tostring(s):gsub("'", "'\\''") .. "'" end
local function runOK(cmd)
    local a, _, c = os.execute(cmd)
    return a == 0 or a == true and (c == nil or c == 0)
end
local _posix
local function posixLib()
    if _posix ~= nil then return _posix or nil end
    if platform.windows then _posix=false; return nil end
    local ok, ffi = pcall(require, 'ffi')
    if not ok or not ffi then _posix=false; return nil end
    local defined = pcall(function()
        ffi.cdef[[
            int mkdir(const char *path, int mode);
            int rmdir(const char *path);
            typedef struct { long tv_sec; long tv_nsec; } FS_TIMESPEC;
            int nanosleep(const FS_TIMESPEC *req, const FS_TIMESPEC *rem);
        ]]
    end)
    if not defined then _posix=false; return nil end
    _posix = ffi
    return ffi
end
local function posixMkdir(path)
    local ffi = posixLib()
    if not ffi then return nil end
    if ffi.C.mkdir(path, 493) == 0 then return 'created' end
    if ffi.errno() == 17 then return 'exists' end
    return 'error'
end
local function ensureDir(path)
    path = tostring(path):gsub('\\','/'):gsub('/+$','')
    if platform.windows then return runOK('mkdir -p '..quote(path)) end
    if not posixLib() then
        if bmd and type(bmd.createdir)=='function' and pcall(bmd.createdir, path) then return true end
        noteFailure('Cannot create '..path)
        return false
    end
    local acc = ''
    for part in path:gmatch('[^/]+') do
        acc = acc..'/'..part
        local result = posixMkdir(acc)
        if result ~= 'created' and result ~= 'exists' then
            noteFailure('Cannot create '..acc)
            return false
        end
    end
    return acc ~= ''
end
local function mkdirExclusive(path)
    local result = posixMkdir(path)
    if result == 'created' then return true end
    if result == 'exists' then return false end
    if platform.windows then return runOK('mkdir '..quote(path)..' 2>/dev/null') end
    noteFailure('Cannot lock '..path)
    return false
end
local function removeDir(path)
    local ffi = posixLib()
    if ffi and ffi.C.rmdir(path) == 0 then return true end
    if platform.windows then return runOK('rmdir '..quote(path)..' 2>/dev/null') end
    return false
end
local function sleepOne()
    local ffi = posixLib()
    if ffi then
        local ok = pcall(function()
            local req = ffi.new('FS_TIMESPEC')
            req.tv_sec = 1
            req.tv_nsec = 0
            ffi.C.nanosleep(req, nil)
        end)
        if ok then return end
    end
    if bmd and type(bmd.wait) == 'function' and pcall(bmd.wait, 1) then return end
    if platform.windows then os.execute('/bin/sleep 1'); return end
    local started = os.clock()
    while os.clock() - started < 1 do end
end
local function jobsFromEntries(dir, entries)
    local jobs = {}
    for _, entry in pairs(entries) do
        local name, isDir
        if type(entry) == 'table' then
            name = entry.Name or entry.name
            isDir = entry.IsDir or entry.isDir
        elseif type(entry) == 'string' then
            name = entry
        end
        if type(name) == 'string' and name:match('%.job$') and not isDir then
            jobs[#jobs+1] = dir..'/'..name
        end
    end
    table.sort(jobs)
    return jobs
end
local function listJobPaths(dir)
    if not platform.windows then
        if bmd and type(bmd.readdir) == 'function' then
            for _, folder in ipairs({dir, dir..'/', dir..'/*'}) do
                local ok, entries = pcall(bmd.readdir, folder)
                if ok and type(entries) == 'table' then return jobsFromEntries(dir, entries) end
            end
        end
        noteFailure('Cannot list '..dir)
        return {}
    end
    local pipe = assert(io.popen('find '..quote(dir)..' -maxdepth 1 -type f -name "*.job" -print | sort'))
    local paths = {}
    for path in pipe:lines() do paths[#paths+1] = path end
    pipe:close()
    return paths
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
for _,dir in ipairs(dirs) do
    if not ensureDir(dir) then error('Cannot create '..dir) end
end
pcall(function()
    local f = io.open(root..'/logs/bridge.log', 'a')
    if f then f:write(os.date('%Y-%m-%d %H:%M:%S') .. ' START home=' .. home .. '\n'); f:close() end
end)
-- Manual Workspace launches must also refuse a live legacy bridge.
local legacyHeartbeat = io.open(root..'/bridge_heartbeat.txt','r')
if legacyHeartbeat then
    local value = legacyHeartbeat:read('*a'); legacyHeartbeat:close()
    if platform.windows and not tonumber(value) then
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
if not mkdirExclusive(lockDir) then
    -- Recheck the lease after losing mkdir: another script may just have started.
    local fresh = readPairs(stateFile)
    local leaseAge = os.time() - (tonumber(fresh.updated_at) or 0)
    local lockTime = 0
    if platform.windows then
        local stat = io.popen('/usr/bin/stat -f %m '..quote(lockDir))
        lockTime = stat and tonumber(stat:read('*l')) or os.time()
        if stat then stat:close() end
    end
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
    if importing.batch_id and not resumable then
        error('IMPORT_RECOVERY_REQUIRED: 上次导入仍持有运行锁，不能接管可能仍在执行的进程。请检查旧 Bridge 和批次日志')
    end
    if not removeDir(lockDir) or not mkdirExclusive(lockDir) then
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
    noteFailure('')
    local lostChecks=0
    while not exists(root..'/v0_5_0/STOP') do
        -- Publish before the Resolve call so a slow or briefly failing API does not look offline.
        publish()
        local linked=pcall(acquireResolve)
        lostChecks=linked and 0 or lostChecks+1
        if lostChecks>=15 then
            report('OFFLINE','达芬奇连接已失效，旧 Bridge 已退出；请重新唤醒')
            return
        end
        publish()
        local paths=listJobPaths(inbox)
        for _,path in ipairs(paths) do
            local job=readPairs(path)
            state.request_id=job.request_id or ''
            state.warning=''
            local success, result=pcall(function()
                if job.action~='PREPARE_DAILY' and job.action~='IMPORT_BATCH' and job.action~='START_AUTOEDIT' and job.action~='FINISH_BATCH' then error('UNSUPPORTED_ACTION') end
                if not state.request_id:match('^[a-f0-9]+$') then error('INVALID_REQUEST_ID') end
                app = acquireResolve()
                local versionOK, version = pcall(function() return app:GetVersionString() end)
                state.resolve_version = versionOK and tostring(version) or 'unknown'
                if job.action=='IMPORT_BATCH' then
                    state.batch_id=job.batch_id or ''
                    local path=platform.directory..'/FlowStudio_Import_Batch.lua'
                    local importBatch=assert(loadfile(path),'IMPORT_MODULE_MISSING')()
                    return importBatch(app,job,report)
                end
                if job.action=='FINISH_BATCH' then
                    local module=assert(loadfile(platform.directory..'/FlowStudio_Finish_Batch.lua'))()
                    return module.run(app,job,report)
                end
                if job.action=='START_AUTOEDIT' then
                    state.batch_id=job.batch_id or ''
                    local path=platform.directory..'/Autoediting_V1.7_FlowStudio.lua'
                    local module=assert(loadfile(path),'AUTOEDIT_MODULE_MISSING')()
                    return module.run(app,job,report)
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
                local function resumable(lock)
                    return lock.stage=='WAITING_USER_REVIEW' or lock.stage=='ANALYSIS_ERROR' or
                           lock.stage=='CUTTING_ERROR' or lock.stage=='IMPORT_ERROR' or
                           lock.action=='FINISH_BATCH'
                end
                -- Only one Resolve operation can run at once, but paused batches belong
                -- to their own work date. Park another date's resumable lock and restore
                -- the selected date's lock when switching history/today.
                if pipeline.action and pipeline.work_date and pipeline.work_date~=job.work_date then
                    if not resumable(pipeline) then error('PIPELINE_LOCKED: 其他日期剪辑批次仍在运行') end
                    assert(pipeline.work_date:match('^%d%d%d%d%-%d%d%-%d%d$'),'INVALID_PIPELINE_DATE')
                    local parked=suspendedDir..'/pipeline_'..pipeline.work_date..'.ini'
                    os.remove(parked)
                    assert(os.rename(pipelinePath,parked),'PARK_OLD_PIPELINE_FAILED')
                    pipeline={}
                end
                local selected=suspendedDir..'/pipeline_'..job.work_date..'.ini'
                if not pipeline.action and exists(selected) then
                    assert(os.rename(selected,pipelinePath),'RESTORE_PIPELINE_FAILED')
                    pipeline=readPairs(pipelinePath)
                end
                if pipeline.action and pipeline.action~='IMPORT_BATCH' then
                    local paused=resumable(pipeline)
                    if not paused then error('PIPELINE_LOCKED: 当前剪辑批次未结束') end
                    if pipeline.work_date and pipeline.work_date~=job.work_date then
                        error('PIPELINE_LOCKED: 当前剪辑批次日期不匹配')
                    end
                end
                local prepared=prepareDaily(app,job,report)
                if prepared.timeline_created=='true' then
                    -- Durable receipt lets Studio invalidate only the deleted timeline's
                    -- unfinished work, even if the UI reconnects after this command.
                    atomicWrite(root..'/v0_5_0/rebuild_'..job.work_date..'.ini',
                        'rebuild_id='..job.request_id..'\nwork_date='..job.work_date..'\nproject='..prepared.project..'\ntimeline='..prepared.timeline..'\n')
                    if pipeline.batch_id and pipeline.work_date==job.work_date then
                        assert(os.rename(root..'/pipeline.lock',root..'/logs/pipeline_before_rebuild_'..job.request_id..'.ini'),'ARCHIVE_OLD_PIPELINE_FAILED')
                    end
                end
                return prepared
            end)
            if success then
                for k,v in pairs(result) do state[k]=v end
                report(result.stage or 'READY',job.action=='FINISH_BATCH' and '批次导出完成，成品记录已保留' or job.action=='START_AUTOEDIT' and '自动剪辑完成，等待人工检查；未执行清理或导出' or job.action=='IMPORT_BATCH' and ('剪辑素材导入完成 · 新增 '..tostring(result.imported_count)..' · 已存在跳过 '..tostring(result.skipped_count)) or '达芬奇已就绪')
            else
                report('ERROR',tostring(result))
                atomicWrite(root..'/v0_5_0/error/'..(path:match('([^/]+)$'))..'.txt',tostring(result))
            end
            assert(os.rename(path,root..'/v0_5_0/'..(success and 'done/' or 'error/')..path:match('([^/]+)$')))
        end
        -- Detect manual project / timeline changes while idle; READY must be truthful.
        if state.stage=='READY' then
            local connected, manager = pcall(function() local _, pm = acquireResolve(); return pm end)
            local project=connected and manager:GetCurrentProject()
            local timeline=project and project:GetCurrentTimeline()
            if not project or project:GetName()~=state.project or not timeline or timeline:GetName()~=state.timeline then
                report('IDLE','当前项目或时间线已切换，请再次唤醒达芬奇')
            end
        end
        sleepOne()
    end
    os.remove(root..'/v0_5_0/STOP')
    report('OFFLINE','Bridge 已停止')
end)
if not ok then noteFailure(err); pcall(report,'OFFLINE',tostring(err)) end
removeDir(lockDir)
if not ok then error(err) end
