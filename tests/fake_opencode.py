#!/usr/bin/env python3
"""Stand-in for `opencode run --format json`. Behaviour comes from the prompt."""
import json, os, re, subprocess, sys, time
from pathlib import Path

args = sys.argv[1:]
prompt = args[-1]
trace = Path(os.environ["FAKE_TRACE"])
fifo_ok = not sys.stdin.isatty() and sys.stdin.read(1) == ""  # stdin must be closed, or this blocks
active = trace / "oc-active"
peak = 2 if active.exists() else 1
active.touch()
with open(trace / "oc.jsonl", "a") as f:
    f.write(json.dumps({"args": args, "prompt": prompt, "cwd": os.getcwd(), "stdin_closed": fifo_ok, "peak": peak,
                        "wall": os.environ.get("GIT_CONFIG_KEY_0", ""), "perms": os.environ.get("OPENCODE_CONFIG_CONTENT", ""), "pwd": os.environ.get("PWD", ""),
                        "real_cwd": os.getcwd()}) + "\n")


def emit(kind, **kw):
    print(json.dumps({"type": kind, "sessionID": "ses_fake", **kw}), flush=True)


def finish(text):
    active.unlink()
    emit("text", part={"text": text})
    emit("step_finish", part={"tokens": {"total": 1000}})
    sys.exit()


if "SLOWOC" in prompt:
    time.sleep(1)
if "ESCAPE" in prompt:
    # What the real incident did: reach the main checkout and commit there.
    repo = re.search(r"REPO=(\S+)", prompt).group(1)
    out = []
    out.append(subprocess.run(f"git -C {repo} commit --allow-empty -qm escaped", shell=True, capture_output=True, text=True).returncode)
    try:
        Path(repo, "escaped.txt").write_text("x")
        out.append(0)
    except OSError:
        out.append(1)
    try:
        (Path.home() / ".crew-escape-probe").write_text("x")
        out.append(0)
    except OSError:
        out.append(1)
    (trace / "escape.json").write_text(json.dumps(out))
if "OCSILENT" in prompt and "Guidance" not in prompt:
    active.unlink()
    emit("step_finish", part={"reason": "length", "tokens": {"total": 50000}})
    sys.exit()
if "OCFAIL" in prompt:
    active.unlink()
    emit("error", error={"name": "boom"})
    sys.exit(1)
if "OCASK" in prompt and "Guidance" not in prompt:
    finish("stuck\nNEED_HUMAN: which api?")
if "ANALYSIS" in prompt:
    finish("just an answer, no code")
n = sum(1 for _ in open(trace / "oc.jsonl"))
Path(f"qwen{n}.txt").write_text("x")  # left uncommitted on purpose
finish("wrote it")
