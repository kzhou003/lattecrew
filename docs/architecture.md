# Architecture

## Layers

| Layer | Component | Where | Measured cost |
|---|---|---|---|
| Front door | Slack apps, one per bot; phone or terminal | Slack | – |
| Gateway | Kiro Crew: one gateway per Slack identity; Bots are source-defined conductors | Mac (`@codex` in Slack, plus a `claude` Bot in the dashboard), latte (`@claude`, `@qwen`) | `@qwen` turn 20.7 s → 10.8 s after the prefix fix |
| Harness | Claude Code, OpenCode, Codex CLI | both | Claude Code ~3 s start-up per call; OpenCode ~2 s |
| Transport | MCP over SSH on Tailscale | Mac → latte | new MCP session 459 ms, live session 10 ms |
| Jobs | `crewd`: queue, worktrees, budgets, GPU lock, ledger, Landlock | latte | tools 0.8% of a local job |
| Model router | llama-swap: one model on the GPU at a time | latte :8100 | +1.4 ms per request; 35–66 s per swap |
| Serving | vLLM (Qwen), vLLM-Omni (image, speech, video) | latte :8101–8104 | prefill ~3,500 tok/s cold; decode 13 ms/token |
| GPU | RTX 5090 32 GB, 575 W | latte | decode at ~84% of memory bandwidth |

## Job kinds in crewd

- **task**: one Claude Code instance does the work in a worktree.
- **team**: plan → gate (high risk waits for your approval) → code (up to 3 slices in parallel, then integrate) → review → QA, at most 2 rounds.
- **local**: Qwen writes through OpenCode → Claude reviews read-only, seeing the task and the diff but not the author's claims → on CHANGES the findings go back to the same OpenCode session → after 2 rounds the job asks you; reply `claude` to hand it to Claude.

Every job lives in `~/latte-crew/var/jobs/<id>/` (state, logs, plans, reviews); spending goes to `var/ledger.jsonl`. Results stay on `crew/<id>` branches until you merge.

## One GPU, many models

`llama-swap` starts the requested model and stops the others. `crewd` and `media-bot` take an `flock` on `~/latte-models/gpu.lock` around GPU work so a video request cannot evict Qwen in the middle of a job. Media models unload after 5 idle minutes (`ttl: 300`).

## Who sees what

| From → to | Content |
|---|---|
| You → gateway | your message |
| Gateway → crewd (MCP) | task prompt, repo, risk, title |
| crewd → Qwen | role prompt, worktree path, task (+ plan) |
| Qwen → crewd | commit, self-report (not shown to the reviewer) |
| crewd → reviewer | task + `git diff base...HEAD`; read-only |
| reviewer → crewd | findings with file:line and a failing scenario, `VERDICT: PASS/CHANGES` |
| crewd → you (Slack cron) | state changes, questions, final summary |
