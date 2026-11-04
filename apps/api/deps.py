"""FastAPI 依赖：数据库会话、分页、调用主体。

B1 只有本地用户（owner_id="local"）；Agent 侧不发放任何凭证（BR-12）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Generic, Iterator, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from packages.persistence import get_session

T = TypeVar("T")


@dataclass(frozen=True)
class ActorContext:
    actor_type: str  # user | system | agent
    actor_id: str
    owner_id: str = "local"


def get_actor() -> ActorContext:
    """B1 固定为本地用户；M5 接入账号体系后替换为真实鉴权。"""
    return ActorContext(actor_type="user", actor_id="local")


def get_db() -> Iterator[Session]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


class PageParams:
    def __init__(
        self,
        page: int = Query(1, ge=1, description="页码，从 1 开始"),
        page_size: int = Query(20, ge=1, le=200, description="每页条数，最大 200"),
    ):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def paginate(db: Session, stmt: Select, params: PageParams) -> tuple[list, int]:
    """执行分页查询，返回 (rows, total)。禁止在列表接口里直接返回全量。"""
    total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = db.execute(stmt.offset(params.offset).limit(params.page_size)).scalars().all()
    return list(rows), int(total)


def total_pages(total: int, page_size: int) -> int:
    return max(1, math.ceil(total / page_size)) if page_size else 1
