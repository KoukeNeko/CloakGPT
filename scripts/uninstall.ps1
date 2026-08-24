[CmdletBinding()]
param(
    [string]$InstallDir = $env:CLOAKGPT_INSTALL_DIR,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"
$userHomeDir = [Environment]::GetFolderPath("UserProfile")
if ([string]::IsNullOrWhiteSpace($userHomeDir)) {
    throw "Could not determine the current user's home directory"
}
$userHomeDir = [IO.Path]::GetFullPath($userHomeDir)
$workingDir = [IO.Path]::GetFullPath((Get-Location).Path)

function Expand-CloakGptPath {
    param([Parameter(Mandatory)][string]$Path)

    if ($Path -eq "~") {
        return $userHomeDir
    }
    if ($Path.StartsWith("~/") -or $Path.StartsWith("~\")) {
        return [IO.Path]::GetFullPath((Join-Path $userHomeDir $Path.Substring(2)))
    }
    return [IO.Path]::GetFullPath($Path)
}

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\CloakGPT"
}
$InstallDir = Expand-CloakGptPath $InstallDir
$executable = Join-Path $InstallDir "cloakgpt.exe"

if ([string]::IsNullOrWhiteSpace($env:CLOAKGPT_DATA_DIR)) {
    $dataDir = Join-Path $env:LOCALAPPDATA "CloakGPT"
} else {
    $dataDir = Expand-CloakGptPath $env:CLOAKGPT_DATA_DIR
}
if ([string]::IsNullOrWhiteSpace($env:CLOAKBROWSER_CACHE_DIR)) {
    $browserCacheDir = Join-Path $userHomeDir ".cloakbrowser"
} else {
    $browserCacheDir = Expand-CloakGptPath $env:CLOAKBROWSER_CACHE_DIR
}

if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    $codexHome = Join-Path $userHomeDir ".codex"
} else {
    $codexHome = Expand-CloakGptPath $env:CODEX_HOME
}
$skillPaths = @(
    (Join-Path $userHomeDir ".aider-desk\skills\use-cloakgpt"),
    (Join-Path $userHomeDir ".agents\skills\use-cloakgpt"),
    (Join-Path $userHomeDir ".claude\skills\use-cloakgpt"),
    (Join-Path $userHomeDir ".config\agents\skills\use-cloakgpt"),
    (Join-Path $userHomeDir ".gemini\skills\use-cloakgpt"),
    (Join-Path $userHomeDir ".openclaw\skills\use-cloakgpt"),
    (Join-Path $codexHome "skills\use-cloakgpt")
)

function Get-NormalizedPath {
    param([Parameter(Mandatory)][string]$Path)
    return ([IO.Path]::GetFullPath($Path)).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
}

function Assert-SafeTree {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label
    )

    $target = Get-NormalizedPath $Path
    $root = Get-NormalizedPath ([IO.Path]::GetPathRoot($target))
    if ([string]::Equals($target, $root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove filesystem root for ${Label}: $target"
    }

    $separator = [IO.Path]::DirectorySeparatorChar
    foreach ($protectedPath in @($userHomeDir, $workingDir, $InstallDir)) {
        $protected = Get-NormalizedPath $protectedPath
        if ([string]::Equals(
            $target,
            $protected,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Refusing to remove protected directory $target for $Label"
        }
        if ($protected.StartsWith(
            $target + $separator,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Refusing to remove $target because it contains $protected"
        }
    }
}

function Remove-CloakGptTree {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label
    )

    $item = Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    if ($null -eq $item) {
        return
    }
    Assert-SafeTree -Path $Path -Label $Label
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        Remove-Item -LiteralPath $Path -Force
    } else {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    Write-Host "Removed ${Label}: $Path"
}

foreach ($plannedTree in @($dataDir, $browserCacheDir) + $skillPaths) {
    if ($null -ne (Get-Item -LiteralPath $plannedTree -Force -ErrorAction SilentlyContinue)) {
        Assert-SafeTree -Path $plannedTree -Label "planned uninstall target"
    }
}

if (-not $Yes) {
    $interactive = $Host.Name -eq "ConsoleHost"
    try {
        $interactive = $interactive -and -not [Console]::IsInputRedirected
    } catch {
        $interactive = $false
    }
    if (-not $interactive) {
        throw "Complete uninstall requires an interactive confirmation or -Yes"
    }

    Write-Warning "This permanently removes CloakGPT and all local CloakGPT data."
    Write-Host (
        "ChatGPT cookies/session, conversation state, CloakBrowser downloads " +
        "and license data, and installed use-cloakgpt Agent Skills will be deleted."
    )
    $answer = Read-Host "Type REMOVE to continue"
    if ($answer -cne "REMOVE") {
        Write-Host "Uninstall cancelled."
        return
    }
}

if (Test-Path -LiteralPath $executable -PathType Leaf) {
    try {
        & $executable daemon stop *> $null
    } catch {
        # The daemon may not be running; removal can continue.
    }
}

$skillCliFailed = $false
$npxCommand = Get-Command "npx.cmd" -ErrorAction SilentlyContinue
if ($null -eq $npxCommand) {
    $npxCommand = Get-Command "npx" -ErrorAction SilentlyContinue
}
if ($null -ne $npxCommand) {
    try {
        & $npxCommand.Source -y skills remove use-cloakgpt --global --agent "*" --yes
        if ($LASTEXITCODE -ne 0) {
            throw "Agent Skills CLI exited with code $LASTEXITCODE"
        }
        Write-Host "Removed use-cloakgpt through the Agent Skills CLI."
    } catch {
        $skillCliFailed = $true
        Write-Warning (
            "Agent Skills CLI removal failed; removing known paths directly. " +
            $_.Exception.Message
        )
    }
}

foreach ($skillPath in $skillPaths) {
    Remove-CloakGptTree -Path $skillPath -Label "Agent Skill"
}

Remove-CloakGptTree -Path $dataDir -Label "CloakGPT user data"
Remove-CloakGptTree `
    -Path $browserCacheDir `
    -Label "CloakBrowser cache and license data"

if (Test-Path -LiteralPath $executable -PathType Leaf) {
    Remove-Item -LiteralPath $executable -Force
    Write-Host "Removed executable: $executable"
} else {
    Write-Host "CloakGPT executable was not present at $executable"
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$pathEntries = @($userPath -split ";" | Where-Object { $_ })
$remainingEntries = @(
    $pathEntries | Where-Object {
        -not [string]::Equals(
            $_.TrimEnd("\"),
            $InstallDir.TrimEnd("\"),
            [StringComparison]::OrdinalIgnoreCase
        )
    }
)
if ($remainingEntries.Count -ne $pathEntries.Count) {
    [Environment]::SetEnvironmentVariable("Path", ($remainingEntries -join ";"), "User")
    Write-Host "Removed $InstallDir from your user PATH."
}
if ((Test-Path -LiteralPath $InstallDir -PathType Container) -and
    $null -eq (Get-ChildItem -LiteralPath $InstallDir -Force | Select-Object -First 1)) {
    Remove-Item -LiteralPath $InstallDir -Force
    Write-Host "Removed empty install directory: $InstallDir"
}

if ($skillCliFailed) {
    Write-Warning (
        "Known skill paths were removed, but the Agent Skills CLI could not " +
        "verify every runtime."
    )
}
Write-Host "CloakGPT complete uninstall finished."
