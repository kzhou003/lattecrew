# Media bots

`media_bot.py` connects four Slack apps (`@z-image`, `@qwen-tts`, `@wan`, `@qwen-chat`) over Socket Mode. A message to a bot becomes one request to llama-swap, under the shared GPU lock; the result is uploaded back to the thread. No LLM is involved. The owner (`OWNER_ID`) is always allowed and unlimited. Others come from `ALLOWED_USERS`: `*` for every member of this workspace (users from other workspaces via Slack Connect are ignored), or a comma list of user IDs. Each non-owner gets a daily quota per bot (`DAILY_LIMITS`, default 30 images, 30 speech clips, 3 videos, 100 chat messages) and one request at a time; counts reset when the service restarts.

```bash
./install.sh                         # first run writes ~/.config/latte-media/env from env.example
$EDITOR ~/.config/latte-media/env    # owner Slack user ID and each bot's xoxb-/xapp- tokens
./install.sh                         # starts the media-bot user service
```

Bots without tokens are skipped; a bot whose token fails does not stop the others. The same script is also a CLI used by the Mac's MCP bridge: `media_bot.py image "<prompt>" --size 1024x1024`, `speech "<text>"`, `video wan "<prompt>" --seconds 5`.

## @qwen-chat

Plain chat with the local Qwen3.8 in Slack threads: every DM gets a reply, in channels it answers when mentioned, and it reads the thread for context (last 20 messages, ~24K characters). `think=on` in a message turns on Qwen's reasoning for that answer. It has no tools. If Qwen is already loaded (for example during a crewd job) it answers right away; otherwise it takes the GPU lock, waits for any image or video job, and loads Qwen (about a minute). Create the app from `slack/manifest-qwen-chat.yaml` and put its tokens in `QWEN_CHAT_BOT_TOKEN` / `QWEN_CHAT_APP_TOKEN`.

