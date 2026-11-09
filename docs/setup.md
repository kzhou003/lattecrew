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
| Qwen3.8-27B AWQ INT4 | `qwen3.8` | 8101 | context 131,072, FP8 KV cache, MTP speculative decoding (3 draft tokens), 2 sequences, prefix caching, tool and reasoning parsers |
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

Defaults, measured in [lattecrew_bench](https://github.com/kzhou003/lattecrew_bench) (E11, E12): 128K context with an FP8 KV cache and MTP speculative decoding. That gives ~150–200K tokens of KV cache, finds a planted fact at 129K tokens, and decodes ~118 tok/s instead of ~78. The FP8 KV path JIT-compiles kernels once and needs a CUDA compiler; without sudo, install one with conda (`conda create -p ~/latte-models/cuda13 -c conda-forge cuda-nvcc=13.0 cuda-version=13.0 cuda-cudart-dev cuda-cccl cuda-nvrtc-dev`, then `ln -s targets/x86_64-linux/lib ~/latte-models/cuda13/lib64`); `serve-qwen.sh` uses it when present. To go back to the old setup: `CTX=65536 KV_DTYPE=auto MTP=0`.

## Phase 2. crewd

```bash
ssh latte 'cd ~/lattecrew && crew/install.sh'
```
Installs to `~/latte-crew/`, links `~/.local/bin/crew`, starts the `crewd` user service. Edit `~/latte-crew/config.json` for budgets, concurrency, timeouts and `repo_roots` (where your repos live).

**Check:** `ssh latte 'crew health && crew task "Say hello in one sentence." --risk low && sleep 60 && crew status'`

## Phase 3. Kiro Crew gateways

Kiro Crew runs one gateway per Slack identity.

**Mac gateway (`@codex` in Slack, plus a `claude` Bot).** The Kiro desktop app owns this gateway.
1. Create the two Bots: `kirocrew agent create --name codex --display-name codex` and `kirocrew agent create --name claude --display-name claude`.
2. Pin each Bot's harness in `~/.kiro/crew/config.json`: `agents.codex.acp_backend = "codex"`, `agents.claude.acp_backend = "claude"` (the CLI has no flag for it).
3. **Set the gateway default to Codex**: `kirocrew config set agent.acp_backend codex`. Kiro applies a Bot's own `acp_backend` only to its dashboard DM and its workers. Slack threads are not tied to a Bot, so they run on the gateway default; without this step `@codex` in Slack is answered by Claude Code.
4. Bind Slack to the codex Bot: in `config.json`, set `slack.channels.<DM id>.agent` and `slack.channels.<channel id>.agent` to `codex` (not settable from the CLI), and `kirocrew config set slack.command codex`.
5. Let both Bots dispatch to latte: `gateways/mac/install.sh`; copy [`gateways/mac/claude-bot-CLAUDE.md`](../gateways/mac/claude-bot-CLAUDE.md) to `~/.kiro/crew/workspace-member-claude/CLAUDE.md` and run `claude mcp add -s local latte-crew ~/.local/bin/latte-crew-mcp` in that directory; copy [`gateways/mac/codex-bot-AGENTS.md`](../gateways/mac/codex-bot-AGENTS.md) to `~/.kiro/crew/workspace-member-codex/AGENTS.md` and run `codex mcp add latte-crew -- ~/.local/bin/latte-crew-mcp`. Bot conductors mount no MCP from `mcp.json`, so the per-harness registration is what reaches them.
6. Media Bots on the Mac (optional): in the Bot's workspace, `claude mcp add -s local latte-media ~/.local/bin/latte-media-mcp image|speech|wan`.
7. Restart: the app-owned gateway refuses `kirocrew restart`; use the app (Settings → About → Restart gateway) or `curl -X POST "http://127.0.0.1:5476/api/restart?token=$(kirocrew token | head -1 | sed 's/.*token=//')"`.

**Check:** DM `@codex` in Slack, then confirm the session ran on Codex: the newest `~/.kiro/crew/usage/tokens/<date>.jsonl` row for that thread has `"provider": "codex"`.

**latte gateway (`@claude` on the GPU machine).** A system service, slash command `/claude` (`kirocrew config set slack.command claude`):
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

## Phase 6. Claude Code and OpenCode on the local model

vLLM serves both the OpenAI API (`/v1/chat/completions`) and the Anthropic Messages API (`/v1/messages`, with `thinking` blocks), and llama-swap routes both. So both CLIs can run on Qwen, on the GPU machine (127.0.0.1:8100) and on the Mac (127.0.0.1:18100 through the tunnel LaunchAgent).

```bash
install -m 755 models/bin/claude-qwen models/bin/opencode-qwen ~/.local/bin/   # on each machine
claude-qwen                      # Claude Code UI, tools, skills; the model is Qwen3.8 on the 5090
claude-qwen -p "explain this repo"
opencode-qwen                    # OpenCode with latte/qwen3.8
opencode-qwen run "fix the failing test"
```

What `claude-qwen` sets, and why:

| Setting | Value | Why |
|---|---|---|
| `ANTHROPIC_BASE_URL` | first of :8100 / :18100 that answers | same script on both machines |
| `ANTHROPIC_AUTH_TOKEN` | `local` | vLLM ignores it; it also keeps your Claude subscription out of this process |
| `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL` | `qwen3.8` | every model alias, including subagents, goes to Qwen |
| `CLAUDE_CODE_EFFORT_LEVEL` | `medium` (`QWEN_EFFORT`) | Claude Code's default `high` is rejected: Qwen's chat template accepts only `xhigh`, `medium`, `low` |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | 131072 | the served context; Claude Code otherwise assumes 200K for an unknown model and compacts too late |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | 8192 | a smaller output reserve leaves more room; Claude Code's own prompt is ~11K, so ~100K is left for work |

Measured: a one-tool question takes 4–8 s in either CLI. With 128K, `claude-qwen -p` finished benchmark task t4 on its own in 84 s (24 turns, wrote 21 tests, hidden tests 17/17). At 65K the same kind of session thrashed on compaction (7 compactions, ~15 minutes), so do not run Claude Code on less than ~100K. Claude.ai connectors are off in a `claude-qwen` session (expected: another auth source is set).

**Check:** `claude-qwen -p "What is 17*23?"` and `opencode-qwen run "What is 17*23?"` both print 391 on both machines.

## Phase 7. Measure

See [`bench/README.md`](../bench/README.md). Run the probes after any change to the serving stack, and the collaboration benchmark after any change to roles, models or crewd.
