# harness guardrails の穴探し

対象: `plugins/guardrails/scripts/irreversible_ops.py` と `protected_paths.py`（入口は `guard.sh`、契約は `_common.py`）。
これは Claude Code の PreToolUse フックで、Bash / Edit / Write の tool_input を JSON で受け取る。
不可逆操作か保護パスへの書き込みを見つけると、`permissionDecision: ask` を返す。

問い: **判定器が何も返さない（素通りする）のに、実際には不可逆操作や保護パスへの書き込みになるコマンド**を挙げよ。

- 1 件ごとに、コマンド・素通りする理由（コードの該当行）・実際の害を書く
- 次の既知の穴は除く: `python -c` などインタプリタの中身、実行時に決まる変数展開、`curl -o` / `wget -O` / `gpg --output` / `rsync` / `tar -C`、4 段目より深い入れ子、オプションの無い `rm file`
- ファイルは変更しない。読むためのコマンドと、判定器に JSON を流して確かめることはしてよい（例: `printf '%s' '{"tool_input":{"command":"..."}}' | python3 plugins/guardrails/scripts/irreversible_ops.py`）
- 判定器に流して素通りを確かめたものには「確認済み」、確かめていないものには「未確認」と付ける
- 日本語で答える
