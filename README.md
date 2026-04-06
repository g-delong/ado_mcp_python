# Azure DevOps MCP Server (Python)

Python reimplementation of the TypeScript Azure DevOps MCP server:
https://github.com/microsoft/azure-devops-mcp

## Current state

- MCP server built with `FastMCP`
- Auth modes: `interactive`, `azcli`, `env`, `envvar`
- Domain-based registration
- Implemented domains:
  - `mcp-apps`
  - `core`
  - `repositories`
  - `work`
  - `work-items`
  - `pipelines`
- Test status: `uv run pytest -q` is green in this repo

## Quick start (uv)

### 1. Install dependencies

```powershell
uv sync
```

### 2. Configure environment

Create `.env` from `.env.example`:

```env
ADO_MCP_AUTH_TOKEN=your_pat_here
ADO_ORG=your_org
ADO_PROJECT=your_project
```

`.env` is git-ignored.

### 3. Run server

Organization can be passed explicitly or loaded from `ADO_ORG`.

```powershell
uv run mcp-server-azuredevops-python --authentication env --domains all
```

Explicit organization form:

```powershell
uv run mcp-server-azuredevops-python contoso --authentication env --domains all
```

Azure CLI auth:

```powershell
uv run mcp-server-azuredevops-python contoso --authentication azcli --domains all
```

## Local PAT smoke test

Run:

```powershell
uv run python scripts/smoke_test_pat.py
```

The smoke script validates:

- auth header/custom REST reachability
- core projects
- core teams
- repositories list
- work item WIQL query
- pipeline build definitions

If `uv` cannot update the environment because a running process locks the console script executable, run with:

```powershell
$env:UV_NO_SYNC='1'; uv run python scripts/smoke_test_pat.py
```

## Implemented tools

### mcp-apps

- `mcp_apps_ping`

### core

- `core_list_projects`
- `core_list_project_teams`

### repositories

- `repo_list_repos_by_project`
- `repo_list_pull_requests_by_repo_or_project`
- `repo_get_pull_request_by_id`
- `repo_get_pull_request_changes`
- `repo_list_pull_requests_by_commits`
- `repo_search_commits`
- `repo_get_commit_by_id`
- `repo_create_pull_request`
- `repo_get_repo_by_name_or_id`
- `repo_list_branches_by_repo`
- `repo_list_my_branches_by_repo`
- `repo_get_branch_by_name`
- `repo_create_branch`
- `repo_update_pull_request`
- `repo_update_pull_request_reviewers`
- `repo_list_pull_request_threads`
- `repo_list_pull_request_thread_comments`
- `repo_reply_to_comment`
- `repo_create_pull_request_thread`
- `repo_update_pull_request_thread`
- `repo_vote_pull_request`
- `repo_list_directory`
- `repo_get_file_content`

### work-items

- `wit_my_work_items`
- `wit_list_backlogs`
- `wit_list_backlog_work_items`
- `wit_get_work_item`
- `wit_get_work_items_batch_by_ids`
- `wit_update_work_item`
- `wit_create_work_item`
- `wit_list_work_item_comments`
- `wit_list_work_item_revisions`
- `wit_get_work_items_for_iteration`
- `wit_add_work_item_comment`
- `wit_update_work_item_comment`
- `wit_add_child_work_items`
- `wit_link_work_item_to_pull_request`
- `wit_get_work_item_type`
- `wit_get_query`
- `wit_get_query_results_by_id`
- `wit_update_work_items_batch`
- `wit_work_items_link`
- `wit_work_item_unlink`
- `wit_add_artifact_link`
- `wit_get_work_item_attachment`

### work

- `work_list_team_iterations`
- `work_list_iterations`
- `work_create_iterations`
- `work_assign_iterations`
- `work_get_team_capacity`
- `work_update_team_capacity`
- `work_get_iteration_capacities`
- `work_get_team_settings`

### pipelines

- `pipelines_get_builds`
- `pipelines_get_build_changes`
- `pipelines_get_build_definitions`
- `pipelines_get_build_definition_revisions`
- `pipelines_get_build_log`
- `pipelines_get_build_log_by_id`
- `pipelines_get_build_status`
- `pipelines_update_build_stage`
- `pipelines_create_pipeline`
- `pipelines_get_run`
- `pipelines_list_runs`
- `pipelines_run_pipeline`
- `pipelines_list_artifacts`
- `pipelines_download_artifact`

## Notes

- This is a clean-room Python implementation, not a line-by-line transpile.
- For PAT mode (`env`/`envvar`), custom HTTP calls use Basic auth headers and SDK calls use `BasicAuthentication`.
- Repository tools accepting `repositoryId` support GUID or repository name; when a name is provided, pass `project`.
- `repo_list_directory` and `repo_get_file_content` reject path traversal (`..`) and backslash paths.
- `repo_get_pull_request_changes` returns normalized change metadata with optional file content hydration.

## Remaining scope

Not implemented yet:

- `wiki`
- `search`
- `test-plans`
- `advanced-security`
