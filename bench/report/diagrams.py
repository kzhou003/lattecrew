"""Diagrams for the LatteCrew report: drawn from measured data, in inline SVG."""
from charts import esc, frame, fmt

def stack(layers, w=760):
    """layers: list of (name, sub, [measure lines], css). A vertical stack of the request path."""
    bh, gap, top = 58, 16, 8
    h = top + len(layers) * (bh + gap)
    p = ['<defs><marker id="arr" viewBox="0 0 10 10" refX="5" refY="9" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         '<path d="M0,0 L10,0 L5,10 z" class="arrowhead"/></marker></defs>']
    for i, (name, sub, measures, css) in enumerate(layers):
        y = top + i * (bh + gap)
        p.append(f'<g class="hit" data-tip="{esc(name + " · " + " / ".join(measures))}">'
                 f'<rect class="node {css}" x="4" y="{y}" width="{w*0.46:.0f}" height="{bh}" rx="8"/>'
                 f'<text class="nodet" x="20" y="{y+24}">{esc(name)}</text>'
                 f'<text class="nodes" x="20" y="{y+44}">{esc(sub)}</text>')
        for j, m in enumerate(measures[:2]):
            p.append(f'<text class="meas" x="{w*0.46+28:.0f}" y="{y+24+j*20}">{esc(m)}</text>')
        p.append('</g>')
        if i + 1 < len(layers):
            p.append(f'<line class="flow" x1="{w*0.23:.0f}" y1="{y+bh+2}" x2="{w*0.23:.0f}" y2="{y+bh+gap-3}" marker-end="url(#arr)"/>')
    return frame(w, h, "".join(p), "LatteCrew request path with measured latency per layer")

def prompt_layout(total, header, volatile, stable_after, w=760):
    """Two bars showing which part of the Kiro prompt the prefix cache can reuse, before and after reordering."""
    L, R = 120, 20
    X = lambda t: L + (w - L - R) * t / total
    p = []
    rows = [("改动前", [(0, header, "seg-ok", f"开头 {header} 个 token：可复用"),
                       (header, header + volatile, "seg-bad", "bash 工具描述：含本会话的临时目录，每轮不同"),
                       (header + volatile, total, "seg-miss", "其后全部无法复用：106 个工具定义 + 系统提示 + 用户消息")]),
            ("工具重排后", [(0, stable_after, "seg-ok", f"可复用前缀 {stable_after:,} 个 token（47 个 784-token 块）"),
                          (stable_after, total, "seg-miss", "每轮重算：易变的 bash 工具、系统提示尾部、用户消息")])]
    for r, (name, segs) in enumerate(rows):
        y = 26 + r * 64
        p.append(f'<text class="lab" x="{L-12}" y="{y+16}" text-anchor="end" dominant-baseline="middle">{esc(name)}</text>')
        for a, b, cls, tip in segs:
            p.append(f'<rect class="{cls} hit" data-tip="{esc(tip)}" x="{X(a)+1:.1f}" y="{y}" width="{max(3, X(b)-X(a)-2):.1f}" height="32" rx="4"/>')
    for t in (0, 10000, 20000, 30000, 40000, total):
        p.append(f'<text class="tick" x="{X(t):.1f}" y="16" text-anchor="middle">{fmt(t)}</text>')
    return frame(w, 26 + 2 * 64, "".join(p), "Kiro prompt prefix that vLLM can reuse")

def sequence(lanes, msgs, w=760, row=46):
    """lanes: list of (name, sub). msgs: list of (from, to, label, sub, css). A sequence diagram."""
    top = 64
    h = top + row * len(msgs) + 20
    lx = lambda i: 70 + i * (w - 140) / (len(lanes) - 1)
    p = ['<defs><marker id="arr2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
         '<path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>']
    for i, (n, s) in enumerate(lanes):
        p.append(f'<rect class="node" x="{lx(i)-62:.0f}" y="4" width="124" height="44" rx="8"/>'
                 f'<text class="nodet" x="{lx(i):.0f}" y="23" text-anchor="middle">{esc(n)}</text>'
                 f'<text class="nodes" x="{lx(i):.0f}" y="40" text-anchor="middle">{esc(s)}</text>'
                 f'<line class="life" x1="{lx(i):.0f}" x2="{lx(i):.0f}" y1="50" y2="{h-6}"/>')
    for k, (a, b, label, sub, css) in enumerate(msgs):
        y = top + k * row + 16
        x1, x2 = lx(a), lx(b)
        if a == b and a == len(lanes) - 1:
            p.append(f'<g class="hit" data-tip="{esc(label + " · " + sub)}"><path class="msg {css}" d="M{x1:.0f},{y} h-34 v16 h30" marker-end="url(#arr2)"/>'
                     f'<text class="msgt" x="{x1-42:.0f}" y="{y+4}" text-anchor="end">{esc(label)}</text>'
                     f'<text class="msgs" x="{x1-42:.0f}" y="{y+20}" text-anchor="end">{esc(sub)}</text></g>')
        elif a == b:
            p.append(f'<g class="hit" data-tip="{esc(label + " · " + sub)}"><path class="msg {css}" d="M{x1:.0f},{y} h34 v16 h-30" marker-end="url(#arr2)"/>'
                     f'<text class="msgt" x="{x1+42:.0f}" y="{y+4}">{esc(label)}</text>'
                     f'<text class="msgs" x="{x1+42:.0f}" y="{y+20}">{esc(sub)}</text></g>')
        else:
            d = 1 if x2 > x1 else -1
            mid = (x1 + x2) / 2
            p.append(f'<g class="hit" data-tip="{esc(label + " · " + sub)}"><line class="msg {css}" x1="{x1+d*4:.0f}" x2="{x2-d*6:.0f}" y1="{y+8}" y2="{y+8}" marker-end="url(#arr2)"/>'
                     f'<text class="msgt" x="{mid:.0f}" y="{y+2}" text-anchor="middle">{esc(label)}</text>'
                     f'<text class="msgs" x="{mid:.0f}" y="{y+24}" text-anchor="middle">{esc(sub)}</text></g>')
    return frame(w, h, "".join(p), "Who passes what to whom in one collaborative task")

def gantt(runs, w=760, row=30):
    """runs: list of (title, [ (lane, start_s, end_s, css, tip) ]), shared time axis in seconds."""
    tmax = max(e for _, segs in runs for _, _, e, _, _ in segs) * 1.03
    L, R = 130, 20
    X = lambda t: L + (w - L - R) * t / tmax
    lanes_all = []
    for title, segs in runs:
        ls = []
        for s in segs:
            if s[0] not in ls:
                ls.append(s[0])
        lanes_all.append(ls)
    h = 30 + sum(24 + row * len(ls) for ls in lanes_all) + 10
    p = []
    step = 60 if tmax < 900 else 120
    t = 0
    while t <= tmax:
        p.append(f'<line class="grid" x1="{X(t):.1f}" x2="{X(t):.1f}" y1="20" y2="{h-6}"/>'
                 f'<text class="tick" x="{X(t):.1f}" y="14" text-anchor="middle">{t//60:.0f} 分</text>')
        t += step
    y = 30
    for (title, segs), ls in zip(runs, lanes_all):
        p.append(f'<text class="nodet" x="4" y="{y+12}">{esc(title)}</text>')
        y += 24
        for lane in ls:
            p.append(f'<text class="lab" x="{L-10}" y="{y+row/2}" text-anchor="end" dominant-baseline="middle">{esc(lane)}</text>')
            for ln, a, b, css, tip in segs:
                if ln != lane:
                    continue
                p.append(f'<rect class="{css} hit" data-tip="{esc(tip)}" x="{X(a):.1f}" y="{y+5}" width="{max(2, X(b)-X(a)-1):.1f}" height="{row-10}" rx="3"/>')
            y += row
    return frame(w, h, "".join(p), "Timeline of two runs of task t4")
