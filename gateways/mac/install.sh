#!/usr/bin/env bash
# Mac side: MCP bridges to the GPU machine, the model tunnel for OpenCode, and bot instructions.
# Assumes `ssh latte` works without a password (Host alias in ~/.ssh/config).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p ~/.local/bin ~/.config/opencode ~/Downloads/LatteCrew
install -m 755 latte-crew-mcp ~/.local/bin/latte-crew-mcp
install -m 755 latte_media_mcp.py ~/.local/bin/latte-media-mcp
[ -f ~/.config/opencode/opencode.json ] || cp opencode.mac.json ~/.config/opencode/opencode.json
sed "s#__HOME__#$HOME#g" mcp.json.example > /tmp/latte-mcp.json
echo "Merge /tmp/latte-mcp.json into ~/.kiro/crew/mcp.json, then: kirocrew setup --agent-only"
echo "Optional model tunnel (127.0.0.1:18100 -> latte:8100) at login:"
echo "  cp dev.lattecrew.models.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/dev.lattecrew.models.plist"
