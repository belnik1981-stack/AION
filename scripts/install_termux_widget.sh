#!/usr/bin/env bash
set -Eeuo pipefail

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
shortcuts_dir="${AION_WIDGET_SHORTCUTS_DIR:-$HOME/.shortcuts}"
shortcut="$shortcuts_dir/AION_stage1"
mkdir -p "$shortcuts_dir"
chmod 700 "$shortcuts_dir"
temporary="$(mktemp "$shortcuts_dir/.AION_stage1.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
{
    printf '%s\n' '#!/data/data/com.termux/files/usr/bin/bash'
    printf 'exec bash %q\n' "$root/scripts/termux_widget_start.sh"
} > "$temporary"
chmod 700 "$temporary"
if [[ -e "$shortcut" || -L "$shortcut" ]]; then
    if [[ -f "$shortcut" ]] && cmp -s "$temporary" "$shortcut"; then
        printf '[AION] Ярлык уже установлен: %s\n' "$shortcut"
        exit 0
    fi
    printf '[AION] Ярлык %s уже существует и отличается; он не изменён.\n' "$shortcut" >&2
    exit 1
fi
ln "$temporary" "$shortcut"
printf '[AION] Ярлык создан: %s\n' "$shortcut"
printf '[AION] Добавьте виджет Termux:Widget на главный экран Android.\n'
