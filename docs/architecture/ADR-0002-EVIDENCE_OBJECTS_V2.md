# ADR-0002: формальные Evidence Objects и Claim Objects v2

Дата: 2026-09-09  
Статус: **ACCEPTED FOR OFFLINE TRIAL ONLY**

## Решение

Следующий EGDE/AION-прототип реализуется отдельным пакетом `trials/evidence_objects_v2`. Он формализует три связанные сущности:

1. `RawArtifact` — ссылка на неизменённый локальный payload, его размер, SHA-256, версия, минимальные provenance-метаданные, privacy class и цепочка преобразований.
2. `EvidenceObject` — точный byte-span RawArtifact, hash извлечённого фрагмента, версия метода извлечения, отношение к claim и заявленные dependency roots.
3. `ClaimObject` — одно атомарное утверждение, область применимости, risk class, ссылки на evidence, freshness policy, revision и явные запреты использования.

JSON Schema draft 2020-12 задаёт закрытую структуру: неизвестные поля запрещены. Стандартнобиблиотечный validator дополнительно пересчитывает hashes, версии, byte-spans, timestamps, provenance graph, dependency roots и evidence gate.

## Граница исполнения

```text
synthetic local payload
  -> RawArtifact schema + SHA-256
  -> provenance DAG + canonical roots
  -> EvidenceObject span + fragment SHA-256
  -> ClaimObject references + freshness/risk gate
  -> ANALYSIS_ONLY | DENIED
  -> full recomputation before analytical use
```

- нет сети, LLM, provider, Agents SDK, server или shell execution;
- нет чтения/записи существующей memory;
- Truth доступен тесту только для сравнения SHA-256 до/после;
- отчёт нельзя записать внутрь `knowledge/truth`;
- `execution_authorized=false` при любом входе.

## Fail-closed условия

- неизвестное/пропущенное поле или неверный тип;
- повреждённый payload hash, размер, fragment hash или version reference;
- выход payload path за каталог bundle либо символическая ссылка;
- provenance timestamp из будущего или некорректная календарная дата;
- derived artifact приобретён раньше указанного parent либо пытается «омолодить» stale root;
- отсутствующая transformation для производного artifact;
- цикл или отсутствующая ссылка в provenance graph;
- несовпадение заявленных и вычисленных dependency roots;
- повтор stable artifact ID, content hash или точного origin locator не увеличивает число roots;
- дубликат идентичности объекта;
- известный формат credential/private key в payload или метаданных;
- stale/unknown evidence на carrier или dependency root, если после его исключения не выполнен risk threshold;
- Claim revision пропускает непосредственную предыдущую версию либо датирована не позже неё;
- существенное контрдоказательство;
- недостаточное число квалифицированных независимых корней;
- подмена bundle/report после проверки.

## Калибровка риска прототипа

| Risk class | Минимум contract-qualified roots | Максимальный результат |
| --- | ---: | --- |
| `R0` | 1 | `ANALYSIS_ONLY` |
| `R1` | 1 | `ANALYSIS_ONLY` |
| `R2` | 2 | `ANALYSIS_ONLY` |
| `R3` | 3 | `ANALYSIS_ONLY` |

Это параметры тестового стенда, а не вероятность истины. Контрдоказательство закрывает допуск независимо от числа supporting records.

## Что v2 действительно доказывает

- payload не изменился относительно записанного SHA-256;
- evidence fragment действительно является указанным byte-span payload;
- ссылки и версии внутри bundle согласованы;
- явно указанная derivation-цепочка сворачивается к общим первичным корням;
- очевидные алиасы primary roots по stable ID, hash или точному locator консервативно считаются одним корнем;
- неизвестные поля не могут незаметно добавить полномочия;
- gate пересчитывается перед downstream-использованием;
- синтетические негативные случаи воспроизводимо закрываются.

## Что v2 не доказывает

- истинность текста или семантическое соответствие evidence утверждению;
- реальную личность автора, дату публикации либо полноту provenance;
- соответствие заданного `evaluation_time` доверенным внешним часам;
- независимость двух первичных корней, если вход намеренно скрыл их общую зависимость;
- эквивалентность locator после URL-нормализации, редиректов или иных неявных алиасов;
- достоверность заявленных methodology/primary-data полей во внешнем мире;
- безопасность runtime AION, promotion в memory или автономных действий.

Хэш доказывает целостность доступных байтов, но не истинность события. Поля происхождения пока не подписаны внешним доверенным субъектом. Поэтому термины `qualified root` и `integrity checked` используются вместо общего статуса «проверенная истина».

## Следующий архитектурный порог

До candidate store необходим отдельный ADR для append-only записи, revision/correction, блокировки параллельных изменений и разделения `write / verify / approve`. До сетевого пилота отдельно требуются общий deadline, суммарный лимит LLM/tool calls, response-size cap, cancellation и fault-injection tests.
