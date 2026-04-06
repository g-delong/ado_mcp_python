# Azure DevOps MCP Server (Python)

Python reimplementation scaffold of the TypeScript Azure DevOps MCP server:
https://github.com/microsoft/azure-devops-mcp

## What this currently includes

- MCP server using the Python MCP SDK (`FastMCP`)
- CLI shape similar to upstream:
  - positional `organization`
  - `-d/--domains`
  - `-a/--authentication` (`interactive`, `azcli`, `env`, `envvar`)
  - `-t/--tenant`
- Authentication providers:
  - environment token (`ADO_MCP_AUTH_TOKEN`)
  - Azure CLI token
  - interactive device code flow
- Domain-based tool registration
- Initial implemented domains and tool names:
  - `mcp-apps`: `mcp_apps_ping`
  - `core`: `core_list_projects`, `core_list_project_teams`
  - `repositories`: `repo_list_repos_by_project`, `repo_get_repo_by_name_or_id`, `repo_list_branches_by_repo`, `repo_list_my_branches_by_repo`, `repo_get_branch_by_name`, `repo_create_branch`, `repo_list_pull_requests_by_repo_or_project`, `repo_get_pull_request_by_id`, `repo_get_pull_request_changes`, `repo_list_pull_requests_by_commits`, `repo_list_commits`, `repo_get_commit_by_id`, `repo_create_pull_request`, `repo_update_pull_request`, `repo_update_pull_request_reviewers`, `repo_list_pull_request_threads`, `repo_list_pull_request_thread_comments`, `repo_reply_to_comment`, `repo_create_comment_thread`, `repo_vote_pull_request`, `repo_list_directory`, `repo_get_file_content`
  - `work-items`: `wit_get_work_item`, `wit_get_work_items_batch_by_ids`, `wit_create_work_item`, `wit_update_work_item`
  - `pipelines`: `pipelines_get_build_definitions`, `pipelines_get_builds`, `pipelines_get_build_status`, `pipelines_run_pipeline`

## Quick start

### 1. Create venv and install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

### 2. Run server

```powershell
mcp-server-azuredevops-python contoso --authentication envvar --domains core --domains repositories
```

Or with Azure CLI auth:

```powershell
mcp-server-azuredevops-python contoso --authentication azcli --domains all
```

### 3. Env token mode

```powershell
$env:ADO_MCP_AUTH_TOKEN = "<your-ado-token>"
mcp-server-azuredevops-python contoso --authentication envvar
```

## Parity roadmap

The upstream TypeScript server has a very large toolset. This project is intentionally staged.

### Implemented now

- Server bootstrap and auth model
- Domain filtering
- Core repository/work item/pipeline primitives

### Next recommended milestones

1. Full `repositories` parity:
   - branch tools
   - PR comments/threads/reviewers/votes
   - directory listing/file content at version
   - commit and PR-diff rich helpers
2. Full `work-items` parity:
   - comments, revisions, WIQL queries
   - work item links/artifact links
   - markdown format fields and batch update/create behavior
3. Add remaining domains:
   - `work`, `wiki`, `search`, `test-plans`, `advanced-security`
4. Add prompt-based elicitation parity where MCP client supports it.
5. Add comprehensive tests against mocked Azure DevOps clients, matching upstream test intent.

## Notes

- This is a clean-room Python implementation, not a line-by-line transpile.
- Tool names are intentionally aligned where already implemented to simplify MCP client migrations.
- Repository tools that accept `repositoryId` support GUID or repository name. When a name is used, `project` must be provided.
- `repo_list_pull_requests_by_repo_or_project` supports richer filters (`created_by_me`, `created_by_user`, `i_am_reviewer`, `user_is_reviewer`) using API response filtering. For current-user filters, set `current_user_email` or `ADO_MCP_USER_EMAIL`.
- `repo_get_pull_request_changes` currently returns normalized file-level change metadata rather than full line-by-line diff hunks.
- `repo_get_pull_request_by_id` supports optional `includeWorkItemRefs` and `includeLabels` enrichment.
- `repo_list_directory` and `repo_get_file_content` support `versionType` values (`Branch`, `Tag`, `Commit`).
- `repo_get_pull_request_changes` can optionally hydrate `lineContent` for changed files using source/target branch heuristics by change type and caps content length with `lineContentMaxChars`.
- `repo_update_pull_request` supports autocomplete and completion options (`autoComplete`, `autoCompleteUserId`/`autoCompleteUserEmail`, `mergeStrategy`, `deleteSourceBranch`, `transitionWorkItems`, `bypassReason`) and only applies completion options when explicitly provided.
- `repo_update_pull_request_reviewers` and `repo_vote_pull_request` support email/unique-name resolution through Azure DevOps identities APIs.
- `repo_list_directory` and `repo_get_file_content` now reject path traversal (`..`) and backslash paths.
- `repo_create_comment_thread` validates line-range context combinations and enforces `filePath` when line anchors are provided.
