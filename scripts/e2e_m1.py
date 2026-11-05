"""M1 端到端验收（B6）：三个场景，真实 ASGI + 临时 SQLite + 真实提示词文件。

说明：不调用真实 LLM（无外部付费/网络依赖）；模型能力来自本地 catalog。
运行：python scripts/e2e_m1.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "data" / "e2e_m1_temp.db"
PROMPTS_ROOT_DIR = ROOT / "data" / "prompts_e2e"
PROMPTS_DIR = PROMPTS_ROOT_DIR / "employees"

os.environ["AGENTOS_DB_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["AGENTOS_PROMPTS_ROOT"] = PROMPTS_ROOT_DIR.as_posix()
os.environ.setdefault("TEST_MODEL_KEY", "e2e-secret")
os.environ.setdefault("OPENAI_API_KEY", "e2e-openai")

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import create_app  # noqa: E402
from packages.persistence import get_session  # noqa: E402
from packages.persistence.models import UsageRecord  # noqa: E402

HEADERS = {"Origin": "http://127.0.0.1:5173", "X-AgentOS-Client": "web"}
PASSED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} 失败：{detail}")
    PASSED.append(name)
    print(f"[PASS] {name}")


def post(client, url, payload):
    resp = client.post(url, json=payload, headers=HEADERS)
    assert resp.status_code in (200, 201), f"POST {url} -> {resp.status_code} {resp.text}"
    return resp.json()


def scenario_1(client) -> dict:
    company = post(client, "/api/v1/companies", {"name": "E2E 科技"})
    cid = company["id"]
    dev_dept = post(client, f"/api/v1/companies/{cid}/departments", {"name": "研发部"})
    qa_dept = post(client, f"/api/v1/companies/{cid}/departments", {"name": "质量部"})
    dev_pos = post(client, f"/api/v1/companies/{cid}/positions", {
        "name": "开发工程师", "department_id": dev_dept["id"],
        "review_capability_tags": ["coding.python", "test.unit"],
        "default_permissions": {"max_risk_level": "high"},
    })
    qa_pos = post(client, f"/api/v1/companies/{cid}/positions", {
        "name": "测试工程师", "department_id": qa_dept["id"], "can_review": True,
        "review_capability_tags": ["coding.python", "test.unit"],
    })
    cto_pos = post(client, f"/api/v1/companies/{cid}/positions", {
        "name": "CTO", "can_review": True, "is_managerial": True,
        "review_capability_tags": ["coding.python", "test.unit"],
    })
    ds = post(client, f"/api/v1/companies/{cid}/model-connections", {
        "name": "DeepSeek", "provider": "deepseek", "model": "deepseek/deepseek-chat",
        "api_key_ref": "env:TEST_MODEL_KEY",
    })
    oa = post(client, f"/api/v1/companies/{cid}/model-connections", {
        "name": "OpenAI", "provider": "openai", "model": "openai/gpt-4o-mini",
        "api_key_ref": "env:OPENAI_API_KEY",
    })
    cto = post(client, f"/api/v1/companies/{cid}/employees", {
        "name": "CTO 张", "primary_model_id": ds["id"],
        "positions": [{"position_id": cto_pos["id"], "is_primary": True}],
    })
    dev = post(client, f"/api/v1/companies/{cid}/employees", {
        "name": "开发李", "primary_model_id": ds["id"], "department_id": dev_dept["id"],
        "reports_to": cto["id"], "tools_allowed": ["file.write"],
        "positions": [{"position_id": dev_pos["id"], "is_primary": True}],
    })
    qa = post(client, f"/api/v1/companies/{cid}/employees", {
        "name": "测试王", "primary_model_id": oa["id"], "department_id": qa_dept["id"],
        "reports_to": cto["id"],
        "positions": [{"position_id": qa_pos["id"], "is_primary": True}],
    })
    dual = post(client, f"/api/v1/companies/{cid}/employees", {
        "name": "兼任赵", "primary_model_id": ds["id"], "department_id": dev_dept["id"],
        "reports_to": cto["id"],
        "positions": [
            {"position_id": dev_pos["id"], "is_primary": True},
            {"position_id": qa_pos["id"], "is_primary": False},
        ],
    })
    prompt = post(client, f"/api/v1/employees/{dev['id']}/prompts", {
        "content": "# 角色\n你是开发工程师，先写测试再写实现。", "note": "E2E 初版",
    })

    tree = client.get(f"/api/v1/companies/{cid}/org-tree", headers=HEADERS).json()
    check("S1 组织树", len(tree["departments"]) == 2, json.dumps(tree)[:200])
    check("S1 兼任岗位", len(dual["positions"]) == 2, str(dual["positions"]))

    exported = client.get(f"/api/v1/companies/{cid}/export", headers=HEADERS)
    check("S1 导出", exported.status_code == 200 and exported.headers["content-type"] == "application/zip")
    names = zipfile.ZipFile(io.BytesIO(exported.content)).namelist()
    check("S1 导出含提示词", any(n.startswith("prompts/") for n in names))
    check("S1 导出无密钥", b"e2e-secret" not in exported.content)

    imported = client.post("/api/v1/config/import", content=exported.content, headers=HEADERS)
    check("S1 导入", imported.status_code == 200, imported.text)
    result = imported.json()
    check("S1 冲突改名", result["company_name"] != "E2E 科技", result["company_name"])
    check("S1 导入计数", result["counts"]["employees"] == 4 and result["counts"]["prompts"] == 1,
          str(result["counts"]))

    new_employees = client.get(
        f"/api/v1/companies/{result['company_id']}/employees?page_size=200", headers=HEADERS
    ).json()["items"]
    imported_dev = [e for e in new_employees if e["name"] == dev["name"]][0]
    imported_prompts = client.get(
        f"/api/v1/employees/{imported_dev['id']}/prompts", headers=HEADERS
    ).json()
    content = client.get(f"/api/v1/prompts/{imported_prompts[0]['id']}", headers=HEADERS).json()["content"]
    check("S1 提示词往返一致", content == "# 角色\n你是开发工程师，先写测试再写实现。")
    check("S1 哈希一致", imported_prompts[0]["content_hash"] == prompt["content_hash"])

    return {"company_id": cid, "dev": dev, "qa": qa, "cto": cto, "ds": ds, "oa": oa,
            "prompt_employee_ids": [dev["id"], dual["id"], cto["id"], qa["id"]]}


def scenario_2(client, ctx) -> None:
    dev = ctx["dev"]
    switched = client.put(
        f"/api/v1/employees/{dev['id']}/model-binding",
        json={"primary_model_id": ctx["oa"]["id"], "fallback_model_id": ctx["ds"]["id"], "reason": "E2E 切换"},
        headers=HEADERS,
    )
    check("S2 切换模型", switched.status_code == 200, switched.text)
    detail = client.get(f"/api/v1/employees/{dev['id']}", headers=HEADERS).json()
    check("S2 身份不变", detail["id"] == dev["id"])
    primary_logs = [log for log in detail["model_history"] if log["slot"] == "primary"]
    check(
        "S2 历史保留",
        len(primary_logs) == 1
        and primary_logs[0]["from_model_id"] == ctx["ds"]["id"]
        and primary_logs[0]["to_model_id"] == ctx["oa"]["id"],
        json.dumps(detail["model_history"], ensure_ascii=False),
    )

    with get_session() as session:
        for employee, tokens in ((dev, 11), (ctx["qa"], 22)):
            session.add(UsageRecord(
                agent_run_id="e2e-run", employee_key=employee["name"], employee_id=employee["id"],
                model="deepseek/deepseek-chat", prompt_tokens=tokens, completion_tokens=1,
                cost_usd=0.0001, latency_ms=100,
            ))
        session.commit()
        rows = session.query(UsageRecord).filter(UsageRecord.agent_run_id == "e2e-run").all()
    by_employee = {row.employee_id: row.prompt_tokens for row in rows}
    check("S2 成本按员工归因", by_employee[dev["id"]] == 11 and by_employee[ctx["qa"]["id"]] == 22, str(by_employee))

    caps = client.get(f"/api/v1/employees/{dev['id']}/capabilities", headers=HEADERS).json()
    check("S2 能力基于新模型", caps["model"]["known"] is True)
    perms = client.get(f"/api/v1/employees/{dev['id']}/effective-permissions", headers=HEADERS).json()
    check("S2 权限来源链", perms["sources"]["file_ops"][0]["layer"] == "company")


def scenario_3(client, ctx) -> None:
    cid = ctx["company_id"]
    denied = client.put(
        f"/api/v1/employees/{ctx['dev']['id']}/permission-overrides",
        json={"overrides": {"file_ops": ["read", "write"]}}, headers=HEADERS,
    )
    check("S3 员工不能扩权", denied.status_code == 403 and denied.json()["error"]["code"] == "PERMISSION_WIDEN_DENIED")

    preview = client.post(
        f"/api/v1/companies/{cid}/assignments/preview",
        json={
            "required_capabilities": ["coding.python", "test.unit"],
            "required_tools": ["file.write"],
            "risk_level": "medium", "budget_usd": 1.0,
            "selected_employee_id": ctx["dev"]["id"],
        },
        headers=HEADERS,
    )
    check("S3 派工预览", preview.status_code == 200, preview.text)
    body = preview.json()
    ids = [item["employee_id"] for item in body["candidates"]]
    check("S3 工具硬过滤", ctx["qa"]["id"] not in ids and ctx["dev"]["id"] in ids, str(ids))
    reviewer = body["reviewer"]
    check(
        "S3 审查人独立且跨模型",
        reviewer is not None
        and reviewer["employee_id"] != ctx["dev"]["id"]
        and reviewer["pool"] == "formal"
        and reviewer["independence"] in {"T1", "T2", "T3", "T4"}
        and (reviewer["cross_model"] or reviewer["cross_provider"]),
        json.dumps(reviewer, ensure_ascii=False),
    )
    check("S3 数据质量标注", body["data_quality"]["performance"] == "unavailable" and "暂定权重" in body["score_note"])
    saved = client.get(f"/api/v1/assignments/{body['decision_id']}", headers=HEADERS)
    check("S3 决策留痕", saved.status_code == 200 and saved.json()["algorithm_version"] == "m1.0")

    audit = client.get("/api/v1/audit?page_size=100", headers=HEADERS).json()
    actions = {item["action"] for item in audit["items"]}
    check("S3 审计记录", "assignment.preview" in actions and "employee.permission_overrides.denied" in actions,
          str(sorted(actions)))


def cleanup(prompt_employee_ids: list[str]) -> None:
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
        except OSError as exc:  # 清理失败不影响验收结论，文件在 data/（已 gitignore）
            print(f"[WARN] 临时文件清理失败：{path} ({exc})")
    for employee_id in prompt_employee_ids:
        directory = PROMPTS_DIR / employee_id
        if directory.exists():
            shutil.rmtree(directory)
    if PROMPTS_ROOT_DIR.exists():
        shutil.rmtree(PROMPTS_ROOT_DIR, ignore_errors=True)


def main() -> int:
    for path in (DB_PATH, Path(f"{DB_PATH}-wal"), Path(f"{DB_PATH}-shm")):
        if path.exists():
            path.unlink()
    if PROMPTS_ROOT_DIR.exists():
        shutil.rmtree(PROMPTS_ROOT_DIR, ignore_errors=True)
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        context = scenario_1(client)
        scenario_2(client, context)
        scenario_3(client, context)
        cleanup(context["prompt_employee_ids"])
    print(f"\nE2E 完成：{len(PASSED)} 项检查全部通过")
    for line in PASSED:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
