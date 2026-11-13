"""工作区、工具策略与工具调用接口（M3-01..M3-10）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.audit import audit_action
from apps.api.deps import ActorContext, Page, PageParams, get_actor, get_db
from apps.api.schemas.tools import (
    GrantOut,
    GrantRequest,
    ToolCallOut,
    ToolPolicyOut,
    ToolPolicyPatch,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from packages.organization.common import get_or_404, iso_utc
from packages.permissions.effective import compute_effective_permissions
from packages.persistence.models import Company, Employee, TaskApproval, ToolCall, Workspace
from packages.shared.errors import DomainError
from packages.tools import registry
from packages.tools import workspaces as ws_service
from packages.tools.context import ToolContext
from packages.tools.policy import (
    effective_tool_policy,
    global_tools_enabled,
    tool_permission_report,
    validate_policy_patch,
)

router = APIRouter(tags=["tools"])


def _workspace_out(session: Session, actor: ActorContext, row: Workspace) -> dict:
    data = ws_service.serialize_workspace(
        row, ws_service.list_grants(session, actor.owner_id, row.id)
    )
    return data


def _tool_call_out(session: Session, row: ToolCall) -> dict:
    employee = session.get(Employee, row.employee_id) if row.employee_id else None
    approval = session.get(TaskApproval, row.approval_id) if row.approval_id else None
    return {
        "id": row.id,
        "task_id": row.task_id,
        "task_run_id": row.task_run_id,
        "employee_id": row.employee_id,
        "employee_name": employee.name if employee else None,
        "step_id": row.step_id,
        "call_index": row.call_index,
        "tool_name": row.tool_name,
        "category": row.category,
        "risk_level": row.risk_level,
        "status": row.status,
        "args_summary": row.args_summary or {},
        "resolved_path": row.resolved_path,
        "output_summary": row.output_summary or {},
        "output_bytes": row.output_bytes,
        "truncated": row.truncated,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "duration_ms": row.duration_ms,
        "approval_id": row.approval_id,
        "approval_status": approval.status if approval else None,
        "created_at": iso_utc(row.created_at),
        "ended_at": iso_utc(row.ended_at),
    }


# ---------------- 工作区 ----------------
@router.post(
    "/companies/{company_id}/workspaces",
    response_model=WorkspaceOut,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_endpoint(
    company_id: str,
    payload: WorkspaceCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    row = ws_service.create_workspace(
        db, actor.owner_id, company_id,
        name=payload.name, root_path=payload.root_path, mode=payload.mode,
        description=payload.description, created_by=actor.actor_id,
    )
    audit_action(
        db, actor, request, action="workspace.create", target_type="workspace",
        target_id=row.id,
        detail={
            "name": row.name, "root_path": row.root_path,
            "mode": row.mode, "company_id": company_id,
        },
    )
    return _workspace_out(db, actor, row)


@router.get("/companies/{company_id}/workspaces", response_model=list[WorkspaceOut])
def list_workspaces_endpoint(
    company_id: str,
    include_archived: bool = True,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    get_or_404(db, Company, company_id, actor.owner_id, "公司")
    rows = ws_service.list_workspaces(
        db, actor.owner_id, company_id, include_archived=include_archived
    )
    return [_workspace_out(db, actor, row) for row in rows]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
def get_workspace_endpoint(
    workspace_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    row = ws_service.get_workspace(db, actor.owner_id, workspace_id)
    return _workspace_out(db, actor, row)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
def update_workspace_endpoint(
    workspace_id: str,
    payload: WorkspaceUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    row = ws_service.update_workspace(
        db, actor.owner_id, workspace_id,
        name=payload.name, description=payload.description, mode=payload.mode,
    )
    audit_action(
        db, actor, request, action="workspace.update", target_type="workspace",
        target_id=row.id,
        detail={"name": row.name, "mode": row.mode, "description": row.description[:200]},
    )
    return _workspace_out(db, actor, row)


@router.delete("/workspaces/{workspace_id}", response_model=WorkspaceOut)
def archive_workspace_endpoint(
    workspace_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    row = ws_service.archive_workspace(db, actor.owner_id, workspace_id)
    audit_action(
        db, actor, request, action="workspace.archive", target_type="workspace",
        target_id=row.id, detail={"name": row.name, "root_path": row.root_path},
    )
    return _workspace_out(db, actor, row)


@router.get("/workspaces/{workspace_id}/grants", response_model=list[GrantOut])
def list_grants_endpoint(
    workspace_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    ws_service.get_workspace(db, actor.owner_id, workspace_id)
    return ws_service.list_grants(db, actor.owner_id, workspace_id)


@router.post(
    "/workspaces/{workspace_id}/grants",
    response_model=GrantOut,
    status_code=status.HTTP_201_CREATED,
)
def grant_workspace_endpoint(
    workspace_id: str,
    payload: GrantRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    row = ws_service.grant_access(
        db, actor.owner_id, workspace_id,
        employee_id=payload.employee_id, access=payload.access, granted_by=actor.actor_id,
    )
    employee = db.get(Employee, row.employee_id)
    audit_action(
        db, actor, request, action="workspace.grant", target_type="workspace",
        target_id=workspace_id,
        detail={
            "employee_id": row.employee_id,
            "employee_name": employee.name if employee else "",
            "access": row.access,
        },
    )
    return {
        "employee_id": row.employee_id,
        "employee_name": employee.name if employee else "",
        "access": row.access,
        "granted_by": row.granted_by,
        "granted_at": iso_utc(row.granted_at),
    }


@router.delete("/workspaces/{workspace_id}/grants/{employee_id}", status_code=204)
def revoke_workspace_endpoint(
    workspace_id: str,
    employee_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    ws_service.revoke_access(db, actor.owner_id, workspace_id, employee_id)
    audit_action(
        db, actor, request, action="workspace.revoke", target_type="workspace",
        target_id=workspace_id, detail={"employee_id": employee_id},
    )


# ---------------- 工具目录与公司策略 ----------------
# ---------------- 工作区文件浏览（owner 管理视图，只读） ----------------


@router.get("/showcase")
def showcase_endpoint(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """成果展示（M4）：聚合各工作区根目录 showcase.json 里登记的 AI 团队交付成品。

    前端据此渲染"成品展示"页——每项可直接内嵌整站预览（site 端点）或查看文档原文。
    """
    import json
    from pathlib import Path

    from packages.tools.fs import MAX_READ_BYTES
    from packages.tools.paths import PathDenied, safe_resolve

    projects: list[dict] = []
    workspaces = db.execute(
        select(Workspace).where(Workspace.owner_id == actor.owner_id, Workspace.status == "active")
    ).scalars().all()
    for workspace in workspaces:
        manifest = safe_resolve(Path(workspace.root_path), "showcase.json", allow_root=False)
        if not manifest.is_file():
            continue
        raw = manifest.read_bytes()
        if len(raw) > MAX_READ_BYTES or b"\x00" in raw[:8192]:
            continue
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for project in data.get("projects") or []:
            entry = str(project.get("entry") or "").strip()
            if not entry:
                continue
            try:
                target = safe_resolve(Path(workspace.root_path), entry, allow_root=False)
            except PathDenied:
                continue
            if not target.is_file():
                continue  # 成品已不存在则不展示
            projects.append({
                "id": f"{workspace.id}:{entry}",
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
                "entry": entry,
                "type": project.get("type", "site"),
                "icon": project.get("icon", "📦"),
                "title": project.get("title", entry),
                "desc": project.get("desc", ""),
                "highlights": project.get("highlights", []),
            })
    return {"projects": projects}


@router.get("/workspaces/{workspace_id}/files")
def browse_workspace_files_endpoint(
    workspace_id: str,
    path: str = "",
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """列出工作区内目录（owner 管理视图：工作区属 owner 资源，本地用户可浏览；

    路径安全复用工具层 safe_resolve，只读，不上报工具审计——非 Agent 工具调用）。
    """
    from pathlib import Path

    from packages.tools.fs import MAX_LIST_ENTRIES
    from packages.tools.paths import PathDenied, safe_resolve
    from packages.tools.workspaces import get_workspace

    workspace = get_workspace(db, actor.owner_id, workspace_id)
    root = Path(workspace.root_path)
    try:
        target = safe_resolve(root, path, allow_root=True)
    except PathDenied as exc:
        raise DomainError(exc.code, exc.message, 403, exc.detail) from exc
    if not target.is_dir():
        raise DomainError("TOOL_PATH_NOT_FOUND", f"目录不存在：{path}", 404)

    entries = []
    for index, entry in enumerate(sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name))):
        if index >= MAX_LIST_ENTRIES:
            break
        try:
            size = entry.stat().st_size if entry.is_file() else None
        except OSError:
            size = None
        entries.append({"name": entry.name, "type": "file" if entry.is_file() else "dir", "size": size})
    return {"path": path, "count": len(entries), "entries": entries,
            "truncated": len(list(target.iterdir())) > MAX_LIST_ENTRIES}


@router.get("/workspaces/{workspace_id}/files/content")
def read_workspace_file_endpoint(
    workspace_id: str,
    path: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """读取工作区内文本文件（owner 管理视图：同工具层安全标准——256KB 上限、二进制拒绝、密钥扫描）。"""
    from pathlib import Path

    from packages.tools.fs import MAX_READ_BYTES, scan_secrets
    from packages.tools.paths import PathDenied, relative_of, safe_resolve
    from packages.tools.workspaces import get_workspace

    workspace = get_workspace(db, actor.owner_id, workspace_id)
    root = Path(workspace.root_path)
    try:
        target = safe_resolve(root, path, allow_root=False)
    except PathDenied as exc:
        raise DomainError(exc.code, exc.message, 403, exc.detail) from exc
    if not target.is_file():
        raise DomainError("TOOL_PATH_NOT_FOUND", f"文件不存在：{path}", 404)
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise DomainError(
            "TOOL_OUTPUT_TOO_LARGE", f"文件 {size} 字节超过读取上限 {MAX_READ_BYTES}", 413,
            {"size": size, "limit": MAX_READ_BYTES},
        )
    raw = target.read_bytes()
    if b"\x00" in raw[:8192]:
        raise DomainError("TOOL_BINARY_UNSUPPORTED", "二进制文件不支持读取", 415)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DomainError("TOOL_BINARY_UNSUPPORTED", "文件不是合法 UTF-8 文本", 415) from exc
    scan_secrets(text)
    return {"path": relative_of(root, target), "size": size, "content": text}


# 网站预览允许的扩展名 → Content-Type（交付成果 iframe 渲染用）
_PREVIEW_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


@router.get("/workspaces/{workspace_id}/site/{file_path:path}")
def site_preview_endpoint(
    workspace_id: str,
    file_path: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    """按原始 Content-Type 返回工作区文件，供审批卡片的 iframe 直接渲染网站实际效果。

    相对路径资源（styles.css/main.js/图片）会自动落到本端点，整站可交互预览。
    安全边界与工具层一致：owner 资源、safe_resolve、扩展名白名单、5MB 上限、密钥扫描。
    """
    import mimetypes
    from pathlib import Path

    from packages.shared.errors import DomainError as _DomainError
    from packages.tools.fs import MAX_IMAGE_BYTES, scan_secrets
    from packages.tools.paths import PathDenied, safe_resolve
    from packages.tools.workspaces import get_workspace

    workspace = get_workspace(db, actor.owner_id, workspace_id)
    root = Path(workspace.root_path)
    try:
        target = safe_resolve(root, file_path, allow_root=False)
    except PathDenied as exc:
        raise DomainError(exc.code, exc.message, 403, exc.detail) from exc
    if not target.is_file():
        raise DomainError("TOOL_PATH_NOT_FOUND", f"文件不存在：{file_path}", 404)
    suffix = target.suffix.lower()
    media_type = _PREVIEW_TYPES.get(suffix)
    if media_type is None:
        guessed = mimetypes.guess_type(target.name)[0]
        media_type = guessed if guessed and guessed.startswith(("image/", "text/")) else None
    if media_type is None:
        raise _DomainError("TOOL_BINARY_UNSUPPORTED", f"预览不支持该文件类型：{suffix}", 415)
    size = target.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise _DomainError("TOOL_OUTPUT_TOO_LARGE", f"文件 {size} 字节超过预览上限 {MAX_IMAGE_BYTES}", 413)
    raw = target.read_bytes()
    if suffix in {".html", ".htm", ".css", ".js", ".json", ".md", ".txt", ".svg"}:
        if b"\x00" in raw[:8192]:
            raise _DomainError("TOOL_BINARY_UNSUPPORTED", "二进制文件不支持预览", 415)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _DomainError("TOOL_BINARY_UNSUPPORTED", "文件不是合法 UTF-8 文本", 415) from exc
        scan_secrets(text)
    from fastapi import Response

    return Response(content=raw, media_type=media_type)


@router.get("/tools")
def list_tools_endpoint(actor: ActorContext = Depends(get_actor)):
    return {
        "items": registry.list_specs(),
        "global_enabled": global_tools_enabled(),
        "shell_enabled": False,
    }


@router.get("/companies/{company_id}/tool-policy", response_model=ToolPolicyOut)
def get_tool_policy_endpoint(
    company_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    company = get_or_404(db, Company, company_id, actor.owner_id, "公司")
    return {
        "global_enabled": global_tools_enabled(),
        "policy": effective_tool_policy(company),
        "shell_enabled": False,
    }


@router.patch("/companies/{company_id}/tool-policy", response_model=ToolPolicyOut)
def update_tool_policy_endpoint(
    company_id: str,
    payload: ToolPolicyPatch,
    request: Request,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    company = get_or_404(db, Company, company_id, actor.owner_id, "公司")
    patch = {key: value for key, value in payload.model_dump().items() if value is not None}
    validate_policy_patch(dict(patch))
    current = effective_tool_policy(company)
    merged = {**current, **patch}
    if "categories" in patch:
        merged["categories"] = {**current["categories"], **patch["categories"]}
    policy = dict(company.policy or {})
    policy["tools"] = merged
    company.policy = policy
    db.commit()
    audit_action(
        db, actor, request, action="tool_policy.update", target_type="company",
        target_id=company_id, detail={"patch": patch},
    )
    return {
        "global_enabled": global_tools_enabled(),
        "policy": effective_tool_policy(company),
        "shell_enabled": False,
    }


@router.get("/employees/{employee_id}/tool-permissions")
def employee_tool_permissions_endpoint(
    employee_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    employee = get_or_404(db, Employee, employee_id, actor.owner_id, "员工")
    if employee.deleted_at is not None:
        raise DomainError("NOT_FOUND", f"员工不存在：{employee_id}", 404)
    company = get_or_404(db, Company, employee.company_id, actor.owner_id, "公司")
    ctx = ToolContext(
        session=db, owner_id=actor.owner_id, company=company, employee=employee,
        task=None, run=None,
        tool_policy=effective_tool_policy(company),
        permissions=compute_effective_permissions(db, actor.owner_id, employee.id)["permissions"],
    )
    return {"employee_id": employee.id, **tool_permission_report(ctx)}


# ---------------- 工具调用 ----------------
@router.get("/tasks/{task_id}/tool-calls", response_model=Page[ToolCallOut])
def list_task_tool_calls_endpoint(
    task_id: str,
    params: PageParams = Depends(),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    from packages.tasks.service import _task

    _task(db, actor.owner_id, task_id)
    base = select(ToolCall).where(
        ToolCall.owner_id == actor.owner_id, ToolCall.task_id == task_id
    )
    total = db.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()
    rows = db.execute(
        base.order_by(ToolCall.created_at.desc(), ToolCall.call_index.desc())
        .offset(params.offset).limit(params.page_size)
    ).scalars().all()
    return {
        "items": [_tool_call_out(db, row) for row in rows],
        "total": int(total), "page": params.page, "page_size": params.page_size,
    }


@router.get("/tool-calls/{tool_call_id}", response_model=ToolCallOut)
def get_tool_call_endpoint(
    tool_call_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_actor),
):
    row = db.get(ToolCall, tool_call_id)
    if row is None or row.owner_id != actor.owner_id:
        raise DomainError("NOT_FOUND", f"工具调用不存在：{tool_call_id}", 404)
    return _tool_call_out(db, row)
