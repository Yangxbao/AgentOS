"""实验：真实模型（DeepSeek）调用文件读取工具——验证 M3 遗留的"真实模型工具调用未验证"缺口。

诚实性设计：
- test.txt 内容含**随机 nonce 校验码**（模型不可能凭参数知识猜到），
  模型最终汇报里出现 nonce = 真实通过 fs.read_file 读到的铁证；
- 全程记录 tool_call 落库状态、usage_record（billable 必须为 True）、真实成本；
- 失败（模型不调工具/编造内容/报错）原样报告，不伪造成功。

成本护栏：AGENTOS_MAX_TOKENS=512/次、task.budget_usd=0.05 熔断、单步超时 240s。
"""
from __future__ import annotations

import secrets
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB_PATH = ROOT / "data" / "exp_real_tool.db"
PROMPTS_DIR = ROOT / "data" / "prompts_exp_real"
WORKSPACE_ROOT = ROOT / "data" / "exp_real_workspace"

import os  # noqa: E402

os.environ["AGENTOS_DB_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["AGENTOS_PROMPTS_ROOT"] = PROMPTS_DIR.as_posix()
os.environ["AGENTOS_MODEL_MODE"] = "real"  # 本实验明确授权真实调用
os.environ["AGENTOS_TOOL_EXECUTION"] = "on"
os.environ["AGENTOS_MAX_TOKENS"] = "512"

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import create_app  # noqa: E402

HEADERS = {"Origin": "http://127.0.0.1:5173", "X-AgentOS-Client": "web"}
INSTRUCTION = """你现在是一名负责文件分析的 AI 数字员工。

本次任务的目标是验证你能否通过系统提供的文件工具，真实读取工作区中的文件。

## 一、任务目标

请在当前分配给你的工作区中找到 `test.txt`，读取其完整内容，并向我汇报读取结果。

## 二、执行步骤

1. 首先检查当前可用的工具，确认是否可以使用 `fs.list_dir` 和 `fs.read_file`。
2. 使用 `fs.list_dir` 查看当前工作区中的文件和目录。
3. 找到 `test.txt` 后，使用 `fs.read_file` 读取文件内容。
4. 如果文件不在工作区根目录，请根据实际目录结构继续定位，不要猜测文件路径。
5. 读取成功后，整理文件中的实际内容。
6. 如果读取失败，请报告工具返回的真实错误，不要编造文件内容，也不要假装读取成功。

## 三、安全限制

- 只能读取当前授权工作区内的文件。
- 不得访问工作区以外的文件。
- 不得创建、修改、删除或移动任何文件。
- 不得执行 Shell 命令。
- 不得调用与本次文件读取无关的工具。
- 不要通过模型自身知识推测 test.txt 的内容。

## 四、最终汇报

请明确回答：

1. 是否成功调用 `fs.list_dir`？
2. 是否成功找到 `test.txt`？
3. 是否成功调用 `fs.read_file`？
4. 读取到的文件完整内容是什么？
5. 本次调用过程中是否出现错误？
6. 你是否通过真实工具读取了文件，而不是根据已有上下文猜测？

请以实际工具执行结果为依据完成任务。"""


def main() -> int:
    for p in (DB_PATH,):
        if p.exists():
            p.unlink()
    shutil.rmtree(PROMPTS_DIR, ignore_errors=True)
    shutil.rmtree(WORKSPACE_ROOT, ignore_errors=True)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

    nonce = f"NX-{secrets.token_hex(4).upper()}"
    test_txt = WORKSPACE_ROOT / "test.txt"
    test_txt.write_text(
        "这是 AgentOS 真实模型工具调用验证文件。\n"
        f"随机校验码：{nonce}\n"
        "第二行：文件系统工具端到端实验。\n"
        f"生成时间：{datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    print(f"nonce（防编造校验码，模型不可预知）：{nonce}")

    started = datetime.now(timezone.utc)
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        company = client.post("/api/v1/companies", json={"name": "实验公司"}, headers=HEADERS).json()
        conn = client.post(
            f"/api/v1/companies/{company['id']}/model-connections",
            json={"name": "DeepSeek 真实", "provider": "deepseek",
                  "model": "deepseek/deepseek-chat", "api_key_ref": "env:DEEPSEEK_API_KEY"},
            headers=HEADERS,
        ).json()
        pos = client.post(
            f"/api/v1/companies/{company['id']}/positions", json={"name": "文件分析"},
            headers=HEADERS,
        ).json()
        emp = client.post(
            f"/api/v1/companies/{company['id']}/employees",
            json={"name": "文件分析员", "title": "文件分析 AI 数字员工",
                  "primary_model_id": conn["id"],
                  "tools_allowed": ["fs.list_dir", "fs.read_file"],
                  "positions": [{"position_id": pos["id"], "is_primary": True}]},
            headers=HEADERS,
        ).json()
        ws = client.post(
            f"/api/v1/companies/{company['id']}/workspaces",
            json={"name": "实验工作区", "root_path": str(WORKSPACE_ROOT), "mode": "read_write"},
            headers=HEADERS,
        ).json()
        grant = client.post(
            f"/api/v1/workspaces/{ws['id']}/grants",
            json={"employee_id": emp["id"], "access": "read"}, headers=HEADERS,
        )
        assert grant.status_code == 201, grant.text
        policy = client.patch(
            f"/api/v1/companies/{company['id']}/tool-policy",
            json={"categories": {"file_read": True},
                  "allowed_tools": ["fs.list_dir", "fs.read_file"]},
            headers=HEADERS,
        )
        assert policy.status_code == 200, policy.text

        task = client.post(
            f"/api/v1/companies/{company['id']}/tasks",
            json={"title": "真实模型文件读取验证", "objective": "验证真实模型调用 fs 工具",
                  "assignee_employee_id": emp["id"], "execution_mode": "real",
                  "budget_usd": 0.05,
                  "context": {"step_timeout_s": 240},
                  "instruction": INSTRUCTION},
            headers=HEADERS,
        ).json()
        run = client.post(f"/api/v1/tasks/{task['id']}/run", headers=HEADERS)
        print("run:", run.status_code, run.json())
        assert run.status_code == 202

        deadline = time.time() + 300
        detail = {}
        while time.time() < deadline:
            detail = client.get(f"/api/v1/tasks/{task['id']}").json()
            if detail["state"] in {"succeeded", "failed", "paused", "cancelled"}:
                break
            time.sleep(1)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()

        print("\n===== 实验结果 =====")
        print("任务终态:", detail["state"], f"（耗时 {elapsed:.1f}s）")
        print("task.result.error:", detail.get("result", {}).get("error"))
        summary = (detail.get("result") or {}).get("summary") or ""
        print("\n----- 模型最终汇报（原文）-----")
        print(summary)
        print("----- 汇报结束 -----\n")

        calls = client.get(f"/api/v1/tasks/{task['id']}/tool-calls").json()["items"]
        print("工具调用落库记录：")
        for c in calls:
            print(f"  - {c['tool_name']} | status={c['status']} | {c.get('error_code')} | "
                  f"output={json.dumps(c.get('output_summary'), ensure_ascii=False)[:200]}")

        usage = client.get(f"/api/v1/tasks/{task['id']}/usage").json()
        print("用量与真实成本：", {k: usage.get(k) for k in
                                   ("calls", "total_prompt_tokens", "total_completion_tokens",
                                    "total_cost_usd", "total_tokens")})

        nonce_in_summary = nonce in summary
        read_ok = any(
            c["tool_name"] == "fs.read_file" and c["status"] == "succeeded" for c in calls
        )
        list_ok = any(
            c["tool_name"] == "fs.list_dir" and c["status"] == "succeeded" for c in calls
        )
        print("\n===== 判定 =====")
        print(f"1 fs.list_dir 真实调用成功: {list_ok}")
        print(f"2 fs.read_file 真实调用成功: {read_ok}")
        print(f"3 nonce 出现在模型汇报中（真实读取铁证）: {nonce_in_summary}")
        print(f"4 billable=True（真实计费）: {usage.get('billable_calls', 0) > 0 or bool(usage.get('calls'))}")
        ok = detail["state"] == "succeeded" and list_ok and read_ok and nonce_in_summary
        print(f"\n实验结论: {'PASS — 真实模型通过系统工具真实读取了文件' if ok else 'FAIL — 见上方原始证据'}")
        return 0 if ok else 1


import json  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
