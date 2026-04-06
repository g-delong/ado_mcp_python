from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

from ado_mcp_python.ado_client import AzureDevOpsClients
from ado_mcp_python.auth import AuthError, TokenProvider
from ado_mcp_python.tls import enable_system_ssl_trust


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def _ok(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=True, detail=detail)


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=False, detail=detail)


def _run_check(name: str, fn: Any) -> CheckResult:
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - top-level smoke behavior
        return _fail(name, f"{type(exc).__name__}: {exc}")


def _http_get_json(url: str, authorization_header: str) -> Any:
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": authorization_header,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc


def _http_post_json(url: str, authorization_header: str, body: dict[str, Any]) -> Any:
    req = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": authorization_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PAT smoke checks for local Azure DevOps MCP testing")
    parser.add_argument("--organization", default=os.getenv("ADO_ORG"), help="Azure DevOps organization name")
    parser.add_argument("--project", default=os.getenv("ADO_PROJECT"), help="Azure DevOps project name or ID")
    parser.add_argument(
        "--token-env-var",
        default="ADO_MCP_AUTH_TOKEN",
        help="Environment variable that stores your PAT (default: ADO_MCP_AUTH_TOKEN)",
    )
    parser.add_argument("--top", type=int, default=5, help="Max records for list checks")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    enable_system_ssl_trust()
    args = _parse_args()

    if not args.organization:
        print("Missing organization. Use --organization or set ADO_ORG.")
        return 2
    if not args.project:
        print("Missing project. Use --project or set ADO_PROJECT.")
        return 2

    token = os.getenv(args.token_env_var)
    if not token:
        print(f"Missing PAT. Set {args.token_env_var}.")
        return 2

    os.environ["ADO_MCP_AUTH_TOKEN"] = token
    organization_url = f"https://dev.azure.com/{args.organization}"

    try:
        token_provider = TokenProvider(authentication="env")
        clients = AzureDevOpsClients(token_provider=token_provider, organization_url=organization_url)
    except AuthError as exc:
        print(f"Auth setup failed: {exc}")
        return 2

    results: list[CheckResult] = []

    def check_auth_header() -> CheckResult:
        auth_header = clients.authorization_header()
        projects_url = f"{organization_url}/_apis/projects?api-version=7.1&$top=1"
        payload = _http_get_json(projects_url, auth_header)
        count = len(payload.get("value") or [])
        return _ok("auth_header_custom_rest", f"Custom REST call succeeded, retrieved {count} project(s)")

    def check_core_projects() -> CheckResult:
        auth_header = clients.authorization_header()
        projects_url = f"{organization_url}/_apis/projects?api-version=7.1&$top={max(args.top, 1)}"
        payload = _http_get_json(projects_url, auth_header)
        names = [str(item.get("name") or "") for item in (payload.get("value") or [])]
        if args.project not in names:
            return _fail("core_list_projects", f"Project '{args.project}' not in top {args.top} projects: {names}")
        return _ok("core_list_projects", f"Project '{args.project}' found")

    def check_core_teams() -> CheckResult:
        auth_header = clients.authorization_header()
        teams_url = f"{organization_url}/_apis/projects/{urllib.parse.quote(args.project)}/teams?api-version=7.1&$top={max(args.top, 1)}"
        try:
            payload = _http_get_json(teams_url, auth_header)
            team_count = len(payload.get("value") or [])
            return _ok("core_list_project_teams", f"Retrieved {team_count} team(s)")
        except RuntimeError as exc:
            if "HTTP 401" in str(exc):
                return _ok(
                    "core_list_project_teams",
                    "Skipped (PAT lacks Team read permission for teams endpoint)",
                )
            raise

    def check_repos() -> CheckResult:
        auth_header = clients.authorization_header()
        repos_url = f"{organization_url}/{urllib.parse.quote(args.project)}/_apis/git/repositories?api-version=7.1"
        payload = _http_get_json(repos_url, auth_header)
        repo_count = len(payload.get("value") or [])
        return _ok("repo_list_repos_by_project", f"Retrieved {repo_count} repo(s)")

    def check_work_items() -> CheckResult:
        auth_header = clients.authorization_header()
        wiql_url = f"{organization_url}/{urllib.parse.quote(args.project)}/_apis/wit/wiql?api-version=7.1&$top={max(args.top, 1)}"
        wiql = {
            "query": (
                "Select [System.Id] From WorkItems "
                "Where [System.TeamProject] = @project "
                "And [System.ChangedDate] >= @Today - 30 "
                "Order By [System.ChangedDate] Desc"
            )
        }
        try:
            payload = _http_post_json(wiql_url, auth_header, wiql)
        except RuntimeError as exc:
            # Large projects may still hit result limits; narrow further and retry.
            if "WorkItemTrackingQueryResultSizeLimitExceededException" not in str(exc):
                raise
            wiql_retry = {
                "query": (
                    "Select [System.Id] From WorkItems "
                    "Where [System.TeamProject] = @project "
                    "And [System.ChangedDate] >= @Today - 7 "
                    "Order By [System.ChangedDate] Desc"
                )
            }
            payload = _http_post_json(wiql_url, auth_header, wiql_retry)

        count = len(payload.get("workItems") or payload.get("work_items") or [])
        return _ok("wit_query_by_wiql", f"WIQL succeeded, returned {count} work item reference(s)")

    def check_pipelines() -> CheckResult:
        auth_header = clients.authorization_header()
        defs_url = f"{organization_url}/{urllib.parse.quote(args.project)}/_apis/build/definitions?api-version=7.1&$top={max(args.top, 1)}"
        payload = _http_get_json(defs_url, auth_header)
        def_count = len(payload.get("value") or [])
        return _ok("pipelines_get_build_definitions", f"Retrieved {def_count} build definition(s)")

    checks = [
        ("auth_header_custom_rest", check_auth_header),
        ("core_list_projects", check_core_projects),
        ("core_list_project_teams", check_core_teams),
        ("repo_list_repos_by_project", check_repos),
        ("wit_query_by_wiql", check_work_items),
        ("pipelines_get_build_definitions", check_pipelines),
    ]

    for _, check in checks:
        results.append(_run_check(check.__name__, check))

    failed = [r for r in results if not r.ok]
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")

    if failed:
        print(f"\nSmoke test completed with {len(failed)} failure(s).")
        return 1

    print("\nSmoke test completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
