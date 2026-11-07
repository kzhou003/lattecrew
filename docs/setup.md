# Setup runbook

The order matters: each phase depends on the one before it. Every phase ends with a **check**; do not continue until it passes.

Names used below: the GPU machine is `latte` (an SSH `Host` alias on the Mac), the repo is cloned at `~/lattecrew` on both machines.

## Phase 0. Machines and access

1. Put both machines on Tailscale (or one LAN). On the Mac, add to `~/.ssh/config`:
   ```
   Host latte
     HostName <tailscale-name-or-ip>
     User <you>
     ControlMaster auto
     ControlPath ~/.ssh/cm-%r@%h:%p
     ControlPersist 10m
   ```
   `ControlMaster` reuses one connection: a new SSH handshake costs ~350 ms, a reused one ~40 ms.
2. Keep the GPU machine awake: `sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target`.
3. Let user services run without a login: `sudo loginctl enable-linger $USER`.
4. Install Claude Code on both machines and log in (`claude`, then `/login`). Install Node 22 (nvm) and OpenCode on latte (`npm i -g opencode-ai`).

**Check:** `ssh latte 'nvidia-smi --query-gpu=name,memory.total --format=csv,noheader && claude --version && opencode --version'`

## Phase 1. Models on the GPU

```bash
ssh latte 'cd ~/lattecrew && models/install.sh'
```
This creates `~/latte-models/env` (vLLM 0.32 + vLLM-Omni 0.32, torch for CUDA 13), downloads the weights, installs the serve scripts and starts `llama-swap` on `127.0.0.1:8100`. Download the llama-swap binary first (the script tells you where).

| Model | Name in requests | Port | Notes |
|---|---|---|---|
| Qwen3.8-27B AWQ INT4 | `qwen3.8` | 8101 | context 65,536, 2 sequences, prefix caching, tool and reasoning parsers |
| Z-Image-Turbo | `z-image` | 8102 | `/v1/images/generations` |
| Qwen3-TTS-12Hz-1.7B-CustomVoice | `qwen-tts` | 8103 | `/v1/audio/speech` |
| Wan2.2-TI2V-5B | `wan2.2-ti2v` | 8104 | multipart `/upstream/wan2.2-ti2v/v1/videos/sync`, CPU offload |

`serve-qwen.sh` sizes `--gpu-memory-utilization` from the memory that is actually free, because a desktop browser can hold ~2 GB of VRAM. Logs go to `~/latte-models/logs/`.

**Check:**
```bash
ssh latte 'curl -s 127.0.0.1:8100/v1/chat/completions -H "Content-Type: application/json" \
  -d "{\"model\":\"qwen3.8\",\"messages\":[{\"role\":\"user\",\"content\":\"say ok\"}],\"max_tokens\":20}"'
```
The first call loads the model (~60 s).

Optional, measured 1.5–2× faster decode: MTP speculative decoding. `serve-qwen.sh` appends `$EXTRA` to the vLLM command, so add to the `qwen3.8` entry in `~/latte-models/llama-swap.yaml`:
```yaml
    env:
      - 'EXTRA=--speculative-config {"method":"qwen3_5_mtp","num_speculative_tokens":3}'
```
It costs ~40% of the KV cache (140K → 78K tokens).

## Phase 2. crewd

```bash
ssh latte 'cd ~/lattecrew && crew/install.sh'
```
Installs to `~/latte-crew/`, links `~/.local/bin/crew`, starts the `crewd` user service. Edit `~/latte-crew/config.json` for budgets, concurrency, timeouts and `repo_roots` (where your repos live).

**Check:** `ssh latte 'crew health && crew task "Say hello in one sentence." --risk low && sleep 60 && crew status'`

## Phase 3. Kiro Crew gateways

Kiro Crew runs one gateway per Slack identity.

**Mac gateway (`@claude` and the `@codex` Bot).** The Kiro desktop app owns this gateway.
1. Use the Claude Code harness: `kirocrew config set agent.acp_backend claude` and `kirocrew config set agent.member_acp_backend claude`.
2. Give it the crew tools: `gateways/mac/install.sh`, merge the printed `mcp.json` into `~/.kiro/crew/mcp.json`, then `kirocrew setup --agent-only`.
3. A Bot chats through a conductor that mounts no user MCP. To let a Bot delegate, put [`gateways/mac/claude-bot-CLAUDE.md`](../gateways/mac/claude-bot-CLAUDE.md) in `~/.kiro/crew/workspace-member-<bot>/CLAUDE.md` and run, in that directory, `claude mcp add -s local latte-crew ~/.local/bin/latte-crew-mcp`.
4. Codex Bot: `kirocrew config set agents.<bot>.acp_backend codex`.
5. Media Bots on the Mac (optional): in the Bot's workspace, `claude mcp add -s local latte-media ~/.local/bin/latte-media-mcp image|speech|wan`.

**latte gateway (`@claude` on the GPU machine).** A system service:
```bash
ssh latte
kirocrew sandbox install-profile     # AppArmor profile (asks for sudo); ~/.kiro must not be group-writable
kirocrew service install             # system unit `kirocrew` (asks for sudo); rerun after every Kiro Crew update
sudoedit /etc/kirocrew/kirocrew.env  # PATH=<node bin>:~/.local/bin:/usr/local/bin:/usr/bin:/bin
sudo systemctl restart kirocrew
```

**`@qwen` gateway on latte.** OpenCode on the local model, its own home and port:
```bash
ssh latte 'cd ~/lattecrew && gateways/latte/setup-qwen-gateway.sh'
```

**Job notifications.** Copy [`gateways/latte/latte_notify.py`](../gateways/latte/latte_notify.py) to `~/.kiro/crew/crons/` on latte and schedule it as a script cron in the dashboard (every 2 minutes). It posts finished or blocked jobs to your Slack DM.

**Check:** `kirocrew doctor` on each machine; `gateways/latte/qwen-chat.sh "reply with ok"` on latte.

## Phase 4. Slack

1. Create one Slack app per bot from the manifests in [`slack/`](../slack/) (api.slack.com → Create New App → From a manifest). Install each to the workspace.
2. For each Kiro gateway, run `kirocrew setup --slack` (with `KIROCREW_HOME` set for `@qwen`) and paste that app's bot and app-level tokens.
3. Let the bots see each other in the team channel: add the other bots' IDs to `slack.trusted_bot_ids` and set `slack.trusted_bot_turn_limit` to `1` (at the default 5, two bots answer each other's footers). Channel bindings (`slack.channels`) can only be edited in `config.json`.
4. Media bots: fill `~/.config/latte-media/env` on latte (owner user ID and the three bots' tokens), then `media-bot/install.sh`.

**Check:** DM each bot "hi"; in the team channel, mention two bots at once.

## Phase 5. Phone access (optional)

Kiro Crew's phone access publishes the dashboard with Tailscale Serve. If it reports that Serve is not enabled, open the link Tailscale prints and enable Serve for the tailnet once. The phone dashboard shows one session at a time; Slack is the better phone client.

## Phase 6. Measure

See [`bench/README.md`](../bench/README.md). Run the probes after any change to the serving stack, and the collaboration benchmark after any change to roles, models or crewd.
