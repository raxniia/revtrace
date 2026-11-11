from __future__ import annotations

import json

import openai

from .base import Completion, LLMError, Message, ToolCall, ToolSpec


def to_openai(system: str, messages: list[Message]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for message in messages:
        if message.role == "tool":
            out.append({"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content})
        elif message.role == "assistant":
            entry: dict = {"role": "assistant", "content": message.content or None}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": json.dumps(c.arguments, ensure_ascii=False),
                        },
                    }
                    for c in message.tool_calls
                ]
            out.append(entry)
        else:
            out.append({"role": "user", "content": message.content})
    return out


def _parse_arguments(raw: str | None) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, api_key: str, base_url: str = "", client: openai.OpenAI | None = None):
        if not model:
            raise LLMError("REVTRACE_MODEL is required for the openai provider")
        self.model = model
        self.client = client or openai.OpenAI(
            api_key=api_key or "not-needed", base_url=base_url or None, max_retries=3
        )

    def complete(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        force_tool: str | None = None,
        max_tokens: int = 2000,
    ) -> Completion:
        request: dict = {
            "model": self.model,
            "messages": to_openai(system, messages),
            "max_completion_tokens": max_tokens,
        }
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
            if force_tool:
                request["tool_choice"] = {"type": "function", "function": {"name": force_tool}}
        try:
            try:
                response = self.client.chat.completions.create(**request)
            except openai.BadRequestError as exc:
                if "max_completion_tokens" not in str(exc):
                    raise
                request["max_tokens"] = request.pop("max_completion_tokens")
                response = self.client.chat.completions.create(**request)
        except openai.APIError as exc:
            raise LLMError(f"OpenAI-compatible request failed: {exc}") from exc
        message = response.choices[0].message
        calls = [
            ToolCall(c.id, c.function.name, _parse_arguments(c.function.arguments))
            for c in (message.tool_calls or [])
            if c.type == "function"
        ]
        usage = response.usage
        return Completion(
            message.content or "",
            calls,
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )
