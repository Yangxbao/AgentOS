# AgentRater · 测试报告

> 测试工程师：陈严  
> 日期：2025-07-11  
> 依据文档：`agentrater/prd.md` v1.0  
> 测试范围：prd.md、data/agents.json、index.html、styles.css、app.js、agent.html、detail.js

---

## 一、验收标准逐项核对

| # | 验收标准 | 结果 | 说明 |
|---|----------|------|------|
| AC-01 | 首页展示 20 张 Agent 卡片，每张完整显示：缩略图、名称、分类、星级评分、评价数、一句话简介、收藏按钮 | **PASS** | JSON 含 20 条数据；app.js `createCard()` 渲染了 img、name、category、stars+ratingNum、reviewCount、summary、fav 按钮，字段齐全 |
| AC-02 | 搜索功能：输入关键词后卡片实时过滤，匹配名称/简介/标签；清空关键词恢复全量；无结果时展示空状态提示 | **PASS** | app.js 搜索防抖 300ms，匹配 name/summary/tags（toLowerCase + indexOf）；searchClear 按钮清空；emptyState 友好提示 |
| AC-03 | 分类筛选：点击分类 Tab 仅展示对应分类 Agent，点击「全部」恢复；选中 Tab 有高亮态 | **FAIL** | Tab 切换与高亮逻辑正确，但**分类枚举与 PRD 不一致**（见缺陷 D-03） |
| AC-04 | 评分排序：切换「综合评分↓」后卡片按评分从高到低重排；切换「评价数↓」按评价数降序；切换「默认」恢复原始顺序；排序互斥且高亮 | **PASS** | `getFilteredAgents()` 中 rating/reviewCount 降序、default 按 id 升序；点击切换 active 类互斥 |
| AC-05 | 详情页完整展示：Agent 大图、名称、分类、标签、评分、评价数、简介、收藏按钮均正确渲染 | **PASS** | detail.js `renderDetail()` 输出 img、h1 name、category pill、tags、stars+ratingNum+reviewCount、summary、fav 按钮 |
| AC-06 | 评分分布图：5→1 星柱状分布正确显示，各星级人数之和 = 总评价数，百分比计算正确 | **FAIL** | 5→1 星条形图渲染正确，人数之和经调整后等于 reviewCount；但**分布由高斯模拟生成而非实际评价数据计算**，且**缺少百分比显示**（见缺陷 D-04、D-05） |
| AC-07 | 评价列表：展示该 Agent 全部评价，每条含用户名、星级、内容、时间、点赞按钮及点赞数 | **FAIL** | 渲染了 username、stars、content、like 按钮；但**缺少时间字段**（数据无 timestamp、UI 未展示），**缺少点赞数显示**（见缺陷 D-06、D-07） |
| AC-08 | 评价点赞 toggle：点击 👍 点赞数 +1 且按钮变为已赞态；再次点击取消，点赞数 -1；刷新页面后点赞状态保留（localStorage） | **PASS** | detail.js 事件委托处理 like-btn 点击，toggle likedMap 并写入 `agentrater_review_likes`；UI 切换 👍/👏 + 已赞/点赞 文案 |
| AC-09 | 写评价并即时可见：点击「写评价」弹出模态框，选星级 + 输入内容后提交，新评价出现在列表顶部，该 Agent 评价数 +1、评分重算 | **FAIL** | **功能完全缺失**——agent.html 和 detail.js 中无「写评价」按钮、无模态框、无提交逻辑（见缺陷 D-08） |
| AC-10 | 收藏功能：点击 ❤ 切换收藏状态，导航栏收藏角标实时更新；刷新后收藏状态保留（localStorage） | **PASS** | app.js / detail.js 均使用 `agentrater_favorites` 键存取；首页 `updateFavBadge()` 更新角标；详情页双向同步 |
| AC-11 | 卡片→详情跳转：点击卡片跳转至 `detail.html?id=xxx`，详情页数据与卡片一致 | **FAIL** | 跳转逻辑存在，但目标文件为 `agent.html` 非 PRD 指定的 `detail.html`；且 id 格式为 `a01` 非 PRD 指定的 `agent_01`（见缺陷 D-09、D-02） |
| AC-12 | 详情→首页返回：点击返回按钮回到首页，之前的搜索关键词、分类筛选、排序状态保留 | **FAIL** | 返回链接为简单 `href="index.html"`，**未通过 URL query 或 sessionStorage 传递状态**，首页将重置为默认状态（见缺陷 D-10） |

---

## 二、专项检查

| 检查项 | 结果 | 说明 |
|--------|------|------|
| JSON 可解析且 20 条 | **PASS** | `agents.json` 为合法 JSON 数组，长度 20 |
| 图片路径存在（对照 images/ 目录） | **PASS** | 20 个文件 `images/shop_01.jpg` ~ `images/shop_20.jpg` 均存在 |
| 图片内容有效 | **FAIL** | 全部 20 个 .jpg 文件内容为 Cloudflare 522 错误 HTML 页面，非有效 JPEG 图像（见缺陷 D-01） |
| 搜索逻辑正确 | **PASS** | 关键词匹配 name/summary/tags，不区分大小写，防抖 300ms |
| 筛选逻辑正确 | **PASS** | 分类 Tab 过滤 + 仅看收藏过滤，与搜索取交集 |
| 排序逻辑正确 | **PASS** | rating↓ / reviewCount↓ / default(id↑) 三种排序互斥 |
| 详情页 URL 参数处理 | **PASS** | `URLSearchParams` 解析 `id`，缺失或未匹配时渲染 404 友好提示 |
| localStorage 键无冲突 | **PASS** | `agentrater_favorites`（app.js + detail.js 共用）、`agentrater_review_likes`（detail.js），无冲突 |
| 零外部依赖 | **PASS** | 无 CDN、无 import、无第三方库引用 |
| 响应式适配 | **PASS** | styles.css 三断点（1024/768/480）；agent.html 内联样式同步适配 |
| 无障碍 | **PASS** | img 有 alt、星级有 aria-label、按钮有 aria-label、可键盘聚焦 |

---

## 三、缺陷列表

| 编号 | 严重级 | 位置 | 描述 | 修复建议 |
|------|--------|------|------|----------|
| D-01 | **P0/Critical** | `images/shop_01.jpg` ~ `shop_20.jpg` | 全部 20 张图片文件内容为 Cloudflare 522 错误 HTML（picsum.photos 连接超时），非有效 JPEG 图像，页面将显示破碎图标 | 重新下载有效图片素材（如使用 `https://picsum.photos/800/600?random=N` 或本地占位图），确保文件为二进制 JPEG 格式 |
| D-02 | **P2/Minor** | `data/agents.json` | Agent `id` 格式为 `a01`~`a20`，PRD 3.1 规定格式为 `agent_XX`（如 `agent_01`） | 将所有 id 改为 `agent_01`~`agent_20` 格式，同步更新 app.js 跳转链接和 detail.js 匹配逻辑 |
| D-03 | **P1/Major** | `data/agents.json` + `index.html` | 分类枚举与 PRD 3.2 不一致。PRD 规定：编程助手/客服机器人/数据分析/绘画创作/写作辅助/翻译语言/其他；实际数据使用：编程助手/客服机器人/数据分析/创意设计/办公效率。缺少 4 个 PRD 分类，多出 2 个非 PRD 分类 | 方案A：调整数据使 Agent 分布到 PRD 规定的 7 个分类中；方案B：更新 PRD 使分类枚举与实际一致。同时更新 index.html 的 category-tabs |
| D-04 | **P1/Major** | `detail.js` → `computeRatingDist()` | 评分分布由高斯权重模拟生成，PRD 3.4 明确要求"评分分布由评价数据实时计算得出"。当前实现忽略 reviews 中各条评价的实际星级 | 改为遍历 `agent.reviews` 统计各星级实际人数；若 reviewCount > reviews.length，对剩余人数按比例分配 |
| D-05 | **P2/Minor** | `detail.js` → `renderDetail()` 评分分布行 | PRD 2.2 规定每行显示"星数 + 横条 + 百分比 + 人数"，当前仅显示"星数 + 横条 + 人数"，缺少百分比 | 在 `.dist-count` 前增加一个 `<span class="dist-pct">XX%</span>` 元素，计算 `count / reviewCount * 100` |
| D-06 | **P1/Major** | `data/agents.json` + `detail.js` | PRD 2.2 / AC-07 要求评价显示"时间"，但 reviews 数据无 timestamp 字段，UI 也未渲染时间 | 为每条 review 增加 `time` 字段（如 `"2025-06-15"`），在 `renderDetail()` 的 review-item 中增加时间显示元素 |
| D-07 | **P2/Minor** | `detail.js` → `renderDetail()` 评价项 | PRD 2.2 / AC-07 要求显示"点赞数"，当前 like-btn 仅显示"点赞/已赞"文案，无数值 | 为每条 review 增加 `likes` 计数字段；like-btn 中显示 `👍 12` 格式；toggle 时 +1/-1 并更新显示 |
| D-08 | **P0/Critical** | `agent.html` + `detail.js` | **「写评价」功能完全缺失**。PRD AC-09 要求：点击「写评价」弹出模态框 → 选 1~5 星 + 输入内容（≥5字）→ 提交后追加到评价列表顶部 → reviewCount+1 → rating 重算 | 1) 在 agent.html 增加「写评价」按钮和模态框 HTML；2) 在 detail.js 增加模态框打开/关闭、星级选择、内容校验、提交逻辑；3) 提交后 unshift 新评价到 agent.reviews，更新 reviewCount 和 rating，重新渲染 |
| D-09 | **P2/Minor** | `app.js` + `agent.html` | 详情页文件名为 `agent.html`，PRD 2.2 / AC-11 指定路由为 `/detail.html?id=xxx` | 将 `agent.html` 重命名为 `detail.html`，同步修改 app.js 中跳转链接 `window.location.href = 'detail.html?id=...'` |
| D-10 | **P1/Major** | `agent.html` → 返回链接 + `app.js` | PRD AC-12 要求返回首页时保留之前的搜索/筛选/排序状态，当前返回链接为简单 `href="index.html"`，无状态传递 | 方案A：返回时将状态编码到 URL query（`index.html?kw=xxx&cat=xxx&sort=xxx`），首页 init 时读取并恢复；方案B：使用 sessionStorage 存储状态，首页 init 时读取并恢复 |
| D-11 | **P2/Minor** | `index.html` → category-tabs | 分类 Tab 仅 6 个（全部+5类），PRD 规定 8 个（全部+7类）。即使按实际数据分类也应包含全部出现的分类值 | 与 D-03 修复联动：确定最终分类枚举后，在 index.html 中补全所有分类 Tab |

---

## 四、测试结论

| 指标 | 值 |
|------|-----|
| 验收标准总数 | 12 |
| PASS | 6 |
| FAIL | 6 |
| 通过率 | 50% |
| 缺陷总数 | **11** |
| P0/Critical | 2（D-01 图片损坏、D-08 写评价缺失） |
| P1/Major | 4（D-03 分类枚举、D-04 分布模拟、D-06 时间缺失、D-10 返回状态） |
| P2/Minor | 5（D-02 ID格式、D-05 百分比、D-07 点赞数、D-09 文件名、D-11 Tab数） |

### 阻塞发布缺陷（P0）

1. **D-01**：全部图片文件无效，首屏和详情页图片将全部破碎，严重影响用户体验
2. **D-08**：「写评价」核心互动功能缺失，无法满足 PRD 核心目标"互动：点赞、收藏、评价形成社区氛围"

### 建议优先修复顺序

1. D-01（图片素材）→ D-08（写评价）→ D-04（评分分布计算）→ D-03（分类枚举）→ D-06（评价时间）→ D-10（返回状态保留）→ 其余 P2 项

---

> **测试完成，11 个缺陷**
