#!/usr/bin/env bash
# Install the model layer on the GPU machine: a vLLM + vLLM-Omni venv, model weights,
# the serve scripts, llama-swap as a user service, and the OpenCode provider config.
#   ./install.sh            everything
#   SKIP_ENV=1 ./install.sh scripts and services only
set -euo pipefail
cd "$(dirname "$0")"
D=$HOME/latte-models
mkdir -p "$D/bin" "$D/logs" "$D/outputs"
cp bin/*.sh "$D/bin/"; chmod +x "$D/bin/"*.sh
[ -n "${SKIP_ENV:-}" ] || bash install-env.sh
# llama-swap: one model on the GPU at a time, on 127.0.0.1:8100.
if [ ! -x "$D/bin/llama-swap" ]; then
  echo "Download llama-swap (https://github.com/mostlygeek/llama-swap/releases, linux_amd64) to $D/bin/llama-swap, then rerun."; exit 1
fi
sed "s#__HOME__#$HOME#g" llama-swap.yaml.template > "$D/llama-swap.yaml"
mkdir -p ~/.config/systemd/user ~/.config/opencode
cp systemd/llama-swap.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now llama-swap.service
# Keep user services running without a login session.
loginctl show-user "$USER" -p Linger | grep -q yes || echo "Run once: sudo loginctl enable-linger $USER"
[ -f ~/.config/opencode/opencode.json ] || cp opencode.latte.json ~/.config/opencode/opencode.json
curl -s http://127.0.0.1:8100/v1/models | head -c 300; echo
