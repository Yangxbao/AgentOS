"""轻量语义检索（M4-RAG 检索半环）：TF-IDF + 中文 2-gram 向量 + 余弦相似度。

定位：为记忆检索补一条"模糊语义"召回通道——FTS5/2-gram LIKE 解决"词面命中"，
TF-IDF 余弦解决"多词查询的相关性排序"。纯标准库实现（无 embedding API、无向量库、
零外部依赖），与项目"零付费/本地优先"姿态一致。生成半环沿用既有记忆注入机制。

设计：
- 索引即算即用（记忆条数在几十~几千量级，无需持久化倒排）；
- 分词：中文连续段切 2-gram + ASCII 词（分词口径的唯一权威在此，service.py 反向引用）；
- 打分：查询向量 × 候选向量余弦，IDF 权重抑制常见字噪声。
"""
from __future__ import annotations

import math
import re
from collections import Counter

_ASCII_WORD = re.compile(r"[A-Za-z0-9_]{2,}")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]{2,}")


def cjk_2grams(text: str) -> list[str]:
    """中文连续段 → 2-gram（FTS5 unicode61 把连续中文当一整块 token，子串查询命不中）。"""
    grams: list[str] = []
    for run in _CJK_RUN.findall(text or ""):
        if len(run) == 2:
            grams.append(run)
        else:
            grams.extend(run[i:i + 2] for i in range(len(run) - 1))
    return grams


def tokenize(text: str) -> list[str]:
    """中文 2-gram + ASCII 词的统一分词。"""
    tokens = cjk_2grams(text or "")
    tokens.extend(w.lower() for w in _ASCII_WORD.findall(text or ""))
    return tokens


def _vectorize(tokens: list[str], idf: dict[str, float] | None = None) -> dict[str, float]:
    counts = Counter(tokens)
    if not counts:
        return {}
    if idf is None:
        return {t: (1 + math.log(c)) for t, c in counts.items()}  # 子线性 TF
    return {t: (1 + math.log(c)) * idf.get(t, 1.0) for t, c in counts.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[t] * b[t] for t in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def rank_by_similarity(query: str, docs: list[tuple[str, str]], top_k: int | None = None) -> list[tuple[str, float]]:
    """按查询与文档的相关性排序。

    Args:
        query: 查询字符串。
        docs: [(doc_id, text), ...] 候选文档。
        top_k: 返回前 k 个（None = 全部，仅保留得分 > 0）。

    Returns:
        [(doc_id, score 0..1), ...] 按得分降序。
    """
    if not query or not docs:
        return []
    q_tokens = tokenize(query)
    if not q_tokens:
        return []

    # IDF：候选语料的文档频率（抑制常见字噪声）
    doc_tokens = [(doc_id, tokenize(text)) for doc_id, text in docs]
    df: Counter = Counter()
    for _, tokens in doc_tokens:
        df.update(set(tokens))
    total_docs = max(len(doc_tokens), 1)
    idf = {t: math.log((total_docs + 1) / (count + 1)) + 1.0 for t, count in df.items()}

    q_vec = _vectorize(q_tokens, idf)
    scored = []
    for doc_id, tokens in doc_tokens:
        score = _cosine(q_vec, _vectorize(tokens, idf))
        if score > 0:
            scored.append((doc_id, score))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    if top_k is not None:
        scored = scored[:top_k]
    return scored
