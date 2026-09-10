# PROJECT CHECKPOINT — Evidence Objects v2

Дата и время: `2026-09-10T10:12:55Z`  
Проект / ветка: `belnik1981-stack/AION` / `evidence-objects-v2-20260909`  
Проверенный кодовый снимок: `db978259be938da94a9db4d7bb217e182fb5fe77`  
Непосредственная основа: `information-cleaning-trial-v1-20260908@58708b5e460bd713008b973d648cef3471a5b735`  
Область: изолированный offline-контур `RawArtifact → EvidenceObject → ClaimObject → ANALYSIS_ONLY | DENIED`.

Этот checkpoint добавляется отдельным documentation-only потомком проверенного снимка; его собственный commit не изменяет исполняемый код.

## Подтверждено

- **VERIFIED** — локальные architecture, repository hygiene, v1 regression и v2 safety harness завершились `PASS`; v2 runner воспроизвёл 21/21 adversarial cases.
- **VERIFIED** — GitHub Actions на `db978259...`: `Offline evidence-objects v2 trial` run `34464790312` и `Offline information-cleaning trial` run `34464790212` завершились `success`.
- **FACT** — stacked diff относительно v1 ограничен 18 ожидаемыми файлами; случайные изменения executable modes восстановлены.
- **VERIFIED** — Truth остался byte-identical: `truth.json` SHA-256 `a542f48a63395e6c0e2c4784889de75296adf7057bd254734ccdc0f7f593ca32`; `system.yaml` SHA-256 `fe115f7bf7c6206bc3de7adc44aa259461bd9ecf5eb2b8a81ab67f2d4c44ef45`.
- **FACT** — provider/LLM, API-ключи, runtime AION, существующая memory и внешние действия испытанием не используются.

## Решения

- **DECISION** — максимальный допуск v2 только `ANALYSIS_ONLY`, `execution_authorized=false`; причина: integrity и внутренний provenance не доказывают истинность; альтернатива runtime promotion отклонена; последствие — безопасный ограниченный тест без автономности; статус `ACCEPTED FOR OFFLINE TRIAL ONLY`.
- **DECISION** — stable artifact ID, одинаковый content hash или точный `origin_locator` консервативно сворачиваются в один primary root; причина: запрет простого раздувания независимости; последствие — возможен безопасный false negative для реально независимых идентичных байтов.
- **DECISION** — v2 оформлен stacked draft PR на v1, не на `master`; merge требует отдельного разрешения владельца.

## Изменено

- `trials/evidence_objects_v2/` — строгие схемы, validator, deterministic runner и synthetic fixtures — проверено harness и CI.
- `tests/harness/test_evidence_objects_v2.py` — integrity, provenance, temporal/revision, leak, tamper и isolation tests — `PASS`.
- `.github/workflows/offline-evidence-objects-v2.yml` — независимый Python 3.11 прогон — `success`.
- `docs/architecture/ADR-0002-EVIDENCE_OBJECTS_V2.md`, `docs/trials/EVIDENCE_OBJECTS_V2.md`, `docs/PROJECT_STATE.md` — границы и ограничения синхронизированы с кодом.

## Открыто

- **OPEN** — semantic verification claim отсутствует; необходимо отдельное evidence или ручная/независимая проверка содержания.
- **OPEN** — внешняя подлинность provenance, автора и locator не подтверждается; необходимы подпись/доверенный capture либо внешний реестр.
- **OPEN** — скрытые common roots и неочевидные aliases locator не распознаются; необходима внешняя dependency discovery и нормализация.
- **OPEN** — `evaluation_time` задаётся fixture и не связан с доверенными часами; необходим отдельный trusted-time adapter до live-использования.
- **OPEN** — общий runtime deadline, суммарный лимит LLM/tool calls, response-size cap, cancellation и безопасный memory promotion не реализованы.

## Не считать завершённым

- готовность production/runtime AION;
- подключение v2 к server, provider, сети, candidate/long-term memory или Truth;
- доказательство повышения фактической точности на внешнем benchmark;
- разрешение merge в `master` или автономного исполнения.

## Последний успешный тест

- Локально: `python -m tests.harness.test_evidence_objects_v2` → `EVIDENCE OBJECTS V2 TRIAL: PASS`.
- CI: `https://github.com/belnik1981-stack/AION/actions/runs/34464790312` → `success`.
- V1 regression CI: `https://github.com/belnik1981-stack/AION/actions/runs/34464790212` → `success`.
- Draft PR: `https://github.com/belnik1981-stack/AION/pull/3`.

## Следующее действие

- Независимо повторить offline-v2 на Android/Termux с чистого checkout ветки. Критерий завершения: hygiene, v1 regression и v2 harness дают `PASS`, runner сообщает `passed=true` и 21 adversarial case, а `git status --short --branch` не показывает созданных тестом файлов.

## Источники состояния

- `docs/PROJECT_STATE.md` — состояние и открытые блокеры;
- `docs/architecture/ADR-0002-EVIDENCE_OBJECTS_V2.md` — архитектурная граница;
- `docs/trials/EVIDENCE_OBJECTS_V2.md` — инструкция и критерии;
- `trials/evidence_objects_v2/fixtures/valid_bundle.json` — positive control;
- `trials/evidence_objects_v2/fixtures/adversarial_cases.json` — 21 negative case;
- Git commits `58708b5e460bd713008b973d648cef3471a5b735`, `ac38a9dadb848c3bd0fed0d550fbc5439c65075a`, `db978259be938da94a9db4d7bb217e182fb5fe77`.
