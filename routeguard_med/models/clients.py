"""LLM/local-model clients for RouteGuard-Med.

Supports OpenAI, OpenAI-compatible APIs such as some Qwen/DeepSeek/GLM gateways,
and Ollama local models. The public demo does not require any paid API.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


@dataclass
class ChatResponse:
    text: str
    raw: Dict[str, Any] | None = None


class BaseChatClient:
    def chat(self, system: str, user: str, temperature: float = 0.0) -> ChatResponse:
        raise NotImplementedError


class OpenAICompatibleClient(BaseChatClient):
    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        try:
            from openai import OpenAI
        except Exception as e:
            raise RuntimeError("Install OpenAI SDK: pip install openai") from e
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model

    def chat(self, system: str, user: str, temperature: float = 0.0) -> ChatResponse:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return ChatResponse(text=resp.choices[0].message.content or "", raw=resp.model_dump())


class OllamaClient(BaseChatClient):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:3b"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(self, system: str, user: str, temperature: float = 0.0) -> ChatResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": temperature},
        }
        r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        return ChatResponse(text=data.get("message", {}).get("content", ""), raw=data)


class StubClient(BaseChatClient):
    def chat(self, system: str, user: str, temperature: float = 0.0) -> ChatResponse:
        return ChatResponse(text=json.dumps({"action": "retrieve", "confidence": 0.5, "rationale": "Stub client fallback."}))
