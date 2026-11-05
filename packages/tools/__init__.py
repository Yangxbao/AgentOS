"""M3-A 工具执行层。

边界（务必遵守）：
- 所有工具调用必须经过 `packages.tools.invoke.invoke_tool`，禁止直接调用 handler；
- 文件工具只能访问 `workspace` 授权目录；
- `shell.run` 只注册为禁用态，M3 不存在任何可执行命令的代码路径。
"""

from .context import ToolContext, ToolOutcome  # noqa: F401
from .invoke import invoke_tool  # noqa: F401
from .registry import REGISTRY, ToolSpec, get_spec, list_specs, model_schemas  # noqa: F401

__all__ = [
    "REGISTRY",
    "ToolContext",
    "ToolOutcome",
    "ToolSpec",
    "get_spec",
    "invoke_tool",
    "list_specs",
    "model_schemas",
]
