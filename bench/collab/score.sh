#!/usr/bin/env bash
# Score every job in results.jsonl. Hidden tests exist on latte only for the length of this run.
cd "$(dirname "$0")"
JOBS=$(python3 -c "import json; print(' '.join(json.loads(l)['job'] for l in open('results.jsonl') if json.loads(l).get('job')))")
ssh -o BatchMode=yes latte 'rm -rf /tmp/hidden-tests; mkdir -p /tmp/hidden-tests'
scp -q hidden/*.py latte:/tmp/hidden-tests/; ls extra/*.py >/dev/null 2>&1 && scp -q extra/*.py latte:/tmp/hidden-tests/; scp -q score_remote.py latte:/tmp/score_remote.py
ssh -o BatchMode=yes latte "python3 /tmp/score_remote.py /tmp/hidden-tests $JOBS"
scp -q latte:/tmp/scored.json scored.json
ssh -o BatchMode=yes latte 'rm -rf /tmp/hidden-tests /tmp/score_remote.py /tmp/scored.json'
