# 📰 Alfa News Agent

<p align="center">
  **ИИ-агент для анализа новостей**
  <br>
  Проект команды для <b>Alpha Hackathon · Новостная аналитика</b>
</p>

---

## 💡 О проекте

**Alfa News Agent** — проект по созданию интеллектуального агента, который использует большие языковые модели (LLM) для анализа новостей и получения полезных аналитических выводов.

Наша цель — превратить поток новостной информации в структурированную аналитику, которая помогает лучше понимать события и их контекст.

## 🛠️ Технологии

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-AI-7C3AED?style=for-the-badge)
![GitHub](https://img.shields.io/badge/GitHub-181717?style=for-the-badge&logo=github&logoColor=white)

## 🚀 Статус

Реализован модуль **бизнес-контекста компании (задача 1)**: загрузка трёх CSV,
SQLite-граф платежей и связей, профиль компании, положение в выборке и
объяснимые признаки значимости новостей. Запуск без Docker и внешних зависимостей.
Инструкция и контракт: [company_context/README.md](company_context/README.md).

```powershell
python -m company_context build --companies data/appendix_1/df_Uid_data_hack.csv --links data/appendix_1/df_Fid_Uid_link_hack.csv --payments data/appendix_1/df_Uid_payment_hack.csv --database data/processed/company_context.sqlite --report data/processed/dataset_audit.json
python -m company_context profile --database data/processed/company_context.sqlite --company-id U_67 --output data/processed/company_profile.json
python -m unittest discover -s tests -v
```

🟡 **В разработке**

Добавлен модуль **анализа новостей `news_analysis`**: обучение ранжирования на
размеченных парах «компания–событие», релевантность по полному графу платежей и связям,
сценарные расчёты и подбор долей действий с учётом затрат, бюджета и ограничений.
Python API, CLI, контракты и ограничения: [news_analysis/README.md](news_analysis/README.md).
Внешних зависимостей и сетевых вызовов у расчётного модуля нет.

Подготовлен [стартовый набор обучения](data/training_v1/README.md): 24 публикации,
20 профилей, 480 пар с AI-разметкой, признаками, источниками и отложенными выборками.
Есть воспроизводимая сборка, проверка целостности и импорт человеческой проверки.
AI-разметка не является независимым эталоном; готовые обученные веса не поставляются.
Доступен [пересмотр v2 с опорой на исследования](data/training_v2/README.md):
8 рецензированных статей, рабочая статья ФРБ и официальная методология;
34 изменения приоритета, 323 предварительно допустимые пары, 157 отложенных.
Для каждой оценки сохранены источники, условия применимости и неизвестные величины.
Это AI-разметка с исследовательским обоснованием; независимой экспертной проверки нет.
Финансовые расчёты условны и требуют явных параметров. Парсер новостей, RAG,
LLM-оркестратор, текстовая AI-интерпретация и интерфейс находятся в разработке.

---

<p align="center">
  Made with 🧠 and Python
</p>
