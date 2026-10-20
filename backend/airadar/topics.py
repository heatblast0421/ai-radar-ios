"""Deterministic topic classifier.

Topics are assigned with transparent keyword rules (not by an LLM), so the same text always
gets the same topics and you can see exactly why something was tagged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    id: str
    name: str
    description: str
    patterns: tuple[str, ...]
    engineering: bool = False   # counts towards the Engineering Lab
    research: bool = False      # counts towards Models & Research
    industry: bool = False      # counts towards AI Industry


TOPICS: tuple[Topic, ...] = (
    Topic("agents", "Agents", "AI agents, harnesses, multi-agent systems and orchestration", (
        r"agents?", r"agentic", r"multi[- ]agent", r"agent harness(es)?", r"harness", r"orchestrat\w*",
        r"computer[- ]use", r"browser[- ]use", r"coding agents?", r"swe[- ]?agent", r"autonomous agents?",
        r"a2a", r"crewai", r"autogen", r"langgraph", r"openhands", r"claude code", r"codex cli", r"subagents?",
    ), engineering=True),
    Topic("mcp", "MCP & Tools", "Model Context Protocol, tool calling and function calling", (
        r"mcp", r"model context protocol", r"tool[- ]calling", r"function[- ]calling", r"tool[- ]use",
        r"mcp servers?", r"structured outputs?",
    ), engineering=True),
    Topic("rag", "RAG & Retrieval", "Retrieval-augmented generation, embeddings, search, vector stores", (
        r"rag", r"retrieval[- ]augmented", r"retrieval", r"vector (database|db|store|search)", r"embeddings?",
        r"re-?rank\w*", r"semantic search", r"graph ?rag", r"hybrid search", r"chunking", r"knowledge graph",
    ), engineering=True),
    Topic("memory", "Memory & Context", "Agent memory, long context and context engineering", (
        r"agent memory", r"long[- ]term memory", r"memory layer", r"long[- ]context", r"context windows?",
        r"context engineering", r"context management", r"mem0", r"letta", r"memgpt", r"compaction",
    ), engineering=True),
    Topic("evals", "Evals & Observability", "Evaluations, benchmarks, tracing and monitoring", (
        r"evals?", r"evaluations?", r"benchmarks?", r"leaderboards?", r"observability", r"tracing",
        r"llm[- ]as[- ]a[- ]judge", r"red[- ]teaming", r"langfuse", r"swe[- ]bench\w*", r"arena",
    ), engineering=True, research=True),
    Topic("inference", "Inference & Optimization", "Serving, quantization, kernels and speed-ups", (
        r"inference", r"serving", r"quantiz\w+", r"vllm", r"llama\.cpp", r"gguf", r"kv[- ]cache",
        r"speculative decoding", r"tensorrt", r"sglang", r"distill\w*", r"cuda", r"kernels?", r"flash ?attention",
        r"throughput", r"tokens per second", r"latency", r"ollama", r"mlx", r"on[- ]device",
    ), engineering=True),
    Topic("infra", "AI Infrastructure", "Deployment, GPUs, MLOps and production platforms", (
        r"deploy\w*", r"mlops", r"llmops", r"gpus?", r"tpus?", r"clusters?", r"kubernetes", r"data ?cent(er|re)s?",
        r"production", r"gateway", r"litellm", r"scaling", r"compute", r"sandbox(es|ing)?",
    ), engineering=True),
    Topic("training", "Training & Fine-tuning", "Pre-training, post-training, RL and fine-tuning", (
        r"fine[- ]?tun\w+", r"rlhf", r"reinforcement learning", r"pre-?training", r"post-?training", r"lora",
        r"dpo", r"grpo", r"synthetic data", r"datasets?", r"unsloth", r"training run",
    ), research=True, engineering=True),
    Topic("models", "Models & APIs", "New models, model releases and API updates", (
        r"llms?", r"large language models?", r"language models?", r"foundation models?", r"open[- ]weights?",
        r"open[- ]source models?", r"reasoning models?", r"gpt-?\d[\w\.\-]*", r"o\d(-mini|-pro)?", r"claude",
        r"gemini", r"gemma", r"llama ?\d*", r"qwen\w*", r"mistral", r"mixtral", r"deepseek\w*", r"grok",
        r"phi-?\d", r"kimi", r"glm-?\d*", r"model release", r"new model", r"llm apis?", r"responses api", r"sonnet", r"opus", r"haiku",
    ), research=True),
    Topic("multimodal", "Multimodal", "Vision, audio, speech, image and video generation", (
        r"multimodal", r"vision[- ]language", r"vlms?", r"image generation", r"video generation", r"text[- ]to[- ](image|video|speech)",
        r"speech", r"tts", r"asr", r"voice", r"diffusion", r"world models?",
    ), research=True),
    Topic("devtools", "Developer Tools", "Coding assistants, SDKs, IDEs and AI developer products", (
        r"copilot", r"cursor", r"ide", r"sdks?", r"cli", r"code generation", r"coding assistants?",
        r"developer tools?", r"devtools", r"vibe coding", r"windsurf", r"code review",
    ), engineering=True),
    Topic("safety", "Safety & Security", "Security issues, prompt injection, alignment and interpretability", (
        r"safety", r"alignment", r"interpretability", r"jailbreaks?", r"prompt injection", r"security",
        r"vulnerabilit(y|ies)", r"cve-\d{4}-\d+", r"exploit\w*", r"malware", r"supply[- ]chain", r"data leak\w*",
    ), research=True, engineering=True),
    Topic("research", "Research", "Papers and scientific results", (
        r"paper", r"arxiv", r"preprint", r"we propose", r"state[- ]of[- ]the[- ]art", r"novel",
    ), research=True),
    Topic("industry", "Industry", "Startups, funding, launches, acquisitions and policy", (
        r"funding", r"raises?", r"raised", r"series [a-e]", r"seed round", r"valuation", r"acqui(res?|red|sition)",
        r"startups?", r"ipo", r"partnership", r"layoffs?", r"revenue", r"pricing", r"regulation", r"eu ai act",
        r"lawsuit", r"antitrust", r"launch(es|ed)?", r"\$\d+(\.\d+)? ?(m|b|million|billion)",
    ), industry=True),
)

TOPIC_BY_ID = {t.id: t for t in TOPICS}

# Strong signals that a text is about AI at all. Weak words like "model" or "agent" alone are not enough.
AI_STRONG = [
    r"ai", r"a\.i\.", r"artificial intelligence", r"machine learning", r"deep learning", r"neural( network)?s?",
    r"llms?", r"large language models?", r"language models?", r"gpt-?\d*\w*", r"chatgpt", r"openai", r"anthropic",
    r"claude", r"gemini", r"deepmind", r"hugging ?face", r"transformers?", r"diffusion", r"generative",
    r"genai", r"mistral", r"llama", r"qwen", r"deepseek", r"copilot", r"mcp", r"model context protocol", r"rag",
    r"embeddings?", r"fine[- ]?tun\w+", r"inference", r"vllm", r"ollama", r"agentic", r"ai agents?", r"multi-agent",
    r"prompt(s|ing)?", r"tokens?", r"chatbots?", r"nvidia", r"xai", r"grok", r"kimi", r"moonshot", r"perplexity",
    r"cursor", r"reinforcement learning", r"rlhf", r"benchmarks?", r"vector database", r"reasoning model",
]


def _compile(words) -> re.Pattern:
    return re.compile(r"(?<![\w\-])(?:" + "|".join(words) + r")(?![\w])", re.IGNORECASE)


_TOPIC_RES = {t.id: _compile(t.patterns) for t in TOPICS}
_AI_RE = _compile(AI_STRONG)
# "AI" must be upper case to count (avoid "ai" inside other words / names).
_AI_UPPER_RE = re.compile(r"(?<![\w])AI(?![\w])")


@dataclass
class Classification:
    topics: list[str]
    topic_hits: dict[str, int]
    ai_relevance: float  # 0..1
    ai_hits: int


def classify(title: str, text: str = "", extra_tags: list[str] | None = None) -> Classification:
    title = title or ""
    body = (text or "")[:4000]
    tags = " ".join(extra_tags or [])
    hits: dict[str, int] = {}
    for tid, rx in _TOPIC_RES.items():
        n = 3 * len(rx.findall(title)) + len(rx.findall(body)) + 2 * len(rx.findall(tags.replace("-", " ")))
        if n:
            hits[tid] = n
    ai_title = len(_AI_RE.findall(title)) + len(_AI_UPPER_RE.findall(title))
    ai_body = len(_AI_RE.findall(body)) + len(_AI_UPPER_RE.findall(body))
    ai_tags = len(_AI_RE.findall(tags.replace("-", " ")))
    ai_hits = ai_title * 3 + ai_body + ai_tags * 2
    # Smooth 0..1 relevance: a title mention alone is strong evidence.
    relevance = min(1.0, (ai_title * 0.45) + (min(ai_body, 8) * 0.07) + (min(ai_tags, 4) * 0.15))
    # Topics need a minimum signal; generic words in a long body should not tag everything.
    topics = [tid for tid, n in sorted(hits.items(), key=lambda kv: -kv[1]) if n >= 2]
    # "research" and "industry" are framing topics; keep them only when strongly indicated.
    for framing in ("research", "industry"):
        if framing in topics and hits[framing] < 3:
            topics.remove(framing)
    return Classification(topics=topics[:5], topic_hits=hits, ai_relevance=round(relevance, 3), ai_hits=ai_hits)


def topics_payload() -> list[dict]:
    return [{"id": t.id, "name": t.name, "description": t.description} for t in TOPICS]
