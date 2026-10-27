"""Anthropic Messages JSON/tool-use mappings, without SDK retries or thinking replay."""

from app.services.llm.base import BaseProvider
from app.services.llm.contracts import APIProtocol, FailureCode, Provider
from app.services.llm.protocol_support import (
    InvalidOutput,
    WireOutcome,
    action,
    decode_scope,
    request_id,
    tool_arguments,
    usage,
)


class AnthropicProvider(BaseProvider):
    provider = Provider.ANTHROPIC
    protocol = APIProtocol.MESSAGES
    suffix = "/messages"
    authentication = ("anthropic_api_key",)

    @property
    def headers(self):
        return (("anthropic-version", "2023-06-01"),)

    def encode(self, wire):
        if wire.temperature is not None and wire.temperature > 1:
            raise InvalidOutput()
        messages = list(wire.messages)
        for exchange in wire.history:
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": exchange.action.call_id,
                                "name": exchange.action.arguments.name,
                                "input": tool_arguments(exchange),
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": exchange.action.call_id,
                                "content": exchange.output_json,
                                "is_error": exchange.is_error,
                            }
                        ],
                    },
                ]
            )
        payload = {
            "model": wire.model,
            "system": wire.system,
            "messages": messages,
            "max_tokens": wire.max_output_tokens,
            "stream": False,
        }
        if wire.temperature is not None:
            payload["temperature"] = wire.temperature
        if wire.schema is not None:
            payload["output_config"] = {"format": {"type": "json_schema", "schema": wire.schema}}
        if wire.tools:
            payload["tools"] = [
                {"name": item["name"], "input_schema": item["parameters"]} for item in wire.tools
            ]
        return payload

    def decode(self, request, response):
        request = decode_scope(request)
        data = response.data
        if not isinstance(data, dict) or data.get("model", request.model_id) != request.model_id:
            raise InvalidOutput()
        identity = request_id(data, response.provider_request_id)
        counts = usage(data.get("usage"), "anthropic")
        reason = data.get("stop_reason")
        if reason in {"max_tokens", "model_context_window_exceeded"}:
            return WireOutcome("truncated", counts, identity, failure=FailureCode.TRUNCATED)
        if reason == "refusal":
            return WireOutcome("refused", counts, identity, failure=FailureCode.REFUSAL)
        if reason == "pause_turn":
            return WireOutcome("failed", counts, identity, failure=FailureCode.PROVIDER_UNAVAILABLE)
        if reason not in {"end_turn", "stop_sequence", "tool_use"} or not isinstance(
            data.get("content"), list
        ):
            raise InvalidOutput()
        texts, actions = [], []
        for item in data["content"]:
            kind = item.get("type")
            if kind in {"thinking", "redacted_thinking"}:
                continue
            if kind == "text" and isinstance(item.get("text"), str):
                texts.append(item["text"])
            elif kind == "tool_use" and request.native_requested:
                actions.append(
                    action(
                        item.get("id"), item.get("name"), item.get("input"), request.allowed_tools
                    )
                )
            else:
                raise InvalidOutput()
        if (reason == "tool_use") != bool(actions):
            raise InvalidOutput()
        return WireOutcome(
            "tool_actions" if actions else "completed",
            counts,
            identity,
            text="".join(texts),
            actions=tuple(actions),
        )
