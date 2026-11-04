# BerriAI/litellm 调研笔记（重点：供应商列表、Proxy/网关模式、费用追踪）

> 调研时间：2026-11-05。

## 1. 基本信息

- 仓库地址：https://github.com/BerriAI/litellm 【已验证-页面抓取】
- 可访问性：可访问，GitHub 主页与 README raw（main）抓取成功【已验证-页面抓取】
- License：主体 **MIT**（Copyright (c) 2023 Berri AI）；`enterprise/` 目录内容受 `enterprise/LICENSE` 定义的商业许可证约束【已验证-页面抓取：LICENSE 文件全文】
- 最近维护迹象：非常活跃——最近 commit `83be155`（2026-11-04），累计 55,859 commits；13.0k forks；star 数页面未直接显示，未找到【已验证-页面抓取】
- 技术栈：**Rust 核心**（`litellm-rust`）+ **Python**（SDK 与 Proxy，Prisma/Postgres）+ TypeScript 管理面板（`ui/litellm-dashboard`）；Docker/Terraform/Helm【已验证-页面抓取】
- 官方文档站：https://docs.litellm.ai ；模型价格站：https://models.litellm.ai
- 背景：Y Combinator W23 孵化【官方文档结论：README】

## 2. 核心架构与目录结构

【官方文档结论】双形态架构：

| 形态 | 定位 | 目标用户 |
|---|---|---|
| **LiteLLM AI Gateway（Proxy Server）** | 中心化 LLM 网关服务 | Gen AI/ML 平台团队 |
| **LiteLLM Python SDK** | 应用内库集成 | 开发者 |

网关功能组件：虚拟密钥、花费追踪、护栏、负载均衡、缓存、Admin Dashboard UI、Auto Routing、A2A 网关、MCP 网关。官方宣称性能 1k RPS 下 P95 延迟 8ms【官方文档结论】。
生产部署为组件化架构：gateway/backend/UI 分离 + 托管 Postgres + Redis + 对象存储【官方文档结论：README Terraform 段】。

## 3. Agent 管理方式

【官方文档结论】LiteLLM 本身不定义 Agent，但提供 Agent 相关网关能力：

- **A2A 端点**（`/a2a`）：调用 A2A Agents（LangGraph、Vertex AI Agent Engine 等）
- **Agent Providers**：LangGraph、Pydantic AI Agents 作为 provider 类别接入【已验证-页面抓取：providers 文档页】
- README 宣称可在任意模型上运行 Claude Code、Codex、OpenCode、Deep Agents 等【官方文档结论】

## 4. 模型接入方式（重点）

### 统一接口形态

【官方文档结论】所有供应商通过**一个 OpenAI 格式 API** 调用；模型标识为 `<prefix>/<model-name>`（如 `anthropic/claude-sonnet-5`、`openai/gpt-4o`），同一请求在 Python SDK 与 Gateway 中通用。支持的端点：`/chat/completions`、`/responses`、`/embeddings`、`/images`、`/audio`、`/batches`、`/rerank`、`/a2a`、`/messages` 等。

### 支持的供应商类别

【已验证-页面抓取：docs.litellm.ai/docs/providers】官方表述支持 **100+ 供应商**，分类如下：

- **Popular**：OpenAI、Anthropic、Google AI Studio/Gemini、Vertex AI、Azure OpenAI、Azure AI、Bedrock、Mistral、xAI、Deepseek、Groq
- **Self-Hosted & Local**：Ollama、vLLM、LM Studio、Llamafile、Docker Model Runner、Triton、Xinference、Nvidia NIM、自定义 API Server
- **Gateways & OpenAI-Compatible**：OpenRouter、Vercel AI Gateway、Helicone、Poe、任意 OpenAI 兼容端点
- **国内厂商**：Dashscope（阿里云，含 chat/embeddings/images/audio/video/rerank）、QwenCloud/千问、Volcengine（火山引擎）、Moonshot、Z.AI（智谱）、Tencent TokenHub、MiniMax、Xiaomi MiMo
- **Vector Stores**：Milvus、MongoDB、AWS S3 Vectors、Valkey、RAGFlow
- **Agent Providers**：LangGraph、Pydantic AI Agents
- **专项能力**：Deepgram/ElevenLabs（语音）、Jina/Voyage（embedding）、Recraft/Fal（图像）等

每模型的价格与上下文窗口维护在 models.litellm.ai（对应仓库内 `model_prices_and_context_window.json`）【官方文档结论】。

### 费用 / token 统计能力（重点）

【已验证-页面抓取：virtual_keys 文档页】

- **成本计算**：单价存于 `model_prices_and_context_window.json`，由 `completion_cost()` 计算；调用 chat/completions/embeddings 时自动以 USD 累计花费
- **追踪维度与存储**：密钥（`LiteLLM_VerificationTokenTable`）、用户（`LiteLLM_UserTable`）、团队（`LiteLLM_TeamTable`）、终端用户；查询端点 `/key/info`、`/user/info`、`/team/info`、`/end_user/info`
- **预算控制**：`max_budget`（USD 上限）、`budget_duration`（重置周期）、`budget_limits`（多时间窗口）、临时增额 `temp_budget_increase`；超限拒绝（HTTP 400）；`self_serve_budget_policy` 控制用户可否自助改预算
- **速率限制**：`tpm_limit`（token/分钟）、`rpm_limit`（请求/分钟）、`max_parallel_requests`，可在密钥级设置并设全局上限（`upperbound_key_generate_params`）
- 需 Postgres 数据库支撑（`DATABASE_URL`）

## 5. CLI 接入方式

【官方文档结论】提供 CLI 启动 Proxy：`uv tool install 'litellm[proxy]'` 后 `litellm --model gpt-4o`，默认监听 0.0.0.0:4000；客户端用 OpenAI SDK 指向 `base_url=http://0.0.0.0:4000` 即可。程序化接入主要靠 OpenAI 兼容 HTTP API 与 Python SDK。

## 6. 多 Agent 协作方式

不直接提供编排，通过 A2A 网关端点与 MCP 网关（把 MCP server 工具接入任意 LLM）间接支持【官方文档结论】。

## 7. 人工审批/人在回路机制

未找到（网关层无 HITL 概念；护栏 guardrails 属自动校验）。

## 8. 权限控制机制

【已验证-页面抓取：virtual_keys 文档页】

- **Master Key**：`LITELLM_MASTER_KEY`（须 `sk-` 开头）作为管理员密钥
- **虚拟密钥**：`/key/generate` 签发，绑定 `models` 列表、`user_id`/`team_id`；支持 `/key/block`、`/key/unblock`
- **继承模型**：密钥从所有者继承模型访问/管理路由/预算/速率限制，可用 `allowed_routes`、`object_permission.mcp_servers` 等覆盖
- **密钥轮换**：`/key/{key}/regenerate`（企业版），支持 grace_period 与 `auto_rotate` 定时轮换
- 自定义管控 hook：`custom_key_generate` / `custom_key_policy`；`key_alias_pattern` 正则约束
- 企业版：SSO 单点登录【官方文档结论】

## 9. 运行记录/持久化能力

【官方文档结论+已验证-页面抓取】Postgres 存储密钥/用户/团队/花费；支持可观测性回调（Lunary、MLflow、Langfuse 等）；日志/缓存可按项目定制；Prisma 管理 schema（部署时 `prisma migrate deploy`）。

## 10. 部署方式

【官方文档结论：README】

- Docker（GHCR 镜像，cosign 签名；稳定版用 `-stable` 标签，发布前经 12 小时负载测试）
- Terraform 模块：AWS（ECS Fargate + Aurora + ElastiCache + ALB）、GCP（Cloud Run + Cloud SQL + Memorystore）
- Helm、一键部署按钮（Render/Railway/AWS/GCP）
- 开发者模式：`docker-compose up db prometheus` + `make bootstrap`

## 11. 实际运行条件

- Proxy 生产用法需 Postgres；Redis 用于缓存/限流（Terraform 栈含托管 Redis）【官方文档结论】
- Python SDK：`uv add litellm`（另有仅 SDK 的 `litellm-core` 发行版，二选一安装）【官方文档结论】
- 各供应商 API key 通过环境变量注入（如 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`）【官方文档结论】

## 12. 已知限制

- 虚拟密钥/花费追踪等企业级功能依赖 Postgres，纯内存模式能力受限【已验证-页面抓取：virtual_keys 前提条件】
- 部分功能（密钥轮换、SSO 等）锁在商业许可的 enterprise 版【已验证-页面抓取：LICENSE + 文档页】
- README 未展开速率限制细节，需查专门文档【已验证-页面抓取】
- 双发行版（litellm 与 litellm-core）文件重叠，同环境只能装一个【官方文档结论】

## 13. 对 AgentOS 的借鉴价值

- **值得借鉴**：`<prefix>/<model>` 统一寻址 + OpenAI 兼容 API 的接入形态；模型价格表驱动的 `completion_cost()` 费用核算；虚拟密钥 + 预算 + tpm/rpm 限额的多租户模型；密钥继承/覆盖矩阵；Terraform 组件化部署参考。
- **不适合照搬**：整套多语言（Rust+Python+TS）栈过重；Admin UI 与 AgentOS 自身控制台重复。
- **需自研**：与 AgentOS Agent 模型的映射（把 LiteLLM 的虚拟密钥体系挂到 AgentOS 的 Agent/用户体系下）；若只作库使用则直接依赖其 Python SDK 即可【推断】。

## 14. 分类建议

**C（模型网关）**——核心定位即 AI Gateway/LLM 代理【官方文档结论】；兼具 B 的边缘能力（A2A/MCP/Agent providers），但不足以归为工作流框架。
