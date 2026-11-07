#!/usr/bin/env python3
"""Stand-in for `claude -p`. Behaviour comes from the prompt text and the role in --name."""
import json, os, re, subprocess, sys, time, uuid
from pathlib import Path

args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "subscriptionType": "pro"})); sys.exit()
name = args[args.index("--name") + 1]
role = name.split()[-1]
prompt = sys.stdin.read()
trace = Path(os.environ["FAKE_TRACE"])
tag = uuid.uuid4().hex
(trace / "running").mkdir(parents=True, exist_ok=True)
(trace / "running" / tag).touch()
peak = len(list((trace / "running").iterdir()))
with open(trace / "calls.jsonl", "a") as f:
    f.write(json.dumps({"role": role, "args": args, "prompt": prompt, "peak": peak,
                        "start": time.time(), "cwd": os.getcwd()}) + "\n")


def done(text, **kw):
    (trace / "running" / tag).unlink()
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}))
    print(json.dumps({"type": "result", "result": text, "is_error": False, "total_cost_usd": 0.5,
                      "num_turns": 2, **kw}))
    sys.exit()


def commit(fn, body):
    Path(fn).write_text(body)
    subprocess.run(f"git add -A && git commit -qm {fn}", shell=True, check=True)


if "SLEEP" in prompt:
    time.sleep(float(re.search(r"SLEEP(\d+)", prompt).group(1)) / 10)
if "FREEZE" in prompt:
    time.sleep(600)
marker = trace / "limited"
if "LIMITONCE" in prompt and not marker.exists():
    marker.touch()
    done("You've hit your usage limit, resets at 3pm", is_error=True, num_turns=0)
if "CRASHONCE" in prompt and not marker.exists():
    marker.touch()
    done("internal boom", is_error=True, num_turns=1)
if "ASKME" in prompt and "--resume" not in args:
    done("I am stuck.\nNEED_HUMAN: which database?")

if role == "worker":
    commit("worker.txt", "ok")
    done(f"worker done: {prompt[:60]}")
if role == "planner":
    if "ASKPLAN" in prompt and "Guidance" not in prompt:
        done("NEED_HUMAN: which api?")
    n = 3 if "SLICE3" in prompt else 2 if "SLICE2" in prompt or "CONFLICT" in prompt else 1
    body = json.dumps({"slices": [{"title": f"s{i}", "instructions": f"do s{i}"} for i in range(n)]})
    done(f"spec\n```json\n{body}\n```")
if role == "coder":
    if "merge of slice" in prompt:
        if "BADMERGE" in open(trace / "calls.jsonl").readline():
            done("gave up")
        subprocess.run("printf merged > same.txt; git add -A; git commit -qm resolved", shell=True, check=True)
        done("resolved")
    index = re.search(r"Your slice only: s(\d)", prompt)
    if "CONFLICT" in prompt and index:
        commit("same.txt", f"v{index.group(1)}")
    elif index:
        time.sleep(0.5)
        commit(f"slice{index.group(1)}.txt", "x")
    else:
        Path(f"impl-{uuid.uuid4().hex[:6]}.txt").write_text("x")  # left uncommitted on purpose
    done("coded")
if role in ("reviewer", "griller"):
    time.sleep(0.5)
    coders = sum(json.loads(x)["role"] == "coder" for x in open(trace / "calls.jsonl"))
    if "ALWAYSBAD" in prompt or ("BADFIRST" in prompt and coders < 2):
        done("problem at x.py:1\nVERDICT: CHANGES")
    done("VERDICT: PASS")
if role == "local_reviewer":
    runs = sum(1 for _ in open(trace / "oc.jsonl"))
    if "ALWAYSBAD" in prompt or ("BADFIRST" in prompt and runs < 2):
        done("bug at x.py:1\nVERDICT: CHANGES")
    done("looks right\nVERDICT: PASS")
if role == "qa":
    done("all checked\nVERDICT: READY")
