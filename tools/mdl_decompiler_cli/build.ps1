param(
    [string]$CrowbarRepoPath = ""
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutExe = Join-Path $ScriptDir "MdlDecompilerCli.exe"
$VbcExe = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\vbc.exe"

if (-not (Test-Path $VbcExe)) {
    throw "vbc.exe not found at $VbcExe"
}

$TempClone = ""
if ([string]::IsNullOrWhiteSpace($CrowbarRepoPath)) {
    $TempClone = Join-Path $env:TEMP ("crowbar_src_" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
    Write-Host "Cloning ZeqMacaw/Crowbar into $TempClone..."
    git clone --depth 1 https://github.com/ZeqMacaw/Crowbar.git $TempClone
    $CrowbarRepoPath = $TempClone
}

try {
    $ProjRoot = Join-Path $CrowbarRepoPath "Crowbar"
    [xml]$Proj = Get-Content (Join-Path $ProjRoot "Crowbar.vbproj")

    $Includes = $Proj.Project.ItemGroup.Compile.Include | Where-Object {
        $_ -like "Core\Decompiler\*" -or
        $_ -like "Core\DebugLog\*" -or
        $_ -like "Core\GameModel\*" -or
        ($_ -like "Core\- General\*" -and
            $_ -notlike "*XmlColor.vb" -and
            $_ -notlike "*LzhamApi.vb" -and
            $_ -notlike "*WindowsJob.vb" -and
            $_ -notlike "*Win32Api.vb" -and
            $_ -notlike "*Workarounds.vb") -or
        $_ -eq "Core\- Application\AppConstants.vb" -or
        $_ -eq "Core\- Application\AppEnums.vb"
    }

    $Files = @((Join-Path $ScriptDir "CliMain.vb")) + ($Includes | ForEach-Object { ".\" + $_ })
    $RspPath = Join-Path $ScriptDir "build.rsp"

    $RspLines = @(
        "/nologo",
        "/target:exe",
        "/out:`"$OutExe`"",
        "/rootnamespace:Crowbar",
        "/optionstrict+",
        "/imports:Microsoft.VisualBasic,System,System.Collections,System.Collections.Generic,System.IO,System.Diagnostics,System.Windows.Forms",
        "/r:System.dll",
        "/r:System.Core.dll",
        "/r:System.Xml.dll",
        "/r:System.Windows.Forms.dll"
    ) + ($Files | ForEach-Object { "`"$_`"" })

    [System.IO.File]::WriteAllLines($RspPath, $RspLines, [System.Text.Encoding]::ASCII)

    Push-Location $ProjRoot
    try {
        & $VbcExe "@$RspPath"
        if ($LASTEXITCODE -ne 0) {
            throw "vbc.exe failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
        if (Test-Path $RspPath) {
            Remove-Item $RspPath -Force
        }
    }

    Write-Host "Successfully built $OutExe"
}
finally {
    if ($TempClone -and (Test-Path $TempClone)) {
        Remove-Item $TempClone -Recurse -Force
    }
}
