#!/usr/bin/env bash
# Kernel-layer comparison for Qwen. Holds the GPU lock so no bot swaps a model in meanwhile.
cd ~/latte-bench; exec 9>>~/latte-models/gpu.lock; flock 9
OUT=out/kernel.jsonl; rm -f $OUT; mkdir -p out/prof
curl -s -m 30 "http://127.0.0.1:8100/unload" > /dev/null; sleep 8
C13=$HOME/latte-models/cuda13
up(){ for i in $(seq 1 120); do curl -sf -m 2 http://127.0.0.1:8101/health > /dev/null && return 0; sleep 5; done; return 1; }
run(){ # label, env..., -- extra
  local label=$1; shift
  echo "== $label $(date +%T)" >> out/kernel.log
  env "$@" setsid ~/latte-models/bin/serve-qwen.sh & local p=$!
  if up; then python3 kprobe.py $label $OUT >> out/kernel.log 2>&1; grep -E "attention backend|sampl" ~/latte-models/logs/qwen.log | tail -3 >> out/kernel.log; else echo "$label failed to start" >> out/kernel.log; tail -30 ~/latte-models/logs/qwen.log >> out/kernel.log; fi
  kill -- -$p 2>/dev/null; sleep 3; pkill -f "vllm serve" ; sleep 10
}
run base FI_SAMPLER=0
run fi-sampler FI_SAMPLER=1 CUDA_HOME=$C13 PATH=$C13/bin:$PATH
run fi-attn FI_SAMPLER=1 CUDA_HOME=$C13 PATH=$C13/bin:$PATH "EXTRA=--attention-backend FLASHINFER"
# torch profiler on the baseline: one 8K prefill, then a 64-token decode
echo "== profile $(date +%T)" >> out/kernel.log
env FI_SAMPLER=0 "EXTRA=--profiler-config {\"profiler\":\"torch\",\"torch_profiler_dir\":\"$HOME/latte-bench/out/prof\",\"torch_profiler_with_stack\":false,\"active_iterations\":400}" setsid ~/latte-models/bin/serve-qwen.sh & p=$!
if up; then python3 - >> out/kernel.log 2>&1 <<'P'
import json,urllib.request as u,uuid,time,os
B="http://127.0.0.1:8101"
def chat(p,n): u.urlopen(u.Request(B+"/v1/chat/completions",data=json.dumps({"model":"qwen3.8","messages":[{"role":"user","content":p}],"max_tokens":n,"ignore_eos":True,"chat_template_kwargs":{"enable_thinking":False}}).encode(),headers={"Content-Type":"application/json"})).read()
fill="".join(f"def f{i}(x):\n    return x * {i}\n" for i in range(1200))
chat("warm "+fill[:3000],8)
for name,(p,n) in {"prefill":("# "+uuid.uuid4().hex+fill,1),"decode":("hi "+uuid.uuid4().hex,64)}.items():
    u.urlopen(u.Request(B+"/start_profile",method="POST")).read(); chat(p,n); u.urlopen(u.Request(B+"/stop_profile",method="POST")).read()
    time.sleep(20); os.makedirs(f"out/prof/{name}",exist_ok=True)
    for f in os.listdir("out/prof"):
        if os.path.isfile(f"out/prof/{f}"): os.rename(f"out/prof/{f}",f"out/prof/{name}/{f}")
    print("profiled",name,os.listdir(f"out/prof/{name}"))
P
fi
kill -- -$p 2>/dev/null; sleep 3; pkill -f "vllm serve"; sleep 5
echo FINISHED > out/kernel.done
