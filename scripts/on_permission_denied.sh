#!/usr/bin/env bash
# Capture PermissionDenied events as operational signals.
# Input: JSON on stdin with tool_name, arguments, reason
# Output: '{}' (no retry -- signal only)

input=$(cat)

# Use Python for safe JSON serialization (prevents JSONL injection)
if [ -f ".paircoder/config.yaml" ]; then
    mkdir -p .paircoder/telemetry
    echo "$input" | python3 -c "
import json, sys, datetime
try:
    data = json.loads(sys.stdin.read())
except Exception:
    data = {}
tool = data.get('tool_name', 'unknown')
sig = {
    'signal_type': 'permission_denied',
    'severity': 'warning',
    'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
    'session_id': '',
    'payload': {'tool_name': tool},
    'source': 'automated',
}
print(json.dumps(sig))
" >> .paircoder/telemetry/signals.jsonl 2>/dev/null
fi

# Don't retry -- signal only
echo '{}'
exit 0
