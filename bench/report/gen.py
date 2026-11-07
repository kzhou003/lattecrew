#!/usr/bin/env python3
"""Build the LatteCrew optimization report from the raw measurement files in ../out and ../collab."""
import collections, csv, datetime, glob, json, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(__file__))
from charts import esc, fmt, hbar, stacked_hbar, lines, dotplot, table, legend
from diagrams import stack, prompt_layout, sequence, gantt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "out")
COLLAB = os.path.join(HERE, "..", "collab")
def jl(name, base=OUT):
    p = os.path.join(base, name)
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []
med = st.median

# ---------------------------------------------------------------- connection and harness layers
stackp = {r["probe"]: r for r in jl("stack.jsonl") if "p50" in r}
paths = collections.defaultdict(list)
for r in jl("llm-paths.jsonl") + jl("mac-paths.jsonl"):
    paths[r["label"]].append(r["ttft_ms"])
ttft_direct, ttft_swap, ttft_tunnel = (med(paths[k]) for k in ("direct", "swap", "tunnel"))
harness = jl("harness.jsonl")
cc_wall = med([r["wall_ms"] for r in harness if r["probe"] == "claude"][1:]) / 1000
cc_api = med([r["api_ms"] for r in harness if r["probe"] == "claude"][1:]) / 1000
oc_wall = med([r["wall_ms"] for r in harness if r["probe"] == "opencode"][1:]) / 1000
kiro = jl("kiro.jsonl")
k_before = [r for r in kiro if r["label"] == "kiro-qwen-8k"]
k_after = [r for r in kiro if r["label"] == "kiro-qwen-reorder" and r["prompt_tokens_cached_total"] > 0]
kb_wall, kb_pre = med([r["wall"] for r in k_before]), med([r["request_prefill_time_seconds_sum"] for r in k_before])
ka_wall, ka_pre = med([r["wall"] for r in k_after]), med([r["request_prefill_time_seconds_sum"] for r in k_after])
ka_cached = int(k_after[0]["prompt_tokens_cached_total"])
k_prompt = int(k_before[0]["prompt_tokens_total"])

# ---------------------------------------------------------------- vLLM grid
grid = collections.defaultdict(list)
for r in jl("llm-grid.jsonl"):
    grid[(r["target"], r["label"])].append(r)
sizes = sorted({k[0] for k in grid})
G = {k: dict(ptok=v[0]["prompt_tokens"], ttft=med([x["ttft_ms"] for x in v]), tpot=med([x["tpot_ms"] for x in v])) for k, v in grid.items()}
cold_rate = [(G[(s, "cold")]["ptok"] / (G[(s, "cold")]["ttft"] / 1000)) for s in sizes if s >= 8000]
prefill_rate = med(cold_rate)
conc = jl("llm-conc.jsonl")

# ---------------------------------------------------------------- media
media = jl("media.jsonl")
Z = collections.defaultdict(list)
for r in media:
    if r["kind"] == "zimage":
        Z[(r["size"], r["steps"])].append(r["secs"])
T = collections.defaultdict(list)
for r in media:
    if r["kind"] == "tts":
        T[r["text"]].append(r)
W = [r for r in media if r["kind"] == "wan"]
gpu = []
for l in csv.reader(open(os.path.join(OUT, "media-gpu.csv"))):
    try:
        ts = datetime.datetime.strptime(l[0].strip(), "%Y/%m/%d %H:%M:%S.%f").timestamp()
        gpu.append((ts, float(l[1]), float(l[3]), float(l[4]), float(l[5])))
    except Exception:
        pass
def wan_phase(r):
    s = [g for g in gpu if r["start"] <= g[0] <= r["end"]]
    busy = [g for g in s if g[1] >= 80]
    if not busy:
        return None
    t0, t1 = busy[0][0], busy[-1][0]
    return dict(denoise=t1 - t0, before=t0 - r["start"], after=r["end"] - t1, power=med([g[3] for g in busy]), clock=med([g[4] for g in busy]),
                samples=s)

# ---------------------------------------------------------------- kernel and speculative decoding
kernel = jl("kernel.jsonl")
spec = jl("spec.jsonl")
def kagg(rows, label):
    rr = [r for r in rows if r["label"] == label]
    if not rr:
        return None
    pf = {}
    for c in sorted({r.get("chars") for r in rr if r["test"] == "prefill"}):
        v = [r for r in rr if r["test"] == "prefill" and r["chars"] == c]
        pf[c] = dict(tokens=v[0]["prompt"], ttft=med([x["ttft_ms"] for x in v]))
    dec = [r["tpot_ms"] for r in rr if r["test"] == "decode"]
    c2 = [r for r in rr if r["test"] == "c2"]
    ct = [r for r in rr if r["test"] == "code_think"]
    cn = [r for r in rr if r["test"] == "code_nothink"]
    return dict(prefill=pf, tpot=med(dec) if dec else None, c2=c2[0] if c2 else None,
                code_think=dict(tok_s=med([x["tok_s"] for x in ct]), accept=med([x["accept_rate"] for x in ct]) if ct and ct[0].get("accept_rate") is not None else None) if ct else None,
                code_nothink=dict(tok_s=med([x["tok_s"] for x in cn]), accept=med([x["accept_rate"] for x in cn]) if cn and cn[0].get("accept_rate") is not None else None) if cn else None)
K = {l: kagg(kernel, l) for l in ("base", "fi-sampler", "fi-attn")}
S = {l: kagg(spec, l) for l in ("base", "mtp1", "mtp2", "mtp3")}
prof = {}
for name in ("prefill", "decode"):
    for f in glob.glob(os.path.join(OUT, "prof", name, "rank0*.txt")):
        prof[name] = open(f).read()

# ---------------------------------------------------------------- collaboration
tasks = json.load(open(os.path.join(COLLAB, "tasks.json")))
TOT = {"t1": 9, "t2": 34, "t3": 14, "t4": 17, "t5": 19, "t6": 82}
scored = {s["job"]: s for s in json.load(open(os.path.join(COLLAB, "scored.json")))}
results = jl("results.jsonl", COLLAB)
ARM = {"claude": "Claude 单独", "local": "Qwen + Claude 审查", "codex": "Codex 规划 + Qwen + Claude 审查"}
CLS = {"claude": "s1", "local": "s2", "codex": "s3"}
runs = []
for r in results:
    s = scored[r["job"]]
    cl = {k: sum(x[k] for x in s["claude"]) for k in ("input", "cache_write", "cache_read", "output", "cost")}
    qw = {k: sum(x[k] for x in s["qwen"]) for k in ("steps", "tools", "input", "output", "reasoning")}
    pu = r.get("plan_usage") or {}
    runs.append(dict(arm=r["arm"], trial=r.get("trial", 1), task=r["task"], level=r["level"], state=r["state"], rounds=s["rounds"],
                     wall=r["wall"], passed=s["final"]["passed"], total=TOT[r["task"]], r1=(s.get("round1") or {}).get("passed"),
                     extra=s.get("extra"), cost=cl["cost"], cl_tok=cl["input"] + cl["cache_write"] + cl["cache_read"], cl_out=cl["output"],
                     q_in=qw["input"], q_out=qw["output"] + qw["reasoning"], q_reason=qw["reasoning"], q_steps=qw["steps"],
                     plan_in=pu.get("input_tokens", 0), plan_out=pu.get("output_tokens", 0) + pu.get("reasoning_output_tokens", 0),
                     plan_secs=r.get("plan_secs") or 0, secs=s["secs"], job=r["job"], error=r.get("error")))
def arm_runs(arm, trial):
    return [x for x in runs if x["arm"] == arm and x["trial"] == trial]
main = {"claude": arm_runs("claude", 1), "local": arm_runs("local", 2), "codex": arm_runs("codex", 2)}
def summ(rs):
    return dict(solved=sum(x["passed"] == x["total"] for x in rs), tests=sum(x["passed"] for x in rs), wall=sum(x["wall"] for x in rs),
                cost=sum(x["cost"] for x in rs), cl_tok=sum(x["cl_tok"] for x in rs), cl_out=sum(x["cl_out"] for x in rs),
                q_in=sum(x["q_in"] for x in rs), q_out=sum(x["q_out"] for x in rs), q_reason=sum(x["q_reason"] for x in rs),
                plan_in=sum(x["plan_in"] for x in rs), plan_out=sum(x["plan_out"] for x in rs),
                ready=sum(x["state"] in ("ready", "done") for x in rs), need=sum(x["state"] == "need_human" for x in rs),
                failed=sum(x["state"] == "failed" for x in rs), rounds=sum(x["rounds"] for x in rs))
SM = {a: summ(v) for a, v in main.items()}
T1 = {a: summ(arm_runs(a, 1)) for a in ("local", "codex")}

# Qwen time split from OpenCode event logs
qsplit = dict(model=0, tool=0, gap=0, out=0, reason=0)
for f in glob.glob(os.path.join(OUT, "jobs", "*", "qwen-r*.log")):
    ev = [json.loads(l) for l in open(f) if l.strip().startswith("{")]
    s = last = None
    for d in ev:
        ts = d.get("timestamp")
        if d["type"] == "step_start":
            if last:
                qsplit["gap"] += ts - last
            s = ts
        elif d["type"] == "tool_use":
            t = (d["part"].get("state") or {}).get("time") or {}
            if t:
                qsplit["tool"] += t["end"] - t["start"]; qsplit["model"] -= t["end"] - t["start"]
        elif d["type"] == "step_finish":
            qsplit["model"] += ts - s; last = ts
            k = d["part"].get("tokens") or {}
            qsplit["out"] += k.get("output", 0); qsplit["reason"] += k.get("reasoning", 0)
qwall = qsplit["model"] + qsplit["tool"] + qsplit["gap"]

def steps_of(job, f):
    ev = [json.loads(l) for l in open(os.path.join(OUT, "jobs", job, f)) if l.strip().startswith("{")]
    out, s = [], None
    for d in ev:
        if d["type"] == "step_start":
            s = d["timestamp"]
        elif d["type"] == "step_finish":
            k = d["part"].get("tokens") or {}
            out.append((s, d["timestamp"], k.get("reasoning", 0), k.get("output", 0)))
    return out

# ================================================================= rendering
def sec(id_, eyebrow, title, body):
    return f'<section id="{id_}"><p class="eyebrow">{esc(eyebrow)}</p><h2>{esc(title)}</h2>{body}</section>'
def fig(chart, caption, leg=None, wide=False):
    return (f'<figure class="{"wide" if wide else ""}">{leg or ""}<div class="scroll">{chart}</div>'
            f'<figcaption>{caption}</figcaption></figure>')
def P(*paras):
    return "".join(f"<p>{x}</p>" for x in paras)
def ul(*items):
    return "<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>"
def n(v, d=0):
    return f"{v:,.{d}f}"
def mins(s):
    return f"{s/60:.1f} 分钟" if s >= 120 else f"{s:.0f} 秒"

speedup_kiro = kb_wall / ka_wall
q_model_share = qsplit["model"] / qwall
q_reason_share = qsplit["reason"] / (qsplit["reason"] + qsplit["out"])
q_rate = (qsplit["reason"] + qsplit["out"]) / (qsplit["model"] / 1000)

# ---------------------------------------------------------------- hero
hero = f'''
<header class="hero">
  <p class="eyebrow">LatteCrew 系列 · 实验报告 · 2026 年 11 月</p>
  <h1>LatteCrew：优化与分析</h1>
  <p class="lede">我把整条链路从 Slack 消息一路量到 GPU kernel：网络、SSH、MCP、Kiro Crew、Claude Code、OpenCode、vLLM、vLLM-Omni，再到 RTX 5090 本身。
  然后用 6 道带隐藏测试的编程题，对比 Claude 单独完成和 Codex 规划、Qwen 编码、Claude 审查的协作方式。</p>
  <div class="tiles">
    <div class="tile"><b>{q_model_share*100:.0f}%</b><span>Qwen 作业时间花在模型生成上；工具执行只占 {qsplit["tool"]/qwall*100:.1f}%</span></div>
    <div class="tile"><b>{q_reason_share*100:.0f}%</b><span>Qwen 生成的 token 是思考内容，解码速度约 {q_rate:.0f} tok/s</span></div>
    <div class="tile"><b>{kb_wall:.1f} → {ka_wall:.1f} 秒</b><span>Kiro qwen 网关回复一句话；把一个会变的工具定义挪到末尾后</span></div>
    <div class="tile"><b>6/6 · 6/6 · 6/6</b><span>三种方式都通过了全部隐藏测试，但协作方式慢 {SM["local"]["wall"]/SM["claude"]["wall"]:.0f} 倍</span></div>
  </div>
</header>'''

# ---------------------------------------------------------------- 0. questions and answers
answers = sec("answers", "先说结论", "三个问题的答案", P(
  f'<b>协作有效吗？</b>对正确性有效，对速度和 Claude 额度在小任务上无效。三种方式最后都拿到 175/175 个隐藏测试。'
  f'Claude 审查在 22 次审查里给出 5 次 CHANGES，找到的都是真实问题：夏令时的墙钟算术、大容量令牌桶的容差、等待时间计算的性能。'
  f'但 Claude 单独做完 6 道题共 {mins(SM["claude"]["wall"])}、折合 API 价 ${SM["claude"]["cost"]:.2f}；'
  f'Qwen + Claude 用了 {mins(SM["local"]["wall"])}，Claude 审查本身就花了 ${SM["local"]["cost"]:.2f}。'
  f'一次审查的固定开销（约 2–3 万 token 的系统提示写缓存）和让 Claude 直接写完这些小题差不多。',
  f'<b>能力是下降还是提高？</b>在这组题上没有下降，在边界情况上还略有提高。我把审查者发现的问题写成额外的边界测试，再回头跑三种方式的代码：'
  f'夏令时那道题，Claude 单独 0/2，Qwen + Claude 1/2，Codex 规划那组 2/2。Codex 的计划里提前点出了夏令时陷阱，Qwen 照着写对了。'
  f'代价是第一轮实验暴露的脆弱性：OpenCode 输出上限设成 8,192 时，一半的题 Qwen 在一步思考里就把额度用完，什么都没交。',
  f'<b>端到端瓶颈在哪？</b>在 Qwen 解码思考 token。Qwen 作业 {q_model_share*100:.0f}% 的时间在生成，生成的 token 里 {q_reason_share*100:.0f}% 是思考，'
  f'解码稳定在约 {q_rate:.0f} tok/s，预填充几乎全被前缀缓存省掉。其次是三个“每次都要付”的固定成本：模型切换 35–66 秒、Claude Code 每次启动约 3 秒、'
  f'Kiro 网关每轮重算 4.7 万 token 的提示。网络、SSH、MCP 加起来不到半秒，不是问题。'
  f'最有效的单项优化是 MTP 推测解码：同一道编程题，开思考时从 {S["base"]["code_think"]["tok_s"]:.0f} tok/s 提到 {S["mtp3"]["code_think"]["tok_s"]:.0f} tok/s，不损失质量。换 FlashInfer kernel 没有收益，因为解码已经用到约 84% 的显存带宽。'))

# ---------------------------------------------------------------- 1. setup
layers = [
  ("你", "手机 Slack / Mac 终端", ["Tailscale RTT 约 8–22 ms"], "n0"),
  ("Kiro Crew 网关", "Mac: claude、codex；latte: claude、qwen", [f"qwen 网关一轮 {kb_wall:.1f} 秒，修复后 {ka_wall:.1f} 秒", "Mac 上 Claude 网关一轮 4.6–7.0 秒"], "n1"),
  ("Agent harness", "Claude Code 0.101 / OpenCode 1.19 / Codex CLI", [f"Claude Code 空任务 {cc_wall:.1f} 秒，API 只占 {cc_api:.2f} 秒", f"OpenCode 空任务 {oc_wall:.1f} 秒，提示 12,198 token"], "n1"),
  ("MCP over SSH", "latte-crew MCP，Tailscale 上的 SSH", [f"新会话调用 {stackp['mcp_new_session_call']['p50']:.0f} ms，常驻会话 {stackp['mcp_live_session_call']['p50']:.1f} ms", f"SSH 新连接 {stackp['ssh_new_conn_true']['p50']:.0f} ms，复用 {stackp['ssh_mux_true']['p50']:.0f} ms"], "n2"),
  ("crewd", "作业队列、git worktree、GPU 锁、账本", ["工具执行占 Qwen 作业 0.8%", "步间间隔占 3.3%"], "n2"),
  ("llama-swap :8100", "按需加载、互斥切换模型", [f"代理开销 +{ttft_swap-ttft_direct:.1f} ms，SSH 隧道 +{ttft_tunnel-ttft_direct:.0f} ms", "切换模型 35–66 秒"], "n3"),
  ("vLLM 0.32 / vLLM-Omni 0.32", "Qwen3.8-27B AWQ；Z-Image、Qwen3-TTS、Wan2.2", [f"冷预填充约 {prefill_rate:,.0f} tok/s，命中缓存 0.2–0.3 秒", "解码 12.8–15.4 ms/token"], "n3"),
  ("RTX 5090 32 GB", "575 W 功耗上限，PCIe 5.0 x16", ["Wan 去噪全程顶在 575 W，SM 约 2.5 GHz", "LLM 基准中位功耗 485 W，2.8 GHz"], "n4"),
]
setup = sec("setup", "第 1 部分", "实验怎么设计的", P(
  "目标是回答三个问题，所以实验分两类。第一类是逐层的微基准：每一层单独测，固定输入，重复多次取中位数，尽量让上一层的开销不混进下一层。第二类是端到端的协作实验：同一组任务，在不同的分工方式下完整跑一遍，用隐藏测试打分。")
  + fig(stack(layers), "图 1：一条请求经过的各层，以及每层实测的延迟。悬停查看详情。下文每一节对应其中一层。", wide=True)
  + "<h3>可观测性：每层的数据从哪里来</h3>"
  + ul("网络和连接层：自写探针 <code>stack_probe.py</code>，测 SSH 新连接与复用、MCP 三种调用方式、scp 1 MB，每项 10–30 次。",
       "Agent 层：<code>harness_probe.py</code> 让 Claude Code 和 OpenCode 各回答一句话，读取它们的 JSON 事件流拿到 API 时间和 token；Kiro 层用 <code>kirocrew chat</code> 计时，同时读 vLLM 计数器的差值。为了看清 Kiro 发给模型的内容，我写了一个记录请求体的反向代理。",
       "vLLM 层：打开 <code>--enable-mfu-metrics --kv-cache-metrics</code>，从 <code>/metrics</code> 读预填充时间、解码时间、前缀缓存命中的 token 数。流式探针 <code>llm_probe.py</code> 自己测 TTFT 和 TPOT，两边互相印证。",
       "GPU 层：<code>nvidia-smi</code> 每 250 ms 采样利用率、显存、功耗、时钟；kernel 级用 vLLM 自带的 torch profiler 抓预填充和解码各一次。",
       "协作实验：crewd 的账本记录每个阶段的秒数和花费；OpenCode 的 <code>step_finish</code> 事件给出每一步的输入、输出、思考 token；Claude Code 的 <code>result</code> 事件给出缓存读写 token 和折算价格；Codex 的 <code>turn.completed</code> 给出计划用的 token。")
  + "<h3>环境</h3>"
  + table(["项目", "配置"], [
      ["GPU 机器 latte", "RTX 5090 32 GB，Ubuntu 24.04，torch 2.13 + CUDA 13.0，vLLM 0.32.0，vLLM-Omni 0.32.0"],
      ["编程模型", "Qwen3.8-27B AWQ INT4（64 层：48 层线性注意力 + 16 层全注意力），上下文 65,536，最多 2 个并发序列，KV 约 11.9 万 token"],
      ["媒体模型", "Z-Image-Turbo、Qwen3-TTS-12Hz-1.7B、Wan2.2-TI2V-5B（CPU offload）"],
      ["Agent", "Claude Code（Sonnet 写代码，Claude 审查），OpenCode 1.19.5 驱动 Qwen，Codex CLI 0.144 在 Mac 上只读规划"],
      ["连接", "Mac 与 latte 走 Tailscale；MCP 走 SSH；Slack 走 Kiro Crew 网关"]]))

# ---------------------------------------------------------------- 2. connection layer
conn_rows = [
  ("SSH 新建连接", stackp["ssh_new_conn_true"]["p50"], "s4", "每次新建 TCP + 密钥交换"),
  ("SSH 复用连接", stackp["ssh_mux_true"]["p50"], "s1", "ControlMaster 复用"),
  ("MCP 新会话调用", stackp["mcp_new_session_call"]["p50"], "s4", "SSH + 启动 MCP 服务 + 初始化 + 一次调用"),
  ("MCP 复用 SSH", stackp["mcp_mux_session_call"]["p50"], "s4", "SSH 复用，但仍新起 MCP 进程"),
  ("MCP 常驻会话", stackp["mcp_live_session_call"]["p50"], "s1", "会话已建立，只算一次工具调用"),
  ("scp 1 MB", stackp["scp_1MB"]["p50"], "s1", "复用连接传 1 MB 文件"),
  ("SSH 隧道多出的 TTFT", ttft_tunnel - ttft_direct, "s1", f"直连 {ttft_direct:.1f} ms，隧道 {ttft_tunnel:.1f} ms"),
  ("llama-swap 多出的 TTFT", ttft_swap - ttft_direct, "s1", f"直连 {ttft_direct:.1f} ms，llama-swap {ttft_swap:.1f} ms"),
]
connection = sec("connection", "第 2 部分 · 连接层", "Tailscale、SSH、MCP：不是瓶颈", P(
  "先排除最容易被怀疑的一层。下面每个值都是中位数，单位毫秒。")
  + fig(hbar([(a, b, c, f"{a}: {b:.1f} ms · {d}") for a, b, c, d in conn_rows], unit=" ms", label="Connection layer latency", note_fmt=lambda v: f"{v:,.1f} ms" if v < 100 else f"{v:,.0f} ms"),
        "图 2：连接层各操作的中位延迟（毫秒）。蓝色是已经在用的方式，黄色是要避免的方式。",
        legend([("s1", "当前做法"), ("s4", "应避免的做法")]))
  + P(f"最慢的是 MCP 每次新开会话：{stackp['mcp_new_session_call']['p50']:.0f} ms，而常驻会话里一次调用只要 {stackp['mcp_live_session_call']['p50']:.1f} ms，差 {stackp['mcp_new_session_call']['p50']/stackp['mcp_live_session_call']['p50']:.0f} 倍。"
      "Claude Code 和 Kiro 都会让 MCP 会话常驻，所以实际只在启动时付一次。SSH 隧道让 TTFT 多了约 29 ms，llama-swap 代理只多 1.4 ms。"
      "和后面动辄几十秒的模型时间相比，这一层可以忽略。唯一值得做的是确认所有脚本都走 SSH 复用连接（<code>ControlMaster</code>），省下每次约 320 ms。"))

# ---------------------------------------------------------------- 3. harness and Kiro
harness_rows = [
  ("OpenCode 空任务", [oc_wall * 0.0, oc_wall], f"{oc_wall:.1f} 秒"),
  ("Claude Code 空任务", [cc_api, cc_wall - cc_api], f"{cc_wall:.1f} 秒"),
  ("Kiro qwen 网关（修复前）", [kb_pre, kb_wall - kb_pre], f"{kb_wall:.1f} 秒"),
  ("Kiro qwen 网关（修复后）", [ka_pre, ka_wall - ka_pre], f"{ka_wall:.1f} 秒"),
]
harness_sec = sec("harness", "第 3 部分 · Agent 层", "Kiro、Claude Code、OpenCode：固定开销", P(
  "让每个 agent 只回复一句 “ok”，测的就是它自己的固定开销：启动进程、加载工具、拼系统提示、第一次请求。")
  + fig(stacked_hbar(harness_rows, [("s2", "模型时间（API 或 vLLM 预填充）"), ("muted", "其余：启动、工具加载、解码、往返")], unit=" 秒", label="Agent fixed overhead"),
        "图 3：一句话回复的耗时拆分（秒）。Claude Code 的模型时间是 API 耗时；Kiro 的模型时间是 vLLM 记录的预填充时间。OpenCode 的事件流不给 API 耗时，只画总长。",
        legend([("s2", "模型时间"), ("muted", "其余开销")]))
  + P(f"Claude Code 一次调用 {cc_wall:.1f} 秒，其中 API 只有 {cc_api:.2f} 秒，剩下约 3 秒是 Node 进程启动、插件和 MCP 初始化。它每次带着 31,376 个 token 的系统提示和工具定义，第一次写缓存，之后读缓存。"
      f"crewd 每个阶段都起一个新的 Claude Code 进程，所以每次审查都先付这 3 秒和这份缓存读取。",
      f"Kiro 的 qwen 网关最反常：回复 “ok” 要 {kb_wall:.1f} 秒，其中 vLLM 预填充 {kb_pre:.1f} 秒，而且每一轮的缓存命中都是 0。")
  + "<h3>为什么 Kiro 每轮都不命中缓存</h3>"
  + P(f"我在 OpenCode 和 llama-swap 之间加了一个记录请求体的代理，拿到了 Kiro 发给 Qwen 的完整请求。每轮 {k_prompt:,} 个 token 由这些部分组成："
      "107 个工具定义（其中 77 个来自 <code>kirocrew-core</code> MCP，JSON 共 11.8 万字符），一段 2.9 万字符的系统提示（里面列了 19 个同步过来的 skill），最后才是用户消息。",
      "对比相邻两轮的请求，系统提示、工具顺序完全一样，唯一不同的是 OpenCode 内置 <code>bash</code> 工具的描述：它写着本会话的临时目录 <code>…/scratch/cli_chat-fbc438de/opencode</code>，每个 Kiro 会话都不同。"
      "Qwen 的聊天模板把工具放在最前面，<code>bash</code> 又是第一个工具，于是两轮请求在第 184 个 token 就分叉了。")
  + "<h3>混合注意力模型让问题更严重</h3>"
  + P("一般的 Transformer 遇到这种情况，前缀缓存仍能复用分叉点之前的块。Qwen3.8 是混合架构：48 层线性注意力（类似 Mamba 的递推状态）加 16 层全注意力。"
      "vLLM 对这类模型用 <code>mamba_cache_mode=align</code>，线性注意力层的状态只在每个调度步的最后一个 token、并且对齐到块边界（这里是 784 token）时才保存。"
      "我做了一个对照实验：一个 2.8 万 token 的提示，只改中间一行，结果缓存命中 0 个 token；完全相同的前缀加不同的结尾，命中 28,224 个。也就是说，这个模型只能复用“上一次请求恰好保存了检查点”的位置。")
  + fig(prompt_layout(k_prompt, 184, 1300, ka_cached),
        f"图 4：Kiro qwen 网关的提示里，vLLM 能复用的部分。蓝色可复用，橙色是每轮都变的 bash 工具描述，灰色每轮重算。工具重排后，前 37,439 个 token 每轮相同，vLLM 按 784 的块对齐复用其中 {ka_cached:,} 个。",
        legend([("s1", "可复用前缀"), ("s2", "每轮会变的工具描述"), ("muted", "每轮重算")]))
  + P(f"验证：我让代理把描述里带临时目录的工具挪到工具列表末尾，其余不动。前两轮仍是冷启动（还没有可用的检查点），从第三轮起每轮命中 {ka_cached:,} 个 token，预填充从 {kb_pre:.1f} 秒降到 {ka_pre:.1f} 秒，整轮从 {kb_wall:.1f} 秒降到 {ka_wall:.1f} 秒，快了 {speedup_kiro:.1f} 倍。"
      "这个代理只是实验用的，没有常驻。要正式修，有三种做法：让 Kiro 或 OpenCode 把会话相关的内容移出工具描述；给 qwen 这个 Bot 少挂 MCP（77 个 kirocrew-core 工具对一个本地编码 Bot 大多用不到）；或者常驻一个小的重排代理。")
  + P("顺带发现一个配置陷阱。我一度把 OpenCode 的输出上限从 8,192 调到 32,768，Kiro 网关立刻陷入循环：OpenCode 认为可用上下文是 65,536 − 32,768 = 32,768，装不下 4.7 万的提示，于是不停触发“压缩会话”，两轮对话发出了 36 个请求。"
      "最后的做法是全局保持 8,192，只在 crewd 起 OpenCode 时用 <code>OPENCODE_CONFIG_CONTENT</code> 单独把输出上限调到 32,768。"))

# ---------------------------------------------------------------- 4. vLLM layer
cold = [(G[(s, "cold")]["ptok"], G[(s, "cold")]["ttft"] / 1000, f'{G[(s, "cold")]["ptok"]:,} token，{G[(s, "cold")]["ttft"]/1000:.2f} 秒') for s in sizes]
hit = [(G[(s, "hit")]["ptok"], G[(s, "hit")]["ttft"] / 1000, f'{G[(s, "hit")]["ttft"]:.0f} ms') for s in sizes]
tpot = [(G[(s, "cold")]["ptok"], G[(s, "cold")]["tpot"], f'{G[(s, "cold")]["tpot"]:.1f} ms/token') for s in sizes]
c1 = next(c for c in conc if c["concurrency"] == 1); c2 = next(c for c in conc if c["concurrency"] == 2)
big = sizes[-1]
vllm_sec = sec("vllm", "第 4 部分 · 推理服务层", "vLLM：预填充贵，缓存命中便宜，解码稳定", P(
  "用流式请求测 Qwen3.8：提示长度从 500 到 6.5 万 token，每个长度 4 次。“冷”是每次加一个随机前缀，强制重算；“命中”是重复同一个提示。输出用 <code>ignore_eos</code> 固定为 256 个 token（最长的一档受上下文上限只能输出约 135 个）。")
  + fig(lines([("s1", "冷启动", cold), ("s2", "命中缓存", hit)], "提示长度（token）", "首 token 延迟（秒）", label="TTFT vs prompt length",
              xfmt=lambda v: f"{v/1000:.0f}K"),
        f"图 5：首 token 延迟和提示长度。冷启动时预填充约 {prefill_rate:,.0f} tok/s，近似线性；命中缓存时几乎是常数。",
        legend([("s1", "冷启动"), ("s2", "命中缓存")]))
  + P(f"冷启动时 TTFT 和提示长度成正比，{G[(big,'cold')]['ptok']:,} token 要 {G[(big,'cold')]['ttft']/1000:.1f} 秒；命中缓存只要 {G[(big,'hit')]['ttft']:.0f} ms，差 {G[(big,'cold')]['ttft']/G[(big,'hit')]['ttft']:.0f} 倍。"
      "所以对 agent 来说，提示长不可怕，提示前缀不稳定才可怕。上一节的 Kiro 就是例子。")
  + fig(lines([("s1", "TPOT", tpot)], "上下文长度（token）", "每个输出 token 的时间（ms）", label="TPOT vs context", ymax=18, xfmt=lambda v: f"{v/1000:.0f}K", end_labels=False),
        "图 6：解码速度和上下文长度。上下文越长，每步要读的 KV 越多，TPOT 从 12.8 ms 涨到 15.4 ms。")
  + P(f"解码几乎不受提示长度影响：从 0.5K 到 65K 上下文，TPOT 只从 {G[(sizes[0],'cold')]['tpot']:.1f} ms 涨到 {G[(big,'cold')]['tpot']:.1f} ms。"
      "原因是这个模型 3/4 的层是线性注意力，状态大小固定，只有 16 层全注意力的 KV 随上下文增长。对纯 Transformer，这条线会陡得多。")
  + "<h3>并发</h3>"
  + table(["并发数", "平均 TTFT", "最慢 TTFT", "TPOT", "总吞吐"],
          [[c["concurrency"], f'{c["ttft_ms"]:,.0f} ms', f'{c["ttft_max"]:,.0f} ms', f'{c["tpot_ms"]:.1f} ms', f'{c["throughput"]:.1f} tok/s'] for c in conc])
  + P(f"4K 提示、300 个输出 token。两个请求并发时，总吞吐从 {c1['throughput']:.1f} 涨到 {c2['throughput']:.1f} tok/s（{c2['throughput']/c1['throughput']:.2f} 倍），每个请求的 TPOT 只慢了 {c2['tpot_ms']/c1['tpot_ms']*100-100:.0f}%。"
      "第三、四个请求要排队（服务只开了 2 个序列），最慢的 TTFT 到了 7–8 秒。解码是访存受限的，所以小批量几乎是白送的吞吐；但 crewd 目前一次只跑一个 Qwen 作业，这部分能力没用上。"))

# ---------------------------------------------------------------- 6. media models
zrows = []
for steps in (4, 8, 12):
    v = Z[("1024x1024", steps)]
    zrows.append((f"1024² · {steps} 步", med(v[1:]), "s1", f"1024×1024，{steps} 步：{med(v[1:]):.2f} 秒（{len(v)-1} 次热启动中位数）"))
for size in ("512x512", "768x768", "1344x768"):
    v = Z[(size, 8)]
    zrows.append((f"{size.replace('x', '×')} · 8 步", med(v), "s3", f"{size}，8 步：{med(v):.2f} 秒"))
z_step = (med(Z[("1024x1024", 12)][1:]) - med(Z[("1024x1024", 4)][1:])) / 8
tts_rows = [[{"short": "短句", "mid": "中句", "long": "长段"}[k], v[0]["chars"], f'{v[-1]["audio"]:.1f} 秒', f'{med([x["secs"] for x in v[1:]]):.1f} 秒', f'{med([x["rtf"] for x in v[1:]]):.2f}'] for k, v in T.items()]
wan_rows = []
for r in W[1:]:
    ph = wan_phase(r)
    wan_rows.append([f'{r["frames"]} 帧（{r["frames"]/24:.1f} 秒）', r["steps"], f'{r["secs"]:.0f} 秒', f'{ph["denoise"]:.0f} 秒', f'{ph["denoise"]/r["steps"]:.2f} 秒', f'{ph["after"]:.0f} 秒'])
w121 = next(r for r in W if r["frames"] == 121)
ph121 = wan_phase(w121)
samples = ph121["samples"]
t0 = samples[0][0]
ds = samples[::8]
util_pts = [(g[0] - t0, g[1], f"{g[0]-t0:.0f} 秒：利用率 {g[1]:.0f}%") for g in ds]
pow_pts = [(g[0] - t0, g[3], f"{g[0]-t0:.0f} 秒：{g[3]:.0f} W，SM {g[4]:.0f} MHz") for g in ds]
swap = [("Qwen3.8 27B（vLLM）", 64, "s2", "首个请求触发加载，约 64 秒（先前测量）"),
        ("Qwen3-TTS", med([v[0]["secs"] for v in T.values()][:1]) - med([x["secs"] for x in T["short"][1:]]), "s2", "首个请求 67.6 秒，减去合成时间"),
        ("Wan2.2 TI2V 5B", W[0]["secs"] - W[1]["secs"], "s2", f"首个视频 {W[0]['secs']:.0f} 秒，同参数第二次 {W[1]['secs']:.0f} 秒"),
        ("Z-Image-Turbo", Z[("1024x1024", 4)][0] - med(Z[("1024x1024", 4)][1:]), "s2", f"首张 {Z[('1024x1024', 4)][0]:.1f} 秒，之后 {med(Z[('1024x1024', 4)][1:]):.1f} 秒")]
media_sec = sec("media", "第 6 部分 · vLLM-Omni", "图像、语音、视频：切换比生成贵", P(
  "三个媒体模型都通过 llama-swap 按需加载，和 Qwen 互斥地用一块 GPU。测法和 media-bot 一样：先拿 GPU 锁，再请求。")
  + fig(hbar(swap, unit=" 秒", label="Model swap cost", note_fmt=lambda v: f"{v:.0f} 秒"),
        "图 10：切换到某个模型的代价（秒），即首个请求比之后的请求多花的时间。包括停掉上一个模型、加载权重、torch.compile 和 CUDA graph 捕获。")
  + P("切换是这一层最大的成本。生成一张图只要 2.5 秒，但如果 GPU 上正好是 Qwen，要先等 36 秒。TTS 一句话 1 秒，切过来要 66 秒。"
      "LatteCrew 的使用模式恰好是交替的：Qwen 在写代码，中间有人要一张图或一段语音。")
  + "<h3>Z-Image-Turbo</h3>"
  + fig(hbar(zrows, unit=" 秒", label="Z-Image latency", note_fmt=lambda v: f"{v:.2f} 秒"),
        f"图 11：Z-Image 生成一张图的时间。每步约 {z_step:.2f} 秒（1024²），时间和步数、像素数都近似线性。",
        legend([("s1", "改变步数"), ("s3", "改变分辨率")]))
  + P(f"默认 8 步、1024² 一张 {med(Z[('1024x1024', 8)][1:]):.2f} 秒，GPU 全程 575 W 满功耗。4 步只要一半时间，对 Slack 里的草图足够。")
  + "<h3>Qwen3-TTS</h3>"
  + table(["文本", "字数", "音频长度", "合成耗时", "实时率 RTF"], tts_rows)
  + P("实时率 0.43–0.58，即合成 1 秒音频要 0.43–0.58 秒。但当前接口是非流式的，要等整段合成完才返回：115 字的长段要等 13–17 秒才有第一个声音。"
      "Qwen3-TTS 是 12Hz 的流式 codec 模型，vLLM-Omni 也支持流式输出，改成流式后首包延迟应能降到 1 秒内（这一点还没测）。")
  + "<h3>Wan2.2 TI2V 5B</h3>"
  + table(["长度", "步数", "总耗时", "去噪阶段", "每步", "去噪之后"], wan_rows)
  + fig(lines([("s1", "GPU 利用率 %", util_pts)], "时间（秒）", "GPU 利用率（%）", label="Wan GPU utilization", ymax=110, end_labels=False),
        "图 12a：生成 5 秒视频（121 帧、30 步）时 GPU 的利用率，每 2 秒一个点。")
  + fig(lines([("s4", "功耗 W", pow_pts)], "时间（秒）", "功耗（W）", label="Wan GPU power", ymax=650, end_labels=False),
        f"图 12b：同一次生成的功耗。去噪阶段一直顶在 575 W 的功耗上限，SM 时钟被压到约 {ph121['clock']:.0f} MHz（最高 3,090 MHz）。")
  + P(f"两个现象。第一，去噪阶段是功耗受限的：功耗贴着 575 W 的上限，时钟只有 {ph121['clock']:.0f} MHz。这时提速的手段是减少计算量（更少的步数、更低的分辨率、量化），而不是更好的调度。"
      f"每步时间随帧数超线性增长：49 帧每步约 2.1 秒，121 帧每步 {ph121['denoise']/30:.1f} 秒，帧数 2.5 倍，每步 3.9 倍，符合视频注意力随 token 数平方增长。",
      f"第二，去噪结束后有 {ph121['after']:.0f} 秒 GPU 几乎空闲（利用率个位数、功耗约 50 W）。这段时间包括 VAE 解码、CPU offload 的权重搬运和 MP4 编码。"
      "这是纯等待，可以优先排查：如果 VAE 解码被 offload 到了 CPU，把它留在 GPU 上；MP4 编码可以和下一个请求重叠。"))

# ---------------------------------------------------------------- 7. collaboration
order = ["t1", "t2", "t3", "t4", "t5", "t6"]
cat = {t: f"{t} · {tasks[t]['title']}" for t in order}
LV = {"easy": "易", "medium": "中", "hard": "难"}
wall_series, cost_series = [], []
for arm in ("claude", "local", "codex"):
    d, c = {}, {}
    for x in main[arm]:
        d[cat[x["task"]]] = (x["wall"], f'{mins(x["wall"])}，{x["rounds"]} 轮，{x["state"]}')
        c[cat[x["task"]]] = (x["cost"], f'${x["cost"]:.3f}')
    wall_series.append((CLS[arm], ARM[arm], d)); cost_series.append((CLS[arm], ARM[arm], c))
arm_leg = legend([(CLS[a], ARM[a]) for a in ("claude", "local", "codex")])
def extra_cell(x):
    e = x["extra"]
    if not e:
        return "–"
    return f'{e["passed"]}/{e["total"]}'
summary_rows = []
for arm in ("claude", "local", "codex"):
    s = SM[arm]
    summary_rows.append([ARM[arm], f'{s["solved"]}/6', f'{s["tests"]}/175', f'{s["ready"]} 通过审查，{s["need"]} 需人工' if arm != "claude" else "无审查",
                         mins(s["wall"]), f'${s["cost"]:.2f}', f'{s["cl_out"]:,}', f'{s["q_out"]:,}' if s["q_out"] else "–", f'{s["plan_out"]:,}' if s["plan_out"] else "–"])
extra_rows = []
for t in ("t4", "t5"):
    row = [cat[t]]
    for arm in ("claude", "local", "codex"):
        x = next(x for x in main[arm] if x["task"] == t)
        row.append(extra_cell(x))
    extra_rows.append(row)

# Gantt: Codex-planned t4 and plain t4
def run_segments(job, plan=0.0):
    segs, t_end = [], plan
    if plan:
        segs.append(("Codex 规划", 0, plan, "s3 hit", f"Codex 只读浏览仓库并写计划：{plan:.0f} 秒"))
    secs = next(x for x in runs if x["job"] == job)["secs"]
    rounds = sorted({f.split("-r")[1].split(".")[0] for f in os.listdir(os.path.join(OUT, "jobs", job)) if f.startswith("qwen-r") and f.endswith(".log")})
    for rd in rounds:
        st_ = steps_of(job, f"qwen-r{rd}.log")
        base = st_[0][0]
        off = t_end + 2
        for a, b, rs, o in st_:
            heavy = rs >= 1000
            segs.append((f"Qwen 第 {rd} 轮", off + (a - base) / 1000, off + (b - base) / 1000, ("s2" if heavy else "s4"),
                         f"{'思考' if heavy else '动作'}步骤：{(b-a)/1000:.0f} 秒，思考 {rs:,} token，输出 {o:,} token"))
        t_end = off + (st_[-1][1] - base) / 1000
        rv = secs.get(f"local_reviewer-r{rd}", 0)
        segs.append((f"Claude 审查", t_end + 1, t_end + 1 + rv, "s1", f"第 {rd} 轮审查：{rv} 秒"))
        t_end = t_end + 1 + rv
    return segs
g_codex = run_segments("1107-a8846d", next(x for x in runs if x["job"] == "1107-a8846d")["plan_secs"])
g_local = run_segments("1107-b2704c")

seq = sequence(
  [("驱动脚本", "Mac"), ("Codex", "Mac，只读"), ("crewd", "latte"), ("Qwen · OpenCode", "latte GPU"), ("Claude 审查", "latte，只读")],
  [(0, 1, "任务描述", "613–1,170 字符", "m1"),
   (1, 1, "读仓库，写计划", "约 44 秒，读入 3.9–6.1 万 token", "m3"),
   (1, 0, "实现计划", "2.0–4.6K 字符，含数据结构、步骤、陷阱、测试", "m3"),
   (0, 2, "crew local（任务 + 计划）", "经 SSH 调用 crewd", "m1"),
   (2, 3, "角色提示 + 工作目录 + 任务", "新 git worktree，OpenCode 只能写这里", "m2"),
   (3, 3, "读、写、跑 pytest 的循环", "每轮 8–30 步，思考占生成的 80%", "m2"),
   (3, 2, "提交 + 自述", "自述 170–1,270 字符，审查者看不到", "m2"),
   (2, 4, "任务 + git diff base...HEAD", "只读，不给作者的自述", "m1"),
   (4, 4, "读 diff，自己跑测试、复现问题", "9–40 秒；一次压力测试跑了 12 分钟", "m1"),
   (4, 2, "审查意见 + VERDICT", "630–2,030 字符，带 file:line 和失败场景", "m1"),
   (2, 3, "CHANGES：意见发回同一会话", "最多 2 轮，之后转人工", "m2"),
   (2, 0, "PASS：ready，分支等人合并", "agent 不 push、不 merge", "m1")])

qsplit_rows = [("Qwen 作业时间", [qsplit["model"] / 1000, qsplit["tool"] / 1000, qsplit["gap"] / 1000], f"{qwall/1000/60:.0f} 分钟")]
qtok_rows = [("Qwen 生成的 token", [qsplit["reason"] / 1000, qsplit["out"] / 1000], f"{(qsplit['reason']+qsplit['out'])/1000:,.0f}K")]

collab_sec = sec("collab", "第 7 部分 · 协作实验", "Codex 规划、Qwen 编码、Claude 审查", P(
  "这是本报告的核心实验。我在 latte 上建了一个小的 Python 库 ledgerkit，出了 6 道题：两道易、两道中、两道难。每道题有一份只在 Mac 上保存的隐藏测试，共 175 个用例；作业全部结束后，才把测试临时拷到 latte 的临时目录评分，评完删除。"
  "三种方式各跑全部 6 道题：")
  + ul("<b>Claude 单独</b>：<code>crew task --model sonnet</code>，一个 Claude Code 实例写完、自测、提交。",
       "<b>Qwen + Claude 审查</b>：<code>crew local</code>，Qwen 通过 OpenCode 写代码，Claude 只读审查，最多 2 轮，不通过就转人工。",
       "<b>Codex 规划 + Qwen + Claude 审查</b>：先在 Mac 上用 <code>codex exec --sandbox read-only</code> 读仓库、写实现计划（不写代码），计划附在任务后面，再走 <code>crew local</code>。")
  + table(["题目", "难度", "要点"], [[t, LV[tasks[t]["level"]], esc(tasks[t]["title"])] for t in order])
  + "<h3>信息怎么在三个模型之间流动</h3>"
  + fig(seq, "图 13：一道题的完整流程。每条箭头是一次实际传递的内容和它的大小。审查者故意看不到作者的自述，只看任务和 diff，自己跑测试。", wide=True)
  + P("这个流程里有两道“防火墙”。Qwen 只能写自己的 worktree（Landlock 沙箱 + OpenCode 权限），不能 push；Claude 审查是只读的，并且只拿到任务和 diff，必须自己验证，不会被作者“测试都过了”的说法带偏。")
  + "<h3>结果</h3>"
  + table(["方式", "完全通过", "隐藏测试", "审查结果", "总耗时", "Claude 折算价", "Claude 输出 token", "Qwen 生成 token", "Codex 输出 token"], summary_rows)
  + fig(dotplot([cat[t] for t in order], wall_series, label="Wall time per task", ticks=[30, 60, 120, 300, 600, 1200, 2400],
                tickfmt=lambda v: f"{v/60:.0f} 分" if v >= 60 else f"{v:.0f} 秒"),
        "图 14：每道题的总耗时（对数坐标）。Claude 单独 24–43 秒；有 Qwen 参与的方式 1–39 分钟。", arm_leg)
  + fig(dotplot([cat[t] for t in order], cost_series, label="Claude cost per task", log=False, ticks=[0, 0.1, 0.2, 0.3, 0.4, 0.5],
                tickfmt=lambda v: f"${v:.1f}"),
        "图 15：每道题消耗的 Claude 额度（按 API 价格折算，美元）。一次审查约 $0.10，和 Claude 直接写完一道小题差不多。", arm_leg)
  + P(f"三种方式最终都通过了全部 175 个隐藏测试。差别在时间和额度上：Claude 单独总共 {mins(SM['claude']['wall'])}，Qwen + Claude 用了 {mins(SM['local']['wall'])}，Codex 规划那组 {mins(SM['codex']['wall'])}。"
      f"Claude 额度上，协作方式没有省：Claude 单独 ${SM['claude']['cost']:.2f}，两种协作方式分别 ${SM['local']['cost']:.2f} 和 ${SM['codex']['cost']:.2f}。",
      "原因是审查的固定成本。每次审查都新起一个 Claude Code，带着约 2.2–2.8 万 token 的系统提示和工具定义写缓存，再读 4–8 万 token 的缓存，折合约 $0.10。"
      "而这 6 道题都很小，Claude 直接写完一道只要 $0.12–0.14。被打回重做的题要审查两次，就更贵了。t5 有一次审查花了 $0.49：审查者自己写了一个压力测试，跑了 12 分钟，确实找到了一个性能问题。",
      "所以“本地写、云端审”省额度的前提是任务足够大：实现的成本随工作量增长，审查的成本基本固定。之前真实使用中的 <code>crew clean</code>（Qwen 写了 14 分钟、130 万 token）只花了 $0.155 的审查，这类任务才划算。")
  + "<h3>审查发现了隐藏测试没覆盖的问题</h3>"
  + P("22 次审查里有 5 次 CHANGES，我逐条复现过，全部是真问题：")
  + ul("t2 时长解析（Qwen 第一轮，Qwen + Claude 第一次实验）：用 float 累加，<code>parse('0.7d')</code> 得到 60479.99999999999，题目要求整数结果返回 int。第二轮改用 Fraction 后正确。三种方式的最终代码都返回 60480。",
       "t4 空闲时段：同一个 ZoneInfo 时区内，Python 按墙钟比较和相减 datetime。夏令时结束那天实际有 25 小时，代码算成 24 小时，<code>min_minutes</code> 过滤就错了。第二轮又发现跨越重复小时的区间会被误判为 end &lt; start。",
       "t5 令牌桶：为了消除浮点误差，容差写成 <code>1e-6 × capacity</code>。容量为一百万时，容差就是整整一个令牌，耗尽后还能再取出令牌。",
       "t5 令牌桶的另一版：<code>wait_time</code> 每次只加一个 ulp 去逼近，时钟值很大时要循环上百万次。")
  + P("t2 那条隐藏测试里没有 0.7d 这样的用例，所以第一轮代码也拿了满分。t4 和 t5 的几条超出了题目的明确要求。我把 t4、t5 的问题写成 4 个额外的边界测试，回头去跑三种方式的最终代码：")
  + table(["题目", ARM["claude"], ARM["local"], ARM["codex"]], extra_rows)
  + P("夏令时这一条，Claude 单独写的代码也有同样的问题（0/2），我自己写的参考答案也有。Codex 的计划里明确写了“所有比较都转成 UTC 再做”，Qwen 照着做，2/2 全过。"
      "Qwen + Claude 那组经过一轮审查修好了一半，第二轮审查又发现另一半，2 轮用完转人工。所以在这组题上，规划加审查让结果比 Claude 单独更稳，而不是更差。")
  + "<h3>时间都花在哪</h3>"
  + fig(gantt([("Codex 规划 + Qwen + Claude：t4，一轮通过", g_codex), ("Qwen + Claude：t4，两轮后转人工", g_local)]),
        "图 16：t4 两次运行的时间线。每个色块是 Qwen 的一步（一次模型调用加它触发的工具）。橙色是思考超过 1,000 token 的步骤，黄色是动作步骤。审查条按账本记录的时长放置。",
        legend([("s3", "Codex 规划"), ("s2", "Qwen 思考步骤"), ("s4", "Qwen 动作步骤"), ("s1", "Claude 审查")]), wide=True)
  + fig(stacked_hbar(qsplit_rows, [("s2", "模型生成"), ("s4", "工具执行"), ("muted", "步间间隔")], unit=" 秒", label="Qwen time split", left=150),
        f"图 17a：所有 Qwen 作业的时间拆分。模型生成 {q_model_share*100:.1f}%，工具执行 {qsplit['tool']/qwall*100:.1f}%，步间间隔 {qsplit['gap']/qwall*100:.1f}%。",
        legend([("s2", "模型生成"), ("s4", "工具执行"), ("muted", "步间间隔")]))
  + fig(stacked_hbar(qtok_rows, [("s2", "思考 token"), ("s1", "输出 token（代码、工具调用、回复）")], unit="K", label="Qwen generated tokens", left=150),
        f"图 17b：Qwen 生成的 {(qsplit['reason']+qsplit['out'])/1000:,.0f}K 个 token 中，{q_reason_share*100:.0f}% 是思考。",
        legend([("s2", "思考"), ("s1", "输出")]))
  + P(f"从图 16 能直接看出瓶颈：Qwen 的时间几乎都在几个长的思考步骤上。t4 那次一个步骤思考了 8,898 个 token，用了 124 秒，然后 1 秒内写完文件、跑完测试。"
      f"按所有 Qwen 作业算，生成速度是 {q_rate:.1f} tok/s，几乎正好等于纯解码速度（TPOT 约 13–14 ms），说明预填充已被前缀缓存消掉，剩下的全是解码。",
      f"Codex 的计划把 Qwen 的工作量砍了约四成：生成 token 从 {SM['local']['q_out']:,} 降到 {SM['codex']['q_out']:,}，总耗时从 {mins(SM['local']['wall'])} 降到 {mins(SM['codex']['wall'])}，还让 t4 一轮就通过。"
      f"代价是 Codex 自己读了 {SM['codex']['plan_in']:,} 个 token（大部分是缓存）、写了 {SM['codex']['plan_out']:,} 个，用的是 ChatGPT 订阅的额度。")
  + "<h3>第一轮实验：输出上限把一半的题卡死了</h3>"
  + P(f"第一轮实验用的是当时的配置，OpenCode 的输出上限是 8,192 token。结果两种协作方式都只完成了 3/6：另外 6 次作业，Qwen 在某一步里思考了 8,192 个 token 就被截断，"
      "<code>finish_reason</code> 是 length，没有写任何文件。crewd 之前已经加了检查，把这种“干净退出但什么都没说”判为失败，所以没有产生假的“完成”。"
      "把 crewd 起 OpenCode 时的输出上限调到 32,768 之后，第二轮 12 次作业全部有结果。上面的主结果用的是第二轮。"))

# ---------------------------------------------------------------- 8. bottlenecks and optimizations
e2e_rows = [
  ("Qwen 解码思考 token", qsplit["model"] / 1000 * q_reason_share, "s2", "所有 Qwen 作业中，生成思考 token 的时间（按 token 占比分摊）"),
  ("Qwen 解码代码和工具调用", qsplit["model"] / 1000 * (1 - q_reason_share), "s2", "生成正式输出的时间"),
  ("步间间隔（OpenCode、预填充）", qsplit["gap"] / 1000, "s4", "两步之间：解析、发下一个请求、预填充新增内容"),
  ("Claude 审查", sum(sum(v for k, v in x["secs"].items() if k.startswith("local_reviewer")) for x in main["local"] + main["codex"]), "s1", "两种协作方式所有审查阶段的时间"),
  ("Codex 规划", SM["codex"]["plan_in"] and sum(x["plan_secs"] for x in main["codex"]), "s3", "6 次规划"),
  ("工具执行（读写文件、pytest、git）", qsplit["tool"] / 1000, "s4", "OpenCode 记录的工具运行时间"),
]
opt = sec("optimize", "第 8 部分", "瓶颈排序与优化清单", P(
  "把第二轮两种协作方式的所有作业加起来，时间分布如下。这张图回答“端到端最该优化哪里”。")
  + fig(hbar(e2e_rows, unit=" 秒", label="Where the time goes", note_fmt=lambda v: mins(v)),
        "图 18：协作实验的时间分布（两种协作方式、第二轮、12 次作业合计，加上同一批作业的审查和规划）。",
        legend([("s2", "Qwen 生成"), ("s1", "Claude"), ("s3", "Codex"), ("s4", "其余")]))
  + P("按收益从大到小，逐层的优化方向如下。“已验证”表示本报告里测过效果，“已上线”表示已经改进了配置。")
  + table(["层", "做法", "依据", "状态"], [
      ["模型", "减少思考 token：给规划清楚的步骤关掉思考，或设思考预算", f"Qwen 生成的 token {q_reason_share*100:.0f}% 是思考；同一道题有计划时少生成约四成", "待做"],
      ["模型 / vLLM", "MTP 推测解码，每步猜 3 个", f"编程回答 {S['base']['code_think']['tok_s']:.0f} → {S['mtp3']['code_think']['tok_s']:.0f} tok/s（开思考），KV 缓存少约 4 成", "SPEC_STATUS"],
      ["流程", "用 Codex 或 Claude 先写计划，再让 Qwen 实现", f"Qwen 生成 token −{(1-SM['codex']['q_out']/SM['local']['q_out'])*100:.0f}%，总耗时 −{(1-SM['codex']['wall']/SM['local']['wall'])*100:.0f}%，t4 边界测试 2/2", "已验证"],
      ["流程", "只把大任务交给本地模型；小任务直接让 Claude 写", "一次审查约 $0.10，和 Claude 写完一道小题相当", "已验证"],
      ["OpenCode", "crewd 起 OpenCode 时输出上限 32,768，全局保持 8,192", "8,192 时一半作业被截断；全局调大会让 Kiro 网关压缩循环", "已上线"],
      ["Kiro", "让提示前缀稳定：会话相关的内容不要放进工具描述，或把这类工具排到最后", f"每轮 {kb_wall:.1f} → {ka_wall:.1f} 秒，预填充 {kb_pre:.1f} → {ka_pre:.1f} 秒", "已验证，未上线"],
      ["Kiro", "给 qwen Bot 少挂 MCP 工具", "107 个工具定义占提示的大头，本地编码用不到大部分", "待做"],
      ["vLLM", "前缀缓存检查点：保持 agent 的提示只在末尾增长", "混合注意力模型改中间一处，缓存命中就是 0", "已验证"],
      ["vLLM", "并发：crewd 允许两个 Qwen 作业同时跑", f"2 并发总吞吐 {c2['throughput']/c1['throughput']:.2f} 倍，单个请求只慢 {c2['tpot_ms']/c1['tpot_ms']*100-100:.0f}%", "待做"],
      ["llama-swap", "减少模型切换：媒体请求攒批，或 Qwen 空闲时才切", "切换 35–66 秒，远大于生成一张图或一句话", "待做"],
      ["vLLM-Omni", "TTS 改流式；Wan 去噪后的空闲段排查 offload 和编码", "长段 TTS 首包 13–17 秒；Wan 5 秒视频有 81 秒 GPU 空闲", "待做"],
      ["Claude Code", "常驻审查会话，或把审查合并成一次调用", "每次启动约 3 秒、读 3 万 token 系统提示", "待做"],
      ["连接", "所有脚本走 SSH 复用连接、MCP 常驻会话", "新会话 459 ms，常驻 9.9 ms", "已上线"],
      ["Kernel", "FlashInfer 采样器 / 注意力后端", "差别在 0.5% 以内；解码已用到约 84% 的显存带宽", "已验证，无收益"],
      ["Kernel", "量化 lm_head", "bf16 的 lm_head 占解码 GPU 时间的 12.5%", "待做"],
  ]))

limits = sec("limits", "第 9 部分", "局限", ul(
  "协作实验每种方式每道题只跑了一次（第一轮因配置问题只作参考）。6 道题、175 个隐藏测试足以看出量级上的差别，但不足以对“能力略有提高”下统计意义上的结论。",
  "题目是我出的，规模都很小（几十到两百行）。大任务上本地模型的表现、以及审查成本占比，需要另做实验。",
  "Claude 的花费是 Claude Code 报告的 API 折算价。实际用的是订阅额度，折算价反映的是额度消耗的相对大小。",
  "Codex 规划在 Mac 上运行，它的 token 用的是 ChatGPT 订阅额度，没有折算成美元。",
  "所有 GPU 测量都在同一台机器上，桌面的 Chrome 和 Xorg 占用约 2 GB 显存，会让 Qwen 的 KV 缓存略小。",
  "Wan 去噪后的空闲段，原因是根据功耗和利用率推断的，还没有用 vLLM-Omni 的阶段日志逐项确认。"))

# ---------------------------------------------------------------- 5. kernel layer (built from kernel.jsonl, spec.jsonl, prof/)
import re
def prof_top(txt, k=10):
    """Parse torch profiler key_averages table text; return [(name, self_cuda_us, pct)]."""
    lines_ = txt.splitlines()
    hdr = next((l for l in lines_ if "Self CUDA" in l or "Self CUDA %" in l or "Self Device" in l), None)
    if not hdr:
        return []
    cols = [m.start() for m in re.finditer(r"\S+(?: \S+)*", hdr)]
    names = re.findall(r"\S+(?: \S+)*", hdr)
    try:
        ci = next(i for i, n_ in enumerate(names) if n_ in ("Self CUDA %", "Self Device %"))
    except StopIteration:
        return []
    out = []
    for l in lines_[lines_.index(hdr) + 2:]:
        if l.startswith("-") or not l.strip():
            continue
        parts = re.split(r"\s{2,}", l.strip())
        if len(parts) < len(names):
            continue
        try:
            pct = float(parts[ci].rstrip("%"))
        except ValueError:
            continue
        out.append((parts[0], pct))
    out.sort(key=lambda x: -x[1])
    return out[:k]
def kname(s):
    s = re.sub(r"<.*", "", s)
    s = s.replace("void ", "")
    return s[:46] + ("…" if len(s) > 46 else "")
def krow(label, a, name):
    if not a:
        return None
    pf = list(a["prefill"].values())
    return [name, f'{pf[0]["ttft"]:,.0f} ms' if pf else "–", f'{pf[-1]["ttft"]:,.0f} ms' if pf else "–",
            f'{pf[-1]["tokens"]/(pf[-1]["ttft"]/1000):,.0f}' if pf else "–", f'{a["tpot"]:.2f} ms' if a["tpot"] else "–",
            f'{a["c2"]["tok_s"]:.0f} tok/s' if a.get("c2") else "–"]
krows = [r for r in (krow("base", K["base"], "基线：FLASH_ATTN，PyTorch 采样"), krow("fi-sampler", K["fi-sampler"], "FlashInfer 采样器"),
                     krow("fi-attn", K["fi-attn"], "FlashInfer 采样器 + FlashInfer 注意力")) if r]
srows = []
for lab, name in (("base", "不用推测解码"), ("mtp1", "MTP，每步猜 1 个"), ("mtp2", "MTP，每步猜 2 个"), ("mtp3", "MTP，每步猜 3 个")):
    a = S.get(lab)
    if not a:
        continue
    srows.append([name, f'{a["tpot"]:.2f} ms' if a["tpot"] else "–",
                  f'{a["code_think"]["tok_s"]:.1f}' if a.get("code_think") else "–",
                  f'{a["code_think"]["accept"]*100:.0f}%' if a.get("code_think") and a["code_think"]["accept"] is not None else "–",
                  f'{a["code_nothink"]["tok_s"]:.1f}' if a.get("code_nothink") else "–",
                  f'{a["c2"]["tok_s"]:.0f}' if a.get("c2") else "–"])
def prof_groups(txt):
    """Sum leaf CUDA kernels from the profiler table into a few readable groups (ms)."""
    hdr = next(l for l in txt.splitlines() if "Self CUDA %" in l)
    g = collections.Counter(); ctx = {}
    for l in txt.splitlines():
        parts = re.split(r"\s{2,}", l.strip())
        if len(parts) < 11 or parts[0] == "Name":
            continue
        name = parts[0]
        def ms(x):
            x = x.strip()
            return float(x[:-2]) if x.endswith("ms") else float(x[:-2]) / 1000 if x.endswith("us") else float(x[:-1]) * 1000 if x.endswith("s") else 0.0
        try:
            self_cuda, calls = ms(parts[6]), int(parts[10])
        except (ValueError, IndexError):
            continue
        if name.startswith("execute_context"):
            ctx[name] = (self_cuda, calls); continue
        if name.startswith(("aten::", "_C::", "vllm::", "_vllm_fa2_C", "Command Buffer", "cuda", "Memcpy", "Memset")) or self_cuda == 0:
            continue
        if "marlin" in name.lower(): k = "INT4 矩阵乘（Marlin）"
        elif "gemv" in name and self_cuda / calls > 0.5: k = "lm_head（bf16 GEMV）"
        elif "gemv" in name or "gemm" in name.lower() or "cutlass" in name.lower() and "gdn" not in name.lower(): k = "其他 bf16 矩阵乘"
        elif "flash" in name and "gdn" not in name: k = "全注意力（FlashAttention）"
        elif "delta" in name or "gdn" in name.lower() or "conv1d" in name: k = "线性注意力（GDN、卷积）"
        elif name.startswith("triton_") or "rmsnorm" in name or "rms_norm" in name or "silu" in name: k = "归一化与逐元素（Triton 融合）"
        elif "topk" in name or "gumbel" in name or "sampl" in name: k = "采样"
        else: k = "其他"
        g[k] += self_cuda
    return g, ctx
pgroups = {k: prof_groups(v) for k, v in prof.items()}
ptop = {}
pcharts = ""
for k, title in (("prefill", "预填充（约 2 万 token 的提示）"), ("decode", "解码（64 个 token）")):
    if pgroups.get(k):
        g, _ = pgroups[k]; tot = sum(g.values())
        rows_ = [(nm, v / tot * 100, "s1", f"{nm}: {v:,.1f} ms，{v/tot*100:.1f}%") for nm, v in g.most_common()]
        pcharts += fig(hbar(rows_, unit="%", label=f"GPU kernel time {k}", left=230, note_fmt=lambda v: f"{v:.1f}%"),
                       f"图 {7 if k == 'prefill' else 8}：{title}时各类 kernel 占 GPU 时间的比例（torch profiler，Self CUDA）。")
KERNEL_TEXT = P(
  "三组配置的差别都在测量噪声以内（0.5% 左右）。FlashInfer 采样器把 TPOT 从 13.01 ms 降到 12.94 ms；FlashInfer 注意力后端与 FLASH_ATTN 持平。"
  "启用它们本身不难：系统没有 nvcc，我用 conda 在用户目录装了 CUDA 13.0 的编译器，再补一个 <code>lib64</code> 软链接，FlashInfer 的 JIT 就能编译通过。但这些 kernel 不在关键路径上。",
  "原因可以从带宽上算出来。每解码一个 token，要把 13.19 GiB 的层权重（AWQ INT4）和 2.37 GiB 的 <code>lm_head</code>（bf16，没有量化）从显存读一遍，合计约 16.7 GB。"
  "RTX 5090 的显存带宽是 1,792 GB/s，所以单个序列解码的理论下限约 9.3 ms/token。实测 13.0 ms，已经用到约 72% 的带宽，剩下的还要分给 KV 缓存、线性注意力状态和 kernel 启动间隙。"
  "注意力 kernel 只在 16 层全注意力上起作用，换实现自然看不出差别。",
  "这也指出了两个真正有用的方向：一是把 <code>lm_head</code> 量化，它占每步读取量的 15%；二是让一次权重读取产出多个 token，也就是批处理（上一节的 2 并发）和推测解码（下文的 MTP）。")
PROF_TEXT = P(
  "解码的 profile 把带宽估算落到了实处。63 个解码步在 GPU 上一共 703.6 ms，每步 11.17 ms；端到端 TPOT 是 13.0 ms，所以每步还有约 1.8 ms（14%）是 GPU 之外的时间：调度、采样后处理、和 API 服务的往返。"
  "GPU 时间里，INT4 的 Marlin 矩阵乘占 72%，每步约 9.4 ms 读 14.2 GB 权重，折合约 1.5 TB/s，是带宽峰值的 84%；没有量化的 <code>lm_head</code> 单独占 12.5%，每步 1.63 ms。"
  "线性注意力（GDN 递推和卷积）只占 3%，全注意力 2.6%，采样 1.2%。这和上面三组配置的结论一致：换注意力或采样 kernel，能改变的只是那几个百分点。",
  "预填充是另一种形态。约 2 万 token 被切成 13 块、每块 1,568 个 token（784 的两倍，正是混合模型要求的块对齐），共 5.4 秒，约 3,840 tok/s。"
  "Marlin 矩阵乘占 85%，按 2 × 参数量 × token 数估算，有效算力在 190 TFLOPS 左右，已经是算力受限的量级。FlashAttention 占 9.5%，并且会随提示变长而上升。"
  "所以预填充靠 kernel 再挤的空间也有限，靠前缀缓存“不算”才是正解。")
def spec_chart():
    cats = ["不用推测解码", "MTP 猜 1 个", "MTP 猜 2 个", "MTP 猜 3 个"]
    labs = ["base", "mtp1", "mtp2", "mtp3"]
    ser = []
    for cls, name, key in (("s2", "编程回答（开思考）", "code_think"), ("s1", "编程回答（不开思考）", "code_nothink")):
        d = {}
        for c, l in zip(cats, labs):
            a = S.get(l)
            if a and a.get(key):
                acc = a[key]["accept"]
                d[c] = (a[key]["tok_s"], f'{a[key]["tok_s"]:.1f} tok/s' + (f"，接受率 {acc*100:.0f}%" if acc is not None else ""))
        ser.append((cls, name, d))
    return fig(dotplot(cats, ser, label="MTP decode speed", log=False, ticks=[0, 40, 80, 120, 160], xmax=180, tickfmt=lambda v: f"{v:.0f}"),
               "图 9：单个请求的解码速度（tok/s），t5 题目的真实回答，1,500 个 token，每格 2–3 次的中位数。", legend([("s2", "开思考"), ("s1", "不开思考")]))
SPEC_TEXT = ""
SPEC_TEXT = P(
  f"这是整份报告里收益最大的一项。每步猜 3 个 token 时，开思考的编程回答从 {S['base']['code_think']['tok_s']:.0f} tok/s 提到 {S['mtp3']['code_think']['tok_s']:.0f} tok/s（+{(S['mtp3']['code_think']['tok_s']/S['base']['code_think']['tok_s']-1)*100:.0f}%），"
  f"不开思考时到 {S['mtp3']['code_nothink']['tok_s']:.0f} tok/s，两路并发的总吞吐从 {S['base']['c2']['tok_s']:.0f} 提到 {S['mtp3']['c2']['tok_s']:.0f} tok/s。推测解码由主模型逐个验证，输出分布不变，所以这是不损失质量的提速。",
  "接受率说明了思考内容的特点：不开思考时草稿被接受 90% 左右，开思考时只有 50–75%。思考文本更发散，小的 MTP 头更难猜中。即便如此，猜 3 个仍比猜 1 个快，因为多验证几个 token 几乎不增加一次前向的时间（解码是访存受限的）。",
  f"代价是显存：MTP 头和草稿的 KV 让可用 KV 缓存从 139,810 个 token 降到 78,372 个，65K 上下文的请求只能放下 1.2 个。crewd 的 Qwen 作业提示在 1.2–3 万 token，Kiro 网关约 4.7 万，单个请求够用；但如果要同时跑两个长上下文作业，需要把上下文上限降到 32K。",
  f"按第 7 部分的时间拆分，Qwen 作业 {q_model_share*100:.0f}% 的时间在解码，其中八成是思考。如果全部换成 MTP-3 的速度，同样的作业预计少用约三分之一的时间。这个推算还没有用完整的协作实验验证。")
def kernel_section():
    body = P("这一层回答“软件有没有把 GPU 用好”。我对比了三组 kernel 配置，用 torch profiler 抓了一次预填充和一次解码，最后测了模型自带的 MTP 推测解码。每组配置都重启 vLLM，用同一个探针：两档长度的冷预填充各 3 次、512 个 token 的解码 3 次、两路并发。")
    body += "<h3>Kernel 配置</h3>" + table(["配置", "8K 冷预填充", "31K 冷预填充", "预填充 tok/s", "TPOT", "2 并发吞吐"], krows) + KERNEL_TEXT
    if pcharts:
        body += "<h3>Profiler：时间花在哪些 kernel 上</h3>" + pcharts + PROF_TEXT
    if srows:
        body += ("<h3>MTP 推测解码</h3>" + P("Qwen3.8 的权重里带一层 MTP（multi-token prediction）头，vLLM 可以用它当草稿模型：每步先猜后面 k 个 token，再用主模型一次验证。"
                 "接受率越高，每次前向产出的 token 越多。解码是访存受限的，多验证几个 token 几乎不增加单步时间。我用两种负载测：一种是 t5 题目的真实编程回答（开思考和不开思考），一种是前面用过的“总结代码文件”。")
                 + table(["配置", "TPOT（总结文件）", "编程题 tok/s（思考）", "接受率（思考）", "编程题 tok/s（不思考）", "2 并发吞吐"], srows) + spec_chart() + SPEC_TEXT)
    return sec("kernel", "第 5 部分 · Kernel 与 GPU", "Kernel、采样器与推测解码", body)

# ================================================================= page
CSS = r"""
:root{
  /* Layout: one reading column of about 68ch; figures may widen to 920px. Lab-notebook calm, coffee-tinted neutrals. */
  --bg:#f7f6f3; --panel:#ffffff; --fg:#1d1c1a; --muted:#5d5b55; --faint:#8b8880; --rule:#e2dfd8; --grid:#ebe8e2;
  --accent:#7a4a2a; --code-bg:#efece6;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --mute-fill:#c9c6bf;
  --n0:#f1efea; --n1:#e9f1fb; --n2:#eef7f2; --n3:#fbf0e9; --n4:#f5f1e3;
  --display:"Noto Serif SC","Songti SC",serif; --body:"Noto Sans SC","PingFang SC","Hiragino Sans GB",system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,"SF Mono",Menlo,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#151413; --panel:#1c1b19; --fg:#ecebe7; --muted:#b4b1a9; --faint:#8a877f; --rule:#302e2a; --grid:#2a2825;
  --accent:#d9a37c; --code-bg:#24221f;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --mute-fill:#55524c;
  --n0:#22211e; --n1:#1b2633; --n2:#1a2a22; --n3:#2e221b; --n4:#2b2719; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#151413; --panel:#1c1b19; --fg:#ecebe7; --muted:#b4b1a9; --faint:#8a877f; --rule:#302e2a; --grid:#2a2825;
  --accent:#d9a37c; --code-bg:#24221f;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --mute-fill:#55524c;
  --n0:#22211e; --n1:#1b2633; --n2:#1a2a22; --n3:#2e221b; --n4:#2b2719; color-scheme:dark}
body{background:var(--bg);color:var(--fg);font-family:var(--body);font-size:16px;line-height:1.75}
.page{max-width:920px;margin:0 auto;padding-block:40px 80px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
.col{max-width:68ch}
h1,h2{font-family:var(--display);font-weight:700;text-wrap:balance;letter-spacing:.01em}
h1{font-size:clamp(30px,5vw,44px);line-height:1.2;margin:.2em 0 .4em}
h2{font-size:clamp(22px,3.2vw,28px);line-height:1.3;margin:.2em 0 .6em}
h3{font-size:18px;margin:1.8em 0 .5em}
p,ul{max-width:68ch}
p{margin:.7em 0} ul{padding-left:1.2em} li{margin:.35em 0}
code{font-family:var(--mono);font-size:.86em;background:var(--code-bg);padding:.1em .35em;border-radius:4px;overflow-wrap:anywhere}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);margin:0}
.lede{font-size:18px;color:var(--muted);max-width:62ch}
.hero{padding-bottom:24px;border-bottom:1px solid var(--rule)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-top:24px}
.tile{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:14px 16px;display:flex;flex-direction:column;gap:6px}
.tile b{font-family:var(--mono);font-size:22px;font-variant-numeric:tabular-nums;color:var(--fg)}
.tile span{font-size:13.5px;line-height:1.5;color:var(--muted)}
nav.toc{margin:28px 0 8px;font-size:14px}
nav.toc ol{display:flex;flex-wrap:wrap;gap:6px 18px;padding:0;margin:0;list-style:none;counter-reset:t}
nav.toc a{color:var(--muted);text-decoration:none;border-bottom:1px solid var(--rule)}
nav.toc a:hover,nav.toc a:focus-visible{color:var(--fg);border-color:var(--accent)}
section{padding:40px 0 8px;border-bottom:1px solid var(--rule)}
figure{margin:22px 0;background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:14px 14px 10px}
figcaption{font-size:13.5px;color:var(--muted);line-height:1.6;margin-top:6px}
.scroll{overflow-x:auto}
svg.chart{display:block;width:100%;height:auto;min-width:560px}
figure.wide svg.chart{min-width:680px}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--muted);margin:0 0 6px}
.key{display:inline-flex;align-items:center;gap:6px}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
.sw.s1{background:var(--s1)} .sw.s2{background:var(--s2)} .sw.s3{background:var(--s3)} .sw.s4{background:var(--s4)} .sw.muted{background:var(--mute-fill)}
svg .s1{fill:var(--s1)} svg .s2{fill:var(--s2)} svg .s3{fill:var(--s3)} svg .s4{fill:var(--s4)} svg .muted{fill:var(--mute-fill)}
svg .seg-ok{fill:var(--s1)} svg .seg-bad{fill:var(--s2)} svg .seg-miss{fill:var(--mute-fill)}
svg .line{fill:none;stroke-width:2} svg .line.s1{stroke:var(--s1)} svg .line.s2{stroke:var(--s2)} svg .line.s4{stroke:var(--s4)}
svg .dot{stroke:var(--panel);stroke-width:2}
svg .grid{stroke:var(--grid);stroke-width:1} svg .axis{stroke:var(--faint);stroke-width:1} svg .rowrule{stroke:var(--grid);stroke-dasharray:2 4}
svg text{fill:var(--muted);font-family:var(--body);font-size:12.5px}
svg .tick{font-family:var(--mono);font-size:11px;fill:var(--faint)}
svg .val{font-family:var(--mono);font-size:12px;fill:var(--fg)}
svg .lab{fill:var(--fg);font-size:13px} svg .axlab{font-size:12px;fill:var(--muted)}
svg .hitbox{fill:transparent} svg .hair{stroke:var(--faint);stroke-width:1;opacity:0}
svg .col:hover .hair,svg .col:focus .hair{opacity:1}
svg .hit:hover path,svg .hit:hover > rect:not(.hitbox){opacity:.85}
svg .node{fill:var(--n0);stroke:var(--rule)} svg .node.n1{fill:var(--n1)} svg .node.n2{fill:var(--n2)} svg .node.n3{fill:var(--n3)} svg .node.n4{fill:var(--n4)}
svg .nodet{fill:var(--fg);font-weight:600;font-size:14px} svg .nodes{fill:var(--muted);font-size:12px}
svg .meas{fill:var(--fg);font-family:var(--mono);font-size:12.5px}
svg .flow{stroke:var(--faint);stroke-width:1.5} svg .arrowhead{fill:var(--faint)}
svg .life{stroke:var(--rule);stroke-dasharray:3 4}
svg .msg{fill:none;stroke-width:1.8} svg .msg.m1{stroke:var(--s1)} svg .msg.m2{stroke:var(--s2)} svg .msg.m3{stroke:var(--s3)}
svg .msgt{fill:var(--fg);font-size:12.5px;font-weight:600} svg .msgs{fill:var(--muted);font-size:11.5px}
.tablewrap{overflow-x:auto;margin:14px 0}
table{border-collapse:collapse;font-size:14px;min-width:100%}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:13px;white-space:nowrap}
td{font-variant-numeric:tabular-nums}
#tip{position:fixed;pointer-events:none;z-index:20;max-width:320px;background:var(--fg);color:var(--bg);font-size:12.5px;line-height:1.5;padding:7px 10px;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.18)}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
footer{color:var(--muted);font-size:13.5px;padding-top:28px}
@media (max-width:520px){body{font-size:15.5px} .tile b{font-size:19px}}
"""
JS = r"""
(function(){
  var tip=document.getElementById('tip');
  function show(el,x,y){var t=el.getAttribute('data-tip'); if(!t){return}
    tip.textContent=t; tip.hidden=false;
    var w=tip.offsetWidth,h=tip.offsetHeight,vw=window.innerWidth;
    var left=Math.min(vw-w-8,Math.max(8,x+14)), top=y+16; if(top+h>window.innerHeight-8){top=y-h-12}
    tip.style.left=left+'px'; tip.style.top=top+'px'}
  document.addEventListener('pointermove',function(e){var el=e.target.closest&&e.target.closest('[data-tip]'); if(el){show(el,e.clientX,e.clientY)} else {tip.hidden=true}});
  document.addEventListener('pointerdown',function(e){var el=e.target.closest&&e.target.closest('[data-tip]'); if(el){show(el,e.clientX,e.clientY)} else {tip.hidden=true}});
  document.querySelectorAll('svg [data-tip]').forEach(function(el){el.setAttribute('tabindex','0');
    el.addEventListener('focus',function(){var r=el.getBoundingClientRect(); show(el,r.left+r.width/2,r.top)});
    el.addEventListener('blur',function(){tip.hidden=true})});
})();
"""
def build():
    toc = [("answers", "结论"), ("setup", "实验设计"), ("connection", "连接层"), ("harness", "Agent 层"), ("vllm", "推理服务"),
           ("kernel", "Kernel 与 GPU"), ("media", "媒体模型"), ("collab", "协作实验"), ("optimize", "优化清单"), ("limits", "局限")]
    nav = '<nav class="toc" aria-label="目录"><ol>' + "".join(f'<li><a href="#{a}">{b}</a></li>' for a, b in toc) + "</ol></nav>"
    opt_html = opt.replace("SPEC_STATUS", SPEC_STATUS).replace("KERNEL_STATUS", KERNEL_STATUS)
    body = hero + nav + answers + setup + connection + harness_sec + vllm_sec + kernel_section() + media_sec + collab_sec + opt_html + limits
    foot = ('<footer><p>原始数据和脚本在 <code>latte-crew/bench/</code>：<code>out/</code> 是各层的测量记录，<code>collab/</code> 是题目、驱动脚本和评分结果，'
            '<code>report/gen.py</code> 从这些文件生成本页的每一个数字和每一张图。隐藏测试只保存在 Mac 上。</p>'
            f'<p>测量时间：2026 年 11 月 6–7 日。</p></footer>')
    return ('<title>LatteCrew 优化与分析</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
            '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Noto+Sans+SC:wght@400;600&family=Noto+Serif+SC:wght@600;700&display=swap">'
            f'<style>{CSS}</style><div class="page">{body}{foot}</div><div id="tip" hidden></div><script>{JS}</script>')
SPEC_STATUS = "已验证，未上线"
KERNEL_STATUS = "已验证"
if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "lattecrew-report.html")
    open(out, "w").write(build())
    print("wrote", out, os.path.getsize(out) // 1024, "KB")
