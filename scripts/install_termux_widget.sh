#!/usr/bin/env bash
# Bootstrap only; installation never stops the user's running AION instance.
set -Eeuo pipefail
umask 077
missing=()
command -v python3 >/dev/null || missing+=(python)
command -v git >/dev/null || missing+=(git)
if ((${#missing[@]})); then
  if ! command -v pkg >/dev/null; then
    echo '[FAIL] Install Python 3.10+, Git and Bash first.' >&2
    exit 2
  fi
  pkg install -y "${missing[@]}"
fi
if command -v pkg >/dev/null; then
  missing=()
  command -v termux-open-url >/dev/null || missing+=(termux-tools)
  # Android usually builds pinned PyYAML/Cython from source rather than wheels.
  command -v clang >/dev/null || missing+=(clang)
  command -v make >/dev/null || missing+=(make)
  test -f "${PREFIX:-/data/data/com.termux/files/usr}/include/yaml.h" || missing+=(libyaml)
  python3 -m ensurepip --version >/dev/null 2>&1 || missing+=(python-ensurepip-wheels)
  if ((${#missing[@]})); then
    pkg install -y "${missing[@]}"
  fi
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/tools/termux_widget.py" install "$@"
