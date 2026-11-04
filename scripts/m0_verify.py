"""AgentOS M0 最小技术验证脚本。

运行：python scripts/m0_verify.py
产出：docs/testing/m0_results.json（机器可读）+ 终端摘要
原则：只报告真实执行结果；缺前置条件标 BLOCKED，失败标 FAIL，绝不伪造。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

RESULTS: list[dict] = []


def record(vid: str, name: str, status: str, detail: str = "", evidence: dict | None = None) -> None:
    RESULTS.append({
        "id": vid, "name": name, "status": status,  # PASS / FAIL / SKIP / BLOCKED
        "detail": detail[:2000], "evidence": evidence or {},
    })
    print(f"[{status:>7}] {vid} {name} — {detail[:120]}")


def v1_deepseek() -> None:
    """V1: LiteLLM → DeepSeek 真实调用（返回内容 + token + 费用）。"""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        record("V1", "LiteLLM 调用 DeepSeek", "BLOCKED", "缺少 DEEPSEEK_API_KEY（.env 未配置）")
        return
    from packages.model_gateway import chat

    async def _run():
        return await chat(
            "deepseek/deepseek-chat",
            [{"role": "user", "content": "用一句中文回答：1+1 等于几？"}],
            timeout=30.0, max_tokens=64,
        )

    try:
        resp = asyncio.run(_run())
        ok = bool(resp.content.strip())
        record(
            "V1", "LiteLLM 调用 DeepSeek", "PASS" if ok else "FAIL",
            f"内容={resp.content.strip()[:50]!r} tokens={resp.usage.prompt_tokens}+{resp.usage.completion_tokens} "
            f"cost={resp.usage.cost_usd} latency={resp.usage.latency_ms}ms",
            evidence={"content": resp.content[:200], "usage": resp.usage.to_dict()},
        )
    except Exception as exc:
        record("V1", "LiteLLM 调用 DeepSeek", "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}")


def v2_second_provider() -> None:
    """V2: 第二个供应商真实调用。"""
    candidates = [
        ("OPENAI_API_KEY", "openai/gpt-4o-mini"),
        ("ANTHROPIC_API_KEY", "anthropic/claude-haiku-4-5"),
        ("GOOGLE_API_KEY", "gemini/gemini-2.0-flash"),
        ("OPENROUTER_API_KEY", "openrouter/deepseek/deepseek-chat"),
    ]
    available = [(env, model) for env, model in candidates if os.environ.get(env)]
    if not available:
        record("V2", "第二供应商调用", "SKIP",
               "未配置第二供应商 Key（OPENAI/ANTHROPIC/GOOGLE/OPENROUTER 均为空）——如实标记，不计失败")
        return
    from packages.model_gateway import chat
    env, model = available[0]

    async def _run():
        return await chat(model, [{"role": "user", "content": "Reply with one word: ok"}],
                          timeout=30.0, max_tokens=16)

    try:
        resp = asyncio.run(_run())
        record("V2", f"第二供应商调用（{model}，{env}）", "PASS" if resp.content.strip() else "FAIL",
               f"内容={resp.content.strip()[:50]!r}", evidence={"usage": resp.usage.to_dict()})
    except Exception as exc:
        record("V2", f"第二供应商调用（{model}）", "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}")


def v3_adapter_interface() -> None:
    """V3: AgentAdapter 接口落地 + 能力声明诚实性。"""
    from packages.agent_core import LiteLLMAdapter
    from packages.agent_core.adapter import CapabilityNotSupported

    adapter = LiteLLMAdapter(model="deepseek/deepseek-chat")
    caps = adapter.get_capabilities().to_dict()
    checks = {
        "caps_complete": len(caps) == 8,
        "file_ops_honest": caps["file_ops"] is False,
        "approval_hook_honest": caps["approval_hook"] is False,
    }

    async def _interrupt_raises() -> bool:
        from packages.shared.types import ExecutionHandle
        try:
            await adapter.interrupt(ExecutionHandle(), "test")
            return False
        except CapabilityNotSupported:
            return True

    try:
        checks["interrupt_raises"] = asyncio.run(_interrupt_raises())
    except Exception:
        checks["interrupt_raises"] = False
    ok = all(checks.values())
    record("V3", "AgentAdapter 接口与能力声明", "PASS" if ok else "FAIL",
           f"checks={checks}", evidence=checks)


def v4_sequential_handoff() -> None:
    """V4: 双员工（研究员→审查员）顺序协作，真实交接。"""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        record("V4", "双 Agent 顺序协作", "BLOCKED", "缺少 DEEPSEEK_API_KEY")
        return
    from packages.agent_core import LiteLLMAdapter
    from packages.persistence import get_session, init_db
    from packages.workflow_engine import EmployeeSpec, run_sequential_handoff

    init_db()
    researcher = EmployeeSpec(
        key="m0-researcher", role="研究员", goal="对目标做事实性简明分析",
        backstory="严谨，只说有据可查的内容", adapter=LiteLLMAdapter("deepseek/deepseek-chat"),
    )
    reviewer = EmployeeSpec(
        key="m0-reviewer", role="独立审查员", goal="发现分析中的事实与逻辑风险",
        backstory="挑剔但公正，不接受含糊结论", adapter=LiteLLMAdapter("deepseek/deepseek-chat"),
    )
    try:
        with get_session() as session:
            result = asyncio.run(run_sequential_handoff(
                session, researcher, reviewer,
                "用 LangGraph 作为多 Agent 系统的任务调度内核有哪些主要优势？",
            ))
        evidence = {
            "task_id": result.get("task_id"),
            "task_state": result.get("task_state"),
            "review_parsed": result.get("review_parsed"),
            "research_preview": (result.get("research_output") or "")[:300],
            "review_preview": (result.get("review_output") or "")[:300],
        }
        ok = result["ok"] and result["review_parsed"].get("conclusion") in ("pass", "reject", "unknown")
        record("V4", "双 Agent 顺序协作", "PASS" if ok else "FAIL",
               f"task_state={result.get('task_state')} review={result.get('review_parsed', {}).get('conclusion')}",
               evidence=evidence)
    except Exception as exc:
        record("V4", "双 Agent 顺序协作", "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}",
               evidence={"traceback": traceback.format_exc()[-1000:]})


def v5_langgraph_interrupt() -> None:
    """V5: LangGraph interrupt 审批暂停/恢复 + SqliteSaver 持久化。"""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        from packages.workflow_engine.approval_graph import (
            resume_with_decision,
            start_and_wait_approval,
        )
    except ImportError as exc:
        record("V5", "LangGraph interrupt 审批", "FAIL", f"导入失败：{exc}")
        return

    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    ckpt_path = str(ROOT / "data" / "m0_lg_checkpoints.db")
    try:
        with SqliteSaver.from_conn_string(ckpt_path) as ckpt:
            suspended = start_and_wait_approval(ckpt, "m0-thread-1", "删除文件 data/tmp.txt", "high")
            interrupted = "__interrupt__" in suspended
            resumed = resume_with_decision(ckpt, "m0-thread-1", approved=False)
            ok = interrupted and resumed.get("result") == "rejected" and resumed.get("decided_by") == "user"
            record("V5", "LangGraph interrupt 审批", "PASS" if ok else "FAIL",
                   f"挂起={interrupted} 恢复后 result={resumed.get('result')} decided_by={resumed.get('decided_by')}",
                   evidence={"suspended": {k: str(v)[:200] for k, v in suspended.items()},
                             "resumed": {k: str(v)[:200] for k, v in resumed.items()}})
    except Exception as exc:
        record("V5", "LangGraph interrupt 审批", "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}",
               evidence={"traceback": traceback.format_exc()[-1000:]})


def v6_persistence_restart() -> None:
    """V6: 执行记录持久化——写库、关闭引擎、重开引擎、记录仍在；失败任务有 error。"""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from packages.persistence.db import DEFAULT_DB_URL, make_engine
    from packages.persistence.models import Base, Task, TaskRun
    from packages.shared.types import new_id

    url = os.environ.get("AGENTOS_DB_URL") or DEFAULT_DB_URL
    db_path = url.replace("sqlite:///", "")
    try:
        engine1 = make_engine(url)
        Base.metadata.create_all(engine1)
        marker_id = new_id()
        sf1 = sessionmaker(bind=engine1, expire_on_commit=False, future=True)
        with sf1() as s1:
            t = Task(id=marker_id, title="M0-V6 持久化标记任务", state="failed")
            s1.add(t)
            s1.flush()
            s1.add(TaskRun(id=new_id(), task_id=marker_id, run_no=1, state="failed",
                           error="V6 故意写入的失败样例"))
            s1.commit()
        engine1.dispose()

        # 模拟"重启"：全新引擎与会话
        engine2 = create_engine(url, future=True)
        sf2 = sessionmaker(bind=engine2, future=True)
        with sf2() as s2:
            row = s2.execute(select(Task).where(Task.id == marker_id)).scalar_one_or_none()
            runs = s2.execute(select(TaskRun).where(TaskRun.task_id == marker_id)).scalars().all()
        ok = row is not None and len(runs) == 1 and runs[0].error
        err = runs[0].error if runs else None
        record("V6", "持久化与重启保留", "PASS" if ok else "FAIL",
               f"重开后任务存在={row is not None} 失败记录数={len(runs)} error={err!r} db={db_path}")
        engine2.dispose()
    except Exception as exc:
        record("V6", "持久化与重启保留", "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}")


def v7_codex_cli() -> None:
    """V7: Codex CLI headless（需用户预先安装并认证）。"""
    codex = shutil.which("codex")
    if not codex:
        record("V7", "Codex CLI headless", "BLOCKED",
               "未检测到 codex 可执行文件。需用户授权安装（npm i -g @openai/codex）并完成 ChatGPT/API 认证")
        return
    try:
        proc = subprocess.run(
            [codex, "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check",
             "用一句中文回答：1+1 等于几？不要操作任何文件。"],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT / "data"),
        )
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        events = []
        for ln in lines:
            try:
                events.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
        ok = proc.returncode == 0 and len(events) > 0
        record("V7", "Codex CLI headless", "PASS" if ok else "FAIL",
               f"returncode={proc.returncode} JSONL事件数={len(events)}",
               evidence={"event_types": [e.get("type") for e in events][:20],
                         "stderr_tail": proc.stderr[-300:]})
    except subprocess.TimeoutExpired:
        record("V7", "Codex CLI headless", "FAIL", "120s 超时")
    except Exception as exc:
        record("V7", "Codex CLI headless", "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}")


def v8_crewai_comparison() -> None:
    """V8: CrewAI 对照实验（安装失败或缺 Key 则 SKIP/BLOCKED，不影响主体验证）。"""
    try:
        import crewai  # noqa: F401
    except ImportError:
        record("V8", "CrewAI 对照实验", "SKIP", "crewai 未安装（requirements-experiments.txt 可选依赖）")
        return
    if not os.environ.get("DEEPSEEK_API_KEY"):
        record("V8", "CrewAI 对照实验", "BLOCKED", "缺少 DEEPSEEK_API_KEY")
        return
    record("V8", "CrewAI 对照实验", "SKIP", "crewai 已安装；对照实验待 M0 收尾时按需执行（避免重复烧 Token）")


def main() -> int:
    started = time.time()
    print(f"AgentOS M0 验证开始 python={sys.version.split()[0]} cwd={ROOT}\n")
    v1_deepseek()
    v2_second_provider()
    v3_adapter_interface()
    v4_sequential_handoff()
    v5_langgraph_interrupt()
    v6_persistence_restart()
    v7_codex_cli()
    v8_crewai_comparison()

    summary = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        "duration_s": round(time.time() - started, 1),
        "python": sys.version.split()[0],
        "results": RESULTS,
        "counts": {
            s: sum(1 for r in RESULTS if r["status"] == s)
            for s in ("PASS", "FAIL", "SKIP", "BLOCKED")
        },
    }
    out = ROOT / "docs" / "testing" / "m0_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果写入 {out}\n统计：{summary['counts']}")
    return 0 if summary["counts"]["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
