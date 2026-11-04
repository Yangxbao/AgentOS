"""模型网关：LiteLLM 封装。不知道"员工"概念，只提供统一调用与计价。"""
from .gateway import GatewayError, GatewayResponse, chat

__all__ = ["GatewayError", "GatewayResponse", "chat"]
