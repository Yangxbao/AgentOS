"""B4 配置导入导出：zip 内容、无密钥、dry-run、rename、往返一致、路径穿越。"""
from __future__ import annotations

import io
import json
import tempfile
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


# ---------------------------------------------------------------- M3 后：工作区/授权/记忆随包迁移


def test_export_includes_workspaces_grants_memories(
    write_client, seeded_company, seeded_connection, seeded_employee, seeded_workspace
):
    """导出包含工作区/授权/记忆三个新文件与 counts。"""
    grant = write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": seeded_employee["id"], "access": "read"},
    )
    assert grant.status_code == 201, grant.text
    resp = write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/memories",
        json={"scope": "employee", "employee_id": seeded_employee["id"],
              "title": "导出记忆", "content": "随包迁移的唯一内容 unique-export-mem"},
    )
    assert resp.status_code == 201, resp.text

    data = _export(write_client, seeded_company["id"])
    names = _zip_names(data)
    assert "workspaces.json" in names
    assert "workspace_grants.json" in names
    assert "memories.json" in names

    bundle = zipfile.ZipFile(io.BytesIO(data))
    workspaces = json.loads(bundle.read("workspaces.json"))
    grants = json.loads(bundle.read("workspace_grants.json"))
    memories = json.loads(bundle.read("memories.json"))
    assert any(w["root_path"] == seeded_workspace["root_path"] for w in workspaces)
    assert any(g["employee_id"] == seeded_employee["id"] for g in grants)
    assert any(m["content"] == "随包迁移的唯一内容 unique-export-mem" for m in memories)

    manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["counts"]["workspaces"] == len(workspaces)
    assert manifest["counts"]["memories"] == len(memories)


def test_import_roundtrips_workspaces_grants_memories(
    write_client, seeded_company, seeded_connection, seeded_employee, seeded_workspace
):
    """导出 → 导入（rename）：新公司获得工作区/授权/记忆，且映射到新员工 id；记忆可检索。"""
    write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": seeded_employee["id"], "access": "read"},
    )
    write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/memories",
        json={"scope": "employee", "employee_id": seeded_employee["id"],
              "title": "往返记忆", "content": "roundtrip-mem-content"},
    )
    data = _export(write_client, seeded_company["id"])

    result = _import(write_client, data)
    assert result["counts"]["workspaces"] == 1
    assert result["counts"]["workspace_grants"] >= 1
    assert result["counts"]["memories"] >= 1

    new_company_id = result["company_id"]
    workspaces = write_client.get(f"/api/v1/companies/{new_company_id}/workspaces").json()
    assert len(workspaces) == 1
    imported_ws = workspaces[0]
    assert imported_ws["root_path"] == seeded_workspace["root_path"]

    # 授权映射到新员工（rename 策略下 id 全新）
    imported_employees = write_client.get(
        f"/api/v1/companies/{new_company_id}/employees?page_size=100"
    ).json()["items"]
    new_emp_ids = {e["id"] for e in imported_employees}
    grant_employee_ids = {g["employee_id"] for g in imported_ws["grants"]}
    assert grant_employee_ids and grant_employee_ids.issubset(new_emp_ids)

    # 记忆可检索（新公司、新员工视角）
    resp = write_client.get(
        f"/api/v1/memories/search?q=roundtrip-mem-content&company_id={new_company_id}"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] >= 1


def test_import_skips_workspace_with_invalid_root(write_client, seeded_company,
                                                  seeded_connection, seeded_employee):
    """root 非法的工作区导入时跳过并记 warning（不阻断整体导入，不放宽安全）。"""
    data = _export(write_client, seeded_company["id"])
    bundle = zipfile.ZipFile(io.BytesIO(data))
    workspaces = json.loads(bundle.read("workspaces.json")) if "workspaces.json" in bundle.namelist() else []
    workspaces.append({
        "id": "fake000000000000000000000000", "name": "越权工作区",
        "slug": "evil", "root_path": r"C:\Windows", "mode": "read_write",
        "status": "active", "description": "",
    })
    payload_files = {name: bundle.read(name) for name in bundle.namelist()}
    payload_files["workspaces.json"] = json.dumps(workspaces, ensure_ascii=False).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in payload_files.items():
            archive.writestr(name, content)
    patched = buffer.getvalue()

    result = _import(write_client, patched)
    warnings = result.get("warnings") or []
    assert any("越权工作区" in w for w in warnings)
    new_company_id = result["company_id"]
    names = [w["name"] for w in write_client.get(
        f"/api/v1/companies/{new_company_id}/workspaces"
    ).json()]
    assert "越权工作区" not in names


def _import(write_client, data: bytes) -> dict:
    resp = write_client.post(
        "/api/v1/config/import?dry_run=false",
        content=data,
        headers={"Content-Type": "application/zip", **WRITE_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_import_hardens_tampered_values(write_client, seeded_company, seeded_connection,
                                        seeded_employee):
    """防篡改加固：包内非法 mode/scope/kind 回退默认；content 再脱敏；越权记忆跳过。"""
    data = _export(write_client, seeded_company["id"])
    bundle = zipfile.ZipFile(io.BytesIO(data))
    payload_files = {name: bundle.read(name) for name in bundle.namelist()}

    memories = json.loads(payload_files.get("memories.json", b"[]"))
    memories.extend([
        # 非法 scope → 回退 employee，但 employee_id 缺失 → 跳过
        {"scope": "hacker", "employee_id": None, "title": "越权记忆",
         "content": " hacked-with-sk-abcdef12345678 ", "kind": "no-such-kind"},
        # 非法 kind → 回退 note；content 再脱敏
        {"scope": "project", "employee_id": None, "title": "被篡改",
         "content": "公司级 memory：我的 key 是 sk-tamperedkey12345678", "kind": "no-such-kind"},
    ])
    payload_files["memories.json"] = json.dumps(memories, ensure_ascii=False).encode("utf-8")

    workspaces = json.loads(payload_files.get("workspaces.json", b"[]"))
    workspaces.append({
        "id": "fake100000000000000000000000", "name": "篡改模式工作区",
        "slug": "tampered", "root_path": tempfile.gettempdir(),
        "mode": "root_mode", "status": "vanished", "description": "",
    })
    payload_files["workspaces.json"] = json.dumps(workspaces, ensure_ascii=False).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in payload_files.items():
            archive.writestr(name, content)

    result = _import(write_client, buffer.getvalue())
    assert result["counts"]["memories"] == 1  # 越权记忆被跳过，公司级记忆保留

    new_company_id = result["company_id"]
    memories_list = write_client.get(
        f"/api/v1/companies/{new_company_id}/memories"
    ).json()["items"]
    by_title = {item["title"]: item for item in memories_list}
    assert "被篡改" in by_title
    tampered = by_title["被篡改"]
    assert tampered["kind"] == "note"
    assert "sk-tamperedkey12345678" not in tampered["content"]  # 再脱敏
    assert "sk-***" in tampered["content"]

    workspaces_list = write_client.get(f"/api/v1/companies/{new_company_id}/workspaces").json()
    tampered_ws = next(w for w in workspaces_list if w["name"] == "篡改模式工作区")
    assert tampered_ws["mode"] == "read_write"  # 非法 mode 回退默认
    assert tampered_ws["status"] == "active"    # 非法 status 回退默认

    assert result["counts"]["workspaces"] >= 1


def test_dry_run_tolerates_m3_bundle_files(write_client, seeded_company, seeded_connection,
                                           seeded_employee, seeded_workspace):
    """dry_run 对含 M3 新文件（workspaces/grants/memories）的包正常预检（不报错不丢失）。"""
    write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": seeded_employee["id"], "access": "read"},
    )
    write_client.post(
        f"/api/v1/companies/{seeded_company['id']}/memories",
        json={"scope": "employee", "employee_id": seeded_employee["id"],
              "title": "预检记忆", "content": "dry-run-mem-content"},
    )
    data = _export(write_client, seeded_company["id"])
    resp = write_client.post("/api/v1/config/import?dry_run=true", content=data,
                             headers={"Content-Type": "application/zip"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is True
    assert body["company_name"] == seeded_company["name"]
