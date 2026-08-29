"""One interface, two adapters — item 3.

    AIProvider (abstract)
      ├── OllamaProvider              local, http://localhost:11434
      └── OpenAICompatibleProvider    base_url + model slug

The second adapter covers OpenAI, OpenRouter, Ollama Cloud and any custom
endpoint; there is deliberately no bespoke per-vendor adapter. Credentials
are env vars only (item 5): the config stores the NAME of the env var,
never a value. Every reply records which model actually answered — an
explanation that doesn't name its author is a hole.

No third-party HTTP dependency: urllib from the standard library.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass


class ProviderError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    model: str          # the model that actually answered
    provider_label: str


def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise ProviderError(f"provider unreachable at {url}: {e}") from e


class AIProvider(ABC):
    """Narrates a finished evidence contract. Never chooses tools, never
    computes: the deterministic router ran before this object was called."""

    @abstractmethod
    def narrate(self, system_prompt: str, user_prompt: str) -> Reply: ...

    @abstractmethod
    def chain_text(self) -> str:
        """Item 6: show the evidence path, not just the destination."""


class OllamaProvider(AIProvider):
    def __init__(self, model: str, base_url: str = "http://localhost:11434",
                 timeout: float = 180.0, think: bool | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.think = think  # False = ask hybrid-reasoning models to skip
        #                     the thinking pass (narration needs none)

    def narrate(self, system_prompt: str, user_prompt: str) -> Reply:
        payload = {"model": self.model, "stream": False,
                   "options": {"temperature": 0.0},
                   "messages": [{"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}]}
        if self.think is not None:
            payload["think"] = self.think
        try:
            out = _post_json(f"{self.base_url}/api/chat", payload,
                             {}, self.timeout)
        except ProviderError:
            if "think" not in payload:
                raise
            payload.pop("think")  # model may not support the flag
            out = _post_json(f"{self.base_url}/api/chat", payload,
                             {}, self.timeout)
        return Reply(text=out.get("message", {}).get("content", ""),
                     model=out.get("model", self.model),
                     provider_label="ollama, local")

    def chain_text(self) -> str:
        return "\n".join([
            f"Provider: Ollama (local)   Model: {self.model}",
            f"Endpoint: {self.base_url}",
            "Evidence leaves this machine: NO",
        ])


class OpenAICompatibleProvider(AIProvider):
    """OpenAI, OpenRouter, Ollama Cloud, or any /v1-compatible endpoint."""

    def __init__(self, model: str, base_url: str,
                 api_key_env: str = "OPENAI_API_KEY", timeout: float = 120.0):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env   # the NAME; the value stays in env
        self.timeout = timeout

    def _key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ProviderError(
                f"env var {self.api_key_env} is not set. Export it and "
                "retry; strikeone never stores or prompts for secrets.")
        return key

    def narrate(self, system_prompt: str, user_prompt: str) -> Reply:
        out = _post_json(
            f"{self.base_url}/chat/completions",
            {"model": self.model, "temperature": 0.0,
             "messages": [{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_prompt}]},
            {"Authorization": f"Bearer {self._key()}"}, self.timeout)
        try:
            text = out["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise ProviderError(f"unexpected response shape: {out}") from e
        answered = out.get("model", self.model)  # aggregators may rewrite
        return Reply(text=text, model=answered,
                     provider_label=f"{self._host()}, remote")

    def _host(self) -> str:
        return self.base_url.split("//", 1)[-1].split("/", 1)[0]

    def chain_text(self) -> str:
        host = self._host()
        lines = [f"Provider: {host}       Model: {self.model}"]
        if "openrouter" in host:
            upstream = self.model.split("/", 1)[0] if "/" in self.model \
                else "the routed provider"
            lines += [
                f"Evidence path: this machine → {host} → {upstream}",
                "(an aggregator is two parties, not one)",
            ]
        else:
            lines.append(f"Evidence path: this machine → {host}")
        lines += [
            "Sent: decision evidence only (no raw transactions, no "
            "holdout data)",
            f"Credential: env var {self.api_key_env} "
            "(never stored, never prompted for)",
        ]
        return "\n".join(lines)
