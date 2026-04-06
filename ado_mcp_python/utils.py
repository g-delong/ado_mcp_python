from __future__ import annotations

from typing import Any


def to_primitive(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [to_primitive(v) for v in value]

    if isinstance(value, tuple):
        return [to_primitive(v) for v in value]

    if isinstance(value, dict):
        return {str(k): to_primitive(v) for k, v in value.items()}

    as_dict = getattr(value, "as_dict", None)
    if callable(as_dict):
        return to_primitive(as_dict())

    model_dict = getattr(value, "__dict__", None)
    if isinstance(model_dict, dict):
        return {str(k): to_primitive(v) for k, v in model_dict.items() if not str(k).startswith("_")}

    return str(value)


def paginate(items: list[Any], top: int = 100, skip: int = 0) -> list[Any]:
    safe_skip = max(skip, 0)
    safe_top = max(top, 0)
    return items[safe_skip : safe_skip + safe_top]
