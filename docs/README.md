# AION

Версия ядра: `0.1.0`  
Статус: исследовательский прототип; автономное и production-использование не разрешено.

## Назначение

AION — модульная AI-система, разрабатываемая с учётом работы через Android/Termux. Текущий инженерный приоритет — проверяемые ограничения, прослеживаемость данных и отделение Truth от изменяемой памяти и модельных ответов.

## Фактические контуры

- `core/` — runtime AION, multi-model orchestration и analysis-only bridges;
- `verification/` — детерминированная оценка evidence и транзакционный promotion;
- `learning/` — карантин и evidence-gated калибровка надёжности;
- `memory/` — ограниченное активное окно и crash-safe append-only архив принятых событий;
- `knowledge/truth/` — read-only governance-слой;
- `trials/information_cleaning_v1/` — детерминированная очистка синтетических records;
- `trials/evidence_objects_v2/` — offline RawArtifact/EvidenceObject/ClaimObject, integrity/provenance graph и fail-closed gate;
- `evidence/` — bounded network collector и преобразование его результата только в карантинный Evidence v2 draft;
- `tests/harness/` — локальные архитектурные и safety-проверки.

Evidence Objects v2 подключаются к runtime только через analysis-only bridge.
Он не разрешает execution, Truth update или автоматический memory promotion.
Claim registry принимает только целостный process-sealed контекст bridge, а не
произвольный список claims; seal не заменяет внешнюю проверку источника.
Детерминированные offline trials сами не вызывают provider или сеть.

## Проверка v2

Единая приёмка актуального `master` для владельца и QA:

```bash
bash scripts/owner_acceptance_test.sh
```

Она запускает полный offline-контур в изолированной локальной копии и не пишет
в основную runtime-память checkout. Подробный контракт — в
[`TEST_SPECIMEN.md`](TEST_SPECIMEN.md).

Низкоуровневые проверки отдельных trials:

```bash
python -m tests.harness.test_repository_hygiene
python -m tests.harness.test_information_cleaning_trial
python -m tests.harness.test_evidence_objects_v2
python -m trials.evidence_objects_v2.run_trial --output trial_output/evidence-v2.json
```

API-ключ для этих команд не требуется.

Сбор публичных документов в новый карантинный пакет выполняется отдельно:

```bash
python tools/prepare_evidence_candidate.py \
  --claim "Проверяемое утверждение" \
  --url "https://example.org/source" \
  --output ./private-evidence-candidate
```

Команда использует сеть, но не LLM/API-ключ. Ожидаемый admission token такого
пакета — `DENIED`: до независимой смысловой проверки он не входит в runtime.

## Документы состояния

- [Архитектура и QA испытательного образца](TEST_SPECIMEN.md)
- [Итоговый аудит испытательного образца](../reports/AION_TEST_SPECIMEN_AUDIT_2026-10-20.md)
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
- [ADR-0011: evidence-gated adaptive learning](architecture/ADR-0011-EVIDENCE-GATED-ADAPTIVE-LEARNING.md)
- [ADR-0012: карантинное преобразование evidence](architecture/ADR-0012-QUARANTINED-EVIDENCE-INGESTION.md)
- [ADR-0013: ограниченный эпизодический архив](architecture/ADR-0013-BOUNDED-EPISODIC-ARCHIVE.md)
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
- merge в `master` допускается только в рамках явно делегированных полномочий
  после обязательных успешных проверок и проверки точной головы PR.
