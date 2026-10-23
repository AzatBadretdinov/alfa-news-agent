"""Adapters for ContextStore and the checked, optional news_analysis checkout."""
import importlib
import os
import sys
from datetime import datetime
from pathlib import Path
from company_context import ContextStore, build_database
from .contracts import ROOT


def prepare_context():
    database = Path(os.environ.get("CONTEXT_DB", ROOT / "var/integration/context.sqlite3"))
    mode = os.environ.get("CONTEXT_MODE", "fixture")
    if mode not in {"fixture", "existing"}:
        raise ValueError("CONTEXT_MODE must be fixture or existing")
    if mode == "fixture":
        # Separate fixture database: never implicitly rebuild a user's existing database.
        database.parent.mkdir(parents=True, exist_ok=True)
        if not database.exists():
            fixtures = ROOT / "tests/fixtures/company_context"
            build_database(fixtures / "companies.csv", database, links=fixtures / "links.csv",
                           payments=fixtures / "payments.csv", revenue_unit="unknown")
    if not database.is_file():
        raise ValueError("CONTEXT_DB does not exist; build it explicitly with company_context CLI")
    with ContextStore(database):
        pass
    return database, mode


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class RankAdapter:
    def __init__(self):
        self.mode = os.environ.get("RANK_MODE", "mock")
        self.analyze = None
        if self.mode == "news-analysis":
            path = Path(os.environ.get("NEWS_MODULE_PATH", ROOT / "var/sources/news-analysis"))
            if not (path / "news_analysis/__init__.py").is_file():
                raise ValueError("Run python scripts/prepare_news_source.py before RANK_MODE=news-analysis")
            sys.path.insert(0, str(path.resolve()))
            self.analyze = importlib.import_module("news_analysis").analyze_news
        elif self.mode != "mock":
            raise ValueError("RANK_MODE must be mock or news-analysis")

    def rank(self, store, request):
        ids = [event["news_id"] for event in request["events"]]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate news_id")
        if self.analyze:
            # Only validated extraction enters the original pipeline. No fabricated scenario parameters.
            result = self.analyze(store, request["company_id"], request["events"], request["as_of"], limit=request["limit"])
            items = []
            for card in result["cards"]:
                features = card["company_evidence"]["features"]
                reasons = [{"code": key, "text": f"{key}: {features['values'][key]}",
                            "profile_paths": value["profile_pointers"]}
                           for key, value in features["evidence"].items() if features["values"][key]]
                items.append({"news_id": card["news_id"], "event_id": card["event_id"], "score": card["score"],
                              "score_kind": card["score_kind"], "reasons": reasons or [
                                  {"code": "baseline", "text": "Базовая оценка; прямое влияние не подтверждено", "profile_paths": []}],
                              "warnings": card["self_check"]["warnings"]})
            return {"company_id": result["company_id"], "as_of": result["as_of"], "items": items,
                    "excluded_future_news_ids": result["excluded_future_news_ids"], "truncated": result["truncated"]}
        profile = store.get_company_profile(request["company_id"])
        future, clusters = [], {}
        for event in request["events"]:
            if timestamp(event["published_at"]) > timestamp(request["as_of"]):
                future.append(event["news_id"])
                continue
            old = clusters.get(event["event_id"])
            if not old or (timestamp(event["published_at"]), event["news_id"]) > (timestamp(old["published_at"]), old["news_id"]):
                clusters[event["event_id"]] = event
        items = []
        for event in clusters.values():
            match = profile["industry"]["okved_division"] in event["okved_divisions"]
            items.append({"news_id": event["news_id"], "event_id": event["event_id"], "score": 0.8 if match else 0.2,
                          "score_kind": "mock", "reasons": [{"code": "fixture_industry", "text": "Учебное сопоставление ОКВЭД" if match else "Учебный общий контекст",
                                                              "profile_paths": ["/industry/okved_division"]}],
                          "warnings": ["mock_ranker_not_a_model"]})
        items.sort(key=lambda item: (-item["score"], item["event_id"]))
        return {"company_id": request["company_id"], "as_of": request["as_of"], "items": items[:request["limit"]],
                "excluded_future_news_ids": future, "truncated": len(items) > request["limit"]}
