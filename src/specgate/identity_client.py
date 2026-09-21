"""Authenticated client for creating or refreshing a project namespace."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from specgate.transport import call_tool


@dataclass(frozen=True)
class ProjectClient:
    url: str
    token: str
    transport: str = "streamable"
    ca_file: Path | None = None
    timeout_seconds: float = 30

    async def setup(
        self,
        *,
        path_metadata: str | None = None,
        remote_metadata: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        result = await call_tool(
            self.url,
            self.token,
            "project_setup",
            {
                "path_metadata": path_metadata,
                "remote_metadata": remote_metadata,
                "project_id": project_id,
            },
            transport=self.transport,
            ca_file=self.ca_file,
            timeout_seconds=self.timeout_seconds,
        )
        if result.is_error or result.structured_content is None:
            raise ValueError("O MCP não retornou um project válido.")
        content: dict[str, Any] = result.structured_content
        return content

    async def list_data(self, project_id: str) -> dict[str, Any]:
        return await self._call("project_data_list", {}, project_id)

    async def export_data(self, project_id: str) -> dict[str, Any]:
        return await self._call("project_data_export", {}, project_id)

    async def delete_data(
        self, project_id: str, process_ids: list[str] | None = None
    ) -> dict[str, Any]:
        return await self._call(
            "project_data_delete", {"process_ids": process_ids}, project_id
        )

    async def usage_metrics(self, project_id: str) -> dict[str, Any]:
        return await self._call("project_usage_metrics", {}, project_id)

    async def apply_retention(self, project_id: str) -> dict[str, Any]:
        return await self._call("project_data_apply_retention", {}, project_id)

    async def _call(
        self, tool: str, arguments: dict[str, Any], project_id: str
    ) -> dict[str, Any]:
        result = await call_tool(
            self.url,
            self.token,
            tool,
            arguments,
            transport=self.transport,
            ca_file=self.ca_file,
            timeout_seconds=self.timeout_seconds,
            project_id=project_id,
        )
        if result.is_error or result.structured_content is None:
            raise ValueError("MCP returned no valid project data.")
        content: dict[str, Any] = result.structured_content
        return content
