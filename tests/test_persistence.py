"""持久化测试：多执行记录不覆盖、重启保留、失败记录 error（使用临时库，无网络）。"""
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from packages.persistence.models import Base, Task, TaskRun


def _session_factory(tmp_path):
    url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(url, future=True)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)


def test_multiple_runs_not_overwritten(tmp_path):
    engine, sf = _session_factory(tmp_path)
    with sf() as s:
        t = Task(id="t1", title="x", state="done")
        s.add(t)
        s.flush()
        s.add(TaskRun(id="r1", task_id="t1", run_no=1, state="failed", error="第一次失败"))
        s.add(TaskRun(id="r2", task_id="t1", run_no=2, state="succeeded"))
        s.commit()
    with sf() as s:
        runs = s.execute(select(TaskRun).where(TaskRun.task_id == "t1")).scalars().all()
    assert len(runs) == 2
    assert runs[0].error == "第一次失败"  # 历史失败记录未被成功重跑覆盖
    engine.dispose()


def test_restart_keeps_records(tmp_path):
    engine, sf = _session_factory(tmp_path)
    with sf() as s:
        s.add(Task(id="t-restart", title="重启保留", state="review_passed"))
        s.commit()
    engine.dispose()

    # 全新引擎模拟进程重启
    url = f"sqlite:///{tmp_path}/test.db"
    engine2 = create_engine(url, future=True)
    sf2 = sessionmaker(bind=engine2, future=True)
    with sf2() as s:
        row = s.execute(select(Task).where(Task.id == "t-restart")).scalar_one_or_none()
    assert row is not None
    assert row.state == "review_passed"
    engine2.dispose()
