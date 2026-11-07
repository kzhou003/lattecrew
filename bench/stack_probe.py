#!/usr/bin/env python3
"""Upper-stack overhead from the Mac: ssh, MCP, harness startup. Writes JSON lines."""
import json, os, statistics as st, subprocess, sys, time
OUT = sys.argv[1]
def rec(**k):
    with open(OUT, "a") as f: f.write(json.dumps(k, ensure_ascii=False) + "\n")
    print({a: (round(b, 1) if isinstance(b, float) else b) for a, b in k.items() if a != "samples"}, flush=True)
def timeit(name, fn, n):
    s = []
    for _ in range(n):
        t = time.perf_counter(); fn(); s.append((time.perf_counter() - t) * 1e3)
    rec(probe=name, n=n, p50=st.median(s), p95=sorted(s)[max(int(n * .95) - 1, 0)], min=min(s), samples=s)
SSH = ["/usr/bin/ssh", "-o", "BatchMode=yes", "latte"]
timeit("ssh_new_conn_true", lambda: subprocess.run(SSH + ["true"], capture_output=True), 15)
CTL = "/tmp/lc-probe.sock"
subprocess.run(["/usr/bin/ssh", "-o", "BatchMode=yes", "-o", f"ControlPath={CTL}", "-o", "ControlMaster=yes", "-o", "ControlPersist=120", "-fN", "latte"])
time.sleep(1)
MUX = ["/usr/bin/ssh", "-o", "BatchMode=yes", "-o", f"ControlPath={CTL}", "latte"]
timeit("ssh_mux_true", lambda: subprocess.run(MUX + ["true"], capture_output=True), 15)
INIT = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
CALL = '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"crew_repos","arguments":{}}}\n'
CMD = "/usr/bin/python3 ~/latte-crew/crew.py mcp"
timeit("mcp_new_session_call", lambda: subprocess.run(SSH + [CMD], input=(INIT + CALL).encode(), capture_output=True), 10)
timeit("mcp_mux_session_call", lambda: subprocess.run(MUX + [CMD], input=(INIT + CALL).encode(), capture_output=True), 10)
# one long-lived session, as a bot holds it
p = subprocess.Popen(SSH + [CMD], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
p.stdin.write(INIT); p.stdin.flush(); p.stdout.readline()
def live():
    p.stdin.write(CALL); p.stdin.flush(); p.stdout.readline()
timeit("mcp_live_session_call", live, 30)
p.stdin.close(); p.wait()
timeit("scp_1MB", lambda: subprocess.run(["/usr/bin/scp", "-q", "-o", f"ControlPath={CTL}", "latte:/tmp/lc-1m", "/tmp/lc-1m"]), 8)
os.environ["PATH"] = os.path.expanduser("~/.local/bin:") + os.environ["PATH"]
def claude_once():
    t = time.perf_counter()
    r = subprocess.run(["claude", "-p", "--output-format", "json", "--model", "haiku", "--tools", "", "reply with exactly: ok"], capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd="/tmp")
    wall = (time.perf_counter() - t) * 1e3
    try:
        d = json.loads(r.stdout); rec(probe="claude_p_once", wall_ms=wall, api_ms=float(d.get("duration_api_ms") or 0), overhead_ms=wall - float(d.get("duration_api_ms") or 0), cost=d.get("total_cost_usd"), usage={k: (d.get("usage") or {}).get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")})
    except Exception as e:
        rec(probe="claude_p_once", wall_ms=wall, err=str(e)[:100], out=r.stdout[:100])
for _ in range(4): claude_once()
