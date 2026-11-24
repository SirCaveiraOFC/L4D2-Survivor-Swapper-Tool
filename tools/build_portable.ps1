param(
    [string]$PythonVersion = "3.13.5",
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ToolsDir "..")).Path

$AppMetaPath = Join-Path $RepoRoot "core\app_meta.py"
$metaText = Get-Content -LiteralPath $AppMetaPath -Raw -Encoding UTF8
$maj = if ($metaText -match 'major:\s*int\s*=\s*(\d+)') { $Matches[1] } else { "2" }
$min = if ($metaText -match 'minor:\s*int\s*=\s*(\d+)') { $Matches[1] } else { "0" }
$pat = if ($metaText -match 'patch:\s*int\s*=\s*(\d+)') { $Matches[1] } else { "0" }
$AppVersion = "$maj.$min.$pat"

$CacheDir = Join-Path ([System.IO.Path]::GetTempPath()) "l4d2sw_build_cache"
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null

$VerParts = $PythonVersion.Split(".")
$PySeriesTag = "$($VerParts[0])$($VerParts[1])"
$EmbedZipName = "python-$PythonVersion-embed-amd64.zip"
$EmbedZipUrl = "https://www.python.org/ftp/python/$PythonVersion/$EmbedZipName"
$EmbedZipPath = Join-Path $CacheDir $EmbedZipName
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$GetPipPath = Join-Path $CacheDir "get-pip.py"

if (-not (Test-Path -LiteralPath $EmbedZipPath)) {
    Write-Host "Downloading Python $PythonVersion Embeddable Package..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $EmbedZipUrl -OutFile $EmbedZipPath -UseBasicParsing
}
if (-not (Test-Path -LiteralPath $GetPipPath)) {
    Write-Host "Downloading get-pip.py..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $GetPipUrl -OutFile $GetPipPath -UseBasicParsing
}

$DistRoot = Join-Path $RepoRoot "dist"
$BundleDir = Join-Path $DistRoot "L4D2-Survivor-Swapper-Tool-Portable"
$RuntimeDir = Join-Path $BundleDir "runtime"

if (Test-Path -LiteralPath $BundleDir) {
    Write-Host "Cleaning previous bundle at $BundleDir..."
    Remove-Item -LiteralPath $BundleDir -Recurse -Force
}
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

Write-Host "Extracting embedded Python runtime..."
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::ExtractToDirectory($EmbedZipPath, $RuntimeDir)

$PthFile = Join-Path $RuntimeDir "python$PySeriesTag._pth"
if (-not (Test-Path -LiteralPath $PthFile)) {
    throw "Expected ._pth file not found: $PthFile"
}
$pthLines = @(
    "python$PySeriesTag.zip",
    ".",
    "..",
    "Lib\site-packages",
    "import site"
)
[System.IO.File]::WriteAllLines($PthFile, $pthLines, [System.Text.Encoding]::ASCII)

$RuntimePython = Join-Path $RuntimeDir "python.exe"
$ReqFile = Join-Path $RepoRoot "requirements.txt"
$origPath = $env:PATH
$origPyPath = $env:PYTHONPATH
$origPyHome = $env:PYTHONHOME
$origNoUser = $env:PYTHONNOUSERSITE
try {
    $env:PYTHONPATH = ""
    $env:PYTHONHOME = ""
    $env:PYTHONNOUSERSITE = "1"

    Write-Host "Bootstrapping pip inside embedded runtime..."
    & $RuntimePython $GetPipPath --no-warn-script-location
    if ($LASTEXITCODE -ne 0) {
        throw "get-pip.py failed with exit code $LASTEXITCODE"
    }

    Write-Host "Installing dependencies (slim PySide6-Essentials + Fluent-Widgets without WebEngine)..."
    $deps = @(
        "PySide6-Essentials>=6.9.0",
        "PySideSix-Frameless-Window>=0.8.0",
        "darkdetect",
        "vpk>=1.4.0",
        "vdf>=3.4",
        "psutil>=5.9.0"
    )
    & $RuntimePython -m pip install --no-cache-dir --no-warn-script-location @deps
    if ($LASTEXITCODE -ne 0) {
        throw "pip install core dependencies failed with exit code $LASTEXITCODE"
    }
    & $RuntimePython -m pip install --no-cache-dir --no-warn-script-location --no-deps "PySide6-Fluent-Widgets>=1.11.0"
    if ($LASTEXITCODE -ne 0) {
        throw "pip install PySide6-Fluent-Widgets failed with exit code $LASTEXITCODE"
    }
}
finally {
    if ($null -ne $origPath) { $env:PATH = $origPath }
    if ($null -ne $origPyPath) { $env:PYTHONPATH = $origPyPath }
    if ($null -ne $origPyHome) { $env:PYTHONHOME = $origPyHome }
    if ($null -ne $origNoUser) { $env:PYTHONNOUSERSITE = $origNoUser } else { Remove-Item Env:PYTHONNOUSERSITE -ErrorAction SilentlyContinue }
}

Write-Host "Copying application source and assets..."
$RootFiles = @(
    "app.py",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "requirements.txt",
    "_RUN.bat",
    "_INSTALL_REQUIREMENTS.bat"
)
foreach ($f in $RootFiles) {
    $src = Join-Path $RepoRoot $f
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $BundleDir $f) -Force
    }
}

$ExcludeDirs = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($ex in @("__pycache__", ".pytest_cache", "bin", "obj")) {
    [void]$ExcludeDirs.Add($ex)
}

function Copy-CleanTree {
    param([string]$SrcDir, [string]$DstDir)
    if (-not (Test-Path -LiteralPath $SrcDir)) { return }
    New-Item -ItemType Directory -Path $DstDir -Force | Out-Null
    foreach ($entry in Get-ChildItem -LiteralPath $SrcDir -Force) {
        if ($entry.PSIsContainer) {
            if ($ExcludeDirs.Contains($entry.Name)) { continue }
            Copy-CleanTree -SrcDir $entry.FullName -DstDir (Join-Path $DstDir $entry.Name)
        } else {
            if ($entry.Extension -in @(".pyc", ".pyo")) { continue }
            Copy-Item -LiteralPath $entry.FullName -Destination (Join-Path $DstDir $entry.Name) -Force
        }
    }
}

foreach ($d in @("core", "ui", "docs", "tools", "HUNK'S_SURVIVOR_SWAP_KIT", "tests")) {
    Copy-CleanTree -SrcDir (Join-Path $RepoRoot $d) -DstDir (Join-Path $BundleDir $d)
}

$LauncherExe = Join-Path $BundleDir "L4D2 Survivor Swapper Tool.exe"
$LauncherBuild = Join-Path $ToolsDir "launcher\build.ps1"
& $LauncherBuild -OutputExe $LauncherExe -Version "$AppVersion.0"

Write-Host "Running isolated portable verification (no system PATH Python)..."
$origPath = $env:PATH
$origPyPath = $env:PYTHONPATH
$origPyHome = $env:PYTHONHOME
$origQt = $env:QT_QPA_PLATFORM
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONPATH = ""
    $env:PYTHONHOME = ""
    $env:QT_QPA_PLATFORM = "offscreen"
    & $RuntimePython -c "import shutil, tempfile; from pathlib import Path; from PySide6.QtWidgets import QApplication; import PySide6, qfluentwidgets, vpk, vdf, psutil, core.app_meta, core.updater; from ui.main_window import MainWindow; tmp = Path(tempfile.mkdtemp()); app = QApplication([]); w = MainWindow(project_root=tmp); w._wizard_timer.stop(); w._update_check_timer.stop(); w.show(); app.processEvents(); w.close(); shutil.rmtree(tmp, ignore_errors=True); print('PORTABLE_GUI_OK:', core.app_meta.APP_META.version, core.app_meta.APP_META.license_name)"
    if ($LASTEXITCODE -ne 0) {
        throw "Portable GUI import verification failed"
    }
    $chkOut = & $LauncherExe --check-env 2>&1 | Out-String
    if ($chkOut -notmatch "L4D2 Survivor Swapper Environment Check") {
        throw "Portable launcher CLI verification failed: $chkOut"
    }
    foreach ($userArtifact in @("settings.json", "conversion_history.json", ".update_manifest.json")) {
        $uaPath = Join-Path $BundleDir $userArtifact
        if (Test-Path -LiteralPath $uaPath) { Remove-Item -LiteralPath $uaPath -Force }
    }
    Write-Host "Launcher verified OK in isolated environment."
}
finally {
    $env:PATH = $origPath
    if ($null -ne $origPyPath) { $env:PYTHONPATH = $origPyPath }
    if ($null -ne $origPyHome) { $env:PYTHONHOME = $origPyHome }
    if ($null -ne $origQt) { $env:QT_QPA_PLATFORM = $origQt } else { Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue }
}

foreach ($cacheSub in Get-ChildItem -LiteralPath $BundleDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue) {
    Remove-Item -LiteralPath $cacheSub.FullName -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $SkipZip) {
    $ZipPath = Join-Path $DistRoot "L4D2-Survivor-Swapper-Tool-v$AppVersion-win64.zip"
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    $StageParent = Join-Path ([System.IO.Path]::GetTempPath()) ("l4d2sw_zip_" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    $NamedFolder = Join-Path $StageParent "L4D2 Survivor Swapper Tool"
    New-Item -ItemType Directory -Path $StageParent -Force | Out-Null
    try {
        Copy-CleanTree -SrcDir $BundleDir -DstDir $NamedFolder
        Write-Host "Creating portable ZIP archive at $ZipPath..."
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $StageParent,
            $ZipPath,
            [System.IO.Compression.CompressionLevel]::Optimal,
            $false
        )
    }
    finally {
        if (Test-Path -Path $StageParent) {
            [System.IO.Directory]::Delete($StageParent, $true)
        }
    }
    $zipMb = [Math]::Round((Get-Item -LiteralPath $ZipPath).Length / 1MB, 1)
    Write-Host "Portable ZIP ready: $ZipPath ($zipMb MB)"
}

Write-Host "Portable bundle ready at: $BundleDir"
