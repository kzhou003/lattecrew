#!/usr/bin/env bash
# Install crewd on the GPU machine into ~/latte-crew and start it as a user service.
# The Mac's MCP bridge and the notify cron expect crew.py at ~/latte-crew/crew.py.
set -euo pipefail
SRC=$(cd "$(dirname "$0")" && pwd)
DST=$HOME/latte-crew
mkdir -p "$DST/var" ~/.local/bin ~/.config/systemd/user
cp "$SRC/crew.py" "$SRC/config.example.json" "$SRC/opencode-permissions.json" "$DST/"
cp -r "$SRC/roles" "$DST/"
cp "$SRC/systemd/crewd.service" ~/.config/systemd/user/crewd.service
cd "$DST"
[ -f config.json ] || cp config.example.json config.json
chmod +x crew.py
ln -sf "$DST/crew.py" ~/.local/bin/crew
systemctl --user daemon-reload
systemctl --user enable crewd.service >/dev/null 2>&1
systemctl --user restart crewd.service
systemctl --user is-active crewd.service
crew health
