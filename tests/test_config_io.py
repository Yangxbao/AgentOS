"""B4 配置导入导出：zip 内容、无密钥、dry-run、rename、往返一致、路径穿越。"""
from __future__ import annotations

import io
import json
import zipfile

WRITE_HEADERS = {"Origin": "http://127.0.0.1:5173", "X-AgentOS-Client": "web"}


def _export(write_client, company_id):
    resp = write_client.get(f"/api/v1/companies/{company_id}/export")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    return resp.content


def _zip_names(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.namelist()


def test_export_contains_structure_and_no_secrets(write_client, seeded_company, seeded_connection, seeded_employee):
    write_client.post(
        f"/api/v1/employees/{seeded_employee['id']}/prompts",
        json={"content": "# 角色\n测试", "note": "导出"},
    )
    data = _export(write_client, seeded_company["id"])
    names = _zip_names(data)
    assert "manifest.json" in names
    assert any(name.startswith("prompts/") for name in names)

    raw = b"".join(
        zipfile.ZipFile(io.BytesIO(data)).read(name) for name in names
    )
    assert b"sk-" not in raw
    assert b"test-secret" not in raw  # 只保留 env 引用，不含密钥值

    manifest = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
    assert manifest["contains_secrets"] is False
    assert manifest["counts"]["employees"] == 1


def test_export_then_import_renames_and_roundtrips(write_client, seeded_company, seeded_connection, seeded_employee):
    prompt = write_client.post(
        f"/api/v1/employees/{seeded_employee['id']}/prompts",
        json={"content": "# 角色\n往返测试", "note": "往返"},
    ).json()

    data = _export(write_client, seeded_company["id"])

    dry = write_client.post("/api/v1/config/import?dry_run=true", content=data)
    assert dry.status_code == 200, dry.text
    assert dry.json()["dry_run"] is True
    assert dry.json()["conflict"] is True
    assert dry.json()["counts"]["employees"] == 1

    imported = write_client.post("/api/v1/config/import", content=data)
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["company_name"] != seeded_company["name"]
    assert result["company_name"].startswith(seeded_company["name"])
    assert result["counts"]["employees"] == 1

    # 新公司里能找到员工与提示词，内容哈希一致
    companies = write_client.get("/api/v1/companies?page_size=200").json()["items"]
    new_company = [c for c in companies if c["id"] == result["company_id"]][0]
    employees = write_client.get(
        f"/api/v1/companies/{new_company['id']}/employees?page_size=200"
    ).json()["items"]
    assert len(employees) == 1
    new_employee = employees[0]
    prompts = write_client.get(f"/api/v1/employees/{new_employee['id']}/prompts").json()
    assert len(prompts) == 1
    content = write_client.get(f"/api/v1/prompts/{prompts[0]['id']}").json()["content"]
    assert content == "# 角色\n往返测试"
    assert prompts[0]["content_hash"] == prompt["content_hash"]


def test_import_rejects_path_traversal(write_client, seeded_company):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../evil.txt", "x")
        archive.writestr("manifest.json", "{}")
    resp = write_client.post("/api/v1/config/import?dry_run=true", content=buffer.getvalue())
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "IMPORT_UNSAFE_PATH"


def test_import_rejects_invalid_bundle(write_client):
    resp = write_client.post("/api/v1/config/import", content=b"not-a-zip")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "IMPORT_INVALID_BUNDLE"
