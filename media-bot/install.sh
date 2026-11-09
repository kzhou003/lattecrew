#!/usr/bin/env bash
# Install the media bots (@z-image, @qwen-tts, @wan) and @qwen-chat as a user service on the GPU machine.
set -euo pipefail
cd "$(dirname "$0")"
ENV=~/latte-models/bot-env
if [ ! -x $ENV/bin/python ]; then
  python3 -m venv $ENV
  $ENV/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cpu
fi
$ENV/bin/pip install -q -r requirements.txt
$ENV/bin/python -c "import spacy.util,sys; sys.exit(0 if spacy.util.is_package('en_core_web_sm') else 1)" \
  || $ENV/bin/python -m spacy download en_core_web_sm -q
# Qdrant holds @qwen-chat's long-term memory. Localhost only; its data lives under ~/latte-models/qdrant.
if ! docker inspect qdrant >/dev/null 2>&1; then
  mkdir -p ~/latte-models/qdrant/storage
  docker run -d --name qdrant --restart unless-stopped -p 127.0.0.1:6333:6333 -e QDRANT__TELEMETRY_DISABLED=true \
    -v ~/latte-models/qdrant/storage:/qdrant/storage qdrant/qdrant:v1.20.0
fi
mkdir -p ~/latte-crew ~/.config/latte-media ~/.config/systemd/user
cp media_bot.py chat_tools.py chat_memory.py ~/latte-crew/
if [ ! -f ~/.config/latte-media/env ]; then
  cp env.example ~/.config/latte-media/env; chmod 600 ~/.config/latte-media/env
  echo "Fill in ~/.config/latte-media/env (Slack tokens), then rerun."; exit 1
fi
cp media-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now media-bot.service
systemctl --user is-active media-bot.service
