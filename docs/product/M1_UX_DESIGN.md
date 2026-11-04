# M1 前端页面与交互设计

> v1.0（待确认）｜2026-11-05｜技术栈沿用 M0：React 18 + TS + Vite + Tailwind v4 + zustand + react-router-dom
> M1 新增：shadcn/ui（组件）、@tanstack/react-query（服务端状态）、@xyflow/react（组织图）
> 原则：前端不承载业务规则；所有校验以服务端返回为准；不允许假数据演示

---

## 1. 信息架构

```
/                          → 重定向 /org
/org                       组织架构（默认首页，含组织图）
/employees                 员工列表
/employees/new             建员工向导（3 步）
/employees/:id             员工详情（Tabs）
/settings/organization     公司/部门/岗位设置
/settings/models           模型连接管理
/settings/import-export    导入导出
/settings/audit            审计日志
/assignments/preview       派工预览（调试/验证台）
```

顶部栏：公司切换器 + 全局搜索（员工/部门）+ "新建员工"主按钮。
左侧栏：组织架构 / 员工 / 派工预览 / 设置（展开：组织、模型连接、导入导出、审计）。

---

## 2. 页面设计

### P1 组织架构 `/org`

**布局**：左侧部门树（可折叠，显示人数）；右侧 React Flow 画布；右上角工具栏（缩放/适应/自动布局/仅显示汇报线）。

**节点类型**：
| 节点 | 内容 | 交互 |
|---|---|---|
| 公司节点 | 公司名 + 员工数 | 点击打开公司设置 |
| 部门节点 | 部门名 + 人数徽标 | 双击改名；拖动 = 改父级；右键菜单（新建子部门/新建员工/删除） |
| 员工节点 | 头像 + 名字 + 岗位徽标 + 模型小标签 | 拖动 = 调部门（或拖到另一员工上 = 改汇报对象）；点击打开详情抽屉 |
| 汇报线 | reports_to 实线；兼任虚线 | hover 高亮双方 |

**关键交互规则**：
1. 拖拽结束才发请求（乐观更新 + 失败回滚 + Toast）
2. 成环/超深度由服务端拒绝，前端展示服务端 message，不自行猜测
3. 未保存状态不适用（拖拽即时保存），但有 500ms 节流合并
4. 员工禁用态节点降透明度 + "已停用"标签，不可作为汇报对象

**空态**：无部门时展示"先建第一个部门"引导卡（不自动创建数据）。

### P2 员工列表 `/employees`

表格列：姓名/岗位/部门/主模型/状态/最近变更。支持按状态、部门、关键词过滤；行内快速停用/启用（二次确认）；点击行进详情。
顶部提示条：当存在"停用但仍是某任务负责人"（M2 后）或"模型连接不健康"时显示黄色警示。

### P3 建员工向导 `/employees/new`（3 步）

| 步骤 | 内容 | 校验 |
|---|---|---|
| 1 身份 | 姓名、头像（emoji 选择器）、岗位（多选，1 主）、部门、汇报对象、简介、性格 | 姓名必填；主岗必选；姓名重复由服务端报错 |
| 2 模型与工具 | 主模型连接（下拉，显示健康状态点）、备用模型（可选）、工具白名单（复选） | 主模型必选；无健康连接时给"先去配置模型连接"的跳转 |
| 3 提示词与权限 | 初始提示词（模板选择：分析师/开发/测试/主管 四套骨架）、权限档（只读/工作区可写/受限网络） | 提示词非空（可一键用模板）；权限档只能选 ≤ 公司策略上限 |

右侧常驻"将创建的内容"摘要。完成后跳详情页并高亮提示词 Tab。

### P4 员工详情 `/employees/:id`（5 个 Tab）

1. **档案**：编辑姓名/岗位/部门/汇报/简介/性格；停用/删除（危险区，输入姓名确认）
2. **模型**：主/备模型卡片（显示 provider、健康、最近延迟）、"切换模型"抽屉（选新模型 + 填原因 + 显示能力差异 warning）、切换历史（model_switch_log）
3. **提示词**：左侧版本列表（active 标记、时间、note），右侧 Markdown 编辑器；操作「保存为新版本」「与上一版对比」「激活此版本」；保存后显示哈希短码
4. **权限**：三层来源可视化——
   ```
   公司策略上限：workspace=project_only, file_ops=[read,write], network=allowlist
   岗位默认（主岗 技术审查官）：file_ops=[read], network=deny
   员工覆盖：file_ops=[read]
   ─────────────────────────────
   有效权限：file_ops=[read] ← 标出来源链
   ```
   员工覆盖项中，任何比"岗位默认"更宽的选项置灰，hover 解释"公司策略/岗位默认不允许放宽"
5. **能力与记录**：能力矩阵（8 项，来源标注 adapter/模型/工具）、最近审计 20 条

### P5 模型连接 `/settings/models`

卡片网格：每个连接显示 provider 图标、模型、健康点（绿/红/灰）、最近测试时间、被多少员工引用。
操作：测试连接（按钮转 loading，成功显示延迟 ms，失败显示错误分类）、编辑、停用、删除（被引用时禁用并提示引用数）。
新建表单：provider 选择 → 模型（catalog 下拉可手填）→ 密钥引用（默认填入 `env:XXX_API_KEY`，显式提示"请输入环境变量名，不要粘贴密钥本体"）→ 高级（base_url/timeout/retries）。

### P6 导入导出 `/settings/import-export`
导出：选择公司 → 预览将包含的实体数量 → 下载 zip。
导入：拖入 zip → dry-run 结果表（新建/覆盖/跳过，逐项可勾选）→ 执行 → 结果摘要 + 失败明细。冲突策略三选一：改名保留两者/跳过/合并（仅同 ID）。

### P7 派工预览 `/assignments/preview`
表单：能力标签多选、工具多选、风险等级、预算、备注。
结果：候选人卡片列表（分数条 + 5 项因子小条形图 + 警告）、被排除者折叠区（显示硬过滤原因）、审查人卡片（含 cross_model 标记）。
底部："该结果仅预览，M2 才会真正派发"的说明（避免误解为已派工）。

---

## 3. 状态管理与数据流

| 层 | 方案 | 说明 |
|---|---|---|
| 服务端状态 | TanStack Query | queryKey 规范：`['org-tree', companyId]`、`['employee', id]`、`['models', companyId]`；写操作后 invalidate 相关 key |
| 客户端 UI 状态 | zustand | 当前公司、侧栏折叠、组织图视图设置（仅 UI，不放业务数据） |
| 表单 | react-hook-form + zod（与服务端 schema 对齐的客户端预校验） | 服务端仍是唯一权威 |
| 错误呈现 | 统一 `ApiError` → Toast + 表单字段级错误映射 | 409 类业务错误直接在相关控件下展示 |

---

## 4. 交互与体验细则

1. **危险操作**：删除员工/部门、放宽权限、归档公司 → 二次确认（删除员工需输入姓名）
2. **加载态**：骨架屏用于列表/详情；组织图首次加载显示"正在构建组织图"
3. **空态**：每个列表都有引导动作，不出现空白页
4. **乐观更新**：仅组织图拖拽使用，失败必须回滚并提示
5. **可访问性**：所有图标按钮有 aria-label；焦点可见；组织图提供"列表视图"替代（键盘可达）
6. **文案**：全中文；错误文案必须包含"发生了什么 + 怎么办"，不出现裸英文异常

---

## 5. 组件清单（复用优先）

```
components/
├── ui/                  # shadcn/ui 生成：Button/Dialog/Input/Select/Tabs/Toast/Badge/Skeleton
├── org/OrgCanvas.tsx    # React Flow 画布 + 自定义节点
├── org/DepartmentTree.tsx
├── employee/EmployeeForm.tsx  ModelBindingDrawer.tsx  PermissionMatrix.tsx
├── prompt/PromptEditor.tsx    VersionList.tsx  DiffView.tsx
├── model/ConnectionCard.tsx   ConnectionForm.tsx  HealthDot.tsx
└── common/DangerConfirm.tsx   EmptyState.tsx  ErrorBoundary.tsx
```

**前端测试边界**：纯函数（组织树组装、权限来源合并展示、分数条归一化）用 vitest 单测；交互链路 M1 用手工验收清单（Playwright 属重型依赖，需你单独批准后再引入）。
