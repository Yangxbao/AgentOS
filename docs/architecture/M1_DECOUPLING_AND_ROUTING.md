# 员工-模型解耦 与 组织驱动任务分配

> v1.0（待确认）｜2026-11-05｜本文回答两个问题：
> ① 员工如何与模型彻底解耦？② 组织关系如何真正影响任务分配，而不是"装饰性组织图"？

---

# Part A 员工-模型解耦

## A1 三层分离模型

```
员工身份层（employee）        模型连接层（model_connection）        执行层（adapter）
  id / 姓名 / 岗位 / 权限   →   provider + model + 凭据引用      →   LiteLLMAdapter / CLIAdapter
  提示词 / 能力声明             健康状态 / 超时重试 / 费用          实际调用与事件流
```

**铁律**：
1. `employee` 只存 `primary_model_id` / `fallback_model_id` 两个引用，**不存 provider、不存 model 名、不存密钥**
2. `agent_run` 记录本次真实使用的 `model` 字符串（快照），**历史不可被后续切换改写**
3. 所有"按模型统计"的报表都必须能回退到"按员工统计"，因为员工才是组织单位

## A2 运行时模型解析链（resolve_model）

```python
def resolve_model(employee, company) -> ResolvedModel:
    # 1. 主模型连接必须存在且启用
    primary = get_connection(employee.primary_model_id)
    if primary and primary.enabled and health_ok(primary):
        return ResolvedModel(primary, role="primary")
    # 2. 主模型不可用 → 备用（显式配置，不静默跨员工借用）
    if employee.fallback_model_id:
        fb = get_connection(employee.fallback_model_id)
        if fb and fb.enabled and health_ok(fb):
            return ResolvedModel(fb, role="fallback", warning="主模型不可用，已降级到备用模型")
    # 3. 都不可用 → 拒绝派单，绝不偷偷换成别的人员/模型
    raise NoAvailableModel(employee_id=employee.id)
```

设计选择说明：
- **不做"全公司模型池自动兜底"**：那会让"谁在干活、用什么模型、花谁的钱"变得不可解释，违背成本绩效中心的设计目标
- 降级必须产生可见事件（M2 写入 task_event，M1 在派工预览里直接排除并给出原因）
- 健康检查有 TTL 缓存（默认 5 分钟），避免每次派工都打网络请求

## A3 切换模型的完整流程（M1 交付）

```
用户点击"切换模型"
 → PUT /employees/{id}/model-binding {primary, fallback, reason}
 → 服务端校验：连接属于同一公司、enabled、api_key_ref 可解析（不实际调用）
 → 能力差异检测：新模型能力 ∩ 员工已声明能力，若产生缺口 → 200 + warnings
 → 事务内：更新 employee + 写 model_switch_log + 写 audit_log
 → 前端刷新：档案不变、历史运行记录带旧模型名、新任务用新模型
```

**测试用例（必须落地）**：
| 编号 | 场景 | 期望 |
|---|---|---|
| A3-1 | 员工 A、B 共用连接 M | 各自 agent_run 的 model 相同但 employee 归属正确，usage 不串账 |
| A3-2 | A 从 M1 切到 M2 | A.id 不变；历史 run 仍显示 M1；新 run 显示 M2；switch_log 一条 |
| A3-3 | 切到能力更弱的模型 | 返回 warnings，且该员工不再出现在需要该能力的派工候选中 |
| A3-4 | 切到已停用的连接 | 422 拒绝 |
| A3-5 | 删除被引用的连接 | 409 `BR_MODEL_IN_USE`（提示引用员工数） |

## A4 能力的三层来源（不混淆）

| 层 | 来源 | 例子 | 用途 |
|---|---|---|---|
| Adapter 能力 | `Adapter.get_capabilities()` 实测 | API 型无 file_ops | 决定"能不能做这类动作" |
| 模型能力 | catalog 元数据（上下文长度、是否支持 tool/JSON） | deepseek-chat 支持 JSON mode | 决定"模型是否胜任" |
| 授权能力 | 员工 `tools_allowed` + 权限档案 | 只授权 `file.read` | 决定"允许不允做" |

**有效能力 = Adapter 能力 ∩ 模型能力 ∩ 授权能力**。任一层缺失即不可派单，并在派工预览里给出具体缺失项（不是笼统的"不匹配"）。

---

# Part B 组织如何驱动任务分配

## B1 总体思路：约束式派工，而不是让 AI 自由点将

```
任务需求 ──硬过滤──▶ 候选集 ──打分排序──▶ 排序结果 ──CEO 只能在此集合内选──▶ 派工决策落库
                （不可协商）                   （可解释）                （越界即拒绝）
```

这样做的原因：让 LLM 在全体员工里"自由选择"会产生三种事故——选了没权限的人、选了不能审查自己的人、选了最贵的模型干最便宜的活。**组织数据的作用就是把 LLM 的选择空间压到合法且合理的范围**。

## B2 AssignmentRequest（派工请求）

```python
@dataclass
class AssignmentRequest:
    required_capabilities: list[str]   # ["coding.python", "test.unit"]
    required_tools: list[str]          # ["file.write"]
    risk_level: str                    # low|medium|high|critical
    budget_usd: float | None
    prefer_department_id: str | None   # 项目归属部门（偏好而非硬约束）
    exclude_employee_ids: list[str]    # 例如已失败过的执行人（M3 返工场景）
    notes: str = ""
```

## B3 硬过滤（顺序执行，任一不过即淘汰并记录原因）

| # | 规则 | 淘汰原因码 |
|---|---|---|
| 1 | 员工状态 = active，且所属公司 = 任务公司 | `inactive` |
| 2 | 员工有可用模型（resolve_model 成功） | `no_model` |
| 3 | 有效能力覆盖 `required_capabilities` | `capability_missing:<cap>` |
| 4 | 授权工具覆盖 `required_tools` | `tool_denied:<tool>` |
| 5 | 员工 `max_risk_level` ≥ 任务 `risk_level` | `risk_exceeded` |
| 6 | 预算可行性：`estimated_cost(employee.model) ≤ budget` | `over_budget` |
| 7 | 不在 `exclude_employee_ids` | `excluded_by_request` |
| 8 | 组织可用性：员工所在部门未被归档 | `department_archived` |

> 硬过滤全部由**代码**执行，不交给 LLM。LLM 只能看到过滤后的候选集。

## B4 打分公式（M1 v1，可解释优先于精巧）

```
score = 0.30 * position_match        # 岗位职责与所需能力标签的重合度（岗位 responsibilities 打标签）
      + 0.20 * review_chain_distance # 与"项目归属部门负责人"的汇报链距离（越近越高，跨部门衰减）
      + 0.20 * performance           # 历史绩效（M1 无数据时取中性值 0.5，并标注 data_insufficient）
      + 0.15 * cost_efficiency       # 相对成本（同能力档位下更便宜者高）
      + 0.15 * load                  # 当前负载（M1 恒为 0.5；M2 接入真实在跑任务数）
```

设计取舍：
- 权重写在 `packages/organization/assignment.py` 的常量表里，**带 `algorithm_version`**，改权重必须改版本号，历史决策可追溯
- `performance` 在 M1 无数据时给中性值并显式标注，**不假装有绩效数据**；M3 接入真实指标后自动生效
- 每个因子输出 0~1 的原始分与权重贡献，前端条形图直接展示

## B5 审查人推导（监督链，M1 先做算法不做执行）

```python
def derive_reviewer(doer, request, company) -> ReviewerDecision:
    chain = walk_reports_to_up(doer, company)      # 沿 reports_to 上溯，最多 5 层
    for candidate in chain:
        if candidate.id == doer.id: continue
        if candidate.status != "active": continue
        if not capability_covers(candidate, request.required_capabilities): continue
        cross_model = provider_of(candidate) != provider_of(doer)
        return ReviewerDecision(candidate, cross_model=cross_model,
                                reason=f"汇报链第 {n} 层上级；{'跨模型' if cross_model else '同模型'}")
    # 无上级可用 → 独立审查池：同公司、不同部门、能力匹配、优先跨模型
    pool = [e for e in active_employees(company)
            if e.department_id != doer.department_id
            and capability_covers(e, request.required_capabilities)]
    pool.sort(key=lambda e: (provider_of(e) == provider_of(doer), e.id))
    if pool:
        return ReviewerDecision(pool[0], cross_model=..., reason="独立审查池（跨部门）")
    return ReviewerDecision(None, reason="无可用审查人：需用户指定或放宽能力要求")
```

**约束**：
- `reviewer != doer`（BR-10）
- 同部门"开发-测试"配对被允许，但 `cross_model` 优先级更高（呼应"开发员不能自证"）
- 审查人只能是"建议"，最终任命权在用户与 M3 的监督流程

## B6 审批链与管理者的边界

| 角色 | 能做什么 | 绝对不能做什么 |
|---|---|---|
| 执行员工 | 提交任务结果、发起高危动作审批请求 | 批准自己的请求、修改自己的权限 |
| 管理者员工（is_managerial=true） | **建议**通过/打回、升级给用户 | 代替用户批准（系统层面无此 API） |
| 用户 | 批准/拒绝/改派/改权限 | —（唯一授权源） |

`reports_to` 在审批中的唯一作用是**决定"谁的建议先被展示"**，不产生任何自动批准能力。这条边界写进 M1_SECURITY.md 的测试清单。

## B7 M1 的交付形态与 M2 的衔接

M1 交付：
1. `packages/organization/assignment.py`：硬过滤 + 打分 + 审查人推导（纯函数，可单测）
2. `POST /assignments/preview`：给定需求返回排序与原因，落 `assignment_decision`
3. 前端派工预览台

M2 衔接：task-engine 在派工时调用同一个 `preview()` 拿到候选集，再把候选集作为约束传给 CEO Agent（prompt 中注入候选清单 + 每人理由），CEO 的选择若不在候选集内 → 拒绝并重新规划。这样"组织影响分配"在 M2 自然成立，不需要重写。

## B8 算法验收（可测试的判据）

| 编号 | 给定组织 | 输入需求 | 期望 |
|---|---|---|---|
| B8-1 | 研发部有 dev1（主模型 A）+ qa1（模型 B，汇报给 dev1） | 需 coding+test | 候选含 dev1/qa1；审查人 = qa1 或研发负责人，且 ≠ 执行人 |
| B8-2 | dev1 权限 file_ops=[read] | 需 file.write | dev1 被 `tool_denied` 排除，理由明确 |
| B8-3 | 只有 dev1 一人 | 需 coding | 审查人为空 + 原因"无可用审查人"，不硬凑 |
| B8-4 | dev1（模型 A）与 dev2（模型 B）同岗 | 需 coding | 跨模型审查优先选择不同 provider 的审查人 |
| B8-5 | 任务风险 critical，公司策略 max=high | 任意 | 全员 `risk_exceeded`，返回"需提升公司策略或用户直接指派" |
