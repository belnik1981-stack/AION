# AION — итоговый аудит испытательного образца

Дата: 2026-10-20
Проверенный implementation baseline после финального HTTP smoke:
`master@558befa9b171bfcb5a705a24c3210781da425004` (PR #39).

## Вердикт

Статус автоматизированной части:

**READY — воспроизводимый offline test specimen.**

Статус внешней приёмки:

**PENDING — актуальный live API и фактический Termux/cloud запуск владельца.**

## Подтверждено

- два и более явных model ID не сворачиваются в одномодельный PASS;
- исходные ответы, ошибки моделей, claim registry, разногласия и role assignment
  остаются раздельно наблюдаемыми;
- verifier остаётся `llm_review_only`, а `truth_verified=False`;
- общий deadline, call budget, output cap, bounded retry и cycle guard работают
  fail-closed;
- evidence collector, карантинный draft, Evidence Objects v2 и analysis-only
  bridge не дают автоматического execution/Truth/memory promotion;
- long-term promotion и adaptive learning требуют заново валидируемого evidence;
- коммерческая зависимость анализируется отдельным view и не меняет итог;
- JSON state, audit и episodic archive имеют проверяемые crash-recovery пути;
- отклонённый ответ не записывается как принятый, а активная память ограничена
  без автоматического удаления старой истории;
- секреты проходят общий redaction, provider exception text не публикуется;
- owner launcher тестирует точный commit в отдельном clone и доказывает
  неизменность основной runtime memory и Truth;
- статический AST-анализ 47 runtime-модулей и 89 внутренних import edges не
  обнаружил цикла на этом snapshot;
- настоящий offline HTTP smoke использует ephemeral loopback port и не вызывает
  внешнюю модель.

## Фактические уровни испытаний

| Уровень | Результат |
|---|---|
| Статика / hygiene | PASS |
| Модульные и контрактные harness | PASS |
| Интеграционный pipeline | PASS на mock/fault injection |
| Offline cleaning/evidence trials | PASS |
| Storage corruption/concurrency | PASS |
| Provider 400/404/429/5xx/truncation simulations | PASS |
| Loopback HTTP | PASS локально и в CI на Python 3.10/3.12 |
| Public OpenRouter catalog без генерации | PASS на PR #37 |
| Актуальный генеративный live API | NOT RUN — ключ отсутствует |
| Фактический Android/Termux | NOT RUN — требуется устройство владельца |

Запуски PR #39: GitHub Actions `39388457179`, `39388457191`, `39388457209`,
`39388457230`, `39388457246`; все завершены `success`. В offline matrix прошли
Python 3.10/3.12 и отдельный optional Agents SDK contract. Post-merge команда
`bash scripts/owner_acceptance_test.sh` завершилась `[ACCEPTANCE PASS]` на
`master@558befa9...`, `live=SKIP`; основная runtime-память и Truth не изменились.

## Нерешённые границы

- разные model ID/авторы не доказывают независимые обучающие данные;
- модельная рецензия не доказывает фактическую истинность;
- внешняя подлинность provenance и semantic verification не универсальны;
- DNS guard не устраняет абсолютно все варианты rebinding;
- локальная память не зашифрована at rest;
- web‑сервер не имеет пользовательской auth и поэтому остаётся loopback-only;
- уже начатый системный сетевой вызов отменяется best-effort;
- основной pipeline и optional Agents SDK не делят один глобальный счётчик
  между параллельными процессами;
- бесплатность и доступность OpenRouter моделей меняются вне AION.

Эти ограничения не являются скрытыми PASS: они должны оставаться в отчёте и
интерфейсе до отдельного доказательного исправления.

## Команда владельца

Офлайн‑приёмка актуального `master`:

```bash
bash scripts/owner_acceptance_test.sh
```

После неё отдельный bounded live‑этап:

```bash
read -r -s -p "OpenRouter API key: " AION_API_KEY; echo
export AION_API_KEY
bash scripts/owner_acceptance_test.sh --live
unset AION_API_KEY
```

Окончательная пользовательская приёмка не объявляется до второго запуска и
фактического повторения на целевом Android/Termux либо cloud host.
