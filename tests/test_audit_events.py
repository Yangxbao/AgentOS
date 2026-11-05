"""M1 收尾：核心审计事件覆盖、request_id 透传、detail 脱敏、只增不改。"""
from __future__ import annotations

import json

from packages.permissions.audit import REDACTED, sanitize_detail


def _audits(client, target_id: str | None = None, action: str | None = None) -> list[dict]:
    params: dict = {"page_size": 200}
    if target_id:
        params["target_id"] = target_id
    if action:
        params["action"] = action
    resp = client.get("/api/v1/audit", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def _find(rows: list[dict], action: str) -> dict:
    for row in rows:
        if row["action"] == action:
            return row
    raise AssertionError(f"未找到审计事件 {action}，实际：{[r['action'] for r in rows]}")


def _create_employee(client, company_id: str, connection_id: str, name: str, **extra):
    resp = client.post(
        f"/api/v1/companies/{company_id}/employees",
        json={"name": name, "primary_model_id": connection_id, **extra},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_employee_lifecycle_audited(write_client, seeded_company, seeded_connection):
    employee = _create_employee(
        write_client, seeded_company["id"], seeded_connection["id"], "审计员工", title="初级"
    )
    created = write_client.get(
        f"/api/v1/employees/{employee['id']}/audit"
    ).json()["items"]
    create_row = _find(created, "employee.create")
    assert create_row["detail"]["name"] == "审计员工"
    assert create_row["target_type"] == "employee"
    assert create_row["actor_type"] == "user"

    update = write_client.patch(
        f"/api/v1/employees/{employee['id']}", json={"title": "高级"}
    )
    assert update.status_code == 200, update.text
    rows = _audits(write_client, employee["id"])
    update_row = _find(rows, "employee.update")
    assert update_row["detail"]["changed"] == ["title"]
    assert update_row["detail"]["before"]["title"] == "初级"
    assert update_row["detail"]["after"]["title"] == "高级"

    assert write_client.post(f"/api/v1/employees/{employee['id']}/disable").status_code == 200
    assert write_client.post(f"/api/v1/employees/{employee['id']}/enable").status_code == 200
    assert write_client.delete(f"/api/v1/employees/{employee['id']}").status_code == 204

    rows = _audits(write_client, employee["id"])
    actions = [row["action"] for row in rows]
    for action in (
        "employee.create", "employee.update", "employee.disable",
        "employee.enable", "employee.delete",
    ):
        assert action in actions, f"缺少审计事件 {action}"
    assert _find(rows, "employee.disable")["detail"]["status"] == "disabled"
    assert _find(rows, "employee.delete")["detail"]["soft_deleted"] is True


def test_audit_request_id_is_propagated(write_client, seeded_company, seeded_connection):
    resp = write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/employees",
        json={"name": "带请求号员工", "primary_model_id": seeded_connection["id"]},
        headers={"X-Request-ID": "audit-req-0001"},
    )
    assert resp.status_code == 201, resp.text
    employee_id = resp.json()["id"]
    row = _find(_audits(write_client, employee_id), "employee.create")
    assert row["request_id"] == "audit-req-0001"


def test_model_binding_switch_audited(write_client, seeded_company, seeded_connection):
    second = write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/model-connections",
        json={
            "name": "备用连接", "provider": "deepseek",
            "model": "deepseek/deepseek-reasoner", "api_key_ref": "env:TEST_MODEL_KEY",
        },
    )
    assert second.status_code == 201, second.text
    employee = _create_employee(
        write_client, seeded_company["id"], seeded_connection["id"], "换模型员工"
    )
    resp = write_client.put(
        f"/api/v1/employees/{employee['id']}/model-binding",
        json={
            "primary_model_id": second.json()["id"],
            "fallback_model_id": seeded_connection["id"],
            "reason": "切换到更强模型",
        },
    )
    assert resp.status_code == 200, resp.text
    row = _find(_audits(write_client, employee["id"]), "employee.model_binding.update")
    assert row["detail"]["primary_model_id"] == {
        "from": seeded_connection["id"], "to": second.json()["id"],
    }
    assert row["detail"]["fallback_model_id"] == {
        "from": None, "to": seeded_connection["id"],
    }
    assert row["detail"]["reason"] == "切换到更强模型"


def test_connection_config_and_switch_audited(write_client, seeded_company, seeded_connection):
    created = write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/model-connections",
        json={
            "name": "审计连接", "provider": "deepseek",
            "model": "deepseek/deepseek-reasoner", "api_key_ref": "env:AUDIT_KEY",
        },
    )
    assert created.status_code == 201, created.text
    conn = created.json()

    create_row = _find(_audits(write_client, conn["id"]), "model_connection.create")
    assert create_row["detail"]["provider"] == "deepseek"
    assert create_row["detail"]["api_key_ref"] == "env:AUDIT_KEY"  # 只存引用，不存密钥值

    renamed = write_client.patch(f"/api/v1/model-connections/{conn['id']}", json={"name": "改名连接"})
    assert renamed.status_code == 200, renamed.text
    disabled = write_client.patch(f"/api/v1/model-connections/{conn['id']}", json={"enabled": False})
    assert disabled.status_code == 200, disabled.text

    rows = _audits(write_client, conn["id"], action="model_connection.update")
    assert len(rows) == 2
    assert rows[0]["detail"]["changed"] == ["enabled"]  # 最新一条
    assert rows[1]["detail"]["changed"] == ["name"]

    assert write_client.delete(f"/api/v1/model-connections/{conn['id']}").status_code == 204
    delete_row = _find(_audits(write_client, conn["id"]), "model_connection.delete")
    assert delete_row["detail"]["name"] == "改名连接"


def test_prompt_and_config_audited(write_client, seeded_company, seeded_employee):
    employee_id = seeded_employee["id"]
    v1 = write_client.post(
        f"/api/v1/employees/{employee_id}/prompts", json={"content": "第一版", "note": "初版"}
    )
    assert v1.status_code == 201, v1.text
    v2 = write_client.post(
        f"/api/v1/employees/{employee_id}/prompts", json={"content": "第二版", "note": "改版"}
    )
    assert v2.status_code == 201, v2.text
    assert write_client.post(f"/api/v1/prompts/{v2.json()['id']}/activate").status_code == 200

    create_row = _find(_audits(write_client, v2.json()["id"]), "prompt.version.create")
    assert create_row["detail"]["version"] == 2
    assert create_row["detail"]["content_hash"] == v2.json()["content_hash"]

    activate_row = _find(_audits(write_client, v2.json()["id"]), "prompt.version.activate")
    assert activate_row["detail"]["version"] == 2
    assert activate_row["detail"]["previous_active_versions"] == [1]

    export = write_client.get(f"/api/v1/companies/{seeded_company['id']}/export")
    assert export.status_code == 200
    _find(_audits(write_client, seeded_company["id"]), "config.export")

    imported = write_client.post("/api/v1/config/import", content=export.content)
    assert imported.status_code == 200, imported.text
    import_row = _find(
        _audits(write_client, imported.json()["company_id"]), "config.import"
    )
    assert import_row["detail"]["strategy"] == "rename"
    assert import_row["detail"]["counts"]["prompts"] == 2
    assert import_row["detail"]["counts"]["employees"] == 1


def test_audit_detail_sanitizes_plaintext_secret(write_client, seeded_company, seeded_connection):
    second = write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/model-connections",
        json={
            "name": "第二连接", "provider": "deepseek",
            "model": "deepseek/deepseek-reasoner", "api_key_ref": "env:TEST_MODEL_KEY",
        },
    ).json()
    employee = _create_employee(
        write_client, seeded_company["id"], seeded_connection["id"], "脱敏员工"
    )
    write_client.put(
        f"/api/v1/employees/{employee['id']}/model-binding",
        json={
            "primary_model_id": second["id"],
            "reason": "误粘贴 sk-abcdefgh12345678 与 Bearer abcdefghijklmn",
        },
    )
    rows = _audits(write_client, employee["id"])
    raw = json.dumps(rows, ensure_ascii=False)
    assert "sk-abcdefgh12345678" not in raw
    assert "Bearer abcdefghijklmn" not in raw
    assert REDACTED in raw


def test_sanitize_detail_rules():
    cleaned = sanitize_detail({
        "api_key": "sk-abcdefgh12345678",
        "api_key_ref": "env:DEEPSEEK_API_KEY",  # 引用必须保留
        "nested": [{"token": "Bearer abcdefghijklmn", "note": "泄露 sk-9999999999"}],
        "enabled": False,
    })
    assert cleaned["api_key"] == REDACTED
    assert cleaned["api_key_ref"] == "env:DEEPSEEK_API_KEY"
    assert cleaned["nested"][0]["token"] == REDACTED
    assert "sk-" not in cleaned["nested"][0]["note"]
    assert cleaned["enabled"] is False
