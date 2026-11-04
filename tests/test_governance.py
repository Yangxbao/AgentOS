"""B5 验收：三层权限、有效能力、派工硬过滤与打分、双池审查人、审计只增。"""
from __future__ import annotations

import pytest

TAGS = ["coding.python", "test.unit"]


def _position(write_client, company_id, name, tags=None, can_review=False, permissions=None):
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/positions",
        json={
            "name": name, "can_review": can_review,
            "review_capability_tags": tags or [], "default_permissions": permissions or {},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _employee(write_client, company_id, connection_id, name, department_id=None,
              positions=None, reports_to=None, tools=None, permissions=None, status=None):
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/employees",
        json={
            "name": name, "primary_model_id": connection_id, "department_id": department_id,
            "reports_to": reports_to, "tools_allowed": tools or [],
            "permission_profile": permissions or {},
            "positions": [{"position_id": p, "is_primary": True} for p in (positions or [])],
        },
    )
    assert resp.status_code == 201, resp.text
    employee = resp.json()
    if status == "disabled":
        write_client.post(f"/api/v1/employees/{employee['id']}/disable")
        employee["status"] = "disabled"
    return employee


def _second_connection(write_client, company_id, name, model, env="TEST_MODEL_KEY"):
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/model-connections",
        json={"name": name, "provider": model.split("/")[0], "model": model,
              "api_key_ref": f"env:{env}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _dept(write_client, company_id, name):
    resp = write_client.post(f"/api/v1/companies/{company_id}/departments", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_effective_permissions_position_cannot_widen(write_client, seeded_company, seeded_connection):
    company_id = seeded_company["id"]
    position = _position(
        write_client, company_id, "工程师", permissions={"file_ops": ["read", "write"], "shell": "approval_required"}
    )
    employee = _employee(write_client, company_id, seeded_connection["id"], "工程师甲", positions=[position["id"]])

    result = write_client.get(f"/api/v1/employees/{employee['id']}/effective-permissions")
    assert result.status_code == 200
    body = result.json()
    # 公司默认 file_ops=[read]，岗位想加 write 但被上层收窄；shell 同理
    assert body["permissions"]["file_ops"] == ["read"]
    assert body["permissions"]["shell"] == "deny"
    assert [item["layer"] for item in body["sources"]["file_ops"]] == ["company", "position"]


def test_employee_override_cannot_widen_and_is_audited(write_client, seeded_employee):
    resp = write_client.put(
        f"/api/v1/employees/{seeded_employee['id']}/permission-overrides",
        json={"overrides": {"file_ops": ["read", "write"]}},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "PERMISSION_WIDEN_DENIED"

    audit = write_client.get(f"/api/v1/employees/{seeded_employee['id']}/audit")
    assert audit.status_code == 200
    actions = [item["action"] for item in audit.json()["items"]]
    assert "employee.permission_overrides.denied" in actions


def test_employee_override_narrow_allowed(write_client, seeded_employee):
    resp = write_client.put(
        f"/api/v1/employees/{seeded_employee['id']}/permission-overrides",
        json={"overrides": {"file_ops": [], "shell": "deny"}},
    )
    assert resp.status_code == 200
    assert resp.json()["permissions"]["file_ops"] == []


def test_capabilities_endpoint(write_client, seeded_employee):
    resp = write_client.get(f"/api/v1/employees/{seeded_employee['id']}/capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"]["known"] is True
    assert body["effective"]["structured_output"] is True
    assert body["effective"]["file_ops"] is False  # API 型适配器不支持文件操作
    assert body["model_available"] is True


def test_assignment_hard_filters(write_client, seeded_company, seeded_connection):
    company_id = seeded_company["id"]
    position = _position(write_client, company_id, "开发", tags=TAGS)
    _employee(write_client, company_id, seeded_connection["id"], "开发甲", positions=[position["id"]])
    disabled = _employee(write_client, company_id, seeded_connection["id"], "停用乙", positions=[position["id"]],
                         status="disabled")
    no_tool = _employee(write_client, company_id, seeded_connection["id"], "无工具丙", positions=[position["id"]])

    resp = write_client.post(
        f"/api/v1/companies/{company_id}/assignments/preview",
        json={
            "required_capabilities": TAGS, "required_tools": ["file.write"],
            "risk_level": "medium", "budget_usd": 1.0,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidates"] == []
    reasons = {item["employee_id"]: item["reason"] for item in body["excluded"]}
    assert reasons[disabled["id"]] == "inactive"
    assert reasons[no_tool["id"]].startswith("tool_denied")

    missing = write_client.post(
        f"/api/v1/companies/{company_id}/assignments/preview",
        json={"required_capabilities": ["coding.rust"], "risk_level": "low"},
    )
    assert missing.json()["candidates"] == []


def test_assignment_scoring_and_data_quality(write_client, seeded_company, seeded_connection):
    company_id = seeded_company["id"]
    dept = _dept(write_client, company_id, "研发部")
    position = _position(write_client, company_id, "开发", tags=TAGS, permissions={"max_risk_level": "high"})
    employee = _employee(write_client, company_id, seeded_connection["id"], "开发甲",
                         department_id=dept["id"], positions=[position["id"]], tools=["file.write"])

    resp = write_client.post(
        f"/api/v1/companies/{company_id}/assignments/preview",
        json={
            "required_capabilities": TAGS, "required_tools": ["file.write"],
            "risk_level": "medium", "budget_usd": 1.0, "prefer_department_id": dept["id"],
        },
    )
    body = resp.json()
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["employee_id"] == employee["id"]
    assert 0 < body["candidates"][0]["score"] <= 1
    assert body["data_quality"] == {"performance": "unavailable", "load": "unavailable"}
    assert "暂定权重" in body["score_note"]

    saved = write_client.get(f"/api/v1/assignments/{body['decision_id']}")
    assert saved.status_code == 200
    assert saved.json()["algorithm_version"] == "m1.0"


def test_reviewer_formal_pool_prefers_independent_qa(write_client, seeded_company, seeded_connection, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    company_id = seeded_company["id"]
    dev_dept = _dept(write_client, company_id, "研发部")
    qa_dept = _dept(write_client, company_id, "质量部")
    dev_pos = _position(write_client, company_id, "开发", tags=TAGS)
    qa_pos = _position(write_client, company_id, "测试", tags=TAGS, can_review=True)
    openai_conn = _second_connection(write_client, company_id, "OpenAI", "openai/gpt-4o-mini", "OPENAI_API_KEY")
    cto_pos = _position(write_client, company_id, "CTO", tags=TAGS, can_review=True)

    cto = _employee(write_client, company_id, seeded_connection["id"], "CTO", positions=[cto_pos["id"]])
    dev = _employee(write_client, company_id, seeded_connection["id"], "开发甲",
                    department_id=dev_dept["id"], positions=[dev_pos["id"]], reports_to=cto["id"])
    qa = _employee(write_client, company_id, openai_conn["id"], "测试乙",
                   department_id=qa_dept["id"], positions=[qa_pos["id"]], reports_to=cto["id"])

    resp = write_client.post(
        f"/api/v1/companies/{company_id}/assignments/preview",
        json={"required_capabilities": TAGS, "risk_level": "low", "selected_employee_id": dev["id"]},
    )
    body = resp.json()
    reviewer = body["reviewer"]
    assert reviewer["employee_id"] == qa["id"]  # T1 正式池优先
    assert reviewer["independence"] == "T1"
    assert reviewer["pool"] == "formal"
    assert reviewer["cross_provider"] is True
    assert reviewer["cross_model"] is True
    assert reviewer["degraded_reviewer"] is False


def test_reviewer_degraded_only_when_formal_empty(write_client, seeded_company, seeded_connection):
    company_id = seeded_company["id"]
    dept_a = _dept(write_client, company_id, "研发部")
    dept_b = _dept(write_client, company_id, "运营部")
    dev_pos = _position(write_client, company_id, "开发", tags=TAGS)
    plain_pos = _position(write_client, company_id, "运营", tags=TAGS)  # 无 can_review

    dev = _employee(write_client, company_id, seeded_connection["id"], "开发甲",
                    department_id=dept_a["id"], positions=[dev_pos["id"]])
    _employee(write_client, company_id, seeded_connection["id"], "运营乙",
              department_id=dept_b["id"], positions=[plain_pos["id"]])

    body = write_client.post(
        f"/api/v1/companies/{company_id}/assignments/preview",
        json={"required_capabilities": TAGS, "risk_level": "low", "selected_employee_id": dev["id"]},
    ).json()
    assert body["reviewer"]["employee_id"] != dev["id"]
    assert body["reviewer"]["independence"] == "T6"
    assert body["reviewer"]["degraded_reviewer"] is True
    assert "degraded_reviewer_used" in body["reviewer"]["warnings"]


def test_reviewer_empty_returns_reason(write_client, seeded_company, seeded_connection):
    company_id = seeded_company["id"]
    dev_pos = _position(write_client, company_id, "开发", tags=TAGS)
    _employee(write_client, company_id, seeded_connection["id"], "独苗", positions=[dev_pos["id"]])

    body = write_client.post(
        f"/api/v1/companies/{company_id}/assignments/preview",
        json={"required_capabilities": TAGS, "risk_level": "low"},
    ).json()
    assert body["reviewer"] is None
    assert body["reviewer_reason_code"] == "company_has_single_employee"


def test_cross_model_versus_cross_provider(write_client, seeded_company, seeded_connection, monkeypatch):
    """同供应商不同模型：cross_model=True 但 cross_provider=False。"""
    monkeypatch.setenv("TEST_MODEL_KEY", "x")
    company_id = seeded_company["id"]
    dev_dept = _dept(write_client, company_id, "研发部")
    qa_dept = _dept(write_client, company_id, "质量部")
    dev_pos = _position(write_client, company_id, "开发", tags=TAGS)
    qa_pos = _position(write_client, company_id, "测试", tags=TAGS, can_review=True)
    reasoner = _second_connection(write_client, company_id, "DeepSeek Reasoner", "deepseek/deepseek-reasoner")

    dev = _employee(write_client, company_id, seeded_connection["id"], "开发甲",
                    department_id=dev_dept["id"], positions=[dev_pos["id"]])
    qa = _employee(write_client, company_id, reasoner["id"], "测试乙",
                   department_id=qa_dept["id"], positions=[qa_pos["id"]])

    body = write_client.post(
        f"/api/v1/companies/{company_id}/assignments/preview",
        json={"required_capabilities": TAGS, "risk_level": "low", "selected_employee_id": dev["id"]},
    ).json()
    assert body["reviewer"]["employee_id"] == qa["id"]
    assert body["reviewer"]["cross_model"] is True
    assert body["reviewer"]["cross_provider"] is False
    assert body["reviewer"]["independence"] == "T1"


def test_audit_is_append_only_and_filterable(write_client, seeded_company, seeded_employee):
    write_client.put(
        f"/api/v1/employees/{seeded_employee['id']}/permission-overrides",
        json={"overrides": {"file_ops": []}},
    )
    listing = write_client.get("/api/v1/audit?action=employee.permission_overrides.update")
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1

    # 没有更新/删除审计的接口
    assert write_client.delete("/api/v1/audit/1").status_code in (404, 405)
    assert write_client.patch("/api/v1/audit/1", json={}).status_code in (404, 405)


@pytest.mark.parametrize("bad_risk", ["extreme"])
def test_assignment_invalid_risk(write_client, seeded_company, bad_risk):
    resp = write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/assignments/preview",
        json={"risk_level": bad_risk},
    )
    assert resp.status_code == 422
