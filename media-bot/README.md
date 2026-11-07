# Media bots

`media_bot.py` connects three Slack apps (`@z-image`, `@qwen-tts`, `@wan`) over Socket Mode. A message to a bot becomes one request to llama-swap, under the shared GPU lock; the result is uploaded back to the thread. No LLM is involved. Only `OWNER_ID` may use them.

```bash
./install.sh                         # first run writes ~/.config/latte-media/env from env.example
$EDITOR ~/.config/latte-media/env    # owner Slack user ID and each bot's xoxb-/xapp- tokens
./install.sh                         # starts the media-bot user service
```

Bots without tokens are skipped; a bot whose token fails does not stop the others. The same script is also a CLI used by the Mac's MCP bridge: `media_bot.py image "<prompt>" --size 1024x1024`, `speech "<text>"`, `video wan "<prompt>" --seconds 5`.
