from __future__ import annotations

import inspect

import ado_mcp_python.tools_work as mod
from ado_mcp_python.tools_work import _filter_out_ids, _is_iteration_node


def test_is_iteration_node_true_for_int_enum_value() -> None:
    assert _is_iteration_node({"structureType": 1})


def test_is_iteration_node_true_for_string_value() -> None:
    assert _is_iteration_node({"structureType": "Iteration"})


def test_is_iteration_node_false_for_area() -> None:
    assert not _is_iteration_node({"structureType": 0})


def test_filter_out_ids_removes_nested_nodes() -> None:
    tree = [
        {
            "id": 1,
            "children": [
                {"id": 2, "children": []},
                {"id": 3, "children": []},
            ],
        }
    ]
    out = _filter_out_ids(tree, {2})
    assert out[0]["id"] == 1
    child_ids = [c["id"] for c in out[0]["children"]]
    assert child_ids == [3]


def test_work_tool_names_present_in_source() -> None:
    src = inspect.getsource(mod)
    expected_names = [
        "work_list_team_iterations",
        "work_list_iterations",
        "work_create_iterations",
        "work_assign_iterations",
        "work_get_team_capacity",
        "work_update_team_capacity",
        "work_get_iteration_capacities",
        "work_get_team_settings",
    ]
    for name in expected_names:
        assert name in src
