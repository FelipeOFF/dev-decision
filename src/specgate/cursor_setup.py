"""Selective installation and diagnostics for the controlled Cursor ACP client."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, TypedDict

from specgate.codex_setup import _files, _manifest, _owned_and_unchanged, _validate_url
from specgate.cursor_client import CursorControlledClient
from specgate.mcp_catalog import merge_json_mcp, remove_json_mcp
from specgate.product import (
    CURSOR_MARKER,
    CURSOR_MARKERS,
    CURSOR_OWNER,
    CURSOR_OWNERS,
    SKILL,
    SKILL_NAMES,
    TOKEN_ENV,
)
from specgate.transport import list_tools

_SKILL = SKILL
_MARKER = CURSOR_MARKER
_OWNER = CURSOR_OWNER
_TOKEN_ENV = TOKEN_ENV
_REQUIRED_TOOLS = {"jev_decide", "jev_find", "jev_screen", "jev_verify"}


class CursorSetupReport(TypedDict):
    skill: Literal["created", "unchanged", "removed", "preserved", "absent"]
    mcp: Literal["created", "unchanged", "updated", "removed", "preserved", "absent"]


def _run(command: Sequence[str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*command, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _skill_dir(skill_root: Path) -> Path:
    root = skill_root.expanduser().resolve()
    current = root / _SKILL
    if current.exists():
        return current
    for name in SKILL_NAMES:
        candidate = root / name
        if candidate.exists():
            return candidate
    return current


def _mcp_path(skill_root: Path) -> Path:
    return skill_root.expanduser().resolve().parent / "mcp.json"


def _write_marker(path: Path, manifest: dict[str, object]) -> None:
    (path / _MARKER).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    for name in CURSOR_MARKERS:
        if name == _MARKER:
            continue
        (path / name).unlink(missing_ok=True)


def install_cursor(
    source: Path, skill_root: Path, url: str, *, token: str | None = None
) -> CursorSetupReport:
    """Install the managed skill and a native Cursor MCP catalog entry."""
    _validate_url(url)
    source = source.resolve()
    root = skill_root.expanduser().resolve()
    target = root / _SKILL
    existing = _skill_dir(skill_root)
    if not (source / "SKILL.md").is_file():
        raise ValueError("The Specgate skill must contain SKILL.md.")
    previous = _manifest(existing, CURSOR_MARKERS) if existing.exists() else None
    if existing.exists() and (
        previous is None
        or not _owned_and_unchanged(
            existing, previous, owners=CURSOR_OWNERS, markers=CURSOR_MARKERS
        )
    ):
        raise ValueError("The destination skill exists and is not plugin-managed.")
    mcp_status = merge_json_mcp(
        _mcp_path(skill_root), url, include_type=False, token=token
    )
    previous_mcp = (previous or {}).get("mcp")
    source_files = _files(source, CURSOR_MARKERS)
    manifest = {
        "version": 1,
        "owner": _OWNER,
        "files": source_files,
        "mcp": {
            "name": "specgate",
            "url": url,
            "created": mcp_status == "created"
            or (isinstance(previous_mcp, dict) and previous_mcp.get("created")),
        },
    }
    try:
        if (
            previous is not None
            and previous.get("files") == source_files
            and existing == target
        ):
            _write_marker(target, manifest)
            return {"skill": "unchanged", "mcp": mcp_status}
        skill_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{_SKILL}.", dir=skill_root))
        staging.rmdir()
        shutil.copytree(source, staging)
        _write_marker(staging, manifest)
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
        if existing != target and existing.exists():
            shutil.rmtree(existing)
    except Exception:
        if mcp_status == "created":
            remove_json_mcp(
                _mcp_path(skill_root), url, created=True, include_type=False
            )
        raise
    return {"skill": "created", "mcp": mcp_status}


async def diagnose_cursor(
    skill_root: Path,
    url: str,
    token: str,
    *,
    cursor_command: Sequence[str] | None = None,
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    """Verify the explicit Cursor binary, ACP v1 handshake, skill and MCP tools."""
    target = _skill_dir(skill_root)
    manifest = _manifest(target, CURSOR_MARKERS) if target.exists() else None
    if manifest is None or not _owned_and_unchanged(
        target, manifest, owners=CURSOR_OWNERS, markers=CURSOR_MARKERS
    ):
        raise ValueError("The managed Specgate skill is missing or modified.")
    command = (
        tuple(cursor_command)
        if cursor_command is not None
        else (str(Path.home() / ".local/bin/cursor-agent"),)
    )
    if len(command) == 1 and Path(command[0]).name != "cursor-agent":
        raise ValueError(
            "Use the explicit cursor-agent executable, not agent from PATH."
        )
    version = _run(command, "--version")
    if version.returncode or not version.stdout.strip():
        raise ValueError("The explicit cursor-agent runtime is unavailable.")

    async def unused_decision(_: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Diagnostics must not start an inference turn.")

    try:
        async with CursorControlledClient(
            decide=unused_decision,
            command=(*command, "acp"),
            timeout_seconds=timeout_seconds,
            authenticate=False,
        ) as client:
            acp: dict[str, Any] = dict(client.diagnostic)
    except RuntimeError as error:
        acp = {"usable": False, "error": str(error)}
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
            "catalog": str(_mcp_path(skill_root)),
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
    """Remove only an unchanged skill and Specgate-owned MCP catalog entry."""
    target = _skill_dir(skill_root)
    manifest = _manifest(target, CURSOR_MARKERS) if target.exists() else None
    if manifest is None:
        return {
            "skill": "preserved" if target.exists() else "absent",
            "mcp": "absent",
        }
    mcp = manifest.get("mcp")
    mcp_status = remove_json_mcp(
        _mcp_path(skill_root),
        str(mcp.get("url", "")) if isinstance(mcp, dict) else "",
        created=isinstance(mcp, dict) and mcp.get("created") is True,
        include_type=False,
    )
    if not _owned_and_unchanged(
        target, manifest, owners=CURSOR_OWNERS, markers=CURSOR_MARKERS
    ):
        return {"skill": "preserved", "mcp": mcp_status}
    shutil.rmtree(target)
    return {"skill": "removed", "mcp": mcp_status}
