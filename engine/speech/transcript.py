"""Transcript cleaning and wake-name detection (adapted from Jarvis)."""

from __future__ import annotations

import re

_NAME = re.compile(
    r"\b(pekka|p\.e\.k\.k\.a|peka|pecca|pecka|pecker|packa|paca|pika|pega|becca|becker|becky|pk|nova|jarvis|jarvys|jervis|jarvas|jarves|javis)\b",
    re.I,
)

_WAKE_PREFIX = re.compile(
    r"^(hey|ok|okay|a)?\s*(pekka|p\.e\.k\.k\.a|peka|pecca|pecka|pecker|packa|paca|pika|pega|becca|becker|becky|pk|nova|jarvis|jarvys|jervis|jarvas|jarves|javis)\b[\s,.!?\-]*",
    re.I,
)


def clean_transcript(text: str, strip_name: bool = False, wake_name: str = "P.E.K.K.A") -> str:
    """Drop non-speech annotations like [Music], (sigh) and optionally strip leading wake name."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]|\*[^*]*\*", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,-")
    if strip_name:
        text = _WAKE_PREFIX.sub("", text).strip()
        text = re.sub(rf"^(hey|ok|okay)?\s*{re.escape(wake_name)}\b[\s,.!?\-]*", "", text, flags=re.I).strip()
    return text if re.search(r"[A-Za-z\u0900-\u097F]{2,}", text) else ""


def addressed(text: str, wake_name: str = "P.E.K.K.A") -> bool:
    """True if speech names P.E.K.K.A (or configured wake_name)."""
    if bool(_NAME.search(text)):
        return True
    return bool(re.search(rf"\b{re.escape(wake_name)}\b", text, re.I))
