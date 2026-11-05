"""极简 JSON Schema 校验（只覆盖工具参数需要的子集）。

为什么不用 pydantic/jsonschema：工具 schema 要原样发给模型，
本地校验必须与下发给模型的约束一致；自己实现可保证两边同源，且不引入新依赖。

支持：type(object/string/integer/number/boolean/array)、properties、required、
additionalProperties=false、enum、maxLength、minLength、minimum、maximum、maxItems。
未知字段一律拒绝（additionalProperties 默认 false）。
"""
from __future__ import annotations

from typing import Any

from packages.shared.errors import DomainError

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _type_ok(expected: str, value: Any) -> bool:
    py = _TYPE_MAP.get(expected)
    if py is None:
        return True
    if expected in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, py)


def validate_args(schema: dict, args: Any, *, tool: str = "") -> dict:
    """校验并返回清洗后的参数（只保留 schema 声明过的键）。"""
    if not isinstance(args, dict):
        raise DomainError(
            "TOOL_ARGS_INVALID", f"{tool} 参数必须是对象", 422, {"tool": tool}
        )
    properties: dict = schema.get("properties") or {}
    required: list[str] = schema.get("required") or []
    errors: list[str] = []

    unknown = sorted(set(args) - set(properties))
    if unknown and not schema.get("additionalProperties", False):
        errors.append(f"未知参数：{', '.join(unknown)}")
    for name in required:
        if name not in args:
            errors.append(f"缺少必填参数：{name}")

    cleaned: dict[str, Any] = {}
    for name, spec in properties.items():
        if name not in args:
            if "default" in spec:
                cleaned[name] = spec["default"]
            continue
        value = args[name]
        expected = spec.get("type")
        if expected and not _type_ok(expected, value):
            errors.append(f"参数 {name} 类型应为 {expected}")
            continue
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"参数 {name} 必须是 {spec['enum']} 之一")
            continue
        if isinstance(value, str):
            if "maxLength" in spec and len(value) > spec["maxLength"]:
                errors.append(f"参数 {name} 超过最大长度 {spec['maxLength']}")
                continue
            if "minLength" in spec and len(value) < spec["minLength"]:
                errors.append(f"参数 {name} 长度不足 {spec['minLength']}")
                continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in spec and value < spec["minimum"]:
                errors.append(f"参数 {name} 不能小于 {spec['minimum']}")
                continue
            if "maximum" in spec and value > spec["maximum"]:
                errors.append(f"参数 {name} 不能大于 {spec['maximum']}")
                continue
        if isinstance(value, list) and "maxItems" in spec and len(value) > spec["maxItems"]:
            errors.append(f"参数 {name} 元素过多（上限 {spec['maxItems']}）")
            continue
        cleaned[name] = value

    if errors:
        raise DomainError(
            "TOOL_ARGS_INVALID", "；".join(errors)[:400], 422, {"tool": tool, "errors": errors}
        )
    return cleaned
