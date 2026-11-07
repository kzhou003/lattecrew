# Slack apps

One manifest per bot. Create each at https://api.slack.com/apps → **Create New App** → **From a manifest**, choose the workspace, paste the YAML, then **Install to Workspace**.

| Manifest | Bot | Connected by |
|---|---|---|
| `manifest.yaml` | first gateway app (`KiroCrew-latte`; rename to `@claude` or `@codex`) | Mac Kiro gateway: `kirocrew setup --slack` |
| `manifest-latte.yaml` | the latte gateway bot (renamed `@claude` in Slack) | latte Kiro gateway |
| `manifest-qwen.yaml` | `@qwen` | `KIROCREW_HOME=~/.kiro/crew-qwen kirocrew setup --slack` |
| `manifest-z-image.yaml`, `manifest-qwen-tts.yaml`, `manifest-wan.yaml` | media bots | `~/.config/latte-media/env` |

Each app needs a bot token (`xoxb-`) and an app-level token with `connections:write` (`xapp-`) for Socket Mode. Never commit them.
