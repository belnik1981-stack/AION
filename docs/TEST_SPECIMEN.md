# AION: архитектура и QA испытательного образца

Дата фиксации: 2026-10-20
Целевая ветка: `master`

## 1. Граница образца

Испытательный образец доказывает один основной сценарий: безопасно получить
законченные исходные ответы минимум двух явно различающихся моделей, сохранить
их раздельно, сопоставить утверждения и разногласия, выполнить ограниченную
ротацию ролей, сформировать итог с видимой неопределённостью и записать только
принятый результат в crash-safe episodic memory.

Он не обещает объективную истинность ответа, реальную независимость обучающих
данных моделей, внешнюю подлинность каждого источника или production SLA.

## 2. Карта архитектуры

| Контур | Ответственность | Основные зависимости | Побочный эффект / граница |
|---|---|---|---|
| `core/pipeline.py` | Оркестрация single/multi-model, роли, остановка, итог | `core/agents`, registry, bridge, budget | Пишет episodic memory только после принятия |
| `core/runtime_budget.py` | Общий deadline и число LLM-вызовов одного pipeline | монотонные часы, Truth limits | Fail-closed при исчерпании |
| `providers/` | OpenAI-compatible HTTP, free-only, timeout, размер ответа | OpenRouter/API env | Сеть; текст внешних исключений не выдаётся |
| `core/claim_registry.py` | Атомарные claims, совпадения, расхождения, источники | process-sealed evidence context | Agreement явно помечается как not proof |
| `trials/evidence_objects_v2/` | RawArtifact/Evidence/Claim, provenance DAG, gate | JSON fixtures/schemas | Offline; не подтверждает внешнюю подлинность |
| `evidence/` | Bounded fetch и карантинный draft | HTTPS/DNS guard, Evidence v2 | Автосбор получает `DENIED`, не Truth |
| `verification/` | Проверка evidence и транзакционный promotion | long-term memory, audit | Требует reviewer; promotion не меняет Truth |
| `learning/` | Evidence-gated калибровка надёжности | verification records | Не является самообучением истине |
| `commercial_dependency/` | Параллельная гипотеза о влиянии стимулов | claim registry | Не изменяет доверенный итог |
| `memory/` | Активное окно и архив принятых событий | `storage/atomic_json.py` | Локальные приватные данные, `0600`, не Git |
| `knowledge/truth/` | Неизменяемые принципы и пределы | `core/truth.py` | Только чтение во время runtime/tests |
| `server.py` | Локальная web‑панель | engine, pipeline, storage | Только `127.0.0.1`; нет внешней auth; HTTP smoke offline |
| `scripts/owner_acceptance_test.sh` | Приёмка точного commit в изоляции | Git, Bash, Python 3.10+ | Отчёт; основную память не открывает для записи |

Главные входы:

- QA/владелец: `bash scripts/owner_acceptance_test.sh`;
- CLI pipeline: `python pipeline_cli.py "задача"`;
- локальная web‑панель: `bash start_app.sh`;
- evidence quarantine: `python tools/prepare_evidence_candidate.py ...`.

## 3. Основной поток

1. Пользовательский ввод проходит ограничения размера и redaction.
2. Опциональный Evidence v2 bundle валидируется и допускается только как
   analysis-only context.
3. Не менее двух моделей получают исходную задачу раздельно.
4. Ошибки, пустые и усечённые ответы сохраняют отдельный диагностический статус;
   одномодельный остаток не считается успешной многомодельной проверкой.
5. Claim registry отделяет claims, model-reported sources, совпадения,
   противоречия и minority/divergent позиции.
6. Коммерческий view вычисляется параллельно и не подменяет основной registry.
7. Роли ротируются в пределах Truth/runtime budget; cycle guard останавливает
   повтор или колебание.
8. Verifier выполняет LLM-review. Поля остаются
   `verification_scope=llm_review_only` и `truth_verified=False`.
9. Только принятый итог записывается в активную episodic memory; вытесненная
   история сначала попадает в проверяемый архив.

Пути отказа, обязательные для образца:

- одна модель недоступна — multi-model PASS запрещён;
- HTTP 429 — дальнейшие модельные вызовы прекращаются;
- усечённый ответ — максимум один bounded retry, затем отказ;
- повреждённая память / audit / archive — запись останавливается без очистки;
- существенное противоречие или недостаток evidence — `DENIED` либо видимая
  неопределённость, а не повышение до факта;
- исчерпан deadline/call budget или обнаружен цикл — безопасная остановка.

## 4. Архитектурные конфликты и приоритеты

| Приоритет | Состояние | Основание | Действие |
|---|---|---|---|
| Блокирующий для offline‑образца | Закрыт | Основной pipeline, storage, Truth и испытания проходят общий life trial | Сохранять CI gate |
| Блокирующий для актуального live‑приёма | Открыт до запуска владельцем | В среде разработки нет ключа; бесплатные модели меняются | `owner_acceptance_test.sh --live` |
| Главный | Открыт | Внешняя подлинность provenance и semantic truth не доказаны | Не повышать LLM review до objective verification |
| Главный | Ограничен | Сервер без auth | Оставлять loopback-only; не публиковать порт |
| Главный | Открыт | Runtime/archive не зашифрованы at rest | Защищать устройство/FS; проектировать отдельную миграцию |
| Главный | Открыт | DNS guard не исключает все варианты rebinding | Не считать collector универсальным безопасным crawler |
| Незначительный | Контролируется | Pattern-redaction не знает неизвестные форматы секретов | Leak guard + запрет секретов во входах/логах |

Блокирующие циклические импорты не проявились при полном импорте, компиляции и
life trial. Это не доказательство их невозможности во всех будущих расширениях.

## 5. Уровни проверки

| Уровень | Текущее подтверждение |
|---|---|
| 1. Статика | `compileall`, shell syntax, repository hygiene |
| 2. Модульные | Budget, cycle guard, redaction, storage, quarantine, registry |
| 3. Интеграционные | Pipeline, evidence/commercial bridges, memory gate, loopback HTTP |
| 4. Offline | `full_life_test.sh`, cleaning v1, Evidence Objects v2 |
| 5. Реальный API | Только отдельный `--live`; текущий результат нельзя имитировать |
| 6. Устойчивость | 400/404/429/5xx, timeout, truncation, corruption, concurrency |
| 7. Достоверность | False independence, stale/missing provenance, contradiction controls |
| 8. Termux/cloud | Launcher совместим; фактический запуск владельца обязателен |

## 6. Приёмка QA

На чистом актуальном `master`:

```bash
bash scripts/owner_acceptance_test.sh
```

Обязательные признаки:

- все строки `[STAGE ...]` завершаются PASS либо явно допустимым SKIP live;
- есть `[PASS] OFFLINE LIFE TRIAL`;
- есть `[PASS] Primary runtime and memory unchanged`;
- есть `[PASS] Truth unchanged`;
- финал `[ACCEPTANCE PASS]` содержит точный commit;
- рядом созданы закрытые `.log` и `.json` отчёты.

Для реального подтверждения многомодельного контура владелец повторяет:

```bash
read -r -s -p "OpenRouter API key: " AION_API_KEY; echo
export AION_API_KEY
bash scripts/owner_acceptance_test.sh --live
unset AION_API_KEY
```

Успех live‑этапа требует двух законченных исходных ответов разных eligible
free‑моделей, одной принятой ротации ролей, `truth_verified=False` и неизменной
Truth. Любой 429, отказ каталога, незавершённый ответ или неполный role contract
означает FAIL/SKIP внешней готовности, а не дефект, который можно скрыть.

## 7. Решение о готовности

До личного запуска владельца допустимый статус:

**READY — воспроизводимый offline test specimen; LIVE ACCEPTANCE PENDING.**

Недопустимые формулировки: «абсолютно достоверен», «полностью автономен»,
«production-ready», «модели независимо доказали истину».
