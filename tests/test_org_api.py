"""B2 组织域验收：公司/部门/岗位 CRUD、规则 BR-02/03/04a-e/05、组织树、分页与并发。"""
from __future__ import annotations

import pytest

# ---------- 公司 API-01..05 ----------

def test_company_create_list_get(write_client):
    created = write_client.post("/api/v1/companies", json={"name": "星辰科技", "description": "AI 公司"})
    assert created.status_code == 201
    company = created.json()
    assert company["status"] == "active"
    assert company["policy"]["max_risk_level"] == "medium"
    assert company["policy"]["review_policy"]["allow_subordinate_review"] is False

    listed = write_client.get("/api/v1/companies")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == company["id"]

    got = write_client.get(f"/api/v1/companies/{company['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "星辰科技"


def test_company_duplicate_name_rejected(write_client, seeded_company):
    resp = write_client.post("/api/v1/companies", json={"name": seeded_company["name"]})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BR_COMPANY_NAME_TAKEN"


def test_company_update_and_stale_conflict(write_client, seeded_company):
    company_id = seeded_company["id"]
    ok = write_client.patch(
        f"/api/v1/companies/{company_id}",
        json={"description": "更新后的简介", "expected_updated_at": seeded_company["updated_at"]},
    )
    assert ok.status_code == 200
    assert ok.json()["description"] == "更新后的简介"

    stale = write_client.patch(
        f"/api/v1/companies/{company_id}",
        json={"description": "过期写入", "expected_updated_at": seeded_company["updated_at"]},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "CONFLICT_STALE"


def test_company_archive_blocks_org_changes(write_client, seeded_company):
    company_id = seeded_company["id"]
    archived = write_client.post(f"/api/v1/companies/{company_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    blocked = write_client.post(
        f"/api/v1/companies/{company_id}/departments", json={"name": "研发部"}
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "BR_COMPANY_ARCHIVED"


# ---------- 部门 API-06..11 ----------

def _create_department(write_client, company_id, name, parent_id=None):
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/departments",
        json={"name": name, "parent_id": parent_id},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_position(write_client, company_id, name, **kwargs):
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/positions",
        json={"name": name, **kwargs},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_department_depth_calculation(write_client, seeded_company):
    company_id = seeded_company["id"]
    l1 = _create_department(write_client, company_id, "研发中心")
    l2 = _create_department(write_client, company_id, "平台部", l1["id"])
    l3 = _create_department(write_client, company_id, "基础组", l2["id"])
    assert (l1["depth"], l2["depth"], l3["depth"]) == (0, 1, 2)


def test_department_max_depth_rejected(write_client, seeded_company):
    company_id = seeded_company["id"]
    parent = _create_department(write_client, company_id, "L0")
    for level in range(1, 8):  # 建到第 8 层（depth 0..7）
        parent = _create_department(write_client, company_id, f"L{level}", parent["id"])
    assert parent["depth"] == 7

    too_deep = write_client.post(
        f"/api/v1/companies/{company_id}/departments",
        json={"name": "L8", "parent_id": parent["id"]},
    )
    assert too_deep.status_code == 409
    assert too_deep.json()["error"]["code"] == "BR_DEPARTMENT_MAX_DEPTH"


def test_department_duplicate_name(write_client, seeded_company):
    company_id = seeded_company["id"]
    _create_department(write_client, company_id, "质量部")
    dup = write_client.post(f"/api/v1/companies/{company_id}/departments", json={"name": "质量部"})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "BR_DEPARTMENT_NAME_TAKEN"


def test_department_move_to_descendant_rejected(write_client, seeded_company):
    company_id = seeded_company["id"]
    root = _create_department(write_client, company_id, "研发中心")
    child = _create_department(write_client, company_id, "平台部", root["id"])

    resp = write_client.post(
        f"/api/v1/departments/{root['id']}/move",
        json={"new_parent_id": child["id"]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BR_DEPARTMENT_CYCLE"


def test_department_delete_protection(write_client, seeded_company):
    company_id = seeded_company["id"]
    root = _create_department(write_client, company_id, "研发中心")
    _create_department(write_client, company_id, "平台部", root["id"])

    has_child = write_client.delete(f"/api/v1/departments/{root['id']}")
    assert has_child.status_code == 409
    assert has_child.json()["error"]["code"] == "BR_DEPARTMENT_HAS_CHILDREN"

    empty = _create_department(write_client, company_id, "临时组")
    deleted = write_client.delete(f"/api/v1/departments/{empty['id']}")
    assert deleted.status_code == 204


def test_department_with_position_cannot_be_deleted(write_client, seeded_company):
    company_id = seeded_company["id"]
    dept = _create_department(write_client, company_id, "平台部")
    _create_position(write_client, company_id, "后端工程师", department_id=dept["id"])

    resp = write_client.delete(f"/api/v1/departments/{dept['id']}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BR_DEPARTMENT_HAS_POSITIONS"


# ---------- 岗位 API-12..16 ----------

def test_position_crud_and_review_flag(write_client, seeded_company):
    company_id = seeded_company["id"]
    dept = _create_department(write_client, company_id, "质量部")
    position = _create_position(
        write_client, company_id, "技术审查官",
        department_id=dept["id"], can_review=True,
        review_capability_tags=["code.review"], is_managerial=True,
        default_permissions={"file_ops": ["read"]},
    )
    assert position["can_review"] is True
    assert position["review_capability_tags"] == ["code.review"]

    updated = write_client.patch(
        f"/api/v1/positions/{position['id']}",
        json={"responsibilities": "负责代码审查"},
    )
    assert updated.status_code == 200
    assert updated.json()["responsibilities"] == "负责代码审查"

    got = write_client.get(f"/api/v1/positions/{position['id']}")
    assert got.status_code == 200

    listed = write_client.get(f"/api/v1/companies/{company_id}/positions")
    assert listed.json()["total"] == 1

    deleted = write_client.delete(f"/api/v1/positions/{position['id']}")
    assert deleted.status_code == 204


def test_position_duplicate_name(write_client, seeded_company):
    company_id = seeded_company["id"]
    _create_position(write_client, company_id, "测试工程师")
    dup = write_client.post(
        f"/api/v1/companies/{company_id}/positions", json={"name": "测试工程师"}
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "BR_POSITION_NAME_TAKEN"


# ---------- 组织树与分页 ----------

def test_org_tree_structure(write_client, seeded_company):
    company_id = seeded_company["id"]
    root = _create_department(write_client, company_id, "研发中心")
    child = _create_department(write_client, company_id, "平台部", root["id"])
    _create_position(write_client, company_id, "平台负责人", department_id=child["id"])
    _create_position(write_client, company_id, "CTO", department_id=None, is_managerial=True)

    tree = write_client.get(f"/api/v1/companies/{company_id}/org-tree")
    assert tree.status_code == 200
    body = tree.json()
    assert body["company"]["id"] == company_id
    assert len(body["departments"]) == 1
    root_node = body["departments"][0]
    assert root_node["name"] == "研发中心"
    assert len(root_node["children"]) == 1
    assert root_node["children"][0]["positions"][0]["name"] == "平台负责人"
    assert body["unassigned_positions"][0]["name"] == "CTO"


def test_page_size_limit_on_real_endpoint(write_client, seeded_company):
    company_id = seeded_company["id"]
    resp = write_client.get(f"/api/v1/companies/{company_id}/positions?page_size=201")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("missing", ["nonexistent-company"])
def test_org_endpoints_404(write_client, missing):
    resp = write_client.get(f"/api/v1/companies/{missing}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"
