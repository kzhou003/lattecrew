#!/usr/bin/python3
"""MCP stdio server for one media model on latte. Usage: latte-media-mcp image|speech|wan

The model runs on latte under the shared GPU lock. The finished file is copied to ~/Downloads/LatteCrew.
"""
import json
import os
import shlex
import subprocess
import sys

KIND = sys.argv[1]
SAVE = os.path.expanduser("~/Downloads/LatteCrew")
BOT = "~/latte-models/env/bin/python ~/latte-crew/media_bot.py"
TOOLS = {
    "image": ("generate_image", "Generate an image with Z-Image-Turbo on the local RTX 5090. Takes about a minute at most. Unreliable for Chinese text in images.",
              {"prompt": {"type": "string", "description": "What to draw, in detail."},
               "size": {"type": "string", "enum": ["1024x1024", "1344x768", "768x1344", "1152x896", "896x1152"]}}),
    "speech": ("generate_speech", "Turn text into speech with Qwen3-TTS on the local RTX 5090.",
               {"text": {"type": "string", "description": "The exact words to read."},
                "voice": {"type": "string", "enum": ["vivian", "serena", "uncle_fu", "dylan", "eric", "ryan", "aiden", "ono_anna", "sohee"]}}),
    "wan": ("generate_video", "Generate a video with Wan2.2 on the local RTX 5090. Takes 3 to 4 minutes for 5 seconds.",
            {"prompt": {"type": "string", "description": "The scene and its motion, in detail."},
             "seconds": {"type": "integer", "minimum": 1, "maximum": 8}}),
}


def remote(args):
    if KIND == "image":
        cmd = f"{BOT} image {shlex.quote(args['prompt'])} --size {shlex.quote(args.get('size') or '1024x1024')}"
    elif KIND == "speech":
        cmd = f"{BOT} speech {shlex.quote(args['text'])} --voice {shlex.quote(args.get('voice') or 'vivian')}"
    else:
        cmd = f"{BOT} video wan {shlex.quote(args['prompt'])} --seconds {int(args.get('seconds') or 5)}"
    done = subprocess.run(["/usr/bin/ssh", "-o", "BatchMode=yes", "latte", cmd], capture_output=True, text=True, timeout=2400)
    lines = [x for x in done.stdout.splitlines() if x.startswith("/")]
    if done.returncode or not lines:
        raise RuntimeError((done.stderr or done.stdout).strip().splitlines()[-1][:300] if (done.stderr or done.stdout).strip() else "generation failed")
    os.makedirs(SAVE, exist_ok=True)
    local = os.path.join(SAVE, os.path.basename(lines[-1]))
    subprocess.run(["/usr/bin/scp", "-q", "-o", "BatchMode=yes", f"latte:{lines[-1]}", local], check=True, timeout=300)
    return local


def respond(msg):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2024-11-05"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "latte-media", "version": "1.0.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        name, desc, props = TOOLS[KIND]
        result = {"tools": [{"name": name, "description": desc, "inputSchema": {"type": "object", "properties": props, "required": [next(iter(props))]}}]}
    elif method == "tools/call":
        try:
            path = remote(msg["params"].get("arguments") or {})
            result = {"content": [{"type": "text", "text": f"Saved to {path}"}]}
        except Exception as err:
            result = {"content": [{"type": "text", "text": f"error: {err}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown method"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


for line in sys.stdin:
    if line.strip():
        answer = respond(json.loads(line))
        if answer:
            print(json.dumps(answer, ensure_ascii=False), flush=True)
