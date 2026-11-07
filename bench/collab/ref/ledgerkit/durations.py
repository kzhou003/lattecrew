import re
from fractions import Fraction
U = {"d": 86400, "h": 3600, "m": 60, "s": 1}
def parse(text):
    t = text.strip()
    neg = t.startswith("-")
    if neg: t = t[1:]
    pos = 0; total = Fraction(0); last = 99; n = 0; order = "dhms"
    while pos < len(t):
        m = re.compile(r"\s*(\d+(?:\.\d+)?)([dhms])").match(t, pos)
        if not m or (pos == 0 and t[0].isspace()): raise ValueError(text)
        i = order.index(m[2])
        if n and i <= last: raise ValueError(text)
        total += Fraction(m[1]) * U[m[2]]; last = i; n += 1; pos = m.end()
    if not n: raise ValueError(text)
    total = -total if neg else total
    return int(total) if total.denominator == 1 else float(total)
def format(seconds):
    if seconds == 0: return "0s"
    s = abs(seconds); out = "-" if seconds < 0 else ""
    for k, v in U.items():
        q, s = divmod(s, v)
        if q: out += f"{q}{k}"
    return out
