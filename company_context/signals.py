"""Explainable candidate topics for ranking; weights are rules, not probabilities."""


def relevance_signals(profile):
    result = []

    def add(topic, reason, weight, evidence, entities=None):
        result.append({"topic": topic, "reason": reason, "weight": weight,
                       "evidence": evidence, "entities": entities or []})

    products = profile["bank_products"]
    credit = [key for key in ("loan", "leasing", "factoring") if products[key] is True]
    if credit:
        add("ключевая ставка и финансирование", "Отмечены продукты финансирования: " + ", ".join(credit)
            + ". Размер обязательств и условия ставки неизвестны.", 0.9,
            ["/bank_products/" + key for key in credit])
    if products["deposit"] is True:
        add("депозитные ставки", "В данных отмечен депозитный продукт.", 0.7, ["/bank_products/deposit"])
    trade = profile["foreign_trade"]
    if trade["has_fts"] is True or (trade["has_fts"] is None and trade["countries"]):
        add("внешняя торговля и валютные условия", "Есть сведения ФТС. Направление торговли и валюты не установлены.",
            0.8, ["/foreign_trade/has_fts", "/foreign_trade/countries"], trade["countries"])
        for index, country in enumerate(trade["countries"]):
            add("торговые условия: " + country, "Страна указана в сведениях ФТС.", 0.8,
                [f"/foreign_trade/countries/{index}"], [country])
    industry = profile["industry"]
    if industry["okved_code"] or industry["name"]:
        add("отраслевые события", "Основная деятельность: " + (industry["name"] or industry["okved_code"]),
            0.75, ["/industry/okved_code", "/industry/name"],
            [v for v in (industry["okved_code"], industry["name"], industry["sector"]) if v])
    if profile["geography"]["region"]:
        add("региональные события", "Регион регистрации компании; география операций может отличаться.",
            0.6, ["/geography/region"], [profile["geography"]["region"]])
    if profile["group"]["members_total"] > 1 or profile["related_companies_total"]:
        add("события связанных компаний", "Есть общая группа или связи через физлиц. Контроль и владение не установлены.",
            0.7, ["/group", "/related_companies"])
    for index, cp in enumerate(profile["counterparties"]):
        if cp["share_of_direction"] is not None and cp["share_of_direction"] >= 0.25:
            add("события контрагента: " + cp["company_id"],
                "Не менее 25% наблюдаемого потока данного направления. Договорная роль не установлена.",
                0.85, [f"/counterparties/{index}"], [cp["company_id"]])
    return sorted(result, key=lambda item: (-item["weight"], item["topic"]))
