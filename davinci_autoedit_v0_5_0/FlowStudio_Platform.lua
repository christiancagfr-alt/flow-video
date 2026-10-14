-- Platform-local OS facade. Never changes Resolve's global os/io tables.
if _G.__FLOWSTUDIO_PLATFORM then return _G.__FLOWSTUDIO_PLATFORM end
local nativeOS, nativeIO = os, io
local windows = type(package) == 'table' and type(package.config) == 'string' and package.config:sub(1, 1) == '\\'
local P = {windows=windows, os=os, io=io, loadfile=loadfile}
function P.path(s) return P.windows and tostring(s):gsub('\\','/') or s end
local source = ''
if type(debug) == 'table' and type(debug.getinfo) == 'function' then
    local info = debug.getinfo(1, 'S')
    source = info and info.source or ''
end
source = tostring(source):sub(2)
P.directory=P.path(source):match('^(.*)/[^/]+$') or ''
if not P.windows then return P end
local ffi=assert(require('ffi'),'Windows bridge requires LuaJIT FFI')
ffi.cdef[[
typedef struct { unsigned long cb; wchar_t *reserved; wchar_t *desktop; wchar_t *title; unsigned long x,y,xsize,ysize,xchars,ychars,fill,flags; unsigned short show,cbreserved; unsigned char *reserved2; void *input,*output,*error; } FS_STARTUP;
typedef struct { void *process,*thread; unsigned long pid,tid; } FS_PROCESS;
int MultiByteToWideChar(unsigned int,unsigned long,const char*,int,wchar_t*,int);
int CreateProcessW(const wchar_t*,wchar_t*,void*,void*,int,unsigned long,void*,const wchar_t*,FS_STARTUP*,FS_PROCESS*);
unsigned long WaitForSingleObject(void*,unsigned long);
int GetExitCodeProcess(void*,unsigned long*);
int TerminateProcess(void*,unsigned int);
int CloseHandle(void*);
unsigned long GetCurrentProcessId(void);
void Sleep(unsigned long);
int MoveFileExW(const wchar_t*,const wchar_t*,unsigned long);
int DeleteFileW(const wchar_t*);
void *GetForegroundWindow(void);
unsigned long GetWindowThreadProcessId(void*,unsigned long*);
void keybd_event(unsigned char,unsigned char,unsigned long,uintptr_t);
void *_wfopen(const wchar_t*,const wchar_t*);
size_t fread(void*,size_t,size_t,void*);
size_t fwrite(const void*,size_t,size_t,void*);
int fclose(void*); int fflush(void*); int fgetc(void*);
int fseek(void*,long,int); long ftell(void*);
]]
local K=ffi.load('kernel32');local U=ffi.load('user32');local C=ffi.load('msvcrt')
local function wide(text)
    text=tostring(text)
    local n=K.MultiByteToWideChar(65001,0,text,#text,nil,0)
    local out=ffi.new('wchar_t[?]',n+1)
    K.MultiByteToWideChar(65001,0,text,#text,out,n)
    return out
end
local function open(path,mode)
    local handle=C._wfopen(wide(path),wide(mode or 'r'))
    if handle==nil then return nil,'Cannot open '..tostring(path) end
    local file={handle=handle}
    function file:close() if self.handle then C.fclose(self.handle);self.handle=nil end;return true end
    function file:flush() return C.fflush(self.handle)==0 end
    function file:write(...)
        for _,value in ipairs({...}) do local s=tostring(value);assert(tonumber(C.fwrite(s,1,#s,self.handle))==#s,'WRITE_FAILED') end
        return self
    end
    function file:read(mode)
        mode=mode or '*l'
        if type(mode)=='number' then
            local buffer=ffi.new('char[?]',math.max(1,mode));local n=tonumber(C.fread(buffer,1,mode,self.handle))
            return n>0 and ffi.string(buffer,n) or nil
        end
        if mode=='*a' or mode=='a' then
            local parts={}
            while true do local chunk=self:read(8192);if not chunk then break end;parts[#parts+1]=chunk end
            return table.concat(parts)
        end
        local chars={}
        while true do
            local ch=C.fgetc(self.handle)
            if ch==-1 then return #chars>0 and table.concat(chars) or nil end
            if ch==10 then return table.concat(chars) end
            if ch~=13 then chars[#chars+1]=string.char(ch) end
        end
    end
    function file:lines() return function() return self:read('*l') end end
    function file:seek(whence,offset)
        local codes={set=0,cur=1,['end']=2}
        if C.fseek(self.handle,offset or 0,codes[whence or 'cur'])~=0 then return nil end
        return tonumber(C.ftell(self.handle))
    end
    return file
end
P.io=setmetatable({open=open},{__index=nativeIO})
P.os=setmetatable({},{__index=nativeOS})
function P.os.getenv(key)
    return key=='HOME' and P.path(nativeOS.getenv('USERPROFILE')) or nativeOS.getenv(key)
end
function P.os.rename(old,new)
    if K.MoveFileExW(wide(old),wide(new),1)~=0 then return true end
    return nil,'RENAME_FAILED: '..old
end
function P.os.remove(path)
    return K.DeleteFileW(wide(path))~=0
end
function P.loadfile(path)
    local file,err=open(path,'rb');if not file then return nil,err end
    local text=file:read('*a');file:close()
    return loadstring(text,'@'..path)
end
local config={}
local file=assert(open(P.directory..'/windows-runtime.ini','r'),'WINDOWS_RUNTIME_NOT_INSTALLED')
for line in file:lines() do local k,v=line:match('^([^=]+)=(.*)$');if k then config[k]=v end end
file:close()
local serial=0
local function quoteWindows(s)
    s=tostring(s);s=s:gsub('(\\*)"','%1%1\\"'):gsub('(\\+)$','%1%1')
    return '"'..s..'"'
end
function P.rpc(command)
    serial=serial+1
    local request=P.directory..'/windows-request-'..tonumber(K.GetCurrentProcessId())..'-'..serial..'.txt'
    local output=request:gsub('%.txt$','.out')
    local f=assert(open(request,'wb'));f:write(command);f:close()
    local args={config.python,config.helper,'--request',request,'--pid',tostring(tonumber(K.GetCurrentProcessId()))}
    for i,arg in ipairs(args) do args[i]=quoteWindows(assert(arg,'WINDOWS_RUNTIME_CONFIG_MISSING')) end
    local startup=ffi.new('FS_STARTUP');startup.cb=ffi.sizeof(startup);startup.flags=1;startup.show=0
    local process=ffi.new('FS_PROCESS')
    assert(K.CreateProcessW(nil,wide(table.concat(args,' ')),nil,nil,0,0x08000000,nil,nil,startup,process)~=0,'WINDOWS_HELPER_START_FAILED')
    K.CloseHandle(process.thread)
    local wait=K.WaitForSingleObject(process.process,command=='FS_FINISH_CHOICE' and 3600000 or 240000)
    if wait~=0 then K.TerminateProcess(process.process,1);K.CloseHandle(process.process);error('WINDOWS_HELPER_TIMEOUT') end
    local code=ffi.new('unsigned long[1]');K.GetExitCodeProcess(process.process,code);K.CloseHandle(process.process)
    local result=open(output,'rb');local text=result and result:read('*a') or ''
    if result then result:close() end
    P.os.remove(request);P.os.remove(output)
    return tonumber(code[0]),text
end
function P.os.execute(command)
    local delay=command:match('^/bin/sleep ([%d%.]+)$')
    if delay then K.Sleep(math.floor(tonumber(delay)*1000));return 0 end
    local code,text=P.rpc(command)
    if code~=0 then
        local log=open(P.directory..'/windows-runtime.log','ab')
        if log then log:write(text..'\n');log:close() end
    end
    return code
end
function P.io.popen(command,mode)
    assert(mode==nil or mode=='r','WINDOWS_WRITE_PIPE_UNSUPPORTED')
    local code,text=P.rpc(command)
    local object={position=1}
    function object:read(mode)
        if mode=='*a' then local rest=text:sub(self.position);self.position=#text+1;return rest end
        if self.position>#text then return nil end
        local finish=text:find('\n',self.position,true) or #text+1
        local line=text:sub(self.position,finish-1):gsub('\r$','');self.position=finish+1;return line
    end
    function object:lines() return function() return self:read('*l') end end
    function object:close() return code==0 and true or nil,'exit',code end
    return object
end
function P.focusTimeline()
    local code,text=P.rpc('FS_TIMELINE_FOCUS');return code==0,text
end
function P.blade()
    local pid=ffi.new('unsigned long[1]')
    U.GetWindowThreadProcessId(U.GetForegroundWindow(),pid)
    if tonumber(pid[0])~=tonumber(K.GetCurrentProcessId()) then return false end
    -- Never send a shortcut to another application if focus changed during a cut.
    U.keybd_event(0x11,0,0,0);U.keybd_event(0x42,0,0,0)
    U.keybd_event(0x42,0,2,0);U.keybd_event(0x11,0,2,0)
    return true
end
function P.finishChoice()
    local code,text=P.rpc('FS_FINISH_CHOICE');assert(code==0,text);return text
end
_G.__FLOWSTUDIO_PLATFORM=P
return P
