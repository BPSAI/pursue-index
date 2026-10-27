"""Validate a tranche-ready record against the vendored schema, no deps.

The poll lane installs only ``requirements-poll.txt`` (hash-locked), which
has no ``jsonschema``. This module interprets the vendored
``schemas/tranche-ready.schema.json`` document directly -- the schema stays
the single source of the rules -- implementing exactly the JSON Schema
2020-12 keywords that document uses. Any other keyword raises
:class:`UnsupportedSchemaError` when the schema is loaded, so a future
schema version that adds one fails closed instead of going half-checked.

Error messages name the field and the rule, never the offending value: the
messages reach an auto-filed issue body and the values are upstream text.

Every error carries ``field``, the ``/``-joined path of the offending value
(``fetch``, ``candidates/0/byte_verdict``), because that is what the poll's
failure issue names. ``format: date-time`` is enforced (RFC 3339), not only
annotated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pursue_index.paths import installed_checkout_root

__all__ = ["SchemaError", "UnsupportedSchemaError", "load_schema", "schema_path", "validate"]

_SCHEMA_RELPATH = Path("schemas") / "tranche-ready.schema.json"

_SUPPORTED = frozenset({
    "$schema", "$id", "$ref", "$defs", "title", "description", "type", "const", "enum",
    "pattern", "maxLength", "minimum", "format", "required", "properties", "additionalProperties",
    "items", "minItems", "maxItems",
})
_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})")
_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,), "array": (list,), "string": (str,), "boolean": (bool,),
    "integer": (int,), "number": (int, float), "null": (type(None),),
}


class UnsupportedSchemaError(ValueError):
    """The schema uses a keyword this validator does not implement."""


@dataclass(frozen=True)
class SchemaError:
    """One violation: the offending value's path and what is wrong."""

    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.field or '<root>'}: {self.message}"


def schema_path() -> Path:
    """The vendored schema in the checkout this code runs from.

    A contract the code enforces, so it is located with the code (as
    ``paths.installed_scripts_dir`` locates scripts), never via the data
    root a CLI run happens to stand in.
    """
    root = installed_checkout_root()
    if root is None:
        raise FileNotFoundError(f"no source checkout to read {_SCHEMA_RELPATH} from")
    return root / _SCHEMA_RELPATH


def load_schema(path: Path | None = None) -> dict[str, Any]:
    """The schema document, refused if it uses an unimplemented keyword."""
    schema = json.loads((path or schema_path()).read_text(encoding="utf-8"))
    _assert_supported(schema, "")
    return schema


def _assert_supported(node: Any, where: str) -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key not in _SUPPORTED:
            raise UnsupportedSchemaError(f"unsupported schema keyword {key!r} at {where or '/'}")
        if key in ("properties", "$defs"):
            for name, sub in value.items():
                _assert_supported(sub, f"{where}/{key}/{name}")
        elif key in ("items", "additionalProperties"):
            _assert_supported(value, f"{where}/{key}")


def validate(instance: Any, schema: dict[str, Any]) -> list[SchemaError]:
    """Every violation of ``schema`` in ``instance`` (empty when valid)."""
    errors: list[SchemaError] = []
    _check(instance, schema, (), schema, errors)
    return errors


def _check(value: Any, node: dict, path: tuple, root: dict, errors: list[SchemaError]) -> None:
    if "$ref" in node:
        node = _resolve(node["$ref"], root)
    where = "/".join(str(p) for p in path)
    if "type" in node and not _is_type(value, node["type"]):
        errors.append(SchemaError(where, f"expected type {node['type']}, got {_json_type(value)}"))
        return
    if "const" in node and not _json_equal(value, node["const"]):
        errors.append(SchemaError(where, f"must equal {node['const']!r}"))
    if "enum" in node and not any(_json_equal(value, e) for e in node["enum"]):
        errors.append(SchemaError(where, f"is not one of {node['enum']!r}"))
    if isinstance(value, str):
        _check_string(value, node, where, errors)
    elif isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in node and value < node["minimum"]:
            errors.append(SchemaError(where, f"is below the minimum {node['minimum']}"))
    elif isinstance(value, dict):
        _check_object(value, node, path, root, errors)
    elif isinstance(value, list):
        _check_array(value, node, path, root, errors)


def _check_string(value: str, node: dict, where: str, errors: list[SchemaError]) -> None:
    if "maxLength" in node and len(value) > node["maxLength"]:
        errors.append(SchemaError(where, f"is longer than {node['maxLength']} characters"))
    if "pattern" in node and re.search(node["pattern"], value) is None:
        errors.append(SchemaError(where, f"does not match {node['pattern']}"))
    if node.get("format") == "date-time" and not _is_date_time(value):
        errors.append(SchemaError(where, "is not an RFC 3339 date-time"))


def _check_object(value: dict, node: dict, path: tuple, root: dict, errors: list) -> None:
    props = node.get("properties", {})
    for name in node.get("required", []):
        if name not in value:
            errors.append(SchemaError("/".join(map(str, (*path, name))), "required property missing"))
    extra = node.get("additionalProperties", True)
    for name, sub in value.items():
        if name in props:
            _check(sub, props[name], (*path, name), root, errors)
        elif extra is False:
            errors.append(SchemaError("/".join(map(str, (*path, name))), "property not allowed"))
        elif isinstance(extra, dict):
            _check(sub, extra, (*path, name), root, errors)


def _check_array(value: list, node: dict, path: tuple, root: dict, errors: list) -> None:
    where = "/".join(map(str, path))
    if len(value) < node.get("minItems", 0):
        errors.append(SchemaError(where, f"needs at least {node['minItems']} item(s)"))
    if "maxItems" in node and len(value) > node["maxItems"]:
        errors.append(SchemaError(where, f"allows at most {node['maxItems']} item(s)"))
    if isinstance(node.get("items"), dict):
        for i, item in enumerate(value):
            _check(item, node["items"], (*path, i), root, errors)


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise UnsupportedSchemaError(f"only local $ref is supported, got {ref!r}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _is_type(value: Any, declared: str | list[str]) -> bool:
    names = [declared] if isinstance(declared, str) else declared
    for name in names:
        if isinstance(value, bool) and name not in ("boolean",):
            continue
        if isinstance(value, _TYPES[name]):
            return True
    return False


def _json_type(value: Any) -> str:
    return next((n for n in ("null", "boolean", "integer", "number", "string", "array", "object")
                 if _is_type(value, n)), type(value).__name__)


def _json_equal(a: Any, b: Any) -> bool:
    """JSON equality: ``True`` is not ``1`` (Python says it is)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def _is_date_time(value: str) -> bool:
    if _DATE_TIME.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return False
    return True
