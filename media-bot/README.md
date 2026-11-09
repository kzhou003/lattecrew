# Media bots

`media_bot.py` connects three Slack apps (`@z-image`, `@qwen-tts`, `@wan`) over Socket Mode. A message to a bot becomes one request to llama-swap, under the shared GPU lock; the result is uploaded back to the thread. No LLM is involved. The owner (`OWNER_ID`) is always allowed and unlimited. Others come from `ALLOWED_USERS`: `*` for every member of this workspace (users from other workspaces via Slack Connect are ignored), or a comma list of user IDs. Each non-owner gets a daily quota per bot (`DAILY_LIMITS`, default 30 images, 30 speech clips, 3 videos) and one request at a time; counts reset when the service restarts.

```bash
./install.sh                         # first run writes ~/.config/latte-media/env from env.example
$EDITOR ~/.config/latte-media/env    # owner Slack user ID and each bot's xoxb-/xapp- tokens
./install.sh                         # starts the media-bot user service
```

Bots without tokens are skipped; a bot whose token fails does not stop the others. The same script is also a CLI used by the Mac's MCP bridge: `media_bot.py image "<prompt>" --size 1024x1024`, `speech "<text>"`, `video wan "<prompt>" --seconds 5`.
