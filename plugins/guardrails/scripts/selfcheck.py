"""SessionStart で guardrails の生存を確認する。

黙って死ぬガードレールは、何も無いより悪い。守られていると思わせて守っていないため。
この自己診断は「登録されているか」ではなく **実際に動くか** を毎回確かめ、
異常なら systemMessage でユーザーに、additionalContext で Claude に知らせる。

要件は実際の誤診からそのまま来ている:

  - どのパスの guard.sh が動くのか分からず、実行されないファイル（キャッシュ側）に
    診断ログを仕込んで「フックが発火しない」と 2 セッション誤診した。
    → 有効な CLAUDE_PLUGIN_ROOT を毎回明示する。
  - PreToolUse フックの permissionDecision "ask" が Claude Code 側で表示されず、
    ガードレールが素通しになっていた（deny は同一経路で機能する）。
    → decision が ask のときは、その旨と手動確認の手順を添える。

判定は fail-safe に倒す。この診断自体が失敗してもセッションは止めない（常に exit 0）。
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import decision  # noqa: E402

# 判定器へ食わせる合成ペイロード。実在しないパスを使い、副作用を持たせない。
PROBES = (
    (
        "irreversible_ops.py",
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /tmp/guardrails-selfcheck-absent"},
        },
    ),
    (
        "protected_paths.py",
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/guardrails-selfcheck-absent/.env",
                "content": "x",
            },
        },
    ),
)


def run_probe(root, checker, payload):
    """guard.sh を実際に起動し、判定器が決定を返すところまでを通しで確認する。

    戻り値は (ok, 詳細)。ok が False なら詳細をそのまま問題として報告する。
    """
    guard = os.path.join(root, "scripts", "guard.sh")
    try:
        proc = subprocess.run(
            ["sh", guard, checker],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return False, "%s: guard.sh が 10 秒で終わらない" % checker
    except OSError as exc:
        return False, "%s: guard.sh を起動できない (%s)" % (checker, exc)

    if proc.returncode != 0:
        return False, "%s: guard.sh が exit %d" % (checker, proc.returncode)

    out = proc.stdout.strip()
    if not out:
        return False, "%s: 危険な操作を検出できていない（出力が空）" % checker

    try:
        got = json.loads(out)
    except json.JSONDecodeError:
        return False, "%s: 出力が JSON でない (%.60s)" % (checker, out)

    specific = got.get("hookSpecificOutput", {})
    got_decision = specific.get("permissionDecision")
    if got_decision not in ("ask", "deny"):
        return False, "%s: permissionDecision が %r" % (checker, got_decision)

    return True, got_decision


def main():
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass  # 入力は使わない。読めなくても診断は続ける。

    problems = []
    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")

    if not root:
        problems.append("CLAUDE_PLUGIN_ROOT が未設定")
    elif not os.path.isdir(root):
        problems.append("CLAUDE_PLUGIN_ROOT が存在しない: %s" % root)
    else:
        guard = os.path.join(root, "scripts", "guard.sh")
        if not os.path.isfile(guard):
            problems.append("guard.sh が無い: %s" % guard)
        else:
            for checker, payload in PROBES:
                if not os.path.isfile(os.path.join(root, "scripts", checker)):
                    problems.append("判定器が無い: %s" % checker)
                    continue
                ok, detail = run_probe(root, checker, payload)
                if not ok:
                    problems.append(detail)

    emit(problems, root)


def emit(problems, root):
    where = root or "(不明)"
    current = decision()

    if problems:
        listed = "\n".join("  - " + p for p in problems)
        user_msg = (
            "guardrails が機能していない。不可逆操作は自動では止まらない。\n"
            "実行中のプラグイン: %s\n%s" % (where, listed)
        )
        agent_msg = (
            "guardrails の自己診断が失敗した。ガードレールは現在機能していないため、"
            "不可逆操作（commit/push/reset/rm 等）の前には必ず自分でユーザーに確認を取ること。\n"
            "実行中のプラグイン: %s\n%s" % (where, listed)
        )
    else:
        user_msg = None
        agent_msg = "guardrails: 有効（%s、decision=%s）" % (where, current)

    if current == "ask":
        caveat = (
            "注意: PreToolUse フックの permissionDecision \"ask\" は、"
            "Claude Code 側で確認ダイアログとして表示されない場合がある"
            "（v2.1.220 で default / acceptEdits の両方で実測。deny は同一経路で機能する）。"
            "ask が表示されるかは次で手動確認できる:\n"
            "  rm -f /tmp/guardrails-manual-check\n"
            "確認が出なければ、この環境で guardrails は検出しても素通しになる。"
        )
        agent_msg += "\n" + caveat
        if problems:
            user_msg += "\n" + caveat

    out = {"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": agent_msg,
    }}
    if user_msg:
        out["systemMessage"] = user_msg

    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
