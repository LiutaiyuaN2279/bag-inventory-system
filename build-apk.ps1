# 一键构建 APK（Windows PowerShell）
#
# 用法：powershell -ExecutionPolicy Bypass -File build-apk.ps1
# 产物：dist-apk\箱包采购与库存管理.apk
#
# 依赖（二选一）：
#   A) 本机已装 JDK17 + Android SDK（platforms;android-34、build-tools;34.0.0）+ Gradle 8.x
#      直接设置 JAVA_HOME / ANDROID_HOME 即可运行
#   B) 使用项目内工具链 .tmp-run\toolchain（本仓库打包时用的便携版）
#      需要 .tmp-run\toolchain\{jdk,sdk,gradle} 三个目录

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$tc = Join-Path $root '.tmp-run\toolchain'

function Resolve-Env {
    # 优先用项目内便携工具链，找不到再回退到系统环境变量
    if (Test-Path "$tc\jdk") {
        $env:JAVA_HOME = (Get-ChildItem "$tc\jdk" -Directory | Select-Object -First 1).FullName
        $env:ANDROID_HOME = "$tc\sdk"
        $env:ANDROID_SDK_ROOT = "$tc\sdk"
        return 'toolchain'
    }
    if ($env:JAVA_HOME -and $env:ANDROID_HOME) { return 'system' }
    throw "未找到构建环境：请安装 JDK17 + Android SDK，或准备 $tc\{jdk,sdk,gradle}"
}

$mode = Resolve-Env

# Gradle 与各类工具需要可写的用户目录；默认指向工作区内，避免权限问题
$env:GRADLE_USER_HOME = Join-Path $root '.tmp-run\gradle-home'
$env:TEMP = Join-Path $root '.tmp-run\tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:GRADLE_USER_HOME, $env:TEMP | Out-Null

if (Test-Path "$tc\gradle") {
    $gradleExe = Join-Path (Get-ChildItem "$tc\gradle" -Directory | Select-Object -First 1).FullName 'bin\gradle.bat'
} else {
    $gradleExe = 'gradle'
}

Write-Host "构建环境：$mode / JAVA_HOME=$env:JAVA_HOME"

# 1) 构建前端并同步到 android/app/src/main/assets/www
Push-Location (Join-Path $root 'frontend')
try {
    Write-Host '==> 构建前端…'
    & cmd /c "set TEMP=$env:TEMP&& set TMP=$env:TEMP&& npm run build:apk 2>&1"
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
} finally {
    Pop-Location
}

# 2) 打 APK
Push-Location (Join-Path $root 'android')
try {
    Write-Host '==> 打包 APK…'
    & cmd /c "`"$gradleExe`" assembleRelease --no-daemon 2>&1"
    if ($LASTEXITCODE -ne 0) { throw 'Gradle 构建失败' }
} finally {
    Pop-Location
}

# 3) 输出到 dist-apk
$apk = Join-Path $root 'android\app\build\outputs\apk\release\app-release.apk'
if (-not (Test-Path $apk)) { throw "未找到 APK 产物：$apk" }

$outDir = Join-Path $root 'dist-apk'
New-Item -ItemType Directory -Force $outDir | Out-Null
$target = Join-Path $outDir '箱包采购与库存管理.apk'
Copy-Item $apk $target -Force

$size = [math]::Round((Get-Item $target).Length / 1MB, 2)
Write-Host ''
Write-Host "构建成功：$target（$size MB）"
Write-Host '安装前请确认：电脑已用 --host 0.0.0.0 启动后端，并已放行 8000 端口防火墙。'
