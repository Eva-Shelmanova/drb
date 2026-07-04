from __future__ import annotations

from typing import Any

import requests

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


class OpenRouterClient:
    """Small OpenAI-compatible OpenRouter chat client."""

    def __init__(
        self,
        api_key: str,
        base_url: str = OPENROUTER_BASE_URL,
        timeout_seconds: int = 600,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def chat_completion(
        self,
        model_slug: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
        extra_body: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model_slug,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if extra_body:
            payload.update(extra_body)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            url=url,
            json=payload,
            headers=headers,
            timeout=(15, self.timeout_seconds),  # (connect_timeout, read_timeout)
        )

        raw_json: dict[str, Any] = {}
        try:
            raw_json = response.json()
        except Exception:
            pass

        if not response.ok:
            error_obj = raw_json.get("error", {})
            if isinstance(error_obj, dict):
                code = error_obj.get("code", response.status_code)
                msg = error_obj.get("message", "Unknown OpenRouter error")
                raise requests.HTTPError(
                    f"OpenRouter error (code={code}): {msg}",
                    response=response,
                )
            raise requests.HTTPError(
                f"OpenRouter error: {raw_json or response.text}",
                response=response,
            )

        choices = raw_json.get("choices", [])
        text = ""
        if choices:
            choice = choices[0]
            message = choice.get("message", {})
            content = message.get("content", "")
            text = _extract_text_content(content)
            if not text and choice.get("finish_reason") == "length":
                raise ValueError(
                    "Response truncated: model hit max_tokens before producing output "
                    "(finish_reason=length). Increase --max-tokens or reduce prompt size."
                )

        usage: dict[str, Any] | None = raw_json.get("usage")
        return text, raw_json, usage
