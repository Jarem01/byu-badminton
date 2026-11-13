"""Generic dataclass <-> JSON-able (de)serialization driven by type hints.

Keeps the entity dataclasses pure (no serialization boilerplate) while giving
exact, typed round-tripping for the whole ``Tournament`` object graph. Handles
nested dataclasses, ``Optional``, ``list``/``dict``/``tuple``/``set`` and
``Literal`` fields.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from typing import Any, Union, get_args, get_origin, get_type_hints

_hints_cache: dict[type, dict[str, Any]] = {}


def _hints(cls: type) -> dict[str, Any]:
    h = _hints_cache.get(cls)
    if h is None:
        # Resolve string annotations against the class's own module namespace.
        module = __import__(cls.__module__, fromlist=["*"])
        h = get_type_hints(cls, vars(module))
        _hints_cache[cls] = h
    return h


def to_jsonable(obj: Any) -> Any:
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name))
                for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in obj]
    raise TypeError(f"Cannot serialize {type(obj)!r}")


def _is_union(tp: Any) -> bool:
    return get_origin(tp) is Union or get_origin(tp) is types.UnionType


def from_jsonable(tp: Any, data: Any) -> Any:
    # Any / unannotated: pass through.
    if tp is Any or tp is None:
        return data

    origin = get_origin(tp)

    if _is_union(tp):
        args = [a for a in get_args(tp) if a is not type(None)]
        if data is None:
            return None
        # Optional[X] and simple unions: use the first non-None arm.
        return from_jsonable(args[0], data)

    if origin is typing.Literal:
        return data  # value already validated by producer

    if origin in (list, set, frozenset):
        (item_t,) = get_args(tp) or (Any,)
        seq = [from_jsonable(item_t, v) for v in (data or [])]
        return seq if origin is list else origin(seq)

    if origin is tuple:
        args = get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(from_jsonable(args[0], v) for v in (data or []))
        return tuple(from_jsonable(a, v) for a, v in zip(args, data or []))

    if origin is dict:
        k_t, v_t = get_args(tp) or (str, Any)
        return {k: from_jsonable(v_t, v) for k, v in (data or {}).items()}

    if dataclasses.is_dataclass(tp) and isinstance(tp, type):
        hints = _hints(tp)
        kwargs = {}
        for f in dataclasses.fields(tp):
            if f.name in data:
                kwargs[f.name] = from_jsonable(hints[f.name], data[f.name])
        return tp(**kwargs)

    # Primitives and anything else.
    return data
