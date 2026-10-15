"""Minimal Anthropic Messages API client for structured output.

Every call offers one tool and asks Claude to answer by calling it, so the
reply is a JSON object matching the tool's input schema. (Current models
reject a forced tool_choice, so the request uses "auto" plus an instruction.)
Standard library only; errors never include the key.
"""
import json
import time
import urllib.error
import urllib.request

API_VERSION = "2023-06-01"
RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}
# Models that take output_config.effort, and those that accept the server-side
# fallback a refused request can retry on.
EFFORT_MODELS = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable-5", "claude-opus-4-8", "claude-opus-4-7")
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """A classification call failed. `code` is safe to store and display."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class AnthropicClient:
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.anthropic.com",
                 timeout: float = 120.0, max_retries: int = 2, effort: str = "low"):
        self._key, self.model, self._url = api_key, model, base_url.rstrip("/") + "/v1/messages"
        self._timeout, self._retries, self.effort = timeout, max_retries, effort
        self._first_party = base_url.rstrip("/") == "https://api.anthropic.com"

    def tool_call(self, *, system: str, prompt: str, tool: dict, max_tokens: int = 2048) -> dict:
        """Return the input object of the tool Claude calls."""
        request = {
            "model": self.model,
            # Thinking shares this budget on current models, so leave room for it.
            "max_tokens": max(max_tokens, 4096),
            "system": f"{system}\n\nRespond only by calling the {tool['name']} tool.",
            "messages": [{"role": "user", "content": prompt}],
            "tools": [tool], "tool_choice": {"type": "auto"},
        }
        if self.model.startswith(EFFORT_MODELS):
            request["output_config"] = {"effort": self.effort}
        headers = {"x-api-key": self._key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        if self._first_party and self.model in FALLBACK_MODELS:
            # A request Claude declines on safety grounds is retried on a fallback model.
            request["fallbacks"] = "default"
            headers["anthropic-beta"] = FALLBACK_BETA
        body = json.dumps(request).encode("utf-8")
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
        if payload.get("stop_reason") == "refusal":
            raise LLMError("llm_refused")
        for block in payload.get("content") or []:
            if block.get("type") == "tool_use" and block.get("name") == tool["name"] and isinstance(block.get("input"), dict):
                return block["input"]
        raise LLMError("llm_no_tool_result")


def from_settings(settings):
    if not settings.llm_api_key:
        return None
    return AnthropicClient(settings.llm_api_key, settings.llm_model, settings.llm_base_url)
