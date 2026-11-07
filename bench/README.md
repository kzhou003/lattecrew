# Benchmarks

The measurement study behind *LatteCrew: 优化与分析*. Every probe writes JSON lines to `bench/out/`; `report/gen.py` builds the HTML report from those files only, and `report/gen_methods.py` builds the methods page that quotes the code below.

| Probe | Runs on | Measures |
|---|---|---|
| `stack_probe.py <out.jsonl>` | Mac | SSH new vs. reused connection, MCP call in a new / reused / live session, scp 1 MB |
| `harness_probe.py` | latte | one-word turns through Claude Code and OpenCode: wall time, API time, tokens |
| `capture_proxy.py <out.jsonl>` | latte | logging reverse proxy on :8110 in front of llama-swap; `REORDER=1` moves tools with per-session text to the end |
| `llm_probe.py <url> <out> grid\|paths\|conc [--metrics url]` | latte / Mac | streaming TTFT, TPOT, cache hits vs. prompt length; three network paths; concurrency 1–4 |
| `kprobe.py`, `run_kernel.sh` | latte | kernel configs (FlashInfer sampler / attention) and a torch-profiler capture |
| `kprobe2.py`, `run_spec.sh` | latte | MTP speculative decoding k = 1..3 on a real coding answer, with acceptance counters |
| `media_probe.py` + `gpu_fast.sh` | latte | Z-Image steps and sizes, TTS real-time factor, Wan frames and steps, swap cost, 4 Hz GPU trace |

Rules all probes follow: one layer at a time; fixed input, medians over 4–30 repeats; client timing cross-checked with vLLM `/metrics` deltas; a random uuid prefix forces a cold cache; `ignore_eos` fixes output length; GPU-changing runs hold `~/latte-models/gpu.lock`.

## Collaboration benchmark (`collab/`)

Six tasks on a small library (`collab/repo`, reference solutions in `collab/ref`), three arms:

```bash
cd collab
python3 run.py claude          # crew task --model sonnet
python3 run.py local           # crew local: Qwen writes, Claude reviews
python3 run.py codex           # codex exec read-only plan, then crew local
./score.sh                     # hidden tests copied to latte only for scoring, then deleted
```

**Hidden tests are not in this repo** (175 cases in `collab/hidden/test_t1..t6.py`), so agents working in a clone cannot see them. Write your own for each task in `tasks.json`, check them against `ref/`, and keep them outside the GPU machine. `score_remote.py` also runs optional extra edge tests from `collab/extra/`.

## Report

```bash
python3 report/gen.py              # report/lattecrew-report.html
python3 report/gen_methods.py      # report/lattecrew-methods.html (+ standalone)
```
