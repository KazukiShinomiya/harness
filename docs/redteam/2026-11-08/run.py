"""cases.jsonl の各コマンドを guardrails の判定器に Bash の tool_input として流し、結果を表にする。"""
import json
import os
import subprocess
import sys

root = os.path.expanduser("~/repos/harness/plugins/guardrails/scripts")
cases_path = sys.argv[1]

for line in open(cases_path, encoding="utf-8"):
    case = json.loads(line)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": case["cmd"]}})
    proc = subprocess.run(
        [sys.executable, os.path.join(root, case["checker"])],
        input=payload, capture_output=True, text=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_PLUGIN_OPTION_")},
    )
    if proc.returncode != 0:
        verdict = "ERROR->ask"
    elif proc.stdout.strip():
        verdict = "HIT " + json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
    else:
        verdict = "PASS(素通り)"
    print(f'{case["id"]:4} {verdict:14} {case["cmd"]}   # {case["note"]}')
