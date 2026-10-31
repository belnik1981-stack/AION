#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
url="http://localhost:8080"
export AION_DATA_DIR="${AION_DATA_DIR:-$HOME/.local/share/aion}"

aion_is_ready() {
    python3 - "$root" "$AION_DATA_DIR" <<'PY' >/dev/null 2>&1
from hashlib import sha256
from pathlib import Path
import sys
from urllib.request import ProxyHandler, build_opener
expected = sha256(str(Path(sys.argv[1]).resolve()).encode("utf-8")).hexdigest()[:16]
expected_data = sha256(str(Path(sys.argv[2]).resolve()).encode("utf-8")).hexdigest()[:16]
opener = build_opener(ProxyHandler({}))
with opener.open("http://127.0.0.1:8080/", timeout=1) as response:
    page = response.read(12000)
    if (response.status != 200 or b"AION Control Panel" not in page
            or response.headers.get("X-AION-Instance") != expected
            or response.headers.get("X-AION-Data") != expected_data):
        raise SystemExit(1)
PY
}

port_is_in_use() {
    python3 - <<'PY' >/dev/null 2>&1
import socket
with socket.create_connection(("127.0.0.1", 8080), timeout=1):
    pass
PY
}

open_browser() {
    if command -v termux-open-url >/dev/null 2>&1; then
        termux-open-url "$url"
    else
        am start -a android.intent.action.VIEW -d "$url" >/dev/null
    fi
}

if aion_is_ready; then
    open_browser
    exit 0
fi
if port_is_in_use; then
    printf '[AION] Порт 8080 занят другим сервером или AION ещё обрабатывает запрос. Остановите прежний сервер.\n' >&2
    exit 1
fi

python3 "$root/scripts/migrate_stage1_data.py"

printf '[AION] Для реального вопроса нужен ваш ключ OpenRouter.\n'
read -r -s -p 'Ключ OpenRouter (ввод скрыт): ' AION_API_KEY
printf '\n'
if [[ -z "$AION_API_KEY" ]]; then
    printf '[AION] Пустой ключ; запуск отменён.\n' >&2
    exit 2
fi
export AION_API_KEY
export AION_MODEL=openrouter/free
export AION_MODELS=
export AION_FREE_ONLY=1

bash "$root/start_app.sh" &
server_pid=$!
stop_server() {
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
    printf '[AION] Локальный сервер остановлен.\n'
}
trap stop_server EXIT
trap 'exit 130' INT TERM

for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if aion_is_ready; then
        printf '[AION] Сервер готов: %s\n' "$url"
        open_browser
        wait "$server_pid" || true
        exit 0
    fi
    if ! kill -0 "$server_pid" 2>/dev/null; then
        printf '[AION] Сервер не запустился; проверьте сообщение выше.\n' >&2
        exit 1
    fi
    sleep 1
done
printf '[AION] Сервер не ответил за 10 секунд.\n' >&2
exit 1
