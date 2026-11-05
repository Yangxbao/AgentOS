"""记忆工具（M3-C）：Agent 通过五层权限写入/检索记忆。

- memory.remember：Agent 只能写自己的 employee 作用域（提升需人工）；
- memory.search：只能检索自己可见的作用域（跨员工私有记忆检索不到）。

记忆内容在 service 层写入时已脱敏；返回给模型的内容属于数据，
由调用方（提示词边界）保证按不可信数据处理。
"""
from __future__ import annotations

from .context import ToolContext


async def remember(ctx: ToolContext, args: dict) -> dict:
    from packages.memory.service import create_memory

    result = create_memory(
        ctx.session, ctx.owner_id,
        scope="employee",
        company_id=ctx.company.id if ctx.company else None,
        employee_id=ctx.employee.id,
        title=str(args.get("title") or ""),
        content=str(args.get("content") or ""),
        kind=str(args.get("kind") or "note"),
        tags=list(args.get("tags") or []),
        source_task_id=ctx.task.id if ctx.task else None,
        created_by=ctx.employee.id,
        created_by_type="agent",
    )
    return {
        "id": result["id"],
        "duplicate": result.get("duplicate", False),
        "scope": result["scope"],
        "title": result["title"],
    }


async def search(ctx: ToolContext, args: dict) -> dict:
    from packages.memory.service import search_memories

    items = search_memories(
        ctx.session, ctx.owner_id,
        query=str(args.get("query") or ""),
        company_id=ctx.company.id if ctx.company else None,
        viewer_employee_id=ctx.employee.id,
        top_k=int(args.get("top_k") or 5),
    )
    return {
        "count": len(items),
        "items": [
            {
                "id": item["id"], "scope": item["scope"], "kind": item["kind"],
                "title": item["title"], "content": item["content"],
                "updated_at": item["updated_at"],
            }
            for item in items
        ],
    }
