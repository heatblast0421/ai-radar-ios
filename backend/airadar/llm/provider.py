"""LLM provider abstraction. The provider is detected from the API key format, so one secret
(LLM_API_KEY) is all that is needed:

    gsk_...   -> Groq (OpenAI-compatible, has a free tier)
    xai-...   -> xAI Grok
    AIza...   -> Google Gemini (OpenAI-compatible endpoint)
    sk-ant-.. -> Anthropic Claude
    sk-...    -> OpenAI

LLM_PROVIDER / LLM_BASE_URL / LLM_MODEL override detection when needed.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ..http import FetchError, Http

log = logging.getLogger("airadar.llm")

PROVIDERS = {
    "groq": {"base": "https://api.groq.com/openai/v1", "prefs": [
        "openai/gpt-oss-120b", "llama-3.3-70b-versatile", "moonshotai/kimi-k2-instruct-0905", "moonshotai/kimi-k2-instruct",
        "qwen/qwen3-32b", "meta-llama/llama-4-maverick-17b-128e-instruct", "openai/gpt-oss-20b", "llama-3.1-8b-instant"]},
    "xai": {"base": "https://api.x.ai/v1", "prefs": [
        "grok-4-fast-non-reasoning", "grok-4-1-fast-non-reasoning", "grok-4-fast", "grok-3-mini", "grok-4"]},
    "gemini": {"base": "https://generativelanguage.googleapis.com/v1beta/openai", "prefs": [
        "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-2.5-flash-lite", "gemini-2.5-flash"]},
    "openai": {"base": "https://api.openai.com/v1", "prefs": ["gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini"]},
    "anthropic": {"base": "https://api.anthropic.com/v1", "prefs": [
        "claude-haiku-5-5", "claude-haiku-4-5", "claude-3-5-haiku-latest"]},
}
_EXCLUDE = re.compile(r"(?i)whisper|guard|tts|embed|audio|image|vision-only|playai|compound|safeguard|moderation|transcribe|live|imagen|veo")


def detect_provider(key: str) -> str:
    if key.startswith("gsk_"):
        return "groq"
    if key.startswith("xai-"):
        return "xai"
    if key.startswith("AIza"):
        return "gemini"
    if key.startswith("sk-ant-"):
        return "anthropic"
    return "openai"


class LLMUnavailable(Exception):
    """Raised when the provider is rate limited or down; the pipeline continues without AI text."""


@dataclass
class LLMResponse:
    data: dict
    input_tokens: int | None
    output_tokens: int | None


class LLM:
    def __init__(self, api_key: str, http: Http, provider: str | None = None, model: str | None = None,
                 base_url: str | None = None):
        self.key = api_key
        self.http = http
        self.provider = provider or detect_provider(api_key)
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown LLM provider {self.provider}")
        self.base = (base_url or PROVIDERS[self.provider]["base"]).rstrip("/")
        self._model = model

    # -------------------------------------------------------------- model selection
    @property
    def model(self) -> str:
        if not self._model:
            self._model = self._pick_model()
        return self._model

    def _pick_model(self) -> str:
        prefs = PROVIDERS[self.provider]["prefs"]
        try:
            available = self.list_models()
        except Exception as exc:  # listing is a nicety; fall back to the first preference
            log.warning("could not list models (%s); using %s", exc, prefs[0])
            return prefs[0]
        ids = [m for m in available if not _EXCLUDE.search(m)]
        norm = {m.split("/", 1)[-1] if self.provider == "gemini" else m: m for m in ids}
        for p in prefs:
            if p in norm:
                return norm[p]
        # newest-looking fallback inside the same family
        family = {"groq": "llama", "xai": "grok", "gemini": "flash", "openai": "mini", "anthropic": "haiku"}[self.provider]
        fam = sorted([m for m in ids if family in m], reverse=True)
        if fam:
            return fam[0]
        if ids:
            return ids[0]
        return prefs[0]

    def list_models(self) -> list[str]:
        if self.provider == "anthropic":
            resp = self.http.get(f"{self.base}/models", headers=self._anthropic_headers())
            return [m["id"] for m in resp.json().get("data", [])]
        resp = self.http.get(f"{self.base}/models", headers={"Authorization": f"Bearer {self.key}"})
        data = resp.json().get("data", [])
        return [m.get("id", "").removeprefix("models/") for m in data if m.get("id")]

    def _anthropic_headers(self) -> dict:
        return {"x-api-key": self.key, "anthropic-version": "2023-06-01"}

    # -------------------------------------------------------------- calls
    def json_call(self, system: str, user: str, max_tokens: int = 1800, temperature: float = 0.2) -> LLMResponse:
        try:
            if self.provider == "anthropic":
                return self._anthropic(system, user, max_tokens, temperature)
            return self._openai_compatible(system, user, max_tokens, temperature)
        except FetchError as exc:
            if exc.status in (401, 403):
                raise LLMUnavailable(f"API key rejected by {self.provider} (HTTP {exc.status})") from exc
            if exc.status in (429, 500, 502, 503, 504, None):
                raise LLMUnavailable(f"{self.provider} unavailable or rate limited: {exc}") from exc
            raise

    def _openai_compatible(self, system, user, max_tokens, temperature) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self.provider == "groq" and "gpt-oss" in self.model:
            body["reasoning_effort"] = "low"
            body["max_tokens"] = max_tokens + 1200  # reasoning tokens count against the limit
        try:
            resp = self.http.request("POST", f"{self.base}/chat/completions", json=body, max_wait=40,
                                     headers={"Authorization": f"Bearer {self.key}"})
        except FetchError as exc:
            if exc.status == 400 and "response_format" in str(exc):
                body.pop("response_format", None)
                resp = self.http.request("POST", f"{self.base}/chat/completions", json=body, max_wait=40,
                                         headers={"Authorization": f"Bearer {self.key}"})
            else:
                raise
        payload = resp.json()
        text = payload["choices"][0]["message"].get("content") or ""
        usage = payload.get("usage") or {}
        return LLMResponse(parse_json(text), usage.get("prompt_tokens"), usage.get("completion_tokens"))

    def _anthropic(self, system, user, max_tokens, temperature) -> LLMResponse:
        body = {"model": self.model, "system": system, "max_tokens": max_tokens, "temperature": temperature,
                "messages": [{"role": "user", "content": user}]}
        resp = self.http.request("POST", f"{self.base}/messages", json=body, headers=self._anthropic_headers(), max_wait=40)
        payload = resp.json()
        text = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text")
        usage = payload.get("usage") or {}
        return LLMResponse(parse_json(text), usage.get("input_tokens"), usage.get("output_tokens"))


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise ValueError("model did not return JSON")
