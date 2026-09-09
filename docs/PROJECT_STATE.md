# PROJECT STATE

Дата контрольной точки: 2026-09-09  
Рабочая ветка: `evidence-objects-v2-20260909`  
Непосредственная основа: `information-cleaning-trial-v1-20260908@58708b5e460bd713008b973d648cef3471a5b735`  
Основа v1 после синхронизации: `master@d866435a42efc7f0c38e8f8bdbb3aa93908b641d`  
Начальная контрольная точка аудита: `master@540957cc3114f060dadeec90284b2366fb81183e`

## 1. Цель

AION рассматривается как технический инструмент для последовательной проверки элементов концепции здорового и постдефицитного общества:

`формализация → измерение → моделирование → реализация → проверка → масштабирование`.

Текущая работа ограничена воспроизводимыми offline-испытаниями очистки информации, формальных evidence objects и безопасного допуска только к аналитическому использованию.

## 2. Рабочий протокол

`READ-ONLY аудит → карта архитектуры → архитектурная заморозка → реализация → тестирование → интеграция`.

READ-ONLY аудит существующего кода для данного испытания завершён. Его результат: [`docs/audit/READ_ONLY_AUDIT_2026-09-08.md`](audit/READ_ONLY_AUDIT_2026-09-08.md).

Архитектура заморожена только для изолированного прототипа v1: [`ADR-0001`](architecture/ADR-0001-INFORMATION_CLEANING_TRIAL_V1.md). Это не заморозка всей будущей архитектуры AION.

Формальная граница Evidence Object / Claim Object v2 зафиксирована в [`ADR-0002`](architecture/ADR-0002-EVIDENCE_OBJECTS_V2.md). Она также не разрешает runtime-интеграцию.

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

Дополнительно в изолированном v2 реализованы:

- закрытые JSON Schema draft 2020-12 для RawArtifact, EvidenceObject, ClaimObject и bundle;
- проверка payload/fragment SHA-256, точных версий и byte-spans;
- provenance DAG, transformation refs, cycle detection и dependency-root collapse;
- консервативная свёртка очевидных primary-root aliases по stable ID, content hash и точному origin locator;
- freshness/risk gate по carrier и первичным dependency roots без «омоложения» через преобразование и без единого псевдоточного «процента истины»;
- запрет path traversal, symlink, неизвестных полей и credential-like данных;
- downstream recomputation при изменении отчёта, bundle или payload;
- adversarial trial с валидным control и fail-closed негативными случаями.

V2 не определяет истинность текста, не подтверждает внешнюю личность автора и не обнаруживает скрытую общую зависимость, если входной provenance намеренно её не указал.

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
| Синтетический Samsung Notes/PDF negative control | 10 релевантных записей → 2 root → только 1 verified; risk=`critical` | `DENIED` |
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
- **P-005 PARTIAL:** формальные Evidence Object/Claim Object, content hash, provenance graph и revision contract реализованы в offline v2; внешняя аутентичность provenance и semantic verification остаются OPEN.
- **P-006 OPEN:** экспериментальный promotion gate доверяет входному `decision=verified` и поэтому не допускается к long-term memory.
- **P-007 OPEN:** adaptive learning экспериментальной ветки принимает не связанную с проверенной записью оценку, что допускает poisoning.
- **P-008 OPEN:** OpenAI-compatible provider читает response body целиком; отдельного ограничения размера ответа до JSON-разбора нет.

Экспериментальная ветка `agents-sdk-adapter-20260908` остаётся исследовательским прототипом и не должна сливаться как готовая система.

## 7. Следующий разрешённый этап

После независимого повторения v2 offline-теста:

1. спроектировать append-only candidate store с атомарной записью и revision/correction;
2. разделить полномочия `write / verify / approve`;
3. добавить fault-injection tests для параллельной записи и восстановления;
4. отдельно реализовать общий deadline, суммарный лимит LLM/tool calls и response-size cap;
5. отдельно согласовать любые полномочия на подключение runtime, memory или исполнение действий.

Слияние в `master` и автономное выполнение не разрешены этой контрольной точкой.

## 8. Правило достоверности

- **FACT** — подтверждено кодом, тестом или первичным артефактом.
- **DECISION** — явно принятое ограниченное архитектурное решение.
- **HYPOTHESIS** — рабочая гипотеза.
- **OPEN** — вопрос требует реализации или проверки.
- **UNKNOWN** — данных недостаточно.

Нельзя превращать `HYPOTHESIS`, `OPEN` или AI-generated текст в `FACT` без отдельной проверки.
