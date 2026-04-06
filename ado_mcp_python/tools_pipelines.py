from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .ado_client import AzureDevOpsClients
from .utils import to_primitive


def _safe_getattr_call(obj: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(obj, method_name, None)
    if not callable(method):
        raise NotImplementedError(f"Azure DevOps Python SDK method '{method_name}' is unavailable in this environment.")
    return method(*args, **kwargs)


def _is_safe_relative_path(path_text: str) -> bool:
    candidate = Path(path_text)
    return not candidate.is_absolute() and ".." not in candidate.parts


def _read_stream_bytes(stream: Any) -> bytes:
    if isinstance(stream, bytes):
        return stream
    if hasattr(stream, "read"):
        return bytes(stream.read())
    chunks: list[bytes] = []
    for chunk in stream:
        chunks.append(bytes(chunk))
    return b"".join(chunks)


def register_pipeline_tools(mcp: FastMCP, clients: AzureDevOpsClients) -> None:
    @mcp.tool(name="pipelines_get_build_definitions", description="Retrieve build definitions for a project.")
    def pipelines_get_build_definitions(
        project: str,
        repositoryId: str | None = None,
        repositoryType: str | None = None,
        name: str | None = None,
        path: str | None = None,
        queryOrder: str | None = None,
        top: int | None = None,
        continuationToken: str | None = None,
        minMetricsTime: str | None = None,
        definitionIds: list[int] | None = None,
        builtAfter: str | None = None,
        notBuiltAfter: str | None = None,
        includeAllProperties: bool | None = None,
        includeLatestBuilds: bool | None = None,
        taskIdFilter: str | None = None,
        processType: int | None = None,
        yamlFilename: str | None = None,
    ) -> list[dict[str, Any]]:
        build_client = clients.build()
        defs = _safe_getattr_call(
            build_client,
            "get_definitions",
            project,
            name,
            repositoryId,
            repositoryType,
            queryOrder,
            top,
            continuationToken,
            minMetricsTime,
            definitionIds,
            path,
            builtAfter,
            notBuiltAfter,
            includeAllProperties,
            includeLatestBuilds,
            taskIdFilter,
            processType,
            yamlFilename,
        )
        return to_primitive(defs)

    @mcp.tool(name="pipelines_create_pipeline", description="Create a pipeline definition with YAML configuration.")
    def pipelines_create_pipeline(
        project: str,
        name: str,
        yamlPath: str,
        repositoryType: str,
        repositoryName: str,
        folder: str | None = None,
        repositoryId: str | None = None,
        repositoryConnectionId: str | None = None,
    ) -> dict[str, Any]:
        pipelines_client = clients.pipelines()

        repository_payload: dict[str, Any] = {"type": repositoryType}
        normalized_repo_type = repositoryType.lower()
        if normalized_repo_type in {"azurereposgit", "tfsgit", "azure_repos_git"}:
            repository_payload["id"] = repositoryId
            repository_payload["name"] = repositoryName
        elif normalized_repo_type == "github":
            if not repositoryConnectionId:
                raise ValueError("repositoryConnectionId is required for GitHub repositories")
            repository_payload["connection"] = {"id": repositoryConnectionId}
            repository_payload["fullname"] = repositoryName
        else:
            raise ValueError("Unsupported repositoryType")

        create_payload = {
            "name": name,
            "folder": folder or "\\",
            "configuration": {
                "type": "yaml",
                "path": yamlPath,
                "repository": repository_payload,
                "variables": None,
            },
        }

        pipeline = _safe_getattr_call(pipelines_client, "create_pipeline", create_payload, project)
        return to_primitive(pipeline)

    @mcp.tool(name="pipelines_get_build_definition_revisions", description="Retrieve revisions for a build definition.")
    def pipelines_get_build_definition_revisions(project: str, definitionId: int) -> list[dict[str, Any]]:
        build_client = clients.build()
        revisions = _safe_getattr_call(build_client, "get_definition_revisions", project, definitionId)
        return to_primitive(revisions)

    @mcp.tool(name="pipelines_get_builds", description="Retrieve builds for a project.")
    def pipelines_get_builds(
        project: str,
        definitions: list[int] | None = None,
        queues: list[int] | None = None,
        buildNumber: str | None = None,
        minTime: str | None = None,
        maxTime: str | None = None,
        requestedFor: str | None = None,
        reasonFilter: int | None = None,
        statusFilter: int | None = None,
        resultFilter: int | None = None,
        tagFilters: list[str] | None = None,
        properties: list[str] | None = None,
        top: int | None = None,
        continuationToken: str | None = None,
        maxBuildsPerDefinition: int | None = None,
        deletedFilter: int | None = None,
        queryOrder: str | None = "QueueTimeDescending",
        branchName: str | None = None,
        buildIds: list[int] | None = None,
        repositoryId: str | None = None,
        repositoryType: str | None = None,
    ) -> list[dict[str, Any]]:
        build_client = clients.build()
        builds = _safe_getattr_call(
            build_client,
            "get_builds",
            project,
            definitions,
            queues,
            buildNumber,
            minTime,
            maxTime,
            requestedFor,
            reasonFilter,
            statusFilter,
            resultFilter,
            tagFilters,
            properties,
            top,
            continuationToken,
            maxBuildsPerDefinition,
            deletedFilter,
            queryOrder,
            branchName,
            buildIds,
            repositoryId,
            repositoryType,
        )
        return to_primitive(builds)

    @mcp.tool(name="pipelines_get_build_log", description="Retrieve logs metadata for a specific build.")
    def pipelines_get_build_log(project: str, buildId: int) -> list[dict[str, Any]]:
        build_client = clients.build()
        logs = _safe_getattr_call(build_client, "get_build_logs", project, buildId)
        return to_primitive(logs)

    @mcp.tool(name="pipelines_get_build_log_by_id", description="Get specific build log content by log ID.")
    def pipelines_get_build_log_by_id(
        project: str,
        buildId: int,
        logId: int,
        startLine: int | None = None,
        endLine: int | None = None,
    ) -> dict[str, Any]:
        build_client = clients.build()
        lines = _safe_getattr_call(build_client, "get_build_log_lines", project, buildId, logId, startLine, endLine)
        data = to_primitive(lines)
        return {"buildId": buildId, "logId": logId, "content": data}

    @mcp.tool(name="pipelines_get_build_changes", description="Get changes associated with a specific build.")
    def pipelines_get_build_changes(
        project: str,
        buildId: int,
        continuationToken: str | None = None,
        top: int = 100,
        includeSourceChange: bool | None = None,
    ) -> list[dict[str, Any]]:
        build_client = clients.build()
        changes = _safe_getattr_call(
            build_client,
            "get_build_changes",
            project,
            buildId,
            continuationToken,
            top,
            includeSourceChange,
        )
        return to_primitive(changes)

    @mcp.tool(name="pipelines_get_run", description="Get a run for a particular pipeline.")
    def pipelines_get_run(project: str, pipelineId: int, runId: int) -> dict[str, Any]:
        pipelines_client = clients.pipelines()
        run = _safe_getattr_call(pipelines_client, "get_run", project, pipelineId, runId)
        return to_primitive(run)

    @mcp.tool(name="pipelines_list_runs", description="List runs for a particular pipeline.")
    def pipelines_list_runs(project: str, pipelineId: int) -> dict[str, Any]:
        pipelines_client = clients.pipelines()
        runs = _safe_getattr_call(pipelines_client, "list_runs", project, pipelineId)
        return to_primitive(runs)

    @mcp.tool(name="pipelines_get_build_status", description="Get build status report by build ID.")
    def pipelines_get_build_status(project: str, buildId: int) -> dict[str, Any]:
        build_client = clients.build()
        build = _safe_getattr_call(build_client, "get_build_report", project, buildId)
        return to_primitive(build)

    @mcp.tool(name="pipelines_update_build_stage", description="Update a specific stage in a build.")
    def pipelines_update_build_stage(
        project: str,
        buildId: int,
        stageName: str,
        status: str,
        forceRetryAllJobs: bool = False,
    ) -> dict[str, Any]:
        build_client = clients.build()
        params = {
            "force_retry_all_jobs": forceRetryAllJobs,
            "state": status,
        }
        updated = _safe_getattr_call(build_client, "update_stage", params, buildId, stageName, project)
        return to_primitive(updated)

    @mcp.tool(name="pipelines_run_pipeline", description="Start a new run of a pipeline.")
    def pipelines_run_pipeline(
        project: str,
        pipelineId: int,
        pipelineVersion: int | None = None,
        previewRun: bool | None = None,
        resources: dict[str, Any] | None = None,
        stagesToSkip: list[str] | None = None,
        templateParameters: dict[str, str] | None = None,
        variables: dict[str, dict[str, Any]] | None = None,
        yamlOverride: str | None = None,
    ) -> dict[str, Any]:
        if not previewRun and yamlOverride:
            raise ValueError("yamlOverride can only be provided when previewRun is true")

        pipelines_client = clients.pipelines()
        run_request = {
            "previewRun": previewRun,
            "resources": resources or {},
            "stagesToSkip": stagesToSkip,
            "templateParameters": templateParameters,
            "variables": variables,
            "yamlOverride": yamlOverride,
        }
        pipeline_run = _safe_getattr_call(pipelines_client, "run_pipeline", run_request, project, pipelineId, pipelineVersion)
        return to_primitive(pipeline_run)

    @mcp.tool(name="pipelines_list_artifacts", description="List artifacts for a given build.")
    def pipelines_list_artifacts(project: str, buildId: int) -> list[dict[str, Any]]:
        build_client = clients.build()
        artifacts = _safe_getattr_call(build_client, "get_artifacts", project, buildId)
        return to_primitive(artifacts)

    @mcp.tool(name="pipelines_download_artifact", description="Download a pipeline artifact.")
    def pipelines_download_artifact(
        project: str,
        buildId: int,
        artifactName: str,
        destinationPath: str | None = None,
    ) -> dict[str, Any]:
        if ".." in artifactName:
            raise ValueError("Invalid artifactName: path traversal is not allowed")
        if destinationPath and not _is_safe_relative_path(destinationPath):
            raise ValueError("Invalid destinationPath: absolute paths and path traversals are not allowed")

        build_client = clients.build()
        artifact = _safe_getattr_call(build_client, "get_artifact", project, buildId, artifactName)
        if not artifact:
            return {"message": f"Artifact {artifactName} not found in build {buildId}."}

        file_stream = _safe_getattr_call(build_client, "get_artifact_content_zip", project, buildId, artifactName)

        if destinationPath:
            dest_root = Path(destinationPath)
            dest_root.mkdir(parents=True, exist_ok=True)
            artifact_file = dest_root / f"{artifactName}.zip"
            artifact_file.write_bytes(_read_stream_bytes(file_stream))
            return {"message": f"Artifact {artifactName} downloaded to {destinationPath}."}

        base64_data = base64.b64encode(_read_stream_bytes(file_stream)).decode("ascii")
        return {
            "resource": {
                "uri": f"data:application/zip;base64,{base64_data}",
                "mimeType": "application/zip",
                "text": base64_data,
            }
        }
