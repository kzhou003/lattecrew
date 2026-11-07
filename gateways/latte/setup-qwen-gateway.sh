#!/usr/bin/env bash
# Set up the @qwen Kiro Crew gateway on the GPU machine: OpenCode on the local Qwen model,
# with its own data home (~/.kiro/crew-qwen) and port (5477), as a user systemd service.
# Run after models/install.sh and after the main gateway (~/.kiro/crew) exists.
set -euo pipefail
cd "$(dirname "$0")"
NODE_BIN=${NODE_BIN:-$(dirname "$(command -v node)")}
export PATH=$NODE_BIN:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
export KIROCREW_HOME=$HOME/.kiro/crew-qwen KIROCREW_PORT=5477
mkdir -p "$KIROCREW_HOME/workspace"; chmod 700 "$KIROCREW_HOME"
# Same MCP servers as the main gateway (latte-crew), so @qwen can dispatch crew_local jobs.
cp ~/.kiro/crew/mcp.json "$KIROCREW_HOME/mcp.json"; chmod 600 "$KIROCREW_HOME/mcp.json"
kirocrew setup --agent-only 2>&1 | tail -1
kirocrew config set agent.acp_backend opencode | tail -1
kirocrew config set agent.member_acp_backend opencode | tail -1
kirocrew config set timezone "${TZ_NAME:-America/Los_Angeles}" | tail -1
kirocrew config set auto_update false | tail -1
cp qwen-AGENTS.md "$KIROCREW_HOME/workspace/AGENTS.md"
mkdir -p ~/.config/systemd/user
sed "s#__NODE_BIN__#$NODE_BIN#" kirocrew-qwen.service > ~/.config/systemd/user/kirocrew-qwen.service
systemctl --user daemon-reload
systemctl --user enable --now kirocrew-qwen.service
echo "Gateway on 127.0.0.1:5477. Next: KIROCREW_HOME=$KIROCREW_HOME kirocrew setup --slack  (uses the @qwen Slack app)"
