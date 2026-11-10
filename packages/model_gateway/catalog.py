"""Provider 与模型目录（静态元数据，B3）。

用途：模型下拉、能力差异提示、派工打分中的成本/能力参考。
不含任何价格承诺；成本以 LiteLLM 价格表实测为准。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    context_window: int
    structured_output: bool = True
    tool_calling: bool = True
    cost_tier: str = "middle"  # premium|middle|budget|local


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    api_key_env: str
    models: list[ModelInfo] = field(default_factory=list)


PROVIDERS: dict[str, ProviderInfo] = {
    "deepseek": ProviderInfo(
        id="deepseek", label="DeepSeek", api_key_env="DEEPSEEK_API_KEY",
        models=[
            ModelInfo("deepseek/deepseek-chat", "DeepSeek Chat", 64_000, cost_tier="budget"),
            ModelInfo("deepseek/deepseek-reasoner", "DeepSeek Reasoner", 64_000, cost_tier="middle"),
        ],
    ),
    "openai": ProviderInfo(
        id="openai", label="OpenAI", api_key_env="OPENAI_API_KEY",
        models=[
            ModelInfo("openai/gpt-4o-mini", "GPT-4o mini", 128_000, cost_tier="budget"),
            ModelInfo("openai/gpt-4o", "GPT-4o", 128_000, cost_tier="premium"),
        ],
    ),
    "anthropic": ProviderInfo(
        id="anthropic", label="Anthropic", api_key_env="ANTHROPIC_API_KEY",
        models=[
            ModelInfo("anthropic/claude-haiku-4-5", "Claude Haiku 4.5", 200_000, cost_tier="budget"),
            ModelInfo("anthropic/claude-sonnet-4-5", "Claude Sonnet 4.5", 200_000, cost_tier="premium"),
        ],
    ),
    "gemini": ProviderInfo(
        id="gemini", label="Google Gemini", api_key_env="GOOGLE_API_KEY",
        models=[
            ModelInfo("gemini/gemini-2.0-flash", "Gemini 2.0 Flash", 1_000_000, cost_tier="budget"),
        ],
    ),
    "openrouter": ProviderInfo(
        id="openrouter", label="OpenRouter", api_key_env="OPENROUTER_API_KEY",
        models=[
            ModelInfo("openrouter/deepseek/deepseek-chat", "DeepSeek Chat (OpenRouter)", 64_000, cost_tier="budget"),
            # :free 免费档清单随 OpenRouter 调整，以下为 2026-11-11 实测可用（支持 function calling）
            ModelInfo("openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
                      "Nemotron 3 Ultra 550B（:free 免费档）", 1_000_000, cost_tier="local"),
            ModelInfo("openrouter/dots-studio/dots-3-note-preview:free",
                      "Dots-3 Note Preview（:free 免费档）", 512_000, cost_tier="local"),
        ],
    ),
    "zhipu": ProviderInfo(
        id="zhipu", label="智谱 AI", api_key_env="ZHIPU_API_KEY",
        models=[
            ModelInfo("openai/glm-4-flash", "GLM-4-Flash（免费）", 128_000, cost_tier="local"),
            ModelInfo("openai/glm-4.5-flash", "GLM-4.5-Flash（免费）", 128_000, cost_tier="local"),
            ModelInfo("openai/glm-4-plus", "GLM-4-Plus", 128_000, cost_tier="premium"),
        ],
    ),
    "siliconflow": ProviderInfo(
        id="siliconflow", label="硅基流动", api_key_env="SILICONFLOW_API_KEY",
        models=[
            ModelInfo("openai/Qwen/Qwen2.5-7B-Instruct", "Qwen2.5-7B（免费）", 32_000, cost_tier="local"),
            ModelInfo("openai/THUDM/glm-4-9b-chat", "GLM-4-9B（免费）", 32_000, cost_tier="local"),
        ],
    ),
    "groq": ProviderInfo(
        id="groq", label="Groq（免费档）", api_key_env="GROQ_API_KEY",
        models=[
            ModelInfo("openai/llama-3.3-70b-versatile", "Llama 3.3 70B（免费档）", 128_000, cost_tier="local"),
            ModelInfo("openai/llama-3.1-8b-instant", "Llama 3.1 8B（免费档）", 128_000, cost_tier="local"),
        ],
    ),
    "baidu": ProviderInfo(
        id="baidu", label="百度千帆（免费模型）", api_key_env="BAIDU_API_KEY",
        models=[
            ModelInfo("openai/ernie-speed-8k", "ERNIE Speed 8K（免费）", 8_000, cost_tier="local"),
            ModelInfo("openai/ernie-lite-8k", "ERNIE Lite 8K（免费）", 8_000, cost_tier="local"),
        ],
    ),
    "ollama": ProviderInfo(
        id="ollama", label="Ollama（本地）", api_key_env="",
        models=[
            ModelInfo("ollama/llama3.1", "Llama 3.1（本地）", 128_000, cost_tier="local"),
        ],
    ),
}


def provider_info(provider: str) -> ProviderInfo | None:
    return PROVIDERS.get(provider)


def model_info(model: str) -> ModelInfo | None:
    for provider in PROVIDERS.values():
        for info in provider.models:
            if info.id == model:
                return info
    return None


def capabilities_of(model: str) -> dict:
    info = model_info(model)
    if info is None:
        return {"known": False, "structured_output": None, "tool_calling": None, "context_window": None}
    return {
        "known": True,
        "structured_output": info.structured_output,
        "tool_calling": info.tool_calling,
        "context_window": info.context_window,
        "cost_tier": info.cost_tier,
    }


def list_models(provider: str) -> list[dict]:
    info = provider_info(provider)
    if info is None:
        return []
    return [
        {
            "id": m.id,
            "label": m.label,
            "context_window": m.context_window,
            "structured_output": m.structured_output,
            "tool_calling": m.tool_calling,
            "cost_tier": m.cost_tier,
        }
        for m in info.models
    ]


def provider_ids() -> list[str]:
    return list(PROVIDERS)
