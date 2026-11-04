"""提示词文件存储 + 不可变版本 + 哈希校验（§9.6 一致性协议）。

顺序：临时文件 → flush/fsync → 原子改名 → 计算哈希 → DB 事务；DB 失败清理文件。
"""
from __future__ import annotations

import difflib
import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.organization.common import iso_utc
from packages.persistence.models import Employee, PromptRevision
from packages.shared.errors import DomainError
from packages.shared.types import new_id

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_ROOT = REPO_ROOT / "data" / "prompts"


def _employee(session: Session, owner_id: str, employee_id: str) -> Employee:
    employee = session.get(Employee, employee_id)
    if employee is None or employee.owner_id != owner_id or employee.deleted_at is not None:
        raise DomainError("NOT_FOUND", f"员工不存在：{employee_id}", 404)
    return employee


def _dir(employee_id: str) -> Path:
    return PROMPTS_ROOT / "employees" / employee_id


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def serialize_revision(revision: PromptRevision) -> dict:
    return {
        "id": revision.id,
        "employee_id": revision.employee_id,
        "version": revision.version,
        "file_path": revision.file_path,
        "content_hash": revision.content_hash,
        "note": revision.note,
        "is_active": revision.is_active,
        "created_at": iso_utc(revision.created_at),
    }


def list_revisions(session: Session, owner_id: str, employee_id: str) -> list[PromptRevision]:
    _employee(session, owner_id, employee_id)
    return list(session.execute(
        select(PromptRevision)
        .where(PromptRevision.employee_id == employee_id)
        .order_by(PromptRevision.version.desc())
    ).scalars().all())


def get_revision(session: Session, owner_id: str, revision_id: str) -> PromptRevision:
    revision = session.get(PromptRevision, revision_id)
    if revision is None or revision.owner_id != owner_id:
        raise DomainError("NOT_FOUND", f"提示词版本不存在：{revision_id}", 404)
    return revision


def read_content(revision: PromptRevision, verify: bool = True) -> str:
    path = REPO_ROOT / revision.file_path
    if not path.exists():
        raise DomainError(
            "BR_PROMPT_FILE_MISSING",
            f"提示词文件缺失：{revision.file_path}（可用对账脚本检查）",
            409,
            {"revision_id": revision.id},
        )
    content = path.read_text(encoding="utf-8")
    if verify and _hash(content) != revision.content_hash:
        raise DomainError(
            "BR_PROMPT_HASH_MISMATCH",
            "提示词文件内容与数据库记录不一致，拒绝加载",
            409,
            {"revision_id": revision.id},
        )
    return content


def create_revision(
    session: Session,
    owner_id: str,
    employee_id: str,
    *,
    content: str,
    note: str = "",
    created_by: str = "local",
) -> PromptRevision:
    employee = _employee(session, owner_id, employee_id)
    text = content or ""
    if not text.strip():
        raise DomainError("VALIDATION_ERROR", "提示词内容不能为空", 422)

    last = session.execute(
        select(PromptRevision).where(PromptRevision.employee_id == employee_id).order_by(PromptRevision.version.desc())
    ).scalars().first()
    version = (last.version + 1) if last else 1
    directory = _dir(employee_id)
    directory.mkdir(parents=True, exist_ok=True)
    final_path = directory / f"v{version:04d}.md"
    tmp_path = directory / f".tmp-{uuid.uuid4().hex}.md"

    with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, final_path)

    revision = PromptRevision(
        id=new_id(), owner_id=owner_id, employee_id=employee_id, version=version,
        file_path=_rel(final_path), content_hash=_hash(text), note=note,
        created_by=created_by, is_active=last is None,
    )
    try:
        session.add(revision)
        if last is None:
            employee.prompt_active_version = version
        session.commit()
    except Exception:
        session.rollback()
        final_path.unlink(missing_ok=True)  # 失败补偿：清理孤儿文件
        raise
    session.refresh(revision)
    return revision


def activate_revision(session: Session, owner_id: str, revision_id: str) -> PromptRevision:
    revision = get_revision(session, owner_id, revision_id)
    employee = _employee(session, owner_id, revision.employee_id)
    read_content(revision)  # 激活前校验文件存在且哈希一致
    session.execute(
        PromptRevision.__table__.update()
        .where(PromptRevision.employee_id == employee.id)
        .values(is_active=False)
    )
    revision.is_active = True
    employee.prompt_active_version = revision.version
    session.commit()
    session.refresh(revision)
    return revision


def diff_against_previous(session: Session, owner_id: str, revision_id: str) -> str:
    revision = get_revision(session, owner_id, revision_id)
    current = read_content(revision)
    previous = session.execute(
        select(PromptRevision)
        .where(PromptRevision.employee_id == revision.employee_id, PromptRevision.version < revision.version)
        .order_by(PromptRevision.version.desc())
    ).scalars().first()
    if previous is None:
        return "（首个版本，无对比基准）"
    old = read_content(previous)
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), current.splitlines(keepends=True),
        fromfile=f"v{previous.version}", tofile=f"v{revision.version}",
    ))


def load_active_prompt(session: Session, employee_id: str) -> tuple[str, int]:
    """运行时加载激活版本（供 M2 复用）；哈希不符直接报错，不静默降级。"""
    revision = session.execute(
        select(PromptRevision).where(
            PromptRevision.employee_id == employee_id, PromptRevision.is_active.is_(True)
        )
    ).scalars().first()
    if revision is None:
        raise DomainError("BR_PROMPT_MISSING", "该员工没有激活的提示词版本", 409)
    return read_content(revision), revision.version


def reconcile(root: Path | None = None) -> dict:
    """扫描文件与 DB，报告孤儿/缺失/哈希不符。只读；修复由脚本决定。"""
    from packages.persistence import get_session

    root = root or PROMPTS_ROOT
    report = {"orphan_files": [], "missing_files": [], "hash_mismatch": []}
    with get_session() as session:
        revisions = session.execute(select(PromptRevision)).scalars().all()
        known = {r.file_path for r in revisions}
        for revision in revisions:
            path = REPO_ROOT / revision.file_path
            if not path.exists():
                report["missing_files"].append(revision.file_path)
            elif _hash(path.read_text(encoding="utf-8")) != revision.content_hash:
                report["hash_mismatch"].append(revision.file_path)
    if root.exists():
        for path in root.rglob("v*.md"):
            rel = _rel(path)
            if rel not in known and not path.name.startswith(".tmp-"):
                report["orphan_files"].append(rel)
    return report


_ = datetime  # 保留导入给未来版本时间戳扩展
