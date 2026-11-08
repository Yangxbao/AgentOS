"""M3-0 浏览器验收：用本机已安装的 Microsoft Edge（headless + CDP）真实渲染并点击。

不安装 Playwright / 任何新依赖；只用标准库 + 已安装的 websockets。
覆盖：任务列表、表单创建、单 Agent 执行、审批、多 Agent、暂停/恢复、模型连接、
员工详情、组织设置、监控、组织图、未捕获 JS 异常。

用法：
    python scripts/browser_acceptance.py
输出：docs/testing/m3_browser_acceptance.txt（终端同时打印）
截图：docs/testing/m3_browser/*.png
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "browser_acceptance.db"
PROMPTS_DIR = ROOT / "data" / "prompts_browser_acceptance"
SHOT_DIR = ROOT / "docs" / "testing" / "m3_browser"
EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]
API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:5173"
DEBUG_PORT = 9333
HEADERS = {"Content-Type": "application/json", "Origin": WEB, "X-AgentOS-Client": "web"}
# 本机验收必须绕过系统代理，否则 127.0.0.1 可能被代理拦截
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# 本机验收必须绕过系统代理，否则 127.0.0.1 可能被代理拦截
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(name)
        print(f"[PASS] {name}")
    else:
        FAILED.append(name)
        print(f"[FAIL] {name} :: {detail}")


def api(method: str, path: str, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(API + path, data=data, method=method, headers=HEADERS)
    with OPENER.open(request, timeout=20) as response:
        body = response.read()
    return json.loads(body) if body else None


def wait_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with OPENER.open(url, timeout=2) as response:
                response.read()
                return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    raise RuntimeError(f"等待 {url} 超时")


def seed() -> dict:
    company = api("POST", "/api/v1/companies", {"name": "浏览器验收公司"})
    connection = api("POST", f"/api/v1/companies/{company['id']}/model-connections", {
        "name": "Mock 连接", "provider": "deepseek",
        "model": "deepseek/deepseek-chat", "api_key_ref": "env:BROWSER_TEST_KEY",
    })
    def position(name: str, **extra) -> dict:
        return api("POST", f"/api/v1/companies/{company['id']}/positions", {"name": name, **extra})

    def employee(name: str, title: str, position_id: str) -> dict:
        return api("POST", f"/api/v1/companies/{company['id']}/employees", {
            "name": name, "title": title, "primary_model_id": connection["id"],
            "positions": [{"position_id": position_id, "is_primary": True}],
        })

    manager = employee("经理甲", "负责人", position("负责人", is_managerial=True, can_review=True)["id"])
    dev = employee("开发乙", "开发工程师", position("开发")["id"])
    qa = employee("测试丙", "测试工程师", position("测试", can_review=True)["id"])
    draft = api("POST", f"/api/v1/companies/{company['id']}/tasks", {
        "title": "浏览器验收-待执行", "objective": "点击执行后完成",
        "assignee_employee_id": dev["id"], "execution_mode": "mock",
    })
    approval = api("POST", f"/api/v1/companies/{company['id']}/tasks", {
        "title": "浏览器验收-待审批", "objective": "需要人工审批",
        "assignee_employee_id": dev["id"], "execution_mode": "mock",
        "approval_required": True,
    })
    multi = api("POST", f"/api/v1/companies/{company['id']}/tasks", {
        "title": "浏览器验收-多Agent", "objective": "三步协作",
        "assignee_employee_id": manager["id"], "execution_mode": "mock",
    })
    api("PUT", f"/api/v1/tasks/{multi['id']}/plan", {"steps": [
        {"id": "s1", "employee_id": dev["id"], "instruction": "第一步"},
        {"id": "s2", "employee_id": qa["id"], "instruction": "第二步", "depends_on": ["s1"]},
        {"id": "s3", "employee_id": manager["id"], "instruction": "第三步", "depends_on": ["s2"]},
    ]})
    slow = api("POST", f"/api/v1/companies/{company['id']}/tasks", {
        "title": "浏览器验收-暂停恢复", "objective": "慢任务",
        "assignee_employee_id": dev["id"], "execution_mode": "mock",
    })
    api("PUT", f"/api/v1/tasks/{slow['id']}/plan", {"steps": [
        {"id": "s1", "employee_id": dev["id"], "instruction": "[slow:1200] 一"},
        {"id": "s2", "employee_id": qa["id"], "instruction": "[slow:1200] 二", "depends_on": ["s1"]},
        {"id": "s3", "employee_id": manager["id"], "instruction": "[slow:1200] 三", "depends_on": ["s2"]},
    ]})
    # ---------------- M3-A 工具执行层 ----------------
    ws_root = ROOT / "data" / "browser_acceptance_ws"
    (ws_root / "notes").mkdir(parents=True, exist_ok=True)
    (ws_root / "notes" / "a.txt").write_text("hello", encoding="utf-8")
    (ws_root / "notes" / "b.txt").write_text("world", encoding="utf-8")
    workspace = api("POST", f"/api/v1/companies/{company['id']}/workspaces", {
        "name": "验收工作区", "root_path": ws_root.as_posix(), "mode": "read_write",
    })
    tool_employee = api("POST", f"/api/v1/companies/{company['id']}/employees", {
        "name": "工具乙", "title": "执行工程师",
        "primary_model_id": connection["id"],
        "tools_allowed": [
            "fs.list_dir", "fs.read_file", "fs.stat", "fs.write_file", "fs.delete_file",
        ],
    })
    api("POST", f"/api/v1/workspaces/{workspace['id']}/grants", {
        "employee_id": tool_employee["id"], "access": "write",
    })
    ws_id = workspace["id"]

    def tool_task(title: str, instruction: str) -> dict:
        return api("POST", f"/api/v1/companies/{company['id']}/tasks", {
            "title": title, "objective": "工具验收", "instruction": instruction,
            "assignee_employee_id": tool_employee["id"], "execution_mode": "mock",
        })

    tool_ok = tool_task(
        "浏览器验收-工具成功",
        f'[tool:fs.list_dir {{"workspace_id":"{ws_id}","path":"notes"}}] 列目录',
    )
    tool_denied = tool_task(
        "浏览器验收-工具拒绝",
        f'[tool:fs.delete_file {{"workspace_id":"{ws_id}","path":"notes/a.txt"}}] 删除文件',
    )
    tool_approve = tool_task(
        "浏览器验收-工具审批",
        f'[tool:fs.write_file {{"workspace_id":"{ws_id}","path":"notes/a.txt",'
        f'"content":"APPROVED","mode":"overwrite"}}] 覆盖文件',
    )
    tool_reject = tool_task(
        "浏览器验收-工具驳回",
        f'[tool:fs.write_file {{"workspace_id":"{ws_id}","path":"notes/b.txt",'
        f'"content":"REJECTED","mode":"overwrite"}}] 覆盖文件',
    )

    return {
        "company": company, "connection": connection,
        "manager": manager, "employee": dev, "qa": qa,
        "draft": draft, "approval": approval, "multi": multi, "slow": slow,
        "workspace": workspace, "tool_employee": tool_employee,
        "tool_ok": tool_ok, "tool_denied": tool_denied,
        "tool_approve": tool_approve, "tool_reject": tool_reject,
    }


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0
        self.exceptions: list[str] = []

    @classmethod
    async def connect(cls, ws_url: str) -> "CDP":
        ws = await websockets.connect(ws_url, max_size=40 * 1024 * 1024)
        return cls(ws)

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        current = self._id
        await self.ws.send(json.dumps({"id": current, "method": method, "params": params or {}}))
        while True:
            message = json.loads(await self.ws.recv())
            if message.get("id") == current:
                if "error" in message:
                    raise RuntimeError(f"CDP {method} 失败：{message['error']}")
                return message.get("result", {})
            if message.get("method") == "Runtime.exceptionThrown":
                detail = message.get("params", {}).get("exceptionDetails", {})
                self.exceptions.append(str(detail.get("text") or detail.get("exception", {})))

    async def eval(self, expression: str):
        result = await self.send("Runtime.evaluate", {
            "expression": expression, "returnByValue": True, "awaitPromise": True,
        })
        if "exceptionDetails" in result:
            raise RuntimeError(f"JS 执行失败：{result['exceptionDetails']}")
        return result.get("result", {}).get("value")

    async def goto(self, url: str) -> None:
        await self.send("Page.navigate", {"url": url})
        await self.wait("document.readyState === 'complete'", 20, f"加载 {url}")

    async def wait(self, expression: str, timeout: float, desc: str) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if await self.eval(expression):
                    return
            except RuntimeError:
                pass
            await asyncio.sleep(0.2)
        raise AssertionError(f"等待超时：{desc}")

    async def text(self) -> str:
        return await self.eval("document.body ? document.body.innerText : ''") or ""

    async def wait_text(self, needle: str, timeout: float = 20) -> None:
        await self.wait(
            f"document.body && document.body.innerText.includes({json.dumps(needle)})",
            timeout, f"页面出现文本 {needle}",
        )

    async def click(self, label: str) -> None:
        js = (
            "(() => { const target = [...document.querySelectorAll('button,a')]"
            f".find(el => el.textContent.trim() === {json.dumps(label)});"
            " if (!target) return false; target.click(); return true; })()"
        )
        if not await self.eval(js):
            raise AssertionError(f"找不到可点击元素：{label}")

    async def set_field(self, label_text: str, value: str) -> None:
        js = f"""(() => {{
          const label = [...document.querySelectorAll('label')]
            .find(el => el.textContent.includes({json.dumps(label_text)}));
          if (!label) return 'label-not-found';
          const el = label.querySelector('input,textarea,select');
          if (!el) return 'field-not-found';
          const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype
            : el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, {json.dumps(value)});
          el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', {{bubbles: true}}));
          return 'ok';
        }})()"""
        result = await self.eval(js)
        if result != "ok":
            raise AssertionError(f"填写字段失败 {label_text}: {result}")

    async def select_text(self, label_text: str, option_text: str) -> None:
        js = f"""(() => {{
          const label = [...document.querySelectorAll('label')]
            .find(el => el.textContent.includes({json.dumps(label_text)}));
          if (!label) return 'label-not-found';
          const el = label.querySelector('select');
          if (!el) return 'select-not-found';
          const option = [...el.options].find(item => item.textContent.includes({json.dumps(option_text)}));
          if (!option) return 'option-not-found';
          Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(el, option.value);
          el.dispatchEvent(new Event('change', {{bubbles: true}}));
          return 'ok';
        }})()"""
        result = await self.eval(js)
        if result != "ok":
            raise AssertionError(f"选择失败 {label_text}={option_text}: {result}")

    async def set_placeholder(self, placeholder_prefix: str, value: str) -> None:
        js = f"""(() => {{
          const el = document.querySelector('input[placeholder^={json.dumps(placeholder_prefix)}]');
          if (!el) return 'not-found';
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, {json.dumps(value)});
          el.dispatchEvent(new Event('input', {{bubbles: true}}));
          return 'ok';
        }})()"""
        result = await self.eval(js)
        if result != "ok":
            raise AssertionError(f"填写输入框失败 {placeholder_prefix}: {result}")

    async def click_selector(self, selector: str) -> None:
        js = (
            f"(() => {{ const el = document.querySelector({json.dumps(selector)});"
            " if (!el) return false; el.click(); return true; })()"
        )
        if not await self.eval(js):
            raise AssertionError(f"找不到元素：{selector}")

    async def set_selector(self, selector: str, value: str) -> None:
        js = f"""(() => {{
          const el = document.querySelector({json.dumps(selector)});
          if (!el) return 'missing';
          const proto = el.tagName === 'TEXTAREA'
            ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
          setter.call(el, {json.dumps(value)});
          el.dispatchEvent(new Event('input', {{ bubbles: true }}));
          return 'ok';
        }})()"""
        if await self.eval(js) != "ok":
            raise AssertionError(f"设置输入失败：{selector}")

    async def set_select(self, selector: str, value: str) -> None:
        js = f"""(() => {{
          const el = document.querySelector({json.dumps(selector)});
          if (!el) return 'missing';
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLSelectElement.prototype, 'value').set;
          setter.call(el, {json.dumps(value)});
          el.dispatchEvent(new Event('change', {{ bubbles: true }}));
          return 'ok';
        }})()"""
        if await self.eval(js) != "ok":
            raise AssertionError(f"设置下拉失败：{selector}")

    async def wait_selector(self, selector: str, timeout: float, desc: str) -> None:
        await self.wait(
            f"Boolean(document.querySelector({json.dumps(selector)}))", timeout, desc
        )

    async def screenshot(self, name: str) -> str:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        data = await self.send("Page.captureScreenshot", {"format": "png"})
        path = SHOT_DIR / f"{name}.png"
        path.write_bytes(base64.b64decode(data["data"]))
        return str(path)


async def run_checks(cdp: CDP, ctx: dict) -> None:
    # 1. 任务列表渲染
    await cdp.goto(f"{WEB}/tasks")
    await cdp.wait_text("浏览器验收-待执行")
    check("B1 任务列表真实渲染", "浏览器验收-待执行" in await cdp.text())
    await cdp.screenshot("02_tasks")

    # 2. 浏览器创建任务
    await cdp.click("新建任务")
    await cdp.wait_text("执行员工")
    await cdp.set_field("标题", "浏览器验收-UI创建")
    await cdp.set_field("目标 / 指令", "由浏览器表单创建")
    await cdp.select_text("执行员工", "开发乙")
    await cdp.click("创建")
    await cdp.wait_text("浏览器验收-UI创建", timeout=20)
    check("B2 浏览器表单创建任务", "已创建" in await cdp.text())
    await cdp.screenshot("03_task_created")

    # 3. 打开任务详情并点击执行
    await cdp.goto(f"{WEB}/tasks/{ctx['draft']['id']}")
    await cdp.wait_text("执行计划")
    check("B3 任务详情页渲染", "待执行" in await cdp.text() or "草稿" in await cdp.text())
    await cdp.click("执行")
    await cdp.wait_text("已完成", timeout=30)
    check("B4 浏览器点击执行并完成", "已完成" in await cdp.text())
    await cdp.screenshot("04_task_succeeded")

    # 4. 审批流程
    await cdp.goto(f"{WEB}/tasks/{ctx['approval']['id']}")
    await cdp.wait_text("执行计划")
    await cdp.click("执行")
    # 任务标题本身含“待审批”，必须等真正的审批卡片出现，否则会误判
    await cdp.wait_text("关卡：", timeout=30)
    check("B5 执行后停在待审批", "关卡：执行前" in await cdp.text())
    # B5.5：审批中心页（同一待审批在全局视图可见，且显示任务标题与关卡）
    await cdp.goto(f"{WEB}/approvals")
    await cdp.wait_text("审批中心", timeout=15)
    # 用单次原子 eval 断言（两次 eval 之间撞上 React 重渲染会读到只有 header 的中间态）
    # SPA 断言必须轮询重试（React 首次提交 + 数据加载存在渲染中间态，单次 eval 会撞上）
    deadline = time.time() + 15
    ok_b55 = False
    b55_text = ""
    while time.time() < deadline:
        probe = json.loads(await cdp.eval(
            "JSON.stringify({"
            # 审批中心的闸门列显示"执行前"（任务详情页才是"关卡：执行前"）
            "gate: document.body.innerText.includes('执行前') && document.body.innerText.includes('工具调用类审批'),"
            "titleHit: document.body.innerText.includes("
            + json.dumps(ctx["approval"]["title"]) + "),"
            "text: document.body.innerText.slice(0, 300)"
            "})"
        ))
        ok_b55 = probe["gate"] and probe["titleHit"]
        b55_text = probe["text"]
        if ok_b55:
            break
        await asyncio.sleep(0.5)
    check(
        "B5.5 审批中心聚合显示待审批与任务标题",
        ok_b55,
        b55_text,
    )
    await cdp.screenshot("05b_approvals_center")

    await cdp.goto(f"{WEB}/tasks/{ctx['approval']['id']}")
    await cdp.wait_text("关卡：", timeout=15)
    await cdp.set_placeholder("审批意见", "浏览器验收通过")
    await cdp.click("批准")
    await cdp.wait_text("已完成", timeout=30)
    check("B6 浏览器批准并完成", "已完成" in await cdp.text())
    await cdp.screenshot("05_approval_approved")

    # 5. 多 Agent 协作（三步计划，真实点击执行）
    await cdp.goto(f"{WEB}/tasks/{ctx['multi']['id']}")
    await cdp.wait_text("执行计划")
    await cdp.click("执行")
    await cdp.wait_text("已完成", timeout=40)
    multi_text = await cdp.text()
    check("B7 多 Agent 浏览器执行与交接",
          "子任务" in multi_text and "agent.handoff" in multi_text,
          multi_text[:200])
    await cdp.screenshot("06_multi_agent")

    # 6. 暂停 / 恢复（慢步骤，留出暂停窗口）
    await cdp.goto(f"{WEB}/tasks/{ctx['slow']['id']}")
    await cdp.wait_text("执行计划")
    await cdp.click("执行")
    await cdp.wait(
        "[...document.querySelectorAll('button')]"
        ".some(b => b.textContent.trim() === '暂停' && !b.disabled)",
        20, "暂停按钮可用",
    )
    await cdp.click("暂停")
    await cdp.wait_text("已暂停", timeout=30)
    check("B8 浏览器暂停任务", "已暂停" in await cdp.text())
    await cdp.screenshot("07_paused")
    await cdp.click("恢复")
    await cdp.wait_text("已完成", timeout=40)
    check("B9 浏览器恢复并完成", "已完成" in await cdp.text())
    await cdp.screenshot("08_resumed")

    # 7. 模型连接页
    await cdp.goto(f"{WEB}/settings/models")
    await cdp.wait_text("Mock 连接")
    models_text = await cdp.text()
    check("B10 模型连接页渲染", "env:BROWSER_TEST_KEY" in models_text and "凭据可用" in models_text)
    await cdp.screenshot("09_models")

    # 8. 员工详情（权限 + 提示词）
    await cdp.goto(f"{WEB}/employees/{ctx['employee']['id']}")
    await cdp.wait_text("有效权限")
    check("B11 员工详情权限与提示词区块", "提示词版本" in await cdp.text())
    await cdp.screenshot("10_employee_detail")

    # 9. 组织设置：浏览器创建部门
    await cdp.goto(f"{WEB}/settings/organization")
    await cdp.wait_text("添加部门")
    await cdp.set_placeholder("部门名称", "浏览器验收部门")
    await cdp.click("添加部门")
    await cdp.wait_text("浏览器验收部门", timeout=20)
    check("B12 组织设置创建部门", "浏览器验收部门" in await cdp.text())
    await cdp.screenshot("11_org_settings")

    # 10. 监控页
    await cdp.goto(f"{WEB}/monitor")
    await cdp.wait_text("今日成本")
    monitor_text = await cdp.text()
    check("B13 监控页显示成本与状态",
          "任务总数" in monitor_text and "今日成本" in monitor_text
          and "最近 Agent 执行" in monitor_text)
    await cdp.screenshot("12_monitor")

    # 11. 员工页
    await cdp.goto(f"{WEB}/employees")
    await cdp.wait_text("开发乙")
    check("B14 员工页渲染", "开发乙" in await cdp.text())
    await cdp.screenshot("13_employees")

    # 12. 组织图：公司 + 部门 + 员工三个节点
    await cdp.goto(f"{WEB}/org")
    await cdp.wait(
        "[...document.querySelectorAll('.react-flow__node')]"
        ".some(node => node.innerText.includes('浏览器验收公司'))",
        20, "组织图出现公司节点",
    )
    node_count = await cdp.eval("document.querySelectorAll('.react-flow__node').length")
    org_text = await cdp.text()
    check("B15 组织图渲染公司/部门/员工",
          int(node_count or 0) >= 3 and "浏览器验收部门" in org_text,
          f"节点数 {node_count}")
    await cdp.screenshot("14_org")



    # ---------------- M3-A：工具执行层 ----------------
    await cdp.goto(f"{WEB}/settings/workspaces")
    await cdp.wait_text("验收工作区", 20)
    ws_text = await cdp.text()
    check(
        "M3-1 工作区页渲染（含根路径）",
        "验收工作区" in ws_text and "browser_acceptance_ws" in ws_text,
    )
    await cdp.screenshot("m3_01_workspaces")

    await cdp.set_selector('[data-testid="ws-name"]', "浏览器新建工作区")
    await cdp.click_selector('[data-testid="ws-create"]')
    await cdp.wait_text("浏览器新建工作区", 20)
    check("M3-2 浏览器创建新工作区", "浏览器新建工作区" in await cdp.text())

    created = [
        item for item in api("GET", f"/api/v1/companies/{ctx['company']['id']}/workspaces")
        if item["name"] == "浏览器新建工作区"
    ]
    assert created, "新建的工作区未出现在 API 列表"
    created_id = created[0]["id"]
    await cdp.set_select(
        f'[data-testid="ws-grant-employee-{created_id}"]', ctx["tool_employee"]["id"]
    )
    await cdp.set_select(f'[data-testid="ws-grant-access-{created_id}"]', "write")
    await cdp.click_selector(f'[data-testid="ws-grant-submit-{created_id}"]')
    await cdp.wait_text("授权已保存", 20)
    check("M3-3 浏览器授权员工（读写）", "工具乙" in await cdp.text())
    await cdp.screenshot("m3_02_workspace_grant")

    await cdp.click_selector(
        f'[data-testid="ws-revoke-{created_id}-{ctx["tool_employee"]["id"]}"]'
    )
    await cdp.wait_text("授权已撤销（立即生效）", 20)
    check("M3-4 浏览器撤销授权", "授权已撤销" in await cdp.text())

    await cdp.goto(f"{WEB}/settings/tools")
    await cdp.wait_text("工具策略")
    policy_text = await cdp.text()
    check(
        "M3-5 工具策略页与工具列表",
        "fs.read_file" in policy_text and "http.request" in policy_text
        and "工具白名单" in policy_text,
    )
    check(
        "M3-6 Shell 永久禁用说明",
        "永久禁用" in policy_text and "shell.run" in policy_text,
    )
    await cdp.screenshot("m3_03_tool_policy")

    # 成功调用
    await cdp.goto(f"{WEB}/tasks/{ctx['tool_ok']['id']}")
    await cdp.wait_text("工具调用")
    await cdp.click("执行")
    await cdp.wait_text("已完成", 30)
    ok_text = await cdp.text()
    ok_calls = api("GET", f"/api/v1/tasks/{ctx['tool_ok']['id']}/tool-calls")
    check(
        "M3-7 工具调用面板显示成功记录",
        "fs.list_dir" in ok_text and "succeeded" in ok_text
        and ok_calls["items"] and ok_calls["items"][0]["status"] == "succeeded",
        str(ok_calls["items"])[:200],
    )
    check("M3-8 时间线包含工具事件", "tool.succeeded" in ok_text)
    await cdp.screenshot("m3_04_tool_call_panel")

    await cdp.goto(f"{WEB}/tasks/{ctx['tool_ok']['id']}")
    await cdp.wait_text("fs.list_dir", 20)
    check("M3-9 刷新后工具记录仍存在", "fs.list_dir" in await cdp.text())

    # 拒绝记录
    await cdp.goto(f"{WEB}/tasks/{ctx['tool_denied']['id']}")
    await cdp.wait_text("工具调用")
    await cdp.click("执行")
    await cdp.wait_text("已完成", 30)
    denied_text = await cdp.text()
    denied_calls = api("GET", f"/api/v1/tasks/{ctx['tool_denied']['id']}/tool-calls")
    check(
        "M3-10 被拒绝的工具调用同样展示",
        "TOOL_NOT_GRANTED" in denied_text and "denied" in denied_text
        and denied_calls["items"] and denied_calls["items"][0]["status"] == "denied",
        str(denied_calls["items"])[:200],
    )
    await cdp.screenshot("m3_05_tool_denied")

    # 审批 → 批准
    await cdp.goto(f"{WEB}/tasks/{ctx['tool_approve']['id']}")
    await cdp.wait_text("执行计划")
    await cdp.click("执行")
    await cdp.wait_text("批准调用", 30)
    check("M3-11 工具调用进入待审批", "批准调用" in await cdp.text())
    await cdp.screenshot("m3_06_tool_approval")
    await cdp.click("批准调用")
    await cdp.wait_text("已完成", 30)
    check("M3-12 批准后恢复并完成", "已完成" in await cdp.text())
    await cdp.screenshot("m3_07_tool_approved")

    # 驳回
    await cdp.goto(f"{WEB}/tasks/{ctx['tool_reject']['id']}")
    await cdp.wait_text("执行计划")
    await cdp.click("执行")
    await cdp.wait_text("驳回调用", 30)
    await cdp.click("驳回调用")
    await cdp.wait_text("失败", 30)
    check(
        "M3-13 驳回工具调用后任务失败",
        "TOOL_APPROVAL_REJECTED" in await cdp.text(),
    )
    await cdp.screenshot("m3_08_tool_rejected")


def find_edge() -> Path:
    for path in EDGE_CANDIDATES:
        if path.exists():
            return path
    raise RuntimeError("未找到 Microsoft Edge，无法执行浏览器验收（未安装其他浏览器工具）")


def launch_edge(profile: Path) -> subprocess.Popen:
    edge = find_edge()
    shutil.rmtree(profile, ignore_errors=True)
    return subprocess.Popen([
        str(edge), "--headless=new", f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
        "--disable-extensions", "--disable-gpu", "--window-size=1440,900",
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def new_target() -> dict:
    url = f"http://127.0.0.1:{DEBUG_PORT}/json/new?url=about:blank"
    for method in ("PUT", "GET"):
        try:
            request = urllib.request.Request(url, method=method)
            with OPENER.open(request, timeout=10) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError:
            continue
    raise RuntimeError("无法创建 Edge 调试目标")


def main() -> int:
    for path in (DB_PATH, Path(f"{DB_PATH}-wal"), Path(f"{DB_PATH}-shm")):
        if path.exists():
            path.unlink()
    shutil.rmtree(PROMPTS_DIR, ignore_errors=True)
    shutil.rmtree(ROOT / "data" / "browser_acceptance_ws", ignore_errors=True)
    shutil.rmtree(SHOT_DIR, ignore_errors=True)
    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "AGENTOS_DB_URL": f"sqlite:///{DB_PATH.as_posix()}",
        "AGENTOS_PROMPTS_ROOT": PROMPTS_DIR.as_posix(),
        "AGENTOS_MODEL_MODE": "mock",
        "BROWSER_TEST_KEY": "browser-secret",
        "AGENTOS_TOOL_EXECUTION": "on",
    })
    api_proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "run_api.py"), "--port", "8000"],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    web_proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve_web.py"), "--port", "5173"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    edge_proc = None
    try:
        wait_http(f"{API}/api/health")
        wait_http(f"{WEB}/")
        ctx = seed()
        edge_proc = launch_edge(ROOT / "data" / "edge_profile_browser_acceptance")
        wait_http(f"http://127.0.0.1:{DEBUG_PORT}/json/version")
        target = new_target()
        cdp = asyncio.run(_drive(target["webSocketDebuggerUrl"], ctx))
        if cdp.exceptions:
            check("B16 无未捕获 JS 异常", False, "; ".join(cdp.exceptions[:5]))
        else:
            check("B16 无未捕获 JS 异常", True)
    finally:
        for proc in (edge_proc, web_proc, api_proc):
            if proc is not None:
                proc.kill()
                proc.wait(timeout=10)
        shutil.rmtree(ROOT / "data" / "edge_profile_browser_acceptance", ignore_errors=True)

    print(f"\n浏览器验收完成：{len(PASSED)} 项通过，{len(FAILED)} 项失败")
    for name in PASSED:
        print(f"  - {name}")
    for name in FAILED:
        print(f"  ! {name}")

    report = ROOT / "docs" / "testing" / "m3_browser_acceptance.txt"
    lines = [
        "AgentOS M3 浏览器验收（Microsoft Edge headless + CDP，未安装新工具）",
        f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "覆盖：任务中心全链路（创建/执行/审批/多Agent/暂停恢复/监控/组织图）",
        "M3-A：工作区创建/授权/撤销、工具策略与 Shell 禁用、工具调用面板、"
        "拒绝记录、工具审批批准与驳回、时间线、刷新持久化",
        f"结果：{len(PASSED)} 项通过，{len(FAILED)} 项失败",
        "",
    ]
    lines += [f"[PASS] {name}" for name in PASSED]
    lines += [f"[FAIL] {name}" for name in FAILED]
    lines += ["", "截图：docs/testing/m3_browser/"]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"证据已写入：{report}")
    return 0 if not FAILED else 1


async def _drive(ws_url: str, ctx: dict) -> CDP:
    cdp = await CDP.connect(ws_url)
    await cdp.send("Page.enable")
    await cdp.send("Runtime.enable")
    await run_checks(cdp, ctx)
    await cdp.ws.close()
    return cdp


if __name__ == "__main__":
    raise SystemExit(main())
