# PROJECT STATE
## Философия здорового сообщества / AION

> Контрольная точка проекта.
> Этот документ фиксирует подтверждённое состояние системы,
> принятые решения и ближайший следующий шаг.
> Не заменяет инструкции проекта.

---

## 1. Цель

Постепенно проверить, какие элементы концепции здорового
и постдефицитного общества могут быть:

формализованы → измерены → смоделированы → реализованы →
проверены → масштабированы.

AION рассматривается как один из технических инструментов
практической проверки этой концепции.

---

## 2. Рабочий протокол

Текущий инженерный протокол AION:

READ-ONLY статический аудит
→ карта существующей архитектуры
→ целевая архитектура
→ архитектурная заморозка
→ реализация
→ тестирование
→ интеграция.

До завершения READ-ONLY аудита архитектуру не объединять
и не изменять без необходимости.

---

## 3. Подтверждённое состояние AION

### Core

Существуют:

- core/engine.py
- core/llm.py
- core/truth.py
- core/diagnostics.py
- core/version.py

### Execution flow

Подтверждена цепочка:

Engine
→ LLM Gateway
→ Provider Registry
→ Provider
→ внешний LLM API.

`core/llm.py` является единой точкой обращения Engine к LLM.

### Truth layer

Существуют:

- knowledge/truth/truth.json
- knowledge/truth/system.yaml

`core/truth.py` предоставляет:

- load_truth()
- load_system()
- get_principles()
- get_execution_limits()
- truth_status()

Truth читается рабочим ядром.

Автоматическая запись Truth не предусмотрена.

### Проверено

Успешно выполнено:

- Python compile для core/truth.py и core/engine.py;
- загрузка принципов;
- загрузка execution limits;
- truth_status();
- load_state();
- build_prompt().

Текущие limits:

- max_iterations = 3
- timeout_seconds = 30

---

## 4. Подтверждённая архитектура

Engine:

- загружает state;
- читает Truth;
- строит prompt;
- вызывает LLM;
- сохраняет результат.

Engine не должен изменять Truth.

LLM Gateway:

`core/llm.py → providers.registry.create_provider()`

Provider:

`OpenAICompatibleProvider`

Использует:

- AION_API_URL
- AION_API_KEY
- AION_MODEL

API-ключ не хранится в коде.

---

## 5. Обнаруженные проблемы

### P-001 — max_iterations пока декларативен

Truth содержит:

`max_iterations = 3`

Engine передаёт значение в state и prompt.

Но реального механизма, ограничивающего количество итераций,
в Engine пока не обнаружено.

Следовательно:

`max_iterations` пока не является enforced safety control.

Статус: OPEN.

### P-002 — timeout не связан с Truth

Truth содержит:

`timeout_seconds = 30`

Provider имеет собственный:

`timeout = 30`

и передаёт его в `urlopen()`.

Но Provider пока не получает timeout непосредственно
из Truth.

Следовательно, два значения совпадают случайно,
а не вследствие единого источника конфигурации.

Статус: OPEN.

### P-003 — provider audit не завершён

Необходимо проверить:

- providers/base.py
- providers/registry.py

После этого завершить карту provider-слоя.

Статус: OPEN.

---

## 6. Что пока НЕ следует делать

До завершения текущего READ-ONLY аудита:

- не объединять архитектуру наугад;
- не переносить компоненты между проектами;
- не менять execution model;
- не считать prompt ограничителем безопасности;
- не считать max_iterations реально enforced;
- не считать timeout из Truth реально enforced;
- не проводить массовый рефакторинг.

---

## 7. Текущая стадия

READ-ONLY STATIC AUDIT

Truth layer — частично реализован и проверен.

Execution-control — обнаружены архитектурные разрывы.

Provider-layer — аудит продолжается.

Архитектурная заморозка ещё НЕ выполнена.

---

## 8. Следующий шаг

Проверить:

1. providers/base.py
2. providers/registry.py

Затем обновить архитектурную карту.

После завершения полного READ-ONLY аудита:

→ сформировать целевую архитектуру;
→ оформить Architecture Decision Record;
→ заморозить архитектуру;
→ только затем переходить к реализации.

---

## 9. Правило достоверности

Статусы:

FACT — подтверждено кодом/тестом/источником.

DECISION — принято архитектурное решение.

HYPOTHESIS — рабочая гипотеза.

OPEN — вопрос требует проверки.

UNKNOWN — данных недостаточно.

Нельзя превращать HYPOTHESIS или OPEN в FACT без проверки.

---

## 10. Последняя контрольная точка

Последний подтверждённый результат:

get_principles() работает.
get_execution_limits() работает.
truth_status() работает.
build_prompt() работает.

Последнее обнаружение:

max_iterations и timeout_seconds пока не имеют
полного runtime enforcement.

Следующее действие:

READ-ONLY inspection providers/base.py и providers/registry.py.
