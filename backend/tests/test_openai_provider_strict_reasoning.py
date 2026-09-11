"""Regression tests proving the installed llm-ontology-mapper OpenAIProvider's
`strict` flag genuinely prevents the silent reasoning_effort-drop-and-retry
behavior Bridge relies on for explicit user reasoning configuration.

These call the real OpenAIProvider class (not a Bridge-level mock) with a
faked `openai.OpenAI` chat-completions client, so a change to the pinned
llm-ontology-mapper dependency that weakens `strict` semantics would fail
these tests rather than silently regressing Bridge's Test Connection
guarantees.
"""

from unittest.mock import MagicMock

import httpx
import openai
import pytest
from llm_ontology_mapper.providers import ChatMessage, OpenAIProvider


def _reasoning_rejected_error() -> openai.BadRequestError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        400, request=request, text="Unsupported parameter: 'reasoning_effort'"
    )
    return openai.BadRequestError(
        "Unsupported parameter: 'reasoning_effort' is not supported with this model.",
        response=response,
        body=None,
    )


def _fake_success_response(model: str = "o3") -> MagicMock:
    return MagicMock(
        choices=[MagicMock(message=MagicMock(content="OK"), finish_reason="stop")],
        model=model,
        usage=MagicMock(prompt_tokens=1, completion_tokens=1),
    )


def test_strict_reasoning_rejection_does_not_retry_and_raises():
    """An explicit, strict reasoning_effort that OpenAI rejects must fail —
    never silently retry without it and return a response the caller never
    asked for."""
    provider = OpenAIProvider(model="o3", api_key="sk-test")
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = _reasoning_rejected_error()
    provider._client = fake_client  # bypass lazy SDK client construction

    with pytest.raises(RuntimeError, match="reasoning_effort"):
        provider.complete(
            [ChatMessage(role="user", content="hi")],
            reasoning_effort="high",
            strict=True,
        )

    assert fake_client.chat.completions.create.call_count == 1
    sent_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert sent_kwargs.get("reasoning_effort") == "high"


def test_non_strict_reasoning_rejection_silently_retries_without_it():
    """Documents the library's default (non-strict) behavior — the opposite
    of what Bridge asks for when reasoning_effort is an explicit user
    choice. Without strict=True, a rejected reasoning_effort is dropped and
    the retried request can succeed with a different configuration than the
    caller requested."""
    provider = OpenAIProvider(model="o3", api_key="sk-test")
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = [
        _reasoning_rejected_error(),
        _fake_success_response(),
    ]
    provider._client = fake_client

    response = provider.complete(
        [ChatMessage(role="user", content="hi")],
        reasoning_effort="high",
    )

    assert response.content == "OK"
    assert fake_client.chat.completions.create.call_count == 2
    second_call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert "reasoning_effort" not in second_call_kwargs
