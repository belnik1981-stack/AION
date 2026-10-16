# PROJECT CHECKPOINT

Дата и время: 2026-09-08 UTC  
Проект / ветка: `belnik1981-stack/AION` / `information-cleaning-trial-v1-20260908`  
Проверенный кодовый commit: `a06f983196f2a52be0ce3af775eab6f9ad32d416`  
Область: безопасный offline-прототип очистки информации v1, аудит и подготовка draft PR.

## Подтверждено

- **VERIFIED** — репозиторий имеет `visibility=private` — GitHub repository metadata, проверено 2026-09-08.
- **VERIFIED** — защищённый кодовый commit основан непосредственно на `master@d866435a42efc7f0c38e8f8bdbb3aa93908b641d`.
- **VERIFIED** — `REPOSITORY HYGIENE TEST: PASS` и `INFORMATION CLEANING TRIAL: PASS` — локальный Python 3.12.14, без сети/API/LLM.
- **VERIFIED** — полный origin dialogue, авторская позиция и бинарные/транспортные материалы отсутствуют в дереве защищённого commit; сохранены только SHA-256.
- **VERIFIED** — Truth не изменяется испытанием; SHA-256 до и после совпадает.

## Решения

- **DECISION** — не хранить чувствительные provenance-источники открытым текстом в Git — минимизация раскрытия важнее удобства просмотра; альтернатива с plaintext в приватной ветке отклонена; для сопоставления оставлены хэши.
- **DECISION** — v1 остаётся отдельным offline-контуром — текущие runtime limits не доказаны полностью; следствие: только `ANALYSIS_ONLY` либо `DENIED`, внешних действий нет.
- **DECISION** — draft PR не разрешает merge — слияние требует отдельного решения владельца.

## Изменено

- `trials/information_cleaning_v1/` — детерминированная очистка, quarantine, redaction, deduplication, dependency collapse, contradiction gate и downstream revalidation.
- `tests/harness/` — негативные, положительные, contradiction, token-forgery, Truth-integrity и leak-guard проверки.
- `tools/check_repository_hygiene.py` — проверка типовых credentials и запрещённых материалов без вывода найденного значения.
- `.gitignore` и удаление отслеживаемых runtime-снимков — изменяемые пользовательские данные отделены от исходного кода; история остаётся восстановимой в Git.
- `docs/` — аудит, ADR, инструкция испытания, source manifest и план v2.

## Открыто

- **OPEN** — GitHub Actions CI для draft PR — требуется успешный run на текущем tip ветки.
- **OPEN** — общий deadline и суммарный лимит LLM/tool calls — не закрыты, потому сетевой runtime не входит в v1.
- **OPEN** — реальная проверка provenance и независимости dependency roots — v1 использует контролируемые fixture-поля.
- **OPEN** — защищённое хранение самих приватных первичных материалов — Git-хэши подтверждают соответствие, но не заменяют отдельное зашифрованное хранилище с внешним ключом.

## Не считать завершённым

- AION не готов к автономным внешним действиям.
- EGDE не интегрирован в runtime, memory или Truth.
- Успех синтетических fixtures не доказывает качество на реальных источниках.
- Free-only model policy не является предварительной гарантией нулевой стоимости provider-запроса.

## Последний успешный тест

```bash
python -m tests.harness.test_repository_hygiene
python -m tests.harness.test_information_cleaning_trial
python -m trials.information_cleaning_v1.run_trial --output trial_output/result.json
```

Результат: оба harness — `PASS`; три сценария дали ожидаемые `DENIED / ANALYSIS_ONLY / DENIED`.

## Следующее действие

Реализовать JSON Schema и validator для `RawArtifact`, `EvidenceObject` и `ClaimObject` по `docs/roadmap/NEXT_STEP_EVIDENCE_OBJECT_V2.md`. Критерий завершения: все негативные provenance/integrity fixtures fail-closed, Truth byte-identical, execution token отсутствует.

## Источники состояния

- `master@d866435a42efc7f0c38e8f8bdbb3aa93908b641d` — актуальная база при подготовке защищённого commit.
- `a06f983196f2a52be0ce3af775eab6f9ad32d416` — проверенный кодовый commit.
- `docs/audit/READ_ONLY_AUDIT_2026-09-08.md` — текущий аудит и delta-аудит master.
- `docs/architecture/ADR-0001-INFORMATION_CLEANING_TRIAL_V1.md` — архитектурная граница v1.
- `docs/egde/SOURCE_MANIFEST_2026-09-08.md` — хэши приватных исходных материалов.
- `docs/roadmap/NEXT_STEP_EVIDENCE_OBJECT_V2.md` — утверждённый следующий инженерный шаг.
