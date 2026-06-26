from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_VSEGPT_BASE_URL = "https://api.vsegpt.ru/v1"
DEFAULT_VSEGPT_MODEL = "openai/gpt-4o-mini"


class LLMConfigurationError(RuntimeError):
    """Raised when the LLM provider is not configured enough to run."""


class LLMRequestError(RuntimeError):
    """Raised when the LLM provider returns an error response."""


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    api_key: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    response_format: dict[str, str] | None
    title: str = "DataCon ChemX checker"

    @classmethod
    def from_env(
        cls,
        *,
        provider: str = "vsegpt",
        model: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        use_response_format: bool = True,
    ) -> "LLMConfig":
        provider_key = provider.upper().replace("-", "_")
        api_key_names = [f"{provider_key}_API_KEY", "LLM_API_KEY"]
        if provider_key == "VSEGPT":
            api_key_names.insert(1, "VSEGPT_API_KEY")
        elif provider_key == "OPENAI":
            api_key_names.insert(1, "OPENAI_API_KEY")
        api_key = next((os.getenv(name, "").strip() for name in api_key_names if os.getenv(name, "").strip()), "")
        if not api_key:
            raise LLMConfigurationError(
                "LLM API key is not configured. Set VSEGPT_API_KEY in the environment or in a local .env file."
            )

        resolved_base_url = (
            base_url
            or os.getenv(f"{provider_key}_BASE_URL")
            or os.getenv("VSEGPT_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or DEFAULT_VSEGPT_BASE_URL
        ).strip()
        resolved_model = (
            model
            or os.getenv(f"{provider_key}_MODEL")
            or os.getenv("VSEGPT_MODEL")
            or os.getenv("LLM_MODEL")
            or DEFAULT_VSEGPT_MODEL
        ).strip()

        return cls(
            provider=provider,
            api_key=api_key,
            base_url=resolved_base_url.rstrip("/"),
            model=resolved_model,
            temperature=_env_float(f"{provider_key}_TEMPERATURE", temperature, default=0.01),
            max_tokens=_env_int(f"{provider_key}_MAX_TOKENS", max_tokens, default=4000),
            timeout_seconds=_env_float(f"{provider_key}_TIMEOUT", timeout_seconds, default=120.0),
            response_format={"type": "json_output"} if use_response_format else None,
        )

    @property
    def chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "response_format": self.response_format,
            "api_key": _redact(self.api_key),
        }


class ChatCompletionsClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def complete(self, *, system: str, user: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "n": 1,
        }
        if self.config.response_format:
            payload["response_format"] = self.config.response_format

        request = urllib.request.Request(
            self.config.chat_completions_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "X-Title": self.config.title,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise LLMRequestError(f"LLM request failed with HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise LLMRequestError(f"LLM request failed: {exc}") from exc

        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise LLMRequestError(f"LLM provider returned non-JSON response: {body[:500]}") from exc

        content = _extract_chat_content(result)
        parsed, parse_error = extract_json_payload(content)
        return {
            "provider_response": result,
            "content": content,
            "parsed_json": parsed,
            "parse_error": parse_error,
            "usage": result.get("usage"),
        }


def load_env_file(path: Path) -> bool:
    if not path.exists():
        return False

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return True


def extract_json_payload(content: str) -> tuple[Any | None, str | None]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)

    for candidate in (text, _between(text, "[", "]"), _between(text, "{", "}")):
        if candidate is None:
            continue
        try:
            return json.loads(candidate), None
        except json.JSONDecodeError as exc:
            last_error = str(exc)
    return None, last_error if "last_error" in locals() else "No JSON object or array found in model response."


def _extract_chat_content(result: dict[str, Any]) -> str:
    choices = result.get("choices") or []
    if not choices:
        raise LLMRequestError(f"LLM response has no choices: {json.dumps(result, ensure_ascii=False)[:500]}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [part.get("text", "") for part in content if isinstance(part, dict)]
        return "\n".join(part for part in parts if part)
    raise LLMRequestError(f"LLM response has no message.content: {json.dumps(result, ensure_ascii=False)[:500]}")


def _between(text: str, start: str, end: str) -> str | None:
    left = text.find(start)
    right = text.rfind(end)
    if left == -1 or right == -1 or right <= left:
        return None
    return text[left : right + 1]


def _env_float(key: str, value: float | None, *, default: float) -> float:
    if value is not None:
        return value
    raw = os.getenv(key)
    return float(raw) if raw else default


def _env_int(key: str, value: int | None, *, default: int) -> int:
    if value is not None:
        return value
    raw = os.getenv(key)
    return int(raw) if raw else default


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"
