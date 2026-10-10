"""Minimal Anthropic Messages API client for structured classification.

Every call forces one tool so the reply is a JSON object that matches the
tool's input schema. Standard library only; errors never include the key.
"""
import json
import time
import urllib.error
import urllib.request

API_VERSION = "2023-06-01"
RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}


class LLMError(Exception):
    """A classification call failed. `code` is safe to store and display."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class AnthropicClient:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.anthropic.com",
                 timeout: float = 90.0, max_retries: int = 2):
        self._key, self.model, self._url = api_key, model, base_url.rstrip("/") + "/v1/messages"
        self._timeout, self._retries = timeout, max_retries

    def tool_call(self, *, system: str, prompt: str, tool: dict, max_tokens: int = 2048) -> dict:
        """Return the forced tool's input object."""
        body = json.dumps({
            "model": self.model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [tool], "tool_choice": {"type": "tool", "name": tool["name"]},
        }).encode("utf-8")
        headers = {"x-api-key": self._key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        for attempt in range(self._retries + 1):
            request = urllib.request.Request(self._url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    payload = json.load(response)
                break
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()
                if status in (401, 403):
                    raise LLMError("llm_unauthorized")
                if status not in RETRYABLE or attempt == self._retries:
                    raise LLMError(f"llm_http_{status}")
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == self._retries:
                    raise LLMError("llm_unreachable")
            except ValueError:
                raise LLMError("llm_invalid_response")
            time.sleep(min(8.0, 1.0 * 2 ** attempt))
        for block in payload.get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == tool["name"] and isinstance(block.get("input"), dict):
                return block["input"]
        raise LLMError("llm_no_tool_result")


def from_settings(settings):
    if not settings.llm_api_key:
        return None
    return AnthropicClient(settings.llm_api_key, settings.llm_model, settings.llm_base_url)
