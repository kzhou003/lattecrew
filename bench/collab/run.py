#!/usr/bin/env python3
"""Run the collaboration experiment from the Mac. Hidden tests stay here until every job has finished.

run.py <arm> [task ...]    arm: claude | local | codex
"""
import json, os, re, shlex, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results.jsonl")
TRIAL = int(os.environ.get("TRIAL", "1"))
TASKS = json.load(open(os.path.join(HERE, "tasks.json")))
CREW = "python3 ~/latte-crew/crew.py"
def ssh(cmd, **k):
    return subprocess.run(["/usr/bin/ssh", "-o", "BatchMode=yes", "latte", cmd], capture_output=True, text=True, **k)
def rec(**k):
    with open(OUT, "a") as f: f.write(json.dumps(k, ensure_ascii=False) + "\n")
def plan(task):
    """Codex plans from a read-only copy of the repo. Returns the plan and its usage."""
    prompt = ("You are the planner for a less capable coder who will not see this conversation. Read the repo, then write an "
              "implementation plan for the task below: the data structures, the algorithm step by step, every edge case and trap, "
              "and the tests to add. Do not write the final code. Be concise.\n\nTask:\n" + task)
    t = time.time()
    r = subprocess.run(["codex", "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check", "-C", os.path.join(HERE, "repo"), prompt],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600)
    text, usage = "", {}
    for line in r.stdout.splitlines():
        try: d = json.loads(line)
        except json.JSONDecodeError: continue
        item = d.get("item") or {}
        if item.get("type") in ("agent_message", "assistant_message") and item.get("text"):
            text = item["text"]
        if d.get("usage"):
            usage = d["usage"]
    return text, usage, time.time() - t, r.stderr[-300:] if not text else ""
def wait(jid):
    while True:
        d = json.loads(ssh(f"{CREW} status {jid}").stdout)
        if d["state"] not in ("queued", "running"):
            return d
        time.sleep(10)
def run(arm, tid):
    task = TASKS[tid]; prompt = task["prompt"]; meta = {}
    if arm == "codex":
        old = [json.loads(x) for x in open(OUT)] if os.path.exists(OUT) else []
        saved = [r for r in old if r["arm"] == "codex" and r["task"] == tid and r.get("plan")]
        if saved:  # reuse the plan so the coder side is the only thing that changes between trials
            r0 = saved[0]; text, usage, secs, err = r0["plan"], r0["plan_usage"], r0["plan_secs"], ""
        else:
            text, usage, secs, err = plan(prompt)
        if not text:
            print("plan failed", err); rec(arm=arm, task=tid, error=err); return
        meta = {"plan_usage": usage, "plan_secs": round(secs, 1), "plan_chars": len(text), "plan": text}
        prompt += "\n\nImplementation plan from the senior planner. Follow it unless the code proves it wrong:\n" + text
    if arm == "claude":
        cmd = f"{CREW} task {shlex.quote(prompt)} --repo ledgerkit --risk low --model sonnet --title {shlex.quote(arm + ' ' + tid)}"
    else:
        cmd = f"{CREW} local {shlex.quote(prompt)} --repo ledgerkit --risk low --title {shlex.quote(arm + ' ' + tid)}"
    t = time.time(); out = ssh(cmd); jid = json.loads(out.stdout)["id"]
    print(arm, tid, jid, flush=True)
    d = wait(jid)
    rec(arm=arm, trial=TRIAL, task=tid, level=task["level"], job=jid, state=d["state"], verdict=d.get("verdict"), round=d["round"], wall=round(time.time() - t, 1), cost=d["cost_usd"], error=d.get("error"), **meta)
    print(" ->", d["state"], d.get("verdict"), "round", d["round"], round(time.time() - t), "s", flush=True)
arm = sys.argv[1]
for tid in sys.argv[2:] or list(TASKS):
    run(arm, tid)
