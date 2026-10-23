"""Versioned company-event features; missing values have their own indicators."""

import math
from .contracts import normalized, timestamp, validate_event

FEATURE_VERSION = "company_event_v1"
FEATURE_NAMES = (
    "rate_financing", "rate_deposit", "fx_trade", "industry_match", "country_match", "region_match",
    "direct_company_match", "related_company_match", "graph_in_share", "graph_out_share",
    "graph_in_coverage", "graph_out_coverage", "freshness",
    "disputed", "industry_unknown", "financing_unknown", "deposit_unknown",
    "trade_unknown", "graph_in_unknown", "graph_out_unknown",
)
BASELINE_WEIGHTS = (0.9, 0.7, 0.8, 0.75, 0.8, 0.6, 1.0, 0.7, 0.85, 0.85, 0, 0, 0.1, -0.5, 0, 0, 0, 0, 0, 0)


def extract_features(profile, event, as_of, graph=None):
    validate_event(event)
    if profile.get("schema_version") != "1.0":
        raise ValueError("Expected company profile schema 1.0")
    age = (timestamp(as_of) - timestamp(event["published_at"])).total_seconds() / 86400
    if age < 0:
        raise ValueError("Cannot score a news item published after as_of")
    if graph and (graph.get("company_id") != profile["company_id"] or graph.get("event_id") != event["event_id"]):
        raise ValueError("Graph evidence belongs to another company/event")
    products = profile.get("bank_products", {})
    financing = [products.get(key) for key in ("loan", "leasing", "factoring")]
    trade = profile.get("foreign_trade", {})
    industry = profile.get("industry", {})
    incoming = (graph or {}).get("in", {}).get("matched_share")
    outgoing = (graph or {}).get("out", {}).get("matched_share")
    in_coverage = (graph or {}).get("in", {}).get("attribute_coverage_share")
    out_coverage = (graph or {}).get("out", {}).get("attribute_coverage_share")
    rate = event["event_type"] == "rate_change"
    values = {
        "rate_financing": float(rate and any(x is True for x in financing)),
        "rate_deposit": float(rate and products.get("deposit") is True),
        "fx_trade": float(event["event_type"] == "fx_change" and
                          (trade.get("has_fts") is True or
                           (trade.get("has_fts") is None and bool(trade.get("countries"))))),
        "industry_match": float(industry.get("okved_division") in event.get("okved_divisions", [])),
        "country_match": float(trade.get("has_fts") is not False and bool(normalized(trade.get("countries", [])) & normalized(event.get("countries", [])))),
        "region_match": float(bool(normalized([profile.get("geography", {}).get("region")]) & normalized(event.get("regions", [])))),
        "direct_company_match": float(profile["company_id"] in event.get("company_ids", [])),
        "related_company_match": float(bool((graph or {}).get("related_company_matches"))),
        "graph_in_share": incoming if incoming is not None else 0.0,
        "graph_out_share": outgoing if outgoing is not None else 0.0,
        "graph_in_coverage": in_coverage if in_coverage is not None else 0.0,
        "graph_out_coverage": out_coverage if out_coverage is not None else 0.0,
        "freshness": math.exp(-math.log(2) * age / 7),
        "disputed": float(event["fact_status"] == "disputed"),
        "industry_unknown": float(not industry.get("okved_division")),
        "financing_unknown": float(rate and not any(x is True for x in financing) and any(x is None for x in financing)),
        "deposit_unknown": float(rate and products.get("deposit") is None),
        "trade_unknown": float(bool(event.get("countries")) and trade.get("has_fts") is not False and not trade.get("countries")),
        "graph_in_unknown": float(incoming is None or in_coverage is None or in_coverage < 1),
        "graph_out_unknown": float(outgoing is None or out_coverage is None or out_coverage < 1),
    }
    pointers = {
        "rate_financing": ["/bank_products/loan", "/bank_products/leasing", "/bank_products/factoring"],
        "rate_deposit": ["/bank_products/deposit"], "industry_match": ["/industry/okved_division"],
        "fx_trade": ["/foreign_trade"],
        "country_match": ["/foreign_trade"], "region_match": ["/geography/region"],
        "direct_company_match": ["/company_id"], "industry_unknown": ["/industry"],
        "financing_unknown": ["/bank_products"], "deposit_unknown": ["/bank_products/deposit"],
        "trade_unknown": ["/foreign_trade"],
    }
    evidence = {name: {"profile_pointers": pointers.get(name, []), "news_sources": event["sources"],
                       "graph_pointer": ("/related_company_matches" if name == "related_company_match" else
                                         "/" + ("in" if "_in_" in name else "out") if name.startswith("graph_") else None)}
                for name in FEATURE_NAMES}
    return {"version": FEATURE_VERSION, "values": values, "evidence": evidence}


def baseline_score(values):
    """Explicit untrained comparison baseline, inspired by existing theme priorities."""
    return sum(values[name] * weight for name, weight in zip(FEATURE_NAMES, BASELINE_WEIGHTS))
