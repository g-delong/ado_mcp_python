from __future__ import annotations

import inspect

import ado_mcp_python.tools_pipelines as mod
from ado_mcp_python.tools_pipelines import _is_safe_relative_path


def test_safe_relative_path_accepts_simple_relative() -> None:
    assert _is_safe_relative_path("artifacts")


def test_safe_relative_path_rejects_traversal() -> None:
    assert not _is_safe_relative_path("../artifacts")


def test_safe_relative_path_rejects_absolute_windows_path() -> None:
    assert not _is_safe_relative_path("C:/temp")


def test_pipeline_tool_names_present_in_source() -> None:
    src = inspect.getsource(mod)
    expected_names = [
        "pipelines_get_builds",
        "pipelines_get_build_changes",
        "pipelines_get_build_definitions",
        "pipelines_get_build_definition_revisions",
        "pipelines_get_build_log",
        "pipelines_get_build_log_by_id",
        "pipelines_get_build_status",
        "pipelines_update_build_stage",
        "pipelines_create_pipeline",
        "pipelines_get_run",
        "pipelines_list_runs",
        "pipelines_run_pipeline",
        "pipelines_list_artifacts",
        "pipelines_download_artifact",
    ]

    for name in expected_names:
        assert name in src
