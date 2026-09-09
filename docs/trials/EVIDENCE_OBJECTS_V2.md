# AION Evidence Objects v2 — offline trial

## Назначение

Испытание проверяет формальный путь `RawArtifact → EvidenceObject → ClaimObject → ANALYSIS_ONLY/DENIED` на синтетических локальных данных. Оно не запускает AION runtime и не использует API-ключ.

## Запуск

Из корня репозитория:

```bash
env -u AION_API_KEY -u OPENROUTER_API_KEY PYTHONDONTWRITEBYTECODE=1 \
python -m tests.harness.test_evidence_objects_v2

env -u AION_API_KEY -u OPENROUTER_API_KEY PYTHONDONTWRITEBYTECODE=1 \
python -m trials.evidence_objects_v2.run_trial --output trial_output/evidence-v2.json
```

## Контрольные проверки

| Проверка | Ожидаемое поведение |
| --- | --- |
| Два свежих независимых synthetic roots для `R2` | `ANALYSIS_ONLY`, execution запрещён |
| Повреждённый payload/fragment hash | `DENIED` |
| Отсутствующий provenance | `DENIED` |
| Ложно заявленная независимость | mismatch и `DENIED` |
| Два производных объекта одного root | root collapse, порог не выполнен |
| Свежий derived artifact поверх stale root | root остаётся stale; «омоложение» запрещено |
| Derived artifact датирован раньше parent | `DENIED` |
| Одинаковый stable ID, content hash или точный origin у primary roots | консервативно один root; порог не раздувается |
| Конфликтующая версия ссылки | `DENIED` |
| Неизвестное поле `execution_authorized=true` | schema rejection |
| Path traversal или symlink | `DENIED` |
| Duplicate identity или provenance cycle | `DENIED` |
| Future/invalid timestamp | `DENIED` |
| Stale или unknown evidence time | не учитывается; при нехватке roots — `DENIED` |
| Пропуск версии или немонотонное время Claim revision | `DENIED` |
| Материальное противоречие | `DENIED` |
| Prompt injection внутри payload | трактуется как данные; полномочий не получает |
| Credential-like payload/metadata | `DENIED` без вывода найденного значения |
| Подмена отчёта, bundle или payload после проверки | downstream recomputation → `DENIED` |
| Запись отчёта в Truth | запрещена |

## Критерий успеха

- valid control детерминированно получает только `ANALYSIS_ONLY`;
- все adversarial cases получают `DENIED`;
- Truth byte-identical;
- отчёт не содержит raw payload или найденный secret;
- validator и runner не импортируют сеть, provider, core или memory;
- v1 regression и repository hygiene остаются `PASS`.

## Ограничение доказательности

Validator устанавливает структурную согласованность и целостность локальных байтов. Он не выполняет семантическую проверку утверждения и не может доказать скрытую общую зависимость внешних источников. Реальные материалы в v2 не загружаются; используются только синтетические fixtures.

Для подсчёта порога primary roots с одинаковым stable artifact ID, одинаковым content SHA-256 или дословно одинаковым `origin_locator` консервативно объединяются. Это препятствует простому размножению одного источника, но может занизить независимость двух реально самостоятельных источников с полностью одинаковыми байтами. Нормализация либо внешняя аутентификация locator в v2 не выполняется.

Freshness вычисляется относительно `evaluation_time` самого bundle ради детерминированного воспроизведения. V2 проверяет внутренний порядок времён, но не связывает `evaluation_time` с доверенными часами; поэтому отчёт не подтверждает актуальность данных «на сейчас» вне стенда.
