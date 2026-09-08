# AION Information Cleaning Trial v1

## Что проверяется

Первый тест проверяет не «истинность вообще», а работоспособность ограниченного механизма:

- отделить посторонний цифровой шум от релевантных evidence records;
- нормализовать текст и удалить известные секреты/адреса электронной почты;
- свернуть точные дубли;
- не принять множество производных записей за множество независимых корней;
- сохранить контрдоказательства;
- закрыть допуск при одинаковом тексте с конфликтующими метаданными;
- закрыть downstream-доступ при невыполнении evidence contract;
- не изменять `knowledge/truth`.

## Запуск в Termux

Выполнять из каталога `~/AION`:

```bash
git fetch origin
git switch information-cleaning-trial-v1-20260908
python -m tests.harness.test_information_cleaning_trial
python -m tests.harness.test_repository_hygiene
python -m trials.information_cleaning_v1.run_trial --output trial_output/result.json
```

API-ключ не требуется. Сеть, server, `run_cycle()` и LLM не запускаются.

## Критерии завершения

- Negative control: `10 sources -> 2 roots -> 1 verified root -> DENIED`.
- Positive control: `2 verified roots -> ANALYSIS_ONLY`, но `execution_authorized=false`.
- Contradiction control: подтверждённое противоречие сохранено, токен `DENIED`.
- Секрет и email отсутствуют в отчёте.
- Шум присутствует в quarantine metadata, но не влияет на evidence gate.
- Повторный запуск даёт тот же результат.
- Подмена одного `admission_token` не открывает downstream-доступ: контракт пересчитывается.
- SHA-256 файлов Truth до и после совпадает.
- Репозиторный leak-guard не обнаруживает запрещённых credentials, открытых provenance-транскриптов и отслеживаемых runtime-файлов.

Успешный тест означает готовность только прототипа очистки v1 к следующему ограниченному эксперименту. Он не означает готовность AION к автономным решениям или production-использованию.

Ограничение v1: provenance-поля в fixtures заданы заранее и не подтверждаются внешней системой идентичности/целостности. Следующий этап должен вводить формальные Evidence Object/Claim Object и проверку происхождения, а не доверять произвольному JSON.
