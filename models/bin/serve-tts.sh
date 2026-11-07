#!/usr/bin/env bash
# Qwen3-TTS CustomVoice through vLLM-Omni. Local only.
cd ~/latte-models
exec >> logs/tts.log 2>&1
export HF_HUB_OFFLINE=1 VLLM_USE_FLASHINFER_SAMPLER=0
D=$(env/bin/python -c "import vllm_omni,os;print(os.path.dirname(vllm_omni.__file__))")
exec env/bin/vllm serve Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice --deploy-config "$D/deploy/qwen3_tts.yaml" --omni --host 127.0.0.1 --port 8103 --trust-remote-code --enforce-eager
