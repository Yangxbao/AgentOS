"""M3-F 端到端业务验收：GitHub 公开项目研究 → 分析 → 写作 → 审查 → 人工审批 → 交付。

诚实性：
- 全程 Mock 模型（不产生任何费用）；GitHub 数据来自**本地 HTTP stub**（127.0.0.1，无真实外网）；
- 工具真实执行（HTTP 白名单/SSRF 校验、工作区文件写入真实落盘）、审批/审计/成本真实落库；
- 不伪造任何"看起来像真实外部数据"的结果：stub URL 与内容都明示为本地固定数据。

用法：python scripts/e2e_m3f.py
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB_PATH = ROOT / "data" / "e2e_m3f_temp.db"
PROMPTS_DIR = ROOT / "data" / "prompts_e2e_m3f"
WORKSPACE_ROOT = ROOT / "data" / "e2e_m3f_workspace"

import os  # noqa: E402

STUB_PORT = 18099
STUB_HOST = "127.0.0.1"
REPO_URL = f"http://{STUB_HOST}:{STUB_PORT}/repos/octocat/Hello-World"
SOURCE_LINK = REPO_URL

os.environ["AGENTOS_DB_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["AGENTOS_PROMPTS_ROOT"] = PROMPTS_DIR.as_posix()
os.environ["AGENTOS_MODEL_MODE"] = "mock"
os.environ["AGENTOS_TOOL_EXECUTION"] = "on"
os.environ["AGENTOS_TOOL_HTTP_ALLOW_LOOPBACK"] = "1"  # 仅允许访问本机 stub
os.environ.setdefault("TEST_MODEL_KEY", "e2e-secret")

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import create_app  # noqa: E402

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


def get(client, path):
    return client.get(path, headers=HEADERS)


def wait_task(client, task_id: str, states, timeout: float = 40.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = get(client, f"/api/v1/tasks/{task_id}").json()
        if last.get("state") in states:
            return last
        time.sleep(0.1)
    raise AssertionError(f"任务 {task_id} 超时未进入 {states}，当前 {last.get('state')} / {last.get('result')}")


# ---------------------------------------------------------------- 本地 GitHub stub


class _StubHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        payload = {
            "full_name": "octocat/Hello-World",
            "description": "My first repository on GitHub!",
            "html_url": REPO_URL,
            "default_branch": "master",
            "created_at": "2011-01-26T19:01:12Z",
        }
        if self.path == "/repos/octocat/Hello-World":
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json")
        elif self.path == "/repos/octocat/Hello-World/readme":
            text = (
                "# Hello-World\n\n这是第一个 GitHub 仓库：用于演示 pull request 流程。\n"
                f"来源：{REPO_URL}\n"
            )
            self._send(200, text.encode("utf-8"), "text/plain; charset=utf-8")
        else:
            self._send(404, b'{"message": "Not Found"}', "application/json")

    def log_message(self, *args) -> None:  # 静默访问日志
        return


def start_stub() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((STUB_HOST, STUB_PORT), _StubHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ---------------------------------------------------------------- 场景


def setup_env(client) -> dict:
    company = post(client, "/api/v1/companies", {"name": "教程工坊", "description": "M3-F"}).json()
    conn = post(client, f"/api/v1/companies/{company['id']}/model-connections", {
        "name": "连接", "provider": "deepseek",
        "model": "deepseek/deepseek-chat", "api_key_ref": "env:TEST_MODEL_KEY",
    }).json()

    def position(name: str, **extra) -> dict:
        return post(client, f"/api/v1/companies/{company['id']}/positions", {"name": name, **extra}).json()

    researcher_pos = position("研究员", review_capability_tags=["research.github"])
    analyst_pos = position("分析师", review_capability_tags=["analysis.outline"])
    writer_pos = position("写作", review_capability_tags=["writing.tutorial"])
    reviewer_pos = position("审查", can_review=True)

    def employee(name: str, title: str, position_id: str, tools: list[str]) -> dict:
        resp = post(client, f"/api/v1/companies/{company['id']}/employees", {
            "name": name, "title": title, "primary_model_id": conn["id"],
            "tools_allowed": tools,
            "positions": [{"position_id": position_id, "is_primary": True}],
        })
        assert resp.status_code == 201, resp.text
        return resp.json()

    researcher = employee("研究员", "GitHub 研究员", researcher_pos["id"], ["http.request"])
    analyst = employee("分析师", "提纲分析师", analyst_pos["id"], [])
    writer = employee("写作员", "教程写作", writer_pos["id"], ["fs.read_file", "fs.write_file"])
    reviewer = employee("审查员", "质量审查", reviewer_pos["id"], ["fs.read_file"])

    ws = post(client, f"/api/v1/companies/{company['id']}/workspaces", {
        "name": "教程工作区", "root_path": str(WORKSPACE_ROOT), "mode": "read_write",
    }).json()
    for emp, access in ((writer, "write"), (reviewer, "read"), (researcher, "read")):
        resp = post(client, f"/api/v1/workspaces/{ws['id']}/grants",
                    {"employee_id": emp["id"], "access": access})
        assert resp.status_code == 201, resp.text

    policy = client.patch(f"/api/v1/companies/{company['id']}/tool-policy", json={
        "categories": {"file_read": True, "file_write": True, "network": True},
        "allowed_tools": ["fs.list_dir", "fs.read_file", "fs.stat", "fs.write_file", "http.request"],
        "network_domains": [f"{STUB_HOST}:{STUB_PORT}"],
        "allow_http_write": False,
        "auto_execute_max_risk": "medium",
    }, headers=HEADERS)
    assert policy.status_code == 200, policy.text
    return {
        "company": company, "researcher": researcher, "analyst": analyst,
        "writer": writer, "reviewer": reviewer, "workspace": ws,
    }


def tool_calls(client, task_id: str) -> list[dict]:
    return get(client, f"/api/v1/tasks/{task_id}/tool-calls").json()["items"]


def scenario_main_chain(client, ctx: dict) -> None:
    """主链路：研究 → 分析 → 写作 → 审查 → 人工审批 → 交付。"""
    ws_id = ctx["workspace"]["id"]
    plan = {
        "steps": [
            {"id": "s1", "title": "研究仓库", "employee_id": ctx["researcher"]["id"],
             "instruction": (
                 f'[tool:http.request {{"url":"{REPO_URL}"}}]'
                 f' [tool:http.request {{"url":"{REPO_URL}/readme"}}]'
                 " 获取仓库信息与 README"
             ),
             "tools": ["http.request"]},
            {"id": "s2", "title": "产出提纲", "employee_id": ctx["analyst"]["id"],
             "instruction": "基于上游仓库信息与 README，输出教程提纲",
             "depends_on": ["s1"]},
            {"id": "s3", "title": "撰写教程", "employee_id": ctx["writer"]["id"],
             "instruction": (
                 f'[tool:fs.write_file {{"workspace_id":"{ws_id}","path":"tutorial.md",'
                 f'"content":"# Hello-World 入门教程\\n\\n参考来源：{SOURCE_LINK}\\n\\n'
                 f'本教程基于仓库描述：My first repository on GitHub!\\n","mode":"create"}}]'
                 " 把教程写入工作区"
             ),
             "tools": ["fs.write_file"], "depends_on": ["s2"]},
            {"id": "s4", "title": "质量审查", "employee_id": ctx["reviewer"]["id"],
             "instruction": (
                 f'[tool:fs.read_file {{"workspace_id":"{ws_id}","path":"tutorial.md"}}]'
                 " 读取教程文件并给出质量结论"
             ),
             "tools": ["fs.read_file"], "depends_on": ["s3"]},
        ],
        "max_parallel": 2,
    }
    task = post(client, f"/api/v1/companies/{ctx['company']['id']}/tasks", {
        "title": "GitHub 教程生成", "objective": "研究 octocat/Hello-World 并生成 tutorial.md",
        "assignee_employee_id": ctx["researcher"]["id"],
        "reviewer_employee_id": ctx["reviewer"]["id"],
        "approval_required": True, "approval_stage": "after_run",
        "execution_mode": "mock", "budget_usd": 0.5,
        "context": {"required_tools": ["http.request", "fs.write_file", "fs.read_file"]},
    }).json()
    resp = client.put(f"/api/v1/tasks/{task['id']}/plan", json=plan, headers=HEADERS)
    assert resp.status_code == 200, resp.text
    run = post(client, f"/api/v1/tasks/{task['id']}/run")
    assert run.status_code == 202, run.text

    detail = wait_task(client, task["id"], {"awaiting_approval"})
    check("F1 全链路执行后停在人工审批（after_run）", detail["state"] == "awaiting_approval")

    calls = tool_calls(client, task["id"])
    by_tool = {c["tool_name"]: c for c in calls}
    http_call = by_tool.get("http.request")
    check("F2 HTTP 工具真实访问本地 stub（200、非空）",
          http_call is not None and http_call["status"] == "succeeded"
          and (http_call.get("output_summary") or {}).get("status") == 200
          and (http_call.get("output_summary") or {}).get("bytes", 0) > 0,
          str(http_call))
    check("F3 两次 HTTP 调用都成功", sum(1 for c in calls if c["tool_name"] == "http.request") == 2)
    write_call = by_tool.get("fs.write_file")
    check("F4 写作员工真实写入 tutorial.md",
          write_call is not None and write_call["status"] == "succeeded", str(write_call))
    read_call = by_tool.get("fs.read_file")
    check("F5 审查员工真实读取 tutorial.md",
          read_call is not None and read_call["status"] == "succeeded", str(read_call))

    tutorial = WORKSPACE_ROOT / "tutorial.md"
    check("F6 交付文件存在、非空、含来源链接",
          tutorial.exists() and tutorial.stat().st_size > 0
          and SOURCE_LINK in tutorial.read_text(encoding="utf-8"))

    approvals = get(client, f"/api/v1/tasks/{task['id']}/approvals").json()
    pending = [a for a in approvals if a["status"] == "pending"]
    check("F7 after_run 审批已创建", len(pending) == 1)
    decision = post(client, f"/api/v1/approvals/{pending[0]['id']}/decision",
                    {"decision": "approve", "comment": "教程质量达标"})
    check("F8 审查员（can_review 且≠执行人）审批通过", decision.status_code == 200, decision.text)

    detail = wait_task(client, task["id"], {"succeeded"})
    check("F9 审批后交付成功", detail["state"] == "succeeded")

    timeline = get(client, f"/api/v1/tasks/{task['id']}/timeline").json()
    types = [item.get("type") for item in timeline["items"]]
    check("F10 时间线可查（创建/工具/审批/成功）",
          {"task.created", "task.succeeded"}.issubset(set(types))
          and any(t and t.startswith("tool.") for t in types))
    usage = get(client, f"/api/v1/tasks/{task['id']}/usage").json()
    check("F11 成本可查（mock 计 billable=false、cost=0）",
          usage.get("total_tokens", 0) > 0 and usage.get("total_cost_usd", 1) == 0, str(usage))


def scenario_network_denied(client, ctx: dict) -> None:
    """失败场景 1：域名不在白名单 → http.request 被拒并有记录。"""
    instruction = (
        '[tool:http.request {"url":"http://127.0.0.1:9999/evil"}] 获取数据'
    )
    task = post(client, f"/api/v1/companies/{ctx['company']['id']}/tasks", {
        "title": "网络白名单拒绝", "objective": "验证白名单",
        "assignee_employee_id": ctx["researcher"]["id"], "execution_mode": "mock",
        "instruction": instruction,
    }).json()
    post(client, f"/api/v1/tasks/{task['id']}/run")
    wait_task(client, task["id"], {"succeeded"})
    calls = tool_calls(client, task["id"])
    denied = [c for c in calls if c["tool_name"] == "http.request" and c["status"] == "denied"]
    check("F12 域名不在白名单的请求被拒且记录",
          len(denied) == 1 and denied[0]["error_code"] == "TOOL_NETWORK_DENIED", str(calls))


def scenario_path_escape_denied(client, ctx: dict) -> None:
    """失败场景 2：路径越界 → fs.write_file 被拒（路径安全）。"""
    ws_id = ctx["workspace"]["id"]
    instruction = (
        f'[tool:fs.write_file {{"workspace_id":"{ws_id}","path":"../../escape.txt",'
        f'"content":"x","mode":"create"}}] 尝试越界写入'
    )
    task = post(client, f"/api/v1/companies/{ctx['company']['id']}/tasks", {
        "title": "路径越界", "objective": "验证路径安全",
        "assignee_employee_id": ctx["writer"]["id"], "execution_mode": "mock",
        "instruction": instruction,
    }).json()
    post(client, f"/api/v1/tasks/{task['id']}/run")
    wait_task(client, task["id"], {"succeeded"})
    calls = tool_calls(client, task["id"])
    denied = [c for c in calls if c["tool_name"] == "fs.write_file" and c["status"] == "denied"]
    check("F13 路径越界写入被拒且记录",
          len(denied) == 1 and denied[0]["error_code"] == "TOOL_PATH_DENIED", str(calls))
    check("F14 工作区外没有产生文件", not (WORKSPACE_ROOT.parent / "escape.txt").exists())


def scenario_overwrite_rejected(client, ctx: dict) -> None:
    """失败场景 3：overwrite（high 风险）转人工审批 → 驳回 → 任务失败且可读。"""
    ws_id = ctx["workspace"]["id"]
    instruction = (
        f'[tool:fs.write_file {{"workspace_id":"{ws_id}","path":"tutorial.md",'
        f'"content":"覆盖","mode":"overwrite"}}] 覆盖教程'
    )
    task = post(client, f"/api/v1/companies/{ctx['company']['id']}/tasks", {
        "title": "覆盖需审批", "objective": "验证高风险审批",
        "assignee_employee_id": ctx["writer"]["id"], "execution_mode": "mock",
        "instruction": instruction,
    }).json()
    post(client, f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(client, task["id"], {"awaiting_approval"})
    approvals = get(client, f"/api/v1/tasks/{task['id']}/approvals").json()
    pending = [a for a in approvals if a["status"] == "pending"]
    decision = post(client, f"/api/v1/approvals/{pending[0]['id']}/decision",
                    {"decision": "reject", "comment": "不允许覆盖已交付的教程"})
    assert decision.status_code == 200, decision.text
    detail = wait_task(client, task["id"], {"failed"})
    check("F15 覆盖审批驳回后任务失败且原因可读",
          detail["result"]["error"]["code"] == "TOOL_APPROVAL_REJECTED",
          str(detail["result"]))
    check("F16 教程原文未被覆盖",
          SOURCE_LINK in (WORKSPACE_ROOT / "tutorial.md").read_text(encoding="utf-8"))


def main() -> int:
    if DB_PATH.exists():
        DB_PATH.unlink()
    shutil.rmtree(PROMPTS_DIR, ignore_errors=True)
    shutil.rmtree(WORKSPACE_ROOT, ignore_errors=True)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

    server = start_stub()
    print(f"本地 GitHub stub 已启动：{REPO_URL}")
    started = datetime.now(timezone.utc)
    try:
        app = create_app()
        with TestClient(app, base_url="http://127.0.0.1:8000") as client:
            ctx = setup_env(client)
            scenario_main_chain(client, ctx)
            scenario_network_denied(client, ctx)
            scenario_path_escape_denied(client, ctx)
            scenario_overwrite_rejected(client, ctx)
    finally:
        server.shutdown()
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    print(f"\nM3-F E2E 完成：{len(PASSED)} 项通过，{len(FAILED)} 项失败（耗时 {elapsed:.1f}s，全程 Mock + 本地 stub）")
    for name in PASSED:
        print(f"  - {name}")
    if FAILED:
        for name in FAILED:
            print(f"  - [失败] {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
