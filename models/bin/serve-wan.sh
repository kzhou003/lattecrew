#!/usr/bin/env bash
# Wan2.2 TI2V-5B through vLLM-Omni, with CPU offload. Local only.
cd ~/latte-models
exec >> logs/wan.log 2>&1
export HF_HUB_OFFLINE=1 VLLM_USE_FLASHINFER_SAMPLER=0
D=$(env/bin/python -c "import vllm_omni,os;print(os.path.dirname(vllm_omni.__file__))")
exec env/bin/vllm serve Wan-AI/Wan2.2-TI2V-5B-Diffusers --deploy-config "$D/deploy/wan2_2_ti2v.yaml" --omni --host 127.0.0.1 --port 8104 --enable-cpu-offload
