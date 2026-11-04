"""Agent 核心：身份、能力声明、统一 Adapter 接口。"""
from .adapter import AgentAdapter, LiteLLMAdapter

__all__ = ["AgentAdapter", "LiteLLMAdapter"]
