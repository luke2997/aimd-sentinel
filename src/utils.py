from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from typing import Any


def stable_hash(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("®", "").replace("™", "")
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def short_alias(device_name: str) -> str:
    """Return a search-friendly short alias for long product-family names."""
    first = re.split(r"[;,(]", device_name)[0].strip()
    return first if len(first) >= 3 else device_name.strip()


def split_search_aliases(value: str | None, *, max_aliases: int = 8) -> list[str]:
    """
    Convert long FDA product-family names into openFDA-safe search aliases.

    Example:
    "MAGNETOM Sola; MAGNETOM Altea; MAGNETOM Flow.Elite"
    -> ["MAGNETOM Sola", "MAGNETOM Altea", "MAGNETOM Flow Elite"]

    openFDA search can reject long quoted phrases containing semicolons,
    parentheses, plus signs, slashes, or other Lucene-ish punctuation.
    This function keeps specific product names while avoiding brittle queries.
    """
    if not value:
        return []

    raw = str(value).replace("®", "").replace("™", "")
    parts = re.split(r"[;|]", raw)
    aliases: list[str] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Remove version strings and parenthetical fragments for search.
        variants = [part, re.sub(r"\([^)]*\)", " ", part)]

        for variant in variants:
            # Keep alpha/numeric tokens and turn punctuation into spaces.
            cleaned = unicodedata.normalize("NFKC", variant)
            cleaned = re.sub(r"[\/,:;+*?^~!{}\[\]()]", " ", cleaned)
            cleaned = cleaned.replace(".", " ")
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if len(cleaned) < 3:
                continue
            if cleaned.lower() in {"system", "software", "station", "web"}:
                continue
            if cleaned not in aliases:
                aliases.append(cleaned)
            if len(aliases) >= max_aliases:
                return aliases

    return aliases


def clean_openfda_phrase(value: str) -> str:
    """Return a phrase that is safe to put inside an openFDA quoted search term."""
    cleaned = str(value).replace("®", "").replace("™", "").replace('"', " ")
    cleaned = unicodedata.normalize("NFKC", cleaned)
    cleaned = re.sub(r"[;|]", " ", cleaned)
    cleaned = re.sub(r"[\/,:;+*?^~!{}\[\]()]", " ", cleaned)
    cleaned = cleaned.replace(".", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parse_date(value: Any) -> date | None:
    if value in (None, "", "null"):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def quote_openfda_term(value: str) -> str:
    cleaned = clean_openfda_phrase(value)
    return f'"{cleaned}"'


def field_term(field: str, value: str) -> str:
    return f"{field}:{quote_openfda_term(value)}"


def or_query(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def and_query(parts: list[str]) -> str:
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(" + " AND ".join(parts) + ")"


def record_key(record: dict[str, Any], candidates: list[str], fallback_prefix: str) -> str:
    for key in candidates:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return f"{fallback_prefix}:{stable_hash(record)[:24]}"


def flatten_mdr_text(record: dict[str, Any]) -> str:
    texts = []
    for item in record.get("mdr_text") or []:
        if isinstance(item, dict):
            text = item.get("text") or item.get("text_type_code") or ""
            if text:
                texts.append(str(text))
    return "\n\n".join(texts).strip()


def first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None
