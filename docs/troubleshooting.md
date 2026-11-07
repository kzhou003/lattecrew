# Troubleshooting and lessons

| Symptom | Cause | Fix |
|---|---|---|
| `opencode run` hangs forever | it waits on stdin | always run it with stdin closed (`< /dev/null`); crewd does |
| A Qwen job committed to `main` | OpenCode used `$PWD`, not the worktree | set `PWD` and pass `--dir`; Landlock and the foreign-ref check now block it |
| Qwen job "finished" with no output | reasoning used the whole output limit (`finish_reason: length`) | crewd fails such jobs; give crew jobs `output: 32768` via `opencode-permissions.json` |
| `@qwen` gateway loops on "compacting" | global OpenCode output limit raised: 65,536 − 32,768 < Kiro's 47K prompt | keep the global limit at 8,192; raise it only per process for crewd |
| `@qwen` slow (~20 s per reply), 0 cache hits | OpenCode's `bash` tool description contains a per-session path at token 184; hybrid models only reuse checkpointed prefixes | move volatile tools last (tested with `bench/capture_proxy.py REORDER=1`), or mount fewer MCP tools on that Bot |
| Qwen fails to start: not enough free memory | a desktop browser holds ~2 GB VRAM | `serve-qwen.sh` sizes `--gpu-memory-utilization` from free memory |
| A Slack bot crash-loops | one bot's token was revoked | media-bot connects each bot separately and skips bots without tokens |
| Two bots reply to each other forever | they treat each other's footers as messages | `slack.trusted_bot_turn_limit = 1` |
| A Bot ignores the crew tools | Bot conductors mount no user MCP | `claude mcp add -s local` in the Bot workspace plus its `CLAUDE.md` |
| `kirocrew config set slack.channels` refused | not settable from the CLI | edit `config.json` |
| FlashInfer JIT link error `cannot find -lcudart` | conda puts CUDA libs in `targets/x86_64-linux/lib` | `ln -s targets/x86_64-linux/lib lib64` in the toolkit dir (it gave no speed-up anyway) |
| `pkill -f pattern` over ssh kills your own ssh | the remote command line contains the pattern | put the kill in a script file and run that |
| Deleting a model directory frees no disk | HF cache keeps weights in `hub/blobs/` | remove the unreferenced blobs too |
