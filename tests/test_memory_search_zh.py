"""记忆检索中文增强：2-gram 召回 + 相关性排序（查询端，不改表结构）。"""
from __future__ import annotations

from packages.memory.retrieval import cjk_2grams as _cjk_2grams
from packages.memory.service import _expand_query_tokens


def test_cjk_2grams_basic():
    assert _cjk_2grams("诗人") == ["诗人"]
    assert _cjk_2grams("大肥鱼") == ["大肥", "肥鱼"]
    assert _cjk_2grams("abc 诗人") == ["诗人"]  # ASCII 段不拆
    assert _cjk_2grams("诗") == []  # 单字不产 2-gram


def test_expand_query_tokens_keeps_original_words_first():
    tokens = _expand_query_tokens("数字员工 预算")
    assert tokens[0] == "数字员工"
    assert tokens[1] == "预算"
    # 中文段产生 2-gram：数字/字员/员工
    for gram in ("数字", "字员", "员工"):
        assert gram in tokens


def _create_memory(write_client, company_id: str, title: str, content: str) -> dict:
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/memories",
        json={"scope": "company", "kind": "note", "title": title, "content": content},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _search(write_client, company_id: str, query: str) -> list[dict]:
    resp = write_client.get(
        "/api/v1/memories/search",
        params={"q": query, "company_id": company_id, "top_k": 5},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def test_chinese_contiguous_substring_recall(write_client, seeded_company):
    cid = seeded_company["id"]
    _create_memory(write_client, cid, "诗人档案", "大肥鱼是诗人，喜欢在深夜写十四行诗")
    items = _search(write_client, cid, "十四行")
    assert len(items) == 1
    assert items[0]["title"] == "诗人档案"


def test_chinese_noncontiguous_2gram_recall(write_client, seeded_company):
    """查询词在原文中不连续（员工…预算），靠 2-gram 召回——增强前这是空结果。"""
    cid = seeded_company["id"]
    _create_memory(write_client, cid, "项目背景", "数字员工系统需要审批与预算控制")
    items = _search(write_client, cid, "员工预算")
    assert len(items) == 1
    assert items[0]["title"] == "项目背景"


def test_relevance_orders_multi_hit_first(write_client, seeded_company):
    """两个候选都命中时，命中词更多、覆盖更全的排前面。"""
    cid = seeded_company["id"]
    _create_memory(write_client, cid, "弱相关", "预算表在共享盘")
    _create_memory(write_client, cid, "强相关", "数字员工系统的预算由公司策略约束，预算超支会熔断")
    items = _search(write_client, cid, "数字员工 预算")
    assert items, "至少召回一条"
    assert items[0]["title"] == "强相关"


def test_english_query_still_works(write_client, seeded_company):
    cid = seeded_company["id"]
    _create_memory(write_client, cid, "english", "deploy checklist for release v2")
    items = _search(write_client, cid, "release")
    assert len(items) == 1
    assert items[0]["title"] == "english"
