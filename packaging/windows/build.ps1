# Builds the Windows app: dist\Clippy (portable folder), dist\Clippy-portable-<version>-win64.zip and
# dist\Clippy-Setup-<version>-win64.exe. Needs uv, the MSVC tools (cl, rc) and Inno Setup 6 (iscc).
#   ./packaging/windows/build.ps1               build
#   ./packaging/windows/build.ps1 -SmokeTest    also start the built app, download parts through it, test the
#                                               built-in AI and run the test suite with the bundled Python
param([switch]$SmokeTest)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Here = $PSScriptRoot
$Out = Join-Path $Root "dist"
$App = Join-Path $Out "Clippy"
$Version = if ($env:CLIPPY_VERSION) { $env:CLIPPY_VERSION -replace '^v', '' } else { "0.1.0" }
function Step($t) { Write-Host "`n=== $t" -ForegroundColor Cyan }
function Run($exe) { & $exe @args; if ($LASTEXITCODE) { throw "$exe failed ($LASTEXITCODE)" } }

Step "Clean"
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Force $App | Out-Null

Step "Python (relocatable build, lives inside the app folder)"
$pyTmp = Join-Path $Out "py"
Run uv python install 3.13 --install-dir $pyTmp
$pyDir = Get-ChildItem $pyTmp -Directory | Where-Object { Test-Path (Join-Path $_.FullName "python.exe") } | Select-Object -First 1
Move-Item $pyDir.FullName (Join-Path $App "python")
Remove-Item -Recurse -Force $pyTmp
$Py = Join-Path $App "python\python.exe"
& $Py -m pip --version 2>$null; if ($LASTEXITCODE) { Run $Py -m ensurepip }
Run $Py -m pip install --disable-pip-version-check --no-warn-script-location --upgrade pip

Step "Packages (NVIDIA libraries are left out: the app downloads them only on PCs with an NVIDIA card)"
$req = Join-Path $Out "requirements-app.txt"
Get-Content (Join-Path $Root "requirements.txt") | Where-Object { $_ -notmatch '^nvidia-' } | Set-Content $req
& $Py -m pip install --disable-pip-version-check --no-warn-script-location -r $req "yt-dlp[default]" deno
if ($LASTEXITCODE) {
  Write-Host "Exact versions not available for this Python; installing the newest compatible ones"
  (Get-Content $req) -replace '[=<>~!;].*$', '' | Where-Object { $_.Trim() } | Set-Content $req
  Run $Py -m pip install --disable-pip-version-check --no-warn-script-location -r $req "yt-dlp[default]" deno
}

Step "Clippy"
Copy-Item -Recurse (Join-Path $Root "clippy") (Join-Path $App "clippy")
Get-ChildItem (Join-Path $App "clippy") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Copy-Item -Recurse (Join-Path $Root "fonts") (Join-Path $App "fonts")
New-Item -ItemType Directory -Force (Join-Path $App "models") | Out-Null
Copy-Item (Join-Path $Root "models\face_detection_yunet_2023mar.onnx") (Join-Path $App "models")
Copy-Item -Recurse (Join-Path $Root "LICENSES") (Join-Path $App "LICENSES")
foreach ($f in "LICENSE", "README.md", "config.toml") { Copy-Item (Join-Path $Root $f) $App }

Step "Clippy.exe"
Push-Location $Here
Run rc /nologo /fo launcher.res launcher.rc
Run cl /nologo /O2 /W3 launcher.c launcher.res /Fe:"$App\Clippy.exe" /link /SUBSYSTEM:WINDOWS user32.lib
Remove-Item launcher.obj, launcher.res -ErrorAction SilentlyContinue
Pop-Location

if ($SmokeTest) {
  Step "Smoke test: start the built app"
  $env:PATH = (Join-Path $App "bin") + ";" + $env:PATH
  $log = Join-Path $Out "server.log"
  $srv = Start-Process $Py -ArgumentList "-m", "clippy", "web", "--no-browser", "--port", "7860" -WorkingDirectory $App `
         -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -WindowStyle Hidden
  $api = "http://127.0.0.1:7860/api"
  $ok = $false
  foreach ($i in 1..60) { try { Invoke-RestMethod "$api/status" | Out-Null; $ok = $true; break } catch { Start-Sleep 1 } }
  if (-not $ok) { Get-Content $log, "$log.err" -ErrorAction SilentlyContinue; throw "The app's server didn't start" }
  $setup = Invoke-RestMethod "$api/setup"
  Write-Host ("Missing on a fresh install: " + ($setup.missing -join ", "))
  Write-Host ("Hardware: " + ($setup.hardware | ConvertTo-Json -Compress))

  function Install-Part($id) {
    Invoke-RestMethod -Method Post "$api/setup/install" -ContentType "application/json" -Body (@{ id = $id } | ConvertTo-Json) | Out-Null
    foreach ($i in 1..600) {
      Start-Sleep 2
      $s = Invoke-RestMethod "$api/setup"
      $rows = @($s.components) + @($s.models)
      $row = $rows | Where-Object { $_.id -eq $id -or ("model:" + $_.id) -eq $id } | Select-Object -First 1
      if ($row.task -and $row.task.state -eq "failed") { throw "$id failed: $($row.task.error)" }
      if ($row.installed -and -not ($row.task -and $row.task.state -eq "running")) { Write-Host "  ready: $id"; return }
    }
    throw "$id took too long"
  }
  Step "Smoke test: download parts through the app"
  Install-Part "ffmpeg"
  Install-Part "emoji"
  Install-Part "engine"
  Install-Part "model:Qwen3.5-4B-Q4_K_M"
  Run (Join-Path $App "bin\ffmpeg.exe") -hide_banner -version
  Step "Smoke test: the built-in AI answers"
  Push-Location $App
  $answer = & $Py -m clippy ai test 2>&1 | Out-String
  Pop-Location
  Write-Host $answer
  if ($answer -notmatch "Test answer") { throw "The built-in AI didn't answer" }
  Stop-Process -Id $srv.Id -Force

  Step "Test suite with the bundled Python"
  Run $Py -m pip install --disable-pip-version-check --no-warn-script-location pytest
  Push-Location $Root
  & $Py -m pytest -q -p no:cacheprovider tests
  $failed = $LASTEXITCODE
  Pop-Location
  Run $Py -m pip uninstall -y pytest pluggy iniconfig
  if ($failed) { throw "Tests failed on Windows" }

  Step "Remove everything the smoke test downloaded"
  foreach ($d in "bin", "engine", "downloads", "data", "output", "models\llm", "models\whisper") {
    $p = Join-Path $App $d; if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  }
  foreach ($f in "settings.json", "fonts\NotoColorEmoji.ttf") { $p = Join-Path $App $f; if (Test-Path $p) { Remove-Item -Force $p } }
}
Get-ChildItem $App -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Step "Portable zip"
$zip = Join-Path $Out "Clippy-portable-$Version-win64.zip"
Compress-Archive -Path $App -DestinationPath $zip -CompressionLevel Optimal

Step "Installer"
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
$env:CLIPPY_VERSION = $Version
Run $iscc /Q (Join-Path $Here "clippy.iss")

Step "Done"
Get-ChildItem $Out -File | ForEach-Object { "{0,8:N0} MB  {1}" -f ($_.Length / 1MB), $_.Name }
