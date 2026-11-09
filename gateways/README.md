# Gateways

## latte (GPU machine)

| File | Purpose |
|---|---|
| `latte/setup-qwen-gateway.sh` | the `@qwen` gateway: `KIROCREW_HOME=~/.kiro/crew-qwen`, port 5477, OpenCode backend, user service |
| `latte/kirocrew-qwen.service` | its unit (`__NODE_BIN__` filled in by the script) |
| `latte/qwen-AGENTS.md` | instructions for `@qwen`: dispatch with `crew_local`, escalate hard work to `@claude` |
| `latte/latte_notify.py` | Kiro script cron: posts crewd job updates to your Slack DM |
| `latte/qwen-chat.sh` | send one message to the `@qwen` gateway from the shell and show the reply |

The main latte gateway (`@claude`) is the system service from `kirocrew service install`; see `docs/setup.md`.

## Mac

| File | Purpose |
|---|---|
| `mac/install.sh` | installs the bridges below and prints the next steps |
| `mac/latte-crew-mcp` | MCP stdio bridge: `ssh latte python3 ~/latte-crew/crew.py mcp` |
| `mac/latte_media_mcp.py` | MCP server for one media model (`image`, `speech`, `wan`); saves results to `~/Downloads/LatteCrew` |
| `mac/mcp.json.example` | the `latte-crew` server entry for `~/.kiro/crew/mcp.json` |
| `mac/claude-bot-CLAUDE.md` | instructions for the `claude` Bot: delegate repo work to latte (`~/.kiro/crew/workspace-member-claude/CLAUDE.md`) |
| `mac/codex-bot-AGENTS.md` | the same for the `codex` Bot; Codex reads `AGENTS.md` (`workspace-member-codex/AGENTS.md`) |
| `mac/opencode.mac.json` | OpenCode on the Mac using latte's models through the tunnel |
| `mac/dev.lattecrew.models.plist` | LaunchAgent for the tunnel 127.0.0.1:18100 → latte:8100 |
