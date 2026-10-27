"""Explicit compatible Chat Completions dialect. No gateway capability assumptions."""

from app.services.llm.base import BaseProvider
from app.services.llm.contracts import APIProtocol, FailureCode, Provider
from app.services.llm.protocol_support import (
    InvalidOutput,
    WireOutcome,
    action,
    compact,
    decode_scope,
    request_id,
    tool_arguments,
    tool_output,
    usage,
)


class CompatibleProvider(BaseProvider):
    provider = Provider.COMPATIBLE
    protocol = APIProtocol.CHAT_COMPLETIONS
    suffix = "/chat/completions"
    authentication = ("bearer", "gateway_api_key")

    def encode(self, wire):
        messages = [{"role": "system", "content": wire.system}, *wire.messages]
        for exchange in wire.history:
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": exchange.action.call_id,
                                "type": "function",
                                "function": {
                                    "name": exchange.action.arguments.name,
                                    "arguments": compact(tool_arguments(exchange)),
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": exchange.action.call_id,
                        "content": tool_output(exchange),
                    },
                ]
            )
        payload = {
            "model": wire.model,
            "messages": messages,
            "stream": False,
            self.options.compatible_token_parameter: wire.max_output_tokens,
        }
        if wire.temperature is not None:
            payload["temperature"] = wire.temperature
        if wire.schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "application_output",
                    "strict": True,
                    "schema": wire.schema,
                },
            }
        if wire.tools:
            payload["tools"] = [{"type": "function", "function": item} for item in wire.tools]
        return payload

    def decode(self, request, response):
        request = decode_scope(request)
        data = response.data
        if not isinstance(data, dict) or data.get("model", request.model_id) != request.model_id:
            raise InvalidOutput()
        counts = usage(data.get("usage"), "chat")
        identity = request_id(data, response.provider_request_id)
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise InvalidOutput()
        item = choices[0]
        reason = item.get("finish_reason")
        message = item.get("message", {})
        if reason == "length":
            return WireOutcome("truncated", counts, identity, failure=FailureCode.TRUNCATED)
        if reason == "content_filter" or message.get("refusal"):
            return WireOutcome("refused", counts, identity, failure=FailureCode.REFUSAL)
        if reason == "tool_calls":
            if not request.native_requested:
                raise InvalidOutput()
            actions = []
            for call in message.get("tool_calls", []):
                if call.get("type") != "function":
                    raise InvalidOutput()
                function = call["function"]
                actions.append(
                    action(
                        call.get("id"),
                        function.get("name"),
                        function.get("arguments"),
                        request.allowed_tools,
                    )
                )
            return WireOutcome("tool_actions", counts, identity, actions=tuple(actions))
        if (
            reason != "stop"
            or message.get("tool_calls")
            or not isinstance(message.get("content"), str)
        ):
            raise InvalidOutput()
        return WireOutcome("completed", counts, identity, text=message["content"])
