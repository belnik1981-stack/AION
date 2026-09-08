# PROJECT STATE

Дата контрольной точки: 2026-09-08  
Рабочая ветка: `information-cleaning-trial-v1-20260908`  
Исходная основа: `trial-readiness-2026-09-08@b509ef540318f87cf33a03c53091c2a66b3c4647`  
Актуальная основа после синхронизации перед PR: `master@d866435a42efc7f0c38e8f8bdbb3aa93908b641d`  
Начальная контрольная точка аудита: `master@540957cc3114f060dadeec90284b2366fb81183e`

## 1. Цель

AION рассматривается как технический инструмент для последовательной проверки элементов концепции здорового и постдефицитного общества:

`формализация → измерение → моделирование → реализация → проверка → масштабирование`.

Текущая работа ограничена подготовкой воспроизводимого испытания очистки информации и её безопасного допуска к дальнейшему аналитическому использованию.

## 2. Рабочий протокол

`READ-ONLY аудит → карта архитектуры → архитектурная заморозка → реализация → тестирование → интеграция`.

READ-ONLY аудит существующего кода для данного испытания завершён. Его результат: [`docs/audit/READ_ONLY_AUDIT_2026-09-08.md`](audit/READ_ONLY_AUDIT_2026-09-08.md).

Архитектура заморожена только для изолированного прототипа v1: [`ADR-0001`](architecture/ADR-0001-INFORMATION_CLEANING_TRIAL_V1.md). Это не заморозка всей будущей архитектуры AION.

## 3. Подтверждённая карта исполнения

```text
main.py / server.py / pipeline_cli.py
  -> core.engine или core.pipeline
  -> core.llm
  -> providers.registry
  -> providers.openai_compatible
  -> внешний OpenAI-compatible API

core.pipeline -> core.agents -> memory.store
core.truth -> knowledge/truth/{truth.json,system.yaml}
```

FACT: автоматическая запись в Truth существующим кодом не обнаружена.

FACT: API-ключ берётся из `AION_API_KEY`; в исходном коде значение ключа не хранится.

## 4. Что реализовано в рабочей ветке

- детерминированный offline-контур `trials/information_cleaning_v1`;
- строгая схема контролируемых fixtures и безопасные пределы размера;
- нормализация Unicode/пробелов;
- редактирование известных форматов секретов и email;
- карантин явно размеченного цифрового шума без бесследного удаления;
- точная дедупликация с fail-closed при конфликте метаданных дубликатов;
- свёртка evidence records по заявленному dependency root;
- сохранение существенных противоречий;
- токены только `ANALYSIS_ONLY` или `DENIED`; `execution_authorized=false` всегда;
- повторная проверка evidence contract перед downstream-использованием;
- запрет записи отчёта в `knowledge/truth`;
- offline safety harness и отдельный GitHub Actions workflow;
- leak-guard, который не печатает найденные значения и блокирует типовые credentials, приватные ключи, открытые provenance-транскрипты, бинарные транспортные архивы и отслеживаемые runtime-данные;
- отделение изменяемых runtime-данных от исходного кода через `.gitignore`.

Сетевые вызовы, LLM, Agents SDK, server, `run_cycle()` и существующая память к v1 не подключены.

Полный origin dialogue, авторская позиция, DOCX/PDF/ZIP/PATCH не включаются в Git-ветку. В `docs/egde/SOURCE_MANIFEST_2026-09-08.md` остаются только SHA-256. Это уменьшает объём раскрываемых авторских и персональных материалов даже внутри приватного репозитория.

## 5. Локальный результат испытания

Команда:

```bash
python -m tests.harness.test_information_cleaning_trial
```

Результат: `INFORMATION CLEANING TRIAL: PASS`.

Контрольные сценарии:

| Сценарий | Проверяемое условие | Результат |
| --- | --- | --- |
| Samsung Notes negative control | 10 релевантных записей → 2 root → только 1 verified; risk=`critical` | `DENIED` |
| Positive analytical control | 2 verified root, дубликат удалён, secret/email редактированы | `ANALYSIS_ONLY` |
| Contradiction control | порог поддержки выполнен, но есть проверенное контрдоказательство | `DENIED` |

Truth до и после теста остался byte-identical:

- `knowledge/truth/truth.json`: SHA-256 `a542f48a63395e6c0e2c4784889de75296adf7057bd254734ccdc0f7f593ca32`;
- `knowledge/truth/system.yaml`: SHA-256 `fe115f7bf7c6206bc3de7adc44aa259461bd9ecf5eb2b8a81ab67f2d4c44ef45`.

## 6. Открытые блокеры runtime-интеграции

- **P-001 PARTIAL/OPEN:** `max_iterations` теперь ограничивает цикл доработки, но не является единым лимитом общего числа LLM-вызовов; при значении 3 pipeline способен сделать до 9 вызовов.
- **P-002 OPEN:** provider timeout не связан доказанным путём с `timeout_seconds` из Truth.
- **P-003 CLOSED FOR AUDIT:** `providers/base.py` и `providers/registry.py` проверены; реестр поддерживает только `openai_compatible`.
- **P-004 OPEN:** нет доверенного механизма проверки реальной независимости внешних dependency roots.
- **P-005 OPEN:** нет формальных Evidence Object/Claim Object с обязательными provenance, content hash, verification method и revision history.
- **P-006 OPEN:** экспериментальный promotion gate доверяет входному `decision=verified` и поэтому не допускается к long-term memory.
- **P-007 OPEN:** adaptive learning экспериментальной ветки принимает не связанную с проверенной записью оценку, что допускает poisoning.
- **P-008 OPEN:** OpenAI-compatible provider читает response body целиком; отдельного ограничения размера ответа до JSON-разбора нет.

Экспериментальная ветка `agents-sdk-adapter-20260908` остаётся исследовательским прототипом и не должна сливаться как готовая система.

## 7. Следующий разрешённый этап

После независимого повторения offline-теста:

1. определить схемы Evidence Object и Claim Object;
2. реализовать проверяемый provenance/dependency contract для публичного тестового набора;
3. провести adversarial-тесты ложных, устаревших, зависимых и противоречивых источников;
4. оформить отдельный ADR до подключения candidate store;
5. отдельно согласовать любые полномочия на запись в memory или исполнение действий.

Слияние в `master` и автономное выполнение не разрешены этой контрольной точкой.

## 8. Правило достоверности

- **FACT** — подтверждено кодом, тестом или первичным артефактом.
- **DECISION** — явно принятое ограниченное архитектурное решение.
- **HYPOTHESIS** — рабочая гипотеза.
- **OPEN** — вопрос требует реализации или проверки.
- **UNKNOWN** — данных недостаточно.

Нельзя превращать `HYPOTHESIS`, `OPEN` или AI-generated текст в `FACT` без отдельной проверки.
