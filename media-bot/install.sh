#!/usr/bin/env bash
# Install the media bots (@z-image, @qwen-tts, @wan) as a user service on the GPU machine.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p ~/latte-crew ~/.config/latte-media ~/.config/systemd/user
cp media_bot.py ~/latte-crew/
if [ ! -f ~/.config/latte-media/env ]; then
  cp env.example ~/.config/latte-media/env; chmod 600 ~/.config/latte-media/env
  echo "Fill in ~/.config/latte-media/env (Slack tokens), then rerun."; exit 1
fi
cp media-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now media-bot.service
systemctl --user is-active media-bot.service
