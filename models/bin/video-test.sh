#!/usr/bin/env bash
# video-test.sh <model> <label> <WxH> <frames> <steps> <guidance> <fps> <prompt>
L=~/latte-models/logs; O=~/latte-models/outputs
touch $L/.watch; ~/latte-models/bin/watch-vram.sh $L/.watch > $L/$2.vram 2>/dev/null &
S=$(date +%s)
code=$(curl -s -m 1500 -o "$O/$2.mp4" -w "%{http_code} %{size_download}" http://127.0.0.1:8100/upstream/$1/v1/videos/sync \
  -F "prompt=$8" -F "size=$3" -F "num_frames=$4" -F "num_inference_steps=$5" -F "guidance_scale=$6" -F "fps=$7" -F "seed=7")
echo "$2 http/size=$code secs=$(( $(date +%s)-S ))"
rm -f $L/.watch; sleep 2
echo "peak_vram_mib/power: $(sort -n $L/$2.vram | tail -1) maxpower: $(sort -t, -k2 -n $L/$2.vram | tail -1 | cut -d, -f2)"
head -c 300 "$O/$2.mp4" | grep -a -c "error" | sed "s/^/error_marker=/"
