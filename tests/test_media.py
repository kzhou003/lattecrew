"""Media bot logic with a fake Slack client and a fake model gateway."""
import fcntl, json, os, sys, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="mediatest"))
os.environ.update(MEDIA_HOME=str(TMP), CREW_GPU_LOCK=str(TMP / "gpu.lock"), MEDIA_GPU_WAIT="1")
sys.path.insert(0, os.environ.get("CREW_DIR", str(Path(__file__).resolve().parent.parent / "media-bot")))
import base64
import re
import media_bot as m

SEEN = []
RUNNING = ["qwen3.8"]


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        if "multipart" in self.headers.get("Content-Type", ""):
            body = {k: v for k, v in re.findall(r'name="(\w+)"\r\n\r\n(.*?)\r\n', raw.decode(), re.S)}
        else:
            body = json.loads(raw)
        SEEN.append((self.path, body))
        data = json.dumps({"data": [{"b64_json": base64.b64encode(b"PNG").decode()}]}).encode() if "images" in self.path else b"WAV"
        if "chat/completions" in self.path:
            data = json.dumps({"choices": [{"message": {"content": "ANSWER " + body["messages"][-1]["content"]}}]}).encode()
        if "videos" in self.path:
            data = b"MP4"
        self.send_response(200); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if self.path == "/running":
            data = json.dumps({"running": [{"model": RUNNING[0], "state": "ready"}] if RUNNING[0] else []}).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(data)

    def log_message(self, *_):
        pass


server = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=server.serve_forever, daemon=True).start()
m.GATEWAY = f"http://127.0.0.1:{server.server_port}"


class Slack:
    def __init__(self):
        self.posts, self.files, self.reactions = [], [], []

    def chat_postMessage(self, **kw):
        self.posts.append(kw)

    def files_upload_v2(self, **kw):
        self.files.append(kw)

    def conversations_replies(self, **kw):
        return {"messages": self.thread}

    thread = []

    def reactions_add(self, **kw):
        self.reactions.append(kw["name"])


def event(text, user="OWNER", **kw):
    return {"type": "app_mention", "user": user, "text": text, "channel": "C1", "ts": str(time.time()), **kw}


class Tests(unittest.TestCase):
    def setUp(self):
        SEEN.clear()
        self.slack = Slack()
        self.image = m.MediaBot("image", self.slack, "OWNER")
        self.speech = m.MediaBot("speech", self.slack, "OWNER")

    def test_image_flow_uploads_into_the_thread(self):
        self.image.handle(event("<@U1> a cat size=1344x768 seed=7"))
        path, body = SEEN[0]
        self.assertEqual((path, body["model"], body["prompt"], body["size"], body["seed"]),
                         ("/v1/images/generations", "z-image", "a cat", "1344x768", 7))
        self.assertTrue(self.slack.files[0]["file"].endswith(".png"))
        self.assertIn("white_check_mark", self.slack.reactions)

    def test_speech_flow(self):
        self.speech.handle(event("你好 voice=ryan style=温柔"))
        body = SEEN[0][1]
        self.assertEqual((body["model"], body["input"], body["voice"], body["instructions"]), ("qwen-tts", "你好", "ryan", "温柔"))
        self.assertEqual(Path(self.slack.files[0]["file"]).read_bytes(), b"WAV")

    def test_video_goes_through_upstream_with_form_fields(self):
        bot = m.MediaBot("wan", self.slack, "OWNER")
        bot.handle(event("a cat seconds=3 size=704x1280 seed=9"))
        path, body = SEEN[0]
        self.assertEqual(path, "/upstream/wan2.2-ti2v/v1/videos/sync")
        self.assertEqual((body["prompt"], body["size"], body["num_frames"], body["seed"], body["fps"]),
                         ("a cat", "704x1280", "73", "9", "24"))
        self.assertTrue(self.slack.files[0]["file"].endswith(".mp4"))
        self.assertIn("开始生成视频", self.slack.posts[0]["text"])

    def test_video_rejects_sizes_it_does_not_support(self):
        bot = m.MediaBot("wan", self.slack, "OWNER")
        bot.handle(event("a cat size=832x480"))
        self.assertEqual(SEEN, [])

    def test_video_length_is_bounded(self):
        bot = m.MediaBot("wan", self.slack, "OWNER")
        for text in ("cat seconds=60", "cat seconds=0", "cat seconds=abc"):
            bot.handle(event(text))
        self.assertEqual(SEEN, [])
        self.assertEqual(len(self.slack.posts), 3)

    def test_strangers_and_bots_are_ignored(self):
        self.image.handle(event("a cat", user="SOMEONE"))
        self.image.handle(event("a cat", bot_id="B1"))
        self.image.handle(event("a cat", subtype="message_changed"))
        self.assertEqual((SEEN, self.slack.posts), ([], []))

    def test_channel_message_without_mention_is_ignored_but_dm_works(self):
        self.image.handle({**event("a cat"), "type": "message", "channel_type": "channel"})
        self.assertEqual(SEEN, [])
        self.image.handle({**event("a cat"), "type": "message", "channel_type": "im"})
        self.assertEqual(len(SEEN), 1)

    def test_mention_and_message_events_run_once(self):
        e = event("a cat", channel_type="im")
        self.image.handle(e)
        self.image.handle({**e, "type": "message"})
        self.assertEqual(len(SEEN), 1)

    def test_bad_options_get_a_reply_and_no_model_call(self):
        for text in ("cat size=9x9", "cat seed=abc", ""):
            self.image.handle(event(text))
        self.speech.handle(event("hi voice=nobody"))
        self.speech.handle(event("字" * (m.MAX_SPEECH_CHARS + 1)))
        self.assertEqual(SEEN, [])
        self.assertEqual(len(self.slack.posts), 5)

    def test_steps_are_clamped(self):
        self.image.handle(event("a cat steps=500"))
        self.assertEqual(SEEN[0][1]["num_inference_steps"], 12)

    def test_waits_for_gpu_and_gives_up_politely(self):
        with open(m.GPU_LOCK, "a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            self.image.handle(event("a cat"))
        self.assertEqual(SEEN, [])
        self.assertIn("排队", self.slack.posts[0]["text"])
        self.assertIn("放弃", self.slack.posts[1]["text"])

    def test_runs_after_gpu_is_released(self):
        held = open(m.GPU_LOCK, "a+")
        fcntl.flock(held, fcntl.LOCK_EX)
        threading.Timer(0.3, held.close).start()
        self.image.handle(event("a cat"))
        self.assertEqual(len(SEEN), 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)


class Sharing(unittest.TestCase):
    def setUp(self):
        SEEN.clear()
        self.slack = Slack()

    def test_listed_users_are_served_and_others_ignored(self):
        bot = m.MediaBot("image", self.slack, "OWNER", allowed={"FRIEND"})
        bot.handle(event("a cat", user="FRIEND"))
        bot.handle(event("a dog", user="STRANGER"))
        self.assertEqual([b["prompt"] for _, b in SEEN], ["a cat"])

    def test_star_means_this_workspace_only(self):
        bot = m.MediaBot("image", self.slack, "OWNER", allowed="*", team="T1")
        bot.handle(event("a cat", user="ANYONE", team="T1"))
        bot.handle(event("a dog", user="GUEST", user_team="T2"))
        self.assertEqual([b["prompt"] for _, b in SEEN], ["a cat"])

    def test_daily_quota_for_others_not_for_the_owner(self):
        bot = m.MediaBot("image", self.slack, "OWNER", allowed="*", team="T1", limits={"image": 2})
        for i in range(3):
            bot.handle(event(f"cat {i}", user="FRIEND", team="T1"))
        for i in range(3):
            bot.handle(event(f"owner {i}", user="OWNER"))
        self.assertEqual(len(SEEN), 5)
        self.assertTrue(any("额度用完" in p["text"] for p in self.slack.posts))

    def test_one_request_at_a_time_per_user(self):
        bot = m.MediaBot("image", self.slack, "OWNER", allowed="*", team="T1")
        self.assertIsNone(bot.claim("FRIEND"))
        self.assertIn("还在生成", bot.claim("FRIEND"))
        bot.release("FRIEND")
        self.assertIsNone(bot.claim("FRIEND"))

    def test_limits_parse(self):
        self.assertEqual(m.parse_limits("wan=1,image=5")["wan"], 1)
        self.assertEqual(m.parse_allowed(" * "), "*")
        self.assertEqual(m.parse_allowed("U1, U2"), {"U1", "U2"})


class Chat(unittest.TestCase):
    def setUp(self):
        SEEN.clear()
        RUNNING[0] = "qwen3.8"
        self.slack = Slack()
        self.bot = m.ChatBot(self.slack, "OWNER", allowed="*", team="T1", bot_user="UBOT")

    def test_answers_in_the_thread_with_a_system_prompt(self):
        self.bot.handle(event("<@UBOT> 什么是 KV cache？", user="FRIEND", team="T1"))
        path, body = SEEN[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "什么是 KV cache？"})
        self.assertFalse(body["chat_template_kwargs"]["enable_thinking"])
        self.assertTrue(self.slack.posts[-1]["text"].startswith("ANSWER"))

    def test_thread_history_alternates_roles(self):
        self.slack.thread = [{"user": "FRIEND", "text": "<@UBOT> hi"}, {"bot_id": "B1", "user": "UBOT", "text": "hello"},
                             {"user": "FRIEND", "text": "<@UBOT> and then? think=on"}]
        self.bot.handle(event("<@UBOT> and then? think=on", user="FRIEND", team="T1", thread_ts="1.0"))
        roles = [x["role"] for x in SEEN[0][1]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])
        self.assertEqual(SEEN[0][1]["messages"][-1]["content"], "and then?")
        self.assertTrue(SEEN[0][1]["chat_template_kwargs"]["enable_thinking"])

    def test_loads_qwen_under_the_gpu_lock_when_another_model_is_up(self):
        RUNNING[0] = "wan2.2-ti2v"
        self.bot.handle(event("hello", user="OWNER", channel_type="im", type="message"))
        self.assertTrue(any("加载" in p["text"] for p in self.slack.posts))
        self.assertEqual(SEEN[0][0], "/v1/chat/completions")

    def test_help_and_strangers(self):
        self.bot.handle(event("<@UBOT> help", user="FRIEND", team="T1"))
        self.bot.handle(event("<@UBOT> hi", user="X", user_team="T9"))
        self.assertEqual(SEEN, [])
        self.assertEqual(len(self.slack.posts), 1)

