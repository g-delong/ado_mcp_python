from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .ado_client import AzureDevOpsClients
from .utils import to_primitive


def register_mcp_apps_tools(mcp: FastMCP) -> None:
    @mcp.tool(name="mcp_apps_ping", description="A simple ping tool to verify that the mcp-apps domain is enabled.")
    def mcp_apps_ping() -> dict[str, Any]:
        return {"message": "pong - mcp-apps domain is active"}


def register_core_tools(mcp: FastMCP, clients: AzureDevOpsClients) -> None:
    @mcp.tool(name="core_list_projects", description="Retrieve a list of projects in your Azure DevOps organization.")
    def core_list_projects(state_filter: str = "wellFormed", top: int = 100, skip: int = 0) -> list[dict[str, Any]]:
        core_client = clients.core()
        projects = core_client.get_projects(state_filter=state_filter, top=top, skip=skip)
        return to_primitive(projects)

    @mcp.tool(
        name="core_list_project_teams",
        description="Retrieve a list of teams for an Azure DevOps project.",
    )
    def core_list_project_teams(project: str, mine: bool | None = None, top: int = 100, skip: int = 0) -> list[dict[str, Any]]:
        core_client = clients.core()
        teams = core_client.get_teams(project_id=project, mine=mine, top=top, skip=skip)
        return to_primitive(teams)
