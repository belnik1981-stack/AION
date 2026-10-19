# AION

Версия ядра: `0.1.0`  
Статус: исследовательский прототип; автономное и production-использование не разрешено.

## Назначение

AION — модульная AI-система, разрабатываемая с учётом работы через Android/Termux. Текущий инженерный приоритет — проверяемые ограничения, прослеживаемость данных и отделение Truth от изменяемой памяти и модельных ответов.

## Фактические контуры

- `core/` — существующий runtime AION и OpenAI-compatible provider;
- `knowledge/truth/` — read-only governance-слой;
- `trials/information_cleaning_v1/` — детерминированная очистка синтетических records;
- `trials/evidence_objects_v2/` — offline RawArtifact/EvidenceObject/ClaimObject, integrity/provenance graph и fail-closed gate;
- `tests/harness/` — локальные архитектурные и safety-проверки.

Offline trials не подключены к runtime, provider, сети, существующей memory или автономным действиям. Максимальный результат evidence-контуров — `ANALYSIS_ONLY` при `execution_authorized=false`.

## Проверка v2

```bash
python -m tests.harness.test_repository_hygiene
python -m tests.harness.test_information_cleaning_trial
python -m tests.harness.test_evidence_objects_v2
python -m trials.evidence_objects_v2.run_trial --output trial_output/evidence-v2.json
```

API-ключ для этих команд не требуется.

## Документы состояния

- [PROJECT_STATE](PROJECT_STATE.md)
- [ADR-0001: information cleaning v1](architecture/ADR-0001-INFORMATION_CLEANING_TRIAL_V1.md)
- [ADR-0002: Evidence Objects v2](architecture/ADR-0002-EVIDENCE_OBJECTS_V2.md)
- [ADR-0003: общий runtime-бюджет](architecture/ADR-0003-GLOBAL_RUNTIME_BUDGET.md)
- [ADR-0004: crash-safe JSON-хранилища](architecture/ADR-0004-CRASH-SAFE-JSON-STORAGE.md)
- [ADR-0005: границы чувствительных данных](architecture/ADR-0005-SENSITIVE-DATA-BOUNDARIES.md)
- [ADR-0006: транзакционный promotion](architecture/ADR-0006-TRANSACTIONAL-PROMOTION.md)
- [ADR-0007: реестр утверждений и разногласий](architecture/ADR-0007-CLAIM-DISAGREEMENT-REGISTRY.md)
- [ADR-0008: параллельная коммерческая оценка](architecture/ADR-0008-COMMERCIAL-PARALLEL-BRIDGE.md)
- [ADR-0009: сетевая граница evidence collector](architecture/ADR-0009-EVIDENCE-NETWORK-BOUNDARY.md)
- [ADR-0010: ограниченный Agents SDK runtime](architecture/ADR-0010-BOUNDED-AGENTS-SDK-RUNTIME.md)
- [Инструкция v2](trials/EVIDENCE_OBJECTS_V2.md)
- [Source manifest](egde/SOURCE_MANIFEST_2026-09-08.md)

## Открытые ограничения

- внешняя подлинность provenance и скрытые зависимости источников не доказаны;
- semantic verification claim не реализована;
- long-term promotion разрешён только после fresh verification, явного reviewer
  и восстанавливаемой audit-транзакции; внешняя подлинность evidence этим не доказывается;
- принудительная отмена уже начатого системного сетевого вызова остаётся best-effort;
- основной pipeline и optional Agents SDK имеют отдельные bounded budgets и
  пока не делят один общий счётчик между одновременными запусками;
- актуальное реальное API-испытание требует ключ владельца и доступных бесплатных моделей;
- merge в `master` требует отдельного решения владельца.
