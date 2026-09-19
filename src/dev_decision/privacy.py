"""Reject known credential/session markers; this is not semantic sanitization."""

import re
from typing import Any

_PRIVATE_MARKER = re.compile(
    r"sk-or-v1-[A-Za-z0-9_-]{16,}"
    r"|-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"
    r"|Claude-Session:\s*https?://[^\s<>]+"
    r"|Claude-Session:\s*[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b"
    r"|https?://claude\.ai/code/session_[A-Za-z0-9_-]+"
    r"|(?:~|/[^\s\"'<>]*)/\.(?:codex/sessions|claude/projects|grok/sessions)/"
    r"[A-Za-z0-9_./-]*[A-Za-z0-9_-]\.jsonl\b",
    re.IGNORECASE,
)


def ensure_safe_content(value: Any, *, secrets: tuple[str, ...] = ()) -> None:
    """Check fields recursively without including rejected content in errors."""
    if isinstance(value, str):
        if _PRIVATE_MARKER.search(value) or any(
            secret and secret in value for secret in secrets
        ):
            raise ValueError(
                "Conteúdo sensível bloqueado; remova credenciais e referências de sessão."
            )
    elif isinstance(value, dict):
        for key, item in value.items():
            ensure_safe_content(key, secrets=secrets)
            ensure_safe_content(item, secrets=secrets)
    elif isinstance(value, (tuple, list)):
        for item in value:
            ensure_safe_content(item, secrets=secrets)
