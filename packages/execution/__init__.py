"""执行引擎（M2-B）：Adapter 工厂、权限闸门、执行器、后台 worker。"""
from .adapter_factory import AdapterBundle, build_adapter, resolve_connection
from .executor import execute_run
from .guard import check_execution, steps_of
from .observability import (
    agent_run_detail,
    monitor_summary,
    runs_of_task,
    serialize_agent_run,
    serialize_run,
    task_timeline,
    task_usage,
    usage_summary,
)
from .prompting import build_system_prompt
from .runner import TaskRunner

__all__ = [
    "AdapterBundle",
    "build_adapter",
    "resolve_connection",
    "execute_run",
    "check_execution",
    "steps_of",
    "build_system_prompt",
    "TaskRunner",
    "task_timeline",
    "task_usage",
    "runs_of_task",
    "agent_run_detail",
    "usage_summary",
    "monitor_summary",
    "serialize_run",
    "serialize_agent_run",
]
