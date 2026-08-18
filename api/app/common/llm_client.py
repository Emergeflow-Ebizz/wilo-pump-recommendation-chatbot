"""Provider-agnostic LLM client wrapper.

All SDK-specific calls are isolated here so the rest of the app (llm_parser,
llm_explainer) never imports a provider SDK directly. Swapping providers only
means changing this file's internals, not any caller.
"""
import json
import logging
import os
from contextvars import ContextVar

# Set by main.py's rate_limit_and_log middleware to the endpoint and client
# IP that triggered the current LLM call(s), so per-call cost log rows
# (below) can be traced back to the request - and the caller - that caused
# them, not just which endpoint was hit.
current_endpoint: ContextVar[str] = ContextVar("current_endpoint", default="unknown")
current_client_ip: ContextVar[str] = ContextVar("current_client_ip", default="unknown")

_llm_cost_logger = logging.getLogger("wilo_pump_chatbot.llm_cost")

# Approximate list pricing, USD per million tokens - used only to estimate
# cost in the per-call log rows below, not for billing. claude-sonnet-5 is
# at introductory pricing through 2026-08-31; update to $3.00/$15.00 after
# that, and re-check all three whenever Anthropic changes pricing.
_COST_PER_MTOK = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}


def _estimate_cost_usd(model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    prices = _COST_PER_MTOK.get(model)
    if prices is None or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


def _log_llm_call(
    model: str, attempt: int, input_tokens: int | None, output_tokens: int | None,
    duration_ms: float, stop_reason: str | None,
) -> None:
    cost_usd = _estimate_cost_usd(model, input_tokens, output_tokens)
    endpoint = current_endpoint.get()
    client_ip = current_client_ip.get()
    max_tokens_hit = stop_reason == "max_tokens"
    # `extra` fields land as attributes on the LogRecord - sheets_logger.py
    # reads them directly to build one column per field in the LLM_Calls
    # sheet, rather than cramming everything into a single message string.
    _llm_cost_logger.warning(
        "endpoint=%s attempt=%d model=%s cost_usd=%s stop_reason=%s",
        endpoint, attempt, model, f"{cost_usd:.6f}" if cost_usd is not None else "n/a", stop_reason,
        extra={
            "llm_endpoint": endpoint,
            "llm_attempt": attempt,
            "llm_model": model,
            "llm_input_tokens": input_tokens,
            "llm_output_tokens": output_tokens,
            "llm_cost_usd": cost_usd,
            "llm_duration_ms": duration_ms,
            "llm_stop_reason": stop_reason,
            "llm_max_tokens_hit": max_tokens_hit,
            "llm_client_ip": client_ip,
        },
    )


class LLMUnavailableError(Exception):
    """Raised when no LLM provider/API key is configured, or the call fails."""


def _get_config() -> tuple[str, str, str]:
    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    api_key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL", "claude-sonnet-5")
    if not api_key:
        raise LLMUnavailableError("LLM_API_KEY is not configured")
    return provider, api_key, model


def complete(system_prompt: str, user_prompt: str, *, json_schema: dict | None = None, temperature: float | None = None) -> str:
    """Send a single-turn prompt to the configured LLM provider and return text.

    If json_schema is given, the provider is forced to call a tool whose
    input matches that schema - the API itself returns a parsed JSON object
    (no free text, no markdown fences to strip), which is re-serialized here
    so callers can json.loads() it uniformly.

    temperature: optional override. If None, uses default (0 for schema calls,
    1.0 for text). Pass explicitly to override.

    Raises LLMUnavailableError if not configured or the call fails, so callers
    can degrade gracefully.
    """
    provider, api_key, model = _get_config()

    try:
        if provider == "anthropic":
            return _complete_anthropic(api_key, model, system_prompt, user_prompt, json_schema, temperature)
        raise LLMUnavailableError(f"Unsupported LLM_PROVIDER: {provider}")
    except LLMUnavailableError:
        raise
    except Exception as e:
        raise LLMUnavailableError(f"LLM call failed: {e}") from e


def _complete_anthropic(
    api_key: str, model: str, system_prompt: str, user_prompt: str, json_schema: dict | None, temperature: float | None = None
) -> str:
    # Calls the Anthropic REST API directly over HTTP instead of using the
    # `anthropic` SDK, which depends on the native `jiter` extension - that
    # extension is blocked by this machine's Application Control policy.
    import httpx
    import time

    # Determine max_tokens and temperature based on whether structured output
    # (tool-use with schema) is being used. Structured calls are just extracting
    # JSON from a fixed schema - they need less headroom and zero temperature
    # for determinism. Unstructured text calls get standard tokens and temp.
    max_tokens = 256 if json_schema else 1024
    if temperature is None:
        temperature = 0.0 if json_schema else 1.0

    request_body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    if json_schema is not None:
        # Force structured output via tool-use: the API parses the model's
        # output against this schema server-side and returns it as an
        # actual JSON object in a tool_use block, not free text.
        request_body["tools"] = [
            {
                "name": "respond",
                "description": "Provide your structured response.",
                "input_schema": json_schema,
            }
        ]
        request_body["tool_choice"] = {"type": "tool", "name": "respond"}

    max_retries = 1
    for attempt in range(max_retries + 1):
        attempt_start = time.monotonic()
        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=request_body,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage", {})
            _log_llm_call(
                model, attempt + 1, usage.get("input_tokens"), usage.get("output_tokens"),
                (time.monotonic() - attempt_start) * 1000, data.get("stop_reason"),
            )
            break
        except httpx.HTTPStatusError as e:
            _log_llm_call(model, attempt + 1, None, None, (time.monotonic() - attempt_start) * 1000, f"error:{e.response.status_code}")
            # A response did come back, just with a bad status - retry once
            # on transient 5xx or 429 (rate limit).
            if attempt < max_retries and e.response.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.5)
                continue
            raise
        except httpx.RequestError as e:
            _log_llm_call(model, attempt + 1, None, None, (time.monotonic() - attempt_start) * 1000, f"error:{type(e).__name__}")
            # The request itself never completed (timeout, connection reset,
            # DNS failure, etc.) - there's no response object to inspect here,
            # unlike HTTPStatusError above. Retry once, since these are
            # typically transient too.
            if attempt < max_retries:
                time.sleep(0.5)
                continue
            raise

    if json_schema is not None:
        tool_use = next(block for block in data["content"] if block["type"] == "tool_use")
        return json.dumps(tool_use["input"])

    return "".join(block["text"] for block in data["content"] if block["type"] == "text")
