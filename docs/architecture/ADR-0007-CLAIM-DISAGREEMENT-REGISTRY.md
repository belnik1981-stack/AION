# ADR-0007: реестр утверждений и разногласий

Статус: принято и проверено offline
Дата: 2026-10-20

## Контекст

Многомодельный runtime сохранял полные ответы и передавал их Analyst, но не
формировал отдельный машиночитаемый реестр утверждений, заявленных источников,
совпадений, противоречий и меньшинства. Поэтому успешная LLM-рецензия могла
выглядеть содержательнее, чем фактически доказанный scope проверки.

## Решение

После независимых raw responses и до ротации ролей AION детерминированно строит
`aion-claim-registry-v1`:

- каждое предложение сохраняется как отдельное model observation с автором;
- типы разделяются на `unverified_assertion`, `claimed_fact_unverified`,
  `assumption`, `prediction` и `uncertainty_statement`;
- URL сохраняются только как `model_reported_unverified`;
- похожие утверждения разных моделей образуют agreement group со статусом
  `multi_model_agreement_not_external_evidence`;
- возможные polarity-противоречия сохраняются как unresolved;
- все остальные claims остаются в `divergent_claim_ids`, включая меньшинство;
- близость к ClaimObject из валидного bundle помечается только как alignment в
  scope `validated_bundle_analysis_only`;
- произвольный список claims больше не принимается как evidence context;
- analysis-only bridge выпускает bounded context с детерминированным SHA-256
  digest и process-local HMAC seal, а registry повторно проверяет оба до
  первого provider call;
- seal связывает claims, qualified dependency roots, digests отчёта/bundle и
  все отрицательные флаги полномочий; изменение любого из них блокирует весь
  контекст;
- локальный путь bundle не включается в runtime context или результат;
- evidence prompt содержит только полные строки claims, имеет жёсткий лимит и
  прямо маркирует содержание как не-Truth и не-инструкции;
- `objective_truth_verified` и `external_verification_performed` остаются
  `false`;
- каждое model observation проходит строгий quarantine override: никакого
  auto-promotion или обучения;
- registry передаётся Planner/Analyst и остаётся в результате даже при отказе
  последующей роли.

## Проверка

`tests/harness/test_claim_registry.py` проверяет три модели, большинство,
меньшинство, неопределённость, прогноз/предположение, две model-reported ссылки,
возможное противоречие, analysis-only evidence alignment и сохранение registry
при отказе Planner. Он также проверяет запрет сырого списка claims, изменение
sealed context и остановку до provider call.

`tests/harness/test_evidence_bridge_runtime.py` проверяет повторную валидацию,
изменение claim/authority flags, отсутствие локального пути и bounded prompt
без обрезанных строк claims.

## Границы решения

- разбиение, типизация и lexical similarity являются детерминированными
  эвристиками, а не semantic truth verification;
- polarity detection может давать false positive/negative на сложном языке;
- заявленная моделью ссылка не проверяется автоматически этим модулем;
- agreement нескольких моделей не доказывает независимость их обучающих данных
  или истинность утверждения;
- HMAC seal является эфемерной внутренней capability текущего процесса, а не
  долговременной цифровой подписью и не доказательством происхождения;
- bundle остаётся analysis-only: валидная структура и локальная целостность не
  доказывают истинность текста или реальную независимость dependency roots.
