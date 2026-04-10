param(
    [string]$ProjectRoot = "D:\HuaweiAI\quantSystem2\android_app",
    [switch]$RunConnectedTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Ensure-Adb {
    if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
        throw "adb not found. Please add Android Platform Tools to PATH."
    }
}

function Ensure-Device {
    $devices = & adb devices
    $online = $devices | Select-String -Pattern "device$"
    if (-not $online) {
        throw "No online device detected. Connect a device and enable USB debugging."
    }
}

function Set-Wifi([bool]$enabled) {
    & adb shell svc wifi $(if ($enabled) { "enable" } else { "disable" }) | Out-Null
}

function Set-Data([bool]$enabled) {
    & adb shell svc data $(if ($enabled) { "enable" } else { "disable" }) | Out-Null
}

function Wait-Seconds([int]$seconds) {
    Start-Sleep -Seconds $seconds
}

Ensure-Adb
Ensure-Device

Step "Network resilience regression started"
Write-Host "Device detected. Keep Quant app in foreground on Overview or Stocks page."

try {
    Step "Scenario 1: mobile data only (disable Wi-Fi)"
    Set-Wifi $false
    Set-Data $true
    Wait-Seconds 8

    Step "Scenario 2: fully offline (disable Wi-Fi and data)"
    Set-Wifi $false
    Set-Data $false
    Wait-Seconds 10

    Step "Scenario 3: network recovery (enable data then Wi-Fi)"
    Set-Data $true
    Wait-Seconds 6
    Set-Wifi $true
    Wait-Seconds 8

    if ($RunConnectedTests) {
        Step "Run connectedDebugAndroidTest (optional)"
        Push-Location $ProjectRoot
        try {
            & .\gradlew.bat :app:connectedDebugAndroidTest --no-daemon
        } finally {
            Pop-Location
        }
    }

    Step "Regression flow finished"
    Write-Host "Please verify on device:"
    Write-Host "1) Offline shows readable error and retry entry"
    Write-Host "2) Cache fallback shows local/offline source"
    Write-Host "3) After recovery, refresh works again"
}
finally {
    Step "Restore default network (Wi-Fi + data enabled)"
    Set-Wifi $true
    Set-Data $true
}
