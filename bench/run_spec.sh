#!/usr/bin/env bash
# MTP speculative decoding against the same baseline. Holds the GPU lock.
cd ~/latte-bench; exec 9>>~/latte-models/gpu.lock; flock 9
OUT=out/spec.jsonl; rm -f $OUT
curl -s -m 30 "http://127.0.0.1:8100/unload" > /dev/null; sleep 5
up(){ for i in $(seq 1 120); do curl -sf -m 2 http://127.0.0.1:8101/health > /dev/null && return 0; sleep 5; done; return 1; }
run(){ local label=$1; shift
  echo "== $label $(date +%T)" >> out/spec.log
  env "$@" setsid ~/latte-models/bin/serve-qwen.sh & local p=$!
  if up; then
    grep -E "KV cache|Maximum concurrency|speculative|Speculative" ~/latte-models/logs/qwen.log | tail -3 >> out/spec.log
    python3 kprobe2.py $label $OUT >> out/spec.log 2>&1
    [ "$label" = base ] && python3 - >> out/spec.log 2>&1 <<'P'
import json,urllib.request as u
rows=[json.loads(l) for l in open("out/capture3.jsonl")]
big=[r["body"] for r in rows if r["body"].get("tools")]
def tok(b):
    return json.loads(u.urlopen(u.Request("http://127.0.0.1:8101/tokenize",data=json.dumps({"model":"qwen3.8","messages":b["messages"],"tools":b["tools"]}).encode(),headers={"Content-Type":"application/json"})).read())["tokens"]
a,b=tok(big[0]),tok(big[-1]); i=next(i for i,(x,y) in enumerate(zip(a,b)) if x!=y)
print("REORDER_PREFIX", json.dumps({"tokens":len(a),"first_diff":i}))
P
  else echo "$label failed to start" >> out/spec.log; tail -30 ~/latte-models/logs/qwen.log >> out/spec.log; fi
  kill -- -$p 2>/dev/null; sleep 3; pkill -f "vllm serve"; sleep 10
}
run base FI_SAMPLER=0
run mtp1 FI_SAMPLER=0 'EXTRA=--speculative-config {"method":"qwen3_5_mtp","num_speculative_tokens":1}'
run mtp2 FI_SAMPLER=0 'EXTRA=--speculative-config {"method":"qwen3_5_mtp","num_speculative_tokens":2}'
run mtp3 FI_SAMPLER=0 'EXTRA=--speculative-config {"method":"qwen3_5_mtp","num_speculative_tokens":3}'
echo FINISHED > out/spec.done
