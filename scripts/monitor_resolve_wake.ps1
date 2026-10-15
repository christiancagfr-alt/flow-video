param([int]$DurationSeconds = 180)

$ErrorActionPreference = 'Continue'
$bridgeRoot = Join-Path $env:USERPROFILE 'Documents\FlowStudioResolveBridge'
$bridgeLogs = Join-Path $bridgeRoot 'logs'
$scriptDir = Join-Path $env:APPDATA 'Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\FlowStudioAuto'
$resolveLogs = Join-Path $env:APPDATA 'Blackmagic Design\DaVinci Resolve\Support\logs'
$flowLogs = Join-Path $env:LOCALAPPDATA 'FlowStudio\data\logs'
New-Item -ItemType Directory -Force -Path $bridgeLogs | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $bridgeLogs "wake-diagnostic-$stamp.txt"

function Write-Log([string]$Text) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'), $Text
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Host $Text
}

function Get-Signature([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return '<missing>' }
    $item = Get-Item -LiteralPath $Path -ErrorAction SilentlyContinue
    if (-not $item) { return '<unreadable>' }
    return '{0}:{1}' -f $item.LastWriteTimeUtc.Ticks, $item.Length
}

function Write-Tail([string]$Path, [int]$Count = 15) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    try {
        Get-Content -LiteralPath $Path -Tail $Count -Encoding UTF8 -ErrorAction Stop | ForEach-Object {
            Write-Log ('  ' + $_)
        }
    } catch {
        Write-Log ('  Could not read file: ' + $_.Exception.Message)
    }
}

Write-Log 'Flow Studio / DaVinci Bridge wake diagnostic started.'
Write-Log ('Capture file: ' + $logPath)
Write-Log 'Click Workspace > Scripts > FlowStudioAuto > FlowStudio_Resolve_Bridge_v1.1.14 during this 180-second capture.'

$targets = @(
    (Join-Path $bridgeRoot 'bridge_state.ini'),
    (Join-Path $bridgeRoot 'bridge_heartbeat.txt'),
    (Join-Path $bridgeRoot 'bridge_status.txt'),
    (Join-Path $bridgeLogs 'bridge.log'),
    (Join-Path $scriptDir 'flowstudio-bridge-boot.txt'),
    (Join-Path $scriptDir 'windows-runtime.log'),
    (Join-Path $scriptDir 'windows-runtime.ini'),
    (Join-Path $flowLogs 'davinci-workflow.log')
)
$known = @{}
foreach ($path in $targets) { $known[$path] = Get-Signature $path }

$resolveDebug = Join-Path $resolveLogs 'ResolveDebug.txt'
$seenDebug = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
$debugPattern = 'FlowStudio_Resolve_Bridge|FlowStudio_Platform|windows_resolve_runtime|HOME unavailable|No module named|WINDOWS_HELPER|SANDBOX|RESOLVE_MAIN_WINDOW|RESOLVE_MENU_NOT_FOUND'
if (Test-Path -LiteralPath $resolveDebug -PathType Leaf) {
    try {
        Get-Content -LiteralPath $resolveDebug -Tail 400 -Encoding UTF8 | Where-Object { $_ -match $debugPattern } | ForEach-Object {
            [void]$seenDebug.Add($_)
        }
    } catch {}
}

$resolve = Get-CimInstance Win32_Process -Filter "Name='Resolve.exe'" -ErrorAction SilentlyContinue
if ($resolve) {
    foreach ($process in $resolve) {
        Write-Log ('Resolve process: PID=' + $process.ProcessId + ' EXE=' + $process.ExecutablePath)
    }
} else {
    Write-Log 'Resolve.exe is not running at capture start.'
}
Write-Log 'Existing Bridge runtime configuration:'
Write-Tail (Join-Path $scriptDir 'windows-runtime.ini') 5
Write-Log 'Monitoring file changes and Resolve Lua errors. Leave this window open while clicking the Bridge menu item.'

$iterations = [Math]::Max(1, [Math]::Ceiling($DurationSeconds / 2))
for ($i = 0; $i -lt $iterations; $i++) {
    foreach ($path in $targets) {
        $signature = Get-Signature $path
        if ($signature -ne $known[$path]) {
            $known[$path] = $signature
            Write-Log ('Changed: ' + $path + ' [' + $signature + ']')
            if ($signature -ne '<missing>' -and (Test-Path -LiteralPath $path -PathType Leaf)) {
                Write-Tail $path 12
            }
        }
    }
    if (Test-Path -LiteralPath $resolveDebug -PathType Leaf) {
        try {
            Get-Content -LiteralPath $resolveDebug -Tail 400 -Encoding UTF8 | Where-Object { $_ -match $debugPattern } | ForEach-Object {
                if ($seenDebug.Add($_)) { Write-Log ('ResolveDebug: ' + $_) }
            }
        } catch {
            Write-Log ('ResolveDebug read failed: ' + $_.Exception.Message)
        }
    }
    Start-Sleep -Seconds 2
}

if (-not (Test-Path -LiteralPath (Join-Path $bridgeRoot 'bridge_state.ini'))) {
    Write-Log 'RESULT: Bridge did not create bridge_state.ini during this capture.'
}
if (-not (Test-Path -LiteralPath (Join-Path $bridgeRoot 'bridge_heartbeat.txt'))) {
    Write-Log 'RESULT: Bridge did not create bridge_heartbeat.txt during this capture.'
}
Write-Log ('Capture finished. Send this file for diagnosis: ' + $logPath)
