# AION: полная практическая проверка на облачном сервере

Ветка: `integration-life-trial-v1-20261015`

## Назначение

Проверить одной последовательностью:

1. компиляцию;
2. архитектуру и загрузку Truth;
3. очистку информации v1;
4. Evidence Objects v2;
5. analysis-only evidence bridge;
6. неизменность Truth;
7. одиночный реальный LLM-вызов;
8. мультимодельную ротацию, если заданы две разные модели.

Результат считается подтверждением жизнеспособности только для проверенных функций и условий. Это не доказывает фактическую истинность ответов моделей.

## 1. Подготовка Ubuntu/Debian-сервера

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip gh
gh auth login
```

При `gh auth login` выбрать GitHub.com, HTTPS и вход через браузер. API-ключ модели туда не вводится.

## 2. Получение точной ветки

Если AION ещё не клонирован:

```bash
cd ~
gh repo clone belnik1981-stack/AION
cd ~/AION
git fetch --all --prune
git switch integration-life-trial-v1-20261015
git pull --ff-only origin integration-life-trial-v1-20261015
```

Если папка `~/AION` уже существует:

```bash
cd ~/AION
git status --short --branch
git fetch --all --prune
git switch integration-life-trial-v1-20261015
git pull --ff-only origin integration-life-trial-v1-20261015
```

Если `git status` показывает ваши незакоммиченные изменения, остановиться и не переключать ветку до их сохранения.

## 3. Изолированная среда Python

```bash
cd ~/AION
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
```

## 4. Полная офлайн-проверка

```bash
cd ~/AION
. .venv/bin/activate
bash scripts/full_life_test.sh
```

Нормальный итог:

```text
[PASS] Truth unchanged after offline tests
[PASS] OFFLINE LIFE TRIAL
```

Отчёт сохраняется в `test-reports/life-trial-<время>.log`.

## 5. Реальная проверка одной модели

Ключ вводить скрыто, чтобы он не попал в историю команд:

```bash
cd ~/AION
. .venv/bin/activate
read -s -p "OpenRouter API key: " AION_API_KEY
echo
export AION_API_KEY
export AION_LIVE_TEST=1
export AION_PROVIDER=openai_compatible
export AION_API_URL=https://openrouter.ai/api/v1
export AION_MODEL='inclusionai/ling-3.0-flash-fin:free'
export AION_FREE_ONLY=1
export AION_TIMEOUT=30
export AION_MAX_TOKENS=900
export AION_REASONING_EFFORT=none
bash scripts/full_life_test.sh
```

Успех требует непустого финального ответа, отсутствия статуса `error` и неизменности Truth.

## 6. Реальная проверка нескольких моделей

Нужно указать минимум две разные фактически доступные модели OpenRouter с суффиксом `:free`:

```bash
export AION_MODELS='ПЕРВАЯ_МОДЕЛЬ:free,ВТОРАЯ_МОДЕЛЬ:free'
bash scripts/full_life_test.sh
```

Нормальный итог:

```text
"mode": "multi_model_role_rotation"
"independent_model_count": 2
[PASS] FULL LIFE TRIAL
```

`openrouter/free` не следует считать независимой второй моделью рядом с конкретной моделью: маршрутизатор может выбрать тот же источник.

## 7. Проверка пользовательской задачи

После успешного теста:

```bash
python pipeline_cli.py "Проанализируй предоставленное утверждение, отдели факты, гипотезы, противоречия и недостающие доказательства."
```

Для веб-интерфейса:

```bash
bash start_app.sh
```

Затем открыть `http://АДРЕС_СЕРВЕРА:8080`, только если порт защищён firewall/VPN. Не публиковать порт 8080 в интернет без аутентификации.

## 8. Стоп-условия

Испытание остановить, если:

- изменились `knowledge/truth/truth.json` или `knowledge/truth/system.yaml`;
- ключ появился в выводе или файлах;
- возник бесконечный повтор;
- запрос не завершился после provider timeout;
- модель вернула пустой или обрезанный ответ;
- одна из двух моделей недоступна;
- Git показывает неожиданные изменения исходного кода.

Остановка: `Ctrl+C`.

## 9. Критерий жизнеспособности

`READY WITH CONDITIONS`, если:

- офлайн-тесты полностью прошли;
- один реальный запрос завершился;
- два разных модельных ответа получены;
- мультимодельный режим сформировал непустой результат;
- Truth не изменился;
- повторный запуск воспроизводит результат исполнения без зависания.

Точность и истинность содержательного ответа оцениваются отдельно на заранее подготовленном наборе задач с известными эталонами.
