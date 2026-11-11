# 星舟科技官网一期 — 测试报告

| 字段 | 内容 |
|------|------|
| 项目名称 | 星舟科技官网建设项目（一期） |
| 版本 | v1.1（缺陷修复后） |
| 测试工程师 | 测试工程师-陈严 |
| 测试日期 | 2026-11-12 |
| 修复日期 | 2026-11-12 |
| 测试范围 | 五页响应式站点全量验收测试 |
| 测试方法 | 静态代码审查 + PRD 验收标准逐条核对 |

---

## 1 验收标准逐项核对

### AC-01 五页完整交付

| 检查项 | 结果 | 说明 |
|--------|------|------|
| index.html 存在且非空 | ✅ PASS | 16,818 B，含 Hero + 三项服务卡片 + 核心优势 + 关键数字 + 新闻速递 + 合作伙伴 + 导航 + 页脚 |
| services.html 存在且非空 | ✅ PASS | 12,257 B，含三项服务详情 + 五步服务流程 + CTA 区块 |
| about.html 存在且非空 | ✅ PASS | 14,840 B，含公司简介 + 使命与愿景 + 核心团队 + 发展里程碑 + 企业文化 |
| news.html 存在且非空 | ✅ PASS | 16,382 B，含 6 条新闻 + 分类筛选 + 封面图占位 + 分类标签 + 加载更多 |
| contact.html 存在且非空 | ✅ PASS | 7,368 B，含联系表单 + 公司信息 + 地图占位 |

**AC-01 结论：✅ PASS**

---

### AC-02 移动端不破版

| 检查项 | 结果 | 说明 |
|--------|------|------|
| CSS 含 @media (max-width: 1024px) | ✅ PASS | 平板竖屏：grid 2 列，footer 2 列 |
| CSS 含 @media (max-width: 768px) | ✅ PASS | 移动端：grid 1 列，汉堡菜单展开，hero 自适应，footer 1 列 |
| CSS 含 @media (max-width: 480px) | ✅ PASS | 小屏：容器缩进，字号降级，按钮缩放 |
| 导航移动端折叠为汉堡菜单 | ✅ PASS | `.navbar__toggle` 在 ≤768px 显示，JS 控制展开/收起 |
| 服务卡片网格响应式 | ✅ PASS | 3 列 → 2 列 → 1 列 |
| 页脚网格响应式 | ✅ PASS | 4 列 → 2 列 → 1 列 |
| Hero 区域移动端适配 | ✅ PASS | min-height: auto，字号降级，CTA 纵向排列 |

> 注：无法在真实浏览器 375px/414px/768px/1024px/1440px 下截图验证，仅做代码级审查。

**AC-02 结论：✅ PASS（代码级）**

---

### AC-03 统一导航与页脚

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 五页导航结构一致 | ✅ PASS | 均为 `<nav class="navbar">` + 5 个 `<a class="navbar__link">` |
| 五页导航链接目标一致 | ✅ PASS | index.html / services.html / about.html / news.html / contact.html |
| 五页页脚结构一致 | ✅ PASS | 均含品牌列 + 快速链接 + 业务板块 + 联系方式 + 版权 |
| 当前页导航高亮 | ✅ PASS | main.js `initNavHighlight()` 按文件名匹配添加 `.navbar__link--active` |
| 移动端汉堡菜单可展开/收起 | ✅ PASS | main.js `initMobileMenu()` 控制 `.navbar__menu--open` 切换 |

**AC-03 结论：✅ PASS**

---

### AC-04 联系表单校验

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 姓名字段存在 | ✅ PASS | `<input name="name">` + `<label for="contact-name">` |
| 邮箱字段存在 | ✅ PASS | `<input type="email" name="email">` + `<label for="contact-email">` |
| 留言字段存在 | ✅ PASS | `<textarea name="message">` + `<label for="contact-message">` |
| 姓名为空时提示 | ✅ PASS | JS: `showFieldError(nameInput, '请输入您的姓名')` |
| 姓名少于 2 字符时提示 | ✅ PASS | JS: `showFieldError(nameInput, '姓名至少 2 个字符')` |
| 邮箱格式错误时提示 | ✅ PASS | JS: 正则 `/^[^\s@]+@[^\s@]+\.[^\s@]+$/` 校验 |
| 留言少于 10 字时提示 | ✅ PASS | JS: `showFieldError(msgInput, '留言至少 10 个字符')` |
| 错误信息就近显示 | ✅ PASS | `.form__error` 紧跟各 input，`.form__error--visible` 控制显隐 |
| 校验通过后显示成功提示 | ✅ PASS | 按钮文本变为"已提交 ✓"并禁用 |
| 校验通过后清空表单 | ✅ PASS | **D-01 已修复**：main.js 在 `if (valid)` 分支中调用 `form.reset()` 并清除所有 `.form__error--visible` / `.form__input--error` |

**AC-04 结论：✅ PASS**

---

### AC-05 零外部依赖可离线打开

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 无外部 CSS 引用 | ✅ PASS | 所有页面仅引用同级 `styles.css`（相对路径） |
| 无外部 JS 引用 | ✅ PASS | 所有页面仅引用同级 `main.js`（相对路径） |
| 无外部字体引用 | ✅ PASS | CSS 使用系统字体栈，无 Google Fonts 等 CDN |
| 无外部图片引用 | ✅ PASS | 所有图标为内联 SVG，无 `<img src="http…">` |
| 无 `http://` / `https://` 外链资源 | ✅ PASS | 全站所有 `href`/`src` 均为相对路径或 `#` 锚点 |
| main.js 无外部 API 调用 | ✅ PASS | 纯原生 JS，零网络请求 |

**AC-05 结论：✅ PASS**

---

### AC-06 色彩合规

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 主色为 #0B2545（深空蓝） | ✅ PASS | `--color-deep-space: #0B2545`；`--color-primary: #0B2545` |
| 强调色为 #D4AF37（星辉金） | ✅ PASS | `--color-star-gold: #D4AF37`；`--color-accent: #D4AF37` |
| CSS 中无红色系主色/强调色 | ✅ PASS | 全文无 #FF0000 / #E00 / red 等红色值 |
| CSS 中无紫色系主色/强调色 | ✅ PASS | 全文无 #800080 / purple 等紫色值 |
| 内联 SVG 色值合规 | ✅ PASS | 所有 SVG fill/stroke 仅使用 #0B2545 和 #D4AF37 |
| 功能色避开红/紫 | ✅ PASS | success=#2E8B57(绿), warning=#D4AF37(金), info=#163A64(深蓝) |

**AC-06 结论：✅ PASS**

---

### AC-07 文案体现商业航天业务

| 检查项 | 结果 | 说明 |
|--------|------|------|
| "卫星服务/卫星在轨服务" 出现 | ✅ PASS | 五页均包含 |
| "火箭测运控" 出现 | ✅ PASS | 五页均包含 |
| "数据应用/航天数据应用" 出现 | ✅ PASS | 五页均包含 |
| 无通用模板无关文案 | ✅ PASS | 全站文案围绕商业航天、卫星、火箭、遥感等主题 |

**AC-07 结论：✅ PASS**

---

### AC-08 首屏性能

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 无外部依赖阻塞渲染 | ✅ PASS | 零 CDN 资源 |
| 图标使用内联 SVG | ✅ PASS | 无位图请求 |
| CSS/JS 文件体积合理 | ✅ PASS | styles.css 18.7KB, main.js 8.0KB |

> 注：无法在 Chrome DevTools Performance 下实测 LCP，仅做代码级评估。本地打开预计 LCP < 1s。

**AC-08 结论：✅ PASS（代码级评估）**

---

### AC-09 语义化与无障碍

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 使用 `<nav>` 语义标签 | ✅ PASS | 五页均含 `<nav class="navbar" role="navigation">` |
| 使用 `<section>` 语义标签 | ✅ PASS | 五页均使用 `<section>` 划分内容模块 |
| 使用 `<article>` 语义标签 | ✅ PASS | 卡片/新闻项均使用 `<article>` |
| 使用 `<footer>` 语义标签 | ✅ PASS | 五页均含 `<footer class="footer">` |
| 使用 `<main>` 语义标签 | ✅ PASS | **D-02 已修复**：五页均添加 `<main id="main-content" role="main">` 包裹主内容 |
| 使用 `<header>` 语义标签 | ✅ PASS | **D-11 已修复**：内页 page-header 改为 `<header>`；首页 Hero 改为 `<header>` |
| SVG 图标含 alt/aria-hidden | ✅ PASS | 所有装饰性 SVG 均 `aria-hidden="true"` |
| 表单 input 均有对应 label | ✅ PASS | 三个 input/textarea 均有 `<label for="…">` 关联 |
| 表单错误含 aria-live | ✅ PASS | `.form__error` 元素均含 `aria-live="polite"` |
| 导航含 aria-label | ✅ PASS | `<nav aria-label="主导航">`；汉堡按钮含 `aria-label`/`aria-expanded` |

**AC-09 结论：✅ PASS**

---

### AC-10 交付物完整

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 页面文件 HTML × 5 | ✅ PASS | index / services / about / news / contact |
| 样式文件 CSS | ✅ PASS | styles.css |
| 脚本文件 JS | ✅ PASS | main.js |
| 图标资源（内联 SVG） | ✅ PASS | 全部内联，无外部文件 |
| 产品需求文档 | ✅ PASS | docs/prd.md |
| 测试报告 | ✅ PASS | 本文档 docs/test_report.md |

> 注：docs/design-system.md 和 docs/delivery-report.md 非本测试步骤产出，不纳入本次判定。

**AC-10 结论：✅ PASS（测试工程师可确认部分）**

---

## 2 验收结果汇总

| 编号 | 验收条目 | 结果 |
|------|----------|------|
| AC-01 | 五页完整交付 | ✅ PASS |
| AC-02 | 移动端不破版 | ✅ PASS（代码级） |
| AC-03 | 统一导航与页脚 | ✅ PASS |
| AC-04 | 联系表单校验 | ✅ PASS |
| AC-05 | 零外部依赖可离线打开 | ✅ PASS |
| AC-06 | 色彩合规 | ✅ PASS |
| AC-07 | 文案体现商业航天业务 | ✅ PASS |
| AC-08 | 首屏性能 | ✅ PASS（代码级） |
| AC-09 | 语义化与无障碍 | ✅ PASS |
| AC-10 | 交付物完整 | ✅ PASS |

**通过 10 / 10，失败 0 / 10**

---

## 3 缺陷列表与修复情况

| 编号 | 严重级 | 位置 | 描述 | 修复状态 | 修复说明 |
|------|--------|------|------|----------|----------|
| D-01 | Medium | `main.js` | 联系表单校验通过后未清空表单字段 | ✅ 已修复 | 在 `if (valid)` 分支中添加 `form.reset()`，并清除所有 `.form__error--visible` / `.form__input--error` / `.form__textarea--error` 类名 |
| D-02 | Medium | 全部 5 个 HTML | 五页均缺少 `<main>` 语义标签 | ✅ 已修复 | 每页在 `<nav>` 与 `<footer>` 之间添加 `<main id="main-content" role="main">` 包裹 |
| D-03 | Low | `index.html` | 首页缺少核心优势、关键数字、新闻速递、合作伙伴模块 | ✅ 已修复 | 补充核心优势 section（4 项卡片）、关键数字 section（3 组数据）、新闻速递 section（3 条新闻 + 查看全部按钮）、合作伙伴占位 section（4 格占位） |
| D-04 | Low | `news.html` | 新闻页缺少分类筛选标签 | ✅ 已修复 | 在新闻列表上方添加分类筛选按钮组（全部/公司动态/行业资讯/技术前沿），JS `initNewsFilter()` 实现前端静态切换 |
| D-05 | Low | `news.html` | 新闻条目缺少封面图占位与分类标签 | ✅ 已修复 | 每条新闻添加 `.news-item__cover` 封面图占位块（灰色背景 + SVG 图标）及分类标签 `<span>` |
| D-06 | Low | `news.html` | 仅 2 条新闻且无加载更多 | ✅ 已修复 | 补充至 6 条示例新闻（4 条默认显示 + 2 条 `.news-item--hidden`），添加"加载更多"按钮，JS `initLoadMore()` 控制显示 |
| D-07 | Low | `about.html` | 缺少"使命与愿景"独立模块 | ✅ 已修复 | 在公司简介与核心团队之间添加"使命与愿景"section，含使命卡片 + 愿景卡片 |
| D-08 | Low | `about.html` | 缺少"企业文化"模块 | ✅ 已修复 | 在发展里程碑之后添加企业文化 section，含 3 张关键词卡片（极致可靠、开放协作、星辰大海） |
| D-09 | Low | `contact.html` | 缺少"地图占位"区域 | ✅ 已修复 | 在公司信息卡片下方添加地图占位块（灰色背景 + 定位 SVG 图标 + "地图加载区域"提示文字） |
| D-10 | Low | `services.html` | 缺少独立 CTA 区块 | ✅ 已修复 | 在服务流程 section 之后添加 CTA section，含标题 + 说明文案 + "联系我们获取方案"按钮 |
| D-11 | Low | 全部 5 个 HTML | page-header 使用 `<section>` 而非 `<header>` | ✅ 已修复 | 内页 `<section class="page-header">` 改为 `<header class="page-header">`；首页 Hero 区域改为 `<header class="hero">` |

---

## 4 缺陷统计

| 严重级 | 数量 | 编号 | 修复数 |
|--------|------|------|--------|
| High | 0 | — | 0 |
| Medium | 2 | D-01, D-02 | 2 |
| Low | 9 | D-03 ~ D-11 | 9 |
| **合计** | **11** | | **11** |

**全部 11 个缺陷已修复，修复率 100%**

---

## 5 修复变更文件清单

| 文件 | 修改内容 |
|------|----------|
| `main.js` | D-01: 添加 `form.reset()` + 清除错误状态；D-04/D-06: 添加 `initNewsFilter()` + `initLoadMore()` 函数 |
| `styles.css` | D-04: 添加 `.news-filter__btn` 系列样式；D-06: 添加 `.news-item--hidden` 样式；D-05: 添加 `.news-item__cover` 移动端响应式 |
| `index.html` | D-02: 添加 `<main>`；D-03: 补充核心优势/关键数字/新闻速递/合作伙伴模块；D-11: Hero 改为 `<header>` |
| `services.html` | D-02: 添加 `<main>`；D-10: 添加 CTA 区块；D-11: page-header 改为 `<header>` |
| `about.html` | D-02: 添加 `<main>`；D-07: 添加使命与愿景模块；D-08: 添加企业文化模块；D-11: page-header 改为 `<header>` |
| `news.html` | D-02: 添加 `<main>`；D-04: 添加分类筛选；D-05: 添加封面图占位+分类标签；D-06: 补充至6条+加载更多；D-11: page-header 改为 `<header>` |
| `contact.html` | D-02: 添加 `<main>`；D-09: 添加地图占位；D-11: page-header 改为 `<header>` |

---

## 6 附加检查项

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 五页互链完整性 | ✅ PASS | 导航 5 链接 + 页脚 5 链接 + 卡片/CTA 链接均使用相对路径，可互相跳转 |
| 导航高亮逻辑 | ✅ PASS | main.js 按 pathname 文件名精确匹配，当前页 `.navbar__link--active` |
| 汉堡菜单交互 | ✅ PASS | 点击切换 `.navbar__menu--open` / `.navbar__toggle--open`，点击菜单项自动收起 |
| 导航栏滚动效果 | ✅ PASS | scroll > 10px 时背景色加深 |
| 新闻日期渲染 | ✅ PASS | `data-news-date` 属性由 JS 解析并填充 `.news-item__day` / `.news-item__month` |
| 新闻分类筛选 | ✅ PASS | `initNewsFilter()` 按 `data-filter` / `data-category` 匹配显示/隐藏 |
| 加载更多 | ✅ PASS | `initLoadMore()` 移除 `.news-item--hidden` 并隐藏按钮 |
| CSS 变量体系完整 | ✅ PASS | 色彩/字号/间距/圆角/阴影/过渡均通过 CSS 自定义属性管理 |
| smooth scroll | ✅ PASS | `html { scroll-behavior: smooth; }` |
| 无 XSS 风险 | ✅ PASS | 表单不回显用户输入至 DOM，无 `innerHTML` 拼接 |
| 版权年份 | ⚠️ INFO | 硬编码为 2024，建议改为动态获取当前年份 |

---

*测试报告结束*
