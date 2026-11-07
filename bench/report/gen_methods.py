#!/usr/bin/env python3
"""Build the methods page: how every LatteCrew measurement was implemented, with the core code quoted from the real scripts."""
import html, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import gen  # reuses CSS, tooltip JS and the stack diagram helper
from diagrams import stack

B = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
esc = lambda s: html.escape(str(s), quote=True)

def snip(path, start, end=None, n=None):
    """Quote lines of a real script, from the first line containing `start` up to (not including) `end`, or n lines."""
    lines = open(os.path.join(B, path)).read().splitlines()
    i = next(k for k, l in enumerate(lines) if start in l)
    if end is not None:
        j = next(k for k in range(i + 1, len(lines)) if end in lines[k])
    else:
        j = min(len(lines), i + (n or 20))
    return lines[i:j], i + 1

def code(path, start, end=None, n=None, note=""):
    body, line = snip(path, start, end, n)
    return (f'<figure class="code"><figcaption><code>{esc(os.path.normpath(os.path.join("bench", path)))}</code> · 第 {line} 行起{(" · " + note) if note else ""}</figcaption>'
            f'<pre><code>{esc(chr(10).join(body))}</code></pre></figure>')

def raw(text, cap):
    return f'<figure class="code"><figcaption>{cap}</figcaption><pre><code>{esc(text.strip())}</code></pre></figure>'

def card(rows):
    return '<dl class="spec">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"

def sec(id_, eyebrow, title, body):
    return f'<section id="{id_}"><p class="eyebrow">{esc(eyebrow)}</p><h2>{esc(title)}</h2>{body}</section>'

P = gen.P
ul = gen.ul

# ------------------------------------------------------------------ map of probes
layers = [
    ("你 / Slack / 终端", "测量起点", ["stack_probe.py 在 Mac 上计时"], "n0"),
    ("Kiro Crew 网关", "kirocrew chat", ["Kiro 轮次 + /metrics 差值", "capture_proxy.py 抓请求体"], "n1"),
    ("Agent harness", "Claude Code / OpenCode / Codex", ["harness_probe.py：一句话任务", "作业日志：逐步事件与时间戳"], "n1"),
    ("MCP over SSH", "crew.py mcp", ["stack_probe.py：JSON-RPC 直连", "新会话 / 复用 / 常驻"], "n2"),
    ("crewd", "作业、worktree、账本", ["ledger.jsonl：每阶段秒数和花费", "round_heads：每轮 commit"], "n2"),
    ("llama-swap", ":8100", ["llm_probe.py paths：三条路径对比", "media_probe.py：首个请求 = 切换成本"], "n3"),
    ("vLLM / vLLM-Omni", ":8101–8104", ["llm_probe.py grid / conc；kprobe 系列", "/metrics 计数器与直方图"], "n3"),
    ("RTX 5090", "GPU", ["gpu_fast.sh：nvidia-smi 250 ms", "torch profiler；safetensors 字节数"], "n4"),
]

intro = f'''
<header class="hero">
  <p class="eyebrow">LatteCrew 系列 · 实验方法附录</p>
  <h1>LatteCrew 实验方法</h1>
  <p class="lede">这一页记录《LatteCrew：优化与分析》里每个数字是怎么得到的：测什么、在哪台机器上跑、怎么计时、怎么算，以及脚本的核心代码。代码块都直接摘自 <code>latte-crew/bench/</code> 里实际运行的脚本。</p>
</header>'''

principles = sec("principles", "总则", "所有实验共用的做法", ul(
    "<b>一层一测。</b>每个探针只经过它要测的那一层和它下面的层，尽量不让上层的开销混进来。比如测 vLLM 时直连 8101 端口，不经过 llama-swap 和 SSH。",
    "<b>固定输入，重复取中位数。</b>同一个输入重复 4–30 次，报告中位数，必要时附 p95 和最小值。中位数对偶发的网络抖动不敏感。",
    "<b>客户端计时和服务端计数器互相印证。</b>客户端用 <code>time.perf_counter()</code> 计时；服务端在请求前后各读一次 vLLM 的 Prometheus <code>/metrics</code>，取差值，得到这一个请求的预填充时间、解码时间、缓存命中 token 数。两边对得上，才采用。",
    "<b>强制冷启动。</b>需要测“不命中缓存”时，在提示开头放一个随机 uuid，让前缀缓存无法复用。",
    "<b>固定输出长度。</b>用 <code>ignore_eos: true</code> 和 <code>max_tokens</code> 让每次输出同样多的 token，TPOT 才能比较。",
    "<b>独占 GPU。</b>会改动 GPU 状态的实验（重启 vLLM、媒体模型）先拿 <code>~/latte-models/gpu.lock</code> 上的 <code>flock</code>，和 media-bot、crewd 用同一把锁，避免 Bot 在测量中途切换模型。",
    "<b>结果全部落盘。</b>每个探针把一行 JSON 追加到 <code>bench/out/*.jsonl</code>，报告生成器 <code>report/gen.py</code> 只从这些文件读数，不手抄数字。")
    + '<figure><div class="scroll">' + stack(layers) + '</div><figcaption>图 1：每一层用哪个探针、读哪些数据。</figcaption></figure>')

# ------------------------------------------------------------------ 1 connection
connection = sec("connection", "实验 1 · 连接层", "SSH、MCP、scp 的延迟", card([
    ("脚本", "<code>bench/stack_probe.py</code>，在 Mac 上运行"),
    ("测什么", "SSH 新建连接和复用连接；MCP 三种调用方式；复用连接下 scp 1 MB"),
    ("重复次数", "SSH 各 15 次，MCP 新会话和复用各 10 次，常驻会话 30 次，scp 8 次"),
    ("输出", "<code>out/stack.jsonl</code>：每项的 p50、p95、最小值和所有样本"),
]) + P("计时的核心是一个通用函数：执行 n 次，记录每次的毫秒数，算中位数和 p95。")
  + code("stack_probe.py", "def timeit", "SSH = ")
  + P("SSH 复用靠 OpenSSH 的 ControlMaster：先建一条后台主连接，之后的 <code>ssh</code> 通过同一个 socket 发起，不再握手。")
  + code("stack_probe.py", "SSH = [", "INIT = ")
  + P("MCP 不经过任何客户端库，直接把 JSON-RPC 的两行消息写进 <code>crew.py mcp</code> 的标准输入：一行 <code>initialize</code>，一行 <code>tools/call</code>。"
      "“新会话”每次都新开 SSH 并启动 MCP 进程；“常驻会话”只启动一次，之后每次只写一行调用、读一行结果，这和 Bot 持有 MCP 连接的方式一样。")
  + code("stack_probe.py", "INIT = ", "timeit(\"scp_1MB\"")
  + P("SSH 隧道和 llama-swap 的开销不在这个脚本里测，而是在实验 3 里比较三条路径的 TTFT。"))

# ------------------------------------------------------------------ 2 harness
harness = sec("harness", "实验 2 · Agent 层", "Claude Code、OpenCode 和 Kiro 网关的固定开销", card([
    ("脚本", "<code>bench/harness_probe.py</code>（latte 上）；Kiro 部分是同样思路的内联脚本，结果在 <code>out/kiro.jsonl</code>"),
    ("输入", "同一句提示 <code>reply with exactly: ok</code>，让模型几乎不用生成，测到的就是 harness 自己的开销"),
    ("重复次数", "各 4 次，第 1 次含冷缓存，报告时取后 3 次的中位数"),
    ("输出", "<code>out/harness.jsonl</code>、<code>out/kiro.jsonl</code>"),
]) + P("Claude Code 用 <code>-p --output-format json</code> 非交互运行，它输出的 JSON 里有 API 耗时和缓存读写 token。总时长减去 <code>duration_api_ms</code>，就是进程启动、插件和 MCP 初始化的时间。"
       "OpenCode 用 <code>run --format json</code>，从事件流里的 <code>step_finish</code> 读 token。两者都必须关闭标准输入，否则会一直等待。")
  + code("harness_probe.py", "for i in range(4):", n=10, note="Claude Code")
  + code("harness_probe.py", "\"opencode\", \"run\"", n=10, note="OpenCode")
  + "<h3>Kiro 轮次：用服务端计数器拆分</h3>"
  + P("Kiro 网关在 OpenCode 后面调用 vLLM，客户端看不到模型时间，所以在每一轮前后各读一次 <code>/metrics</code>，取六个计数器的差值：提示 token、缓存命中 token、生成 token、成功请求数、预填充秒数、解码秒数。")
  + raw('''H = os.path.expanduser("~")
env = dict(os.environ, KIROCREW_HOME=H + "/.kiro/crew-qwen", KIROCREW_PORT="5477", PATH=...)
def m():
    t = u.urlopen("http://127.0.0.1:8101/metrics").read().decode()
    g = lambda k: sum(float(l.split()[-1]) for l in t.splitlines() if l.startswith(k + "{"))
    return {k: g("vllm:" + k) for k in ("prompt_tokens_total", "prompt_tokens_cached_total",
            "generation_tokens_total", "request_success_total",
            "request_prefill_time_seconds_sum", "request_decode_time_seconds_sum")}
for i in range(4):
    a = m(); t = time.time()
    subprocess.run(["timeout", "120", "kirocrew", "chat", "-m", "reply with exactly: ok"], env=env, ...)
    w = time.time() - t; b = m()
    d = {k: round(b[k] - a[k], 2) for k in a}; d.update(turn=i, wall=round(w, 2))''', "Kiro 轮次测量（在 latte 上通过 ssh 运行的内联脚本）")
  + "<h3>抓包代理：看清 Kiro 发给模型的内容</h3>"
  + P("为了找出为什么每轮缓存命中都是 0，我写了一个只用标准库的反向代理，监听 8110，把请求原样转发给 llama-swap，并把每个 <code>/chat/completions</code> 的请求体写到文件。"
      "测试时临时把 OpenCode 配置里的 <code>baseURL</code> 改到 8110，跑两轮 Kiro，再改回去。流式响应用 <code>read1</code> 边读边写回，不影响客户端的流式体验。")
  + code("capture_proxy.py", "class H(", "    def do_GET")
  + P("拿到请求体后，用 vLLM 的 <code>/tokenize</code> 接口把两轮请求（messages 加 tools）各自转换成 token，找出第一个不同的位置。这一步给出了“第 184 个 token 分叉”和“重排后前 37,439 个 token 相同”这两个数字。")
  + raw('''def tok(b):
    r = u.urlopen(u.Request("http://127.0.0.1:8101/tokenize",
        data=json.dumps({"model": "qwen3.8", "messages": b["messages"], "tools": b["tools"]}).encode(),
        headers={"Content-Type": "application/json"})).read()
    return json.loads(r)["tokens"]
a, b = tok(first_turn), tok(second_turn)
i = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y)   # first differing token''', "找出两轮请求的分叉点")
  + P("修复验证用的是同一个代理，环境变量 <code>REORDER=1</code> 时，把描述里含 <code>/scratch/</code> 路径的工具挪到工具列表末尾，其余内容不动：")
  + code("capture_proxy.py", "if os.environ.get(\"REORDER\")", n=5)
  + "<h3>混合模型前缀缓存的对照实验</h3>"
  + P("为了确认“中间改一处就完全不命中”是模型架构造成的，我用一个约 2.8 万 token 的合成提示做了三次请求：原始提示；只改中间一行；与第二次完全相同、只改结尾。每次都读 <code>prompt_tokens_cached_total</code> 的差值。结果分别命中 0、0、28,224 个 token。")
  + raw('''body = lambda tag: (''.join(f"def f{i}(x):\\n    return x*{i}\\n" for i in range(900)) + "# " + tag + "\\n"
                   + ''.join(f"def g{i}(x):\\n    return x+{i}\\n" for i in range(900)))
head = "# " + uuid.uuid4().hex + "\\n"
ask(head + body("A") + "\\nQ?")        # first
ask(head + body("B") + "\\nQ?")        # change in the middle   -> 0 cached
ask(head + body("B") + "\\nQ? more")   # same as previous up to the end -> 28,224 cached''', "中间修改对照实验"))

# ------------------------------------------------------------------ 3 vLLM
vllm = sec("vllm", "实验 3 · 推理服务层", "TTFT、TPOT、缓存命中和并发", card([
    ("脚本", "<code>bench/llm_probe.py &lt;base_url&gt; &lt;out&gt; grid|paths|conc [--metrics url]</code>"),
    ("服务配置", "vLLM 0.32，Qwen3.8-27B AWQ，<code>--max-model-len 65536 --max-num-seqs 2 --enable-prefix-caching --enable-mfu-metrics --kv-cache-metrics</code>"),
    ("请求参数", "流式，<code>temperature=0</code>，<code>ignore_eos=true</code>，关闭思考（<code>enable_thinking=false</code>）"),
    ("输出", "<code>out/llm-grid.jsonl</code>、<code>llm-conc.jsonl</code>、<code>llm-paths.jsonl</code>、<code>mac-paths.jsonl</code>；GPU 同步采样 <code>llm-gpu.csv</code>"),
]) + P("合成提示由重复的 Python 函数行组成，每行约 34 个 token，按目标长度拼接。开头的 <code>tag</code> 是随机 uuid，用来控制缓存能否命中。")
  + code("llm_probe.py", "LINE = ", "def stream")
  + P("TTFT 和 TPOT 的定义写在 <code>stream()</code> 里：TTFT 是发出请求到收到第一个内容 delta；TPOT 是第一个到最后一个 token 的时间除以 (输出 token 数 − 1)。思考内容的 delta 也算 token。同时记录相邻 token 间隔的 p99，用来发现卡顿。")
  + code("llm_probe.py", "def stream", "def scrape")
  + P("服务端数据来自 <code>/metrics</code>。<code>scrape()</code> 把所有 <code>vllm:*</code> 计数器按名字加总（忽略直方图的分桶），<code>run()</code> 在请求前后各抓一次，把差值存进每行结果的 <code>srv</code> 字段。"
      "vLLM 在响应里返回的 <code>cached_tokens</code> 是空的，所以缓存命中只能从这里读。")
  + code("llm_probe.py", "def scrape", "if MODE == \"grid\"")
  + "<h3>三种模式</h3>"
  + code("llm_probe.py", "if MODE == \"grid\"", "elif MODE == \"conc\"")
  + ul("<b>grid</b>：7 档长度 × 4 次。每次先发一个新 uuid 的提示（冷），紧接着原样再发一次（命中）。",
       "<b>paths</b>：同一个 500 token 的提示先发一次预热，再发 30 次。分别以 <code>http://127.0.0.1:8101</code>（直连 vLLM）、<code>:8100</code>（llama-swap）在 latte 上运行，以及在 Mac 上经 SSH 隧道 <code>127.0.0.1:18100</code> 运行。三者 TTFT 中位数之差就是每一层的开销。",
       "<b>conc</b>：1–4 个线程同时发 4K 提示、300 个输出 token，每个线程的提示都不同。记录平均和最慢的 TTFT、平均 TPOT、总吞吐（所有输出 token / 墙钟时间）。")
  + code("llm_probe.py", "elif MODE == \"conc\"", n=14))

# ------------------------------------------------------------------ 4 kernel
kernel = sec("kernel", "实验 4 · Kernel 与 GPU", "Kernel 配置、profiler、MTP 和带宽上限", card([
    ("脚本", "<code>kprobe.py</code> + <code>run_kernel.sh</code>（kernel 配置与 profiler），<code>kprobe2.py</code> + <code>run_spec.sh</code>（MTP）"),
    ("编译器", "conda 安装的 CUDA 13.0 nvcc，位于 <code>~/latte-models/cuda13</code>；补了 <code>lib64 → targets/x86_64-linux/lib</code> 软链接，FlashInfer 的 JIT 才能链接到 <code>libcudart</code>"),
    ("控制变量", "每组配置都重启 vLLM；同一个探针；全程持有 GPU 锁"),
    ("输出", "<code>out/kernel.jsonl</code>、<code>out/spec.jsonl</code>、<code>out/prof/{prefill,decode}/</code>"),
]) + P("驱动脚本先拿 GPU 锁，让 llama-swap 卸载当前模型，然后对每组配置：用指定的环境变量和参数启动 <code>serve-qwen.sh</code>，轮询 <code>/health</code> 直到就绪，跑探针，最后结束整个进程组。")
  + code("run_kernel.sh", "cd ~/latte-bench; exec 9", "# torch profiler")
  + P("探针本身包括：两档长度的冷预填充各 3 次（输出 2 个 token，只看 TTFT）；512 个 token 的解码 3 次；两路并发各 512 个 token。采样参数用 Qwen 推荐的 <code>top_p=0.8, top_k=20</code>，这样采样器才会真正走 top-k/top-p 路径。")
  + code("kprobe.py", "stream(prompt(2000), 16)", n=12)
  + "<h3>torch profiler</h3>"
  + P("vLLM 自带 profiler 开关。启动时传 <code>--profiler-config</code>，运行中用 <code>POST /start_profile</code> 和 <code>/stop_profile</code> 包住一个请求，profiler 会写出 Chrome trace 和一张按 kernel 汇总的表。我分别包住一次约 2 万 token 的预填充和一次 64 token 的解码。")
  + code("run_kernel.sh", "# torch profiler", "kill -- -$p")
  + P("报告里的分类图来自那张汇总表：只取叶子 CUDA kernel 的 Self CUDA 时间（排除 <code>aten::</code>、<code>_C::</code> 这类 CPU 侧的包装，避免重复计算），再按名字归类：<code>marlin</code> 是 INT4 矩阵乘，耗时超过 0.5 ms 的 <code>gemv</code> 是 <code>lm_head</code>，<code>flash</code> 是全注意力，<code>delta</code>/<code>gdn</code>/<code>conv1d</code> 是线性注意力，以此类推。"
      "<code>execute_context_0(0)_generation_1(1)</code> 这一行的总时间除以调用次数，就是每个解码步的 GPU 时间（11.17 ms）。")
  + code("report/gen.py", "def prof_groups", "pgroups = ")
  + "<h3>MTP 推测解码</h3>"
  + P("在同一个探针上加了一个更真实的负载：用 t5 题目的原文让模型写 1,500 个 token 的回答，开思考 3 次、不开思考 2 次。"
      "推测解码的接受率从 <code>/metrics</code> 的 <code>spec_decode_num_draft_tokens</code> 和 <code>num_accepted_tokens</code> 的差值算出。配置只差一个参数：<code>--speculative-config {\"method\":\"qwen3_5_mtp\",\"num_speculative_tokens\":k}</code>，k = 1、2、3。")
  + code("kprobe2.py", "def spec():", "def rec(")
  + "<h3>带宽上限是怎么算的</h3>"
  + P("不读模型卡片，直接解析 safetensors 文件头：每个文件开头 8 字节是头部长度，头部 JSON 里有每个张量的字节范围。按名字把张量分到层、<code>lm_head</code>、嵌入、视觉编码器和 MTP，加总字节数。"
      "每生成一个 token 要读一遍层权重和 <code>lm_head</code>（嵌入只查一行），共约 16.7 GB；除以 RTX 5090 的 1,792 GB/s，得到 9.3 ms 的理论下限。")
  + raw('''for p in glob.glob(snapshot + "model-*.safetensors"):
    with open(p, "rb") as fh:
        n = struct.unpack("<Q", fh.read(8))[0]          # header length
        h = json.loads(fh.read(n))                      # tensor name -> dtype, shape, data_offsets
    for k, v in h.items():
        if k == "__metadata__": continue
        size = v["data_offsets"][1] - v["data_offsets"][0]
        g = ("visual" if "visual" in k else "mtp" if k.startswith("mtp") else
             "embed" if "embed_tokens" in k else "lm_head" if "lm_head" in k else "layers")
        tot[g] += size''', "按组件统计权重字节数")
  + "<h3>GPU 采样</h3>"
  + P("最早用每秒一次的循环（<code>gpu_trace.sh</code>）；媒体实验需要更细，改用 <code>nvidia-smi</code> 自带的循环模式，每 250 ms 一行，直到停止文件被删除。")
  + code("gpu_fast.sh", "nvidia-smi", n=4))

# ------------------------------------------------------------------ 5 media
media = sec("media", "实验 5 · 媒体模型", "Z-Image、Qwen3-TTS、Wan 和模型切换", card([
    ("脚本", "<code>bench/media_probe.py</code>，配合 <code>gpu_fast.sh</code> 在后台采样"),
    ("入口", "全部通过 llama-swap（:8100）；Wan 的 multipart 接口走 <code>/upstream/wan2.2-ti2v/v1/videos/sync</code>"),
    ("输出", "<code>out/media.jsonl</code>（每次请求的起止时间与耗时）、<code>out/media-gpu.csv</code>"),
]) + P("脚本一开始就拿 GPU 锁，和 media-bot 的行为一致。每个请求记录开始的 Unix 时间，之后用它把 GPU 采样对齐到具体某一次生成。")
  + code("media_probe.py", "lock = open", "for steps in")
  + ul("<b>Z-Image</b>：1024² 下 4、8、12 步各 4 次，再测 512²、768²、1344×768 各 3 次（8 步）。每张图用不同的 seed。",
       "<b>TTS</b>：短、中、长三段中文各 4 次。返回的 wav 用 <code>wave</code> 模块读出帧数和采样率，算出音频时长；实时率 RTF = 合成耗时 / 音频时长。",
       "<b>Wan</b>：25 帧跑两次（第一次含加载），之后 49 帧、121 帧，以及 49 帧下 15 和 50 步。",
       "<b>切换成本</b>：每个模型第一次请求的耗时减去之后同参数请求的中位数。因为 llama-swap 是互斥的，第一次请求包含了卸载上一个模型、加载权重、torch.compile 和 CUDA graph 捕获。")
  + code("media_probe.py", "for name, text in T.items():", "def video")
  + code("media_probe.py", "def video", n=8)
  + P("Wan 的阶段划分用的是 GPU 采样：在一次请求的起止时间内，利用率 ≥ 80% 的第一个和最后一个采样点之间算作去噪阶段，之前是排队和加载，之后是收尾（VAE 解码、搬运、编码）。去噪阶段内取功耗和 SM 时钟的中位数。")
  + code("report/gen.py", "def wan_phase", "# ----"))

# ------------------------------------------------------------------ 6 collab
collab = sec("collab", "实验 6 · 协作实验", "题目、三种方式、隐藏测试和打分", card([
    ("题库", "<code>collab/repo/</code>（ledgerkit 初始仓库）、<code>collab/tasks.json</code>（6 道题）、<code>collab/ref/</code>（参考答案）"),
    ("隐藏测试", "<code>collab/hidden/test_t1..t6.py</code>，共 175 个用例，只保存在 Mac 上；参考答案先跑通全部用例，确认测试本身没错"),
    ("额外边界测试", "<code>collab/extra/</code>，由审查者发现的问题改写，共 4 个"),
    ("驱动", "<code>collab/run.py &lt;claude|local|codex&gt;</code>，在 Mac 上运行"),
    ("打分", "<code>collab/score.sh</code> + <code>score_remote.py</code>，结果在 <code>collab/scored.json</code>"),
]) + P("仓库放在 latte 的 <code>~/development/ledgerkit</code>，初始化成 git 仓库，crewd 会为每个作业创建独立的 worktree 和分支，所以 18 个作业互不干扰，最后每个分支对应一份答案。")
  + "<h3>驱动脚本</h3>"
  + P("Claude 单独用 <code>crew task --model sonnet</code>；另外两种用 <code>crew local</code>。Codex 组先在 Mac 上对仓库的只读副本运行 <code>codex exec --json --sandbox read-only</code>，要求它只写计划不写代码，从事件流里取最后一条 agent 消息作为计划、取 <code>turn.completed</code> 的用量，然后把计划附在任务后面提交。")
  + code("collab/run.py", "def plan(task):", "def wait(jid)")
  + P("第二轮实验复用了第一轮的 Codex 计划，这样两轮之间唯一变化的是 Qwen 一侧的配置：")
  + code("collab/run.py", "def run(arm, tid):", "    if arm == \"claude\":")
  + P("每个作业提交后每 10 秒查一次状态，结束时记录状态、审查结论、轮数、墙钟时间和花费。")
  + "<h3>每一轮都能单独打分</h3>"
  + P("为了区分“第一轮就对了”和“审查后才改对”，我在 crewd 里加了一行：Qwen 每一轮提交后，把当时的 commit 追加到作业的 <code>round_heads</code>。")
  + code("../crew/crew.py", "    autocommit(cwd, f\"crew {ctx.jid} round", n=4)
  + "<h3>打分时隐藏测试才离开 Mac</h3>"
  + P("所有作业结束后，<code>score.sh</code> 才把隐藏测试和额外测试拷到 latte 的 <code>/tmp</code>，跑完立刻删除。这样 Qwen、Claude、Codex 在答题时都不可能看到测试。")
  + code("collab/score.sh", "JOBS=", n=6)
  + P("对每个 commit，用 <code>git archive</code> 导出到一个新的临时目录（不碰工作区），放入对应的隐藏测试，用 pytest 跑，从最后一行解析通过、失败、出错的数量。")
  + code("collab/score_remote.py", "def score(sha, task", "def claude_usage")
  + "<h3>token 和时间从哪里来</h3>"
  + ul("<b>Claude</b>：每次 Claude Code 运行的 <code>result</code> 事件，里面有输入、缓存写、缓存读、输出 token 和折算价格。",
       "<b>Qwen</b>：OpenCode 的 <code>step_finish</code> 事件，每一步的输入、输出、思考 token。",
       "<b>Codex</b>：<code>turn.completed</code> 里的 <code>input_tokens</code>、<code>cached_input_tokens</code>、<code>output_tokens</code>。",
       "<b>阶段时间</b>：crewd 的 <code>ledger.jsonl</code>，每个阶段（qwen-r1、local_reviewer-r1 …）一行，带秒数。")
  + code("collab/score_remote.py", "def qwen_usage", "out = []")
  + "<h3>Qwen 的时间拆分</h3>"
  + P("OpenCode 的事件都带毫秒时间戳：<code>step_start</code>、<code>step_finish</code>，以及每个 <code>tool_use</code> 的开始和结束时间。一步的时长减去其中工具的运行时间，就是模型时间；上一步结束到下一步开始之间是步间间隔。报告里“模型 95.9%、工具 0.8%、间隔 3.3%”就是这样把 28 次 Qwen 运行加总得到的。")
  + code("report/gen.py", "# Qwen time split from OpenCode event logs", "qwall = ")
  + "<h3>审查发现的复现</h3>"
  + P("每条 CHANGES 意见都在对应的 commit 上复现过。t2 用审查者给的输入直接调用函数；t4 和 t5 写成了额外的边界测试，再在三种方式的最终代码上统一运行。")
  + (code("collab/extra/test_extra_t4.py", "from datetime", n=16) if os.path.exists(os.path.join(B, "collab/extra/test_extra_t4.py")) else ""))

# ------------------------------------------------------------------ 7 report
report = sec("report", "数据到报告", "数字是怎么进到报告里的", P(
    "所有原始结果用 rsync 从 latte 的 <code>~/latte-bench/out/</code> 拉回 Mac 的 <code>bench/out/</code>，作业目录拉到 <code>bench/out/jobs/</code>。"
    "<code>report/gen.py</code> 读取这些文件，计算中位数和比例，用 <code>charts.py</code>、<code>diagrams.py</code> 生成内联 SVG，输出一个完整的 HTML。"
    "报告正文里的数字大多是 f-string 直接引用计算结果；少数从日志里人工读出的数字（例如带宽、profiler 每步时间）在本页对应的小节里给出了来源。")
  + ul("<code>python3 bench/report/gen.py</code>：生成分析报告",
       "<code>python3 bench/report/gen_methods.py</code>：生成本页"))

limits = sec("limits", "已知局限", "这些方法测不到或测不准的地方", ul(
    "重复次数不多：微基准 4–30 次，协作实验每种方式每道题 1 次（第一轮因配置问题仅作参考）。",
    "连接层的数字包含 Tailscale 当时的网络状况；Mac 上的测量和 latte 上的测量没有做时钟同步，所以没有拼成同一条时间线。",
    "Kiro 修复只用实验代理验证了 4 轮，没有在真实流量上长期观察。",
    "Profiler 只抓了一次预填充和一次解码；分类是按 kernel 名字归的，个别 kernel 可能归错类。",
    "Wan 收尾阶段的成分是根据功耗和利用率推断的，没有对照 vLLM-Omni 的阶段日志。",
    "Claude 的花费是 Claude Code 报告的 API 折算价，实际用的是订阅额度。"))

EXTRA_CSS = r"""
.spec{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;margin:18px 0;padding:14px 16px;background:var(--panel);border:1px solid var(--rule);border-radius:10px;font-size:14.5px}
.spec dt{color:var(--muted);font-weight:600;white-space:nowrap}
.spec dd{margin:0;min-width:0;overflow-wrap:anywhere}
figure.code{padding:0;overflow:hidden}
figure.code figcaption{margin:0;padding:8px 14px;border-bottom:1px solid var(--rule);font-size:12.5px}
figure.code pre{margin:0;padding:12px 14px;overflow-x:auto;background:var(--code-bg)}
figure.code pre code{background:none;padding:0;font-size:12.5px;line-height:1.6;white-space:pre;overflow-wrap:normal}
@media (max-width:520px){.spec{grid-template-columns:1fr}.spec dt{margin-top:6px}}
"""

def build():
    toc = [("principles", "总则"), ("connection", "连接层"), ("harness", "Agent 层"), ("vllm", "推理服务"), ("kernel", "Kernel 与 GPU"),
           ("media", "媒体模型"), ("collab", "协作实验"), ("report", "数据到报告"), ("limits", "局限")]
    nav = '<nav class="toc" aria-label="目录"><ol>' + "".join(f'<li><a href="#{a}">{b}</a></li>' for a, b in toc) + "</ol></nav>"
    body = intro + nav + principles + connection + harness + vllm + kernel + media + collab + report + limits
    foot = '<footer><p>配套报告：《LatteCrew：优化与分析》。脚本位于 <code>latte-crew/bench/</code>；隐藏测试只保存在 Mac 上。</p></footer>'
    return ('<title>LatteCrew 实验方法</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
            '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Noto+Sans+SC:wght@400;600&family=Noto+Serif+SC:wght@600;700&display=swap">'
            f'<style>{gen.CSS}{EXTRA_CSS}</style><div class="page">{body}{foot}</div><div id="tip" hidden></div><script>{gen.JS}</script>')

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    page = build()
    open(os.path.join(here, "lattecrew-methods.html"), "w").write(page)
    full = ('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<title>LatteCrew 实验方法</title>\n</head>\n<body style="margin:0">\n' + page.split("\n", 2)[2] + "\n</body>\n</html>\n")
    open(os.path.join(here, "lattecrew-methods-standalone.html"), "w").write(full)
    print("wrote lattecrew-methods.html and lattecrew-methods-standalone.html", len(page) // 1024, "KB")
