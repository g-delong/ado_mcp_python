from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

from .ado_client import AzureDevOpsClients
from .utils import to_primitive


_BATCH_API_VERSION = "7.1"
_COMMENTS_API_VERSION = "7.1-preview.4"

_DEFAULT_BATCH_FIELDS = [
    "System.Id",
    "System.WorkItemType",
    "System.Title",
    "System.State",
    "System.Parent",
    "System.Tags",
    "Microsoft.VSTS.Common.StackRank",
    "System.AssignedTo",
]

_IDENTITY_FIELDS = {
    "System.AssignedTo",
    "System.CreatedBy",
    "System.ChangedBy",
    "System.AuthorizedAs",
    "Microsoft.VSTS.Common.ActivatedBy",
    "Microsoft.VSTS.Common.ResolvedBy",
    "Microsoft.VSTS.Common.ClosedBy",
}

_LINK_TYPE_MAP = {
    "parent": "System.LinkTypes.Hierarchy-Reverse",
    "child": "System.LinkTypes.Hierarchy-Forward",
    "duplicate": "System.LinkTypes.Duplicate-Forward",
    "duplicate of": "System.LinkTypes.Duplicate-Reverse",
    "related": "System.LinkTypes.Related",
    "successor": "System.LinkTypes.Dependency-Forward",
    "predecessor": "System.LinkTypes.Dependency-Reverse",
    "tested by": "Microsoft.VSTS.Common.TestedBy-Forward",
    "tests": "Microsoft.VSTS.Common.TestedBy-Reverse",
    "affects": "Microsoft.VSTS.Common.Affects-Forward",
    "affected by": "Microsoft.VSTS.Common.Affects-Reverse",
    "artifact": "ArtifactLink",
}


def _safe_getattr_call(obj: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(obj, method_name, None)
    if not callable(method):
        raise NotImplementedError(f"Azure DevOps Python SDK method '{method_name}' is unavailable in this environment.")
    return method(*args, **kwargs)


def _ado_json_request(
    clients: AzureDevOpsClients,
    method: str,
    path: str,
    query: dict[str, Any] | None = None,
    body: Any | None = None,
    content_type: str = "application/json",
) -> Any:
    org_url = clients.organization_url.rstrip("/")
    authorization = clients.authorization_header()
    query_string = ""
    if query:
        clean_query = {k: v for k, v in query.items() if v is not None}
        query_string = f"?{urllib.parse.urlencode(clean_query, doseq=True)}"
    url = f"{org_url}/{path.lstrip('/')}" + query_string

    payload: bytes | None = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Authorization": authorization,
            "Accept": "application/json",
            "Content-Type": content_type,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            if not data:
                return {}
            text = data.decode("utf-8", errors="replace")
            return json.loads(text)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure DevOps API request failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Azure DevOps API request failed: {exc.reason}") from exc


def _format_identity_fields(work_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in work_items:
        fields = item.get("fields")
        if not isinstance(fields, dict):
            continue
        for field_name in _IDENTITY_FIELDS:
            identity = fields.get(field_name)
            if isinstance(identity, dict):
                display_name = str(identity.get("displayName") or "").strip()
                unique_name = str(identity.get("uniqueName") or "").strip()
                combined = f"{display_name} <{unique_name}>".strip()
                fields[field_name] = combined if combined else display_name or unique_name
    return work_items


def _get_link_type_from_name(name: str) -> str:
    link_type = _LINK_TYPE_MAP.get(name.lower())
    if not link_type:
        raise ValueError(f"Unknown link type: {name}")
    return link_type


def _get_mime_type(file_name: str | None) -> str:
    if not file_name or "." not in file_name:
        return "application/octet-stream"
    ext = file_name.rsplit(".", 1)[-1].lower()
    mime_types = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "svg": "image/svg+xml",
        "webp": "image/webp",
        "pdf": "application/pdf",
        "txt": "text/plain",
        "json": "application/json",
        "zip": "application/zip",
    }
    return mime_types.get(ext, "application/octet-stream")


def _field_value(value: str, format_name: str | None = None) -> str:
    # Azure DevOps accepts plain strings for most field updates; markdown formatting is
    # carried by optional multiline format operations for long text fields.
    _ = format_name
    return value


def _field_patch_ops(fields: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"op": "add", "path": f"/fields/{name}", "value": value} for name, value in fields.items()]


def register_work_item_tools(mcp: FastMCP, clients: AzureDevOpsClients) -> None:
    @mcp.tool(name="wit_list_backlogs", description="Receive a list of backlogs for a given project and team.")
    def wit_list_backlogs(project: str, team: str) -> list[dict[str, Any]]:
        work_client = clients.work()
        backlogs = _safe_getattr_call(work_client, "get_backlogs", {"project": project, "team": team})
        return to_primitive(backlogs)

    @mcp.tool(
        name="wit_list_backlog_work_items",
        description="Retrieve backlog work items for a given project, team, and backlog category.",
    )
    def wit_list_backlog_work_items(project: str, team: str, backlogId: str) -> dict[str, Any]:
        work_client = clients.work()
        work_items = _safe_getattr_call(work_client, "get_backlog_level_work_items", {"project": project, "team": team}, backlogId)
        return to_primitive(work_items)

    @mcp.tool(name="wit_my_work_items", description="Retrieve a list of work items relevant to the authenticated user.")
    def wit_my_work_items(
        project: str,
        type: str = "assignedtome",
        top: int = 50,
        includeCompleted: bool = False,
    ) -> dict[str, Any]:
        query = {
            "$top": max(1, top),
            "includeDeleted": str(bool(includeCompleted)).lower(),
            "api-version": "7.1",
        }
        return _ado_json_request(clients, "GET", f"{urllib.parse.quote(project)}/_apis/wit/queries/{urllib.parse.quote(type)}", query=query)

    @mcp.tool(name="wit_get_work_items_batch_by_ids", description="Get multiple work items by IDs.")
    def wit_get_work_items_batch_by_ids(project: str, ids: list[int], fields: list[str] | None = None) -> list[dict[str, Any]]:
        if not ids:
            raise ValueError("ids must contain at least one work item ID.")

        wit_client = clients.work_item_tracking()
        fields_to_use = fields if fields else _DEFAULT_BATCH_FIELDS
        items = _safe_getattr_call(wit_client, "get_work_items_batch", {"ids": ids, "fields": fields_to_use}, project)
        primitive = to_primitive(items)
        if isinstance(primitive, list):
            return _format_identity_fields(primitive)
        return primitive

    @mcp.tool(name="wit_get_work_item", description="Get a work item by ID.")
    def wit_get_work_item(
        id: int,
        project: str,
        fields: list[str] | None = None,
        asOf: str | None = None,
        expand: str | None = None,
    ) -> dict[str, Any]:
        wit_client = clients.work_item_tracking()
        item = _safe_getattr_call(
            wit_client,
            "get_work_item",
            id,
            fields,
            asOf,
            expand,
            project,
        )
        return to_primitive(item)

    @mcp.tool(name="wit_list_work_item_comments", description="Retrieve comments for a work item by ID.")
    def wit_list_work_item_comments(project: str, workItemId: int, top: int = 50) -> dict[str, Any]:
        wit_client = clients.work_item_tracking()
        comments = _safe_getattr_call(wit_client, "get_comments", project, workItemId, top)
        return to_primitive(comments)

    @mcp.tool(name="wit_add_work_item_comment", description="Add a comment to a work item by ID.")
    def wit_add_work_item_comment(project: str, workItemId: int, comment: str, format: str = "html") -> dict[str, Any]:
        format_parameter = 0 if format.lower() == "markdown" else 1
        return _ado_json_request(
            clients,
            "POST",
            f"{urllib.parse.quote(project)}/_apis/wit/workItems/{workItemId}/comments",
            query={"format": format_parameter, "api-version": _COMMENTS_API_VERSION},
            body={"text": comment},
        )

    @mcp.tool(name="wit_update_work_item_comment", description="Update an existing comment on a work item by ID.")
    def wit_update_work_item_comment(project: str, workItemId: int, commentId: int, text: str, format: str = "html") -> dict[str, Any]:
        format_parameter = 0 if format.lower() == "markdown" else 1
        return _ado_json_request(
            clients,
            "PATCH",
            f"{urllib.parse.quote(project)}/_apis/wit/workItems/{workItemId}/comments/{commentId}",
            query={"format": format_parameter, "api-version": _COMMENTS_API_VERSION},
            body={"text": text},
        )

    @mcp.tool(name="wit_list_work_item_revisions", description="Retrieve revisions for a work item by ID.")
    def wit_list_work_item_revisions(
        project: str,
        workItemId: int,
        top: int = 50,
        skip: int = 0,
        expand: str | None = None,
    ) -> list[dict[str, Any]]:
        wit_client = clients.work_item_tracking()
        revisions = _safe_getattr_call(wit_client, "get_revisions", workItemId, top, skip, expand, project)
        return to_primitive(revisions)

    @mcp.tool(name="wit_get_work_items_for_iteration", description="Retrieve work items for a specified iteration.")
    def wit_get_work_items_for_iteration(project: str, iterationId: str, team: str | None = None) -> dict[str, Any]:
        work_client = clients.work()
        team_context = {"project": project, "team": team}
        work_items = _safe_getattr_call(work_client, "get_iteration_work_items", team_context, iterationId)
        return to_primitive(work_items)

    @mcp.tool(name="wit_update_work_item", description="Update a work item by ID with field operations.")
    def wit_update_work_item(id: int, updates: list[dict[str, Any]]) -> dict[str, Any]:
        if not updates:
            raise ValueError("updates must contain at least one operation.")

        wit_client = clients.work_item_tracking()
        normalized_updates: list[dict[str, Any]] = []
        for update in updates:
            op = str(update.get("op", "add")).lower()
            if op not in {"add", "replace", "remove"}:
                raise ValueError("op must be one of: add, replace, remove")
            path = update.get("path")
            if not isinstance(path, str) or not path:
                raise ValueError("Each update must include a non-empty path.")
            payload: dict[str, Any] = {"op": op, "path": path}
            if op != "remove":
                payload["value"] = update.get("value")
            normalized_updates.append(payload)

        updated = _safe_getattr_call(wit_client, "update_work_item", None, normalized_updates, id)
        return to_primitive(updated)

    @mcp.tool(name="wit_get_work_item_type", description="Get a specific work item type.")
    def wit_get_work_item_type(project: str, workItemType: str) -> dict[str, Any]:
        wit_client = clients.work_item_tracking()
        item_type = _safe_getattr_call(wit_client, "get_work_item_type", project, workItemType)
        return to_primitive(item_type)

    @mcp.tool(name="wit_create_work_item", description="Create a work item.")
    def wit_create_work_item(project: str, workItemType: str, fields: list[dict[str, Any]] | dict[str, Any]) -> dict[str, Any]:
        if not fields:
            raise ValueError("fields must contain at least one field value")

        document: list[dict[str, Any]] = []
        if isinstance(fields, dict):
            document = _field_patch_ops(fields)
        else:
            for item in fields:
                name = item.get("name")
                value = item.get("value")
                format_name = item.get("format")
                if not isinstance(name, str) or not name:
                    raise ValueError("Each field must include a non-empty name.")
                if value is None:
                    raise ValueError(f"Field '{name}' is missing a value.")
                text_value = str(value)
                document.append({"op": "add", "path": f"/fields/{name}", "value": _field_value(text_value, format_name)})
                if str(format_name or "").lower() == "markdown" and len(text_value) > 50:
                    document.append({"op": "add", "path": f"/multilineFieldsFormat/{name}", "value": "Markdown"})

        wit_client = clients.work_item_tracking()
        created = _safe_getattr_call(wit_client, "create_work_item", None, document, project, workItemType)
        return to_primitive(created)

    @mcp.tool(name="wit_get_query", description="Get a query by its ID or path.")
    def wit_get_query(
        project: str,
        query: str,
        expand: str | None = None,
        depth: int = 0,
        includeDeleted: bool = False,
        useIsoDateFormat: bool = False,
    ) -> dict[str, Any]:
        wit_client = clients.work_item_tracking()
        query_data = _safe_getattr_call(
            wit_client,
            "get_query",
            project,
            query,
            expand,
            depth,
            includeDeleted,
            useIsoDateFormat,
        )
        return to_primitive(query_data)

    @mcp.tool(
        name="wit_get_query_results_by_id",
        description="Retrieve query results by query ID. Supports full or IDs-only response.",
    )
    def wit_get_query_results_by_id(
        id: str,
        project: str | None = None,
        team: str | None = None,
        timePrecision: bool | None = None,
        top: int = 50,
        responseType: str = "full",
    ) -> dict[str, Any]:
        wit_client = clients.work_item_tracking()
        team_context = {"project": project, "team": team}
        query_result = _safe_getattr_call(wit_client, "query_by_id", id, team_context, timePrecision, top)
        result_data = to_primitive(query_result)

        if responseType == "ids":
            work_items = result_data.get("workItems") or result_data.get("work_items") or []
            ids = [item.get("id") for item in work_items if item.get("id") is not None]
            return {"ids": ids, "count": len(ids)}

        return result_data

    @mcp.tool(name="wit_update_work_items_batch", description="Update work items in batch.")
    def wit_update_work_items_batch(updates: list[dict[str, Any]]) -> dict[str, Any]:
        if not updates:
            raise ValueError("updates must contain at least one update operation")

        grouped: dict[int, list[dict[str, Any]]] = {}
        for update in updates:
            work_item_id = int(update.get("id"))
            grouped.setdefault(work_item_id, []).append(update)

        body: list[dict[str, Any]] = []
        for work_item_id, item_updates in grouped.items():
            operations: list[dict[str, Any]] = []
            for item in item_updates:
                op = str(item.get("op", "Add"))
                path = str(item.get("path", ""))
                value = item.get("value")
                format_name = item.get("format")
                operation: dict[str, Any] = {"op": op, "path": path}
                if op.lower() != "remove":
                    operation["value"] = _field_value(str(value or ""), format_name)
                operations.append(operation)
                if str(format_name or "").lower() == "markdown" and isinstance(value, str) and len(value) > 50:
                    operations.append(
                        {
                            "op": "Add",
                            "path": f"/multilineFieldsFormat{path.replace('/fields', '')}",
                            "value": "Markdown",
                        }
                    )

            body.append(
                {
                    "method": "PATCH",
                    "uri": f"/_apis/wit/workitems/{work_item_id}?api-version={_BATCH_API_VERSION}",
                    "headers": {"Content-Type": "application/json-patch+json"},
                    "body": operations,
                }
            )

        return _ado_json_request(
            clients,
            "PATCH",
            f"_apis/wit/$batch",
            query={"api-version": _BATCH_API_VERSION},
            body=body,
        )

    @mcp.tool(name="wit_work_items_link", description="Link work items together in batch.")
    def wit_work_items_link(project: str, updates: list[dict[str, Any]]) -> dict[str, Any]:
        if not updates:
            raise ValueError("updates must contain at least one link operation")

        org_url = clients.organization_url.rstrip("/")
        grouped: dict[int, list[dict[str, Any]]] = {}
        for update in updates:
            grouped.setdefault(int(update.get("id")), []).append(update)

        body: list[dict[str, Any]] = []
        for source_id, item_updates in grouped.items():
            link_ops: list[dict[str, Any]] = []
            for update in item_updates:
                link_to_id = int(update.get("linkToId"))
                link_type = _get_link_type_from_name(str(update.get("type", "related")))
                comment = str(update.get("comment") or "")
                link_ops.append(
                    {
                        "op": "add",
                        "path": "/relations/-",
                        "value": {
                            "rel": link_type,
                            "url": f"{org_url}/{urllib.parse.quote(project)}/_apis/wit/workItems/{link_to_id}",
                            "attributes": {"comment": comment},
                        },
                    }
                )

            body.append(
                {
                    "method": "PATCH",
                    "uri": f"/_apis/wit/workitems/{source_id}?api-version={_BATCH_API_VERSION}",
                    "headers": {"Content-Type": "application/json-patch+json"},
                    "body": link_ops,
                }
            )

        return _ado_json_request(
            clients,
            "PATCH",
            f"_apis/wit/$batch",
            query={"api-version": _BATCH_API_VERSION},
            body=body,
        )

    @mcp.tool(name="wit_work_item_unlink", description="Remove one or many links from a single work item.")
    def wit_work_item_unlink(project: str, id: int, type: str = "related", url: str | None = None) -> dict[str, Any]:
        wit_client = clients.work_item_tracking()
        work_item = _safe_getattr_call(wit_client, "get_work_item", id, None, None, "relations", project)
        work_item_data = to_primitive(work_item)
        relations = work_item_data.get("relations") or []
        link_type = _get_link_type_from_name(type)

        if url:
            indexes = [idx for idx, relation in enumerate(relations) if relation.get("url") == url]
        else:
            indexes = [idx for idx, relation in enumerate(relations) if relation.get("rel") == link_type]

        if not indexes:
            return {"removed": 0, "message": "No matching relations found.", "relations": relations}

        indexes.sort(reverse=True)
        remove_ops = [{"op": "remove", "path": f"/relations/{idx}"} for idx in indexes]
        updated = _safe_getattr_call(wit_client, "update_work_item", None, remove_ops, id, project)
        return {
            "removed": len(indexes),
            "removedRelations": [relations[idx] for idx in sorted(indexes)],
            "updatedWorkItem": to_primitive(updated),
        }

    @mcp.tool(name="wit_add_child_work_items", description="Create one or many child work items from a parent work item.")
    def wit_add_child_work_items(parentId: int, project: str, workItemType: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            raise ValueError("items must contain at least one child work item definition")
        if len(items) > 50:
            raise ValueError("A maximum of 50 child work items can be created in a single call.")

        org_url = clients.organization_url.rstrip("/")
        body: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or "")
            format_name = str(item.get("format") or "Html")
            if not title:
                raise ValueError("Each child item must include a non-empty title.")

            ops: list[dict[str, Any]] = [
                {"op": "add", "path": "/id", "value": f"-{idx + 1}"},
                {"op": "add", "path": "/fields/System.Title", "value": title},
                {"op": "add", "path": "/fields/System.Description", "value": _field_value(description, format_name)},
                {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.ReproSteps", "value": _field_value(description, format_name)},
                {
                    "op": "add",
                    "path": "/relations/-",
                    "value": {
                        "rel": "System.LinkTypes.Hierarchy-Reverse",
                        "url": f"{org_url}/{urllib.parse.quote(project)}/_apis/wit/workItems/{parentId}",
                    },
                },
            ]

            area_path = str(item.get("areaPath") or "").strip()
            iteration_path = str(item.get("iterationPath") or "").strip()
            if area_path:
                ops.append({"op": "add", "path": "/fields/System.AreaPath", "value": area_path})
            if iteration_path:
                ops.append({"op": "add", "path": "/fields/System.IterationPath", "value": iteration_path})
            if format_name.lower() == "markdown":
                ops.append({"op": "add", "path": "/multilineFieldsFormat/System.Description", "value": "Markdown"})
                ops.append({"op": "add", "path": "/multilineFieldsFormat/Microsoft.VSTS.TCM.ReproSteps", "value": "Markdown"})

            body.append(
                {
                    "method": "PATCH",
                    "uri": f"/{urllib.parse.quote(project)}/_apis/wit/workitems/${urllib.parse.quote(workItemType)}?api-version={_BATCH_API_VERSION}",
                    "headers": {"Content-Type": "application/json-patch+json"},
                    "body": ops,
                }
            )

        return _ado_json_request(
            clients,
            "PATCH",
            "_apis/wit/$batch",
            query={"api-version": _BATCH_API_VERSION},
            body=body,
        )

    @mcp.tool(name="wit_link_work_item_to_pull_request", description="Link a single work item to an existing pull request.")
    def wit_link_work_item_to_pull_request(
        projectId: str,
        repositoryId: str,
        pullRequestId: int,
        workItemId: int,
        pullRequestProjectId: str | None = None,
    ) -> dict[str, Any]:
        artifact_project_id = pullRequestProjectId.strip() if isinstance(pullRequestProjectId, str) and pullRequestProjectId.strip() else projectId
        artifact_path = f"{artifact_project_id}/{repositoryId}/{pullRequestId}"
        vstfs_url = f"vstfs:///Git/PullRequestId/{urllib.parse.quote(artifact_path)}"

        patch_document = [
            {
                "op": "add",
                "path": "/relations/-",
                "value": {
                    "rel": "ArtifactLink",
                    "url": vstfs_url,
                    "attributes": {"name": "Pull Request"},
                },
            }
        ]

        wit_client = clients.work_item_tracking()
        updated = _safe_getattr_call(wit_client, "update_work_item", {}, patch_document, workItemId, projectId)
        return {
            "workItemId": workItemId,
            "pullRequestId": pullRequestId,
            "success": bool(updated),
            "result": to_primitive(updated),
        }

    @mcp.tool(
        name="wit_add_artifact_link",
        description="Add artifact links to work items, optionally building vstfs URI from component parameters.",
    )
    def wit_add_artifact_link(
        workItemId: int,
        project: str,
        artifactUri: str | None = None,
        projectId: str | None = None,
        repositoryId: str | None = None,
        branchName: str | None = None,
        commitId: str | None = None,
        pullRequestId: int | None = None,
        buildId: int | None = None,
        linkType: str = "Branch",
        comment: str | None = None,
    ) -> dict[str, Any]:
        final_artifact_uri = artifactUri
        if not final_artifact_uri:
            if linkType == "Branch":
                if not projectId or not repositoryId or not branchName:
                    raise ValueError("For 'Branch' links, projectId, repositoryId, and branchName are required.")
                final_artifact_uri = f"vstfs:///Git/Ref/{urllib.parse.quote(projectId)}%2F{urllib.parse.quote(repositoryId)}%2FGB{urllib.parse.quote(branchName)}"
            elif linkType == "Fixed in Commit":
                if not projectId or not repositoryId or not commitId:
                    raise ValueError("For 'Fixed in Commit' links, projectId, repositoryId, and commitId are required.")
                final_artifact_uri = f"vstfs:///Git/Commit/{urllib.parse.quote(projectId)}%2F{urllib.parse.quote(repositoryId)}%2F{urllib.parse.quote(commitId)}"
            elif linkType == "Pull Request":
                if not projectId or not repositoryId or pullRequestId is None:
                    raise ValueError("For 'Pull Request' links, projectId, repositoryId, and pullRequestId are required.")
                final_artifact_uri = f"vstfs:///Git/PullRequestId/{urllib.parse.quote(projectId)}%2F{urllib.parse.quote(repositoryId)}%2F{pullRequestId}"
            elif linkType in {"Build", "Found in build", "Integrated in build"}:
                if buildId is None:
                    raise ValueError(f"For '{linkType}' links, buildId is required.")
                final_artifact_uri = f"vstfs:///Build/Build/{buildId}"
            else:
                raise ValueError(f"URI building from components is not supported for link type '{linkType}'. Provide artifactUri.")

        patch_document = [
            {
                "op": "add",
                "path": "/relations/-",
                "value": {
                    "rel": "ArtifactLink",
                    "url": final_artifact_uri,
                    "attributes": {"name": linkType, **({"comment": comment} if comment else {})},
                },
            }
        ]

        wit_client = clients.work_item_tracking()
        updated = _safe_getattr_call(wit_client, "update_work_item", {}, patch_document, workItemId, project)
        return {
            "workItemId": workItemId,
            "artifactUri": final_artifact_uri,
            "linkType": linkType,
            "comment": comment,
            "success": bool(updated),
            "result": to_primitive(updated),
        }

    @mcp.tool(
        name="wit_get_work_item_attachment",
        description="Download a work item attachment and return a base64 data resource.",
    )
    def wit_get_work_item_attachment(project: str, attachmentId: str, fileName: str | None = None) -> dict[str, Any]:
        wit_client = clients.work_item_tracking()
        content = _safe_getattr_call(wit_client, "get_attachment_content", attachmentId, fileName, project)

        raw_bytes: bytes
        if isinstance(content, bytes):
            raw_bytes = content
        elif hasattr(content, "read"):
            raw_bytes = content.read()
        else:
            chunks: list[bytes] = []
            for chunk in content:
                chunks.append(bytes(chunk))
            raw_bytes = b"".join(chunks)

        base64_data = base64.b64encode(raw_bytes).decode("ascii")
        mime_type = _get_mime_type(fileName)
        return {
            "resource": {
                "uri": f"data:{mime_type};base64,{base64_data}",
                "mimeType": mime_type,
                "blob": base64_data,
            }
        }
