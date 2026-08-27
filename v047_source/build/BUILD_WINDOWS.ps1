$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PythonVersion = "3.13.15"
$BuildVenv = Join-Path $Root ".build-venv"
$PythonExe = Join-Path $BuildVenv "Scripts\python.exe"
$PythonRuntime = Join-Path $PSScriptRoot "python-runtime-3.13.15"
$BasePython = Join-Path $PythonRuntime "tools\python.exe"
$NuGetExe = Join-Path $PSScriptRoot "nuget.exe"
$NuGetStage = Join-Path $PSScriptRoot "python-nuget-stage"
$BrowserDir = Join-Path $PSScriptRoot "playwright-browsers"
$ReleaseDir = Join-Path $PSScriptRoot "release"

if (-not [Environment]::Is64BitOperatingSystem) { throw "Поддерживается только 64-битная Windows 10/11." }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = "1"

function Invoke-Download([string]$Uri, [string]$OutFile) {
  Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $OutFile
}

function Assert-LastExit([string]$Stage) {
  if ($LASTEXITCODE -ne 0) {
    throw "Сбой этапа '$Stage'. Код: $LASTEXITCODE."
  }
}

function Test-PythonRuntime([string]$Path) {
  if (-not (Test-Path $Path)) { return $false }
  & $Path -I -c "import logging, re, asyncio, venv; assert hasattr(logging, 'getLogger')" *> $null
  return ($LASTEXITCODE -eq 0)
}

if (-not (Test-PythonRuntime $BasePython)) {
  if (Test-Path $PythonRuntime) {
    Remove-Item $PythonRuntime -Recurse -Force
  }
  if (Test-Path $NuGetStage) { Remove-Item $NuGetStage -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $NuGetStage | Out-Null
  if (-not (Test-Path $NuGetExe)) {
    Invoke-Download "https://dist.nuget.org/win-x86-commandline/latest/nuget.exe" $NuGetExe
  }
  & $NuGetExe install python -Version $PythonVersion -ExcludeVersion -OutputDirectory $NuGetStage -NonInteractive -DirectDownload -NoCache
  Assert-LastExit "nuget python"
  $NuGetPython = Join-Path $NuGetStage "python"
  if (-not (Test-Path (Join-Path $NuGetPython "tools\python.exe"))) {
    throw "NuGet не распаковал переносимый Python $PythonVersion."
  }
  Move-Item $NuGetPython $PythonRuntime
  Remove-Item $NuGetStage -Recurse -Force
}

if (-not (Test-PythonRuntime $BasePython)) { throw "Локальный Python $PythonVersion не прошёл проверку стандартной библиотеки." }
if (Test-Path $BuildVenv) { Remove-Item $BuildVenv -Recurse -Force }
& $BasePython -m venv $BuildVenv
if ($LASTEXITCODE -ne 0 -or -not (Test-PythonRuntime $PythonExe)) {
  throw "Не удалось создать изолированное окружение сборки."
}
& $PythonExe -m pip install --upgrade pip
Assert-LastExit "pip upgrade"
& $PythonExe -m pip install -e "$Root\backend[desktop]"
Assert-LastExit "dependencies"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

$FrontendIndex = Join-Path $Root "frontend\dist\index.html"
if (-not (Test-Path $FrontendIndex)) {
  throw "В архиве отсутствует готовый frontend\dist\index.html."
}

& $PythonExe -c "from PIL import Image; Image.open(r'$PSScriptRoot\app-icon.png').save(r'$PSScriptRoot\app-icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
Assert-LastExit "icon"
$WebViewInstaller = Join-Path $PSScriptRoot "MicrosoftEdgeWebView2Setup.exe"
if (-not (Test-Path $WebViewInstaller)) {
  Invoke-Download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" $WebViewInstaller
}
$env:PLAYWRIGHT_BROWSERS_PATH = $BrowserDir
& $PythonExe -m playwright install chromium
Assert-LastExit "playwright"

Push-Location $PSScriptRoot
& $PythonExe -m PyInstaller --noconfirm --clean VKOutreachManager.spec
Assert-LastExit "pyinstaller"
Copy-Item $WebViewInstaller "dist\VK Outreach Manager\MicrosoftEdgeWebView2Setup.exe" -Force
$PackagedWebViewInstaller = Join-Path $PSScriptRoot "dist\VK Outreach Manager\MicrosoftEdgeWebView2Setup.exe"
if (-not (Test-Path $PackagedWebViewInstaller) -or (Get-Item $PackagedWebViewInstaller).Length -lt 100000) {
  throw "WebView2 bootstrapper не попал в готовую сборку."
}
$BuiltExe = Join-Path $PSScriptRoot "dist\VK Outreach Manager\VK Outreach Manager.exe"
function Invoke-FrozenSelfTest([string]$Flag, [string]$Stage, [int]$RunNumber) {
  $SafeStage = $Stage -replace '[^A-Za-z0-9-]', '-'
  $SelfTestLog = Join-Path $PSScriptRoot "$SafeStage-$RunNumber-error.log"
  Remove-Item $SelfTestLog -Force -ErrorAction SilentlyContinue
  $env:VK_OUTREACH_SELF_TEST_LOG = $SelfTestLog
  try {
    $SelfTest = Start-Process -FilePath $BuiltExe -ArgumentList $Flag -Wait -PassThru
  } finally {
    Remove-Item Env:VK_OUTREACH_SELF_TEST_LOG -ErrorAction SilentlyContinue
  }
  if ($SelfTest.ExitCode -ne 0) {
    if (Test-Path $SelfTestLog) {
      $SelfTestDetails = Get-Content -Raw -Encoding UTF8 $SelfTestLog
    } else {
      $SelfTestDetails = "Приложение завершилось без диагностического журнала."
    }
    throw "Готовый EXE не прошёл $Stage, запуск $RunNumber.`n$SelfTestDetails"
  }
  Remove-Item $SelfTestLog -Force -ErrorAction SilentlyContinue
}

1..2 | ForEach-Object { Invoke-FrozenSelfTest "--self-test" "application-self-test" $_ }
1..2 | ForEach-Object { Invoke-FrozenSelfTest "--browser-self-test" "browser-self-test" $_ }
1..2 | ForEach-Object { Invoke-FrozenSelfTest "--frontend-self-test" "frontend-self-test" $_ }
Compress-Archive -Path "dist\VK Outreach Manager\*" -DestinationPath "release\VK_Outreach_Manager_Portable_0.4.4.zip" -Force
$Iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $Iscc) {
  $InnoInstaller = Join-Path $env:TEMP "inno-setup.exe"
  Invoke-Download "https://jrsoftware.org/download.php/is.exe" $InnoInstaller
  $InnoInstall = Start-Process $InnoInstaller -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /CURRENTUSER" -Wait -PassThru
  if ($InnoInstall.ExitCode -ne 0) { throw "Inno Setup не установился. Код: $($InnoInstall.ExitCode)." }
  $InnoCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
  )
  $IsccPath = $InnoCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
  if (-not $IsccPath) { throw "Не удалось автоматически установить Inno Setup." }
} else {
  $IsccPath = $Iscc.Source
}
& $IsccPath installer.iss
Assert-LastExit "inno setup"
Pop-Location
Write-Host "Готово. Файлы находятся в build\release"
