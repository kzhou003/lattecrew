"""Tools for @qwen-chat: web search, safe page fetching, exact arithmetic, and Slack formatting.

Everything here is reachable by any member of the Slack workspace, so it is written defensively:
fetch_url only talks to public addresses (every redirect hop is re-checked and the connection is
pinned to the address that was checked), downloads are capped in size and time, and the
calculator evaluates a parsed expression tree, never Python code.
"""
import ast
import html
import http.client
import ipaddress
import json
import math
import operator
import os
import re
import socket
import ssl
import urllib.parse
import urllib.request
from html.parser import HTMLParser

SEARX = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8888")
FETCH_MAX_BYTES = 3 * 1024 * 1024
FETCH_MAX_CHARS = 12000
FETCH_TIMEOUT = 15
MAX_REDIRECTS = 4
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) qwen-chat/1.0 (+LatteCrew)"

TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web. Use for anything recent, factual details you are unsure of, prices, versions, "
                       "documentation or news. Returns titles, URLs and snippets; open a result with fetch_url when the "
                       "snippet is not enough.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search query. Use English for technical topics."}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_url",
        "description": "Open a public web page and return its main text (truncated). Use it to read a search result or "
                       "a link the user gave you.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "calculate",
        "description": "Evaluate an arithmetic expression exactly: + - * / // % **, parentheses, and math functions "
                       "such as sqrt, log, log2, log10, exp, sin, cos, tan, floor, ceil, round, abs, min, max; constants pi, e.",
        "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}},
]


# ------------------------------------------------------------------ search
def web_search(query, n=6):
    q = urllib.parse.urlencode({"q": query, "format": "json", "safesearch": 1})
    with urllib.request.urlopen(f"{SEARX}/search?{q}", timeout=20) as r:
        data = json.loads(r.read())
    out = []
    for item in data.get("results", [])[:n]:
        snippet = " ".join((item.get("content") or "").split())[:300]
        out.append(f"- {item.get('title', '').strip()}\n  {item.get('url')}\n  {snippet}")
    return "\n".join(out) if out else "No results."


# ------------------------------------------------------------------ fetch
class Blocked(Exception):
    pass


def public_address(host, port):
    """Resolve host and return one public IP for it, or raise Blocked."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise Blocked(f"cannot resolve {host}") from None
    ips = [info[4][0] for info in infos]
    for ip in ips:
        addr = ipaddress.ip_address(ip.split("%")[0])
        if (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved
                or addr.is_unspecified or addr in ipaddress.ip_network("100.64.0.0/10")
                or (addr.version == 6 and addr.ipv4_mapped and not addr.ipv4_mapped.is_global)):
            raise Blocked(f"{host} resolves to a non-public address")
    return ips[0]


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, **kw):
        super().__init__(host, context=ssl.create_default_context(), **kw)
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head", "nav", "footer", "form", "iframe"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.title, self.in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_to_text(raw):
    p = _Text()
    p.feed(raw)
    text = "".join(p.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    body = "\n".join(line for line in lines if line)
    return " ".join(p.title.split()), body


def fetch_url(url):
    for _ in range(MAX_REDIRECTS + 1):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise Blocked("only public http(s) URLs can be opened")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        ip = public_address(parts.hostname, port)
        cls = _PinnedHTTPS if parts.scheme == "https" else _PinnedHTTP
        conn = cls(parts.hostname, ip, port=port, timeout=FETCH_TIMEOUT)
        path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
        try:
            conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,*/*;q=0.5",
                                               "Accept-Encoding": "identity"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308) and resp.getheader("Location"):
                url = urllib.parse.urljoin(url, resp.getheader("Location"))
                continue
            if resp.status >= 400:
                return f"HTTP {resp.status} for {url}"
            ctype = resp.getheader("Content-Type", "")
            raw = resp.read(FETCH_MAX_BYTES + 1)[:FETCH_MAX_BYTES]
        finally:
            conn.close()
        charset = (re.search(r"charset=([\w-]+)", ctype) or [None, "utf-8"])[1]
        text = raw.decode(charset, errors="replace")
        if "html" in ctype or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
            title, body = html_to_text(text)
        elif ctype.startswith(("text/", "application/json", "application/xml")):
            title, body = "", text
        else:
            return f"{url} is not a text page ({ctype or 'unknown type'})."
        body = body[:FETCH_MAX_CHARS] + ("\n[truncated]" if len(body) > FETCH_MAX_CHARS else "")
        return f"URL: {url}\nTitle: {title}\n\n{body}"
    raise Blocked("too many redirects")


# ------------------------------------------------------------------ calculator
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {name: getattr(math, name) for name in ("sqrt", "log", "log2", "log10", "exp", "sin", "cos", "tan", "asin",
                                                  "acos", "atan", "floor", "ceil", "factorial", "gcd", "hypot")}
_FUNCS.update(abs=abs, round=round, min=min, max=max)
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def calculate(expression):
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 1000 or abs(left) > 1e12):
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            args = [ev(a) for a in node.args]
            if node.func.id == "factorial" and args and args[0] > 1000:
                raise ValueError("factorial argument too large")
            return _FUNCS[node.func.id](*args)
        raise ValueError("unsupported expression")
    if len(expression) > 300:
        raise ValueError("expression too long")
    return repr(ev(ast.parse(expression.replace("^", "**"), mode="eval")))


# ------------------------------------------------------------------ dispatch
def run_tool(name, arguments):
    """Run one tool call. Returns text for the model; errors come back as text too."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        if name == "web_search":
            return web_search(str(args["query"])[:300])
        if name == "fetch_url":
            return fetch_url(str(args["url"]))
        if name == "calculate":
            return calculate(str(args["expression"]))
        return f"Unknown tool {name}."
    except Blocked as err:
        return f"Refused: {err}."
    except Exception as err:
        return f"Tool error: {type(err).__name__}: {str(err)[:200]}"


# ------------------------------------------------------------------ Slack formatting
_CODE = re.compile(r"```.*?```", re.S)


def to_mrkdwn(text):
    """Common Markdown to Slack mrkdwn; code blocks are left alone."""
    keep = []

    def stash(m):
        keep.append(m.group(0))
        return f"\x00{len(keep) - 1}\x00"

    text = _CODE.sub(stash, text)
    text = re.sub(r"`[^`\n]+`", stash, text)
    text = re.sub(r"^#{1,6}\s+(.+?)\s*#*\s*$", r"*\1*", text, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"(?<![\w*])__(.+?)__(?![\w*])", r"_\1_", text)
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    text = re.sub(r"!?\[([^\]]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", text)
    text = re.sub(r"^(\s*)[-*]\s+", r"\1• ", text, flags=re.M)
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], text)


def host_of(url):
    return urllib.parse.urlsplit(url).hostname or url
