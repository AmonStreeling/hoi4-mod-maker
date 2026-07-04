# HOI4 Map Maker Workshop deploy (safe)
#
# 跑这个之前先跑 build_exe.bat 生成 dist/HOI4MapMaker/
#
# 安全语义:
# - 只删 mod 目录里的 HOI4MapMaker.exe + _internal/
# - 保留 thumbnail.png / common/ / localisation/ / 其他文件
# - 外层 .mod 和 descriptor.mod 用 in-place 修改, 只动 version 和 supported_version
# - picture / remote_file_id / path 等 Steam Workshop 关键字段绝不动
#
# 版本号自动从 ../version.py 的 VERSION 字段读
$ErrorActionPreference = "Stop"

$MOD_DIR = "D:\Documents\Paradox Interactive\Hearts of Iron IV\mod\hoi4_map_maker"
$OUTER_MOD = "D:\Documents\Paradox Interactive\Hearts of Iron IV\mod\hoi4_map_maker.mod"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$REPO_ROOT = Split-Path -Parent $SCRIPT_DIR
$DIST_DIR = Join-Path $REPO_ROOT "dist\HOI4MapMaker"
$VERSION_PY = Join-Path $REPO_ROOT "version.py"
$SUP_VER = "1.19.*"

# 从 version.py 读 VERSION
$verLine = Get-Content $VERSION_PY | Where-Object { $_ -match '^VERSION\s*=' } | Select-Object -First 1
if (-not $verLine -or $verLine -notmatch '"([^"]+)"') {
    Write-Error "Cannot parse VERSION from $VERSION_PY"
    exit 1
}
$VER = $Matches[1]

Write-Output "Deploying v$VER to $MOD_DIR"

# Sanity checks
if (-not (Test-Path $MOD_DIR)) {
    Write-Error "MOD_DIR missing: $MOD_DIR`nFirst-time deploy must be manual (create dir + thumbnail.png + outer .mod with remote_file_id from Steam)."
    exit 1
}
if (-not (Test-Path $OUTER_MOD)) {
    Write-Error "OUTER_MOD missing: $OUTER_MOD"
    exit 1
}
if (-not (Test-Path (Join-Path $DIST_DIR "HOI4MapMaker.exe"))) {
    Write-Error "Build missing: $DIST_DIR\HOI4MapMaker.exe`nRun build_exe.bat first."
    exit 1
}

Write-Output "[1/4] Delete old exe + _internal (keep thumbnail/common/localisation)..."
$exeTarget = Join-Path $MOD_DIR "HOI4MapMaker.exe"
$internalTarget = Join-Path $MOD_DIR "_internal"
if (Test-Path $exeTarget) { Remove-Item -Force $exeTarget }
if (Test-Path $internalTarget) { Remove-Item -Recurse -Force $internalTarget }

Write-Output "[2/4] Copy new build..."
Copy-Item -Path (Join-Path $DIST_DIR "HOI4MapMaker.exe") -Destination $MOD_DIR
Copy-Item -Path (Join-Path $DIST_DIR "_internal") -Destination $MOD_DIR -Recurse

Write-Output "[3/4] In-place patch descriptor.mod version fields..."
$descPath = Join-Path $MOD_DIR "descriptor.mod"
(Get-Content $descPath) | ForEach-Object {
    if ($_ -match '^version=') { "version=`"$VER`"" }
    elseif ($_ -match '^supported_version=') { "supported_version=`"$SUP_VER`"" }
    else { $_ }
} | Set-Content $descPath -Encoding utf8

Write-Output "[3/4] In-place patch outer .mod (preserve picture / remote_file_id / path)..."
(Get-Content $OUTER_MOD) | ForEach-Object {
    if ($_ -match '^version=') { "version=`"$VER`"" }
    elseif ($_ -match '^supported_version=') { "supported_version=`"$SUP_VER`"" }
    else { $_ }
} | Set-Content $OUTER_MOD -Encoding utf8

Write-Output "[4/4] Verify Workshop key fields preserved..."
$outerContent = Get-Content $OUTER_MOD -Raw
if ($outerContent -notmatch 'remote_file_id="\d+"') {
    Write-Warning "remote_file_id missing from outer .mod after deploy! Steam Workshop upload will create a new entry."
}
Write-Output "--- outer .mod after deploy ---"
Get-Content $OUTER_MOD
Write-Output "--- descriptor.mod after deploy ---"
Get-Content $descPath

Write-Output "`n=== Deploy OK ==="
Write-Output "Next: HOI4 launcher -> Mod Tools -> Upload Mod -> hoi4_map_maker"
