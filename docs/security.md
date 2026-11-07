# Security model

Agents run as your user on the GPU machine. What keeps them in bounds:

| Guard | Applies to | Mechanism |
|---|---|---|
| Worktree per job | all jobs | `git worktree`, branch `crew/<id>`; agents never push or merge |
| Push wall | all jobs | `PUSH_WALL` env sets an unreachable push URL; tests check every remote |
| Claude permissions | Claude jobs | `disallowed_tools` in `config.json`: no push, sudo, ssh, scp, systemctl; no reads of `~/.ssh`, `~/.aws`, Claude credentials |
| Landlock | Qwen jobs | `crew.py _sandbox` limits writes to the worktree, the repo's git dir and temp |
| OpenCode permissions | Qwen jobs | per-process `OPENCODE_CONFIG_CONTENT` denies push, ssh, curl, external directories |
| Foreign-ref check | Qwen jobs | a job fails if it moved any branch but its own |
| Budgets and timeouts | all jobs | per job, per day, per risk level |
| Human gates | team (high risk), local after 2 rounds | `need_human`; only you answer |
| AppArmor | latte Kiro gateway | `kirocrew-userns` profile |

## Known gaps

1. **Reads are not confined for Qwen jobs**, and `~/.kiro` (Slack tokens) and `~/.config` are not on Claude's deny list.
2. **Network is not confined for Qwen jobs**: OpenCode rules match command names, so `python3 -c "urllib..."` gets out.

Together they allow prompt injection → read a token → send it out. Planned fixes, in order: Landlock read rules and a TCP rule allowing only `127.0.0.1:8100` for Qwen jobs (no sudo needed, kernel ABI ≥ 4); add `~/.kiro/**` and `~/.config/**` to Claude's deny list; run jobs as a separate Unix user.

Never commit `crew/config.json`, `~/.config/latte-media/env` or Kiro's `config.json`; they hold budgets and tokens.
