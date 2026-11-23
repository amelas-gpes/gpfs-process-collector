[CmdletBinding()]
param([switch]$BuildOnly)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$appDir = Join-Path $project '.local\desktop'
$null = New-Item -ItemType Directory -Path $appDir -Force
$running = $null
if ([Threading.Mutex]::TryOpenExisting('Local\GPFS.ProcessCollector.Desktop', [ref]$running)) {
    $running.Dispose()
    throw 'Close the Process Collector window before reinstalling the desktop host.'
}
$sourceIcon = Join-Path $PSScriptRoot 'ProcessCollector.ico'
$icon = Join-Path $appDir 'ProcessCollector.ico'
$exe = Join-Path $appDir 'ProcessCollector.exe'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$sdk = Join-Path $env:USERPROFILE '.nuget\packages\microsoft.web.webview2\1.0.4258.31'
$core = Join-Path $sdk 'lib\net462\Microsoft.Web.WebView2.Core.dll'
$forms = Join-Path $sdk 'lib\net462\Microsoft.Web.WebView2.WinForms.dll'
$loader = Join-Path $sdk 'runtimes\win-x64\native\WebView2Loader.dll'
foreach ($required in @($sourceIcon, $compiler, $core, $forms, $loader)) {
    if (!(Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing required local file: $required" }
}
if (!(Test-Path -LiteralPath $icon) -or (Get-FileHash -LiteralPath $sourceIcon).Hash -ne (Get-FileHash -LiteralPath $icon).Hash) {
    Copy-Item -LiteralPath $sourceIcon -Destination $icon -Force
}

# Build alongside the installed host. A failed compilation cannot damage the working executable.
$candidate = Join-Path $appDir ("ProcessCollector." + [guid]::NewGuid().ToString('N') + ".exe")
try {
    & $compiler /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 "/win32icon:$icon" "/out:$candidate" "/reference:$core" "/reference:$forms" /reference:System.Drawing.dll /reference:System.Windows.Forms.dll (Join-Path $PSScriptRoot 'NativeHost.cs') (Join-Path $PSScriptRoot 'HostLogic.cs')
    if ($LASTEXITCODE -ne 0) { throw "Desktop host compilation failed ($LASTEXITCODE)." }
    # Validate task ownership before replacing the currently working executable.
    if (-not $BuildOnly) { & (Join-Path $PSScriptRoot 'register-updates.ps1') }
    if (Test-Path -LiteralPath $exe) { [IO.File]::Replace($candidate, $exe, ($candidate + '.old')) }
    else { [IO.File]::Move($candidate, $exe) }
} finally {
    foreach ($temporary in @($candidate, ($candidate + '.old'))) {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue }
    }
}
if ($BuildOnly) { Write-Output $exe; return }

$programs = [Environment]::GetFolderPath('Programs')
$linkName = 'GPFS Process Collector.lnk'
$linkPath = Join-Path $programs $linkName
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($linkPath)
$shortcut.TargetPath = $exe
$shortcut.IconLocation = "$exe,0"
$shortcut.WorkingDirectory = $project
$shortcut.Description = 'GPFS Process Collector'
$shortcut.Save()

$shell = New-Object -ComObject Shell.Application
$item = $shell.NameSpace($programs).ParseName($linkName)
$verbs = @($item.Verbs())
$pin = $verbs | Where-Object { ($_.Name -replace '&','') -eq 'Pin to taskbar' } | Select-Object -First 1
if ($pin) { $pin.DoIt() }
$pinned = $shell.NameSpace($programs).ParseName($linkName).Verbs() | Where-Object { ($_.Name -replace '&','') -eq 'Unpin from taskbar' }
if (-not $pinned) { Write-Output 'To pin the app, find GPFS Process Collector in Start, right-click it and choose Pin to taskbar.' }
[pscustomobject]@{ Launcher = $exe; StartMenu = $linkPath; PinVerified = [bool]$pinned }
