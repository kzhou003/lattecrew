#!/usr/bin/env python3
"""Slack bots for models that are not agents: @z-image, @qwen-tts and @wan.

No LLM is involved. A message from an allowed user becomes one model request, and
the file goes back to the thread. The owner is always allowed and unlimited; others
come from ALLOWED_USERS (a comma list of Slack user IDs, or `*` for every member of
this workspace) and get a daily quota per bot plus one request at a time. The GPU lock is shared with crewd, so a request
waits for a running Qwen job instead of evicting the model halfway through.

    media_bot.py serve                   run the configured bots
    media_bot.py image "a cat" --size 1344x768
    media_bot.py speech "你好" --voice vivian
    media_bot.py video wan "a cat walking" --seconds 3
"""
import argparse
import base64
import fcntl
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

log = logging.getLogger("media-bot")
GATEWAY = os.environ.get("MEDIA_GATEWAY", "http://127.0.0.1:8100")
HOME = Path(os.environ.get("MEDIA_HOME", Path.home() / "latte-models"))
GPU_LOCK = Path(os.environ.get("CREW_GPU_LOCK", HOME / "gpu.lock"))
OUTPUT = HOME / "outputs"
GPU_WAIT_SECS = int(os.environ.get("MEDIA_GPU_WAIT", 900))
SIZES = {"1024x1024", "1344x768", "768x1344", "1152x896", "896x1152", "1536x640", "640x1536"}
VOICES = {"aiden", "dylan", "eric", "ono_anna", "ryan", "serena", "sohee", "uncle_fu", "vivian"}
MAX_SPEECH_CHARS = 1500
MAX_VIDEO_SECONDS = 8
FPS = 24
VIDEO = {
    "wan": {"model": "wan2.2-ti2v", "sizes": {"1280x704", "704x1280"}, "size": "1280x704",
            "steps": 30, "guidance": 5.0, "eta": "3 到 4 分钟"},
}
MENTION = re.compile(r"<@[A-Z0-9]+>")
HELP = {
    "image": "发一句图片描述就行。可选：`size=1344x768`、`seed=42`、`steps=9`。中文长标题容易写错，适合配图，不适合文字设计。",
    "speech": "发一段文字就行。可选：`voice=vivian`（可选 " + "、".join(sorted(VOICES)) + "）、`style=用温柔的语气说`。",
}
for _kind, _spec in VIDEO.items():
    HELP[_kind] = (f"发一句视频描述就行。可选：`size={_spec['size']}`（可选 " + "、".join(sorted(_spec["sizes"])) +
                   f"）、`seconds=5`（1 到 {MAX_VIDEO_SECONDS} 秒）、`seed=42`。生成通常要 {_spec['eta']}。")


class Busy(Exception):
    pass


class GpuLease:
    """Holds the shared GPU lock, telling the caller once if it has to wait."""

    def __init__(self, on_wait=None, timeout=None):
        self.on_wait, self.timeout = on_wait, GPU_WAIT_SECS if timeout is None else timeout

    def __enter__(self):
        GPU_LOCK.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(GPU_LOCK, "a+")
        start, told = time.time(), False
        while True:
            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.time() - start > self.timeout:
                    self.handle.close()
                    raise Busy() from None
                if not told and self.on_wait:
                    told = True
                    self.on_wait()
                time.sleep(2)

    def __exit__(self, *_):
        self.handle.close()


def post(path, body, timeout=300):
    request = urllib.request.Request(GATEWAY + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def stamp(ext):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    return OUTPUT / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(2).hex()}.{ext}"


def generate_image(prompt, size="1024x1024", seed=None, steps=8):
    body = {"model": "z-image", "prompt": prompt, "size": size, "num_inference_steps": steps}
    if seed is not None:
        body["seed"] = seed
    data = json.loads(post("/v1/images/generations", body))["data"][0]["b64_json"]
    path = stamp("png")
    path.write_bytes(base64.b64decode(data))
    return path


def generate_speech(text, voice="vivian", style=None):
    body = {"model": "qwen-tts", "input": text, "voice": voice, "language": "Auto", "response_format": "wav"}
    if style:
        body["instructions"] = style
    path = stamp("wav")
    path.write_bytes(post("/v1/audio/speech", body))
    return path


def generate_video(kind, prompt, size=None, seconds=5, seed=None):
    """Video goes through /upstream: llama-swap has no /v1/videos route, and this one passes multipart untouched."""
    spec = VIDEO[kind]
    fields = {"prompt": prompt, "size": size or spec["size"], "num_frames": seconds * FPS + 1, "fps": FPS,
              "num_inference_steps": spec["steps"], "guidance_scale": spec["guidance"]}
    if seed is not None:
        fields["seed"] = seed
    boundary = uuid.uuid4().hex
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                    for k, v in fields.items()) + f"--{boundary}--\r\n".encode()
    request = urllib.request.Request(f"{GATEWAY}/upstream/{spec['model']}/v1/videos/sync", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(request, timeout=1800) as response:
        data = response.read()
    path = stamp("mp4")
    path.write_bytes(data)
    return path


def parse_options(text):
    """Pull `key=value` options out of a message. Returns (remaining text, options)."""
    text = MENTION.sub("", text)
    options = {}

    def take(match):
        options[match.group(1).lower()] = match.group(2)
        return ""

    text = re.sub(r"(?:^|\s)(size|seed|steps|seconds|voice|style)=(\S+)", take, text, flags=re.I)
    return " ".join(text.split()), options


def build_request(kind, text):
    """Validate one message. Returns (generate function, kwargs) or raises ValueError with a reply."""
    prompt, options = parse_options(text)
    if not prompt or prompt.lower() in ("help", "帮助"):
        raise ValueError(HELP[kind])
    if kind == "image":
        size = options.get("size", "1024x1024")
        if size not in SIZES:
            raise ValueError("支持的尺寸：" + "、".join(sorted(SIZES)))
        try:
            seed = int(options["seed"]) if "seed" in options else None
            steps = min(max(int(options.get("steps", 8)), 4), 12)
        except ValueError:
            raise ValueError("seed 和 steps 要是整数") from None
        return generate_image, {"prompt": prompt, "size": size, "seed": seed, "steps": steps}
    if kind in VIDEO:
        spec = VIDEO[kind]
        size = options.get("size", spec["size"])
        if size not in spec["sizes"]:
            raise ValueError("支持的尺寸：" + "、".join(sorted(spec["sizes"])))
        try:
            seconds = int(options.get("seconds", 5))
            seed = int(options["seed"]) if "seed" in options else None
        except ValueError:
            raise ValueError("seconds 和 seed 要是整数") from None
        if not 1 <= seconds <= MAX_VIDEO_SECONDS:
            raise ValueError(f"时长要在 1 到 {MAX_VIDEO_SECONDS} 秒之间。")
        return generate_video, {"kind": kind, "prompt": prompt, "size": size, "seconds": seconds, "seed": seed}
    voice = options.get("voice", "vivian").lower()
    if voice not in VOICES:
        raise ValueError("可选声音：" + "、".join(sorted(VOICES)))
    if len(prompt) > MAX_SPEECH_CHARS:
        raise ValueError(f"文字太长了，一次最多 {MAX_SPEECH_CHARS} 字。")
    return generate_speech, {"text": prompt, "voice": voice, "style": options.get("style")}


DEFAULT_DAILY = {"image": 30, "speech": 30, "wan": 3}


def parse_allowed(value):
    """`*` -> "*" (every member of this workspace); otherwise a set of user IDs."""
    value = (value or "").strip()
    if value == "*":
        return "*"
    return {v.strip() for v in value.split(",") if v.strip()}


def parse_limits(value):
    limits = dict(DEFAULT_DAILY)
    for part in (value or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() and v.strip().isdigit():
                limits[k.strip()] = int(v)
    return limits


class MediaBot:
    def __init__(self, kind, client, owner, allowed=None, team=None, limits=None):
        self.kind, self.client, self.owner = kind, client, owner
        self.allowed = allowed if allowed == "*" else set(allowed or ())
        self.team = team            # this workspace; with `*`, events from other teams are ignored
        self.limit = (limits or DEFAULT_DAILY).get(kind, 0)
        self.seen, self.seen_lock = {}, threading.Lock()
        self.usage, self.busy = {}, set()   # (day, user) -> count; users with a request running

    def allowed_user(self, event):
        user = event.get("user")
        if user == self.owner:
            return True
        if self.allowed == "*":
            team = event.get("user_team") or event.get("team")
            return bool(user) and (self.team is None or team is None or team == self.team)
        return user in self.allowed

    def claim(self, user):
        """Count one request for a non-owner. Returns an error message or None."""
        if user == self.owner:
            return None
        day = time.strftime("%Y-%m-%d")
        with self.seen_lock:
            if user in self.busy:
                return "你上一个请求还在生成，等它完成再发下一个。"
            used = self.usage.get((day, user), 0)
            if used >= self.limit:
                return f"今天的额度用完了（每人每天 {self.limit} 次），明天再来。"
            self.usage[(day, user)] = used + 1
            self.busy.add(user)
        return None

    def release(self, user):
        with self.seen_lock:
            self.busy.discard(user)

    def duplicate(self, key):
        # Slack can deliver one message as both `message` and `app_mention`, and it retries.
        with self.seen_lock:
            now = time.time()
            self.seen = {k: t for k, t in self.seen.items() if now - t < 600}
            if key in self.seen:
                return True
            self.seen[key] = now
        return False

    def wanted(self, event):
        if event.get("bot_id") or event.get("subtype") or not self.allowed_user(event):
            return False
        return event.get("type") == "app_mention" or event.get("channel_type") == "im"

    def react(self, event, name):
        try:
            self.client.reactions_add(channel=event["channel"], timestamp=event["ts"], name=name)
        except Exception:
            log.debug("reaction failed", exc_info=True)

    def reply(self, event, text):
        self.client.chat_postMessage(channel=event["channel"], thread_ts=event.get("thread_ts") or event["ts"], text=text)

    def handle(self, event):
        if not self.wanted(event) or self.duplicate((event["channel"], event["ts"])):
            return
        try:
            func, kwargs = build_request(self.kind, event.get("text", ""))
        except ValueError as err:
            self.reply(event, str(err))
            return
        user = event.get("user")
        refusal = self.claim(user)
        if refusal:
            self.reply(event, refusal)
            return
        try:
            self.run(event, func, kwargs)
        finally:
            self.release(user)

    def run(self, event, func, kwargs):
        self.react(event, "hourglass_flowing_sand")
        if self.kind in VIDEO:
            self.reply(event, f"开始生成视频，通常要 {VIDEO[self.kind]['eta']}。")
        try:
            start = time.time()
            with GpuLease(on_wait=lambda: self.reply(event, "GPU 正在跑 Qwen 任务，我排队等它结束。")):
                path = func(**kwargs)
            self.client.files_upload_v2(channel=event["channel"], thread_ts=event.get("thread_ts") or event["ts"],
                                        file=str(path), filename=path.name,
                                        initial_comment=f"用时 {time.time() - start:.0f} 秒")
            self.react(event, "white_check_mark")
        except Busy:
            self.reply(event, f"GPU 忙了超过 {GPU_WAIT_SECS // 60} 分钟，这次先放弃。稍后再发一次。")
        except urllib.error.URLError as err:
            log.exception("model request failed")
            self.reply(event, f"模型请求失败：{err}")
        except Exception as err:
            log.exception("media request failed")
            self.reply(event, f"生成失败：{type(err).__name__}")


def load_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.strip().split("=", 1)
            values[key] = value.strip("\"'")
    return values


def serve(env_path):
    from slack_sdk import WebClient
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse

    env = load_env(env_path)
    owner, clients = env["OWNER_ID"], []
    allowed, limits = parse_allowed(env.get("ALLOWED_USERS")), parse_limits(env.get("DAILY_LIMITS"))
    for kind, prefix in (("image", "Z_IMAGE"), ("speech", "QWEN_TTS"), ("wan", "WAN")):
        if not env.get(f"{prefix}_BOT_TOKEN") or env[f"{prefix}_BOT_TOKEN"].endswith("..."):
            log.info("%s has no token yet, skipping", kind)
            continue
        web = WebClient(token=env[f"{prefix}_BOT_TOKEN"])
        try:
            team = web.auth_test().get("team_id")
        except Exception:
            team = None
        bot = MediaBot(kind, web, owner, allowed, team, limits)
        socket = SocketModeClient(app_token=env[f"{prefix}_APP_TOKEN"], web_client=web)

        def listener(client, request, bot=bot):
            if not isinstance(request, SocketModeRequest):
                return
            client.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))
            if request.type == "events_api":
                event = request.payload.get("event", {})
                threading.Thread(target=bot.handle, args=(event,), daemon=True).start()

        socket.socket_mode_request_listeners.append(listener)
        try:
            socket.connect()
        except Exception as err:
            # One revoked token must not take the other bots down with it.
            log.error("%s could not connect: %s", kind, str(err).splitlines()[-1][:160])
            continue
        clients.append(socket)
        log.info("%s connected", kind)
    if not clients:
        sys.exit("no bot could connect")
    threading.Event().wait()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve").add_argument("--env", default=str(Path.home() / ".config/latte-media/env"))
    image = sub.add_parser("image")
    image.add_argument("prompt")
    image.add_argument("--size", default="1024x1024")
    speech = sub.add_parser("speech")
    speech.add_argument("text")
    speech.add_argument("--voice", default="vivian")
    video = sub.add_parser("video")
    video.add_argument("kind", choices=sorted(VIDEO))
    video.add_argument("prompt")
    video.add_argument("--seconds", type=int, default=3)
    args = parser.parse_args()
    if args.cmd == "serve":
        serve(args.env)
    elif args.cmd == "image":
        with GpuLease():
            print(generate_image(args.prompt, args.size))
    elif args.cmd == "video":
        with GpuLease():
            print(generate_video(args.kind, args.prompt, seconds=args.seconds))
    else:
        with GpuLease():
            print(generate_speech(args.text, args.voice))


if __name__ == "__main__":
    sys.exit(main())
