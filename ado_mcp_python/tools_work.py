from __future__ import annotations

from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

from .ado_client import AzureDevOpsClients
from .utils import to_primitive


def _is_iteration_node(node: dict[str, Any]) -> bool:
    structure_type = node.get("structureType")
    if isinstance(structure_type, int):
        # Azure DevOps enum value for Iteration in many SDK responses.
        return structure_type == 1
    if isinstance(structure_type, str):
        return structure_type.lower() == "iteration"
    return False


def _filter_out_ids(nodes: list[dict[str, Any]], excluded_ids: set[int]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for node in nodes:
        node_id = node.get("id")
        if isinstance(node_id, int) and node_id in excluded_ids:
            continue

        copied = dict(node)
        children = copied.get("children")
        if isinstance(children, list):
            copied["children"] = _filter_out_ids(children, excluded_ids)
        filtered.append(copied)
    return filtered


def register_work_tools(mcp: FastMCP, clients: AzureDevOpsClients) -> None:
    @mcp.tool(
        name="work_list_team_iterations",
        description="Retrieve a list of iterations for a specific team in a project.",
    )
    def work_list_team_iterations(
        project: str,
        team: str,
        timeframe: str | None = None,
    ) -> list[dict[str, Any]]:
        work_client = clients.work()
        iterations = work_client.get_team_iterations({"project": project, "team": team}, timeframe)
        return to_primitive(iterations)

    @mcp.tool(name="work_list_iterations", description="List all iterations in a specified Azure DevOps project.")
    def work_list_iterations(
        project: str,
        depth: int = 2,
        excludedIds: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        wit_client = clients.work_item_tracking()
        nodes = wit_client.get_classification_nodes(project, [], depth)
        data = to_primitive(nodes) or []

        if not isinstance(data, list):
            return []

        iteration_nodes = [node for node in data if isinstance(node, dict) and _is_iteration_node(node)]

        if excludedIds:
            iteration_nodes = _filter_out_ids(iteration_nodes, set(excludedIds))

        return iteration_nodes

    @mcp.tool(name="work_create_iterations", description="Create new iterations in a specified Azure DevOps project.")
    def work_create_iterations(project: str, iterations: list[dict[str, str]]) -> list[dict[str, Any]]:
        if not iterations:
            raise ValueError("iterations must include at least one iteration definition")

        wit_client = clients.work_item_tracking()
        created: list[Any] = []

        for entry in iterations:
            iteration_name = str(entry.get("iterationName") or "").strip()
            if not iteration_name:
                raise ValueError("Each iteration must include a non-empty iterationName")

            start_date = entry.get("startDate")
            finish_date = entry.get("finishDate")
            payload = {
                "name": iteration_name,
                "attributes": {
                    "startDate": datetime.fromisoformat(start_date.replace("Z", "+00:00")) if start_date else None,
                    "finishDate": datetime.fromisoformat(finish_date.replace("Z", "+00:00")) if finish_date else None,
                },
            }
            result = wit_client.create_or_update_classification_node(payload, project, "iterations")
            created.append(result)

        return to_primitive(created)

    @mcp.tool(name="work_assign_iterations", description="Assign existing iterations to a specific team in a project.")
    def work_assign_iterations(project: str, team: str, iterations: list[dict[str, str]]) -> list[dict[str, Any]]:
        if not iterations:
            raise ValueError("iterations must include at least one iteration assignment")

        work_client = clients.work()
        team_context = {"project": project, "team": team}
        results: list[Any] = []
        for entry in iterations:
            identifier = str(entry.get("identifier") or "").strip()
            path = str(entry.get("path") or "").strip()
            if not identifier or not path:
                raise ValueError("Each iteration assignment requires identifier and path")
            assignment = work_client.post_team_iteration({"id": identifier, "path": path}, team_context)
            results.append(assignment)
        return to_primitive(results)

    @mcp.tool(
        name="work_get_team_capacity",
        description="Get team capacity for a specific team and iteration in a project.",
    )
    def work_get_team_capacity(project: str, team: str, iterationId: str) -> dict[str, Any]:
        work_client = clients.work()
        team_context = {"project": project, "team": team}
        capacity = work_client.get_capacities_with_identity_ref_and_totals(team_context, iterationId)
        return to_primitive(capacity)

    @mcp.tool(
        name="work_update_team_capacity",
        description="Update the team capacity of a team member for a specific iteration in a project.",
    )
    def work_update_team_capacity(
        project: str,
        team: str,
        teamMemberId: str,
        iterationId: str,
        activities: list[dict[str, Any]],
        daysOff: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        if not activities:
            raise ValueError("activities must include at least one activity")

        patch = {
            "activities": [
                {
                    "name": str(activity.get("name") or ""),
                    "capacityPerDay": float(activity.get("capacityPerDay") or 0),
                }
                for activity in activities
            ],
            "daysOff": [
                {
                    "start": datetime.fromisoformat(str(day.get("start") or "").replace("Z", "+00:00")),
                    "end": datetime.fromisoformat(str(day.get("end") or "").replace("Z", "+00:00")),
                }
                for day in (daysOff or [])
            ],
        }

        work_client = clients.work()
        team_context = {"project": project, "team": team}
        updated = work_client.update_capacity_with_identity_ref(patch, team_context, iterationId, teamMemberId)
        return to_primitive(updated)

    @mcp.tool(
        name="work_get_iteration_capacities",
        description="Get iteration capacity totals for all teams in an iteration.",
    )
    def work_get_iteration_capacities(project: str, iterationId: str) -> dict[str, Any]:
        work_client = clients.work()
        capacities = work_client.get_total_iteration_capacities(project, iterationId)
        return to_primitive(capacities)

    @mcp.tool(
        name="work_get_team_settings",
        description="Get team settings including default iteration, backlog iteration, and area path.",
    )
    def work_get_team_settings(project: str, team: str) -> dict[str, Any]:
        work_client = clients.work()
        team_context = {"project": project, "team": team}
        team_settings = to_primitive(work_client.get_team_settings(team_context)) or {}
        team_field_values = to_primitive(work_client.get_team_field_values(team_context)) or {}
        return {
            "backlogIteration": team_settings.get("backlogIteration"),
            "defaultIteration": team_settings.get("defaultIteration"),
            "defaultIterationMacro": team_settings.get("defaultIterationMacro"),
            "backlogVisibilities": team_settings.get("backlogVisibilities"),
            "bugsBehavior": team_settings.get("bugsBehavior"),
            "workingDays": team_settings.get("workingDays"),
            "defaultAreaPath": team_field_values.get("defaultValue"),
            "areaPathField": team_field_values.get("field"),
            "areaPaths": team_field_values.get("values"),
        }
