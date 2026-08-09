"""SessionStart で guardrails の生存を確認する。

黙って死ぬガードレールは、何も無いより悪い。守られていると思わせて守っていないため。
この自己診断は「登録されているか」ではなく **実際に動くか** を毎回確かめ、
異常なら systemMessage でユーザーに、additionalContext で Claude に知らせる。

要件は実際の誤診からそのまま来ている:

  - どのパスの guard.sh が動くのか分からず、実行されないファイル（キャッシュ側）に
    診断ログを仕込んで「フックが発火しない」と 2 セッション誤診した。
    → 有効な CLAUDE_PLUGIN_ROOT を毎回明示する。
  - PreToolUse フックの permissionDecision "ask" が Claude Code 側で表示されず、
    ガードレールが素通しになっていた（v2.1.220。deny は同一経路で機能する）。
    v2.1.226 では同じ機でもセッションによって出たり出なかったりする。
    → decision が ask のときは、版で挙動が変わることと手動確認の手順を添える。
  - 診断対象がプラグイン層だけだったため、**permissions 層が一件も適用されて
    いない状態が何セッションも気付かれずに続いた**。SESSION_STATE には「適用済み」と
    書いてあり、記録の方が実態から外れていた。
    → 四層すべてを毎回実測する。手で書いた状態表は腐るが、実測は腐らない。

四層それぞれについて、次の三つを区別する。

    有効           そのまま報告する
    未適用         異常ではない。層を入れていない環境の方が多い。報告はするが警告しない
    導入済みで故障  **これだけが警告に値する**。守られているつもりで守られていない状態

判定は fail-safe に倒す。この診断自体が失敗してもセッションは止めない（常に exit 0）。
"""

import collections
import json
import os
import shutil
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

# name    報告に出す層の名前
# status  一行の状態。additionalContext に必ず載る
# problem 導入済みなのに機能していない場合の説明。None なら警告しない
Layer = collections.namedtuple("Layer", "name status problem")


# ---------------------------------------------------------------- プラグイン層


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


def check_plugin_layer(root):
    """プラグイン層。ここだけは「未適用」があり得ない——動いている以上、導入されている。"""
    problems = []

    if not root:
        return ["CLAUDE_PLUGIN_ROOT が未設定"]
    if not os.path.isdir(root):
        return ["CLAUDE_PLUGIN_ROOT が存在しない: %s" % root]

    guard = os.path.join(root, "scripts", "guard.sh")
    if not os.path.isfile(guard):
        return ["guard.sh が無い: %s" % guard]

    for checker, payload in PROBES:
        if not os.path.isfile(os.path.join(root, "scripts", checker)):
            problems.append("判定器が無い: %s" % checker)
            continue
        ok, detail = run_probe(root, checker, payload)
        if not ok:
            problems.append(detail)

    return problems


# ---------------------------------------------------------------- git 層


def git_config(key):
    """git config の値。未設定なら ""、git を起動できなければ None。"""
    try:
        proc = subprocess.run(
            ["git", "config", "--get", key],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else ""


def check_git_layer():
    """core.hooksPath が harness の githooks を指し、実行できる状態か。

    core.hooksPath が壊れたパスを指していても git は何も言わずに hook を一つも
    実行しない。この層の失敗は常に沈黙するので、こちらから見に行くしかない。
    """
    raw = git_config("core.hooksPath")

    if raw is None:
        return Layer("git 層", "判定不能（git を起動できない）", None)
    if not raw:
        return Layer("git 層", "未適用（core.hooksPath が未設定）", None)

    path = os.path.expanduser(raw)
    if not os.path.isdir(path):
        return Layer(
            "git 層",
            "**壊れている**（%s が無い）" % path,
            "git 層: core.hooksPath が存在しないディレクトリを指している: %s\n"
            "    git は hook を一つも実行しない。秘密情報のコミットも強制 push も止まらない" % path,
        )

    # harness の githooks かどうか。他人の実装なら口を出さない。
    if not os.path.isfile(os.path.join(path, "_lib.sh")):
        return Layer("git 層", "harness 以外の実装（%s）" % path, None)

    missing = [
        hook
        for hook in ("pre-commit", "pre-push")
        if not os.access(os.path.join(path, hook), os.X_OK)
    ]
    if missing:
        return Layer(
            "git 層",
            "**壊れている**（%s に実行権限が無い）" % "/".join(missing),
            "git 層: %s に実行権限が無い（%s）。git はこの hook を黙って飛ばす\n"
            "    chmod +x %s" % ("/".join(missing), path, " ".join(os.path.join(path, h) for h in missing)),
        )

    if git_config("guardrails.disable") == "true":
        # 事故ではなく明示的な意思表示。警告はしないが、黙りもしない。
        return Layer("git 層", "明示的に無効（guardrails.disable=true）", None)

    return Layer("git 層", "有効（%s）" % path, None)


# ---------------------------------------------------------------- permissions 層


def settings_files():
    """deny 規則が入り得る場所。読み取りのみ。"""
    home = os.path.expanduser("~")
    paths = [
        os.path.join(home, ".claude", "settings.json"),
        os.path.join(home, ".claude", "settings.local.json"),
    ]
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if project:
        paths += [
            os.path.join(project, ".claude", "settings.json"),
            os.path.join(project, ".claude", "settings.local.json"),
        ]
    return paths


def check_permissions_layer():
    """deny 規則が実際に入っているか。

    プラグインからは permissions を配れないため、この層だけは手で入れる必要がある。
    入れ忘れても何も起きない——ask が表示されない版（v2.1.220 等）では、この層の不在が
    そのまま「何も止まらない」に直結する。
    """
    total = 0
    unreadable = []

    for path in settings_files():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            unreadable.append("%s (%s)" % (path, exc))
            continue
        if not isinstance(data, dict):
            unreadable.append("%s (最上位が JSON オブジェクトでない)" % path)
            continue
        rules = data.get("permissions", {})
        rules = rules.get("deny", []) if isinstance(rules, dict) else []
        if isinstance(rules, list):
            total += len(rules)

    if unreadable:
        return Layer(
            "permissions 層",
            "**読めない設定ファイルがある**",
            "permissions 層: 設定ファイルを読めない。deny 規則は効いていない可能性がある:\n    "
            + "\n    ".join(unreadable),
        )

    if total == 0:
        return Layer("permissions 層", "未適用（deny 規則が 1 件も無い）", None)

    return Layer("permissions 層", "deny %d 件" % total, None)


# ---------------------------------------------------------------- OS/FS 層


def is_rm_guard(path):
    return bool(path) and os.path.basename(os.path.realpath(path)) == "rm-guard"


def check_osfs_layer():
    """PATH 上の rm が rm-guard に解決され、ゴミ箱へ送れる状態か。

    設置してあっても PATH の並びが違えば効かない。効かないことは何も起きないので
    気付けない——「~/.local/bin/rm はあるのに rm は /usr/bin/rm」を明示的に拾う。
    """
    installed = os.path.expanduser("~/.local/bin/rm")
    resolved = shutil.which("rm")

    if is_rm_guard(resolved):
        if shutil.which("trash-put"):
            return Layer("OS/FS 層", "有効（rm -> rm-guard）", None)
        return Layer(
            "OS/FS 層",
            "**壊れている**（trash-put が無い）",
            "OS/FS 層: rm-guard は効いているが trash-put が無い。この状態ではあらゆる rm が失敗する\n"
            "    sudo apt install trash-cli",
        )

    if os.path.lexists(installed) and is_rm_guard(installed):
        return Layer(
            "OS/FS 層",
            "**効いていない**（rm は %s）" % (resolved or "解決できない"),
            "OS/FS 層: %s に rm-guard を設置してあるが、PATH 上では %s が先に解決される。\n"
            "    設置してあるのに効いていない。~/.local/bin を PATH の前方へ置くこと"
            % (installed, resolved or "(rm が見つからない)"),
        )

    return Layer("OS/FS 層", "未適用（rm は %s）" % (resolved or "不明"), None)


# ---------------------------------------------------------------- 報告


def emit(plugin_problems, layers, root):
    where = root or "(不明)"
    current = decision()
    summary = "\n".join("  %s: %s" % (layer.name, layer.status) for layer in layers)
    layer_problems = [layer.problem for layer in layers if layer.problem]

    if plugin_problems:
        listed = "\n".join("  - " + problem for problem in plugin_problems)
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

    agent_msg += "\n" + summary

    # 未適用の層は警告しない（層を入れていない環境の方が多い）。
    # 導入済みなのに機能していない層だけがユーザーへの警告に値する。
    if layer_problems:
        listed = "\n".join("  - " + problem for problem in layer_problems)
        head = "guardrails: 導入済みの層が機能していない。守られているつもりで守られていない:\n"
        user_msg = head + listed if user_msg is None else user_msg + "\n\n" + head + listed
        agent_msg += "\n\n" + head + listed

    if current == "ask":
        caveat = (
            "注意: \"ask\" の確認ダイアログが表示されない環境がある"
            "（v2.1.220 の WSL2 機で実測。v2.1.226 のネイティブ Linux 機では表示される）。"
            "permissions の ask ルールはどちらでも表示されない。deny はどの環境でも効く。"
            "この環境で出るかは次で確かめられる"
            "（ファイルは存在しないので Yes と答えても副作用は無い）:\n"
            "  rm -f /tmp/guardrails-manual-check\n"
            "**単独で撃ち、人間が画面を見ること。** 複合コマンドにすると後半が allow に"
            "拾われて紛れる。また確認の不在はエージェントには観測できない——出て承認された"
            "場合と戻り値が同じになる。確認が出ないなら、この環境で guardrails は検出しても"
            "素通しになる。確実に止めたいものは decision=deny か git 層（githooks/）へ寄せること。"
        )
        agent_msg += "\n" + caveat
        if user_msg:
            user_msg += "\n" + caveat

    out = {"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": agent_msg,
    }}
    if user_msg:
        out["systemMessage"] = user_msg

    json.dump(out, sys.stdout)


def main():
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass  # 入力は使わない。読めなくても診断は続ける。

    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    plugin_problems = check_plugin_layer(root)

    # 他の三層は読み取りだけで判定する。どれが失敗しても診断全体は続ける。
    layers = []
    for check in (check_git_layer, check_permissions_layer, check_osfs_layer):
        try:
            layers.append(check())
        except Exception as exc:  # noqa: BLE001 -- 診断の失敗で起動を止めない
            layers.append(Layer(check.__name__, "判定不能（%s）" % exc, None))

    emit(plugin_problems, layers, root)


if __name__ == "__main__":
    main()
