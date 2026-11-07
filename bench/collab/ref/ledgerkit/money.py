def split(total_cents, weights):
    if not weights or any(w < 0 for w in weights) or sum(weights) == 0:
        raise ValueError("bad weights")
    if total_cents < 0:
        return [-x for x in split(-total_cents, weights)]
    s = sum(weights)
    parts = [total_cents * w // s for w in weights]
    rem = [(total_cents * w) % s for w in weights]
    for i in sorted(range(len(weights)), key=lambda i: (-rem[i], i))[: total_cents - sum(parts)]:
        parts[i] += 1
    return parts
