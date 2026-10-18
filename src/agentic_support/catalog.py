"""Product names used to resolve follow-up questions such as "is it waterproof?".

The catalog maps each product's knowledge-base document to a display name and
the words customers use for it. Memory stores only the document ID of the
product under discussion; the retrieval query is rewritten deterministically
by appending the display name, so no conversation text is sent to an LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Product:
    doc_id: str
    display_name: str
    pattern: re.Pattern[str]


PRODUCTS: tuple[Product, ...] = (
    Product(
        doc_id="kb-002-trailmark-28",
        display_name="Trailmark 28 backpack",
        pattern=re.compile(r"\btrail\s?mark\b", re.I),
    ),
    Product(
        doc_id="kb-003-cityhaul-20",
        display_name="CityHaul 20 backpack",
        pattern=re.compile(r"\bcity\s?haul\b", re.I),
    ),
    Product(
        doc_id="kb-004-custom-latitude-pack",
        display_name="Custom Latitude Pack",
        pattern=re.compile(r"\blatitude\b", re.I),
    ),
)
_BY_DOC_ID = {product.doc_id: product for product in PRODUCTS}
_PRODUCT_REFERENCE = re.compile(
    r"\b(?:it|its|it's|this|that|this\s+one|that\s+one|the\s+(?:bag|pack|backpack))\b",
    re.I,
)


def products_mentioned(text: str) -> tuple[Product, ...]:
    return tuple(product for product in PRODUCTS if product.pattern.search(text))


def product_for_doc(doc_id: str) -> Product | None:
    return _BY_DOC_ID.get(doc_id)


def product_for_item_name(item_name: str) -> Product | None:
    mentioned = products_mentioned(item_name)
    return mentioned[0] if len(mentioned) == 1 else None


def rewrite_product_follow_up(text: str, active_product_doc_id: str | None) -> str | None:
    """Return a self-contained query for a pronoun follow-up, or ``None``.

    Only rewrites when the message names no product itself and refers back
    with a pronoun ("does it have a laptop sleeve?"). The rewrite appends the
    product's display name; the customer's words are left unchanged.
    """

    if active_product_doc_id is None or products_mentioned(text):
        return None
    product = product_for_doc(active_product_doc_id)
    if product is None or not _PRODUCT_REFERENCE.search(text):
        return None
    return f"{text} ({product.display_name})"
