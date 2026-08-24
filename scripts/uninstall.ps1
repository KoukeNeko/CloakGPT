[CmdletBinding()]
param(
    [string]$InstallDir = $env:CLOAKGPT_INSTALL_DIR
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\CloakGPT"
}
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$executable = Join-Path $InstallDir "cloakgpt.exe"

if (Test-Path -LiteralPath $executable -PathType Leaf) {
    Remove-Item -LiteralPath $executable -Force
    Write-Host "Removed $executable"
} else {
    Write-Host "CloakGPT is not installed at $executable"
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

Write-Host "Browser profile and conversation state were preserved."
