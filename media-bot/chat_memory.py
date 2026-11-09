"""Long-term memory for @qwen-chat: Mem0 OSS on Qdrant, bge-m3 embeddings on the CPU, extraction by the local Qwen.

Rules, because every member of the workspace can talk to the bot:
- Memories belong to one Slack user. What is learned in a DM is only recalled in DMs; channel threads only see
  what was learned in channels, since a channel reply is visible to everyone there.
- Only the user's own words are sent for extraction, never the assistant's answer or web pages, so a page that
  says "remember that ..." cannot plant a memory.
- Secrets are redacted before anything is sent, and any memory that still looks like a secret is deleted.
- Extraction needs the LLM, which shares one GPU with image and video models. It runs in the background only
  while Qwen is already loaded, so remembering never evicts another model; searching needs no GPU at all.
- Users can list, delete and pause their memories, or add one directly (see COMMANDS).
"""
import json
import logging
import os
import queue
import re
import threading
import time
from pathlib import Path

log = logging.getLogger("media-bot.memory")
HOME = Path(os.environ.get("MEMORY_HOME", Path.home() / "latte-models" / "memory"))
QDRANT_HOST = os.environ.get("QDRANT_HOST", "127.0.0.1")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", 6333))
COLLECTION = os.environ.get("MEMORY_COLLECTION", "qwen_chat_memory")
EMBED_MODEL = os.environ.get("MEMORY_EMBED_MODEL", "BAAI/bge-m3")
LLM_URL = os.environ.get("MEMORY_LLM_URL", "http://127.0.0.1:8100/v1")
LLM_MODEL = os.environ.get("MEMORY_LLM_MODEL", "qwen3.8")
RECALL_TOP_K = 6
RECALL_THRESHOLD = 0.45      # Mem0's combined score; below this the probe returned unrelated memories
PENDING_MAX_AGE = 6 * 3600   # a turn not extracted within 6 hours (Qwen never loaded) is dropped
MIN_CHARS = 6
POLL_SECS = 20              # how often a queued turn checks whether Qwen is loaded

SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}|xox[abprs]-[A-Za-z0-9-]{10,}|xapp-[A-Za-z0-9-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_\w{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|hf_[A-Za-z0-9]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})")
LABELLED = re.compile(r"((?:password|passwd|passcode|pin|token|api[ _-]?key|secret|密码|口令|密钥|验证码)\s*(?:is|=|:|：|是|为)\s*)\S+",
                      re.I)
REDACTED = "[REDACTED]"

INSTRUCTIONS = """Only extract durable facts about the user that the USER stated or confirmed:
- who they chose to say they are (name, role, team, time zone, location at city level),
- stable preferences (answer language and style, tools, languages, formats),
- ongoing projects, goals and plans, and things they explicitly asked you to remember.
Do NOT extract:
- answers, recommendations or facts that came from the assistant or from web pages, or general knowledge,
- one-off questions or tasks ("translate this", "what is X"),
- credentials of any kind (passwords, API keys, tokens, account numbers) or anything marked [REDACTED],
- health, financial or other sensitive details unless the user explicitly asked you to remember them,
- private details about other people.
Write each memory as one short, self-contained sentence. If nothing qualifies, return an empty list."""

COMMANDS = ("记忆：`memory` 看我记住了你什么（只在私信里列出），`forget 2` 删第 2 条，`forget all` 全部删除，"
            "`memory off` / `memory on` 暂停或恢复记忆，`remember: 内容` 直接让我记住一句话。")
_LIST = re.compile(r"^(memory|memories|记忆|你记得我什么|你记住了什么)[?？]?$", re.I)
_FORGET = re.compile(r"^(?:forget|忘掉|忘记|删除记忆)\s*(all|全部|所有|\d+)$", re.I)
_TOGGLE = re.compile(r"^(?:memory|记忆)\s*(on|off|开|关)$", re.I)
_NOTE = re.compile(r"^(?:remember|记住)\s*[:：]\s*(.+)$", re.I | re.S)


def redact(text):
    return LABELLED.sub(lambda m: m.group(1) + REDACTED, SECRET.sub(REDACTED, text))


def looks_secret(text):
    return bool(SECRET.search(text) or LABELLED.search(text) or REDACTED in text)


def user_key(user):
    return f"slack-{user}"


def build_backend():
    """The real Mem0 instance. Imported lazily: loading bge-m3 takes seconds and needs packages tests do not have."""
    HOME.mkdir(parents=True, exist_ok=True)
    os.environ["MEM0_TELEMETRY"] = "False"          # Mem0 reports usage to PostHog unless this is off
    os.environ.setdefault("FASTEMBED_CACHE_PATH", str(HOME / "fastembed"))   # BM25 model; the default is /tmp
    from mem0 import Memory
    backend = Memory.from_config({
        "vector_store": {"provider": "qdrant", "config": {
            "host": QDRANT_HOST, "port": QDRANT_PORT, "collection_name": COLLECTION, "embedding_model_dims": 1024}},
        "llm": {"provider": "vllm", "config": {
            "model": LLM_MODEL, "vllm_base_url": LLM_URL, "temperature": 0.1, "max_tokens": 2000}},
        "embedder": {"provider": "huggingface", "config": {
            "model": EMBED_MODEL, "embedding_dims": 1024, "model_kwargs": {"device": "cpu"}}},
        "history_db_path": str(HOME / "history.db"),
        "custom_instructions": INSTRUCTIONS,
    })
    # Qwen3.8 thinks by default. Extraction is a JSON task, and thinking would triple its time.
    create = backend.llm.client.chat.completions.create

    def no_thinking(**kw):
        kw.setdefault("extra_body", {})["chat_template_kwargs"] = {"enable_thinking": False}
        return create(**kw)

    backend.llm.client.chat.completions.create = no_thinking
    return backend


class ChatMemory:
    def __init__(self, llm_ready, backend=None, home=HOME, enabled=True):
        """llm_ready() says whether Qwen is loaded; backend is a Mem0-like object (built in the background if None)."""
        self.llm_ready, self.home = llm_ready, Path(home)
        self.backend, self.enabled = backend, enabled
        self.ready = threading.Event()
        self.write_lock = threading.Lock()
        self.pending = queue.Queue()
        self.last_list = {}                      # user -> memory ids in the order last shown
        self.prefs_path = self.home / "prefs.json"
        try:
            self.paused = set(json.loads(self.prefs_path.read_text()).get("paused", []))
        except (OSError, ValueError):
            self.paused = set()
        if not enabled:
            return
        if backend is not None:
            self.ready.set()
        else:
            threading.Thread(target=self._build, name="memory-init", daemon=True).start()
        threading.Thread(target=self._worker, name="memory-writer", daemon=True).start()

    def _build(self):
        try:
            started = time.time()
            self.backend = build_backend()
            self.ready.set()
            log.info("memory ready in %.0f s", time.time() - started)
        except Exception:
            log.exception("memory disabled: Mem0, Qdrant or the embedding model is not available")

    @property
    def on(self):
        return self.enabled and self.ready.is_set()

    # ------------------------------------------------------------------ recall
    def recall(self, user, query, dm):
        """Relevant memories for this turn, oldest first, as 'YYYY-MM-DD fact' lines. Never raises."""
        if not self.on or user in self.paused or not query.strip():
            return []
        filters = {"user_id": user_key(user)}
        if not dm:
            filters["visibility"] = "channel"
        try:
            found = self.backend.search(query[:2000], filters=filters, top_k=RECALL_TOP_K,
                                        threshold=RECALL_THRESHOLD).get("results", [])
        except Exception:
            log.warning("memory search failed", exc_info=True)
            return []
        found.sort(key=lambda r: r.get("created_at") or "")
        return [f"{(r.get('created_at') or '')[:10]} {r['memory']}".strip() for r in found if r.get("memory")]

    # ------------------------------------------------------------------ learn
    def learn(self, user, text, dm):
        """Queue one user message for extraction after the reply has been sent."""
        if not self.on or user in self.paused or len(text.strip()) < MIN_CHARS or self.command(text):
            return
        self.pending.put((time.time(), user, redact(text)[:4000], dm))

    def _worker(self):
        while True:
            queued, user, text, dm = self.pending.get()
            while not (self.ready.is_set() and self.llm_ready()):
                if time.time() - queued > PENDING_MAX_AGE:
                    break
                time.sleep(POLL_SECS)
            else:
                self._extract(user, text, dm)
            self.pending.task_done()

    def _extract(self, user, text, dm):
        meta = {"visibility": "dm" if dm else "channel", "source": "slack"}
        try:
            with self.write_lock:
                result = self.backend.add([{"role": "user", "content": text}], user_id=user_key(user), metadata=meta)
            for item in result.get("results", []):
                if looks_secret(item.get("memory", "")):
                    self.backend.delete(item["id"])
                    log.warning("dropped a memory that looked like a secret")
        except Exception:
            log.warning("memory extraction failed", exc_info=True)

    # ------------------------------------------------------------------ user commands
    @staticmethod
    def command(text):
        text = text.strip()
        return bool(_LIST.match(text) or _FORGET.match(text) or _TOGGLE.match(text) or _NOTE.match(text))

    def handle_command(self, user, text, dm):
        """Reply text for a memory command, or None if this is not one."""
        text = text.strip()
        if not self.command(text):
            return None
        if not self.enabled:
            return "这个 bot 没有开启长期记忆。"
        if not self.ready.is_set():
            return "记忆模块还在启动（加载 embedding 模型），过一分钟再试。"
        key = user_key(user)
        if (m := _TOGGLE.match(text)):
            if m.group(1).lower() in ("off", "关"):
                self.paused.add(user)
                reply = "已暂停：我不再记新的事，也不会用已有的记忆。`memory on` 恢复，`forget all` 删除已有的。"
            else:
                self.paused.discard(user)
                reply = "已恢复记忆。"
            self._save_prefs()
            return reply
        if (m := _NOTE.match(text)):
            note = m.group(1).strip()
            if looks_secret(redact(note)):
                return "这看起来像密码或密钥，我不会记。"
            if user in self.paused:
                return "你暂停了记忆，先发 `memory on`。"
            with self.write_lock:
                self.backend.add([{"role": "user", "content": note[:1000]}], user_id=key, infer=False,
                                 metadata={"visibility": "dm" if dm else "channel", "source": "explicit"})
            return "记住了。"
        items = self._all(key)
        if (m := _FORGET.match(text)):
            arg = m.group(1).lower()
            if arg in ("all", "全部", "所有"):
                self.backend.delete_all(user_id=key)
                self.last_list.pop(user, None)
                return f"已删除你的全部记忆（{len(items)} 条）。"
            shown = self.last_list.get(user) or [i["id"] for i in items]
            n = int(arg)
            if not 1 <= n <= len(shown):
                return "没有这一条。先发 `memory` 看编号。"
            self.backend.delete(shown[n - 1])
            self.last_list[user] = shown[:n - 1] + shown[n:]
            return f"已删除第 {n} 条。"
        if not dm:
            return "记忆列表只在私信里显示。私信我 `memory` 就能看到。"
        if not items:
            return "我还没有记住关于你的任何事。" + ("（你暂停了记忆）" if user in self.paused else "")
        self.last_list[user] = [i["id"] for i in items]
        lines = [f"{n}. {i['memory']}  _({(i.get('created_at') or '')[:10]}"
                 f"{'，频道' if (i.get('metadata') or {}).get('visibility') == 'channel' else '，私信'})_"
                 for n, i in enumerate(items, 1)]
        return "我记住了这些：\n" + "\n".join(lines) + "\n\n`forget 2` 删一条，`forget all` 全删，`memory off` 暂停。"

    def _all(self, key):
        items = self.backend.get_all(filters={"user_id": key}, top_k=200).get("results", [])
        return sorted(items, key=lambda r: r.get("created_at") or "")

    def _save_prefs(self):
        try:
            self.home.mkdir(parents=True, exist_ok=True)
            self.prefs_path.write_text(json.dumps({"paused": sorted(self.paused)}))
        except OSError:
            log.warning("could not save memory preferences", exc_info=True)
