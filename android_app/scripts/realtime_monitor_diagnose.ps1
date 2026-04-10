param(
    [string]$BaseUrl = "https://silvicultural-nonrectangularly-lyle.ngrok-free.dev/",
    [int]$Samples = 15,
    [int]$IntervalSeconds = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Normalize-BaseUrl([string]$url) {
    $v = ""
    if ($null -ne $url) { $v = [string]$url }
    $v = $v.Trim()
    if ([string]::IsNullOrWhiteSpace($v)) { throw "BaseUrl is empty." }
    if (-not $v.EndsWith("/")) { $v += "/" }
    return $v
}

function Invoke-Api([string]$url, [string]$method = "GET", [object]$body = $null, [int]$timeoutSec = 20) {
    $headers = @{ "ngrok-skip-browser-warning" = "1" }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        if ($method -eq "POST") {
            $resp = Invoke-RestMethod -Headers $headers -TimeoutSec $timeoutSec -Method Post -ContentType "application/json" -Uri $url -Body ($body | ConvertTo-Json -Compress -Depth 8)
        } else {
            $resp = Invoke-RestMethod -Headers $headers -TimeoutSec $timeoutSec -Method Get -Uri $url
        }
        $sw.Stop()
        return [PSCustomObject]@{
            ok = $true
            ms = [int]$sw.ElapsedMilliseconds
            data = $resp
            err = $null
        }
    } catch {
        $sw.Stop()
        return [PSCustomObject]@{
            ok = $false
            ms = [int]$sw.ElapsedMilliseconds
            data = $null
            err = $_.Exception.Message
        }
    }
}

$base = Normalize-BaseUrl $BaseUrl
Write-Host "BaseUrl: $base"

Write-Host ""
Write-Host "1) Start monitor runtime..."
$start = Invoke-Api -url ($base + "api/action") -method "POST" -body @{ action = "start_monitor_runtime"; confirmed = $true } -timeoutSec 30
if ($start.ok) {
    Write-Host ("start_monitor_runtime: OK ({0} ms)" -f $start.ms)
} else {
    Write-Host ("start_monitor_runtime: FAIL ({0} ms) - {1}" -f $start.ms, $start.err)
}

Write-Host ""
Write-Host "2) Sampling /api/dashboard/overview ..."
$latencies = New-Object System.Collections.Generic.List[int]
$timeouts = 0
$failures = 0
$runtimeUsableCount = 0
$activeCount = 0
$refreshValues = New-Object System.Collections.Generic.HashSet[string]

for ($i = 1; $i -le $Samples; $i++) {
    $r = Invoke-Api -url ($base + "api/dashboard/overview") -timeoutSec 20
    if ($r.ok) {
        $latencies.Add($r.ms)
        $snapshot = $null
        if ($null -ne $r.data -and $r.data.PSObject.Properties.Name -contains "data") {
            $snapshot = $r.data.data
        } else {
            $snapshot = $r.data
        }

        $monitor = $null
        if ($null -ne $snapshot) {
            if ($snapshot.PSObject.Properties.Name -contains "monitor_session") {
                $monitor = $snapshot.monitor_session
            } elseif ($snapshot.PSObject.Properties.Name -contains "monitorSession") {
                $monitor = $snapshot.monitorSession
            }
        }
        if ($monitor -ne $null) {
            $runtimeUsable = $null
            if ($monitor.PSObject.Properties.Name -contains "runtime_usable") { $runtimeUsable = $monitor.runtime_usable }
            elseif ($monitor.PSObject.Properties.Name -contains "runtimeUsable") { $runtimeUsable = $monitor.runtimeUsable }
            if ($runtimeUsable -eq $true) { $runtimeUsableCount++ }

            $isActive = $null
            if ($monitor.PSObject.Properties.Name -contains "is_active") { $isActive = $monitor.is_active }
            elseif ($monitor.PSObject.Properties.Name -contains "isActive") { $isActive = $monitor.isActive }
            if ($isActive -eq $true) { $activeCount++ }

            $lastRefresh = ""
            if ($monitor.PSObject.Properties.Name -contains "last_refresh_at" -and $null -ne $monitor.last_refresh_at) {
                $lastRefresh = [string]$monitor.last_refresh_at
            } elseif ($monitor.PSObject.Properties.Name -contains "lastRefreshAt" -and $null -ne $monitor.lastRefreshAt) {
                $lastRefresh = [string]$monitor.lastRefreshAt
            }
            if (-not [string]::IsNullOrWhiteSpace($lastRefresh)) { [void]$refreshValues.Add($lastRefresh) }
        }
        Write-Host ("[{0}/{1}] OK {2} ms" -f $i, $Samples, $r.ms)
    } else {
        if ($r.err -like "*timed out*") { $timeouts++ } else { $failures++ }
        Write-Host ("[{0}/{1}] FAIL {2} ms - {3}" -f $i, $Samples, $r.ms, $r.err)
    }
    Start-Sleep -Seconds $IntervalSeconds
}

Write-Host ""
Write-Host "2.1) Sampling monitor status from /api/dashboard ..."
$monitorSample = Invoke-Api -url ($base + "api/dashboard") -timeoutSec 25
if ($monitorSample.ok) {
    $root = $null
    if ($null -ne $monitorSample.data -and $monitorSample.data.PSObject.Properties.Name -contains "data") {
        $root = $monitorSample.data.data
    } else {
        $root = $monitorSample.data
    }
    $m = $null
    if ($null -ne $root) {
        if ($root.PSObject.Properties.Name -contains "monitor_session") { $m = $root.monitor_session }
        elseif ($root.PSObject.Properties.Name -contains "monitorSession") { $m = $root.monitorSession }
    }
    if ($null -ne $m) {
        $isActiveOneShot = $false
        if ($m.PSObject.Properties.Name -contains "is_active") { $isActiveOneShot = [bool]$m.is_active }
        elseif ($m.PSObject.Properties.Name -contains "isActive") { $isActiveOneShot = [bool]$m.isActive }
        $runtimeUsableOneShot = $false
        if ($m.PSObject.Properties.Name -contains "runtime_usable") { $runtimeUsableOneShot = [bool]$m.runtime_usable }
        elseif ($m.PSObject.Properties.Name -contains "runtimeUsable") { $runtimeUsableOneShot = [bool]$m.runtimeUsable }
        $lastRefreshOneShot = ""
        if ($m.PSObject.Properties.Name -contains "last_refresh_at" -and $null -ne $m.last_refresh_at) { $lastRefreshOneShot = [string]$m.last_refresh_at }
        elseif ($m.PSObject.Properties.Name -contains "lastRefreshAt" -and $null -ne $m.lastRefreshAt) { $lastRefreshOneShot = [string]$m.lastRefreshAt }
        Write-Host ("monitor_session one-shot: is_active={0}, runtime_usable={1}, last_refresh_at={2}" -f $isActiveOneShot, $runtimeUsableOneShot, $lastRefreshOneShot)
        if ($isActiveOneShot) { $activeCount++ }
        if ($runtimeUsableOneShot) { $runtimeUsableCount++ }
        if (-not [string]::IsNullOrWhiteSpace($lastRefreshOneShot)) { [void]$refreshValues.Add($lastRefreshOneShot) }
    } else {
        Write-Host "monitor_session one-shot: missing in /api/dashboard response"
    }
} else {
    Write-Host ("monitor_session one-shot request failed: {0}" -f $monitorSample.err)
}

Write-Host ""
Write-Host "3) Summary"
if ($latencies.Count -gt 0) {
    $sorted = $latencies | Sort-Object
    $p50 = $sorted[[Math]::Floor(($sorted.Count - 1) * 0.5)]
    $p90 = $sorted[[Math]::Floor(($sorted.Count - 1) * 0.9)]
    $avg = [Math]::Round((($latencies | Measure-Object -Average).Average), 1)
Write-Host ("latency count={0}, avg={1}ms, p50={2}ms, p90={3}ms" -f $latencies.Count, $avg, $p50, $p90)
} else {
    Write-Host "latency count=0"
}

$total = [double]$Samples
$successRate = [Math]::Round((($latencies.Count / $total) * 100), 1)
Write-Host ("successRate={0}% timeout={1} failure={2}" -f $successRate, $timeouts, $failures)
Write-Host "monitor_session.is_active true count=$activeCount"
Write-Host "monitor_session.runtime_usable true count=$runtimeUsableCount"
Write-Host "monitor_session.last_refresh_at distinct values=$($refreshValues.Count)"

Write-Host ""
Write-Host "4) Verdict"
if ($latencies.Count -ge [Math]::Ceiling($Samples * 0.8) -and $timeouts -le 1 -and ($refreshValues.Count -ge 1 -or $runtimeUsableCount -ge 1 -or $activeCount -ge 1)) {
    Write-Host "PASS: Realtime monitor is healthy and low-latency usable."
} elseif ($latencies.Count -ge [Math]::Ceiling($Samples * 0.6)) {
    Write-Host "WARN: Service is usable but unstable. Check mobile network and tunnel jitter."
} else {
    Write-Host "FAIL: Realtime monitor is unstable or unavailable. Prioritize network path fixes."
}
