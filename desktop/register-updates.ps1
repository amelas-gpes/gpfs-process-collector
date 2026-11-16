[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$taskName = 'GPFS Process Collector Update'
$project = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'common.ps1')
# VOICE_INTERVIEWER_PYTHON, if it is set now, else the Codex runtime. Resolved here, once: the
# task below and the window (through python.txt, written at the end) then use this interpreter.
$python = Resolve-CollectorPython -Configured $env:VOICE_INTERVIEWER_PYTHON `
    -Default (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
$pythonWindowless = $python.Windowless
$manager = Join-Path $PSScriptRoot 'manage.py'
if (-not (Test-Path -LiteralPath $manager -PathType Leaf)) {
    throw "Missing required file: $manager"
}

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$sid = $identity.User.Value
$arguments = '-I -B "{0}" update' -f $manager
$action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument $arguments -WorkingDirectory $project
$existing = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    $old = @($existing.Actions)
    $owned = $old.Count -eq 1 -and $old[0].Execute -eq $pythonWindowless -and
        $old[0].Arguments -match '^-I -B "([^"]+\\desktop\\manage\.py)" update$' -and
        (Join-Path $old[0].WorkingDirectory 'desktop\manage.py') -eq $Matches[1]
    if (-not $owned) { throw "Another scheduled task already uses the name '$taskName'. Inspect it in Task Scheduler before replacing it." }
    if ($old[0].Arguments -ne $arguments) { Write-Output "Updating the Process Collector task to use $manager." }
}

$logon = New-ScheduledTaskTrigger -AtLogOn -User $sid
$interval = New-TimeSpan -Minutes 15
$periodic = New-ScheduledTaskTrigger -Once -At ([DateTime]::Now.Add($interval)) -RepetitionInterval $interval
$principal = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 6 -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$definition = New-ScheduledTask -Action $action -Trigger @($logon, $periodic) -Principal $principal -Settings $settings `
    -Description 'Download Process Collector updates from GitHub main while the app owner is signed in. A download is only unpacked and checked; it runs after it is approved in the desktop window.'
Register-ScheduledTask -TaskName $taskName -TaskPath '\' -InputObject $definition -Force | Out-Null

[xml]$saved = Export-ScheduledTask -TaskName $taskName -TaskPath '\'
$task = $saved.Task
$scheduledAction = $task.Actions.Exec
$taskInterval = [System.Xml.XmlConvert]::ToTimeSpan($task.Triggers.TimeTrigger.Repetition.Interval)
$userIdentifiers = @($sid, $identity.Name)
if ($scheduledAction.Command -ne $pythonWindowless -or $scheduledAction.Arguments -ne $arguments -or
    $scheduledAction.WorkingDirectory -ne $project -or $task.Triggers.LogonTrigger.UserId -notin $userIdentifiers -or
    $taskInterval -ne $interval -or $task.Triggers.TimeTrigger.Repetition.Duration -or
    $task.Principals.Principal.UserId -notin $userIdentifiers -or $task.Principals.Principal.LogonType -ne 'InteractiveToken' -or
    $task.Principals.Principal.RunLevel -eq 'HighestAvailable' -or $task.Settings.MultipleInstancesPolicy -ne 'IgnoreNew') {
    throw "Windows registered '$taskName' with unexpected settings."
}
# The window reads its interpreter from this file, beside its executable, so that it and the
# task registered above run the same Python.
$hostFolder = Join-Path $project '.local\desktop'
$null = New-Item -ItemType Directory -Path $hostFolder -Force
[IO.File]::WriteAllText((Join-Path $hostFolder 'python.txt'), $python.Console + "`r`n")
Write-Output "Registered '$taskName' at sign-in and every 15 minutes for the current user, with Python from $($python.Source): $($python.Console)"
