from datetime import timedelta
def _a(d):
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError("naive")
def free_slots(busy, day_start, day_end, min_minutes=0):
    _a(day_start); _a(day_end)
    if day_end <= day_start: raise ValueError
    iv = []
    for s, e in busy:
        _a(s); _a(e)
        if e < s: raise ValueError
        if s == e: continue
        s, e = max(s, day_start), min(e, day_end)
        if s < e: iv.append((s, e))
    tz = day_start.tzinfo; out = []; cur = day_start
    for s, e in sorted(iv):
        if s > cur: out.append((cur, s))
        cur = max(cur, e)
    if cur < day_end: out.append((cur, day_end))
    m = timedelta(minutes=min_minutes)
    return [(a.astimezone(tz), b.astimezone(tz)) for a, b in out if b - a >= m and b > a]
