#!/usr/bin/env bash
# Log GPU memory and power once a second until the file named in $1 is removed.
while [ -e "$1" ]; do nvidia-smi --query-gpu=memory.used,power.draw --format=csv,noheader,nounits; sleep 1; done
