# harness guardrails の修正後レビュー

対象: `plugins/guardrails/scripts/` の `_shell.py`（共通のコマンド分解）、`irreversible_ops.py`、`protected_paths.py`（入口は `guard.sh`、契約は `_common.py`）。
これは Claude Code の PreToolUse フックで、Bash / Edit / Write の tool_input を JSON で受け取る。不可逆操作か保護パスへの書き込みを見つけると、`permissionDecision: ask` を返す。
フック入力には `cwd` も入る（例: `{"cwd":"/home/u/repo","tool_input":{"command":"..."}}`）。

最近、コマンドを単純コマンドに分けて判定するように直した。直した結果を二つの軸で調べてほしい。

## 問い 1: まだ残っている素通り

判定器が何も返さないのに、実際には不可逆操作や保護パスへの書き込みになるコマンドを挙げよ。

- `tests/guardrails-cases.jsonl` に入っているもの（expect=hit）は、すでに拾えている。同じ型の言い換えは挙げなくてよい
- 次の既知の穴は除く: `python -c` などインタプリタの中身、実行時に決まる変数展開、`curl -o` / `wget -O` / `gpg --output` / `rsync` / `tar -C`、4 段目より深い入れ子、オプションの無い `rm file`

## 問い 2: 誤検出

読むだけの日常操作（または明らかに無害な操作）なのに、確認（ask）が出てしまうコマンドを挙げよ。確認が多すぎると、人間は読まずに承認するようになる。

## 共通

- 1 件ごとに、コマンド・理由（コードの該当行）・実害（問い 2 では、なぜ無害か）を書く
- ファイルは変更しない。読むためのコマンドと、判定器に JSON を流して確かめることはしてよい（例: `printf '%s' '{"tool_input":{"command":"..."}}' | python3 plugins/guardrails/scripts/irreversible_ops.py`）
- 判定器に流して確かめたものには「確認済み」、確かめていないものには「未確認」と付ける
- 重要度の高い順に並べる。日本語で答える
