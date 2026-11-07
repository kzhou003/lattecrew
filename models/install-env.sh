#!/usr/bin/env bash
# P0/P1 groundwork: isolated env for vLLM + vLLM-Omni, then model downloads.
set -uo pipefail
cd ~/latte-models
python3.12 -m venv env || exit 1
env/bin/pip install -q -U pip uv || exit 1
env/bin/uv pip install --python env/bin/python "vllm==0.32.0" "vllm-omni==0.32.0" "huggingface_hub[cli]" --torch-backend=cu130 ; echo "install_exit=$?"
env/bin/python - <<"P"
import torch, importlib.metadata as m
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
print("vllm", m.version("vllm"), "omni", m.version("vllm-omni"))
P
echo "env_exit=$?"
for r in cyankiwi/Qwen3.8-27B-AWQ-INT4 Tongyi-MAI/Z-Image-Turbo Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice Wan-AI/Wan2.2-TI2V-5B-Diffusers; do
  echo "== $r"; env/bin/hf download "$r" --quiet; echo "dl_exit[$r]=$?"
done
echo ALL_DONE
