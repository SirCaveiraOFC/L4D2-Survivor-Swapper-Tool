param(
    [string]$OutputExe = "",
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$CscExe = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not (Test-Path -LiteralPath $CscExe)) {
    throw "csc.exe not found at $CscExe"
}

if ([string]::IsNullOrWhiteSpace($OutputExe)) {
    $OutputExe = Join-Path $RepoRoot "L4D2 Survivor Swapper Tool.exe"
}

$AppMetaPath = Join-Path $RepoRoot "core\app_meta.py"
if ([string]::IsNullOrWhiteSpace($Version) -and (Test-Path -LiteralPath $AppMetaPath)) {
    $metaText = Get-Content -LiteralPath $AppMetaPath -Raw -Encoding UTF8
    $maj = if ($metaText -match 'major:\s*int\s*=\s*(\d+)') { $Matches[1] } else { "2" }
    $min = if ($metaText -match 'minor:\s*int\s*=\s*(\d+)') { $Matches[1] } else { "0" }
    $pat = if ($metaText -match 'patch:\s*int\s*=\s*(\d+)') { $Matches[1] } else { "0" }
    $Version = "$maj.$min.$pat.0"
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = "2.0.0.0"
}

$MainCs = Join-Path $ScriptDir "LauncherMain.cs"
$IconPath = Join-Path $RepoRoot "ui\app_icon.ico"
$OutDir = Split-Path -Parent $OutputExe
if ($OutDir -and -not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$TempSrc = Join-Path ([System.IO.Path]::GetTempPath()) ("l4d2sw_launcher_" + [Guid]::NewGuid().ToString("N").Substring(0, 8) + ".cs")
try {
    $csContent = [System.IO.File]::ReadAllText($MainCs, [System.Text.Encoding]::UTF8)
    $csContent = $csContent -replace 'AssemblyVersion\("[^"]+"\)', "AssemblyVersion(`"$Version`")"
    $csContent = $csContent -replace 'AssemblyFileVersion\("[^"]+"\)', "AssemblyFileVersion(`"$Version`")"
    [System.IO.File]::WriteAllText($TempSrc, $csContent, [System.Text.Encoding]::UTF8)

    $cscArgs = @(
        "/nologo",
        "/target:winexe",
        "/platform:x64",
        "/optimize+",
        "/r:System.dll",
        "/r:System.Windows.Forms.dll",
        "/out:$OutputExe"
    )
    if (Test-Path -LiteralPath $IconPath) {
        $cscArgs += "/win32icon:$IconPath"
    }
    $cscArgs += $TempSrc

    & $CscExe @cscArgs
    if ($LASTEXITCODE -ne 0) {
        throw "csc.exe failed with exit code $LASTEXITCODE"
    }
    Write-Host "Built launcher: $OutputExe (v$Version)"
}
finally {
    if (Test-Path -Path $TempSrc) {
        [System.IO.File]::Delete($TempSrc)
    }
}
