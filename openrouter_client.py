#!/usr/bin/env python3
"""Small OpenRouter utility for calling an LLM with a prompt."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OpenRouterError(RuntimeError):
    """Raised when OpenRouter returns an error or an unexpected response."""


def load_env_file(path: Path) -> None:
    """Load simple KEY: VALUE or KEY=VALUE pairs into os.environ if unset."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        separator = ":" if ":" in line else "=" if "=" in line else None
        if not separator:
            continue

        key, value = line.split(separator, 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def load_default_env_files() -> None:
    for filename in ("env.yaml", "ENV.yaml", ".env"):
        load_env_file(Path(filename))


@dataclass
class OpenRouterClient:
    api_key: str | None = None
    model: str = "openrouter/owl-alpha"
    base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    timeout: int = 60
    site_url: str | None = None
    app_name: str | None = None

    def __post_init__(self) -> None:
        load_default_env_files()
        self.api_key = self.api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise OpenRouterError("Missing OpenRouter API key. Set OPENROUTER_API_KEY or pass api_key.")

    def ask(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> str:
        """Send a prompt to OpenRouter and return the assistant response text."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if extra_body:
            body.update(extra_body)

        response = self._post(body)
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError(f"Unexpected OpenRouter response: {response}") from exc

        if not isinstance(content, str):
            raise OpenRouterError(f"Unexpected OpenRouter message content: {content!r}")
        return content

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            headers["X-Title"] = self.app_name

        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw_response = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise OpenRouterError(f"OpenRouter HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise OpenRouterError(f"Failed to call OpenRouter: {exc}") from exc

        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            raise OpenRouterError(f"OpenRouter returned invalid JSON: {raw_response}") from exc

        if not isinstance(parsed, dict):
            raise OpenRouterError(f"OpenRouter returned unexpected JSON: {parsed!r}")
        if "error" in parsed:
            raise OpenRouterError(f"OpenRouter error: {parsed['error']}")
        return parsed


if __name__ == "__main__":
    client = OpenRouterClient()
    print(client.ask("Reply with a one-sentence hello."))
