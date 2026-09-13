[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$SkipTests,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ($env:OS -ne "Windows_NT") { throw "Build the Windows release on Windows." }
if (-not $Python) {
    $localPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path -LiteralPath $localPython) { $localPython } else { "python" }
}
$buildRoot = Join-Path $projectRoot "build\windows"
$distRoot = Join-Path $projectRoot "dist\windows"
$releaseRoot = Join-Path $projectRoot "release"
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$env:PYINSTALLER_CONFIG_DIR = Join-Path $buildRoot "cache"
$env:PYTHONDONTWRITEBYTECODE = "1"

function Invoke-BuildPython {
    param([string[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE." }
}

Push-Location -LiteralPath $projectRoot
try {
    Invoke-BuildPython -Arguments @("-c", "import sys, struct; assert sys.platform == 'win32' and struct.calcsize('P') == 8, 'Windows x64 Python required'; print(sys.version)")
    if (-not $SkipInstall) {
        Invoke-BuildPython -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements-build.txt")
    }
    if (-not $SkipTests) {
        Invoke-BuildPython -Arguments @("-B", "tests/run_all.py")
    }
    $versionLine = Select-String -LiteralPath (Join-Path $projectRoot "desktop_gremlin.py") -Pattern '^VERSION = "([^"]+)"$'
    if (-not $versionLine) { throw "Could not read VERSION from desktop_gremlin.py." }
    $releaseVersion = $versionLine.Matches[0].Groups[1].Value
    if ($env:GITHUB_REF_TYPE -eq "tag" -and $env:GITHUB_REF_NAME -ne "v$releaseVersion") {
        throw "Release tag must match source VERSION: v$releaseVersion."
    }
    Invoke-BuildPython -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "--workpath", $buildRoot, "--distpath", $distRoot, "DesktopGremlin.spec")
    $analysisWarnings = Join-Path $buildRoot "DesktopGremlin\warn-DesktopGremlin.txt"
    if (Select-String -LiteralPath $analysisWarnings -Pattern '^missing module named gremlin_') {
        throw "PyInstaller analysis could not find an application module."
    }
    $bundleRoot = Join-Path $distRoot "DesktopGremlin"
    $smokeReport = Join-Path $buildRoot "packaged-self-test.json"
    Invoke-BuildPython -Arguments @("-B", "packaging/release.py", "smoke", "--bundle", $bundleRoot, "--report", $smokeReport, "--version", $releaseVersion)
    Invoke-BuildPython -Arguments @("-B", "packaging/release.py", "package", "--bundle", $bundleRoot, "--output", $releaseRoot, "--version", $releaseVersion, "--guide", "USER_DOWNLOAD_GUIDE.md", "--license", "LICENSE")
    Write-Output "Ready: $releaseRoot\DesktopGremlin-$releaseVersion-Windows-x64.zip"
} finally {
    Pop-Location
}
