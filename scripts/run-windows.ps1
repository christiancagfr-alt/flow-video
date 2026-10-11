$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$logDir = Join-Path $projectRoot 'data\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$bootLog = Join-Path $logDir 'startup-windows.log'
$pythonExe = Join-Path $projectRoot '.venv-windows\Scripts\python.exe'
$pythonwExe = Join-Path $projectRoot '.venv-windows\Scripts\pythonw.exe'
try {
    $portablePython = Join-Path $projectRoot 'runtime\pythonw.exe'
    if (Test-Path -LiteralPath $portablePython) {
        Start-Process -FilePath $portablePython -ArgumentList ('"' + (Join-Path $projectRoot 'main.py') + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden
        exit 0
    }
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        $basePython = $null
        foreach ($candidate in @('py.exe', 'python.exe')) {
            $tool = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($tool) {
                $ErrorActionPreference = 'Continue'
                $found = & $tool.Source -c 'import sys; assert (3,10) <= sys.version_info[:2] < (3,15); print(sys.executable)' 2>> $bootLog
                $ErrorActionPreference = 'Stop'
                if ($LASTEXITCODE -eq 0) { $basePython = $found.Trim(); break }
            }
        }
        if (-not $basePython) { throw 'Python 3.10-3.14 is required.' }
        & $basePython -m venv (Join-Path $projectRoot '.venv-windows') >> $bootLog 2>&1
        if ($LASTEXITCODE -ne 0) { throw 'Unable to create Windows Python environment.' }
    }
    $ErrorActionPreference = 'Continue'
    & $pythonExe -c 'import PySide6, googleapiclient.discovery, google.oauth2.credentials, google_auth_oauthlib.flow, keyring, pywinauto, psutil, win32crypt' >> $bootLog 2>&1
    if ($LASTEXITCODE -ne 0) {
        & $pythonExe -m pip install --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple -r (Join-Path $projectRoot 'requirements-windows.txt') >> $bootLog 2>&1
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. See startup-windows.log.' }
    }
    $ErrorActionPreference = 'Stop'
    Start-Process -FilePath $pythonwExe -ArgumentList ('"' + (Join-Path $projectRoot 'main.py') + '"') -WorkingDirectory $projectRoot -WindowStyle Hidden
} catch {
    $_ | Out-File -FilePath $bootLog -Append -Encoding utf8
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("Flow Studio could not start.`n$($_.Exception.Message)`nLog: $bootLog", 'Flow Studio') | Out-Null
    exit 1
}
