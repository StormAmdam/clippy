# Builds the Windows app: dist\Clippy (portable folder), dist\Clippy-portable-<version>-win64.zip and
# dist\Clippy-Setup-<version>-win64.exe. Needs uv, the MSVC tools (cl, rc) and Inno Setup 6 (iscc).
#   ./packaging/windows/build.ps1               build
#   ./packaging/windows/build.ps1 -SmokeTest    also test the built app from a folder with a name like C:\Users\Jörg:
#                                               download parts through it, ask the built-in AI, transcribe speech,
#                                               make a real clip (smoke.py) and run the test suite with its Python
param([switch]$SmokeTest)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Here = $PSScriptRoot
$Out = Join-Path $Root "dist"
$App = Join-Path $Out "Clippy"
$Version = if ($env:CLIPPY_VERSION) { $env:CLIPPY_VERSION -replace '^v', '' } else { "0.3.1" }
function Step($t) { Write-Host "`n=== $t" -ForegroundColor Cyan }
function Run($exe) { & $exe @args; if ($LASTEXITCODE) { throw "$exe failed ($LASTEXITCODE)" } }

Step "Clean"
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Force $App | Out-Null

Step "Python (relocatable build, lives inside the app folder)"
$pyTmp = Join-Path $Out "py"
Run uv python install 3.13 --install-dir $pyTmp
# uv also makes a "cpython-3.13-…" shortcut (junction) to the real "cpython-3.13.N-…" folder: take the real one
$pyDir = Get-ChildItem $pyTmp -Directory |
  Where-Object { -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -and (Test-Path (Join-Path $_.FullName "python.exe")) } |
  Select-Object -First 1
if (-not $pyDir) { throw "uv didn't install a Python folder" }
Copy-Item -Recurse $pyDir.FullName (Join-Path $App "python")
Remove-Item -Recurse -Force $pyTmp
# uv marks its Pythons "externally managed" (pip refuses to touch them). This one belongs to the app alone, and the
# app itself uses pip later (NVIDIA acceleration), so drop the marker.
Get-ChildItem (Join-Path $App "python") -Recurse -Filter "EXTERNALLY-MANAGED" | Remove-Item -Force
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
Copy-Item -Recurse (Join-Path $Root "community") (Join-Path $App "community")   # the community extensions list, offline
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
  # Run it all from a folder named like a non-English Windows user's (C:\Users\Jörg 测试\…), space included: the AI
  # engine, ffmpeg, Whisper and the face finder must all cope with paths like that.
  $Test = Join-Path $Out ("J" + [char]0x00F6 + "rg " + [char]0x6D4B + [char]0x8BD5)
  New-Item -ItemType Directory -Force $Test | Out-Null
  $TestApp = Join-Path $Test "Clippy"
  Move-Item $App $TestApp
  $TPy = Join-Path $TestApp "python\python.exe"

  Step "Smoke test: start the built app (in $TestApp)"
  $env:PATH = (Join-Path $TestApp "bin") + ";" + $env:PATH
  $log = Join-Path $Out "server.log"
  $srv = Start-Process $TPy -ArgumentList "-m", "clippy", "web", "--no-browser", "--port", "7860" -WorkingDirectory $TestApp `
         -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -WindowStyle Hidden
  $api = "http://127.0.0.1:7860/api"
  $ok = $false
  foreach ($i in 1..60) { try { Invoke-RestMethod "$api/status" | Out-Null; $ok = $true; break } catch { Start-Sleep 1 } }
  if (-not $ok) { Get-Content $log, "$log.err" -ErrorAction SilentlyContinue; throw "The app's server didn't start" }
  $setup = Invoke-RestMethod "$api/setup"
  Write-Host ("Missing on a fresh install: " + ($setup.missing -join ", "))
  Write-Host ("Hardware: " + ($setup.hardware | ConvertTo-Json -Compress))
  if ($setup.folder -ne $TestApp) { throw "The app reports its folder as $($setup.folder), not $TestApp" }

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
  # the small speech model, for the transcription test (people get large-v3-turbo)
  Invoke-RestMethod -Method Post "$api/settings" -ContentType "application/json" -Body '{"whisper_model": "tiny"}' | Out-Null
  Install-Part "whisper"
  Run (Join-Path $TestApp "bin\ffmpeg.exe") -hide_banner -version
  Step "Smoke test: the built-in AI answers"
  Push-Location $TestApp
  $answer = & $TPy -m clippy ai test 2>&1 | Out-String
  Pop-Location
  Write-Host $answer
  if ($answer -notmatch "Test answer") { throw "The built-in AI didn't answer" }

  Step "Smoke test: speech, transcription and a real clip"
  Run $TPy -X utf8 (Join-Path $Here "smoke.py") --app $TestApp --api "http://127.0.0.1:7860" --out (Join-Path $Out "smoke")

  Step "Smoke test: ending Clippy also ends its AI engine"
  if (-not (Get-Process llama-server -ErrorAction SilentlyContinue)) { throw "The built-in AI should still be loaded after making a clip" }
  Stop-Process -Id $srv.Id -Force                      # like End task in Task Manager
  $gone = $false
  foreach ($i in 1..30) { if (-not (Get-Process llama-server -ErrorAction SilentlyContinue)) { $gone = $true; break }; Start-Sleep 1 }
  if (-not $gone) { Get-Process llama-server | Format-Table Id, Path; throw "The AI engine kept running after Clippy was ended" }
  Write-Host "  the AI engine ended with Clippy"

  Step "Test suite with the bundled Python (temp files in the same kind of folder)"
  # -X utf8: pip prints this folder's name, and fails without UTF-8 mode (the app's own pip calls use it too)
  Run $TPy -X utf8 -m pip install --disable-pip-version-check --no-warn-script-location pytest
  Push-Location $Root
  & $TPy -X utf8 -m pytest -q -p no:cacheprovider tests --basetemp (Join-Path $Test "pytest temp")   # UTF-8 mode, as the app always runs
  $failed = $LASTEXITCODE
  Pop-Location
  Run $TPy -X utf8 -m pip uninstall -y pytest pluggy iniconfig
  if ($failed) { throw "Tests failed on Windows" }

  Step "Remove everything the smoke test downloaded"
  foreach ($d in "bin", "engine", "downloads", "data", "output", "models\llm", "models\whisper") {
    $p = Join-Path $TestApp $d; if (Test-Path $p) { Remove-Item -Recurse -Force $p }
  }
  foreach ($f in "settings.json", "fonts\NotoColorEmoji.ttf") { $p = Join-Path $TestApp $f; if (Test-Path $p) { Remove-Item -Force $p } }
  Move-Item $TestApp $App
  Remove-Item -Recurse -Force $Test
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
