import threading, time
from collections import OrderedDict
class TTLCache:
    def __init__(self, maxsize, ttl, clock=time.monotonic):
        if maxsize < 1 or ttl <= 0: raise ValueError
        self.m, self.t, self.c = maxsize, ttl, clock
        self.d = OrderedDict(); self.l = threading.RLock(); self.s = dict(hits=0, misses=0, evictions=0)
    def _purge(self):
        now = self.c()
        for k in [k for k, (_, t) in self.d.items() if now - t >= self.t]: del self.d[k]
    def put(self, k, v):
        with self.l:
            self._purge()
            if k in self.d: del self.d[k]
            elif len(self.d) >= self.m: self.d.popitem(last=False); self.s["evictions"] += 1
            self.d[k] = (v, self.c())
    def get(self, k, default=None):
        with self.l:
            self._purge()
            if k not in self.d: self.s["misses"] += 1; return default
            self.d.move_to_end(k); self.s["hits"] += 1; return self.d[k][0]
    def __len__(self):
        with self.l: self._purge(); return len(self.d)
    def __contains__(self, k):
        with self.l: self._purge(); return k in self.d
    def stats(self):
        with self.l: return dict(self.s)
