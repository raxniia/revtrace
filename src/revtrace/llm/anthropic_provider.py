from __future__ import annotations

import anthropic

from .base import Completion, LLMError, Message, ToolCall, ToolSpec


def to_anthropic(messages: list[Message]) -> list[dict]:
    out: list[dict] = []
    for message in messages:
        if message.role == "tool":
            block = {"type": "tool_result", "tool_use_id": message.tool_call_id, "content": message.content}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        elif message.role == "assistant":
            blocks: list[dict] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks += [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                for c in message.tool_calls
            ]
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": "user", "content": message.content})
    return out


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self, model: str, api_key: str, base_url: str = "", client: anthropic.Anthropic | None = None
    ):
        self.model = model
        self.client = client or anthropic.Anthropic(api_key=api_key, base_url=base_url or None, max_retries=3)

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
            "max_tokens": max_tokens,
            "system": system,
            "messages": to_anthropic(messages),
        }
        if tools:
            request["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]
            if force_tool:
                request["tool_choice"] = {"type": "tool", "name": force_tool}
        try:
            response = self.client.messages.create(**request)
        except anthropic.APIError as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc
        text = "".join(block.text for block in response.content if block.type == "text")
        calls = [
            ToolCall(block.id, block.name, dict(block.input))
            for block in response.content
            if block.type == "tool_use"
        ]
        return Completion(text, calls, response.usage.input_tokens, response.usage.output_tokens)
