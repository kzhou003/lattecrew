#!/usr/bin/env python3
"""Harness overhead on latte: Claude Code, OpenCode and a Kiro Crew gateway turn. Same trivial prompt each."""
import json, os, subprocess, sys, time
OUT = os.path.expanduser("~/latte-bench/out/harness.jsonl")
H = os.path.expanduser("~")
ENV = {**os.environ, "PATH": os.environ.get("NODE_BIN", "") + f":{H}/.local/bin:" + os.environ["PATH"]}
os.chdir("/tmp")
def rec(**k):
    open(OUT, "a").write(json.dumps(k, ensure_ascii=False) + "\n")
    print({a: (round(b, 1) if isinstance(b, float) else b) for a, b in k.items()}, flush=True)
for i in range(4):
    t = time.perf_counter()
    r = subprocess.run(["claude", "-p", "--output-format", "json", "--model", "haiku", "reply with exactly: ok"], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=ENV)
    wall = (time.perf_counter() - t) * 1e3
    try:
        d = json.loads(r.stdout); u = d.get("usage") or {}
        rec(probe="claude", wall_ms=wall, api_ms=float(d.get("duration_api_ms") or 0), cost=d.get("total_cost_usd"), input=u.get("input_tokens"), cache_write=u.get("cache_creation_input_tokens"), cache_read=u.get("cache_read_input_tokens"), output=u.get("output_tokens"))
    except Exception as e:
        rec(probe="claude", wall_ms=wall, err=(r.stdout or r.stderr)[:160])
for i in range(4):
    t = time.perf_counter()
    r = subprocess.run(["opencode", "run", "--auto", "--format", "json", "-m", "latte/qwen3.8", "reply with exactly: ok"], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=ENV)
    wall = (time.perf_counter() - t) * 1e3
    tok = {}; steps = 0
    for l in r.stdout.splitlines():
        try: d = json.loads(l)
        except Exception: continue
        if d.get("type") == "step_finish":
            steps += 1; tok = d["part"].get("tokens") or tok
    rec(probe="opencode", wall_ms=wall, steps=steps, tokens=tok)
