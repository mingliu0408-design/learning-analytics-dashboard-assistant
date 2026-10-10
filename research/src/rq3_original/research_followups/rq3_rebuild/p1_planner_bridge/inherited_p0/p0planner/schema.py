"""Strict validator for the small JSON Schema vocabulary used by P0 only.

This is not a general JSON Schema implementation. No coercion/default filling.
Schemas are packaged alongside code; unknown schema keywords fail closed.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KEYWORDS = {"$schema", "title", "description", "type", "properties", "required",
            "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
            "minLength", "enum", "const", "minimum", "maximum", "anyOf"}


def load_schema(name: str) -> dict:
    return json.loads((ROOT / name).read_text())


def schema_errors(value: Any, schema: dict, path: str = "$") -> list[dict]:
    unknown = set(schema) - KEYWORDS
    if unknown:
        raise ValueError(f"Unsupported P0 schema keywords: {sorted(unknown)}")
    errors = []

    def error(code: str, message: str, at: str = path) -> None:
        errors.append({"code": code, "path": at, "message": message})

    if "anyOf" in schema:
        alternatives = [schema_errors(value, s, path) for s in schema["anyOf"]]
        if not any(not e for e in alternatives):
            # Preserve exact nested paths in the closest alternative.
            errors.extend(min(alternatives, key=len))
        return errors
    typ = schema.get("type")
    matches = {"object": isinstance(value, dict), "array": isinstance(value, list),
               "string": isinstance(value, str), "boolean": type(value) is bool,
               "integer": type(value) is int,
               "number": type(value) in (int, float), "null": value is None}
    if typ and not matches[typ]:
        error("SCHEMA_TYPE", f"Expected {typ}; got {type(value).__name__}.")
        return errors
    if type(value) in (int, float):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            error("NON_FINITE_NUMBER", "A finite, representable numeric value is required.")
            return errors
        if "minimum" in schema and value < schema["minimum"]:
            error("NUMERIC_RANGE", f"Minimum is {schema['minimum']}.")
        if "maximum" in schema and value > schema["maximum"]:
            error("NUMERIC_RANGE", f"Maximum is {schema['maximum']}.")
    if "enum" in schema and value not in schema["enum"]:
        error("SCHEMA_ENUM", "Value is outside the declared vocabulary.")
    if "const" in schema and value != schema["const"]:
        error("SCHEMA_CONST", "Value differs from the required constant.")
    if isinstance(value, str) and len(value.strip()) < schema.get("minLength", 0):
        error("EMPTY_STRING", "A nonblank string is required.")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                error("REQUIRED_FIELD", f"Missing {key}.", f"{path}.{key}")
        for key, item in value.items():
            if key in props:
                errors.extend(schema_errors(item, props[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                error("UNEXPECTED_FIELD", "Field is not in the runtime contract.", f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            error("ARRAY_SIZE", "Array length is outside the declared range.")
        if schema.get("uniqueItems"):
            if any(item in value[:i] for i, item in enumerate(value)):
                error("DUPLICATE_ITEM", "Array entries must be unique.")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(schema_errors(item, schema["items"], f"{path}[{i}]"))
    return errors
