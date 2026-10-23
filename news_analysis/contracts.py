"""Validated input contracts. Text extraction belongs to the news/RAG component."""

import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

EVENT_TYPES = {"rate_change", "fx_change", "commodity_price_change", "trade_restriction",
               "regional_event", "company_event", "other"}


def finite(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name}: expected a finite number")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{name}: outside allowed range [{minimum}, {maximum}]")
    return float(value)


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: expected a nonempty string")
    return value


def timestamp(value):
    text(value, "timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def validate_event(event):
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    for key in ("news_id", "event_id", "title"):
        text(event.get(key), key)
    if event.get("event_type") not in EVENT_TYPES:
        raise ValueError("Unknown event_type")
    timestamp(event.get("published_at"))
    if event.get("event_at") is not None:
        timestamp(event["event_at"])
    for key in ("okved_divisions", "countries", "regions", "company_ids"):
        if not isinstance(event.get(key, []), list):
            raise ValueError(f"{key} must be a list")
        for item in event.get(key, []):
            text(item, key)
        if key == "okved_divisions" and any(not re.fullmatch(r"\d{2}", x) for x in event.get(key, [])):
            raise ValueError("okved_divisions must contain two-digit codes")
    if event.get("company_ids"):
        text(event.get("entity_mapping_source"), "entity_mapping_source")
    if not isinstance(event.get("sources"), list) or not event["sources"]:
        raise ValueError("Every event needs at least one source with an excerpt")
    for source in event["sources"]:
        if not isinstance(source, dict):
            raise ValueError("Each source must be an object")
        parsed = urlparse(text(source.get("url"), "source.url"))
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("Source URL must be HTTP(S)")
        text(source.get("excerpt"), "source.excerpt")
    if event.get("fact_status") not in {"reported", "confirmed", "disputed"}:
        raise ValueError("fact_status must be reported, confirmed or disputed")
    return event


def normalized(values):
    return {x.strip().casefold().replace("ё", "е") for x in values if x}


def deduplicate(events, as_of):
    """One item per upstream event cluster. Later reporting cannot leak backwards."""
    cutoff = timestamp(as_of)
    if not isinstance(events, (list, tuple)):
        raise ValueError("events must be an array")
    clusters, future = {}, []
    ids = set()
    for event in events:
        validate_event(event)
        if event["news_id"] in ids:
            raise ValueError("Duplicate news_id")
        ids.add(event["news_id"])
        if timestamp(event["published_at"]) > cutoff:
            future.append(event["news_id"])
            continue
        clusters.setdefault(event["event_id"], []).append(event)
    result = []
    for group in clusters.values():
        chosen = max(group, key=lambda e: (timestamp(e["published_at"]), e["news_id"]))
        # Keep the chosen extraction and its evidence together; do not silently merge claims.
        result.append(dict(chosen, duplicate_news_ids=sorted(e["news_id"] for e in group
                                                           if e["news_id"] != chosen["news_id"])))
    return result, future
