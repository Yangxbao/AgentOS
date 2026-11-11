"""视觉链路（M4 前置）：fs.read_image 工具 + tool_loop 多模态消息注入。"""
from __future__ import annotations

import base64

import pytest

from packages.execution.tool_loop import _flush_pending_images
from packages.shared.errors import DomainError
from packages.tools.context import ToolContext
from packages.tools.fs import read_image

# 1x1 透明 PNG 的最小合法字节（公开常量，用于无 Pillow 生成测试图）
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def vision_employee(write_client, seeded_team, seeded_workspace):
    """绑定测试连接 + 授权 fs.read_image 的员工（读工作区）。"""
    company_id = seeded_team["company"]["id"]
    resp = write_client.post(
        f"/api/v1/companies/{company_id}/employees",
        json={
            "name": "视觉员工", "title": "质检",
            "primary_model_id": seeded_team["connection"]["id"],
            "tools_allowed": ["fs.read_image"],
        },
    )
    assert resp.status_code == 201, resp.text
    grant = write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": resp.json()["id"], "access": "read"},
    )
    assert grant.status_code == 201, grant.text
    return resp.json()


def _ctx(db_url, seeded_team, vision_employee) -> ToolContext:
    from packages.persistence import get_session
    from packages.persistence.models import Company, Employee
    from packages.tools.policy import effective_tool_policy

    with get_session() as session:
        employee = session.get(Employee, vision_employee["id"])
        company = session.get(Company, employee.company_id)
        return ToolContext(
            session=session, owner_id=employee.owner_id, company=company,
            employee=employee, tool_policy=effective_tool_policy(company),
        )


@pytest.fixture
def image_in_workspace(workspace_root):
    target = workspace_root / "notes" / "spec.png"
    target.write_bytes(PNG_1PX)
    return "notes/spec.png"


async def test_read_image_fills_pending_images(db_url, seeded_team, vision_employee,
                                               seeded_workspace, image_in_workspace):
    ctx = _ctx(db_url, seeded_team, vision_employee)
    result = await read_image(ctx, {
        "workspace_id": seeded_workspace["id"], "path": image_in_workspace,
    })
    assert result["image_ref"] == "img_1"
    assert result["mime"] == "image/png"
    assert len(ctx.pending_images) == 1
    image = ctx.pending_images[0]
    assert image["data_uri"].startswith("data:image/png;base64,")
    # 工具结果文本不含 base64（避免撑爆上下文）
    assert "base64" not in str(result)


async def test_read_image_rejects_non_image(db_url, seeded_team, vision_employee,
                                            seeded_workspace, workspace_root):
    (workspace_root / "notes" / "plain.txt").write_text("hello", encoding="utf-8")
    ctx = _ctx(db_url, seeded_team, vision_employee)
    with pytest.raises(DomainError) as exc_info:
        await read_image(ctx, {"workspace_id": seeded_workspace["id"], "path": "notes/plain.txt"})
    assert exc_info.value.code == "TOOL_ARGS_INVALID"


async def test_read_image_rejects_oversize(db_url, seeded_team, vision_employee,
                                           seeded_workspace, workspace_root, monkeypatch):
    import packages.tools.fs as fs_mod

    monkeypatch.setattr(fs_mod, "MAX_IMAGE_BYTES", 4)
    (workspace_root / "notes" / "big.png").write_bytes(PNG_1PX)
    ctx = _ctx(db_url, seeded_team, vision_employee)
    with pytest.raises(DomainError) as exc_info:
        await read_image(ctx, {"workspace_id": seeded_workspace["id"], "path": "notes/big.png"})
    assert exc_info.value.code == "TOOL_OUTPUT_TOO_LARGE"


async def test_read_image_rejects_path_escape(db_url, seeded_team, vision_employee,
                                              seeded_workspace):
    ctx = _ctx(db_url, seeded_team, vision_employee)
    with pytest.raises(DomainError) as exc_info:
        await read_image(ctx, {"workspace_id": seeded_workspace["id"], "path": "../outside.png"})
    assert exc_info.value.code in {"TOOL_PATH_DENIED", "TOOL_PATH_NOT_FOUND"}


def test_flush_pending_images_appends_user_message():
    ctx = ToolContext.__new__(ToolContext)  # 只测消息变换，不碰 DB
    ctx.pending_images = [{"data_uri": "data:image/png;base64,AAAA", "ref": "img_1"}]
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "看图"},
        {"role": "assistant", "content": "", "tool_calls": []},
        {"role": "tool", "tool_call_id": "c1", "name": "fs.read_image", "content": "{}"},
    ]
    _flush_pending_images(messages, ctx)
    assert len(messages) == 5
    injected = messages[-1]
    assert injected["role"] == "user"
    parts = injected["content"]
    assert parts[0]["type"] == "text" and "数据" in parts[0]["text"]
    assert parts[1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    # 幂等：清空后再次调用不追加
    _flush_pending_images(messages, ctx)
    assert len(messages) == 5


def test_flush_noop_without_images():
    ctx = ToolContext.__new__(ToolContext)
    ctx.pending_images = []
    messages: list[dict] = [{"role": "user", "content": "hi"}]
    _flush_pending_images(messages, ctx)
    assert messages == [{"role": "user", "content": "hi"}]


def test_litellm_adapter_injects_images_as_content_parts():
    import asyncio

    from packages.agent_core.adapter import LiteLLMAdapter
    from packages.shared.types import AgentTask

    adapter = LiteLLMAdapter(model="test-model")
    handle = asyncio.run(adapter.execute(
        AgentTask(instruction="看图说话", images=["data:image/png;base64,AAAA"]),
        system_prompt="sys",
    ))
    messages = adapter._handles[handle.id]["messages"]
    assert messages[0]["role"] == "system"
    user = messages[1]
    assert user["role"] == "user"
    assert isinstance(user["content"], list)
    assert user["content"][0]["type"] == "text" and "看图说话" in user["content"][0]["text"]
    assert "数据" in user["content"][0]["text"]  # 图片不可信数据声明
    assert user["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


def test_litellm_adapter_plain_text_without_images():
    import asyncio

    from packages.agent_core.adapter import LiteLLMAdapter
    from packages.shared.types import AgentTask

    adapter = LiteLLMAdapter(model="test-model")
    handle = asyncio.run(adapter.execute(AgentTask(instruction="纯文本")))
    user = adapter._handles[handle.id]["messages"][-1]
    assert isinstance(user["content"], str) and user["content"] == "纯文本"


def test_task_images_requires_workspace_grant(db_url, seeded_team, seeded_workspace,
                                              workspace_root, image_in_workspace):
    """没有工作区读授权的员工：context.images 直接拒绝（不静默跳过）。"""
    import pytest as _pytest

    from packages.execution.executor import _task_images
    from packages.persistence import get_session
    from packages.persistence.models import Employee, Task
    from packages.shared.errors import DomainError
    from packages.shared.types import new_id

    with get_session() as session:
        employee = session.get(Employee, seeded_team["manager"]["id"])  # 经理未授权工作区
        task = Task(id=new_id(), title="t", company_id=employee.company_id,
                    owner_id=employee.owner_id,
                    context={"images": [{"workspace_id": seeded_workspace["id"],
                                         "path": image_in_workspace}]})
        session.add(task)
        session.commit()
        with _pytest.raises(DomainError):
            _task_images(session, task, employee, {})


def test_task_images_converts_with_grant(write_client, db_url, seeded_team, seeded_workspace,
                                         workspace_root, image_in_workspace):
    """已授权员工：context.images → data URI 列表（复用 fs 安全读取）。"""
    from packages.execution.executor import _task_images
    from packages.persistence import get_session
    from packages.persistence.models import Employee, Task
    from packages.shared.types import new_id

    grant = write_client.post(
        f"/api/v1/workspaces/{seeded_workspace['id']}/grants",
        json={"employee_id": seeded_team["manager"]["id"], "access": "read"},
    )
    assert grant.status_code == 201, grant.text

    with get_session() as session:
        employee = session.get(Employee, seeded_team["manager"]["id"])
        task = Task(id=new_id(), title="t", company_id=employee.company_id,
                    owner_id=employee.owner_id,
                    context={"images": [{"workspace_id": seeded_workspace["id"],
                                         "path": image_in_workspace}]})
        session.add(task)
        session.commit()
        # 任务级 images（步骤未声明时回退）与步骤级声明都应生效
        uris = _task_images(session, task, employee, {})
        assert len(uris) == 1
        assert uris[0].startswith("data:image/png;base64,")
        step_level = {"workspace_id": seeded_workspace["id"], "path": "notes/spec.png"}
        uris2 = _task_images(session, task, employee, {"images": [step_level]})
        assert len(uris2) == 1 and uris2[0].startswith("data:image/png;base64,")
