#!/usr/bin/env python3
"""Media model timing through llama-swap. Holds the GPU lock like media-bot does."""
import base64, fcntl, json, os, subprocess, sys, time, urllib.request as u, uuid, wave, io
H = os.path.expanduser("~"); OUT = f"{H}/latte-bench/out/media.jsonl"
lock = open(f"{H}/latte-models/gpu.lock", "a+"); fcntl.flock(lock, fcntl.LOCK_EX)
B = "http://127.0.0.1:8100"
def rec(**k):
    open(OUT, "a").write(json.dumps(k, ensure_ascii=False) + "\n"); print(k, flush=True)
def post(p, b):
    t = time.time(); r = u.urlopen(u.Request(B + p, data=json.dumps(b).encode(), headers={"Content-Type": "application/json"}), timeout=900).read()
    return r, time.time() - t, t
P = "a lighthouse on a rocky coast at golden hour, film photo"
for steps in (4, 8, 12):
    for rep in range(4):
        r, d, t = post("/v1/images/generations", {"model": "z-image", "prompt": P, "size": "1024x1024", "seed": rep, "num_inference_steps": steps})
        rec(kind="zimage", steps=steps, rep=rep, secs=round(d, 2), start=t, size="1024x1024")
for size in ("512x512", "768x768", "1344x768"):
    for rep in range(3):
        r, d, t = post("/v1/images/generations", {"model": "z-image", "prompt": P, "size": size, "seed": rep, "num_inference_steps": 8})
        rec(kind="zimage", steps=8, rep=rep, secs=round(d, 2), start=t, size=size)
T = {"short": "今天的任务已经全部完成。", "mid": "今天的任务已经全部完成，感谢大家的努力。我们明天上午九点继续讨论下一阶段的计划，请提前准备好相关材料。", "long": "本地模型的好处是不用担心额度，但切换模型需要时间。我们测量了每一层的延迟，发现输入处理占了大部分时间，而不是生成本身。接下来我们会优化缓存和上下文长度，看看能带来多大的改善。这样的实验让系统的瓶颈变得清楚，也让优化有了明确的方向。"}
for name, text in T.items():
    for rep in range(4):
        r, d, t = post("/v1/audio/speech", {"model": "qwen-tts", "input": text, "language": "Chinese", "voice": "vivian", "response_format": "wav"})
        w = wave.open(io.BytesIO(r)); dur = w.getnframes() / w.getframerate()
        rec(kind="tts", text=name, chars=len(text), rep=rep, secs=round(d, 2), audio=round(dur, 2), rtf=round(d / dur, 3), start=t)
def video(frames, steps, rep, size="1280x704"):
    b = uuid.uuid4().hex; f = {"prompt": "a white cat walking on a windowsill, soft light", "size": size, "num_frames": frames, "fps": 24, "num_inference_steps": steps, "guidance_scale": 5.0, "seed": rep}
    body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in f.items()) + f"--{b}--\r\n".encode()
    t = time.time(); r = u.urlopen(u.Request(B + "/upstream/wan2.2-ti2v/v1/videos/sync", data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"}), timeout=1500).read()
    rec(kind="wan", frames=frames, steps=steps, rep=rep, size=size, secs=round(time.time() - t, 1), bytes=len(r), start=t, end=time.time())
for frames, steps in ((25, 30), (25, 30), (49, 30), (121, 30), (49, 15), (49, 50)):
    video(frames, steps, 0)
