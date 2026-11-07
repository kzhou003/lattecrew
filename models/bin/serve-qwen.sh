#!/usr/bin/env bash
# Qwen3.8-27B 4-bit through vLLM. Local only. CTX overrides the context length.
cd ~/latte-models
exec >> logs/qwen.log 2>&1
# Claim what is actually free: a browser on the desktop can hold 2 GB, and a fixed 0.90 then refuses to start.
FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits); TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)
UTIL=${UTIL:-$(python3 -c "print(round(min(0.90, ($FREE - 700) / $TOTAL), 3))")}
echo "qwen start: free=${FREE}MiB util=${UTIL}"
export HF_HUB_OFFLINE=1 VLLM_LOGGING_LEVEL=INFO VLLM_USE_FLASHINFER_SAMPLER=${FI_SAMPLER:-0}
exec env/bin/vllm serve ${MODEL:-cyankiwi/Qwen3.8-27B-AWQ-INT4} \
  --served-model-name qwen3.8 --host 127.0.0.1 --port 8101 \
  --max-model-len "${CTX:-65536}" --gpu-memory-utilization "${UTIL:-0.90}" --max-num-seqs "${SEQS:-2}" \
  --tool-call-parser qwen3_coder --enable-auto-tool-choice --reasoning-parser qwen3 \
  --limit-mm-per-prompt "{\"image\":0,\"video\":0}" --enable-prefix-caching --enable-mfu-metrics --kv-cache-metrics ${EXTRA:-}
