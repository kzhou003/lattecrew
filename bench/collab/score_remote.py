#!/usr/bin/env python3
"""Runs on latte. Scores commits with hidden tests in a temp dir, and extracts token usage from job logs."""
import json, os, re, shutil, subprocess, sys, tempfile
H = os.path.expanduser("~"); JOBS = f"{H}/latte-crew/var/jobs"; REPO = f"{H}/development/ledgerkit"; HIDDEN = sys.argv[1]
def score(sha, task, extra=False):
    d = tempfile.mkdtemp(prefix="score-")
    try:
        subprocess.run(f"git -C {REPO} archive {sha} | tar -x -C {d}", shell=True, check=True)
        name = f"test_extra_{task}.py" if extra else f"test_{task}.py"
        if not os.path.exists(f"{HIDDEN}/{name}"): return None
        shutil.copy(f"{HIDDEN}/{name}", f"{d}/test_hidden_{task}.py")
        r = subprocess.run(["timeout", "180", "python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", f"test_hidden_{task}.py"], cwd=d, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": d})
        last = (r.stdout.strip().splitlines() or [""])[-1]
        p = int((re.search(r"(\d+) passed", last) or [0, 0])[1]); f = int((re.search(r"(\d+) failed", last) or [0, 0])[1]); e = int((re.search(r"(\d+) error", last) or [0, 0])[1])
        return {"passed": p, "failed": f, "errors": e, "total": p + f + e, "line": last[-90:]}
    finally:
        shutil.rmtree(d, ignore_errors=True)
def claude_usage(path):
    u = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0, "cost": 0.0, "api_ms": 0, "turns": 0}
    for l in open(path):
        try: d = json.loads(l)
        except Exception: continue
        if d.get("type") == "result":
            x = d.get("usage") or {}
            u["input"] += x.get("input_tokens") or 0; u["cache_write"] += x.get("cache_creation_input_tokens") or 0
            u["cache_read"] += x.get("cache_read_input_tokens") or 0; u["output"] += x.get("output_tokens") or 0
            u["cost"] += d.get("total_cost_usd") or 0; u["api_ms"] += d.get("duration_api_ms") or 0; u["turns"] += d.get("num_turns") or 0
    return u
def qwen_usage(path):
    u = {"steps": 0, "tools": 0, "input": 0, "output": 0, "reasoning": 0, "max_input": 0}
    for l in open(path):
        try: d = json.loads(l)
        except Exception: continue
        if d.get("type") == "step_finish":
            t = d["part"].get("tokens") or {}; u["steps"] += 1
            u["input"] += t.get("input") or 0; u["output"] += t.get("output") or 0; u["reasoning"] += t.get("reasoning") or 0
            u["max_input"] = max(u["max_input"], t.get("input") or 0)
        if d.get("type") == "tool_use": u["tools"] += 1
    return u
out = []
for jid in sys.argv[2:]:
    j = json.load(open(f"{JOBS}/{jid}/job.json")); task = j["title"].split()[-1]; arm = j["title"].split()[0]
    w = j["worktree"]; row = {"job": jid, "arm": arm, "task": task, "kind": j["kind"], "state": j["state"], "verdict": j.get("verdict"), "rounds": j["round"]}
    head = subprocess.run(["git", "-C", REPO, "rev-parse", j["branch"]], capture_output=True, text=True).stdout.strip()
    row["final"] = score(head, task) if head and head != j["base"] else {"passed": 0, "failed": 0, "errors": 0, "total": 0, "line": "no commit"}
    row["extra"] = score(head, task, True) if head and head != j["base"] else None
    heads = j.get("round_heads") or []
    if heads:
        row["round1"] = score(heads[0], task)
    logs = sorted(os.listdir(f"{JOBS}/{jid}"))
    row["claude"] = [dict(file=f, **claude_usage(f"{JOBS}/{jid}/{f}")) for f in logs if f.endswith(".log") and not f.startswith("qwen")]
    row["qwen"] = [dict(file=f, **qwen_usage(f"{JOBS}/{jid}/{f}")) for f in logs if f.startswith("qwen") and f.endswith(".log")]
    ledger = [json.loads(x) for x in open(f"{H}/latte-crew/var/ledger.jsonl") if json.loads(x)["job"] == jid]
    row["secs"] = {r["tag"]: r.get("seconds") for r in ledger}
    out.append(row); print(json.dumps({k: row[k] for k in ("job", "arm", "task", "state")}), row["final"]["line"], (row.get("round1") or {}).get("line"), flush=True)
json.dump(out, open("/tmp/scored.json", "w"))
