"""Idempotent Codex-only installation owned by Dev Decision."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, TypedDict
from urllib.parse import urlsplit

from dev_decision.codex_client import CodexControlledClient
from dev_decision.transport import list_tools

_NAME = "dev_decision"
_SKILL = "dev-decision"
_MARKER = ".dev-decision-install.json"
_TOKEN_ENV = "DEV_DECISION_MCP_API_KEY"
_REQUIRED_TOOLS = {"jev_decide", "jev_find", "jev_screen", "jev_verify"}


class SetupReport(TypedDict):
    skill: Literal["created", "unchanged", "removed", "preserved", "absent"]
    mcp: Literal["created", "unchanged", "removed", "preserved", "absent"]


def _run(command: Sequence[str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*command, *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _mcp_config(command: Sequence[str]) -> dict[str, object] | None:
    result = _run(command, "mcp", "get", _NAME, "--json")
    if result.returncode:
        if "No MCP server named" in result.stderr:
            return None
        raise ValueError("Codex could not inspect the Dev Decision MCP configuration.")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("Codex returned an invalid MCP configuration.") from error
    if not isinstance(value, dict):
        raise TypeError("Codex returned an invalid MCP configuration.")
    return value


def _mcp_matches(config: dict[str, object], url: str) -> bool:
    transport = config.get("transport", config)
    return bool(
        isinstance(transport, dict)
        and transport.get("url") == url
        and transport.get("bearer_token_env_var") == _TOKEN_ENV
    )


def _mcp_usable(config: dict[str, object], url: str) -> bool:
    disabled = config.get("disabled_tools", [])
    enabled = config.get("enabled_tools")
    return bool(
        _mcp_matches(config, url)
        and config.get("enabled", True) is True
        and isinstance(disabled, list)
        and not (_REQUIRED_TOOLS & set(disabled))
        and (
            enabled is None
            or (isinstance(enabled, list) and _REQUIRED_TOOLS <= set(enabled))
        )
    )


def _validate_url(url: str) -> None:
    endpoint = urlsplit(url)
    try:
        loopback = ipaddress.ip_address(endpoint.hostname or "").is_loopback
    except ValueError:
        loopback = endpoint.hostname == "localhost"
    if (
        endpoint.scheme not in {"http", "https"}
        or (endpoint.scheme == "http" and not loopback)
        or not endpoint.hostname
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.query
        or endpoint.fragment
        or any(character.isspace() or ord(character) < 32 for character in url)
    ):
        raise ValueError(
            "Use an explicit HTTPS URL or loopback HTTP URL without credentials."
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
        manifest.get("owner") == _NAME
        and isinstance(manifest.get("files"), dict)
        and _files(path) == manifest["files"]
    )


def install_codex(
    source: Path,
    skill_root: Path,
    url: str,
    *,
    codex_command: Sequence[str] = ("codex",),
) -> SetupReport:
    """Install the managed skill and native Codex MCP entry without secrets."""
    _validate_url(url)
    source = source.resolve()
    target = skill_root.expanduser().resolve() / _SKILL
    if not (source / "SKILL.md").is_file():
        raise ValueError("The Dev Decision skill must contain SKILL.md.")
    previous = _manifest(target) if target.exists() else None
    if target.exists() and (
        previous is None or not _owned_and_unchanged(target, previous)
    ):
        raise ValueError("The destination skill exists and is not plugin-managed.")

    config = _mcp_config(codex_command)
    if config is not None and not _mcp_matches(config, url):
        raise ValueError(
            "The dev_decision MCP entry already has another configuration."
        )
    mcp_created = config is None
    if mcp_created:
        added = _run(
            codex_command,
            "mcp",
            "add",
            _NAME,
            "--url",
            url,
            "--bearer-token-env-var",
            _TOKEN_ENV,
        )
        if added.returncode:
            raise ValueError("Codex could not register the Dev Decision MCP.")

    try:
        source_files = _files(source)
        previous_mcp = (previous or {}).get("mcp")
        manifest = {
            "version": 1,
            "owner": _NAME,
            "files": source_files,
            "mcp": {
                "name": _NAME,
                "url": url,
                "bearer_token_env_var": _TOKEN_ENV,
                "created": bool(
                    mcp_created
                    or (isinstance(previous_mcp, dict) and previous_mcp.get("created"))
                ),
            },
        }
        skill_status: Literal["created", "unchanged"]
        if previous is not None and previous.get("files") == source_files:
            (target / _MARKER).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
            )
            skill_status = "unchanged"
        else:
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
            skill_status = "created"
    except Exception as error:
        if mcp_created:
            rollback = _run(codex_command, "mcp", "remove", _NAME)
            if rollback.returncode:
                raise ExceptionGroup(
                    "Codex installation and MCP rollback failed.",
                    [
                        error,
                        RuntimeError(rollback.stderr.strip() or "MCP rollback failed."),
                    ],
                )
        raise
    return {
        "skill": skill_status,
        "mcp": "created" if mcp_created else "unchanged",
    }


async def diagnose_codex(
    project: Path,
    skill_root: Path,
    url: str,
    token: str,
    *,
    codex_command: Sequence[str] = ("codex",),
    timeout_seconds: float = 30,
) -> dict[str, Any]:
    """Verify the installed skill, native config, app-server and MCP catalog."""
    target = skill_root.expanduser().resolve() / _SKILL
    manifest = _manifest(target) if target.exists() else None
    if manifest is None or not _owned_and_unchanged(target, manifest):
        raise ValueError("The managed Dev Decision skill is missing or modified.")
    config = _mcp_config(codex_command)
    if config is None or not _mcp_usable(config, url):
        raise ValueError("The managed Dev Decision MCP configuration is unavailable.")
    version = _run(codex_command, "--version")
    if version.returncode or not version.stdout.strip():
        raise ValueError("The Codex runtime is unavailable.")

    async def unused_decision(_: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Diagnostics must not delegate the question.")

    command = (
        *codex_command,
        "-c",
        "features.default_mode_request_user_input=true",
        "app-server",
        "--stdio",
    )
    async with CodexControlledClient(
        decide=unused_decision,
        command=command,
        timeout_seconds=timeout_seconds,
    ) as client:
        skills = await client.list_skills(project)
        expected_path = str((target / "SKILL.md").resolve())
        loaded = [
            skill
            for skill in skills
            if skill.name == _SKILL and str(Path(skill.path).resolve()) == expected_path
        ]
        if len(loaded) != 1:
            raise ValueError(
                "The app-server did not load the managed skill exactly once."
            )
        app_server = dict(client.diagnostic)
        app_server["skills_list"] = "verified"
        app_server["model_turn"] = "not_started"

    tools = await list_tools(url, token, timeout_seconds=timeout_seconds)
    if not _REQUIRED_TOOLS <= set(tools):
        raise ValueError("The MCP server does not expose all required decision tools.")
    return {
        "usable": True,
        "runtime": version.stdout.strip(),
        "skill": {"name": _SKILL, "loaded": True, "path": expected_path},
        "mcp": {
            "url": url,
            "authentication": f"bearer_env:{_TOKEN_ENV}",
            "transport": "streamable_http_sse",
            "tools": sorted(tools),
        },
        "app_server": app_server,
        "scope": "controlled_app_server",
        "limitations": [
            "Controls only turns started by this Python app-server client.",
            "Does not intercept desktop prompts or free-form questions universally.",
        ],
    }


def uninstall_codex(
    skill_root: Path,
    *,
    codex_command: Sequence[str] = ("codex",),
) -> SetupReport:
    """Remove only unchanged entries previously created by this installer."""
    target = skill_root.expanduser().resolve() / _SKILL
    manifest = _manifest(target) if target.exists() else None
    skill_status: Literal["removed", "preserved", "absent"] = "absent"
    mcp_status: Literal["removed", "preserved", "absent"] = "absent"
    if manifest is None:
        if target.exists():
            skill_status = "preserved"
        return {"skill": skill_status, "mcp": mcp_status}

    mcp = manifest.get("mcp")
    config = _mcp_config(codex_command)
    if isinstance(mcp, dict) and mcp.get("created") is True:
        if config is None:
            mcp_status = "absent"
        elif _mcp_matches(config, str(mcp.get("url", ""))):
            removed = _run(codex_command, "mcp", "remove", _NAME)
            if removed.returncode:
                raise ValueError("Codex could not remove the Dev Decision MCP.")
            mcp_status = "removed"
        else:
            mcp_status = "preserved"
    elif config is not None:
        mcp_status = "preserved"

    if _owned_and_unchanged(target, manifest):
        shutil.rmtree(target)
        skill_status = "removed"
    else:
        skill_status = "preserved"
    return {"skill": skill_status, "mcp": mcp_status}
