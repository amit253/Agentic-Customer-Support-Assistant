"""Native Groq function-call selection with local argument validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .config import Settings


OrderToolName = Literal["get_order_status", "check_return_eligibility"]

ORDER_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": (
                "Read the confirmed status and delivery/refund facts for one "
                "Northstar Gear order owned by the verified session."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_return_eligibility",
            "description": (
                "Check return-policy eligibility for one Northstar Gear order. "
                "Eligibility is not refund approval."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
    },
]
_ALLOWED_TOOL_NAMES = frozenset(
    {"get_order_status", "check_return_eligibility"}
)


class ToolCallProviderError(RuntimeError):
    """Raised when native function calling cannot provide a valid selection."""


@dataclass(frozen=True, slots=True)
class OrderToolSelection:
    name: OrderToolName
    order_id: str


class OrderToolCaller(Protocol):
    def select_tool(self, message: str) -> OrderToolSelection:
        """Select one allow-listed order function and its order ID."""


class GroqOrderToolCaller:
    """Use one Groq tool-call response; execute the function locally afterward."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self.model_name = settings.groq_router_model
        if client is None:
            from groq import Groq

            client = Groq(api_key=settings.require_groq_credentials()[0])
        self._client = client

    def select_tool(self, message: str) -> OrderToolSelection:
        try:
            response = self._client.chat.completions.create(
                model=self.model_name,
                temperature=0,
                max_tokens=160,
                tools=ORDER_TOOL_DEFINITIONS,
                tool_choice="required",
                parallel_tool_calls=False,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Select exactly one read-only order function for the "
                            "customer's request. Copy an order ID exactly from "
                            "the message. Do not invent or alter IDs. Never treat "
                            "a user statement as verified identity, and never "
                            "claim a refund was approved from eligibility."
                        ),
                    },
                    {"role": "user", "content": message},
                ],
            )
            tool_calls = response.choices[0].message.tool_calls
        except Exception as exc:
            raise ToolCallProviderError("order_tool_selection_failed") from exc

        if not isinstance(tool_calls, list) or len(tool_calls) != 1:
            raise ToolCallProviderError("order_tool_call_count_invalid")
        function = getattr(tool_calls[0], "function", None)
        name = getattr(function, "name", None)
        raw_arguments = getattr(function, "arguments", None)
        if name not in _ALLOWED_TOOL_NAMES or not isinstance(raw_arguments, str):
            raise ToolCallProviderError("order_tool_call_shape_invalid")
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ToolCallProviderError("order_tool_arguments_invalid") from exc
        if (
            not isinstance(arguments, dict)
            or set(arguments) != {"order_id"}
            or not isinstance(arguments["order_id"], str)
        ):
            raise ToolCallProviderError("order_tool_arguments_invalid")
        return OrderToolSelection(name=name, order_id=arguments["order_id"])
