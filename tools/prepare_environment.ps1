$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$Utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $Utf8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONHOME = $null
$env:PYTHONPATH = $null
$Runtime = Join-Path $Root '.runtime'
$PythonDir = Join-Path $Runtime 'python'
$Python = Join-Path $PythonDir 'python.exe'
$Downloads = Join-Path $Runtime 'downloads'

function Download-File([string]$Url, [string]$Target) {
    Write-Host "[MaaSOW] Downloading $Url"
    $Partial = "$Target.partial"
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Partial -TimeoutSec 300
    Move-Item -LiteralPath $Partial -Destination $Target -Force
}
function Install-MicrosoftRuntime([string]$Url, [string]$Name, [string[]]$Arguments) {
    $Installer = Join-Path $Downloads $Name
    Download-File $Url $Installer
    $Signature = Get-AuthenticodeSignature -LiteralPath $Installer
    if ($Signature.Status -ne 'Valid' -or $Signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        throw "Microsoft installer signature verification failed: $Name"
    }
    Write-Host "[MaaSOW] Installing $Name. Windows may request administrator approval."
    $Process = Start-Process -FilePath $Installer -ArgumentList $Arguments -Wait -PassThru -WindowStyle Hidden
    if ($Process.ExitCode -eq 3010) { throw 'Runtime installed. Restart Windows, then run the environment preparation BAT again.' }
    if ($Process.ExitCode -notin @(0, 1638)) { throw "$Name failed, exit code $($Process.ExitCode)" }
}
function Test-WebView {
    foreach ($Base in @('HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients',
                        'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients',
                        'HKCU:\Software\Microsoft\EdgeUpdate\Clients')) {
        if (Test-Path -LiteralPath $Base) {
            foreach ($Key in Get-ChildItem -LiteralPath $Base) {
                $Product = Get-ItemProperty -LiteralPath $Key.PSPath
                if ($Product.name -match 'WebView2' -and $Product.pv -and $Product.pv -ne '0.0.0.0') { return $true }
            }
        }
    }
    return $false
}
try {
    if (-not [Environment]::Is64BitOperatingSystem -or [Environment]::OSVersion.Version.Build -lt 17763) {
        throw 'Windows 10 1809 or later, x64, is required.'
    }
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'This package targets x64 Windows. ARM64 is not validated.'
    }
    New-Item -ItemType Directory -Force -Path $Downloads | Out-Null
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MaaRuntimeProbe {
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);
    [DllImport("kernel32")] public static extern bool FreeLibrary(IntPtr module);
}
'@
    $NativeLibrary = Join-Path $Root 'maafw\MaaFramework.dll'
    if (-not (Test-Path -LiteralPath $NativeLibrary)) { throw 'Missing maafw. Extract the complete package.' }
    $Handle = [MaaRuntimeProbe]::LoadLibraryEx($NativeLibrary, [IntPtr]::Zero, 0x1100)
    if ($Handle -eq [IntPtr]::Zero) {
        Install-MicrosoftRuntime 'https://aka.ms/vs/17/release/vc_redist.x64.exe' 'vc_redist.x64.exe' @('/install','/passive','/norestart')
        $Handle = [MaaRuntimeProbe]::LoadLibraryEx($NativeLibrary, [IntPtr]::Zero, 0x1100)
        if ($Handle -eq [IntPtr]::Zero) { throw 'MaaFramework DLL still cannot load. Check Windows version and missing files.' }
    }
    [void][MaaRuntimeProbe]::FreeLibrary($Handle)
    if (-not (Test-WebView)) {
        Install-MicrosoftRuntime 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' 'MicrosoftEdgeWebview2Setup.exe' @('/silent','/install')
        if (-not (Test-WebView)) { throw 'WebView2 installation could not be verified. Restart and retry the environment preparation BAT.' }
    } else { Write-Host '[MaaSOW] WebView2 is installed.' }
    $PythonReady = $false
    if (Test-Path -LiteralPath $Python) {
        & $Python -X utf8 -c "import sys,struct; sys.exit(0 if sys.version_info[:2]==(3,12) and struct.calcsize('P')==8 else 1)"
        $PythonReady = ($LASTEXITCODE -eq 0)
    }
    if (-not $PythonReady) {
        $Archive = Join-Path $Downloads 'python-3.12.10-embed-amd64.zip'
        Download-File 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' $Archive
        $ExpectedHash = '4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3'
        if ((Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -ne $ExpectedHash) {
            throw 'Python archive checksum failed. Retry the environment preparation BAT.'
        }
        Expand-Archive -LiteralPath $Archive -DestinationPath $PythonDir -Force
    }
    $SearchPaths = @('python312.zip', '.', 'Lib/site-packages', '..\..', 'import site', '') -join [Environment]::NewLine
    [IO.File]::WriteAllText((Join-Path $PythonDir 'python312._pth'), $SearchPaths, $Utf8)
    $Site = Join-Path $PythonDir 'Lib\site-packages'
    New-Item -ItemType Directory -Force -Path $Site | Out-Null
    [IO.File]::WriteAllText((Join-Path $Site 'sitecustomize.py'), @'
import sys
sys.dont_write_bytecode = True
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="backslashreplace")
'@, $Utf8)
    & $Python -X utf8 (Join-Path $PSScriptRoot 'check_environment.py') --imports-only
    if ($LASTEXITCODE -ne 0) {
        & $Python -X utf8 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('pip') else 1)"
        if ($LASTEXITCODE -ne 0) {
            $GetPip = Join-Path $Downloads 'get-pip.py'
            Download-File 'https://bootstrap.pypa.io/get-pip.py' $GetPip
            & $Python -X utf8 $GetPip --no-warn-script-location --disable-pip-version-check
            if ($LASTEXITCODE -ne 0) { throw 'pip setup failed. Check network access to pypi.org.' }
        }
        & $Python -X utf8 -m pip install --disable-pip-version-check --no-warn-script-location --only-binary=:all: -r (Join-Path $Root 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network access and retry the environment preparation BAT.' }
    }
    & $Python -X utf8 (Join-Path $Root 'generate_interface.py')
    if ($LASTEXITCODE -ne 0) { throw 'Task configuration generation failed.' }
    & $Python -X utf8 (Join-Path $PSScriptRoot 'check_environment.py')
    if ($LASTEXITCODE -ne 0) { throw 'Environment check failed.' }
    Write-Host '[MaaSOW] Environment ready.'
    exit 0
} catch {
    Write-Host "[MaaSOW] ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
