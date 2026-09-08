# READ-ONLY аудит AION перед испытанием очистки информации

Дата: 2026-09-08  
Исходный `master` при начале аудита: `540957cc3114f060dadeec90284b2366fb81183e`  
Актуальный `master`, по которому выполнен дополнительный delta-аудит перед PR: `d866435a42efc7f0c38e8f8bdbb3aa93908b641d`  
Подготовительная ветка: `trial-readiness-2026-09-08`, tip `b509ef540318f87cf33a03c53091c2a66b3c4647`  
Экспериментальная ветка: `agents-sdk-adapter-20260908`, tip `b4f493a69c19295bae55b1554274fff8d0b973ee`  
Рабочая ветка испытания: `information-cleaning-trial-v1-20260908`

## Граница проверки

Проверены структура репозитория, точки входа, `core`, Truth, provider-слой, память, multi-agent pipeline, подготовительная ветка запуска, экспериментальные ingestion/evidence/verification/learning-модули и переданные EGDE-материалы. После независимого продвижения `master` на 12 коммитов дополнительно проверены изменённые `core/agents.py`, `core/llm.py`, `core/pipeline.py`, `providers/base.py`, `providers/openai_compatible.py` и `start_app.sh`. Реальный API и `run_cycle()` в этом аудите не запускались. `master` этой работой не изменялся.

## Целостность переданных источников

| Материал | SHA-256 | Результат |
| --- | --- | --- |
| `AION_EGDE_research_branch_2026-09-05.patch` | `281382e4033da0c668e25323e7ce347ebb06dfd81f2221fbb9c01c578e96c425` | Совпадает с копией внутри ZIP |
| `AUTHOR_POSITION_IP_POWER_ASYMMETRY.md` | `3b079456e0faea671c6d0685b3e01a85cea13129f3ae07ca05c23feb363856ad` | Совпадает с manifest ветки |
| `CONVERSATION_ORIGIN_2026-09-05.md` | `c5117aaf91ca8b6dce796e5e82d3ebc14bdf4760014a36f55fe6e89ad4426d0f` | Совпадает с manifest ветки |
| `INTEGRATION_NOTE_AION.md` | `4978de64973aa1fee15c3237f2f7ef0de8cb05431c0e61c2ea9db658e8c03d5e` | Совпадает с manifest ветки |
| `Evidence_Gated_Decision_Environment_v1.0_RU.docx` | `e5f9bbe0ca5352101fe596f28d022af2f859071b1804dc825b918837d7ad58c3` | Совпадает с публикационным пакетом |

У документа DOCX внутренние OOXML-даты указывают 2013 год, а текстовая версия — 2026-09-05. Это дефект метаданных шаблона: дату авторства нельзя доказывать полями `docProps/core.xml`; для контроля применяются содержимое, Git-история и SHA-256.

`Notes_260905_123559.pdf` не является публикационным PDF EGDE. В нём две страницы: первая содержит посторонний HTML/JavaScript-фрагмент, вторая — целевой контрольный сценарий. Это пригодный пример цифрового шума.

## Подтверждённая карта исполнения

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

Автоматическая запись в Truth кодом не обнаружена.

## Provider и execution-control

- `providers/base.py` задаёт контракт `ask(prompt, max_tokens=None)`/`health()`.
- `providers/registry.py` выбирает только `openai_compatible`.
- Ключ берётся из `AION_API_KEY`; значения ключа в исходном коде нет.
- Timeout provider не связан доказанным путём с `timeout_seconds` из Truth.
- `max_iterations` ограничивает цикл доработки, но не является общим бюджетом LLM-вызовов. При значении 3 pipeline способен выполнить до 9 вызовов: planner, analyst, critic и до трёх пар synthesizer/verifier.
- Актуальный `master:start_app.sh` больше не ищет ключ по домашнему каталогу: ключ требуется передать явно; для OpenRouter по умолчанию включён `AION_FREE_ONLY`.
- Введены раздельные per-role token budgets, отбрасывание ответов с признаком truncation и точный формат финального verifier (`OK` либо `FAIL: ...`). Это полезные ограничения, но не доказательная проверка фактов.
- Free-only policy проверяет имя модели до запроса и reported cost после ответа. Она не является предварительной криптографической гарантией нулевой стоимости: запрос к внешнему provider уже выполнен до проверки reported cost.
- HTTP-ответ читается целиком до JSON-разбора; отдельного лимита размера response body нет.

## Аудит экспериментальной ветки очистки

Полезные заготовки: изоляция candidate store от Truth, редактирование известных форматов секретов, точная дедупликация, evidence records, журналирование и offline-тесты.

Блокирующие дефекты:

1. **CRITICAL — недостоверный promotion gate.** `promote_verified_claim()` доверяет входному JSON с `decision=verified` и не пересчитывает контракт перед записью в long-term knowledge.
2. **CRITICAL — независимость не доказана.** Домен сайта автоматически считается `independent_group`, хотя разные домены могут зависеть от одного первичного, организационного или финансового корня.
3. **CRITICAL — learning poisoning.** Adaptive learning принимает числовой `evidence_score` без структурной связи с проверенной записью.
4. **HIGH — сетевой сборщик не годится для первого безопасного пилота.** Он читает ответ целиком до обрезки и не ограничивает redirects/локальные адреса.
5. **HIGH — provenance неполон.** Не обязательны content hash, способ проверки dependency root и воспроизводимость.
6. **HIGH — downstream use не имеет отдельного допуска.** Непроверенная запись технически не отделена от допустимой к использованию.
7. **MEDIUM — iterable evidence может быть исчерпан дважды.** `verify_candidate_record()` повторно обходит уже использованный iterable.
8. **MEDIUM — runtime-записи неатомарны и не защищены от параллельного изменения.**

Вывод: `agents-sdk-adapter-20260908` сохраняется как исследовательский прототип и не должна сливаться в `master` как готовая система.

## Артефакты, требующие уборки

- ошибочный пустой файл `max_iterations|timeout_seconds|execution_limits|MAX_ITERATIONS|TIMT_SECONDS|limits`, отмеченный в ранних материалах, уже отсутствует в проверенных текущих деревьях `master` и подготовительной ветки;
- устаревший `project_summary.txt` с runtime-снимком и пользовательским текстом;
- отслеживаемые `state.json`, episodic history и long-term runtime data.

В испытательной ветке существующие runtime-копии удаляются только из дерева ветки, остаются восстановимыми через Git-историю и впредь игнорируются как изменяемые пользовательские данные. Дополнительное удаление уже отсутствующего ошибочного файла не требуется.

## Разрешённая граница первого испытания

Только изолированный детерминированный offline-контур:

- без API-ключа, сети, LLM и Agents SDK;
- без `run_cycle()`, `run_pipeline()` и server;
- без записи в Truth или существующую память;
- с синтетическими fixtures;
- с карантином шума, редактированием секретов и дедупликацией;
- с явными dependency roots, сохранением противоречий и fail-closed;
- с downstream-допуском только `ANALYSIS_ONLY` либо `DENIED`.

Архитектура этого контура зафиксирована в ADR-0001 до его интеграции с ядром.
