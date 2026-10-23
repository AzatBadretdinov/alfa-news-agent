"""Integration entry points for the agent/backend; no remote calls or LLM costs."""

from .contracts import deduplicate, text
from .features import FEATURE_VERSION, extract_features, baseline_score
from .graph import PaymentGraph
from .scenarios import optimize_actions


def prepare_training_rows(store, company_ids, events, as_of):
    """Export unlabelled, traceable company-event pairs for human annotation."""
    selected, _ = deduplicate(events, as_of)
    rows = []
    if len(set(company_ids)) != len(company_ids):
        raise ValueError("Repeated company_id")
    for uid in company_ids:
        profile = store.get_company_profile(uid)
        graph = PaymentGraph(store, uid)
        for event in selected:
            exposure = graph.exposure(event)
            features = extract_features(profile, event, as_of, exposure)
            rows.append({"company_id": uid, "event_id": event["event_id"], "query_id": uid + "@" + as_of,
                         "published_at": event["published_at"], "as_of": as_of,
                         "feature_version": FEATURE_VERSION, "features": features["values"],
                         "label": None, "label_origin": "human", "annotation_reason": "",
                         "annotation_context": {"event": event, "profile": profile, "graph": exposure,
                                                "feature_evidence": features["evidence"]}})
    return rows


def conditional_advice(profile, event):
    kind = event["event_type"]
    financing = any(profile["bank_products"].get(key) is True for key in ("loan", "leasing", "factoring"))
    if kind == "rate_change" and financing:
        return [{"action": "Сравнить стоимость сохранения текущих условий и защиты части финансирования от изменения ставки.",
                 "condition": "Договор допускает изменение ставки; известны остаток, сроки и доступные предложения.",
                 "required_data": ["остаток переоцениваемого долга", "изменение ставки по договору", "срок переоценки",
                                   "стоимость и доступность каждого действия"],
                 "profile_evidence": ["/bank_products"], "status": "conditional_direction"}]
    if kind == "rate_change" and profile["bank_products"].get("deposit") is True:
        return [{"action": "Проверить сроки депозитов, условия переоценки и потребность в ликвидности.",
                 "condition": "В профиле отмечен депозит; суммы и договорные условия требуют уточнения.",
                 "required_data": ["сроки и ставки депозитов", "план платежей"],
                 "profile_evidence": ["/bank_products/deposit"], "status": "conditional_direction"}]
    if kind in {"fx_change", "trade_restriction"}:
        return [{"action": "Уточнить затронутые валюты, страны, товары и договоры; затем сравнить доступные способы снизить экспозицию.",
                 "condition": "Сведения ФТС сами по себе не подтверждают импорт, экспорт или валютный риск.",
                 "required_data": ["валюты поступлений и выплат", "встречные потоки и уже действующая защита", "условия договоров"],
                 "profile_evidence": ["/foreign_trade"], "status": "conditional_direction"}]
    if kind == "commodity_price_change":
        return [{"action": "Уточнить, является компания покупателем или продавцом затронутого ресурса, и сравнить условия договоров.",
                 "condition": "ОКВЭД и платежи не определяют знак финансового эффекта.",
                 "required_data": ["объём открытых закупок или продаж", "доля расходов, чувствительная к цене", "доступные цены фиксации"],
                 "profile_evidence": ["/industry", "/payment_summary"], "status": "conditional_direction"}]
    return [{"action": "Проверить, какие операции и договоры компании затрагивает событие.",
             "condition": "Сначала подтвердить связь события с бизнесом.",
             "required_data": ["затронутые операции", "сроки", "доступные альтернативы и их стоимость"],
             "profile_evidence": ["/industry", "/geography"], "status": "conditional_direction"}]


def analyze_news(store, company_id, events, as_of, model=None, cases=(), bank_analytics=(), limit=10):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be 1..100")
    if not isinstance(cases, (list, tuple)) or not isinstance(bank_analytics, (list, tuple)):
        raise ValueError("cases and bank_analytics must be arrays")
    profile = store.get_company_profile(company_id)
    selected, future = deduplicate(events, as_of)
    selected_ids = {event["event_id"] for event in selected}
    by_event = {}
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each case must be an object")
        if case.get("company_id") != company_id or case.get("event_id") not in selected_ids:
            raise ValueError("Scenario must belong to this company and an included event")
        if case["event_id"] in by_event:
            raise ValueError("Only one scenario case per event is supported")
        by_event[case["event_id"]] = case
    bank = {}
    for item in bank_analytics:
        if not isinstance(item, dict):
            raise ValueError("Each bank excerpt must be an object")
        for key in ("event_id", "source", "excerpt"):
            text(item.get(key), "bank_analytics." + key)
        if item["event_id"] not in selected_ids:
            raise ValueError("Bank excerpt must reference an included event")
        bank.setdefault(item["event_id"], []).append(item)
    graph = PaymentGraph(store, company_id)
    cards = []
    for event in selected:
        exposure = graph.exposure(event)
        features = extract_features(profile, event, as_of, exposure)
        score = model.predict(features["values"]) if model else baseline_score(features["values"])
        case = by_event.get(event["event_id"])
        if case and case.get("kind") != event["event_type"]:
            raise ValueError("Scenario kind must match the event_type")
        scenario = optimize_actions(case) if case else {"status": "not_requested", "recommendation": None}
        bank_view = bank.get(event["event_id"], [])
        checks = []
        if not bank_view:
            checks.append("bank_position_not_provided")
        if event["fact_status"] != "confirmed":
            checks.append("event_requires_source_verification")
        if not model:
            checks.append("ranking_uses_manual_baseline_no_trained_model")
        elif model.metadata.get("label_origin") != "human":
            checks.append("ranker_not_validated_on_human_labels")
        if not case:
            checks.append("financial_effect_not_estimated")
        elif scenario["status"] == "needs_parameters":
            checks.append("scenario_parameters_missing")
        checks.extend(profile["data_quality"]["warnings"])
        cards.append({"event_id": event["event_id"], "news_id": event["news_id"], "score": score,
                      "score_kind": "logistic_relevance_uncalibrated" if model else "manual_feature_baseline",
                      "facts": event, "company_evidence": {"profile_provenance": profile["provenance"],
                                                             "features": features, "graph": exposure},
                      "bank_view": bank_view,
                      "model_assessment": {"feature_contributions": model.explain(features) if model else [],
                                           "intercept": model.intercept if model else None,
                                           "scenario": scenario, "conditional_advice": conditional_advice(profile, event)},
                      "self_check": {"warnings": sorted(set(checks)),
                                     "needs_more_data": bool(checks), "position_of_bank_inferred": False}})
    cards.sort(key=lambda card: (-card["score"], card["event_id"]))
    return {"schema_version": "1.0", "company_id": company_id, "as_of": as_of,
            "ranking_model": model.to_dict() if model else None,
            "events_considered": len(cards), "cards": cards[:limit], "truncated": len(cards) > limit,
            "excluded_future_news_ids": future,
            "trace": [{"step": "load_company_profile", "snapshot": store.metadata["built_at"]},
                      {"step": "deduplicate_and_filter_publication_time", "events": len(selected)},
                      {"step": "match_company_and_all_payment_edges", "feature_version": FEATURE_VERSION},
                      {"step": "rank_events", "method": "learned" if model else "manual_baseline"},
                      {"step": "evaluate_conditional_actions", "cases": len(by_event)},
                      {"step": "self_check", "warnings": sorted({w for c in cards for w in c["self_check"]["warnings"]})}],
            "limitations": ["Ранжирование оценивает релевантность, а не вероятность или величину ущерба.",
                            "Прогноз временных рядов и эмпирическое обучение эффекта действий требуют отдельной истории."]}
