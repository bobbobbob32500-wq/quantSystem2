Param(
    [ValidateSet("debug", "release")]
    [string]$Variant = "debug",
    [string]$Changelog = "Routine update and stability improvements",
    [string]$ApkUrl = "",
    [Nullable[int]]$VersionCode = $null,
    [string]$VersionName = "",
    [switch]$ForceUpdate
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AndroidRoot = Join-Path $ProjectRoot "android_app"
$ReleaseMeta = Join-Path $ProjectRoot "data\releases\android-latest.json"

if ($VersionCode -eq $null) {
    $nextCode = 1
    if (Test-Path $ReleaseMeta) {
        try {
            $meta = Get-Content $ReleaseMeta -Raw | ConvertFrom-Json
            if ($meta.latest_version_code -ne $null) {
                $nextCode = [int]$meta.latest_version_code + 1
            }
        }
        catch {
            $nextCode = 1
        }
    }
    $VersionCode = $nextCode
}

if (-not $VersionName -or -not $VersionName.Trim()) {
    $VersionName = "1.0.$VersionCode"
}

Push-Location $AndroidRoot
try {
    if ($Variant -eq "release") {
        .\gradlew.bat assembleRelease --no-daemon "-PAPP_VERSION_CODE=$VersionCode" "-PAPP_VERSION_NAME=$VersionName"
        $ApkPath = Join-Path $AndroidRoot "app\build\outputs\apk\release\app-release.apk"
    }
    else {
        .\gradlew.bat assembleDebug --no-daemon "-PAPP_VERSION_CODE=$VersionCode" "-PAPP_VERSION_NAME=$VersionName"
        $ApkPath = Join-Path $AndroidRoot "app\build\outputs\apk\debug\app-debug.apk"
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path $ApkPath)) {
    throw "APK not found after build: $ApkPath"
}

$PublishScript = Join-Path $ProjectRoot "scripts\publish_android_release.py"
$Args = @(
    $PublishScript,
    "--apk", $ApkPath,
    "--changelog", $Changelog
)

if ($ApkUrl -and $ApkUrl.Trim()) {
    $Args += @("--apk-url", $ApkUrl.Trim())
}
$Args += @("--version-code", [string]$VersionCode)
$Args += @("--version-name", $VersionName.Trim())
if ($ForceUpdate) {
    $Args += "--force-update"
}

python @Args
