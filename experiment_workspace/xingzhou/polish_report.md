# 星舟官网 · 发布前打磨报告

> 审计范围：`xingzhou/website/` 下 5 个 HTML 页面 + `styles.css`  
> 审计维度：SEO / Favicon / 无障碍 / 一致性  
> 审计时间：2026-11-12

---

## 一、SEO

### 1.1 meta description

| 文件 | 状态 | 说明 |
|------|------|------|
| index.html | ✅ 已有 | `星舟科技 — 商业航天解决方案提供商，专注卫星在轨服务、火箭测运控与航天数据应用` |
| services.html | ✅ 已有 | `星舟科技服务方案 — 卫星在轨服务、火箭测运控、航天数据应用全链路解决方案` |
| about.html | ✅ 已有 | `关于星舟科技 — 商业航天初创公司，专注卫星在轨服务、火箭测运控与航天数据应用` |
| news.html | ✅ 已有 | `星舟科技新闻动态 — 商业航天领域最新进展与公司动态` |
| contact.html | ✅ 已有 | `联系星舟科技 — 商务合作咨询、技术方案咨询与售后服务` |

### 1.2 og:title / og:description

| 文件 | og:title | og:description |
|------|----------|----------------|
| index.html | ✅ 已有 | ✅ 已有 |
| services.html | ✅ 已有 | ✅ 已有 |
| about.html | ✅ 已有 | ✅ 已有 |
| news.html | ✅ 已有 | ✅ 已有 |
| contact.html | ✅ 已有 | ✅ 已有 |

### 1.3 lang 属性

| 文件 | 状态 |
|------|------|
| index.html | ✅ `lang="zh-CN"` |
| services.html | ✅ `lang="zh-CN"` |
| about.html | ✅ `lang="zh-CN"` |
| news.html | ✅ `lang="zh-CN"` |
| contact.html | ✅ `lang="zh-CN"` |

### SEO 改进清单

| # | 文件 | 改进动作 | 状态 |
|---|------|----------|------|
| 1 | index.html | 在 `<head>` 中添加 `<meta property="og:title" content="首页 — 星舟科技">` | ✅ 已完成 |
| 2 | index.html | 在 `<head>` 中添加 `<meta property="og:description" content="星舟科技 — 商业航天解决方案提供商，专注卫星在轨服务、火箭测运控与航天数据应用">` | ✅ 已完成 |
| 3 | services.html | 在 `<head>` 中添加 `<meta property="og:title" content="服务方案 — 星舟科技">` | ✅ 已完成 |
| 4 | services.html | 在 `<head>` 中添加 `<meta property="og:description" content="星舟科技服务方案 — 卫星在轨服务、火箭测运控、航天数据应用全链路解决方案">` | ✅ 已完成 |
| 5 | about.html | 在 `<head>` 中添加 `<meta property="og:title" content="关于我们 — 星舟科技">` | ✅ 已完成 |
| 6 | about.html | 在 `<head>` 中添加 `<meta property="og:description" content="关于星舟科技 — 商业航天初创公司，专注卫星在轨服务、火箭测运控与航天数据应用">` | ✅ 已完成 |
| 7 | news.html | 在 `<head>` 中添加 `<meta property="og:title" content="新闻动态 — 星舟科技">` | ✅ 已完成 |
| 8 | news.html | 在 `<head>` 中添加 `<meta property="og:description" content="星舟科技新闻动态 — 商业航天领域最新进展与公司动态">` | ✅ 已完成 |
| 9 | contact.html | 在 `<head>` 中添加 `<meta property="og:title" content="联系我们 — 星舟科技">` | ✅ 已完成 |
| 10 | contact.html | 在 `<head>` 中添加 `<meta property="og:description" content="联系星舟科技 — 商务合作咨询、技术方案咨询与售后服务">` | ✅ 已完成 |

> 每页同时补充了 `og:type`（首页 `website`，其余 `article`）和 `og:locale`（`zh_CN`），以完善 Open Graph 协议覆盖。✅ 已完成

---

## 二、Favicon

| 文件 | 状态 |
|------|------|
| index.html | ✅ 已有 — 内联 SVG favicon |
| services.html | ✅ 已有 |
| about.html | ✅ 已有 |
| news.html | ✅ 已有 |
| contact.html | ✅ 已有 |

### Favicon 改进清单

| # | 文件 | 改进动作 | 状态 |
|---|------|----------|------|
| 11 | index.html | 在 `<head>` 中添加内联 SVG favicon：`<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,…">`，使用品牌火箭轮廓 SVG（深空蓝底 + 星辉金火箭），保持零外部依赖 | ✅ 已完成 |
| 12 | services.html | 同上，添加内联 SVG favicon | ✅ 已完成 |
| 13 | about.html | 同上 | ✅ 已完成 |
| 14 | news.html | 同上 | ✅ 已完成 |
| 15 | contact.html | 同上 | ✅ 已完成 |

> **已使用 data URI**（全站 5 页统一）：
> ```html
> <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 36 36'%3E%3Crect width='36' height='36' rx='6' fill='%230B2545'/%3E%3Cpath d='M18 4 L22 14 L26 22 L18 32 L10 22 L14 14 Z' fill='%23D4AF37' opacity='0.9'/%3E%3C/svg%3E">
> ```

---

## 三、无障碍（Accessibility）

### 3.1 图片 alt

全站无 `<img>` 标签，所有图形均使用内联 SVG，且全部标记 `aria-hidden="true"`（装饰性图形），**无需补充 alt**。✅

### 3.2 按钮 aria-label

| 按钮 | 文件 | 状态 | 说明 |
|------|------|------|------|
| 导航菜单切换 | 全部 5 页 | ✅ | `aria-label="打开菜单"` + `aria-expanded="false"` |
| 新闻筛选「全部」 | news.html | ✅ | `aria-pressed="true"` |
| 新闻筛选「公司动态」 | news.html | ✅ | `aria-pressed="false"` |
| 新闻筛选「行业资讯」 | news.html | ✅ | `aria-pressed="false"` |
| 新闻筛选「技术前沿」 | news.html | ✅ | `aria-pressed="false"` |
| 「加载更多」 | news.html | ✅ | `aria-label="加载更多新闻"` |
| 「提交留言」 | contact.html | ✅ | 有可见文本，语义明确 |

### 3.3 表单 label 关联

| 字段 | 文件 | 状态 | 说明 |
|------|------|------|------|
| 姓名 | contact.html | ✅ | `<label for="contact-name">` ↔ `<input id="contact-name">` |
| 邮箱 | contact.html | ✅ | `<label for="contact-email">` ↔ `<input id="contact-email">` |
| 留言 | contact.html | ✅ | `<label for="contact-message">` ↔ `<textarea id="contact-message">` |
| 表单容器 | contact.html | ✅ | `<h2 id="contact-form-heading">发送留言</h2>` + `<form aria-labelledby="contact-form-heading">` |

### 无障碍改进清单

| # | 文件 | 改进动作 | 状态 |
|---|------|----------|------|
| 16 | news.html | 为「全部」筛选按钮添加 `aria-pressed="true"`（当前激活态） | ✅ 已完成 |
| 17 | news.html | 为「公司动态」「行业资讯」「技术前沿」筛选按钮添加 `aria-pressed="false"`（非激活态） | ✅ 已完成 |
| 18 | news.html | 为「加载更多」按钮添加 `aria-label="加载更多新闻"` | ✅ 已完成 |
| 19 | contact.html | 为 `<h2>发送留言</h2>` 添加 `id="contact-form-heading"`，为 `<form>` 添加 `aria-labelledby="contact-form-heading"` | ✅ 已完成 |

> **额外建议**（非阻塞项）：全站添加跳转主内容链接 `<a href="#main-content" class="skip-link">跳至主内容</a>`，提升键盘用户导航效率。

---

## 四、一致性 — 页面 title 规范

规范格式：**页面名 — 星舟科技**

| 文件 | 当前 title | 是否合规 | 期望 title |
|------|-----------|----------|-----------|
| index.html | `首页 — 星舟科技` | ✅ | — |
| services.html | `服务方案 — 星舟科技` | ✅ | — |
| about.html | `关于我们 — 星舟科技` | ✅ | — |
| news.html | `新闻动态 — 星舟科技` | ✅ | — |
| contact.html | `联系我们 — 星舟科技` | ✅ | — |

### 一致性改进清单

| # | 文件 | 改进动作 | 状态 |
|---|------|----------|------|
| 20 | index.html | 将 `<title>` 修改为 `首页 — 星舟科技` | ✅ 已完成 |

---

## 五、styles.css 审计备注

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 品牌色值 | ✅ | `--color-deep-space: #0B2545`、`--color-star-gold: #D4AF37`，符合品牌规范 |
| 红紫色调 | ✅ | 功能色使用 `#2E8B57`（success）、`#D4AF37`（warning）、`#163A64`（info），无红/紫 |
| 响应式断点 | ✅ | 覆盖 1024px / 768px / 480px 三档 |
| 零外部依赖 | ✅ | 无 `@import`、无外部字体 CDN、无外部图标库 |
| focus 样式 | ✅ | 链接 hover/focus 同态，表单输入有 focus ring |

---

## 六、改进总览

| 维度 | 改进项数 | 完成状态 |
|------|----------|----------|
| SEO（og:title + og:description + og:type + og:locale） | 10 | ✅ 全部完成 |
| Favicon | 5 | ✅ 全部完成 |
| 无障碍 | 4 | ✅ 全部完成 |
| 一致性（title） | 1 | ✅ 全部完成 |
| **合计** | **20** | **✅ 全部完成** |

---

## 七、优先级建议

| 优先级 | 改进项 | 理由 | 状态 |
|--------|--------|------|------|
| 🔴 P0 | #11–15 Favicon | 浏览器默认图标影响品牌专业度，且实现成本极低（复制一行代码） | ✅ 已完成 |
| 🔴 P0 | #20 Title 一致性 | 首页 title 不合规，影响搜索引擎结果展示 | ✅ 已完成 |
| 🟡 P1 | #1–10 OG 标签 | 社交分享无预览卡片，影响传播效果 | ✅ 已完成 |
| 🟡 P1 | #16–19 无障碍 | 筛选按钮状态不可感知，表单缺少语义关联 | ✅ 已完成 |
| 🟢 P2 | 跳转链接（skip-link） | 键盘导航最佳实践，非 WCAG A/AA 强制要求 | 待定 |
