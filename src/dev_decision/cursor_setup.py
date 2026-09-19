"""Selective installation and diagnostics for the controlled Cursor ACP client."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, TypedDict

from dev_decision.cursor_client import CursorControlledClient
from dev_decision.transport import list_tools

_SKILL = "dev-decision"
_MARKER = ".dev-decision-cursor.json"
_OWNER = "dev_decision_cursor"
_TOKEN_ENV = "DEV_DECISION_MCP_API_KEY"
_REQUIRED_TOOLS = {"jev_decide", "jev_find", "jev_screen", "jev_verify"}


class CursorSetupReport(TypedDict):
    skill: Literal["created", "unchanged", "removed", "preserved", "absent"]


def _run(command: Sequence[str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*command, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _files(path: Path) -> dict[str, str]:
    return {
        file.relative_to(path).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(path.rglob("*"))
        if file.is_file() and file.name != _MARKER
    }


def _manifest(path: Path) -> dict[str, object] | None:
    marker = path / _MARKER
    if not marker.is_file():
        return None
    try:
        value = json.loads(marker.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _owned_and_unchanged(path: Path, manifest: dict[str, object]) -> bool:
    return (
        manifest.get("owner") == _OWNER
        and isinstance(manifest.get("files"), dict)
        and _files(path) == manifest["files"]
    )


def install_cursor(source: Path, skill_root: Path) -> CursorSetupReport:
    """Install only the managed skill; the client owns MCP transport at runtime."""
    source = source.resolve()
    target = skill_root.expanduser().resolve() / _SKILL
    if not (source / "SKILL.md").is_file():
        raise ValueError("The Dev Decision skill must contain SKILL.md.")
    previous = _manifest(target) if target.exists() else None
    if target.exists() and (
        previous is None or not _owned_and_unchanged(target, previous)
    ):
        raise ValueError("The destination skill exists and is not plugin-managed.")
    source_files = _files(source)
    manifest = {"version": 1, "owner": _OWNER, "files": source_files}
    if previous is not None and previous.get("files") == source_files:
        (target / _MARKER).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        return {"skill": "unchanged"}
    skill_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{_SKILL}.", dir=skill_root))
    staging.rmdir()
    shutil.copytree(source, staging)
    (staging / _MARKER).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    return {"skill": "created"}


async def diagnose_cursor(
    skill_root: Path,
    url: str,
    token: str,
    *,
    cursor_command: Sequence[str] | None = None,
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    """Verify the explicit Cursor binary, ACP v1 handshake, skill and MCP tools."""
    target = skill_root.expanduser().resolve() / _SKILL
    manifest = _manifest(target) if target.exists() else None
    if manifest is None or not _owned_and_unchanged(target, manifest):
        raise ValueError("The managed Dev Decision skill is missing or modified.")
    command = tuple(cursor_command) if cursor_command is not None else (
        str(Path.home() / ".local/bin/cursor-agent"),
    )
    if len(command) == 1 and Path(command[0]).name != "cursor-agent":
        raise ValueError("Use the explicit cursor-agent executable, not agent from PATH.")
    version = _run(command, "--version")
    if version.returncode or not version.stdout.strip():
        raise ValueError("The explicit cursor-agent runtime is unavailable.")

    async def unused_decision(_: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Diagnostics must not start an inference turn.")

    async with CursorControlledClient(
        decide=unused_decision,
        command=(*command, "acp"),
        timeout_seconds=timeout_seconds,
        authenticate=False,
    ) as client:
        acp = dict(client.diagnostic)
    tools = await list_tools(url, token, timeout_seconds=timeout_seconds)
    if not _REQUIRED_TOOLS <= set(tools):
        raise ValueError("The MCP server does not expose all required decision tools.")
    return {
        "usable": True,
        "runtime": f"cursor-agent {version.stdout.strip()}",
        "skill": {
            "name": _SKILL,
            "loaded_by": "controlled_prompt",
            "path": str((target / "SKILL.md").resolve()),
        },
        "mcp": {
            "url": url,
            "authentication": f"bearer_env:{_TOKEN_ENV}",
            "transport": "streamable_http_sse",
            "tools": sorted(tools),
        },
        "acp": acp,
        "scope": "controlled_cursor_acp",
        "limitations": [
            "The installed runtime was validated through ACP v1 initialize only.",
            "The controlled client requires an existing cursor-agent login.",
            "cursor/ask_question was validated with a local protocol double, without inference.",
            "Hooks do not answer native questions; start the turn through this Python client.",
            "Permissions, plans, multiple questions and multi-select answers require human review.",
        ],
    }


def uninstall_cursor(skill_root: Path) -> CursorSetupReport:
    """Remove only an unchanged skill created by this installer."""
    target = skill_root.expanduser().resolve() / _SKILL
    manifest = _manifest(target) if target.exists() else None
    if manifest is None:
        return {"skill": "preserved" if target.exists() else "absent"}
    if not _owned_and_unchanged(target, manifest):
        return {"skill": "preserved"}
    shutil.rmtree(target)
    return {"skill": "removed"}
