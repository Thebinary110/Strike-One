"""AI-layer configuration: .strikeone-ai.toml — items 5 and 7.

AI is DISABLED by default: no file, no provider, and every deterministic
command behaves exactly as it does today. The file stores provider,
base_url, model and the NAME of the credential env var. It never stores a
secret: the writer refuses to persist any value that equals the value of
an environment variable whose name matches *KEY* or *TOKEN* (asserted by
test), and `strikeone ai setup` only DETECTS env vars — it never asks
for one (a masked prompt still leaves the key in scrollback and any
recording buffer).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

AI_CONFIG_FILE = ".strikeone-ai.toml"


class CredentialLeakError(RuntimeError):
    pass


def _secret_values() -> set:
    vals = set()
    for name, val in os.environ.items():
        up = name.upper()
        if ("KEY" in up or "TOKEN" in up) and val and len(val) >= 8:
            vals.add(val)
    return vals


def guarded_write(path: Path | str, pairs: dict) -> None:
    """The ONLY writer of the AI config. Refuses to persist secrets."""
    secrets = _secret_values()
    for k, v in pairs.items():
        if str(v) in secrets:
            raise CredentialLeakError(
                f"refusing to write {k!r}: its value matches a *KEY*/*TOKEN* "
                "environment variable. Credentials stay in the environment; "
                "the config stores only the env var's NAME.")
        if k.lower() in ("api_key", "apikey", "token", "secret"):
            raise CredentialLeakError(
                f"refusing to write a field named {k!r}; store the env var "
                "NAME under api_key_env instead.")
    lines = ["[ai]"] + [f'{k} = "{v}"' for k, v in pairs.items()]
    Path(path).write_text("\n".join(lines) + "\n")


@dataclass
class AIConfig:
    provider: str = ""        # "ollama" | "openai-compatible"
    model: str = ""
    base_url: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    think: str = ""           # "" | "on" | "off" (ollama hybrid reasoners)

    @staticmethod
    def load(path: Path | str = AI_CONFIG_FILE) -> "AIConfig | None":
        p = Path(path)
        if not p.exists():
            return None
        import tomllib
        raw = tomllib.loads(p.read_text()).get("ai", {})
        if not raw.get("provider"):
            return None
        return AIConfig(provider=raw.get("provider", ""),
                        model=raw.get("model", ""),
                        base_url=raw.get("base_url", ""),
                        api_key_env=raw.get("api_key_env", "OPENAI_API_KEY"),
                        think=raw.get("think", ""))

    def save(self, path: Path | str = AI_CONFIG_FILE) -> None:
        pairs = {"provider": self.provider, "model": self.model}
        if self.base_url:
            pairs["base_url"] = self.base_url
        if self.think:
            pairs["think"] = self.think
        if self.provider == "openai-compatible":
            pairs["api_key_env"] = self.api_key_env
        guarded_write(path, pairs)

    def build(self):
        from strikeone.ai.providers import (OllamaProvider,
                                            OpenAICompatibleProvider)
        if self.provider == "ollama":
            think = {"on": True, "off": False}.get(self.think)
            return OllamaProvider(model=self.model,
                                  base_url=self.base_url
                                  or "http://localhost:11434",
                                  think=think)
        if self.provider == "openai-compatible":
            if not self.base_url:
                raise ValueError("openai-compatible needs base_url")
            return OpenAICompatibleProvider(model=self.model,
                                            base_url=self.base_url,
                                            api_key_env=self.api_key_env)
        raise ValueError(f"unknown provider {self.provider!r}")


KNOWN_KEY_ENVS = ["OPENAI_API_KEY", "OPENROUTER_API_KEY"]


def detect_env() -> list:
    """Names (never values) of known credential env vars that are set."""
    return [n for n in KNOWN_KEY_ENVS if os.environ.get(n)]
