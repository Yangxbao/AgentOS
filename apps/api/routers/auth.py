"""M4：账号体系接口（注册/登录/会话/登出/状态）。

认证开关 AGENTOS_AUTH 默认 off：
- off：登录/注册仍可用（账号可预建），但业务接口不强制鉴权（owner=local，兼容）；
- on：除本路由与 /api/health 外，全部接口要求 Bearer 会话。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from apps.api.audit import audit_action
from apps.api.deps import get_actor
from packages import auth as auth_service
from packages.persistence import get_session

router = APIRouter(tags=["auth"])


class RegisterBody(BaseModel):
    username: str
    password: str
    display_name: str = ""


class LoginBody(BaseModel):
    username: str
    password: str


@router.get("/auth/status")
def auth_status():
    """前端据此决定是否展示登录页与 401 跳转。"""
    return {"enabled": auth_service.auth_enabled()}


@router.post("/auth/register")
def register_endpoint(body: RegisterBody, request: Request):
    db = get_session()
    try:
        result = auth_service.register(
            db, username=body.username, password=body.password, display_name=body.display_name
        )
    finally:
        db.close()
    _audit_auth(
        request, action="auth.register",
        detail={"username": result["username"]},
        owner_id=result["owner_id"], actor_id=result["username"],
    )
    return {"ok": True, **result}


@router.post("/auth/login")
def login_endpoint(body: LoginBody, request: Request):
    db = get_session()
    try:
        result = auth_service.login(db, username=body.username, password=body.password)
    finally:
        db.close()
    user = result["user"]
    _audit_auth(
        request, action="auth.login",
        detail={"username": user["username"]},
        owner_id=user["owner_id"], actor_id=user["username"],
    )
    return result


@router.get("/auth/me")
def me_endpoint(actor=Depends(get_actor)):
    return {"actor": actor.actor_id, "owner_id": actor.owner_id}


@router.post("/auth/logout")
def logout_endpoint(request: Request, actor=Depends(get_actor)):
    header = request.headers.get("Authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    db = get_session()
    try:
        removed = auth_service.logout(db, token)
    finally:
        db.close()
    return {"ok": removed}


def _audit_auth(request: Request, *, action: str, detail: dict, owner_id: str = "local",
                actor_id: str = "anonymous") -> None:
    """认证动作（注册/登录）写审计：无 Actor 上下文，就地构造。"""
    from apps.api.deps import ActorContext, get_session

    db = get_session()
    try:
        actor = ActorContext(actor_type="user", actor_id=actor_id, owner_id=owner_id)
        audit_action(
            db, actor, request,
            action=action, target_type="auth",
            target_id=(detail or {}).get("username", "-"), detail=detail,
        )
    finally:
        db.close()
