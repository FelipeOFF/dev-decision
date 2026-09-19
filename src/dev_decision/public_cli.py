"""Interactive entry point used by the npm bootstrap."""

import argparse
import asyncio
import getpass
import json
import os
from pathlib import Path
from typing import Any

from dev_decision.client import ReviewRequest
from dev_decision.public_setup import (
    detect_public_harnesses,
    doctor_public_harnesses,
    install_public_harnesses,
    managed_project_id,
    public_harness_capabilities,
    uninstall_public_harnesses,
    update_public_harnesses,
)
from dev_decision.routing import route_skills
from dev_decision.transport import call_tool, negotiate_protocol


def _bundled_skills() -> Path:
    configured = os.environ.get("DEV_DECISION_SKILL_SOURCE")
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
        "the Dev Decision MCP, escalating only business choices, authorizations, "
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
    parser = argparse.ArgumentParser(description="Instalador público Dev Decision")
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
            available = detect_public_harnesses()
            if args.harness:
                missing = sorted(set(args.harness) - set(available))
                if missing:
                    raise ValueError(
                        "Harnesses not found: " + ", ".join(missing)
                    )
                selected = tuple(args.harness)
            elif args.yes:
                selected = available
            else:
                selected = tuple(
                    name
                    for name in available
                    if input(f"Instalar integração global de {name}? [Y/n] ")
                    .strip()
                    .lower()
                    not in {"n", "no", "não", "nao"}
                )
            if not selected:
                print(json.dumps({"installed": False, "harnesses": []}))
                return
            host = _endpoint(args.host or input("Host HTTPS do MCP: ").strip())
            api_key = os.environ.get("DEV_DECISION_MCP_API_KEY") or getpass.getpass(
                "API key do MCP: "
            )
            result: Any = install_public_harnesses(
                _bundled_skills(),
                host,
                api_key,
                selected,
            )
        elif args.command == "doctor":
            result = asyncio.run(
                doctor_public_harnesses(
                    args.project, timeout_seconds=args.timeout
                )
            )
        elif args.command == "update":
            result = update_public_harnesses(_bundled_skills())
        elif args.command == "smoke":
            api_key = os.environ.get("DEV_DECISION_MCP_API_KEY", "")
            result = asyncio.run(_smoke(args.project, _endpoint(args.host), api_key))
        else:
            result = uninstall_public_harnesses()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, ExceptionGroup) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
