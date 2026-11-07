# crewd

One stdlib-only Python file (`crew.py`) that is four things:

| Command | Role |
|---|---|
| `crew.py daemon` | the `crewd` service: starts runnable jobs within the instance and budget limits |
| `crew.py _run <job>` | runs one job through its stages (started by the daemon) |
| `crew.py mcp` | MCP server over stdio; the Mac reaches it with `ssh latte crew.py mcp` |
| `crew.py task/team/local/status/logs/diff/reply/cancel/events/repos/health/clean` | CLI, same functions as the MCP tools |

## Install

```bash
./install.sh        # copies to ~/latte-crew, links ~/.local/bin/crew, starts the crewd user service
```

## Use

```bash
crew task  "Fix the off-by-one in pager.py and add a test" --repo myrepo --risk low
crew team  "Add OAuth login" --repo webapp --risk high          # stops for SPEC approval
crew local "Add a --json flag to the CLI" --repo tools           # Qwen writes, Claude reviews
crew status [job]   crew logs <job> [name]   crew diff <job>
crew reply <job> "use the v2 API"     crew reply <job> claude    # hand a local job to Claude
crew cancel <job>   crew events --since 0   crew health   crew clean --days 7
```

## Files

| File | Purpose |
|---|---|
| `config.example.json` | budgets, concurrency, timeouts per risk, `repo_roots`, Claude deny rules, local model names |
| `opencode-permissions.json` | per-process OpenCode permissions and the 32K output limit for crew jobs |
| `roles/*.md` | role prompts: worker, planner, coder, reviewer, griller, qa, local_coder, local_reviewer |
| `systemd/crewd.service` | user unit |

Environment overrides: `CREW_VAR`, `CREW_CONFIG`, `CREW_CLAUDE`, `CREW_OPENCODE`, `CREW_NODE_BIN`, `CREW_GPU_LOCK`.

## Tests

`python3 -m unittest discover -s tests` from the repo root, on Linux (Landlock). They use fake `claude` and `opencode` binaries from `tests/`, so they cost nothing and need no GPU.
