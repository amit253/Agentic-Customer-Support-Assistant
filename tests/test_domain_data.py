from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path

import pytest

from agentic_support.contracts import ReturnEligibilityResult, parse_order_id
from agentic_support.demo_data import DEMO_ORDERS, DEMO_SESSIONS


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE = ROOT / "knowledge_base"
EVALS = ROOT / "evals"


def _read_jsonl(filename: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (EVALS / filename).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_all_demo_order_ids_are_valid_and_unique() -> None:
    assert len(DEMO_ORDERS) == 7
    for order_id, order in DEMO_ORDERS.items():
        parsed = parse_order_id(order_id)
        assert parsed.year == 2026
        assert order.order_id == order_id
        assert order.customer_id.startswith("cust_")


def test_order_id_parser_rejects_malformed_and_bad_checksum_values() -> None:
    with pytest.raises(ValueError, match="must match"):
        parse_order_id("NS-26-1042")
    with pytest.raises(ValueError, match="check digit"):
        parse_order_id("NS-26-1042-6")


def test_demo_sessions_have_explicit_verification_and_channels() -> None:
    assert len(DEMO_SESSIONS) == 4
    assert all(session.session_id == key for key, session in DEMO_SESSIONS.items())
    assert {session.channel for session in DEMO_SESSIONS.values()} == {"text", "voice"}
    assert sum(session.verified for session in DEMO_SESSIONS.values()) == 3


def test_return_eligibility_contract_contains_no_refund_fields() -> None:
    field_names = {field.name for field in fields(ReturnEligibilityResult)}
    assert {
        "eligible",
        "reason_code",
        "policy_basis",
        "deadline",
        "next_action",
    }.issubset(field_names)
    assert "confirmed_refund_amount" not in field_names
    assert "refund_status" not in field_names


def test_knowledge_base_has_10_to_20_unique_document_ids() -> None:
    documents = sorted(KNOWLEDGE_BASE.glob("*.md"))
    assert 10 <= len(documents) <= 20

    document_ids = []
    for document in documents:
        content = document.read_text(encoding="utf-8")
        match = re.search(r"^doc_id:\s*(\S+)$", content, re.MULTILINE)
        assert match is not None, document.name
        document_ids.append(match.group(1))
    assert len(document_ids) == len(set(document_ids))


def test_seed_evaluation_examples_reference_real_documents() -> None:
    document_ids = {
        re.search(
            r"^doc_id:\s*(\S+)$",
            document.read_text(encoding="utf-8"),
            re.MULTILINE,
        ).group(1)
        for document in KNOWLEDGE_BASE.glob("*.md")
    }

    retrieval_cases = _read_jsonl("retrieval_seed.jsonl")
    assert len(retrieval_cases) == 12
    assert all(
        set(case["expected_doc_ids"]).issubset(document_ids)
        for case in retrieval_cases
    )
    assert any(case["case_type"] == "unanswerable" for case in retrieval_cases)


def test_routing_and_guardrail_seed_examples_have_labels() -> None:
    routing_cases = _read_jsonl("routing_seed.jsonl")
    assert len(routing_cases) == 12
    assert {case["expected_intent"] for case in routing_cases} == {
        "product_question",
        "order_status",
        "escalate_to_human",
    }
    assert all(
        {"id", "session_id", "text", "expected_intent"}.issubset(case)
        for case in routing_cases
    )

    guardrail_cases = _read_jsonl("guardrail_seed.jsonl")
    assert len(guardrail_cases) == 8
    assert all(
        {"id", "text", "expected_action", "category"}.issubset(case)
        for case in guardrail_cases
    )
