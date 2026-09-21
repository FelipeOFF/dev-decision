"""Merge and remove native MCP catalog entries without wiping foreign servers."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

from specgate.product import LEGACY_MCP_SERVER, MCP_SERVER, TOKEN_ENV

McpStatus = Literal["created", "unchanged", "updated", "removed", "preserved", "absent"]
_GROK_TABLE = f"mcp_servers.{MCP_SERVER}"
_GROK_LEGACY_TABLE = f"mcp_servers.{LEGACY_MCP_SERVER}"


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def http_headers(
    token_env: str = TOKEN_ENV, *, token: str | None = None
) -> dict[str, str]:
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {"Authorization": f"Bearer ${{{token_env}}}"}


def json_http_server(
    url: str, *, include_type: bool = True, token: str | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {"url": url, "headers": http_headers(token=token)}
    if include_type:
        return {"type": "http", **entry}
    return entry


def _authorization(existing: object) -> str:
    if not isinstance(existing, dict):
        return ""
    headers = existing.get("headers")
    if not isinstance(headers, dict):
        return ""
    for key, value in headers.items():
        if key.lower() == "authorization" and isinstance(value, str):
            return value
    return ""


def specgate_http_owned(existing: object, url: str) -> bool:
    if not isinstance(existing, dict):
        return False
    if existing.get("url") != url:
        return False
    return _authorization(existing).startswith("Bearer ")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path.name} is not valid JSON.") from error
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} is not a JSON object.")
    return value


def entry_matches(existing: object, entry: dict[str, Any]) -> bool:
    if not isinstance(existing, dict):
        return False
    return existing.get("url") == entry.get("url") and existing.get(
        "headers"
    ) == entry.get("headers")


def merge_json_mcp(
    path: Path,
    url: str,
    *,
    include_type: bool = True,
    name: str = MCP_SERVER,
    token: str | None = None,
) -> McpStatus:
    """Insert or confirm a Specgate HTTP server in an mcpServers JSON catalog."""
    entry = json_http_server(url, include_type=include_type, token=token)
    data = _read_json_object(path)
    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
        data["mcpServers"] = servers
    elif not isinstance(servers, dict):
        raise ValueError("MCP catalog mcpServers is invalid.")
    existing = servers.get(name)
    if (
        existing is not None
        and not specgate_http_owned(existing, url)
        and (existing.get("url") != url or not entry_matches(existing, entry))
    ):
        raise ValueError("The specgate MCP entry already has another configuration.")
    if entry_matches(existing, entry):
        return "unchanged"
    had_owned = existing is not None and specgate_http_owned(existing, url)
    servers[name] = entry
    _write_json(path, data)
    return "updated" if had_owned else "created"


def remove_json_mcp(
    path: Path,
    url: str,
    *,
    created: bool,
    include_type: bool = True,
    name: str = MCP_SERVER,
    token: str | None = None,
) -> McpStatus:
    """Remove only a Specgate entry this installer previously created."""
    names = (name, LEGACY_MCP_SERVER) if name == MCP_SERVER else (name,)
    if not path.exists():
        return "absent"
    data = _read_json_object(path)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return "absent"
    target = next((candidate for candidate in names if candidate in servers), None)
    if target is None:
        return "absent"
    if not created:
        return "preserved"
    existing = servers[target]
    entry = json_http_server(url, include_type=include_type, token=token)
    if not entry_matches(existing, entry) and not specgate_http_owned(existing, url):
        return "preserved"
    servers.pop(target)
    if not servers:
        data.pop("mcpServers", None)
    _write_json(path, data)
    return "removed"


def grok_server_block(url: str, *, token: str | None = None) -> str:
    authorization = f"Bearer {token}" if token else f"Bearer ${{{TOKEN_ENV}}}"
    return (
        f"[{_GROK_TABLE}]\n"
        f"url = {_toml_string(url)}\n"
        f"headers = {{ Authorization = {_toml_string(authorization)} }}\n"
    )


def _table_span(text: str, table: str) -> tuple[int, int] | None:
    header = f"[{table}]"
    nested = f"[{table}."
    start: int | None = None
    for match in re.finditer(r"(?m)^[ \t]*(\[[^\]]+\])", text):
        name = match.group(1)
        if name == header or name.startswith(nested):
            if start is None:
                start = match.start()
            continue
        if start is not None:
            return start, match.start()
    if start is None:
        return None
    return start, len(text.rstrip() + "\n") if text.endswith("\n") else len(text)


def _table_url(block: str) -> str | None:
    match = re.search(r'(?m)^\s*url\s*=\s*"([^"]*)"\s*$', block)
    return match.group(1) if match else None


def merge_grok_config(path: Path, url: str, *, token: str | None = None) -> McpStatus:
    """Merge [mcp_servers.specgate] into ~/.grok/config.toml."""
    text = path.read_text() if path.is_file() else ""
    span = _table_span(text, _GROK_TABLE)
    block = grok_server_block(url, token=token)
    if span is None:
        prefix = text if not text or text.endswith("\n") else text + "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix = prefix.rstrip("\n") + "\n\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prefix + block if prefix else block)
        return "created"
    existing = text[span[0] : span[1]]
    current_url = _table_url(existing)
    if current_url not in {None, url}:
        raise ValueError("The specgate MCP entry already has another configuration.")
    if existing.strip() == block.strip():
        return "unchanged"
    path.write_text(text[: span[0]] + block + text[span[1] :])
    return "updated" if current_url == url else "created"


def remove_grok_config(path: Path, url: str, *, created: bool) -> McpStatus:
    """Remove Specgate or leftover Dev Decision tables this installer created."""
    if not path.is_file():
        return "absent"
    text = path.read_text()
    status: McpStatus = "absent"
    for table in (_GROK_TABLE, _GROK_LEGACY_TABLE):
        span = _table_span(text, table)
        if span is None:
            continue
        if not created:
            return "preserved"
        block = text[span[0] : span[1]]
        current_url = _table_url(block)
        if current_url not in {None, url}:
            return "preserved"
        before = text[: span[0]].rstrip()
        after = text[span[1] :].lstrip("\n")
        text = f"{before}\n\n{after}" if before and after else before + after
        if text and not text.endswith("\n"):
            text += "\n"
        status = "removed"
    if status == "removed":
        path.write_text(text)
    return status
