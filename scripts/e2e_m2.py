"""M2 端到端验收（M2-F）：10 项检查，真实 ASGI + 临时库 + 独立提示词目录。

默认全部走 Mock（不产生任何外部调用/费用）。加 `--real` 时额外执行一次
现有 DeepSeek 配置的最小真实调用（max_tokens 由 AGENTOS_MAX_TOKENS 限制，默认 96）。

用法：
    python scripts/e2e_m2.py
    python scripts/e2e_m2.py --real
"""
from __future__ import annotations

import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB_PATH = ROOT / "data" / "e2e_m2_temp.db"
PROMPTS_DIR = ROOT / "data" / "prompts_e2e_m2"

import os  # noqa: E402

os.environ["AGENTOS_DB_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["AGENTOS_PROMPTS_ROOT"] = PROMPTS_DIR.as_posix()
os.environ["AGENTOS_MODEL_MODE"] = "mock"
os.environ["AGENTOS_MAX_TOKENS"] = "96"
os.environ.setdefault("TEST_MODEL_KEY", "e2e-secret")

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import create_app  # noqa: E402
from packages.execution.runner import TaskRunner  # noqa: E402
from packages.persistence import get_session  # noqa: E402
from packages.persistence.models import Task, TaskRun  # noqa: E402
from packages.shared.types import new_id  # noqa: E402

HEADERS = {"Origin": "http://127.0.0.1:5173", "X-AgentOS-Client": "web"}
PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"[PASS] {name}")
    else:
        FAILED.append(name)
        print(f"[FAIL] {name} :: {detail}")


def post(client, path, payload=None):
    return client.post(path, json=payload if payload is not None else {}, headers=HEADERS)


def get(client, path, params=None):
    return client.get(path, params=params, headers=HEADERS)


def wait_task(client, task_id: str, states, timeout: float = 40.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = get(client, f"/api/v1/tasks/{task_id}").json()
        if last.get("state") in states:
            return last
        time.sleep(0.1)
    raise AssertionError(f"任务 {task_id} 超时未进入 {states}，当前 {last.get('state')} / {last.get('result')}")


def agents_of(detail: dict) -> list[dict]:
    return [agent for run in detail["runs"] for agent in run["agent_runs"]]


def setup_company(client) -> dict:
    company = post(client, "/api/v1/companies", {"name": "M2 验收公司"}).json()
    cid = company["id"]
    connection = post(client, f"/api/v1/companies/{cid}/model-connections", {
        "name": "DeepSeek", "provider": "deepseek",
        "model": "deepseek/deepseek-chat", "api_key_ref": "env:DEEPSEEK_API_KEY",
        "timeout_s": 60,
    }).json()

    def position(name, **extra):
        return post(client, f"/api/v1/companies/{cid}/positions", {"name": name, **extra}).json()

    def employee(name, title, position_id, tools=None):
        return post(client, f"/api/v1/companies/{cid}/employees", {
            "name": name, "title": title, "primary_model_id": connection["id"],
            "tools_allowed": tools or [],
            "positions": [{"position_id": position_id, "is_primary": True}],
        }).json()

    manager_pos = position("负责人", is_managerial=True, can_review=True)
    dev_pos = position("开发", review_capability_tags=["coding.python"])
    qa_pos = position("测试", can_review=True, review_capability_tags=["test.unit"])
    return {
        "company": company, "connection": connection,
        "manager": employee("经理甲", "负责人", manager_pos["id"]),
        "dev": employee("开发乙", "开发工程师", dev_pos["id"], tools=["file.write"]),
        "qa": employee("测试丙", "测试工程师", qa_pos["id"]),
    }


def create_task(client, company_id, assignee, **extra) -> dict:
    payload = {"title": "验收任务", "objective": "完成验收目标", "assignee_employee_id": assignee, **extra}
    resp = post(client, f"/api/v1/companies/{company_id}/tasks", payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def scenario_1_single(client, ctx) -> None:
    task = create_task(client, ctx["company"]["id"], ctx["dev"]["id"],
                       title="S1 单 Agent", execution_mode="mock")
    assert post(client, f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(client, task["id"], {"succeeded"})
    agents = agents_of(detail)
    check("S1 单 Agent 完成任务", len(agents) == 1 and agents[0]["state"] == "succeeded")
    check("S1 Mock 不计费", detail["usage"]["records"][0]["billable"] is False
          and detail["usage"]["total_cost_usd"] == 0.0, str(detail["usage"]))
    check("S1 事件与结果落库", bool(detail["result"].get("summary")) and len(detail["runs"]) == 1)


def scenario_2_multi(client, ctx) -> None:
    company_id = ctx["company"]["id"]
    task = create_task(client, company_id, ctx["manager"]["id"], title="S2 三员工协作")
    plan = client.put(f"/api/v1/tasks/{task['id']}/plan", json={"steps": [
        {"id": "s1", "employee_id": ctx["dev"]["id"], "instruction": "调研需求"},
        {"id": "s2", "employee_id": ctx["qa"]["id"], "instruction": "验证方案", "depends_on": ["s1"]},
        {"id": "s3", "employee_id": ctx["manager"]["id"], "instruction": "汇总结论", "depends_on": ["s2"]},
    ]}, headers=HEADERS)
    assert plan.status_code == 200, plan.text
    assert post(client, f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(client, task["id"], {"succeeded"})
    agents = agents_of(detail)
    check("S2 三员工各执行一步",
          [agent["step_id"] for agent in agents] == ["s1", "s2", "s3"]
          and len({agent["employee_id"] for agent in agents}) == 3)
    timeline = get(client, f"/api/v1/tasks/{task['id']}/timeline").json()["items"]
    handoffs = [item for item in timeline if item["kind"] == "handoff"]
    check("S2 交接记录完整", len(handoffs) == 2 and all(item["summary"] for item in handoffs))
    check("S2 子任务全部完成", {child["state"] for child in detail["children"]} == {"succeeded"})


def scenario_3_approval(client, ctx) -> None:
    task = create_task(client, ctx["company"]["id"], ctx["dev"]["id"],
                       title="S3 审批后恢复", approval_required=True, approval_stage="after_run",
                       execution_mode="mock")
    assert post(client, f"/api/v1/tasks/{task['id']}/run").status_code == 202
    gated = wait_task(client, task["id"], {"awaiting_approval"})
    before = len(agents_of(gated))
    approval = gated["pending_approvals"][0]
    resp = post(client, f"/api/v1/approvals/{approval['id']}/decision",
                {"decision": "approve", "comment": "验收通过"})
    assert resp.status_code == 200, resp.text
    final = wait_task(client, task["id"], {"succeeded"})
    check("S3 审批后恢复且不重复执行",
          before == 1 and len(agents_of(final)) == 1 and final["state"] == "succeeded")


def scenario_4_reject(client, ctx) -> None:
    company_id = ctx["company"]["id"]
    task = create_task(client, company_id, ctx["dev"]["id"],
                       title="S4 驳回重做", approval_required=True,
                       approval_stage="after_run", execution_mode="mock")
    plan = client.put(f"/api/v1/tasks/{task['id']}/plan", json={"steps": [
        {"id": "s1", "employee_id": ctx["dev"]["id"], "instruction": "第一步"},
        {"id": "s2", "employee_id": ctx["qa"]["id"], "instruction": "第二步", "depends_on": ["s1"]},
    ]}, headers=HEADERS)
    assert plan.status_code == 200, plan.text
    assert post(client, f"/api/v1/tasks/{task['id']}/run").status_code == 202
    gated = wait_task(client, task["id"], {"awaiting_approval"})
    approval = gated["pending_approvals"][0]
    rejected = post(client, f"/api/v1/approvals/{approval['id']}/decision",
                    {"decision": "request_changes", "comment": "第二步重做",
                     "rewind_step_id": "s2"})
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["state"] == "rework_required"

    assert post(client, f"/api/v1/tasks/{task['id']}/resume").status_code == 202
    again = wait_task(client, task["id"], {"awaiting_approval"})
    agents = agents_of(again)
    counts = {step: [agent["step_id"] for agent in agents].count(step) for step in ("s1", "s2")}
    second = again["pending_approvals"][0]
    assert post(client, f"/api/v1/approvals/{second['id']}/decision",
                {"decision": "approve", "comment": "重做通过"}).status_code == 200
    final = wait_task(client, task["id"], {"succeeded"})
    check("S4 驳回回到指定步骤且不重跑上游",
          counts == {"s1": 1, "s2": 2} and final["rework_count"] == 1, str(counts))


def scenario_5_failure_and_cancel(client, ctx) -> None:
    company_id = ctx["company"]["id"]
    failed_task = create_task(client, company_id, ctx["dev"]["id"],
                              title="S5 失败", instruction="[fail] 故意失败", execution_mode="mock")
    assert post(client, f"/api/v1/tasks/{failed_task['id']}/run").status_code == 202
    failed = wait_task(client, failed_task["id"], {"failed"})
    check("S5 失败被正确记录",
          failed["result"]["error"]["code"] == "EXECUTION_FAILED"
          and agents_of(failed)[0]["state"] == "failed")

    cancel_task = create_task(client, company_id, ctx["dev"]["id"],
                              title="S5 取消", execution_mode="mock")
    plan = client.put(f"/api/v1/tasks/{cancel_task['id']}/plan", json={"steps": [
        {"id": "s1", "employee_id": ctx["dev"]["id"], "instruction": "慢步骤一"},
        {"id": "s2", "employee_id": ctx["qa"]["id"], "instruction": "[slow:300] 慢步骤二", "depends_on": ["s1"]},
        {"id": "s3", "employee_id": ctx["manager"]["id"], "instruction": "[slow:300] 慢步骤三", "depends_on": ["s2"]},
    ]}, headers=HEADERS)
    assert plan.status_code == 200, plan.text
    assert post(client, f"/api/v1/tasks/{cancel_task['id']}/run").status_code == 202
    deadline = time.time() + 20
    while time.time() < deadline:
        if agents_of(get(client, f"/api/v1/tasks/{cancel_task['id']}").json()):
            break
        time.sleep(0.05)
    assert post(client, f"/api/v1/tasks/{cancel_task['id']}/cancel").status_code == 200
    cancelled = wait_task(client, cancel_task["id"], {"cancelled"})
    check("S5 取消在步骤边界生效",
          cancelled["state"] == "cancelled" and len(agents_of(cancelled)) < 3)


def scenario_6_restart(client, ctx) -> None:
    task = create_task(client, ctx["company"]["id"], ctx["dev"]["id"],
                       title="S6 重启恢复", execution_mode="mock")
    session = get_session()
    try:
        session.add(TaskRun(
            id=new_id(), owner_id="local", task_id=task["id"], run_no=1, trigger="manual",
            state="running", mode="mock", checkpoint={}, worker_id="dead-worker",
            started_at=datetime.now(timezone.utc),
        ))
        db_task = session.get(Task, task["id"])
        db_task.state = "running"
        session.commit()
    finally:
        session.close()

    recovered = TaskRunner().recover()
    detail = get(client, f"/api/v1/tasks/{task['id']}").json()
    assert recovered["interrupted_runs"] == 1
    check("S6 重启后标记中断并转 paused",
          detail["state"] == "paused" and detail["runs"][0]["state"] == "interrupted")
    assert post(client, f"/api/v1/tasks/{task['id']}/resume").status_code == 202
    final = wait_task(client, task["id"], {"succeeded"})
    check("S6 恢复后续跑成功", final["runs"][-1]["run_no"] == 2)


def scenario_7_permission(client, ctx) -> None:
    task = create_task(client, ctx["company"]["id"], ctx["qa"]["id"],
                       title="S7 权限隔离", context={"required_tools": ["file.write"]},
                       execution_mode="mock")
    assert post(client, f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(client, task["id"], {"failed"})
    check("S7 越权工具被拒且未调用模型",
          detail["result"]["error"]["code"] == "EXECUTION_PERMISSION_DENIED"
          and agents_of(detail) == [] and detail["usage"]["calls"] == 0)


def scenario_8_real(client, ctx) -> None:
    key_configured = bool(os.environ.get("DEEPSEEK_API_KEY"))
    if not key_configured:
        print("[SKIP] S8 真实模型：未配置 DEEPSEEK_API_KEY，标记为未验证")
        return
    task = create_task(client, ctx["company"]["id"], ctx["manager"]["id"],
                       title="S8 真实模型最小协作",
                       instruction="只回复这一句话：M2 real call ok",
                       execution_mode="real")
    plan = client.put(f"/api/v1/tasks/{task['id']}/plan", json={"steps": [
        {"id": "s1", "employee_id": ctx["dev"]["id"],
         "instruction": "只回复这一句话：M2 real step1 ok"},
        {"id": "s2", "employee_id": ctx["qa"]["id"],
         "instruction": "只回复这一句话：M2 real step2 ok", "depends_on": ["s1"]},
    ]}, headers=HEADERS)
    assert plan.status_code == 200, plan.text
    assert post(client, f"/api/v1/tasks/{task['id']}/run").status_code == 202
    detail = wait_task(client, task["id"], {"succeeded", "failed"}, timeout=240)
    agents = agents_of(detail)
    ok = detail["state"] == "succeeded" and len(agents) == 2 and all(
        agent["state"] == "succeeded" for agent in agents
    )
    check("S8 真实模型完成两步协作", bool(ok), str(detail.get("result")))
    if not ok:
        return
    records = detail["usage"]["records"]
    handoffs = [item for item in get(client, f"/api/v1/tasks/{task['id']}/timeline").json()["items"]
                if item["kind"] == "handoff"]
    check("S8 真实调用全部计费且交接落库",
          all(item["billable"] is True for item in records) and len(handoffs) == 1)
    for record in records:
        print(f"       {record['employee_name']} model={record['model']} "
              f"tokens={record['prompt_tokens']}+{record['completion_tokens']} "
              f"cost=${record['cost_usd']}")
    print(f"       合计 tokens={detail['usage']['total_tokens']} "
          f"cost=${detail['usage']['total_cost_usd']}")


def cleanup() -> None:
    from packages.persistence import db as db_module

    factory = getattr(db_module, "_session_factory", None)
    if factory is not None:
        bind = factory.kw.get("bind")
        if bind is not None:
            bind.dispose()
    for path in (DB_PATH, Path(f"{DB_PATH}-wal"), Path(f"{DB_PATH}-shm")):
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            print(f"[WARN] 临时数据库清理失败：{path} ({exc})")
    if PROMPTS_DIR.exists():
        shutil.rmtree(PROMPTS_DIR, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    run_real = "--real" in argv
    for path in (DB_PATH, Path(f"{DB_PATH}-wal"), Path(f"{DB_PATH}-shm")):
        if path.exists():
            path.unlink()
    if PROMPTS_DIR.exists():
        shutil.rmtree(PROMPTS_DIR, ignore_errors=True)

    app = create_app()
    print(f"M2 E2E 开始（mock 模式{'+ 真实最小调用' if run_real else ''}）")
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        ctx = setup_company(client)
        scenario_1_single(client, ctx)
        scenario_2_multi(client, ctx)
        scenario_3_approval(client, ctx)
        scenario_4_reject(client, ctx)
        scenario_5_failure_and_cancel(client, ctx)
        scenario_6_restart(client, ctx)
        scenario_7_permission(client, ctx)
        if run_real:
            scenario_8_real(client, ctx)

    cleanup()
    print(f"\nM2 E2E 完成：{len(PASSED)} 项通过，{len(FAILED)} 项失败")
    for name in PASSED:
        print(f"  - {name}")
    for name in FAILED:
        print(f"  ! {name}")
    print("浏览器可视化验收：未执行（未安装 Playwright，按约束不安装）")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
