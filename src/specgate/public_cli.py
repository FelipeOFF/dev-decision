"""Interactive entry point for the public pipx client."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from specgate.client import ReviewRequest
from specgate.product import (
    LEGACY_SKILL_SOURCE_ENV,
    SKILL_SOURCE_ENV,
    mcp_api_key,
)
from specgate.public_setup import (
    HarnessName,
    detect_public_harnesses,
    doctor_public_harnesses,
    install_public_harnesses,
    managed_project_id,
    public_harness_capabilities,
    uninstall_public_harnesses,
    update_public_harnesses,
)
from specgate.routing import route_skills
from specgate.transport import call_tool, negotiate_protocol

_HARNESS_SETUP_HINTS = {
    "codex": "Codex — app-server controlado",
    "claude-code": "Claude Code — hooks nativos (UserPromptSubmit, PreToolUse)",
    "cursor": "Cursor — ACP controlado",
    "grok-build": "Grok Build — ACP controlado",
    "grok-bot": (
        "Grok Bot — cooperativo: copie GROK_BOT.md e anexe o Custom MCP; "
        "sem interceptação obrigatória"
    ),
}


def public_harness_setup_hints() -> dict[str, str]:
    """Return the installer line shown for each supported harness."""
    return dict(_HARNESS_SETUP_HINTS)


def _ask(prompt: str, stdin: TextIO, stderr: TextIO) -> str:
    print(prompt, end="", file=stderr, flush=True)
    try:
        return stdin.readline()
    except KeyboardInterrupt:
        print("\nCancelado.", file=stderr)
        raise SystemExit(130) from None


def prompt_harness_selection(
    available: Sequence[HarnessName],
    *,
    stdin: TextIO,
    stderr: TextIO,
) -> tuple[HarnessName, ...]:
    """Toggle detected harnesses; empty input confirms the current selection."""
    if not available:
        print(
            "Nenhum harness suportado foi detectado nesta máquina.",
            file=stderr,
        )
        return ()
    selected = set(available)
    names = tuple(available)
    while True:
        print(
            "Harnesses detectados. a instala em todos; números alternam a seleção; Enter confirma.",
            file=stderr,
        )
        print(file=stderr)
        all_mark = "x" if selected == set(names) else " "
        print(
            f"  [{all_mark}] a  Todos — instalar em todos os harnesses detectados",
            file=stderr,
        )
        for index, name in enumerate(names, start=1):
            mark = "x" if name in selected else " "
            print(
                f"  [{mark}] {index}  {_HARNESS_SETUP_HINTS[name]}",
                file=stderr,
            )
        print(file=stderr)
        line = _ask(
            "Toggle (números ou a=todos) ou Enter para continuar: ",
            stdin,
            stderr,
        )
        if line == "" or not line.strip():
            break
        for token in line.replace(",", " ").split():
            key = token.lower()
            if key == "a":
                if selected == set(names):
                    selected.clear()
                else:
                    selected.update(names)
                continue
            if not token.isdigit() or not 1 <= int(token) <= len(names):
                print(f"Valor inválido: {token}", file=stderr)
                continue
            name = names[int(token) - 1]
            if name in selected:
                selected.remove(name)
            else:
                selected.add(name)
    if not selected:
        print("Nenhum harness selecionado.", file=stderr)
        return ()
    return tuple(name for name in names if name in selected)


def select_harnesses(
    *,
    available: Sequence[HarnessName],
    requested: Sequence[str] | None,
    accept_all: bool,
    stdin: TextIO,
    stderr: TextIO,
) -> tuple[HarnessName, ...]:
    """Resolve harnesses from flags or the interactive toggle prompt."""
    names = tuple(available)
    if requested:
        missing = sorted(set(requested) - set(names))
        if missing:
            raise ValueError("Harnesses not found: " + ", ".join(missing))
        wanted = set(requested)
        return tuple(name for name in names if name in wanted)
    if accept_all:
        return names
    return prompt_harness_selection(names, stdin=stdin, stderr=stderr)


def prompt_host(
    raw: str | None,
    *,
    stdin: TextIO,
    stderr: TextIO,
) -> str:
    """Read the MCP origin if it was not passed as --host."""
    if raw is None:
        raw = _ask("Host HTTPS do MCP: ", stdin, stderr).strip()
    return _endpoint(raw)


def prompt_api_key(
    *,
    stdin: TextIO,
    stderr: TextIO,
    environ: Mapping[str, str] | None = None,
    get_pass: Any = getpass.getpass,
) -> str:
    """Prefer SPECGATE_MCP_API_KEY, then DEV_DECISION_MCP_API_KEY; else prompt."""
    env = mcp_api_key(environ)
    if env:
        return env
    return str(get_pass("API key do MCP: "))


def _bundled_skills() -> Path:
    configured = os.environ.get(SKILL_SOURCE_ENV) or os.environ.get(
        LEGACY_SKILL_SOURCE_ENV
    )
    if configured:
        return Path(configured)
    packaged = Path(__file__).with_name("skills")
    return packaged if packaged.is_dir() else Path(__file__).resolve().parents[2] / "skill"


def _endpoint(value: str) -> str:
    value = value.rstrip("/")
    return value if value.endswith(("/mcp", "/sse")) else f"{value}/mcp"


async def _smoke(project: Path, host: str, token: str) -> dict[str, Any]:
    project = project.resolve()
    skills = _bundled_skills().resolve()
    query = (
        "Resolve specification questions from authorized project evidence through "
        "the Specgate MCP, escalating only business choices, authorizations, "
        "and persistent gaps."
    )
    request = ReviewRequest(
        objective="Route the requirements clarification skill with authorized evidence.",
        tool="jev_find",
        arguments={"query": query},
        sources=["CONTEXT.md"],
        required=["CONTEXT.md"],
        artifact=query,
        skill_roots=[str(skills)],
    )
    project_id = managed_project_id()
    protocol = await negotiate_protocol(host, token, project_id=project_id)
    route = await route_skills(
        request,
        project,
        host,
        token,
        authorized_roots=[skills],
        project_id=project_id,
    )
    operation = await call_tool(
        host,
        token,
        "jev_screen",
        {"text": "Public release smoke fixture.", "purpose": "Verify attached MCP."},
        project_id=project_id,
    )
    content = operation.structured_content
    if operation.is_error or content is None or content.get("mode") != "mock":
        raise ValueError("Local smoke requires a successful mock MCP operation.")
    candidate = route.get("candidate")
    return {
        "paid_calls": 0,
        "protocol": {
            "client_version": protocol.client_version,
            "server_version": protocol.server_version,
            "capabilities": sorted(protocol.capabilities),
        },
        "route": {
            "status": route["status"],
            "candidate": candidate.get("id") if isinstance(candidate, dict) else None,
            "action": route["action"],
        },
        "attached_operation": {
            "status": "completed",
            "action": content.get("action"),
            "mode": content["mode"],
        },
        "harnesses": public_harness_capabilities(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Instalador público Specgate")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install")
    install.add_argument("--host")
    install.add_argument(
        "--harness",
        action="append",
        choices=tuple(public_harness_capabilities()),
    )
    install.add_argument("--yes", action="store_true")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--project", type=Path, default=Path.cwd())
    doctor.add_argument("--timeout", type=float, default=30)
    commands.add_parser("update")
    smoke = commands.add_parser("smoke")
    smoke.add_argument("--host", required=True)
    smoke.add_argument("--project", type=Path, default=Path.cwd())
    commands.add_parser("uninstall")
    args = parser.parse_args()

    try:
        if args.command == "install":
            selected = select_harnesses(
                available=detect_public_harnesses(),
                requested=args.harness,
                accept_all=args.yes,
                stdin=sys.stdin,
                stderr=sys.stderr,
            )
            if not selected:
                print(json.dumps({"installed": False, "harnesses": []}))
                return
            host = prompt_host(args.host, stdin=sys.stdin, stderr=sys.stderr)
            api_key = prompt_api_key(stdin=sys.stdin, stderr=sys.stderr)
            result = install_public_harnesses(
                _bundled_skills(),
                host,
                api_key,
                selected,
            )
            try:
                result["doctor"] = asyncio.run(
                    doctor_public_harnesses(Path.cwd())
                )
            except (ValueError, OSError, ExceptionGroup) as error:
                result["doctor"] = {
                    "status": "configured_unverified",
                    "error": str(error),
                }
        elif args.command == "doctor":
            result = asyncio.run(
                doctor_public_harnesses(
                    args.project, timeout_seconds=args.timeout
                )
            )
        elif args.command == "update":
            result = update_public_harnesses(_bundled_skills())
        elif args.command == "smoke":
            api_key = mcp_api_key()
            result = asyncio.run(_smoke(args.project, _endpoint(args.host), api_key))
        else:
            result = uninstall_public_harnesses()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        print("\nCancelado.", file=sys.stderr)
        raise SystemExit(130) from None
    except (ValueError, OSError, ExceptionGroup) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
