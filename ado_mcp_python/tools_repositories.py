from __future__ import annotations

import base64
import json
import os
import posixpath
import re
import urllib.parse
import urllib.request
import urllib.error
from typing import Any

from mcp.server.fastmcp import FastMCP

from .ado_client import AzureDevOpsClients
from .utils import paginate, to_primitive


_PR_STATUS_TO_INT = {
    "NotSet": 0,
    "Active": 1,
    "Abandoned": 2,
    "Completed": 3,
    "All": 4,
}


def _normalize_ref_name(branch_name: str) -> str:
    return branch_name if branch_name.startswith("refs/") else f"refs/heads/{branch_name}"


def _safe_getattr_call(obj: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    method = getattr(obj, method_name, None)
    if not callable(method):
        raise NotImplementedError(f"Azure DevOps Python SDK method '{method_name}' is unavailable in this environment.")
    return method(*args, **kwargs)


def _pr_status_value(status: str) -> int:
    return _PR_STATUS_TO_INT.get(status, _PR_STATUS_TO_INT["Active"])


_PR_QUERY_TYPE_TO_INT = {
    "LastMergeCommit": 1,
    "Commit": 2,
}

_VERSION_TYPE_TO_INT = {
    "Branch": 0,
    "Tag": 1,
    "Commit": 2,
}

_MERGE_STRATEGY_TO_INT = {
    "NoFastForward": 1,
    "Squash": 2,
    "Rebase": 3,
    "RebaseMerge": 4,
}

_GUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _value_ci(value: Any) -> str:
    return str(value or "").lower()


def _resolve_current_user_email(current_user_email: str | None) -> str | None:
    if current_user_email:
        return current_user_email
    return os.getenv("ADO_MCP_USER_EMAIL")


def _pr_created_by_email(pr: dict[str, Any]) -> str:
    created_by = pr.get("createdBy") or pr.get("created_by") or {}
    return _value_ci(created_by.get("uniqueName") or created_by.get("mailAddress") or created_by.get("displayName"))


def _pr_reviewer_emails(pr: dict[str, Any]) -> set[str]:
    reviewers = pr.get("reviewers") or []
    values: set[str] = set()
    for reviewer in reviewers:
        values.add(_value_ci(reviewer.get("uniqueName") or reviewer.get("mailAddress") or reviewer.get("displayName")))
    return values


def _build_version_descriptor(version: str | None, version_type: str | None) -> dict[str, Any] | None:
    if not version:
        return None

    descriptor: dict[str, Any] = {"version": version}
    if version_type:
        mapped = _VERSION_TYPE_TO_INT.get(version_type)
        if mapped is None:
            raise ValueError("versionType must be one of: Branch, Tag, Commit")
        descriptor["version_type"] = mapped
    return descriptor


def _is_guid(value: str) -> bool:
    return bool(_GUID_PATTERN.match(value))


def _resolve_repository_id(git_client: Any, repository_id_or_name: str, project: str | None) -> str:
    if _is_guid(repository_id_or_name):
        return repository_id_or_name

    if not project:
        raise ValueError("Project must be provided when repositoryId is a repository name instead of a GUID.")

    repo = _safe_getattr_call(git_client, "get_repository", repository_id=repository_id_or_name, project=project)
    repo_data = to_primitive(repo) or {}
    resolved_id = repo_data.get("id")
    if not resolved_id:
        raise ValueError(f"Could not resolve repository name '{repository_id_or_name}' in project '{project}'.")
    return str(resolved_id)


def _validate_repo_path(path: str) -> str:
    if not path:
        raise ValueError("path cannot be empty.")

    normalized = path if path.startswith("/") else f"/{path}"
    if "\\" in normalized:
        raise ValueError("path must use forward slashes.")

    segments = [s for s in normalized.split("/") if s]
    if any(segment == ".." for segment in segments):
        raise ValueError("path traversal is not allowed.")

    return posixpath.normpath(normalized)


def _resolve_identity_id(clients: AzureDevOpsClients, user_email: str) -> str:
    authorization = clients.authorization_header()
    org_url = clients.organization_url.rstrip("/")

    if "/" not in org_url:
        raise ValueError("Invalid organization URL.")
    org_name = org_url.rsplit("/", 1)[-1]

    query = urllib.parse.urlencode(
        {
            "searchFilter": "General",
            "filterValue": user_email,
            "queryMembership": "None",
            "api-version": "7.1-preview.1",
        }
    )
    url = f"https://vssps.dev.azure.com/{org_name}/_apis/identities?{query}"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": authorization,
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="ignore")
        raise ValueError(f"Failed to resolve identity for '{user_email}': HTTP {exc.code} {message}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Failed to resolve identity for '{user_email}': {exc.reason}") from exc

    items = payload.get("value") or []
    if not items:
        raise ValueError(f"No user found for email/unique name: {user_email}")

    user_id = items[0].get("id")
    if not user_id:
        raise ValueError(f"Identity record for {user_email} did not include an id.")

    return str(user_id)


def _fetch_file_text(
    git_client: Any,
    repository_id: str,
    path: str,
    project: str | None,
    version: str | None,
    version_type: str | None,
) -> str | None:
    descriptor = _build_version_descriptor(version, version_type)
    try:
        item = _safe_getattr_call(
            git_client,
            "get_item",
            repository_id=repository_id,
            path=path,
            project=project,
            include_content=True,
            version_descriptor=descriptor,
        )
        data = to_primitive(item) or {}
        content = data.get("content")
        if isinstance(content, str):
            return content
        return None
    except Exception:
        return None


def register_repository_tools(mcp: FastMCP, clients: AzureDevOpsClients) -> None:
    @mcp.tool(name="repo_list_repos_by_project", description="Retrieve a list of repositories for a given project.")
    def repo_list_repos_by_project(project: str, top: int = 100, skip: int = 0, repoNameFilter: str | None = None) -> list[dict[str, Any]]:
        git_client = clients.git()
        repos = git_client.get_repositories(project=project, include_hidden=False)
        data = to_primitive(repos) or []

        if repoNameFilter:
            needle = repoNameFilter.lower()
            data = [r for r in data if needle in (r.get("name") or "").lower()]

        data.sort(key=lambda r: (r.get("name") or "").lower())
        return paginate(data, top=top, skip=skip)

    @mcp.tool(
        name="repo_list_pull_requests_by_repo_or_project",
        description="Retrieve pull requests for a repository or project.",
    )
    def repo_list_pull_requests_by_repo_or_project(
        repositoryId: str | None = None,
        project: str | None = None,
        status: str = "Active",
        sourceRefName: str | None = None,
        targetRefName: str | None = None,
        created_by_me: bool = False,
        created_by_user: str | None = None,
        i_am_reviewer: bool = False,
        user_is_reviewer: str | None = None,
        current_user_email: str | None = None,
        top: int = 100,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        if not repositoryId and not project:
            raise ValueError("Either repositoryId or project must be provided.")

        git_client = clients.git()
        criteria: dict[str, Any] = {"status": _pr_status_value(status)}
        resolved_repository_id: str | None = None
        if repositoryId:
            resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
            criteria["repository_id"] = resolved_repository_id
        if sourceRefName:
            criteria["source_ref_name"] = sourceRefName
        if targetRefName:
            criteria["target_ref_name"] = targetRefName

        if resolved_repository_id:
            prs = git_client.get_pull_requests(
            repository_id=resolved_repository_id,
                search_criteria=criteria,
                project=project,
                skip=skip,
                top=top,
            )
        else:
            prs = git_client.get_pull_requests_by_project(
                project=project,
                search_criteria=criteria,
                skip=skip,
                top=top,
            )

        data = to_primitive(prs) or []

        if created_by_user:
            creator = _value_ci(created_by_user)
            data = [pr for pr in data if _pr_created_by_email(pr) == creator]

        if user_is_reviewer:
            reviewer = _value_ci(user_is_reviewer)
            data = [pr for pr in data if reviewer in _pr_reviewer_emails(pr)]

        current_user = _resolve_current_user_email(current_user_email)

        if created_by_me:
            if not current_user:
                raise ValueError("created_by_me requires current_user_email or ADO_MCP_USER_EMAIL.")
            creator = _value_ci(current_user)
            data = [pr for pr in data if _pr_created_by_email(pr) == creator]

        if i_am_reviewer:
            if not current_user:
                raise ValueError("i_am_reviewer requires current_user_email or ADO_MCP_USER_EMAIL.")
            reviewer = _value_ci(current_user)
            data = [pr for pr in data if reviewer in _pr_reviewer_emails(pr)]

        return data

    @mcp.tool(name="repo_get_pull_request_by_id", description="Get a pull request by its ID.")
    def repo_get_pull_request_by_id(
        repositoryId: str,
        pullRequestId: int,
        project: str | None = None,
        includeWorkItemRefs: bool = False,
        includeLabels: bool = False,
    ) -> dict[str, Any]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        try:
            pr = _safe_getattr_call(
                git_client,
                "get_pull_request",
                repository_id=resolved_repository_id,
                pull_request_id=pullRequestId,
                project=project,
                include_work_item_refs=includeWorkItemRefs,
            )
        except TypeError:
            pr = _safe_getattr_call(
                git_client,
                "get_pull_request",
                repository_id=resolved_repository_id,
                pull_request_id=pullRequestId,
                project=project,
            )

        result = to_primitive(pr)

        if includeLabels:
            try:
                labels = _safe_getattr_call(
                    git_client,
                    "get_pull_request_labels",
                    repository_id=resolved_repository_id,
                    pull_request_id=pullRequestId,
                    project=project,
                )
                labels_data = to_primitive(labels) or []
                label_names = [x.get("name") for x in labels_data if x.get("name")]
                result["labelSummary"] = {
                    "labels": label_names,
                    "labelCount": len(label_names),
                }
            except Exception as exc:
                result["labelSummaryError"] = str(exc)

        return result

    @mcp.tool(
        name="repo_get_pull_request_changes",
        description="Get pull request iteration changes and optional compare metadata.",
    )
    def repo_get_pull_request_changes(
        repositoryId: str,
        pullRequestId: int,
        iterationId: int | None = None,
        project: str | None = None,
        top: int = 100,
        skip: int = 0,
        compareTo: int | None = None,
        includeDiffs: bool = True,
        includeLineContent: bool = True,
        lineContentMaxChars: int = 2000,
    ) -> dict[str, Any]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)

        resolved_iteration = iterationId
        if resolved_iteration is None:
            iterations = _safe_getattr_call(
                git_client,
                "get_pull_request_iterations",
                repository_id=resolved_repository_id,
                pull_request_id=pullRequestId,
                project=project,
            )
            iteration_data = to_primitive(iterations) or []
            if not iteration_data:
                raise ValueError("No pull request iterations found.")
            resolved_iteration = max(int(x.get("id") or 0) for x in iteration_data)

        try:
            changes = _safe_getattr_call(
                git_client,
                "get_pull_request_iteration_changes",
                repository_id=resolved_repository_id,
                pull_request_id=pullRequestId,
                iteration_id=resolved_iteration,
                project=project,
                top=top,
                skip=skip,
                compare_to=compareTo,
            )
        except TypeError:
            # Older SDK variants may not support compare_to named arg.
            changes = _safe_getattr_call(
                git_client,
                "get_pull_request_iteration_changes",
                repository_id=resolved_repository_id,
                pull_request_id=pullRequestId,
                iteration_id=resolved_iteration,
                project=project,
                top=top,
                skip=skip,
            )
        changes_data = to_primitive(changes) or {}

        if not includeDiffs:
            return {
                "repositoryId": repositoryId,
                "pullRequestId": pullRequestId,
                "iterationId": resolved_iteration,
                "changes": changes_data,
            }

        # The Python SDK surface does not expose rich line-by-line diff blocks in a consistent way
        # across versions, so this tool returns normalized change entries plus optional file metadata.
        change_entries = changes_data.get("changeEntries") or changes_data.get("change_entries") or []
        source_branch: str | None = None
        target_branch: str | None = None
        if includeLineContent:
            try:
                pr = _safe_getattr_call(
                    git_client,
                    "get_pull_request",
                    repository_id=resolved_repository_id,
                    pull_request_id=pullRequestId,
                    project=project,
                )
                pr_data = to_primitive(pr) or {}
                source_branch = pr_data.get("sourceRefName") or pr_data.get("source_ref_name")
                target_branch = pr_data.get("targetRefName") or pr_data.get("target_ref_name")
                if isinstance(source_branch, str) and source_branch.startswith("refs/heads/"):
                    source_branch = source_branch[len("refs/heads/") :]
                if isinstance(target_branch, str) and target_branch.startswith("refs/heads/"):
                    target_branch = target_branch[len("refs/heads/") :]
            except Exception:
                source_branch = None
                target_branch = None

        normalized_entries: list[dict[str, Any]] = []
        for entry in change_entries:
            item = entry.get("item") or {}
            item_path = item.get("path")
            original_path = entry.get("originalPath") or entry.get("original_path") or item_path
            change_type_value = entry.get("changeType") or entry.get("change_type")
            change_type_text = _value_ci(change_type_value)

            is_delete = change_type_text in {"2", "delete", "deleting"} or "delete" in change_type_text
            is_add = change_type_text in {"1", "add", "adding"} or "add" in change_type_text
            is_rename = "rename" in change_type_text or "rename" in _value_ci(entry.get("changeTypeExtended") or "")

            line_content: str | None = None
            if includeLineContent and isinstance(item_path, str):
                if is_delete and target_branch and isinstance(original_path, str):
                    line_content = _fetch_file_text(
                        git_client,
                        repository_id=resolved_repository_id,
                        path=original_path,
                        project=project,
                        version=target_branch,
                        version_type="Branch",
                    )
                elif source_branch:
                    path_for_source = item_path
                    if is_rename and isinstance(item_path, str):
                        path_for_source = item_path
                    line_content = _fetch_file_text(
                        git_client,
                        repository_id=resolved_repository_id,
                        path=path_for_source,
                        project=project,
                        version=source_branch,
                        version_type="Branch",
                    )
                if isinstance(line_content, str):
                    line_content = line_content[: max(0, lineContentMaxChars)]

            normalized_entries.append(
                {
                    "changeType": change_type_value,
                    "path": item_path,
                    "originalPath": original_path,
                    "objectId": item.get("objectId") or item.get("object_id"),
                    "gitObjectType": item.get("gitObjectType") or item.get("git_object_type"),
                    "isAdd": is_add,
                    "isDelete": is_delete,
                    "isRename": is_rename,
                    "lineContent": line_content,
                }
            )

        return {
            "repositoryId": repositoryId,
            "pullRequestId": pullRequestId,
            "iterationId": resolved_iteration,
            "includeLineContentRequested": includeLineContent,
            "diffMode": "metadata",
            "changes": normalized_entries,
            "raw": changes_data,
        }

    @mcp.tool(
        name="repo_list_pull_requests_by_commits",
        description="List pull requests by commit IDs.",
    )
    def repo_list_pull_requests_by_commits(
        project: str,
        repository: str,
        commits: list[str],
        queryType: str = "LastMergeCommit",
    ) -> dict[str, Any]:
        if not commits:
            raise ValueError("commits cannot be empty.")

        qtype = _PR_QUERY_TYPE_TO_INT.get(queryType)
        if qtype is None:
            raise ValueError("queryType must be one of: LastMergeCommit, Commit")

        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repository, project)
        query_payload = {
            "queries": [
                {
                    "items": commits,
                    "type": qtype,
                }
            ]
        }
        try:
            result = _safe_getattr_call(
                git_client,
                "get_pull_request_query",
                query=query_payload,
                repository_id=resolved_repository_id,
                project=project,
            )
        except TypeError:
            # Alternate generated signatures in some SDK versions.
            result = _safe_getattr_call(
                git_client,
                "get_pull_request_query",
                queries=query_payload,
                repository_id=resolved_repository_id,
                project=project,
            )
        return to_primitive(result)

    @mcp.tool(
        name="repo_search_commits",
        description=(
            "Search for commits in a repository with comprehensive filtering capabilities. "
            "Supports searching by description/comment text, time range, author, committer, "
            "specific commit IDs, and more. This is the unified tool for all commit search operations."
        ),
    )
    def repo_search_commits(
        project: str,
        repository: str,
        fromCommit: str | None = None,
        toCommit: str | None = None,
        version: str | None = None,
        versionType: str | None = None,
        skip: int = 0,
        top: int = 10,
        searchText: str | None = None,
        author: str | None = None,
        authorEmail: str | None = None,
        committer: str | None = None,
        committerEmail: str | None = None,
        fromDate: str | None = None,
        toDate: str | None = None,
        includeWorkItems: bool = False,
        includeLinks: bool = False,
        commitIds: list[str] | None = None,
        historySimplificationMode: str | None = None,
    ) -> list[dict[str, Any]]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repository, project)

        # When specific commit IDs are provided, retrieve them individually.
        if commitIds:
            results = []
            batch_size = min(top, len(commitIds))
            requested = commitIds[skip : skip + batch_size]
            for cid in requested:
                try:
                    sub_criteria: dict[str, Any] = {
                        "from_commit_id": cid,
                        "to_commit_id": cid,
                        "include_links": includeLinks,
                        "include_work_items": includeWorkItems,
                    }
                    found = _safe_getattr_call(
                        git_client,
                        "get_commits",
                        repository_id=resolved_repository_id,
                        search_criteria=sub_criteria,
                        project=project,
                    )
                    if found:
                        results.append(to_primitive(found[0]))
                    else:
                        results.append({"commitId": cid, "error": "not found"})
                except Exception as e:
                    results.append({"commitId": cid, "error": str(e)})
            return results

        criteria: dict[str, Any] = {
            "$top": max(0, top),
            "$skip": max(0, skip),
            "include_links": includeLinks,
            "include_work_items": includeWorkItems,
        }

        if fromCommit:
            criteria["from_commit_id"] = fromCommit
        if toCommit:
            criteria["to_commit_id"] = toCommit
        if version:
            criteria["item_version"] = _build_version_descriptor(version, versionType)
        if author:
            criteria["author"] = author
        if fromDate:
            criteria["from_date"] = fromDate
        if toDate:
            criteria["to_date"] = toDate
        if historySimplificationMode:
            # forward-compat: pass through if SDK accepts it
            criteria["history_mode"] = historySimplificationMode

        try:
            commits = _safe_getattr_call(
                git_client,
                "get_commits",
                repository_id=resolved_repository_id,
                search_criteria=criteria,
                project=project,
            )
        except TypeError:
            commits = _safe_getattr_call(
                git_client,
                "get_commits",
                repository_id=resolved_repository_id,
                project=project,
                search_criteria=criteria,
            )

        result = to_primitive(commits) if commits else []

        # Client-side filters not natively supported by the API
        if searchText:
            lc = searchText.lower()
            result = [c for c in result if lc in (c.get("comment") or "").lower()]
        if authorEmail:
            lc = authorEmail.lower()
            result = [c for c in result if (c.get("author") or {}).get("email", "").lower() == lc]
        if committer:
            lc = committer.lower()
            result = [
                c for c in result
                if lc in (c.get("committer") or {}).get("name", "").lower()
                or lc in (c.get("committer") or {}).get("email", "").lower()
            ]
        if committerEmail:
            lc = committerEmail.lower()
            result = [c for c in result if (c.get("committer") or {}).get("email", "").lower() == lc]

        return result

    @mcp.tool(
        name="repo_get_commit_by_id",
        description="Get a specific commit by commit ID.",
    )
    def repo_get_commit_by_id(
        project: str,
        repository: str,
        commitId: str,
        changeCount: int = 100,
    ) -> dict[str, Any]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repository, project)
        try:
            commit = _safe_getattr_call(
                git_client,
                "get_commit",
                repository_id=resolved_repository_id,
                commit_id=commitId,
                project=project,
                change_count=max(1, changeCount),
            )
        except TypeError:
            commit = _safe_getattr_call(
                git_client,
                "get_commit",
                repository_id=resolved_repository_id,
                commit_id=commitId,
                project=project,
            )
        return to_primitive(commit)

    @mcp.tool(name="repo_create_pull_request", description="Create a new pull request.")
    def repo_create_pull_request(
        repositoryId: str,
        sourceRefName: str,
        targetRefName: str,
        title: str,
        description: str | None = None,
        isDraft: bool = False,
        project: str | None = None,
    ) -> dict[str, Any]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        payload = {
            "source_ref_name": sourceRefName,
            "target_ref_name": targetRefName,
            "title": title,
            "description": description,
            "is_draft": isDraft,
        }
        created = git_client.create_pull_request(git_pull_request_to_create=payload, repository_id=resolved_repository_id, project=project)
        return to_primitive(created)

    @mcp.tool(name="repo_get_repo_by_name_or_id", description="Get repository details by repo ID or repo name.")
    def repo_get_repo_by_name_or_id(repositoryId: str, project: str | None = None) -> dict[str, Any]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        repo = _safe_getattr_call(git_client, "get_repository", repository_id=resolved_repository_id, project=project)
        return to_primitive(repo)

    @mcp.tool(name="repo_list_branches_by_repo", description="List branches for a repository.")
    def repo_list_branches_by_repo(repositoryId: str, project: str | None = None, top: int = 100, skip: int = 0) -> list[dict[str, Any]]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        refs = _safe_getattr_call(git_client, "get_refs", repository_id=resolved_repository_id, project=project, filter="heads/")
        data = to_primitive(refs) or []
        data.sort(key=lambda x: (x.get("name") or "").lower())
        return paginate(data, top=top, skip=skip)

    @mcp.tool(name="repo_list_my_branches_by_repo", description="List branches authored by the supplied user email.")
    def repo_list_my_branches_by_repo(
        repositoryId: str,
        project: str | None = None,
        userEmail: str | None = None,
        top: int = 100,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        refs = _safe_getattr_call(git_client, "get_refs", repository_id=resolved_repository_id, project=project, filter="heads/")
        data = to_primitive(refs) or []

        if userEmail:
            needle = userEmail.lower()
            data = [
                ref
                for ref in data
                if needle
                in (
                    ((ref.get("creator") or {}).get("unique_name"))
                    or ((ref.get("creator") or {}).get("mail_address"))
                    or ""
                ).lower()
            ]

        data.sort(key=lambda x: (x.get("name") or "").lower())
        return paginate(data, top=top, skip=skip)

    @mcp.tool(name="repo_get_branch_by_name", description="Get a single branch by branch name.")
    def repo_get_branch_by_name(repositoryId: str, branchName: str, project: str | None = None) -> dict[str, Any]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        ref_name = _normalize_ref_name(branchName)
        refs = _safe_getattr_call(git_client, "get_refs", repository_id=resolved_repository_id, project=project, filter=ref_name)
        data = to_primitive(refs) or []
        if not data:
            raise ValueError(f"Branch not found: {branchName}")
        return data[0]

    @mcp.tool(name="repo_create_branch", description="Create a branch from an existing branch or commit.")
    def repo_create_branch(
        repositoryId: str,
        branchName: str,
        sourceRefName: str,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        source_ref = _normalize_ref_name(sourceRefName)
        source_refs = _safe_getattr_call(git_client, "get_refs", repository_id=resolved_repository_id, project=project, filter=source_ref)
        source_data = to_primitive(source_refs) or []
        if not source_data:
            raise ValueError(f"Source branch not found: {sourceRefName}")

        old_object_id = source_data[0].get("object_id") or source_data[0].get("objectId")
        if not old_object_id:
            raise ValueError("Source branch does not contain an object id.")

        create_ref = {
            "name": _normalize_ref_name(branchName),
            "old_object_id": "0000000000000000000000000000000000000000",
            "new_object_id": old_object_id,
        }
        result = _safe_getattr_call(git_client, "update_refs", ref_updates=[create_ref], repository_id=resolved_repository_id, project=project)
        return to_primitive(result)

    @mcp.tool(name="repo_update_pull_request", description="Update pull request metadata.")
    def repo_update_pull_request(
        repositoryId: str,
        pullRequestId: int,
        project: str | None = None,
        title: str | None = None,
        description: str | None = None,
        isDraft: bool | None = None,
        targetRefName: str | None = None,
        status: str | None = None,
        autoComplete: bool | None = None,
        autoCompleteUserId: str | None = None,
        autoCompleteUserEmail: str | None = None,
        mergeStrategy: str | None = None,
        deleteSourceBranch: bool | None = None,
        transitionWorkItems: bool | None = None,
        bypassReason: str | None = None,
    ) -> dict[str, Any]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if isDraft is not None:
            payload["is_draft"] = isDraft
        if targetRefName is not None:
            payload["target_ref_name"] = _normalize_ref_name(targetRefName)
        if status is not None:
            payload["status"] = _pr_status_value(status)

        completion_options: dict[str, Any] = {}
        completion_options_requested = False
        if mergeStrategy is not None:
            mapped_strategy = _MERGE_STRATEGY_TO_INT.get(mergeStrategy)
            if mapped_strategy is None:
                raise ValueError("mergeStrategy must be one of: NoFastForward, Squash, Rebase, RebaseMerge")
            completion_options["merge_strategy"] = mapped_strategy
            completion_options_requested = True
        if deleteSourceBranch is not None:
            completion_options["delete_source_branch"] = bool(deleteSourceBranch)
            completion_options_requested = True
        if transitionWorkItems is not None:
            completion_options["transition_work_items"] = bool(transitionWorkItems)
            completion_options_requested = True
        if bypassReason:
            completion_options["bypass_reason"] = bypassReason
            completion_options_requested = True

        if completion_options_requested:
            payload["completion_options"] = completion_options

        if autoComplete is not None:
            if autoComplete:
                resolved_auto_user_id = autoCompleteUserId
                if not resolved_auto_user_id and autoCompleteUserEmail:
                    resolved_auto_user_id = _resolve_identity_id(clients, autoCompleteUserEmail)
                if not resolved_auto_user_id:
                    raise ValueError("autoComplete=true requires autoCompleteUserId or autoCompleteUserEmail.")
                payload["auto_complete_set_by"] = {"id": resolved_auto_user_id}
            else:
                payload["auto_complete_set_by"] = None

        if not payload:
            raise ValueError("At least one field must be provided for update.")

        updated = _safe_getattr_call(
            git_client,
            "update_pull_request",
            git_pull_request_to_update=payload,
            repository_id=resolved_repository_id,
            pull_request_id=pullRequestId,
            project=project,
        )
        return to_primitive(updated)

    @mcp.tool(name="repo_update_pull_request_reviewers", description="Add or remove pull request reviewers.")
    def repo_update_pull_request_reviewers(
        repositoryId: str,
        pullRequestId: int,
        reviewerIdsToAdd: list[str] | None = None,
        reviewerEmailsToAdd: list[str] | None = None,
        reviewerIdsToRemove: list[str] | None = None,
        reviewerEmailsToRemove: list[str] | None = None,
        project: str | None = None,
    ) -> dict[str, Any]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        added: list[Any] = []
        removed: list[Any] = []

        add_ids = list(reviewerIdsToAdd or [])
        remove_ids = list(reviewerIdsToRemove or [])

        for email in reviewerEmailsToAdd or []:
            add_ids.append(_resolve_identity_id(clients, email))

        for email in reviewerEmailsToRemove or []:
            remove_ids.append(_resolve_identity_id(clients, email))

        for reviewer_id in add_ids:
            result = _safe_getattr_call(
                git_client,
                "create_pull_request_reviewer",
                reviewer={"id": reviewer_id},
                repository_id=resolved_repository_id,
                pull_request_id=pullRequestId,
                reviewer_id=reviewer_id,
                project=project,
            )
            added.append(to_primitive(result))

        for reviewer_id in remove_ids:
            result = _safe_getattr_call(
                git_client,
                "delete_pull_request_reviewer",
                repository_id=resolved_repository_id,
                pull_request_id=pullRequestId,
                reviewer_id=reviewer_id,
                project=project,
            )
            removed.append(to_primitive(result))

        return {"added": added, "removed": removed}

    @mcp.tool(name="repo_list_pull_request_threads", description="List pull request threads.")
    def repo_list_pull_request_threads(
        repositoryId: str,
        pullRequestId: int,
        project: str | None = None,
        top: int = 100,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        threads = _safe_getattr_call(git_client, "get_threads", repository_id=resolved_repository_id, pull_request_id=pullRequestId, project=project)
        data = to_primitive(threads) or []
        data.sort(key=lambda t: int(t.get("id") or 0))
        return paginate(data, top=top, skip=skip)

    @mcp.tool(name="repo_list_pull_request_thread_comments", description="List comments for a pull request thread.")
    def repo_list_pull_request_thread_comments(
        repositoryId: str,
        pullRequestId: int,
        threadId: int,
        project: str | None = None,
        top: int = 100,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        comments = _safe_getattr_call(
            git_client,
            "get_comments",
            repository_id=resolved_repository_id,
            pull_request_id=pullRequestId,
            thread_id=threadId,
            project=project,
        )
        data = to_primitive(comments) or []
        data.sort(key=lambda c: int(c.get("id") or 0))
        return paginate(data, top=top, skip=skip)

    @mcp.tool(name="repo_reply_to_comment", description="Reply to a pull request thread comment.")
    def repo_reply_to_comment(
        repositoryId: str,
        pullRequestId: int,
        threadId: int,
        content: str,
        project: str | None = None,
    ) -> dict[str, Any]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        comment_payload = {"content": content, "comment_type": 1}
        comment = _safe_getattr_call(
            git_client,
            "create_comment",
            comment=comment_payload,
            repository_id=resolved_repository_id,
            pull_request_id=pullRequestId,
            thread_id=threadId,
            project=project,
        )
        return to_primitive(comment)

    @mcp.tool(
        name="repo_create_pull_request_thread",
        description="Create a pull request comment thread, optionally attached to a file line range.",
    )
    def repo_create_pull_request_thread(
        repositoryId: str,
        pullRequestId: int,
        content: str,
        project: str | None = None,
        filePath: str | None = None,
        status: str | None = None,
        rightFileStartLine: int | None = None,
        rightFileStartOffset: int | None = None,
        rightFileEndLine: int | None = None,
        rightFileEndOffset: int | None = None,
    ) -> dict[str, Any]:
        if rightFileStartOffset is not None and rightFileStartLine is None:
            raise ValueError("rightFileStartLine must be specified if rightFileStartOffset is specified.")
        if rightFileEndLine is not None and rightFileStartLine is None:
            raise ValueError("rightFileStartLine must be specified if rightFileEndLine is specified.")
        if rightFileEndOffset is not None and rightFileEndLine is None:
            raise ValueError("rightFileEndLine must be specified if rightFileEndOffset is specified.")
        if rightFileStartLine is not None and rightFileStartLine < 1:
            raise ValueError("rightFileStartLine must be greater than or equal to 1.")
        if rightFileEndLine is not None and rightFileEndLine < 1:
            raise ValueError("rightFileEndLine must be greater than or equal to 1.")
        if rightFileStartOffset is not None and rightFileStartOffset < 1:
            raise ValueError("rightFileStartOffset must be greater than or equal to 1.")
        if rightFileEndOffset is not None and rightFileEndOffset < 1:
            raise ValueError("rightFileEndOffset must be greater than or equal to 1.")
        if rightFileStartLine is not None and rightFileStartOffset is None:
            raise ValueError("rightFileStartOffset must be specified if rightFileStartLine is specified.")
        if rightFileEndLine is not None and rightFileEndOffset is None:
            raise ValueError("rightFileEndOffset must be specified if rightFileEndLine is specified.")
        if (
            rightFileStartLine is not None
            or rightFileStartOffset is not None
            or rightFileEndLine is not None
            or rightFileEndOffset is not None
        ) and not filePath:
            raise ValueError("filePath must be provided when line context is specified.")
        if rightFileStartLine is not None and rightFileEndLine is not None:
            if rightFileEndLine < rightFileStartLine:
                raise ValueError("rightFileEndLine must be greater than or equal to rightFileStartLine.")
            if rightFileEndLine == rightFileStartLine and rightFileStartOffset and rightFileEndOffset and rightFileEndOffset < rightFileStartOffset:
                raise ValueError("rightFileEndOffset must be greater than or equal to rightFileStartOffset when start and end lines are equal.")

        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)

        thread_context: dict[str, Any] | None = None
        if filePath:
            normalized_path = _validate_repo_path(filePath)
            thread_context = {"file_path": normalized_path}

            if rightFileStartLine is not None:
                thread_context["right_file_start"] = {
                    "line": rightFileStartLine,
                    "offset": rightFileStartOffset,
                }
            if rightFileEndLine is not None:
                thread_context["right_file_end"] = {
                    "line": rightFileEndLine,
                    "offset": rightFileEndOffset,
                }

        thread_payload: dict[str, Any] = {
            "comments": [{"content": content, "comment_type": 1}],
        }
        if status:
            thread_payload["status"] = status
        if thread_context:
            thread_payload["thread_context"] = thread_context

        thread = _safe_getattr_call(
            git_client,
            "create_thread",
            comment_thread=thread_payload,
            repository_id=resolved_repository_id,
            pull_request_id=pullRequestId,
            project=project,
        )
        return to_primitive(thread)

    @mcp.tool(
        name="repo_update_pull_request_thread",
        description="Update the status of an existing pull request comment thread (e.g., resolve, close, or reactivate it).",
    )
    def repo_update_pull_request_thread(
        repositoryId: str,
        pullRequestId: int,
        threadId: int,
        status: str,
        project: str | None = None,
    ) -> dict[str, Any]:
        """
        Valid status values (case-insensitive): Active, Resolved, WontFix, Closed, ByDesign, Fixed, Unknown.
        """
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)

        # Build minimal update payload — only status is supported by upstream
        update_payload: dict[str, Any] = {"status": status}

        thread = _safe_getattr_call(
            git_client,
            "update_thread",
            comment_thread=update_payload,
            repository_id=resolved_repository_id,
            pull_request_id=pullRequestId,
            thread_id=threadId,
            project=project,
        )
        if not thread:
            raise ValueError(f"Failed to update thread {threadId}. The thread was not updated successfully.")
        return to_primitive(thread)

    @mcp.tool(name="repo_vote_pull_request", description="Cast a pull request vote for a reviewer identity.")
    def repo_vote_pull_request(
        repositoryId: str,
        pullRequestId: int,
        vote: str,
        reviewerId: str | None = None,
        reviewerEmail: str | None = None,
        project: str | None = None,
    ) -> dict[str, Any]:
        vote_map = {
            "Approved": 10,
            "ApprovedWithSuggestions": 5,
            "NoVote": 0,
            "WaitingForAuthor": -5,
            "Rejected": -10,
        }
        if vote not in vote_map:
            raise ValueError("Invalid vote value.")

        resolved_reviewer_id = reviewerId
        if not resolved_reviewer_id and reviewerEmail:
            resolved_reviewer_id = _resolve_identity_id(clients, reviewerEmail)
        if not resolved_reviewer_id:
            current_user = os.getenv("ADO_MCP_USER_EMAIL")
            if current_user:
                resolved_reviewer_id = _resolve_identity_id(clients, current_user)

        if not resolved_reviewer_id:
            raise ValueError("Provide reviewerId or reviewerEmail, or set ADO_MCP_USER_EMAIL.")

        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        reviewer = _safe_getattr_call(
            git_client,
            "create_pull_request_reviewer",
            reviewer={"id": resolved_reviewer_id, "vote": vote_map[vote]},
            repository_id=resolved_repository_id,
            pull_request_id=pullRequestId,
            reviewer_id=resolved_reviewer_id,
            project=project,
        )
        return to_primitive(reviewer)

    @mcp.tool(name="repo_list_directory", description="List files and folders in a repository directory.")
    def repo_list_directory(
        repositoryId: str,
        path: str = "/",
        project: str | None = None,
        version: str | None = None,
        versionType: str | None = None,
        top: int = 200,
        skip: int = 0,
    ) -> list[dict[str, Any]]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        normalized_path = _validate_repo_path(path)
        version_descriptor = _build_version_descriptor(version, versionType)
        items = _safe_getattr_call(
            git_client,
            "get_items",
            repository_id=resolved_repository_id,
            project=project,
            scope_path=normalized_path,
            recursion_level="OneLevel",
            version_descriptor=version_descriptor,
            include_content_metadata=True,
        )
        data = to_primitive(items) or []
        if normalized_path != "/":
            prefix = normalized_path.rstrip("/") + "/"
            data = [x for x in data if (x.get("path") or "").startswith(prefix) and (x.get("path") or "") != normalized_path]
        data.sort(key=lambda x: (x.get("path") or "").lower())
        return paginate(data, top=top, skip=skip)

    @mcp.tool(name="repo_get_file_content", description="Get file content from a repository at an optional version.")
    def repo_get_file_content(
        repositoryId: str,
        path: str,
        project: str | None = None,
        version: str | None = None,
        versionType: str | None = None,
        asBase64: bool = False,
    ) -> dict[str, Any]:
        git_client = clients.git()
        resolved_repository_id = _resolve_repository_id(git_client, repositoryId, project)
        normalized_path = _validate_repo_path(path)
        version_descriptor = _build_version_descriptor(version, versionType)
        item = _safe_getattr_call(
            git_client,
            "get_item",
            repository_id=resolved_repository_id,
            path=normalized_path,
            project=project,
            include_content=True,
            version_descriptor=version_descriptor,
        )
        data = to_primitive(item)
        content = data.get("content")

        if content is None:
            return {
                "path": normalized_path,
                "message": "File metadata returned, but content was not included by this API response.",
                "item": data,
            }

        if asBase64:
            encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
            return {"path": normalized_path, "encoding": "base64", "content": encoded}

        return {"path": normalized_path, "encoding": "utf-8", "content": content}
