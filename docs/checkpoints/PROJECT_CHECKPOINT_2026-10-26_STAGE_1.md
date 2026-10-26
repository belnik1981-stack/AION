# Контрольная точка этапа 1 — 2026-10-26

- Исходный `master`: `f2d1bf26cda92ef0632167a18e5bfd81548e436c`.
- Ветка: `codex/stage-1-persistent-memory-20261026`.
- Статус: реализация этапа 1; подтверждение владельца ещё не получено.
- Предыдущая JSON-память, Truth и мультимодельный pipeline сохраняются.
- Операционная память: `memory/session.py`, локальная SQLite-база в
  `knowledge/session/`, команды `session_cli.py`.
- Откат кода: вернуться к исходному commit или закрыть PR без слияния.
  Личные runtime-данные остаются локально и не входят в Git.
- Откат данных: выбрать проверенную копию через `session_cli.py restore`;
  исходные файлы сохраняются с суффиксом `.before-restore-*`.
- Следующее действие: личная офлайн-проверка в Termux по инструкции ниже,
  затем решение владельца по этапу 1. Этап 2 не запускать автоматически.

## Проверки в среде разработки

- Новый тест восстановления после завершения дочернего процесса: PASS.
- Существующие офлайн-тесты до HTTP smoke: PASS; оба trial runner: PASS.
- HTTP smoke: НЕ ПРОВЕРЕН — песочница запретила локальный сокет.
- Работа на Android: ожидает личной проверки владельца; этот документ не
  объявляет весь AION успешно испытанным.

## Личная проверка в Termux

В отдельном checkout ветки PR, с Python 3.10+ и без API-ключа:

```bash
cd AION
PYTHONPATH=. python3 tests/harness/test_session_persistence.py
python3 session_cli.py set AION_MODEL example/model:free
python3 session_cli.py decision "Пробное решение этапа 1"
python3 session_cli.py checkpoint "Проба перед перезапуском"
python3 -c 'from memory.session import begin_task; print(begin_task("Незавершённая пробная задача", "pipeline"))'
python3 session_cli.py status
```

Полностью закройте Termux, откройте снова, перейдите в тот же каталог и
выполните `python3 session_cli.py status`. Убедитесь, что профиль, решение,
контрольная точка и текст задачи сохранились, а задача имеет статус
`interrupted`. Команды не обращаются к моделям и не требуют ключа. База
остаётся только на телефоне, поэтому не публикуйте её вместе с отчётом.
