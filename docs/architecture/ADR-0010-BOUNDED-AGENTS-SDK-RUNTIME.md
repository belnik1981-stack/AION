# ADR-0010: ограниченный optional Agents SDK runtime

Статус: принято и проверено offline
Дата: 2026-10-19

## Контекст

Необязательный `runtimes/openai_agents.py` обходил ограничения основного
pipeline: его моделью по умолчанию была потенциально платная модель, SDK/client
мог повторять запросы, общий wall-clock deadline отсутствовал, а сырой текст
исключения попадал в `AgentsRuntimeError`.

## Решение

- модель по умолчанию заменена на `openrouter/free`;
- `AION_FREE_ONLY` включён по умолчанию и до импорта SDK допускает только
  `openrouter/free` либо явный идентификатор с `:free`;
- custom API endpoint требует отдельного `AION_ALLOW_CUSTOM_API=1`, HTTPS и
  отключения непроверяемой free-only гарантии;
- `max_turns` ограничен меньшим из Truth `max_iterations` и общего настроенного
  call ceiling;
- `ModelSettings.timeout` ограничивает каждый model call, а
  `asyncio.wait_for` — весь agent run по Truth `timeout_seconds`;
- SDK client retries отключены (`max_retries=0`);
- `ModelSettings.max_tokens` ограничен диапазоном `1..4096`;
- tracing остаётся opt-in, а логирование model/tool data принудительно
  отключено;
- task и output проходят центральное редактирование секретов;
- provider/SDK exceptions преобразуются в стабильные коды без сырого текста;
- результат прямо содержит `truth_verified=false`, scope
  `agents_sdk_runtime_only` и отсутствие полномочий записи Truth/memory.

Для async-среды предоставлен `run_agent_async`; синхронный wrapper отказывается
вкладывать второй event loop.

## Проверка

`tests/harness/test_agents_runtime_adapter.py` без сети проверяет:

- безопасный status без ключа и полного API URL;
- блокировку платной модели и custom credential target;
- output-token ceiling;
- отключённые retries, per-call timeout, whole-run deadline и turn ceiling;
- редактирование секрета во входе и выходе;
- отсутствие сырого provider exception;
- закрытие клиента и запрет вложенного sync event loop.

Отдельный CI-job устанавливает закреплённый `openai-agents==0.22.1` и запускает
`test_agents_sdk_import_contract.py`: реальные SDK-классы создаются с
timeout/max_tokens и отключёнными client retries, но provider не вызывается.

## Границы решения

- основной runtime проверяется mock-контрактом, а совместимость типов — с
  установленным SDK в CI; ни одна из этих проверок не является API-тестом;
- отдельный запуск Agents SDK имеет собственный bounded budget, но не делит
  один счётчик с одновременно запущенным основным pipeline;
- `max_turns` ограничивает AI invocations по контракту SDK, но AION не
  воспроизводит внутреннюю телеметрию провайдера;
- free-only label и нулевая фактическая стоимость требуют отдельной проверки
  каталога/ответа провайдера; этот adapter не доказывает их объективно;
- успешный SDK run является модельным наблюдением, а не внешней проверкой.
