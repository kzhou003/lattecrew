# Slack apps

One manifest per bot. Create each at https://api.slack.com/apps → **Create New App** → **From a manifest**, choose the workspace, paste the YAML, then **Install to Workspace**.

| Manifest | Bot | Connected by |
|---|---|---|
| `manifest-codex.yaml` | `@codex`, slash command `/codex` | Mac Kiro gateway: `kirocrew setup --slack`, then `kirocrew config set slack.command codex` |
| `manifest-claude.yaml` | `@claude`, slash command `/claude` | latte Kiro gateway, `slack.command claude` |
| `manifest-qwen.yaml` | `@qwen` | `KIROCREW_HOME=~/.kiro/crew-qwen kirocrew setup --slack` |
| `manifest-z-image.yaml`, `manifest-qwen-tts.yaml`, `manifest-wan.yaml` | media bots | `~/.config/latte-media/env` |

Kiro's `slack.command` must equal the app's slash command without the slash; change both together. Each app needs a bot token (`xoxb-`) and an app-level token with `connections:write` (`xapp-`) for Socket Mode. Never commit them.
