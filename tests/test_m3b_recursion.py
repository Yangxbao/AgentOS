"""M3-B 递归任务拆分与动态计划：层级上限、树步骤上限、自动分配、replan、父子预算。

验收对齐总任务书 M3-B：
- 三层任务树执行成功，子任务 nested run + 检查点续跑；
- 第 4 层被拒 TASK_DEPTH_EXCEEDED；总步骤超 50 被拒 TASK_STEP_BUDGET_EXCEEDED；
- 步骤省略 employee_id 自动分配并记录 decision；
- 失败步骤 replan 后只重跑失败及其下游，上游不重复；replan 超 3 次被拒；
- 子任务成本计入父任务预算（树聚合），递归不能逃避预算。
"""
from __future__ import annotations

from pathlib import Path

from tests.helpers import all_agent_runs, create_task, wait_task


def _run(client, task_id: str) -> None:
    resp = client.post(f"/api/v1/tasks/{task_id}/run")
    assert resp.status_code == 202, resp.text


def _set_plan(client, task_id: str, steps: list[dict]) -> dict:
    resp = client.put(f"/api/v1/tasks/{task_id}/plan", json={"steps": steps})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _children(client, task_id: str) -> list[dict]:
    return client.get(f"/api/v1/tasks/{task_id}").json()["children"]


def test_three_layer_tree_executes_and_aggregates(write_client, seeded_team, tools_on):
    """三层任务树：根 → 子 → 孙，nested run 驱动，父步骤聚合子计划产出。"""
    company_id = seeded_team["company"]["id"]
    manager, dev, qa = seeded_team["manager"]["id"], seeded_team["dev"]["id"], seeded_team["qa"]["id"]
    task = create_task(
        write_client, company_id, manager, title="三层递归",
        instruction="根任务",
    )
    _set_plan(write_client, task["id"], [
        {"id": "s1", "employee_id": dev, "instruction": "父步骤：交给子计划"},
    ])
    child = _children(write_client, task["id"])[0]
    _set_plan(write_client, child["id"], [
        {"id": "s1", "employee_id": qa, "instruction": "子步骤甲：由孙执行"},
        {"id": "s2", "employee_id": qa, "instruction": "子步骤乙：由孙执行", "depends_on": ["s1"]},
    ])
    grandchild = _children(write_client, child["id"])
    assert len(grandchild) == 2

    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"succeeded"})
    assert detail["state"] == "succeeded"

    child_detail = write_client.get(f"/api/v1/tasks/{child['id']}").json()
    assert child_detail["state"] == "succeeded"

    # 子任务的 nested run 与孙步骤的 agent_run 都真实存在
    runs = child_detail["runs"]
    assert any(r["trigger"] == "nested" for r in runs)
    agents = all_agent_runs(detail) + [a for r in runs for a in r["agent_runs"]]
    assert sum(1 for a in agents if a["step_id"] in {"s1", "s2"}) >= 2

    # 父步骤聚合了子计划产出（mock 输出带 [mock] 前缀）
    output = detail["plan"]["steps"][0]
    assert output["id"] == "s1"
    timeline = write_client.get(f"/api/v1/tasks/{task['id']}/timeline").json()["items"]
    assert any(item["type"] == "task.succeeded" for item in timeline)


def test_depth_4_rejected(write_client, seeded_team):
    """第 4 层被拒：TASK_DEPTH_EXCEEDED（深度上限由后端强制）。"""
    company_id = seeded_team["company"]["id"]
    dev, qa = seeded_team["dev"]["id"], seeded_team["qa"]["id"]
    task = create_task(write_client, company_id, dev, title="深度限制", instruction="根")
    _set_plan(write_client, task["id"], [{"id": "s1", "employee_id": qa, "instruction": "L1"}])
    child = _children(write_client, task["id"])[0]          # depth 1
    _set_plan(write_client, child["id"], [{"id": "s1", "employee_id": qa, "instruction": "L2"}])
    grandchild = _children(write_client, child["id"])[0]     # depth 2
    _set_plan(write_client, grandchild["id"], [{"id": "s1", "employee_id": qa, "instruction": "L3"}])
    great = _children(write_client, grandchild["id"])[0]     # depth 3

    resp = write_client.put(
        f"/api/v1/tasks/{great['id']}/plan",
        json={"steps": [{"id": "s1", "employee_id": qa, "instruction": "L4"}]},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TASK_DEPTH_EXCEEDED"


def test_tree_total_steps_capped(write_client, seeded_team):
    """任务树总步骤超 50 被拒：TASK_STEP_BUDGET_EXCEEDED（跨全树计数）。"""
    company_id = seeded_team["company"]["id"]
    dev, qa = seeded_team["dev"]["id"], seeded_team["qa"]["id"]
    task = create_task(write_client, company_id, dev, title="步骤上限", instruction="根")
    _set_plan(write_client, task["id"], [
        {"id": f"s{i}", "employee_id": qa, "instruction": f"步骤{i}"} for i in range(1, 21)
    ])
    children = _children(write_client, task["id"])
    child_a, child_b = children[0]["id"], children[1]["id"]

    # 子树 A：20 步 → 全树 40，仍允许
    resp = write_client.put(f"/api/v1/tasks/{child_a}/plan", json={
        "steps": [{"id": f"a{i}", "employee_id": qa, "instruction": f"A{i}"} for i in range(1, 21)],
    })
    assert resp.status_code == 200, resp.text

    # 子树 B：15 步 → 全树 55 > 50，拒绝
    resp = write_client.put(f"/api/v1/tasks/{child_b}/plan", json={
        "steps": [{"id": f"b{i}", "employee_id": qa, "instruction": f"B{i}"} for i in range(1, 16)],
    })
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TASK_STEP_BUDGET_EXCEEDED"


def test_step_without_employee_auto_assigned(write_client, seeded_team):
    """省略 employee_id 的步骤按能力/工具自动分配，并记录 assignment decision。"""
    company_id = seeded_team["company"]["id"]
    dev = seeded_team["dev"]["id"]
    task = create_task(write_client, company_id, dev, title="自动分配", instruction="根")
    detail = _set_plan(write_client, task["id"], [
        {"id": "s1", "instruction": "谁有空谁做"},
    ])
    step = detail["plan"]["steps"][0]
    assert step["employee_id"] and step["employee_id"] != ""
    assert step["auto_assigned"] is True
    assert step["assignment_decision_id"]
    # decision 落库可查（派工决策历史）
    resp = write_client.get(
        f"/api/v1/assignments/{step['assignment_decision_id']}"
    )
    assert resp.status_code == 200, resp.text


def test_replan_reruns_only_failed_and_downstream(write_client, seeded_team):
    """replan：只重置失败步骤及下游；重试后上游不重复执行。"""
    company_id = seeded_team["company"]["id"]
    dev, qa = seeded_team["dev"]["id"], seeded_team["qa"]["id"]
    task = create_task(write_client, company_id, dev, title="重规划", instruction="根")
    _set_plan(write_client, task["id"], [
        {"id": "s1", "employee_id": qa, "instruction": "上游成功步骤"},
        {"id": "s2", "employee_id": qa, "instruction": "[fail] 下游失败步骤", "depends_on": ["s1"]},
    ])
    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"failed"})
    assert detail["result"]["error"]["code"] == "EXECUTION_FAILED"
    before_agents = all_agent_runs(detail)
    assert sum(1 for a in before_agents if a["step_id"] == "s1") == 1

    resp = write_client.post(f"/api/v1/tasks/{task['id']}/replan", json={
        "steps": [
            {"id": "s1", "employee_id": qa, "instruction": "上游成功步骤"},
            {"id": "s2", "employee_id": qa, "instruction": "修复后的下游步骤", "depends_on": ["s1"]},
        ],
        "failed_step_id": "s2",
        "reason": "修复失败步骤",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan_revision"] == 2 and body["replan_count"] == 1

    # 计划版本历史
    revisions = write_client.get(f"/api/v1/tasks/{task['id']}/plan-revisions").json()
    assert revisions["total"] == 2
    assert revisions["items"][-1]["reason"] == "修复失败步骤"

    # 重试：s1 不重复执行（仍是 1 个 agent_run），s2 重跑成功
    resp = write_client.post(f"/api/v1/tasks/{task['id']}/retry")
    assert resp.status_code == 202, resp.text
    detail = wait_task(write_client, task["id"], {"succeeded"})
    agents = all_agent_runs(detail)
    assert sum(1 for a in agents if a["step_id"] == "s1") == 1  # 上游不重复
    assert sum(1 for a in agents if a["step_id"] == "s2") == 2  # 失败 1 次 + 重跑成功 1 次


def test_replan_limit_3(write_client, seeded_team):
    """replan 超 3 次被拒：TASK_REPLAN_LIMIT。"""
    company_id = seeded_team["company"]["id"]
    dev, qa = seeded_team["dev"]["id"], seeded_team["qa"]["id"]
    task = create_task(write_client, company_id, dev, title="重规划上限", instruction="根")
    _set_plan(write_client, task["id"], [
        {"id": "s1", "employee_id": qa, "instruction": "[fail] 一直失败"},
    ])
    _run(write_client, task["id"])
    wait_task(write_client, task["id"], {"failed"})

    steps = [{"id": "s1", "employee_id": qa, "instruction": "[fail] 一直失败"}]
    for _ in range(3):
        resp = write_client.post(
            f"/api/v1/tasks/{task['id']}/replan",
            json={"steps": steps, "failed_step_id": "s1", "reason": "再试"},
        )
        assert resp.status_code == 200, resp.text
    resp = write_client.post(
        f"/api/v1/tasks/{task['id']}/replan",
        json={"steps": steps, "failed_step_id": "s1", "reason": "第四次"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "TASK_REPLAN_LIMIT"


def test_nested_failure_propagates_and_partial_success_kept(write_client, seeded_team, tools_on):
    """失败传播：孙步骤失败 → 子任务失败 → 父任务失败；已完成上游保留在子检查点。"""
    company_id = seeded_team["company"]["id"]
    dev, qa = seeded_team["dev"]["id"], seeded_team["qa"]["id"]
    task = create_task(write_client, company_id, dev, title="失败传播", instruction="根")
    _set_plan(write_client, task["id"], [
        {"id": "s1", "employee_id": dev, "instruction": "父步骤（子计划）"},
    ])
    child = _children(write_client, task["id"])[0]
    _set_plan(write_client, child["id"], [
        {"id": "g1", "employee_id": qa, "instruction": "孙步骤成功"},
        {"id": "g2", "employee_id": qa, "instruction": "[fail] 孙步骤失败", "depends_on": ["g1"]},
    ])
    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"failed"})
    assert detail["state"] == "failed"

    child_detail = write_client.get(f"/api/v1/tasks/{child['id']}").json()
    assert child_detail["state"] == "failed"
    # 部分成功：g1 完成并保留在 nested 检查点
    nested_runs = [r for r in child_detail["runs"] if r["trigger"] == "nested"]
    assert nested_runs and nested_runs[-1]["state"] == "failed"
    assert nested_runs[-1]["checkpoint"]["completed_steps"] == ["g1"]

    # 修复后重试父任务：nested 续跑只补 g2，g1 不重复
    write_client.post(f"/api/v1/tasks/{task['id']}/replan", json={
        "steps": [{"id": "s1", "employee_id": dev, "instruction": "父步骤（子计划）"}],
        "failed_step_id": "s1",
        "reason": "修复子计划",
    })
    # 子任务在 replan 中被重置为 pending；重新给子任务下发修好的计划
    child_pending = _children(write_client, task["id"])
    target = next(c for c in child_pending if c["id"] == child["id"])
    assert target["state"] == "pending"
    _set_plan(write_client, child["id"], [
        {"id": "g1", "employee_id": qa, "instruction": "孙步骤成功"},
        {"id": "g2", "employee_id": qa, "instruction": "孙步骤已修复", "depends_on": ["g1"]},
    ])
    resp = write_client.post(f"/api/v1/tasks/{task['id']}/retry")
    assert resp.status_code == 202, resp.text
    detail = wait_task(write_client, task["id"], {"succeeded"})
    assert detail["state"] == "succeeded"
    assert write_client.get(f"/api/v1/tasks/{child['id']}").json()["state"] == "succeeded"


def test_child_cost_counts_toward_parent_budget(write_client, seeded_team, tools_on):
    """父子预算：子树消耗计入根预算（树聚合），递归不能逃避预算限制。

    mock 模式下执行器把 cost 强制写 0（M3-E 诚实性规则），单次调用路径没有
    工具循环的 pending 机制，因此用 Token 预算触发熔断；成本/用量的可追溯性
    （usage_record 挂在子任务 nested run 上）单独断言。
    """
    company_id = seeded_team["company"]["id"]
    resp = write_client.patch(
        f"/api/v1/companies/{company_id}",
        json={"policy": {"default_task_budget_tokens": 5}},
    )
    assert resp.status_code == 200, resp.text

    dev, qa = seeded_team["dev"]["id"], seeded_team["qa"]["id"]
    task = create_task(write_client, company_id, dev, title="父子预算", instruction="根")
    _set_plan(write_client, task["id"], [
        {"id": "s1", "employee_id": dev, "instruction": "父步骤（子计划）"},
    ])
    child = _children(write_client, task["id"])[0]
    _set_plan(write_client, child["id"], [
        {"id": "g1", "employee_id": qa, "instruction": "孙步骤一"},
        {"id": "g2", "employee_id": qa, "instruction": "孙步骤二", "depends_on": ["g1"]},
    ])
    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"paused"})
    # 孙步骤一消耗后，孙步骤二开始前的树级预算检查触发暂停
    assert detail["result"]["error"]["code"] == "BUDGET_EXCEEDED"
    assert "task.budget_exceeded" in [
        item.get("type")
        for item in write_client.get(f"/api/v1/tasks/{task['id']}/timeline").json()["items"]
    ]
    # 成本/用量真实挂在子任务的 nested run 上（可追溯），且 mock 标记 billable=false
    child_detail = write_client.get(f"/api/v1/tasks/{child['id']}").json()
    nested_runs = [r for r in child_detail["runs"] if r["trigger"] == "nested"]
    assert nested_runs, "子任务应有 nested run"
    usage = write_client.get(
        f"/api/v1/tasks/{child['id']}/usage"
    ).json()
    assert usage["total_tokens"] > 0


def test_nested_tool_approval_suspends_parent(write_client, seeded_team, tool_employee,
                                              seeded_workspace, tools_on):
    """子计划内的高风险工具审批：父任务同步挂起，批准后恢复完成。"""
    company_id = seeded_team["company"]["id"]
    dev = seeded_team["dev"]["id"]
    task = create_task(write_client, company_id, dev, title="嵌套审批", instruction="根")
    _set_plan(write_client, task["id"], [
        {"id": "s1", "employee_id": dev, "instruction": "父步骤（子计划）"},
    ])
    child = _children(write_client, task["id"])[0]
    # 子计划步骤交给 tool_employee，执行 overwrite 写文件（high 风险 → 需审批）
    _set_plan(write_client, child["id"], [
        {"id": "g1", "employee_id": tool_employee["id"],
         "instruction": (
             f'[tool:fs.write_file {{"workspace_id":"{seeded_workspace["id"]}",'
             f'"path":"notes/a.txt","content":"nested","mode":"overwrite"}}] 覆盖写入'
         )},
    ])
    _run(write_client, task["id"])
    detail = wait_task(write_client, task["id"], {"awaiting_approval"})
    assert detail["state"] == "awaiting_approval"
    assert write_client.get(f"/api/v1/tasks/{child['id']}").json()["state"] == "awaiting_approval"

    # 找到工具审批并批准 → 子任务经审批 run 恢复完成；父任务自动续跑后聚合成功
    approvals = write_client.get(f"/api/v1/tasks/{child['id']}/approvals").json()
    pending = next(a for a in approvals if a["status"] == "pending")
    resp = write_client.post(f"/api/v1/approvals/{pending['id']}/decision", json={
        "decision": "approve", "comment": "同意",
    })
    assert resp.status_code == 200, resp.text
    child_detail = wait_task(write_client, child["id"], {"succeeded"})
    assert child_detail["state"] == "succeeded"

    # 2026-11-08：批准后父任务自动续跑，不再需要人工 resume
    detail = wait_task(write_client, task["id"], {"succeeded"}, timeout=40.0)
    assert detail["state"] == "succeeded"
    types = [i.get("type") for i in _event_types_list(write_client, task["id"])]
    assert "task.auto_resumed" in types


def _event_types_list(client, task_id: str) -> list[dict]:
    return client.get(f"/api/v1/tasks/{task_id}/timeline").json()["items"]


def test_nested_approval_auto_resumes_parent(write_client, seeded_team, tool_employee,
                                             seeded_workspace, workspace_root, tools_on):
    """子任务内工具审批批准后：子任务恢复完成 → 父任务自动续跑（无需人工再点恢复）。

    对应 M3-B 已知限制的修复；人工恢复路径（手动 resume）仍保留可用。
    """
    company_id = seeded_team["company"]["id"]
    dev = seeded_team["dev"]["id"]
    task = create_task(write_client, company_id, dev, title="嵌套审批自动续跑", instruction="根")
    resp = write_client.put(f"/api/v1/tasks/{task['id']}/plan", json={"steps": [
        {"id": "s1", "employee_id": dev, "instruction": "父步骤（子计划）"},
    ]})
    assert resp.status_code == 200, resp.text
    child = write_client.get(f"/api/v1/tasks/{task['id']}").json()["children"][0]
    resp = write_client.put(f"/api/v1/tasks/{child['id']}/plan", json={"steps": [
        {"id": "g1", "employee_id": tool_employee["id"],
         "instruction": (
             f'[tool:fs.write_file {{"workspace_id":"{seeded_workspace["id"]}",'
             f'"path":"notes/auto_resume.txt","content":"auto","mode":"overwrite"}}] 覆盖写入'
         )},
    ]})
    assert resp.status_code == 200, resp.text

    write_client.post(f"/api/v1/tasks/{task['id']}/run")
    detail = wait_task(write_client, task["id"], {"awaiting_approval"})
    assert detail["state"] == "awaiting_approval"

    # 批准子任务里的工具调用 → 子任务经审批 run 恢复完成 → 父任务应自动续跑成功
    approvals = write_client.get(f"/api/v1/tasks/{child['id']}/approvals").json()
    pending = next(a for a in approvals if a["status"] == "pending")
    resp = write_client.post(
        f"/api/v1/approvals/{pending['id']}/decision", json={"decision": "approve"}
    )
    assert resp.status_code == 200, resp.text

    detail = wait_task(write_client, task["id"], {"succeeded"}, timeout=40.0)
    assert detail["state"] == "succeeded"
    assert write_client.get(f"/api/v1/tasks/{child['id']}").json()["state"] == "succeeded"

    # 自动续跑事件已记录（区别于人工 resume）
    types = [i.get("type") for i in _event_types_list(write_client, task["id"])]
    assert "task.auto_resumed" in types

    from pathlib import Path
    assert (Path(workspace_root) / "notes" / "auto_resume.txt").read_text(encoding="utf-8") == "auto"


def test_three_level_nested_approval_cascades_auto_resume(
    write_client, seeded_team, tool_employee, seeded_workspace, workspace_root, tools_on
):
    """祖父→父→子三层嵌套：子任务工具审批批准后，auto_resume 逐层级联到祖父。

    同时验证本批"预算预扣"在嵌套入口不破坏 mock 链路（mock 预估为 0）。
    """
    company_id = seeded_team["company"]["id"]
    dev = seeded_team["dev"]["id"]
    grand = create_task(write_client, company_id, dev, title="祖父", instruction="祖父根任务")
    resp = write_client.put(f"/api/v1/tasks/{grand['id']}/plan", json={"steps": [
        {"id": "s1", "employee_id": dev, "instruction": "父层（子计划）"},
    ]})
    assert resp.status_code == 200, resp.text
    parent = write_client.get(f"/api/v1/tasks/{grand['id']}").json()["children"][0]
    resp = write_client.put(f"/api/v1/tasks/{parent['id']}/plan", json={"steps": [
        {"id": "g1", "employee_id": dev, "instruction": "子层（孙计划）"},
    ]})
    assert resp.status_code == 200, resp.text
    child = write_client.get(f"/api/v1/tasks/{parent['id']}").json()["children"][0]
    resp = write_client.put(f"/api/v1/tasks/{child['id']}/plan", json={"steps": [
        {"id": "x1", "employee_id": tool_employee["id"],
         "instruction": (
             f'[tool:fs.write_file {{"workspace_id":"{seeded_workspace["id"]}",'
             f'"path":"notes/cascade.txt","content":"cascade","mode":"overwrite"}}] 覆盖写入'
         )},
    ]})
    assert resp.status_code == 200, resp.text

    write_client.post(f"/api/v1/tasks/{grand['id']}/run")
    detail = wait_task(write_client, grand["id"], {"awaiting_approval"})
    assert detail["state"] == "awaiting_approval"

    approvals = write_client.get(f"/api/v1/tasks/{child['id']}/approvals").json()
    pending = next(a for a in approvals if a["status"] == "pending")
    resp = write_client.post(
        f"/api/v1/approvals/{pending['id']}/decision", json={"decision": "approve"}
    )
    assert resp.status_code == 200, resp.text

    # 三层级联：祖父自动续跑成功，子/父均成功
    detail = wait_task(write_client, grand["id"], {"succeeded"}, timeout=60.0)
    assert detail["state"] == "succeeded"
    assert write_client.get(f"/api/v1/tasks/{parent['id']}").json()["state"] == "succeeded"
    assert write_client.get(f"/api/v1/tasks/{child['id']}").json()["state"] == "succeeded"

    # 被自动续跑的两层（父、祖父）有 auto_resumed 事件；
    # 孙任务由审批批准直接入队（trigger=approval），天然没有该事件
    for tid in (grand["id"], parent["id"]):
        types = [i.get("type") for i in _event_types_list(write_client, tid)]
        assert "task.auto_resumed" in types, f"任务 {tid} 缺少 auto_resumed 事件"
    assert (Path(workspace_root) / "notes" / "cascade.txt").read_text(encoding="utf-8") == "cascade"
