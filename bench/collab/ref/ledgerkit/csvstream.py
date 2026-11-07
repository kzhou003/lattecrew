class CsvStream:
    def __init__(self, delimiter=","):
        self.d = delimiter; self._reset()
    def _reset(self):
        self.row = []; self.f = []; self.st = "start"; self.seen = False; self.pending_cr = False
    def _end(self, out):
        if self.row or self.f or self.seen:
            self.row.append("".join(self.f)); out.append(self.row)
        self.row = []; self.f = []; self.st = "start"; self.seen = False
    def feed(self, chunk):
        out = []
        for ch in chunk:
            if self.pending_cr:
                self.pending_cr = False
                if ch == "\n": continue
            st = self.st
            if st == "inq":
                if ch == '"': self.st = "q2"
                else: self.f.append(ch)
                continue
            if st == "q2":
                if ch == '"': self.f.append('"'); self.st = "inq"; continue
                if ch not in (self.d, "\n", "\r"): raise ValueError("after quote")
                self.st = "field"
            if ch == self.d:
                self.row.append("".join(self.f)); self.f = []; self.st = "start"; self.seen = True
            elif ch in "\r\n":
                self._end(out)
                if ch == "\r": self.pending_cr = True
            elif ch == '"' and self.st == "start":
                self.st = "inq"; self.seen = True
            else:
                self.f.append(ch); self.st = "field"; self.seen = True
        return out
    def finish(self):
        if self.st == "inq": raise ValueError("open quote")
        out = []; self._end(out); self._reset(); return out
