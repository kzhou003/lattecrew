def split(total_cents, weights):
    """Split an amount between parties in proportion to their weights."""
    s = sum(weights)
    return [round(total_cents * w / s) for w in weights]
