"""工具注册中心（M3-A）。

约束：
- 未注册的工具一律拒绝；
- 只有被注册且 enabled 的工具才可能进入模型可见的 schema 列表；
- `shell.run` 永久 enabled=False（且 handler 直接抛 SHELL_DISABLED）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from packages.shared.errors import DomainError

from . import fs, http, memory, shell
from .context import ToolContext

Handler = Callable[[ToolContext, dict], Awaitable[dict]]

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str  # file_read | file_write | network | shell | memory
    description: str
    params: dict
    risk: str
    side_effects: str  # none | write | network | destructive
    idempotent: bool
    handler: Handler = field(repr=False, compare=False)
    timeout_s: int = 30
    max_output_bytes: int = 256 * 1024
    requires_approval: bool = False
    enabled_by_default: bool = False
    enabled: bool = True  # False = 永久禁用（shell）

    def model_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params,
            },
        }


def risk_rank(value: str | None) -> int:
    return RISK_ORDER.get(str(value or "low"), 0)


_FILE_ID = {
    "type": "string",
    "minLength": 1,
    "maxLength": 32,
    "description": "工作区 ID",
}
_REL_PATH = {
    "type": "string",
    "minLength": 1,
    "maxLength": 400,
    "description": "工作区内的相对路径，不允许 .. / 绝对路径 / 盘符",
}

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="fs.list_dir",
        category="file_read",
        description="列出工作区内某个目录的内容（不跟随符号链接，限制深度与条目数）。",
        params={
            "type": "object",
            "properties": {
                "workspace_id": _FILE_ID,
                "path": {"type": "string", "maxLength": 400, "default": "", "description": "相对目录，空表示工作区根"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
            },
            "required": ["workspace_id"],
        },
        risk="low",
        side_effects="none",
        idempotent=True,
        handler=fs.list_dir,
        enabled_by_default=True,
    ),
    ToolSpec(
        name="fs.read_file",
        category="file_read",
        description="读取工作区内的 UTF-8 文本文件（上限 256KB，敏感文件与密钥内容会被拒绝）。",
        params={
            "type": "object",
            "properties": {
                "workspace_id": _FILE_ID,
                "path": _REL_PATH,
                "with_line_numbers": {"type": "boolean", "default": False},
            },
            "required": ["workspace_id", "path"],
        },
        risk="low",
        side_effects="none",
        idempotent=True,
        handler=fs.read_file,
        enabled_by_default=True,
    ),
    ToolSpec(
        name="fs.stat",
        category="file_read",
        description="查看工作区内文件/目录的元信息（不返回正文）。",
        params={
            "type": "object",
            "properties": {"workspace_id": _FILE_ID, "path": _REL_PATH},
            "required": ["workspace_id", "path"],
        },
        risk="low",
        side_effects="none",
        idempotent=True,
        handler=fs.stat_path,
        enabled_by_default=True,
    ),
    ToolSpec(
        name="fs.write_file",
        category="file_write",
        description=(
            "在工作区写文件。mode=create 仅新建（不覆盖）；overwrite 覆盖已有文件；append 追加。"
            "返回字节数与 sha256，不返回正文。"
        ),
        params={
            "type": "object",
            "properties": {
                "workspace_id": _FILE_ID,
                "path": _REL_PATH,
                "content": {"type": "string", "maxLength": 1048576},
                "mode": {
                    "type": "string",
                    "enum": ["create", "overwrite", "append"],
                    "default": "create",
                },
            },
            "required": ["workspace_id", "path", "content"],
        },
        risk="medium",
        side_effects="write",
        idempotent=False,
        handler=fs.write_file,
        enabled_by_default=True,
    ),
    ToolSpec(
        name="fs.delete_file",
        category="file_write",
        description="删除工作区内的单个文件（不递归、不删目录）。高风险，默认关闭且必须人工审批。",
        params={
            "type": "object",
            "properties": {"workspace_id": _FILE_ID, "path": _REL_PATH},
            "required": ["workspace_id", "path"],
        },
        risk="high",
        side_effects="destructive",
        idempotent=False,
        handler=fs.delete_file,
        requires_approval=True,
        enabled_by_default=False,
    ),
    ToolSpec(
        name="http.request",
        category="network",
        description=(
            "按公司域名白名单发起 HTTP 请求（默认仅 GET/HEAD；写方法需公司策略开启并人工审批）。"
            "禁止自定义 Host/Cookie/Authorization。"
        ),
        params={
            "type": "object",
            "properties": {
                "url": {"type": "string", "minLength": 8, "maxLength": 2000},
                "method": {
                    "type": "string",
                    "enum": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
                    "default": "GET",
                },
                "headers": {"type": "object", "default": {}},
                "body": {"type": "string", "maxLength": 262144},
                "timeout_s": {"type": "integer", "minimum": 1, "maximum": 60, "default": 30},
            },
            "required": ["url"],
        },
        risk="medium",
        side_effects="network",
        idempotent=False,
        handler=http.request,
        timeout_s=35,
        max_output_bytes=2 * 1024 * 1024,
        enabled_by_default=False,
    ),
    ToolSpec(
        name="shell.run",
        category="shell",
        description="（不可用）执行 Shell 命令。M3 永久禁用，调用会返回 SHELL_DISABLED。",
        params={
            "type": "object",
            "properties": {"command": {"type": "string", "maxLength": 2000}},
            "required": ["command"],
        },
        risk="critical",
        side_effects="destructive",
        idempotent=False,
        handler=shell.run,
        enabled=False,
        enabled_by_default=False,
    ),
    ToolSpec(
        name="memory.remember",
        category="memory",
        description="把一条经验/事实写入你自己的私有记忆（employee 作用域），供以后检索。",
        params={
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 200, "description": "一句话标题"},
                "content": {"type": "string", "maxLength": 4000, "description": "记忆内容（纯文本）"},
                "kind": {"type": "string", "enum": ["fact", "decision", "artifact", "summary", "note"]},
                "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            },
            "required": ["title", "content"],
        },
        risk="low",
        side_effects="write",
        idempotent=False,
        handler=memory.remember,
        timeout_s=10,
    ),
    ToolSpec(
        name="memory.search",
        category="memory",
        description="检索你有权访问的记忆（自己的私有记忆 + 所在公司的共享记忆）。",
        params={
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 400, "description": "检索关键词"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
        },
        risk="low",
        side_effects="none",
        idempotent=True,
        handler=memory.search,
        timeout_s=10,
    ),
]

REGISTRY: dict[str, ToolSpec] = {spec.name: spec for spec in SPECS}


def get_spec(name: str) -> ToolSpec:
    spec = REGISTRY.get(name)
    if spec is None:
        raise DomainError(
            "TOOL_NOT_REGISTERED", f"未注册的工具：{name}", 403,
            {"tool": name, "available": sorted(REGISTRY)},
        )
    return spec


def list_specs() -> list[dict]:
    return [
        {
            "name": spec.name,
            "category": spec.category,
            "description": spec.description,
            "risk": spec.risk,
            "side_effects": spec.side_effects,
            "idempotent": spec.idempotent,
            "timeout_s": spec.timeout_s,
            "max_output_bytes": spec.max_output_bytes,
            "requires_approval": spec.requires_approval,
            "enabled_by_default": spec.enabled_by_default,
            "enabled": spec.enabled,
            "params": spec.params,
        }
        for spec in SPECS
    ]


def model_name(name: str) -> str:
    """真实工具名 → 模型侧名称：`fs.list_dir` → `fs__list_dir`。

    OpenAI 兼容 API（含 DeepSeek）要求 function name 匹配 ^[a-zA-Z0-9_-]{1,64}$，
    点号不合法；真实模型返回的 tool_calls 用的是模型侧名称，需 from_model_name 还原。
    现有工具名均为 `x.y` 且不含双下划线，映射双射。
    """
    return name.replace(".", "__")


_MODEL_NAME_MAP: dict[str, str] = {
    model_name(name): name for name in REGISTRY
}


def from_model_name(model_side_name: str) -> str | None:
    """模型侧名称 → 真实工具名；无法映射时返回 None（保持原样由调用方处理）。"""
    if model_side_name in REGISTRY:
        return model_side_name
    return _MODEL_NAME_MAP.get(model_side_name)


def model_schemas(tool_names: list[str]) -> list[dict]:
    """只把已授权的工具 schema 发给模型（模型不知道未授权工具存在）。

    schema 里的 function.name 使用 model_name()（合法字符集），见 registry.model_name。
    """
    schemas = []
    for name in tool_names:
        spec = REGISTRY.get(name)
        if spec is None or not spec.enabled:
            continue
        schema = spec.model_schema()
        schema["function"]["name"] = model_name(spec.name)
        schemas.append(schema)
    return schemas
