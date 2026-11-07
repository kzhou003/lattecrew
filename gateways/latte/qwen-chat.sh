#!/usr/bin/env bash
export KIROCREW_HOME=$HOME/.kiro/crew-qwen KIROCREW_PORT=5477 PATH=$(dirname "$(command -v node)"):$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
cd ~ ; S=$(date +%s)
timeout 160 kirocrew chat -m "$1" > /tmp/qc.log 2>&1 < /dev/null
echo "exit=$? secs=$(( $(date +%s)-S ))"
grep -v -E "WARNING|^\s*$" /tmp/qc.log | tail -8 | cut -c1-200
grep -c -E "WARNING.*(ToolGate|refus|Unroutable)" /tmp/qc.log
grep -E "ERROR|Error:|Traceback" /tmp/qc.log | tail -3 | cut -c1-220
