"""Small inline-SVG chart helpers for the LatteCrew report.

Colors come from CSS classes (s1..s4, muted) so both themes work. Every mark carries
data-tip, which the page script turns into a hover tooltip. Values are also shown in
tables next to each chart.
"""
import html, math

def esc(s):
    return html.escape(str(s), quote=True)

def nice_ticks(lo, hi, n=5):
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=mag * 10)
    t = math.ceil(lo / step) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 10))
        t += step
    return out

def fmt(v, unit=""):
    if isinstance(v, float) and abs(v - round(v)) > 1e-9:
        s = f"{v:,.1f}" if abs(v) < 100 else f"{v:,.0f}"
    else:
        s = f"{int(round(v)):,}"
    return s + unit

def frame(w, h, body, label):
    return (f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}" '
            f'preserveAspectRatio="xMidYMid meet">{body}</svg>')

def legend(items):
    """items: list of (css_class, label). HTML legend placed above a chart."""
    return '<div class="legend">' + "".join(
        f'<span class="key"><i class="sw {c}"></i>{esc(t)}</span>' for c, t in items) + "</div>"

def hbar(rows, unit="", w=720, label="", maxv=None, row_h=30, left=210, note_fmt=None):
    """rows: list of (name, value, css_class, tip). Horizontal bars from a zero baseline."""
    maxv = maxv or max(r[1] for r in rows) * 1.12
    right = 70
    h = 26 + row_h * len(rows) + 8
    x = lambda v: left + (w - left - right) * v / maxv
    p = []
    for t in nice_ticks(0, maxv, 5):
        p.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="18" y2="{h-8}"/>'
                 f'<text class="tick" x="{x(t):.1f}" y="12" text-anchor="middle">{fmt(t)}</text>')
    for i, (name, v, cls, tip) in enumerate(rows):
        y = 26 + i * row_h
        bw = max(2, x(v) - left)
        p.append(f'<g class="hit" data-tip="{esc(tip)}"><rect class="hitbox" x="0" y="{y-3}" width="{w}" height="{row_h}"/>'
                 f'<text class="lab" x="{left-10}" y="{y+row_h/2}" text-anchor="end" dominant-baseline="middle">{esc(name)}</text>'
                 f'<path class="{cls}" d="M{left},{y+4} h{bw-4:.1f} a4,4 0 0 1 4,4 v{row_h-16} a4,4 0 0 1 -4,4 h-{bw-4:.1f} z"/>'
                 f'<text class="val" x="{left+bw+6:.1f}" y="{y+row_h/2}" dominant-baseline="middle">{esc(note_fmt(v) if note_fmt else fmt(v, unit))}</text></g>')
    p.append(f'<line class="axis" x1="{left}" x2="{left}" y1="18" y2="{h-8}"/>')
    return frame(w, h, "".join(p), label)

def stacked_hbar(rows, segs, unit="", w=720, label="", row_h=34, left=210, maxv=None):
    """rows: list of (name, [values per seg], tip). segs: list of (css_class, seg_name)."""
    maxv = maxv or max(sum(r[1]) for r in rows) * 1.1
    right = 70
    h = 26 + row_h * len(rows) + 8
    x = lambda v: left + (w - left - right) * v / maxv
    p = []
    for t in nice_ticks(0, maxv, 5):
        p.append(f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="18" y2="{h-8}"/>'
                 f'<text class="tick" x="{x(t):.1f}" y="12" text-anchor="middle">{fmt(t)}</text>')
    for i, (name, vals, tip) in enumerate(rows):
        y = 26 + i * row_h
        p.append(f'<text class="lab" x="{left-10}" y="{y+row_h/2}" text-anchor="end" dominant-baseline="middle">{esc(name)}</text>')
        acc = 0
        for (cls, sname), v in zip(segs, vals):
            if v <= 0:
                continue
            x0, x1 = x(acc), x(acc + v)
            p.append(f'<rect class="{cls} hit" data-tip="{esc(name + " · " + sname + ": " + fmt(v, unit))}" x="{x0+1:.1f}" y="{y+5}" '
                     f'width="{max(1.5, x1-x0-2):.1f}" height="{row_h-12}" rx="3"/>')
            acc += v
        p.append(f'<text class="val" x="{x(acc)+6:.1f}" y="{y+row_h/2}" dominant-baseline="middle">{esc(tip)}</text>')
    p.append(f'<line class="axis" x1="{left}" x2="{left}" y1="18" y2="{h-8}"/>')
    return frame(w, h, "".join(p), label)

def lines(series, xlab, ylab, w=720, h=300, label="", xmax=None, ymax=None, xfmt=None, yfmt=None, end_labels=True):
    """series: list of (css_class, name, [(x, y, tip)]). Crosshair columns snap to the shared x values."""
    L, R, T, B = 58, 120 if end_labels else 24, 16, 44
    xs = sorted({pt[0] for _, _, pts in series for pt in pts})
    xmax = xmax or max(xs) * 1.04
    ymax = ymax or max(pt[1] for _, _, pts in series for pt in pts) * 1.12
    X = lambda v: L + (w - L - R) * v / xmax
    Y = lambda v: h - B - (h - T - B) * v / ymax
    p = []
    for t in nice_ticks(0, ymax, 5):
        p.append(f'<line class="grid" x1="{L}" x2="{w-R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"/>'
                 f'<text class="tick" x="{L-8}" y="{Y(t):.1f}" text-anchor="end" dominant-baseline="middle">{esc(yfmt(t) if yfmt else fmt(t))}</text>')
    for t in nice_ticks(0, xmax, 6):
        p.append(f'<text class="tick" x="{X(t):.1f}" y="{h-B+18}" text-anchor="middle">{esc(xfmt(t) if xfmt else fmt(t))}</text>')
    p.append(f'<line class="axis" x1="{L}" x2="{w-R}" y1="{h-B}" y2="{h-B}"/>')
    p.append(f'<text class="axlab" x="{(L+w-R)/2}" y="{h-6}" text-anchor="middle">{esc(xlab)}</text>')
    p.append(f'<text class="axlab" x="14" y="{(T+h-B)/2}" text-anchor="middle" transform="rotate(-90 14 {(T+h-B)/2})">{esc(ylab)}</text>')
    for cls, name, pts in series:
        d = " ".join(f'{"M" if i == 0 else "L"}{X(a):.1f},{Y(b):.1f}' for i, (a, b, _) in enumerate(pts))
        p.append(f'<path class="line {cls}" d="{d}"/>')
        for a, b, _ in pts:
            p.append(f'<circle class="dot {cls}" cx="{X(a):.1f}" cy="{Y(b):.1f}" r="4.5"/>')
        if end_labels:
            a, b, _ = pts[-1]
            p.append(f'<text class="lab" x="{X(a)+10:.1f}" y="{Y(b):.1f}" dominant-baseline="middle">{esc(name)}</text>')
    # crosshair columns
    for i, xv in enumerate(xs):
        lo = (X(xs[i - 1]) + X(xv)) / 2 if i else L
        hi = (X(xs[i + 1]) + X(xv)) / 2 if i + 1 < len(xs) else w - R
        tips = [f"{name}: {tip}" for _, name, pts in series for a, b, tip in pts if a == xv]
        p.append(f'<g class="hit col" data-tip="{esc(" | ".join(tips))}"><rect class="hitbox" x="{lo:.1f}" y="{T}" width="{hi-lo:.1f}" height="{h-T-B}"/>'
                 f'<line class="hair" x1="{X(xv):.1f}" x2="{X(xv):.1f}" y1="{T}" y2="{h-B}"/></g>')
    return frame(w, h, "".join(p), label)

def dotplot(cats, series, w=720, label="", log=True, ticks=None, tickfmt=None, row_h=34, left=150, xmax=None):
    """cats: row names. series: list of (css_class, name, {cat: (value, tip)}). Log x axis by default."""
    R = 40
    h = 30 + row_h * len(cats) + 10
    vals = [v for _, _, d in series for v, _ in d.values()]
    lo, hi = (min(vals) * 0.8, (xmax or max(vals) * 1.25))
    if log:
        X = lambda v: left + (w - left - R) * (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
    else:
        lo = 0
        X = lambda v: left + (w - left - R) * v / hi
    p = []
    for t in ticks or nice_ticks(0, hi, 5):
        if t < lo or t > hi:
            continue
        p.append(f'<line class="grid" x1="{X(t):.1f}" x2="{X(t):.1f}" y1="22" y2="{h-6}"/>'
                 f'<text class="tick" x="{X(t):.1f}" y="14" text-anchor="middle">{esc(tickfmt(t) if tickfmt else fmt(t))}</text>')
    off = {i: (i - (len(series) - 1) / 2) * 7 for i in range(len(series))}
    for r, c in enumerate(cats):
        y = 30 + r * row_h + row_h / 2
        p.append(f'<text class="lab" x="{left-12}" y="{y}" text-anchor="end" dominant-baseline="middle">{esc(c)}</text>'
                 f'<line class="rowrule" x1="{left}" x2="{w-R}" y1="{y}" y2="{y}"/>')
        for i, (cls, name, d) in enumerate(series):
            if c not in d:
                continue
            v, tip = d[c]
            p.append(f'<g class="hit" data-tip="{esc(name + " · " + c + ": " + tip)}"><circle class="hitbox" cx="{X(v):.1f}" cy="{y+off[i]:.1f}" r="11"/>'
                     f'<circle class="dot {cls}" cx="{X(v):.1f}" cy="{y+off[i]:.1f}" r="6"/></g>')
    return frame(w, h, "".join(p), label)

def table(head, rows, cls=""):
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tablewrap"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'
