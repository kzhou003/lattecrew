#!/usr/bin/env bash
# Stop any model server and wait until the GPU memory is released.
pkill -f "bin/vllm serve"
for i in $(seq 1 30); do
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits)
  [ "$used" -lt 3000 ] && { echo "freed_after=${i}s used=${used}MiB"; exit 0; }
  sleep 1
done
echo "still used=${used}MiB"; pkill -9 -f "bin/vllm serve"; exit 1
