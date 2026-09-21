"""Public protocol metadata shared by the MCP server and Python client."""

import re
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = "1.0.0"
HANDSHAKE_TOOL = "dev_decision_handshake"
PROTOCOL_CAPABILITIES = frozenset({"attached_operations", "heartbeat", "sse_progress"})
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


@dataclass(frozen=True)
class NegotiatedProtocol:
    client_version: str
    server_version: str
    capabilities: frozenset[str]
    operation_mode: str


def protocol_metadata(version: str = PROTOCOL_VERSION) -> dict[str, Any]:
    _major(version)
    return {
        "version": version,
        "capabilities": sorted(PROTOCOL_CAPABILITIES),
        "operationMode": "attached",
    }


def negotiate(
    settings: dict[str, Any] | None, client_version: str = PROTOCOL_VERSION
) -> NegotiatedProtocol:
    if settings is None:
        raise ValueError("The MCP server does not advertise the Specgate protocol.")
    server_version = settings.get("version")
    capabilities = settings.get("capabilities")
    operation_mode = settings.get("operationMode")
    if (
        not isinstance(server_version, str)
        or not isinstance(capabilities, list)
        or not all(isinstance(item, str) for item in capabilities)
        or operation_mode != "attached"
    ):
        raise ValueError("The MCP server advertised an invalid protocol.")
    if _major(server_version) != _major(client_version):
        raise ValueError(
            f"Incompatible protocols: client {client_version}, server {server_version}."
        )
    negotiated = PROTOCOL_CAPABILITIES.intersection(capabilities)
    missing = PROTOCOL_CAPABILITIES.difference(negotiated)
    if missing:
        raise ValueError(
            "The MCP server is missing required capabilities: "
            + ", ".join(sorted(missing))
            + "."
        )
    return NegotiatedProtocol(
        client_version=client_version,
        server_version=server_version,
        capabilities=frozenset(negotiated),
        operation_mode=operation_mode,
    )


def _major(version: str) -> int:
    match = _SEMVER.fullmatch(version)
    if match is None:
        raise ValueError("The protocol version must follow SemVer.")
    return int(match.group(1))
