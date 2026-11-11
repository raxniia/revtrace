from __future__ import annotations

from types import SimpleNamespace

from anthropic.types import Message as AnthropicMessage
from openai.types.chat import ChatCompletion

from revtrace.llm import Message, ToolCall, ToolSpec
from revtrace.llm.anthropic_provider import AnthropicProvider, to_anthropic
from revtrace.llm.openai_provider import OpenAIProvider, to_openai

HISTORY = [
    Message("user", "why?"),
    Message(
        "assistant",
        "checking",
        [ToolCall("c1", "lookup", {"month": "2026-10"}), ToolCall("c2", "lookup", {})],
    ),
    Message("tool", '{"a": 1}', tool_call_id="c1"),
    Message("tool", '{"b": 2}', tool_call_id="c2"),
]
SPEC = ToolSpec("lookup", "Look something up", {"type": "object", "properties": {}, "required": []})


def test_anthropic_groups_tool_results_into_one_user_turn():
    converted = to_anthropic(HISTORY)
    assert [m["role"] for m in converted] == ["user", "assistant", "user"]
    assert [b["type"] for b in converted[1]["content"]] == ["text", "tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in converted[2]["content"]] == ["c1", "c2"]


def test_openai_keeps_one_message_per_tool_result():
    converted = to_openai("system prompt", HISTORY)
    assert [m["role"] for m in converted] == ["system", "user", "assistant", "tool", "tool"]
    assert converted[2]["tool_calls"][0]["function"]["arguments"] == '{"month": "2026-10"}'


def test_anthropic_provider_parses_tool_use():
    response = AnthropicMessage.model_validate(
        {
            "id": "m1",
            "type": "message",
            "role": "assistant",
            "model": "test",
            "content": [
                {"type": "text", "text": "Let me check."},
                {"type": "tool_use", "id": "t1", "name": "lookup", "input": {"month": "2026-10"}},
            ],
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 7},
        }
    )
    sent = {}

    def create(**request):
        sent.update(request)
        return response

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    completion = AnthropicProvider("test", "key", client=client).complete(
        "sys", HISTORY[:1], [SPEC], "lookup"
    )
    assert completion.text == "Let me check."
    assert completion.tool_calls == [ToolCall("t1", "lookup", {"month": "2026-10"})]
    assert (completion.input_tokens, completion.output_tokens) == (12, 7)
    assert sent["tool_choice"] == {"type": "tool", "name": "lookup"}
    assert sent["tools"][0]["input_schema"] == SPEC.parameters


def test_openai_provider_parses_tool_calls_and_bad_json():
    response = ChatCompletion.model_validate(
        {
            "id": "c",
            "object": "chat.completion",
            "created": 1,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "a",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"x": 1}'},
                            },
                            {
                                "id": "b",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": "{oops"},
                            },
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        }
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))
    completion = OpenAIProvider("test", "key", client=client).complete("sys", HISTORY[:1], [SPEC])
    assert [c.arguments for c in completion.tool_calls] == [{"x": 1}, {}]
    assert completion.input_tokens == 3
