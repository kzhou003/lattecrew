import threading, time
class TokenBucket:
    EPS = 1e-9
    def __init__(self, rate, capacity, clock=time.monotonic):
        if rate <= 0 or capacity <= 0: raise ValueError
        self.r, self.cap, self.c = rate, capacity, clock
        self.tok = float(capacity); self.last = clock(); self.l = threading.Lock()
    def _refill(self):
        now = self.c(); d = now - self.last; self.last = now
        if d > 0: self.tok = min(self.cap, self.tok + d * self.r)
    def _chk(self, n):
        if n <= 0 or n > self.cap: raise ValueError
    def try_acquire(self, n=1):
        self._chk(n)
        with self.l:
            self._refill()
            if self.tok + self.EPS * max(1, n) >= n:
                self.tok = max(0.0, self.tok - n); return True
            return False
    def wait_time(self, n=1):
        self._chk(n)
        with self.l:
            self._refill()
            return 0 if self.tok + self.EPS * max(1, n) >= n else (n - self.tok) / self.r
