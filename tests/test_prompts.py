"""B4 提示词：不可变版本、激活、diff、哈希校验、文件一致性。"""
from __future__ import annotations

from pathlib import Path

from packages.prompts.service import PROMPTS_ROOT


def _create_prompt(write_client, employee_id, content, note=""):
    resp = write_client.post(
        f"/api/v1/employees/{employee_id}/prompts", json={"content": content, "note": note}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_prompt_version_immutable_and_active(write_client, seeded_employee):
    employee_id = seeded_employee["id"]
    v1 = _create_prompt(write_client, employee_id, "# 角色\n你是分析师。", "初版")
    assert v1["version"] == 1
    assert v1["is_active"] is True
    file_v1 = Path(v1["file_path"])
    assert not file_v1.is_absolute()
    assert file_v1.exists()
    original = file_v1.read_text(encoding="utf-8")

    v2 = _create_prompt(write_client, employee_id, "# 角色\n你是高级分析师。", "强化")
    assert v2["version"] == 2
    assert v2["is_active"] is False
    assert file_v1.read_text(encoding="utf-8") == original  # v1 文件未被改写

    versions = write_client.get(f"/api/v1/employees/{employee_id}/prompts")
    assert [item["version"] for item in versions.json()] == [2, 1]


def test_prompt_activate_switch_pointer(write_client, seeded_employee):
    employee_id = seeded_employee["id"]
    v1 = _create_prompt(write_client, employee_id, "第一版")
    v2 = _create_prompt(write_client, employee_id, "第二版")

    activated = write_client.post(f"/api/v1/prompts/{v2['id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["is_active"] is True

    versions = write_client.get(f"/api/v1/employees/{employee_id}/prompts").json()
    active = [item for item in versions if item["is_active"]]
    assert len(active) == 1 and active[0]["version"] == 2
    assert Path(v1["file_path"]).exists()


def test_prompt_diff(write_client, seeded_employee):
    employee_id = seeded_employee["id"]
    _create_prompt(write_client, employee_id, "line one\nline two\n")
    v2 = _create_prompt(write_client, employee_id, "line one\nline two changed\n")
    diff = write_client.get(f"/api/v1/prompts/{v2['id']}/diff")
    assert diff.status_code == 200
    text = diff.json()["diff"]
    assert "-line two" in text and "+line two changed" in text


def test_prompt_hash_mismatch_detected(write_client, seeded_employee):
    employee_id = seeded_employee["id"]
    v1 = _create_prompt(write_client, employee_id, "原始内容")
    path = Path(v1["file_path"])
    path.write_text("被篡改的内容", encoding="utf-8")

    resp = write_client.get(f"/api/v1/prompts/{v1['id']}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BR_PROMPT_HASH_MISMATCH"

    activate = write_client.post(f"/api/v1/prompts/{v1['id']}/activate")
    assert activate.status_code == 409


def test_prompt_empty_rejected(write_client, seeded_employee):
    resp = write_client.post(
        f"/api/v1/employees/{seeded_employee['id']}/prompts", json={"content": "   "}
    )
    assert resp.status_code == 422


def test_prompt_files_under_expected_directory(seeded_employee):
    assert (PROMPTS_ROOT / "employees").exists()
