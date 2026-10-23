# Alfa News Agent

Персональная новостная аналитика для компаний: профиль бизнеса → релевантные новости → анализ с источниками → уточняющие вопросы.

В этой ветке объединены `master`, `feature/news-analysis`, `feature/node-prototype` и `role5/integration-foundation`. История и предметные модули сохранены. Состав, проверки и порядок передачи в master: [MERGE_TO_MASTER.md](docs/integration/MERGE_TO_MASTER.md).

## Запуск без Docker

Нужны Python 3.12 и Node.js 24.13–24.x. Команды выполнять из корня проекта. Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt -c requirements.lock
npm ci
npm run integration:dev
```

Linux/macOS: вместо PowerShell-активации выполнить `source .venv/bin/activate`, остальные команды те же.

Открыть <http://localhost:8000/integration>. Одна команда запускает Python API, Node gateway и моки; Ctrl+C завершает процессы. Этот стенд использует маленькие синтетические данные, отдельные базы в `var/integration/dev`, demo без внешних LLM. Существующий продуктовый интерфейс доступен на <http://localhost:8000/> и пока использует старый `/api`.

## Подключить Python-ранжирование из объединённого проекта

Пакет `news_analysis` уже находится в репозитории. После установки зависимостей и сборки:

```powershell
$env:RANK_MODE = 'news-analysis'
$env:NEWS_MODULE_PATH = (Get-Location).Path
python scripts/dev.py --native-providers
```

Запускаются четыре процесса: Python, отдельные Node-сервисы агента и поиска, gateway. Профиль и ранжирование поступают из Python. Для возврата к мокам удалить эти переменные из окружения. На Linux/macOS аналогичный запуск: `RANK_MODE=news-analysis NEWS_MODULE_PATH=. python scripts/dev.py --native-providers`.

Настоящие данные, модели и сервисы подключаются явно. Наличие пакетов в master само по себе не переводит demo-интерфейс на обученный ML или production RAG. Локальные `/v1` анализы и история живут в памяти gateway до перезапуска/истечения срока; старый `/api` имеет отдельное SQLite-состояние.

## Модули и документы

| Путь | Назначение | Инструкция |
|---|---|---|
| `company_context/` | CSV → SQLite, профиль компании, платёжные связи, provenance и неизвестные значения | [Профиль](company_context/README.md) |
| `news_analysis/` | Признаки, граф, baseline/ML ranker, условные сценарии, подготовка датасетов | [Python API и CLI](news_analysis/README.md) |
| `server/`, `frontend/` | Node-прототип: агент, RSS, лексический поиск, UI, legacy `/api` | [Архитектура прототипа](docs/ARCHITECTURE.md) |
| `integration/`, `server/integration/` | Python/Node `/v1`, адаптеры, HTTP-клиенты, моки, SDK и общий запуск | [Архитектура интеграции](docs/integration/ARCHITECTURE.md) |
| `contracts/v1/` | JSON Schema 2020-12, OpenAPI 3.1, примеры | [Контракты](docs/integration/CONTRACTS.md) |
| `data/training_v1/`, `data/training_v2/` | Датасеты, источники, ревью и ограничения AI-разметки | [v1](data/training_v1/README.md), [v2](data/training_v2/README.md) |
| `tests/`, `server/**/tests/` | Unit-, контрактные и интеграционные проверки | [Проверка объединения](docs/integration/MERGE_TO_MASTER.md) |

Распределение работы пяти ролей: [TEAM.md](docs/integration/TEAM.md). После принятия объединения новые рабочие ветки создавать от обновлённого master. Старые указания на базу `feature/node-prototype` относятся к первоначальному отдельному PR интеграции.

## Отдельный legacy Node-прототип

```powershell
npm ci
# Только если личного .env ещё нет:
Copy-Item .env.example .env
npm start
```

Этот запуск обслуживает старый `/api` без Python. Первый старт импортирует полные gzip CSV в `var/app-node.sqlite3`; интерфейс — <http://localhost:8000/>. `start_windows.bat` также относится к этому режиму. Не смешивать его DTO `published/actions/relevance` с `/v1` `published_at/recommendations/score_kind`.

## Проверки

```powershell
python scripts/build_contracts.py --check
npm run typecheck
npm test
npm run build
python -m unittest discover -s tests -q
python scripts/prepare_news_source.py
python -m pytest tests/integration -q
python scripts/dev.py --smoke
```

Исходный `test_llm.py` — отдельная ручная сетевая проверка; он не входит в эту офлайн-команду unittest. Подробный отчёт объединения: [MERGE_TO_MASTER.md](docs/integration/MERGE_TO_MASTER.md).

## Docker — дополнительный способ запуска

```powershell
docker compose up --build --wait
```

Он запускает общий стенд с моками. Проверенный overlay Python-ветки можно подключить по [первоначальной инструкции интеграции](docs/integration/START_HERE.md). Docker необязателен для локальной разработки; контейнерный запуск в среде подготовки не проверялся.

## Ограничения

- Стандартный стенд помечает синтетические данные и моки; live LLM требует явной конфигурации и ключа в локальном `.env`. Ключи в Git не добавлять.
- Исходный Node RAG — лексический поиск по 64 OCR-страницам 9 документов; полноценный гибридный поиск и оценка качества остаются задачей роли 3. Недатированные bank-фрагменты не используются для подтверждения позиции банка на `as_of`.
- Python baseline имеет собственную шкалу; `score_kind` обязателен. Релевантность не является вероятностью ущерба. AI-разметка датасетов не заменяет независимую экспертную оценку; готовые проверенные веса не поставляются.
- Неизвестные единицы выручки, валюты/периоды платежей и условия договоров нельзя достраивать. Платёж не доказывает поставку, связь через физлицо — владение. Сценарные расчёты требуют явных параметров.
- Проект рассчитан на локальную разработку; выбор company ID не является аутентификацией.

GitHub-публикацию и merge выполняет пользователь. Подготовка этой объединённой ветки выполнена только локально.
