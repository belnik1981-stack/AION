# PROJECT CHECKPOINT

Дата: 2026-10-15
Проект / ветка: AION / `integration-life-trial-v1-20261015`
База: `multi-model-role-rotation-v1-20260911@bae39bca8673ec0a9e8d295eeee7b450d0da9f25`
Область: совместимая интеграция проверенной цепочки и полный сценарий испытания.

## Подтверждено

- VERIFIED — `information-cleaning-trial-v1-20260908` является предком Evidence Objects v2.
- VERIFIED — `evidence-objects-v2-20260909` является предком multi-model role rotation.
- VERIFIED — обе унаследованные офлайн-проверки успешно выполнялись на head исходной ветки.
- FACT — `trial-readiness` и `agents-sdk-adapter` расходятся с текущей основой и конфликтуют в runtime-файлах.

## Решения

- DECISION — не переносить старые конфликтующие runtime-файлы автоматически.
- DECISION — использовать мультимодельную ветку как минимальную совместимую основу.
- DECISION — добавить единый bounded life-trial, CI и облачный runbook.
- DECISION — не изменять `master` без отдельного разрешения владельца.

## Изменено

- `scripts/full_life_test.sh` — офлайн и опциональная реальная проверка, контроль неизменности Truth.
- `.github/workflows/integration-life-trial.yml` — запуск офлайн-проверки на Python 3.10 и 3.12.
- `docs/CLOUD_FULL_LIFE_TRIAL_RUNBOOK_2026-10-15.md` — инструкция владельцу проекта.

## Открыто

- OPEN — реальная проверка с двумя разными моделями; требуется ключ владельца и доступные model IDs.
- OPEN — общий лимит всех LLM-вызовов ещё не enforced единым runtime-бюджетом.
- OPEN — provider timeout не связан доказанно с общим Truth deadline.
- OPEN — старые Agents SDK/learning/commercial modules требуют отдельного переноса и регрессии, если они ещё нужны.

## Не считать завершённым

- Полную эксплуатационную готовность и качество ответов на реальных задачах.
- Совместимость старых расходящихся runtime-веток.
- Слияние в `master`.

## Последний успешный тест

- Исходная база: GitHub Actions `Offline information-cleaning trial` и `Offline evidence-objects v2 trial` — success.

## Следующее действие

- Дождаться CI интеграционной ветки; затем владелец выполняет облачный live trial по runbook.

## Источники состояния

- GitHub branch comparisons, проверенные 2026-10-15.
- `docs/PROJECT_STATE.md` в исходной мультимодельной ветке.
- GitHub Actions исходных веток.
