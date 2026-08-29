"""Report whether the installed use-cloakgpt Agent Skill matches this build."""

import os
import subprocess
import sys
from pathlib import Path

SKILL_NAME = "use-cloakgpt"
SKILL_SOURCE_URL = (
    "https://github.com/KoukeNeko/CloakGPT/tree/main/skills/use-cloakgpt"
)
SKILL_INSTALL_COMMAND = ("npx", "-y", "skills", "add", SKILL_SOURCE_URL, "-g")
SKILL_FILE_NAME = "SKILL.md"

# The same user-level destinations the official uninstaller knows about.
AGENT_SKILL_DIRECTORIES = (
    ".aider-desk/skills",
    ".agents/skills",
    ".claude/skills",
    ".config/agents/skills",
    ".gemini/skills",
    ".openclaw/skills",
)
CODEX_HOME_ENV_VAR = "CODEX_HOME"
CODEX_DEFAULT_HOME = ".codex"


def _home_dir() -> Path:
    return Path.home()


def _bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).parent


def bundled_skill_text() -> str | None:
    """Return the skill this build ships, or None when it is unavailable."""
    path = _bundle_dir() / "skills" / SKILL_NAME / SKILL_FILE_NAME
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _candidate_skill_paths() -> list[Path]:
    home = _home_dir()
    candidates = [
        home / directory / SKILL_NAME / SKILL_FILE_NAME
        for directory in AGENT_SKILL_DIRECTORIES
    ]
    codex_home = os.environ.get(CODEX_HOME_ENV_VAR)
    codex_root = Path(codex_home) if codex_home else home / CODEX_DEFAULT_HOME
    candidates.append(codex_root / "skills" / SKILL_NAME / SKILL_FILE_NAME)
    return candidates


def outdated_skill_paths(bundled_text: str | None) -> list[Path]:
    """Return installed copies whose content differs from this build's skill."""
    if bundled_text is None:
        return []
    outdated = []
    for path in _candidate_skill_paths():
        try:
            installed = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if installed != bundled_text:
            outdated.append(path)
    return outdated


def install_command_text() -> str:
    return " ".join(SKILL_INSTALL_COMMAND)


def refresh_skill() -> bool:
    """Re-install through the official skills CLI, which owns its bookkeeping."""
    try:
        completed = subprocess.run(SKILL_INSTALL_COMMAND, check=False)
    except OSError:
        return False
    return completed.returncode == 0
