from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from agentic_support.config import Settings
from agentic_support.contracts import CustomerSession, OrderStatusResult
from agentic_support.demo_data import DEMO_SESSIONS
from agentic_support.facts import AllowedFacts, OutputClaimGuard
from agentic_support.grounded_answers import (
    GroundedAnswer,
    GroundedAnswerError,
    GroqGroundedAnswerer,
)
from agentic_support.handlers import build_default_registry
from agentic_support.handlers import HandlerRegistry
from agentic_support.pipeline import SupportService
from agentic_support.retrieval import (
    DenseVectorIndex,
    DocumentChunk,
    GroundedRetriever,
    RetrievalHit,
)
from agentic_support.routing import StructuredIntentRouter
from agentic_support.tool_calling import (
    GroqOrderToolCaller,
    OrderToolSelection,
    ToolCallProviderError,
)
from agentic_support.tools import DeterministicOrderTools


def _groq_response(*, content: str | None = None, tool_calls: list[Any] | None = None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)]
    )


class FakeGroqClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return self.response


@dataclass
class StaticClassifier:
    payload: dict[str, object]

    def classify(self, message: str) -> dict[str, object]:
        return self.payload


class TestEmbedder:
    model_name = "test-embedder"

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return np.asarray(
            [
                [0.0, 1.0] if text.startswith("unrelated") else [1.0, 0.0]
                for text in texts
            ],
            dtype=np.float32,
        )


def _chunk() -> DocumentChunk:
    return DocumentChunk(
        chunk_id="kb-test#chunk-000",
        doc_id="kb-test",
        title="Test product facts",
        source_path="knowledge_base/kb-test.md",
        chunk_index=0,
        text="The Trailmark 28 has a 28-liter capacity and costs $120.00.",
    )


def _retriever() -> GroundedRetriever:
    chunk = _chunk()
    return GroundedRetriever(
        embedder=TestEmbedder(),
        index=DenseVectorIndex(
            (chunk,),
            np.asarray([[1.0, 0.0]], dtype=np.float32),
        ),
        min_similarity=0.5,
    )


def _settings() -> Settings:
    return Settings.from_environment({})


def _service(registry: HandlerRegistry) -> SupportService:
    return SupportService(
        router=StructuredIntentRouter(
            StaticClassifier({"intent": "product_question", "confidence": 0.99})
        ),
        registry=registry,
    )


def test_grounded_answerer_sends_passages_and_parses_citations() -> None:
    client = FakeGroqClient(
        _groq_response(
            content=json.dumps(
                {
                    "answer": "The Trailmark 28 has a 28-liter capacity.",
                    "citations": ["kb-test#chunk-000"],
                }
            )
        )
    )
    answerer = GroqGroundedAnswerer(_settings(), client=client)
    hit = RetrievalHit(_chunk(), score=0.91)

    result = answerer.answer("What is its capacity?", [hit])

    assert result == GroundedAnswer(
        "The Trailmark 28 has a 28-liter capacity.",
        ("kb-test#chunk-000",),
    )
    sent_payload = json.loads(client.requests[0]["messages"][1]["content"])
    assert sent_payload["passages"][0]["chunk_id"] == "kb-test#chunk-000"
    assert client.requests[0]["temperature"] == 0


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        json.dumps({"answer": 7, "citations": ["kb-test#chunk-000"]}),
        json.dumps({"answer": "", "citations": ["kb-test#chunk-000"]}),
    ],
)
def test_grounded_answerer_rejects_invalid_provider_output(content: str) -> None:
    answerer = GroqGroundedAnswerer(
        _settings(), client=FakeGroqClient(_groq_response(content=content))
    )

    with pytest.raises(GroundedAnswerError):
        answerer.answer("What is its capacity?", [RetrievalHit(_chunk(), 0.91)])


@pytest.mark.parametrize(
    "payload",
    [
        {"answer": "A plausible answer.", "citations": []},
        {
            "answer": "I don't have that information.",
            "citations": [],
            "insufficient_evidence": True,
        },
    ],
)
def test_uncited_answer_becomes_insufficient_evidence_and_is_never_shown(
    payload: dict[str, object],
) -> None:
    # Live Groq returned an honest "not enough information" answer with no
    # citations for a comparison question; that used to crash the handler.
    client = FakeGroqClient(_groq_response(content=json.dumps(payload)))
    answer = GroqGroundedAnswerer(_settings(), client=client).answer(
        "Is it bigger than the other one?", [RetrievalHit(_chunk(), 0.91)]
    )
    assert answer.insufficient_evidence is True
    assert answer.cited_chunk_ids == ()

    service = _service(
        build_default_registry(
            retriever=_retriever(),
            answerer=GroqGroundedAnswerer(_settings(), client=client),
        )
    )
    response = service.handle("What is the backpack capacity?")

    assert response.status == "ok"
    assert "not have enough verified information" in response.message
    assert "A plausible answer" not in response.message
    assert (
        response.metadata["retrieval_reason"]
        == "answerer_reported_insufficient_evidence"
    )


def test_product_answer_is_guarded_and_cites_only_retrieved_chunks() -> None:
    client = FakeGroqClient(
        _groq_response(
            content=json.dumps(
                {
                    "answer": "The pack has a 28-liter capacity and costs $120.00.",
                    "citations": ["kb-test#chunk-000"],
                }
            )
        )
    )
    service = _service(
        build_default_registry(
            retriever=_retriever(),
            answerer=GroqGroundedAnswerer(_settings(), client=client),
        )
    )

    response = service.handle("What is the backpack capacity and price?")

    assert response.status == "ok"
    assert "Sources: Test product facts" in response.message
    assert "kb-test#chunk-000" not in response.message
    assert response.metadata["cited_sources"] == ("Test product facts",)
    assert response.metadata["cited_chunk_ids"] == ("kb-test#chunk-000",)


def test_unknown_product_citation_fails_closed() -> None:
    class InventedCitationAnswerer:
        def answer(self, question: str, hits: object) -> GroundedAnswer:
            return GroundedAnswer(
                "The pack has a 28-liter capacity.",
                ("kb-not-retrieved#chunk-000",),
            )

    service = _service(
        build_default_registry(
            retriever=_retriever(),
            answerer=InventedCitationAnswerer(),  # type: ignore[arg-type]
        )
    )

    response = service.handle("What is the backpack capacity?")

    assert response.status == "failed_closed"
    assert response.metadata["reason"] == "handler_error"


def test_insufficient_product_evidence_skips_answer_generation() -> None:
    class CountingAnswerer:
        calls = 0

        def answer(self, question: str, hits: object) -> GroundedAnswer:
            self.calls += 1
            return GroundedAnswer("Should not be called.", ("kb-test#chunk-000",))

    answerer = CountingAnswerer()
    service = _service(
        build_default_registry(retriever=_retriever(), answerer=answerer)  # type: ignore[arg-type]
    )

    response = service.handle("unrelated question")

    assert response.status == "ok"
    assert answerer.calls == 0
    assert "not have enough verified information" in response.message


@pytest.mark.parametrize(
    ("intent", "message"),
    [
        ("product_question", "What is the backpack capacity?"),
        ("order_status", "Where is order NS-26-1042-5?"),
    ],
)
def test_unconfigured_product_or_order_path_fails_closed(
    intent: str, message: str
) -> None:
    service = SupportService(
        router=StructuredIntentRouter(
            StaticClassifier({"intent": intent, "confidence": 0.99})
        ),
        registry=build_default_registry(),
    )

    response = service.handle(message, session_id="demo-session-nadia")

    assert response.status == "failed_closed"
    assert response.metadata["reason"] == "handler_error"


def test_retrieval_facts_are_scoped_to_cited_chunks() -> None:
    cited = _chunk()
    other = DocumentChunk(
        chunk_id="kb-other#chunk-000",
        doc_id="kb-other",
        title="Other facts",
        source_path="knowledge_base/kb-other.md",
        chunk_index=0,
        text="A different model costs $999.00.",
    )
    allowed_facts = AllowedFacts.from_retrieval([cited])
    all_facts = AllowedFacts.from_retrieval([cited, other])

    assert "$999.00" in all_facts.amounts
    assert "$999.00" not in allowed_facts.amounts
    assert OutputClaimGuard().validate(
        "The price is $120.00.", allowed_facts
    ).allowed
    assert not OutputClaimGuard().validate(
        "The price is $999.00.", allowed_facts
    ).allowed


def _tool_call(name: str, arguments: str) -> object:
    return SimpleNamespace(
        function=SimpleNamespace(name=name, arguments=arguments)
    )


def test_order_tool_caller_parses_one_allowlisted_call() -> None:
    client = FakeGroqClient(
        _groq_response(
            tool_calls=[
                _tool_call(
                    "get_order_status",
                    json.dumps({"order_id": "NS-26-1042-5"}),
                )
            ]
        )
    )
    caller = GroqOrderToolCaller(_settings(), client=client)

    selection = caller.select_tool("Where is order NS-26-1042-5?")

    assert selection == OrderToolSelection("get_order_status", "NS-26-1042-5")
    assert client.requests[0]["tool_choice"] == "required"
    assert client.requests[0]["parallel_tool_calls"] is False


@pytest.mark.parametrize(
    "tool_calls",
    [
        [],
        [_tool_call("delete_order", json.dumps({"order_id": "NS-26-1042-5"}))],
        [_tool_call("get_order_status", json.dumps({"order_id": "NS-26-1042-5", "session_id": "forged"}))],
        [_tool_call("get_order_status", "not-json")],
        [
            _tool_call("get_order_status", json.dumps({"order_id": "NS-26-1042-5"})),
            _tool_call("get_order_status", json.dumps({"order_id": "NS-26-1042-5"})),
        ],
    ],
)
def test_order_tool_caller_rejects_invalid_calls(tool_calls: list[object]) -> None:
    caller = GroqOrderToolCaller(
        _settings(), client=FakeGroqClient(_groq_response(tool_calls=tool_calls))
    )

    with pytest.raises(ToolCallProviderError):
        caller.select_tool("Where is order NS-26-1042-5?")


class CountingOrderTools(DeterministicOrderTools):
    def __init__(self) -> None:
        self.status_calls = 0

    def get_order_status(
        self, *, order_id: str, session: CustomerSession
    ) -> OrderStatusResult:
        self.status_calls += 1
        return super().get_order_status(order_id=order_id, session=session)


@dataclass
class FixedToolCaller:
    selection: OrderToolSelection

    def select_tool(self, message: str) -> OrderToolSelection:
        return self.selection


def _order_service(tools: CountingOrderTools, caller: FixedToolCaller) -> SupportService:
    return SupportService(
        router=StructuredIntentRouter(
            StaticClassifier({"intent": "order_status", "confidence": 0.99})
        ),
        registry=build_default_registry(
            order_tools=tools,
            order_tool_caller=caller,
        ),
    )


def test_native_selection_executes_local_owned_order_tool() -> None:
    tools = CountingOrderTools()
    service = _order_service(
        tools,
        FixedToolCaller(OrderToolSelection("get_order_status", "NS-26-1042-5")),
    )

    response = service.handle(
        "Where is order NS-26-1042-5?",
        session_id="demo-session-nadia",
    )

    assert response.status == "ok"
    assert tools.status_calls == 1
    assert response.metadata["tool_name"] == "get_order_status"


def test_altered_model_order_id_never_executes_local_tool() -> None:
    tools = CountingOrderTools()
    service = _order_service(
        tools,
        FixedToolCaller(OrderToolSelection("get_order_status", "NS-26-2044-8")),
    )

    response = service.handle(
        "Where is order NS-26-1042-5?",
        session_id="demo-session-nadia",
    )

    assert response.status == "failed_closed"
    assert tools.status_calls == 0


def test_model_selected_call_still_obeys_server_side_ownership() -> None:
    tools = CountingOrderTools()
    service = _order_service(
        tools,
        FixedToolCaller(OrderToolSelection("get_order_status", "NS-26-2044-8")),
    )

    response = service.handle(
        "Where is order NS-26-2044-8?",
        session_id="demo-session-nadia",
    )

    assert response.status == "ok"
    assert response.metadata["tool_error"] == "ownership_mismatch"
    assert tools.status_calls == 1
    assert "NS-26-2044-8" not in response.message


def test_provider_failure_does_not_execute_order_tool() -> None:
    class BrokenToolCaller:
        def select_tool(self, message: str) -> OrderToolSelection:
            raise ToolCallProviderError("order_tool_selection_failed")

    tools = CountingOrderTools()
    service = SupportService(
        router=StructuredIntentRouter(
            StaticClassifier({"intent": "order_status", "confidence": 0.99})
        ),
        registry=build_default_registry(
            order_tools=tools,
            order_tool_caller=BrokenToolCaller(),
        ),
    )

    response = service.handle(
        "Where is order NS-26-1042-5?",
        session_id="demo-session-nadia",
    )

    assert response.status == "failed_closed"
    assert tools.status_calls == 0


def _live_settings() -> Settings:
    if os.environ.get("RUN_LIVE_GROQ_TESTS") != "1":
        pytest.skip("set RUN_LIVE_GROQ_TESTS=1 to enable live Groq checks")
    settings = Settings.from_environment()
    if not settings.groq_configured:
        pytest.skip("Groq credentials are not configured")
    return settings


@pytest.mark.live
def test_live_groq_product_answer_uses_valid_cited_evidence() -> None:
    settings = _live_settings()
    question = "How many liters is the Trailmark 28 backpack?"
    retriever = GroundedRetriever.from_directory(
        Path(__file__).resolve().parents[1] / "knowledge_base"
    )
    retrieval = retriever.retrieve(question)

    assert retrieval.sufficient_evidence
    answer = GroqGroundedAnswerer(settings).answer(question, retrieval.hits)
    retrieved_ids = {hit.chunk.chunk_id for hit in retrieval.hits}

    assert answer.text
    assert answer.cited_chunk_ids
    assert set(answer.cited_chunk_ids).issubset(retrieved_ids)
    cited_chunks = [
        hit.chunk
        for hit in retrieval.hits
        if hit.chunk.chunk_id in answer.cited_chunk_ids
    ]
    response = f"{answer.text}\n\nSources: {', '.join(answer.cited_chunk_ids)}"
    assert OutputClaimGuard().validate(
        response, AllowedFacts.from_retrieval(cited_chunks)
    ).allowed


@pytest.mark.live
def test_live_groq_order_call_selects_and_executes_verified_read_only_tool() -> None:
    settings = _live_settings()
    user_message = "Please check the status of order NS-26-1042-5."

    selection = GroqOrderToolCaller(settings).select_tool(user_message)

    assert selection.name == "get_order_status"
    assert selection.order_id == "NS-26-1042-5"
    session = DEMO_SESSIONS["demo-session-nadia"]
    result = DeterministicOrderTools().get_order_status(
        order_id=selection.order_id,
        session=session,
    )
    assert result.order_id == selection.order_id
