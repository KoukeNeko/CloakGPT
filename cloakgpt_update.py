"""Secure self-update support for packaged CloakGPT executables."""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import certifi

from cloakgpt_build import ASSET_NAME, CHANNEL, VERSION


REPOSITORY = "KoukeNeko/CloakGPT"
API_ROOT = f"https://api.github.com/repos/{REPOSITORY}/releases"
API_VERSION = "2022-11-28"
HEX_DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")
StatusCallback = Callable[[str], None]


def version_text() -> str:
    suffix = f" ({ASSET_NAME})" if ASSET_NAME else ""
    return f"cloakgpt {VERSION}{suffix}"


def _request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"CloakGPT/{VERSION}",
            "X-GitHub-Api-Version": API_VERSION,
        },
    )


def _ca_bundle() -> str:
    configured = os.environ.get("SSL_CERT_FILE")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_file():
            raise RuntimeError(
                f"SSL_CERT_FILE does not name a CA bundle file: {path}"
            )
        return str(path)
    return certifi.where()


def _tls_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=_ca_bundle())


def _open_url(url: str, *, timeout: int):
    return urlopen(_request(url), timeout=timeout, context=_tls_context())


def _read_json(url: str) -> Any:
    try:
        with _open_url(url, timeout=30) as response:
            return json.load(response)
    except Exception as error:
        raise RuntimeError(f"could not read GitHub release information: {error}") from error


def _release_for(*, channel: str | None, version: str | None) -> dict[str, Any]:
    if version:
        tag = version if version.startswith("v") else f"v{version}"
        release = _read_json(f"{API_ROOT}/tags/{quote(tag, safe='')}")
    elif channel == "stable":
        release = _read_json(f"{API_ROOT}/latest")
    else:
        releases = _read_json(f"{API_ROOT}?per_page=100")
        release = max(
            (
                item
                for item in releases
                if item.get("prerelease") and not item.get("draft")
            ),
            key=lambda item: str(
                item.get("published_at") or item.get("created_at") or ""
            ),
            default=None,
        )

    if not isinstance(release, dict) or not release.get("tag_name"):
        selected = version or channel
        raise RuntimeError(f"no public {selected} release was found")
    if release.get("draft"):
        raise RuntimeError("refusing to install a draft release")
    return release


def _asset(release: dict[str, Any], name: str) -> dict[str, Any]:
    for item in release.get("assets", []):
        if item.get("name") == name and item.get("browser_download_url"):
            return item
    raise RuntimeError(f"release {release['tag_name']} does not contain {name}")


def _download_file(url: str, destination: Path) -> None:
    try:
        with _open_url(url, timeout=60) as response:
            with destination.open("xb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
    except Exception as error:
        raise RuntimeError(f"download failed: {error}") from error


def _download_text(url: str) -> str:
    try:
        with _open_url(url, timeout=30) as response:
            data = response.read(4097)
    except Exception as error:
        raise RuntimeError(f"checksum download failed: {error}") from error
    if len(data) > 4096:
        raise RuntimeError("checksum file is unexpectedly large")
    return data.decode("ascii")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stage_release(release: dict[str, Any], target: Path) -> Path:
    executable_asset = _asset(release, ASSET_NAME)
    checksum_asset = _asset(release, f"{ASSET_NAME}.sha256")
    staged = target.with_name(f".{target.name}.update-{uuid.uuid4().hex}")
    _download_file(executable_asset["browser_download_url"], staged)
    try:
        checksum_parts = _download_text(checksum_asset["browser_download_url"]).split()
        if not checksum_parts:
            raise RuntimeError("release checksum is empty")
        expected = checksum_parts[0]
        if not HEX_DIGEST.fullmatch(expected):
            raise RuntimeError("release checksum is invalid")
        actual = _sha256(staged)
        if actual.lower() != expected.lower():
            raise RuntimeError("SHA-256 checksum mismatch")

        api_digest = executable_asset.get("digest")
        if api_digest:
            algorithm, separator, value = str(api_digest).partition(":")
            if separator != ":" or algorithm.lower() != "sha256":
                raise RuntimeError("GitHub returned an unsupported asset digest")
            if actual.lower() != value.lower():
                raise RuntimeError("GitHub asset digest mismatch")

        mode = target.stat().st_mode
        staged.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    if getattr(sys, "frozen", False):
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return environment


def _smoke_test(staged: Path, version: str) -> None:
    options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": _child_environment(),
        "timeout": 60,
    }
    version_check = subprocess.run([str(staged), "--version"], **options)
    if version_check.returncode or version not in version_check.stdout:
        raise RuntimeError("downloaded executable failed its version check")
    driver_check = subprocess.run([str(staged), "_playwright_check"], **options)
    if driver_check.returncode:
        raise RuntimeError("downloaded executable failed its Playwright smoke test")


def _replace_posix(staged: Path, target: Path, version: str) -> None:
    backup = target.with_name(f".{target.name}.backup-{uuid.uuid4().hex}")
    os.replace(target, backup)
    try:
        os.replace(staged, target)
        check = subprocess.run(
            [str(target), "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_child_environment(),
            timeout=60,
        )
        if check.returncode or version not in check.stdout:
            raise RuntimeError("updated executable failed its final version check")
    except Exception:
        target.unlink(missing_ok=True)
        os.replace(backup, target)
        raise
    backup.unlink()


WINDOWS_HELPER = r'''param(
    [int]$ParentPid,
    [string]$Target,
    [string]$Staged,
    [string]$Backup,
    [string]$ResultPath,
    [string]$ExpectedVersion
)
$ErrorActionPreference = "Stop"
Wait-Process -Id $ParentPid -ErrorAction SilentlyContinue
$result = $null
try {
    $moved = $false
    for ($attempt = 0; $attempt -lt 100 -and -not $moved; $attempt++) {
        try {
            Move-Item -LiteralPath $Target -Destination $Backup -Force
            $moved = $true
        } catch {
            Start-Sleep -Milliseconds 100
        }
    }
    if (-not $moved) { throw "The existing executable remained locked." }
    Move-Item -LiteralPath $Staged -Destination $Target -Force
    $versionOutput = (& $Target --version 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0 -or -not $versionOutput.Contains($ExpectedVersion)) {
        throw "The updated executable failed its final version check."
    }
    Remove-Item -LiteralPath $Backup -Force
    $result = @{ status = "updated"; version = $ExpectedVersion }
} catch {
    if (Test-Path -LiteralPath $Backup) {
        if (Test-Path -LiteralPath $Target) {
            Remove-Item -LiteralPath $Target -Force
        }
        Move-Item -LiteralPath $Backup -Destination $Target -Force
    }
    $result = @{ status = "failed"; error = $_.Exception.Message }
} finally {
    if (Test-Path -LiteralPath $Staged) {
        Remove-Item -LiteralPath $Staged -Force
    }
    $json = $result | ConvertTo-Json -Compress
    [IO.File]::WriteAllText(
        $ResultPath,
        $json,
        (New-Object Text.UTF8Encoding($false))
    )
    Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
}
'''


def _schedule_windows_replace(staged: Path, target: Path, version: str) -> None:
    token = uuid.uuid4().hex
    helper = target.with_name(f".{target.name}.update-{token}.ps1")
    backup = target.with_name(f".{target.name}.backup-{token}")
    result_path = target.with_name(".cloakgpt-update-result.json")
    log_path = target.with_name(".cloakgpt-update.log")
    helper.write_text(WINDOWS_HELPER, encoding="utf-8")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(helper),
        "-ParentPid",
        str(os.getpid()),
        "-Target",
        str(target),
        "-Staged",
        str(staged),
        "-Backup",
        str(backup),
        "-ResultPath",
        str(result_path),
        "-ExpectedVersion",
        version,
    ]
    try:
        with log_path.open("ab") as log:
            subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                env=_child_environment(),
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                ),
            )
    except Exception:
        helper.unlink(missing_ok=True)
        raise


def consume_windows_update_result(executable: Path | None = None) -> dict | None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return None
    target = executable or Path(sys.executable)
    result_path = target.with_name(".cloakgpt-update-result.json")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        result_path.unlink(missing_ok=True)
        return None
    result_path.unlink(missing_ok=True)
    return result if isinstance(result, dict) else None


def update_cloakgpt(
    *,
    channel: str | None = None,
    version: str | None = None,
    check: bool = False,
    status_callback: StatusCallback | None = None,
    stop_daemon: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if not getattr(sys, "frozen", False) or not ASSET_NAME:
        raise RuntimeError(
            "self-update is available only in packaged releases; update this "
            "source checkout with git instead"
        )
    selected_channel = channel or (CHANNEL if CHANNEL in {"stable", "prerelease"} else None)
    if version is None and selected_channel is None:
        raise RuntimeError("choose --channel stable or --channel prerelease")

    release = _release_for(channel=selected_channel, version=version)
    target_version = str(release["tag_name"])
    result: dict[str, Any] = {
        "current": VERSION,
        "target": target_version,
        "channel": selected_channel,
        "asset": ASSET_NAME,
    }
    if target_version == VERSION:
        result["status"] = "up_to_date"
        return result
    if check:
        result["status"] = "update_available"
        return result

    status = status_callback or (lambda _message: None)
    target = Path(sys.executable).resolve()
    status(f"Downloading {ASSET_NAME} ({target_version})...")
    staged = _stage_release(release, target)
    scheduled = False
    try:
        status("SHA-256 verified; testing the downloaded executable...")
        _smoke_test(staged, target_version)
        if stop_daemon is not None:
            status("Stopping the CloakGPT daemon...")
            stop_daemon()
        if os.name == "nt":
            _schedule_windows_replace(staged, target, target_version)
            scheduled = True
            result["status"] = "staged"
        else:
            _replace_posix(staged, target, target_version)
            result["status"] = "updated"
        return result
    finally:
        if not scheduled:
            staged.unlink(missing_ok=True)
