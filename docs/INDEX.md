# Карта проекта — с чего начать

> Одностраничная навигация для жюри и новых участников: что это, где что лежит, как запустить проверки. Подробности — по ссылкам.

## Что это
Персональная новостная аналитика для крупного бизнеса: **профиль компании → релевантные новости → интерпретация с источниками и позицией банка → уточняющие вопросы**. Не лента-пересказ, а объяснение влияния события на конкретную компанию. Агентная логика + RAG по аналитике Альфа-Банка.

## Структура (модули кода)

| Путь | Назначение | Стек / роль | Детали |
|---|---|---|---|
| `company_context/` | CSV → SQLite, профиль компании, граф платежей, provenance | Python / 1 | `company_context/README.md` |
| `news_analysis/` | признаки, граф, baseline/ML-ранкер, сценарии, датасеты | Python / 1 | `news_analysis/README.md` |
| `server/`, `frontend/` | агент, LLM, RSS, RAG-поиск, UI | Node/TS / 2,3,4 | `docs/ARCHITECTURE.md` |
| `integration/`, `server/integration/` | gateway, адаптеры, моки, общий запуск | Python+Node / 5 | `docs/integration/` |
| `contracts/v1/` | JSON Schema 2020-12 + OpenAPI 3.1 + примеры | — / 5 | `docs/integration/CONTRACTS.md` |

## Документация (ориентирование)

| Документ | О чём |
|---|---|
| `docs/ARCHITECTURE_OVERVIEW.md` | Единая схема гибрида Python+Node, потоки, контракты, роли |
| `docs/DECISIONS.md` | Ключевые решения (приватность, стек, единицы выручки) |
| `docs/SECURITY.md` | Безопасность AI: RBAC, защита данных, журналирование, prompt injection |
| `docs/MONITORING.md` | Метрики и процесс мониторинга качества (критерий №12) |
| `docs/SCALABILITY.md` | Масштабирование на отрасли/клиентов/источники (критерий №7) |
| `docs/LABELING_GUIDE.md` | Разметка релевантности 0–3 для оценки качества |
| `docs/DEMO_COMPANIES.md` | 3 демо-компании + матрица персонализации |
| `docs/DEMO_SCRIPT.md` | Пошаговый сценарий защиты (5 минут) |
| `docs/BASELINE_REPORT.md` | Реальная baseline-метрика ранжирования |
| `data/demo/` | Fixtures: компании, новости, разметка, привязка к аналитике банка |

## Как запустить проверки (офлайн, без расхода бюджета)

```bash
# качество ранжирования на демо-наборе
python scripts/evaluate_ranking.py --labels data/demo/eval/labels.json \
  --predictions data/demo/eval/sample_predictions.json --k 3

# оценка бюджета в рублях
python scripts/estimate_budget.py --usage data/demo/sample_usage.json \
  --prices data/demo/model_prices.json

# контрактный тест демо-новостей
python -m pytest tests/test_demo_news_contract.py -q
```

Полный список проверок кода (typecheck/test/build Python+Node) — в корневом `README.md`, раздел «Проверки».

## Демо за 2 минуты
Открыть UI → переключать 3 компании из `data/demo/demo_companies.json` (`U_34911`, `U_99262`, `U_4909`) → показать, что одна и та же новость про ключевую ставку значима для компаний с кредитами и не значима для энергокомпании без кредитов. Сценарий целиком — `docs/DEMO_SCRIPT.md`.

## Соответствие критериям ТЗ

| Критерий успеха | Где закрыт |
|---|---|
| Бизнес-контекст, отбор значимых событий | `company_context/`, `news_analysis/` |
| Персонализация (не отраслевой тренд) | `docs/DEMO_COMPANIES.md` (матрица) |
| Качество отбора (измеримо) | `docs/BASELINE_REPORT.md`, `scripts/evaluate_ranking.py` |
| Позиция банка отделена от вывода AI | `data/demo/news_bank_mapping.json`, карточка UI |
| Трассируемость (№11) | provenance + `docs/ARCHITECTURE_OVERVIEW.md` |
| Масштабируемость (№7) | `docs/SCALABILITY.md` |
| Мониторинг качества (№12) | `docs/MONITORING.md` |
| Безопасность AI | `docs/SECURITY.md` |
| Бюджет 500 ₽/день | `scripts/estimate_budget.py` |
