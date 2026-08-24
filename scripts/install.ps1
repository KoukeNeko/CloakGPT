[CmdletBinding()]
param(
    [string]$Version = $env:CLOAKGPT_VERSION,
    [string]$InstallDir = $env:CLOAKGPT_INSTALL_DIR
)

$ErrorActionPreference = "Stop"
$repository = "KoukeNeko/CloakGPT"
$asset = "cloakgpt-windows-x86_64.exe"

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = "latest"
} elseif ($Version -ne "latest" -and -not $Version.StartsWith("v")) {
    $Version = "v$Version"
}

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\CloakGPT"
}
$InstallDir = [IO.Path]::GetFullPath($InstallDir)

if ($Version -eq "latest") {
    $downloadBase = "https://github.com/$repository/releases/latest/download"
} else {
    $downloadBase = "https://github.com/$repository/releases/download/$Version"
}

$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd(
    [IO.Path]::DirectorySeparatorChar
)
$tempDir = [IO.Path]::GetFullPath(
    (Join-Path $tempRoot ("cloakgpt-" + [Guid]::NewGuid().ToString("N")))
)
if (-not $tempDir.StartsWith(
    $tempRoot + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "Refusing to use a temporary path outside $tempRoot"
}

New-Item -ItemType Directory -Path $tempDir | Out-Null
try {
    $downloadedAsset = Join-Path $tempDir $asset
    $downloadedChecksum = "$downloadedAsset.sha256"

    Write-Host "Downloading $asset ($Version)..."
    Invoke-WebRequest -Uri "$downloadBase/$asset" -OutFile $downloadedAsset
    Invoke-WebRequest -Uri "$downloadBase/$asset.sha256" -OutFile $downloadedChecksum

    $expected = ((Get-Content -LiteralPath $downloadedChecksum -Raw).Trim() -split "\s+")[0]
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $downloadedAsset).Hash
    if ($expected -ne $actual) {
        throw "SHA-256 checksum mismatch"
    }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $installedExecutable = Join-Path $InstallDir "cloakgpt.exe"
    Copy-Item -LiteralPath $downloadedAsset -Destination $installedExecutable -Force

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $pathEntries = @($userPath -split ";" | Where-Object { $_ })
    if ($InstallDir -notin $pathEntries) {
        $newUserPath = (($pathEntries + $InstallDir) -join ";")
        [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
        Write-Host "Added $InstallDir to your user PATH. Open a new terminal to use it."
    }

    Write-Host "Installed cloakgpt to $installedExecutable"
} finally {
    if (Test-Path -LiteralPath $tempDir) {
        Remove-Item -LiteralPath $tempDir -Recurse -Force
    }
}
