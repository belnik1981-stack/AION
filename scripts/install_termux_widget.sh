#!/usr/bin/env bash
set -Eeuo pipefail

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
shortcuts_dir="${AION_WIDGET_SHORTCUTS_DIR:-$HOME/.shortcuts}"
shortcut="$shortcuts_dir/AION_stage1"
mkdir -p "$shortcuts_dir"
chmod 700 "$shortcuts_dir"
{
    printf '%s\n' '#!/data/data/com.termux/files/usr/bin/bash'
    printf 'exec bash %q\n' "$root/scripts/termux_widget_start.sh"
} > "$shortcut"
chmod 700 "$shortcut"
printf '[AION] Ярлык создан: %s\n' "$shortcut"
printf '[AION] Добавьте виджет Termux:Widget на главный экран Android.\n'
