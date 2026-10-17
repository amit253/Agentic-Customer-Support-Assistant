from __future__ import annotations

import copy

import pytest

from agentic_support.demo_data import DEMO_ORDERS, DEMO_SESSIONS
from agentic_support.tools import DeterministicOrderTools, OrderToolError


def test_owned_order_status_returns_only_confirmed_facts() -> None:
    tools = DeterministicOrderTools()
    result = tools.get_order_status(
        order_id="NS-26-1042-5",
        session=DEMO_SESSIONS["demo-session-nadia"],
    )

    assert result.order_id == "NS-26-1042-5"
    assert result.status == "delivered"
    assert result.delivered_date is not None
    assert result.confirmed_refund_amount is None


def test_cross_customer_order_lookup_is_rejected() -> None:
    tools = DeterministicOrderTools()

    with pytest.raises(OrderToolError, match="ownership_mismatch"):
        tools.get_order_status(
            order_id="NS-26-2044-8",
            session=DEMO_SESSIONS["demo-session-nadia"],
        )


def test_malformed_and_unverified_tool_arguments_are_rejected() -> None:
    tools = DeterministicOrderTools()

    with pytest.raises(OrderToolError, match="malformed_order_id"):
        tools.get_order_status(
            order_id="NS-26-1042",
            session=DEMO_SESSIONS["demo-session-nadia"],
        )
    with pytest.raises(OrderToolError, match="unverified_session"):
        tools.get_order_status(
            order_id="NS-26-1042-5",
            session=DEMO_SESSIONS["demo-session-unverified"],
        )
    with pytest.raises(OrderToolError, match="malformed_order_id"):
        tools.get_order_status(
            order_id=None,  # type: ignore[arg-type]
            session=DEMO_SESSIONS["demo-session-nadia"],
        )


def test_eligibility_does_not_approve_refund() -> None:
    tools = DeterministicOrderTools()
    result = tools.check_return_eligibility(
        order_id="NS-26-2044-8",
        session=DEMO_SESSIONS["demo-session-omar"],
    )

    assert result.eligible is True
    assert result.reason_code == "eligible_trail_week"
    assert result.deadline is not None
    assert not hasattr(result, "confirmed_refund_amount")
    assert not hasattr(result, "refund_status")


def test_tools_do_not_mutate_deterministic_records() -> None:
    before = copy.deepcopy(dict(DEMO_ORDERS))
    tools = DeterministicOrderTools()
    tools.get_order_status(
        order_id="NS-26-1042-5",
        session=DEMO_SESSIONS["demo-session-nadia"],
    )
    assert dict(DEMO_ORDERS) == before
