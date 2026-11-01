# Run local v1 training in cycles: TrainMinutes on, PauseMinutes frozen, until it ends.
# Freezing uses NtSuspendProcess, so no progress is lost. Keeps Windows awake meanwhile.
#   powershell -File scripts/gpu_duty_cycle.ps1 -TrainMinutes 120 -PauseMinutes 60
param(
    [int]$TrainMinutes = 120,
    [int]$PauseMinutes = 60,
    [string]$Match = "*train_v1_local*"
)

Add-Type -Namespace W -Name P -MemberDefinition @'
[DllImport("ntdll.dll")] public static extern int NtSuspendProcess(IntPtr h);
[DllImport("ntdll.dll")] public static extern int NtResumeProcess(IntPtr h);
[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);
'@

$root = Split-Path $PSScriptRoot -Parent
$log = Join-Path $root ("results\logs\duty_cycle_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
function Say([string]$msg) { "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg | Tee-Object -FilePath $log -Append }

# ES_CONTINUOUS | ES_SYSTEM_REQUIRED: no sleep while frozen either.
[void][W.P]::SetThreadExecutionState(0x80000001)

$ids = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like $Match } | ForEach-Object { $_.ProcessId })
if (-not $ids) { Say "no training process matches $Match"; exit 1 }
Say ("training PIDs: {0}; cycle {1} min on, {2} min off" -f ($ids -join ", "), $TrainMinutes, $PauseMinutes)

function Alive { foreach ($id in $ids) { if (Get-Process -Id $id -ErrorAction SilentlyContinue) { return $true } }; return $false }
function SetAll([bool]$run) {
    foreach ($id in $ids) {
        $p = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($p) { if ($run) { [void][W.P]::NtResumeProcess($p.Handle) } else { [void][W.P]::NtSuspendProcess($p.Handle) } }
    }
}
# Waits up to $minutes, returning early (false) if training exits.
function WaitWhileAlive([int]$minutes) {
    $end = (Get-Date).AddMinutes($minutes)
    while ((Get-Date) -lt $end) { if (-not (Alive)) { return $false }; Start-Sleep 30 }
    return $true
}

while (Alive) {
    SetAll $true; Say "resumed"
    if (-not (WaitWhileAlive $TrainMinutes)) { break }
    SetAll $false; Say "frozen"
    if (-not (WaitWhileAlive $PauseMinutes)) { break }
}
Say "training process exited; duty cycle done"
