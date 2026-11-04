"""M0 LangGraph 验证：interrupt 审批暂停/恢复 + SqliteSaver 持久化。

证明 LangGraph 的 interrupt/Command(resume) 三件套可作为人工审批中心的语义内核。
注意 LangGraph 规则：节点恢复时从头重放，副作用必须在 interrupt 之后或保证幂等。
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ApprovalState(TypedDict, total=False):
    action: str
    risk_level: str
    approved: bool
    decided_by: str
    result: str


def _propose_node(state: ApprovalState) -> dict[str, Any]:
    return {"result": "proposed"}


def _approval_node(state: ApprovalState) -> dict[str, Any]:
    # 副作用（落库/执行动作）必须放在 interrupt 返回之后，保证恢复重放时不重复执行
    decision = interrupt({
        "type": "approval_required",
        "action": state["action"],
        "risk_level": state["risk_level"],
    })
    return {
        "approved": bool(decision.get("approved")),
        "decided_by": str(decision.get("decided_by", "user")),
        "result": "approved" if decision.get("approved") else "rejected",
    }


def build_approval_graph(checkpointer: SqliteSaver):
    graph = StateGraph(ApprovalState)
    graph.add_node("propose", _propose_node)
    graph.add_node("approval", _approval_node)
    graph.add_edge(START, "propose")
    graph.add_edge("propose", "approval")
    graph.add_edge("approval", END)
    return graph.compile(checkpointer=checkpointer)


def start_and_wait_approval(checkpointer: SqliteSaver, thread_id: str, action: str, risk_level: str) -> dict[str, Any]:
    """启动图，预期在审批点挂起。返回挂起时的 interrupt 信息。"""
    app = build_approval_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke({"action": action, "risk_level": risk_level}, config)
    # LangGraph 挂起时返回包含 __interrupt__ 的状态
    return result


def resume_with_decision(checkpointer: SqliteSaver, thread_id: str, approved: bool) -> dict[str, Any]:
    """用用户决定恢复图执行。"""
    app = build_approval_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    return app.invoke(Command(resume={"approved": approved, "decided_by": "user"}), config)
