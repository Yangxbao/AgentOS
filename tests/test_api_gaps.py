"""M1 收尾：补齐三个此前缺少直接测试的接口。

1. PATCH /api/v1/departments/{id}：纯改名 + 空名/重名/陈旧版本边界；
2. PUT /api/v1/employees/{id}/permission-overrides：多键组合、拒绝扩权、合法收窄、失败不部分写入；
3. POST /api/v1/model-connections/{id}/test：Mock 上游验证成功/认证失败/超时，不发起真实付费调用。
"""
from __future__ import annotations

from packages.agent_core.adapter import HealthStatus


def _dept(client, company_id: str, name: str) -> dict:
    resp = client.post(f"/api/v1/companies/{company_id}/departments", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------- 部门 PATCH


def test_department_rename(write_client, seeded_company):
    dept = _dept(write_client, seeded_company["id"], "研发部")
    resp = write_client.patch(f"/api/v1/departments/{dept['id']}", json={"name": "研发中心"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "研发中心"
    assert body["parent_id"] == dept["parent_id"]
    assert body["depth"] == dept["depth"]

    listed = write_client.get(f"/api/v1/companies/{seeded_company['id']}/departments").json()
    assert [item["name"] for item in listed["items"]] == ["研发中心"]


def test_department_rename_boundaries(write_client, seeded_company):
    company_id = seeded_company["id"]
    first = _dept(write_client, company_id, "研发部")
    _dept(write_client, company_id, "质量部")

    # 纯空白名：pydantic 过长度校验，领域层 strip 后拒绝
    blank = write_client.patch(f"/api/v1/departments/{first['id']}", json={"name": "   "})
    assert blank.status_code == 422
    assert blank.json()["error"]["code"] == "VALIDATION_ERROR"

    # 同公司重名
    duplicate = write_client.patch(f"/api/v1/departments/{first['id']}", json={"name": "质量部"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "BR_DEPARTMENT_NAME_TAKEN"

    # 陈旧版本
    stale = write_client.patch(
        f"/api/v1/departments/{first['id']}",
        json={"name": "研发中心", "expected_updated_at": "2000-01-01T00:00:00+00:00"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFLICT_STALE"

    # 不存在的部门
    missing = write_client.patch("/api/v1/departments/not-exist", json={"name": "随便"})
    assert missing.status_code == 404

    # 失败请求都没改到库
    listed = write_client.get(f"/api/v1/companies/{company_id}/departments").json()
    names = sorted(item["name"] for item in listed["items"])
    assert names == ["研发部", "质量部"]


# ------------------------------------------------------- 员工权限覆盖


def _put_overrides(client, employee_id: str, overrides: dict):
    return client.put(
        f"/api/v1/employees/{employee_id}/permission-overrides",
        json={"overrides": overrides},
    )


def test_permission_overrides_matrix(write_client, seeded_employee):
    employee_id = seeded_employee["id"]

    unknown = _put_overrides(write_client, employee_id, {"root_access": True})
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "VALIDATION_ERROR"

    widen_risk = _put_overrides(write_client, employee_id, {"max_risk_level": "high"})
    assert widen_risk.status_code == 403
    assert widen_risk.json()["error"]["code"] == "PERMISSION_WIDEN_DENIED"

    narrow_risk = _put_overrides(write_client, employee_id, {"max_risk_level": "low"})
    assert narrow_risk.status_code == 200, narrow_risk.text
    assert narrow_risk.json()["permissions"]["max_risk_level"] == "low"

    narrow_files = _put_overrides(write_client, employee_id, {"file_ops": ["read"]})
    assert narrow_files.status_code == 200, narrow_files.text
    assert narrow_files.json()["permissions"]["file_ops"] == ["read"]

    widen_files = _put_overrides(write_client, employee_id, {"file_ops": ["read", "write"]})
    assert widen_files.status_code == 403
    assert widen_files.json()["error"]["code"] == "PERMISSION_WIDEN_DENIED"

    # 多键混合：第一个键合法收窄、第二个键扩权 → 整体拒绝，且第一个键不得被部分写入
    mixed = _put_overrides(write_client, employee_id, {"file_ops": [], "shell": "allow_all"})
    assert mixed.status_code == 403
    current = write_client.get(f"/api/v1/employees/{employee_id}/effective-permissions").json()
    assert current["permissions"]["file_ops"] == ["read"]

    # requires_approval 语义：员工覆盖值视为“完整清单”，少列审批项=放宽 → 拒绝；
    # 只有“原清单 + 新项”这种收紧才允许。
    current_approvals = current["permissions"]["requires_approval"]
    remove_approval = _put_overrides(
        write_client, employee_id, {"requires_approval": current_approvals[:1]}
    )
    assert remove_approval.status_code == 403
    add_approval = _put_overrides(
        write_client, employee_id,
        {"requires_approval": [*current_approvals, "external_publish"]},
    )
    assert add_approval.status_code == 200, add_approval.text
    assert "external_publish" in add_approval.json()["permissions"]["requires_approval"]
    assert set(current_approvals).issubset(add_approval.json()["permissions"]["requires_approval"])

    # 拒绝事件留痕
    actions = [
        row["action"]
        for row in write_client.get(f"/api/v1/employees/{employee_id}/audit").json()["items"]
    ]
    assert actions.count("employee.permission_overrides.denied") >= 3


# ------------------------------------------------------- 连接测试（Mock 上游）


class _FakeAdapter:
    """替身：不联网、不花钱，返回预设健康结果。"""

    last_kwargs: dict = {}
    result = HealthStatus(ok=True)

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs

    async def health_check(self) -> HealthStatus:
        return type(self).result


def _patch_adapter(monkeypatch, result: HealthStatus) -> None:
    _FakeAdapter.result = result
    _FakeAdapter.last_kwargs = {}
    monkeypatch.setattr("packages.organization.connections.LiteLLMAdapter", _FakeAdapter)


def test_connection_test_success(write_client, seeded_connection, monkeypatch):
    _patch_adapter(monkeypatch, HealthStatus(ok=True, detail="ok"))
    resp = write_client.post(f"/api/v1/model-connections/{seeded_connection['id']}/test")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0
    assert body["model"] == seeded_connection["model"]
    # 适配器拿到的是解析后的密钥与连接级配置，但响应绝不回显
    assert _FakeAdapter.last_kwargs["api_key"] == "test-secret"
    assert "test-secret" not in resp.text

    listed = write_client.get(
        f"/api/v1/companies/{seeded_connection['company_id']}/model-connections"
    ).json()
    conn = [item for item in listed if item["id"] == seeded_connection["id"]][0]
    assert conn["last_health_status"] == "ok"
    assert conn["last_health_latency_ms"] is not None

    actions = [
        row["action"]
        for row in write_client.get(
            "/api/v1/audit", params={"target_id": seeded_connection["id"], "page_size": 50}
        ).json()["items"]
    ]
    assert "model_connection.test" in actions


def test_connection_test_auth_failure_is_redacted(write_client, seeded_connection, monkeypatch):
    _patch_adapter(
        monkeypatch,
        HealthStatus(ok=False, detail="401 Unauthorized: invalid api key sk-abcdefgh12345678"),
    )
    resp = write_client.post(f"/api/v1/model-connections/{seeded_connection['id']}/test")
    assert resp.status_code == 502, resp.text
    error = resp.json()["error"]
    assert error["code"] == "UPSTREAM_AUTH_FAILED"
    assert error["detail"]["kind"] == "AUTH"
    assert "sk-abcdefgh12345678" not in resp.text
    assert "test-secret" not in resp.text

    listed = write_client.get(
        f"/api/v1/companies/{seeded_connection['company_id']}/model-connections"
    ).json()
    conn = [item for item in listed if item["id"] == seeded_connection["id"]][0]
    assert conn["last_health_status"] == "fail"


def test_connection_test_timeout(write_client, seeded_connection, monkeypatch):
    _patch_adapter(monkeypatch, HealthStatus(ok=False, detail="Request timed out after 60s"))
    resp = write_client.post(f"/api/v1/model-connections/{seeded_connection['id']}/test")
    assert resp.status_code == 504, resp.text
    assert resp.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert resp.json()["error"]["detail"]["kind"] == "TIMEOUT"


def test_connection_test_unknown_error(write_client, seeded_connection, monkeypatch):
    _patch_adapter(monkeypatch, HealthStatus(ok=False, detail="502 bad gateway"))
    resp = write_client.post(f"/api/v1/model-connections/{seeded_connection['id']}/test")
    assert resp.status_code == 502, resp.text
    assert resp.json()["error"]["code"] == "UPSTREAM_ERROR"
