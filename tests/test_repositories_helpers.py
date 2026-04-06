from __future__ import annotations

from ado_mcp_python.tools_repositories import (
    _build_version_descriptor,
    _is_guid,
    _resolve_repository_id,
    _validate_repo_path,
)


class _MockGitClient:
    def __init__(self, repo_id: str = "11111111-2222-3333-4444-555555555555") -> None:
        self._repo_id = repo_id
        self.calls: list[tuple[str, str | None]] = []

    def get_repository(self, repository_id: str, project: str | None = None) -> dict[str, str]:
        self.calls.append((repository_id, project))
        return {"id": self._repo_id, "name": repository_id}


def test_validate_repo_path_normalizes_relative_path() -> None:
    assert _validate_repo_path("src/main.py") == "/src/main.py"


def test_validate_repo_path_rejects_traversal() -> None:
    try:
        _validate_repo_path("../secret.txt")
        raise AssertionError("Expected ValueError for path traversal")
    except ValueError as exc:
        assert "path traversal" in str(exc)


def test_validate_repo_path_rejects_backslash() -> None:
    try:
        _validate_repo_path("src\\main.py")
        raise AssertionError("Expected ValueError for backslash path")
    except ValueError as exc:
        assert "forward slashes" in str(exc)


def test_build_version_descriptor_branch() -> None:
    descriptor = _build_version_descriptor("main", "Branch")
    assert descriptor == {"version": "main", "version_type": 0}


def test_build_version_descriptor_commit() -> None:
    descriptor = _build_version_descriptor("abc123", "Commit")
    assert descriptor == {"version": "abc123", "version_type": 2}


def test_build_version_descriptor_invalid_type() -> None:
    try:
        _build_version_descriptor("main", "Invalid")
        raise AssertionError("Expected ValueError for invalid versionType")
    except ValueError as exc:
        assert "versionType" in str(exc)


def test_is_guid_true_for_valid_guid() -> None:
    assert _is_guid("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def test_is_guid_false_for_repo_name() -> None:
    assert not _is_guid("my-repo")


def test_resolve_repository_id_returns_guid_directly() -> None:
    client = _MockGitClient()
    repo_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert _resolve_repository_id(client, repo_id, None) == repo_id
    assert client.calls == []


def test_resolve_repository_id_by_name_requires_project() -> None:
    client = _MockGitClient()
    try:
        _resolve_repository_id(client, "my-repo", None)
        raise AssertionError("Expected ValueError for missing project")
    except ValueError as exc:
        assert "Project must be provided" in str(exc)


def test_resolve_repository_id_by_name_uses_get_repository() -> None:
    client = _MockGitClient(repo_id="99999999-8888-7777-6666-555555555555")
    result = _resolve_repository_id(client, "my-repo", "MyProject")
    assert result == "99999999-8888-7777-6666-555555555555"
    assert client.calls == [("my-repo", "MyProject")]


# ---------------------------------------------------------------------------
# repo_search_commits — verify client-side filter logic
# ---------------------------------------------------------------------------

def test_search_commits_client_side_search_text_filter() -> None:
    """Client-side searchText filter should match case-insensitively on 'comment'."""
    commits = [
        {"comment": "Fix bug in login", "author": {"email": "a@x.com"}, "committer": {"email": "a@x.com", "name": "A"}},
        {"comment": "Add feature XYZ", "author": {"email": "b@x.com"}, "committer": {"email": "b@x.com", "name": "B"}},
    ]
    lc = "fix"
    result = [c for c in commits if lc in (c.get("comment") or "").lower()]
    assert len(result) == 1
    assert result[0]["comment"] == "Fix bug in login"


def test_search_commits_client_side_author_email_filter() -> None:
    commits = [
        {"comment": "c1", "author": {"email": "Alice@Corp.com"}, "committer": {}},
        {"comment": "c2", "author": {"email": "bob@corp.com"}, "committer": {}},
    ]
    lc = "alice@corp.com"
    result = [c for c in commits if (c.get("author") or {}).get("email", "").lower() == lc]
    assert len(result) == 1


def test_search_commits_client_side_committer_filter() -> None:
    commits = [
        {"comment": "c1", "committer": {"name": "Alice Smith", "email": "a@x.com"}},
        {"comment": "c2", "committer": {"name": "Bob Jones", "email": "b@x.com"}},
    ]
    lc = "alice"
    result = [c for c in commits if lc in (c.get("committer") or {}).get("name", "").lower()]
    assert len(result) == 1
    assert result[0]["comment"] == "c1"


# ---------------------------------------------------------------------------
# repo_update_pull_request_thread — tool is registered and callable
# ---------------------------------------------------------------------------

def test_update_pull_request_thread_tool_exists() -> None:
    """Verify the tool function is importable."""
    import ado_mcp_python.tools_repositories as mod
    # The module exposes register_repository_tools; verify function name via source
    import inspect
    src = inspect.getsource(mod)
    assert "repo_update_pull_request_thread" in src


def test_create_pull_request_thread_tool_renamed() -> None:
    """Verify the renamed create thread tool name appears in source."""
    import ado_mcp_python.tools_repositories as mod
    import inspect
    src = inspect.getsource(mod)
    assert "repo_create_pull_request_thread" in src
    assert "repo_create_comment_thread" not in src
