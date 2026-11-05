"""Shell 工具：只注册，不实现。

M3 不存在任何可执行命令的代码路径——本模块不 import subprocess/os.system/Popen，
调用一律返回 SHELL_DISABLED，无论公司策略、员工授权或模型请求如何组合。
"""
from __future__ import annotations

from packages.shared.errors import DomainError

from .context import ToolContext


async def run(ctx: ToolContext, args: dict) -> dict:  # noqa: ARG001
    raise DomainError(
        "SHELL_DISABLED",
        "M3 不提供 Shell 执行能力（任意命令等于任意代码执行）。需要命令时请人工在终端执行。",
        403,
        {"tool": "shell.run"},
    )
