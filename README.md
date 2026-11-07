# LatteCrew

A small AI team built from a MacBook, one RTX 5090 workstation and Slack.

- **Cloud agents** (Claude Code, Codex) plan, review and handle hard work.
- **A local coder** (Qwen3.8-27B, 4-bit, served by vLLM on the 5090) writes code without using cloud quota.
- **Local media models** (Z-Image-Turbo, Qwen3-TTS, Wan2.2) make images, speech and video on the same GPU.
- **Slack** is the front door: each bot has its own identity (`@claude`, `@codex`, `@qwen`, `@z-image`, `@qwen-tts`, `@wan`), and a shared channel holds the whole team.
- **`crewd`** runs long jobs on the GPU machine in isolated git worktrees, with budgets, a GPU lock, and a human merge gate.

This repo holds the ready-to-use scripts, service files and configs that set it up, plus the benchmark used to measure and tune it.

```
Phone / Slack / terminal
        │
        ▼
Kiro Crew gateways ── Mac: @claude, @codex        latte: @claude, @qwen
        │
        ▼
Agent harness ─────── Claude Code · OpenCode · Codex CLI
        │  MCP over SSH (Tailscale)
        ▼
crewd (latte) ─────── job queue · git worktrees · GPU lock · ledger · Landlock sandbox
        │
        ▼
llama-swap :8100 ──── one model on the GPU at a time
        │
        ▼
vLLM :8101 Qwen3.8-27B │ vLLM-Omni :8102 Z-Image │ :8103 Qwen3-TTS │ :8104 Wan2.2
        │
        ▼
RTX 5090 32 GB
```

## Layout

| Directory | What it is | Runs on |
|---|---|---|
| [`crew/`](crew/) | `crewd`: job runner, CLI and MCP server in one stdlib Python file, role prompts, config | GPU machine |
| [`models/`](models/) | vLLM / vLLM-Omni install, one serve script per model, llama-swap config and service | GPU machine |
| [`media-bot/`](media-bot/) | Slack bots for image, speech and video, no LLM in the loop | GPU machine |
| [`gateways/`](gateways/) | Kiro Crew setup: the `@qwen` gateway on latte; MCP bridges, bot instructions and the model tunnel on the Mac | both |
| [`slack/`](slack/) | Slack app manifests, one per bot | Slack |
| [`skill/`](skill/) | Claude Code skill for dispatching work to latte | Mac |
| [`bench/`](bench/) | probes for every layer, the collaboration benchmark, report generators | both |
| [`tests/`](tests/) | 49 tests for crewd and the media bots, with fake `claude` and `opencode` binaries | GPU machine (Linux) |
| [`docs/`](docs/) | [setup runbook](docs/setup.md), [architecture](docs/architecture.md), [security](docs/security.md), [troubleshooting](docs/troubleshooting.md) | |

## Quick start

Assumptions: a Linux machine with an NVIDIA GPU (32 GB) reachable from the Mac as `ssh latte` (key auth, Tailscale or LAN), Python 3.12 on both, Node 22 on latte, Claude Code logged in on both machines, and [Kiro Crew](https://github.com/kirodotdev/KiroCrew) installed.

```bash
git clone https://github.com/kzhou003/LatteCrew.git && cd LatteCrew
rsync -a --exclude bench/out ./ latte:LatteCrew/      # copy to the GPU machine

# GPU machine
ssh latte 'cd LatteCrew && models/install.sh'          # vLLM env, weights, llama-swap service
ssh latte 'cd LatteCrew && crew/install.sh'            # crewd service, `crew` CLI
ssh latte 'cd LatteCrew && python3 -m unittest discover -s tests'

# Mac
gateways/mac/install.sh                                # MCP bridges, OpenCode config, tunnel plist
```

Then follow [docs/setup.md](docs/setup.md) for the Kiro Crew gateways, Slack apps and media bots. Each step there has the exact commands and a check.

## Using it

From Slack or Claude Code on the Mac:

- "@claude fix the flaky test in repo X on latte" → `crew_task`: one Claude Code instance on latte.
- "@claude build feature Y as a team" → `crew_team`: planner, coders, reviewer, QA.
- "@qwen add a --json flag to the CLI" → `crew_local`: Qwen writes, Claude reviews read-only, up to two rounds.
- "@z-image a lighthouse at golden hour", "@qwen-tts read this aloud", "@wan a cat walking on a windowsill".

On latte: `crew status`, `crew logs <job>`, `crew diff <job>`, `crew reply <job> "..."`. Results stay on local branches `crew/<job>`; nothing is pushed or merged by an agent.

## What we measured

`bench/` reproduces the study behind the blog post *LatteCrew: 优化与分析*. Highlights: the local coder spends 96% of its time decoding and 80% of what it decodes is reasoning; MTP speculative decoding raises coding throughput 1.5–2×; a per-session path inside a tool description silently disabled prefix caching for the Kiro gateway (20.7 s → 10.8 s per turn once fixed). See [`bench/README.md`](bench/README.md).

## License

MIT. Model weights, Kiro Crew, Claude Code, Codex and OpenCode have their own licenses and terms.
