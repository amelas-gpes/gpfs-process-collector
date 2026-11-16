# Functions shared by install.ps1, register-updates.ps1 and uninstall.ps1.
# Loading this file defines them and changes nothing on the computer.

function Resolve-CollectorPython {
    <#
    The Python the desktop app is installed with: python.exe for the window's local service and
    pythonw.exe, in the same folder, for the update task. -Configured is the value of
    VOICE_INTERVIEWER_PYTHON when the installer runs (the variable the .cmd launchers use); when
    it is empty the Codex runtime at -Default is used, as before. The choice is made once, at
    installation: a scheduled task and a pinned window do not see a variable set in one shell.
    #>
    param(
        [AllowEmptyString()][AllowNull()][string]$Configured,
        [Parameter(Mandatory = $true)][string]$Default
    )
    $chosen = if ($Configured) { $Configured.Trim().Trim('"') } else { $Default }
    $source = if ($Configured) { 'VOICE_INTERVIEWER_PYTHON' } else { 'the Codex runtime' }
    if (-not [IO.Path]::IsPathRooted($chosen) -or -not (Test-Path -LiteralPath $chosen -PathType Leaf)) {
        throw "Python for the desktop app was not found at '$chosen' (from $source). Give the full path of an existing python.exe."
    }
    $folder = Split-Path -Parent ([IO.Path]::GetFullPath($chosen))
    $console = Join-Path $folder 'python.exe'
    $windowless = Join-Path $folder 'pythonw.exe'
    foreach ($needed in $console, $windowless) {
        if (-not (Test-Path -LiteralPath $needed -PathType Leaf)) {
            throw "The desktop app needs python.exe (for the window) and pythonw.exe (for the update task) in one folder. Missing: '$needed' (Python from $source)."
        }
    }
    [pscustomobject]@{ Console = $console; Windowless = $windowless; Source = $source }
}
