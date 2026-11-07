#!/usr/bin/env python3
"""Streaming LLM probe: TTFT, TPOT and server-side histograms. Stdlib only.

llm_probe.py <base_url> <out.jsonl> grid|paths|conc [--metrics url]
"""
import json, re, statistics, sys, threading, time, urllib.request as u, uuid
BASE, OUT, MODE = sys.argv[1:4]
METRICS = sys.argv[sys.argv.index("--metrics") + 1] if "--metrics" in sys.argv else None
MODEL = "qwen3.8"
LINE = "def helper_{i}(value, scale={s}):\n    return (value * scale + {i}) % 97  # keeps the table stable\n"

def text(tokens, tag):
    # About 34 tokens a block. tag makes the prefix unique so the cache cannot help.
    n = max(tokens // 34, 1)
    return f"# run {tag}\n" + "".join(LINE.format(i=i, s=i % 13 + 1) for i in range(n))

def stream(prompt, max_tokens=256, thinking=False):
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": 0, "ignore_eos": True, "stream": True, "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": thinking}}
    req = u.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.perf_counter(); first = None; last = None; usage = {}; gaps = []
    with u.urlopen(req, timeout=600) as r:
        for raw in r:
            if not raw.startswith(b"data: ") or raw.startswith(b"data: [DONE]"):
                continue
            d = json.loads(raw[6:])
            if d.get("usage"):
                usage = d["usage"]
            c = d.get("choices") or []
            delta = (c[0].get("delta") or {}) if c else {}
            if delta.get("content") or delta.get("reasoning") or delta.get("reasoning_content"):
                now = time.perf_counter()
                if first is None:
                    first = now
                else:
                    gaps.append(now - last)
                last = now
    n = usage.get("completion_tokens") or 0
    return {"ttft_ms": (first - t0) * 1e3, "e2e_ms": (last - t0) * 1e3,
            "tpot_ms": (last - first) * 1e3 / max(n - 1, 1), "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": n, "cached": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            "gap_p99_ms": sorted(gaps)[int(len(gaps) * .99)] * 1e3 if gaps else None}

def scrape():
    if not METRICS:
        return {}
    out = {}
    for line in u.urlopen(METRICS, timeout=5).read().decode().splitlines():
        m = re.match(r"(vllm:[a-z_0-9]+)(?:_total)?(\{[^}]*\})? ([0-9.e+-]+)$", line)
        if m and not m.group(1).endswith("_bucket"):
            out[m.group(1)] = out.get(m.group(1), 0) + float(m.group(3))
    return out

def record(row):
    with open(OUT, "a") as f:
        f.write(json.dumps(row) + "\n")

def run(label, **meta):
    before = scrape(); r = stream(meta.pop("prompt"), **meta.pop("kw", {})); after = scrape()
    r.update(label=label, **meta)
    r["srv"] = {k.replace("vllm:", ""): round(after[k] - before.get(k, 0), 5) for k in after
                if k.split(":")[1].endswith(("_sum", "_count")) or "prefix_cache" in k or "tokens" in k}
    record(r); return r

if MODE == "grid":
    stream("warm up", 8)
    for size in (500, 2000, 8000, 16000, 32000, 48000, 60000):
        for rep in range(4):
            tag = uuid.uuid4().hex
            p = text(size, tag) + "\nDescribe this table."
            r = run("cold", prompt=p, target=size, rep=rep)
            h = run("hit", prompt=p, target=size, rep=rep)
            print(size, rep, f"cold ttft {r['ttft_ms']:.0f} tpot {r['tpot_ms']:.1f} cached {r['cached']} | hit ttft {h['ttft_ms']:.0f} tpot {h['tpot_ms']:.1f} cached {h['cached']}", flush=True)
elif MODE == "paths":
    label = sys.argv[sys.argv.index("--label") + 1]
    stream("warm up", 8)
    p = text(500, "fixed") + "\nDescribe this table."
    stream(p, 8)
    for rep in range(30):
        r = stream(p, 32); r.update(label=label, rep=rep); record(r)
    rows = [json.loads(x) for x in open(OUT) if json.loads(x).get("label") == label]
    print(label, "ttft p50", round(statistics.median(x["ttft_ms"] for x in rows), 1), "p95", round(sorted(x["ttft_ms"] for x in rows)[int(len(rows) * .95)], 1))
elif MODE == "conc":
    stream("warm up", 8)
    for c in (1, 2, 3, 4):
        res = []
        def work(i):
            res.append(stream(text(4000, uuid.uuid4().hex) + "\nDescribe this table.", 300))
        t0 = time.perf_counter(); ts = [threading.Thread(target=work, args=(i,)) for i in range(c)]
        [t.start() for t in ts]; [t.join() for t in ts]; wall = time.perf_counter() - t0
        row = {"label": "conc", "concurrency": c, "wall_s": wall, "ttft_ms": statistics.mean(x["ttft_ms"] for x in res),
               "ttft_max": max(x["ttft_ms"] for x in res), "tpot_ms": statistics.mean(x["tpot_ms"] for x in res),
               "throughput": sum(x["completion_tokens"] for x in res) / wall}
        record(row); print(row, flush=True)
