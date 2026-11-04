"""工作流引擎：M0 提供顺序协作编排与 LangGraph 审批图验证。"""
from .sequential import EmployeeSpec, run_sequential_handoff

__all__ = ["EmployeeSpec", "run_sequential_handoff"]
