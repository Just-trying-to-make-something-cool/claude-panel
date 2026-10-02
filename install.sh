#!/bin/sh
# Установка панели: venv с Textual, fzf для запасного режима, команда `c` (и русская `с`) в ~/.local/bin.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements.txt"
command -v fzf >/dev/null || { command -v brew >/dev/null && brew install fzf; }
mkdir -p "$HOME/.local/bin"
ln -sf "$ROOT/bin/c" "$HOME/.local/bin/c"
ln -sf "$ROOT/bin/c" "$HOME/.local/bin/с"
chmod +x "$ROOT/bin/c"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "добавь в ~/.zshrc: export PATH=\"\$HOME/.local/bin:\$PATH\"";; esac
echo "готово: набери c в новом окне терминала"
