$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$version = "4.6.0"
$workspace = (Resolve-Path $PSScriptRoot).Path
$dist = Join-Path $workspace "dist"
$stage = Join-Path $dist "AIwithSaeed-Downloader-v$version"
$zip = Join-Path $dist "AIwithSaeed-Downloader-v$version.zip"

foreach ($target in @($dist, $stage)) {
    $full = [System.IO.Path]::GetFullPath($target)
    if (-not $full.StartsWith($workspace + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe release target: $full"
    }
}

if (-not (Test-Path -LiteralPath $dist)) {
    New-Item -ItemType Directory -Path $dist | Out-Null
}
if (Test-Path -LiteralPath $stage) {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}
New-Item -ItemType Directory -Path $stage | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stage "assets") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $stage "docs") | Out-Null

$files = @(
    "app.py", "app_paths.py", "bot.py", "download_config.py", "launcher.pyw",
    "queue_store.py", "release_check.py", "ui_fonts.py", "online_download.py", "official_resources.py", "requirements.txt", "run.bat", "setup.ps1", "README.md",
    "README.en.md", "LICENSE", "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md",
    "docs\REFERENCE.md",
    "QUICK-START-FA.html", "THIRD-PARTY.md", "build-windows.py", "windows_installer.py", "requirements-build.txt"
)
$assets = @(
    "assets\aiwithsaeed-logo-dark.png", "assets\aiwithsaeed-logo-light.png",
    "assets\Vazirmatn-Regular.ttf", "assets\Vazirmatn-Bold.ttf", "assets\OFL.txt",
    "assets\Peyda-Regular.ttf", "assets\Peyda-Bold.ttf", "assets\Peyda-LICENSE-NOTICE.txt"
)

foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $workspace $file) -Destination (Join-Path $stage $file)
}
foreach ($file in $assets) {
    Copy-Item -LiteralPath (Join-Path $workspace $file) -Destination (Join-Path $stage $file)
}
Copy-Item -LiteralPath (Join-Path $workspace "docs\screenshots") -Destination (Join-Path $stage "docs\screenshots") -Recurse
Copy-Item -LiteralPath (Join-Path $workspace "licenses") -Destination (Join-Path $stage "licenses") -Recurse

foreach ($pattern in @("*.db", "*.log", "*.dpapi", "cookies*.txt", ".env*", "*.pyc")) {
    $found = Get-ChildItem -LiteralPath $stage -Recurse -Force -Filter $pattern
    if ($found) { throw "Private runtime file entered the release: $($found.FullName)" }
}

$textFiles = Get-ChildItem -LiteralPath $stage -Recurse -File | Where-Object {
    $_.Extension -in @(".py", ".pyw", ".ps1", ".bat", ".md", ".txt")
}
foreach ($needle in @("aiwithsaeed.ir", "127.0.0.1:10809", "DEFAULT_ALLOWED_CHAT_ID")) {
    $matches = $textFiles | Select-String -SimpleMatch $needle
    if ($matches) { throw "Private or legacy value '$needle' remains in $($matches.Path)" }
}

Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal
$hash = Get-FileHash -LiteralPath $zip -Algorithm SHA256
$checksum = "$($hash.Hash.ToLower())  $([System.IO.Path]::GetFileName($zip))"
Set-Content -LiteralPath (Join-Path $dist "SHA256SUMS.txt") -Value $checksum -Encoding ascii

Write-Host "Public release created:" -ForegroundColor Green
Write-Host $zip
Write-Host "SHA256: $($hash.Hash.ToLower())"
