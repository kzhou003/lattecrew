#!/usr/bin/env python3
"""kprobe.py <label> <out.jsonl>: cold prefill, decode and c=2 numbers for one server config."""
import json, sys, threading, time, urllib.request as u, uuid
B = "http://127.0.0.1:8101"; LABEL, OUT = sys.argv[1], sys.argv[2]
FILL = "".join(f"def f{i}(x):\n    return x * {i} + {i % 7}\n" for i in range(4000))
def stream(prompt, n):
    body = {"model": "qwen3.8", "messages": [{"role": "user", "content": prompt}], "max_tokens": n, "ignore_eos": True, "stream": True,
            "temperature": 0.7, "top_p": 0.8, "top_k": 20, "chat_template_kwargs": {"enable_thinking": False}, "stream_options": {"include_usage": True}}
    t = time.time(); first = None; times = []; usage = {}
    r = u.urlopen(u.Request(B + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}), timeout=600)
    for line in r:
        if not line.startswith(b"data: ") or line.strip() == b"data: [DONE]": continue
        d = json.loads(line[6:])
        if d.get("usage"): usage = d["usage"]
        if d.get("choices") and d["choices"][0]["delta"].get("content"):
            now = time.time(); first = first or now; times.append(now)
    e = time.time()
    return {"ttft_ms": round((first - t) * 1000, 1), "e2e_ms": round((e - t) * 1000, 1),
            "tpot_ms": round((times[-1] - first) * 1000 / max(1, usage.get("completion_tokens", 1) - 1), 2),
            "prompt": usage.get("prompt_tokens"), "out": usage.get("completion_tokens")}
def rec(**k):
    k["label"] = LABEL; open(OUT, "a").write(json.dumps(k) + "\n"); print(k, flush=True)
def prompt(chars):
    return "# " + uuid.uuid4().hex + "\n" + FILL[:chars] + "\nSummarize the file."
stream(prompt(2000), 16)  # warm
for size in (15000, 55000):
    for rep in range(3):
        rec(test="prefill", chars=size, rep=rep, **stream(prompt(size), 1 if False else 2))
for rep in range(3):
    rec(test="decode", rep=rep, **stream(prompt(4000), 512))
res = []
def one(): res.append(stream(prompt(4000), 512))
t = time.time(); th = [threading.Thread(target=one) for _ in range(2)]; [x.start() for x in th]; [x.join() for x in th]
rec(test="c2", wall_ms=round((time.time() - t) * 1000), tok_s=round(sum(r["out"] for r in res) / (time.time() - t), 1), tpot_ms=round(sum(r["tpot_ms"] for r in res) / 2, 2))
