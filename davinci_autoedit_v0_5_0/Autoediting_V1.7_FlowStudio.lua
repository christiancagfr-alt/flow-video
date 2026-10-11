local platformSource=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local platform=assert(loadfile(platformSource:match('^(.*)/[^/]+$')..'/FlowStudio_Platform.lua'))()
local os,io,loadfile=platform.os,platform.io,platform.loadfile
-- Autoediting V1.7.8 FlowStudio: V1.7.6 + per-small-clip head/tail audio-edge scan with adaptive activity threshold.
-- If batch Whisper stalls/fails, the batch falls back to bounded per-video recognition instead of blocking the whole job.
-- If one video still cannot be recognized/aligned after its bounded retry, that video is left untouched and marked Orange for manual editing.
-- Audio analysis is split into groups of at most 20 complete videos. Each batch records the exact
-- Flow Studio manuscript files/video IDs that belong to the same exported WAV, so text alignment
-- can never accidentally use manuscripts from another audio batch.
local HEAD_PAD_SEC,TAIL_PAD_SEC,MIN_TRIM_FRAMES=0.15,0.20,3
local MAX_GAP_FRAMES,WHISPER_TIMEOUT=10,600
local AUDIO_BATCH_VIDEO_LIMIT=20
-- A failed video must never block the whole batch indefinitely. The normal batch Whisper pass
-- counts as the first recognition attempt; only one short single-video retry is allowed by default.
local MAX_SINGLE_VIDEO_RETRIES=1
local SINGLE_VIDEO_RETRY_TIMEOUT=90
local MANUAL_EDIT_MARKER_COLOR='Orange'
local MANUAL_EDIT_MARKER_FALLBACK_COLOR='Sand'
-- Every imported SMALL clip is inspected independently at its own head and tail.
-- Internal pauses are never cut: only the first/last sustained activity inside each clip is used.
-- -48 dBFS is a safety floor; the probe raises the activity threshold adaptively from each clip's peak
-- so low room noise is less likely to block trimming. A sustained ~0.08s activity run confirms speech/audio.
local EDGE_SILENCE_MIN_SEC=0.20
local EDGE_SILENCE_THRESHOLD_DB=-48.0
local EDGE_SILENCE_WINDOW_SEC=0.02
local EDGE_SILENCE_ACTIVE_WINDOWS=4
-- Import markers are advisory anchors. Resolve can shift marker positions by a few frames
-- after timeline/import operations, so use a small tolerance and fall back to the
-- authoritative Studio clip range instead of aborting the whole batch.
local IMPORT_MARKER_TOLERANCE_FRAMES=6
local function shellQuote(s)
    return "'" .. tostring(s or ""):gsub("'", "'\\''") .. "'"
end


local whisperRunner
local function runWhisper(...) return assert(whisperRunner,'WHISPER_RUNNER_NOT_SET')(...) end
local function trim(s) return (tostring(s or ''):gsub('^%s+',''):gsub('%s+$','')) end
local function getTimelineFPS(project)
    local fps = tonumber(project:GetSetting("timelineFrameRate"))
    if not fps then fps = tonumber(project:GetSetting("timelinePlaybackFrameRate")) end
    return fps or 24
end

local function getTimelineStart(timeline)
    local startFrame = 0
    pcall(function() startFrame = tonumber(timeline:GetStartFrame()) or 0 end)
    return startFrame
end

local function collectVideoRanges(timeline)
    local ranges = {}
    local trackCount = timeline:GetTrackCount("video") or 0

    for t=1,trackCount do
        local items = timeline:GetItemListInTrack("video", t) or {}
        for _,item in ipairs(items) do
            local s = tonumber(item:GetStart())
            local e = tonumber(item:GetEnd())
            if s and e and e > s then
                table.insert(ranges,{s=s,e=e})
            end
        end
    end

    table.sort(ranges,function(a,b)
        if a.s == b.s then return a.e < b.e end
        return a.s < b.s
    end)

    return ranges
end

local function unionRanges(ranges)
    local out = {}
    for _,r in ipairs(ranges) do
        local last = out[#out]
        if not last or r.s > last.e then
            table.insert(out,{s=r.s,e=r.e})
        else
            if r.e > last.e then last.e = r.e end
        end
    end
    return out
end

local function splitByGap(unioned)
    local out = {}
    if #unioned == 0 then return out end

    local cur = {s=unioned[1].s,e=unioned[1].e}

    for i=2,#unioned do
        local r = unioned[i]
        local gap = r.s - cur.e

        if gap <= MAX_GAP_FRAMES then
            cur.e = math.max(cur.e,r.e)
        else
            table.insert(out,cur)
            cur = {s=r.s,e=r.e}
        end
    end

    table.insert(out,cur)
    return out
end

local function getAllFinalSegments(timeline)
    return splitByGap(unionRanges(collectVideoRanges(timeline)))
end

local function chooseMainTrackForSegment(timeline, segment)
    local bestTrack = nil
    local bestOverlap = -1
    local bestCount = -1
    local trackCount = timeline:GetTrackCount("video") or 0

    for t=1,trackCount do
        local overlap = 0
        local count = 0
        local items = timeline:GetItemListInTrack("video",t) or {}

        for _,item in ipairs(items) do
            local s = tonumber(item:GetStart())
            local e = tonumber(item:GetEnd())
            if s and e then
                local os = math.max(s,segment.s)
                local oe = math.min(e,segment.e)
                if oe > os then
                    overlap = overlap + (oe-os)
                    count = count + 1
                end
            end
        end

        if overlap > bestOverlap or (overlap == bestOverlap and count > bestCount) then
            bestTrack = t
            bestOverlap = overlap
            bestCount = count
        end
    end

    return bestTrack
end

local function collectClipsInSegment(timeline, trackIndex, segment)
    local clips = {}
    local items = timeline:GetItemListInTrack("video",trackIndex) or {}

    for _,item in ipairs(items) do
        local s = tonumber(item:GetStart())
        local e = tonumber(item:GetEnd())

        if s and e and s < segment.e and e > segment.s then
            table.insert(clips,{
                item=item,
                s=s,
                e=e,
                name=item:GetName() or "未命名"
            })
        end
    end

    table.sort(clips,function(a,b) return a.s < b.s end)
    return clips
end

----------------------------------------------------------------
-- Whisper / SRT / 文案对齐
----------------------------------------------------------------

local function normalizeToken(s)
    s = tostring(s or ""):lower()
    s = s:gsub("“",""):gsub("”",""):gsub("‘",""):gsub("’","")
    s = s:gsub("[^%w']","")
    return s
end

local function tokenizeText(s)
    local out = {}
    s = tostring(s or ""):gsub("\r"," "):gsub("\n"," ")

    for raw in s:gmatch("%S+") do
        local t = normalizeToken(raw)
        if t ~= "" then table.insert(out,t) end
    end

    return out
end

local function parseTime(t)
    local h,m,s,ms = t:match("(%d+):(%d+):(%d+),(%d+)")
    if not h then return nil end
    return tonumber(h)*3600 + tonumber(m)*60 + tonumber(s) + tonumber(ms)/1000
end

local function parseSRT(path)
    local f = io.open(path,"r")
    if not f then return nil,"无法读取 Whisper SRT。" end

    local txt = f:read("*a") or ""
    f:close()

    local lines = {}
    for line in (txt.."\n"):gmatch("(.-)\n") do
        local clean = line:gsub("\r","")
        table.insert(lines,clean)
    end

    local words = {}
    local i = 1

    while i <= #lines do
        if lines[i]:match("^%d+$") and lines[i+1] and lines[i+1]:find("%-%->") then
            local a,b = lines[i+1]:match(
                "(%d+:%d+:%d+,%d+)%s+%-%->%s+(%d+:%d+:%d+,%d+)"
            )

            i = i + 2
            local parts = {}

            while i <= #lines and trim(lines[i]) ~= "" do
                table.insert(parts,trim(lines[i]))
                i = i + 1
            end

            if a and b then
                local toks = tokenizeText(table.concat(parts," "))
                local st,en = parseTime(a),parseTime(b)

                if st and en and #toks > 0 then
                    local dur = math.max(0.001,en-st)

                    for k,tok in ipairs(toks) do
                        table.insert(words,{
                            text=tok,
                            start=st+dur*((k-1)/#toks),
                            finish=st+dur*(k/#toks)
                        })
                    end
                end
            end
        else
            i = i + 1
        end
    end

    if #words == 0 then return nil,"SRT 中没有解析到词。" end
    return words
end

local function levenshtein(a,b)
    local la,lb = #a,#b
    if la == 0 then return lb end
    if lb == 0 then return la end

    local prev,cur = {},{}
    for j=0,lb do prev[j]=j end

    for i=1,la do
        cur[0]=i
        local ca=a:sub(i,i)

        for j=1,lb do
            local cost=(ca==b:sub(j,j)) and 0 or 1
            cur[j]=math.min(
                prev[j]+1,
                cur[j-1]+1,
                prev[j-1]+cost
            )
        end

        prev,cur=cur,prev
    end

    return prev[lb]
end

local function similarity(a,b)
    if a==b then return 1.0 end
    local mx=math.max(#a,#b)
    if mx==0 then return 1.0 end
    return math.max(0,1.0-levenshtein(a,b)/mx)
end

local function alignWithPairs(manuscript,recog)
    local m,n=#manuscript,#recog
    if m==0 or n==0 then return nil end

    local INS,DEL=0.90,0.90
    local dp,bt={},{}

    for i=0,m do dp[i]={}; bt[i]={} end

    dp[0][0]=0
    for j=1,n do dp[0][j]=0; bt[0][j]="L" end
    for i=1,m do dp[i][0]=i*DEL; bt[i][0]="U" end

    for i=1,m do
        for j=1,n do
            local sim=similarity(manuscript[i],recog[j].text)
            local diag=dp[i-1][j-1]+(1-sim)
            local up=dp[i-1][j]+DEL
            local left=dp[i][j-1]+INS

            local best,op=diag,"D"
            if up<best then best,op=up,"U" end
            if left<best then best,op=left,"L" end

            dp[i][j]=best
            bt[i][j]=op
        end
    end

    local endJ,bestCost=1,dp[m][1]

    for j=2,n do
        if dp[m][j]<bestCost then
            bestCost=dp[m][j]
            endJ=j
        end
    end

    local pairs={}
    local i,j=m,endJ
    local simSum,matchCount=0,0

    while i>0 and j>=0 do
        local op=bt[i][j]

        if op=="D" then
            local sim=similarity(manuscript[i],recog[j].text)

            if sim>=0.35 then
                table.insert(pairs,1,{mi=i,rj=j,sim=sim})
                simSum=simSum+sim
                matchCount=matchCount+1
            end

            i=i-1
            j=j-1

        elseif op=="U" then
            i=i-1

        elseif op=="L" then
            j=j-1

        else
            break
        end
    end

    if matchCount==0 then return nil end

    local avg=simSum/matchCount
    local coverage=matchCount/m

    return {
        pairs=pairs,
        confidence=math.max(0,math.min(1,avg*coverage)),
        coverage=coverage,
        avgSimilarity=avg
    }
end

local function assignWordsToClips(words,clips,segment,fps)
    local perClip={}
    for i=1,#clips do perClip[i]={} end

    for wi,w in ipairs(words) do
        local mid=(w.start+w.finish)/2
        local absFrame=segment.s + mid*fps

        for i,c in ipairs(clips) do
            if absFrame>=c.s and absFrame<c.e then
                w.clipIndex=i
                w.wordIndex=wi
                table.insert(perClip[i],w)
                break
            end
        end
    end

    return perClip
end

local function analyzeOneVideo(job,fps)
    local words,err=runWhisper(job.wav,job.whisperBase,WHISPER_TIMEOUT)
    if not words then return nil,err end

    local manuscript=tokenizeText(job.manuscript)
    if #manuscript<3 then return nil,"正确文案太短。" end

    local perClip=assignWordsToClips(words,job.clips,job.segment,fps)
    local aligned=alignWithPairs(manuscript,words)

    if not aligned then
        return nil,"无法把识别结果与正确文案对齐。"
    end

    local clipMatches={}
    for i=1,#job.clips do clipMatches[i]={} end

    for _,p in ipairs(aligned.pairs) do
        local w=words[p.rj]

        if w and w.clipIndex and clipMatches[w.clipIndex] then
            table.insert(
                clipMatches[w.clipIndex],
                {word=w,sim=p.sim,mi=p.mi}
            )
        end
    end

    local results={}
    local cutCount=0
    local unmatched=0

    for i,clip in ipairs(job.clips) do
        local matches=clipMatches[i]
        local clipStartSec=(clip.s-job.segment.s)/fps
        local clipDur=(clip.e-clip.s)/fps

        if #matches==0 then
            table.insert(results,{
                index=i,
                clip=clip,
                matched=false,
                headFrames=0,
                tailFrames=0,
                keepStart=clip.s,
                keepEnd=clip.e,
                confidence=0
            })

            unmatched=unmatched+1

        else
            table.sort(matches,function(a,b)
                return a.word.start<b.word.start
            end)

            local firstW=matches[1].word
            local lastW=matches[#matches].word

            local rawStartLocal=math.max(
                0,
                firstW.start-clipStartSec
            )

            local rawEndLocal=math.min(
                clipDur,
                lastW.finish-clipStartSec
            )

            local simSum=0
            for _,m in ipairs(matches) do
                simSum=simSum+m.sim
            end

            local clipConf=simSum/#matches

            local keepStartSec=math.max(
                0,
                rawStartLocal-HEAD_PAD_SEC
            )

            local keepEndSec=math.min(
                clipDur,
                rawEndLocal+TAIL_PAD_SEC
            )

            local headFrames=math.floor(
                keepStartSec*fps+0.5
            )

            local tailFrames=math.floor(
                (clipDur-keepEndSec)*fps+0.5
            )

            if headFrames<MIN_TRIM_FRAMES then headFrames=0 end
            if tailFrames<MIN_TRIM_FRAMES then tailFrames=0 end

            local keepStart=clip.s+headFrames
            local keepEnd=clip.e-tailFrames

            if keepEnd<=keepStart+1 then
                headFrames=0
                tailFrames=0
                keepStart=clip.s
                keepEnd=clip.e
            end

            if headFrames>0 then cutCount=cutCount+1 end
            if tailFrames>0 then cutCount=cutCount+1 end

            table.insert(results,{
                index=i,
                clip=clip,
                matched=true,
                headFrames=headFrames,
                tailFrames=tailFrames,
                keepStart=keepStart,
                keepEnd=keepEnd,
                confidence=clipConf,
                matches=#matches
            })
        end
    end

    -- Whisper remains responsible for manuscript alignment. In addition, inspect the OUTER
    -- head/tail of EVERY small imported clip independently. This fixes silent padding left between
    -- small Flow segments. We never cut an internal pause: the probe only returns first/last sustained
    -- activity inside that clip. When confirmed silence exists, the audio edge is authoritative for
    -- that clip's boundary while preserving the configured 0.15s/0.20s speech safety pads.
    local clipEdges=job.clipEdgeSilence or {}
    for i,r in ipairs(results) do
        local edge=clipEdges[i]
        if edge then
            local clipDur=(r.clip.e-r.clip.s)/fps
            if edge.headSilence and edge.headSilence>=EDGE_SILENCE_MIN_SEC then
                local audioKeep=r.clip.s+math.floor(math.max(0,edge.activeStart-HEAD_PAD_SEC)*fps+0.5)
                -- Never make an existing confident Whisper trim looser. Audio-edge scanning is an
                -- additional floor: confirmed silence must be removed, while a later text boundary stays later.
                local keepAbs=math.max(r.keepStart or r.clip.s,audioKeep)
                if keepAbs>r.clip.s and keepAbs<r.clip.e then
                    local frames=keepAbs-r.clip.s
                    if frames>=MIN_TRIM_FRAMES then
                        r.headFrames=frames
                        r.keepStart=keepAbs
                        r.headSource='WHISPER_PLUS_PER_CLIP_AUDIO_EDGE'
                    end
                end
            end
            if edge.tailSilence and edge.tailSilence>=EDGE_SILENCE_MIN_SEC then
                local audioKeep=r.clip.s+math.floor(math.min(clipDur,edge.activeEnd+TAIL_PAD_SEC)*fps+0.5)
                -- Same rule at the tail: keep the earlier of the text boundary and confirmed audio edge.
                local keepAbs=math.min(r.keepEnd or r.clip.e,audioKeep)
                if keepAbs>r.clip.s and keepAbs<r.clip.e then
                    local frames=r.clip.e-keepAbs
                    if frames>=MIN_TRIM_FRAMES then
                        r.tailFrames=frames
                        r.keepEnd=keepAbs
                        r.tailSource='WHISPER_PLUS_PER_CLIP_AUDIO_EDGE'
                    end
                end
            end
            -- Never allow two independently-derived edge trims to collapse the clip.
            if r.keepEnd<=r.keepStart+1 then
                r.headFrames=0;r.tailFrames=0;r.keepStart=r.clip.s;r.keepEnd=r.clip.e
                r.headSource=nil;r.tailSource=nil
            end
        end
    end

    -- Recount after per-clip audio-edge overrides so the saved plan matches actual blade operations.
    cutCount=0
    for _,r in ipairs(results) do
        if r.headFrames and r.headFrames>0 then cutCount=cutCount+1 end
        if r.tailFrames and r.tailFrames>0 then cutCount=cutCount+1 end
    end

    return {
        words=words,
        perClip=perClip,
        aligned=aligned,
        results=results,
        cutCount=cutCount,
        unmatched=unmatched,
        clipEdgeSilence=clipEdges
    },nil
end

----------------------------------------------------------------
-- Edit 页面 / Command+B / Marker
----------------------------------------------------------------

local function parseTC(tc,nominal)
    local h,m,s,f=tostring(tc or ""):match(
        "(%d+):(%d+):(%d+)[:;](%d+)"
    )

    if not h then return nil end

    return (
        (
            (
                tonumber(h)*60+tonumber(m)
            )*60+tonumber(s)
        )*nominal
    )+tonumber(f)
end

local function framesToTC(total,nominal)
    if total<0 then total=0 end

    local f=total%nominal
    local totalSec=math.floor(total/nominal)
    local s=totalSec%60
    local totalMin=math.floor(totalSec/60)
    local m=totalMin%60
    local h=math.floor(totalMin/60)%24

    return string.format(
        "%02d:%02d:%02d:%02d",
        h,m,s,f
    )
end

local function absoluteFrameToTimecode(timeline,absFrame,fps)
    local nominal=math.floor(fps+0.5)
    local startFrame=getTimelineStart(timeline)

    local startTC="00:00:00:00"
    pcall(function()
        startTC=timeline:GetStartTimecode() or startTC
    end)

    local startTCFrames=parseTC(startTC,nominal)

    if not startTCFrames then
        return nil,"无法读取 Timeline 起始 Timecode。"
    end

    local offset=math.floor(
        absFrame-startFrame+0.5
    )

    return framesToTC(
        startTCFrames+offset,
        nominal
    )
end

local function openEditPage(resolveObj)
    local ok,ret=pcall(function()
        return resolveObj:OpenPage("edit")
    end)

    if ok and ret~=false then
        os.execute("/bin/sleep 0.9")
        return true
    end

    if platform.windows then return false end
    local apple=[[
tell application "DaVinci Resolve"
    activate
end tell
delay 0.3
tell application "System Events"
    keystroke "4" using {shift down}
end tell
delay 0.9
]]

    local p=io.popen(
        "/usr/bin/osascript <<'APPLESCRIPT'\n" ..
        apple ..
        "\nAPPLESCRIPT\n 2>&1"
    )

    if p then
        p:read("*a")
        p:close()
        return true
    end

    return false
end

local function prepareTimelineFocus()
    if platform.windows then return platform.focusTimeline() end
    local apple=[[
tell application "DaVinci Resolve"
    activate
end tell
delay 0.10
tell application "System Events"
    tell process "DaVinci Resolve"
        if exists menu bar item "工作区" of menu bar 1 then
            click menu item "时间线" of menu 1 of menu item "活动面板选择" of menu 1 of menu bar item "工作区" of menu bar 1
        else
            click menu item "Timeline" of menu 1 of menu item "Active Panel Selection" of menu 1 of menu bar item "Workspace" of menu bar 1
        end if
    end tell
    keystroke "k"
    delay 0.1
    -- Clear a selection that could restrict Command+B to a different clip.
    keystroke "a" using {command down, shift down}
end tell
delay 0.09
]]

    local p=io.popen(
        "/usr/bin/osascript <<'APPLESCRIPT'\n" ..
        apple ..
        "\nAPPLESCRIPT\n 2>&1"
    )

    if not p then
        return false,"无法运行 osascript。"
    end

    local out=p:read("*a") or ""
    local ok=p:close()

    return ok~=nil and ok~=false,out
end

local bladeFocusAt,bladesSinceFocus=0,0
-- 常驻 osascript：每刀只写一行命令，不再每刀启动一次进程。
local bladeProc=nil
local function closeBladeProc()
    if bladeProc then pcall(function() bladeProc:close() end);bladeProc=nil end
end
local function sendBladeKey()
    if platform.windows then return platform.blade() end
    if not bladeProc then
        local ok,p=pcall(io.popen,"/bin/sh -c 'exec /usr/bin/osascript -i >/dev/null 2>&1'",'w')
        if ok and p then bladeProc=p end
    end
    if not bladeProc then return false end
    local ok=pcall(function()
        bladeProc:write('tell application "System Events" to keystroke "b" using {command down}\n')
        bladeProc:flush()
    end)
    if not ok then closeBladeProc() end
    return ok
end
local function movePlayheadAndBlade(timeline,frame,fps)
    -- 聚焦时间线很慢（菜单点击 + 多处 delay），不必每刀都做：首刀、每 20 刀、或超过 30 秒再做。
    local nowT=os.time()
    if bladesSinceFocus==0 or bladesSinceFocus>=20 or nowT-bladeFocusAt>=30 then
        closeBladeProc()
        local focused,focusError=prepareTimelineFocus()
        if not focused then return false,'TIMELINE_FOCUS_FAILED: '..tostring(focusError) end
        bladeFocusAt=os.time();bladesSinceFocus=0
    end
    bladesSinceFocus=bladesSinceFocus+1
    local tc,err=absoluteFrameToTimecode(
        timeline,
        frame,
        fps
    )

    if not tc then return false,err end

    local ok,setRet=pcall(function()
        return timeline:SetCurrentTimecode(tc)
    end)

    if not ok or setRet==false then
        return false,"无法把播放头移动到 "..tc
    end

    local arrived=false
    for i=1,100 do
        if timeline:GetCurrentTimecode()==tc then arrived=true;break end
        os.execute('/bin/sleep 0.02')
    end
    if not arrived then return false,'PLAYHEAD_NOT_READY: '..tc end
    if sendBladeKey() then return true,'' end
    if platform.windows then return false,'RESOLVE_FOCUS_LOST' end
    local p=io.popen([[ /usr/bin/osascript -e 'tell application "System Events" to keystroke "b" using {command down}' 2>&1 ]])
    if not p then return false,'BLADE_COMMAND_FAILED' end
    local out=p:read('*a');local success=p:close()
    return success~=nil and success~=false,out
end

local function findItemByRange(
    timeline,
    trackIndex,
    s,
    e
)
    local items=timeline:GetItemListInTrack(
        "video",
        trackIndex
    ) or {}

    for _,item in ipairs(items) do
        local is=tonumber(item:GetStart())
        local ie=tonumber(item:GetEnd())

        if is and ie and
           math.abs(is-s)<=1 and
           math.abs(ie-e)<=1 then
            return item
        end
    end

    return nil
end

-- Batch orchestration. The alignment, padding and blade helpers above are retained.
local function readPairs(path)
    local values={};local f=io.open(path,'r');if not f then return values end
    for line in f:lines() do local k,v=line:match('^([^=]+)=(.*)$');if k then values[k]=v end end
    f:close();return values
end
local function writePairs(path,values)
    local f=assert(io.open(path..'.tmp','w'),'WRITE_FAILED: '..path)
    for k,v in pairs(values) do f:write(k..'='..tostring(v):gsub('[\r\n]',' ')..'\n') end
    f:close();assert(os.rename(path..'.tmp',path),'PUBLISH_FAILED')
end
local function readText(path) local f=assert(io.open(path,'r'),'FILE_MISSING: '..path);local s=f:read('*a');f:close();return s end
local function readTextOptional(path)
    local f=io.open(path,'r');if not f then return '' end
    local s=f:read('*a') or '';f:close();return s
end
local function terminatePidFile(path)
    local f=io.open(path,'r');if not f then return end
    local pid=tonumber(trim(f:read('*a')));f:close()
    if pid then os.execute('pkill -TERM -P '..pid..' >/dev/null 2>&1; kill -TERM '..pid..' >/dev/null 2>&1') end
end

local SILENCE_PROBE_PY=[=[
import argparse, array, math, os, sys, wave

def decode_pcm(raw, sampwidth):
    if sampwidth == 1:
        return [b - 128 for b in raw], 128.0
    if sampwidth == 2:
        a = array.array('h')
        a.frombytes(raw)
        if sys.byteorder != 'little': a.byteswap()
        return a, 32768.0
    if sampwidth == 4:
        a = array.array('i')
        a.frombytes(raw)
        if sys.byteorder != 'little': a.byteswap()
        return a, 2147483648.0
    if sampwidth == 3:
        out=[]
        for i in range(0, len(raw)-2, 3):
            v=raw[i] | (raw[i+1] << 8) | (raw[i+2] << 16)
            if v & 0x800000: v -= 0x1000000
            out.append(v)
        return out, 8388608.0
    raise ValueError('UNSUPPORTED_SAMPLE_WIDTH_%s' % sampwidth)

def first_run(active, need):
    run=0
    for i,v in enumerate(active):
        if v:
            run += 1
            if run >= need: return i-need+1
        else:
            run=0
    return None

def last_run(active, need):
    run=0
    for i in range(len(active)-1, -1, -1):
        if active[i]:
            run += 1
            if run >= need: return i+need-1
        else:
            run=0
    return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--wav', required=True)
    ap.add_argument('--start', type=float, required=True)
    ap.add_argument('--duration', type=float, required=True)
    ap.add_argument('--threshold-db', type=float, default=-48.0)
    ap.add_argument('--window-sec', type=float, default=0.02)
    ap.add_argument('--active-windows', type=int, default=3)
    a=ap.parse_args()
    with wave.open(a.wav, 'rb') as wf:
        if wf.getcomptype() != 'NONE':
            raise ValueError('COMPRESSED_WAV_NOT_SUPPORTED')
        rate=wf.getframerate(); chans=wf.getnchannels(); sw=wf.getsampwidth(); total=wf.getnframes()
        start=max(0, min(total, int(round(a.start*rate))))
        count=max(0, min(total-start, int(round(a.duration*rate))))
        wf.setpos(start)
        raw=wf.readframes(count)
    vals,full=decode_pcm(raw, sw)
    if count <= 0 or not vals:
        print('status=EMPTY'); return
    win_frames=max(1, int(round(a.window_sec*rate)))
    win_samples=max(chans, win_frames*chans)
    levels=[]
    for off in range(0, len(vals), win_samples):
        chunk=vals[off:off+win_samples]
        if not chunk: break
        ss=0.0
        for v in chunk: ss += float(v)*float(v)
        rms=math.sqrt(ss/max(1,len(chunk)))/full
        db=-120.0 if rms <= 1e-12 else 20.0*math.log10(rms)
        levels.append(db)
    peak=max(levels) if levels else -120.0
    # Adaptive strong threshold: keep the configured -48 dBFS as the quiet-voice safety floor,
    # but raise it when the clip has a healthy peak so low room noise does not look like speech.
    strong_threshold=max(a.threshold_db, min(-34.0, peak-14.0))
    weak_threshold=max(-60.0, strong_threshold-8.0)
    strong=[db >= strong_threshold for db in levels]
    first=first_run(strong, max(1,a.active_windows))
    last=last_run(strong, max(1,a.active_windows))
    if first is None or last is None or last < first:
        print('status=NO_ACTIVITY')
        print('peak_db=%.3f' % peak)
        print('threshold_used_db=%.3f' % strong_threshold)
        return
    # Hysteresis: after a sustained strong run confirms activity, walk outward through softer
    # attack/release samples. This prevents trimming quiet syllable starts/ends.
    while first > 0 and levels[first-1] >= weak_threshold:
        first -= 1
    while last+1 < len(levels) and levels[last+1] >= weak_threshold:
        last += 1
    active_start=min(a.duration, first*win_frames/rate)
    active_end=min(a.duration, (last+1)*win_frames/rate)
    print('status=OK')
    print('active_start=%.6f' % active_start)
    print('active_end=%.6f' % active_end)
    print('head_silence=%.6f' % max(0.0, active_start))
    print('tail_silence=%.6f' % max(0.0, a.duration-active_end))
    print('peak_db=%.3f' % peak)
    print('threshold_used_db=%.3f' % strong_threshold)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('status=ERROR')
        print('error=' + str(e).replace('\n',' '))
        sys.exit(2)
]=]

local function ensureSilenceProbe(path)
    local existing=readTextOptional(path)
    if existing==SILENCE_PROBE_PY then return true end
    local f=assert(io.open(path..'.tmp','w'),'WRITE_FAILED: '..path)
    f:write(SILENCE_PROBE_PY);f:close()
    assert(os.rename(path..'.tmp',path),'PUBLISH_FAILED: '..path)
    return true
end

local function parseSimplePairs(text)
    local out={}
    for line in tostring(text or ''):gmatch('[^\r\n]+') do
        local k,v=line:match('^([^=]+)=(.*)$')
        if k then out[k]=v end
    end
    return out
end

local function probeEdgeSilence(pythonPath,probePath,wavPath,startSec,durationSec,resultPath)
    if not pythonPath or pythonPath=='' then return nil,'PYTHON_PATH_MISSING' end
    if not wavPath or wavPath=='' then return nil,'WAV_PATH_MISSING' end
    if not durationSec or durationSec<=0 then return nil,'INVALID_DURATION' end
    os.remove(resultPath);os.remove(resultPath..'.err')
    local args={pythonPath,probePath,'--wav',wavPath,'--start',string.format('%.6f',startSec),'--duration',string.format('%.6f',durationSec),'--threshold-db',tostring(EDGE_SILENCE_THRESHOLD_DB),'--window-sec',tostring(EDGE_SILENCE_WINDOW_SEC),'--active-windows',tostring(EDGE_SILENCE_ACTIVE_WINDOWS)}
    for i,arg in ipairs(args) do args[i]=shellQuote(arg) end
    local rc=os.execute(table.concat(args,' ')..' > '..shellQuote(resultPath)..' 2> '..shellQuote(resultPath..'.err'))
    local vals=parseSimplePairs(readTextOptional(resultPath))
    if vals.status~='OK' then
        local detail=vals.error or trim(readTextOptional(resultPath..'.err'))
        return nil,(vals.status or 'SILENCE_PROBE_FAILED')..(detail~='' and (': '..detail) or '')
    end
    local activeStart,activeEnd=tonumber(vals.active_start),tonumber(vals.active_end)
    local headSilence,tailSilence=tonumber(vals.head_silence),tonumber(vals.tail_silence)
    if not activeStart or not activeEnd or not headSilence or not tailSilence then return nil,'SILENCE_PROBE_INVALID_OUTPUT' end
    return {activeStart=activeStart,activeEnd=activeEnd,headSilence=headSilence,tailSilence=tailSilence,peakDb=tonumber(vals.peak_db),thresholdUsedDb=tonumber(vals.threshold_used_db),exitCode=rc}
end

local function mkdir(path) local a=os.execute('mkdir -p '..shellQuote(path));assert(a==0 or a==true,'MKDIR_FAILED') end
local function tag(s)
    local t={};if type(s)=='string' and s:sub(1,11)=='FLOWSTUDIO|' then
        for k,v in s:gmatch('|([^=|]+)=([^|]*)') do t[k]=v end
    end;return t
end

local function addManualEditMarker(timeline,origin,bid,attempt,job,reason)
    local markers=timeline:GetMarkers() or {}
    -- Idempotent update: remove an older manual marker for the same video/attempt before adding a fresh one.
    for oldFrame,marker in pairs(markers) do
        local info=type(marker)=='table' and tag(marker.customData) or {}
        if info.batch_id==bid and info.video_id==job.id and info.status=='MANUAL_EDIT' then
            assert(timeline:DeleteMarkerAtFrame(oldFrame),'MANUAL_MARKER_UPDATE_FAILED')
            markers[oldFrame]=nil
        end
    end
    local frame=math.max(0,math.floor(job.segment.s-origin+0.5))
    local last=math.max(frame+1,math.floor(job.segment.e-origin+0.5))
    while markers[frame] and frame<last do frame=frame+1 end
    assert(frame<last,'NO_FREE_MANUAL_MARKER: '..job.id)
    local duration=math.max(1,last-frame)
    local note='识别失败或超时，已自动跳过，不会阻塞其他视频。请手动剪辑。原因：'..tostring(reason or 'UNKNOWN')
    local custom='FLOWSTUDIO|batch_id='..bid..'|attempt_id='..attempt..'|video_id='..job.id..'|status=MANUAL_EDIT|start='..job.segment.s..'|end='..job.segment.e
    local markerOK=timeline:AddMarker(frame,MANUAL_EDIT_MARKER_COLOR,'手动剪辑 · 视频 '..job.id,note,duration,custom)
    if not markerOK then
        -- Older Resolve palettes may not expose an explicit Orange scripting color; Sand is the
        -- closest warm marker color and keeps the batch from failing solely because of palette support.
        markerOK=timeline:AddMarker(frame,MANUAL_EDIT_MARKER_FALLBACK_COLOR,'手动剪辑 · 视频 '..job.id,note,duration,custom)
    end
    assert(markerOK,'MANUAL_MARKER_FAILED: '..job.id)
end

local function resolveImportMarker(markers,origin,bid,id,s,e,usedFrames)
    local candidates={}
    for frame,marker in pairs(markers or {}) do
        local info=type(marker)=='table' and tag(marker.customData) or {}
        if info.batch_id==bid and info.status=='COMPLETE' then
            local mf,ms,me=tonumber(frame),tonumber(info.start),tonumber(info['end'])
            if mf and ms and me then
                local absFrame=origin+mf
                local ds=math.abs(ms-s)
                local de=math.abs(me-e)
                local df=math.abs(absFrame-s)
                if ds<=IMPORT_MARKER_TOLERANCE_FRAMES and de<=IMPORT_MARKER_TOLERANCE_FRAMES and df<=IMPORT_MARKER_TOLERANCE_FRAMES then
                    candidates[#candidates+1]={
                        frame=mf,absFrame=absFrame,info=info,
                        score=ds+de+df,
                        idPenalty=(info.video_id==id) and 0 or 1
                    }
                end
            end
        end
    end
    table.sort(candidates,function(a,b)
        if a.idPenalty~=b.idPenalty then return a.idPenalty<b.idPenalty end
        if a.score~=b.score then return a.score<b.score end
        return a.frame<b.frame
    end)
    for _,c in ipairs(candidates) do
        if not usedFrames[c.frame] then
            usedFrames[c.frame]=id
            return c
        end
    end
    return nil
end
local function renderStatusKind(status)
    local raw=trim(tostring(status or ''):gsub(' ',' '):gsub('　',' '):gsub('﻿',''))
    local s=raw:lower()
    if s=='complete' or s=='completed' or raw=='完成' or raw=='已完成' then return 'complete' end
    if s=='failed' or s=='error' or raw=='失败' or raw=='已失败' then return 'failed' end
    if s=='cancelled' or s=='canceled' or raw=='取消' or raw=='已取消' then return 'cancelled' end
    return 'active'
end

local function sliceTimelineWords(words,startSec,endSec)
    local out={}
    local duration=math.max(0,endSec-startSec)
    for _,w in ipairs(words or {}) do
        local ws,we=tonumber(w.start),tonumber(w.finish)
        if ws and we and we>startSec and ws<endSec then
            local ls=math.max(0,ws-startSec)
            local le=math.min(duration,we-startSec)
            if le>ls then table.insert(out,{text=w.text,start=ls,finish=le}) end
        end
    end
    return out
end

local function cutBoundary(timeline,kind,track,frame)
    local left,right,crossing=false,false,false
    for _,item in ipairs(timeline:GetItemListInTrack(kind,track) or {}) do
        local s,e=item:GetStart(),item:GetEnd()
        if e==frame then left=true end
        if s==frame then right=true end
        if s<frame and e>frame then crossing=true end
    end
    return left and right and not crossing
end
local function confirmCut(timeline,frame,videoTrack,audioTracks,guard)
    local videoOK,missing
    for poll=1,100 do
        guard()
        videoOK=cutBoundary(timeline,'video',videoTrack,frame);missing={}
        for track in pairs(audioTracks) do
            if not cutBoundary(timeline,'audio',track,frame) then missing[#missing+1]=track end
        end
        if videoOK and #missing==0 then return true end
        if poll<100 then os.execute('/bin/sleep 0.02') end
    end
    assert(videoOK,'CUT_NOT_CONFIRMED: frame='..frame..' 视频切刀未确认；保留现场，不会重复发送快捷键')
    error('AUDIO_CUT_NOT_CONFIRMED: frame='..frame..' audio_tracks='..table.concat(missing,',')..' 视频已切开但音频未同步；保留现场')
end

-- V43 already stores a cut plan and import log. Resume only if the original
-- source placement can still be proven; never re-analyze shortened clips.
local function validateResumeSources(timeline,jobs,root,bid)
    local manifest=readPairs(root..'/v0_5_0/batches/'..bid..'/manifest.ini')
    local log=readText(root..'/logs/'..bid..'/import.log')
    local ranges={}
    for vid,sid,a,b in log:gmatch('ACTUAL video_id=(%d+) segment_id=(%d+) start=(%d+) end=(%d+)') do
        local key=vid..':'..sid
        assert(not ranges[key],'RESUME_IMPORT_LOG_AMBIGUOUS')
        ranges[key]={s=tonumber(a),e=tonumber(b)}
    end
    local expected={}
    for i=1,tonumber(manifest.video_count or 0) do
        local pre='v'..i..'_';local vid=manifest[pre..'id'];local parts={}
        for j=1,tonumber(manifest[pre..'segment_count'] or 0) do
            local part=assert(ranges[vid..':'..manifest[pre..'s'..j..'_id']],'RESUME_IMPORT_LOG_MISSING')
            part.path=manifest[pre..'s'..j..'_path'];parts[#parts+1]=part
        end
        expected[vid]=parts
    end
    for _,job in ipairs(jobs) do
        local parts=assert(expected[job.id],'RESUME_SOURCE_ID_MISSING')
        assert(#parts>0 and parts[1].s==job.segment.s and parts[#parts].e==job.segment.e,'RESUME_IMPORT_RANGE_CHANGED')
        for _,kind in ipairs({'video'}) do
            for track=1,1 do
                for _,item in ipairs(timeline:GetItemListInTrack(kind,track) or {}) do
                    local a,b=item:GetStart(),item:GetEnd()
                    if a<job.segment.e and b>job.segment.s then
                        local matched=false
                        for _,part in ipairs(parts) do
                            if a>=part.s and b<=part.e then
                                local media=item:GetMediaPoolItem()
                                assert(media and platform.path(media:GetClipProperty('File Path'))==platform.path(part.path),'RESUME_SOURCE_CHANGED')
                                assert(item:GetLeftOffset()==a-part.s,'RESUME_SOURCE_OFFSET_CHANGED')
                                matched=true;break
                            end
                        end
                    end
                end
            end
        end
    end
end

local function runBatch(app,command,report,test)
    test=test or {};local root=test.root or assert(os.getenv('HOME'))..'/Documents/FlowStudioResolveBridge'
    local bid,attempt=command.batch_id,command.request_id
    assert(type(bid)=='string' and bid:match('^[%w_-]+$'),'INVALID_BATCH_ID')
    assert(type(attempt)=='string' and attempt:match('^[a-f0-9]+$'),'INVALID_ATTEMPT_ID')
    local resume=command.resume=='true'
    local taskId=command.task_id or attempt
    assert(taskId==attempt,'TASK_ID_MISMATCH')
    local base=root..'/v0_5_0/batches/'..bid..'/autoedit/'..attempt
    assert(command.payload_path==base..'/autoedit.ini','PAYLOAD_PATH_MISMATCH')
    local p=readPairs(command.payload_path)
    assert(p.batch_id==bid and p.attempt_id==attempt and p.task_id==taskId,'BATCH_IDENTITY_MISMATCH')
    local reanalyze=(p.reanalyze=='true')
    assert(command.work_date==p.work_date,'HISTORY_DATE_PROTECTED')
    assert(p.whisper_language=='sw','WHISPER_LANGUAGE_MUST_BE_SW')
    assert(p.task_json_path==base..'/task.json','TASK_JSON_PATH_MISMATCH')
    local taskJSON=readText(p.task_json_path)
    assert(taskJSON:find('"task_id": "'..taskId..'"',1,true),'TASK_JSON_ID_MISMATCH')
    assert(taskJSON:find('"batch_id": "'..bid..'"',1,true),'TASK_JSON_BATCH_MISMATCH')
    assert(taskJSON:find('"language": "sw"',1,true),'TASK_JSON_LANGUAGE_MISMATCH')
    local lock=readPairs(root..'/pipeline.lock')
    local lockOK=(resume and lock.batch_id==bid and lock.attempt_id==attempt and lock.action=='START_AUTOEDIT' and lock.stage=='CUTTING_ERROR')
        or (reanalyze and not resume and lock.batch_id==bid and lock.action=='START_AUTOEDIT' and lock.stage=='WAITING_USER_REVIEW')
        or (not resume and not reanalyze and (not lock.batch_id or (lock.batch_id==bid and lock.action=='START_AUTOEDIT' and lock.stage=='ANALYSIS_ERROR')))
    assert(lockOK,'PIPELINE_LOCKED: 当前批次状态不允许自动剪辑或重新识别')
    mkdir(root..'/logs/'..bid);mkdir(base..'/audio');mkdir(base..'/whisper')
    local state={batch_id=bid,attempt_id=attempt,task_id=taskId,resume=tostring(resume),reanalyze=tostring(reanalyze),current=0,total=assert(tonumber(p.video_count)),stage='AUDIO_RENDERING'}
    assert(state.total>0,'EMPTY_BATCH')
    assert(tonumber(p.expected_complete_video_count)==state.total,'EXPECTED_VIDEO_COUNT_MISMATCH')
    local cutting=false
    local function pulse(stage,detail,current)
        state.stage,state.detail=stage,detail;if current then state.current=current end
        state.updated_at=os.time();writePairs(base..'/state.ini',state)
        writePairs(root..'/pipeline.lock',{batch_id=bid,attempt_id=attempt,task_id=taskId,action='START_AUTOEDIT',work_date=p.work_date,stage=stage,updated_at=state.updated_at})
        report(stage,detail,{batch_id=bid,task_id=taskId,current=state.current,total=state.total})
        local f=assert(io.open(root..'/logs/'..bid..'/autoedit.log','a'))
        f:write(os.date('%Y-%m-%d %H:%M:%S')..' attempt='..attempt..' task='..taskId..' stage='..stage..' '..detail..'\n');f:close()
    end
    local ok,result=pcall(function()
        pulse('AUDIO_RENDERING','核对 Studio 任务、文案与完整视频范围',0)
        local pm=assert(app:GetProjectManager(),'PROJECT_MANAGER_UNAVAILABLE')
        local project=assert(pm:GetCurrentProject(),'PROJECT_UNAVAILABLE')
        local timeline=assert(project:GetCurrentTimeline(),'TIMELINE_UNAVAILABLE')
        local timelineID=timeline:GetUniqueId()
        local function guard()
            local active=pm:GetCurrentProject();local t=active and active:GetCurrentTimeline()
            assert(active and active:GetName()==p.project_name and t and t:GetName()==p.timeline_name and t:GetUniqueId()==timelineID,'ACTIVE_TIMELINE_CHANGED')
        end
        guard()
        assert(p.project_name=='FlowStudio-'..p.work_date and p.timeline_name=='MAIN-'..p.work_date,'DAILY_NAME_MISMATCH')
        local fps=assert(tonumber(timeline:GetSetting('timelineFrameRate')),'FPS_UNAVAILABLE')
        assert(fps>0 and math.abs(fps-getTimelineFPS(project))<0.001,'FPS_MISMATCH')
        assert(not tostring(timeline:GetStartTimecode()):find(';',1,true),'DROP_FRAME_NOT_SUPPORTED')
        local origin=timeline:GetStartFrame();local jobs={};local previousEnd=nil;local batchMarkerStart=nil
        local usedImportMarkerFrames={};local importMarkerMatched=0;local importMarkerMissing=0
        -- Re-identification is additive: keep existing blade cuts, but replace the old automatic
        -- red/orange review markers. Old red candidate ranges are carried into the new cut plan so
        -- cleanup still removes them later; blue user markers and import markers are never touched.
        local carriedCandidates,carriedByVideo={},{}
        if reanalyze then
            local deleteFrames={}
            for frame,marker in pairs(timeline:GetMarkers() or {}) do
                local info=type(marker)=='table' and tag(marker.customData) or {}
                if info.batch_id==bid then
                    if marker.color=='Red' and info.candidate_id then
                        local a,b=tonumber(info.start),tonumber(info['end'])
                        if a and b and a<b and (info.type=='HEAD' or info.type=='TAIL') and info.video_id then
                            local old={s=a,e=b,kind=info.type,video_id=info.video_id}
                            carriedCandidates[#carriedCandidates+1]=old
                            carriedByVideo[info.video_id]=carriedByVideo[info.video_id] or {}
                            carriedByVideo[info.video_id][#carriedByVideo[info.video_id]+1]=old
                        end
                        deleteFrames[#deleteFrames+1]=frame
                    elseif info.status=='MANUAL_EDIT' then
                        deleteFrames[#deleteFrames+1]=frame
                    end
                end
            end
            for _,frame in ipairs(deleteFrames) do assert(timeline:DeleteMarkerAtFrame(frame),'REANALYZE_MARKER_CLEAR_FAILED') end
            assert(pm:SaveProject(),'SAVE_REANALYZE_MARKERS_FAILED')
        end
        local function snapshot()
            local rows={}
            for _,kind in ipairs({'video','audio'}) do
                for track=1,timeline:GetTrackCount(kind) do
                    for _,item in ipairs(assert(timeline:GetItemListInTrack(kind,track),'TRACK_READ_FAILED')) do
                        rows[#rows+1]=kind..':'..track..':'..item:GetUniqueId()..':'..item:GetStart()..':'..item:GetEnd()
                    end
                end
            end
            table.sort(rows);return table.concat(rows,'\n')
        end
        local validationSkipped={}
        for i=1,state.total do
            local valid,why=pcall(function()
            local prefix='v'..i..'_';local id=assert(p[prefix..'id']);assert(id:match('^%d+$'),'INVALID_VIDEO_ID')
            local s,e=assert(tonumber(p[prefix..'start'])),assert(tonumber(p[prefix..'end']))
            assert(e>s and s>=origin and (not previousEnd or s>=previousEnd+50),'INVALID_VIDEO_RANGE');previousEnd=e
            local marker=resolveImportMarker(timeline:GetMarkers() or {},origin,bid,id,s,e,usedImportMarkerFrames)
            if marker then
                importMarkerMatched=importMarkerMatched+1
                local markerAbs=marker.absFrame
                batchMarkerStart=(not batchMarkerStart or markerAbs<batchMarkerStart) and markerAbs or batchMarkerStart
            else
                -- Do not abort only because a COMPLETE marker is absent/duplicated.
                -- The clip range below is authoritative and is still validated frame-by-frame.
                importMarkerMissing=importMarkerMissing+1
            end
            local segment={s=s,e=e};local track=1
            local allClips=collectClipsInSegment(timeline,track,segment);local last=s
            for _,clip in ipairs(allClips) do assert(clip.s==last and clip.e<=e,'CLIP_RANGE_CHANGED');last=clip.e end
            assert(#allClips>0 and last==e,'VIDEO_RANGE_INCOMPLETE')
            local skippedSources={}
            for skipIndex=1,tonumber(p[prefix..'skip_source_count'] or 0) do
                skippedSources[assert(p[prefix..'skip_source_'..skipIndex])]=true
            end
            local clips={}
            for _,clip in ipairs(allClips) do
                local excluded=false
                if next(skippedSources) then
                    local media=clip.item:GetMediaPoolItem()
                    local source=platform.path(media and media:GetClipProperty('File Path') or '')
                    if skippedSources[source] then excluded=true end
                end
                if reanalyze then
                    for _,old in ipairs(carriedByVideo[id] or {}) do
                        if clip.s==old.s and clip.e==old.e then excluded=true;break end
                    end
                end
                if not excluded then clips[#clips+1]=clip end
            end
            assert(#clips>0,'REANALYZE_NO_REMAINING_V1_CLIPS: '..id)
            -- V2/V3/... are overlays and are deliberately invisible to auto-edit analysis.
            for a=1,timeline:GetTrackCount('audio') do
                for _,item in ipairs(timeline:GetItemListInTrack('audio',a) or {}) do
                    local as,ae=item:GetStart(),item:GetEnd()
                    if as<e and ae>s then
                        local matching=false;for _,clip in ipairs(allClips) do if clip.s==as and clip.e==ae then matching=true end end
                        assert(matching,'UNRELATED_AUDIO_OVERLAP: '..id)
                    end
                end
            end
            local textPath=base..'/manuscripts/video_'..id..'.txt'
            assert(p[prefix..'manuscript_path']==textPath,'MANUSCRIPT_PATH_MISMATCH')
            jobs[#jobs+1]={id=id,segment=segment,track=track,clips=clips,allClips=allClips,manuscriptPath=textPath,manuscript=readText(textPath)}
            end)
            if not valid then
                local prefix='v'..i..'_';local id=p[prefix..'id'] or tostring(i)
                local skipped={id=id,segment={s=tonumber(p[prefix..'start']) or origin,e=tonumber(p[prefix..'end']) or origin},deferred=true,deferReason=tostring(why),manuscriptPath=p[prefix..'manuscript_path'] or ''}
                validationSkipped[#validationSkipped+1]=skipped
                writePairs(base..'/video_'..id..'_alignment.ini',{video_id=id,status='MANUAL_EDIT_REQUIRED',reason=skipped.deferReason,batch_id=bid,task_id=taskId})
                pulse('AUDIO_RENDERING','视频 '..id..' 检查未通过，已自动跳过，继续其他视频',i)
            end
        end
        if #jobs==0 then
            local ids={};for _,job in ipairs(validationSkipped) do ids[#ids+1]=job.id end
            state.deferred_count=#ids;state.deferred_video_ids=table.concat(ids,',')
            pulse('WAITING_USER_REVIEW','本批视频检查均未通过，已全部跳过，原素材保留',state.total)
            return {stage='WAITING_USER_REVIEW',batch_id=bid,task_id=taskId,project=p.project_name,timeline=p.timeline_name,candidate_count=0,deferred_count=#ids,deferred_video_ids=table.concat(ids,','),manual_edit_count=#ids,manual_edit_video_ids=table.concat(ids,',')}
        end
        local batchStart=jobs[1].segment.s;local batchEnd=jobs[#jobs].segment.e
        for _,job in ipairs(jobs) do batchStart=math.min(batchStart,job.segment.s);batchEnd=math.max(batchEnd,job.segment.e) end
        assert(tonumber(p.batch_start)<=batchStart and tonumber(p.batch_end)>=batchEnd,'BATCH_RANGE_MISMATCH')
        -- Studio's validated batch range is authoritative. Markers are only a secondary anchor.
        local scopeStart=batchStart
        local scopeEnd=assert(tonumber(timeline:GetEndFrame()),'TIMELINE_END_UNAVAILABLE')
        assert(scopeEnd>scopeStart and batchEnd<=scopeEnd,'BATCH_SCOPE_INCOMPLETE')
        if importMarkerMissing>0 then
            local f=assert(io.open(root..'/logs/'..bid..'/autoedit.log','a'))
            f:write(os.date('%Y-%m-%d %H:%M:%S')..' attempt='..attempt..' task='..taskId..' marker_fallback='..importMarkerMissing..' matched='..importMarkerMatched..' tolerance='..IMPORT_MARKER_TOLERANCE_FRAMES..'f\n');f:close()
        end
        local frozen=snapshot()
        if not resume then
        local timelineWav=assert(p.timeline_wav_path,'TIMELINE_WAV_PATH_MISSING')
        local timelineWhisperBase=assert(p.timeline_whisper_base,'TIMELINE_WHISPER_PATH_MISSING')
        assert(timelineWav==base..'/audio/timeline.wav','TIMELINE_WAV_PATH_MISMATCH')
        assert(timelineWhisperBase==base..'/whisper/timeline','TIMELINE_WHISPER_PATH_MISMATCH')

        -- Do NOT export from batch start all the way to Timeline end. That can create a very long
        -- WAV and hurt Whisper accuracy. Split the current Studio batch into short analysis WAVs,
        -- each containing at most AUDIO_BATCH_VIDEO_LIMIT complete videos.
        local audioBatches={}
        local first=1
        while first<=#jobs do
            local last=math.min(#jobs,first+AUDIO_BATCH_VIDEO_LIMIT-1)
            local partIndex=#audioBatches+1
            local stem=(partIndex==1) and 'timeline' or string.format('timeline_part_%03d',partIndex)
            local part={
                index=partIndex,
                first=first,
                last=last,
                s=jobs[first].segment.s,
                e=jobs[last].segment.e,
                stem=stem,
                wav=base..'/audio/'..stem..'.wav',
                whisperBase=base..'/whisper/'..stem,
                manuscriptMap=base..'/manuscripts/'..stem..'_map.ini',
                manuscriptBundle=base..'/manuscripts/'..stem..'_bundle.txt',
                jobs={},
                videoIds={}
            }
            assert(part.e>part.s and part.s>=batchStart and part.e<=batchEnd,'AUDIO_BATCH_RANGE_INVALID')
            local bundleRows={}
            for n=first,last do
                local job=jobs[n]
                part.jobs[#part.jobs+1]=job
                part.videoIds[#part.videoIds+1]=job.id
                job.audioBatch=part
                job.audioBatchIndex=partIndex
                job.wav=part.wav
                job.whisperBase=part.whisperBase
                bundleRows[#bundleRows+1]='[VIDEO '..job.id..']\n'..job.manuscript..'\n[/VIDEO '..job.id..']'
            end
            -- Persist the exact text membership of this WAV batch. This is diagnostic/audit data;
            -- actual alignment below still uses each video's own Flow Studio manuscript.
            local bf=assert(io.open(part.manuscriptBundle..'.tmp','w'),'WRITE_FAILED: '..part.manuscriptBundle)
            bf:write(table.concat(bundleRows,'\n\n'));bf:close()
            assert(os.rename(part.manuscriptBundle..'.tmp',part.manuscriptBundle),'PUBLISH_FAILED')
            writePairs(part.manuscriptMap,{
                part=partIndex,parts=math.ceil(#jobs/AUDIO_BATCH_VIDEO_LIMIT),
                first_video=jobs[first].id,last_video=jobs[last].id,
                video_count=#part.jobs,video_ids=table.concat(part.videoIds,','),
                wav=part.wav,manuscript_bundle=part.manuscriptBundle,
                text_source='Flow Studio per-video manuscripts',audio_batch_limit=AUDIO_BATCH_VIDEO_LIMIT,build='V1.7.8'
            })
            audioBatches[#audioBatches+1]=part
            first=last+1
        end
        assert(#audioBatches>0,'AUDIO_BATCH_EMPTY')
        assert(not project:IsRenderingInProgress(),'RENDER_ALREADY_RUNNING')
        assert(p.wav_preset=='FlowStudio_WAV16' and project:LoadRenderPreset(p.wav_preset),'WAV_PRESET_MISSING: 请先在达芬奇保存 FlowStudio_WAV16（WAV / Linear PCM / 16-bit）预设')

        for partNo,part in ipairs(audioBatches) do
            guard();pulse('AUDIO_RENDERING','分批导出 WAV：第 '..partNo..'/'..#audioBatches..' 批（视频 '..jobs[part.first].id..' - '..jobs[part.last].id..'，最多 '..AUDIO_BATCH_VIDEO_LIMIT..' 个）',part.first-1)
            local renderJob={id=part.stem,segment={s=part.s,e=part.e},wav=part.wav}
            if test.render then
                test.render(renderJob)
            else
                -- Never reuse output from a previous execution of this attempt.
                local previousWav=io.open(part.wav,'rb')
                if previousWav then previousWav:close();error('WAV_OUTPUT_ALREADY_EXISTS: '..part.wav..'；请从 Studio 创建新的分析任务') end
                pcall(function() timeline:ClearMarkInOut('all') end)
                assert(project:SetCurrentRenderMode(1),'RENDER_SINGLE_CLIP_MODE_FAILED')
                assert(project:SetRenderSettings({SelectAllFrames=false,MarkIn=part.s,MarkOut=part.e-1,TargetDir=base..'/audio',CustomName=part.stem,ExportVideo=false,ExportAudio=true}),'WAV_RENDER_SETTINGS_FAILED')
                local renderID=assert(project:AddRenderJob(),'ADD_WAV_RENDER_FAILED')
                part.renderID=renderID
                local renderIni=(#audioBatches==1) and (base..'/timeline_render.ini') or (base..string.format('/timeline_render_part_%03d.ini',partNo))
                writePairs(renderIni,{task_id=taskId,render_id=renderID,status='QUEUED',part=partNo,parts=#audioBatches,start=part.s,['end']=part.e,expected_videos=#part.jobs,first_video=jobs[part.first].id,last_video=jobs[part.last].id,scope='Exact audio analysis batch',manuscript_map=part.manuscriptMap,audio_batch_limit=AUDIO_BATCH_VIDEO_LIMIT,build='V1.7.8'})
                assert(project:StartRendering({renderID}),'START_WAV_RENDER_FAILED')
                local started=os.time();local idlePolls=0
                while true do
                    guard();pulse('AUDIO_RENDERING','分批导出 WAV：第 '..partNo..'/'..#audioBatches..' 批（视频 '..jobs[part.first].id..' - '..jobs[part.last].id..'）',part.first-1)
                    local info=project:GetRenderJobStatus(renderID) or {};local status=tostring(info.JobStatus or '')
                    local kind=renderStatusKind(status)
                    if kind=='complete' then break end
                    assert(kind~='failed' and kind~='cancelled','WAV_RENDER_FAILED: '..status)
                    if not project:IsRenderingInProgress() then
                        os.execute('/bin/sleep 0.25')
                        local finalInfo=project:GetRenderJobStatus(renderID) or {};local finalStatus=tostring(finalInfo.JobStatus or '')
                        if renderStatusKind(finalStatus)=='complete' then break end
                        local finalKind=renderStatusKind(finalStatus)
                        assert(finalKind~='failed' and finalKind~='cancelled','WAV_RENDER_FAILED: '..finalStatus)
                        idlePolls=idlePolls+1
                        assert(idlePolls<5,'WAV_RENDER_NOT_COMPLETE: '..(finalStatus~='' and finalStatus or status))
                    else
                        idlePolls=0
                    end
                    if os.time()-started>1800 then project:StopRendering();error('WAV_RENDER_TIMEOUT') end
                    os.execute('/bin/sleep 1')
                end
                writePairs(renderIni,{task_id=taskId,render_id=renderID,status='COMPLETE',part=partNo,parts=#audioBatches,start=part.s,['end']=part.e,expected_videos=#part.jobs,first_video=jobs[part.first].id,last_video=jobs[part.last].id,scope='Exact audio analysis batch',manuscript_map=part.manuscriptMap,audio_batch_limit=AUDIO_BATCH_VIDEO_LIMIT,build='V1.7.8'})
                local f=assert(io.open(part.wav,'rb'),'WAV_OUTPUT_MISSING: '..part.wav..'；请检查 WAV 预设的格式和文件名');f:close()
            end
        end
        if #audioBatches>1 then
            writePairs(base..'/timeline_render.ini',{task_id=taskId,status='COMPLETE',parts=#audioBatches,expected_videos=state.total,start=batchStart,['end']=batchEnd,scope='Split WAV analysis; max 20 complete videos per part; manuscript map locked to each WAV',audio_batch_limit=AUDIO_BATCH_VIDEO_LIMIT,build='V1.7.8'})
        end

        assert(snapshot()==frozen,'TIMELINE_CHANGED_DURING_ANALYSIS')
        if not test.whisper then
            for partNo,part in ipairs(audioBatches) do
                guard();pulse('WHISPER_RUNNING','Whisper 分批识别：第 '..partNo..'/'..#audioBatches..' 批（视频 '..jobs[part.first].id..' - '..jobs[part.last].id..'）',part.first-1)
                os.remove(part.whisperBase..'.exit');os.remove(part.whisperBase..'.error');os.remove(part.whisperBase..'.srt');os.remove(part.whisperBase..'.pid')
                local batchTimeout=tonumber(p.whisper_timeout) or 600
                local args={p.python_path,p.whisper_runner,'--cli',p.whisper_cli_path,'--model',p.whisper_model_path,'--wav',part.wav,'--output',part.whisperBase,'--language','sw','--duration',tostring((part.e-part.s)/fps),'--fps',tostring(fps),'--timeout',tostring(batchTimeout)}
                for n,arg in ipairs(args) do args[n]=shellQuote(assert(arg,'WHISPER_CONFIG_MISSING')) end
                local launch='('..table.concat(args,' ')..' > '..shellQuote(part.whisperBase..'.launcher.log')..' 2>&1 & echo $! > '..shellQuote(part.whisperBase..'.pid')..')'
                os.execute(launch)
                local started=os.time();local batchOK=false;local batchReason=nil
                while true do
                    local exit=io.open(part.whisperBase..'.exit','r')
                    if exit then
                        local code=tonumber(exit:read('*a'));exit:close()
                        if code==0 then batchOK=true else batchReason='WHISPER_BATCH_EXIT_'..tostring(code or 'UNKNOWN')..': '..trim(readTextOptional(part.whisperBase..'.error')) end
                        break
                    end
                    if os.time()-started>=batchTimeout+30 then
                        batchReason='WHISPER_BATCH_TIMEOUT_'..tostring(batchTimeout+30)..'S'
                        terminatePidFile(part.whisperBase..'.pid')
                        break
                    end
                    guard();pulse('WHISPER_RUNNING','Whisper 分批识别：第 '..partNo..'/'..#audioBatches..' 批',part.first-1);os.execute('/bin/sleep 1')
                end
                if batchOK then
                    local err;part.words,err=parseSRT(part.whisperBase..'.srt')
                    if not part.words or #part.words==0 then batchReason=err or 'WHISPER_BATCH_NO_WORDS';batchOK=false end
                end
                if not batchOK then
                    -- Do not let one problematic audio batch stop all videos. Empty words force each
                    -- member video through the bounded single-video path below, where a bad clip can
                    -- time out independently and be marked for manual editing.
                    part.words={}
                    part.whisperFailedReason=batchReason or 'WHISPER_BATCH_FAILED'
                    pulse('WHISPER_RUNNING','本批次整体识别异常，改为逐个视频识别；单个失败会自动跳过：'..part.whisperFailedReason,part.first-1)
                end
            end
        end

        local manualEditJobs={}
        for _,job in ipairs(validationSkipped) do manualEditJobs[#manualEditJobs+1]=job end
        local maxVideoRetries=tonumber(p.max_video_retries) or MAX_SINGLE_VIDEO_RETRIES
        maxVideoRetries=math.max(0,math.min(2,math.floor(maxVideoRetries)))
        local singleRetryTimeout=tonumber(p.single_video_retry_timeout) or SINGLE_VIDEO_RETRY_TIMEOUT
        singleRetryTimeout=math.max(30,math.min(300,math.floor(singleRetryTimeout)))
        local function passes(a)
            if not a or not a.aligned or a.aligned.confidence<0.65 or a.aligned.coverage<0.75 or a.unmatched~=0 then return false end
            for _,r in ipairs(a.results or {}) do if r.confidence<0.65 then return false end end
            return true
        end
        local silenceProbePath=base..'/silence_probe_v1_7_7.py'
        if not test.silenceProbe then ensureSilenceProbe(silenceProbePath) end
        for i,job in ipairs(jobs) do
            guard();local words,err
            -- Scan EVERY small imported clip independently. This is intentionally separate from
            -- Whisper: text alignment decides what was said; audio-energy decides where each small
            -- clip actually starts/ends. Probe failure is non-fatal and falls back to Whisper only.
            job.clipEdgeSilence={}
            if test.silenceProbe then
                local injected=test.silenceProbe(job,fps)
                if type(injected)=='table' then
                    if injected[1] then job.clipEdgeSilence=injected
                    elseif #job.clips==1 then job.clipEdgeSilence[1]=injected end
                end
            elseif p.python_path and job.audioBatch then
                local part=job.audioBatch
                for clipIndex,clip in ipairs(job.clips) do
                    local relStart=(clip.s-part.s)/fps
                    local duration=(clip.e-clip.s)/fps
                    local probeOut=base..'/whisper/video_'..job.id..'_clip_'..string.format('%03d',clipIndex)..'_edge_silence.ini'
                    local edge,edgeErr=probeEdgeSilence(p.python_path,silenceProbePath,part.wav,relStart,duration,probeOut)
                    local lf=io.open(root..'/logs/'..bid..'/autoedit.log','a')
                    if edge then
                        job.clipEdgeSilence[clipIndex]=edge
                        if lf then lf:write(os.date('%Y-%m-%d %H:%M:%S')..' video='..job.id..' clip='..clipIndex..'/'..#job.clips..' edge_silence head='..string.format('%.3f',edge.headSilence)..' tail='..string.format('%.3f',edge.tailSilence)..' active='..string.format('%.3f',edge.activeStart)..'-'..string.format('%.3f',edge.activeEnd)..' peak_db='..tostring(edge.peakDb or '')..' threshold_used_db='..tostring(edge.thresholdUsedDb or EDGE_SILENCE_THRESHOLD_DB)..'\n');lf:close() end
                    else
                        if lf then lf:write(os.date('%Y-%m-%d %H:%M:%S')..' video='..job.id..' clip='..clipIndex..'/'..#job.clips..' edge_silence_fallback='..tostring(edgeErr)..'\n');lf:close() end
                    end
                end
            end
            if test.whisper then
                words,err=test.whisper(job)
            else
                local part=assert(job.audioBatch,'AUDIO_BATCH_NOT_ASSIGNED')
                assert(job.audioBatchIndex==part.index,'AUDIO_BATCH_TEXT_MAP_MISMATCH: '..job.id)
                assert(job.segment.s>=part.s and job.segment.e<=part.e,'AUDIO_BATCH_VIDEO_OUT_OF_RANGE: '..job.id)
                local rangeStart=(job.segment.s-part.s)/fps
                local rangeEnd=(job.segment.e-part.s)/fps
                words=sliceTimelineWords(part.words,rangeStart,rangeEnd)
            end
            words=words or {}
            assert(#words*#tokenizeText(job.manuscript)<=500000,'ALIGNMENT_SIZE_LIMIT')
            whisperRunner=function() return words end
            pulse('TEXT_ALIGNING','使用 Studio 正确文案核对并计算切点：'..job.id,i)
            local analysis,why=analyzeOneVideo(job,fps)
            local retryNo=0
            local lastReason=why or '文案匹配不足'
            while not passes(analysis) and not test.whisper and retryNo<maxVideoRetries do
                retryNo=retryNo+1
                local retryBase=base..'/whisper/video_'..job.id..'_retry_'..retryNo
                local part=assert(job.audioBatch,'AUDIO_BATCH_NOT_ASSIGNED')
                assert(job.audioBatchIndex==part.index,'AUDIO_BATCH_TEXT_MAP_MISMATCH: '..job.id)
                assert(job.segment.s>=part.s and job.segment.e<=part.e,'AUDIO_BATCH_VIDEO_OUT_OF_RANGE: '..job.id)
                -- Only retry this exact video. A short hard timeout prevents one bad clip from
                -- keeping the whole automatic-edit batch in WHISPER_RUNNING indefinitely.
                os.remove(retryBase..'.exit');os.remove(retryBase..'.error');os.remove(retryBase..'.srt');os.remove(retryBase..'.pid')
                local args={p.python_path,p.whisper_runner,'--cli',p.whisper_cli_path,'--model',p.whisper_model_path,'--wav',part.wav,'--output',retryBase,'--language','sw','--start',tostring((job.segment.s-part.s)/fps),'--duration',tostring((job.segment.e-job.segment.s)/fps),'--fps',tostring(fps),'--timeout',tostring(singleRetryTimeout)}
                for n,arg in ipairs(args) do args[n]=shellQuote(assert(arg)) end
                local launch='('..table.concat(args,' ')..' > '..shellQuote(retryBase..'.launcher.log')..' 2>&1 & echo $! > '..shellQuote(retryBase..'.pid')..')'
                os.execute(launch)
                local started=os.time();local retryOK=false;local retryReason=nil
                while true do
                    local done=io.open(retryBase..'.exit','r')
                    if done then
                        local code=tonumber(done:read('*a'));done:close()
                        if code==0 then retryOK=true else retryReason='WHISPER_RETRY_EXIT_'..tostring(code or 'UNKNOWN') end
                        break
                    end
                    if os.time()-started>=singleRetryTimeout then
                        retryReason='WHISPER_RETRY_TIMEOUT_'..singleRetryTimeout..'S'
                        local pf=io.open(retryBase..'.pid','r')
                        if pf then local pid=tonumber(trim(pf:read('*a')));pf:close();if pid then os.execute('pkill -TERM -P '..pid..' >/dev/null 2>&1; kill -TERM '..pid..' >/dev/null 2>&1') end end
                        break
                    end
                    guard();pulse('WHISPER_RUNNING','匹配不足，单独重识别视频 '..job.id..'（'..retryNo..'/'..maxVideoRetries..'）',i);os.execute('/bin/sleep 1')
                end
                if not retryOK then
                    local errorText=nil;local ef=io.open(retryBase..'.error','r');if ef then errorText=trim(ef:read('*a'));ef:close() end
                    lastReason=retryReason or (errorText~='' and errorText or nil) or 'WHISPER_RETRY_FAILED'
                    break
                end
                words,err=parseSRT(retryBase..'.srt')
                if not words or #words==0 then
                    lastReason=err or 'WHISPER_RETRY_EMPTY'
                    break
                end
                assert(#words*#tokenizeText(job.manuscript)<=500000,'ALIGNMENT_SIZE_LIMIT')
                whisperRunner=function() return words end
                analysis,why=analyzeOneVideo(job,fps)
                lastReason=why or '文案匹配仍不足'
            end
            if passes(analysis) then
                job.analysis=analysis
                writePairs(base..'/video_'..job.id..'_alignment.ini',{video_id=job.id,batch_id=bid,task_id=taskId,status='COMPLETE',audio_part=assert(job.audioBatchIndex),audio_wav=assert(job.wav),manuscript_path=assert(job.manuscriptPath),text_source='Flow Studio',confidence=analysis.aligned.confidence,coverage=analysis.aligned.coverage,unmatched=analysis.unmatched,candidate_count=analysis.cutCount,retries=retryNo,edge_scan_mode='PER_SMALL_CLIP',edge_scan_count=#job.clips,edge_scan_success_count=(function() local n=0;for _ in pairs(job.clipEdgeSilence or {}) do n=n+1 end;return n end)(),silence_threshold_floor_db=EDGE_SILENCE_THRESHOLD_DB,build='V1.7.8'})
            else
                job.deferred=true
                job.deferReason=tostring(lastReason or 'TEXT_ALIGNMENT_FAILED')
                manualEditJobs[#manualEditJobs+1]=job
                writePairs(base..'/video_'..job.id..'_alignment.ini',{video_id=job.id,batch_id=bid,task_id=taskId,status='MANUAL_EDIT_REQUIRED',audio_part=assert(job.audioBatchIndex),audio_wav=assert(job.wav),manuscript_path=assert(job.manuscriptPath),text_source='Flow Studio',reason=job.deferReason,retries=retryNo,build='V1.7.8'})
                pulse('TEXT_ALIGNING','视频 '..job.id..' 识别未通过，已自动跳过；稍后用橙色标记供手动剪辑',i)
            end
        end
        if #manualEditJobs>0 then
            local d={batch_id=bid,attempt_id=attempt,task_id=taskId,status='MANUAL_EDIT_REQUIRED',count=#manualEditJobs,marker_color=MANUAL_EDIT_MARKER_COLOR,build='V1.7.8'}
            local ids={}
            for n,job in ipairs(manualEditJobs) do ids[#ids+1]=job.id;d['v'..n..'_id']=job.id;d['v'..n..'_reason']=job.deferReason;d['v'..n..'_manuscript_path']=job.manuscriptPath;d['v'..n..'_start']=job.segment.s;d['v'..n..'_end']=job.segment.e end
            d.video_ids=table.concat(ids,',')
            writePairs(base..'/manual_edit_videos.ini',d)
            -- Keep the historical diagnostic filename for Studio compatibility, but mark it as
            -- MANUAL_EDIT_REQUIRED so this script no longer describes the clip as a later-batch retry.
            writePairs(base..'/deferred_videos.ini',d)
            writePairs(root..'/v0_5_0/batches/'..bid..'/autoedit_deferred.ini',d)
            state.deferred_count=#manualEditJobs;state.deferred_video_ids=d.video_ids
            state.manual_edit_count=#manualEditJobs;state.manual_edit_video_ids=d.video_ids
        end
        end -- normal analysis; recovery uses the saved plan below
        guard();assert(snapshot()==frozen,'TIMELINE_CHANGED_DURING_ANALYSIS')
        local cuts,candidates={},{}
        if resume then
            validateResumeSources(timeline,jobs,root,bid)
            local plan=readPairs(base..'/cut_plan.ini')
            assert(plan.task_id==taskId and plan.attempt_id==attempt and plan.batch_id==bid,'RESUME_PLAN_ID_MISMATCH')
            local byId={};for _,job in ipairs(jobs) do byId[job.id]=job end
            local count=assert(tonumber(plan.candidate_count),'RESUME_PLAN_MISSING')
            assert(tonumber(plan.scope_start)==scopeStart and plan.scope_rule=='BATCH_MARKER_TO_TIMELINE_END','RESUME_BATCH_SCOPE_CHANGED')
            for i=1,count do
                local pre='c'..i..'_';local job=assert(byId[plan[pre..'video_id']],'RESUME_PLAN_VIDEO_MISMATCH')
                local a,b=tonumber(plan[pre..'start']),tonumber(plan[pre..'end']);local kind=plan[pre..'type']
                assert(a and b and a<b and a>=job.segment.s and b<=job.segment.e and (kind=='HEAD' or kind=='TAIL'),'RESUME_PLAN_RANGE_INVALID')
                candidates[#candidates+1]={s=a,e=b,kind=kind,job=job}
                local frame=kind=='HEAD' and b or a
                cuts[#cuts+1]={frame=frame,job=job}
            end
        else
        if reanalyze and #carriedCandidates>0 then
            local byId={};for _,job in ipairs(jobs) do byId[job.id]=job end
            for _,old in ipairs(carriedCandidates) do
                local job=byId[old.video_id]
                local item=job and findItemByRange(timeline,job.track,old.s,old.e) or nil
                if job and item and old.s>=job.segment.s and old.e<=job.segment.e then
                    candidates[#candidates+1]={s=old.s,e=old.e,kind=old.kind,job=job,carried=true}
                end
            end
        end
        for _,job in ipairs(jobs) do
            if job.analysis then
            for _,r in ipairs(job.analysis.results) do
                for _,part in ipairs({{r.headFrames,r.clip.s,r.keepStart,'HEAD'},{r.tailFrames,r.keepEnd,r.clip.e,'TAIL'}}) do
                    if part[1]>0 then
                        cuts[#cuts+1]={frame=part[4]=='HEAD' and part[3] or part[2],job=job}
                        candidates[#candidates+1]={s=part[2],e=part[3],kind=part[4],job=job}
                    end
                end
            end
            end -- job.analysis; manual-edit videos are intentionally left untouched
        end
        local deferredIds={};for _,job in ipairs(jobs) do if job.deferred then deferredIds[#deferredIds+1]=job.id end end
        local carriedCount=0;for _,c in ipairs(candidates) do if c.carried then carriedCount=carriedCount+1 end end
        local plan={batch_id=bid,attempt_id=attempt,task_id=taskId,candidate_count=#candidates,carried_candidate_count=carriedCount,reanalyze=tostring(reanalyze),deferred_count=#deferredIds,deferred_video_ids=table.concat(deferredIds,','),scope_start=scopeStart,scope_end=scopeEnd,scope_rule='BATCH_MARKER_TO_TIMELINE_END'}
        for i,c in ipairs(candidates) do plan['c'..i..'_video_id']=c.job.id;plan['c'..i..'_start']=c.s;plan['c'..i..'_end']=c.e;plan['c'..i..'_type']=c.kind end
        writePairs(base..'/cut_plan.ini',plan)
        end
        if #cuts>0 then
            assert((test.openEdit or openEditPage)(app),'OPEN_EDIT_PAGE_FAILED')
            if not test.openEdit then
                local ready=false
                for i=1,20 do if app:GetCurrentPage()=='edit' then ready=true;break end;os.execute('/bin/sleep 0.1') end
                assert(ready,'EDIT_PAGE_NOT_READY')
            end
        end
        guard();assert(snapshot()==frozen,'TIMELINE_CHANGED_BEFORE_CUTTING')
        if not test.blade then
            for _,kind in ipairs({'video','audio'}) do
                for track=1,timeline:GetTrackCount(kind) do
                    assert(not timeline:GetIsTrackLocked(kind,track),'TRACK_LOCKED: '..kind..' '..track)
                end
            end
        end
        cutting=true;local manualEditCount=0;for _,job in ipairs(jobs) do if job.deferred then manualEditCount=manualEditCount+1 end end;pulse('CUTTING','可识别视频开始切刀；已跳过 '..manualEditCount..' 个识别失败视频，稍后标橙色供手动剪辑',0)
        table.sort(cuts,function(a,b) return a.frame<b.frame end)
        -- 切点升序；前面的切刀只会把素材一分为二，不改变后面切点处哪些轨道有素材，
        -- 所以各轨道素材范围只扫描一次（视频轨、音轨都一样）。
        local trackRanges,expectedCount={video={},audio={}},{video={},audio={}}
        for _,kind in ipairs({'video','audio'}) do
            for track=1,timeline:GetTrackCount(kind) do
                local list={}
                for _,item in ipairs(timeline:GetItemListInTrack(kind,track) or {}) do list[#list+1]={item:GetStart(),item:GetEnd()} end
                trackRanges[kind][track]=list;expectedCount[kind][track]=#list
            end
        end
        local fastConfirm=not test.blade
        for i,cut in ipairs(cuts) do
            guard();pulse('CUTTING','执行并核验切刀 '..i..' / '..#cuts,0)
            local crossing={video={},audio={}}
            for _,kind in ipairs({'video','audio'}) do
                for track,list in pairs(trackRanges[kind]) do
                    for _,r in ipairs(list) do
                        if r[1]<cut.frame and r[2]>cut.frame then crossing[kind][track]=true;break end
                    end
                end
            end
            local audioTracks=crossing.audio
            cut.audioTracks=audioTracks
            if not test.openEdit then assert(app:GetCurrentPage()=='edit','EDIT_PAGE_CHANGED') end
            local already=false
            if resume then
                already=cutBoundary(timeline,'video',cut.job.track,cut.frame)
                for track in pairs(audioTracks) do already=already and cutBoundary(timeline,'audio',track,cut.frame) end
            end
            local blade=not (resume and already)
            if blade then
                local success,why=(test.blade or movePlayheadAndBlade)(timeline,cut.frame,fps);assert(success,why)
            end
            if fastConfirm then
                -- 快速核验：只比较素材个数（每个被切到的轨道应 +1），不逐个读取起止帧。
                if blade then
                    for _,kind in ipairs({'video','audio'}) do
                        for track in pairs(crossing[kind]) do expectedCount[kind][track]=expectedCount[kind][track]+1 end
                    end
                end
                local confirmed=false
                for poll=1,100 do
                    confirmed=true
                    for _,kind in ipairs({'video','audio'}) do
                        for track in pairs(crossing[kind]) do
                            if #(timeline:GetItemListInTrack(kind,track) or {})~=expectedCount[kind][track] then confirmed=false;break end
                        end
                        if not confirmed then break end
                    end
                    if confirmed then break end
                    if poll<100 then os.execute('/bin/sleep 0.02') end
                end
                assert(confirmed,'CUT_NOT_CONFIRMED: frame='..cut.frame..' 切刀未确认（素材个数未增加）；保留现场，不会重复发送快捷键')
            else
                confirmCut(timeline,cut.frame,cut.job.track,audioTracks,guard)
            end
        end
        closeBladeProc()
        if fastConfirm then
            -- 完整边界核验：每条轨道只读取一遍素材，其后全部在本地比较，所有切点逐一确认。
            guard();pulse('CUTTING','核验全部切点 '..#cuts,0)
            local actual={video={},audio={}}
            for _,kind in ipairs({'video','audio'}) do
                for track in pairs(trackRanges[kind]) do
                    local list={}
                    for _,item in ipairs(timeline:GetItemListInTrack(kind,track) or {}) do list[#list+1]={item:GetStart(),item:GetEnd()} end
                    actual[kind][track]=list
                end
            end
            local function boundaryOK(kind,track,frame)
                local left,right,cross=false,false,false
                for _,r in ipairs(actual[kind][track] or {}) do
                    if r[2]==frame then left=true end
                    if r[1]==frame then right=true end
                    if r[1]<frame and r[2]>frame then cross=true end
                end
                return left and right and not cross
            end
            for _,cut in ipairs(cuts) do
                assert(boundaryOK('video',cut.job.track,cut.frame),'CUT_NOT_CONFIRMED: frame='..cut.frame..' 视频切刀未确认；保留现场')
                for track in pairs(cut.audioTracks or {}) do
                    assert(boundaryOK('audio',track,cut.frame),'AUDIO_CUT_NOT_CONFIRMED: frame='..cut.frame..' audio_track='..track..' 视频已切开但音频未同步；保留现场')
                end
            end
        end
        for i,c in ipairs(candidates) do
            guard();local item=findItemByRange(timeline,c.job.track,c.s,c.e)
            assert(item and item:GetStart()==c.s and item:GetEnd()==c.e,'CANDIDATE_RANGE_NOT_CONFIRMED')
            local markers=timeline:GetMarkers() or {};local frame=c.s-origin
            for oldFrame,marker in pairs(markers) do
                local data=type(marker)=='table' and tag(marker.customData) or {}
                if data.candidate_id==attempt..'_'..i then
                    assert(timeline:DeleteMarkerAtFrame(oldFrame),'CANDIDATE_MARKER_UPDATE_FAILED')
                    markers[oldFrame]=nil
                end
            end
            while markers[frame] and frame<c.e-origin do frame=frame+1 end
            assert(frame<c.e-origin,'NO_FREE_CANDIDATE_MARKER')
            local custom='FLOWSTUDIO|batch_id='..bid..'|video_id='..c.job.id..'|type='..c.kind..'|candidate_id='..attempt..'_'..i..'|start='..c.s..'|end='..c.e
            assert(timeline:AddMarker(frame,'Red','待检查 '..c.kind,'批次 '..bid..' / 视频 '..c.job.id,c.e-origin-frame,custom),'CANDIDATE_MARKER_FAILED')
        end
        -- Recognition/alignment failures do not stop the batch. Leave their clips untouched and
        -- mark the complete video range Orange so the operator can jump straight to manual editing.
        for _,job in ipairs(jobs) do
            if job.deferred then
                guard();addManualEditMarker(timeline,origin,bid,attempt,job,job.deferReason)
            end
        end
        assert(pm:SaveProject(),'SAVE_PROJECT_FAILED')
        local manualEditIds={};for _,job in ipairs(validationSkipped) do manualEditIds[#manualEditIds+1]=job.id;pcall(addManualEditMarker,timeline,origin,bid,attempt,job,job.deferReason) end
        for _,job in ipairs(jobs) do if job.deferred then manualEditIds[#manualEditIds+1]=job.id end end
        pulse('WAITING_USER_REVIEW',(reanalyze and '重新识别完成；已保留原切点并补充新的头尾切点；' or '自动剪辑完成；')..'识别失败已跳过 '..#manualEditIds..' 个，橙色 Marker 请手动剪辑',#jobs)
        return {stage='WAITING_USER_REVIEW',project=p.project_name,timeline=p.timeline_name,batch_id=bid,task_id=taskId,candidate_count=#candidates,deferred_count=#manualEditIds,deferred_video_ids=table.concat(manualEditIds,','),manual_edit_count=#manualEditIds,manual_edit_video_ids=table.concat(manualEditIds,','),manual_marker_color=MANUAL_EDIT_MARKER_COLOR}
    end)
    whisperRunner=nil
    if not ok then pulse((cutting or resume) and 'CUTTING_ERROR' or 'ANALYSIS_ERROR',tostring(result));error(result) end
    return result
end
return {run=runBatch,align=alignWithPairs,analyze=analyzeOneVideo,parseSRT=parseSRT,confirmCut=confirmCut}
