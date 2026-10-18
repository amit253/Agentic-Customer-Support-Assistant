"""Deterministic read-only order tools with session ownership enforcement."""

from __future__ import annotations

from datetime import date

from .contracts import (
    CustomerSession,
    OrderStatusResult,
    OrderSummary,
    ReturnEligibilityResult,
    parse_order_id,
)
from .demo_data import DEMO_AS_OF_DATE, DEMO_ORDERS


class OrderToolError(RuntimeError):
    """Safe, non-sensitive order-tool failure."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class DeterministicOrderTools:
    """Read-only implementation over the fictional Step 2 order records."""

    def _resolve_order(self, order_id: str, session: CustomerSession):
        if not isinstance(order_id, str):
            raise OrderToolError("malformed_order_id")
        if not isinstance(session, CustomerSession) or not session.verified:
            raise OrderToolError("unverified_session")
        try:
            parse_order_id(order_id)
        except ValueError as exc:
            raise OrderToolError("malformed_order_id") from exc
        order = DEMO_ORDERS.get(order_id)
        if order is None:
            raise OrderToolError("order_not_found")
        if order.customer_id != session.customer_id:
            raise OrderToolError("ownership_mismatch")
        return order

    def list_orders(self, *, session: CustomerSession) -> tuple[OrderSummary, ...]:
        """List only the verified customer's own orders, in ID order."""

        if not isinstance(session, CustomerSession) or not session.verified:
            raise OrderToolError("unverified_session")
        return tuple(
            OrderSummary(order_id=order.order_id, item_name=order.item_name, status=order.status)
            for order in sorted(DEMO_ORDERS.values(), key=lambda item: item.order_id)
            if order.customer_id == session.customer_id
        )

    def get_order_status(
        self, *, order_id: str, session: CustomerSession
    ) -> OrderStatusResult:
        order = self._resolve_order(order_id, session)
        return OrderStatusResult(
            order_id=order.order_id,
            item_name=order.item_name,
            status=order.status,
            delivered_date=order.delivered_date,
            estimated_delivery_date=order.estimated_delivery_date,
            refund_status=order.refund_status,
            confirmed_refund_amount=order.confirmed_refund_amount,
            confirmed_refund_date=order.confirmed_refund_date,
        )

    def check_return_eligibility(
        self, *, order_id: str, session: CustomerSession
    ) -> ReturnEligibilityResult:
        order = self._resolve_order(order_id, session)
        if order.delivered_date is None:
            return ReturnEligibilityResult(
                order_id=order.order_id,
                item_name=order.item_name,
                eligible=False,
                reason_code="not_delivered",
                policy_basis="Returns are evaluated after delivery.",
                deadline=None,
                next_action="Wait for delivery before requesting a return.",
            )
        if order.sale_type == "personalized_final_sale":
            return ReturnEligibilityResult(
                order_id=order.order_id,
                item_name=order.item_name,
                eligible=False,
                reason_code="final_sale",
                policy_basis="Personalized items are final sale; defects use warranty review.",
                deadline=None,
                next_action="Contact human support only if reporting a manufacturing defect.",
            )
        if order.status == "return_received" or order.refund_status == "issued":
            return ReturnEligibilityResult(
                order_id=order.order_id,
                item_name=order.item_name,
                eligible=False,
                reason_code="already_returned",
                policy_basis="This order already has a received return or issued refund.",
                deadline=order.return_deadline,
                next_action="Review the confirmed order/refund status.",
            )
        deadline = order.return_deadline
        if deadline is None or deadline < DEMO_AS_OF_DATE:
            return ReturnEligibilityResult(
                order_id=order.order_id,
                item_name=order.item_name,
                eligible=False,
                reason_code="window_expired",
                policy_basis="The applicable return deadline has passed.",
                deadline=deadline,
                next_action="Request human review if you believe an exception applies.",
            )
        reason_code = (
            "eligible_trail_week"
            if order.return_policy_code == "trail_week_extended"
            else "eligible_standard"
        )
        return ReturnEligibilityResult(
            order_id=order.order_id,
            item_name=order.item_name,
            eligible=True,
            reason_code=reason_code,
            policy_basis=order.return_policy_code,
            deadline=deadline,
            next_action="Start a return request; eligibility is not refund approval.",
        )
