from __future__ import annotations

import inspect

import ado_mcp_python.tools_work_items as mod
from ado_mcp_python.tools_work_items import _get_link_type_from_name, _get_mime_type


def test_link_type_mapping_parent() -> None:
    assert _get_link_type_from_name("parent") == "System.LinkTypes.Hierarchy-Reverse"


def test_link_type_mapping_artifact() -> None:
    assert _get_link_type_from_name("artifact") == "ArtifactLink"


def test_link_type_mapping_invalid_raises() -> None:
    try:
        _get_link_type_from_name("not-a-link")
        raise AssertionError("Expected ValueError for invalid link type")
    except ValueError as exc:
        assert "Unknown link type" in str(exc)


def test_get_mime_type_png() -> None:
    assert _get_mime_type("screenshot.png") == "image/png"


def test_get_mime_type_default() -> None:
    assert _get_mime_type("artifact.unknown") == "application/octet-stream"


def test_work_item_tool_names_present_in_source() -> None:
    src = inspect.getsource(mod)
    expected_names = [
        "wit_my_work_items",
        "wit_list_backlogs",
        "wit_list_backlog_work_items",
        "wit_get_work_item",
        "wit_get_work_items_batch_by_ids",
        "wit_update_work_item",
        "wit_create_work_item",
        "wit_list_work_item_comments",
        "wit_list_work_item_revisions",
        "wit_get_work_items_for_iteration",
        "wit_add_work_item_comment",
        "wit_update_work_item_comment",
        "wit_add_child_work_items",
        "wit_link_work_item_to_pull_request",
        "wit_get_work_item_type",
        "wit_get_query",
        "wit_get_query_results_by_id",
        "wit_update_work_items_batch",
        "wit_work_items_link",
        "wit_work_item_unlink",
        "wit_add_artifact_link",
        "wit_get_work_item_attachment",
    ]

    for name in expected_names:
        assert name in src
