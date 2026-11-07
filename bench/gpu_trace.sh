#!/usr/bin/env bash
# gpu_trace.sh <out.csv> <stopfile>: one row per second from nvidia-smi until stopfile disappears.
while [ -e "$2" ]; do
  echo "$(date +%s.%N | cut -c1-14),$(nvidia-smi --query-gpu=utilization.gpu,utilization.memory,memory.used,power.draw,clocks.sm,clocks.mem,temperature.gpu,pcie.link.gen.current --format=csv,noheader,nounits | tr -d ' ')" >> "$1"
  sleep 1
done
