"""Deterministic routing rules: tier 0 of the hybrid router.

Each rule is written for precision, not coverage. A rule only answers when the
message is unambiguous; otherwise it returns ``False`` and the message moves
on to the semantic tier and then the LLM tier. Rules never authorize anything:
order ownership is still enforced by the order tools, and every message has
already passed the input guard before routing.
"""

from __future__ import annotations

import re


ORDER_ID_PATTERN = re.compile(r"\bNS-\d{2}-\d{4}-\d\b", re.I)
ORDER_OPERATION_PATTERN = re.compile(
    r"\b(?:where|status|track|tracking|delivery|deliver|delivered|arrive|"
    r"cancel|refund|eligible|eligibility|check|returnable)\b|"
    r"\b(?:can|may|am)\s+i\s+(?:return|send\s+back)\b|"
    r"\breturn\s+(?:order|it|this|that)\b|"
    r"\bsend\s+back\b|\bkab\s+aayega\b",
    re.I,
)
PRODUCT_LOOKALIKE_PATTERN = re.compile(
    r"\b(?:capacity|size|material|colour|color|care|feature|features|"
    r"specification|specifications|policy|what\s+is|what's|how\s+does|"
    r"does\s+it|waterproof|weather\s*proof|water\s*resistant)\b",
    re.I,
)
_FOLLOW_UP_REFERENCE = re.compile(
    r"\b(?:it|that|this|that\s+one|this\s+one|the\s+order|my\s+order)\b", re.I
)
_FOLLOW_UP_ACTION = re.compile(
    r"\b(?:return|returnable|eligible|send\s+back|status|where|track|deliver|"
    r"delivered|arrive|cancel|refund|check|money\s+(?:sent\s+)?back)\b",
    re.I,
)


def is_explicit_order_operation(message: str) -> bool:
    """Recognize an unambiguous operation on exactly one stated order.

    Product questions may mention an order as background context, so an order
    ID alone is not enough. Only a clear status, delivery, return, refund,
    cancellation, or tracking operation is resolved locally.
    """

    if len(ORDER_ID_PATTERN.findall(message)) != 1:
        return False
    if not ORDER_OPERATION_PATTERN.search(message):
        return False
    if re.search(r"\breturn\s+policy\b", message, re.I):
        return False
    if PRODUCT_LOOKALIKE_PATTERN.search(message):
        return bool(
            re.search(
                r"\b(?:return|returnable|eligible|eligibility|send\s+back|"
                r"refund|cancel)\b",
                message,
                re.I,
            )
            and not re.search(r"\b(?:policy|what\s+is|what's)\b", message, re.I)
        )
    return True


def is_memory_order_follow_up(message: str, *, active_order_id: str | None) -> bool:
    """Recognize a clear pronoun follow-up about the verified active order."""

    if active_order_id is None or ORDER_ID_PATTERN.search(message):
        return False
    if re.search(r"\b(?:other|another|different)\b", message, re.I):
        return False
    return bool(
        _FOLLOW_UP_REFERENCE.search(message) and _FOLLOW_UP_ACTION.search(message)
    )


_HUMAN_TARGET = (
    r"(?:a\s+|an\s+|the\s+|some\s+|real\s+|live\s+)*"
    r"(?:human|person|agent|representative|rep|someone|somebody|staff|"
    r"supervisor|manager|operator|specialist|team\s+member)"
)
_HUMAN_REQUEST_PATTERNS = (
    re.compile(
        r"\b(?:talk|speak|chat)\s+(?:to|with)\s+" + _HUMAN_TARGET + r"\b", re.I
    ),
    re.compile(
        r"\b(?:connect|transfer|put)\s+me\s+(?:to|with|through\s+to)\s+"
        + _HUMAN_TARGET
        + r"\b",
        re.I,
    ),
    re.compile(r"\b(?:get|give|find)\s+me\s+" + _HUMAN_TARGET + r"\b", re.I),
    re.compile(
        r"\b(?:i\s+)?(?:need|want|request|would\s+like)\s+(?:to\s+(?:talk|speak)\s+"
        r"(?:to|with)\s+)?" + _HUMAN_TARGET + r"\b",
        re.I,
    ),
    re.compile(
        r"\b(?:real\s+person|live\s+agent|human\s+agent|human\s+being)\b", re.I
    ),
    re.compile(
        r"^\s*(?:human|agent|representative|operator|supervisor)"
        r"(?:\s+please)?\s*[.!?]*\s*$",
        re.I,
    ),
    re.compile(
        r"\bkisi\s+(?:insaan|insan|aadmi|agent|banda)\s+se\s+baat\b", re.I
    ),
)
_HUMAN_NEGATION = re.compile(
    r"\b(?:don'?t|do\s+not|dont|no\s+need|not|never)\b[^.?!]{0,30}"
    r"\b(?:human|person|agent|representative|someone|staff)\b",
    re.I,
)


def is_explicit_human_request(message: str) -> bool:
    """Recognize an explicit request for a person, unless it is negated."""

    if _HUMAN_NEGATION.search(message):
        return False
    return any(pattern.search(message) for pattern in _HUMAN_REQUEST_PATTERNS)


# Closed vocabulary of smalltalk phrases. A message is "pure smalltalk" only
# when it is made entirely of these phrases (plus filler words), so a request
# such as "hi, can I return order NS-..." never matches.
_SMALLTALK_PHRASES = tuple(
    sorted(
        {
            "hi", "hii", "hiii", "hello", "hey", "hiya", "yo", "howdy",
            "good morning", "good afternoon", "good evening", "good day",
            "namaste", "namaskar", "hola", "greetings",
            "thanks", "thank you", "thank you so much", "thanks a lot",
            "many thanks", "thx", "ty", "cheers", "much appreciated",
            "appreciate it", "shukriya", "dhanyavaad",
            "that was helpful", "that helped", "that helps", "very helpful",
            "helpful", "perfect", "awesome", "nice", "great", "cool",
            "ok", "okay", "k", "alright", "all right", "fine", "sure",
            "got it", "noted", "understood", "sounds good",
            "bye", "goodbye", "bye bye", "see you", "see you later",
            "see ya", "take care", "good night", "that's all",
            "that is all", "nothing else", "no thanks", "that's it",
            "who are you", "what are you", "are you a bot",
            "are you a robot", "are you human", "are you a human",
            "are you a real person", "are you a bot or a real person",
            "are you a bot or a human", "what is your name",
            "what's your name",
            "what can you do", "what can you help me with",
            "what can you help with", "how can you help",
            "how can you help me", "what do you do", "help", "help me",
            "i need help", "i need some help", "can you help me",
            "how are you", "how are you doing", "how's it going",
            "how is it going", "how do you do",
        },
        key=len,
        reverse=True,
    )
)
_SMALLTALK_FILLER = frozenset(
    {
        "there", "mate", "again", "guys", "team", "bot", "northstar",
        "so", "much", "very", "today", "for", "and", "please", "pls",
        "then", "too", "all", "everyone", "friend", "buddy", "sir", "madam",
        "ji", "dear", "assistant",
    }
)


def _normalize_words(message: str) -> str:
    lowered = message.casefold().replace("’", "'")
    lowered = re.sub(r"[^\w\s']", " ", lowered)
    return " ".join(lowered.split())


def is_pure_smalltalk(message: str) -> bool:
    """True only when every word belongs to the closed smalltalk vocabulary."""

    remaining = _normalize_words(message)
    if not remaining or len(remaining) > 80:
        return False
    matched_phrase = False
    while remaining:
        for phrase in _SMALLTALK_PHRASES:
            if remaining == phrase or remaining.startswith(phrase + " "):
                remaining = remaining[len(phrase):].strip()
                matched_phrase = True
                break
        else:
            word, _, rest = remaining.partition(" ")
            if word not in _SMALLTALK_FILLER:
                return False
            remaining = rest
    return matched_phrase


_KEYBOARD_RUNS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_VOWELS = set("aeiouy")


def _is_word_like(token: str) -> bool:
    if len(token) >= 3 and len(set(token)) == 1:
        return False
    if len(token) >= 4 and any(token in row for row in _KEYBOARD_RUNS):
        return False
    if not any(character in _VOWELS for character in token):
        return False
    return re.search(r"[^aeiouy\d]{5,}", token) is None


def is_gibberish(message: str) -> bool:
    """Recognize keyboard mashing, punctuation-only, or digits-only input.

    Returns ``False`` for anything that looks like real words in any
    romanized language, so Hinglish such as "kab aayega" passes through.
    """

    if ORDER_ID_PATTERN.search(message):
        return False
    if not re.search(r"\w", message):
        return True
    words = re.findall(r"[^\W\d_]+", message.casefold())
    if not words:
        return bool(re.fullmatch(r"[\d\s\W]+", message))
    word_like = sum(_is_word_like(word) for word in words)
    return word_like / len(words) < 0.5
