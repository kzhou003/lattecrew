#!/usr/bin/env bash
# Z-Image-Turbo through vLLM-Omni. Local only.
cd ~/latte-models
exec >> logs/zimage.log 2>&1
export HF_HUB_OFFLINE=1 VLLM_USE_FLASHINFER_SAMPLER=0
exec env/bin/vllm serve Tongyi-MAI/Z-Image-Turbo --omni --host 127.0.0.1 --port 8102
