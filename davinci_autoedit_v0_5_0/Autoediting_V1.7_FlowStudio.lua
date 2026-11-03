local platformSource=debug.getinfo(1,'S').source:sub(2):gsub('\\','/')
local platform=assert(loadfile(platformSource:match('^(.*)/[^/]+$')..'/FlowStudio_Platform.lua'))()
local os,io,loadfile=platform.os,platform.io,platform.loadfile
if jit and jit.off then pcall(jit.off) end
-- Autoediting V1.8.0 FlowStudio: Speech-Protected per-small-clip alignment + adaptive audio-edge scan.
-- If batch Whisper stalls/fails, the batch falls back to bounded per-video recognition instead of blocking the whole job.
-- If one video still cannot be recognized/aligned after its bounded retry, that video is left untouched and marked Orange for manual editing.
-- Audio analysis is split into groups of at most 20 complete videos. Each batch records the exact
-- Flow Studio manuscript files/video IDs that belong to the same exported WAV, so text alignment
-- can never accidentally use manuscripts from another audio batch.
local HEAD_PAD_SEC,TAIL_PAD_SEC,MIN_TRIM_FRAMES=0.20,0.25,3
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
local function parseFPSValue(v)
    if v == nil then return nil end
    local n = tonumber(v)
    if n then return n end
    local m = tostring(v):match('([%d%.]+)')
    return m and tonumber(m) or nil
end
local function getTimelineFPS(project)
    local fps = parseFPSValue(project:GetSetting("timelineFrameRate"))
    if not fps then fps = parseFPSValue(project:GetSetting("timelinePlaybackFrameRate")) end
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

local function collectClipsInSegment(timeline, trackIndex, segment, cachedItems)
    local clips = {}
    local items = cachedItems or timeline:GetItemListInTrack("video",trackIndex) or {}

    for _,entry in ipairs(items) do
        local item = entry.item or entry
        local s = tonumber(entry.s or item:GetStart())
        local e = tonumber(entry.e or item:GetEnd())

        if s and e and s < segment.e and e > segment.s then
            table.insert(clips,{
                item=item,
                s=s,
                e=e,
                name=entry.name or item:GetName() or "未命名"
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
    -- ASCII-only lowercase: string.lower is locale dependent and can corrupt UTF-8 bytes
    s = tostring(s or ""):gsub("[A-Z]",function(c) return string.char(c:byte()+32) end)
    s = s:gsub("“",""):gsub("”",""):gsub("‘",""):gsub("’","")
    -- keep UTF-8 letters so non-Latin languages (Chinese, Arabic, Russian...) can be aligned
    s = s:gsub("[^%w'\128-\255]","")
    return s
end

local function utf8Codepoint(ch)
    local b=ch:byte(1)
    if b<128 then return b end
    if b<224 then return (b-192)*64+((ch:byte(2) or 128)-128) end
    if b<240 then return (b-224)*4096+((ch:byte(2) or 128)-128)*64+((ch:byte(3) or 128)-128) end
    return 65536
end

-- Case-fold the common two-byte alphabets (Latin-1, Greek, Cyrillic) to lowercase.
local function foldChar(cp,ch)
    local lower
    if cp>=0xC0 and cp<=0xDE and cp~=0xD7 then lower=cp+32
    elseif cp>=0x391 and cp<=0x3A9 then lower=cp+32
    elseif cp>=0x410 and cp<=0x42F then lower=cp+32
    elseif cp>=0x400 and cp<=0x40F then lower=cp+80 end
    if not lower then return ch end
    return string.char(192+math.floor(lower/64),128+lower%64)
end

-- Scripts written without spaces are tokenized per character.
local function isSpacelessScript(cp)
    return (cp>=0x3040 and cp<=0x30FF) or (cp>=0x3400 and cp<=0x9FFF) or (cp>=0xAC00 and cp<=0xD7AF) or (cp>=0x0E00 and cp<=0x0E7F)
end

local function isUnicodePunct(cp)
    return (cp>=0xA1 and cp<=0xBF) or (cp>=0x2000 and cp<=0x206F) or (cp>=0x3000 and cp<=0x303F)
        or (cp>=0xFF01 and cp<=0xFF0F) or (cp>=0xFF1A and cp<=0xFF20) or (cp>=0xFF3B and cp<=0xFF40) or (cp>=0xFF5B and cp<=0xFF65)
end

local function tokenizeText(s)
    local out = {}
    s = tostring(s or ""):gsub("\r"," "):gsub("\n"," ")

    for raw in s:gmatch("[^ \t\r\n]+") do  -- ASCII whitespace only: %S is locale dependent and can split UTF-8 bytes
        local buf = {}
        local function flush()
            if #buf>0 then
                local t = normalizeToken(table.concat(buf))
                if t ~= "" then table.insert(out,t) end
                buf = {}
            end
        end
        for ch in raw:gmatch("[%z\1-\127\194-\244][\128-\191]*") do
            local cp = utf8Codepoint(ch)
            if cp<128 then
                buf[#buf+1]=ch
            elseif isSpacelessScript(cp) then
                flush(); table.insert(out,ch)
            elseif not isUnicodePunct(cp) then
                buf[#buf+1]=foldChar(cp,ch)
            end
        end
        flush()
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
    local EDGE_SKIP=0.35
    local dp,bt={},{}

    for i=0,m do dp[i]={}; bt[i]={} end

    dp[0][0]=0
    for j=1,n do dp[0][j]=j*EDGE_SKIP; bt[0][j]="L" end
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

    local endJ,bestCost=1,dp[m][1]+(n-1)*EDGE_SKIP

    for j=2,n do
        local cost=dp[m][j]+(n-j)*EDGE_SKIP
        if cost<bestCost then
            bestCost=cost
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

    -- Cloud ASR often splits Swahili compound words into two adjacent tokens
    -- (e.g. "Sikujui" -> "Siku" + "juu", "wawili" -> "wa" + "wili", "yageuzwe" -> "ya" + "geuzwe").
    -- Expand matched pairs to include the adjacent half when concatenation improves similarity.
    local usedRj={}
    for _,p in ipairs(pairs) do usedRj[p.rj]=true end
    local extraPairs={}
    for _,p in ipairs(pairs) do
        local mw=manuscript[p.mi]
        if mw and #mw>=4 then
            if p.rj>1 and not usedRj[p.rj-1] then
                local cSim=similarity(mw,recog[p.rj-1].text..recog[p.rj].text)
                if cSim>=p.sim+0.08 and cSim>=0.55 then
                    usedRj[p.rj-1]=true
                    p.sim=cSim
                    table.insert(extraPairs,{mi=p.mi,rj=p.rj-1,sim=cSim})
                end
            end
            if p.rj<n and not usedRj[p.rj+1] then
                local cSim=similarity(mw,recog[p.rj].text..recog[p.rj+1].text)
                if cSim>=p.sim+0.08 and cSim>=0.55 then
                    usedRj[p.rj+1]=true
                    p.sim=cSim
                    table.insert(extraPairs,{mi=p.mi,rj=p.rj+1,sim=cSim})
                end
            end
        end
    end
    for _,ep in ipairs(extraPairs) do
        table.insert(pairs,ep)
    end
    table.sort(pairs,function(a,b) return a.rj<b.rj end)

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

    local clipEdges=job.clipEdgeSilence or {}
    local results={}
    local cutCount=0
    local unmatched=0

    for i,clip in ipairs(job.clips) do
        local matches=clipMatches[i]
        if #matches==0 and perClip[i] and #perClip[i]>0 then
            local fallbackSim=math.max(0.68,(aligned and aligned.avgSimilarity) or 0.70)
            for _,w in ipairs(perClip[i]) do
                table.insert(matches,{word=w,sim=fallbackSim,mi=0})
            end
        end
        local clipStartSec=(clip.s-job.segment.s)/fps
        local clipDur=(clip.e-clip.s)/fps
        local edge=clipEdges[i]

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
            local firstStartSec=firstW.start
            local lastFinishSec=lastW.finish

            -- Protect ALL recognized words in this small clip (including split words and numbers like "1226").
            if perClip[i] and #perClip[i]>0 then
                table.sort(perClip[i],function(a,b) return a.start<b.start end)
                firstStartSec=math.min(firstStartSec,perClip[i][1].start)
                lastFinishSec=math.max(lastFinishSec,perClip[i][#perClip[i]].finish)
            end

            -- If ASR stretched the final word's end timestamp across trailing silence (>0.90s single-word span),
            -- cap it using the acoustic voice end so true trailing silence can still be trimmed cleanly.
            local lastClipW=(perClip[i] and #perClip[i]>0) and perClip[i][#perClip[i]] or lastW
            if edge and edge.activeEnd and lastClipW and (lastClipW.finish-lastClipW.start)>0.90 then
                local edgeAbsEnd=clipStartSec+edge.activeEnd
                if edgeAbsEnd>=lastClipW.start+0.25 and edgeAbsEnd<lastFinishSec then
                    lastFinishSec=edgeAbsEnd
                end
            end

            local rawStartLocal=math.max(
                0,
                firstStartSec-clipStartSec
            )

            local rawEndLocal=math.min(
                clipDur,
                lastFinishSec-clipStartSec
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

    -- Inspect the OUTER head/tail of EVERY small imported clip independently.
    -- Speech Protection Rule (铁律：严禁切进说话区):
    -- Whenever either ASR word timestamps OR acoustic energy indicates speech is active,
    -- protect that region. Keep the EARLIER head start (math.min) and LATER tail end (math.max).
    for i,r in ipairs(results) do
        local edge=clipEdges[i]
        if edge then
            local hadTextMatch=r.matched
            if not r.matched then
                r.matched=true
                r.confidence=math.max(0.68,(aligned and aligned.avgSimilarity) or 0.70)
                unmatched=math.max(0,unmatched-1)
            end
            local clipDur=(r.clip.e-r.clip.s)/fps
            local audioKeepStart=r.clip.s+math.floor(math.max(0,(edge.activeStart or 0)-HEAD_PAD_SEC)*fps+0.5)
            local audioKeepEnd=r.clip.s+math.floor(math.min(clipDur,(edge.activeEnd or clipDur)+TAIL_PAD_SEC)*fps+0.5)

            local keepStartAbs
            if hadTextMatch then
                keepStartAbs=math.min(r.keepStart or r.clip.s,audioKeepStart)
            elseif edge.headSilence and edge.headSilence>=EDGE_SILENCE_MIN_SEC then
                keepStartAbs=audioKeepStart
            else
                keepStartAbs=r.clip.s
            end
            keepStartAbs=math.max(r.clip.s,math.min(r.clip.e,keepStartAbs))
            local hFrames=keepStartAbs-r.clip.s
            if hFrames>=MIN_TRIM_FRAMES then
                r.headFrames=hFrames
                r.keepStart=keepStartAbs
                r.headSource='SPEECH_PROTECTED_AUDIO_AND_TEXT'
            else
                r.headFrames=0
                r.keepStart=r.clip.s
                r.headSource=nil
            end

            local keepEndAbs
            if hadTextMatch then
                keepEndAbs=math.max(r.keepEnd or r.clip.e,audioKeepEnd)
            elseif edge.tailSilence and edge.tailSilence>=EDGE_SILENCE_MIN_SEC then
                keepEndAbs=audioKeepEnd
            else
                keepEndAbs=r.clip.e
            end
            keepEndAbs=math.max(r.clip.s,math.min(r.clip.e,keepEndAbs))
            local tFrames=r.clip.e-keepEndAbs
            if tFrames>=MIN_TRIM_FRAMES then
                r.tailFrames=tFrames
                r.keepEnd=keepEndAbs
                r.tailSource='SPEECH_PROTECTED_AUDIO_AND_TEXT'
            else
                r.tailFrames=0
                r.keepEnd=r.clip.e
                r.tailSource=nil
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
    os.execute('/bin/sleep '..string.format('%.3f',s))
end

local bladeFocusAt,bladesSinceFocus=0,0
-- 常驻同步 osascript（PTY + FIFO 哨兵确认）：确保每刀快捷键真正投递到达芬奇后才移动下一刀播放头，杜绝异步管道抢跑漏切。
local bladeProc,bladeAck,bladeFifo,bladePid=nil,nil,nil,nil
local bladeSeq=0
local function closeBladeProc()
    local proc,ack,fifo,pid=bladeProc,bladeAck,bladeFifo,bladePid
    bladeProc,bladeAck,bladeFifo,bladePid=nil,nil,nil,nil
    if proc then pcall(function() proc:write(string.char(4)..'\n');proc:flush() end) end
    if ack then pcall(function() ack:close() end) end
    if fifo then pcall(function() os.remove(fifo) end) end
    if pid and tostring(pid):match('^%d+$') then
        os.execute('/usr/bin/pkill -TERM -P '..pid..' >/dev/null 2>&1; /bin/kill -TERM '..pid..' >/dev/null 2>&1')
    end
    if proc then pcall(function() proc:close() end) end
end
local function evalBladeExpr(expr)
    if not (bladeProc and bladeAck) then return nil end
    bladeSeq=bladeSeq+1
    local sentinel='FS_ACK_'..tostring(bladeSeq)
    local okW=pcall(function()
        bladeProc:write(expr..'\n"'..sentinel..'"\n')
        bladeProc:flush()
    end)
    if not okW then closeBladeProc();return nil end
    local prevResult=''
    for _=1,400 do
        local line=bladeAck:read('*l')
        if not line then closeBladeProc();return nil end
        local clean=line:gsub('\r','')
        if clean:find('=> "'..sentinel..'"',1,true) then
            return prevResult
        end
        if clean:sub(1,3)=='=> ' then
            prevResult=trim(clean:sub(4))
        end
    end
    closeBladeProc()
    return nil
end
local function ensureBladeProc()
    if bladeProc and bladeAck then return true end
    closeBladeProc()
    bladeSeq=bladeSeq+1
    local fifo='/tmp/fs_blade_'..tostring(os.time())..'_'..tostring(bladeSeq)..'_'..tostring(math.random(100000,999999))..'.fifo'
    os.remove(fifo)
    local mk=os.execute('/usr/bin/mkfifo '..shellQuote(fifo)..' >/dev/null 2>&1')
    if not (mk==0 or mk==true) then return false end
    local okP,p=pcall(io.popen,"exec /bin/sh -c 'echo FS_PID=$$; exec /usr/bin/script -q /dev/null /usr/bin/osascript -i' > "..shellQuote(fifo).." 2>&1",'w')
    if not (okP and p) then os.remove(fifo);return false end
    local ack=io.open(fifo,'r')
    if not ack then pcall(function() p:close() end);os.remove(fifo);return false end
    local pidLine=ack:read('*l') or ''
    local pid=pidLine:match('FS_PID=(%d+)')
    bladeProc,bladeAck,bladeFifo,bladePid=p,ack,fifo,pid
    -- 提前完成 AppleScript + System Events 冷启动预热（约 140ms），防止首刀异步延迟导致漏切
    local warm=evalBladeExpr('tell application "System Events" to get frontmost of process "DaVinci Resolve"')
    if warm==nil then closeBladeProc();return false end
    return true
end
local function sendBladeKey()
    if platform.windows then
        if platform.blade() then return true,'OK' end
        return false,'NEED_FOCUS'
    end
    if not ensureBladeProc() then return false,'PIPE_INIT_FAILED' end
    local fm=evalBladeExpr('tell application "System Events" to get frontmost of process "DaVinci Resolve"')
    if fm==nil then return false,'PIPE_LOST' end
    if fm~='true' then return false,'NEED_FOCUS' end
    local ack=evalBladeExpr('tell application "System Events" to keystroke "b" using {command down}')
    if ack==nil then return false,'PIPE_LOST' end
    fastSleep(0.025)
    return true,'OK'
end
local function setAndConfirmPlayhead(timeline,tc)
    local ok,setRet=pcall(function() return timeline:SetCurrentTimecode(tc) end)
    if not ok or setRet==false then
        return false,'无法把播放头移动到 '..tc
    end
    for _=1,100 do
        if timeline:GetCurrentTimecode()==tc then return true,'' end
        fastSleep(0.005)
    end
    return false,'PLAYHEAD_NOT_READY: '..tc
end
local function movePlayheadAndBlade(timeline,frame,fps)
    local nowT=os.time()
    if bladesSinceFocus==0 or bladesSinceFocus>=80 or nowT-bladeFocusAt>=90 then
        local focused,focusError=prepareTimelineFocus()
        if not focused then return false,'TIMELINE_FOCUS_FAILED: '..tostring(focusError) end
        bladeFocusAt=os.time();bladesSinceFocus=0
    end
    bladesSinceFocus=bladesSinceFocus+1
    local tc,err=absoluteFrameToTimecode(timeline,frame,fps)
    if not tc then return false,err end

    local arrived,playErr=setAndConfirmPlayhead(timeline,tc)
    if not arrived then return false,playErr end

    local sent,why=sendBladeKey()
    if sent then return true,'' end

    if why=='NEED_FOCUS' then
        local focused,focusError=prepareTimelineFocus()
        if not focused then return false,'TIMELINE_REFOCUS_FAILED: '..tostring(focusError) end
        bladeFocusAt=os.time();bladesSinceFocus=1
        arrived,playErr=setAndConfirmPlayhead(timeline,tc)
        if not arrived then return false,playErr end
        sent,why=sendBladeKey()
        if sent then return true,'' end
    end

    if platform.windows then return false,'RESOLVE_FOCUS_LOST' end
    local p=io.popen([[ /usr/bin/osascript -e 'tell application "DaVinci Resolve" to activate' -e 'delay 0.05' -e 'tell application "System Events" to keystroke "b" using {command down}' 2>&1 ]])
    if not p then return false,'BLADE_COMMAND_FAILED' end
    local out=p:read('*a');local success=p:close()
    fastSleep(0.030)
    return success~=nil and success~=false,out
end

local function findItemByRange(
    timeline,
    trackIndex,
    s,
    e,
    cachedItems
)
    local items=cachedItems or timeline:GetItemListInTrack(
        "video",
        trackIndex
    ) or {}

    for _,entry in ipairs(items) do
        local item=entry.item or entry
        local is=tonumber(entry.s or item:GetStart())
        local ie=tonumber(entry.e or item:GetEnd())

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
    ap.add_argument('--wav', default='')
    ap.add_argument('--start', type=float, default=0.0)
    ap.add_argument('--duration', type=float, default=0.0)
    ap.add_argument('--batch-spec', default='')
    ap.add_argument('--threshold-db', type=float, default=-48.0)
    ap.add_argument('--window-sec', type=float, default=0.02)
    ap.add_argument('--active-windows', type=int, default=3)
    a=ap.parse_args()
    if a.batch_spec:
        by_wav={}
        with open(a.batch_spec, 'r', encoding='utf-8') as sf:
            for line in sf:
                parts=line.rstrip('\r\n').split('\t')
                if len(parts)==4:
                    by_wav.setdefault(parts[0], []).append((float(parts[1]), float(parts[2]), parts[3]))
        for wav_path, items in by_wav.items():
            try:
                wf=wave.open(wav_path, 'rb')
            except Exception:
                continue
            with wf:
                if wf.getcomptype() != 'NONE': continue
                rate=wf.getframerate(); chans=wf.getnchannels(); sw=wf.getsampwidth(); total=wf.getnframes()
                win_frames=max(1, int(round(a.window_sec*rate)))
                win_samples=max(chans, win_frames*chans)
                for s_sec, d_sec, out_path in items:
                    try:
                        start=max(0, min(total, int(round(s_sec*rate))))
                        count=max(0, min(total-start, int(round(d_sec*rate))))
                        wf.setpos(start)
                        raw=wf.readframes(count)
                        vals,full=decode_pcm(raw, sw)
                        if count <= 0 or not vals:
                            res='status=EMPTY\n'
                        else:
                            levels=[]
                            for off in range(0, len(vals), win_samples):
                                chunk=vals[off:off+win_samples:2]
                                if not chunk: break
                                ss=0.0
                                for v in chunk: ss += float(v)*float(v)
                                rms=math.sqrt(ss/max(1,len(chunk)))/full
                                db=-120.0 if rms <= 1e-12 else 20.0*math.log10(rms)
                                levels.append(db)
                            peak=max(levels) if levels else -120.0
                            strong_threshold=max(a.threshold_db, min(-22.0, peak-14.0))
                            weak_threshold=max(-48.0, strong_threshold-6.0)
                            strong=[db >= strong_threshold for db in levels]
                            first=first_run(strong, max(1,a.active_windows))
                            last=last_run(strong, max(1,a.active_windows))
                            if first is None or last is None or last < first:
                                res='status=NO_ACTIVITY\npeak_db=%.3f\nthreshold_used_db=%.3f\n' % (peak, strong_threshold)
                            else:
                                while first > 0 and levels[first-1] >= weak_threshold: first -= 1
                                while last+1 < len(levels) and levels[last+1] >= weak_threshold: last += 1
                                active_start=min(d_sec, first*win_frames/rate)
                                active_end=min(d_sec, (last+1)*win_frames/rate)
                                res=('status=OK\nactive_start=%.6f\nactive_end=%.6f\nhead_silence=%.6f\ntail_silence=%.6f\npeak_db=%.3f\nthreshold_used_db=%.3f\n' %
                                     (active_start, active_end, max(0.0, active_start), max(0.0, d_sec-active_end), peak, strong_threshold))
                        with open(out_path + '.tmp', 'w', encoding='utf-8') as out_f:
                            out_f.write(res)
                        os.replace(out_path + '.tmp', out_path)
                    except Exception:
                        pass
        return
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
        chunk=vals[off:off+win_samples:2]
        if not chunk: break
        ss=0.0
        for v in chunk: ss += float(v)*float(v)
        rms=math.sqrt(ss/max(1,len(chunk)))/full
        db=-120.0 if rms <= 1e-12 else 20.0*math.log10(rms)
        levels.append(db)
    peak=max(levels) if levels else -120.0
    # Adaptive strong threshold: keep the configured -48 dBFS as the quiet-voice safety floor,
    # and place strong_threshold 14 dB below clip speech peak (capped at -22 dBFS so Flow room noise
    # at -28..-34 dBFS never disguises itself as speech).
    strong_threshold=max(a.threshold_db, min(-22.0, peak-14.0))
    weak_threshold=max(-48.0, strong_threshold-6.0)
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

local function runBatchSilenceProbes(pythonPath, probePath, audioBatches, fps, base)
    if not pythonPath or pythonPath=='' then return end
    local specLines={}
    for _,part in ipairs(audioBatches) do
        if part.wav and part.wav~='' then
            for _,job in ipairs(part.jobs or {}) do
                for clipIndex,clip in ipairs(job.clips or {}) do
                    local relStart=(clip.s-part.s)/fps
                    local duration=(clip.e-clip.s)/fps
                    local probeOut=base..'/whisper/video_'..job.id..'_clip_'..string.format('%03d',clipIndex)..'_edge_silence.ini'
                    local cached=parseSimplePairs(readTextOptional(probeOut))
                    if cached.status~='OK' and duration>0 then
                        specLines[#specLines+1]=part.wav..'\t'..string.format('%.6f',relStart)..'\t'..string.format('%.6f',duration)..'\t'..probeOut
                    end
                end
            end
        end
    end
    if #specLines==0 then return end
    local batchSpecPath=base..'/whisper/batch_silence_specs.tsv'
    local f=io.open(batchSpecPath..'.tmp','w')
    if not f then return end
    f:write(table.concat(specLines,'\n')..'\n');f:close()
    os.rename(batchSpecPath..'.tmp',batchSpecPath)
    local args={pythonPath,probePath,'--batch-spec',batchSpecPath,'--threshold-db',tostring(EDGE_SILENCE_THRESHOLD_DB),'--window-sec',tostring(EDGE_SILENCE_WINDOW_SEC),'--active-windows',tostring(EDGE_SILENCE_ACTIVE_WINDOWS)}
    for i,arg in ipairs(args) do args[i]=shellQuote(arg) end
    os.execute(table.concat(args,' ')..' >/dev/null 2>&1')
end

local function probeEdgeSilence(pythonPath,probePath,wavPath,startSec,durationSec,resultPath)
    if not pythonPath or pythonPath=='' then return nil,'PYTHON_PATH_MISSING' end
    if not wavPath or wavPath=='' then return nil,'WAV_PATH_MISSING' end
    if not durationSec or durationSec<=0 then return nil,'INVALID_DURATION' end
    local cachedVals=parseSimplePairs(readTextOptional(resultPath))
    if cachedVals.status=='OK' then
        local cStart,cEnd=tonumber(cachedVals.active_start),tonumber(cachedVals.active_end)
        local cHead,cTail=tonumber(cachedVals.head_silence),tonumber(cachedVals.tail_silence)
        if cStart and cEnd and cHead and cTail then
            return {activeStart=cStart,activeEnd=cEnd,headSilence=cHead,tailSilence=cTail,peakDb=tonumber(cachedVals.peak_db),thresholdUsedDb=tonumber(cachedVals.threshold_used_db),exitCode=0,reused=true}
        end
    end
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

local function addManualEditMarker(timeline,origin,bid,attempt,job,reason,cachedMarkers)
    local markers=cachedMarkers or timeline:GetMarkers() or {}
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
    markers[frame]={color=MANUAL_EDIT_MARKER_COLOR,customData=custom,duration=duration}
end

local function resolveImportMarker(markers,origin,bid,id,s,e,usedFrames)
    local candidates={}
    for frame,marker in pairs(markers or {}) do
        local info=type(marker)=='table' and tag(marker.customData) or {}
        if (info.batch_id==bid or tostring(info.video_id or '')==tostring(id or '')) and info.status=='COMPLETE' then
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

local function cutBoundary(timeline,kind,track,frame,cachedList)
    local left,right,crossing=false,false,false
    local list=cachedList
    if list then
        for _,r in ipairs(list) do
            local s,e=r[1],r[2]
            if e==frame then left=true end
            if s==frame then right=true end
            if s<frame and e>frame then crossing=true end
        end
    else
        for _,item in ipairs(timeline:GetItemListInTrack(kind,track) or {}) do
            local s,e=item:GetStart(),item:GetEnd()
            if e==frame then left=true end
            if s==frame then right=true end
            if s<frame and e>frame then crossing=true end
        end
    end
    return left and right and not crossing
end
local function confirmCut(timeline,frame,videoTrack,audioTracks,guard)
    local videoOK,missing
    for poll=1,100 do
        if poll==1 or poll%10==0 then guard() end
        videoOK=cutBoundary(timeline,'video',videoTrack,frame);missing={}
        for track in pairs(audioTracks) do
            if not cutBoundary(timeline,'audio',track,frame) then missing[#missing+1]=track end
        end
        if videoOK and #missing==0 then return true end
        if poll<100 then fastSleep(0.02) end
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
    local v1Cached={}
    for _,item in ipairs(timeline:GetItemListInTrack('video',1) or {}) do
        v1Cached[#v1Cached+1]={item=item,a=item:GetStart(),b=item:GetEnd()}
    end
    for _,job in ipairs(jobs) do
        local parts=assert(expected[job.id],'RESUME_SOURCE_ID_MISSING')
        assert(#parts>0 and parts[1].s==job.segment.s and parts[#parts].e==job.segment.e,'RESUME_IMPORT_RANGE_CHANGED')
        for _,entry in ipairs(v1Cached) do
            local item,a,b=entry.item,entry.a,entry.b
            if a and b and a<job.segment.e and b>job.segment.s then
                for _,part in ipairs(parts) do
                    if a>=part.s and b<=part.e then
                        local media=item:GetMediaPoolItem()
                        assert(media and platform.path(media:GetClipProperty('File Path'))==platform.path(part.path),'RESUME_SOURCE_CHANGED')
                        assert(item:GetLeftOffset()==a-part.s,'RESUME_SOURCE_OFFSET_CHANGED')
                        break
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
    assert(p.whisper_language and p.whisper_language:match('^%l%l%l?%l?$'),'WHISPER_LANGUAGE_INVALID')
    assert(p.task_json_path==base..'/task.json','TASK_JSON_PATH_MISMATCH')
    local taskJSON=readText(p.task_json_path)
    assert(taskJSON:find('"task_id": "'..taskId..'"',1,true),'TASK_JSON_ID_MISMATCH')
    assert(taskJSON:find('"batch_id": "'..bid..'"',1,true),'TASK_JSON_BATCH_MISMATCH')
    assert(taskJSON:find('"language": "'..p.whisper_language..'"',1,true),'TASK_JSON_LANGUAGE_MISMATCH')
    if command.sub_action == 'CLEAN_MISPLACED_SUBTITLE' or command.sub_action == 'IMPORT_SCRIPTURES' then
        local pm = assert(app:GetProjectManager(), 'PROJECT_MANAGER_UNAVAILABLE')
        local project = assert(pm:GetCurrentProject(), 'PROJECT_UNAVAILABLE')
        local timeline = assert(project:GetCurrentTimeline(), 'TIMELINE_UNAVAILABLE')
        local pool = assert(project:GetMediaPool(), 'MEDIA_POOL_UNAVAILABLE')
        if command.sub_action == 'CLEAN_MISPLACED_SUBTITLE' or tostring(command.manual_trigger or '') ~= '1' then
            local toDelete = {}
            for track = 1, timeline:GetTrackCount('subtitle') do
                pcall(function() timeline:SetTrackLock('subtitle', track, false) end)
                local items = timeline:GetItemListInTrack('subtitle', track) or {}
                for _, it in ipairs(items) do
                    toDelete[#toDelete + 1] = it
                end
            end
            if #toDelete > 0 then
                pcall(function() timeline:DeleteClips(toDelete, false) end)
            end
            local hasCleaned = io.open(base .. '/cleaned.ini', 'r')
            if hasCleaned then
                hasCleaned:close()
            else
                pcall(function() os.remove(base .. '/scriptures_' .. bid .. '.srt') end)
                pcall(function() os.remove(root .. '/v0_5_0/batches/' .. bid .. '/经文字幕_' .. bid .. '.srt') end)
            end
            pcall(function() pm:SaveProject() end)
            local detailMsg = '自动剪辑完成，等待人工检查；经文字幕将在清理后随水印一起挂载'
            report('WAITING_USER_REVIEW', detailMsg)
            return {stage='WAITING_USER_REVIEW', detail=detailMsg, batch_id=bid, deleted_count=#toDelete}
        end
        
        -- 0. 重新生成包含全时间线批次经文的主字幕文件（绝对时间轴对齐；若已有直通生成的经文字幕则直接使用）
        local existingSrt = io.open(base .. '/scriptures_' .. bid .. '.srt', 'r')
        if existingSrt then
            existingSrt:close()
        else
            pcall(function()
                local pyBin = p.python_path or '/Applications/Flow Studio.app/Contents/Resources/python/bin/python3'
                local pyRoot = '/Applications/Flow Studio.app/Contents/Resources'
                local genCmd = 'PYTHONPATH=' .. shellQuote(pyRoot) .. ' ' .. shellQuote(pyBin) .. ' -m app.services.scripture_subtitles ' .. shellQuote(base)
                os.execute(genCmd)
            end)
        end
        
        -- 1. 清理时间线上误放片段及旧字幕轨内容（重新全量精确对齐）
        local toDelete = {}
        for track = 1, timeline:GetTrackCount('video') do
            local items = timeline:GetItemListInTrack('video', track) or {}
            for _, it in ipairs(items) do
                local name = tostring(it:GetName())
                if (name:find('srt') or name:find('经文')) and not name:find('MP4') and not name:find('mp4') then
                    toDelete[#toDelete + 1] = it
                end
            end
        end
        for track = 1, timeline:GetTrackCount('subtitle') do
            local items = timeline:GetItemListInTrack('subtitle', track) or {}
            for _, it in ipairs(items) do
                toDelete[#toDelete + 1] = it
            end
        end
        if #toDelete > 0 then
            pcall(function() timeline:DeleteClips(toDelete, false) end)
        end
        
        -- 2. 导入最新对齐的 SRT 到 MediaPool 中的 Subtitles 目录并挂载至时间线
        local srtPath = base .. '/scriptures_' .. bid .. '.srt'
        local f = io.open(srtPath, 'r')
        if not f then
            srtPath = root .. '/v0_5_0/batches/' .. bid .. '/经文字幕_' .. bid .. '.srt'
            f = io.open(srtPath, 'r')
        end
        local srtContent = f and f:read('*a') or ''
        if f then f:close() end
        local srtItem = nil
        local appendOK, appendRes = false, nil
        local freshSrtPath = ''
        if srtContent and srtContent ~= '' then
            local rootFolder = pool:GetRootFolder()
            local srtFolder = rootFolder
            for _, sub in ipairs(rootFolder:GetSubFolderList() or {}) do
                if sub:GetName() == 'Subtitles' then srtFolder = sub break end
            end
            if srtFolder == rootFolder then
                srtFolder = pool:AddSubFolder(rootFolder, 'Subtitles') or rootFolder
            end
            pool:SetCurrentFolder(srtFolder)
            pcall(function()
                local oldClips = srtFolder:GetClipList() or {}
                if #oldClips > 0 then pool:DeleteClips(oldClips) end
            end)
            freshSrtPath = base .. '/scriptures_' .. bid .. '_' .. os.time() .. '.srt'
            local wf = io.open(freshSrtPath, 'w')
            if wf then wf:write(srtContent); wf:close() end
            
            local srtClips = pool:ImportMedia({ freshSrtPath })
            srtItem = srtClips and srtClips[1]
            if srtItem then
                pool:SetSelectedClip(srtItem)
                if timeline:GetTrackCount('subtitle') == 0 then
                    timeline:AddTrack('subtitle')
                end
                pcall(function() timeline:SetCurrentTimecode('01:00:00:00') end)
                appendOK, appendRes = pcall(function()
                    return pool:AppendToTimeline({ srtItem })
                end)
            end
        end
        local subItemCount = 0
        local subPositions = {}
        pcall(function()
            for t = 1, timeline:GetTrackCount('subtitle') do
                local items = timeline:GetItemListInTrack('subtitle', t) or {}
                subItemCount = subItemCount + #items
                for i, it in ipairs(items) do
                    subPositions[#subPositions + 1] = tostring(it:GetStart())..'-'..tostring(it:GetEnd())
                end
            end
        end)
        pm:SaveProject()
        pcall(function()
            local pyBin = p.python_path or '/Applications/Flow Studio.app/Contents/Resources/python/bin/python3'
            local pyRoot = '/Applications/Flow Studio.app/Contents/Resources'
            local projName = project:GetName()
            local syncDummy = '__FlowStudio_Sync__'
            local switchedOff = false
            if pm.CloseProject then
                local okC, closed = pcall(function() return pm:CloseProject(project) end)
                if okC and closed then switchedOff = true end
            end
            if not switchedOff then
                pcall(function()
                    local d = pm:LoadProject(syncDummy)
                    if not d and pm.GotoRootFolder then pm:GotoRootFolder(); d = pm:LoadProject(syncDummy) end
                    if not d and pm.CreateProject then d = pm:CreateProject(syncDummy); if d then pm:SaveProject() end end
                end)
            end
            local styleCmd = 'PYTHONPATH=' .. shellQuote(pyRoot) .. ' ' .. shellQuote(pyBin) .. ' -m app.services.scripture_subtitles --style-project ' .. shellQuote(projName) .. ' ' .. shellQuote(p.timeline_name or '') .. ' ' .. shellQuote(freshSrtPath or '')
            local h = io.popen(styleCmd)
            local out = h and h:read('*a') or ''
            if h then h:close() end
            local reloaded = pm:LoadProject(projName)
            if not reloaded and pm.GotoRootFolder then
                pcall(function() pm:GotoRootFolder() end)
                reloaded = pm:LoadProject(projName)
            end
            if reloaded and p.timeline_name then
                for ti=1,reloaded:GetTimelineCount() do
                    local cand=reloaded:GetTimelineByIndex(ti)
                    if cand and cand:GetName()==p.timeline_name then reloaded:SetCurrentTimeline(cand);break end
                end
                project = reloaded
            end
        end)
        local detailMsg = '已精确对齐全时间线经文字幕；当前字幕总数='..tostring(subItemCount)..' appendOK='..tostring(appendOK)
        report('WAITING_USER_REVIEW', detailMsg)
        return {stage='WAITING_USER_REVIEW', detail=detailMsg, batch_id=bid, deleted_count=#toDelete, srt_selected=tostring(srtItem ~= nil), append_ok=tostring(appendOK), append_result=tostring(appendRes), sub_item_count=subItemCount, sub_positions=table.concat(subPositions, ';'), fresh_srt=tostring(freshSrtPath)}
    end
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
        local expectedMainTl='MAIN-'..p.work_date
        local validDayTl=(p.timeline_name==expectedMainTl) or (tostring(p.timeline_name or ''):match('^'..expectedMainTl:gsub('%-','%%-')..'%-B%d+$')~=nil)
        assert(p.project_name=='FlowStudio-'..p.work_date and validDayTl,'DAILY_NAME_MISMATCH')
        local fps=assert(parseFPSValue(timeline:GetSetting('timelineFrameRate')) or getTimelineFPS(project),'FPS_UNAVAILABLE')
        local customTl=(tostring(timeline:GetSetting('useCustomSettings') or '')=='1')
        if not customTl then
            local projFps=parseFPSValue(project:GetSetting('timelineFrameRate'))
            if projFps and projFps>0 then
                assert(fps>0 and math.abs(fps-projFps)<0.001,'FPS_MISMATCH')
            end
        end
        assert(fps>0,'FPS_MISMATCH')
        assert(not tostring(timeline:GetStartTimecode()):find(';',1,true),'DROP_FRAME_NOT_SUPPORTED')
        local origin=timeline:GetStartFrame();local jobs={};local previousEnd=nil;local batchMarkerStart=nil
        local usedImportMarkerFrames={};local importMarkerMatched=0;local importMarkerMissing=0
        -- Re-identification / fast overcut repair / multi-batch consolidation: keep existing timeline
        -- blade cuts, clear old automatic Red/Orange markers for videos in this batch, and evaluate
        -- un-edited clips (or all clips on reanalyze) with speech-protected boundaries.
        local carriedCandidates,carriedByVideo={},{}
        local targetVideoSet={}
        for i=1,state.total do
            local vid=p['v'..i..'_id']
            if vid then targetVideoSet[tostring(vid)]=true end
        end
        if not resume then
            local deleteFrames={}
            for frame,marker in pairs(timeline:GetMarkers() or {}) do
                local info=type(marker)=='table' and tag(marker.customData) or {}
                if info.batch_id==bid or (info.video_id and targetVideoSet[tostring(info.video_id)]) then
                    if (marker.color=='Red' and info.candidate_id) or info.status=='MANUAL_EDIT' then
                        deleteFrames[#deleteFrames+1]=frame
                    end
                end
            end
            for _,frame in ipairs(deleteFrames) do assert(timeline:DeleteMarkerAtFrame(frame),'REANALYZE_MARKER_CLEAR_FAILED') end
            if #deleteFrames>0 then assert(pm:SaveProject(),'SAVE_REANALYZE_MARKERS_FAILED') end
        end
        local function safeClipInt(clip,method)
            if not clip or not clip[method] then return nil end
            for _=1,6 do
                local okV,rawV=pcall(function() return clip[method](clip) end)
                local num=okV and tonumber(rawV) or nil
                if num and num==num and math.abs(num)~=math.huge then
                    local r=math.floor(num+0.5)
                    if math.abs(num-r)<0.01 then return r end
                end
                sleepSec(0.02)
            end
            local okLast,lastV=pcall(function() return tonumber(clip[method](clip)) end)
            return (okLast and lastV) and math.floor(lastV+0.5) or nil
        end

        local function switchAwayFromProject(curProj)
            local syncDummy='__FlowStudio_Sync__'
            if pm.CloseProject then
                local okC,closed=pcall(function() return pm:CloseProject(curProj) end)
                if okC and closed then return true end
            end
            local dummy=pm:LoadProject(syncDummy)
            if not dummy and pm.GotoRootFolder then
                pcall(function() pm:GotoRootFolder() end)
                dummy=pm:LoadProject(syncDummy)
            end
            if not dummy and pm.CreateProject then
                dummy=pm:CreateProject(syncDummy)
                if dummy then pcall(function() pm:SaveProject() end) end
            end
            return dummy~=nil
        end

        local function closeAndReloadProject(projName,tlName)
            local reloaded=pm:LoadProject(projName)
            if not reloaded and pm.GotoRootFolder then
                pcall(function() pm:GotoRootFolder() end)
                reloaded=pm:LoadProject(projName)
            end
            assert(reloaded,'RELOAD_AFTER_SUBCLIP_SYNC_FAILED')
            local matchedTl=nil
            if reloaded.GetTimelineCount and reloaded.GetTimelineByIndex then
                for ti=1,(tonumber(reloaded:GetTimelineCount()) or 0) do
                    local cand=reloaded:GetTimelineByIndex(ti)
                    if cand and cand:GetName()==tlName then
                        reloaded:SetCurrentTimeline(cand)
                        matchedTl=cand
                        break
                    end
                end
            end
            project=reloaded
            timeline=assert(matchedTl or reloaded:GetCurrentTimeline(),'RELOAD_SUBCLIP_TIMELINE_MISSING')
            timelineID=timeline:GetUniqueId()
        end

        local function runSubclipDbSync(syncItems,specName)
            if #syncItems==0 then return end
            assert(pm:SaveProject(),'SAVE_BEFORE_SUBCLIP_SYNC_FAILED')
            assert(switchAwayFromProject(project),'SWITCH_BEFORE_SUBCLIP_SYNC_FAILED')
            local syncSpecPath=base..'/'..(specName or 'subclip_sync.ini')
            local syncSpec={
                project_name=p.project_name,
                timeline_name=p.timeline_name,
                timeline_uid=timelineID,
                timeline_fps=fps,
                project_db_path=tostring(test.projectDbPath or ''),
                item_count=#syncItems,
            }
            for sIdx,entry in ipairs(syncItems) do
                local sp='item_'..tostring(sIdx)..'_'
                syncSpec[sp..'uid']=entry.uid
                syncSpec[sp..'kind']=entry.kind
                syncSpec[sp..'start']=entry.start
                syncSpec[sp..'duration']=entry.duration
                syncSpec[sp..'in']=entry.in_offset
                syncSpec[sp..'path']=entry.path
            end
            writePairs(syncSpecPath,syncSpec)
            local pyBin=p.python_path or '/Applications/Flow Studio.app/Contents/Resources/python/bin/python3'
            local pyRoot='/Applications/Flow Studio.app/Contents/Resources'
            local syncCmd='PYTHONPATH='..shellQuote(pyRoot)..' '..shellQuote(pyBin)..' -m app.services.resolve_subclip_sync '..shellQuote(syncSpecPath)
            local sh=io.popen(syncCmd,'r')
            local syncOut=sh and sh:read('*a') or ''
            if sh then sh:close() end
            local syncOk=(syncOut:find('SUBCLIPS_SYNCED:',1,true)~=nil)
            if not syncOk then
                pcall(closeAndReloadProject,p.project_name,p.timeline_name)
                error('SUBCLIP_DB_SYNC_FAILED: '..tostring(syncOut))
            end
            closeAndReloadProject(p.project_name,p.timeline_name)
            if usedDeliverFastPath and app.OpenPage then
                pcall(function()
                    if not app.GetCurrentPage or app:GetCurrentPage()~='deliver' then
                        app:OpenPage('deliver')
                    end
                end)
            end
        end

        local function repairInterruptedBatchSlotsIfNeeded()
            if test.blade then return end
            local manifestPath=root..'/v0_5_0/batches/'..bid..'/manifest.ini'
            local importLogPath=root..'/logs/'..bid..'/import.log'
            local mfCheck=io.open(manifestPath,'r')
            local lgCheck=io.open(importLogPath,'r')
            if not mfCheck or not lgCheck then
                if mfCheck then mfCheck:close() end
                if lgCheck then lgCheck:close() end
                return
            end
            mfCheck:close();lgCheck:close()

            local manifest=readPairs(manifestPath)
            local logTxt=readText(importLogPath)
            local ranges={}
            for vid,sid,a,b in logTxt:gmatch('ACTUAL video_id=(%d+) segment_id=(%d+) start=(%d+) end=(%d+)') do
                ranges[vid..':'..sid]={s=tonumber(a),e=tonumber(b)}
            end
            local partsByVid={}
            local manifestPathSet={}
            for mIdx=1,tonumber(manifest.video_count or 0) do
                local pre='v'..mIdx..'_'
                local vid=tostring(manifest[pre..'id'] or '')
                local segCnt=tonumber(manifest[pre..'segment_count'] or 0) or 0
                if vid~='' and segCnt>0 then
                    local vParts={}
                    local allFound=true
                    for sIdx=1,segCnt do
                        local sid=tostring(manifest[pre..'s'..sIdx..'_id'] or '')
                        local r=ranges[vid..':'..sid]
                        local mpath=manifest[pre..'s'..sIdx..'_path']
                        if not r or not mpath or mpath=='' then allFound=false;break end
                        manifestPathSet[platform.path(mpath)]=true
                        local tp=pre..'s'..sIdx..'_transform_'
                        local tr=nil
                        if manifest[tp..'ZoomX'] then
                            tr={
                                ZoomX=tonumber(manifest[tp..'ZoomX']),
                                ZoomY=tonumber(manifest[tp..'ZoomY']),
                                Pan=tonumber(manifest[tp..'Pan']),
                                Tilt=tonumber(manifest[tp..'Tilt']),
                            }
                        end
                        vParts[#vParts+1]={s=r.s,e=r.e,path=mpath,transform=tr}
                    end
                    if allFound and #vParts>0 then partsByVid[vid]=vParts end
                end
            end

            local hasA1=(tonumber(timeline:GetTrackCount('audio')) or 0)>=1
            local v1Cached,a1Cached={},{}
            for _,it in ipairs(timeline:GetItemListInTrack('video',1) or {}) do
                local s,e=safeClipInt(it,'GetStart'),safeClipInt(it,'GetEnd')
                if s and e then
                    v1Cached[#v1Cached+1]={it=it,s=s,e=e,leftOff=safeClipInt(it,'GetLeftOffset') or 0}
                end
            end
            if hasA1 then
                for _,it in ipairs(timeline:GetItemListInTrack('audio',1) or {}) do
                    local s,e=safeClipInt(it,'GetStart'),safeClipInt(it,'GetEnd')
                    if s and e then a1Cached[#a1Cached+1]={it=it,s=s,e=e} end
                end
            end

            local brokenParts={}
            local partialClear={}
            local seenClear={}
            local batchMaxEnd=0

            for i=1,state.total do
                local pre='v'..i..'_'
                local vid=tostring(p[pre..'id'] or '')
                local vsExp,veExp=tonumber(p[pre..'start']),tonumber(p[pre..'end'])
                if veExp and veExp>batchMaxEnd then batchMaxEnd=veExp end
                local vParts=partsByVid[vid]
                if vParts and vsExp and veExp and vParts[1].s==vsExp and vParts[#vParts].e==veExp then
                    for _,part in ipairs(vParts) do
                        local ovV,ovA={},{}
                        for _,vc in ipairs(v1Cached) do
                            if vc.s<part.e and vc.e>part.s then ovV[#ovV+1]=vc end
                        end
                        for _,ac in ipairs(a1Cached) do
                            if ac.s<part.e and ac.e>part.s then ovA[#ovA+1]=ac end
                        end
                        table.sort(ovV,function(x,y) return x.s<y.s end)
                        table.sort(ovA,function(x,y) return x.s<y.s end)
                        local okV=(#ovV>0 and ovV[1].s==part.s and ovV[#ovV].e==part.e)
                        if okV then
                            for k=1,#ovV do
                                if ovV[k].leftOff~=(ovV[k].s-part.s) then okV=false;break end
                                if k<#ovV and ovV[k].e~=ovV[k+1].s then okV=false;break end
                            end
                        end
                        local okA=(not hasA1) or (#ovA>0 and ovA[1].s==part.s and ovA[#ovA].e==part.e)
                        if okA and hasA1 then
                            for k=1,#ovA-1 do
                                if ovA[k].e~=ovA[k+1].s then okA=false;break end
                            end
                        end
                        if not (okV and okA) then
                            brokenParts[#brokenParts+1]=part
                            for _,x in ipairs(ovV) do
                                if not seenClear[x.it] then seenClear[x.it]=true;partialClear[#partialClear+1]=x.it end
                            end
                            for _,x in ipairs(ovA) do
                                if not seenClear[x.it] then seenClear[x.it]=true;partialClear[#partialClear+1]=x.it end
                            end
                        end
                    end
                end
            end

            -- Also clear any stray 2-frame tail placeholders left behind by an interrupted pre-reload attempt.
            local strayTailRanges={}
            if batchMaxEnd>0 then
                for _,vc in ipairs(v1Cached) do
                    if vc.s>=batchMaxEnd and (vc.e-vc.s)<=4 then
                        local fp=''
                        pcall(function()
                            local mp=vc.it:GetMediaPoolItem()
                            if mp then fp=platform.path(mp:GetClipProperty('File Path') or '') end
                        end)
                        if fp~='' and manifestPathSet[fp] then
                            strayTailRanges[vc.s..':'..vc.e]=true
                            if not seenClear[vc.it] then seenClear[vc.it]=true;partialClear[#partialClear+1]=vc.it end
                        end
                    end
                end
                if next(strayTailRanges) then
                    for _,ac in ipairs(a1Cached) do
                        if ac.s>=batchMaxEnd and strayTailRanges[ac.s..':'..ac.e] then
                            if not seenClear[ac.it] then seenClear[ac.it]=true;partialClear[#partialClear+1]=ac.it end
                        end
                    end
                end
            end

            if #brokenParts==0 then
                if #partialClear>0 then
                    pcall(function() timeline:DeleteClips(partialClear,false) end)
                end
                return
            end

            if app.OpenPage then
                pcall(function()
                    if not app.GetCurrentPage or app:GetCurrentPage()~='deliver' then app:OpenPage('deliver') end
                end)
            end
            pulse('CUTTING','检测到上次中断缺口，正在自动恢复 '..tostring(#brokenParts)..' 个原始片段...',0)

            local pool=assert(project:GetMediaPool(),'MEDIA_POOL_UNAVAILABLE')
            local mediaByPath={}
            local function scanFolder(folder)
                if not folder then return end
                for _,clip in ipairs(folder:GetClipList() or {}) do
                    local fp=''
                    pcall(function() fp=platform.path(clip:GetClipProperty('File Path') or '') end)
                    if fp~='' and not mediaByPath[fp] then mediaByPath[fp]=clip end
                end
                for _,sub in ipairs(folder:GetSubFolderList() or {}) do scanFolder(sub) end
            end
            scanFolder(pool:GetRootFolder())

            local savedLocks={}
            for _,kind in ipairs({'video','audio'}) do
                local tCnt=tonumber(timeline:GetTrackCount(kind)) or 0
                for trk=2,tCnt do
                    local wasLocked=timeline:GetIsTrackLocked(kind,trk)
                    savedLocks[#savedLocks+1]={kind=kind,track=trk,locked=wasLocked}
                    if not wasLocked then pcall(function() timeline:SetTrackLock(kind,trk,true) end) end
                end
            end

            local healOk,healErr=pcall(function()
                if #partialClear>0 then
                    assert(timeline:DeleteClips(partialClear,false),'HEAL_DELETE_PARTIAL_FAILED')
                end
                local existingVUids,existingAUids={},{}
                for _,it in ipairs(timeline:GetItemListInTrack('video',1) or {}) do
                    if it.GetUniqueId then pcall(function() existingVUids[tostring(it:GetUniqueId() or '')]=true end) end
                end
                if hasA1 then
                    for _,it in ipairs(timeline:GetItemListInTrack('audio',1) or {}) do
                        if it.GetUniqueId then pcall(function() existingAUids[tostring(it:GetUniqueId() or '')]=true end) end
                    end
                end

                local healInfos={}
                for _,bp in ipairs(brokenParts) do
                    local normP=platform.path(bp.path)
                    local mp=mediaByPath[normP]
                    if not mp then
                        local imp=pool:ImportMedia({bp.path})
                        mp=imp and imp[1] or nil
                        if mp then mediaByPath[normP]=mp end
                    end
                    assert(mp,'HEAL_MEDIAPOOL_ITEM_MISSING: '..tostring(bp.path))
                    local mpStart=0
                    pcall(function()
                        local sp=tonumber(mp:GetClipProperty('Start'))
                        if sp then mpStart=sp end
                    end)
                    healInfos[#healInfos+1]={
                        mediaPoolItem=mp,
                        startFrame=mpStart,
                        endFrame=mpStart+2,
                        trackIndex=1,
                    }
                end

                local CHUNK=200
                for cStart=1,#healInfos,CHUNK do
                    local cEnd=math.min(#healInfos,cStart+CHUNK-1)
                    local chunk={}
                    for idx=cStart,cEnd do chunk[#chunk+1]=healInfos[idx] end
                    local okB,placedB=pcall(function() return pool:AppendToTimeline(chunk) end)
                    if not (okB and placedB) then
                        for idx=cStart,cEnd do
                            assert(pool:AppendToTimeline({healInfos[idx]}),'HEAL_APPEND_SINGLE_FAILED: '..tostring(idx))
                        end
                    end
                end

                local newV,newA={},{}
                for _,it in ipairs(timeline:GetItemListInTrack('video',1) or {}) do
                    local uid=''
                    if it.GetUniqueId then pcall(function() uid=tostring(it:GetUniqueId() or '') end) end
                    if uid~='' and not existingVUids[uid] then
                        newV[#newV+1]={it=it,uid=uid,st=safeClipInt(it,'GetStart') or 0}
                    end
                end
                table.sort(newV,function(x,y) return x.st<y.st end)
                assert(#newV==#brokenParts,'HEAL_VIDEO_COUNT_MISMATCH: '..tostring(#newV)..' vs '..tostring(#brokenParts))

                if hasA1 then
                    for _,it in ipairs(timeline:GetItemListInTrack('audio',1) or {}) do
                        local uid=''
                        if it.GetUniqueId then pcall(function() uid=tostring(it:GetUniqueId() or '') end) end
                        if uid~='' and not existingAUids[uid] then
                            newA[#newA+1]={it=it,uid=uid,st=safeClipInt(it,'GetStart') or 0}
                        end
                    end
                    table.sort(newA,function(x,y) return x.st<y.st end)
                end

                local healSync={}
                for idx,bp in ipairs(brokenParts) do
                    local vc=newV[idx]
                    if bp.transform and vc.it.SetProperty then
                        for _,tk in ipairs({'ZoomX','ZoomY','Pan','Tilt'}) do
                            if bp.transform[tk]~=nil then
                                assert(vc.it:SetProperty(tk,bp.transform[tk]),'HEAL_TRANSFORM_FAILED: '..tk)
                            end
                        end
                    end
                    healSync[#healSync+1]={
                        uid=vc.uid,kind='video',start=bp.s,duration=bp.e-bp.s,in_offset=0,path=bp.path,
                    }
                    if hasA1 and newA[idx] then
                        healSync[#healSync+1]={
                            uid=newA[idx].uid,kind='audio',start=bp.s,duration=bp.e-bp.s,in_offset=0,path=bp.path,
                        }
                    end
                end
                runSubclipDbSync(healSync,'subclip_heal_sync.ini')
            end)
            for _,entry in ipairs(savedLocks) do
                if not entry.locked then pcall(function() timeline:SetTrackLock(entry.kind,entry.track,false) end) end
            end
            if not healOk then error(healErr) end
        end

        repairInterruptedBatchSlotsIfNeeded()

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
        local cachedInitialMarkers=timeline:GetMarkers() or {}
        local cachedV1Items={}
        for _,item in ipairs(timeline:GetItemListInTrack('video',1) or {}) do
            cachedV1Items[#cachedV1Items+1]={item=item,s=tonumber(item:GetStart()),e=tonumber(item:GetEnd()),name=item:GetName() or '未命名'}
        end
        local cachedAudioTrackItems={}
        for a=1,timeline:GetTrackCount('audio') do
            local alist={}
            for _,item in ipairs(timeline:GetItemListInTrack('audio',a) or {}) do
                alist[#alist+1]={s=item:GetStart(),e=item:GetEnd()}
            end
            cachedAudioTrackItems[a]=alist
        end
        for i=1,state.total do
            local valid,why=pcall(function()
            local prefix='v'..i..'_';local id=assert(p[prefix..'id']);assert(id:match('^%d+$'),'INVALID_VIDEO_ID')
            local s,e=assert(tonumber(p[prefix..'start'])),assert(tonumber(p[prefix..'end']))
            assert(e>s and s>=origin and (not previousEnd or s>=previousEnd+50),'INVALID_VIDEO_RANGE');previousEnd=e
            local marker=resolveImportMarker(cachedInitialMarkers,origin,bid,id,s,e,usedImportMarkerFrames)
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
            local allClips=collectClipsInSegment(timeline,track,segment,cachedV1Items);local last=s
            for _,clip in ipairs(allClips) do assert(clip.s==last and clip.e<=e,'CLIP_RANGE_CHANGED');last=clip.e end
            assert(#allClips>0 and last==e,'VIDEO_RANGE_INCOMPLETE')
            local skippedSources={}
            for skipIndex=1,tonumber(p[prefix..'skip_source_count'] or 0) do
                skippedSources[assert(p[prefix..'skip_source_'..skipIndex])]=true
            end
            -- Group adjacent V1 fragments that belong to the same underlying MP4 source file back into
            -- their original logical small clip [s, e] so re-analysis/repair evaluates the full small clip.
            local logicalClips={}
            for _,clip in ipairs(allClips) do
                local media=clip.item:GetMediaPoolItem()
                local source=platform.path(media and media:GetClipProperty('File Path') or '')
                clip.sourcePath=source
                local prev=logicalClips[#logicalClips]
                if prev and source~='' and prev.sourcePath==source and prev.e==clip.s then
                    prev.e=clip.e
                    prev.lastFragStart=clip.s
                    prev.fragCount=(prev.fragCount or 1)+1
                else
                    logicalClips[#logicalClips+1]={
                        item=clip.item,
                        s=clip.s,
                        e=clip.e,
                        firstFragEnd=clip.e,
                        lastFragStart=clip.s,
                        fragCount=1,
                        sourcePath=source,
                        name=clip.name
                    }
                end
            end
            local clips={}
            for _,clip in ipairs(logicalClips) do
                local excluded=false
                if next(skippedSources) and skippedSources[clip.sourcePath or ''] then
                    excluded=true
                end
                if not excluded then clips[#clips+1]=clip end
            end
            assert(#clips>0,'REANALYZE_NO_REMAINING_V1_CLIPS: '..id)
            -- V2/V3/... are overlays and are deliberately invisible to auto-edit analysis.
            for a,alist in ipairs(cachedAudioTrackItems) do
                for _,aitem in ipairs(alist) do
                    local as,ae=aitem.s,aitem.e
                    if as<e and ae>s then
                        local matching=false;for _,clip in ipairs(allClips) do if clip.s==as and clip.e==ae then matching=true end end
                        assert(matching,'UNRELATED_AUDIO_OVERLAP: '..id)
                    end
                end
            end
            local textPath=base..'/manuscripts/video_'..id..'.txt'
            assert(p[prefix..'manuscript_path']==textPath,'MANUSCRIPT_PATH_MISMATCH')
            jobs[#jobs+1]={id=id,segment=segment,track=track,clips=clips,allClips=allClips,manuscriptPath=textPath,manuscript=readText(textPath),noCut=(p[prefix..'no_cut']=='true')}
            end)
            if not valid then
                local prefix='v'..i..'_';local id=p[prefix..'id'] or tostring(i)
                local skipped={id=id,segment={s=tonumber(p[prefix..'start']) or origin,e=tonumber(p[prefix..'end']) or origin},deferred=true,deferReason=tostring(why),manuscriptPath=p[prefix..'manuscript_path'] or ''}
                validationSkipped[#validationSkipped+1]=skipped
                if not resume then
                    writePairs(base..'/video_'..id..'_alignment.ini',{video_id=id,status='MANUAL_EDIT_REQUIRED',reason=skipped.deferReason,batch_id=bid,task_id=taskId})
                end
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
        pcall(function()
            local srcMap={}
            local srcIdx=0
            for _,job in ipairs(jobs) do
                for _,clip in ipairs(job.clips or {}) do
                    srcIdx=srcIdx+1
                    local sp='s'..srcIdx..'_'
                    local leftOff=(clip.item and clip.item.GetLeftOffset and tonumber(clip.item:GetLeftOffset())) or 0
                    srcMap[sp..'video_id']=tostring(job.id)
                    srcMap[sp..'path']=tostring(clip.sourcePath or '')
                    srcMap[sp..'wav_base_s']=tostring((tonumber(clip.s) or 0)-leftOff)
                    srcMap[sp..'orig_s']=tostring(clip.s or 0)
                    srcMap[sp..'orig_e']=tostring(clip.e or 0)
                end
            end
            srcMap.count=srcIdx
            writePairs(base..'/wav_source_map.ini',srcMap)
            writePairs(root..'/v0_5_0/batches/'..bid..'/wav_source_map.ini',srcMap)
        end)
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
        local jobsToAnalyze={}
        if not resume and not reanalyze then
            local cplan=readPairs(base..'/carried_cut_plan.ini')
            local carriedDone={}
            for vid in tostring(cplan.video_ids or ''):gmatch('[^,]+') do carriedDone[trim(vid)]=true end
            local cByVid={}
            local cCount=tonumber(cplan.candidate_count) or 0
            for i=1,cCount do
                local pre='c'..i..'_'
                local vid=trim(tostring(cplan[pre..'video_id'] or ''))
                local cs,ce,ck=tonumber(cplan[pre..'start']),tonumber(cplan[pre..'end']),cplan[pre..'type']
                if vid~='' and cs and ce and cs<ce and (ck=='HEAD' or ck=='TAIL') then
                    cByVid[vid]=cByVid[vid] or {}
                    table.insert(cByVid[vid],{s=cs,e=ce,kind=ck})
                end
            end
            for _,job in ipairs(jobs) do
                if carriedDone[tostring(job.id)] then
                    local list=cByVid[tostring(job.id)] or {}
                    local allValid=true
                    for _,c in ipairs(list) do
                        local item=findItemByRange(timeline,job.track,c.s,c.e,cachedV1Items)
                        if not (item and item:GetStart()==c.s and item:GetEnd()==c.e and c.s>=job.segment.s and c.e<=job.segment.e) then
                            allValid=false;break
                        end
                    end
                    if allValid then
                        job.alreadyCut=true
                        for _,c in ipairs(list) do
                            carriedCandidates[#carriedCandidates+1]={video_id=job.id,s=c.s,e=c.e,kind=c.kind,job=job,carried=true}
                        end
                    end
                end
            end
        end
        for idx,job in ipairs(jobs) do
            job.jobIndex=idx
            if not job.alreadyCut then
                jobsToAnalyze[#jobsToAnalyze+1]=job
            end
        end
        if not resume then
        local timelineWav=assert(p.timeline_wav_path,'TIMELINE_WAV_PATH_MISSING')
        local timelineWhisperBase=assert(p.timeline_whisper_base,'TIMELINE_WHISPER_PATH_MISSING')
        assert(timelineWav==base..'/audio/timeline.wav','TIMELINE_WAV_PATH_MISMATCH')
        assert(timelineWhisperBase==base..'/whisper/timeline','TIMELINE_WHISPER_PATH_MISMATCH')

        -- Do NOT export from batch start all the way to Timeline end. That can create a very long
        -- WAV and hurt Whisper accuracy. Split the current Studio batch into short analysis WAVs,
        -- each containing at most AUDIO_BATCH_VIDEO_LIMIT complete videos.
        local audioBatches={}
        local k=1
        while k<=#jobsToAnalyze do
            local runEnd=k
            while runEnd<#jobsToAnalyze and (runEnd-k+1)<AUDIO_BATCH_VIDEO_LIMIT and jobsToAnalyze[runEnd+1].jobIndex==jobsToAnalyze[runEnd].jobIndex+1 do
                runEnd=runEnd+1
            end
            local firstJob=jobsToAnalyze[k]
            local lastJob=jobsToAnalyze[runEnd]
            local first=firstJob.jobIndex
            local last=lastJob.jobIndex
            local partIndex=#audioBatches+1
            local stem=(partIndex==1) and 'timeline' or string.format('timeline_part_%03d',partIndex)
            local part={
                index=partIndex,
                first=first,
                last=last,
                s=firstJob.segment.s,
                e=lastJob.segment.e,
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
            for n=k,runEnd do
                local job=jobsToAnalyze[n]
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
                part=partIndex,parts=math.max(1,math.ceil(#jobsToAnalyze/AUDIO_BATCH_VIDEO_LIMIT)),
                first_video=firstJob.id,last_video=lastJob.id,
                video_count=#part.jobs,video_ids=table.concat(part.videoIds,','),
                wav=part.wav,manuscript_bundle=part.manuscriptBundle,
                text_source='Flow Studio per-video manuscripts',audio_batch_limit=AUDIO_BATCH_VIDEO_LIMIT,build='V1.7.8'
            })
            audioBatches[#audioBatches+1]=part
            k=runEnd+1
        end
        local WAV16_PRESET_XML=[=[<?xml version="1.0" encoding="UTF-8"?>
<SmDeliverPresetList DbId="4e731770-e88d-4fb4-8578-137581982de5">
 <FieldsBlob/>
 <PresetList>
  <Element>
   <DbKey>FlowStudio_WAV16</DbKey>
   <DbVal>
    <SyRecordInfo DbId="be2602bf-b22a-431a-a95c-2c62e482382a">
     <FieldsBlob>000000010000000a0000002a00550073006500540069006d0065006c0069006e0065005200650073006f006c007500740069006f006e0000000100010000002800550073006500540069006d0065006c0069006e0065004600720061006d0065005200610074006500000001000100000026005300750062007400690074006c0065005200650063006f007200640043006f00640065006300000002006d73633100000028005300750062007400690074006c0065004500780070006f007200740046006f0072006d006100740000000200000000030000002200520065006e0064006500720041007500640069006f0054007200610063006b00730000000c000000006f00000001000000010000000200300000000c000000005800000001000000020000001c0054007200610063006b0049006e0066006f00560061006c007500650000000200000000010000001a0054007200610063006b0049006e0066006f005400790070006500000002000000000100000024005200650063006f007200640056006900640065006f0045006e00610062006c006500640000000100000000002a005200650063006f007200640041007500640069006f00530061006d0070006c0065005200610074006500000002000000bb800000005e005200650063006f007200640041007500640069006f004e006f0072006d0061006c0069007a006100740069006f006e004f007500740070007500740054007200610063006b00730045006e00610062006c0065005300740061007400650000000c000000001700000001000000010000000200300000000200000000010000002800490073005200650063006f007200640041006c007000680061005000720065006d0075006c0074000000010001000000240043007500730074006f006d00500072006500730065007400490063006f006e00490064000000020000000001</FieldsBlob>
     <RecordClipUniqueName>false</RecordClipUniqueName>
     <RecordBitDepth>8</RecordBitDepth>
     <RecordAsFloat>false</RecordAsFloat>
     <RecordFormatType>wav</RecordFormatType>
     <RecordFormatSubType>lpcm</RecordFormatSubType>
     <RecordAudioEnabled>true</RecordAudioEnabled>
     <RecordAudioNumChannels>2</RecordAudioNumChannels>
     <RecordAudioBitDepth>16</RecordAudioBitDepth>
     <ExtraInfoMap>
      <Element><DbKey>aud_codec</DbKey><DbVal>lpcm</DbVal></Element>
      <Element><DbKey>subs_enable</DbKey><DbVal>0</DbVal></Element>
      <Element><DbKey>aud_discrete</DbKey><DbVal>0</DbVal></Element>
      <Element><DbKey>aud_src_config</DbKey><DbVal>AUX0</DbVal></Element>
      <Element><DbKey>single_wave_file</DbKey><DbVal>1</DbVal></Element>
     </ExtraInfoMap>
    </SyRecordInfo>
   </DbVal>
  </Element>
 </PresetList>
</SmDeliverPresetList>
]=]
        local function ensureWav16RenderPreset(forceSetup)
            local wanted=(p.wav_preset and p.wav_preset~='') and p.wav_preset or 'FlowStudio_WAV16'
            if not forceSetup and project:LoadRenderPreset(wanted) then
                return true
            end
            pulse('AUDIO_RENDERING',(forceSetup and '音频导出异常，正在重新检测并修复 ' or '首次使用未检测到 ')..wanted..' 预设，正在自动配置 WAV 16-bit 导出参数并保存预设…',0)
            -- Layer 1: Try importing the verified FlowStudio_WAV16 XML preset directly into DaVinci Resolve.
            if app and app.ImportRenderPreset and wanted=='FlowStudio_WAV16' then
                local tmpXml=base..'/FlowStudio_WAV16_auto.xml'
                local xf=io.open(tmpXml,'w')
                if xf then
                    xf:write(WAV16_PRESET_XML);xf:close()
                    local okImp,impRes=pcall(function() return app:ImportRenderPreset(tmpXml) end)
                    os.remove(tmpXml)
                    if (okImp and impRes) or project:LoadRenderPreset(wanted) then
                        pcall(function() if project.SetRenderSettings then project:SetRenderSettings({ExportVideo=false,ExportAudio=true,AudioBitDepth=16,AudioSampleRate=48000,ExportSubtitle=false}) end end)
                        pcall(function() if project.SaveAsNewRenderPreset then project:SaveAsNewRenderPreset(wanted) end end)
                        return true
                    end
                end
            end
            -- Layer 2: Universal pure-API setup across all Resolve versions & languages + auto-save preset.
            pcall(function() return project:LoadRenderPreset('Audio Only') or project:LoadRenderPreset('仅音频') end)
            local fmtSet=false
            if project.GetRenderFormats and project.SetCurrentRenderFormatAndCodec then
                local okF,fmts=pcall(function() return project:GetRenderFormats() end)
                if okF and type(fmts)=='table' then
                    for fmtName,ext in pairs(fmts) do
                        local fn=tostring(fmtName or ''):lower()
                        local ex=tostring(ext or ''):lower()
                        if ex=='wav' or ex=='.wav' or fn=='wav' or fn=='wave' then
                            if project.GetRenderCodecs then
                                local okC,codecs=pcall(function() return project:GetRenderCodecs(fmtName) end)
                                if okC and type(codecs)=='table' then
                                    for desc,cName in pairs(codecs) do
                                        local dl=tostring(desc or ''):lower()
                                        local cl=tostring(cName or ''):lower()
                                        if cl:find('pcm',1,true) or dl:find('pcm',1,true) then
                                            local okS,sRes=pcall(function() return project:SetCurrentRenderFormatAndCodec(fmtName,cName) end)
                                            if okS and sRes then fmtSet=true;break end
                                        end
                                    end
                                end
                            end
                            if fmtSet then break end
                        end
                    end
                end
            end
            if not fmtSet and project.SetCurrentRenderFormatAndCodec then
                for _,pair in ipairs({{'wav','LinearPCM'},{'wav','lpcm'},{'Wave','LinearPCM'},{'Wave','lpcm'},{'WAV','LinearPCM'},{'WAV','lpcm'}}) do
                    local okS,sRes=pcall(function() return project:SetCurrentRenderFormatAndCodec(pair[1],pair[2]) end)
                    if okS and sRes then fmtSet=true;break end
                end
            end
            assert(fmtSet,'WAV_PRESET_AUTO_SETUP_FAILED: 无法自动切换 WAV / Linear PCM 音频格式，请在达芬奇交付页手动保存 '..wanted..' 预设')
            if project.SetCurrentRenderMode then pcall(function() project:SetCurrentRenderMode(1) end) end
            if project.SetRenderSettings then
                assert(project:SetRenderSettings({ExportVideo=false,ExportAudio=true}),'WAV_AUDIO_ONLY_SETTINGS_FAILED')
                pcall(function() project:SetRenderSettings({AudioBitDepth=16,AudioSampleRate=48000,ExportSubtitle=false}) end)
                pcall(function() project:SetRenderSettings({AudioCodec='lpcm'}) end)
            end
            if project.SaveAsNewRenderPreset then
                pcall(function() project:SaveAsNewRenderPreset(wanted) end)
            end
            return true
        end
        local presetLoadedOnce=false
        for partNo,part in ipairs(audioBatches) do
            guard();pulse('AUDIO_RENDERING','分批导出 WAV：第 '..partNo..'/'..#audioBatches..' 批（视频 '..jobs[part.first].id..' - '..jobs[part.last].id..'，最多 '..AUDIO_BATCH_VIDEO_LIMIT..' 个）',part.first-1)
            local renderJob={id=part.stem,segment={s=part.s,e=part.e},wav=part.wav}
            if test.render then
                if not presetLoadedOnce then
                    assert(not project:IsRenderingInProgress(),'RENDER_ALREADY_RUNNING')
                    ensureWav16RenderPreset(false)
                    presetLoadedOnce=true
                end
                test.render(renderJob)
            else
                local previousWav=io.open(part.wav,'rb')
                local reuseWav=false
                if previousWav then
                    local wavSize=previousWav:seek('end') or 0
                    previousWav:close()
                    if wavSize>44 then
                        reuseWav=true
                    else
                        os.remove(part.wav)
                    end
                end
                local renderIni=(#audioBatches==1) and (base..'/timeline_render.ini') or (base..string.format('/timeline_render_part_%03d.ini',partNo))
                if reuseWav then
                    pulse('AUDIO_RENDERING','直接复用本批次已导出的 WAV 音频：第 '..partNo..'/'..#audioBatches..' 批',part.first-1)
                    writePairs(renderIni,{task_id=taskId,render_id='REUSED_WAV',status='COMPLETE',part=partNo,parts=#audioBatches,start=part.s,['end']=part.e,expected_videos=#part.jobs,first_video=jobs[part.first].id,last_video=jobs[part.last].id,scope='Reused exact audio analysis batch',manuscript_map=part.manuscriptMap,audio_batch_limit=AUDIO_BATCH_VIDEO_LIMIT,build='V1.8.0'})
                else
                    if not presetLoadedOnce then
                        assert(not project:IsRenderingInProgress(),'RENDER_ALREADY_RUNNING')
                        ensureWav16RenderPreset(false)
                        presetLoadedOnce=true
                    end
                    local function doRenderWavOnce()
                        pcall(function() timeline:ClearMarkInOut('all') end)
                        assert(project:SetCurrentRenderMode(1),'RENDER_SINGLE_CLIP_MODE_FAILED')
                        assert(project:SetRenderSettings({SelectAllFrames=false,MarkIn=part.s,MarkOut=part.e-1,TargetDir=base..'/audio',CustomName=part.stem,ExportVideo=false,ExportAudio=true}),'WAV_RENDER_SETTINGS_FAILED')
                        local renderID=assert(project:AddRenderJob(),'ADD_WAV_RENDER_FAILED')
                        part.renderID=renderID
                        writePairs(renderIni,{task_id=taskId,render_id=renderID,status='QUEUED',part=partNo,parts=#audioBatches,start=part.s,['end']=part.e,expected_videos=#part.jobs,first_video=jobs[part.first].id,last_video=jobs[part.last].id,scope='Exact audio analysis batch',manuscript_map=part.manuscriptMap,audio_batch_limit=AUDIO_BATCH_VIDEO_LIMIT,build='V1.8.0'})
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
                        writePairs(renderIni,{task_id=taskId,render_id=renderID,status='COMPLETE',part=partNo,parts=#audioBatches,start=part.s,['end']=part.e,expected_videos=#part.jobs,first_video=jobs[part.first].id,last_video=jobs[part.last].id,scope='Exact audio analysis batch',manuscript_map=part.manuscriptMap,audio_batch_limit=AUDIO_BATCH_VIDEO_LIMIT,build='V1.8.0'})
                        local f=assert(io.open(part.wav,'rb'),'WAV_OUTPUT_MISSING: '..part.wav..'；请检查 WAV 预设的格式和文件名')
                        local fSize=f:seek('end') or 0
                        f:close()
                        assert(fSize>44,'WAV_OUTPUT_EMPTY: '..part.wav)
                    end
                    local okRender,renderErr=pcall(doRenderWavOnce)
                    if not okRender then
                        -- Only when WAV export fails, re-check / re-create the preset and retry once.
                        local wanted=(p.wav_preset and p.wav_preset~='') and p.wav_preset or 'FlowStudio_WAV16'
                        if not project:LoadRenderPreset(wanted) or tostring(renderErr):find('WAV_',1,true) or tostring(renderErr):find('RENDER_',1,true) then
                            ensureWav16RenderPreset(true)
                            doRenderWavOnce()
                        else
                            error(renderErr)
                        end
                    end
                end
            end
        end
        if #audioBatches>1 then
            writePairs(base..'/timeline_render.ini',{task_id=taskId,status='COMPLETE',parts=#audioBatches,expected_videos=state.total,start=batchStart,['end']=batchEnd,scope='Split WAV analysis; max 20 complete videos per part; manuscript map locked to each WAV',audio_batch_limit=AUDIO_BATCH_VIDEO_LIMIT,build='V1.8.0'})
        end

        assert(snapshot()==frozen,'TIMELINE_CHANGED_DURING_ANALYSIS')
        local asrLabel=(p.asr_provider and p.asr_provider~='') and p.asr_provider or 'Whisper'
        local repairOnly=(p.repair_only=='true')
        local isCloudASR=tostring(p.whisper_cli_path or ''):sub(1,6)=='CLOUD:'
        if not test.whisper then
            local batchTimeout=tonumber(p.whisper_timeout) or 600
            local pendingParts={}
            for partNo,part in ipairs(audioBatches) do
                local reusedSRT=false
                local prevExit=io.open(part.whisperBase..'.exit','r')
                local prevExitCode=nil
                if prevExit then prevExitCode=tonumber(prevExit:read('*a'));prevExit:close() end
                if repairOnly or prevExitCode==0 then
                    local existingWords=parseSRT(part.whisperBase..'.srt')
                    if existingWords and #existingWords>0 then
                        part.words=existingWords
                        reusedSRT=true
                        guard();pulse('WHISPER_RUNNING','直接复用已识别字幕：第 '..partNo..'/'..#audioBatches..' 批',part.first-1)
                    end
                end
                if not reusedSRT then
                    os.remove(part.whisperBase..'.exit');os.remove(part.whisperBase..'.error');os.remove(part.whisperBase..'.srt');os.remove(part.whisperBase..'.pid')
                    local args={p.python_path,p.whisper_runner,'--cli',p.whisper_cli_path,'--model',p.whisper_model_path,'--wav',part.wav,'--output',part.whisperBase,'--language',p.whisper_language,'--duration',tostring((part.e-part.s)/fps),'--fps',tostring(fps),'--timeout',tostring(batchTimeout)}
                    for n,arg in ipairs(args) do args[n]=shellQuote(assert(arg,'WHISPER_CONFIG_MISSING')) end
                    local launch='('..table.concat(args,' ')..' > '..shellQuote(part.whisperBase..'.launcher.log')..' 2>&1 & echo $! > '..shellQuote(part.whisperBase..'.pid')..')'
                    if isCloudASR then
                        os.execute(launch)
                        pendingParts[#pendingParts+1]={partNo=partNo,part=part,started=os.time()}
                    else
                        guard();pulse('WHISPER_RUNNING',asrLabel..' 分批识别：第 '..partNo..'/'..#audioBatches..' 批（视频 '..jobs[part.first].id..' - '..jobs[part.last].id..'）',part.first-1)
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
                            guard();pulse('WHISPER_RUNNING',asrLabel..' 分批识别：第 '..partNo..'/'..#audioBatches..' 批',part.first-1);os.execute('/bin/sleep 1')
                        end
                        if batchOK then
                            local err;part.words,err=parseSRT(part.whisperBase..'.srt')
                            if not part.words or #part.words==0 then batchReason=err or 'WHISPER_BATCH_NO_WORDS';batchOK=false end
                        end
                        if not batchOK then
                            part.words={}
                            part.whisperFailedReason=batchReason or 'WHISPER_BATCH_FAILED'
                            pulse('WHISPER_RUNNING','本批次整体识别异常，改为逐个视频识别；单个失败会自动跳过：'..part.whisperFailedReason,part.first-1)
                        end
                    end
                end
            end
            if #pendingParts>0 then
                local allStarted=os.time()
                while true do
                    local doneCount=0
                    for _,item in ipairs(pendingParts) do
                        local part=item.part
                        if item.done then
                            doneCount=doneCount+1
                        else
                            local exit=io.open(part.whisperBase..'.exit','r')
                            if exit then
                                local code=tonumber(exit:read('*a'));exit:close()
                                item.done=true;doneCount=doneCount+1
                                local batchOK=(code==0)
                                local batchReason=nil
                                if not batchOK then
                                    batchReason='WHISPER_BATCH_EXIT_'..tostring(code or 'UNKNOWN')..': '..trim(readTextOptional(part.whisperBase..'.error'))
                                else
                                    local err;part.words,err=parseSRT(part.whisperBase..'.srt')
                                    if not part.words or #part.words==0 then batchReason=err or 'WHISPER_BATCH_NO_WORDS';batchOK=false end
                                end
                                if not batchOK then
                                    part.words={}
                                    part.whisperFailedReason=batchReason or 'WHISPER_BATCH_FAILED'
                                end
                            elseif os.time()-item.started>=batchTimeout+30 then
                                item.done=true;doneCount=doneCount+1
                                terminatePidFile(part.whisperBase..'.pid')
                                part.words={}
                                part.whisperFailedReason='WHISPER_BATCH_TIMEOUT_'..tostring(batchTimeout+30)..'S'
                            end
                        end
                    end
                    if doneCount>=#pendingParts then break end
                    guard();pulse('WHISPER_RUNNING',asrLabel..' 并发识别中：已完成 '..doneCount..'/'..#pendingParts..' 批',math.floor(doneCount*state.total/#pendingParts))
                    os.execute('/bin/sleep 0.5')
                end
            end
        end

        local manualEditJobs={}
        for _,job in ipairs(validationSkipped) do manualEditJobs[#manualEditJobs+1]=job end
        local maxVideoRetries=tonumber(p.max_video_retries) or MAX_SINGLE_VIDEO_RETRIES
        maxVideoRetries=math.max(0,math.min(2,math.floor(maxVideoRetries)))
        local singleRetryTimeout=tonumber(p.single_video_retry_timeout) or SINGLE_VIDEO_RETRY_TIMEOUT
        singleRetryTimeout=math.max(30,math.min(300,math.floor(singleRetryTimeout)))
        local minConf=isCloudASR and 0.45 or 0.65
        local minCov=isCloudASR and 0.50 or 0.75
        local function passes(a)
            if not a or not a.aligned or a.aligned.confidence<minConf or a.aligned.coverage<minCov or a.unmatched~=0 then return false end
            for _,r in ipairs(a.results or {}) do if r.confidence<minConf then return false end end
            return true
        end
        local silenceProbePath=base..'/silence_probe_v1_8_0.py'
        if not test.silenceProbe and #jobsToAnalyze>0 then
            ensureSilenceProbe(silenceProbePath)
            if p.python_path then
                pulse('TEXT_ALIGNING','批量极速扫描片段首尾静音边界...',0)
                runBatchSilenceProbes(p.python_path, silenceProbePath, audioBatches, fps, base)
            end
        end
        for i,job in ipairs(jobs) do
            guard();local words,err
            if job.alreadyCut then
                pulse('TEXT_ALIGNING','复用已完成切点：视频 '..job.id,i)
            else
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
                local clipCount=#job.clips
                local logLines={}
                local nowStr=os.date('%Y-%m-%d %H:%M:%S')
                for clipIdx=1,clipCount do
                    local clip=job.clips[clipIdx]
                    local relStart=(clip.s-part.s)/fps
                    local duration=(clip.e-clip.s)/fps
                    local probeOut=string.format('%s/whisper/video_%s_clip_%03d_edge_silence.ini',tostring(base),tostring(job.id),clipIdx)
                    local edge,edgeErr=probeEdgeSilence(p.python_path,silenceProbePath,part.wav,relStart,duration,probeOut)
                    if edge then
                        job.clipEdgeSilence[clipIdx]=edge
                        logLines[#logLines+1]=string.format(
                            '%s video=%s clip=%d/%d edge_silence head=%.3f tail=%.3f active=%.3f-%.3f peak_db=%s threshold_used_db=%s\n',
                            nowStr,tostring(job.id),clipIdx,clipCount,
                            tonumber(edge.headSilence) or 0,tonumber(edge.tailSilence) or 0,
                            tonumber(edge.activeStart) or 0,tonumber(edge.activeEnd) or 0,
                            tostring(edge.peakDb or ''),tostring(edge.thresholdUsedDb or EDGE_SILENCE_THRESHOLD_DB)
                        )
                    else
                        logLines[#logLines+1]=string.format(
                            '%s video=%s clip=%d/%d edge_silence_fallback=%s\n',
                            nowStr,tostring(job.id),clipIdx,clipCount,tostring(edgeErr)
                        )
                    end
                end
                if #logLines>0 then
                    local lf=io.open(root..'/logs/'..bid..'/autoedit.log','a')
                    if lf then lf:write(table.concat(logLines,''));lf:close() end
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
            assert(#words*#tokenizeText(job.manuscript)<=5000000,'ALIGNMENT_SIZE_LIMIT')
            whisperRunner=function() return words end
            pulse('TEXT_ALIGNING','使用 Studio 正确文案核对并计算切点：'..job.id,i)
            local analysis,why=analyzeOneVideo(job,fps)
            local retryNo=0
            local lastReason=why or '文案匹配不足'
            while not passes(analysis) and not job.noCut and not test.whisper and retryNo<maxVideoRetries do
                retryNo=retryNo+1
                local retryBase=base..'/whisper/video_'..job.id..'_retry_'..retryNo
                local part=assert(job.audioBatch,'AUDIO_BATCH_NOT_ASSIGNED')
                assert(job.audioBatchIndex==part.index,'AUDIO_BATCH_TEXT_MAP_MISMATCH: '..job.id)
                assert(job.segment.s>=part.s and job.segment.e<=part.e,'AUDIO_BATCH_VIDEO_OUT_OF_RANGE: '..job.id)
                -- Only retry this exact video. A short hard timeout prevents one bad clip from
                -- keeping the whole automatic-edit batch in WHISPER_RUNNING indefinitely.
                os.remove(retryBase..'.exit');os.remove(retryBase..'.error');os.remove(retryBase..'.srt');os.remove(retryBase..'.pid')
                local args={p.python_path,p.whisper_runner,'--cli',p.whisper_cli_path,'--model',p.whisper_model_path,'--wav',part.wav,'--output',retryBase,'--language',p.whisper_language,'--start',tostring((job.segment.s-part.s)/fps),'--duration',tostring((job.segment.e-job.segment.s)/fps),'--fps',tostring(fps),'--timeout',tostring(singleRetryTimeout)}
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
                assert(#words*#tokenizeText(job.manuscript)<=5000000,'ALIGNMENT_SIZE_LIMIT')
                whisperRunner=function() return words end
                analysis,why=analyzeOneVideo(job,fps)
                lastReason=why or '文案匹配仍不足'
            end
            if passes(analysis) or job.noCut then
                if analysis and job.noCut then analysis.cutCount=0 end
                job.analysis=analysis or {aligned={confidence=1.0,coverage=1.0},unmatched=0,cutCount=0,results={}}
                writePairs(base..'/video_'..job.id..'_alignment.ini',{video_id=job.id,batch_id=bid,task_id=taskId,status='COMPLETE',audio_part=assert(job.audioBatchIndex),audio_wav=assert(job.wav),manuscript_path=assert(job.manuscriptPath),text_source='Flow Studio',confidence=job.analysis.aligned.confidence,coverage=job.analysis.aligned.coverage,unmatched=job.analysis.unmatched,candidate_count=job.noCut and 0 or job.analysis.cutCount,no_cut=tostring(job.noCut or false),retries=retryNo,edge_scan_mode='PER_SMALL_CLIP',edge_scan_count=#job.clips,edge_scan_success_count=(function() local n=0;for _ in pairs(job.clipEdgeSilence or {}) do n=n+1 end;return n end)(),silence_threshold_floor_db=EDGE_SILENCE_THRESHOLD_DB,build='V1.7.8'})
            else
                job.deferred=true
                job.deferReason=tostring(lastReason or 'TEXT_ALIGNMENT_FAILED')
                manualEditJobs[#manualEditJobs+1]=job
                writePairs(base..'/video_'..job.id..'_alignment.ini',{video_id=job.id,batch_id=bid,task_id=taskId,status='MANUAL_EDIT_REQUIRED',audio_part=assert(job.audioBatchIndex),audio_wav=assert(job.wav),manuscript_path=assert(job.manuscriptPath),text_source='Flow Studio',reason=job.deferReason,retries=retryNo,build='V1.7.8'})
                pulse('TEXT_ALIGNING','视频 '..job.id..' 识别未通过，已自动跳过；稍后用橙色标记供手动剪辑',i)
            end
            end -- not job.alreadyCut
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
        if #carriedCandidates>0 then
            local byId={};for _,job in ipairs(jobs) do byId[job.id]=job end
            for _,old in ipairs(carriedCandidates) do
                local job=byId[old.video_id] or old.job
                local item=job and findItemByRange(timeline,job.track,old.s,old.e) or nil
                if job and item and old.s>=job.segment.s and old.e<=job.segment.e then
                    candidates[#candidates+1]={s=old.s,e=old.e,kind=old.kind,job=job,carried=true}
                end
            end
        end
        for _,job in ipairs(jobs) do
            if job.analysis and not job.noCut then
            for _,r in ipairs(job.analysis.results) do
                if r.clip.fragCount and r.clip.fragCount>1 then
                    if r.headFrames and r.headFrames>0 and r.clip.firstFragEnd and r.keepStart>r.clip.firstFragEnd then
                        r.keepStart=r.clip.firstFragEnd
                        r.headFrames=r.keepStart-r.clip.s
                        if r.headFrames<MIN_TRIM_FRAMES then r.headFrames=0;r.keepStart=r.clip.s end
                    end
                    if r.tailFrames and r.tailFrames>0 and r.clip.lastFragStart and r.keepEnd<r.clip.lastFragStart then
                        r.keepEnd=r.clip.lastFragStart
                        r.tailFrames=r.clip.e-r.keepEnd
                        if r.tailFrames<MIN_TRIM_FRAMES then r.tailFrames=0;r.keepEnd=r.clip.e end
                    end
                end
                for _,part in ipairs({{r.headFrames,r.clip.s,r.keepStart,'HEAD'},{r.tailFrames,r.keepEnd,r.clip.e,'TAIL'}}) do
                    if part[1] and part[1]>0 then
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
        guard();assert(snapshot()==frozen,'TIMELINE_CHANGED_BEFORE_CUTTING')
        cutting=true
        local manualEditCount=0;for _,job in ipairs(jobs) do if job.deferred then manualEditCount=manualEditCount+1 end end
        table.sort(cuts,function(a,b) return a.frame<b.frame end)
        local postCutVideoItems={}
        local usedDeliverFastPath=false

        if test.blade then
            -- Legacy injected blade callback path (kept for mock unit-test compatibility)
            if #cuts>0 then
                assert((test.openEdit or openEditPage)(app),'OPEN_EDIT_PAGE_FAILED')
                if not test.openEdit then
                    local ready=false
                    for i=1,20 do if app:GetCurrentPage()=='edit' then ready=true;break end;os.execute('/bin/sleep 0.1') end
                    assert(ready,'EDIT_PAGE_NOT_READY')
                end
            end
            pulse('CUTTING','可识别视频开始切刀；已跳过 '..manualEditCount..' 个识别失败视频，稍后标橙色供手动剪辑',0)
            local trackRanges,expectedCount={video={},audio={}},{video={},audio={}}
            for _,kind in ipairs({'video','audio'}) do
                for track=1,timeline:GetTrackCount(kind) do
                    local list={}
                    for _,item in ipairs(timeline:GetItemListInTrack(kind,track) or {}) do list[#list+1]={item:GetStart(),item:GetEnd()} end
                    trackRanges[kind][track]=list;expectedCount[kind][track]=#list
                end
            end
            local function splitCachedRange(list,frame)
                if not list then return end
                for idx,r in ipairs(list) do
                    if r[1]<frame and r[2]>frame then
                        local oldEnd=r[2];r[2]=frame;table.insert(list,idx+1,{frame,oldEnd});return
                    end
                end
            end
            local fastConfirm=test.fastConfirm
            for i,cut in ipairs(cuts) do
                if i==1 or i==#cuts or i%10==0 then
                    guard();pulse('CUTTING','执行并核验切刀 '..i..' / '..#cuts,0)
                end
                local crossing={video={},audio={}}
                local touchingAudio={}
                for _,kind in ipairs({'video','audio'}) do
                    for track,list in pairs(trackRanges[kind]) do
                        for _,r in ipairs(list) do
                            if r[1]<cut.frame and r[2]>cut.frame then crossing[kind][track]=true;break end
                            if kind=='audio' and (r[1]==cut.frame or r[2]==cut.frame) then touchingAudio[track]=true end
                        end
                    end
                end
                local audioTracks={}
                for track in pairs(crossing.audio) do audioTracks[track]=true end
                for track in pairs(touchingAudio) do audioTracks[track]=true end
                cut.audioTracks=audioTracks
                if not test.openEdit then assert(app:GetCurrentPage()=='edit','EDIT_PAGE_CHANGED') end
                local already=cutBoundary(timeline,'video',cut.job.track,cut.frame,fastConfirm and trackRanges.video[cut.job.track] or nil)
                for track in pairs(audioTracks) do already=already and cutBoundary(timeline,'audio',track,cut.frame,fastConfirm and trackRanges.audio[track] or nil) end
                if not already then
                    local success,why=test.blade(timeline,cut.frame,fps);assert(success,why)
                    if fastConfirm then
                        for _,kind in ipairs({'video','audio'}) do
                            for track in pairs(crossing[kind]) do
                                expectedCount[kind][track]=expectedCount[kind][track]+1
                                splitCachedRange(trackRanges[kind][track],cut.frame)
                            end
                        end
                    end
                end
                if not fastConfirm then
                    confirmCut(timeline,cut.frame,cut.job.track,audioTracks,guard)
                end
            end
            closeBladeProc()
            if fastConfirm then
                for repairPass=1,4 do
                    guard()
                    if repairPass==1 then pulse('CUTTING','核验全部切点 '..#cuts,0) end
                    local actual={video={},audio={}}
                    local startsMap,endsMap={video={},audio={}},{video={},audio={}}
                    postCutVideoItems={}
                    for _,kind in ipairs({'video','audio'}) do
                        for track in pairs(trackRanges[kind]) do
                            local list,sMap,eMap={},{},{}
                            local vlist=(kind=='video') and {} or nil
                            for _,item in ipairs(timeline:GetItemListInTrack(kind,track) or {}) do
                                local s,e=item:GetStart(),item:GetEnd()
                                list[#list+1]={s,e}
                                sMap[s]=true;eMap[e]=true
                                if vlist then vlist[#vlist+1]={item=item,s=s,e=e} end
                            end
                            actual[kind][track]=list
                            startsMap[kind][track]=sMap
                            endsMap[kind][track]=eMap
                            if vlist then postCutVideoItems[track]=vlist end
                        end
                    end
                    local function boundaryOK(kind,track,frame)
                        local sMap=startsMap[kind][track]
                        local eMap=endsMap[kind][track]
                        if not (sMap and eMap and sMap[frame] and eMap[frame]) then return false end
                        for _,r in ipairs(actual[kind][track] or {}) do
                            if r[1]<frame and r[2]>frame then return false end
                        end
                        return true
                    end
                    if repairPass==4 then
                        for _,cut in ipairs(cuts) do
                            assert(boundaryOK('video',cut.job.track,cut.frame),'CUT_NOT_CONFIRMED: frame='..cut.frame..' 视频切刀未确认；保留现场')
                            for track in pairs(cut.audioTracks or {}) do
                                assert(boundaryOK('audio',track,cut.frame),'AUDIO_CUT_NOT_CONFIRMED: frame='..cut.frame..' audio_track='..track..' 视频已切开但音频未同步；保留现场')
                            end
                        end
                        break
                    end
                    local missed={}
                    for _,cut in ipairs(cuts) do
                        local okCut=boundaryOK('video',cut.job.track,cut.frame)
                        if okCut then
                            for track in pairs(cut.audioTracks or {}) do
                                if not boundaryOK('audio',track,cut.frame) then okCut=false;break end
                            end
                        end
                        if not okCut then missed[#missed+1]=cut end
                    end
                    if #missed==0 then break end
                    local lf=io.open(root..'/logs/'..bid..'/autoedit.log','a')
                    if lf then
                        lf:write(os.date('%Y-%m-%d %H:%M:%S')..' SELF_HEAL_CUTS pass='..repairPass..' missed='..#missed..'\n')
                        lf:close()
                    end
                    pulse('CUTTING','自动补切漏切边界（第 '..repairPass..' 轮，剩余 '..#missed..' 处）',0)
                    if not test.openEdit then openEditPage(app) end
                    local focused,focusErr=(test.focus or prepareTimelineFocus)()
                    assert(focused,'TIMELINE_REFOCUS_FAILED: '..tostring(focusErr))
                    bladeFocusAt=os.time();bladesSinceFocus=1
                    for mIdx,cut in ipairs(missed) do
                        if mIdx==1 or mIdx==#missed or mIdx%5==0 then guard() end
                        local success,why=test.blade(timeline,cut.frame,fps);assert(success,why)
                        pcall(confirmCut,timeline,cut.frame,cut.job.track,cut.audioTracks or {},guard)
                    end
                    closeBladeProc()
                end
            else
                for track=1,timeline:GetTrackCount('video') do
                    local vlist={}
                    for _,item in ipairs(timeline:GetItemListInTrack('video',track) or {}) do
                        vlist[#vlist+1]={item=item,s=item:GetStart(),e=item:GetEnd()}
                    end
                    postCutVideoItems[track]=vlist
                end
            end
        else
            -- Solution 1: Native API Batch Sub-Clip Rebuild on Deliver page (zero keystrokes, zero focus hijack, ~2-5s for 1000 cuts).
            assert(not timeline:GetIsTrackLocked('video',1),'TRACK_LOCKED: video 1')
            local hasA1=(tonumber(timeline:GetTrackCount('audio')) or 0)>=1
            if hasA1 then
                assert(not timeline:GetIsTrackLocked('audio',1),'TRACK_LOCKED: audio 1')
            end

            -- Switch to Deliver page to disable Edit-page waveform/filmstrip/viewer redraws during bulk sub-clip rebuild & marker creation.
            if app.OpenPage then
                pcall(function()
                    if not app.GetCurrentPage or app:GetCurrentPage()~='deliver' then
                        app:OpenPage('deliver')
                    end
                end)
                usedDeliverFastPath=true
            end

            pulse('CUTTING','开始后台极速子片段切分（共 '..#cuts..' 处切点，无需占用鼠标键盘焦点；已跳过 '..manualEditCount..' 个识别失败视频）',0)

            -- Deduplicate cut frames per video track in ascending order.
            local uniqueCuts={}
            for _,cut in ipairs(cuts) do
                local prev=uniqueCuts[#uniqueCuts]
                if not prev or prev.frame~=cut.frame or prev.track~=cut.job.track then
                    uniqueCuts[#uniqueCuts+1]={frame=cut.frame,track=cut.job.track,job=cut.job}
                end
            end

            if #uniqueCuts>0 then
                local v1Raw=timeline:GetItemListInTrack('video',1) or {}
                local a1Raw=hasA1 and (timeline:GetItemListInTrack('audio',1) or {}) or {}
                local a1ByRange={}
                for _,ait in ipairs(a1Raw) do
                    local as,ae=tonumber(ait:GetStart()),tonumber(ait:GetEnd())
                    if as and ae then a1ByRange[as..':'..ae]=ait end
                end

                local DEFAULT_VPROPS={
                    ZoomX=1.0,ZoomY=1.0,Pan=0.0,Tilt=0.0,RotationAngle=0.0,
                    AnchorPointX=0.0,AnchorPointY=0.0,
                    CropLeft=0.0,CropRight=0.0,CropTop=0.0,CropBottom=0.0,Opacity=100.0,
                }

                local syncItems={}
                local extraSpecs={}
                local cutCursor=1
                local nUnique=#uniqueCuts

                for _,vItem in ipairs(v1Raw) do
                    local vs,ve=safeClipInt(vItem,'GetStart'),safeClipInt(vItem,'GetEnd')
                    if vs and ve and ve>vs then
                        while cutCursor<=nUnique and uniqueCuts[cutCursor].frame<=vs do
                            cutCursor=cutCursor+1
                        end
                        local pts={vs}
                        local scan=cutCursor
                        while scan<=nUnique and uniqueCuts[scan].frame<ve do
                            local cf=uniqueCuts[scan].frame
                            if cf>pts[#pts] then pts[#pts+1]=cf end
                            scan=scan+1
                        end
                        if #pts>1 then
                            pts[#pts+1]=ve
                            cutCursor=scan

                            local mpItem=assert(vItem:GetMediaPoolItem(),'CUT_CLIP_MEDIAPOOL_MISSING')
                            local rawPath=''
                            pcall(function() rawPath=tostring(mpItem:GetClipProperty('File Path') or '') end)
                            local mpStart=0
                            pcall(function()
                                local sProp=tonumber(mpItem:GetClipProperty('Start'))
                                if sProp then mpStart=sProp end
                            end)
                            local origLeft=safeClipInt(vItem,'GetLeftOffset') or 0

                            local vProps=nil
                            if vItem.GetProperty then
                                local okAll,allP=pcall(function() return vItem:GetProperty() end)
                                if okAll and type(allP)=='table' then
                                    for pk,defVal in pairs(DEFAULT_VPROPS) do
                                        local num=tonumber(allP[pk])
                                        if num and math.abs(num-defVal)>0.0005 then
                                            vProps=vProps or {}
                                            vProps[pk]=num
                                        end
                                    end
                                else
                                    for pk,defVal in pairs(DEFAULT_VPROPS) do
                                        local okP,pv=pcall(function() return vItem:GetProperty(pk) end)
                                        local num=okP and tonumber(pv) or nil
                                        if num and math.abs(num-defVal)>0.0005 then
                                            vProps=vProps or {}
                                            vProps[pk]=num
                                        end
                                    end
                                end
                            end

                            local aItem=a1ByRange[vs..':'..ve]
                            local hasClipAudio=(aItem~=nil)
                            local aProps=nil
                            if aItem and aItem.GetProperty then
                                local okVol,vol=pcall(function() return tonumber(aItem:GetProperty('Volume')) end)
                                if okVol and vol and math.abs(vol-0.0)>0.001 and math.abs(vol-1.0)>0.001 then
                                    aProps={Volume=vol}
                                end
                            end

                            -- Fragment 1 [pts[1], pts[2]): keep existing V1/A1 clip in-place (ZERO DeleteClips!),
                            -- shortening its Duration atomically in Project.db while preserving all clip metadata/links.
                            local vUid=''
                            if vItem.GetUniqueId then pcall(function() vUid=tostring(vItem:GetUniqueId() or '') end) end
                            syncItems[#syncItems+1]={
                                uid=vUid,
                                kind='video',
                                start=pts[1],
                                duration=pts[2]-pts[1],
                                in_offset=origLeft,
                                path=rawPath,
                            }
                            if aItem then
                                local aUid=''
                                if aItem.GetUniqueId then pcall(function() aUid=tostring(aItem:GetUniqueId() or '') end) end
                                syncItems[#syncItems+1]={
                                    uid=aUid,
                                    kind='audio',
                                    start=pts[1],
                                    duration=pts[2]-pts[1],
                                    in_offset=origLeft,
                                    path=rawPath,
                                }
                            end

                            -- Fragments 2..#pts-1: batch-append lightweight 2-frame instances (`endFrame = mpStart + 2` is
                            -- exclusive in DaVinci Resolve -> 2 source frames, always > 0!) at timeline tail, then place
                            -- at exact [segS, segE) + In=inTl in the single Project.db transaction.
                            for k=2,#pts-1 do
                                local segS,segE=pts[k],pts[k+1]
                                local dur=segE-segS
                                local inTl=origLeft+(segS-vs)
                                local cInfo={
                                    mediaPoolItem=mpItem,
                                    startFrame=mpStart,
                                    endFrame=mpStart+2,
                                    trackIndex=1,
                                }
                                if not hasClipAudio then cInfo.mediaType=1 end
                                extraSpecs[#extraSpecs+1]={
                                    s=segS,
                                    e=segE,
                                    dur=dur,
                                    inTl=inTl,
                                    hasAudio=hasClipAudio,
                                    rawPath=rawPath,
                                    vProps=vProps,
                                    aProps=aProps,
                                    clipInfo=cInfo,
                                }
                            end
                        end
                    end
                end

                if #extraSpecs>0 then
                    local pool=assert(project:GetMediaPool(),'MEDIA_POOL_UNAVAILABLE')
                    local existingVUids,existingAUids={},{}
                    for _,it in ipairs(v1Raw) do
                        if it.GetUniqueId then pcall(function() existingVUids[tostring(it:GetUniqueId() or '')]=true end) end
                    end
                    for _,it in ipairs(a1Raw) do
                        if it.GetUniqueId then pcall(function() existingAUids[tostring(it:GetUniqueId() or '')]=true end) end
                    end

                    -- Temporarily lock V2+ and A2+ so upper overlays/music tracks are 100% protected.
                    local savedLocks={}
                    local function lockProtectedTracks()
                        for _,kind in ipairs({'video','audio'}) do
                            local tCnt=tonumber(timeline:GetTrackCount(kind)) or 0
                            for trk=2,tCnt do
                                local wasLocked=timeline:GetIsTrackLocked(kind,trk)
                                savedLocks[#savedLocks+1]={kind=kind,track=trk,locked=wasLocked}
                                if not wasLocked then
                                    pcall(function() timeline:SetTrackLock(kind,trk,true) end)
                                end
                            end
                        end
                    end
                    local function restoreProtectedTracks()
                        for _,entry in ipairs(savedLocks) do
                            if not entry.locked then
                                pcall(function() timeline:SetTrackLock(entry.kind,entry.track,false) end)
                            end
                        end
                    end

                    local appendOk,appendErr=pcall(function()
                        lockProtectedTracks()
                        local APPEND_CHUNK=200
                        for cStart=1,#extraSpecs,APPEND_CHUNK do
                            local cEnd=math.min(#extraSpecs,cStart+APPEND_CHUNK-1)
                            local chunk={}
                            for idx=cStart,cEnd do chunk[#chunk+1]=extraSpecs[idx].clipInfo end
                            guard()
                            pulse('CUTTING','极速批量创建子片段 '..tostring(cEnd)..' / '..tostring(#extraSpecs),0)
                            local okBatch,placedBatch=pcall(function() return pool:AppendToTimeline(chunk) end)
                            if not (okBatch and placedBatch) then
                                for idx=cStart,cEnd do
                                    assert(pool:AppendToTimeline({extraSpecs[idx].clipInfo}),'SUBCLIP_APPEND_SINGLE_FAILED: '..tostring(idx))
                                end
                            end
                        end
                    end)
                    restoreProtectedTracks()
                    if not appendOk then error(appendErr) end

                    local newVClips={}
                    for _,it in ipairs(timeline:GetItemListInTrack('video',1) or {}) do
                        local uid=''
                        if it.GetUniqueId then pcall(function() uid=tostring(it:GetUniqueId() or '') end) end
                        if uid~='' and not existingVUids[uid] then
                            newVClips[#newVClips+1]={it=it,uid=uid,st=safeClipInt(it,'GetStart') or 0}
                        end
                    end
                    table.sort(newVClips,function(a,b) return a.st<b.st end)
                    assert(#newVClips==#extraSpecs,'SUBCLIP_NEW_VIDEO_COUNT_MISMATCH: '..tostring(#newVClips)..' vs '..tostring(#extraSpecs))

                    local extraAudioSpecs={}
                    for _,sub in ipairs(extraSpecs) do
                        if sub.hasAudio then extraAudioSpecs[#extraAudioSpecs+1]=sub end
                    end
                    local newAClips={}
                    if hasA1 and #extraAudioSpecs>0 then
                        for _,it in ipairs(timeline:GetItemListInTrack('audio',1) or {}) do
                            local uid=''
                            if it.GetUniqueId then pcall(function() uid=tostring(it:GetUniqueId() or '') end) end
                            if uid~='' and not existingAUids[uid] then
                                newAClips[#newAClips+1]={it=it,uid=uid,st=safeClipInt(it,'GetStart') or 0}
                            end
                        end
                        table.sort(newAClips,function(a,b) return a.st<b.st end)
                        assert(#newAClips==#extraAudioSpecs,'SUBCLIP_NEW_AUDIO_COUNT_MISMATCH: '..tostring(#newAClips)..' vs '..tostring(#extraAudioSpecs))
                    end

                    for idx,sub in ipairs(extraSpecs) do
                        local vc=newVClips[idx]
                        if sub.vProps and vc.it.SetProperty then
                            for pk,pv in pairs(sub.vProps) do
                                assert(vc.it:SetProperty(pk,pv),'SUBCLIP_TRANSFORM_SET_FAILED: '..tostring(pk))
                            end
                        end
                        syncItems[#syncItems+1]={
                            uid=vc.uid,
                            kind='video',
                            start=sub.s,
                            duration=sub.dur,
                            in_offset=sub.inTl,
                            path=sub.rawPath,
                        }
                    end
                    for idx,sub in ipairs(extraAudioSpecs) do
                        local ac=newAClips[idx]
                        if sub.aProps and ac.it.SetProperty then
                            for pk,pv in pairs(sub.aProps) do
                                pcall(function() ac.it:SetProperty(pk,pv) end)
                            end
                        end
                        syncItems[#syncItems+1]={
                            uid=ac.uid,
                            kind='audio',
                            start=sub.s,
                            duration=sub.dur,
                            in_offset=sub.inTl,
                            path=sub.rawPath,
                        }
                    end

                    pulse('CUTTING','正在帧级精确校准 '..tostring(#syncItems)..' 个子片段入出点...',0)
                    runSubclipDbSync(syncItems,'subclip_sync.ini')
                end
            end

            -- Final single-pass verification of all V1 & A1 cut boundaries + build postCutVideoItems cache.
            pulse('CUTTING','核验全部切点 '..#cuts,0)
            local vStarts,vEnds={},{}
            local vCached={}
            for _,item in ipairs(timeline:GetItemListInTrack('video',1) or {}) do
                local s,e=tonumber(item:GetStart()),tonumber(item:GetEnd())
                if s and e then
                    vStarts[s]=true;vEnds[e]=true
                    vCached[#vCached+1]={item=item,s=s,e=e}
                end
            end
            postCutVideoItems[1]=vCached

            local aStarts,aEnds={},{}
            local aRanges={}
            if hasA1 then
                for _,item in ipairs(timeline:GetItemListInTrack('audio',1) or {}) do
                    local s,e=tonumber(item:GetStart()),tonumber(item:GetEnd())
                    if s and e then
                        aStarts[s]=true;aEnds[e]=true
                        aRanges[#aRanges+1]={s,e}
                    end
                end
            end

            for _,uc in ipairs(uniqueCuts) do
                local cf=uc.frame
                assert(vStarts[cf] and vEnds[cf],'CUT_NOT_CONFIRMED: frame='..tostring(cf)..' 视频子片段切分未确认')
                for _,vc in ipairs(vCached) do
                    assert(not (vc.s<cf and vc.e>cf),'CUT_CROSSING_REMAINED: frame='..tostring(cf))
                end
                if hasA1 then
                    local hasTouchingAudio=aStarts[cf] or aEnds[cf]
                    for _,ar in ipairs(aRanges) do
                        assert(not (ar[1]<cf and ar[2]>cf),'AUDIO_CUT_NOT_CONFIRMED: frame='..tostring(cf)..' 音频子片段仍跨越切点')
                    end
                    if hasTouchingAudio then
                        assert(aStarts[cf] and aEnds[cf],'AUDIO_CUT_NOT_CONFIRMED: frame='..tostring(cf)..' 音频子片段边界未对齐')
                    end
                end
            end
        end

        local postCutMarkers=timeline:GetMarkers() or {}
        for i,c in ipairs(candidates) do
            if i==1 or i%100==0 then guard() end
            local item=findItemByRange(timeline,c.job.track,c.s,c.e,postCutVideoItems[c.job.track])
            assert(item and item:GetStart()==c.s and item:GetEnd()==c.e,'CANDIDATE_RANGE_NOT_CONFIRMED')
            local markers=postCutMarkers;local frame=c.s-origin
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
            local dur=c.e-origin-frame
            assert(timeline:AddMarker(frame,'Red','待检查 '..c.kind,'批次 '..bid..' / 视频 '..c.job.id,dur,custom),'CANDIDATE_MARKER_FAILED')
            markers[frame]={color='Red',customData=custom,duration=dur}
        end
        -- Recognition/alignment failures do not stop the batch. Leave their clips untouched and
        -- mark the complete video range Orange so the operator can jump straight to manual editing.
        for _,job in ipairs(jobs) do
            if job.deferred then
                guard();addManualEditMarker(timeline,origin,bid,attempt,job,job.deferReason,postCutMarkers)
            end
        end
        local manualEditIds={}
        for _,job in ipairs(validationSkipped) do
            manualEditIds[#manualEditIds+1]=job.id
            pcall(addManualEditMarker,timeline,origin,bid,attempt,job,job.deferReason,postCutMarkers)
        end
        for _,job in ipairs(jobs) do if job.deferred then manualEditIds[#manualEditIds+1]=job.id end end

        -- Return to Edit page after bulk sub-clip rebuild & marker creation so operator sees the cut timeline directly.
        if usedDeliverFastPath and app.OpenPage then
            pcall(function() app:OpenPage('edit') end)
        end

        collectgarbage('collect')
        assert(pm:SaveProject(),'SAVE_PROJECT_FAILED')
        pulse('WAITING_USER_REVIEW',(reanalyze and '重新识别完成；已保留原切点并补充新的头尾切点；' or '自动剪辑完成；')..'识别失败已跳过 '..#manualEditIds..' 个，橙色 Marker 请手动剪辑',#jobs)
        return {stage='WAITING_USER_REVIEW',project=p.project_name,timeline=p.timeline_name,batch_id=bid,task_id=taskId,candidate_count=#candidates,deferred_count=#manualEditIds,deferred_video_ids=table.concat(manualEditIds,','),manual_edit_count=#manualEditIds,manual_edit_video_ids=table.concat(manualEditIds,','),manual_marker_color=MANUAL_EDIT_MARKER_COLOR}
    end)
    whisperRunner=nil
    closeBladeProc()
    if not ok then pulse((cutting or resume) and 'CUTTING_ERROR' or 'ANALYSIS_ERROR',tostring(result));error(result) end
    return result
end
return {run=runBatch,align=alignWithPairs,analyze=analyzeOneVideo,parseSRT=parseSRT,confirmCut=confirmCut}
