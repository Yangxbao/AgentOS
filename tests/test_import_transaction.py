"""M1 收尾：配置导入整体事务 + 文件补偿 + 孤儿可被对账发现。

三个失败注入：
1. 提示词激活阶段数据库失败 → DB 全回滚 + 已写文件补偿删除；
2. 文件写入/改名失败 → 无临时文件残留、DB 无残留；
3. 文件补偿失败 → 保留孤儿文件，reconcile() 能报告，且不误删已有版本。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from packages.prompts.service import reconcile

HEADERS = {"Origin": "http://127.0.0.1:5173", "X-AgentOS-Client": "web"}


@pytest.fixture
def tolerant_client(db_url):
    """允许 500 返回而不抛异常：失败注入需要读取错误包络。"""
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False) as client:
        client.headers.update(HEADERS)
        yield client


def _files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _total(client: TestClient, path: str) -> int:
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    return resp.json()["total"]


def _create_prompts(client: TestClient, employee_id: str) -> None:
    for content, note in (("第一版", "初版"), ("第二版", "改版")):
        resp = client.post(
            f"/api/v1/employees/{employee_id}/prompts",
            json={"content": content, "note": note},
        )
        assert resp.status_code == 201, resp.text


def _export(client: TestClient, company_id: str) -> bytes:
    exported = client.get(f"/api/v1/companies/{company_id}/export")
    assert exported.status_code == 200, exported.text
    return exported.content


def test_import_midway_db_failure_rolls_back(write_client, seeded_company, seeded_employee,
                                             tolerant_client, isolated_prompt_root, monkeypatch):
    _create_prompts(write_client, seeded_employee["id"])
    data = _export(write_client, seeded_company["id"])
    companies_before = _total(write_client, "/api/v1/companies?page_size=200")
    audits_before = _total(write_client, "/api/v1/audit?page_size=200")
    files_before = _files(isolated_prompt_root)

    def boom(*args, **kwargs):
        raise RuntimeError("injected db failure during prompt activation")

    monkeypatch.setattr("packages.config_io.service.activate_revision", boom)
    resp = tolerant_client.post("/api/v1/config/import", content=data)
    assert resp.status_code == 500, resp.text
    assert resp.json()["error"]["code"] == "INTERNAL_ERROR"

    # 公司/员工/提示词元数据全部回滚，审计也不残留
    assert _total(write_client, "/api/v1/companies?page_size=200") == companies_before
    assert _total(write_client, "/api/v1/audit?page_size=200") == audits_before
    # 已写完的提示词文件被补偿删除，原有版本文件不受影响
    assert _files(isolated_prompt_root) == files_before
    assert reconcile(isolated_prompt_root)["orphan_files"] == []


def test_import_file_write_failure_leaves_nothing(write_client, seeded_company, seeded_employee,
                                                  tolerant_client, isolated_prompt_root, monkeypatch):
    _create_prompts(write_client, seeded_employee["id"])
    data = _export(write_client, seeded_company["id"])
    companies_before = _total(write_client, "/api/v1/companies?page_size=200")
    files_before = _files(isolated_prompt_root)

    def disk_full(src, dst):
        raise OSError("injected disk full")

    monkeypatch.setattr("packages.prompts.service._atomic_replace", disk_full)
    resp = tolerant_client.post("/api/v1/config/import", content=data)
    assert resp.status_code == 500, resp.text

    assert _total(write_client, "/api/v1/companies?page_size=200") == companies_before
    assert _files(isolated_prompt_root) == files_before
    # 不留下 .tmp-* 临时文件
    assert not [name for name in _files(isolated_prompt_root) if "/.tmp-" in f"/{name}"]


def test_import_compensation_failure_keeps_orphan_for_reconcile(
    write_client, seeded_company, seeded_employee, tolerant_client, isolated_prompt_root, monkeypatch
):
    _create_prompts(write_client, seeded_employee["id"])
    data = _export(write_client, seeded_company["id"])
    companies_before = _total(write_client, "/api/v1/companies?page_size=200")
    files_before = _files(isolated_prompt_root)

    def boom(*args, **kwargs):
        raise RuntimeError("injected db failure")

    monkeypatch.setattr("packages.config_io.service.activate_revision", boom)
    monkeypatch.setattr("packages.config_io.service._unlink_quietly", lambda path: False)

    resp = tolerant_client.post("/api/v1/config/import", content=data)
    assert resp.status_code == 500, resp.text

    # 数据库仍然整体回滚
    assert _total(write_client, "/api/v1/companies?page_size=200") == companies_before
    # 补偿失败 → 文件留在磁盘，对账脚本必须能发现（2 个提示词版本）
    report = reconcile(isolated_prompt_root)
    assert len(report["orphan_files"]) == 2, report
    assert report["missing_files"] == []
    # 已有有效版本文件未被误删
    assert files_before.issubset(_files(isolated_prompt_root))


def test_import_preserves_prompt_versions_and_hashes(write_client, seeded_company, seeded_employee):
    _create_prompts(write_client, seeded_employee["id"])
    revisions = write_client.get(f"/api/v1/employees/{seeded_employee['id']}/prompts").json()
    second = [item for item in revisions if item["version"] == 2][0]
    assert write_client.post(f"/api/v1/prompts/{second['id']}/activate").status_code == 200

    imported = write_client.post(
        "/api/v1/config/import", content=_export(write_client, seeded_company["id"])
    )
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["counts"]["prompts"] == 2

    employees = write_client.get(
        f"/api/v1/companies/{result['company_id']}/employees?page_size=200"
    ).json()["items"]
    assert len(employees) == 1
    revisions = write_client.get(f"/api/v1/employees/{employees[0]['id']}/prompts").json()
    by_version = {item["version"]: item for item in revisions}
    assert set(by_version) == {1, 2}
    contents = {
        version: write_client.get(f"/api/v1/prompts/{item['id']}").json()["content"]
        for version, item in by_version.items()
    }
    assert contents[1] == "第一版"
    assert contents[2] == "第二版"
    active = [item["version"] for item in revisions if item["is_active"]]
    assert active == [2]
