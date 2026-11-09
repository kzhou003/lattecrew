# Media bots

`media_bot.py` connects four Slack apps (`@z-image`, `@qwen-tts`, `@wan`, `@qwen-chat`) over Socket Mode. A message to a bot becomes one request to llama-swap, under the shared GPU lock; the result is uploaded back to the thread. No LLM is involved. The owner (`OWNER_ID`) is always allowed and unlimited. Others come from `ALLOWED_USERS`: `*` for every member of this workspace (users from other workspaces via Slack Connect are ignored), or a comma list of user IDs. Each non-owner gets a daily quota per bot (`DAILY_LIMITS`, default 30 images, 30 speech clips, 3 videos, 100 chat messages) and one request at a time; counts reset when the service restarts.

```bash
./install.sh                         # first run writes ~/.config/latte-media/env from env.example
$EDITOR ~/.config/latte-media/env    # owner Slack user ID and each bot's xoxb-/xapp- tokens
./install.sh                         # starts the media-bot user service
```

Bots without tokens are skipped; a bot whose token fails does not stop the others. The same script is also a CLI used by the Mac's MCP bridge: `media_bot.py image "<prompt>" --size 1024x1024`, `speech "<text>"`, `video wan "<prompt>" --seconds 5`.

## @qwen-chat

Chat with the local Qwen3.8 in Slack threads, with three tools (`chat_tools.py`):

| Tool | What it does | Guard |
|---|---|---|
| `web_search` | queries a self-hosted SearXNG on `127.0.0.1:8888` | per-person daily web quota (`web` in `DAILY_LIMITS`, default 60) |
| `fetch_url` | opens a page and returns its main text (12K characters) | public addresses only: loopback, private, link-local and Tailscale (`100.64.0.0/10`) are refused; every redirect is re-checked and the connection is pinned to the checked IP; 3 MB, 15 s, http(s) only |
| `calculate` | exact arithmetic from a parsed expression tree | no Python evaluation; exponent and factorial caps |

How it behaves: every DM gets a reply in a thread, in channels it answers when mentioned, and it reads the thread for context (last 20 messages, ~24K characters) including text, code and log files people upload (needs the `files:read` scope). One progress message shows what it is doing (searching, reading a site, calculating) and is replaced by the answer, with source links. At most 6 tool calls per question. `think=on` turns on Qwen's reasoning for that answer. Markdown is converted to Slack mrkdwn. If Qwen is already loaded it answers right away; otherwise it takes the GPU lock, waits for any image or video job, and loads Qwen (about a minute).

SearXNG (once):

```bash
mkdir -p ~/latte-models/searxng
cat > ~/latte-models/searxng/settings.yml <<EOF
use_default_settings: true
server: {secret_key: "$(python3 -c 'import secrets;print(secrets.token_hex(32))')", limiter: false, image_proxy: false}
search: {safe_search: 1, formats: [html, json]}
EOF
docker run -d --name searxng --restart unless-stopped -p 127.0.0.1:8888:8080 \
  -v ~/latte-models/searxng:/etc/searxng:rw docker.io/searxng/searxng:latest
```

Create the Slack app from `slack/manifest-qwen-chat.yaml` and put its tokens in `QWEN_CHAT_BOT_TOKEN` (`xoxb-`) and `QWEN_CHAT_APP_TOKEN` (`xapp-`); swapping them gives `not_allowed_token_type`. `install.sh` copies `media_bot.py`, `chat_tools.py` and `chat_memory.py` to `~/latte-crew/` and runs the service from its own venv, `~/latte-models/bot-env` (`requirements.txt`, CPU torch), so it never touches vLLM's packages.

### Long-term memory (`chat_memory.py`)

@qwen-chat remembers durable facts about each person (preferences, ongoing projects, things they asked it to remember) with [Mem0 OSS](https://github.com/mem0ai/mem0) 2.2.1 on Qdrant 1.20 (container `qdrant`, `127.0.0.1:6333`, data in `~/latte-models/qdrant`).

- **Recall**: before each answer, the question is searched in that person's memories (bge-m3 on the CPU, semantic + BM25 + entity scores, threshold 0.45, top 6) and the hits go into the system prompt with their dates. About 50 to 150 ms; no GPU.
- **Learn**: after the answer is posted, the person's own message (never the answer or web pages) is queued for extraction by Qwen with thinking off. The queue only runs while Qwen is already loaded, so remembering never evicts an image or video model; a turn that waits more than 6 hours is dropped.
- **Isolation**: memories are keyed by Slack user ID. Facts learned in a DM are recalled only in DMs; channel threads only see facts learned in channels.
- **Secrets**: API keys, Slack/GitHub/HF tokens, private keys, JWTs and `password: …` style values are redacted before extraction, and any stored memory that still looks like one is deleted.
- **Commands** (no LLM call): `memory` lists (DM only), `forget 2`, `forget all`, `memory off` / `memory on` (kept in `~/latte-models/memory/prefs.json`), `remember: …` stores one sentence verbatim.
- Mem0 telemetry is switched off (`MEM0_TELEMETRY=False`), and so is Qdrant's. `QWEN_CHAT_MEMORY=off` in the env file disables memory. If Qdrant or the embedding model is down, the bot answers without memory.
