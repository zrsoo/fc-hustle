$ErrorActionPreference = 'Stop'
# Read-only inspection. Persist process category/PID only, never argument values.
$pattern = '(?i)(fc_access[.\\/](controller_v1|actors_v1|continuous_v1|production_v1)|tests[\\/]probe_|private-captures[\\/]controller-v1-probes)'
$workers = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^(python|pythonw|node|powershell|pwsh)(\.exe)?$' -and
    $_.CommandLine -match $pattern
} | ForEach-Object { @{ pid = $_.ProcessId; name = $_.Name; category = 'FC account service or probe' } })
$listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object {
    $_.LocalPort -in 8783,8784
} | ForEach-Object { @{ port = $_.LocalPort; pid = $_.OwningProcess } })
$jobs = @(Get-ScheduledTask -ErrorAction Stop | Where-Object {
    $_.State -ne 'Disabled' -and (@($_.Actions | Where-Object {
        ($_.Execute + ' ' + $_.Arguments + ' ' + $_.WorkingDirectory) -match
        '(?i)(fc-hustle|fc_access|controller-v1|actors-v1|continuous-v1)'
    }).Count -gt 0)
} | ForEach-Object { @{ name = $_.TaskName; path = $_.TaskPath; state = [string]$_.State } })
@{ observed_at = [DateTime]::UtcNow.ToString('o'); production_workers = $workers;
   production_listeners = $listeners; scheduled_mutation_jobs = $jobs } | ConvertTo-Json -Depth 5 -Compress
