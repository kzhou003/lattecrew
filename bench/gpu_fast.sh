#!/usr/bin/env bash
# gpu_fast.sh <out.csv> <stopfile>: GPU state at about 4 Hz via the nvidia-smi loop.
nvidia-smi --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,power.draw,clocks.sm,clocks.mem,pcie.link.gen.current --format=csv,noheader,nounits -lms 250 > "$1" &
P=$!
while [ -e "$2" ]; do sleep 1; done
kill $P
