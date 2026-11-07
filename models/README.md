# Models

| File | Purpose |
|---|---|
| `install.sh` | venv + weights (`install-env.sh`), copies `bin/` to `~/latte-models/bin`, renders `llama-swap.yaml`, starts the service |
| `install-env.sh` | `~/latte-models/env` with vLLM 0.32 and vLLM-Omni 0.32 (CUDA 13 torch), then `hf download` of every model |
| `bin/serve-qwen.sh` | Qwen3.8-27B AWQ on :8101; sizes GPU memory from free VRAM; env `CTX`, `SEQS`, `UTIL`, `MODEL`, `EXTRA`, `FI_SAMPLER` |
| `bin/serve-zimage.sh` | Z-Image-Turbo on :8102 (vLLM-Omni) |
| `bin/serve-tts.sh` | Qwen3-TTS CustomVoice on :8103 |
| `bin/serve-wan.sh` | Wan2.2-TI2V-5B on :8104 with CPU offload |
| `bin/stop-gpu.sh` | stop any server and wait until VRAM is free |
| `bin/watch-vram.sh`, `bin/video-test.sh` | VRAM/power logger and a video smoke test |
| `llama-swap.yaml.template` | one model at a time on :8100; media models unload after 300 s idle |
| `systemd/llama-swap.service` | user unit |
| `opencode.latte.json` | OpenCode provider `latte/qwen3.8` → `127.0.0.1:8100` |

Calls:
```bash
curl 127.0.0.1:8100/v1/chat/completions -d '{"model":"qwen3.8","messages":[...]}'
curl 127.0.0.1:8100/v1/images/generations -d '{"model":"z-image","prompt":"...","size":"1024x1024"}'
curl 127.0.0.1:8100/v1/audio/speech -d '{"model":"qwen-tts","input":"...","voice":"vivian"}' -o out.wav
bin/video-test.sh wan2.2-ti2v t1 1280x704 49 30 5.0 24 "a cat walking on a windowsill"
```
All servers bind to 127.0.0.1. The Mac reaches them through an SSH tunnel (`gateways/mac/dev.lattecrew.models.plist`, 127.0.0.1:18100).
