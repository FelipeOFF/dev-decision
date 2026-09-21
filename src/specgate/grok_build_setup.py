"""Selective installation and diagnostics for the Grok Build ACP client."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, TypedDict

from specgate.codex_setup import _files, _manifest, _owned_and_unchanged, _validate_url
from specgate.grok_build_client import GrokBuildControlledClient
from specgate.mcp_catalog import (
    merge_grok_config,
    merge_json_mcp,
    remove_grok_config,
    remove_json_mcp,
)
from specgate.product import (
    GROK_BUILD_MARKER,
    GROK_BUILD_MARKERS,
    GROK_BUILD_OWNER,
    GROK_BUILD_OWNERS,
    SKILL,
    SKILL_NAMES,
    TOKEN_ENV,
)
from specgate.transport import list_tools

_SKILL = SKILL
_MARKER = GROK_BUILD_MARKER
_OWNER = GROK_BUILD_OWNER
_TOKEN_ENV = TOKEN_ENV
_REQUIRED_TOOLS = {"jev_decide", "jev_find", "jev_screen", "jev_verify"}


class GrokBuildSetupReport(TypedDict):
    skill: Literal["created", "unchanged", "removed", "preserved", "absent"]
    mcp: Literal["created", "unchanged", "removed", "preserved", "absent"]


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


def _catalog_root(skill_root: Path) -> Path:
    return skill_root.expanduser().resolve().parent


def _write_marker(path: Path, manifest: dict[str, object]) -> None:
    (path / _MARKER).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    for name in GROK_BUILD_MARKERS:
        if name == _MARKER:
            continue
        (path / name).unlink(missing_ok=True)


def _install_native_mcp(skill_root: Path, url: str) -> Literal["created", "unchanged"]:
    root = _catalog_root(skill_root)
    status = merge_grok_config(root / "config.toml", url)
    created = status == "created"
    mcp_json = root / "mcp.json"
    if mcp_json.is_file() and merge_json_mcp(mcp_json, url, include_type=False) == "created":
        created = True
    return "created" if created else "unchanged"


def _remove_native_mcp(
    skill_root: Path, url: str, *, created: bool
) -> Literal["created", "unchanged", "removed", "preserved", "absent"]:
    root = _catalog_root(skill_root)
    toml_status = remove_grok_config(root / "config.toml", url, created=created)
    mcp_json = root / "mcp.json"
    json_status: Literal["created", "unchanged", "removed", "preserved", "absent"] = (
        "absent"
    )
    if mcp_json.is_file():
        json_status = remove_json_mcp(
            mcp_json, url, created=created, include_type=False
        )
    for status in (toml_status, json_status):
        if status == "preserved":
            return "preserved"
    if "removed" in {toml_status, json_status}:
        return "removed"
    if toml_status == "absent" and json_status == "absent":
        return "absent"
    return toml_status


def install_grok_build(source: Path, skill_root: Path, url: str) -> GrokBuildSetupReport:
    """Install the managed skill and native Grok MCP catalog entry."""
    _validate_url(url)
    source = source.resolve()
    root = skill_root.expanduser().resolve()
    target = root / _SKILL
    existing = _skill_dir(skill_root)
    if not (source / "SKILL.md").is_file():
        raise ValueError("The Specgate skill must contain SKILL.md.")
    previous = (
        _manifest(existing, GROK_BUILD_MARKERS) if existing.exists() else None
    )
    if existing.exists() and (
        previous is None
        or not _owned_and_unchanged(
            existing,
            previous,
            owners=GROK_BUILD_OWNERS,
            markers=GROK_BUILD_MARKERS,
        )
    ):
        raise ValueError("The destination skill exists and is not plugin-managed.")
    mcp_status = _install_native_mcp(skill_root, url)
    previous_mcp = (previous or {}).get("mcp")
    source_files = _files(source, GROK_BUILD_MARKERS)
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
            _remove_native_mcp(skill_root, url, created=True)
        raise
    return {"skill": "created", "mcp": mcp_status}


async def diagnose_grok_build(
    skill_root: Path,
    url: str,
    token: str,
    *,
    grok_command: Sequence[str] = ("grok",),
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    """Verify the Grok runtime, ACP v1 handshake, skill and MCP tools."""
    target = _skill_dir(skill_root)
    manifest = _manifest(target, GROK_BUILD_MARKERS) if target.exists() else None
    if manifest is None or not _owned_and_unchanged(
        target, manifest, owners=GROK_BUILD_OWNERS, markers=GROK_BUILD_MARKERS
    ):
        raise ValueError("The managed Specgate skill is missing or modified.")
    command = tuple(grok_command)
    version = _run(command, "--version")
    if version.returncode or not version.stdout.strip():
        raise ValueError("The Grok Build runtime is unavailable.")

    async def unused_decision(_: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Diagnostics must not start an inference turn.")

    async with GrokBuildControlledClient(
        decide=unused_decision,
        command=(*command, "agent", "stdio"),
        timeout_seconds=timeout_seconds,
        authenticate=False,
    ) as client:
        acp = dict(client.diagnostic)
    tools = await list_tools(url, token, timeout_seconds=timeout_seconds)
    if not _REQUIRED_TOOLS <= set(tools):
        raise ValueError("The MCP server does not expose all required decision tools.")
    return {
        "usable": True,
        "runtime": version.stdout.strip(),
        "skill": {
            "name": _SKILL,
            "loaded_by": "controlled_prompt",
            "path": str((target / "SKILL.md").resolve()),
        },
        "mcp": {
            "url": url,
            "authentication": f"bearer_env:{_TOKEN_ENV}",
            "transport": "streamable_http_sse",
            "catalog": str(_catalog_root(skill_root) / "config.toml"),
            "tools": sorted(tools),
        },
        "acp": acp,
        "scope": "controlled_grok_build_acp",
        "limitations": [
            "The installed runtime was validated through ACP v1 initialize only.",
            "The controlled client requires an existing Grok Build login.",
            "x.ai/ask_user_question used the official 1.0.24 contract with a local protocol double.",
            "Hooks do not answer native questions; start the turn through this Python client.",
            "Permissions, plans, multiple questions and multi-select answers require human review.",
            "The wrapper still injects SPECGATE_MCP_API_KEY when config.toml is absent.",
        ],
    }


def uninstall_grok_build(skill_root: Path) -> GrokBuildSetupReport:
    """Remove only an unchanged skill and Specgate-owned MCP catalog entry."""
    target = _skill_dir(skill_root)
    manifest = _manifest(target, GROK_BUILD_MARKERS) if target.exists() else None
    if manifest is None:
        return {
            "skill": "preserved" if target.exists() else "absent",
            "mcp": "absent",
        }
    mcp = manifest.get("mcp")
    mcp_status = _remove_native_mcp(
        skill_root,
        str(mcp.get("url", "")) if isinstance(mcp, dict) else "",
        created=isinstance(mcp, dict) and mcp.get("created") is True,
    )
    if not _owned_and_unchanged(
        target, manifest, owners=GROK_BUILD_OWNERS, markers=GROK_BUILD_MARKERS
    ):
        return {"skill": "preserved", "mcp": mcp_status}
    shutil.rmtree(target)
    return {"skill": "removed", "mcp": mcp_status}
