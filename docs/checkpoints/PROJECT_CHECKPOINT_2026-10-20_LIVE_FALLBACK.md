# AION checkpoint: bounded live-model fallback — 2026-10-20

## Контрольная точка

- Базовый commit: `8e19bf358328310cdd8bb39ed197b296b4d46428`.
- Рабочая ветка: `codex/live-provider-fallback-20261020`.
- Изменён только чистый worktree; незавершённое локальное изменение
  `core/commercial_bridge.py` в исходном каталоге не включено.

## Подтверждено

- `nvidia/nemotron-3.5-super-vl:free` ранее дал завершённый одиночный ответ.
- `xingchen-agi/xing4.0-29b-a4b:free` в последнем испытании вернул HTTP 429.
- `dots-studio/dots-3-note-preview:free` ранее дал provider error.
- Offline life trial и Truth-integrity проверки проходят на базовом снимке.

## Изменения в этой ветке

1. HTTP 429 получает безопасную классификацию: `platform`,
   `upstream_provider` или `unknown`; сохраняется только числовой `Retry-After`.
2. Платформенный/неизвестный 429 останавливает preflight. Подтверждённый
   upstream-429 в автоматическом выборе пропускает только отказавший model ID;
   тот же ID не повторяется. Явная пара остаётся точным контрактом.
3. Автоматический выбор допускает до восьми текущих каталоговых кандидатов и
   пропускает безопасные кандидатные provider errors/HTTP 400, 404, 500, 502,
   503, 504 в пределах этого лимита.
4. Бюджет Planner по умолчанию повышен с 512 до 1600 токенов; остаётся один
   ограниченный retry до общего потолка роли.
5. HTTP 401/403 теперь типизированы как `ProviderHTTPError`, поэтому ошибка
   доступа не маскируется под доступность следующей модели.

## Проверки

- `test_provider_resilience.py` — PASS.
- `test_live_free_multi_model_trial.py` — PASS.
- `test_runtime_budget.py` — PASS.
- Полный `scripts/full_life_test.sh` в offline-режиме — PASS; все перечисленные
  архитектурные, memory, evidence, safety и smoke-тесты прошли; live provider
  не запускался из-за отсутствия ключа в этой среде.

## Следующее действие

После публикации этой ветки запускать live-тест без `AION_MODELS`, чтобы
автоматический каталог мог выбрать альтернативу. Если журнал покажет
`[RATE LIMIT SCOPE] platform` или `unknown`, дальнейшие повторы до указанного
`[RETRY AFTER]`/сброса квоты запрещены. Если покажет
`upstream_provider`, допускается один ограниченный автоматический переход к
другому текущему `:free` ID.

Live PASS всё ещё означает только `verification_scope=llm_review_only`;
`truth_verified=False` сохраняется.
