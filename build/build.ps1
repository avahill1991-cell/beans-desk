# Build signed Windows executables.
#
# Two artifacts:
#   build\dist\beansdesk-cli.exe   console build (engine, scripting, support)
#   build\dist\BeansDesk.exe       windowed desktop app (what customers double-click)
#
# The console build is NOT named beansdesk.exe: Windows filenames are
# case-insensitive, so beansdesk.exe and BeansDesk.exe are the same file and the
# second build silently overwrites the first.
#
# Prerequisites:
#   py -m pip install --upgrade pyinstaller customtkinter
#   A code-signing identity. Unsigned builds trigger SmartScreen and cost refunds.
#
# Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File build\build.ps1

param(
    [string]$CertThumbprint = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> cleaning"
foreach ($dir in @("build\dist", "build\work", "build\cli", "build\gui")) {
    if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
}

Write-Host "==> running tests"
py -m unittest discover -s tests -t .
if ($LASTEXITCODE -ne 0) { throw "tests failed - refusing to build" }

Write-Host "==> packaging console build"
py -m PyInstaller `
    --noconfirm --clean --onefile --console `
    --name "beansdesk-cli" `
    --distpath "build\dist" --workpath "build\work\cli" --specpath "build\cli" `
    --collect-submodules beansdesk `
    --exclude-module customtkinter --exclude-module numpy --exclude-module PIL `
    --exclude-module tkinter `
    "beansdesk\__main__.py"
if ($LASTEXITCODE -ne 0) { throw "console build failed" }

Write-Host "==> packaging desktop build"
py -m PyInstaller `
    --noconfirm --clean --onefile --windowed `
    --name "BeansDesk" `
    --distpath "build\dist" --workpath "build\work\gui" --specpath "build\gui" `
    --collect-all customtkinter `
    --collect-submodules beansdesk `
    "beansdesk\launcher.py"
if ($LASTEXITCODE -ne 0) { throw "desktop build failed" }

$targets = @("build\dist\beansdesk-cli.exe", "build\dist\BeansDesk.exe")
foreach ($exe in $targets) { Write-Host "==> built $exe" }

if ($CertThumbprint -ne "") {
    foreach ($exe in $targets) {
        Write-Host "==> signing $exe"
        & signtool.exe sign /sha1 $CertThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $exe
        if ($LASTEXITCODE -ne 0) { throw "signing failed for $exe" }
        & signtool.exe verify /pa $exe
    }
} else {
    Write-Warning "No -CertThumbprint given. These binaries are UNSIGNED and must not be sold."
}

Write-Host ""
Write-Host "Smoke test on a clean Windows VM (no Python installed):"
Write-Host "  .\build\dist\beansdesk-cli.exe --version"
Write-Host "  .\build\dist\BeansDesk.exe"
Write-Host ""
Write-Host "Signing options, cheapest first:"
Write-Host "  1. Azure Trusted Signing  ~`$10/month, no hardware token, best for a solo seller"
Write-Host "  2. OV certificate         ~`$200-300/year + token, reputation builds over time"
Write-Host "  3. EV certificate         ~`$300-500/year + hardware token, instant SmartScreen trust"
