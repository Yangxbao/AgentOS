"""M3-0 浏览器验收：用本机已安装的 Microsoft Edge（headless + CDP）真实渲染并点击。

不安装 Playwright / 任何新依赖；只用标准库 + 已安装的 websockets。
覆盖：任务列表渲染、浏览器创建任务、执行、审批通过、监控、员工页。

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
    position = api("POST", f"/api/v1/companies/{company['id']}/positions", {
        "name": "开发", "can_review": True,
    })
    employee = api("POST", f"/api/v1/companies/{company['id']}/employees", {
        "name": "开发乙", "title": "开发工程师", "primary_model_id": connection["id"],
        "positions": [{"position_id": position["id"], "is_primary": True}],
    })
    draft = api("POST", f"/api/v1/companies/{company['id']}/tasks", {
        "title": "浏览器验收-待执行", "objective": "点击执行后完成",
        "assignee_employee_id": employee["id"], "execution_mode": "mock",
    })
    approval = api("POST", f"/api/v1/companies/{company['id']}/tasks", {
        "title": "浏览器验收-待审批", "objective": "需要人工审批",
        "assignee_employee_id": employee["id"], "execution_mode": "mock",
        "approval_required": True,
    })
    return {
        "company": company, "employee": employee,
        "draft": draft, "approval": approval,
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
    await cdp.set_placeholder("审批意见", "浏览器验收通过")
    await cdp.click("批准")
    await cdp.wait_text("已完成", timeout=30)
    check("B6 浏览器批准并完成", "已完成" in await cdp.text())
    await cdp.screenshot("05_approval_approved")

    # 5. 监控页
    await cdp.goto(f"{WEB}/monitor")
    await cdp.wait_text("今日成本")
    monitor_text = await cdp.text()
    check("B7 监控页显示成本与状态",
          "任务总数" in monitor_text and "今日成本" in monitor_text
          and "最近 Agent 执行" in monitor_text)
    await cdp.screenshot("06_monitor")

    # 6. 员工页
    await cdp.goto(f"{WEB}/employees")
    await cdp.wait_text("开发乙")
    check("B8 员工页渲染", "开发乙" in await cdp.text())
    await cdp.screenshot("07_employees")

    # 7. 组织页：必须检查画布节点，不能只看下拉框文字
    await cdp.goto(f"{WEB}/org")
    await cdp.wait(
        "[...document.querySelectorAll('.react-flow__node')]"
        ".some(node => node.innerText.includes('浏览器验收公司'))",
        20, "组织图出现公司节点",
    )
    node_count = await cdp.eval("document.querySelectorAll('.react-flow__node').length")
    check("B9 组织图渲染公司节点与员工节点", int(node_count or 0) >= 2, f"节点数 {node_count}")
    await cdp.screenshot("08_org")


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
    shutil.rmtree(SHOT_DIR, ignore_errors=True)
    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update({
        "AGENTOS_DB_URL": f"sqlite:///{DB_PATH.as_posix()}",
        "AGENTOS_PROMPTS_ROOT": PROMPTS_DIR.as_posix(),
        "AGENTOS_MODEL_MODE": "mock",
        "BROWSER_TEST_KEY": "browser-secret",
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
            check("B10 无未捕获 JS 异常", False, "; ".join(cdp.exceptions[:5]))
        else:
            check("B10 无未捕获 JS 异常", True)
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
