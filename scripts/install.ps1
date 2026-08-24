[CmdletBinding()]
param(
    [string]$Version = $env:CLOAKGPT_VERSION,
    [string]$Channel = $env:CLOAKGPT_CHANNEL,
    [string]$InstallDir = $env:CLOAKGPT_INSTALL_DIR
)

$ErrorActionPreference = "Stop"
$repository = "KoukeNeko/CloakGPT"
$interactive = $Host.Name -eq "ConsoleHost"
try {
    $interactive = $interactive -and -not [Console]::IsInputRedirected
} catch {
    $interactive = $false
}

function Write-InstallMotd {
    param(
        [Parameter(Mandatory)]
        [string]$Executable,
        [Parameter(Mandatory)]
        [bool]$BrowserInstalled,
        [Parameter(Mandatory)]
        [string]$LoginState,
        [Parameter(Mandatory)]
        [bool]$PathAdded,
        [Parameter(Mandatory)]
        [string]$Release
    )

    Write-Host ""
    Write-Host "============================================================"
    if ($BrowserInstalled -and $LoginState -eq "FLOW COMPLETED") {
        Write-Host "  CloakGPT is ready"
    } else {
        Write-Host "  CloakGPT installation needs one more step"
    }
    Write-Host "============================================================"
    Write-Host "  Application : READY"
    Write-Host "  Release     : $Release"
    Write-Host "  Installed at: $Executable"
    if ($BrowserInstalled) {
        Write-Host "  Browser     : READY"
    } else {
        Write-Host "  Browser     : NEEDS SETUP" -ForegroundColor Yellow
    }
    Write-Host "  Login       : $LoginState"
    Write-Host "------------------------------------------------------------"

    if (-not $BrowserInstalled) {
        Write-Host "  Next steps"
        Write-Host "    1. & `"$Executable`" browser install"
        Write-Host "    2. & `"$Executable`" login"
    } elseif ($LoginState -ne "FLOW COMPLETED") {
        Write-Host "  Next step"
        Write-Host "    & `"$Executable`" login"
    } else {
        Write-Host "  Quick start"
        Write-Host "    `$sessionId = & `"$Executable`" session open"
        Write-Host "    & `"$Executable`" ask --session `$sessionId `"Hello`""
    }

    if ($PathAdded) {
        Write-Host "------------------------------------------------------------"
        Write-Host "  PATH notice"
        Write-Host "    Open a new terminal to run: cloakgpt"
    }
    Write-Host "============================================================"
}

$architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
$asset = switch ($architecture) {
    "X64" { "cloakgpt-windows-x86_64.exe" }
    "Arm64" { "cloakgpt-windows-arm64.exe" }
    default { throw "Unsupported Windows architecture: $architecture" }
}

if ([string]::IsNullOrWhiteSpace($Version) -or $Version -eq "latest") {
    if ($Version -eq "latest") {
        $Channel = "stable"
    } elseif ([string]::IsNullOrWhiteSpace($Channel)) {
        if ($interactive) {
            Write-Host "Select a release channel:"
            Write-Host "  1) Stable"
            Write-Host "  2) Prerelease"
            $Channel = Read-Host "Choice [1]"
        } else {
            $Channel = "stable"
        }
    }

    $Channel = switch ($Channel.Trim().ToLowerInvariant()) {
        { $_ -in @("", "1", "stable") } { "stable"; break }
        { $_ -in @("2", "prerelease") } { "prerelease"; break }
        default { throw "Release channel must be 'stable' or 'prerelease'" }
    }

    $apiHeaders = @{
        Accept = "application/vnd.github+json"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
    try {
        if ($Channel -eq "stable") {
            $release = Invoke-RestMethod `
                -Uri "https://api.github.com/repos/$repository/releases/latest" `
                -Headers $apiHeaders
        } else {
            $releases = @(Invoke-RestMethod `
                -Uri "https://api.github.com/repos/$repository/releases?per_page=100" `
                -Headers $apiHeaders)
            $release = $releases |
                Where-Object { $_.prerelease -and -not $_.draft } |
                Select-Object -First 1
        }
    } catch {
        throw (
            "Could not resolve the $Channel release; it may not exist yet " +
            "or GitHub may be unavailable. $($_.Exception.Message)"
        )
    }

    if ($null -eq $release -or [string]::IsNullOrWhiteSpace($release.tag_name)) {
        throw "No public $Channel release was found"
    }
    $Version = $release.tag_name
} elseif (-not $Version.StartsWith("v")) {
    $Version = "v$Version"
}

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\CloakGPT"
}
$InstallDir = [IO.Path]::GetFullPath($InstallDir)

$downloadBase = "https://github.com/$repository/releases/download/$Version"

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
    $pathAdded = $false
    if ($InstallDir -notin $pathEntries) {
        $newUserPath = (($pathEntries + $InstallDir) -join ";")
        [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
        $pathAdded = $true
        Write-Host "Added $InstallDir to your user PATH."
    }

    Write-Host "Installed cloakgpt to $installedExecutable"
    Write-Host "Installing the external CloakBrowser binary..."
    $browserInstalled = $false
    try {
        & $installedExecutable browser install
        $browserInstalled = $LASTEXITCODE -eq 0
    } catch {
        $browserInstalled = $false
    }
    if (-not $browserInstalled) {
        Write-Warning "CloakBrowser installation failed; CloakGPT remains installed."
        $overrideNames = @(
            "CLOAKBROWSER_BINARY_PATH",
            "CLOAKBROWSER_CACHE_DIR",
            "CLOAKBROWSER_DOWNLOAD_URL",
            "CLOAKBROWSER_LICENSE_KEY",
            "CLOAKBROWSER_RELEASE_CHANNEL",
            "CLOAKBROWSER_VERSION"
        ) | Where-Object {
            -not [string]::IsNullOrWhiteSpace(
                [Environment]::GetEnvironmentVariable($_)
            )
        }
        if ($overrideNames.Count -gt 0) {
            Write-Warning (
                "Check the detected environment overrides: " +
                ($overrideNames -join ", ")
            )
        }
        Write-Host "Retry with: & `"$installedExecutable`" browser install"
    } else {
        Write-Host "CloakBrowser installed successfully."
    }

    $loginState = "NOT STARTED"
    if ($browserInstalled) {
        if ($interactive) {
            Write-Host ""
            Write-Host "CloakGPT and CloakBrowser are ready. Opening ChatGPT login..."
            try {
                & $installedExecutable login
                if ($LASTEXITCODE -eq 0) {
                    $loginState = "FLOW COMPLETED"
                } else {
                    $loginState = "INCOMPLETE"
                }
            } catch {
                $loginState = "INCOMPLETE"
            }
            if ($loginState -ne "FLOW COMPLETED") {
                Write-Warning (
                    "ChatGPT login did not complete; run it again from the " +
                    "MOTD command."
                )
            }
        } else {
            $loginState = "WAITING FOR INTERACTIVE TERMINAL"
        }
    } else {
        $loginState = "WAITING FOR CLOAKBROWSER"
    }

    $motdParameters = @{
        Executable = $installedExecutable
        BrowserInstalled = $browserInstalled
        LoginState = $loginState
        PathAdded = $pathAdded
        Release = "$Version ($asset)"
    }
    Write-InstallMotd @motdParameters
} finally {
    if (Test-Path -LiteralPath $tempDir) {
        Remove-Item -LiteralPath $tempDir -Recurse -Force
    }
}
