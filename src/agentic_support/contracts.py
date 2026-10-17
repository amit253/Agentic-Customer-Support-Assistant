"""Domain contracts created before the future tool and agent implementations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Protocol


class ContractValidationError(ValueError):
    """Raised when a fictional support-domain value violates its contract."""


OrderStatus = Literal["processing", "in_transit", "delivered", "return_received"]
SaleType = Literal["standard", "personalized_final_sale"]
RefundStatus = Literal["not_requested", "pending", "issued"]
SupportChannel = Literal["text", "voice"]

_ORDER_ID_PATTERN = re.compile(
    r"^NS-(?P<year>\d{2})-(?P<sequence>\d{4})-(?P<check_digit>\d)$"
)


@dataclass(frozen=True, slots=True)
class ParsedOrderId:
    """The validated components of a Northstar Gear order ID."""

    year: int
    sequence: int
    check_digit: int


def parse_order_id(order_id: str) -> ParsedOrderId:
    """Validate ``NS-YY-NNNN-C`` and its decimal check digit.

    The check digit is the sum of the six year/sequence digits modulo ten.
    This is a fictional format used to make malformed and fabricated IDs easy
    to detect in later tool tests.
    """

    match = _ORDER_ID_PATTERN.fullmatch(order_id)
    if match is None:
        raise ContractValidationError("order_id must match NS-YY-NNNN-C")

    year_suffix = match.group("year")
    sequence_text = match.group("sequence")
    check_digit = int(match.group("check_digit"))
    expected_check_digit = sum(
        int(character) for character in f"{year_suffix}{sequence_text}"
    ) % 10
    if check_digit != expected_check_digit:
        raise ContractValidationError("order_id check digit is invalid")

    return ParsedOrderId(
        year=2000 + int(year_suffix),
        sequence=int(sequence_text),
        check_digit=check_digit,
    )


@dataclass(frozen=True, slots=True)
class CustomerSession:
    """Fictional verified session context used for future tool authorization."""

    session_id: str
    customer_id: str
    verified: bool
    channel: SupportChannel


@dataclass(frozen=True, slots=True)
class DemoOrder:
    """Deterministic fictional order record for future read-only tools."""

    order_id: str
    customer_id: str
    sku: str
    item_name: str
    category: str
    order_date: date
    delivered_date: date | None
    status: OrderStatus
    estimated_delivery_date: date | None
    sale_type: SaleType
    return_policy_code: str
    return_deadline: date | None
    country_code: str
    international_duties: Decimal
    refund_status: RefundStatus
    confirmed_refund_amount: Decimal | None
    confirmed_refund_date: date | None


@dataclass(frozen=True, slots=True)
class OrderStatusResult:
    """Facts a status tool may return; values must come from ``DemoOrder``."""

    order_id: str
    item_name: str
    status: OrderStatus
    delivered_date: date | None
    estimated_delivery_date: date | None
    refund_status: RefundStatus
    confirmed_refund_amount: Decimal | None
    confirmed_refund_date: date | None


@dataclass(frozen=True, slots=True)
class ReturnEligibilityResult:
    """Policy facts only; eligibility is not refund approval or issuance."""

    order_id: str
    eligible: bool
    reason_code: str
    policy_basis: str
    deadline: date | None
    next_action: str


class SupportOrderTools(Protocol):
    """Internal contract for future read-only order tools.

    ``session`` is trusted server-side context. It is not a model-controlled
    tool argument and cannot be replaced by an order ID supplied by a user.
    """

    def get_order_status(
        self, *, order_id: str, session: CustomerSession
    ) -> OrderStatusResult:
        """Return confirmed status facts for an owned order."""

    def check_return_eligibility(
        self, *, order_id: str, session: CustomerSession
    ) -> ReturnEligibilityResult:
        """Return policy eligibility facts without approving a refund."""
