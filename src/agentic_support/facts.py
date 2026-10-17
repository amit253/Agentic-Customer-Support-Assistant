"""Allowed-facts construction and deterministic output-claim validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .contracts import OrderStatusResult, ReturnEligibilityResult


_ORDER_ID_PATTERN = re.compile(r"\bNS-\d{2}-\d{4}-\d\b")
_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MONTH_DATE_PATTERN = re.compile(
    r"\b(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?[,]?\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_NUMERIC_DATE_PATTERN = re.compile(
    r"\b(?P<first>\d{1,2})/(?P<second>\d{1,2})/(?P<year>\d{4})\b"
)
_MONEY_PATTERN = re.compile(
    r"(?<![\w.])(?:[$€£]\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?)(?!\w)"
)
_RELATIVE_DELIVERY_PATTERN = re.compile(
    r"\b(?:deliver(?:y|ed|s)?|arriv(?:e|es|al)|ship(?:s|ped|ping)?)\b"
    r".{0,60}\b(?:today|tomorrow|tonight|next\s+\w+|in\s+\d+\s+days?)\b"
    r"|\b(?:today|tomorrow|tonight|next\s+\w+|in\s+\d+\s+days?)\b"
    r".{0,60}\b(?:deliver(?:y|ed|s)?|arriv(?:e|es|al)|ship(?:s|ped|ping)?)\b",
    re.IGNORECASE,
)
_PROMISE_PATTERNS = (
    re.compile(r"\bwe will refund\b", re.IGNORECASE),
    re.compile(r"\brefund (?:is|has been) approved\b", re.IGNORECASE),
    re.compile(r"\bguaranteed (?:delivery|refund|replacement)\b", re.IGNORECASE),
    re.compile(r"\byou will receive (?:it|your order) by\b", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class AllowedFacts:
    """Facts that a handler is allowed to state in its response."""

    order_ids: frozenset[str] = field(default_factory=frozenset)
    dates: frozenset[str] = field(default_factory=frozenset)
    amounts: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_order_status(cls, result: OrderStatusResult) -> "AllowedFacts":
        dates = {
            value.isoformat()
            for value in (
                result.delivered_date,
                result.estimated_delivery_date,
                result.confirmed_refund_date,
            )
            if value is not None
        }
        amounts = (
            frozenset({f"${result.confirmed_refund_amount:.2f}"})
            if result.confirmed_refund_amount is not None
            else frozenset()
        )
        return cls(
            order_ids=frozenset({result.order_id}),
            dates=frozenset(dates),
            amounts=amounts,
        )

    @classmethod
    def from_return_eligibility(
        cls, result: ReturnEligibilityResult
    ) -> "AllowedFacts":
        dates = (
            frozenset({result.deadline.isoformat()})
            if result.deadline is not None
            else frozenset()
        )
        return cls(order_ids=frozenset({result.order_id}), dates=dates)


@dataclass(frozen=True, slots=True)
class ClaimValidationResult:
    """Output-claim decision used before a response reaches transport."""

    allowed: bool
    reason: str
    unsupported_claims: tuple[str, ...] = ()


class OutputClaimGuard:
    """Block unsupported IDs, dates, amounts, and promise language."""

    @staticmethod
    def _month_date(match: re.Match[str]) -> str | None:
        month = match.group("month").lower()[:3]
        month_numbers = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        try:
            return date(
                int(match.group("year")),
                month_numbers[month],
                int(re.sub(r"(?:st|nd|rd|th)$", "", match.group("day"), flags=re.I)),
            ).isoformat()
        except ValueError:
            return None

    def validate(
        self, message: str, allowed_facts: AllowedFacts | None = None
    ) -> ClaimValidationResult:
        facts = allowed_facts or AllowedFacts()
        unsupported: list[str] = []

        for order_id in _ORDER_ID_PATTERN.findall(message):
            if order_id not in facts.order_ids:
                unsupported.append(f"order_id:{order_id}")
        for date_value in _DATE_PATTERN.findall(message):
            if date_value not in facts.dates:
                unsupported.append(f"date:{date_value}")
        for match in _MONTH_DATE_PATTERN.finditer(message):
            date_value = self._month_date(match)
            if date_value is None or date_value not in facts.dates:
                unsupported.append(f"date:{match.group(0)}")
        for match in _NUMERIC_DATE_PATTERN.finditer(message):
            first = int(match.group("first"))
            second = int(match.group("second"))
            year = int(match.group("year"))
            interpretations: set[str] = set()
            for month, day in ((first, second), (second, first)):
                try:
                    interpretations.add(date(year, month, day).isoformat())
                except ValueError:
                    continue
            if not interpretations or not interpretations.issubset(facts.dates):
                unsupported.append(f"date:{match.group(0)}")
        for amount in _MONEY_PATTERN.findall(message):
            if amount not in facts.amounts:
                unsupported.append(f"amount:{amount}")
        if _RELATIVE_DELIVERY_PATTERN.search(message) is not None:
            unsupported.append("relative_delivery_date")
        for pattern in _PROMISE_PATTERNS:
            match = pattern.search(message)
            if match is not None:
                unsupported.append(f"promise:{match.group(0)}")

        if unsupported:
            return ClaimValidationResult(
                allowed=False,
                reason="unsupported_claim",
                unsupported_claims=tuple(unsupported),
            )
        return ClaimValidationResult(allowed=True, reason="claims_supported")
