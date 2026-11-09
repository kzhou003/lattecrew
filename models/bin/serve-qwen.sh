#!/usr/bin/env bash
# Qwen3.8-27B 4-bit through vLLM. Local only.
# Defaults (measured in lattecrew_bench, E12): 128K context, FP8 KV cache, MTP speculative decoding with 3 draft tokens.
#   CTX=65536 KV_DTYPE=auto MTP=0   the previous setup (bf16 KV, no speculation)
#   UTIL, SEQS, MODEL, EXTRA, FI_SAMPLER as before
cd ~/latte-models
exec >> logs/qwen.log 2>&1
# Claim what is actually free: a browser on the desktop can hold 2 GB, and a fixed 0.90 then refuses to start.
FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits); TOTAL=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)
# Leave ~1.5 GB: MTP and CUDA graphs allocate at run time, and the desktop's VRAM use grows after start-up.
# At 0.90 a long tool-calling chat hit CUDA OOM (55 MiB free) and killed the engine.
UTIL=${UTIL:-$(python3 -c "print(round(min(0.85, ($FREE - 1500) / $TOTAL), 3))")}
CTX=${CTX:-131072}; KV_DTYPE=${KV_DTYPE:-fp8}; MTP=${MTP:-3}
echo "qwen start: free=${FREE}MiB util=${UTIL} ctx=${CTX} kv=${KV_DTYPE} mtp=${MTP}"
# The FP8 KV path JIT-compiles kernels once; it needs a CUDA compiler (user-space conda toolkit, see bench docs).
if [ -d "$HOME/latte-models/cuda13/bin" ]; then export CUDA_HOME=${CUDA_HOME:-$HOME/latte-models/cuda13}; export PATH="$CUDA_HOME/bin:$PATH"; fi
SPEC=()
[ "$MTP" -gt 0 ] && SPEC=(--speculative-config "{\"method\":\"qwen3_5_mtp\",\"num_speculative_tokens\":$MTP}")
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True HF_HUB_OFFLINE=1 VLLM_LOGGING_LEVEL=INFO VLLM_USE_FLASHINFER_SAMPLER=${FI_SAMPLER:-0}
exec env/bin/vllm serve ${MODEL:-cyankiwi/Qwen3.8-27B-AWQ-INT4} \
  --served-model-name qwen3.8 --host 127.0.0.1 --port 8101 \
  --max-model-len "$CTX" --gpu-memory-utilization "$UTIL" --max-num-seqs "${SEQS:-2}" \
  --kv-cache-dtype "$KV_DTYPE" "${SPEC[@]}" \
  --tool-call-parser qwen3_coder --enable-auto-tool-choice --reasoning-parser qwen3 \
  --limit-mm-per-prompt "{\"image\":0,\"video\":0}" --enable-prefix-caching --enable-mfu-metrics --kv-cache-metrics ${EXTRA:-}
