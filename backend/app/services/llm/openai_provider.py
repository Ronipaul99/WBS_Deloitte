"""Explicit, stateless OpenAI Responses JSON protocol over the secure transport."""

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


class OpenAIProvider(BaseProvider):
    provider = Provider.OPENAI
    protocol = APIProtocol.RESPONSES
    suffix = "/responses"
    authentication = ("bearer",)

    def encode(self, wire):
        inputs = list(wire.messages)
        for exchange in wire.history:
            inputs.extend(
                [
                    {
                        "type": "function_call",
                        "call_id": exchange.action.call_id,
                        "name": exchange.action.arguments.name,
                        "arguments": compact(tool_arguments(exchange)),
                    },
                    {
                        "type": "function_call_output",
                        "call_id": exchange.action.call_id,
                        "output": tool_output(exchange),
                    },
                ]
            )
        payload = {
            "model": wire.model,
            "instructions": wire.system,
            "input": inputs,
            "max_output_tokens": wire.max_output_tokens,
            "store": False,
            "stream": False,
        }
        if wire.temperature is not None:
            payload["temperature"] = wire.temperature
        if wire.schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "application_output",
                    "strict": True,
                    "schema": wire.schema,
                }
            }
        if wire.tools:
            payload["tools"] = [
                {"type": "function", "strict": False, **item} for item in wire.tools
            ]
        return payload

    def decode(self, request, response):
        request = decode_scope(request)
        data = response.data
        if not isinstance(data, dict) or data.get("model", request.model_id) != request.model_id:
            raise InvalidOutput()
        counts = usage(data.get("usage"), "responses")
        identity = request_id(data, response.provider_request_id)
        status = data.get("status")
        if status == "incomplete":
            reason = (data.get("incomplete_details") or {}).get("reason")
            if reason == "max_output_tokens":
                return WireOutcome("truncated", counts, identity, failure=FailureCode.TRUNCATED)
            if reason == "content_filter":
                return WireOutcome("refused", counts, identity, failure=FailureCode.REFUSAL)
            raise InvalidOutput()
        if status == "failed":
            return WireOutcome("failed", counts, identity, failure=FailureCode.PROVIDER_UNAVAILABLE)
        if status != "completed" or not isinstance(data.get("output"), list):
            raise InvalidOutput()
        texts, actions = [], []
        for item in data["output"]:
            if (
                item.get("type") in {"message", "function_call"}
                and item.get("status", "completed") != "completed"
            ):
                return WireOutcome("truncated", counts, identity, failure=FailureCode.TRUNCATED)
            if item.get("type") == "reasoning":
                continue  # Never return/replay/persist hidden reasoning or its metadata.
            if item.get("type") == "function_call":
                if not request.native_requested:
                    raise InvalidOutput()
                actions.append(
                    action(
                        item.get("call_id"),
                        item.get("name"),
                        item.get("arguments"),
                        request.allowed_tools,
                    )
                )
            elif item.get("type") == "message":
                for content in item["content"]:
                    if content.get("type") == "refusal":
                        return WireOutcome("refused", counts, identity, failure=FailureCode.REFUSAL)
                    if content.get("type") != "output_text" or not isinstance(
                        content.get("text"), str
                    ):
                        raise InvalidOutput()
                    texts.append(content["text"])
            else:
                raise InvalidOutput()
        return WireOutcome(
            "tool_actions" if actions else "completed",
            counts,
            identity,
            text="".join(texts),
            actions=tuple(actions),
        )
