"""导出/导入 zip 包（B4）。

安全：包内不得含密钥明文（只保留 api_key_ref）；拒绝路径穿越；导入默认 rename 冲突策略。

导入事务性（v1.3）：
- 单个显式事务覆盖公司/部门/岗位/连接/员工/岗位关联/提示词元数据/审计；
- 任一环节失败 → DB 整体回滚，并按“本批次新建文件清单”补偿删除提示词文件；
- 补偿失败不吞掉原异常，仅记录告警，留下可被 reconcile_prompts.py 发现的孤儿文件；
- 只清理本次新建的文件，绝不删除已有有效版本。
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.organization.common import get_or_404
from packages.permissions.audit import write_audit
from packages.persistence.models import (
    Company,
    Department,
    Employee,
    EmployeePosition,
    ModelConnection,
    Position,
)
from packages.prompts.service import (
    activate_revision,
    content_hash,
    create_revision,
    file_path_of,
    list_revisions,
    read_content,
)
from packages.shared.errors import DomainError
from packages.shared.types import new_id

FORMAT_VERSION = 1

logger = logging.getLogger("agentos.config_io")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def export_company(session: Session, owner_id: str, company_id: str) -> bytes:
    company = get_or_404(session, Company, company_id, owner_id, "公司")
    departments = list(session.execute(
        select(Department).where(Department.company_id == company_id).order_by(Department.depth)
    ).scalars().all())
    positions = list(session.execute(
        select(Position).where(Position.company_id == company_id)
    ).scalars().all())
    connections = list(session.execute(
        select(ModelConnection).where(ModelConnection.company_id == company_id)
    ).scalars().all())
    employees = list(session.execute(
        select(Employee).where(Employee.company_id == company_id, Employee.deleted_at.is_(None))
    ).scalars().all())
    # M3 后：工作区/授权/记忆一并导出（跨公司迁移场景；root_path 原样记录，导入时按同机路径校验）
    from packages.tools.workspaces import Workspace  # noqa: PLC0415 - 延迟导入避免包间循环

    workspaces = list(session.execute(
        select(Workspace).where(Workspace.company_id == company_id).order_by(Workspace.name)
    ).scalars().all())
    from packages.persistence.models import EmployeeWorkspaceGrant, MemoryItem

    workspace_grants = list(session.execute(
        select(EmployeeWorkspaceGrant)
        .join(Workspace, Workspace.id == EmployeeWorkspaceGrant.workspace_id)
        .where(Workspace.company_id == company_id)
    ).scalars().all())
    memories = list(session.execute(
        select(MemoryItem).where(
            MemoryItem.company_id == company_id, MemoryItem.status == "active"
        )
    ).scalars().all())

    employees_payload = []
    prompt_files: dict[str, str] = {}
    for employee in employees:
        links = session.execute(
            select(EmployeePosition).where(EmployeePosition.employee_id == employee.id)
        ).scalars().all()
        revisions = list_revisions(session, owner_id, employee.id)
        prompts = []
        for revision in reversed(revisions):  # 版本升序，导入时可直接按顺序重建
            prompts.append({
                "version": revision.version, "note": revision.note,
                "is_active": revision.is_active, "content_hash": revision.content_hash,
            })
            prompt_files[f"prompts/{employee.id}/v{revision.version:04d}.md"] = read_content(
                revision, verify=False
            )
        employees_payload.append({
            "id": employee.id,
            "department_id": employee.department_id,
            "name": employee.name,
            "avatar": employee.avatar,
            "title": employee.title,
            "bio": employee.bio,
            "personality": employee.personality,
            "status": employee.status,
            "reports_to": employee.reports_to,
            "primary_model_id": employee.primary_model_id,
            "fallback_model_id": employee.fallback_model_id,
            "adapter_type": employee.adapter_type,
            "cli_profile": employee.cli_profile,
            "tools_allowed": employee.tools_allowed,
            "permission_profile": employee.permission_profile,
            "positions": [
                {"position_id": link.position_id, "is_primary": link.is_primary} for link in links
            ],
            "prompts": prompts,
        })

    manifest = {
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "company_name": company.name,
        "counts": {
            "departments": len(departments),
            "positions": len(positions),
            "model_connections": len(connections),
            "employees": len(employees),
            "prompts": len(prompt_files),
            "workspaces": len(workspaces),
            "workspace_grants": len(workspace_grants),
            "memories": len(memories),
        },
        "contains_secrets": False,
    }
    payload = {
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2),
        "company.json": json.dumps({
            "name": company.name, "description": company.description, "policy": company.policy,
        }, ensure_ascii=False, indent=2),
        "departments.json": json.dumps([
            {
                "id": d.id, "parent_id": d.parent_id, "name": d.name, "code": d.code,
                "description": d.description, "sort_order": d.sort_order, "depth": d.depth,
            } for d in departments
        ], ensure_ascii=False, indent=2),
        "positions.json": json.dumps([
            {
                "id": p.id, "department_id": p.department_id, "name": p.name, "level": p.level,
                "is_managerial": p.is_managerial, "can_review": p.can_review,
                "review_capability_tags": p.review_capability_tags,
                "responsibilities": p.responsibilities, "default_permissions": p.default_permissions,
            } for p in positions
        ], ensure_ascii=False, indent=2),
        "connections.json": json.dumps([
            {
                "id": c.id, "name": c.name, "provider": c.provider, "model": c.model,
                "api_key_ref": c.api_key_ref, "base_url": c.base_url,
                "timeout_s": c.timeout_s, "max_retries": c.max_retries,
                "model_list_source": c.model_list_source,
            } for c in connections
        ], ensure_ascii=False, indent=2),
        "employees.json": json.dumps(employees_payload, ensure_ascii=False, indent=2),
        "workspaces.json": json.dumps([
            {
                "id": w.id, "name": w.name, "slug": w.slug, "root_path": w.root_path,
                "mode": w.mode, "status": w.status, "description": w.description,
            } for w in workspaces
        ], ensure_ascii=False, indent=2),
        "workspace_grants.json": json.dumps([
            {
                "workspace_id": g.workspace_id, "employee_id": g.employee_id,
                "access": g.access,
            } for g in workspace_grants
        ], ensure_ascii=False, indent=2),
        "memories.json": json.dumps([
            {
                "scope": m.scope, "employee_id": m.employee_id, "kind": m.kind,
                "title": m.title, "content": m.content, "tags": m.tags,
            } for m in memories if m.status == "active"
        ], ensure_ascii=False, indent=2),
    }
    payload.update(prompt_files)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in payload.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _safe_name(name: str) -> None:
    path = PurePosixPath(name)
    if name.startswith("/") or ".." in path.parts or "\\" in name:
        raise DomainError("IMPORT_UNSAFE_PATH", f"压缩包包含不安全路径：{name}", 422)


def _read_bundle(data: bytes) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DomainError("IMPORT_INVALID_BUNDLE", "上传内容不是有效的 zip 包", 422) from exc
    files: dict[str, bytes] = {}
    for name in archive.namelist():
        _safe_name(name)
        files[name] = archive.read(name)
    for required in ("manifest.json", "company.json", "departments.json", "positions.json",
                     "connections.json", "employees.json"):
        if required not in files:
            raise DomainError("IMPORT_INVALID_BUNDLE", f"压缩包缺少 {required}", 422)
    return files


def _json(files: dict[str, bytes], name: str):
    return json.loads(files[name].decode("utf-8"))


def inspect_bundle(session: Session, owner_id: str, data: bytes) -> dict:
    files = _read_bundle(data)
    manifest = _json(files, "manifest.json")
    company = _json(files, "company.json")
    exists = session.execute(
        select(Company).where(Company.owner_id == owner_id, Company.name == company["name"])
    ).first() is not None
    return {
        "dry_run": True,
        "company_name": company["name"],
        "conflict": exists,
        "strategy": "rename" if exists else "create",
        "counts": {
            "departments": len(_json(files, "departments.json")),
            "positions": len(_json(files, "positions.json")),
            "model_connections": len(_json(files, "connections.json")),
            "employees": len(_json(files, "employees.json")),
            "prompts": len([n for n in files if n.startswith("prompts/")]),
        },
        "bundled_manifest": manifest,
    }


def _unique_company_name(session: Session, owner_id: str, base: str) -> str:
    name = base
    index = 1
    while session.execute(
        select(Company).where(Company.owner_id == owner_id, Company.name == name)
    ).first() is not None:
        index += 1
        name = f"{base}（导入 {index}）"
    return name


def _unlink_quietly(path: Path) -> bool:
    """补偿删除；返回是否成功。失败不抛出，交由调用方记录并留给对账脚本。"""
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _compensate_files(created_files: list[Path]) -> list[str]:
    failed: list[str] = []
    for path in created_files:
        if path.exists() and not _unlink_quietly(path):
            failed.append(path.as_posix())
    return failed


def import_company(
    session: Session,
    owner_id: str,
    data: bytes,
    strategy: str = "rename",
    *,
    request_id: str = "-",
    actor_id: str = "local",
) -> dict:
    files = _read_bundle(data)
    company_data = _json(files, "company.json")
    departments = _json(files, "departments.json")
    positions = _json(files, "positions.json")
    connections = _json(files, "connections.json")
    employees = _json(files, "employees.json")
    # M3 后：三个新文件可选（向后兼容旧包）；工作区 root_path 原样导入并按创建同一标准校验，
    # 非法/不存在的路径跳过并记录 warning（不阻断整体导入）
    workspaces = _json(files, "workspaces.json") if "workspaces.json" in files else []
    workspace_grants = _json(files, "workspace_grants.json") if "workspace_grants.json" in files else []
    memories = _json(files, "memories.json") if "memories.json" in files else []
    warnings: list[str] = []

    if strategy not in ("rename",):
        raise DomainError("IMPORT_STRATEGY_UNSUPPORTED", "B4 仅支持 rename 冲突策略", 422)

    created_files: list[Path] = []
    try:
        new_company = Company(
            id=new_id(), owner_id=owner_id,
            name=_unique_company_name(session, owner_id, company_data["name"]),
            description=company_data.get("description", ""),
            policy=company_data.get("policy") or {},
            status="active",
        )
        session.add(new_company)
        session.flush()

        dept_map: dict[str, str] = {}
        for item in sorted(departments, key=lambda d: d.get("depth", 0)):
            new_id_value = new_id()
            dept_map[item["id"]] = new_id_value
            session.add(Department(
                id=new_id_value, owner_id=owner_id, company_id=new_company.id,
                parent_id=dept_map.get(item.get("parent_id")), name=item["name"],
                code=item.get("code", ""), description=item.get("description", ""),
                sort_order=item.get("sort_order", 0), depth=item.get("depth", 0),
            ))
        session.flush()

        position_map: dict[str, str] = {}
        for item in positions:
            new_id_value = new_id()
            position_map[item["id"]] = new_id_value
            session.add(Position(
                id=new_id_value, owner_id=owner_id, company_id=new_company.id,
                department_id=dept_map.get(item.get("department_id")), name=item["name"],
                level=item.get("level", ""), is_managerial=item.get("is_managerial", False),
                can_review=item.get("can_review", False),
                review_capability_tags=item.get("review_capability_tags", []),
                responsibilities=item.get("responsibilities", ""),
                default_permissions=item.get("default_permissions", {}),
            ))
        session.flush()

        connection_map: dict[str, str] = {}
        for item in connections:
            new_id_value = new_id()
            connection_map[item["id"]] = new_id_value
            session.add(ModelConnection(
                id=new_id_value, owner_id=owner_id, company_id=new_company.id,
                name=item["name"], provider=item["provider"], model=item["model"],
                api_key_ref=item["api_key_ref"], base_url=item.get("base_url"),
                timeout_s=item.get("timeout_s", 60), max_retries=item.get("max_retries", 2),
                model_list_source=item.get("model_list_source", "static"), enabled=True,
            ))
        session.flush()

        employee_map: dict[str, str] = {}
        for item in employees:
            new_id_value = new_id()
            employee_map[item["id"]] = new_id_value
            session.add(Employee(
                id=new_id_value, owner_id=owner_id, company_id=new_company.id,
                department_id=dept_map.get(item.get("department_id")), name=item["name"],
                avatar=item.get("avatar", ""), title=item.get("title", ""), bio=item.get("bio", ""),
                personality=item.get("personality", ""), status=item.get("status", "active"),
                reports_to=employee_map.get(item.get("reports_to")),
                primary_model_id=connection_map.get(item.get("primary_model_id")),
                fallback_model_id=connection_map.get(item.get("fallback_model_id")),
                adapter_type=item.get("adapter_type", "api"), cli_profile=item.get("cli_profile"),
                tools_allowed=item.get("tools_allowed", []),
                permission_profile=item.get("permission_profile", {}),
                capabilities_declared={},
            ))
            session.flush()
            for link in item.get("positions", []):
                if link["position_id"] in position_map:
                    session.add(EmployeePosition(
                        employee_id=new_id_value, position_id=position_map[link["position_id"]],
                        is_primary=link.get("is_primary", False), department_id=None,
                    ))
        session.flush()

        # 报告层级第二遍：确保父员工 ID 已映射
        for item in employees:
            if item.get("reports_to") in employee_map:
                employee = session.get(Employee, employee_map[item["id"]])
                employee.reports_to = employee_map[item["reports_to"]]

        # M3 后：工作区导入（root 原样 + validate_root 同标准校验；非法跳过记 warning）
        from packages.persistence.models import EmployeeWorkspaceGrant as _Grant
        from packages.persistence.models import MemoryItem as _Memory
        from packages.persistence.models import Workspace as _Workspace
        from packages.tools.workspaces import validate_root  # noqa: PLC0415

        workspace_map: dict[str, str] = {}
        for item in workspaces:
            try:
                resolved = validate_root(str(item.get("root_path") or ""), must_exist=False)
            except DomainError as exc:
                warnings.append(f"跳过工作区「{item.get('name')}」：{exc.message}")
                continue
            new_ws_id = new_id()
            workspace_map[item["id"]] = new_ws_id
            session.add(_Workspace(
                id=new_ws_id, owner_id=owner_id, company_id=new_company.id,
                name=item.get("name", "工作区"), slug=item.get("slug") or new_ws_id,
                root_path=str(resolved), mode=item.get("mode", "read_write"),
                status=item.get("status", "active"), description=item.get("description", ""),
                created_by="import",
            ))
        session.flush()

        for item in workspace_grants:
            new_ws_id = workspace_map.get(item.get("workspace_id"))
            new_emp_id = employee_map.get(item.get("employee_id"))
            if not new_ws_id or not new_emp_id:
                warnings.append("跳过工作区授权：工作区或员工在本次导入中不存在")
                continue
            session.add(_Grant(
                id=new_id(), owner_id=owner_id, employee_id=new_emp_id,
                workspace_id=new_ws_id, access=item.get("access", "read"),
                granted_by="import",
            ))
        session.flush()

        # 记忆导入：仅 active；作用域映射（employee → 新员工 id；project/company → 新公司）
        from hashlib import sha256 as _sha256

        for item in memories:
            if item.get("scope") == "employee" and item.get("employee_id") not in employee_map:
                warnings.append(f"跳过记忆「{item.get('title')}」：原员工不在本次导入中")
                continue
            content = str(item.get("content") or "")
            if not content.strip():
                continue
            new_mem_id = new_id()
            session.add(_Memory(
                id=new_mem_id, owner_id=owner_id, company_id=new_company.id,
                scope=item.get("scope", "employee"),
                employee_id=employee_map.get(item.get("employee_id")) if item.get("scope") == "employee" else None,
                project_task_id=None, kind=item.get("kind", "note"),
                title=str(item.get("title") or "")[:200], content=content,
                content_hash=_sha256(content.strip().encode("utf-8")).hexdigest(),
                tags=item.get("tags") or [], status="active",
                created_by="import", created_by_type="user",
            ))
        session.flush()
        # FTS 同步（表存在才生效；FTS5 不可用则检索降级 LIKE，不影响导入）
        try:
            from packages.memory.service import _fts_sync

            for mem_row in session.execute(
                select(_Memory).where(
                    _Memory.company_id == new_company.id, _Memory.created_by == "import"
                )
            ).scalars().all():
                _fts_sync(session, mem_row)
        except Exception:  # noqa: BLE001 - FTS 同步失败不影响导入（降级检索仍可用）
            pass

        prompt_count = 0
        for item in employees:
            new_employee_id = employee_map[item["id"]]
            active_revision_id = None
            ordered = sorted(item.get("prompts", []), key=lambda p: p.get("version", 0))
            for prompt in ordered:
                name = f"prompts/{item['id']}/v{prompt['version']:04d}.md"
                if name not in files:
                    raise DomainError(
                        "IMPORT_INVALID_BUNDLE", f"压缩包缺少提示词文件 {name}", 422
                    )
                content = files[name].decode("utf-8")
                expected = prompt.get("content_hash")
                if expected and content_hash(content) != expected:
                    raise DomainError(
                        "IMPORT_PROMPT_HASH_MISMATCH", f"提示词文件哈希不符：{name}", 422,
                        {"expected": expected, "actual": content_hash(content)},
                    )
                revision = create_revision(
                    session, owner_id, new_employee_id,
                    content=content, note=prompt.get("note", ""), created_by="import",
                    commit=False,
                )
                created_files.append(file_path_of(revision))
                prompt_count += 1
                if prompt.get("is_active"):
                    active_revision_id = revision.id
            if active_revision_id:
                activate_revision(session, owner_id, active_revision_id, commit=False)

        write_audit(
            session, owner_id,
            action="config.import", target_type="company", target_id=new_company.id,
            detail={
                "company_id": new_company.id,
                "company_name": new_company.name,
                "strategy": strategy,
                "counts": {
                    "departments": len(dept_map), "positions": len(position_map),
                    "model_connections": len(connection_map), "employees": len(employee_map),
                    "prompts": prompt_count,
                    "workspaces": len(workspace_map), "workspace_grants": len(workspace_grants),
                    "memories": len(memories),
                },
                "warnings": warnings,
            },
            actor_id=actor_id, request_id=request_id, commit=False,
        )
        session.commit()
    except Exception:
        session.rollback()
        failed = _compensate_files(created_files)
        if failed:
            # 补偿失败：保留孤儿文件交给对账脚本，不掩盖原始异常
            logger.warning(
                "导入失败且文件补偿未完成，遗留孤儿文件 %d 个：%s", len(failed), failed
            )
        raise

    return {
        "dry_run": False,
        "company_id": new_company.id,
        "company_name": new_company.name,
        "counts": {
            "departments": len(dept_map), "positions": len(position_map),
            "model_connections": len(connection_map), "employees": len(employee_map),
            "prompts": prompt_count,
            "workspaces": len(workspace_map), "workspace_grants": len(workspace_grants),
            "memories": len(memories),
        },
        "warnings": warnings,
    }
