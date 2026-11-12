"""账号体系（M4）：登录/注册/会话。服务实现在 service.py。"""
from .service import auth_enabled, login, logout, register, resolve_token

__all__ = ["auth_enabled", "login", "logout", "register", "resolve_token"]
